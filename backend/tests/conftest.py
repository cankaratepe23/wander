import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch, tmp_path):
    """Tests never reach Claude, the geocoder or real data: no API key, and a throwaway data dir."""
    monkeypatch.setenv("WANDER_ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("WANDER_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path, dev_mode=True, dev_user_email="alex@example.com", anthropic_api_key=""
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c
