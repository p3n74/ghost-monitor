"""
Ghost Monitor — Lossless Screen Capture Server
Runs on the PC. Serves the contents of a chosen monitor as a lossless PNG
over the local network, on demand.
"""

import sys
import io
import argparse

from flask import Flask, send_file, jsonify, request
import mss
from PIL import Image

# Windows: capture at physical (not scaled) resolution
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor v2
    except Exception:
        pass

app = Flask(__name__)
default_monitor = 2


@app.route("/ping")
def ping():
    return jsonify({"status": "ok"})


@app.route("/monitors")
def monitors():
    """Return geometry of every monitor the OS reports."""
    with mss.mss() as sct:
        return jsonify([
            {
                "index": i,
                "left": m["left"],
                "top": m["top"],
                "width": m["width"],
                "height": m["height"],
            }
            for i, m in enumerate(sct.monitors)
        ])


@app.route("/capture")
def capture():
    """Grab a monitor and return it as a lossless PNG.

    Query params
    ------------
    monitor : int   — monitor index (0 = virtual-all, 1 = primary, 2+ = secondary)
    x, y, w, h      — optional crop rectangle in physical pixels
    """
    idx = request.args.get("monitor", default_monitor, type=int)

    with mss.mss() as sct:
        if idx >= len(sct.monitors):
            idx = 1
        shot = sct.grab(sct.monitors[idx])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    crop_x = request.args.get("x", None, type=int)
    crop_y = request.args.get("y", None, type=int)
    crop_w = request.args.get("w", None, type=int)
    crop_h = request.args.get("h", None, type=int)
    if all(v is not None for v in (crop_x, crop_y, crop_w, crop_h)):
        img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))

    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=1)  # lossless; 1 = fast encode
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


def print_banner(host: str, port: int):
    with mss.mss() as sct:
        print("\n  Ghost Monitor — Screen Capture Server")
        print("  ─────────────────────────────────────")
        print("  Monitors detected:")
        for i, m in enumerate(sct.monitors):
            tag = " (virtual-all)" if i == 0 else ""
            print(f"    [{i}] {m['width']}×{m['height']}  at ({m['left']}, {m['top']}){tag}")
        print(f"\n  Serving monitor {default_monitor}")
        print(f"  Listening on http://{host}:{port}")
        print()
        print("  Endpoints:")
        print("    GET /capture?monitor=N   — lossless PNG")
        print("    GET /capture?monitor=N&x=0&y=0&w=800&h=600  — cropped")
        print("    GET /monitors            — list monitors")
        print("    GET /ping                — health check")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ghost Monitor — Screen Capture Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument(
        "--monitor", type=int, default=2,
        help="Default monitor index: 0=all, 1=primary, 2+=secondary (default: 2)",
    )
    args = parser.parse_args()

    default_monitor = args.monitor
    print_banner(args.host, args.port)
    app.run(host=args.host, port=args.port, threaded=True)
