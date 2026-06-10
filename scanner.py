"""
Waterdrop — duplicate scanner.

Wraps `czkawka_cli` to find duplicate photos/videos between TWO folders and
normalizes the results into simple "pair" groups for the UI.

Three kinds of duplicates are detected:
  - IDENTICAL     : byte-for-byte identical files (certain), via content hash
  - SIMILAR_IMAGE : visually similar photos (resized / re-compressed), perceptual hash
  - SIMILAR_VIDEO : visually similar videos, frame-based comparison

Only groups that span BOTH folders are returned (the user's goal: dedupe across
the two folders). Similar groups whose files are all already byte-identical are
dropped to avoid double-reporting.

Requires the `czkawka_cli` and `ffmpeg`/`ffprobe` binaries — bundled in a
standalone build, otherwise resolved from `bin/` or PATH (see `tools.py`).
See the README for per-OS install instructions.
"""

import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import tools

# File extensions we treat as video; everything else handled is an image.
VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".wmv",
    ".mpg", ".mpeg", ".3gp", ".m2ts", ".ts", ".vob", ".ogv",
}


def video_probe(path):
    """Return {'dimensions': 'WxH', 'duration': seconds} via ffprobe."""
    info = {"dimensions": "", "duration": 0.0}
    try:
        out = subprocess.run(
            [tools.resolve("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, text=True, check=False, timeout=15,
        ).stdout
        data = json.loads(out or "{}")
        stream = (data.get("streams") or [{}])[0]
        w, h = stream.get("width"), stream.get("height")
        if w and h:
            info["dimensions"] = f"{int(w)}x{int(h)}"
        info["duration"] = float((data.get("format") or {}).get("duration") or 0)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        pass
    return info


# Two videos within this many seconds are treated as the same length.
_DURATION_TOLERANCE = 1.0


def _refine_similar_videos(groups):
    """Enrich similar-video groups and split them by duration.

    czkawka's frame-hash similarity is noisy at loose tolerances and can lump
    together many unrelated clips (different lengths, even multiple from the
    same folder). Real re-encodes keep the same DURATION, so we re-cluster each
    group by duration and keep only the resulting cross-folder sub-groups. This
    also adds real resolution (used by the "keep best quality" action).
    """
    files = [f for g in groups for f in g["files"]]
    if files:
        with ThreadPoolExecutor(max_workers=8) as pool:
            metas = list(pool.map(lambda f: video_probe(f["path"]), files))
        for f, meta in zip(files, metas):
            if not f["dimensions"]:
                f["dimensions"] = meta["dimensions"]
            f["_dur"] = meta["duration"]

    def aspect(f):
        m = f["dimensions"].split("x") if f["dimensions"] else []
        if len(m) == 2 and m[0].isdigit() and m[1].isdigit() and int(m[1]):
            return round(int(m[0]) / int(m[1]), 2)
        return 0

    refined = []
    for g in groups:
        # Cluster by duration (sorted so clusters don't chain widely)...
        subs = []
        for f in sorted(g["files"], key=lambda f: f.get("_dur", 0)):
            for s in subs:
                if abs(f.get("_dur", 0) - s[0].get("_dur", 0)) <= _DURATION_TOLERANCE:
                    s.append(f)
                    break
            else:
                subs.append([f])
        # ...then split each duration cluster by aspect ratio. Real duplicates
        # agree on both; unrelated clips czkawka over-matched usually don't.
        for s in subs:
            by_aspect = {}
            for f in s:
                by_aspect.setdefault(aspect(f), []).append(f)
            for fs in by_aspect.values():
                if len(fs) >= 2 and _is_cross_folder(fs):
                    refined.append({"category": "SIMILAR_VIDEO", "files": fs})

    for g in refined:
        for f in g["files"]:
            f.pop("_dur", None)
    return refined


def czkawka_available():
    """Return True if the czkawka_cli binary is bundled or on PATH."""
    return tools.available("czkawka_cli")


def kind_of(path):
    """Classify a path as 'video' or 'image' by its extension."""
    return "video" if os.path.splitext(path)[1].lower() in VIDEO_EXTS else "image"


def _run_czkawka(args, json_path):
    """Run a czkawka_cli sub-command writing compact JSON to json_path.

    `-W` keeps the exit code at 0 even when duplicates are found, `-M` silences
    informational messages. Returns the parsed JSON, or an empty container when
    nothing was found / the file was not produced.
    """
    cmd = [tools.resolve("czkawka_cli"), *args, "-C", json_path, "-W", "-M"]
    subprocess.run(cmd, capture_output=True, text=True, check=False)
    if not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
        return None
    try:
        with open(json_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _iter_dup_groups(data):
    """Yield groups from the `dup` JSON: { "<size>": [ [ {file}, ... ] ] }."""
    if not isinstance(data, dict):
        return
    for groups in data.values():
        for group in groups:
            yield group


def _iter_similar_groups(data):
    """Yield groups from the `image`/`video` JSON: [ [ {file}, ... ] ]."""
    if not isinstance(data, list):
        return
    for group in data:
        yield group


def _normalize_file(entry, folder_a, folder_b):
    """Turn one czkawka file entry into the UI shape, or None if out of scope."""
    path = os.path.realpath(entry.get("path", ""))
    if path.startswith(folder_a + os.sep) or path == folder_a:
        side = "A"
    elif path.startswith(folder_b + os.sep) or path == folder_b:
        side = "B"
    else:
        return None
    width, height = entry.get("width"), entry.get("height")
    dimensions = f"{width}x{height}" if width and height else ""
    return {
        "path": path,
        "side": side,
        "name": os.path.basename(path),
        "size": int(entry.get("size", 0) or 0),
        "dimensions": dimensions,
        "kind": kind_of(path),
    }


def _is_cross_folder(files):
    """True when a group has at least one file on each side (A and B)."""
    return {f["side"] for f in files} == {"A", "B"}


def _dedupe_identical(files, ident_set_of):
    """Within a similar group, keep at most one file per byte-identical set.

    czkawka's similarity scan can lump an exact-duplicate pair together with a
    genuinely similar file. Two byte-identical files are the *same* content, so
    listing both as "similar" just re-reports what the IDENTICAL results already
    cover — and shows the same folder twice. We keep a single representative per
    identical set, preferring one whose side keeps the group spanning both
    folders (so the surviving similar relationship stays cross-folder).

    Files with unique content (not byte-identical to anything) are always kept.
    """
    extras = [f for f in files if f["path"] not in ident_set_of]
    kept = list(extras)
    sides_needed = {"A", "B"} - {f["side"] for f in extras}
    seen = set()
    # Two passes: first take a representative on a still-missing side, then fill
    # any remaining sets — so a set that can supply a missing folder does.
    for prefer_missing in (True, False):
        for f in files:
            sid = ident_set_of.get(f["path"])
            if sid is None or sid in seen:
                continue
            if prefer_missing and f["side"] not in sides_needed:
                continue
            kept.append(f)
            seen.add(sid)
            sides_needed.discard(f["side"])
    return kept


def scan(folder_a, folder_b, image_threshold=12, video_tolerance=10, progress=None):
    """Run all three scans and return normalized cross-folder duplicate groups.

    `progress(step, total, label)` is called before each scan step so the caller
    can report progress. Returns a list of groups:
        {"category": "IDENTICAL|SIMILAR_IMAGE|SIMILAR_VIDEO", "files": [ ... ]}
    """
    folder_a = os.path.realpath(folder_a)
    folder_b = os.path.realpath(folder_b)
    tmp = tempfile.mkdtemp(prefix="waterdrop_")

    def report(step, label):
        if progress:
            progress(step, 3, label)

    try:
        report(0, "Scanning identical files…")
        dup_json = _run_czkawka(
            ["dup", "-d", folder_a, "-d", folder_b, "-s", "hash"],
            os.path.join(tmp, "dup.json"),
        )

        report(1, "Scanning similar images…")
        img_json = _run_czkawka(
            ["image", "-d", folder_a, "-d", folder_b,
             "-c", "16", "-s", str(image_threshold)],
            os.path.join(tmp, "image.json"),
        )

        report(2, "Scanning similar videos…")
        vid_json = _run_czkawka(
            ["video", "-d", folder_a, "-d", folder_b, "-t", str(video_tolerance)],
            os.path.join(tmp, "video.json"),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- normalize identical groups (certain duplicates) ---
    # ident_set_of maps each file to the id of its byte-identical set, so similar
    # groups can drop redundant copies of content already paired up as identical.
    identical_groups = []
    ident_set_of = {}
    for set_id, group in enumerate(_iter_dup_groups(dup_json)):
        files = [f for f in (_normalize_file(e, folder_a, folder_b) for e in group) if f]
        for f in files:
            ident_set_of[f["path"]] = set_id
        if len(files) >= 2 and _is_cross_folder(files):
            identical_groups.append({"category": "IDENTICAL", "files": files})

    def similar_groups(raw, category):
        out = []
        for group in _iter_similar_groups(raw):
            files = [f for f in (_normalize_file(e, folder_a, folder_b) for e in group) if f]
            # Collapse byte-identical copies so they aren't re-reported as similar.
            files = _dedupe_identical(files, ident_set_of)
            if len(files) >= 2 and _is_cross_folder(files):
                out.append({"category": category, "files": files})
        return out

    image_groups = similar_groups(img_json, "SIMILAR_IMAGE")
    video_groups = similar_groups(vid_json, "SIMILAR_VIDEO")

    # Split noisy similar-video clusters by duration and add real resolution.
    video_groups = _refine_similar_videos(video_groups)

    return identical_groups + image_groups + video_groups
