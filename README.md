<p align="center">
  <img src="assets/icon.ico" width="96" height="96" alt="ScreenCanvas icon">
</p>

<h1 align="center">ScreenCanvas</h1>

<p align="center">
  Share two (or more) monitors as a single window in Discord, Zoom, or Teams.
</p>

<p align="center">
  <img src="https://github.com/0xramm/3rdScreen/actions/workflows/build.yml/badge.svg" alt="Build status">
</p>

## Why

Most meeting apps only let you share one screen at a time. ScreenCanvas composites
any number of your monitors into one borderless window, laid out however you like,
so you can share that single window and have everyone see all your screens at once.

## Features

- Detects every connected display (by its real Windows display name).
- Drag-and-drop canvas to arrange and resize each monitor's feed.
- Set an exact output resolution — the canvas and the shared window both adapt to it.
- Adding/removing a source re-tiles the layout to fill the canvas automatically.
- Settings (output size, source layout) persist next to the exe between runs.
- The shared window is a real top-level window (not a tool window), so it shows up
  in Discord/Zoom/Teams' "Application Window" share picker — and it won't freeze
  if you alt-tab away or it gets minimized.

## Setup (run from source)

```
pip install -r requirements.txt
python app.py
```

## Build the exe

```
build.bat
```

This runs PyInstaller and produces `dist\ScreenCanvas.exe` (icon embedded, single file).

GitHub Actions also builds it automatically on every push to `main` — grab the exe
from the latest run's **Artifacts** under the Actions tab.

## Usage

1. Click **+ Add Source** and pick a display — it's added to the canvas.
2. Drag boxes to move them, drag the corner handle to resize, or type an exact
   width/height in the Properties panel.
3. Set the output resolution under Output Size if you want something other than
   1920×1080.
4. Click **Start shared view** — a borderless window titled "ScreenCanvas Output"
   opens. Share *that* window in your meeting app.
5. Press `Esc` (focus the output window) or click **Stop shared view** to end it.

## Settings file

`screencanvas_settings.json` is written next to the exe (or next to `app.py` when
run from source) and reloaded automatically on the next launch.
