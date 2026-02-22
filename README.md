# IronSight Golf Simulator

A native macOS desktop application that connects to an OptiShot 2 swing pad via USB, captures synchronized webcam video, visualizes ball flight in a 3D driving range, and provides AI-powered swing coaching.

## Features

- **OptiShot 2 USB Integration** — Reads swing data directly from the OptiShot 2 swing pad (32 IR sensors, 16 front + 16 back)
- **Ball Flight Physics** — MacDonald & Hanzely (1991) trajectory model with drag, lift (Magnus effect), and wind
- **3D Driving Range** — Three.js visualization with animated trajectories, distance markers, and dispersion patterns
- **Webcam Capture** — Circular buffer captures swing video clips automatically on each swing
- **AI Swing Coach** — Claude-powered analysis of swing video frames and session patterns
- **Session Tracking** — SQLite persistence with session history, stats, and CSV export
- **Mock Mode** — Full simulation without hardware for development and demo

## Quick Start

```bash
# Clone and set up
git clone https://github.com/YOUR_USER/ironsight-golf-simulator.git
cd ironsight-golf-simulator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run in mock mode (no hardware needed)
python -m src.main --mock --gui

# Run with OptiShot 2 connected
python -m src.main --gui

# Run with camera
python -m src.main --mock --gui --camera

# CLI mode (no GUI)
python -m src.main --mock --preset slicer --club Driver
```

## Architecture

```
OptiShot USB → ClubData → Ball Flight Physics → TrajectoryResult
                                                  ↓
                     PyQt6 UI ←── JS Bridge ──→ Three.js Driving Range
                        ↓
                   Camera Clips → AI Coach (Claude API)
                        ↓
                   SQLite Database
```

## Project Structure

```
src/
├── main.py              # Entry point (CLI + GUI)
├── usb_reader.py        # OptiShot 2 USB HID communication
├── mock_usb_reader.py   # Simulated swing data (5 player presets)
├── camera.py            # Webcam capture with circular buffer
├── ball_flight.py       # Ball flight physics (ODE integration)
├── main_window.py       # PyQt6 GUI with Three.js visualization
├── ai_coach.py          # Claude-powered swing analysis
├── models/              # Data models (Shot, Club, Session)
├── database/            # SQLite persistence (schema + queries)
├── utils/               # Constants, config management
└── visualizer/          # Three.js driving range (HTML/JS/CSS)
```

## Testing

```bash
python -m pytest tests/ -v
```

52 tests covering USB parsing, ball flight physics (validated against PGA Tour averages), and AI coach.

## Requirements

- Python 3.11+
- macOS (tested on Apple Silicon)
- OptiShot 2 swing pad (optional — mock mode available)
- Webcam (optional — for swing video capture)
- Anthropic API key (optional — for AI coaching, Phase 6)

## Tech Stack

- **PyQt6** + **PyQt6-WebEngine** — Native GUI with embedded web view
- **Three.js** — 3D driving range visualization
- **OpenCV** — Webcam capture and video processing
- **hidapi** — USB HID communication with OptiShot 2
- **SciPy** — ODE integration for ball flight physics
- **Anthropic Claude API** — AI swing coaching
- **SQLite** — Session and shot data persistence
