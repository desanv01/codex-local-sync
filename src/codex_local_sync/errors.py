"""Public failures safe for the CLI to report without a traceback."""


class SyncError(Exception):
    """A sync operation could not safely complete."""


class ValidationError(SyncError):
    """Input or normalized organization metadata is invalid."""


class ConflictError(SyncError):
    """Competing changes require a human decision."""


class BusyError(SyncError):
    """The settings target or application is busy."""


class CompatibilityError(SyncError):
    """The settings schema or platform is not supported."""
