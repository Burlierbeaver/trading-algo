class BrokerAdapterError(Exception):
    """Base class for all broker-adapter errors."""


class SafetyRailViolation(BrokerAdapterError):
    """A live-mode preflight check rejected the order before submission."""


class BrokerAPIError(BrokerAdapterError):
    """Alpaca returned an error, or the call failed after retries."""


class ReconciliationTimeout(BrokerAdapterError):
    """Polling exhausted POLL_TIMEOUT_S before the order reached a terminal state."""
