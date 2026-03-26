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
    """Raised when an operation exceeds its configured timeout."""
