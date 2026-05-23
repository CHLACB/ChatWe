class AppError(Exception):
    """Base application error."""


class DriverNotConfiguredError(AppError):
    """Raised when the real UIA driver lacks required local locator information."""


class IdentityVerificationError(AppError):
    """Raised when a conversation identity check fails."""


class HistoryReadError(AppError):
    """Raised when local history cannot be read."""


class SendFailedError(AppError):
    """Raised when message sending fails."""
