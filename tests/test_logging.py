"""Tests for enroot package logging (``ENROOT_DEBUG`` and ``configure_logging``)."""

from __future__ import annotations

import logging

import pytest


class _RecordingHandler(logging.Handler):
    """Collect log records for assertions."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def enroot_recording_handler():
    """Attach a recording handler to the ``enroot`` logger; remove after test."""
    log = logging.getLogger("enroot")
    h = _RecordingHandler()
    log.addHandler(h)
    yield h
    log.removeHandler(h)


def test_configure_logging_debug_when_enroot_debug_set(monkeypatch):
    monkeypatch.setenv("ENROOT_DEBUG", "1")
    from enroot.config import configure_logging

    configure_logging()
    assert logging.getLogger("enroot").level == logging.DEBUG


def test_configure_logging_warning_when_enroot_debug_unset(monkeypatch):
    monkeypatch.delenv("ENROOT_DEBUG", raising=False)
    from enroot.config import configure_logging

    configure_logging()
    assert logging.getLogger("enroot").level == logging.WARNING


def test_pull_image_emits_debug_and_info_when_debug_enabled(
    monkeypatch, tmp_path, enroot_recording_handler
):
    monkeypatch.setenv("ENROOT_DEBUG", "1")
    from enroot.config import configure_logging

    configure_logging()

    monkeypatch.setattr("enroot.image.run_enroot", lambda *args, **kwargs: "")

    from enroot.image import pull_image

    pull_image("testlogrepo", directory=str(tmp_path))

    messages = [r.getMessage() for r in enroot_recording_handler.records]
    assert any("Pulling image" in m for m in messages)
    assert any("ENROOT_IMAGES_PATH" in m for m in messages)
    assert any(
        r.levelno == logging.DEBUG and "ENROOT_IMAGES_PATH" in r.getMessage()
        for r in enroot_recording_handler.records
    )


def test_pull_image_no_records_when_quiet(monkeypatch, tmp_path, enroot_recording_handler):
    monkeypatch.delenv("ENROOT_DEBUG", raising=False)
    from enroot.config import configure_logging

    configure_logging()

    monkeypatch.setattr("enroot.image.run_enroot", lambda *args, **kwargs: "")

    from enroot.image import pull_image

    pull_image("testlogrepoquiet", directory=str(tmp_path))

    # Default WARNING level: DEBUG and INFO from pull_image are filtered out before handlers.
    assert enroot_recording_handler.records == []


def test_clear_enroot_containers_logs_info_when_debug_enabled(
    monkeypatch, enroot_recording_handler
):
    monkeypatch.setenv("ENROOT_DEBUG", "1")
    from enroot.config import configure_logging

    configure_logging()

    monkeypatch.setattr("enroot.utils.run_enroot", lambda *args, **kwargs: "")

    from enroot.utils import clear_enroot_containers

    clear_enroot_containers()

    assert any(
        r.levelno == logging.INFO and "Cleared all enroot containers" in r.getMessage()
        for r in enroot_recording_handler.records
    )


def test_clear_enroot_containers_no_info_when_quiet(monkeypatch, enroot_recording_handler):
    monkeypatch.delenv("ENROOT_DEBUG", raising=False)
    from enroot.config import configure_logging

    configure_logging()

    monkeypatch.setattr("enroot.utils.run_enroot", lambda *args, **kwargs: "")

    from enroot.utils import clear_enroot_containers

    clear_enroot_containers()

    assert not any(
        "Cleared all enroot containers" in r.getMessage()
        for r in enroot_recording_handler.records
    )
