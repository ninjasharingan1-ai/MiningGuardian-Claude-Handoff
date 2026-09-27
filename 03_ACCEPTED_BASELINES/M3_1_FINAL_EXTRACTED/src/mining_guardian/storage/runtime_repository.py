"""Additive M3 evidence tables and connection-owned atomic acquisition writes.

M2 ORM sessions and metadata are deliberately not imported. Table creation is an
explicit v1 installation, not an implicit migration of an existing schema.
"""

import hashlib
from uuid import UUID

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine

from mining_guardian.observability.models import RuntimeObservation

MAX_CYCLE_RECORDS = 10_000
MAX_CYCLE_BYTES = 16_777_216
metadata = MetaData()
cycles = Table("m3_runtime_cycles_v1", metadata,
    Column("correlation_id", String(36), primary_key=True),
    Column("record_count", Integer, nullable=False),
    Column("schema_version", Integer, nullable=False),
)
observations = Table("m3_runtime_observations_v1", metadata,
    Column("observation_id", String(36), primary_key=True),
    Column("correlation_id", String(36), ForeignKey("m3_runtime_cycles_v1.correlation_id"), nullable=False, index=True),
    Column("ordinal", Integer, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
)


class RuntimeEvidenceIntegrityError(ValueError):
    pass


def install_runtime_schema(engine: Engine) -> None:
    """Create only missing M3 v1 tables; never alter or repair existing tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        names = set(inspector.get_table_names())
        for table in (cycles, observations):
            if table.name in names:
                columns = inspector.get_columns(table.name)
                expected = {column.name for column in table.columns}
                if {column["name"] for column in columns} != expected:
                    raise RuntimeEvidenceIntegrityError(f"incompatible runtime schema: {table.name}")
                for column in columns:
                    declared = table.c[column["name"]]
                    if column["type"]._type_affinity != declared.type._type_affinity:
                        raise RuntimeEvidenceIntegrityError(f"incompatible runtime column type: {table.name}.{declared.name}")
                primary = inspector.get_pk_constraint(table.name)["constrained_columns"]
                if primary != [next(iter(table.primary_key.columns)).name]:
                    raise RuntimeEvidenceIntegrityError(f"incompatible runtime primary key: {table.name}")
        if cycles.name in names:
            versions = connection.execute(select(cycles.c.schema_version).distinct()).scalars()
            if any(version != 1 for version in versions):
                raise RuntimeEvidenceIntegrityError("unsupported runtime schema version")
        for table in (cycles, observations):
            if table.name not in names:
                table.create(connection)


class RuntimeEvidenceRepository:
    """No caller ORM state is committed/discarded; each write owns its connection."""

    def __init__(self, engine: Engine, max_database_bytes: int = 1_073_741_824):
        if max_database_bytes < 1:
            raise ValueError("max_database_bytes must be positive")
        self.engine = engine
        self.max_database_bytes = max_database_bytes
        self._schema_ready = False

    def save_cycle(self, records: list[RuntimeObservation]) -> None:
        if not records or len(records) > MAX_CYCLE_RECORDS:
            raise RuntimeEvidenceIntegrityError("invalid acquisition size")
        # Revalidate to reject mutable nested data changed after model construction.
        validated = [RuntimeObservation.model_validate(r.model_dump()) for r in records]
        correlation = validated[0].correlation_id
        session = validated[0].guardian_session_id
        if any(r.correlation_id != correlation or r.guardian_session_id != session for r in validated):
            raise RuntimeEvidenceIntegrityError("mixed acquisition context")
        if len({r.observation_id for r in validated}) != len(validated):
            raise RuntimeEvidenceIntegrityError("duplicate observation identity")
        rows = []
        total = 0
        for ordinal, record in enumerate(validated):
            payload = record.model_dump_json()
            encoded = payload.encode("utf-8")
            total += len(encoded)
            if total > MAX_CYCLE_BYTES:
                raise RuntimeEvidenceIntegrityError("acquisition byte limit")
            rows.append({"observation_id": str(record.observation_id),
                         "correlation_id": str(correlation), "ordinal": ordinal,
                         "payload_json": payload, "payload_sha256": hashlib.sha256(encoded).hexdigest()})
        # SQLAlchemy rolls back the entire transaction and closes its connection on failure.
        if not self._schema_ready:
            install_runtime_schema(self.engine)
            self._schema_ready = True
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                page_size = connection.scalar(text("PRAGMA page_size"))
                page_count = connection.scalar(text("PRAGMA page_count"))
                # Conservative admission budget; no retention deletion or M2 mutation.
                if page_size * page_count + total * 2 > self.max_database_bytes:
                    raise RuntimeEvidenceIntegrityError("runtime storage capacity budget exceeded")
            connection.execute(cycles.insert().values(correlation_id=str(correlation),
                record_count=len(rows), schema_version=1))
            connection.execute(observations.insert(), rows)

    def load_cycle(self, correlation_id: UUID) -> list[RuntimeObservation]:
        with self.engine.connect() as connection:
            cycle = connection.execute(select(cycles).where(cycles.c.correlation_id == str(correlation_id))).mappings().first()
            if cycle is None:
                return []
            if cycle["schema_version"] != 1 or not 0 < cycle["record_count"] <= MAX_CYCLE_RECORDS:
                raise RuntimeEvidenceIntegrityError("invalid persisted acquisition header")
            rows = connection.execute(select(observations).where(
                observations.c.correlation_id == str(correlation_id)).order_by(observations.c.ordinal)
                .limit(MAX_CYCLE_RECORDS + 1)).mappings().all()
        if len(rows) != cycle["record_count"]:
            raise RuntimeEvidenceIntegrityError("incomplete persisted acquisition")
        result: list[RuntimeObservation] = []
        total = 0
        for ordinal, row in enumerate(rows):
            payload = row["payload_json"]
            total += len(payload.encode("utf-8"))
            if total > MAX_CYCLE_BYTES or row["ordinal"] != ordinal:
                raise RuntimeEvidenceIntegrityError("invalid persisted acquisition structure")
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["payload_sha256"]:
                raise RuntimeEvidenceIntegrityError("runtime payload integrity mismatch")
            record = RuntimeObservation.model_validate_json(payload)
            if str(record.observation_id) != row["observation_id"] or record.correlation_id != correlation_id:
                raise RuntimeEvidenceIntegrityError("runtime identity mismatch")
            if result and result[0].guardian_session_id != record.guardian_session_id:
                raise RuntimeEvidenceIntegrityError("runtime session mismatch")
            result.append(record)
        return result
