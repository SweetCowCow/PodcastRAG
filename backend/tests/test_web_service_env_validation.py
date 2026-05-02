"""Verify the web service's lifespan startup refuses to launch without
the OAuth/session env, while worker / dispatcher / beat entrypoints
remain importable in the same condition.
"""
import pytest

from app.core.config import settings
from app.main import _validate_web_env


def test_validate_web_env_passes_when_all_set():
    _validate_web_env()


@pytest.mark.parametrize(
    "attr",
    [
        "google_client_id",
        "google_client_secret",
        "google_redirect_uri",
        "session_secret",
    ],
)
def test_validate_web_env_raises_on_missing(attr, monkeypatch):
    monkeypatch.setattr(settings, attr, None)
    with pytest.raises(RuntimeError) as exc:
        _validate_web_env()
    assert attr.upper() in str(exc.value)


def test_worker_entrypoints_import_with_oauth_env_unset(monkeypatch):
    """Worker / dispatcher / beat must import even with OAuth env wiped.

    They never call _validate_web_env so they remain runnable for
    deployments where only the web service is mis-configured.
    """
    for attr in (
        "google_client_id",
        "google_client_secret",
        "google_redirect_uri",
        "session_secret",
    ):
        monkeypatch.setattr(settings, attr, None)

    import importlib

    import app.workers.celery_app
    import app.workers.dispatcher
    import app.workers.tasks

    importlib.reload(app.workers.celery_app)
    importlib.reload(app.workers.tasks)
    importlib.reload(app.workers.dispatcher)
