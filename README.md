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

## Requirements

macOS, plus two command-line tools:

```bash
brew install czkawka ffmpeg
```

Everything else uses what's already on the Mac (Python 3, `osascript` for the
native folder picker, `qlmanage` for thumbnails). No `pip install`, no Node.

## Run

Double-click **`start.command`**, or from a terminal:

```bash
python3 server.py
```

Then open the printed URL (it opens automatically when launched via
`start.command`).

> First launch: if macOS blocks `start.command`, right-click it → **Open**, or run
> `chmod +x start.command` once.

## How to use

1. **Browse…** next to *Folder 1* and *Folder 2* to choose the two folders.
2. Optionally tweak **Image similarity** (0–40, lower = stricter) and
   **Video tolerance** (0–20, lower = stricter).
3. **Start scan**. Progress runs through identical → similar images → similar videos.
4. Browse the results by tab. Click any preview to enlarge it (videos play in place).
5. Press **🗑 Delete this** under the copy you want to remove.

### Safety

- By default deleted files are **moved to the macOS Trash** (recoverable).
- Toggle **Delete permanently** only if you're sure.
- The app **never deletes the last remaining copy** of a group.
- It can only touch files inside the two folders you selected.

## Project layout

```
waterdrop/
  server.py        # local HTTP server: folder picker, scan jobs, media, delete
  scanner.py       # drives czkawka_cli and normalizes results into pairs
  static/          # the web UI (index.html, style.css, app.js)
  start.command    # double-click launcher
```

The command-line version of the same logic lives in `~/Desktop/trova-duplicati.sh`.
