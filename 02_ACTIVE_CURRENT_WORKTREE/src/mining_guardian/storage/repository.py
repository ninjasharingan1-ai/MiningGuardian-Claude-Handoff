import json
from datetime import datetime

from sqlalchemy.orm import Session

from ..enums import AlgorithmStatus, EventSeverity, EventType, SessionHealth, SessionState
from ..models import AlgorithmRecord, Event, HardwareSample, MinerSample, SessionRecord
from .schema import (
    AlgorithmAliasDB,
    AlgorithmDB,
    EventDB,
    HardwareSampleDB,
    MinerSampleDB,
    SessionDB,
)


class AlgorithmRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, algorithm_id: str) -> AlgorithmRecord | None:
        row = self.session.get(AlgorithmDB, algorithm_id)
        return self._to_model(row) if row else None

    def find_by_alias(self, normalized: str, scope_type: str, scope_name: str = "") -> AlgorithmRecord | None:
        alias = (
            self.session.query(AlgorithmAliasDB)
            .filter(
                AlgorithmAliasDB.alias_normalized == normalized,
                AlgorithmAliasDB.scope_type == scope_type,
                AlgorithmAliasDB.scope_name == scope_name,
            )
            .first()
        )
        return self.get(alias.algorithm_id) if alias else None

    def upsert(self, record: AlgorithmRecord) -> AlgorithmRecord:
        row = self.session.get(AlgorithmDB, record.algorithm_id)
        values = record.model_dump()
        values["status"] = record.status.value
        if row is None:
            row = AlgorithmDB(**values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self.session.commit()
        return record

    def add_alias(
        self,
        algorithm_id: str,
        raw_alias: str,
        normalized: str,
        scope_type: str = "alias",
        scope_name: str = "",
    ) -> None:
        existing = (
            self.session.query(AlgorithmAliasDB)
            .filter_by(scope_type=scope_type, scope_name=scope_name, alias_normalized=normalized)
            .first()
        )
        if existing is None:
            self.session.add(
                AlgorithmAliasDB(
                    algorithm_id=algorithm_id,
                    raw_alias=raw_alias,
                    alias_normalized=normalized,
                    scope_type=scope_type,
                    scope_name=scope_name,
                )
            )
            self.session.commit()

    def aliases_for(self, algorithm_id: str) -> list[tuple[str, str, str]]:
        rows = self.session.query(AlgorithmAliasDB).filter_by(algorithm_id=algorithm_id).all()
        return [(r.scope_type, r.scope_name, r.raw_alias) for r in rows]

    @staticmethod
    def _to_model(row: AlgorithmDB) -> AlgorithmRecord:
        return AlgorithmRecord(
            algorithm_id=row.algorithm_id,
            canonical_name=row.canonical_name,
            display_name=row.display_name,
            status=AlgorithmStatus(row.status),
            source=row.source,
            last_verified_at=row.last_verified_at,
            underlying_asset=row.underlying_asset,
            optimizer_eligible=bool(row.optimizer_eligible),
        )


class SessionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, record: SessionRecord) -> SessionRecord:
        self.session.add(
            SessionDB(
                session_id=record.session_id,
                miner=record.miner,
                gpu_ids_json=json.dumps(record.gpu_ids),
                algorithm_ids_json=json.dumps(record.algorithm_ids),
                raw_algorithm_names_json=json.dumps(record.raw_algorithm_names),
                payout_coin=record.payout_coin,
                start_time=record.start_time,
                end_time=record.end_time,
                state=record.state.value,
                health=record.health.value,
            )
        )
        self.session.commit()
        return record

    def update_algorithms(self, session_id: str, algorithm_ids: list[str], raw_names: list[str]) -> None:
        row = self.session.get(SessionDB, session_id)
        if row:
            row.algorithm_ids_json = json.dumps(list(dict.fromkeys(algorithm_ids)))
            row.raw_algorithm_names_json = json.dumps(list(dict.fromkeys(raw_names)))
            self.session.commit()

    def update_end_time(self, session_id: str, end_time: datetime) -> None:
        row = self.session.get(SessionDB, session_id)
        if row:
            row.end_time = end_time
            self.session.commit()

    def get_by_id(self, session_id: str) -> SessionRecord | None:
        row = self.session.get(SessionDB, session_id)
        return self._to_model(row) if row else None

    def get_latest(self) -> SessionRecord | None:
        row = self.session.query(SessionDB).order_by(SessionDB.start_time.desc()).first()
        return self._to_model(row) if row else None

    @staticmethod
    def _to_model(row: SessionDB) -> SessionRecord:
        return SessionRecord(
            session_id=row.session_id,
            miner=row.miner,
            gpu_ids=json.loads(row.gpu_ids_json or "[]"),
            algorithm_ids=json.loads(row.algorithm_ids_json or "[]"),
            raw_algorithm_names=json.loads(row.raw_algorithm_names_json or "[]"),
            payout_coin=row.payout_coin,
            start_time=row.start_time,
            end_time=row.end_time,
            state=SessionState(row.state),
            health=SessionHealth(row.health),
        )


class HardwareSampleRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, sample: HardwareSample) -> None:
        self.session.add(
            HardwareSampleDB(
                timestamp=sample.timestamp,
                session_id=sample.session_id,
                gpu_id=sample.gpu_id,
                miner=sample.miner,
                algorithm_ids_json=json.dumps(sample.algorithm_ids),
                temperature_c=sample.temperature_c,
                utilization_gpu=sample.utilization_gpu,
                utilization_memory=sample.utilization_memory,
                core_clock_mhz=sample.core_clock_mhz,
                memory_clock_mhz=sample.memory_clock_mhz,
                power_w=sample.power_w,
                power_limit_w=sample.power_limit_w,
                performance_state=sample.performance_state,
                throttle_reasons=sample.throttle_reasons,
                capability_states_json=json.dumps({k: v.value for k, v in sample.capability_states.items()}),
            )
        )
        self.session.commit()

    def get_latest_by_session(self, session_id: str) -> HardwareSample | None:
        row = (
            self.session.query(HardwareSampleDB)
            .filter_by(session_id=session_id)
            .order_by(HardwareSampleDB.timestamp.desc(), HardwareSampleDB.id.desc())
            .first()
        )
        return self._to_model(row) if row else None

    def get_all_by_session(self, session_id: str) -> list[HardwareSample]:
        rows = (
            self.session.query(HardwareSampleDB)
            .filter_by(session_id=session_id)
            .order_by(HardwareSampleDB.timestamp, HardwareSampleDB.id)
            .all()
        )
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: HardwareSampleDB) -> HardwareSample:
        from ..enums import CapabilityState

        return HardwareSample(
            timestamp=row.timestamp,
            session_id=row.session_id,
            gpu_id=row.gpu_id,
            miner=row.miner,
            algorithm_ids=json.loads(row.algorithm_ids_json or "[]"),
            temperature_c=row.temperature_c,
            utilization_gpu=row.utilization_gpu,
            utilization_memory=row.utilization_memory,
            core_clock_mhz=row.core_clock_mhz,
            memory_clock_mhz=row.memory_clock_mhz,
            power_w=row.power_w,
            power_limit_w=row.power_limit_w,
            performance_state=row.performance_state,
            throttle_reasons=row.throttle_reasons,
            capability_states={
                k: CapabilityState(v)
                for k, v in json.loads(row.capability_states_json or "{}").items()
            },
        )


class MinerSampleRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, sample: MinerSample) -> None:
        self.session.add(
            MinerSampleDB(
                timestamp=sample.timestamp,
                session_id=sample.session_id,
                miner=sample.miner,
                raw_algorithm_name=sample.raw_algorithm_name,
                canonical_algorithm_id=sample.canonical_algorithm_id,
                canonical_algorithm_name=sample.canonical_algorithm_name,
                local_hashrate_hs=sample.local_hashrate_hs,
                accepted_shares=sample.accepted_shares,
                rejected_shares=sample.rejected_shares,
                invalid_shares=sample.invalid_shares,
                miner_uptime_seconds=sample.miner_uptime_seconds,
                gpu_errors=sample.gpu_errors,
                device_ids_json=json.dumps(sample.device_ids),
                raw_data_json=json.dumps(sample.raw_data, default=str),
            )
        )
        self.session.commit()

    def get_latest_by_session(self, session_id: str) -> MinerSample | None:
        row = (
            self.session.query(MinerSampleDB)
            .filter_by(session_id=session_id)
            .order_by(MinerSampleDB.timestamp.desc(), MinerSampleDB.id.desc())
            .first()
        )
        return self._to_model(row) if row else None

    def get_all_by_session(self, session_id: str) -> list[MinerSample]:
        rows = self.session.query(MinerSampleDB).filter_by(session_id=session_id).order_by(MinerSampleDB.id).all()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: MinerSampleDB) -> MinerSample:
        return MinerSample(
            timestamp=row.timestamp,
            session_id=row.session_id,
            miner=row.miner,
            raw_algorithm_name=row.raw_algorithm_name,
            canonical_algorithm_id=row.canonical_algorithm_id,
            canonical_algorithm_name=row.canonical_algorithm_name,
            local_hashrate_hs=row.local_hashrate_hs,
            accepted_shares=row.accepted_shares,
            rejected_shares=row.rejected_shares,
            invalid_shares=row.invalid_shares,
            miner_uptime_seconds=row.miner_uptime_seconds,
            gpu_errors=row.gpu_errors,
            device_ids=json.loads(row.device_ids_json or "[]"),
            raw_data=json.loads(row.raw_data_json or "{}"),
        )


class EventRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, event: Event) -> None:
        self.session.add(
            EventDB(
                timestamp=event.timestamp,
                event_type=event.event_type.value,
                session_id=event.session_id,
                severity=event.severity.value,
                source=event.source,
                message=event.message,
                event_metadata=json.dumps(event.metadata, default=str) if event.metadata is not None else None,
            )
        )
        self.session.commit()

    def get_recent(self, session_id: str | None = None, limit: int = 100) -> list[Event]:
        query = self.session.query(EventDB)
        if session_id is not None:
            query = query.filter_by(session_id=session_id)
        rows = query.order_by(EventDB.timestamp.desc()).limit(limit).all()
        return [
            Event(
                timestamp=row.timestamp,
                event_type=EventType(row.event_type),
                session_id=row.session_id,
                severity=EventSeverity(row.severity),
                source=row.source,
                message=row.message,
                metadata=json.loads(row.event_metadata) if row.event_metadata else None,
            )
            for row in rows
        ]
