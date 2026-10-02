"""ui.py — the entry point to the HUD.  Mark LVIII "Stark Lab" (simple edition).

A clean Iron-Man J.A.R.V.I.S. interface in PyQt6:

  * Centre  — animated arc-reactor HUD (your avatar, voice waveform, radar).
              Videos, pictures and the live camera appear here too.
  * Right   — Diagnostics: CORE / MEMORY / STORAGE / GPU gauges, network,
              a RUN line that opens any app, file or website, and media keys.
  * Bottom  — comms log and command line.
  * Header  — status, clock, MIC, STOP and a ☰ menu for everything else.

JarvisUI keeps the exact public API main.py and every plugin use (`player`).
Old gui/ names are still re-exported at the bottom, so `from ui import X` works.

Keys:      F11 fullscreen · Esc interrupt · Ctrl+L command line ·
           hold Space (outside the text box) = push-to-talk
"""
from __future__ import annotations

import html
import importlib
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import psutil

# Before any Qt import: Qt's video backend prints signed stream URLs otherwise.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QAction, QColor, QConicalGradient, QFont, QFontDatabase,
                         QKeySequence, QPainter, QPainterPath,
                         QLinearGradient, QPen, QPixmap, QRadialGradient, QShortcut)
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog,
                             QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                             QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QMainWindow, QMenu, QPushButton,
                             QSizePolicy, QStackedWidget,
                             QTextBrowser,
                             QTextEdit, QVBoxLayout, QWidget)

try:
    from PyQt6.QtMultimedia import (QAudioOutput, QCamera, QMediaCaptureSession,
                                    QMediaDevices, QMediaPlayer)
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    HAS_MM = True
except Exception:
    HAS_MM = False

SYSTEM = platform.system()
SETTINGS_PATH = Path.home() / ".jarvis_hud.json"
NO_WINDOW = 0x08000000 if SYSTEM == "Windows" else 0

CYAN, CYAN_DIM, AMBER = "#00E5FF", "#0B6F80", "#FFB547"
RED, GREEN, BG, TEXT = "#FF4D4D", "#3DFFA2", "#02070D", "#A8F3FF"


def qc(hex_: str, alpha: int = 255) -> QColor:
    c = QColor(hex_)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def mono_family() -> str:
    fams = set(QFontDatabase.families())
    for f in ("Share Tech Mono", "Orbitron", "Consolas", "Cascadia Mono",
              "SF Mono", "Menlo", "DejaVu Sans Mono"):
        if f in fams:
            return f
    return "monospace"


STYLE = """
* {{ font-family: '{font}'; font-size: 11px; color: {text}; }}
QMainWindow, #central {{ background: {bg}; }}
QPushButton {{
  background: rgba(0,229,255,0.06); border: 1px solid rgba(0,229,255,0.45);
  color: {cyan}; padding: 6px 12px; letter-spacing: 1px; }}
QPushButton:hover {{ background: rgba(0,229,255,0.18); border-color: {cyan}; }}
QPushButton:pressed {{ background: rgba(0,229,255,0.35); color: #fff; }}
QPushButton:checked {{ background: rgba(255,77,77,0.15); border-color: {red}; color: {red}; }}
QPushButton#danger {{ border-color: rgba(255,77,77,0.6); color: {red}; }}
QPushButton#danger:hover {{ background: rgba(255,77,77,0.2); }}
QPushButton::menu-indicator {{ width: 0; }}
QLineEdit, QComboBox {{
  background: rgba(0,20,30,0.85); border: 1px solid rgba(0,229,255,0.35); padding: 7px; }}
QLineEdit:focus {{ border-color: {cyan}; }}
QTextEdit, QTextBrowser, QTableWidget {{
  background: rgba(0,14,22,0.6); border: 1px solid rgba(0,229,255,0.15);
  selection-background-color: rgba(0,229,255,0.22); selection-color: #fff; }}
QHeaderView::section {{ background: transparent; color: {cyan_dim}; border: none;
  border-bottom: 1px solid rgba(0,229,255,0.25); padding: 4px; }}
QTabWidget::pane {{ border: 1px solid rgba(0,229,255,0.25); background: rgba(3,22,32,0.6); top: -1px; }}
QTabBar::tab {{ background: transparent; color: {cyan_dim}; padding: 8px 20px;
  border: 1px solid rgba(0,229,255,0.15); border-bottom: none; margin-right: 2px; letter-spacing: 2px; }}
QTabBar::tab:selected {{ color: {cyan}; background: rgba(0,229,255,0.12); border-color: {cyan}; }}
QMenu {{ background: #03151f; border: 1px solid {cyan_dim}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; color: {text}; }}
QMenu::item:selected {{ background: rgba(0,229,255,0.2); color: {cyan}; }}
QScrollBar:vertical {{ background: transparent; width: 6px; }}
QScrollBar::handle:vertical {{ background: rgba(0,229,255,0.35); min-height: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QDialog {{ background: #03121b; }}
"""


# ── settings ─────────────────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict = {}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── PC helpers ───────────────────────────────────────────────────────────────
def _popen(cmd, shell=False):
    try:
        return subprocess.Popen(cmd, shell=shell, creationflags=NO_WINDOW,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def launch(target: str) -> bool:
    """Open an app name, a file/folder path or a URL."""
    target = target.strip()
    if not target:
        return False
    if re.match(r"^(https?://|www\.)", target, re.I):
        webbrowser.open(target if "://" in target else "https://" + target)
        return True
    path = os.path.expanduser(target)
    if os.path.exists(path):
        if SYSTEM == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            _popen(["open" if SYSTEM == "Darwin" else "xdg-open", path])
        return True
    if SYSTEM == "Windows":
        return _popen(f'start "" "{target}"', shell=True) is not None
    if SYSTEM == "Darwin":
        return _popen(["open", "-a", target]) is not None
    return _popen([target]) is not None


def media_key(name: str) -> None:
    """playpause | next | prev | vol_up | vol_down | mute"""
    try:
        if SYSTEM == "Windows":
            import ctypes
            vk = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1,
                  "vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD}[name]
            for _ in range(2 if name.startswith("vol_") else 1):
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        elif SYSTEM == "Darwin":
            s = {"playpause": 'tell application "Music" to playpause',
                 "next": 'tell application "Music" to next track',
                 "prev": 'tell application "Music" to previous track',
                 "vol_up": "set volume output volume ((output volume of (get volume settings)) + 6)",
                 "vol_down": "set volume output volume ((output volume of (get volume settings)) - 6)",
                 "mute": "set volume output muted (not (output muted of (get volume settings)))"}[name]
            _popen(["osascript", "-e", s])
        else:
            _popen({"playpause": ["playerctl", "play-pause"], "next": ["playerctl", "next"],
                    "prev": ["playerctl", "previous"],
                    "vol_up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
                    "vol_down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
                    "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]}[name])
    except Exception:
        pass


def fmt_rate(b: float) -> str:
    for unit in ("B", "K", "M", "G"):
        if b < 1024:
            return f"{b:.1f}{unit}/s"
        b /= 1024
    return f"{b:.1f}T/s"


# ── background workers ──────────────────────────────────────────────────────
class SysMonitor(QObject):
    updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._run = True
        self._nvsmi = shutil.which("nvidia-smi") is not None
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._run = False

    def _gpu(self):
        if not self._nvsmi:
            return None
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
                                  "--format=csv,noheader,nounits"], capture_output=True,
                                 text=True, timeout=3, creationflags=NO_WINDOW).stdout
            u, t = [float(x) for x in out.splitlines()[0].split(",")]
            return u, t
        except Exception:
            return None

    def _loop(self):
        psutil.cpu_percent(None)
        last, lt, k, gpu = psutil.net_io_counters(), time.time(), 0, None
        root = Path.home().anchor or "/"
        while self._run:
            time.sleep(1.0)
            try:
                vm, du = psutil.virtual_memory(), psutil.disk_usage(root)
                n, now = psutil.net_io_counters(), time.time()
                dt = max(1e-3, now - lt)
                if k % 3 == 0:
                    gpu = self._gpu()
                self.updated.emit({
                    "cpu": psutil.cpu_percent(None),
                    "ram": vm.percent, "ram_txt": f"{vm.used/2**30:.1f}/{vm.total/2**30:.0f}G",
                    "disk": du.percent, "disk_txt": f"{du.free/2**30:.0f}G free",
                    "up": (n.bytes_sent - last.bytes_sent) / dt,
                    "down": (n.bytes_recv - last.bytes_recv) / dt,
                    "gpu": gpu,
                })
                last, lt = n, now
            except Exception:
                pass
            k += 1


# ── painted pieces ──────────────────────────────────────────────────────────
class HudFrame(QFrame):
    """Panel with cut corners, glowing accents and a title."""

    def __init__(self, title: str, accent: str = CYAN, parent=None):
        super().__init__(parent)
        self._title, self._accent = title, accent
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(10, 30, 10, 10)
        self.body.setSpacing(6)

    def set_title(self, t: str):
        self._title = t
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r, c = QRectF(self.rect()).adjusted(1, 1, -1, -1), 12
        path = QPainterPath()
        path.moveTo(r.left() + c, r.top())
        path.lineTo(r.right(), r.top())
        path.lineTo(r.right(), r.bottom() - c)
        path.lineTo(r.right() - c, r.bottom())
        path.lineTo(r.left(), r.bottom())
        path.lineTo(r.left(), r.top() + c)
        path.closeSubpath()
        p.fillPath(path, qc("#041b27", 200))
        p.setPen(QPen(qc(self._accent, 70), 1))
        p.drawPath(path)
        p.setPen(QPen(qc(self._accent, 240), 2))
        p.drawLine(QPointF(r.left() + c, r.top()), QPointF(r.left() + c + 48, r.top()))
        p.drawLine(QPointF(r.right() - c, r.bottom()), QPointF(r.right() - c - 48, r.bottom()))
        f = QFont(self.font())
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(f)
        p.setPen(qc(self._accent))
        p.drawText(QPointF(r.left() + 18, r.top() + 19), "▸ " + self._title.upper())


class Ring(QWidget):
    """Small circular gauge."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label, self._v, self._shown, self._text, self._sub = label, 0.0, 0.0, "--", ""
        self.setMinimumSize(110, 110)
        QTimer(self, timeout=self._tick).start(33)

    def set_value(self, v: float, text: str, sub: str = ""):
        self._v, self._text, self._sub = max(0.0, min(1.0, v)), text, sub

    def _tick(self):
        if abs(self._shown - self._v) > 0.002:
            self._shown += (self._v - self._shown) * 0.15
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = min(self.width(), self.height()) - 12
        r = QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)
        col = RED if self._shown > 0.9 else AMBER if self._shown > 0.75 else CYAN
        p.setPen(QPen(qc(CYAN, 30), 6, cap=Qt.PenCapStyle.FlatCap))
        p.drawArc(r, 225 * 16, -270 * 16)
        p.setPen(QPen(qc(col), 6, cap=Qt.PenCapStyle.FlatCap))
        p.drawArc(r, 225 * 16, int(-270 * 16 * self._shown))
        f = QFont(self.font())
        f.setPointSizeF(max(9, s / 7))
        f.setBold(True)
        p.setFont(f)
        p.setPen(qc(col))
        p.drawText(QRectF(r.left(), r.center().y() - s * 0.2, s, s * 0.3),
                   Qt.AlignmentFlag.AlignCenter, self._text)
        f.setPointSizeF(max(7, s / 13))
        f.setBold(False)
        p.setFont(f)
        p.setPen(qc(CYAN, 190))
        p.drawText(QRectF(r.left(), r.center().y() + s * 0.08, s, s * 0.16),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        if self._sub:
            p.setPen(qc(CYAN, 110))
            p.drawText(QRectF(r.left(), r.center().y() + s * 0.24, s, s * 0.16),
                       Qt.AlignmentFlag.AlignCenter, self._sub)


class HudCanvas(QWidget):
    STATE_COLORS = {"LISTENING": CYAN, "SPEAKING": "#7FF6FF", "THINKING": AMBER,
                    "PROCESSING": AMBER, "MUTED": RED, "ERROR": RED, "IDLE": CYAN_DIM}

    def __init__(self, face_path: str, name: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 300)
        self._name = name
        self.stats: dict = {}
        self._t0 = time.time()
        self._state = "INITIALIZING"
        self._audio, self._audio_ts, self._smooth = 0.0, 0.0, 0.0
        self._vlock = threading.Lock()
        self._vis, self._vhop, self._vat = [], 0.02, 0.0
        self._gl_target, self._gl_until, self._gl = (0.0, 0.0), 0.0, [0.0, 0.0]
        pm = QPixmap(face_path) if face_path and os.path.exists(face_path) else None
        self._pix = pm if pm is not None and not pm.isNull() else None
        self._pix_cache = (0, None)
        self._snap = QLabel(self)
        self._snap.setStyleSheet(f"border: 1px solid {CYAN}; background: #000;")
        self._snap.hide()
        self._snap_timer = QTimer(self, singleShot=True, timeout=self._snap.hide)
        QTimer(self, timeout=self.update).start(16)

    # thread-safe feeds
    def set_audio_level(self, level: float):
        self._audio, self._audio_ts = max(0.0, min(1.0, float(level))), time.time()

    def glance(self, dx: float, dy: float, hold: float = 1.1):
        self._gl_target = (max(-1.0, min(1.0, float(dx))), max(-1.0, min(1.0, float(dy))))
        self._gl_until = time.time() + float(hold)

    def push_visemes(self, frames, hop: float, at: float):
        with self._vlock:
            self._vis, self._vhop, self._vat = list(frames or []), max(1e-3, float(hop)), float(at)

    def set_state(self, s: str):
        self._state = (s or "").upper()

    def show_snapshot(self, img_bytes: bytes):
        pm = QPixmap()
        if not pm.loadFromData(img_bytes):
            return
        pm = pm.scaled(260, 180, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        self._snap.setPixmap(pm)
        self._snap.resize(pm.size())
        self._snap.move(self.width() - pm.width() - 16, 16)
        self._snap.show()
        self._snap_timer.start(8000)

    def _level(self, now):
        lvl = self._audio if now - self._audio_ts < 0.35 else 0.0
        with self._vlock:
            i = int((now - self._vat) / self._vhop) if self._vis else -1
            v = self._vis[i] if 0 <= i < len(self._vis) else None
        if v:
            try:
                lvl = max(lvl, float(v[0]))
            except Exception:
                pass
        return lvl

    @staticmethod
    def _arcs(p, cx, cy, r, rot, segs, width, color):
        p.setPen(QPen(color, width, cap=Qt.PenCapStyle.FlatCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        for start, span in segs:
            p.drawArc(rect, int((start + rot) * 16), int(span * 16))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 - 10
        now = time.time()
        t = now - self._t0
        boot = min(1.0, t / 2.0)
        R = min(w, h - 50) * 0.42 * (1 - (1 - boot) ** 3)
        col = self.STATE_COLORS.get(self._state, CYAN)
        self._smooth += (self._level(now) - self._smooth) * 0.25
        lv = self._smooth

        # background glow + faint grid
        g = QRadialGradient(cx, cy, max(w, h) * 0.7)
        g.setColorAt(0, QColor(0, 36, 50))
        g.setColorAt(1, QColor(BG))
        p.fillRect(self.rect(), g)
        p.setPen(QPen(qc(CYAN, 10), 1))
        for x in range(0, w, 32):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, 32):
            p.drawLine(0, y, w, y)

        if R > 6:
            # tick ring
            p.save()
            p.translate(cx, cy)
            p.rotate(t * 4)
            for i in range(120):
                long_ = i % 10 == 0
                a = math.radians(i * 3)
                r2 = R * (1.07 if long_ else 1.03)
                p.setPen(QPen(qc(col, 200 if long_ else 60), 2 if long_ else 1))
                p.drawLine(QPointF(math.cos(a) * R, math.sin(a) * R),
                           QPointF(math.cos(a) * r2, math.sin(a) * r2))
            p.restore()
            # rotating arcs
            self._arcs(p, cx, cy, R * 0.93, t * 18, [(0, 70), (95, 30), (140, 110), (275, 60)], 3, qc(col, 220))
            self._arcs(p, cx, cy, R * 0.85, -t * 28, [(20, 40), (80, 140), (280, 55)], 7, qc(col, 70))
            self._arcs(p, cx, cy, R * 0.78, t * 40, [(i * 30, 12) for i in range(12)], 2, qc(AMBER, 140))
            # radar sweep
            cg = QConicalGradient(cx, cy, (-t * 70) % 360)
            cg.setColorAt(0.0, qc(col, 80))
            cg.setColorAt(0.15, qc(col, 0))
            cg.setColorAt(1.0, qc(col, 0))
            p.setBrush(cg)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), R * 0.75, R * 0.75)
            # voice waveform
            base = R * 0.58
            for i in range(96):
                a = 2 * math.pi * i / 96
                wob = 0.5 + 0.5 * math.sin(t * 3.1 + i * 0.7) * math.sin(t * 1.7 + i * 0.23)
                L = R * (0.012 + 0.16 * lv * (0.3 + 0.7 * wob))
                p.setPen(QPen(qc(col, 120 + int(135 * min(1, lv * 1.4))), 2))
                p.drawLine(QPointF(cx + math.cos(a) * base, cy + math.sin(a) * base),
                           QPointF(cx + math.cos(a) * (base + L), cy + math.sin(a) * (base + L)))
            # core
            ar = R * 0.52
            glow = QRadialGradient(cx, cy, ar * 1.3)
            glow.setColorAt(0, qc(col, 50 + int(140 * lv)))
            glow.setColorAt(1, qc(col, 0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), ar * 1.3, ar * 1.3)
            tgt = self._gl_target if now < self._gl_until else (0.0, 0.0)
            self._gl[0] += (tgt[0] - self._gl[0]) * 0.08
            self._gl[1] += (tgt[1] - self._gl[1]) * 0.08
            clip = QPainterPath()
            clip.addEllipse(QPointF(cx, cy), ar, ar)
            p.save()
            p.setClipPath(clip)
            if self._pix is not None:
                size = max(8, int(ar * 2.2))
                if self._pix_cache[0] != size:
                    self._pix_cache = (size, self._pix.scaled(
                        size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation))
                pm = self._pix_cache[1]
                p.drawPixmap(int(cx - pm.width() / 2 + self._gl[0] * ar * 0.12),
                             int(cy - pm.height() / 2 + self._gl[1] * ar * 0.12), pm)
                p.fillPath(clip, qc(col, 30))
            else:  # arc reactor
                p.setBrush(Qt.BrushStyle.NoBrush)
                for k, rr in enumerate((0.95, 0.75)):
                    p.setPen(QPen(qc(col, 170 - k * 40), 2))
                    p.drawEllipse(QPointF(cx, cy), ar * rr, ar * rr)
                p.save()
                p.translate(cx, cy)
                p.rotate(t * 25)
                for _ in range(10):
                    p.rotate(36)
                    p.fillRect(QRectF(ar * 0.55, -ar * 0.05, ar * 0.3, ar * 0.1), qc(col, 150))
                p.restore()
                core = QRadialGradient(cx, cy, ar * 0.45)
                core.setColorAt(0, qc("#FFFFFF", 240))
                core.setColorAt(0.4, qc(col, 220))
                core.setColorAt(1, qc(col, 0))
                p.setBrush(core)
                p.setPen(Qt.PenStyle.NoPen)
                rr = ar * (0.42 + 0.08 * lv)
                p.drawEllipse(QPointF(cx, cy), rr, rr)
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qc(col, 235), 2))
            p.drawEllipse(QPointF(cx, cy), ar, ar)

        # corner brackets
        p.setPen(QPen(qc(CYAN, 150), 2))
        L = 24
        for x, y, dx, dy in ((8, 8, 1, 1), (w - 8, 8, -1, 1), (8, h - 8, 1, -1), (w - 8, h - 8, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * L, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))

        # scanline
        sy = (t * 80) % max(1, h)
        sg = QLinearGradient(0, sy - 40, 0, sy)
        sg.setColorAt(0, qc(CYAN, 0))
        sg.setColorAt(1, qc(CYAN, 26))
        p.fillRect(QRectF(0, sy - 40, w, 40), sg)

        # corner readouts
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(f)
        st, dtn = self.stats, datetime.now()
        left = [self._name + "  //  MARK LVIII",
                f"CORE {st.get('cpu', 0):5.1f}%   MEM {st.get('ram', 0):5.1f}%",
                "ALL SYSTEMS NOMINAL" if st.get("cpu", 0) < 90 else "CORE LOAD CRITICAL"]
        right = [dtn.strftime("%H:%M:%S"), dtn.strftime("%a %d %b %Y").upper(), "UPLINK SECURE"]
        for i, s_ in enumerate(left):
            p.setPen(qc(CYAN, 200 if i == 0 else 130))
            p.drawText(QPointF(24, 32 + i * 16), s_)
        for i, s_ in enumerate(right):
            p.setPen(qc(CYAN, 200 if i == 0 else 130))
            p.drawText(QRectF(0, 20 + i * 16, w - 24, 16), Qt.AlignmentFlag.AlignRight, s_)
        p.setPen(qc(CYAN, 110))
        p.drawText(QPointF(24, h - 22),
                   f"▲ {fmt_rate(st.get('up', 0))}   ▼ {fmt_rate(st.get('down', 0))}")
        p.drawText(QRectF(0, h - 34, w - 24, 16), Qt.AlignmentFlag.AlignRight,
                   f"VOX {int(lv * 100):3d}%")
        f.setPointSizeF(13)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6)
        p.setFont(f)
        label = self._state if boot >= 1 else "INITIALIZING"
        a = 255 if self._state not in ("THINKING", "PROCESSING") else 150 + int(105 * abs(math.sin(t * 4)))
        p.setPen(qc(col, a))
        p.drawText(QRectF(0, h - 40, w, 24), Qt.AlignmentFlag.AlignCenter, f"[ {label} ]")


# ── side panel tabs ─────────────────────────────────────────────────────────
class SystemPanel(QWidget):
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        self.cpu, self.ram, self.disk, self.gpu = Ring("CORE"), Ring("MEMORY"), Ring("STORAGE"), Ring("GPU")
        for i, r in enumerate((self.cpu, self.ram, self.disk, self.gpu)):
            grid.addWidget(r, i // 2, i % 2)
        lay.addLayout(grid)
        self.net = QLabel()
        self.net.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.net.setStyleSheet(f"color:{CYAN_DIM}; letter-spacing:1px;")
        lay.addWidget(self.net)

        lay.addWidget(self._heading("RUN"))
        self.run = QLineEdit(placeholderText="app, file, folder or website…")
        self.run.returnPressed.connect(self._run)
        lay.addWidget(self.run)

        lay.addWidget(self._heading("MEDIA"))
        row = QHBoxLayout()
        for text, key in (("⏮", "prev"), ("⏯", "playpause"), ("⏭", "next"),
                          ("🔉", "vol_down"), ("🔊", "vol_up"), ("🔇", "mute")):
            b = QPushButton(text, clicked=lambda _=False, k=key: media_key(k))
            b.setStyleSheet("font-size: 15px; padding: 6px 0;")
            row.addWidget(b)
        lay.addLayout(row)
        lay.addStretch()

    @staticmethod
    def _heading(t):
        l = QLabel(t)
        l.setStyleSheet(f"color:{CYAN}; letter-spacing:3px; margin-top:8px;")
        return l

    def _run(self):
        t = self.run.text().strip()
        if t:
            self.log.emit(("SYS: opening " if launch(t) else "ERROR: couldn't open ") + t)
            self.run.clear()

    def update_stats(self, d: dict):
        self.cpu.set_value(d["cpu"] / 100, f"{d['cpu']:.0f}%")
        self.ram.set_value(d["ram"] / 100, f"{d['ram']:.0f}%", d["ram_txt"])
        self.disk.set_value(d["disk"] / 100, f"{d['disk']:.0f}%", d["disk_txt"])
        if d.get("gpu"):
            u, temp = d["gpu"]
            self.gpu.set_value(u / 100, f"{u:.0f}%", f"{temp:.0f}°C")
        else:
            self.gpu.set_value(0, "N/A")
        self.net.setText(f"▲ {fmt_rate(d['up'])}     ▼ {fmt_rate(d['down'])}")


# ── quiz ────────────────────────────────────────────────────────────────────
class QuizPanel(QWidget):
    finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.head = QLabel()
        self.head.setStyleSheet(f"color:{AMBER}; letter-spacing:2px;")
        self.q = QLabel()
        self.q.setWordWrap(True)
        self.q.setStyleSheet("font-size: 13px;")
        self.opts = QVBoxLayout()
        self.ans = QLineEdit(placeholderText="Your answer…")
        self.ans.returnPressed.connect(lambda: self._answer(self.ans.text()))
        self.fb = QLabel()
        self.fb.setWordWrap(True)
        self.next_btn = QPushButton("NEXT ▸", clicked=self._next)
        nxt = QHBoxLayout()
        nxt.addStretch()
        nxt.addWidget(self.next_btn)
        lay.addWidget(self.head)
        lay.addWidget(self.q)
        lay.addLayout(self.opts)
        lay.addWidget(self.ans)
        lay.addWidget(self.fb)
        lay.addLayout(nxt)
        self._qs, self._i, self._grade, self._topic, self._res = [], 0, None, "", []

    def start(self, topic, questions, grade):
        self._topic, self._qs, self._grade, self._i, self._res = topic, questions, grade, 0, []
        self._show()

    @staticmethod
    def _text(q):
        if isinstance(q, dict):
            return str(q.get("question") or q.get("prompt") or q.get("q") or q.get("text") or q)
        return str(q)

    @staticmethod
    def _options(q):
        o = (q.get("options") or q.get("choices") or []) if isinstance(q, dict) else []
        return [str(x) for x in o] if isinstance(o, (list, tuple)) else []

    def _show(self):
        while self.opts.count():
            w = self.opts.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.fb.clear()
        self.next_btn.setEnabled(False)
        if self._i >= len(self._qs):
            return self._finish()
        q = self._qs[self._i]
        self.head.setText(f"QUIZ · {self._topic.upper()} · {self._i + 1}/{len(self._qs)}")
        self.q.setText(self._text(q))
        opts = self._options(q)
        self.ans.setVisible(not opts)
        self.ans.clear()
        for o in opts:
            self.opts.addWidget(QPushButton(o, clicked=lambda _=False, v=o: self._answer(v)))

    def _answer(self, given):
        if self.next_btn.isEnabled() or self._i >= len(self._qs):
            return
        q = self._qs[self._i]
        verdict = None
        if self._grade:
            try:
                verdict = self._grade(q, given)
            except Exception:
                verdict = None
        self._res.append({"question": self._text(q), "given": given, "correct": verdict})
        if verdict is True:
            self.fb.setText(f"<span style='color:{GREEN}'>✔ CORRECT</span>")
        elif verdict is False:
            right = q.get("answer") if isinstance(q, dict) else None
            self.fb.setText(f"<span style='color:{RED}'>✘ INCORRECT</span>"
                            + (f" — answer: {html.escape(str(right))}" if right else ""))
        else:
            self.fb.setText(f"<span style='color:{AMBER}'>◆ LOGGED — JARVIS will judge this one</span>")
        for i in range(self.opts.count()):
            w = self.opts.itemAt(i).widget()
            if w:
                w.setEnabled(False)
        self.next_btn.setEnabled(True)

    def _next(self):
        self._i += 1
        self._show()

    def _finish(self):
        right = sum(1 for r in self._res if r["correct"] is True)
        judged = sum(1 for r in self._res if r["correct"] is not None)
        self.head.setText(f"QUIZ COMPLETE · {self._topic.upper()}")
        self.q.setText(f"Score: {right}/{judged}")
        self.ans.hide()
        lines = [f"[Quiz finished] Topic: {self._topic}. Score {right}/{judged} on auto-marked questions."]
        for n, r in enumerate(self._res, 1):
            mark = {True: "correct", False: "wrong", None: "PLEASE JUDGE"}[r["correct"]]
            lines.append(f"{n}. {r['question']} — answered: {r['given']} ({mark})")
        self.finished.emit("\n".join(lines))


# ── settings dialog ─────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.setWindowTitle("Settings")
        self.win = win
        form = QFormLayout(self)
        self.voice = QLineEdit(placeholderText="leave empty to keep")
        form.addRow("VOICE", self.voice)
        self.dev = QComboBox()
        self.dev.addItem("(unchanged)")
        if HAS_MM:
            for d in QMediaDevices.audioInputs():
                self.dev.addItem(d.description())
        form.addRow("MICROPHONE", self.dev)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.resize(460, 160)

    def _ok(self):
        w = self.win
        if self.voice.text().strip():
            w._call(w.on_voice_change, self.voice.text().strip())
        if self.dev.currentIndex() > 0:
            w._call(w.on_audio_device_change, self.dev.currentText())
        self.accept()


# ── main window ─────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    _state_sig = pyqtSignal(str)
    _log_sig = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)
    _quiz_sig = pyqtSignal(str, list, object)
    _quiz_hide_sig = pyqtSignal()
    _review_sig = pyqtSignal(str, str, list, list)
    _reconfig_sig = pyqtSignal()
    _camera_sig = pyqtSignal(bytes)
    _video_open_sig = pyqtSignal(str, str, bool, str)
    _image_open_sig = pyqtSignal(str, str)
    _video_close_sig = pyqtSignal()
    _video_mute_sig = pyqtSignal(bool)
    _video_seek_sig = pyqtSignal(float, bool)
    _video_pause_sig = pyqtSignal(bool)
    _confirm_sig = pyqtSignal(str, str)
    _confirm_hide_sig = pyqtSignal()
    _cam_stream_sig = pyqtSignal(bool)
    _phone_sig = pyqtSignal()
    _mute_sig = pyqtSignal(bool)

    def __init__(self, face_path: str):
        super().__init__()
        self._assistant_name = os.environ.get("JARVIS_NAME", "JARVIS")
        self._muted = False
        self._ready = True
        self._state = "LISTENING"
        self._media_kind = ""
        self._split_audio = False
        self._current_file: str | None = None
        self.settings = load_settings()
        for cb in ("on_text_command", "on_remote_clicked", "on_interrupt", "on_voice_change",
                   "on_audio_device_change", "get_plugins", "get_plugin_settings", "on_wake_toggle",
                   "on_wake_manual", "wake_get_state", "ptt_hold", "on_push_to_talk"):
            setattr(self, cb, None)

        self.setWindowTitle(self._assistant_name)
        self.resize(1400, 860)
        self.setAcceptDrops(True)
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)
        center = QVBoxLayout()
        center.setSpacing(10)
        body.addLayout(center, 1)
        spaced = ".".join(self._assistant_name.upper()) if len(self._assistant_name) <= 8 else self._assistant_name.upper()
        self.hud = HudCanvas(face_path, spaced)
        center.addWidget(self._build_media_stack(), 1)
        center.addWidget(self._build_card())
        center.addWidget(self._build_comms())

        self.tabs = HudFrame("Diagnostics")
        self.tabs.setFixedWidth(320)
        self.system = SystemPanel()
        self.system.log.connect(self._log)
        self.tabs.body.addWidget(self.system)
        body.addWidget(self.tabs)

        self._build_confirm(central)
        self.monitor = SysMonitor()
        self.monitor.updated.connect(self.system.update_stats)
        self.monitor.updated.connect(lambda d: setattr(self.hud, 'stats', d))

        for sig, slot in ((self._state_sig, self._set_state), (self._log_sig, self._log),
                          (self._content_sig, self._show_content), (self._quiz_sig, self._show_quiz),
                          (self._quiz_hide_sig, self.card.hide), (self._review_sig, self._show_review),
                          (self._reconfig_sig, self._show_reconfig), (self._camera_sig, self.hud.show_snapshot),
                          (self._video_open_sig, self._open_video), (self._image_open_sig, self._open_image),
                          (self._video_close_sig, self._close_media), (self._video_mute_sig, self._mute_media),
                          (self._video_seek_sig, self._seek_media), (self._video_pause_sig, self._pause_media),
                          (self._confirm_sig, self._show_confirm), (self._confirm_hide_sig, self.confirm.hide),
                          (self._cam_stream_sig, self._camera_stream), (self._phone_sig, self._phone_connected),
                          (self._mute_sig, self._set_mute)):
            sig.connect(slot)

        QShortcut(QKeySequence("F11"), self, activated=self._toggle_fullscreen)
        QShortcut(QKeySequence("Esc"), self, activated=self._interrupt)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.input.setFocus)
        QTimer(self, timeout=lambda: self.clock.setText(datetime.now().strftime("%H:%M:%S"))).start(1000)
        self._set_state("LISTENING")
        self._log(f"SYS: {self._assistant_name} online.")

    # ── construction ────────────────────────────────────────────────────
    def _build_header(self):
        bar = QFrame()
        bar.setFixedHeight(50)
        bar.setStyleSheet("QFrame { background: transparent; border-bottom: 1px solid rgba(0,229,255,0.3); }"
                          "QLabel { border: none; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 4, 6, 6)
        logo = QLabel(f"◉  {'.'.join(self._assistant_name.upper())}")
        logo.setStyleSheet(f"color:{CYAN}; font-size:20px; font-weight:bold; letter-spacing:6px;")
        self.state_lbl = QLabel()
        self.clock = QLabel()
        self.clock.setStyleSheet(f"color:{CYAN}; font-size:15px; letter-spacing:3px;")
        self.mute_btn = QPushButton("MIC", checkable=True, clicked=self._toggle_mute)
        self.mute_btn.setToolTip("Mute / unmute the microphone")

        menu = QMenu(self)
        self.wake_act = QAction("Wake word", self, checkable=True, triggered=self._toggle_wake)
        menu.addAction(self.wake_act)
        menu.addAction("Wake now", lambda: self._call(self.on_wake_manual))
        self.remote_act = menu.addAction("Remote / phone", lambda: self._call(self.on_remote_clicked))
        menu.addAction("Modules", self._show_plugins)
        menu.addSeparator()
        menu.addAction("Show / hide diagnostics", lambda: self.tabs.setVisible(not self.tabs.isVisible()))
        menu.addAction("Fullscreen   F11", self._toggle_fullscreen)
        menu.addAction("Settings…", lambda: SettingsDialog(self).exec())
        menu.aboutToShow.connect(self._sync_wake)
        more = QPushButton("☰")
        more.setMenu(menu)

        lay.addWidget(logo)
        lay.addStretch()
        lay.addWidget(self.state_lbl)
        lay.addSpacing(18)
        lay.addWidget(self.clock)
        lay.addSpacing(18)
        lay.addWidget(self.mute_btn)
        lay.addWidget(QPushButton("STOP", objectName="danger", clicked=self._interrupt))
        lay.addWidget(more)
        return bar

    def _build_media_stack(self):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.media_bar = QFrame()
        self.media_bar.setStyleSheet(f"background: rgba(0,229,255,0.08); border: 1px solid {CYAN_DIM};")
        mb = QHBoxLayout(self.media_bar)
        mb.setContentsMargins(8, 3, 8, 3)
        self.media_title = QLabel()
        self.media_title.setStyleSheet(f"color:{CYAN}; letter-spacing:2px; border:none;")
        self.media_sound = QPushButton("SOUND OFF", clicked=lambda: self._mute_media(not self._media_muted()))
        mb.addWidget(self.media_title, 1)
        mb.addWidget(QPushButton("⏯", clicked=lambda: self._pause_media(self._media_playing())))
        mb.addWidget(self.media_sound)
        mb.addWidget(QPushButton("✕", objectName="danger", clicked=lambda: self._close_media()))
        self.media_bar.hide()
        v.addWidget(self.media_bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.hud)
        self.image_lbl = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.setStyleSheet("background:#000;")
        self._image_pm: QPixmap | None = None
        self.player = self.audio_player = self.camera = None
        if HAS_MM:
            self.video = QVideoWidget()
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
            self.player.setVideoOutput(self.video)
            self.audio_player = QMediaPlayer(self)
            self.audio_out2 = QAudioOutput(self)
            self.audio_player.setAudioOutput(self.audio_out2)
            self.cam_widget = QVideoWidget()
            self.cam_session = QMediaCaptureSession(self)
            self.cam_session.setVideoOutput(self.cam_widget)
            QTimer(self, timeout=self._sync_audio).start(1000)
        else:
            self.video = QLabel("QtMultimedia not installed", alignment=Qt.AlignmentFlag.AlignCenter)
            self.cam_widget = QLabel("QtMultimedia not installed", alignment=Qt.AlignmentFlag.AlignCenter)
        for w in (self.video, self.image_lbl, self.cam_widget):
            self.stack.addWidget(w)
        v.addWidget(self.stack, 1)
        return wrap

    def _build_card(self):
        self.card = HudFrame("Data", accent=AMBER)
        self.card.setMaximumHeight(300)
        self.card_stack = QStackedWidget()
        self.card_text = QTextBrowser(openExternalLinks=True)
        self.quiz = QuizPanel()
        self.quiz.finished.connect(self._send_command)
        self.card_stack.addWidget(self.card_text)
        self.card_stack.addWidget(self.quiz)
        self.card.body.addWidget(self.card_stack)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(QPushButton("CLOSE", clicked=self.card.hide))
        self.card.body.addLayout(row)
        self.card.hide()
        return self.card

    def _build_comms(self):
        frame = HudFrame("Comms")
        frame.setFixedHeight(200)
        self.logbox = QTextEdit(readOnly=True)
        frame.body.addWidget(self.logbox, 1)
        row = QHBoxLayout()
        self.ptt = QPushButton("● TALK")
        self.ptt.setToolTip("Hold to talk (or hold Space)")
        self.ptt.pressed.connect(lambda: self._ptt(True))
        self.ptt.released.connect(lambda: self._ptt(False))
        self.input = QLineEdit(placeholderText=f"Talk to {self._assistant_name}…   (drop a file anywhere to attach it)")
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.ptt)
        row.addWidget(self.input, 1)
        row.addWidget(QPushButton("SEND ▸", clicked=self._submit))
        frame.body.addLayout(row)

        class _DropZone:  # JarvisUI.current_file uses _drop_zone.current_file()
            def __init__(s, win):
                s.win = win

            def current_file(s):
                return s.win._current_file

        self._drop_zone = _DropZone(self)
        return frame

    def _build_confirm(self, parent):
        self.confirm = HudFrame("Confirm", accent=RED, parent=parent)
        self.confirm.setFixedSize(440, 190)
        self.confirm_title = QLabel()
        self.confirm_title.setStyleSheet(f"color:{RED}; font-size:15px; font-weight:bold; letter-spacing:2px;")
        self.confirm_detail = QLabel()
        self.confirm_detail.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(QPushButton("YES", objectName="danger", clicked=lambda: self._confirm_answer("yes")))
        row.addWidget(QPushButton("NO", clicked=lambda: self._confirm_answer("no")))
        self.confirm.body.addWidget(self.confirm_title)
        self.confirm.body.addWidget(self.confirm_detail, 1)
        self.confirm.body.addLayout(row)
        self.confirm.hide()

    # ── helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _call(cb, *args):
        if not callable(cb):
            return None
        try:
            return cb(*args)
        except TypeError:
            try:
                return cb()
            except Exception:
                return None
        except Exception:
            return None

    def _send_command(self, text: str):
        if text.strip():
            self._call(self.on_text_command, text)

    def _submit(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self._log(f"You: {text}")
            self._send_command(text)

    def _log(self, text: str):
        ts = datetime.now().strftime("%H:%M")
        low = str(text).lower()
        color = AMBER if low.startswith("you:") else RED if low.startswith("error") else \
            CYAN_DIM if low.startswith(("sys", "[")) else TEXT
        esc = html.escape(str(text)).replace("\n", "<br>")
        self.logbox.append(f"<span style='color:{CYAN_DIM}'>{ts}</span>&nbsp; <span style='color:{color}'>{esc}</span>")
        self.logbox.verticalScrollBar().setValue(self.logbox.verticalScrollBar().maximum())

    def _set_state(self, s: str):
        s = (s or "").upper()
        self._state = s
        shown = "MUTED" if self._muted and s == "LISTENING" else s
        self.hud.set_state(shown)
        self.state_lbl.setText(f"● {shown}")
        self.state_lbl.setStyleSheet(f"color:{HudCanvas.STATE_COLORS.get(shown, CYAN)}; "
                                     "letter-spacing:3px; font-weight:bold;")

    def _toggle_mute(self):
        self._set_mute(not self._muted)

    def _set_mute(self, v: bool):
        self._muted = bool(v)
        self.mute_btn.setChecked(self._muted)
        self.mute_btn.setText("MIC OFF" if self._muted else "MIC")
        self._set_state("MUTED" if self._muted else "LISTENING")

    def _ptt(self, down: bool):
        self.ptt.setText("◉ LIVE" if down else "● TALK")
        if callable(self.ptt_hold):
            self._call(self.ptt_hold, down)
        else:
            self._call(self.on_push_to_talk, down)

    def _interrupt(self):
        self._call(self.on_interrupt)

    def _sync_wake(self):
        st = self._call(self.wake_get_state)
        if isinstance(st, dict):
            st = st.get("enabled", st.get("on"))
        if isinstance(st, bool):
            self.wake_act.setChecked(st)

    def _toggle_wake(self, checked: bool):
        self._call(self.on_wake_toggle, checked)
        self._log(f"SYS: wake word {'on' if checked else 'off'}")

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _show_plugins(self):
        items = self._call(self.get_plugins) or []
        if isinstance(items, dict):
            items = [f"{k}: {v}" for k, v in items.items()]
        lines = [f"◆ {it.get('name', it)}" if isinstance(it, dict) else f"◆ {it}" for it in items]
        self._show_content("Modules", "\n".join(lines) or "No modules reported.")

    def notify_phone_connected(self):
        self._phone_sig.emit()

    def _phone_connected(self):
        self.remote_act.setText("Remote / phone  ● linked")
        self._log("SYS: phone linked")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self._current_file = urls[0].toLocalFile()
            self._log(f"SYS: attached {Path(self._current_file).name}")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat() and not self.input.hasFocus():
            return self._ptt(True)
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat() and not self.input.hasFocus():
            return self._ptt(False)
        super().keyReleaseEvent(e)

    # ── content card ────────────────────────────────────────────────────
    def _show_content(self, title: str, text: str):
        self.card.set_title(title or "Data")
        self.card_text.setHtml(f"<div style='color:{TEXT}; white-space:pre-wrap'>{html.escape(text)}</div>")
        self.card_stack.setCurrentWidget(self.card_text)
        self.card.show()

    def _show_review(self, title, summary, findings, unclear):
        order = {"serious": 0, "caution": 1, "note": 2}
        colors = {"serious": RED, "caution": AMBER, "note": CYAN}
        parts = [f"<p style='color:{TEXT}'>{html.escape(summary)}</p>"]
        for f in sorted(findings, key=lambda x: order.get(str(x.get("severity", "note")).lower(), 3)):
            sev = str(f.get("severity", "note")).lower()
            parts.append(f"<p><b style='color:{colors.get(sev, CYAN)}'>■ {sev.upper()} · "
                         f"{html.escape(str(f.get('heading', '')))}</b><br>{html.escape(str(f.get('detail', '')))}")
            if f.get("quote"):
                parts.append(f"<br><i style='color:{CYAN_DIM}'>“{html.escape(str(f['quote']))}”</i>")
            if f.get("suggestion"):
                parts.append(f"<br><span style='color:{GREEN}'>→ {html.escape(str(f['suggestion']))}</span>")
            parts.append("</p>")
        if unclear:
            parts.append(f"<p style='color:{AMBER}'>UNCLEAR:</p><ul>"
                         + "".join(f"<li>{html.escape(str(u))}</li>" for u in unclear) + "</ul>")
        self.card.set_title(title or "Review")
        self.card_text.setHtml("".join(parts))
        self.card_stack.setCurrentWidget(self.card_text)
        self.card.show()

    def _show_quiz(self, topic, questions, grade):
        self.card.set_title(f"Quiz · {topic}")
        self.card_stack.setCurrentWidget(self.quiz)
        self.card.show()
        self.quiz.start(topic, questions, grade)

    # ── confirm gate ────────────────────────────────────────────────────
    def _show_confirm(self, title, detail):
        self.confirm_title.setText(title.upper())
        self.confirm_detail.setText(detail)
        self._place_confirm()
        self.confirm.show()
        self.confirm.raise_()

    def _place_confirm(self):
        c = self.centralWidget()
        self.confirm.move((c.width() - self.confirm.width()) // 2, (c.height() - self.confirm.height()) // 3)

    def _confirm_answer(self, word: str):
        self.confirm.hide()
        self._log(f"You: {word}")
        self._send_command(word)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "confirm"):
            self._place_confirm()
        self._fit_image()

    # ── API key ─────────────────────────────────────────────────────────
    def _show_reconfig(self):
        key, ok = QInputDialog.getText(self, "API key", "Authentication failed. Paste a new API key:",
                                       QLineEdit.EchoMode.Password)
        if ok and key.strip():
            cfg = Path("config") / "api_keys.json"
            try:
                cfg.parent.mkdir(exist_ok=True)
                data = json.loads(cfg.read_text()) if cfg.exists() else {}
                data["gemini_api_key"] = key.strip()
                cfg.write_text(json.dumps(data, indent=2))
                os.environ["GEMINI_API_KEY"] = key.strip()
            except Exception as err:
                self._log(f"ERROR: could not save key: {err}")
        self._ready = True

    # ── video / image / camera ──────────────────────────────────────────
    def _media_playing(self) -> bool:
        return bool(self.player and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

    def _media_muted(self) -> bool:
        if not self.player:
            return True
        return (self.audio_out2 if self._split_audio else self.audio_out).isMuted()

    def _show_media_page(self, widget, title, kind):
        self._media_kind = kind
        self.media_title.setText(f"▸ {(title or kind).upper()}")
        self.media_bar.show()
        self.stack.setCurrentWidget(widget)

    def _open_video(self, source, title, muted, audio_source):
        if not HAS_MM or not source:
            self._log("ERROR: video playback unavailable")
            return
        self._close_media(keep_page=True)
        as_url = lambda s: QUrl.fromLocalFile(s) if os.path.exists(s) else QUrl(s)
        self.player.setSource(as_url(source))
        self._split_audio = bool(audio_source)
        if audio_source:
            self.audio_player.setSource(as_url(audio_source))
            self.audio_out.setMuted(True)
            self.audio_player.play()
        self._show_media_page(self.video, title, "video")
        self._mute_media(muted)
        self.player.play()

    def _open_image(self, path, title):
        pm = QPixmap(path)
        if pm.isNull():
            self._log(f"ERROR: cannot open image {path}")
            return
        self._close_media(keep_page=True)
        self._image_pm = pm
        self._show_media_page(self.image_lbl, title or Path(path).name, "image")
        self._fit_image()

    def _fit_image(self):
        if getattr(self, "_image_pm", None) is not None:
            self.image_lbl.setPixmap(self._image_pm.scaled(
                self.stack.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def _close_media(self, keep_page=False):
        if self.player:
            self.player.stop()
            self.audio_player.stop()
            self.audio_player.setSource(QUrl())
        if self.camera:
            self.camera.stop()
            self.camera = None
        self._image_pm = None
        self._split_audio = False
        if not keep_page:
            self._media_kind = ""
            self.media_bar.hide()
            self.stack.setCurrentWidget(self.hud)

    def _mute_media(self, muted: bool):
        if not self.player:
            return
        (self.audio_out2 if self._split_audio else self.audio_out).setMuted(muted)
        self.media_sound.setText("SOUND OFF" if muted else "SOUND ON")

    def _seek_media(self, seconds, relative):
        if not self.player:
            return
        pos = max(0, int(self.player.position() + seconds * 1000 if relative else seconds * 1000))
        self.player.setPosition(pos)
        if self._split_audio:
            self.audio_player.setPosition(pos)

    def _pause_media(self, paused):
        if not self.player:
            return
        for pl in (self.player, self.audio_player if self._split_audio else None):
            if pl:
                pl.pause() if paused else pl.play()

    def _sync_audio(self):
        if self._split_audio and self._media_playing():
            if abs(self.player.position() - self.audio_player.position()) > 300:
                self.audio_player.setPosition(self.player.position())

    def video_is_playing(self) -> bool:
        if self._media_kind == "image":
            return True
        return self._media_kind == "video" and bool(self.player) and \
            self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState

    def video_state(self) -> dict:
        if self._media_kind == "video" and self.player:
            return {"kind": "video", "position": self.player.position() / 1000,
                    "duration": self.player.duration() / 1000,
                    "paused": not self._media_playing()}
        if self._media_kind == "image":
            return {"kind": "image", "position": 0.0, "duration": 0.0, "paused": False}
        return {"kind": "", "position": 0.0, "duration": 0.0, "paused": False}

    def start_camera_stream(self):
        self._cam_stream_sig.emit(True)

    def stop_camera_stream(self):
        self._cam_stream_sig.emit(False)

    def _camera_stream(self, on: bool):
        if not on:
            if self._media_kind == "camera":
                self._close_media()
            return
        if not HAS_MM:
            self._log("ERROR: camera unavailable")
            return
        self._close_media(keep_page=True)
        dev = QMediaDevices.defaultVideoInput()
        if dev.isNull():
            self._log("ERROR: no camera found")
            self._close_media()
            return
        self.camera = QCamera(dev, self)
        self.cam_session.setCamera(self.camera)
        self.camera.start()
        self._show_media_page(self.cam_widget, "Live camera", "camera")

    def closeEvent(self, e):
        self.monitor.stop()
        save_settings(self.settings)
        self._close_media()
        super().closeEvent(e)


# ── public façade (unchanged API) ───────────────────────────────────────────
class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


def _cb_property(name):
    return property(lambda self: getattr(self._win, name),
                    lambda self, cb: setattr(self._win, name, cb))


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._app.setStyleSheet(STYLE.format(font=mono_family(), text=TEXT, bg=BG, cyan=CYAN,
                                             cyan_dim=CYAN_DIM, red=RED))
        self._win = MainWindow(face_path)
        self.root = _RootShim(self._app)
        self._win.show()

    on_text_command = _cb_property("on_text_command")
    on_remote_clicked = _cb_property("on_remote_clicked")
    on_interrupt = _cb_property("on_interrupt")
    on_voice_change = _cb_property("on_voice_change")
    on_audio_device_change = _cb_property("on_audio_device_change")
    get_plugins = _cb_property("get_plugins")
    get_plugin_settings = _cb_property("get_plugin_settings")
    on_wake_toggle = _cb_property("on_wake_toggle")
    on_wake_manual = _cb_property("on_wake_manual")
    wake_get_state = _cb_property("wake_get_state")
    ptt_hold = _cb_property("ptt_hold")
    on_push_to_talk = _cb_property("on_push_to_talk")

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        v = bool(v)
        if v != self._win._muted:
            self._win._muted = v
            self._win._mute_sig.emit(v)

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def show_confirm(self, title: str, detail: str) -> None:
        self._win._confirm_sig.emit(str(title)[:120], str(detail)[:300])

    def hide_confirm(self) -> None:
        self._win._confirm_hide_sig.emit()

    def set_audio_level(self, level: float) -> None:
        try:
            self._win.hud.set_audio_level(level)
        except Exception:
            pass

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        try:
            self._win.hud.glance(dx, dy, hold)
        except Exception:
            pass

    def push_visemes(self, frames, hop: float, at: float) -> None:
        try:
            self._win.hud.push_visemes(frames, hop, at)
        except Exception:
            pass

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        self._win._content_sig.emit(title[:48], text[:4000])

    def show_quiz(self, topic: str, questions, grade=None) -> None:
        self._win._quiz_sig.emit(str(topic or ""), list(questions or []), grade)

    def hide_quiz(self) -> None:
        self._win._quiz_hide_sig.emit()

    def show_review(self, title: str, summary: str, findings, unclear=None) -> None:
        self._win._review_sig.emit(str(title or ""), str(summary or ""),
                                   list(findings or []), list(unclear or []))

    def prompt_reconfig(self):
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        self._win._camera_sig.emit(img_bytes)

    def show_video(self, source: str, title: str = "", muted: bool = True, audio_source: str = "") -> None:
        self._win._video_open_sig.emit(str(source or ""), str(title or ""), bool(muted), str(audio_source or ""))

    def show_image(self, path: str, title: str = "") -> None:
        self._win._image_open_sig.emit(str(path or ""), str(title or ""))

    def stop_video(self) -> None:
        self._win._video_close_sig.emit()

    def set_video_muted(self, muted: bool) -> None:
        self._win._video_mute_sig.emit(bool(muted))

    def video_is_playing(self) -> bool:
        return bool(self._win.video_is_playing())

    def seek_video(self, seconds: float, relative: bool = True) -> None:
        self._win._video_seek_sig.emit(float(seconds), bool(relative))

    def pause_video(self, paused: bool = True) -> None:
        self._win._video_pause_sig.emit(bool(paused))

    def video_state(self) -> dict:
        try:
            return dict(self._win.video_state())
        except Exception:
            return {}

    def start_camera_stream(self) -> None:
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        self._win.stop_camera_stream()

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")



# Compatibility: keep every name the old gui/ package exported importable.
for _modname in ("theme", "metrics", "hud", "widgets", "overlays", "providers_panel", "window"):
    try:
        _mod = importlib.import_module(f"gui.{_modname}")
    except Exception:
        continue
    for _name, _value in vars(_mod).items():
        if not _name.startswith("__") and _name not in globals():
            globals()[_name] = _value
