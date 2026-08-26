import pytest

from storage import db
from storage.paths import set_storage_root


@pytest.fixture
def isolated_storage(tmp_path):
    """Point the storage layer at a throwaway directory for the duration of
    one test, so tests never touch the real ~/MeetNote."""
    set_storage_root(tmp_path)
    db.init_db()
    return tmp_path
