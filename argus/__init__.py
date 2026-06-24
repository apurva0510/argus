import warnings

# Suppress yfinance internal deprecation warnings
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    module="yfinance",
)

__all__ = ["core", "services"]
