import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Autorise HA à charger custom_components/ pendant les tests."""
    yield
