"""M3.2-S2 bounded read-only evidence-query integration tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text

from mining_guardian.observability.models import Quality, Source
from mining_guardian.state.contracts import TimeBasis
from mining_guardian.state.evidence_query import (
    AssociationMode,
    BoundedEvidenceQuery,
    EvidenceQueryChangedError,
    EvidenceQueryConfiguration,
    EvidenceQueryContinuation,
    EvidenceQueryError,
    EvidenceQueryIntegrityError,
    EvidenceQueryLimitError,
    EvidenceQueryRequest,
    QueryCompleteness,
    QueryIntegrity,
    QueryLimitKind,
    SubjectSelector,
)
from mining_guardian.storage.runtime_repository import (
    RuntimeEvidenceRepository,
    install_runtime_schema,
)
from tests.unit.test_runtime_observation import observation

T = datetime(2026, 1, 1, tzinfo=UTC)


# Trusted deterministic test configuration; no production defaults or hardcoded application key.
def configuration(**changes):
    data = {"maximum_filter_terms": 20, "maximum_records": 100, "maximum_decoded_bytes": 2_000_000,
            "maximum_scan_records": 300, "maximum_scan_bytes": 2_000_000, "page_size": 100,
            "maximum_pages": 10, "maximum_predecessor_records": 10, "predecessor_lookback_seconds": 3600,
            "cursor_key": b"test-only-configuration-key-32-bytes"}
    data.update(changes)
    return EvidenceQueryConfiguration(**data)


def reader(engine, **changes):
    return BoundedEvidenceQuery(engine, configuration(**changes))


def request(**changes) -> EvidenceQueryRequest:
    data = {
        "start_time": T - timedelta(minutes=10), "end_time": T + timedelta(minutes=10),
        "time_basis": TimeBasis.GUARDIAN_RECEIPT_TIME,
        "as_of_cutoff": T + timedelta(minutes=10), "session_mode": AssociationMode.ALL,
        "maximum_filter_terms": 20,
        "maximum_records": 20, "maximum_decoded_bytes": 100_000,
        "maximum_scan_records": 100, "maximum_scan_bytes": 500_000,
        "page_size": 20, "maximum_pages": 4,
        "predecessor_lookback_seconds": 0, "maximum_predecessor_records": 0,
    }
    data.update(changes)
    return EvidenceQueryRequest(**data)


def save(repository: RuntimeEvidenceRepository, **changes):
    record = observation(**changes)
    repository.save_cycle([record])
    return record


def test_filters_cutoff_order_adverse_quality_and_null_source_time(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    first = save(repository, observation_id=UUID(int=3), ingestion_time=T,
                 observation_time=T - timedelta(seconds=2), guardian_session_id="session-a",
                 source=Source.NVML, signal="temperature_c", quality=Quality.STALE,
                 provenance={"miner_workload_id": 7})
    second = save(repository, observation_id=UUID(int=1), ingestion_time=T,
                  observation_time=T - timedelta(seconds=2), guardian_session_id="session-a",
                  source=Source.NVML, signal="temperature_c", quality=Quality.CORRUPTED,
                  provenance={"miner_workload_id": 7})
    null_clock = save(repository, observation_id=UUID(int=2), ingestion_time=T,
                      observation_time=None, guardian_session_id=None,
                      signal="temperature_c", provenance={"miner_workload_id": 7})
    save(repository, ingestion_time=T + timedelta(minutes=20),
         observation_time=T, guardian_session_id="session-a", signal="temperature_c")
    save(repository, ingestion_time=T, observation_time=T, guardian_session_id="session-b",
         source=Source.SRBMINER_HTTP, signal="hashrate_hs",
         provenance={"miner_workload_id": 8})
    query = reader(temp_db.engine)

    result = query.query(request(
        time_basis=TimeBasis.SOURCE_OBSERVATION_TIME,
        session_mode=AssociationMode.SPECIFIC, guardian_session_id="session-a",
        sources=(Source.NVML,), signals=("temperature_c",),
        subject_selectors=(SubjectSelector(provenance_key="miner_workload_id", expected_value=7),),
        as_of_cutoff=T + timedelta(minutes=1),
    ))
    assert result.records == (second, first)
    assert result.integrity == QueryIntegrity.VERIFIED
    assert result.completeness == QueryCompleteness.COMPLETE
    assert result.query_duration_seconds >= 0
    assert {record.quality for record in result.records} == {Quality.CORRUPTED, Quality.STALE}
    assert null_clock not in result.records  # Receipt time never substitutes for a null source clock.

    unassociated = query.query(request(session_mode=AssociationMode.UNASSOCIATED))
    assert unassociated.records == (null_clock,)

    instance = query.query(request(source_instance_mode=AssociationMode.SPECIFIC,
                                   source_instance="GPU-tested"))
    assert null_clock in instance.records and all(r.source_instance == "GPU-tested"
                                                  for r in instance.records)
    assert query.query(request(source_instance_mode=AssociationMode.UNASSOCIATED)).records == ()
    assert query.query(request(source_instance_mode=AssociationMode.SPECIFIC,
                               source_instance="missing")).records == ()
    assert query.query(request(sources=(Source.OBSERVER,))).records == ()
    assert query.query(request(signals=("missing",))).records == ()


def test_stable_pagination_continuation_and_changed_watermark(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    expected = [save(repository, observation_id=UUID(int=index + 1),
                     ingestion_time=T + timedelta(seconds=index)) for index in range(5)]
    query = reader(temp_db.engine)
    query_request = request(page_size=2, maximum_pages=3)
    first = query.query(query_request)
    assert first.records == tuple(expected[:2])
    assert first.completeness == QueryCompleteness.HAS_MORE
    second = query.query(query_request, first.continuation)
    third = query.query(query_request, second.continuation)
    assert first.records + second.records + third.records == tuple(expected)
    assert third.completeness == QueryCompleteness.COMPLETE and third.continuation is None
    assert len({first.dataset_watermark, second.dataset_watermark, third.dataset_watermark}) == 1

    initial = query.query(query_request)
    save(repository, ingestion_time=T + timedelta(seconds=9))
    with pytest.raises(EvidenceQueryChangedError, match="changed"):
        query.query(query_request, initial.continuation)
    with pytest.raises(EvidenceQueryChangedError, match="different query"):
        query.query(request(page_size=3, maximum_pages=2), initial.continuation)


@pytest.mark.parametrize("changes, kind", [
    ({"maximum_scan_records": 1}, QueryLimitKind.SCAN_RECORDS),
    ({"maximum_scan_bytes": 1}, QueryLimitKind.SCAN_BYTES),
    ({"maximum_records": 1, "page_size": 1}, QueryLimitKind.RESULT_RECORDS),
    ({"maximum_decoded_bytes": 1}, QueryLimitKind.DECODED_BYTES),
    ({"page_size": 1, "maximum_pages": 1}, QueryLimitKind.PAGINATION),
])
def test_resource_exhaustion_is_typed_and_never_returns_truncated_success(temp_db, changes, kind):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    save(repository, ingestion_time=T)
    save(repository, ingestion_time=T + timedelta(seconds=1))
    with pytest.raises(EvidenceQueryLimitError) as raised:
        reader(temp_db.engine).query(request(**changes))
    assert raised.value.kind == kind


def test_bounded_predecessors_are_separate_and_count_toward_byte_budget(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    old = save(repository, ingestion_time=T - timedelta(seconds=20))
    nearest = save(repository, ingestion_time=T - timedelta(seconds=5))
    current = save(repository, ingestion_time=T + timedelta(seconds=1))
    query_request = request(start_time=T, predecessor_lookback_seconds=30,
                            maximum_predecessor_records=1)
    result = reader(temp_db.engine).query(query_request)
    assert result.records == (current,)
    assert result.predecessors == (nearest,)
    assert old not in result.predecessors
    assert result.decoded_bytes > 0


def test_corruption_identity_header_and_missing_schema_fail_closed(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    record = save(repository)
    query = reader(temp_db.engine)
    assert query.query(request()).records == (record,)
    with temp_db.engine.begin() as connection:
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET payload_json = '{}'"))
    with pytest.raises(EvidenceQueryIntegrityError, match="integrity mismatch"):
        query.query(request())
    with temp_db.engine.begin() as connection:
        payload = record.model_dump_json()
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET payload_json=:payload, "
                                "payload_sha256=:digest, observation_id=:identity"),
                           {"payload": payload, "digest": hashlib.sha256(payload.encode()).hexdigest(),
                            "identity": str(uuid4())})
    with pytest.raises(EvidenceQueryIntegrityError, match="identity mismatch"):
        query.query(request())
    with temp_db.engine.begin() as connection:
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET observation_id=:identity"),
                           {"identity": str(record.observation_id)})
        connection.execute(text("UPDATE m3_runtime_cycles_v1 SET record_count=2"))
    with pytest.raises(EvidenceQueryIntegrityError, match="header"):
        query.query(request())

    empty_engine = create_engine("sqlite://")
    try:
        with pytest.raises(EvidenceQueryIntegrityError, match="missing runtime evidence table"):
            reader(empty_engine).query(request())
    finally:
        empty_engine.dispose()


def test_invalid_payload_session_and_ordinal_corruption_fail_closed(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    correlation = uuid4()
    first = observation(correlation_id=correlation, guardian_session_id="one")
    second = observation(correlation_id=correlation, guardian_session_id="one")
    repository.save_cycle([first, second])
    query = reader(temp_db.engine)
    with temp_db.engine.begin() as connection:
        malformed = '{"schema_version":"future"}'
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET payload_json=:payload, "
                                "payload_sha256=:digest WHERE observation_id=:identity"),
                           {"payload": malformed,
                            "digest": hashlib.sha256(malformed.encode()).hexdigest(),
                            "identity": str(first.observation_id)})
    with pytest.raises(EvidenceQueryIntegrityError, match="invalid canonical"):
        query.query(request())

    replacement = first.model_copy(update={"guardian_session_id": "two"}).model_dump_json()
    with temp_db.engine.begin() as connection:
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET payload_json=:payload, "
                                "payload_sha256=:digest WHERE observation_id=:identity"),
                           {"payload": replacement,
                            "digest": hashlib.sha256(replacement.encode()).hexdigest(),
                            "identity": str(first.observation_id)})
    with pytest.raises(EvidenceQueryIntegrityError, match="session mismatch"):
        query.query(request())

    restored = first.model_dump_json()
    with temp_db.engine.begin() as connection:
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET payload_json=:payload, "
                                "payload_sha256=:digest, ordinal=7 WHERE observation_id=:identity"),
                           {"payload": restored, "digest": hashlib.sha256(restored.encode()).hexdigest(),
                            "identity": str(first.observation_id)})
    with pytest.raises(EvidenceQueryIntegrityError, match="ordinal sequence"):
        query.query(request())

    with temp_db.engine.begin() as connection:
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET ordinal='bad' "
                                "WHERE observation_id=:identity"),
                           {"identity": str(first.observation_id)})
    with pytest.raises(EvidenceQueryIntegrityError, match="invalid runtime acquisition ordinal"):
        query.query(request())


def test_orphan_row_and_incompatible_read_schema_fail_closed():
    orphan_engine = create_engine("sqlite://")
    try:
        install_runtime_schema(orphan_engine)
        record = observation()
        payload = record.model_dump_json()
        with orphan_engine.begin() as connection:
            connection.execute(text("INSERT INTO m3_runtime_observations_v1 "
                "(observation_id, correlation_id, ordinal, payload_json, payload_sha256) "
                "VALUES (:observation, :correlation, 0, :payload, :digest)"),
                {"observation": str(record.observation_id), "correlation": str(record.correlation_id),
                 "payload": payload, "digest": hashlib.sha256(payload.encode()).hexdigest()})
        with pytest.raises(EvidenceQueryIntegrityError, match="no acquisition header"):
            reader(orphan_engine).query(request())
    finally:
        orphan_engine.dispose()

    wrong_engine = create_engine("sqlite://")
    try:
        with wrong_engine.begin() as connection:
            connection.execute(text("CREATE TABLE m3_runtime_cycles_v1 "
                                    "(correlation_id TEXT PRIMARY KEY, wrong INTEGER)"))
            connection.execute(text("CREATE TABLE m3_runtime_observations_v1 "
                "(observation_id TEXT PRIMARY KEY, correlation_id TEXT, ordinal INTEGER, "
                "payload_json TEXT, payload_sha256 TEXT)"))
        with pytest.raises(EvidenceQueryIntegrityError, match="incompatible runtime evidence schema"):
            reader(wrong_engine).query(request())
    finally:
        wrong_engine.dispose()


def test_query_uses_only_read_statements_and_rejects_forged_continuation(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    for index in range(3):
        save(repository, ingestion_time=T + timedelta(seconds=index))
    statements: list[str] = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    event.listen(temp_db.engine, "before_cursor_execute", capture)
    try:
        query = reader(temp_db.engine)
        query_request = request(page_size=2, maximum_pages=2)
        first = query.query(query_request)
        forged = first.continuation.model_copy(update={"next_offset": 99})
        with pytest.raises(EvidenceQueryChangedError, match="position"):
            query.query(query_request, forged)
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", capture)
    assert statements
    assert not any(statement.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"))
                   for statement in statements)


def test_request_contract_rejects_ambiguous_scope_and_unbounded_shapes():
    for changes in (
        {"start_time": T, "end_time": T},
        {"session_mode": AssociationMode.SPECIFIC},
        {"session_mode": AssociationMode.ALL, "guardian_session_id": "unexpected"},
        {"source_instance_mode": AssociationMode.SPECIFIC},
        {"source_instance_mode": AssociationMode.ALL, "source_instance": "unexpected"},
        {"sources": (Source.NVML, Source.NVML)},
        {"signals": ("x", "x")},
        {"signals": ("x", "y"), "maximum_filter_terms": 1},
        {"subject_selectors": (SubjectSelector(provenance_key="worker", expected_value="x"),
                               SubjectSelector(provenance_key="worker", expected_value="y"))},
        {"page_size": 21},
        {"maximum_predecessor_records": 1},
        {"predecessor_lookback_seconds": 1},
        {"schema_version": "future"},
    ):
        with pytest.raises(ValidationError):
            request(**changes)
    with pytest.raises(ValidationError):
        SubjectSelector(provenance_key="bad.path", expected_value="x")
    with pytest.raises(ValidationError):
        SubjectSelector(provenance_key="worker", expected_value=True)
    with pytest.raises(ValidationError):
        SubjectSelector(provenance_key="worker", expected_value="x" * 1025)


@pytest.mark.parametrize("change", [
    {"next_offset": 4}, {"next_page": 2}, {"next_offset": 4, "next_page": 2},
    {"ordering_version": "wrong"}, {"request_sha256": "a" * 64},
    {"dataset_watermark": "b" * 64}, {"schema_version": "wrong"},
    {"integrity_mac": "0" * 64},
])
def test_cursor_tampering_rejected_before_database_access(temp_db, change):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    for i in range(5):
        save(repository, ingestion_time=T + timedelta(seconds=i))
    query = reader(temp_db.engine)
    req = request(page_size=2)
    first = query.query(req)
    cursor = first.continuation.model_dump()
    cursor.update(change)
    calls = []
    def capture(*args):
        calls.append(args[2])
    event.listen(temp_db.engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(EvidenceQueryChangedError):
            query.query(req, json.dumps(cursor))
        assert calls == []
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("wire", ["not-json", "{}", "[]", "x" * 2049])
def test_malformed_wire_cursor_rejected(temp_db, wire):
    with pytest.raises(EvidenceQueryChangedError, match="malformed"):
        reader(temp_db.engine).query(request(), wire)


def test_authenticated_cursor_roundtrip_query_mismatch_and_key_isolation(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    expected = [save(repository, ingestion_time=T + timedelta(seconds=i)) for i in range(5)]
    query = reader(temp_db.engine)
    req = request(page_size=2)
    first = query.query(req)
    wire = first.continuation.model_dump_json()
    assert EvidenceQueryContinuation.model_validate_json(wire) == first.continuation
    second = query.query(req, wire)
    third = query.query(req, second.continuation.model_dump_json())
    assert first.records + second.records + third.records == tuple(expected)
    assert third.completeness == QueryCompleteness.COMPLETE
    assert third.continuation is None
    for changes in ({"signals": ("other",)}, {"start_time": T},
                    {"time_basis": TimeBasis.SOURCE_OBSERVATION_TIME}, {"as_of_cutoff": T}):
        with pytest.raises(EvidenceQueryChangedError, match="different query"):
            query.query(request(page_size=2, **changes), wire)
    with pytest.raises(EvidenceQueryChangedError, match="integrity"):
        reader(temp_db.engine, cursor_key=b"different-test-key-at-least-32-bytes").query(req, wire)
    assert "test-only" not in wire
    assert "cursor_key" not in configuration().model_dump_json()
    save(repository, ingestion_time=T + timedelta(days=1))
    with pytest.raises(EvidenceQueryChangedError, match="changed"):
        query.query(req, wire)


@pytest.mark.parametrize("name", ["maximum_scan_records", "maximum_scan_bytes", "maximum_decoded_bytes",
    "maximum_records", "maximum_filter_terms", "page_size", "maximum_pages",
    "maximum_predecessor_records", "predecessor_lookback_seconds"])
def test_all_trusted_ceilings_reject_before_sql(temp_db, name):
    changes = {name: getattr(configuration(), name) + 1}
    if name == "page_size":
        changes["maximum_records"] = changes[name]
    if name in ("maximum_predecessor_records", "predecessor_lookback_seconds"):
        changes.setdefault("maximum_predecessor_records", 1)
        changes.setdefault("predecessor_lookback_seconds", 1)
    calls = []
    def capture(*args):
        calls.append(args[2])
    event.listen(temp_db.engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(EvidenceQueryError, match="trusted ceiling"):
            reader(temp_db.engine).query(request(**changes))
        assert calls == []
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("value", [0, -1, 10**100, True, 1.5])
def test_unsafe_numeric_limits_never_reach_sql(temp_db, value):
    with pytest.raises(ValidationError):
        request(maximum_scan_records=value)
    # Validate even models forged through model_copy (which bypasses Pydantic).
    with pytest.raises(EvidenceQueryError, match="invalid evidence-query request"):
        reader(temp_db.engine).query(request().model_copy(update={"maximum_scan_records": value}))


def test_caller_cannot_raise_filter_ceiling(temp_db):
    req = request(signals=tuple(f"x{i}" for i in range(21)), maximum_filter_terms=21)
    with pytest.raises(EvidenceQueryError, match="maximum_filter_terms"):
        reader(temp_db.engine).query(req)


@pytest.mark.parametrize("budget", ["maximum_scan_bytes", "maximum_decoded_bytes"])
@pytest.mark.parametrize("matching", [True, False])
def test_oversized_payload_refused_before_fetch_or_decode(temp_db, monkeypatch, budget, matching):
    from mining_guardian.observability.models import RuntimeObservation
    repository = RuntimeEvidenceRepository(temp_db.engine)
    save(repository, signal="large", provenance={"blob": "x" * 1_000_000})
    calls = []
    def capture(*args):
        calls.append(args[2])
    def forbidden(*args, **kwargs):
        pytest.fail("canonical decode occurred before refusal")
    monkeypatch.setattr(RuntimeObservation, "model_validate_json", forbidden)
    event.listen(temp_db.engine, "before_cursor_execute", capture)
    try:
        req = request(**{budget: 1, "maximum_scan_bytes" if budget != "maximum_scan_bytes"
                         else "maximum_decoded_bytes": 2_000_000},
                      signals=("large" if matching else "nonmatching",))
        with pytest.raises(EvidenceQueryLimitError) as error:
            reader(temp_db.engine).query(req)
        assert error.value.kind == (QueryLimitKind.SCAN_BYTES if budget == "maximum_scan_bytes"
                                     else QueryLimitKind.DECODED_BYTES)
        assert any("length(CAST(" in statement for statement in calls)
        assert not any(statement.startswith("SELECT m3_runtime_observations_v1.payload_json")
                       for statement in calls)
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", capture)


def test_exact_byte_record_and_aggregate_scan_boundaries(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    a = save(repository, provenance={"unicode": "?" * 20})
    b = save(repository)
    size = sum(len(r.model_dump_json().encode("utf-8")) for r in (a, b))
    query = reader(temp_db.engine)
    req = request(maximum_records=2, page_size=2, maximum_scan_records=6,
                  maximum_scan_bytes=size, maximum_decoded_bytes=size)
    result = query.query(req)
    assert len(result.records) == 2
    assert result.scanned_records == 6  # two headers + two metadata + two payload rows
    assert result.scanned_bytes == result.decoded_bytes == size
    for changes, kind in (({"maximum_scan_records": 5}, QueryLimitKind.SCAN_RECORDS),
                          ({"maximum_scan_bytes": size - 1}, QueryLimitKind.SCAN_BYTES),
                          ({"maximum_decoded_bytes": size - 1}, QueryLimitKind.DECODED_BYTES),
                          ({"maximum_records": 1, "page_size": 1}, QueryLimitKind.RESULT_RECORDS)):
        with pytest.raises(EvidenceQueryLimitError) as error:
            query.query(EvidenceQueryRequest(**{**req.model_dump(), **changes}))
        assert error.value.kind == kind


def test_exact_temporal_boundaries_and_late_ingestion(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    cutoff = T + timedelta(seconds=10)
    for i, recorded, received in [
        (1, T, T), (2, T + timedelta(microseconds=1), T),
        (3, cutoff, cutoff), (4, cutoff + timedelta(microseconds=1), cutoff),
        (5, T + timedelta(seconds=1), cutoff + timedelta(microseconds=1)),
        (6, None, T),
    ]:
        save(repository, observation_id=UUID(int=i), observation_time=recorded, ingestion_time=received)
    result = reader(temp_db.engine).query(request(start_time=T, end_time=cutoff, as_of_cutoff=cutoff,
        time_basis=TimeBasis.SOURCE_OBSERVATION_TIME))
    assert [r.observation_id.int for r in result.records] == [2, 3]


@pytest.mark.parametrize("column_type,primary,match", [
    ("BLOB", "PRIMARY KEY", "types"), ("TEXT", "", "primary key"),
])
def test_schema_type_and_primary_key_corruption(column_type, primary, match):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE TABLE m3_runtime_cycles_v1 (correlation_id {column_type} "
                                    f"{primary}, record_count INTEGER, schema_version INTEGER)"))
            connection.execute(text("CREATE TABLE m3_runtime_observations_v1 "
                "(observation_id TEXT PRIMARY KEY, correlation_id TEXT, ordinal INTEGER, "
                "payload_json TEXT, payload_sha256 TEXT)"))
        with pytest.raises(EvidenceQueryIntegrityError, match=match):
            reader(engine).query(request())
    finally:
        engine.dispose()


def test_predecessor_ties_boundaries_filters_and_limits(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    for i, seconds, signal in [(1, -10, "wanted"), (2, -9, "wanted"), (3, 0, "wanted"),
                               (4, 0, "wanted"), (5, -1, "other"), (6, -11, "wanted")]:
        save(repository, observation_id=UUID(int=i), ingestion_time=T+timedelta(seconds=seconds), signal=signal)
    req = request(start_time=T, signals=("wanted",), predecessor_lookback_seconds=10,
                  maximum_predecessor_records=3)
    result = reader(temp_db.engine).query(req)
    assert [r.observation_id.int for r in result.predecessors] == [2, 3, 4]
    assert result.records == () and result.completeness == QueryCompleteness.COMPLETE
    limited = reader(temp_db.engine).query(EvidenceQueryRequest(**{**req.model_dump(),
                                                                 "maximum_predecessor_records": 1}))
    assert [r.observation_id.int for r in limited.predecessors] == [4]
    with pytest.raises(EvidenceQueryLimitError, match="decode budget"):
        reader(temp_db.engine).query(EvidenceQueryRequest(**{**req.model_dump(), "maximum_decoded_bytes": 1}))


def test_configuration_key_and_datetime_bounds(temp_db):
    with pytest.raises(ValidationError, match="32 bytes"):
        configuration(cursor_key=b"short")
    with pytest.raises(ValidationError):
        configuration(maximum_scan_records=10**100)
    with pytest.raises(EvidenceQueryError, match="timestamp range"):
        reader(temp_db.engine).query(request(start_time=datetime.min.replace(tzinfo=UTC),
            predecessor_lookback_seconds=1, maximum_predecessor_records=1))


def test_signed_but_impossible_cursor_and_wire_type_rejected(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    for i in range(3):
        save(repository, ingestion_time=T + timedelta(seconds=i))
    query = reader(temp_db.engine)
    req = request(page_size=2)
    first = query.query(req)
    # The test has trusted key access to reach the defensive positional guard.
    impossible = first.continuation.model_copy(update={"next_offset": 99})
    impossible = impossible.model_copy(update={"integrity_mac": query._mac(impossible)})
    with pytest.raises(EvidenceQueryChangedError, match="position"):
        query.query(req, impossible)


def test_invalid_metadata_and_database_failure_are_typed(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    saved = save(repository)
    query = reader(temp_db.engine)
    with temp_db.engine.begin() as connection:
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET observation_id=:bad"),
                           {"bad": "x" * 100})
    with pytest.raises(EvidenceQueryIntegrityError, match="payload or identity"):
        query.query(request())
    with temp_db.engine.begin() as connection:
        connection.execute(text("UPDATE m3_runtime_observations_v1 SET observation_id=:identity"),
                           {"identity": str(saved.observation_id)})
    def outage(*args):
        from sqlalchemy.exc import OperationalError
        raise OperationalError("read", {}, Exception("injected outage"))
    event.listen(temp_db.engine, "before_cursor_execute", outage)
    try:
        with pytest.raises(EvidenceQueryError, match="database read failed"):
            query.query(request())
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", outage)
    assert query.query(request()).records == (saved,)


def test_null_payload_size_fails_before_payload_fetch():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE m3_runtime_cycles_v1 "
                "(correlation_id TEXT PRIMARY KEY, record_count INTEGER, schema_version INTEGER)"))
            connection.execute(text("CREATE TABLE m3_runtime_observations_v1 "
                "(observation_id TEXT PRIMARY KEY, correlation_id TEXT, ordinal INTEGER, "
                "payload_json TEXT, payload_sha256 TEXT)"))
            connection.execute(text("INSERT INTO m3_runtime_observations_v1 VALUES ('a','b',0,NULL,'c')"))
        with pytest.raises(EvidenceQueryIntegrityError, match="payload size"):
            reader(engine).query(request())
    finally:
        engine.dispose()


def test_read_snapshot_is_pinned_during_byte_preflight(temp_db):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    saved = save(repository)
    transactions = []
    def capture(connection, cursor, statement, *args):
        if "length(CAST(" in statement:
            transactions.append(connection.connection.driver_connection.in_transaction)
    event.listen(temp_db.engine, "before_cursor_execute", capture)
    try:
        assert reader(temp_db.engine).query(request()).records == (saved,)
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", capture)
    assert transactions == [True]


# Escapes produce actual Unicode at runtime, independent of editor/shell encoding.
UNICODE_PAYLOADS = [
    pytest.param("plain ASCII", id="ascii"),
    pytest.param("caf\u00e9 d\u00e9j\u00e0", id="accented-latin"),
    pytest.param("\u0645\u0631\u062d\u0628\u0627", id="arabic"),
    pytest.param("\u6f22\u5b57\u4e2d\u6587", id="cjk"),
    pytest.param("\U0001f642\U0001f680", id="emoji"),
    pytest.param("ASCII \u00e9 \u0639 \u6f22 \U0001f642", id="mixed"),
]


@pytest.mark.parametrize("value", UNICODE_PAYLOADS)
def test_utf8_preflight_matches_real_unicode_bytes(temp_db, value):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    record = save(repository, provenance={"unicode": value})
    with temp_db.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA main.encoding").scalar_one() == "UTF-8"
        payload, size = connection.execute(text(
            "SELECT payload_json, length(CAST(payload_json AS BLOB)) "
            "FROM m3_runtime_observations_v1"
        )).one()
    assert value in payload
    assert size == len(payload.encode("utf-8"))
    if not value.isascii():
        assert size > len(payload)  # Character counts cannot pass this test.
    result = reader(temp_db.engine).query(request(maximum_scan_bytes=size, maximum_decoded_bytes=size))
    assert result.records == (record,)
    assert result.scanned_bytes == result.decoded_bytes == size


def assert_no_payload_access(engine, req, monkeypatch, error_type, match):
    from mining_guardian.observability.models import RuntimeObservation

    statements = []

    def capture(*args):
        statements.append(args[2])

    def forbidden(*args, **kwargs):
        pytest.fail("canonical decoding occurred before refusal")

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(RuntimeObservation, "model_validate_json", forbidden)
            with pytest.raises(error_type, match=match):
                reader(engine).query(req)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert "PRAGMA main.encoding" in statements
    assert not any(s.startswith("SELECT m3_runtime_observations_v1.payload_json") for s in statements)
    return statements


@pytest.mark.parametrize("value", ["ASCII", "\u00e9\u0639\u6f22\U0001f642"], ids=["ascii", "multibyte"])
@pytest.mark.parametrize("budget", ["maximum_scan_bytes", "maximum_decoded_bytes"])
@pytest.mark.parametrize("delta", [-1, 0, 1], ids=["one-under", "exact", "one-over"])
def test_unicode_exact_byte_admission(temp_db, monkeypatch, value, budget, delta):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    record = save(repository, provenance={"text": value * 20})
    required = len(record.model_dump_json().encode("utf-8"))
    req = request(**{budget: required + delta})
    if delta < 0:
        calls = assert_no_payload_access(temp_db.engine, req, monkeypatch, EvidenceQueryLimitError,
                                        "scan-byte budget" if budget == "maximum_scan_bytes" else "decode budget")
        assert any("length(CAST(" in s for s in calls)
    else:
        result = reader(temp_db.engine).query(req)
        assert result.records == (record,)
        assert result.completeness == QueryCompleteness.COMPLETE
        assert result.scanned_bytes == result.decoded_bytes == required


@pytest.mark.parametrize("encoding", ["UTF-16le", "UTF-16be"])
def test_utf16_storage_rejected_before_evidence_scan(monkeypatch, encoding):
    engine = create_engine("sqlite://")
    try:
        # Creation-time setup of a new disposable test database, never conversion.
        with engine.begin() as connection:
            connection.exec_driver_sql(f"PRAGMA encoding='{encoding}'")
        repository = RuntimeEvidenceRepository(engine)
        record = save(repository, provenance={"cjk": "\u6f22" * 10_000})
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA main.encoding").scalar_one() == encoding
            size = connection.execute(text(
                "SELECT length(CAST(payload_json AS BLOB)) FROM m3_runtime_observations_v1"
            )).scalar_one()
        assert size < len(record.model_dump_json().encode("utf-8"))  # Original bypass fixture.
        calls = assert_no_payload_access(engine, request(maximum_scan_bytes=size, maximum_decoded_bytes=size),
                                         monkeypatch, EvidenceQueryIntegrityError, "incompatible database encoding")
        assert calls == ["BEGIN", "PRAGMA main.encoding"]
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA main.encoding").scalar_one() == encoding
        assert repository.load_cycle(record.correlation_id) == [record]
    finally:
        engine.dispose()


@pytest.mark.parametrize("metadata_result", ["unknown", "UTF-16", None])
def test_unknown_encoding_metadata_fails_closed(temp_db, monkeypatch, metadata_result):
    # SQLite normally returns a known encoding. Simulate unrecognized/missing metadata.
    def replace_encoding(connection, cursor, statement, parameters, context, executemany):
        if statement == "PRAGMA main.encoding":
            return "SELECT ?", (metadata_result,)
        return statement, parameters

    event.listen(temp_db.engine, "before_cursor_execute", replace_encoding, retval=True)
    try:
        with pytest.raises(EvidenceQueryIntegrityError, match="incompatible database encoding"):
            reader(temp_db.engine).query(request())
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", replace_encoding)


@pytest.mark.parametrize("budget", ["maximum_scan_bytes", "maximum_decoded_bytes"])
def test_cumulative_multibyte_budget_refused_before_any_payload(temp_db, monkeypatch, budget):
    repository = RuntimeEvidenceRepository(temp_db.engine)
    records = [save(repository, provenance={"text": text_value * 40})
               for text_value in ("\u0639", "\u6f22", "\U0001f642")]
    sizes = [len(r.model_dump_json().encode("utf-8")) for r in records]
    ceiling = sum(sizes) - 1
    assert all(size < ceiling for size in sizes)
    calls = assert_no_payload_access(temp_db.engine, request(**{budget: ceiling}), monkeypatch,
                                     EvidenceQueryLimitError,
                                     "scan-byte budget" if budget == "maximum_scan_bytes" else "decode budget")
    assert any("length(CAST(" in s for s in calls)
    result = reader(temp_db.engine).query(request(**{budget: sum(sizes)}))
    assert len(result.records) == 3
    assert result.completeness == QueryCompleteness.COMPLETE
    assert result.scanned_bytes == result.decoded_bytes == sum(sizes)
