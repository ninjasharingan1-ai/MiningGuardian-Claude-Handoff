from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from mining_guardian.storage.runtime_repository import (
    RuntimeEvidenceIntegrityError,
    RuntimeEvidenceRepository,
    install_runtime_schema,
)
from tests.unit.test_runtime_observation import observation


def test_additive_existing_m2_and_lossless_roundtrip(temp_db):
    before = set(inspect(temp_db.engine).get_table_names())
    install_runtime_schema(temp_db.engine)
    assert set(inspect(temp_db.engine).get_table_names()) - before == {"m3_runtime_cycles_v1", "m3_runtime_observations_v1"}
    install_runtime_schema(temp_db.engine)
    record = observation(provenance={"worker": "rig", "raw": [0, None]}, quality_metadata={"capability": "supported"})
    repository = RuntimeEvidenceRepository(temp_db.engine)
    repository.save_cycle([record])
    assert repository.load_cycle(record.correlation_id) == [record]
    with pytest.raises(IntegrityError):
        repository.save_cycle([record])
    assert repository.load_cycle(record.correlation_id) == [record]


def test_partial_insert_rolls_back_and_next_cycle_recovers():
    engine = create_engine("sqlite://")
    try:
        install_runtime_schema(engine)
        repository = RuntimeEvidenceRepository(engine)
        first = observation()

        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO m3_runtime_observations"):
                raise RuntimeError("simulated_disk_failure")

        event.listen(engine, "before_cursor_execute", fail)
        with pytest.raises(RuntimeError):
            repository.save_cycle([first])
        event.remove(engine, "before_cursor_execute", fail)
        assert repository.load_cycle(first.correlation_id) == []
        repository.save_cycle([first])
        assert repository.load_cycle(first.correlation_id) == [first]
        with engine.begin() as connection:
            connection.execute(text("UPDATE m3_runtime_observations_v1 SET payload_json = '{}'"))
        with pytest.raises(RuntimeEvidenceIntegrityError, match="integrity mismatch"):
            repository.load_cycle(first.correlation_id)
    finally:
        engine.dispose()


def test_schema_mismatch_not_repaired_and_context_not_fabricated():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE m3_runtime_cycles_v1 (wrong TEXT)"))
        with pytest.raises(RuntimeEvidenceIntegrityError):
            install_runtime_schema(engine)
        assert inspect(engine).get_table_names() == ["m3_runtime_cycles_v1"]
        repository = RuntimeEvidenceRepository(engine)
        with pytest.raises(RuntimeEvidenceIntegrityError, match="mixed"):
            repository.save_cycle([observation(), observation(correlation_id=uuid4())])
    finally:
        engine.dispose()


def test_capacity_budget_refuses_write_and_recovers_without_deletion():
    engine = create_engine("sqlite://")
    try:
        record = observation()
        repository = RuntimeEvidenceRepository(engine, max_database_bytes=1)
        with pytest.raises(RuntimeEvidenceIntegrityError, match="capacity budget"):
            repository.save_cycle([record])
        assert repository.load_cycle(record.correlation_id) == []
        repository.max_database_bytes = 1_073_741_824
        repository.save_cycle([record])
        assert repository.load_cycle(record.correlation_id) == [record]
    finally:
        engine.dispose()
