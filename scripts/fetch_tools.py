#!/usr/bin/env python3
"""
Fetch the external binaries Waterdrop bundles into a standalone build.

Downloads `czkawka_cli`, `ffmpeg` and `ffprobe` for the *current* OS/arch into
the `bin/` folder, where `tools.resolve()` and the PyInstaller spec look for
them. Run this once before building (CI does it automatically); it is also handy
locally if you want to run Waterdrop from source without a system-wide install:

    python scripts/fetch_tools.py

Sources (all static, self-contained builds):
  - ffmpeg/ffprobe, macOS + Linux : ffmpeg.martin-riedl.de (amd64 / arm64)
  - ffmpeg/ffprobe, Windows        : github.com/BtbN/FFmpeg-Builds (win64-gpl)
  - czkawka_cli, all platforms     : github.com/qarmin/czkawka releases
"""

import io
import json
import os
import platform
import stat
import sys
import urllib.request
import zipfile

# Pinned versions — bump deliberately so builds stay reproducible.
CZKAWKA_VERSION = "11.0.1"

HERE = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(os.path.dirname(HERE), "bin")

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

_MACHINE = platform.machine().lower()
IS_ARM = _MACHINE in ("arm64", "aarch64")
# czkawka asset suffix vs. martin-riedl path token for this arch.
CZK_ARCH = "arm64" if IS_ARM else "x86_64"
MR_ARCH = "arm64" if IS_ARM else "amd64"


def _get(url):
    """Download `url` and return its bytes (with a UA so GitHub is happy)."""
    print(f"  ↓ {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "waterdrop-build"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def _write_binary(name, data):
    """Write bytes to bin/<name> and make it executable. Returns the path."""
    os.makedirs(BIN_DIR, exist_ok=True)
    if IS_WINDOWS and not name.lower().endswith(".exe"):
        name += ".exe"
    dest = os.path.join(BIN_DIR, name)
    with open(dest, "wb") as fh:
        fh.write(data)
    mode = os.stat(dest).st_mode
    os.chmod(dest, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"  ✓ {dest}  ({len(data):,} bytes)")
    return dest


def _zip_member(data, predicate):
    """Return the bytes of the first zip member matching `predicate(name)`."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if not info.is_dir() and predicate(info.filename):
                return zf.read(info)
    raise RuntimeError("no matching member found in archive")


# --------------------------------------------------------------------------- #
# czkawka_cli
# --------------------------------------------------------------------------- #
def fetch_czkawka():
    if IS_WINDOWS:
        asset = "windows_czkawka_cli.exe"
    elif IS_MAC:
        asset = f"mac_czkawka_cli_{CZK_ARCH}"
    elif IS_LINUX:
        asset = f"linux_czkawka_cli_{CZK_ARCH}"
    else:
        raise RuntimeError(f"unsupported platform: {sys.platform}")
    url = (f"https://github.com/qarmin/czkawka/releases/download/"
           f"{CZKAWKA_VERSION}/{asset}")
    _write_binary("czkawka_cli", _get(url))


# --------------------------------------------------------------------------- #
# ffmpeg / ffprobe
# --------------------------------------------------------------------------- #
def fetch_ffmpeg_unix():
    """macOS/Linux: martin-riedl ships each tool as a zip with the binary at root."""
    mr_os = "macos" if IS_MAC else "linux"
    base = f"https://ffmpeg.martin-riedl.de/redirect/latest/{mr_os}/{MR_ARCH}/release"
    for tool in ("ffmpeg", "ffprobe"):
        data = _zip_member(_get(f"{base}/{tool}.zip"),
                           lambda n, t=tool: os.path.basename(n) == t)
        _write_binary(tool, data)


def fetch_ffmpeg_windows():
    """Windows: BtbN ships a win64-gpl zip with the tools under <root>/bin/."""
    api = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
    release = json.loads(_get(api))
    asset = next(a for a in release["assets"]
                 if a["name"].endswith("win64-gpl.zip"))
    archive = _get(asset["browser_download_url"])
    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        data = _zip_member(archive,
                           lambda n, t=tool: n.replace("\\", "/").endswith(f"/bin/{t}"))
        _write_binary(tool, data)


def main():
    print(f"Fetching tools for {sys.platform}/{MR_ARCH} into {BIN_DIR}")
    fetch_czkawka()
    if IS_WINDOWS:
        fetch_ffmpeg_windows()
    else:
        fetch_ffmpeg_unix()
    print("Done.")


if __name__ == "__main__":
    main()
