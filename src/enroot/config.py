import logging
import os
from pathlib import Path

# Default directories for Enroot
USER_CACHE_PATH = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
ENROOT_BASE_PATH = os.path.join(USER_CACHE_PATH, "enroot")
if not os.path.exists(ENROOT_BASE_PATH):
    os.makedirs(ENROOT_BASE_PATH)

if not os.path.exists(os.path.join(ENROOT_BASE_PATH, "images")):
    os.makedirs(os.path.join(ENROOT_BASE_PATH, "images"))

ENROOT_HOME = os.getenv("ENROOT_HOME", ENROOT_BASE_PATH)

ENROOT_IMAGES_PATH = os.getenv("ENROOT_IMAGES_PATH", os.path.join(ENROOT_BASE_PATH, "images"))

# Toggle debug mode via env var
ENROOT_DEBUG = os.getenv("ENROOT_DEBUG", "0") == "1"

# Use async implementation for run_enroot when set (ENROOT_ASYNC=1).
# When unset or 0, sync subprocess is used. When 1, run_enroot() uses run_enroot_async()
# via the event loop when no loop is already running (avoids blocking).
ENROOT_ASYNC = os.getenv("ENROOT_ASYNC", "0") == "1"


def configure_logging() -> None:
    """Configure the ``enroot`` package logger from ``ENROOT_DEBUG``.

    When ``ENROOT_DEBUG=1``, log level is DEBUG (verbose). Otherwise WARNING
    (quiet; only warnings and errors from this package).

    The level is read from the environment each time this is called, so you can
    adjust ``os.environ`` and call again to reconfigure (handlers are only added once).
    """
    debug = os.getenv("ENROOT_DEBUG", "0") == "1"
    log = logging.getLogger("enroot")
    log.setLevel(logging.DEBUG if debug else logging.WARNING)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s [enroot] %(message)s"))
        log.addHandler(handler)
    log.propagate = False


configure_logging()

_log = logging.getLogger("enroot.config")
_log.debug(
    "ENROOT_IMAGES_PATH: env=%r resolved=%s",
    os.getenv("ENROOT_IMAGES_PATH"),
    ENROOT_IMAGES_PATH,
)


def setup_enroot_env():
    global ENROOT_BASE_PATH
    # Define the sub-structure we discussed earlier
    os.environ["ENROOT_DATA_PATH"] = str(os.path.join(ENROOT_BASE_PATH, "data"))
    os.environ["ENROOT_RUNTIME_PATH"] = str(os.path.join(ENROOT_BASE_PATH, "runtime"))
    os.environ["ENROOT_CACHE_PATH"] = str(os.path.join(ENROOT_BASE_PATH, "cache"))

    # Ensure the directories actually exist so subprocess doesn't fail
    for path in [os.environ["ENROOT_DATA_PATH"],
                 os.environ["ENROOT_RUNTIME_PATH"],
                 os.environ["ENROOT_CACHE_PATH"]]:
        os.makedirs(path, exist_ok=True)

# We will use default setting for enroot
# setup_enroot_env()
