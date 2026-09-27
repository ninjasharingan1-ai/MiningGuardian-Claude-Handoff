import hashlib
import re

from sqlalchemy.orm import Session

from ..enums import AlgorithmStatus
from ..logging import get_logger
from ..models import AlgorithmRecord
from ..storage.repository import AlgorithmRepository

logger = get_logger(__name__)


def normalize_algorithm_name(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value.strip()).casefold()


class AlgorithmRegistry:
    """Persistent algorithm identity registry."""

    def __init__(self, session: Session, *, seed_builtins: bool = True):
        self.repository = AlgorithmRepository(session)
        if seed_builtins:
            self.seed_builtins()

    def seed_builtins(self) -> None:
        pearl = AlgorithmRecord(
            algorithm_id="pearlpow",
            canonical_name="PearlPow",
            display_name="PearlPow",
            status=AlgorithmStatus.VERIFIED,
            source="built_in",
            last_verified_at=None,
            optimizer_eligible=True,
        )
        if self.repository.get(pearl.algorithm_id) is None:
            self.repository.upsert(pearl)

        for alias in ("pearlpow", "pearlhash", "PearlPow", "PEARLPOW"):
            self.repository.add_alias(
                pearl.algorithm_id,
                alias,
                normalize_algorithm_name(alias),
                "alias",
                "",
            )
        self.repository.add_alias(
            pearl.algorithm_id,
            "pearlhash",
            normalize_algorithm_name("pearlhash"),
            "miner",
            "srbminer",
        )
        self.repository.add_alias(
            pearl.algorithm_id,
            "pearlpow",
            normalize_algorithm_name("pearlpow"),
            "provider",
            "unmineable",
        )

    def resolve(
        self,
        raw_name: str,
        *,
        scope_type: str = "alias",
        scope_name: str = "",
        discover: bool = True,
    ) -> tuple[AlgorithmRecord | None, bool]:
        exact = raw_name.strip()
        if not exact:
            return None, False

        normalized = normalize_algorithm_name(exact)
        record = self.repository.find_by_alias(normalized, scope_type, scope_name)
        if record is None and scope_type != "alias":
            record = self.repository.find_by_alias(normalized, "alias", "")
        if record is not None:
            return record, False
        if not discover:
            return None, False

        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:48] or "unknown"
        algorithm_id = f"discovered-{slug}-{digest}"
        record = self.repository.get(algorithm_id)
        created = record is None
        if record is None:
            record = AlgorithmRecord(
                algorithm_id=algorithm_id,
                canonical_name=exact,
                display_name=exact,
                status=AlgorithmStatus.DISCOVERED,
                source=f"runtime:{scope_type}:{scope_name or 'generic'}",
                optimizer_eligible=False,
            )
            self.repository.upsert(record)
            logger.warning(
                "algorithm_discovered",
                raw_algorithm_name=exact,
                algorithm_id=algorithm_id,
                source=record.source,
            )
        self.repository.add_alias(
            algorithm_id,
            exact,
            normalized,
            scope_type,
            scope_name,
        )
        return record, created
