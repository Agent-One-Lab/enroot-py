import os

# Default directories for Enroot
USER_CACHE_DIR = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
ENROOT_CACHE_DIR = os.path.join(USER_CACHE_DIR, "enroot")
if not os.path.exists(ENROOT_CACHE_DIR):
    os.makedirs(ENROOT_CACHE_DIR)
if not os.path.exists(os.path.join(ENROOT_CACHE_DIR, "images")):
    os.makedirs(os.path.join(ENROOT_CACHE_DIR, "images"))

ENROOT_HOME = os.getenv("ENROOT_HOME", ENROOT_CACHE_DIR)

# Toggle debug mode via env var
ENROOT_DEBUG = os.getenv("ENROOT_DEBUG", "0") == "1"

