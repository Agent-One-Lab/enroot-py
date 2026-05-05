"""Custom exceptions aligned with docker-py for API compatibility."""

from __future__ import annotations


class EnrootError(Exception):
    """Base exception for enroot client errors."""

    def __init__(self, message: str):
        self.msg = message
        super().__init__(self.msg)


class APIError(EnrootError):
    """Raised when the enroot backend returns an error or a command fails."""


class NotFound(EnrootError):
    """Raised when a container is not found (e.g. containers.get)."""


class ImageNotFound(EnrootError):
    """Raised when an image is not found (e.g. images.get or pull)."""


class TimeoutError(EnrootError):
    """Raised when an operation exceeds its configured timeout (e.g. container create/start)."""


class MemoryError(APIError):
    """Raised when a prlimit ``mem_limit`` exec looks like RLIMIT/OOM (signal death or OOM-like output), not for normal tool exit codes."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        stderr: bytes | None = None,
    ):
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(message)


class MemGuardError(APIError):
    """Raised when a **running** mem-guarded exec hits the RSS cap (host exit 137)."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        output: bytes | None = None,
        stdout: bytes | None = None,
        stderr: bytes | None = None,
    ):
        self.exit_code = exit_code
        self.output = output
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message)
