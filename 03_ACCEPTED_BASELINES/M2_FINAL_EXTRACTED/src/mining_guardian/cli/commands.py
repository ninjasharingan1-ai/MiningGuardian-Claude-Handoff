import asyncio
import time
from datetime import datetime

import click
from sqlalchemy.orm import Session

from ..adapters import NVMLClient, SRBMinerClient
from ..agent.context import (
    ContextBuilder,
    NoTelemetrySessionError,
    WorkingMemoryBuilder,
    WorldStateBuilder,
)
from ..agent.gateway import FakeModelGateway
from ..agent.live import LiveWorldStateBuilder
from ..agent.shadow import ShadowMiningAgent, ShadowReasoningValidationError
from ..agent.temporal import FreshnessPolicy, GuardianSessionStatus
from ..collectors import HardwareCollector, MinerCollector
from ..config import get_database_url, get_settings
from ..core import AlgorithmRegistry, SessionManager
from ..enums import EventSeverity, EventType
from ..formatting import format_hashrate
from ..logging import setup_logging
from ..models import Event, MinerSnapshot
from ..storage import (
    AgentDecisionRepository,
    AgentEpisodeRepository,
    AgentLessonRepository,
    Database,
    EventRepository,
    HardwareSampleRepository,
    MinerSampleRepository,
    SessionRepository,
)


@click.group()
@click.option("--log-level", default="info", help="Logging level")
def cli(log_level: str) -> None:
    """Mining Guardian read-only telemetry and M2.1 shadow reasoning."""
    setup_logging(log_level)


def _resolve_snapshot_algorithms(snapshot: MinerSnapshot, database_url: str) -> None:
    database = Database(database_url)
    try:
        with database.get_session() as db_session:
            registry = AlgorithmRegistry(db_session)
            for workload in snapshot.workloads:
                record, _ = registry.resolve(
                    workload.raw_algorithm_name,
                    scope_type="miner",
                    scope_name=snapshot.miner,
                    discover=True,
                )
                if record is not None:
                    workload.canonical_algorithm_id = record.algorithm_id
                    workload.canonical_algorithm_name = record.canonical_name
    finally:
        database.close()


def _freshness_policy() -> FreshnessPolicy:
    settings = get_settings()
    return FreshnessPolicy(
        fresh_max_age_seconds=settings.freshness_fresh_max_age_seconds,
        recent_max_age_seconds=settings.freshness_recent_max_age_seconds,
    )


def _format_age(value: float | None) -> str:
    return f"{value:.0f} seconds" if value is not None else "unavailable"


@cli.command("probe-gpu")
def probe_gpu() -> None:
    """Read GPU information and telemetry without modifying hardware."""
    settings = get_settings()
    client = NVMLClient()
    try:
        if not client.initialized:
            raise click.ClickException("NVML is unavailable.")
        info = client.get_gpu_info(settings.gpu_index)
        if info is None:
            raise click.ClickException(f"GPU {settings.gpu_index} is unavailable.")
        click.echo(f"GPU: {info.name} (index {info.gpu_index})")
        click.echo(f"Temperature capability: {info.capabilities.can_read_temperature.value}")
        click.echo(f"Clock capability: {info.capabilities.can_read_clocks.value}")
        click.echo(f"Power capability: {info.capabilities.can_read_power.value}")
        click.echo(f"Utilization capability: {info.capabilities.can_read_utilization.value}")
        click.echo(f"Throttle capability: {info.capabilities.can_read_throttle_reasons.value}")
        sample = client.read_telemetry(settings.gpu_index)
        if sample:
            click.echo(f"Temperature: {sample.temperature_c if sample.temperature_c is not None else 'unavailable'}")
            click.echo(f"Power: {sample.power_w if sample.power_w is not None else 'unavailable'}")
    finally:
        client.close()


@cli.command("probe-miner")
def probe_miner() -> None:
    """Read SRBMiner telemetry without controlling the miner."""
    settings = get_settings()
    client = SRBMinerClient(
        host=settings.srbminer_api_host,
        port=settings.srbminer_api_port,
        timeout=settings.srbminer_api_timeout_seconds,
        api_path=settings.srbminer_api_path,
    )
    snapshot = asyncio.run(client.snapshot())
    if snapshot is None:
        raise click.ClickException("SRBMiner API unavailable or invalid.")

    _resolve_snapshot_algorithms(snapshot, get_database_url(settings))

    click.echo(f"Miner: {snapshot.miner}")
    click.echo(f"Version: {snapshot.miner_version or 'unavailable'}")
    uptime = f"{snapshot.uptime_seconds:g} seconds" if snapshot.uptime_seconds is not None else "unavailable"
    click.echo(f"Uptime: {uptime}")
    if not snapshot.workloads:
        click.echo("No parseable workloads reported.")
    for index, workload in enumerate(snapshot.workloads, start=1):
        click.echo(f"Workload {index}:")
        click.echo(f"  Raw Algorithm: {workload.raw_algorithm_name}")
        click.echo(f"  Algorithm: {workload.canonical_algorithm_name or 'unavailable'}")
        click.echo(f"  Hashrate: {format_hashrate(workload.hashrate_hs)}")
        click.echo(f"  Accepted: {workload.accepted_shares if workload.accepted_shares is not None else 'unavailable'}")
        click.echo(f"  Rejected: {workload.rejected_shares if workload.rejected_shares is not None else 'unavailable'}")


@cli.command()
@click.option("--duration", default=0.0, type=float, help="Seconds to observe; 0 means continuous.")
def observe(duration: float) -> None:
    """Collect and persist read-only telemetry."""
    settings = get_settings()
    nvml = NVMLClient()
    miner = SRBMinerClient(
        host=settings.srbminer_api_host,
        port=settings.srbminer_api_port,
        timeout=settings.srbminer_api_timeout_seconds,
        api_path=settings.srbminer_api_path,
    )
    manager = SessionManager()
    session_record = manager.create_session(
        miner="srbminer",
        gpu_ids=[settings.gpu_index],
        payout_coin=settings.payout_coin,
    )
    database = Database(get_database_url(settings))
    click.echo("OBSERVE MODE - READ ONLY. Ctrl+C stops monitoring.")

    try:
        with database.get_session() as db_session:
            registry = AlgorithmRegistry(db_session)
            session_repo = SessionRepository(db_session)
            miner_repo = MinerSampleRepository(db_session)
            hardware_repo = HardwareSampleRepository(db_session)
            event_repo = EventRepository(db_session)
            miner_collector = MinerCollector(miner, registry)
            hardware_collector = HardwareCollector(nvml, settings.gpu_index)

            session_repo.create(session_record)
            event_repo.create(Event(
                timestamp=datetime.now(),
                event_type=EventType.SESSION_STARTED,
                session_id=session_record.session_id,
                source="observer",
                message="Read-only observation session started",
            ))

            started = time.monotonic()
            while duration <= 0 or time.monotonic() - started < duration:
                try:
                    miner_samples = asyncio.run(miner_collector.collect(session_record.session_id))
                    algorithm_ids = [sample.canonical_algorithm_id for sample in miner_samples]
                    raw_names = [sample.raw_algorithm_name for sample in miner_samples]
                    if miner_samples:
                        manager.update_algorithms(algorithm_ids, raw_names)
                        session_repo.update_algorithms(session_record.session_id, algorithm_ids, raw_names)
                        for sample in miner_samples:
                            miner_repo.create(sample)
                    for raw_name, algorithm_id in miner_collector.last_discoveries:
                        event_repo.create(Event(
                            timestamp=datetime.now(),
                            event_type=EventType.ALGORITHM_DISCOVERED,
                            session_id=session_record.session_id,
                            severity=EventSeverity.WARNING,
                            source="algorithm_registry",
                            message=f"Discovered unknown algorithm: {raw_name}",
                            metadata={"raw_algorithm_name": raw_name, "algorithm_id": algorithm_id},
                        ))

                    hardware_sample = asyncio.run(hardware_collector.collect(
                        session_record.session_id,
                        miner="srbminer",
                        algorithm_ids=algorithm_ids,
                    ))
                    if hardware_sample is not None:
                        hardware_repo.create(hardware_sample)
                except Exception as exc:
                    event_repo.create(Event(
                        timestamp=datetime.now(),
                        event_type=EventType.MINER_API_ERROR,
                        session_id=session_record.session_id,
                        severity=EventSeverity.WARNING,
                        source="observer",
                        message=f"Telemetry cycle failed safely: {exc}",
                    ))
                if duration > 0 and time.monotonic() - started >= duration:
                    break
                time.sleep(settings.observe_interval_seconds)
    except KeyboardInterrupt:
        click.echo("Observation interrupted.")
    finally:
        manager.end_session()
        try:
            with database.get_session() as db_session:
                SessionRepository(db_session).update_end_time(session_record.session_id, datetime.now())
                EventRepository(db_session).create(Event(
                    timestamp=datetime.now(),
                    event_type=EventType.SESSION_ENDED,
                    session_id=session_record.session_id,
                    source="observer",
                    message="Read-only observation session ended",
                ))
        finally:
            nvml.close()
            database.close()


@cli.command()
def status() -> None:
    """Show latest persisted read-only status."""
    settings = get_settings()
    database = Database(get_database_url(settings))
    try:
        with database.get_session() as db_session:
            session_repo = SessionRepository(db_session)
            latest = session_repo.get_latest()
            if latest is None:
                click.echo("No sessions recorded.")
                return
            click.echo(f"Session: {latest.session_id}")
            click.echo(f"Miner: {latest.miner}")
            click.echo(f"Algorithms: {', '.join(latest.algorithm_ids) if latest.algorithm_ids else 'unknown'}")
            click.echo(f"Payout coin: {latest.payout_coin or 'not configured'}")
            samples = MinerSampleRepository(db_session).get_all_by_session(latest.session_id)
            if samples:
                latest_by_algorithm = {}
                for sample in samples:
                    latest_by_algorithm[sample.canonical_algorithm_id] = sample
                for sample in latest_by_algorithm.values():
                    click.echo(
                        f"{sample.canonical_algorithm_name} "
                        f"(raw: {sample.raw_algorithm_name}): {format_hashrate(sample.local_hashrate_hs)}"
                    )
            hardware = HardwareSampleRepository(db_session).get_latest_by_session(latest.session_id)
            if hardware:
                click.echo(f"GPU {hardware.gpu_id} temperature: {hardware.temperature_c if hardware.temperature_c is not None else 'unavailable'}")
    finally:
        database.close()



def _create_working_memory_builder(
    db_session: Session,
) -> tuple[WorkingMemoryBuilder, AgentDecisionRepository]:
    session_repo = SessionRepository(db_session)
    miner_repo = MinerSampleRepository(db_session)
    hardware_repo = HardwareSampleRepository(db_session)
    decision_repo = AgentDecisionRepository(db_session)
    lesson_repo = AgentLessonRepository(db_session)
    policy = _freshness_policy()
    world_builder = WorldStateBuilder(
        session_repo,
        miner_repo,
        hardware_repo,
        freshness_policy=policy,
    )
    context_builder = ContextBuilder(
        session_repo,
        miner_repo,
        hardware_repo,
        freshness_policy=policy,
    )
    working_memory_builder = WorkingMemoryBuilder(
        world_builder,
        context_builder,
        decision_repo,
        lesson_repo,
    )
    return working_memory_builder, decision_repo


@cli.command("agent-context")
@click.option("--session-id", default=None, help="Optional persisted session ID.")
@click.option(
    "--live",
    "live_probe",
    is_flag=True,
    help="Perform one ephemeral read-only SRBMiner/NVML probe.",
)
def agent_context(session_id: str | None, live_probe: bool) -> None:
    """Inspect temporally explicit M2.1.1 context without invoking a model."""

    settings = get_settings()
    database = Database(get_database_url(settings))
    nvml: NVMLClient | None = None
    try:
        with database.get_session() as db_session:
            working_memory_builder, _ = _create_working_memory_builder(db_session)
            historical_memory = None
            try:
                historical_memory = working_memory_builder.build(session_id)
            except NoTelemetrySessionError:
                if not live_probe:
                    raise click.ClickException("No persisted mining session is available.") from None

            if live_probe:
                miner = SRBMinerClient(
                    host=settings.srbminer_api_host,
                    port=settings.srbminer_api_port,
                    timeout=settings.srbminer_api_timeout_seconds,
                    api_path=settings.srbminer_api_path,
                )
                nvml = NVMLClient()
                registry = AlgorithmRegistry(db_session, seed_builtins=False)
                live_builder = LiveWorldStateBuilder(
                    miner,
                    nvml,
                    registry,
                    SessionRepository(db_session),
                    gpu_index=settings.gpu_index,
                    freshness_policy=_freshness_policy(),
                )
                world = asyncio.run(live_builder.build())
            else:
                if historical_memory is None:
                    raise click.ClickException("No persisted mining session is available.")
                world = historical_memory.world_state

            click.echo("AGENT CONTEXT - READ ONLY")
            click.echo(f"Observation origin: {world.observation_origin.value}")
            click.echo(f"Generated at: {world.generated_at.isoformat()}")
            click.echo(f"Freshness: {world.freshness.value}")
            click.echo(
                f"Latest miner sample age: {_format_age(world.miner_sample_age_seconds)} "
                f"({world.miner_freshness.value})"
            )
            click.echo(
                f"Latest hardware sample age: {_format_age(world.hardware_sample_age_seconds)} "
                f"({world.hardware_freshness.value})"
            )

            status = world.facts.guardian_session_status
            click.echo(f"Guardian session: {status.value}")
            if world.facts.session_id is not None:
                click.echo(f"Session: {world.facts.session_id}")
            if status is GuardianSessionStatus.ACTIVE:
                click.echo(f"Session age: {_format_age(world.derived.session_age_seconds)}")
            elif status is GuardianSessionStatus.ENDED:
                click.echo(
                    f"Session duration: {_format_age(world.derived.session_duration_seconds)}"
                )

            click.echo(f"Miner: {world.facts.miner or 'unavailable'}")
            click.echo(f"Miner version: {world.facts.miner_version or 'unavailable'}")
            click.echo(f"Miner reachability: {world.facts.miner_reachability.value}")

            if not world.facts.workloads:
                click.echo("Workloads: unavailable")
            for index, workload in enumerate(world.facts.workloads, start=1):
                algorithm_name = workload.canonical_algorithm_name or "unresolved"
                click.echo(
                    f"Workload {index}: {algorithm_name} "
                    f"(raw: {workload.raw_algorithm_name})"
                )
                click.echo(f"  Hashrate: {format_hashrate(workload.local_hashrate_hs)}")

            if not world.facts.gpus:
                click.echo("GPU telemetry: unavailable")
            for gpu in world.facts.gpus:
                temperature = (
                    f"{gpu.temperature_c:g} C"
                    if gpu.temperature_c is not None
                    else "unavailable"
                )
                power = f"{gpu.power_w:g} W" if gpu.power_w is not None else "unavailable"
                utilization = (
                    f"{gpu.utilization_gpu:g}%"
                    if gpu.utilization_gpu is not None
                    else "unavailable"
                )
                click.echo(
                    f"GPU {gpu.gpu_id}: temperature={temperature}, "
                    f"power={power}, utilization={utilization}"
                )

            if live_probe:
                click.echo("Historical context:")
                if historical_memory is None:
                    click.echo("  unavailable")
                else:
                    historical_world = historical_memory.world_state
                    click.echo(f"  source: {historical_world.observation_origin.value}")
                    click.echo(f"  freshness: {historical_world.freshness.value}")
                    click.echo(
                        "  Guardian session: "
                        f"{historical_world.facts.guardian_session_status.value}"
                    )
                    for window in historical_memory.context_windows:
                        click.echo(
                            f"  {window.label}: source={window.observation_origin.value}, "
                            f"freshness={window.freshness.value}, "
                            f"session={window.session_status.value}, "
                            f"miner_samples={window.miner_sample_count}, "
                            f"hardware_samples={window.hardware_sample_count}"
                        )
            elif historical_memory is not None:
                if historical_memory.context_windows:
                    click.echo("Context windows:")
                    for window in historical_memory.context_windows:
                        click.echo(
                            f"  {window.label}: source={window.observation_origin.value}, "
                            f"freshness={window.freshness.value}, "
                            f"session={window.session_status.value}, "
                            f"miner_samples={window.miner_sample_count}, "
                            f"hardware_samples={window.hardware_sample_count}"
                        )
                else:
                    click.echo("Context windows: insufficient data")

            known_signals: list[str] = []
            if world.facts.workloads:
                known_signals.append("workload_identity")
            if any(item.local_hashrate_hs is not None for item in world.facts.workloads):
                known_signals.append("local_hashrate")
            if world.facts.gpus:
                known_signals.append("gpu_identity")
            if any(item.temperature_c is not None for item in world.facts.gpus):
                known_signals.append("gpu_temperature")
            if any(item.power_w is not None for item in world.facts.gpus):
                known_signals.append("gpu_power")
            click.echo(
                f"Known signals: {', '.join(known_signals) if known_signals else 'none'}"
            )
            if world.missing_signals:
                click.echo(f"Missing signals: {', '.join(world.missing_signals)}")
            else:
                click.echo("Missing signals: none")
            if world.context_validity.warnings:
                click.echo(
                    "Freshness warnings: "
                    + " | ".join(world.context_validity.warnings)
                )
            if historical_memory is not None and historical_memory.recent_decisions:
                click.echo("Recent agent decisions:")
                for decision in historical_memory.recent_decisions:
                    click.echo(
                        f"  {decision.decision_id}: {decision.proposal_type.value}, "
                        f"confidence={decision.confidence:.2f}, "
                        f"execution={decision.execution_status.value}"
                    )
            else:
                click.echo("Recent agent decisions: none")
    finally:
        if nvml is not None:
            nvml.close()
        database.close()


@cli.command("agent-shadow-once")
@click.option("--session-id", default=None, help="Optional persisted session ID.")
def agent_shadow_once(session_id: str | None) -> None:
    """Run exactly one fake-gateway shadow reasoning cycle."""
    settings = get_settings()
    database = Database(get_database_url(settings))
    click.echo("SHADOW MODE")
    click.echo("NO ACTION WILL BE EXECUTED")
    try:
        with database.get_session() as db_session:
            working_memory_builder, decision_repo = _create_working_memory_builder(db_session)
            episode_repo = AgentEpisodeRepository(db_session)
            agent = ShadowMiningAgent(
                working_memory_builder,
                FakeModelGateway(),
                decision_repo,
                episode_repo,
            )
            try:
                result = agent.run_once(session_id)
            except (NoTelemetrySessionError, ShadowReasoningValidationError) as exc:
                raise click.ClickException(str(exc)) from exc

            decision = result.decision
            click.echo(f"Decision: {decision.decision_id}")
            click.echo(f"Proposal: {decision.proposal.proposal_type.value}")
            click.echo(f"Confidence: {decision.confidence:.2f}")
            click.echo(f"Execution: {decision.execution_status.value}")
    finally:
        database.close()

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
