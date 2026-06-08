#!/usr/bin/env python3
"""
Waterdrop smoke test — runs on macOS, Windows and Linux in CI.

Validates the cross-platform pieces without requiring czkawka_cli (the scanner
engine), since installing it differs per OS. It checks that:
  - all modules import,
  - ffmpeg/ffprobe are reachable,
  - thumbnails are generated (ffmpeg for video, originals for images),
  - media info is read via ffprobe,
  - the server boots and answers /api/capabilities.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import platform_tools  # noqa: E402
import scanner  # noqa: E402
import server  # noqa: E402  (import side-effect: ensures it loads)
import launch  # noqa: E402

failures = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond:
        failures.append(name)


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def main(tmp):
    check("ffmpeg available", platform_tools.ffmpeg_available())
    check("ffprobe available", platform_tools.ffprobe_available())

    img = os.path.join(tmp, "img.png")
    vid = os.path.join(tmp, "vid.mp4")
    # Generate test media with ffmpeg (lavfi, no input files needed).
    run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:duration=1", "-frames:v", "1",
         "-pix_fmt", "rgb24", img])
    run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=size=640x480:rate=10:duration=2", vid])

    ti, ci = platform_tools.make_thumbnail(img)
    check("image thumbnail returned", bool(ti) and ci is not None)

    tv, cv = platform_tools.make_thumbnail(vid)
    check("video thumbnail generated",
          bool(tv) and os.path.exists(tv) and os.path.getsize(tv) > 0)

    info_i = platform_tools.get_media_info(img)
    check("image dimensions via ffprobe", info_i["width"] == 1280 and info_i["height"] == 720)

    info_v = platform_tools.get_media_info(vid)
    check("video dimensions via ffprobe", info_v["width"] == 640 and info_v["height"] == 480)
    check("video duration via ffprobe", info_v["duration"] > 0)

    check("trash_supported returns a bool", isinstance(platform_tools.trash_supported(), bool))
    check("install_hint non-empty", bool(platform_tools.install_hint()))

    # Boot the server and query its capabilities endpoint.
    env = dict(os.environ, WATERDROP_PORT="8911")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                            cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        booted = False
        for _ in range(50):
            line = proc.stdout.readline()
            if line.startswith("WATERDROP_URL="):
                booted = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        check("server boots and announces URL", booted)
        if booted:
            resp = urllib.request.urlopen("http://127.0.0.1:8911/api/capabilities", timeout=5)
            caps = json.load(resp)
            check("capabilities has 'trash' bool", isinstance(caps.get("trash"), bool))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        main(tmp)
    if failures:
        print(f"\n{len(failures)} check(s) failed:", ", ".join(failures))
        sys.exit(1)
    print("\nAll smoke checks passed.")
