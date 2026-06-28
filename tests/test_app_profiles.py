from __future__ import annotations

from app import create_app
from config.settings import get_settings


def _app(tmp_path, monkeypatch, name: str, profile: str | None = None):
    db_path = tmp_path / f"{name}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SCHEDULER_HEARTBEAT_ENABLED", "false")
    monkeypatch.delenv("ENV_FILE", raising=False)
    if profile is None:
        monkeypatch.delenv("APP_PROFILE", raising=False)
    else:
        monkeypatch.setenv("APP_PROFILE", profile)
    return create_app()


def _paths(app) -> set[str]:
    return {route.path for route in app.routes}


def test_settings_default_to_production_profile(monkeypatch):
    monkeypatch.delenv("ENV_FILE", raising=False)
    monkeypatch.delenv("APP_PROFILE", raising=False)

    settings = get_settings()

    assert settings.app_profile == "production"
    assert settings.enable_demo_routes is False
    assert settings.enable_dataset_replay is False
    assert settings.enable_simulation_clock is False
    assert settings.enable_offline_evaluation is False
    assert settings.enable_mcp_simulation is False
    assert settings.enable_web_ui is False


def test_demo_profile_enables_demo_modules(monkeypatch):
    monkeypatch.delenv("ENV_FILE", raising=False)
    monkeypatch.setenv("APP_PROFILE", "demo")

    settings = get_settings()

    assert settings.app_profile == "demo"
    assert settings.enable_demo_routes is True
    assert settings.enable_dataset_replay is True
    assert settings.enable_simulation_clock is True
    assert settings.enable_offline_evaluation is True
    assert settings.enable_mcp_simulation is True
    assert settings.enable_web_ui is True


def test_production_profile_exposes_core_routes_and_hides_demo_routes(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, "production-default")
    paths = _paths(app)

    assert "/api/orders" in paths
    assert "/api/schedules" in paths
    assert "/api/evaluation/traces" in paths
    assert "/api/evaluation/thresholds/status" in paths
    assert "/api/datasets" not in paths
    assert "/api/simulation/clock" not in paths
    assert "/api/mcp/status" not in paths
    assert "/" not in paths
    assert not hasattr(app.state, "dataset_replay_service")


def test_demo_profile_keeps_replay_simulation_mcp_offline_eval_and_web_routes(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, "demo-profile", profile="demo")
    paths = _paths(app)

    assert "/api/datasets" in paths
    assert "/api/simulation/clock" in paths
    assert "/api/mcp/status" in paths
    assert "/api/evaluation/offline/run" in paths
    assert "/" in paths
    assert hasattr(app.state, "dataset_replay_service")
