#!/usr/bin/env python3
"""
Waterdrop — local web server (Python standard library only).

Serves a small single-page UI to find and remove duplicate photos/videos
between two folders. It drives `czkawka_cli` for scanning, macOS `osascript`
for the native folder picker, `qlmanage` for universal thumbnails (images and
videos), and moves deleted files to the macOS Trash.

Run:  python3 server.py      (then open the printed URL)
"""

import hashlib
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import scanner

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
THUMB_CACHE = os.path.join(tempfile.gettempdir(), "waterdrop_thumbs")
os.makedirs(THUMB_CACHE, exist_ok=True)

# Extra MIME types not always known to the stdlib.
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("video/mp4", ".m4v")

# In-memory job store for scans, and the set of folders the current scan is
# allowed to touch (used to validate every media/thumbnail/delete request).
JOBS = {}
JOBS_LOCK = threading.Lock()
ALLOWED_ROOTS = set()
ROOTS_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def set_allowed_roots(folder_a, folder_b):
    with ROOTS_LOCK:
        ALLOWED_ROOTS.clear()
        ALLOWED_ROOTS.add(os.path.realpath(folder_a))
        ALLOWED_ROOTS.add(os.path.realpath(folder_b))


def allowed_path(path):
    """Return the resolved path if it sits inside an allowed root, else None."""
    if not path:
        return None
    rp = os.path.realpath(path)
    with ROOTS_LOCK:
        for root in ALLOWED_ROOTS:
            if rp == root or rp.startswith(root + os.sep):
                return rp
    return None


def summarize(groups):
    """Counts per category and recoverable bytes (keep one copy per group)."""
    counts = {"IDENTICAL": 0, "SIMILAR_IMAGE": 0, "SIMILAR_VIDEO": 0}
    recoverable = 0
    for g in groups:
        counts[g["category"]] = counts.get(g["category"], 0) + 1
        sizes = [f["size"] for f in g["files"]]
        if sizes:
            recoverable += sum(sizes) - max(sizes)
    return {"counts": counts, "recoverable": recoverable, "groups": len(groups)}


def pick_folder():
    """Show the native macOS 'choose folder' dialog; return path or None."""
    script = 'POSIX path of (choose folder with prompt "Select a folder")'
    proc = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return None  # user cancelled
    return proc.stdout.strip().rstrip("/") or "/"


def make_thumbnail(path):
    """Generate (and cache) a Quick Look thumbnail PNG. Returns a file path.

    Falls back to the original file for images if Quick Look produces nothing.
    """
    mtime = os.path.getmtime(path)
    key = hashlib.sha1(f"{path}:{mtime}".encode()).hexdigest()
    cached = os.path.join(THUMB_CACHE, key + ".png")
    if os.path.exists(cached):
        return cached, "image/png"

    out_dir = tempfile.mkdtemp(prefix="ql_", dir=THUMB_CACHE)
    try:
        subprocess.run(
            ["qlmanage", "-t", "-s", "640", "-o", out_dir, path],
            capture_output=True, text=True, check=False, timeout=20,
        )
        produced = [f for f in os.listdir(out_dir) if f.lower().endswith(".png")]
        if produced:
            shutil.move(os.path.join(out_dir, produced[0]), cached)
            return cached, "image/png"
    except subprocess.TimeoutExpired:
        pass
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    # Fallback: serve the original bytes for images (browsers render them).
    if scanner.kind_of(path) == "image":
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return path, ctype
    return None, None


INFO_CACHE = {}
INFO_LOCK = threading.Lock()


def get_media_info(path):
    """Return resolution/quality metadata for an image or video file.

    Uses `sips` for images and `ffprobe` for videos (both already available on
    macOS once ffmpeg is installed). Results are cached by path + mtime.
    """
    mtime = os.path.getmtime(path)
    cache_key = (path, mtime)
    with INFO_LOCK:
        if cache_key in INFO_CACHE:
            return INFO_CACHE[cache_key]

    kind = scanner.kind_of(path)
    info = {"kind": kind, "size": os.path.getsize(path),
            "width": 0, "height": 0, "duration": 0, "bitrate": 0}

    if kind == "image":
        proc = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
            capture_output=True, text=True, check=False,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("pixelWidth:"):
                info["width"] = int(line.split(":")[1].strip() or 0)
            elif line.startswith("pixelHeight:"):
                info["height"] = int(line.split(":")[1].strip() or 0)
    else:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration,bit_rate",
             "-of", "json", path],
            capture_output=True, text=True, check=False,
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

    with INFO_LOCK:
        INFO_CACHE[cache_key] = info
    return info


def move_to_trash(path):
    """Move a file into the macOS Trash (~/.Trash), recoverable.

    Done with a plain filesystem move — NOT AppleScript/Finder — so it is
    instant and never triggers a macOS automation-permission prompt (which,
    if hidden behind the app window, would make deletion appear to hang).
    Returns True on success.
    """
    try:
        trash = os.path.expanduser("~/.Trash")
        os.makedirs(trash, exist_ok=True)
        base = os.path.basename(path)
        target = os.path.join(trash, base)
        if os.path.exists(target):
            stem, ext = os.path.splitext(base)
            target = os.path.join(trash, f"{stem} {uuid.uuid4().hex[:6]}{ext}")
        shutil.move(path, target)
        return True
    except OSError:
        return False


def delete_many(paths, permanent):
    """Delete a list of files (Trash by default). Returns counts and failures."""
    valid, failed, sizes = [], [], {}
    for p in paths:
        rp = allowed_path(p)
        if rp and os.path.isfile(rp):
            valid.append(rp)
            sizes[rp] = os.path.getsize(rp)
        else:
            failed.append(p)

    freed, deleted = 0, 0
    for rp in valid:
        try:
            ok = True
            if permanent:
                os.remove(rp)
            else:
                ok = move_to_trash(rp)
        except OSError:
            ok = False
        if ok:
            freed += sizes[rp]
            deleted += 1
        else:
            failed.append(rp)
    return {"deleted": deleted, "freed": freed, "failed": failed}


# --------------------------------------------------------------------------- #
# Scan job worker
# --------------------------------------------------------------------------- #
def run_scan_job(job_id, folder_a, folder_b, image_threshold, video_tolerance):
    def progress(step, total, label):
        with JOBS_LOCK:
            JOBS[job_id].update(step=step, total=total, label=label)

    try:
        groups = scanner.scan(
            folder_a, folder_b, image_threshold, video_tolerance, progress
        )
        with JOBS_LOCK:
            JOBS[job_id].update(
                status="done", step=3, total=3, label="Done",
                groups=groups, summary=summarize(groups),
            )
    except Exception as exc:  # surface any failure to the UI
        with JOBS_LOCK:
            JOBS[job_id].update(status="error", error=str(exc))


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "Waterdrop/1.0"

    def log_message(self, *args):
        pass  # keep the console quiet

    # ---- response helpers ------------------------------------------------- #
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype):
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False
        if rng and rng.startswith("bytes="):
            spec = rng.split("=", 1)[1].split(",", 1)[0].strip()
            s, _, e = spec.partition("-")
            if s.strip():
                start = int(s)
                end = int(e) if e.strip() else size - 1
            elif e.strip():  # suffix range: last N bytes
                start = max(0, size - int(e))
            end = min(end, size - 1)
            partial = True

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ---- routing ---------------------------------------------------------- #
    def do_GET(self):
        url = urlparse(self.path)
        path, qs = url.path, parse_qs(url.query)

        if path == "/":
            return self.serve_static("index.html")
        if path.startswith("/static/"):
            return self.serve_static(path[len("/static/"):])
        if path.startswith("/api/scan/"):
            return self.handle_scan_status(path.rsplit("/", 1)[1])
        if path == "/api/thumb":
            return self.handle_thumb(qs.get("path", [""])[0])
        if path == "/api/info":
            return self.handle_info(qs.get("path", [""])[0])
        if path == "/api/media":
            return self.handle_media(qs.get("path", [""])[0])
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/pick-folder":
            return self.handle_pick_folder()
        if path == "/api/scan":
            return self.handle_scan_start()
        if path == "/api/delete":
            return self.handle_delete()
        if path == "/api/delete-bulk":
            return self.handle_delete_bulk()
        self.send_error(404)

    # ---- handlers --------------------------------------------------------- #
    def serve_static(self, rel):
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self.send_error(404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_pick_folder(self):
        folder = pick_folder()
        self.send_json({"cancelled": folder is None, "path": folder or ""})

    def handle_scan_start(self):
        if not scanner.czkawka_available():
            return self.send_json(
                {"error": "czkawka_cli not found. Install with: brew install czkawka ffmpeg"},
                status=400,
            )
        body = self.read_body()
        folder_a = body.get("folderA", "")
        folder_b = body.get("folderB", "")
        if not os.path.isdir(folder_a) or not os.path.isdir(folder_b):
            return self.send_json({"error": "Both folders must exist."}, status=400)

        try:
            image_threshold = max(0, min(40, int(body.get("imageThreshold", 12))))
            video_tolerance = max(0, min(20, int(body.get("videoTolerance", 10))))
        except (TypeError, ValueError):
            image_threshold, video_tolerance = 12, 10

        set_allowed_roots(folder_a, folder_b)
        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "running", "step": 0, "total": 3,
                "label": "Starting…", "groups": [], "summary": None, "error": None,
                "folderA": os.path.realpath(folder_a),
                "folderB": os.path.realpath(folder_b),
            }
        threading.Thread(
            target=run_scan_job,
            args=(job_id, folder_a, folder_b, image_threshold, video_tolerance),
            daemon=True,
        ).start()
        self.send_json({"jobId": job_id})

    def handle_scan_status(self, job_id):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is None:
                return self.send_error(404)
            # Copy so we don't hold the lock while serializing.
            payload = dict(job)
        self.send_json(payload)

    def handle_thumb(self, path):
        rp = allowed_path(path)
        if not rp or not os.path.isfile(rp):
            return self.send_error(404)
        thumb, ctype = make_thumbnail(rp)
        if not thumb:
            return self.send_error(415)
        self.send_file(thumb, ctype)

    def handle_info(self, path):
        rp = allowed_path(path)
        if not rp or not os.path.isfile(rp):
            return self.send_error(404)
        self.send_json(get_media_info(rp))

    def handle_media(self, path):
        rp = allowed_path(path)
        if not rp or not os.path.isfile(rp):
            return self.send_error(404)
        ctype = mimetypes.guess_type(rp)[0] or "application/octet-stream"
        self.send_file(rp, ctype)

    def handle_delete(self):
        body = self.read_body()
        target = allowed_path(body.get("path", ""))
        if not target or not os.path.isfile(target):
            return self.send_json({"error": "File not found or out of scope."}, status=400)

        # Safety: never delete the last surviving copy of a group, unless the
        # caller explicitly asks to (e.g. the "Delete both" action).
        if not body.get("force"):
            keep = [allowed_path(p) for p in body.get("keep", [])]
            keep = [p for p in keep if p and p != target and os.path.isfile(p)]
            if not keep:
                return self.send_json(
                    {"error": "Refusing to delete the last remaining copy."}, status=400
                )

        size = os.path.getsize(target)
        permanent = bool(body.get("permanent"))
        if permanent:
            try:
                os.remove(target)
                ok = True
            except OSError:
                ok = False
        else:
            ok = move_to_trash(target)

        if not ok:
            return self.send_json({"error": "Delete failed."}, status=500)
        self.send_json({"ok": True, "freed": size, "permanent": permanent})

    def handle_delete_bulk(self):
        body = self.read_body()
        paths = body.get("paths", [])
        if not isinstance(paths, list) or not paths:
            return self.send_json({"error": "No files to delete."}, status=400)
        result = delete_many(paths, bool(body.get("permanent")))
        result["ok"] = True
        result["permanent"] = bool(body.get("permanent"))
        self.send_json(result)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def find_free_port(preferred=8765):
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def main():
    port = int(os.environ.get("WATERDROP_PORT") or find_free_port())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Waterdrop running at {url}")
    print("Press Ctrl+C to stop.")
    # Let a launcher know which URL to open.
    print(f"WATERDROP_URL={url}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
