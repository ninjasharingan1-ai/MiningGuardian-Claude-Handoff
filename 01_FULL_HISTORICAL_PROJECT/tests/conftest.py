from pathlib import Path

import pytest

from mining_guardian.storage import Database


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def temp_db(temp_db_path: Path):
    database = Database(f"sqlite:///{temp_db_path.as_posix()}")
    try:
        yield database
    finally:
        database.close()
