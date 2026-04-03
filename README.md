# Ghost Monitor

On-demand, lossless screen viewer from a Windows PC to a MacBook over the local network.

## Why this exists

I do heavy photo editing. My PC handles the workload fine, but its monitor is mediocre.
My MacBook M2 has a gorgeous display, but chokes on the editing software. Every existing
screen-sharing or remote-desktop tool I tried introduced compression, colour shifts, or
latency that defeated the whole point of using a better screen.

I don't need a live stream. I just need to pause, hit a key, and see the exact pixels
my PC is rendering — no resampling, no chroma sub-sampling, no "good enough" JPEG.
So I built this.

**Ghost Monitor** is a two-part tool: a capture server on the PC and a viewer on the Mac.
The server grabs the raw pixel buffer of a chosen monitor and serves it as a lossless PNG
over HTTP. The viewer fetches it on demand and displays it in a full-screen window with
1:1 zoom, pan, and cursor-anchored scroll-zoom. That's it. No daemon, no streaming
protocol, no config files — just a Flask endpoint and a Qt window.

## Architecture

```
┌─────────────┐   HTTP GET /capture   ┌─────────────┐
│  PC Server  │ ◄──────────────────── │  Mac Viewer  │
│  (Flask)    │ ─── lossless PNG ───► │  (PySide6)   │
└─────────────┘                       └─────────────┘
         LAN (Wi-Fi / Ethernet)
```

The server uses `mss` for screen capture and Pillow to encode PNG with `compress_level=0`
(no zlib compression in the PNG stream — still lossless; larger files and slightly faster
encode than higher levels). Transfer size varies a lot with content; expect **larger**
files than zlib-compressed PNGs (often several MB at 1080p+). Capture + encode still takes
on the order of ~100 ms for 1080p on a typical PC. Over a home network that's usually fine.

The viewer is a PySide6 app. At 100% zoom it shows raw, unscaled pixels — no
interpolation. Each pixmap uses the window’s `devicePixelRatio()` so **one capture
pixel maps to one physical LCD pixel** on Retina / HiDPI (not 2×2 physical pixels
from treating the image as 1:1 logical points). Zooming past 100% uses nearest-neighbour
so you see clean pixel squares. Zooming out uses bilinear to avoid aliasing.

## Setup

### PC (Server)

```bash
cd server
pip install -r requirements.txt
python server.py --monitor 2
```

`--monitor 2` targets the second display. Monitor indices: `0` = virtual combined,
`1` = primary, `2`+ = secondary. The server prints detected monitors on startup so you
can verify the right one is selected.

You'll need to allow inbound TCP on port 5000 through Windows Firewall for your LAN
subnet. Easiest way: add an inbound rule for Python or for port 5000 scoped to
`192.168.0.0/16`.

### Mac (Viewer)

Copy the `viewer/` folder to the MacBook, then:

```bash
cd viewer
pip install -r requirements.txt
python viewer.py 192.168.x.x
```

Replace the IP with your PC's local address (`ipconfig` on the PC to find it).

The viewer opens full-screen at 1:1 zoom (one capture pixel per physical display pixel
on the Mac). Pass `--fit` to start fitted to the screen instead.

## Controls

| Input | Action |
|---|---|
| **R** | Fetch a new frame from the PC |
| **F** | Toggle fit-to-screen / free zoom |
| **1** | Jump to 100% zoom |
| **+** / **=** | Zoom in |
| **-** | Zoom out |
| **S** | Save current frame as PNG |
| **Scroll wheel** | Zoom (anchored on cursor position) |
| **Left-click drag** | Pan |
| **Escape** | Quit |

## API

| Endpoint | Description |
|---|---|
| `GET /capture?monitor=N` | Lossless PNG of monitor N |
| `GET /capture?monitor=N&x=0&y=0&w=800&h=600` | Cropped region |
| `GET /monitors` | JSON list of monitors and their geometry |
| `GET /ping` | Health check |

## Things to know

- **Truly lossless.** PNG preserves every pixel. No JPEG, no chroma sub-sampling, no
  quantisation.

- **DPI-aware on Windows.** The server calls `SetProcessDpiAwareness(2)` so it captures
  at physical resolution even if you're running 125% or 150% display scaling.

- **8-bit sRGB ceiling.** Windows screen capture via GDI/DWM outputs 8-bit sRGB. If
  you're working in a 10-bit or HDR pipeline, the captured frame won't reflect that. For
  inspecting sharpness and detail this doesn't matter; for final colour sign-off, be
  aware of the limitation.

- **P3 vs sRGB.** The MacBook display is P3 wide-gamut. Captured data is sRGB. Colours
  may appear slightly more saturated on the Mac. If that bothers you, temporarily assign
  an sRGB profile to the Mac display while viewing.

## Stack

- **Server:** Python, Flask, mss, Pillow
- **Viewer:** Python, PySide6, Pillow, Requests
