"""M3.2-S3 subject, workload and algorithm identity resolution.

Identity is resolved only from a caller-supplied immutable mapping snapshot.
This module never consults or mutates the mutable algorithm registry, never
treats row position as identity, never guesses a GPU-to-workload relationship,
and never infers network, asset or payout identity from an algorithm alias.

Raw source tokens are preserved exactly and are never rewritten, normalized in
place, or silently mapped onto a different algorithm.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from json import dumps
from typing import Annotated, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, StringConstraints, model_validator

from mining_guardian.observability.models import RuntimeObservation
from mining_guardian.state.contracts import FrozenMapping, Name, StateContract

IDENTITY_METHOD = "m3.2.deterministic-identity"
IDENTITY_METHOD_VERSION = "v1"
SUBJECT_RESOLUTION_METHOD = "m3.2.subject-resolution"
SUBJECT_RESOLUTION_METHOD_VERSION = "v1"
ALGORITHM_ALIAS_NORMALIZATION = "strip_casefold_remove_separators"

ProvenanceKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,64}$")]
_IDENTITY_RESERVED = ("|", "=")
_IDENTITY_ROOT = uuid5(NAMESPACE_URL, "miningguardian/m3.2/s3/identity/v1")


class SubjectResolutionError(RuntimeError):
    """Base class for explicit subject-identity failures."""


class SubjectResolutionIntegrityError(SubjectResolutionError):
    """Supplied evidence is not a canonical, unambiguous evidence set."""


class SubjectResolutionLimitError(SubjectResolutionError):
    """A declared bounded-work ceiling was exceeded."""


def canonical_identity_payload(parts: Sequence[str]) -> str:
    """Unambiguous, order-significant encoding of identity-relevant inputs."""
    return dumps(list(parts), separators=(",", ":"), ensure_ascii=True)


def deterministic_uuid(namespace: str, parts: Sequence[str]) -> UUID:
    """Deterministic UUIDv5 identity; no random or wall-clock input is involved."""
    if not namespace:
        raise ValueError("identity namespace must be declared")
    payload = canonical_identity_payload(
        [IDENTITY_METHOD, IDENTITY_METHOD_VERSION, namespace, *parts]
    )
    return uuid5(uuid5(_IDENTITY_ROOT, namespace), payload)


def deterministic_digest(namespace: str, parts: Sequence[str]) -> str:
    """Deterministic SHA-256 identity for string identities such as segment refs."""
    if not namespace:
        raise ValueError("identity namespace must be declared")
    payload = canonical_identity_payload(
        [IDENTITY_METHOD, IDENTITY_METHOD_VERSION, namespace, *parts]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_algorithm_token(token: str) -> str:
    """S3-local, versioned alias normalization.

    Deliberately independent of the mutable algorithm registry: S3 identity must
    be reproducible from the supplied mapping snapshot alone.
    """
    return re.sub(r"[\s_\-]+", "", token.strip()).casefold()


class IdentityComponentStatus(StrEnum):
    """Fixity of one identity component; unknown identity stays explicitly unknown."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    NOT_DECLARED = "NOT_DECLARED"


class IdentityComponent(StateContract):
    """One scoped identity component with all resolver evidence preserved."""

    status: IdentityComponentStatus
    resolved_id: str | None = None
    composed_key: str | None = None
    source_token: str | None = None
    reason: Name
    facts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def outcome_matches_evidence(self) -> Self:
        if self.status == IdentityComponentStatus.NOT_DECLARED:
            if self.resolved_id is not None or self.composed_key is not None or self.source_token is not None:
                raise ValueError("undeclared identity cannot carry resolution evidence")
        elif self.status == IdentityComponentStatus.RESOLVED:
            if self.resolved_id is None:
                raise ValueError("resolved identity requires an identity value")
        elif self.resolved_id is not None:
            raise ValueError("unresolved identity cannot claim an identity value")
        return self


class IdentityResolution(StateContract):
    """Fixed scoped identity for one observation, or explicit unknown components."""

    observation_id: UUID
    subject: IdentityComponent
    workload: IdentityComponent
    algorithm: IdentityComponent
    mapping_id: Name
    mapping_version: Name
    method_name: Name = SUBJECT_RESOLUTION_METHOD
    method_version: Name = SUBJECT_RESOLUTION_METHOD_VERSION

    @property
    def components(self) -> tuple[IdentityComponent, IdentityComponent, IdentityComponent]:
        return (self.subject, self.workload, self.algorithm)

    @property
    def unresolved_components(self) -> tuple[str, ...]:
        """Declared-but-unprovable components; these block scoped arithmetic."""
        return tuple(name for name, component in zip(("subject", "workload", "algorithm"),
                                                     self.components, strict=True)
                     if component.status == IdentityComponentStatus.UNRESOLVED)

    @property
    def resolved(self) -> bool:
        return all(component.status == IdentityComponentStatus.RESOLVED
                   for component in self.components)

    @property
    def scope_key(self) -> str:
        """Deterministic scope signature; undeclared and unresolved stay distinct."""
        parts = []
        for name, component in (("subject", self.subject), ("workload", self.workload),
                                ("algorithm", self.algorithm)):
            value = component.resolved_id if component.status == IdentityComponentStatus.RESOLVED else ""
            parts.append(f"{name}:{component.status.value}:{value}")
        return "|".join(parts)


class SubjectMapping(StateContract):
    """Caller-supplied immutable identity snapshot.

    S3 never mutates, extends or completes this snapshot. There is deliberately
    no network, asset or payout field: an algorithm alias can never establish
    network identity.
    """

    mapping_id: Name
    mapping_version: Name
    subject_provenance_keys: tuple[ProvenanceKey, ...] = ()
    include_source_instance_in_subject_key: bool
    subjects: FrozenMapping[str, str] = Field(default_factory=dict)
    workload_provenance_keys: tuple[ProvenanceKey, ...] = ()
    workloads: FrozenMapping[str, str] = Field(default_factory=dict)
    algorithm_provenance_key: ProvenanceKey | None = None
    algorithms: FrozenMapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent_declarations(self) -> Self:
        for keys, declared, label in (
            (self.subject_provenance_keys,
             bool(self.subjects) or self.include_source_instance_in_subject_key, "subject"),
            (self.workload_provenance_keys, bool(self.workloads), "workload"),
        ):
            if len(set(keys)) != len(keys):
                raise ValueError(f"duplicate {label} provenance key")
            if bool(keys) and not declared:
                raise ValueError(f"declared {label} identity keys require declared {label} identities")
            if not keys and declared and label == "workload":
                raise ValueError("declared workload identities require declared workload keys")
        if self.include_source_instance_in_subject_key and not (
            self.subject_provenance_keys or self.subjects
        ):
            raise ValueError("source-instance subject basis requires a subject declaration")
        if (not self.subject_provenance_keys and not self.include_source_instance_in_subject_key
                and self.subjects):
            raise ValueError("declared subject identities require a declared subject basis")
        if self.algorithm_provenance_key is None and self.algorithms:
            raise ValueError("declared algorithm identities require a declared algorithm key")
        if self.algorithm_provenance_key is not None and not self.algorithms:
            raise ValueError("declared algorithm key requires declared algorithm identities")
        for alias in self.algorithms:
            if alias != normalize_algorithm_token(alias):
                raise ValueError("algorithm aliases must be supplied already normalized")
        for identifier, value in (*self.subjects.items(), *self.workloads.items(),
                                  *self.algorithms.items()):
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("identity declarations require non-empty string keys")
            if not isinstance(value, str) or not value:
                raise ValueError("identity declarations require non-empty string identities")
        return self


class SubjectResolutionConfig(StateContract):
    """Explicit bounded-work configuration; there is no hidden operational default."""

    maximum_observations: int = Field(gt=0)


def _identity_token(key: str, value: object) -> tuple[str | None, str]:
    """Exact declared-key token, or an explicit reason why it is not an identity."""
    if isinstance(value, bool):
        return None, f"boolean_is_not_an_identity:{key}"
    if isinstance(value, int):
        return f"{key}={value}", ""
    if isinstance(value, str):
        if any(character in value for character in _IDENTITY_RESERVED):
            return None, f"identity_value_contains_reserved_separator:{key}"
        return f"{key}={value}", ""
    return None, f"unsupported_identity_value:{key}"


def compose_identity_key(record: RuntimeObservation, keys: Sequence[str], *,
                         include_source_instance: bool = False) -> tuple[str | None, tuple[str, ...]]:
    """Deterministic composed key plus explicit missing or unusable-key facts.

    Row position is never part of an identity key, and a missing key never
    degrades into a weaker identity.
    """
    parts: list[str] = []
    facts: list[str] = []
    if include_source_instance:
        instance = record.source_instance
        if instance is None:
            facts.append("source_instance_unavailable_for_declared_subject_key")
        elif any(character in instance for character in _IDENTITY_RESERVED):
            facts.append("identity_value_contains_reserved_separator:source_instance")
        else:
            parts.append(f"source_instance={instance}")
    for key in keys:
        if key not in record.provenance:
            facts.append(f"declared_key_absent_from_provenance:{key}")
            continue
        token, reason = _identity_token(key, record.provenance[key])
        if token is None:
            facts.append(reason)
        else:
            parts.append(token)
    if facts:
        return None, tuple(facts)
    return "|".join(parts), ()


def _declared_lookup(composed_key: str, declared: Mapping[str, str], reason_prefix: str,
                     facts: tuple[str, ...] = ()) -> IdentityComponent:
    resolved_id = declared.get(composed_key)
    if not isinstance(resolved_id, str) or not resolved_id:
        return IdentityComponent(
            status=IdentityComponentStatus.UNRESOLVED, composed_key=composed_key,
            reason=f"{reason_prefix}_not_certified_by_mapping_snapshot", facts=facts,
        )
    return IdentityComponent(
        status=IdentityComponentStatus.RESOLVED, resolved_id=resolved_id,
        composed_key=composed_key, reason=f"{reason_prefix}_certified_by_mapping_snapshot",
        facts=facts,
    )


def _subject_component(record: RuntimeObservation, mapping: SubjectMapping) -> IdentityComponent:
    declared = bool(mapping.subject_provenance_keys) or mapping.include_source_instance_in_subject_key
    if not declared:
        return IdentityComponent(status=IdentityComponentStatus.NOT_DECLARED,
                                 reason="subject_identity_not_declared")
    composed_key, facts = compose_identity_key(
        record, mapping.subject_provenance_keys,
        include_source_instance=mapping.include_source_instance_in_subject_key)
    if composed_key is None:
        return IdentityComponent(status=IdentityComponentStatus.UNRESOLVED,
                                 reason="subject_key_evidence_incomplete", facts=facts)
    return _declared_lookup(composed_key, mapping.subjects, "subject_key")


def _workload_component(record: RuntimeObservation, mapping: SubjectMapping) -> IdentityComponent:
    if not mapping.workload_provenance_keys:
        return IdentityComponent(status=IdentityComponentStatus.NOT_DECLARED,
                                 reason="workload_identity_not_declared")
    composed_key, facts = compose_identity_key(record, mapping.workload_provenance_keys)
    if composed_key is None:
        return IdentityComponent(status=IdentityComponentStatus.UNRESOLVED,
                                 reason="workload_key_evidence_incomplete", facts=facts)
    return _declared_lookup(composed_key, mapping.workloads, "workload_key")


def _algorithm_component(record: RuntimeObservation, mapping: SubjectMapping) -> IdentityComponent:
    key = mapping.algorithm_provenance_key
    if key is None:
        return IdentityComponent(status=IdentityComponentStatus.NOT_DECLARED,
                                 reason="algorithm_identity_not_declared")
    token = record.provenance.get(key)
    if not isinstance(token, str) or not token.strip():
        return IdentityComponent(
            status=IdentityComponentStatus.UNRESOLVED, reason="algorithm_source_token_unavailable",
            facts=(f"algorithm_provenance_key={key}",))
    normalized = normalize_algorithm_token(token)
    resolved_id = mapping.algorithms.get(normalized)
    if not isinstance(resolved_id, str) or not resolved_id:
        return IdentityComponent(
            status=IdentityComponentStatus.UNRESOLVED, composed_key=normalized, source_token=token,
            reason="algorithm_alias_not_certified_by_mapping_snapshot",
            facts=(ALGORITHM_ALIAS_NORMALIZATION, f"normalized_alias={normalized}"))
    return IdentityComponent(
        status=IdentityComponentStatus.RESOLVED, resolved_id=resolved_id, composed_key=normalized,
        source_token=token, reason="algorithm_alias_certified_by_mapping_snapshot",
        facts=(ALGORITHM_ALIAS_NORMALIZATION, f"normalized_alias={normalized}"))


def resolve_identity(record: RuntimeObservation, mapping: SubjectMapping) -> IdentityResolution:
    """Resolve one observation using only the supplied immutable mapping snapshot.

    The observation is revalidated against its own canonical contract before
    resolution. This rejects structurally invalid evidence and validation-
    bypassing mutation; it does not authenticate the payload, establish that a
    source label is truthful, or prove cryptographic origin.
    """
    try:
        mapping = SubjectMapping.model_validate(mapping.model_dump(warnings=False))
        record = RuntimeObservation.model_validate(record.model_dump(warnings=False))
    except (AttributeError, TypeError, ValueError) as exc:
        raise SubjectResolutionIntegrityError("invalid identity-resolution input") from exc
    return IdentityResolution(
        observation_id=record.observation_id,
        subject=_subject_component(record, mapping),
        workload=_workload_component(record, mapping),
        algorithm=_algorithm_component(record, mapping),
        mapping_id=mapping.mapping_id,
        mapping_version=mapping.mapping_version,
    )


def resolve_identities(records: Sequence[RuntimeObservation], mapping: SubjectMapping,
                       config: SubjectResolutionConfig) -> tuple[IdentityResolution, ...]:
    """Resolve a bounded evidence set: one resolution per observation, canonically ordered."""
    try:
        config = SubjectResolutionConfig.model_validate(config.model_dump(warnings=False))
        records = tuple(records)
    except (AttributeError, TypeError, ValueError) as exc:
        raise SubjectResolutionIntegrityError("invalid identity-resolution input") from exc
    if len(records) > config.maximum_observations:
        raise SubjectResolutionLimitError("identity resolution exceeds the observation budget")
    identities = tuple(resolve_identity(record, mapping) for record in records)
    identifiers = [identity.observation_id for identity in identities]
    if len(set(identifiers)) != len(identifiers):
        raise SubjectResolutionIntegrityError("duplicate evidence identity in identity resolution")
    return tuple(sorted(identities, key=lambda identity: str(identity.observation_id)))

