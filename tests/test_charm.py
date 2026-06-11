import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charm import VantageAgentCharmedOperator


def _operator() -> VantageAgentCharmedOperator:
    return object.__new__(VantageAgentCharmedOperator)


def test_token_url_is_derived_from_app_vantage_url():
    operator = _operator()

    assert (
        operator._token_url("https://app.dev.vantagecompute.ai")
        == "https://auth.dev.vantagecompute.ai/realms/vantage/protocol/openid-connect/token"
    )


def test_token_url_accepts_hostname_without_scheme():
    operator = _operator()

    assert (
        operator._token_url("app.vantagecompute.ai")
        == "https://auth.vantagecompute.ai/realms/vantage/protocol/openid-connect/token"
    )


def test_snap_config_maps_secret_content_to_snap_keys():
    operator = _operator()

    assert operator._snap_config(
        {
            "vantage-url": "https://app.dev.vantagecompute.ai",
            "client-id": "client-id",
            "client-secret": "client-secret",
        }
    ) == {
        "vantage-url": "https://app.dev.vantagecompute.ai",
        "cluster-client-id": "client-id",
        "cluster-client-secret": "client-secret",
    }
