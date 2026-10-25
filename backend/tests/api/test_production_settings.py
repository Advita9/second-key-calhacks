from fastapi.testclient import TestClient
import pytest

from api import deps
from api.main import create_app


@pytest.mark.parametrize("token", ["", "   "])
def test_production_rejects_missing_ops_token(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("KERNEL_LOAD_DOTENV", "0")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OPS_TOKEN", token)
    monkeypatch.setenv("DEMO_MODE", "0")
    deps.reset()

    with pytest.raises(RuntimeError, match="OPS_TOKEN"):
        with TestClient(create_app()):
            pass

    deps.reset()


def test_production_rejects_demo_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KERNEL_LOAD_DOTENV", "0")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OPS_TOKEN", "test-production-token")
    monkeypatch.setenv("DEMO_MODE", "1")
    deps.reset()

    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        with TestClient(create_app()):
            pass

    deps.reset()