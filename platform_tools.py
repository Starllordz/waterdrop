"""
Waterdrop — cross-platform helpers.

All the OS-specific behaviour lives here so the rest of the app stays portable:
folder picker, thumbnails, media metadata, and the Trash. Where possible the
implementation relies on `ffmpeg`/`ffprobe` (already required by the scanner)
instead of OS-only tools, so the same code path works on macOS, Windows and Linux.
"""

import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

import scanner

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")

# On Windows, hide the console windows spawned for helper subprocesses.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

THUMB_CACHE = os.path.join(tempfile.gettempdir(), "waterdrop_thumbs")
os.makedirs(THUMB_CACHE, exist_ok=True)


def _run(cmd, **kwargs):
    """subprocess.run with sane defaults and no flashing console on Windows."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    if _NO_WINDOW:
        kwargs.setdefault("creationflags", _NO_WINDOW)
    return subprocess.run(cmd, **kwargs)


# --------------------------------------------------------------------------- #
# External tool availability
# --------------------------------------------------------------------------- #
def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def ffprobe_available():
    return shutil.which("ffprobe") is not None


def install_hint():
    """Per-OS instructions for installing the required external tools."""
    if IS_MAC:
        return "Install with: brew install czkawka ffmpeg"
    if IS_WINDOWS:
        return "Install with: winget install czkawka.czkawka ffmpeg"
    return "Install with: sudo apt install czkawka ffmpeg  (or your distro's equivalent)"


# --------------------------------------------------------------------------- #
# Folder picker
# --------------------------------------------------------------------------- #
def pick_folder():
    """Show a native 'choose folder' dialog; return the path, or None.

    Returns None when the user cancels OR when no dialog tool is available on
    this system — in that case the user can type/paste the path in the UI.
    """
    try:
        if IS_MAC:
            script = 'POSIX path of (choose folder with prompt "Select a folder")'
            proc = _run(["osascript", "-e", script])
            if proc.returncode != 0:
                return None  # cancelled
            return proc.stdout.strip().rstrip("/") or "/"

        if IS_WINDOWS:
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }"
            )
            proc = _run(["powershell", "-NoProfile", "-STA", "-Command", ps])
            path = proc.stdout.strip()
            return path or None

        # Linux / other Unix: try zenity, then kdialog.
        if shutil.which("zenity"):
            proc = _run(["zenity", "--file-selection", "--directory",
                         "--title=Select a folder"])
            return proc.stdout.strip() or None if proc.returncode == 0 else None
        if shutil.which("kdialog"):
            proc = _run(["kdialog", "--getexistingdirectory", os.path.expanduser("~")])
            return proc.stdout.strip() or None if proc.returncode == 0 else None
    except OSError:
        return None
    return None  # no dialog available — fall back to manual entry in the UI


# --------------------------------------------------------------------------- #
# Thumbnails
# --------------------------------------------------------------------------- #
def make_thumbnail(path):
    """Return (file_path, content_type) for a 640px preview of `path`.

    Videos: a frame is extracted with ffmpeg (portable, no OS tool needed).
    Images: served as-is (browsers scale them); Pillow is used when available
    to produce a lighter thumbnail. Results are cached by path + mtime.
    """
    mtime = os.path.getmtime(path)
    key = hashlib.sha1(f"{path}:{mtime}".encode()).hexdigest()
    cached = os.path.join(THUMB_CACHE, key + ".png")
    if os.path.exists(cached):
        return cached, "image/png"

    kind = scanner.kind_of(path)

    if kind == "video":
        if _ffmpeg_thumbnail(path, cached):
            return cached, "image/png"
        return None, None

    # Image: try Pillow for a real thumbnail, else serve the original bytes.
    if _pillow_thumbnail(path, cached):
        return cached, "image/png"
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return path, ctype


def _ffmpeg_thumbnail(path, out_png):
    """Extract a single 640px-wide frame from a video. Returns True on success."""
    if not ffmpeg_available():
        return False
    tmp = out_png + ".tmp.png"
    # Seek ~1s in for a representative frame; retry at the start for short clips.
    for seek in ("1", "0"):
        try:
            _run(["ffmpeg", "-y", "-ss", seek, "-i", path,
                  "-frames:v", "1", "-vf", "scale=640:-1", tmp], timeout=20)
        except subprocess.TimeoutExpired:
            continue
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            try:
                shutil.move(tmp, out_png)
                return True
            except OSError:
                return False
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


def _pillow_thumbnail(path, out_png):
    """Make a 640px thumbnail with Pillow if it's installed. Returns success."""
    try:
        from PIL import Image  # optional dependency
    except ImportError:
        return False
    try:
        with Image.open(path) as im:
            im.thumbnail((640, 640))
            im.convert("RGB").save(out_png, "PNG")
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Media metadata (resolution / duration / bitrate)
# --------------------------------------------------------------------------- #
_INFO_CACHE = {}
_INFO_LOCK = threading.Lock()


def get_media_info(path):
    """Return {kind,size,width,height,duration,bitrate} for an image or video.

    Uses `ffprobe` for both (it reads image dimensions too), so a single code
    path works on every OS. Cached by path + mtime.
    """
    mtime = os.path.getmtime(path)
    cache_key = (path, mtime)
    with _INFO_LOCK:
        if cache_key in _INFO_CACHE:
            return _INFO_CACHE[cache_key]

    kind = scanner.kind_of(path)
    info = {"kind": kind, "size": os.path.getsize(path),
            "width": 0, "height": 0, "duration": 0, "bitrate": 0}

    if ffprobe_available():
        proc = _run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration,bit_rate",
             "-of", "json", path],
        )
        try:
            data = json.loads(proc.stdout or "{}")
            stream = (data.get("streams") or [{}])[0]
            fmt = data.get("format") or {}
            info["width"] = int(stream.get("width") or 0)
            info["height"] = int(stream.get("height") or 0)
            info["duration"] = float(fmt.get("duration") or 0)
            info["bitrate"] = int(fmt.get("bit_rate") or 0)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

    with _INFO_LOCK:
        _INFO_CACHE[cache_key] = info
    return info


# --------------------------------------------------------------------------- #
# Trash
# --------------------------------------------------------------------------- #
def trash_supported():
    """True if moving files to a recoverable Trash is possible on this system."""
    try:
        import send2trash  # noqa: F401
        return True
    except ImportError:
        return IS_MAC or IS_LINUX  # we have manual fallbacks for these


def move_to_trash(path):
    """Move a file to the OS Trash (recoverable). Returns True on success.

    Prefers the cross-platform `send2trash` library; falls back to a manual
    implementation on macOS (~/.Trash) and Linux (XDG trash spec).
    """
    try:
        from send2trash import send2trash
        send2trash(path)
        return True
    except ImportError:
        pass
    except OSError:
        return False

    if IS_MAC:
        return _trash_macos(path)
    if IS_LINUX:
        return _trash_linux(path)
    return False  # no recoverable Trash available without send2trash


def _trash_macos(path):
    try:
        trash = os.path.expanduser("~/.Trash")
        os.makedirs(trash, exist_ok=True)
        shutil.move(path, _unique_in(trash, os.path.basename(path)))
        return True
    except OSError:
        return False


def _trash_linux(path):
    """Move into the XDG trash (~/.local/share/Trash) with a .trashinfo record."""
    try:
        from urllib.parse import quote
        home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        base_trash = os.path.join(home, "Trash")
        files_dir = os.path.join(base_trash, "files")
        info_dir = os.path.join(base_trash, "info")
        os.makedirs(files_dir, exist_ok=True)
        os.makedirs(info_dir, exist_ok=True)

        name = os.path.basename(path)
        target = _unique_in(files_dir, name)
        final_name = os.path.basename(target)
        info_path = os.path.join(info_dir, final_name + ".trashinfo")
        with open(info_path, "w", encoding="utf-8") as fh:
            fh.write("[Trash Info]\n")
            fh.write(f"Path={quote(os.path.abspath(path))}\n")
            fh.write("DeletionDate=1970-01-01T00:00:00\n")
        shutil.move(path, target)
        return True
    except OSError:
        return False


def _unique_in(directory, base):
    """Return a path inside `directory` for `base`, suffixed if it already exists."""
    target = os.path.join(directory, base)
    if os.path.exists(target):
        stem, ext = os.path.splitext(base)
        target = os.path.join(directory, f"{stem} {uuid.uuid4().hex[:6]}{ext}")
    return target
