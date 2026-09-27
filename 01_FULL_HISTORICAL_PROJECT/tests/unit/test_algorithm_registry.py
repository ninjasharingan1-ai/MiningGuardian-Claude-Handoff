from mining_guardian.core import AlgorithmRegistry
from mining_guardian.enums import AlgorithmStatus
from mining_guardian.storage import Database


def test_pearlpow_aliases(temp_db):
    with temp_db.get_session() as session:
        registry = AlgorithmRegistry(session)
        for raw in ("pearlhash", "pearlpow", "PearlPow", "PEARLPOW"):
            record, created = registry.resolve(raw)
            assert created is False
            assert record is not None
            assert record.algorithm_id == "pearlpow"
            assert record.canonical_name == "PearlPow"


def test_miner_and_provider_specific_aliases(temp_db):
    with temp_db.get_session() as session:
        registry = AlgorithmRegistry(session)
        miner, _ = registry.resolve("pearlhash", scope_type="miner", scope_name="srbminer")
        provider, _ = registry.resolve("pearlpow", scope_type="provider", scope_name="unmineable")
        assert miner is not None and provider is not None
        assert miner.algorithm_id == provider.algorithm_id == "pearlpow"


def test_unknown_discovery_is_optimizer_ineligible(temp_db):
    with temp_db.get_session() as session:
        registry = AlgorithmRegistry(session)
        record, created = registry.resolve(
            "FutureHash-X9", scope_type="miner", scope_name="srbminer"
        )
        assert created is True
        assert record is not None
        assert record.canonical_name == "FutureHash-X9"
        assert record.status == AlgorithmStatus.DISCOVERED
        assert record.optimizer_eligible is False


def test_unknown_discovery_persists_across_restart(temp_db_path):
    url = f"sqlite:///{temp_db_path.as_posix()}"
    first_db = Database(url)
    with first_db.get_session() as session:
        first_registry = AlgorithmRegistry(session)
        first, created = first_registry.resolve("FutureHash-X9", scope_type="miner", scope_name="srbminer")
        assert created is True
        assert first is not None
        algorithm_id = first.algorithm_id
    first_db.close()

    second_db = Database(url)
    with second_db.get_session() as session:
        second_registry = AlgorithmRegistry(session)
        second, created = second_registry.resolve("FutureHash-X9", scope_type="miner", scope_name="srbminer")
        assert created is False
        assert second is not None
        assert second.algorithm_id == algorithm_id
        assert second.optimizer_eligible is False
    second_db.close()
