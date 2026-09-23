import pytest


@pytest.fixture(autouse=True)
def protocol_dir(tmp_path, monkeypatch):
    """Web tests store protocols in a temporary directory, never in the repository."""
    monkeypatch.setenv("PROTOCOL_DIR", str(tmp_path / "protocols"))
