"""Bounded read-only queries over frozen M3.1 runtime evidence."""

import hashlib
import hmac
from datetime import datetime, timedelta
from enum import StrEnum
from time import monotonic
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretBytes,
    StringConstraints,
    field_validator,
    model_validator,
)
from sqlalchemy import LargeBinary, case, cast, func, inspect, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from mining_guardian.observability.models import RuntimeObservation, Source, utc
from mining_guardian.state.contracts import TimeBasis
from mining_guardian.storage.runtime_repository import cycles, observations

# SQLite LIMIT reserves one sentinel row; no operational defaults are implied.
SafeLimit = Annotated[int, Field(strict=True, ge=0, le=2**63 - 2)]

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]


class EvidenceQueryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AssociationMode(StrEnum):
    ALL = "ALL"
    SPECIFIC = "SPECIFIC"
    UNASSOCIATED = "UNASSOCIATED"


class QueryCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    HAS_MORE = "HAS_MORE"


class QueryIntegrity(StrEnum):
    VERIFIED = "VERIFIED"


class QueryLimitKind(StrEnum):
    SCAN_RECORDS = "SCAN_RECORDS"
    SCAN_BYTES = "SCAN_BYTES"
    RESULT_RECORDS = "RESULT_RECORDS"
    DECODED_BYTES = "DECODED_BYTES"
    PAGINATION = "PAGINATION"


class EvidenceQueryError(RuntimeError):
    """Base class for explicit read-only query failures."""


class EvidenceQueryIntegrityError(EvidenceQueryError):
    pass


class EvidenceQueryLimitError(EvidenceQueryError):
    def __init__(self, kind: QueryLimitKind, message: str):
        super().__init__(message)
        self.kind = kind


class EvidenceQueryChangedError(EvidenceQueryError):
    pass


class SubjectSelector(EvidenceQueryContract):
    """Exact top-level provenance match; it makes no identity equivalence claim."""

    provenance_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,64}$")]
    expected_value: Annotated[str, StringConstraints(min_length=1, max_length=1024)] | int

    @field_validator("expected_value", mode="before")
    @classmethod
    def reject_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("boolean is not a subject identity")
        return value


class EvidenceQueryRequest(EvidenceQueryContract):
    start_time: datetime
    end_time: datetime
    time_basis: TimeBasis
    as_of_cutoff: datetime
    session_mode: AssociationMode
    guardian_session_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_instance_mode: AssociationMode = AssociationMode.ALL
    source_instance: str | None = Field(default=None, min_length=1, max_length=1024)
    sources: tuple[Source, ...] = ()
    signals: tuple[Annotated[str, StringConstraints(min_length=1, max_length=128)], ...] = ()
    subject_selectors: tuple[SubjectSelector, ...] = ()
    maximum_filter_terms: SafeLimit = Field(gt=0)
    maximum_records: SafeLimit = Field(gt=0)
    maximum_decoded_bytes: SafeLimit = Field(gt=0)
    maximum_scan_records: SafeLimit = Field(gt=0)
    maximum_scan_bytes: SafeLimit = Field(gt=0)
    page_size: SafeLimit = Field(gt=0)
    maximum_pages: SafeLimit = Field(gt=0)
    predecessor_lookback_seconds: float = Field(ge=0)
    maximum_predecessor_records: SafeLimit = Field(ge=0)
    schema_version: Literal["m3.2.evidence-query.v1"] = "m3.2.evidence-query.v1"

    @field_validator("start_time", "end_time", "as_of_cutoff")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def coherent_scope_and_budgets(self) -> Self:
        if self.start_time >= self.end_time:
            raise ValueError("query interval must be finite and increasing")
        if self.session_mode == AssociationMode.SPECIFIC:
            if self.guardian_session_id is None:
                raise ValueError("specific session mode requires a session identity")
        elif self.guardian_session_id is not None:
            raise ValueError("session identity is valid only in specific mode")
        if self.source_instance_mode == AssociationMode.SPECIFIC:
            if self.source_instance is None:
                raise ValueError("specific source-instance mode requires an identity")
        elif self.source_instance is not None:
            raise ValueError("source-instance identity is valid only in specific mode")
        if len(set(self.sources)) != len(self.sources) or len(set(self.signals)) != len(self.signals):
            raise ValueError("query filters cannot contain duplicates")
        keys = [selector.provenance_key for selector in self.subject_selectors]
        if len(set(keys)) != len(keys):
            raise ValueError("subject provenance keys cannot repeat")
        if len(self.sources) + len(self.signals) + len(self.subject_selectors) > self.maximum_filter_terms:
            raise ValueError("query filters exceed the explicit filter-term budget")
        if self.page_size > self.maximum_records:
            raise ValueError("page size cannot exceed the total record budget")
        predecessor_enabled = self.maximum_predecessor_records > 0
        if predecessor_enabled != (self.predecessor_lookback_seconds > 0):
            raise ValueError("predecessor record and lookback budgets must be enabled together")
        return self


class EvidenceQueryConfiguration(EvidenceQueryContract):
    """Trusted application construction only; never deserialize from a query request.

    All operational ceilings are mandatory. The key must be provisioned by the
    application, shared only by readers intended to accept each other's cursors.
    """

    maximum_filter_terms: SafeLimit = Field(gt=0)
    maximum_records: SafeLimit = Field(gt=0)
    maximum_decoded_bytes: SafeLimit = Field(gt=0)
    maximum_scan_records: SafeLimit = Field(gt=0)
    maximum_scan_bytes: SafeLimit = Field(gt=0)
    page_size: SafeLimit = Field(gt=0)
    maximum_pages: SafeLimit = Field(gt=0)
    maximum_predecessor_records: SafeLimit
    predecessor_lookback_seconds: float = Field(ge=0)
    cursor_key: SecretBytes = Field(exclude=True, repr=False)

    @field_validator("cursor_key")
    @classmethod
    def strong_key(cls, value: SecretBytes) -> SecretBytes:
        if len(value.get_secret_value()) < 32:
            raise ValueError("cursor integrity key requires at least 32 bytes")
        return value


class EvidenceQueryContinuation(EvidenceQueryContract):
    request_sha256: Sha256
    dataset_watermark: Sha256
    next_offset: SafeLimit
    next_page: SafeLimit = Field(ge=1)
    ordering_version: Literal["selected-ingestion-uuid.v1"] = "selected-ingestion-uuid.v1"
    schema_version: Literal["m3.2.evidence-query-continuation.v2"] = "m3.2.evidence-query-continuation.v2"
    integrity_mac: Sha256


class EvidenceQueryResult(EvidenceQueryContract):
    """Transport result; budgets account for the entire scan, not just this page.

    scanned_records = cycle metadata rows + observation metadata rows + payload
    lookups (C + 2*O). Refusal may inspect one extra metadata-only sentinel row.
    scanned_bytes = UTF-8 stored payload bytes fetched; header/identity metadata
    is excluded and bounded by row limits and fixed-width SQL projections.
    decoded_bytes = serialized bytes admitted for ALL canonical decodes,
    including nonmatches. It is neither Python heap usage nor page-result size.
    """
    records: tuple[RuntimeObservation, ...]
    predecessors: tuple[RuntimeObservation, ...]
    completeness: QueryCompleteness
    integrity: QueryIntegrity
    dataset_watermark: Sha256
    request_sha256: Sha256
    continuation: EvidenceQueryContinuation | None
    total_records: int = Field(ge=0)
    decoded_bytes: int = Field(ge=0)
    scanned_records: int = Field(ge=0)
    scanned_bytes: int = Field(ge=0)
    query_duration_seconds: float = Field(ge=0)
    schema_version: Literal["m3.2.evidence-query-result.v1"] = "m3.2.evidence-query-result.v1"


class BoundedEvidenceQuery:
    """Restores exact M3.1 evidence without estimating, admitting, or writing."""

    def __init__(self, engine: Engine, configuration: EvidenceQueryConfiguration):
        if engine.dialect.name != "sqlite":
            raise EvidenceQueryError("bounded payload preflight currently requires SQLite")
        self.engine = engine
        self._configuration = configuration

    def _mac(self, cursor: EvidenceQueryContinuation) -> str:
        message = cursor.model_dump_json(exclude={"integrity_mac"}).encode("utf-8")
        return hmac.new(self._configuration.cursor_key.get_secret_value(), message, hashlib.sha256).hexdigest()

    def _validate_request(self, request: EvidenceQueryRequest) -> EvidenceQueryRequest:
        try:
            # Also rejects objects altered through Pydantic's validation-bypassing model_copy.
            request = EvidenceQueryRequest.model_validate(request.model_dump(warnings=False))
        except ValueError as exc:
            raise EvidenceQueryError("invalid evidence-query request") from exc
        for name in ("maximum_filter_terms", "maximum_records", "maximum_decoded_bytes",
                     "maximum_scan_records", "maximum_scan_bytes", "page_size", "maximum_pages",
                     "maximum_predecessor_records", "predecessor_lookback_seconds"):
            if getattr(request, name) > getattr(self._configuration, name):
                raise EvidenceQueryError(f"query exceeds trusted ceiling: {name}")
        try:
            self.start_for_predecessors(request)
        except OverflowError as exc:
            raise EvidenceQueryError("predecessor interval exceeds timestamp range") from exc
        return request

    def _validate_cursor(self, cursor: EvidenceQueryContinuation | str) -> EvidenceQueryContinuation:
        try:
            if isinstance(cursor, str):
                # Fixed wire-format bound, independent of caller budgets; fields are fixed-size.
                if len(cursor) > 2048:
                    raise ValueError("oversized cursor")
                cursor = EvidenceQueryContinuation.model_validate_json(cursor)
            else:
                cursor = EvidenceQueryContinuation.model_validate(cursor.model_dump())
        except ValueError as exc:
            raise EvidenceQueryChangedError("malformed evidence-query cursor") from exc
        if not hmac.compare_digest(cursor.integrity_mac, self._mac(cursor)):
            raise EvidenceQueryChangedError("cursor position or integrity was altered")
        return cursor

    def query(self, request: EvidenceQueryRequest,
              continuation: EvidenceQueryContinuation | str | None = None) -> EvidenceQueryResult:
        started_at = monotonic()
        request = self._validate_request(request)
        if continuation is not None:
            continuation = self._validate_cursor(continuation)
        request_digest = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
        if continuation is not None and continuation.request_sha256 != request_digest:
            raise EvidenceQueryChangedError("continuation belongs to a different query")

        cycle_rows, stored_rows = self._read_snapshot(request)
        watermark = self._watermark(cycle_rows, stored_rows)
        if continuation is not None and continuation.dataset_watermark != watermark:
            raise EvidenceQueryChangedError("runtime evidence changed during pagination")

        records, sizes = self._validate_snapshot(cycle_rows, stored_rows)
        primary: list[tuple[RuntimeObservation, int]] = []
        predecessors: list[tuple[RuntimeObservation, int]] = []
        predecessor_start = self.start_for_predecessors(request)
        for record, size in zip(records, sizes, strict=True):
            selected_time = self._selected_time(record, request.time_basis)
            if selected_time is None or record.ingestion_time > request.as_of_cutoff:
                continue
            if not self._matches_filters(record, request):
                continue
            if request.start_time < selected_time <= request.end_time:
                primary.append((record, size))
            elif (request.maximum_predecessor_records and predecessor_start < selected_time
                  <= request.start_time):
                predecessors.append((record, size))

        primary.sort(key=lambda item: self._order_key(item[0], request.time_basis))
        predecessors.sort(key=lambda item: self._order_key(item[0], request.time_basis))
        if len(primary) > request.maximum_records:
            raise EvidenceQueryLimitError(QueryLimitKind.RESULT_RECORDS,
                                          "evidence result exceeds record budget")
        pages = (len(primary) + request.page_size - 1) // request.page_size
        if pages > request.maximum_pages:
            raise EvidenceQueryLimitError(QueryLimitKind.PAGINATION,
                                          "evidence result exceeds pagination budget")
        predecessors = predecessors[-request.maximum_predecessor_records:]
        decoded_bytes = sum(sizes)  # Serialized bytes admitted for ALL canonical decodes, including nonmatches.

        offset = continuation.next_offset if continuation is not None else 0
        page = continuation.next_page if continuation is not None else 0
        if (offset > len(primary) or page >= request.maximum_pages
                or offset != page * request.page_size):
            raise EvidenceQueryChangedError("invalid evidence-query continuation position")
        selected = primary[offset:offset + request.page_size]
        next_offset = offset + len(selected)
        has_more = next_offset < len(primary)
        next_token = EvidenceQueryContinuation(
            request_sha256=request_digest, dataset_watermark=watermark,
            next_offset=next_offset, next_page=page + 1, integrity_mac="0" * 64,
        ) if has_more else None
        if next_token is not None:
            next_token = next_token.model_copy(update={"integrity_mac": self._mac(next_token)})
        return EvidenceQueryResult(
            records=tuple(record for record, _ in selected),
            predecessors=tuple(record for record, _ in predecessors) if page == 0 else (),
            completeness=QueryCompleteness.HAS_MORE if has_more else QueryCompleteness.COMPLETE,
            integrity=QueryIntegrity.VERIFIED, dataset_watermark=watermark,
            request_sha256=request_digest, continuation=next_token,
            total_records=len(primary), decoded_bytes=decoded_bytes,
            scanned_records=len(cycle_rows) + 2 * len(stored_rows),
            scanned_bytes=sum(len(str(row["payload_json"]).encode("utf-8")) for row in stored_rows),
            query_duration_seconds=monotonic() - started_at,
        )

    @staticmethod
    def start_for_predecessors(request: EvidenceQueryRequest) -> datetime:
        return request.start_time - timedelta(seconds=request.predecessor_lookback_seconds)

    def _read_snapshot(self, request: EvidenceQueryRequest) -> tuple[list[dict[str, object]],
                                                                      list[dict[str, object]]]:
        # Explicit BEGIN is required: sqlite3 legacy transaction mode does not start
        # a snapshot for SELECT. All size checks and payload fetches share this snapshot.
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN")
                # CAST(TEXT AS BLOB) uses the database encoding. Only UTF-8 storage
                # makes its byte length equal our canonical serialized UTF-8 unit.
                # This is a read-side precondition, not a frozen M3.1 schema rule.
                if connection.exec_driver_sql("PRAGMA main.encoding").scalar() != "UTF-8":
                    raise EvidenceQueryIntegrityError(
                        "incompatible database encoding: S2 evidence queries require UTF-8 SQLite storage"
                    )
                self._verify_schema(connection)
                cycle_rows = [dict(row) for row in connection.execute(
                    select(func.substr(cycles.c.correlation_id, 1, 37).label("correlation_id"),
                           case((func.typeof(cycles.c.record_count) == "integer", cycles.c.record_count))
                           .label("record_count"),
                           case((func.typeof(cycles.c.schema_version) == "integer", cycles.c.schema_version))
                           .label("schema_version"))
                    .order_by(cycles.c.correlation_id)
                    .limit(request.maximum_scan_records + 1)).mappings()]
                remaining = request.maximum_scan_records - len(cycle_rows)
                if remaining < 0:
                    raise EvidenceQueryLimitError(QueryLimitKind.SCAN_RECORDS, "cycle scan exceeds record budget")
                # Each observation costs one bounded metadata read plus one payload lookup.
                # One metadata-only sentinel detects exhaustion; never fetch its payload.
                metadata_rows = [dict(row) for row in connection.execute(select(
                    func.substr(observations.c.observation_id, 1, 37).label("observation_id"),
                    func.substr(observations.c.correlation_id, 1, 37).label("correlation_id"),
                    case((func.typeof(observations.c.ordinal) == "integer", observations.c.ordinal))
                    .label("ordinal"),
                    func.substr(observations.c.payload_sha256, 1, 65).label("payload_sha256"),
                    func.length(cast(observations.c.payload_json, LargeBinary)).label("payload_bytes"),
                ).order_by(observations.c.observation_id).limit(remaining // 2 + 1)).mappings()]
                if 2 * len(metadata_rows) > remaining:
                    raise EvidenceQueryLimitError(QueryLimitKind.SCAN_RECORDS, "aggregate scan exceeds record budget")
                if any(not isinstance(row["payload_bytes"], int) or row["payload_bytes"] < 0
                       for row in metadata_rows):
                    raise EvidenceQueryIntegrityError("invalid persisted payload size")
                total = sum(int(row["payload_bytes"]) for row in metadata_rows)
                if total > request.maximum_scan_bytes:
                    raise EvidenceQueryLimitError(QueryLimitKind.SCAN_BYTES, "payload preflight exceeds scan-byte budget")
                if total > request.maximum_decoded_bytes:
                    raise EvidenceQueryLimitError(QueryLimitKind.DECODED_BYTES, "payload preflight exceeds canonical decode budget")
                stored_rows: list[dict[str, object]] = []
                for row in metadata_rows:
                    payload = connection.scalar(select(observations.c.payload_json).where(
                        observations.c.observation_id == row["observation_id"]))
                    if not isinstance(payload, str):
                        raise EvidenceQueryIntegrityError("invalid persisted payload or identity")
                    stored_rows.append({**row, "payload_json": payload})
                return cycle_rows, stored_rows
        except SQLAlchemyError as exc:
            raise EvidenceQueryError("runtime evidence database read failed") from exc

    def _verify_schema(self, connection: Connection) -> None:
        inspector = inspect(connection)
        for table in (cycles, observations):
            if not inspector.has_table(table.name):
                raise EvidenceQueryIntegrityError(f"missing runtime evidence table: {table.name}")
            columns = inspector.get_columns(table.name)
            actual = {column["name"] for column in columns}
            expected = {column.name for column in table.columns}
            if actual != expected:
                raise EvidenceQueryIntegrityError(f"incompatible runtime evidence schema: {table.name}")
            if any(column["type"]._type_affinity != table.c[column["name"]].type._type_affinity
                   for column in columns):
                raise EvidenceQueryIntegrityError(f"incompatible runtime evidence types: {table.name}")
            primary = inspector.get_pk_constraint(table.name)["constrained_columns"]
            if primary != [next(iter(table.primary_key.columns)).name]:
                raise EvidenceQueryIntegrityError(f"incompatible runtime primary key: {table.name}")

    @staticmethod
    def _watermark(cycle_rows: list[dict[str, object]], stored_rows: list[dict[str, object]]) -> str:
        digest = hashlib.sha256()
        for row in cycle_rows:
            digest.update(f"C|{row['correlation_id']}|{row['record_count']}|{row['schema_version']}\n".encode())
        for row in stored_rows:
            digest.update(f"O|{row['observation_id']}|{row['correlation_id']}|{row['ordinal']}|"
                          f"{row['payload_sha256']}\n".encode())
        return digest.hexdigest()

    @staticmethod
    def _validate_snapshot(cycle_rows: list[dict[str, object]],
                           stored_rows: list[dict[str, object]]) -> tuple[list[RuntimeObservation], list[int]]:
        headers = {str(row["correlation_id"]): row for row in cycle_rows}
        if len(headers) != len(cycle_rows):
            raise EvidenceQueryIntegrityError("duplicate runtime acquisition header")
        grouped: dict[str, list[dict[str, object]]] = {key: [] for key in headers}
        records: list[RuntimeObservation] = []
        sizes: list[int] = []
        sessions: dict[str, str | None] = {}
        for row in stored_rows:
            correlation = str(row["correlation_id"])
            if correlation not in grouped:
                raise EvidenceQueryIntegrityError("runtime observation has no acquisition header")
            grouped[correlation].append(row)
            payload = str(row["payload_json"])
            encoded = payload.encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != row["payload_sha256"]:
                raise EvidenceQueryIntegrityError("runtime payload integrity mismatch")
            try:
                record = RuntimeObservation.model_validate_json(payload)
            except ValueError as exc:
                raise EvidenceQueryIntegrityError("invalid canonical runtime observation") from exc
            if (str(record.observation_id) != row["observation_id"]
                    or str(record.correlation_id) != correlation):
                raise EvidenceQueryIntegrityError("runtime evidence identity mismatch")
            if correlation in sessions and sessions[correlation] != record.guardian_session_id:
                raise EvidenceQueryIntegrityError("runtime acquisition session mismatch")
            sessions[correlation] = record.guardian_session_id
            records.append(record)
            sizes.append(len(encoded))
        for correlation, header in headers.items():
            rows = sorted(grouped[correlation], key=lambda row: BoundedEvidenceQuery._ordinal(row))
            if header["schema_version"] != 1 or header["record_count"] != len(rows):
                raise EvidenceQueryIntegrityError("invalid runtime acquisition header")
            if [row["ordinal"] for row in rows] != list(range(len(rows))):
                raise EvidenceQueryIntegrityError("invalid runtime acquisition ordinal sequence")
        return records, sizes

    @staticmethod
    def _ordinal(row: dict[str, object]) -> int:
        value = row["ordinal"]
        if not isinstance(value, int) or isinstance(value, bool):
            raise EvidenceQueryIntegrityError("invalid runtime acquisition ordinal")
        return value

    @staticmethod
    def _selected_time(record: RuntimeObservation, basis: TimeBasis) -> datetime | None:
        if basis == TimeBasis.SOURCE_OBSERVATION_TIME:
            return record.observation_time
        return record.ingestion_time

    @classmethod
    def _order_key(cls, record: RuntimeObservation, basis: TimeBasis) -> tuple[datetime, datetime, str]:
        selected = cls._selected_time(record, basis)
        if selected is None:  # Only called after null-time exclusion.
            raise EvidenceQueryIntegrityError("selected query time is unavailable")
        return selected, record.ingestion_time, str(record.observation_id)

    @staticmethod
    def _matches_filters(record: RuntimeObservation, request: EvidenceQueryRequest) -> bool:
        if request.session_mode == AssociationMode.SPECIFIC:
            if record.guardian_session_id != request.guardian_session_id:
                return False
        elif request.session_mode == AssociationMode.UNASSOCIATED and record.guardian_session_id is not None:
            return False
        if request.source_instance_mode == AssociationMode.SPECIFIC:
            if record.source_instance != request.source_instance:
                return False
        elif request.source_instance_mode == AssociationMode.UNASSOCIATED and record.source_instance is not None:
            return False
        if request.sources and record.source not in request.sources:
            return False
        if request.signals and record.signal not in request.signals:
            return False
        return all(type(record.provenance.get(selector.provenance_key))
                   is type(selector.expected_value)
                   and record.provenance.get(selector.provenance_key) == selector.expected_value
                   for selector in request.subject_selectors)
