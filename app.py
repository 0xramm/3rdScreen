"""3rdScreen — compose multiple monitors into one borderless window
so it can be shared as a single screen in a meeting app."""
import ctypes
import json
import math
import os
import sys
import tkinter as tk
from tkinter import ttk

import mss
from PIL import Image, ImageTk

DEFAULT_OUTPUT_W, DEFAULT_OUTPUT_H = 1920, 1080
EDITOR_MAX_W, EDITOR_MAX_H = 760, 430
MIN_W, MIN_H = 160, 90
FPS_MS = 33
SETTINGS_FILE = "screencanvas_settings.json"
ICON_REL_PATH = "assets/icon.ico"

PALETTE = ["#4f8cff", "#ff6b6b", "#51cf66", "#ffd43b", "#cc5de8", "#22d3ee"]

BG = "#15161c"
PANEL = "#1c1e27"
PANEL2 = "#23252f"
TEXT = "#e8e8ef"
MUTED = "#8a8d9a"
ACCENT = "#4f8cff"


def clamp(v, lo, hi):
    return max(lo, min(v, hi))


def disable_power_throttling():
    """Opt this process out of Windows' background power throttling (EcoQoS).

    Without this, Windows slows our render-loop timer to a crawl (~8fps instead
    of 30) as soon as the window loses foreground focus, since it treats us like
    any other backgrounded app. A screen-sharing tool needs to keep rendering at
    full rate while unfocused, so we explicitly disable that throttling.
    """
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32

        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_ulong),
                        ("ControlMask", ctypes.c_ulong),
                        ("StateMask", ctypes.c_ulong)]

        PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
        PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
        state = PROCESS_POWER_THROTTLING_STATE(
            Version=1, ControlMask=PROCESS_POWER_THROTTLING_EXECUTION_SPEED, StateMask=0)
        kernel32.SetProcessInformation(
            kernel32.GetCurrentProcess(), PROCESS_POWER_THROTTLING,
            ctypes.byref(state), ctypes.sizeof(state))
    except Exception:
        pass


def app_dir():
    """Directory the running exe lives in (or this script's dir, in dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative):
    """Bundled data file location — PyInstaller extracts --add-data under _MEIPASS."""
    base = getattr(sys, "_MEIPASS", app_dir())
    return os.path.join(base, relative)


def settings_path():
    return os.path.join(app_dir(), SETTINGS_FILE)


def compute_grid_layout(output_w, output_h, count):
    """Tile `count` cells gap-free across (output_w, output_h) in reading order."""
    if count <= 0:
        return []
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    cell_w = output_w / cols
    cell_h = output_h / rows
    rects = []
    for idx in range(count):
        col, row = idx % cols, idx // cols
        x = int(round(col * cell_w))
        y = int(round(row * cell_h))
        w = (output_w - x) if col == cols - 1 else int(round((col + 1) * cell_w)) - x
        h = (output_h - y) if row == rows - 1 else int(round((row + 1) * cell_h)) - y
        rects.append((x, y, w, h))
    return rects


def serialize_state(output_w, output_h, sources):
    return {
        "output_w": output_w,
        "output_h": output_h,
        "sources": [
            {"name": s.name, "mon_info": s.mon_info, "x": s.x, "y": s.y, "w": s.w, "h": s.h}
            for s in sources
        ],
    }


GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE | NOMOVE | NOZORDER | FRAMECHANGED


def strip_window_chrome(hwnd):
    """Remove the title bar/border via Win32 styles instead of overrideredirect.

    overrideredirect() marks the window WS_EX_TOOLWINDOW on Windows, which hides it
    from Alt-Tab and from screen-share window pickers (Discord/Zoom/Teams). Clearing
    the caption/frame styles on a normal top-level window keeps it borderless while
    staying a regular, shareable application window.
    """
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT), ("rcWork", _RECT),
                ("dwFlags", ctypes.c_ulong), ("szDevice", ctypes.c_wchar * 32)]


def display_names_for(monitors):
    """Match mss monitor rects to Windows display device names (e.g. 'Display 1')."""
    names = [f"Display {i + 1}" for i in range(len(monitors))]
    if sys.platform != "win32":
        return names
    try:
        infos = []
        proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.POINTER(_RECT), ctypes.c_ssize_t)

        def _cb(hmonitor, hdc, lprect, lparam):
            info = _MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
            ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))
            infos.append(info)
            return 1

        ctypes.windll.user32.EnumDisplayMonitors(0, 0, proc_t(_cb), 0)

        for i, mon in enumerate(monitors):
            for info in infos:
                r = info.rcMonitor
                if (r.left, r.top, r.right - r.left, r.bottom - r.top) == (
                        mon["left"], mon["top"], mon["width"], mon["height"]):
                    label = info.szDevice.replace(r"\\.\DISPLAY", "Display ")
                    if info.dwFlags & 1:
                        label += " (Primary)"
                    names[i] = label
                    break
    except Exception:
        pass
    return names


class Source:
    _next_id = 0

    def __init__(self, name, mon_info, x, y, w, h):
        self.id = Source._next_id
        Source._next_id += 1
        self.name = name
        self.mon_info = mon_info
        self.x, self.y, self.w, self.h = x, y, w, h
        self.color = PALETTE[self.id % len(PALETTE)]
        self.rect_id = None
        self.label_id = None
        self.handle_id = None


class App:
    def __init__(self):
        disable_power_throttling()
        self.root = tk.Tk()
        self.root.title("3rdScreen")
        self.root.configure(bg=BG)
        self.root.geometry("1000x660")
        self.root.minsize(880, 580)
        self._set_icon(self.root)

        self.sct = mss.MSS()
        self.monitors = self.sct.monitors[1:]  # [0] is the virtual combined monitor
        self.display_names = display_names_for(self.monitors)

        saved = self._load_settings()
        self.output_w = saved["output_w"] if saved else DEFAULT_OUTPUT_W
        self.output_h = saved["output_h"] if saved else DEFAULT_OUTPUT_H
        self.editor_scale = self._compute_editor_scale()

        self.sources = []
        self.selected = None
        self._drag_start = None
        self._drag_orig = None

        self.output_win = None
        self.output_sct = None
        self.output_label = None
        self.output_photo = None
        self.running = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._restore_sources(saved)

    def _set_icon(self, window):
        try:
            window.iconbitmap(resource_path(ICON_REL_PATH))
        except Exception:
            pass

    def _load_settings(self):
        try:
            with open(settings_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_settings(self):
        try:
            data = serialize_state(self.output_w, self.output_h, self.sources)
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _restore_sources(self, saved):
        if not saved:
            return
        for d in saved.get("sources", []):
            src = Source(d["name"], d["mon_info"], d["x"], d["y"], d["w"], d["h"])
            self.sources.append(src)
            self._draw_source(src)
        if self.sources:
            self._select(self.sources[0])
        self._update_status()

    # ---------- UI ----------
    def _build_ui(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TButton", background=PANEL2, foreground=TEXT, borderwidth=0,
                         padding=8, font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#2d3040")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                         padding=10, font=("Segoe UI", 11, "bold"))
        style.map("Accent.TButton", background=[("active", "#3f78e0")])
        style.configure("Stop.TButton", background="#e03131", foreground="white",
                         padding=10, font=("Segoe UI", 11, "bold"))
        style.map("Stop.TButton", background=[("active", "#c92a2a")])
        style.configure("Accent.TMenubutton", background=ACCENT, foreground="white",
                         padding=10, font=("Segoe UI", 11, "bold"))
        style.map("Accent.TMenubutton", background=[("active", "#3f78e0")])

        root_frame = tk.Frame(self.root, bg=BG)
        root_frame.pack(fill="both", expand=True, padx=16, pady=16)

        # Sidebar
        sidebar = tk.Frame(root_frame, bg=PANEL, width=230)
        sidebar.pack(side="left", fill="y", padx=(0, 16))
        sidebar.pack_propagate(False)

        add_btn = ttk.Menubutton(sidebar, text="+  Add Source", style="Accent.TMenubutton")
        add_menu = tk.Menu(add_btn, tearoff=0, bg=PANEL2, fg=TEXT,
                            activebackground=ACCENT, activeforeground="white",
                            font=("Segoe UI", 10))
        for i, mon in enumerate(self.monitors):
            name = self.display_names[i]
            add_menu.add_command(
                label=f"+  {name}   ({mon['width']}×{mon['height']})",
                command=lambda n=name, m=mon: self.add_source(n, m))
        add_btn["menu"] = add_menu
        add_btn.pack(fill="x", padx=14, pady=(14, 10))

        tk.Label(sidebar, text="OUTPUT SIZE", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(10, 6))
        size_row = tk.Frame(sidebar, bg=PANEL)
        size_row.pack(fill="x", padx=14)
        self.width_var = tk.StringVar(value=str(self.output_w))
        self.height_var = tk.StringVar(value=str(self.output_h))
        w_entry = tk.Entry(size_row, textvariable=self.width_var, width=6,
                            bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat")
        w_entry.pack(side="left", ipady=4)
        tk.Label(size_row, text="×", bg=PANEL, fg=MUTED).pack(side="left", padx=4)
        h_entry = tk.Entry(size_row, textvariable=self.height_var, width=6,
                            bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat")
        h_entry.pack(side="left", ipady=4)
        ttk.Button(sidebar, text="Apply size",
                   command=self.apply_canvas_size).pack(fill="x", padx=14, pady=10)

        tk.Label(sidebar, text="PROPERTIES", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(10, 6))
        self.prop_name_label = tk.Label(sidebar, text="No selection — click a box on the canvas",
                                         bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                                         wraplength=190, justify="left")
        self.prop_name_label.pack(anchor="w", padx=14)

        prop_row = tk.Frame(sidebar, bg=PANEL)
        prop_row.pack(fill="x", padx=14, pady=(8, 0))
        self.prop_w_var = tk.StringVar()
        self.prop_h_var = tk.StringVar()
        tk.Entry(prop_row, textvariable=self.prop_w_var, width=6,
                  bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat").pack(side="left", ipady=4)
        tk.Label(prop_row, text="×", bg=PANEL, fg=MUTED).pack(side="left", padx=4)
        tk.Entry(prop_row, textvariable=self.prop_h_var, width=6,
                  bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat").pack(side="left", ipady=4)
        ttk.Button(sidebar, text="Apply size",
                   command=self.apply_source_size).pack(fill="x", padx=14, pady=10)
        ttk.Button(sidebar, text="Remove selected",
                   command=self.remove_selected).pack(fill="x", padx=14)

        # Main area
        main = tk.Frame(root_frame, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        tk.Label(main, text="Layout canvas", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(main, text="Drag a box to move it, drag its corner handle to resize. "
                            "This is exactly how the shared window will look.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 12))

        cw, ch = int(self.output_w * self.editor_scale), int(self.output_h * self.editor_scale)
        canvas_wrap = tk.Frame(main, bg=BG)
        canvas_wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_wrap, width=cw, height=ch, bg="#0b0c10",
                                 highlightthickness=1, highlightbackground="#33364a")
        self.canvas.pack(anchor="n", pady=4)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.save_settings())

        self.root.bind("<Delete>", lambda e: self.remove_selected())

        bottom = tk.Frame(main, bg=BG)
        bottom.pack(fill="x", pady=(16, 0))
        self.status_label = tk.Label(bottom, text="Add at least one display to start",
                                      bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.status_label.pack(side="left")
        self.start_btn = ttk.Button(bottom, text="▶  Start shared view",
                                     style="Accent.TButton", command=self.toggle_output)
        self.start_btn.pack(side="right")

    # ---------- canvas / output size ----------
    def _compute_editor_scale(self):
        return min(EDITOR_MAX_W / self.output_w, EDITOR_MAX_H / self.output_h)

    def apply_canvas_size(self):
        if self.running:
            self.status_label.configure(text="Stop the shared view before changing output size")
            return
        try:
            new_w = int(self.width_var.get())
            new_h = int(self.height_var.get())
        except ValueError:
            return
        new_w = int(clamp(new_w, 320, 7680))
        new_h = int(clamp(new_h, 240, 4320))
        self.width_var.set(str(new_w))
        self.height_var.set(str(new_h))

        sx, sy = new_w / self.output_w, new_h / self.output_h
        self.output_w, self.output_h = new_w, new_h
        self.editor_scale = self._compute_editor_scale()

        for src in self.sources:
            src.x = int(clamp(src.x * sx, 0, self.output_w - MIN_W))
            src.y = int(clamp(src.y * sy, 0, self.output_h - MIN_H))
            src.w = int(clamp(src.w * sx, MIN_W, self.output_w - src.x))
            src.h = int(clamp(src.h * sy, MIN_H, self.output_h - src.y))

        cw, ch = int(self.output_w * self.editor_scale), int(self.output_h * self.editor_scale)
        self.canvas.configure(width=cw, height=ch)
        for src in self.sources:
            self._redraw_source(src)
        self.save_settings()

    def _auto_layout(self):
        """Re-tile every source to fill the canvas edge-to-edge."""
        rects = compute_grid_layout(self.output_w, self.output_h, len(self.sources))
        for src, (x, y, w, h) in zip(self.sources, rects):
            src.x, src.y, src.w, src.h = x, y, w, h
            self._redraw_source(src)

    # ---------- source management ----------
    def add_source(self, name, mon_info):
        src = Source(name, mon_info, 0, 0, self.output_w, self.output_h)
        self.sources.append(src)
        self._draw_source(src)
        self._auto_layout()
        self._select(src)
        self._update_status()
        self.save_settings()

    def _draw_source(self, src):
        tag_rect = f"rect{src.id}"
        tag_handle = f"handle{src.id}"
        cx, cy, cw, ch = self._to_canvas_rect(src)
        src.rect_id = self.canvas.create_rectangle(
            cx, cy, cx + cw, cy + ch, fill=src.color, stipple="gray25",
            outline=src.color, width=2, tags=(tag_rect,))
        src.label_id = self.canvas.create_text(
            cx + cw / 2, cy + ch / 2, text=self._label_text(src),
            fill="white", font=("Segoe UI", 10, "bold"), tags=(tag_rect,))
        hs = 14
        src.handle_id = self.canvas.create_rectangle(
            cx + cw - hs, cy + ch - hs, cx + cw, cy + ch,
            fill="white", outline=src.color, width=2, tags=(tag_handle,))

        self.canvas.tag_bind(tag_rect, "<ButtonPress-1>", lambda e, s=src: self._start_move(e, s))
        self.canvas.tag_bind(tag_rect, "<B1-Motion>", lambda e, s=src: self._do_move(e, s))
        self.canvas.tag_bind(tag_handle, "<ButtonPress-1>", lambda e, s=src: self._start_resize(e, s))
        self.canvas.tag_bind(tag_handle, "<B1-Motion>", lambda e, s=src: self._do_resize(e, s))

    def _label_text(self, src):
        return f"{src.name}\n{src.w}×{src.h}"

    def _to_canvas_rect(self, src):
        return (src.x * self.editor_scale, src.y * self.editor_scale,
                src.w * self.editor_scale, src.h * self.editor_scale)

    def _redraw_source(self, src):
        cx, cy, cw, ch = self._to_canvas_rect(src)
        hs = 14
        self.canvas.coords(src.rect_id, cx, cy, cx + cw, cy + ch)
        self.canvas.coords(src.label_id, cx + cw / 2, cy + ch / 2)
        self.canvas.itemconfig(src.label_id, text=self._label_text(src))
        self.canvas.coords(src.handle_id, cx + cw - hs, cy + ch - hs, cx + cw, cy + ch)
        width = 3 if src is self.selected else 2
        self.canvas.itemconfig(src.rect_id, width=width)

    def _select(self, src):
        self.selected = src
        for s in self.sources:
            self.canvas.itemconfig(s.rect_id, width=3 if s is src else 2)
        self.prop_name_label.configure(text=f"{src.name} — at ({src.x},{src.y})")
        self.prop_w_var.set(str(src.w))
        self.prop_h_var.set(str(src.h))

    def apply_source_size(self):
        src = self.selected
        if not src:
            return
        try:
            w = int(self.prop_w_var.get())
            h = int(self.prop_h_var.get())
        except ValueError:
            return
        src.w = int(clamp(w, MIN_W, self.output_w - src.x))
        src.h = int(clamp(h, MIN_H, self.output_h - src.y))
        self.prop_w_var.set(str(src.w))
        self.prop_h_var.set(str(src.h))
        self._redraw_source(src)
        self.save_settings()

    def remove_selected(self):
        src = self.selected
        if not src:
            return
        self.canvas.delete(f"rect{src.id}")
        self.canvas.delete(f"handle{src.id}")
        self.sources.remove(src)
        self.selected = None
        self.prop_name_label.configure(text="No selection — click a box on the canvas")
        self.prop_w_var.set("")
        self.prop_h_var.set("")
        self._auto_layout()
        self._update_status()
        self.save_settings()

    # ---------- drag / resize ----------
    def _start_move(self, event, src):
        self._select(src)
        self._drag_start = (event.x, event.y)
        self._drag_orig = (src.x, src.y)

    def _do_move(self, event, src):
        if self._drag_start is None:
            return
        dx = (event.x - self._drag_start[0]) / self.editor_scale
        dy = (event.y - self._drag_start[1]) / self.editor_scale
        ox, oy = self._drag_orig
        src.x = int(clamp(ox + dx, 0, self.output_w - src.w))
        src.y = int(clamp(oy + dy, 0, self.output_h - src.h))
        self._redraw_source(src)
        self.prop_name_label.configure(text=f"{src.name} — at ({src.x},{src.y})")

    def _start_resize(self, event, src):
        self._select(src)
        self._drag_start = (event.x, event.y)
        self._drag_orig = (src.w, src.h)

    def _do_resize(self, event, src):
        if self._drag_start is None:
            return
        dx = (event.x - self._drag_start[0]) / self.editor_scale
        dy = (event.y - self._drag_start[1]) / self.editor_scale
        ow, oh = self._drag_orig
        src.w = int(clamp(ow + dx, MIN_W, self.output_w - src.x))
        src.h = int(clamp(oh + dy, MIN_H, self.output_h - src.y))
        self._redraw_source(src)
        self.prop_name_label.configure(text=f"{src.name} — at ({src.x},{src.y})")
        self.prop_w_var.set(str(src.w))
        self.prop_h_var.set(str(src.h))

    def _update_status(self):
        if not self.sources:
            self.status_label.configure(text="Add at least one display to start")
        else:
            self.status_label.configure(
                text=f"{len(self.sources)} source(s) on canvas — ready to share")

    # ---------- borderless shared output ----------
    def toggle_output(self):
        if self.running:
            self.stop_output()
        elif self.sources:
            self.start_output()

    def start_output(self):
        self.output_win = tk.Toplevel(self.root)
        self.output_win.title("3rdScreen Output")
        self.output_win.geometry(f"{self.output_w}x{self.output_h}+60+60")
        self.output_win.configure(bg="black")
        self._set_icon(self.output_win)
        self.output_win.update_idletasks()
        strip_window_chrome(self.output_win.winfo_id())

        self.output_label = tk.Label(self.output_win, bg="black")
        self.output_label.pack(fill="both", expand=True)
        self.output_label.bind("<ButtonPress-1>", self._out_drag_start)
        self.output_label.bind("<B1-Motion>", self._out_drag_move)
        self.output_win.bind("<Escape>", lambda e: self.stop_output())
        # Windows' screen-share capture freezes a window's shared frame while it's
        # minimized, so bounce it straight back to restored (behind other windows,
        # not on top of them) instead of letting it sit minimized.
        self.output_win.bind("<Unmap>", self._on_output_unmap)
        self.output_win.focus_force()

        self.output_sct = mss.MSS()
        self.running = True
        self.start_btn.configure(text="■  Stop shared view", style="Stop.TButton")
        self.status_label.configure(text="Shared view running — share this window in your meeting app (Esc to stop)")
        self._render_loop()

    def _on_output_unmap(self, event):
        if event.widget is self.output_win and self.output_win.state() == "iconic":
            self.output_win.after(10, self._unminimize_output)

    def _unminimize_output(self):
        if self.output_win:
            self.output_win.deiconify()
            self.output_win.lower()

    def _out_drag_start(self, event):
        self._out_drag = (event.x, event.y)

    def _out_drag_move(self, event):
        dx = event.x - self._out_drag[0]
        dy = event.y - self._out_drag[1]
        x = self.output_win.winfo_x() + dx
        y = self.output_win.winfo_y() + dy
        self.output_win.geometry(f"+{x}+{y}")

    def _render_loop(self):
        if not self.running:
            return
        base = Image.new("RGB", (self.output_w, self.output_h), "black")
        for src in self.sources:
            try:
                shot = self.output_sct.grab(src.mon_info)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                img = img.resize((src.w, src.h), Image.BILINEAR)
                base.paste(img, (src.x, src.y))
            except Exception:
                pass
        self.output_photo = ImageTk.PhotoImage(base)
        self.output_label.configure(image=self.output_photo)
        self.output_win.after(FPS_MS, self._render_loop)

    def stop_output(self):
        self.running = False
        if self.output_sct:
            self.output_sct.close()
            self.output_sct = None
        if self.output_win:
            self.output_win.destroy()
            self.output_win = None
        self.start_btn.configure(text="▶  Start shared view", style="Accent.TButton")
        self._update_status()

    def on_close(self):
        self.stop_output()
        self.sct.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
