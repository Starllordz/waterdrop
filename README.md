# 💧 Waterdrop

A tiny local app to **find and remove duplicate photos & videos between two
folders** — even when the duplicates have different file names, sizes, or
resolutions.

You pick two folders, run a scan, see the duplicates **side by side**, and
delete the copies you don't want. By default deleted files go to the **Trash**
(recoverable). Everything runs locally in your browser, served by a small Python
web server — **no data ever leaves your machine**.

It detects three kinds of duplicates:

| Kind | What it finds | Confidence |
|------|---------------|------------|
| **Identical** | Byte-for-byte identical files | 100% certain |
| **Similar images** | Photos resized / re-compressed / saved at a different quality | perceptual match |
| **Similar videos** | The same clip re-encoded or at a different resolution | frame match |

Only duplicates that span **both** folders are reported — Waterdrop is built for
deduplicating *across* two locations (e.g. an old backup vs. your library), not
within a single folder.

---

## Contents

- [Get Waterdrop](#get-waterdrop)
- [Quick start (standalone app)](#quick-start-standalone-app)
- [Running from source](#running-from-source)
- [Using Waterdrop](#using-waterdrop)
- [Tuning the scan](#tuning-the-scan)
- [Safety](#safety)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Building the standalone app](#building-the-standalone-app)
- [License](#license)

---

## Get Waterdrop

There are two ways to run it:

| | Standalone app | From source |
|--|----------------|-------------|
| **Install anything?** | No — Python, `ffmpeg`/`ffprobe` and `czkawka_cli` are all bundled | Yes — you install the tools yourself |
| **Download size** | ~150 MB (per OS) | A few hundred KB |
| **Best for** | End users who just want to run it | Developers, or anyone who already has the tools |
| **Get it** | [Quick start](#quick-start-standalone-app) | [Running from source](#running-from-source) |

---

## Quick start (standalone app)

1. Download the build for your operating system from the
   [**Releases**](../../releases) page (or, for an unreleased commit, from the
   **Build standalone** workflow's artifacts under the
   [Actions](../../actions) tab).
2. Unzip it anywhere.
3. Launch it:

   | OS | How to launch |
   |----|---------------|
   | **macOS** | Open the unzipped folder and run **`Waterdrop`**. The first time, **right-click → Open** to get past Gatekeeper (see [Troubleshooting](#troubleshooting)). |
   | **Windows** | Open the unzipped folder and run **`Waterdrop.exe`**. If SmartScreen warns, click **More info → Run anyway**. |
   | **Linux** | Run **`./Waterdrop`** from the unzipped folder. |

Waterdrop opens automatically in your browser. To stop it, close the terminal
window it opened (or press `Ctrl+C` there).

> The standalone app bundles everything it needs — there is nothing else to
> install. Jump straight to [Using Waterdrop](#using-waterdrop).

---

## Running from source

Lighter to download, but you provide the external tools yourself.

### 1. Requirements

- **Python 3.8+**
- **czkawka** (`czkawka_cli`) — the duplicate-detection engine
- **ffmpeg** (provides `ffprobe`) — thumbnails and media info

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

### 2. Install Waterdrop's Python dependency

```bash
pip install -r requirements.txt
```

This installs `send2trash` (a cross-platform Trash). It's optional — on macOS
and Linux Waterdrop has a built-in Trash fallback, and permanent delete always
works — but recommended, and **required for the Trash on Windows**.

### 3. Run

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

> **Tip:** if you have the bundled binaries in a local `bin/` folder (see
> [Building the standalone app](#building-the-standalone-app)), Waterdrop uses
> those automatically — handy for running from source without a system-wide
> install.

---

## Using Waterdrop

### 1. Choose the two folders

Next to **Folder 1** and **Folder 2**, click **Browse** to pick a folder with
the native dialog, or simply **type/paste a path** into the field (this always
works, even where no folder dialog is available). **Start scan** lights up once
both folders are set.

### 2. Start the scan

Click **Start scan**. A progress bar runs through three passes:
**identical files → similar images → similar videos**. Large folders take a
while — most of the time is czkawka hashing and comparing your media.

### 3. Read the results

Results are grouped into **duplicate groups** (usually a pair, sometimes 3+
copies). At the top you'll see:

- A **summary**: how many groups, how many are *identical* vs *similar*, and the
  approximate space you'd reclaim (`~X recoverable` — the size of every copy
  except the one kept in each group).
- **Tabs** — **Photos** and **Videos** — with a count on each. Switch between
  them to review each media type.

Each **card** shows the duplicate copies next to each other:

- A badge tells you the match type: **100% identical** (exact byte-for-byte
  duplicate) or **similar** (looks the same — resized / re-encoded).
- Under each preview: the **folder it lives in** (chip **A**/**B** + folder
  name), file name, size, resolution, duration/bitrate (video) or megapixels
  (photo).
- When both copies have metadata, Waterdrop labels which is **higher quality**,
  **lower quality**, or **same quality** — so you can keep the best one.
- **Click any preview** to open it full-size in a lightbox; videos play in
  place. Press **Esc**, click the ✕, or click outside to close.

### 4. Delete the copies you don't want

You have three ways to delete, from most precise to fastest:

- **One copy** — click **Delete from `<folder>`** under the copy you want to
  remove. The other copy is kept.
- **A whole group** — click **Delete both copies** (or **Delete all N copies**)
  in the card footer to remove every copy in that group.
- **In bulk** — use the **Bulk delete** bar above the grid to clear many groups
  in the current tab at once. Pick:
  - **mode** —
    - **From a folder**: delete the copy on the side you choose (**Folder 1** or
      **Folder 2**), always keeping the copy on the other side.
    - **Keep best quality**: keep the highest-quality copy of each group and
      delete the rest.
  - **what** — **Identical** only, **Similar** only, or **All**.

  The button shows exactly how many files will go and roughly how much space
  that frees, and asks you to confirm first. Cards disappear as the deletion
  progresses.

Whether files go to the Trash or are deleted permanently depends on the
**Delete permanently** toggle in the setup panel (off by default → Trash).

---

## Tuning the scan

Two sliders in the setup panel control how aggressively *similar* (not
identical) media is matched. Lower = stricter (fewer, more confident matches);
higher = looser (more matches, more false positives). Identical-file detection
is exact and unaffected by these.

| Control | Range | Default | What it does |
|---------|-------|---------|--------------|
| **Image similarity** | 0–40 | 12 | Max perceptual-hash distance for two photos to count as similar. Raise it to catch heavier re-compressions; lower it if you see unrelated photos matched. |
| **Video tolerance** | 0–20 | 10 | How loosely video frames may differ. Waterdrop also re-clusters matched videos by **duration** and **aspect ratio** to drop czkawka's noisier matches. |

---

## Safety

Waterdrop is careful about deletion:

- Deleted files go to the **Trash** by default (recoverable). Turn on **Delete
  permanently** only when you're sure.
- It **never deletes the last remaining copy** of a group from the single-copy
  and bulk actions — there's always at least one left. (The explicit *Delete
  both copies* action is the one exception, and it asks first.)
- It can only touch files **inside the two folders you selected** for the
  current scan — every media, thumbnail, and delete request is validated against
  those roots.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| **"czkawka_cli not found"** when starting a scan (source install) | Install czkawka and make sure `czkawka_cli` is on your `PATH`. See [Requirements](#1-requirements). |
| **"ffmpeg/ffprobe not found"** when starting a scan (source install) | Install ffmpeg (it provides `ffprobe`) and make sure both are on your `PATH`. |
| **macOS: "Waterdrop can't be opened"** (standalone) | The bundled binaries are unsigned, so Gatekeeper quarantines the download. **Right-click the app → Open** once, or clear the flag: `xattr -dr com.apple.quarantine /path/to/Waterdrop`. |
| **Windows: SmartScreen warning** (standalone) | The app is unsigned. Click **More info → Run anyway**. |
| **Browse button does nothing** | No native folder dialog is available on your system — just **type or paste** the folder path into the field instead. |
| **Trash toggle is forced on / "Trash not available"** | Your system has no recoverable Trash that Waterdrop can use (most often Windows without `send2trash`). Run `pip install send2trash`, or accept permanent delete. |
| **HEIC/HEIF previews are blank** | Thumbnails depend on your `ffmpeg` build supporting HEIC/HEIF. The bundled builds include broad codec support; a minimal system ffmpeg may not. |
| **Scan is slow** | Most time is czkawka hashing/comparing — expected for large libraries. Similar-video scanning is the heaviest pass. |

---

## How it works

Waterdrop is a small, dependency-light Python web app. All OS-specific behaviour
(folder picker, thumbnails, media info, Trash) lives in `platform_tools.py` with
graceful fallbacks, so the same code runs on **macOS, Windows and Linux**:

- **Folder picker**: native dialog per OS (osascript / PowerShell / zenity /
  kdialog); if none is available, you type the path in the field.
- **Trash**: `send2trash` everywhere, with a built-in fallback on macOS/Linux.
- **Thumbnails / media info**: generated with `ffmpeg`/`ffprobe` (cross-platform
  — works for both images and videos).
- **Duplicate detection**: driven by `czkawka_cli`, whose results are normalized
  into simple cross-folder groups.

External binaries are located by `tools.py`, which looks (in order) inside a
packaged **bundle**, a local **`bin/`** folder, then the system **`PATH`** — so
the exact same code runs packaged, from a `bin/` checkout, or against system
installs.

### Project layout

```
waterdrop/
  launch.py          # cross-platform launcher (starts server + opens browser)
  server.py          # local HTTP server: scan jobs, media, delete
  scanner.py         # drives czkawka_cli and normalizes results into pairs
  platform_tools.py  # OS-specific bits: folder picker, thumbnails, info, Trash
  tools.py           # locates czkawka_cli/ffmpeg/ffprobe (bundle → bin/ → PATH)
  static/            # the web UI (index.html, style.css, app.js)
  start.command/.sh/.bat   # double-click launchers per OS
  scripts/fetch_tools.py   # downloads the bundled binaries for the current OS
  waterdrop.spec     # PyInstaller spec for the standalone build
  tests/smoke.py     # cross-platform smoke test (runs in CI)
```

---

## Building the standalone app

The standalone builds are produced by the **Build standalone** GitHub Actions
workflow (`.github/workflows/build.yml`) for **linux-x86_64**, **macos-arm64**
and **windows-x86_64**. It runs on demand (**workflow_dispatch**, producing a
`0.0.0-dev.<sha>` package as artifacts) and on version tags (`v*`, which also
publishes a **GitHub Release** with the zips attached). Binaries are **not**
stored in the repo — the workflow downloads them per platform at build time.

### Cutting a release

Versioning is driven by the **git tag**. To publish `1.2.3`:

```bash
git tag v1.2.3
git push origin v1.2.3
```

The workflow then stamps `1.2.3` into `version.py` (so the app reports its own
version — shown in the header and on `/api/capabilities`), builds each OS,
names the zips `Waterdrop-<platform>-1.2.3.zip`, and attaches them to a new
release with auto-generated notes. `version.py` in the repo holds the
development default between releases.

To build one locally:

```bash
pip install pyinstaller -r requirements.txt
python scripts/fetch_tools.py     # downloads ffmpeg/ffprobe/czkawka_cli into bin/
pyinstaller waterdrop.spec        # → dist/Waterdrop/  (distribute the whole folder)
```

`scripts/fetch_tools.py` fetches static binaries for the **current OS/arch**:

- **ffmpeg / ffprobe** — [ffmpeg.martin-riedl.de](https://ffmpeg.martin-riedl.de)
  (macOS + Linux, amd64/arm64) and [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds)
  (Windows).
- **czkawka_cli** — pinned release from [qarmin/czkawka](https://github.com/qarmin/czkawka).

To target another platform (e.g. macOS Intel or Linux arm64), add a matching
entry to the workflow matrix in `.github/workflows/build.yml`.

---

## License

[MIT](LICENSE) © 2026 Stefano Caldarini
