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

print(f"Enroot image path: {os.getenv('ENROOT_IMAGES_PATH')}")

ENROOT_IMAGES_PATH = os.getenv("ENROOT_IMAGES_PATH", os.path.join(ENROOT_BASE_PATH, "images"))

# Toggle debug mode via env var
ENROOT_DEBUG = os.getenv("ENROOT_DEBUG", "0") == "1"

# Use async implementation for run_enroot when set (ENROOT_ASYNC=1).
# When unset or 0, sync subprocess is used. When 1, run_enroot() uses run_enroot_async()
# via the event loop when no loop is already running (avoids blocking).
ENROOT_ASYNC = os.getenv("ENROOT_ASYNC", "0") == "1"

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