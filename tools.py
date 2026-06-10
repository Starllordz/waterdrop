"""
Waterdrop — external tool resolution.

Finds the command-line tools Waterdrop drives (`czkawka_cli`, `ffmpeg`,
`ffprobe`). In a standalone build the binaries ship inside the bundle; from a
source checkout they may sit in a local `bin/` folder; otherwise we fall back to
whatever is on the system PATH. This is the single place that knows where the
tools live, so the rest of the app just calls `tools.resolve("ffmpeg")`.
"""

import os
import shutil
import sys

IS_WINDOWS = os.name == "nt"


def _bundle_dir():
    """Where a packaged build keeps its bundled binaries, or None from source.

    PyInstaller sets ``sys.frozen`` and unpacks bundled data/binaries into
    ``sys._MEIPASS`` (a temp dir for one-file builds, the ``_internal`` folder
    for one-dir builds). Either way that is where we put the tools at build time.
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    return None


def _source_bin_dir():
    """A `bin/` folder next to the source — used when running un-packaged."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")


def _exe(name):
    """Add the .exe suffix on Windows so a bare tool name resolves to a file."""
    if IS_WINDOWS and not name.lower().endswith(".exe"):
        return name + ".exe"
    return name


_CACHE = {}


def resolve(name):
    """Return the path to tool `name`, preferring bundled copies over PATH.

    Search order: the PyInstaller bundle, a local `bin/` folder, then the system
    PATH. Falls back to the bare name so callers still get a runnable command
    (and a clear failure) when the tool is genuinely missing.
    """
    if name in _CACHE:
        return _CACHE[name]

    exe = _exe(name)
    for base in (_bundle_dir(), _source_bin_dir()):
        if not base:
            continue
        cand = os.path.join(base, exe)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            _CACHE[name] = cand
            return cand

    result = shutil.which(name) or shutil.which(exe) or name
    _CACHE[name] = result
    return result


def available(name):
    """True if tool `name` was found (bundled or on PATH)."""
    # resolve() returns an absolute path when found, and the bare name when not.
    return os.path.isabs(resolve(name))
