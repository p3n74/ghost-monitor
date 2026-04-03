"""
Ghost Monitor — Lossless Viewer
Runs on the MacBook. Fetches a lossless PNG from the PC server on demand
and displays it with pixel-accurate zoom and pan.

Controls
--------
R           Refresh (fetch new frame)
F           Toggle fit-to-screen / free zoom
1           Reset to 100 % (1 image pixel = 1 display point)
+ / =       Zoom in
- / _       Zoom out
S           Save current frame to disk
Escape      Quit

Mouse wheel     Zoom centred on cursor
Left-drag       Pan
"""

import sys
import time
import argparse

import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QScrollArea, QLabel,
    QStatusBar, QFileDialog,
)
from PySide6.QtGui import QPixmap, QImage, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QPoint, QEvent, QByteArray

ZOOM_MIN = 0.02
ZOOM_MAX = 9.0
ZOOM_STEP = 1.1


class GhostViewer(QMainWindow):

    def __init__(self, server_url: str, monitor: int = 2, start_fit: bool = False):
        super().__init__()
        self.server_url = server_url.rstrip("/")
        self.monitor = monitor
        self.zoom_level = 1.0
        self.fit_mode = start_fit
        self.original_pixmap: QPixmap | None = None
        self.raw_bytes: bytes | None = None

        self._drag_active = False
        self._drag_origin = QPoint()

        self._build_ui()
        self._bind_keys()
        self.showFullScreen()
        self.refresh()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("Ghost Monitor")
        self.setStyleSheet("background-color: #111;")

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: transparent;")

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.image_label)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: #111; }"
            "QScrollBar { background: #222; }"
            "QScrollBar::handle { background: #555; border-radius: 4px; }"
        )
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll.viewport().installEventFilter(self)
        self.scroll.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        self.setCentralWidget(self.scroll)

        self.bar = QStatusBar()
        self.bar.setStyleSheet(
            "QStatusBar { color: #888; background: #1a1a1a; "
            "font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 12px; }"
        )
        self.setStatusBar(self.bar)
        self.bar.showMessage(
            "[R] Refresh   [F] Fit / Actual   [1] 100%   "
            "[Scroll] Zoom   [Drag] Pan   [S] Save   [Esc] Quit"
        )

    def _bind_keys(self):
        for key, slot in [
            ("R",      self.refresh),
            ("F",      self.toggle_fit),
            ("1",      self.reset_zoom),
            ("S",      self.save_frame),
            ("Escape", self.close),
        ]:
            QShortcut(QKeySequence(key), self).activated.connect(slot)

        QShortcut(QKeySequence("+"), self).activated.connect(
            lambda: self._zoom_by(ZOOM_STEP)
        )
        QShortcut(QKeySequence("="), self).activated.connect(
            lambda: self._zoom_by(ZOOM_STEP)
        )
        QShortcut(QKeySequence("-"), self).activated.connect(
            lambda: self._zoom_by(1 / ZOOM_STEP)
        )

    # ── Network ───────────────────────────────────────────────────────

    def refresh(self):
        url = f"{self.server_url}/capture?monitor={self.monitor}"
        self.bar.showMessage("Fetching…")
        QApplication.processEvents()

        try:
            t0 = time.monotonic()
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            elapsed = time.monotonic() - t0
        except Exception as exc:
            self.bar.showMessage(f"Error: {exc}")
            return

        self.raw_bytes = resp.content
        qimg = QImage.fromData(QByteArray(self.raw_bytes))
        self.original_pixmap = QPixmap.fromImage(qimg)

        if self.fit_mode:
            self._fit_to_screen()
        else:
            self._render()

        w, h = self.original_pixmap.width(), self.original_pixmap.height()
        mb = len(self.raw_bytes) / (1024 * 1024)
        self._update_status(f"Fetched {w}×{h} · {mb:.1f} MB · {elapsed:.2f}s")

    # ── Zoom / Pan ────────────────────────────────────────────────────

    def _render(self):
        """Redraw the image at the current zoom level."""
        if not self.original_pixmap:
            return

        if self.zoom_level == 1.0:
            pm = self.original_pixmap
        else:
            # >100 %: nearest-neighbour keeps individual pixels sharp
            # <100 %: bilinear avoids aliasing
            mode = (
                Qt.TransformationMode.FastTransformation
                if self.zoom_level >= 1.0
                else Qt.TransformationMode.SmoothTransformation
            )
            pm = self.original_pixmap.scaled(
                round(self.original_pixmap.width() * self.zoom_level),
                round(self.original_pixmap.height() * self.zoom_level),
                Qt.AspectRatioMode.KeepAspectRatio,
                mode,
            )

        self.image_label.setPixmap(pm)
        self.image_label.resize(pm.size())

    def _fit_to_screen(self):
        if not self.original_pixmap:
            return
        vp = self.scroll.viewport().size()
        sx = vp.width() / self.original_pixmap.width()
        sy = vp.height() / self.original_pixmap.height()
        self.zoom_level = min(sx, sy)
        self.fit_mode = True
        self._render()

    def toggle_fit(self):
        if self.fit_mode:
            self.zoom_level = 1.0
            self.fit_mode = False
            self._render()
            # centre view after switching to 1:1
            for sb in (self.scroll.horizontalScrollBar(),
                       self.scroll.verticalScrollBar()):
                sb.setValue(sb.maximum() // 2)
        else:
            self._fit_to_screen()
        self._update_status()

    def reset_zoom(self):
        self.zoom_level = 1.0
        self.fit_mode = False
        self._render()
        self._update_status()

    def _zoom_by(self, factor: float, anchor: QPoint | None = None):
        new = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom_level * factor))
        if new == self.zoom_level:
            return

        h_bar = self.scroll.horizontalScrollBar()
        v_bar = self.scroll.verticalScrollBar()

        if anchor is not None:
            img_x = (h_bar.value() + anchor.x()) / self.zoom_level
            img_y = (v_bar.value() + anchor.y()) / self.zoom_level

        self.zoom_level = new
        self.fit_mode = False
        self._render()

        if anchor is not None:
            h_bar.setValue(round(img_x * new - anchor.x()))
            v_bar.setValue(round(img_y * new - anchor.y()))

        self._update_status()

    # ── Save ──────────────────────────────────────────────────────────

    def save_frame(self):
        if not self.raw_bytes:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Frame", "capture.png", "PNG (*.png);;All Files (*)"
        )
        if path:
            with open(path, "wb") as fh:
                fh.write(self.raw_bytes)
            self.bar.showMessage(f"Saved → {path}")

    # ── Status bar ────────────────────────────────────────────────────

    def _update_status(self, prefix: str = ""):
        if not self.original_pixmap:
            return
        w, h = self.original_pixmap.width(), self.original_pixmap.height()
        pct = self.zoom_level * 100
        mode = "Fit" if self.fit_mode else "Free"
        parts = [p for p in [
            prefix,
            f"{w}×{h}",
            f"Zoom {pct:.0f}%",
            mode,
            "[R]efresh  [F]it  [1]00%  [S]ave  [Esc] Quit",
        ] if p]
        self.bar.showMessage("  ·  ".join(parts))

    # ── Events ────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode and self.original_pixmap:
            self._fit_to_screen()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is not self.scroll.viewport():
            return super().eventFilter(obj, event)

        t = event.type()

        # ── Wheel → zoom centred on cursor ──
        if t == QEvent.Type.Wheel:
            dy = event.angleDelta().y()
            if dy == 0:
                return True
            factor = ZOOM_STEP if dy > 0 else (1 / ZOOM_STEP)
            self._zoom_by(factor, anchor=event.position().toPoint())
            return True

        # ── Left-click drag → pan ──
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._drag_origin = event.globalPosition().toPoint()
            self.scroll.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return True

        if t == QEvent.Type.MouseMove and self._drag_active:
            pos = event.globalPosition().toPoint()
            delta = pos - self._drag_origin
            self._drag_origin = pos
            self.scroll.horizontalScrollBar().setValue(
                self.scroll.horizontalScrollBar().value() - delta.x()
            )
            self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().value() - delta.y()
            )
            return True

        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self.scroll.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return True

        return super().eventFilter(obj, event)


# ── Entry point ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ghost Monitor — Lossless Viewer",
    )
    parser.add_argument("host", help="PC server IP address or hostname")
    parser.add_argument("--port", type=int, default=5000, help="Server port (default: 5000)")
    parser.add_argument(
        "--monitor", type=int, default=2,
        help="Monitor index on the PC (default: 2)",
    )
    parser.add_argument(
        "--fit", action="store_true",
        help="Start in fit-to-screen mode instead of 1:1",
    )
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    app = QApplication(sys.argv)
    app.setApplicationName("Ghost Monitor")
    viewer = GhostViewer(url, monitor=args.monitor, start_fit=args.fit)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
