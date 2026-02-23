# IronSight Golf Simulator — Implementation Plan

## Context

Building a native macOS desktop app from scratch that connects to an OptiShot 2 USB swing pad, captures synchronized webcam video, visualizes ball flight in 3D, and provides AI coaching. The repo currently has only `README.md` and `project_plan.md`. The user has a physical OptiShot 2 for testing. We'll build incrementally across 6 phases, committing and pushing after each validated phase.

---

## Phase 0: Project Scaffold

**Goal:** Set up project structure, dependencies, shared models, and constants.

**Files to create:**

- `requirements.txt` — all pip dependencies
- `setup.py` — package metadata
- `.env.example` — template for API keys
- `src/__init__.py`
- `src/models/__init__.py`, `src/models/shot.py`, `src/models/club.py`, `src/models/session.py`
- `src/utils/__init__.py`, `src/utils/constants.py`, `src/utils/config.py`
- `src/database/__init__.py`
- `tests/__init__.py`

**Key details:**

- `constants.py`: Club lofts, smash factors, physics constants, OptiShot VID/PID (`0x0547`/`0x3294`)
- `shot.py`: Dataclasses for `ClubData`, `BallLaunch`, `Shot`
- `club.py`: Club enum with loft, smash factor, typical spin rates
- `config.py`: Settings manager (API key, camera index, device mode)
- Dependencies: `hidapi`, `PyQt6`, `PyQt6-WebEngine`, `opencv-python-headless`, `numpy`, `scipy`, `anthropic`

**Validation:** `pip install -r requirements.txt && python -c "from src.models.shot import Shot; print('OK')"`

**Commit:** `Phase 0: project scaffold — models, constants, dependencies`

---

## Phase 1: USB Communication Proof of Concept

**Goal:** CLI script that reads swing data from OptiShot 2 (or simulates it).

**Files to create:**

- `src/usb_reader.py` — real OptiShot HID reader
- `src/mock_usb_reader.py` — simulator generating realistic swing data
- `src/main.py` — CLI entry point with `--mock` flag
- `tests/test_usb_reader.py`

**Key classes:**

```
OptiShotReader(QThread):
    signals: swing_detected(Shot), device_connected(), device_disconnected(), error(str)
    Methods: run(), _init_device(), _poll_loop(), _parse_packet(data), _detect_swing()
    Protocol: VID 0x0547, PID 0x3294, 60-byte packets, 5-byte sub-packets
    Signatures: 0x81 (back sensors), 0x4A (front sensors)
    Speed calc: SENSORSPACING / (elapsed_time * 18) * 2236.94

MockOptiShotReader(QThread):
    Same signals interface. Generates random swings every 3-8 seconds.
    Presets: consistent_player, beginner, slicer
```

**USB Protocol (from RepliShot research):**

- 16 IR sensors (8 front, 8 back) at 48MHz
- Swing detection: back sensor signature `0x81` + front sensor `0x4A`
- Control commands: `0x50` (enable sensors), `0x52` (green LED), `0x80` (shutdown)
- 2500ms cooldown between valid swings
- Face angle: `atan(x_travel / y_travel) * 180 / PI`
- Path: `(max_front - max_back) + (min_front - min_back)`

**Validation:**

1. `python -m src.main --mock` → prints simulated swing data every few seconds
2. `python -m src.main` (with OptiShot plugged in) → prints real swing data on physical swing
3. `pytest tests/test_usb_reader.py` — unit tests for packet parsing

**Commit:** `Phase 1: USB communication — OptiShot HID reader + mock simulator`

---

## Phase 2: Camera + Swing Detection

**Goal:** Webcam records continuously; swing event triggers MP4 clip extraction.

**Files to create:**

- `src/camera.py`

**Key class:**

```
CameraCapture(QThread):
    signals: frame_ready(ndarray), clip_saved(str)
    Methods: run(), start_capture(), extract_clip(impact_timestamp) -> str
    Circular buffer: deque(maxlen=N) for last 4 seconds at 30fps
    On swing event: save 2 seconds before + 2 seconds after impact as MP4
    Output: ~/IronSight/clips/session_YYYYMMDD/shot_NNN.mp4
```

**Integration:** Wire `OptiShotReader.swing_detected` → `CameraCapture.extract_clip()`

**Validation:**

1. `python -m src.main --mock --camera` → shows live webcam preview, saves MP4 clips on each simulated swing
2. Verify clips are ~4 seconds long and capture the right window
3. Test with real OptiShot: swing → MP4 saved

**Commit:** `Phase 2: camera capture — circular buffer + swing-triggered clip extraction`

---

## Phase 3: Ball Flight Model

**Goal:** Convert club data to ball flight trajectory points.

**Files to create:**

- `src/ball_flight.py`
- `tests/test_ball_flight.py`
- `resources/trackman_validation/pga_averages.json`

**Key functions (adapted from cagrell/golfmodel, MacDonald & Hanzely 1991):**

```
club_to_ball_launch(club_data: ClubData) -> BallLaunch
    Converts club speed + face/path → ball speed, VLA, HLA, spin

compute_trajectory(launch: BallLaunch, wind_speed=0, wind_dir=0) -> TrajectoryResult
    ODE integration (scipy.integrate.solve_ivp) with drag + Magnus lift
    Returns: list of (x, y, z) points, carry_yards, total_yards, apex_yards

TrajectoryResult:
    points: list[tuple[float, float, float]]  # (x, y, z) in yards
    carry_yards: float
    total_yards: float
    apex_yards: float
    lateral_yards: float
    flight_time: float
```

**Physics model:**

- Drag: `F_drag = 0.5 * C_D * rho * A * v²`
- Lift (Magnus): `F_lift = 0.5 * C_L * rho * A * v²`
- C_D and C_L vary with spin ratio and Reynolds number
- ODE solved with `scipy.integrate.solve_ivp` (RK45)

**Validation against PGA Tour averages:**

- Driver (95mph club speed) → ~250 yard carry
- 7-Iron (85mph) → ~170 yard carry
- Wedge (75mph) → ~120 yard carry
- `pytest tests/test_ball_flight.py` — validates within ±15% of PGA averages

**Commit:** `Phase 3: ball flight physics — MacDonald & Hanzely trajectory model`

---

## Phase 4: Basic UI + 3D Visualization

**Goal:** PyQt6 window with Three.js driving range, video playback, shot data, session history.

**Files to create:**

- `src/main_window.py` — PyQt6 main window
- `src/visualizer/index.html` — Three.js scene (adapted from jcole/golf-shot-simulation)
- `src/visualizer/driving-range.js` — ground plane, markers, targets
- `src/visualizer/trajectory.js` — shot arc rendering + animation
- `src/visualizer/camera-controls.js` — orbit camera
- `src/visualizer/api.js` — `window.addShot()`, `window.clearShots()`
- `src/visualizer/styles.css` — stats overlay
- `src/visualizer/lib/three.min.js` — vendored Three.js
- `src/visualizer/lib/OrbitControls.js` — vendored orbit controls
- Update `src/main.py` to launch GUI

**Main window layout:**

```
┌──────────────────────────────────────────────┐
│ Toolbar: [Club Select] [Session] [Settings]  │
├───────────────────────┬──────────────────────┤
│  3D Ball Flight View  │  Swing Video Player  │
│  (QWebEngineView)     │  (QLabel + OpenCV)   │
├───────────────────────┴──────────────────────┤
│  Shot Data: Speed | Launch | Spin | Carry    │
├──────────────────────────────────────────────┤
│  Session History (scrollable shot list)       │
└──────────────────────────────────────────────┘
```

**Python↔JS bridge:**

- Python computes trajectory via `ball_flight.py`, serializes as JSON
- Calls `page().runJavaScript(f"window.addShot({json})")` on QWebEngineView
- Three.js animates the ball along the trajectory path

**Three.js driving range features:**

- Green ground plane with distance markers (50, 100, 150, 200, 250, 300 yards)
- Target circles at key distances
- Animated ball trajectory arc
- Previous shots persist (different opacity)
- Landing spot markers (dispersion pattern)
- Orbit camera (drag to rotate, scroll to zoom)
- Stats overlay

**Validation:**

1. `python -m src.main --mock` → full GUI with simulated swings showing 3D trajectories
2. `python -m src.main --mock --camera` → GUI + live webcam + video clips
3. `python -m src.main` (with OptiShot) → real swings → real trajectories
4. Click past shots in session history to replay trajectory + video

**Commit:** `Phase 4: PyQt6 UI + Three.js driving range visualization`

---

## Phase 5: Polish

**Goal:** Persistent data, session management, export, and packaging.

**Files to create/modify:**

- `src/database/schema.sql` — tables: sessions, shots, ai_feedback
- `src/database/db.py` — SQLite wrapper (create, insert, query)
- Update `src/main_window.py` — session management, CSV export, comparison view
- `setup_mac.py` — py2app configuration for .app bundle

**Features:**

- SQLite database at `~/.ironsight/ironsight.db`
- Auto-save every shot with session grouping
- Session history across app restarts
- CSV export of session data
- Shot comparison (overlay two trajectory arcs)
- Session statistics panel (averages, std dev, dispersion)
- py2app packaging as standalone macOS `.app`

**Validation:**

1. Close and reopen app → previous sessions load from database
2. Export session → valid CSV file
3. Select two shots → comparison overlay works
4. `python setup_mac.py py2app` → produces `dist/IronSight.app`

**Commit:** `Phase 5: persistence, session management, CSV export, macOS packaging`

---

## Phase 6: AI Swing Coach

**Goal:** Claude-powered swing analysis (per-shot video + data, session patterns, trends).

**Files to create:**

- `src/ai_coach.py`
- `tests/test_ai_coach.py`
- Update `src/main_window.py` — coaching panel, analyze buttons, settings
- Update `src/database/schema.sql` — ai_feedback table

**Key class:**

```
AISwingCoach:
    analyze_swing(shot) → str  # 4 video frames + shot data → Claude Sonnet
    analyze_session(shots) → str  # Aggregate stats (text-only, cheaper)
    analyze_trends(session_summaries) → str  # Multi-session comparison

AICoachThread(QThread):  # Non-blocking async analysis
    signals: analysis_complete(str, str), analysis_error(str)
```

**UI additions:** Coaching panel (read-only text), "Analyze Shot" + "Analyze Session" buttons, API key in settings

**Validation:**

1. Set `ANTHROPIC_API_KEY`, trigger swing, click "Analyze Shot" → feedback appears
2. 5+ swings → "Analyze Session" → pattern analysis
3. `pytest tests/test_ai_coach.py` — mocked API tests pass
4. UI stays responsive during analysis (async QThread)

**Commit:** `Phase 6: AI swing coach — Claude-powered video + session analysis`

---

## Architecture Summary

**Threading model (4 threads):**

1. **Main thread** — PyQt6 UI + QWebEngineView (Three.js)
2. **USB thread** (QThread) — OptiShot HID polling or mock generation
3. **Camera thread** (QThread) — OpenCV capture + circular buffer
4. **AI thread** (QThread, Phase 6) — Claude API calls

**Data flow:**

```
OptiShot USB → ClubData → club_to_ball_launch() → BallLaunch
→ compute_trajectory() → TrajectoryResult → JS bridge → Three.js animation
                                           → Camera clip extraction → MP4
                                           → SQLite persistence
                                           → (optional) AI analysis
```

**Key design decisions:**

- Physics computed in Python (scipy), not JavaScript — single source of truth, testable
- Mock reader is a first-class feature, not just for testing
- Three.js receives pre-computed trajectory points via `runJavaScript()` bridge
- All inter-thread communication via Qt signals (thread-safe)
