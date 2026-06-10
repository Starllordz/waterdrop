#!/usr/bin/env python3
"""
Waterdrop launcher — cross-platform (macOS, Windows, Linux).

Starts the local server, waits for it to announce its URL, opens it in a browser
(a dedicated Chrome/Edge app window when available, otherwise the default
browser), and keeps running until the server stops or you press Ctrl+C.
"""

import os
import shutil
import subprocess
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))

# True when running inside a packaged standalone build (PyInstaller). In that
# case there is no separate `python` to spawn server.py with, so we run the
# server in-process instead.
FROZEN = getattr(sys, "frozen", False)


def open_browser(url):
    """Open `url`, preferring a chromeless app window of a chromium browser."""
    candidates = []
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            app_path = f"/Applications/{app}.app"
            if os.path.isdir(app_path):
                # `open -na <app> --args --app=URL` launches a dedicated window.
                if subprocess.run(["open", "-na", app, "--args", f"--app={url}",
                                   "--new-window"]).returncode == 0:
                    return
    elif os.name == "nt":
        prog = os.environ.get("ProgramFiles", r"C:\Program Files")
        progx = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates = [
            os.path.join(prog, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(progx, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(prog, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(progx, r"Microsoft\Edge\Application\msedge.exe"),
        ]
    else:  # Linux / other Unix
        candidates = [shutil.which(b) for b in
                      ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]

    for exe in candidates:
        if exe and os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--new-window"])
                return
            except OSError:
                pass

    webbrowser.open(url)


def run_in_process():
    """Standalone mode: start the server in a thread and open the browser.

    Used when packaged (FROZEN), where there is no external Python interpreter
    to launch server.py as a subprocess.
    """
    import server
    from http.server import ThreadingHTTPServer

    port = int(os.environ.get("WATERDROP_PORT") or server.find_free_port())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    open_browser(url)
    print(f"\n💧 Waterdrop is running at {url}")
    print("Close this window (or press Ctrl+C) to stop the app.")
    try:
        threading.Event().wait()  # block until interrupted
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


def _make_stdout_utf8():
    """Avoid UnicodeEncodeError when printing non-ASCII on a Windows console.

    A redirected stdout (or the cp1252 console) can't encode characters like the
    💧 banner; reconfigure to UTF-8 and replace anything that still won't fit.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    _make_stdout_utf8()
    if FROZEN:
        return run_in_process()

    server = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py")],
        cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    url = None
    try:
        # Read server output until it announces its URL (or dies).
        for line in server.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if line.startswith("WATERDROP_URL="):
                url = line.split("=", 1)[1].strip()
                break
        if url:
            open_browser(url)
            print(f"\n💧 Waterdrop is running at {url}")
            print("Close this window (or press Ctrl+C) to stop the app.")
        # Keep streaming server output until it exits.
        for line in server.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    main()
