from __future__ import annotations
import logging

from argus.core.settings import settings
from argus.sources.base import BaseMarketDataProvider
from argus.sources.yfinance_client import YFinanceProvider
from argus.sources.finnhub_client import FinnhubProvider
from argus.sources.twelvedata_client import TwelveDataProvider
from argus.sources.alphavantage_client import AlphaVantageProvider

logger = logging.getLogger(__name__)

PROVIDERS = {
    "yfinance": YFinanceProvider,
    "finnhub": FinnhubProvider,
    "twelvedata": TwelveDataProvider,
    "alphavantage": AlphaVantageProvider,
}

_logged_resolved = False


def get_market_data_provider(provider_name: str | None = None) -> BaseMarketDataProvider:
    """Resolve and return the configured market data provider instance.

    If the requested/configured provider is not available (e.g. missing API keys),
    it will warn and fall back to yfinance.
    """
    global _logged_resolved
    configured = (provider_name or settings.market_data_provider or "yfinance").lower().strip()

    provider_cls = PROVIDERS.get(configured)
    if not provider_cls:
        logger.warning("Unknown market data provider '%s'. Falling back to yfinance.", configured)
        provider_cls = YFinanceProvider
        configured = "yfinance"

    provider_instance = provider_cls()

    if not provider_instance.is_available():
        logger.warning(
            "API key for provider '%s' is not configured. Falling back to yfinance.", configured
        )
        provider_instance = YFinanceProvider()
        resolved_name = "yfinance"
    else:
        resolved_name = configured

    if not _logged_resolved:
        logger.info("Resolved market data provider: %s (configured: %s)", resolved_name, configured)
        _logged_resolved = True
    else:
        logger.debug("Resolved market data provider: %s", resolved_name)

    return provider_instance
