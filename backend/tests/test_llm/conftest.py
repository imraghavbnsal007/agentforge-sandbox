import pytest

from app.llm.service import reset_provider_cache


@pytest.fixture(autouse=True)
def _fresh_provider_cache():
    reset_provider_cache()
    yield
    reset_provider_cache()
