# 💧 Waterdrop

A tiny local app to **find and remove duplicate photos & videos between two
folders** — even when the duplicates have different file names.

It detects three kinds of duplicates:

| Kind | What it finds | Confidence |
|------|---------------|------------|
| **Identical** | Byte-for-byte identical files | 100% certain |
| **Similar images** | Photos resized / re-compressed / different quality | perceptual match |
| **Similar videos** | The same clip re-encoded or at a different resolution | frame match |

You pick the two folders, run a scan, see the duplicates **side by side**, and
delete the copy you don't want from either folder — by default it goes to the
**Trash** (recoverable).

Everything runs locally in your browser, served by a small Python web server.
No data ever leaves your machine.

## Requirements

- **Python 3.8+**
- **czkawka** (`czkawka_cli`) — the duplicate-detection engine
- **ffmpeg** (provides `ffprobe`) — thumbnails and media info

### Install the tools

**macOS** (with [Homebrew](https://brew.sh)):
```bash
brew install czkawka ffmpeg
```

**Windows** (with [winget](https://learn.microsoft.com/windows/package-manager/)):
```powershell
winget install czkawka.czkawka
winget install Gyan.FFmpeg
```
(Python: install from the Microsoft Store or [python.org](https://python.org).)

**Linux** (Debian/Ubuntu):
```bash
sudo apt install ffmpeg
# czkawka: install the CLI from https://github.com/qarmin/czkawka/releases
#          (or your distro's package / cargo install czkawka_cli)
```

### Install Waterdrop's Python dependency

```bash
pip install -r requirements.txt
```

This installs `send2trash` (a cross-platform Trash). It's optional — on macOS
and Linux Waterdrop has a built-in Trash fallback, and permanent delete always
works — but recommended, and required for the Trash on Windows.

## Run

**Double-click the launcher** for your system:

| OS | Launcher |
|----|----------|
| macOS | `start.command` |
| Windows | `start.bat` |
| Linux | `start.sh` |

…or from a terminal, on any OS:

```bash
python3 launch.py
```

The app opens in your browser automatically. To run just the server without
opening a browser: `python3 server.py`, then open the printed URL.

> macOS first launch: if it blocks `start.command`, right-click it → **Open**,
> or run `chmod +x start.command start.sh` once.

## How to use

1. **Browse…** next to *Folder 1* and *Folder 2* to choose the two folders
   (or just type/paste a path into the field).
2. Optionally tweak **Image similarity** (0–40, lower = stricter) and
   **Video tolerance** (0–20, lower = stricter).
3. **Start scan**. Progress runs through identical → similar images → similar videos.
4. Browse the results by tab. Click any preview to enlarge it (videos play in place).
5. Press **🗑 Delete this** under the copy you want to remove.

### Safety

- By default deleted files are **moved to the Trash** (recoverable).
- Toggle **Delete permanently** only if you're sure.
- The app **never deletes the last remaining copy** of a group.
- It can only touch files inside the two folders you selected.

## Supported platforms

Waterdrop runs on **macOS, Windows and Linux**. All OS-specific behaviour
(folder picker, thumbnails, media info, Trash) lives in `platform_tools.py`,
with graceful fallbacks:

- **Folder picker**: native dialog per OS (osascript / PowerShell / zenity);
  if none is available, just type the path in the field.
- **Trash**: `send2trash` everywhere, with a built-in fallback on macOS/Linux.
- **Thumbnails / info**: generated with `ffmpeg`/`ffprobe` (cross-platform).

> Note: HEIC/HEIF thumbnails depend on your `ffmpeg` build supporting them.

## Project layout

```
waterdrop/
  launch.py          # cross-platform launcher (starts server + opens browser)
  server.py          # local HTTP server: scan jobs, media, delete
  scanner.py         # drives czkawka_cli and normalizes results into pairs
  platform_tools.py  # OS-specific bits: folder picker, thumbnails, info, Trash
  static/            # the web UI (index.html, style.css, app.js)
  start.command/.sh/.bat   # double-click launchers per OS
```

## License

[MIT](LICENSE) © 2026 Stefano Caldarini
