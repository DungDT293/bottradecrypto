class BotTradingError(Exception):
    """Base exception for all bot errors."""
    pass


class SignalParsingError(BotTradingError):
    """Raised when parsing fails or is ambiguous."""
    pass


class SignalValidationError(BotTradingError):
    """Raised when signal logic fails validation checks."""
    pass


class RiskCheckError(BotTradingError):
    """Raised when trade exceeds risk limits."""
    pass


class ExchangeAdapterError(BotTradingError):
    """Raised when exchange rejects or fails request."""
    pass


class AccountStateBlockedError(BotTradingError):
    """Raised when Binance account is not in one-way mode or has unsupported settings."""
    pass


class EmergencyCloseError(BotTradingError):
    """Raised when emergency close fails."""
    pass


class ReconciliationError(BotTradingError):
    """Raised when state reconciliation finds critical discrepancies."""
    pass

