import os

# Les tests tournent hors production : sans code d'accès, le serveur de production refuse l'API (voir main.access_code_guard).
os.environ.setdefault("UNIC_ENV", "development")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _breaker_is_clean():
    """Le disjoncteur est un état global : un test qui provoque des pannes ne doit pas mettre les suivants en pause."""
    from app.breaker import BREAKER
    BREAKER.reset()
    yield
    BREAKER.reset()
