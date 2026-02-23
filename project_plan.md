# IronSight Golf Simulator — Project Plan

**Repository:** `ironsight-golf-simulator` (public)

## Project Overview

IronSight is a native macOS desktop application that connects to an OptiShot 2 swing pad via USB, captures swing data (club speed, face angle, path, tempo), records synchronized webcam video of each swing, visualizes the resulting ball flight in a 3D driving range, and provides AI-powered swing coaching — all in a unified training interface.

---

## Platform: macOS

The OptiShot 2 pad communicates over USB and **did have a macOS version** of its official software (v3.2.x as a `.dmg`), confirming the USB hardware works on Mac. The official software is now end-of-life, but since we're building custom software that reads raw USB data, that doesn't matter.

**macOS works because:**

- The OptiShot 2 pad is a standard USB HID device — macOS can enumerate and communicate with it
- `libusb` and `hidapi` both work on macOS (via Homebrew)
- OpenCV webcam capture works natively on macOS
- Three.js visualization runs in any browser/web view
- Python + PyQt6 is fully supported on macOS (Apple Silicon included)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│              IronSight Golf Simulator (PyQt6)            │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │  USB Module  │  │ Camera Module│  │  Viz Module     │ │
│  │  (hidapi /   │  │ (OpenCV)     │  │  (Three.js      │ │
│  │   libusb)    │  │              │  │   driving range)│ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬──────────┘ │
│         │                  │                  │          │
│  ┌──────▼──────────────────▼──────────────────▼─────────┐│
│  │              Event Bus / Shot Dispatcher             ││
│  │  - Detects swing from USB data                       ││
│  │  - Triggers video clip extraction                    ││
│  │  - Computes ball flight from club data               ││
│  │  - Sends shot to visualizer                          ││
│  └────────────────────────┬─────────────────────────────┘│
│                           │                              │
│  ┌────────────────────────▼─────────────────────────────┐│
│  │              Data / Session Storage                  ││
│  │  SQLite: shots, sessions, video paths, AI feedback   ││
│  └────────────────────────┬─────────────────────────────┘│
│                           │                              │
│  ┌────────────────────────▼─────────────────────────────┐│
│  │         AI Swing Coach (Phase 6)                     ││
│  │  Claude API: video frames + shot data → coaching tips││
│  │  - Per-shot feedback (swing video + club data)       ││
│  │  - Session-level pattern analysis                    ││
│  │  - Trend tracking across sessions                    ││
│  └──────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────┘
```

---

## Tech Stack (Recommended)

| Component               | Technology                             | Rationale                                                               |
| ----------------------- | -------------------------------------- | ----------------------------------------------------------------------- |
| **Language**            | Python 3.11+                           | Fast prototyping, great USB/CV libs, Claude Code works well with Python |
| **UI Framework**        | PyQt6                                  | Native look on macOS, supports web engine for Three.js, cross-platform  |
| **USB Communication**   | `hidapi` (via `pip install hidapi`)    | Simpler than raw libusb for HID devices; fallback to `pyusb` if needed  |
| **Webcam Capture**      | OpenCV (`cv2`)                         | Industry standard, easy circular buffer, works on macOS                 |
| **3D Ball Flight Viz**  | Three.js in QWebEngineView             | Fork jcole/golf-shot-simulation; richest visuals, hot-reloadable        |
| **Ball Flight Physics** | `cagrell/golfmodel` (Python)           | Peer-reviewed physics, already in Python, easy to vendor                |
| **AI Swing Coach**      | Anthropic Claude API (Sonnet)          | Vision capability for frame analysis + reasoning for coaching tips      |
| **Data Storage**        | SQLite (via `sqlite3`)                 | Zero config, stores shots/sessions/video metadata/AI feedback           |
| **Video Storage**       | MP4 files on disk (OpenCV VideoWriter) | Clips saved per-shot, path stored in SQLite                             |
| **Packaging**           | PyInstaller or `py2app`                | Bundle as standalone macOS `.app`                                       |

---

## Visualization: Custom Driving Range

We're building our own 3D driving range visualization. The good news: there are excellent open-source projects to borrow from that handle the hard parts (ball flight physics and 3D rendering).

### Open Source Projects to Leverage

#### 1. `jcole/golf-shot-simulation` (Three.js) ⭐ PRIMARY REFERENCE

- **GitHub:** https://github.com/jcole/golf-shot-simulation
- **What it does:** Complete 3D golf shot visualization using Three.js with sliders for club speed, attack angle, path, backspin, and spin axis. Renders trajectory arc in 3D with a green driving range scene.
- **Physics:** Models gravity, drag, and lift (Magnus effect). Uses Euler integration.
- **Why use it:** This is almost exactly the visualization we need. It's a single `index.html` + JS files. We can embed this in our PyQt app via QWebEngineView, or port it to a standalone Electron/web view. The Three.js scene already has a driving range ground plane, trajectory rendering, and input controls.
- **Inputs match our data:** club speed, vertical angle, horizontal angle, backspin RPM, spin axis — all derivable from OptiShot data.

#### 2. `gdifiore/libgolf` (C++ library)

- **GitHub:** https://github.com/gdifiore/libgolf
- **What it does:** Full trajectory simulation with aerial → bounce → roll phase transitions, dynamic ground surfaces (fairway, rough, green), 3D terrain with slopes.
- **Physics:** Based on Prof. Alan Nathan's research (Univ. of Illinois). More scientifically rigorous than the Three.js version.
- **Why use it:** If we want more accurate ball flight physics (especially bounce and roll), we can call this from Python via ctypes/cffi, or port the math to Python. Great reference for the ball flight model.

#### 3. `cagrell/golfmodel` (Python)

- **GitHub:** https://github.com/cagrell/golfmodel
- **What it does:** Python golf ballistics model based on MacDonald & Hanzely (1991) physics paper. Takes velocity, launch angle, spin RPM, spin axis, wind speed/heading as inputs.
- **Why use it:** It's already in Python! Can be directly integrated as our ball flight engine. Clean, well-documented physics code.

#### 4. `JRhodes95/Golf-Ball-Trajectory-Modelling-in-Python`

- **GitHub:** https://github.com/JRhodes95/Golf-Ball-Trajectory-Modelling-in-Python
- **What it does:** Another Python trajectory model, good for cross-referencing physics.

#### 5. `csites/Seneca-Golf` (Urho3D, C++)

- **GitHub:** https://github.com/csites/Seneca-Golf
- **What it does:** Full open-source golf simulator built on Urho3D engine. The creator actually started with an OptiShot as their launch monitor. Has terrain mapping, ball physics, course rendering.
- **Why use it:** Reference for what a full golf sim looks like. Urho3D is cross-platform (runs on Mac), but this project is very early stage. Better as inspiration than as a foundation.

### Recommended Visualization Architecture

**Approach: Three.js driving range embedded in PyQt via QWebEngineView**

This is the fastest path to a good-looking, interactive 3D driving range on Mac:

```
┌─────────────────────────────────────────┐
│           PyQt6 Main Window             │
│                                         │
│  ┌────────────────┐  ┌────────────────┐ │
│  │ QWebEngineView │  │ Video Player   │ │
│  │ (Three.js      │  │ (OpenCV +      │ │
│  │  driving range)│  │  QLabel)       │ │
│  │                │  │                │ │
│  │ - 3D ground    │  │ - Live preview │ │
│  │ - Trajectory   │  │ - Swing replay │ │
│  │ - Targets      │  │ - Slow-mo      │ │
│  │ - Dispersion   │  │ - Draw tools   │ │
│  └────────────────┘  └────────────────┘ │
│                                         │
│  ┌─────────────────────────────────────┐│
│  │  Shot Data + Session History        ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

**Why Three.js in a web view instead of native OpenGL:**

- The `jcole/golf-shot-simulation` project gives us 80% of the viz for free
- Three.js is much easier to iterate on than raw PyOpenGL
- Hot-reloading the HTML/JS during development (no recompile)
- Can later extract the viz as a standalone web app if wanted
- QWebEngineView communicates with Python via JavaScript bridge (`page.runJavaScript()`)

**Communication flow:**

```
USB swing detected → Python computes ball flight (using cagrell/golfmodel)
    → Python calls JS bridge: page.runJavaScript("addShot({...})")
    → Three.js animates the trajectory in 3D
    → Simultaneously: video clip extracted from circular buffer
```

### Driving Range Scene Features (MVP)

1. **Green ground plane** with distance markers (50, 100, 150, 200, 250, 300 yards)
2. **Target circles** at key distances
3. **Ball trajectory arc** — animated ball flying along the computed path
4. **Trail persistence** — previous shots stay visible (different colors/opacity)
5. **Dispersion pattern** — landing spots accumulate to show your shot pattern
6. **Orbit camera** — click and drag to rotate view, scroll to zoom
7. **Stats overlay** — club speed, ball speed, carry, total, launch angle, spin

### Future Viz Enhancements

- Shot shape labels (draw, fade, slice, hook, straight)
- Wind simulation
- Elevation targets (uphill/downhill)
- Split-screen shot comparison
- Heat map of landing zones

---

## Module Breakdown (for Claude Code implementation)

### Module 1: USB Communication (`usb_reader.py`)

**Goal:** Read raw swing data from OptiShot 2 pad over USB.

**Key reference:** RepliShot source code (`github.com/zaren171/RepliShot`)

**Tasks:**

1. Enumerate USB devices, find OptiShot 2 by vendor/product ID
2. Open HID connection and read interrupt transfers
3. Parse raw byte data into swing metrics:
   - Club head speed (mph)
   - Face angle (degrees open/closed)
   - Swing path (degrees in-to-out / out-to-in)
   - Face contact point
   - Tempo (backswing/downswing ratio)
4. Detect "swing event" (transition from idle → backswing → impact → follow-through)
5. Emit swing event with parsed data to event bus

**USB Sniffing Setup (for reverse engineering):**

```bash
# macOS: use Wireshark with USBPcap equivalent
brew install wireshark
# Or use the `hidapi` enumerate to find device
python -c "import hid; [print(d) for d in hid.enumerate()]"
```

**Implementation notes:**

- Run USB polling on a background thread (QThread)
- The OptiShot has 16 IR sensors at 48MHz — data comes as packets with front/back sensor readings
- A valid swing has data from both front and back sensor rows
- Front sensor only = club change gesture (used by RepliShot for club selection)

### Module 2: Camera Capture (`camera.py`)

**Goal:** Continuously record webcam, extract clip around each swing.

**Tasks:**

1. Open webcam via OpenCV (`cv2.VideoCapture`)
2. Maintain circular buffer of last N seconds (e.g., 4 seconds at 30fps = 120 frames)
3. On swing event from USB module:
   - Mark the frame timestamp at impact
   - Continue recording for 2 more seconds (follow-through)
   - Extract frames from 2 seconds before impact to 2 seconds after
   - Write clip to MP4 file
4. Provide live preview feed to UI

**Implementation notes:**

- Use `collections.deque(maxlen=120)` for circular buffer
- Run capture on dedicated thread
- Consider recording at 60fps if camera supports it (smoother swing playback)
- Allow slow-motion playback (0.25x, 0.5x) in the UI
- Store video path in SQLite linked to shot record

### Module 3: Ball Flight Model (`ball_flight.py`)

**Goal:** Two-stage model: (1) convert club data → ball launch conditions, (2) simulate trajectory.

The OptiShot 2 only measures club data. We need two things: a club-to-ball conversion model and a trajectory physics engine.

#### Stage 1: Club Data → Ball Launch Conditions

**Inputs (from USB):**

- Club head speed (mph)
- Face angle at impact (degrees)
- Club path (degrees in-to-out)
- Face contact point
- Club type (driver, iron, wedge, putter)

**Outputs (estimated launch conditions):**

- Ball speed (from smash factor × club speed)
- Vertical launch angle (VLA)
- Horizontal launch angle (HLA)
- Backspin RPM
- Sidespin RPM / spin axis

```python
# Club-to-ball conversion
def club_to_ball(club_speed, face_angle, path, club_type):
    smash_factor = SMASH_FACTORS[club_type]  # ~1.48 driver, ~1.38 irons
    ball_speed = club_speed * smash_factor

    base_loft = CLUB_LOFTS[club_type]
    dynamic_loft = base_loft + (face_angle * 0.7)
    vla = dynamic_loft * 0.75

    # D-Plane: face contributes ~75% to initial direction (irons)
    hla = face_angle * 0.75 + path * 0.25
    face_to_path = face_angle - path

    backspin = estimate_backspin(ball_speed, dynamic_loft, club_type)
    spin_axis = math.degrees(math.atan2(face_to_path * SPIN_TILT_FACTOR, backspin))

    return BallLaunch(ball_speed, vla, hla, backspin, spin_axis)
```

#### Stage 2: Trajectory Simulation

**Start by forking `cagrell/golfmodel`** (Python, already has the physics):

- Based on MacDonald & Hanzely (1991) peer-reviewed physics
- Takes velocity, launch angles, spin RPM, spin axis, wind as inputs
- Outputs (x, y, z) position arrays — exactly what we feed to Three.js

**Cross-reference with `libgolf`** (C++) for bounce/roll physics if we want landing behavior.

**Cross-reference with `jcole/golf-shot-simulation`** (JS) which also models drag + lift and has Trackman test data for validation (even though tests don't pass yet — we can improve on this).

**Validation data:**

- TrackMan "New Ball Flight Laws" and PGA Tour averages
- The `jcole` repo includes `test/spec/trackman-data.js` with real Trackman shot data
- PGA Tour average carry distances by club for sanity checking

### Module 4: 3D Visualization (`visualizer/`)

**Goal:** Render ball flight on a 3D driving range, embedded in the PyQt app.

**Approach: Fork `jcole/golf-shot-simulation` and embed via QWebEngineView**

The `jcole/golf-shot-simulation` repo is a Three.js app that already renders:

- A 3D driving range scene
- Ball trajectory arcs with gravity, drag, and lift
- Input sliders for club speed, angles, spin
- Animated ball flight

We adapt it to:

1. Remove the manual sliders (our data comes from the OptiShot)
2. Add a JS API that Python can call: `window.addShot(shotData)`
3. Add persistent shot trails (dispersion pattern)
4. Add distance markers and target circles
5. Add an overhead/top-down view toggle
6. Improve the ground plane (color-coded distance bands)

**File structure:**

```
src/visualizer/
├── index.html          # Main Three.js scene (forked from jcole)
├── driving-range.js    # Scene setup: ground, markers, targets
├── trajectory.js       # Shot rendering + animation (from jcole, adapted)
├── physics.js          # Ball flight physics (from jcole, improved)
├── camera-controls.js  # Orbit controls
├── api.js              # window.addShot(), window.clearShots(), etc.
└── styles.css          # Stats overlay styling
```

**Python ↔ JavaScript bridge:**

```python
# In PyQt, after computing ball flight:
shot_json = json.dumps({
    "ballSpeed": 147.5,
    "vla": 14.3,
    "hla": 2.3,
    "backspin": 3250,
    "spinAxis": -13.2,
    "carry": 245,
    "clubType": "driver",
    "clubSpeed": 95.0
})
self.web_view.page().runJavaScript(f"window.addShot({shot_json})")
```

```javascript
// In api.js — called from Python
window.addShot = function (data) {
  const trajectory = computeTrajectory(data);
  renderTrajectoryArc(trajectory);
  animateBall(trajectory);
  addLandingMarker(trajectory.landing);
  updateStatsOverlay(data);
};
```

**Alternative (simpler start):** Use Matplotlib 3D for a quick prototype, then upgrade to Three.js once the pipeline works end-to-end.

### Module 5: Main UI (`main_window.py`)

**Goal:** Unified training interface.

**Layout (PyQt6):**

```
┌──────────────────────────────────────────────────┐
│  Toolbar: [Club Select] [Session] [Settings]     │
├────────────────────────┬─────────────────────────┤
│                        │                         │
│   3D Ball Flight View  │   Swing Video Player    │
│   (QOpenGLWidget)      │   (QVideoWidget or      │
│                        │    OpenCV display)      │
│                        │                         │
├────────────────────────┴─────────────────────────┤
│  Shot Data Panel                                 │
│  Club Speed: 95mph | Ball Speed: 140mph |        │
│  Launch: 14.3° | Spin: 3250rpm | Carry: 245yd    │
├──────────────────────────────────────────────────┤
│  Session History (scrollable list of shots)      │
│  #1: Driver 253yd | #2: 7-iron 165yd | ...       │
└──────────────────────────────────────────────────┘
```

**Key interactions:**

- Select any past shot to replay video + trajectory
- Slow-motion controls on video (0.25x, 0.5x, 1x)
- Drawing tools on video freeze-frame (lines for swing plane, etc.) — stretch goal
- Export session data to CSV
- Side-by-side comparison of two swings — stretch goal

### Module 6: AI Swing Coach (`ai_coach.py`)

**Goal:** Use Claude's vision + reasoning to analyze swing video and shot data, providing personalized coaching feedback after each swing and session-level pattern analysis.

**This module is added AFTER Phases 1-5 are validated and working.** It depends on reliable shot data, video capture, and session history all functioning correctly.

#### Analysis Modes

**A) Per-Shot Analysis (video + data)**

After each swing, extract key frames from the video and send them alongside the shot data to Claude for visual swing analysis:

```python
import anthropic
import base64
import cv2

class AISwingCoach:
    def __init__(self):
        self.client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

    def analyze_swing(self, video_path: str, shot: Shot) -> str:
        """Analyze a single swing using video frames + shot data."""

        # Extract key frames: address, top of backswing, impact, follow-through
        frames = self._extract_key_frames(video_path)
        frame_images = [self._frame_to_base64(f) for f in frames]

        content = []
        labels = ["Address", "Top of backswing", "Impact", "Follow-through"]
        for img_b64, label in zip(frame_images, labels):
            content.append({
                "type": "text",
                "text": f"**{label}:**"
            })
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_b64
                }
            })

        content.append({
            "type": "text",
            "text": f"""Analyze this golf swing. Here is the shot data from the launch monitor:

Club: {shot.club_type}
Club Speed: {shot.club_speed} mph
Face Angle: {shot.face_angle}° ({"open" if shot.face_angle > 0 else "closed"})
Club Path: {shot.path}° ({"in-to-out" if shot.path > 0 else "out-to-in"})
Face-to-Path: {shot.face_angle - shot.path}°
Carry Distance: {shot.carry} yards
Shot Shape: {shot.shot_shape}

Based on the video frames and data:
1. What is the golfer doing well?
2. What is the primary swing fault visible in the video?
3. Give ONE specific drill or feel to fix it.

Be concise and specific. Reference what you see in the frames."""
        })

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": content}]
        )
        return response.content[0].text

    def _extract_key_frames(self, video_path: str) -> list:
        """Extract 4 key frames from swing video."""
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # Approximate positions: 10%, 35%, 50%, 75% through the clip
        positions = [0.10, 0.35, 0.50, 0.75]
        frames = []
        for pos in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total_frames * pos))
            ret, frame = cap.read()
            if ret:
                # Resize to reduce token usage
                frame = cv2.resize(frame, (640, 480))
                frames.append(frame)
        cap.release()
        return frames

    def _frame_to_base64(self, frame) -> str:
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode('utf-8')
```

**B) Session Pattern Analysis (data-only, cheaper)**

After a practice session, analyze the aggregate shot data for patterns without needing video:

```python
    def analyze_session(self, shots: list[Shot]) -> str:
        """Analyze patterns across a full session."""
        stats = {
            "club": shots[0].club_type,
            "num_shots": len(shots),
            "avg_club_speed": round(mean(s.club_speed for s in shots), 1),
            "avg_face_angle": round(mean(s.face_angle for s in shots), 1),
            "std_face_angle": round(stdev(s.face_angle for s in shots), 1),
            "avg_path": round(mean(s.path for s in shots), 1),
            "avg_carry": round(mean(s.carry for s in shots), 1),
            "std_carry": round(stdev(s.carry for s in shots), 1),
            "miss_left_pct": round(sum(1 for s in shots if s.hla < -2) / len(shots) * 100),
            "miss_right_pct": round(sum(1 for s in shots if s.hla > 2) / len(shots) * 100),
        }

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": f"""You are a PGA-certified golf coach.
Analyze this practice session data and identify patterns:

{json.dumps(stats, indent=2)}

Provide:
1. The primary consistency issue you see in the data
2. What this pattern usually indicates about the swing
3. Two specific practice drills to address it
4. What to focus on next session

Be direct and actionable, not generic."""}]
        )
        return response.content[0].text
```

**C) Trend Analysis (across sessions)**

Track progress over multiple sessions:

```python
    def analyze_trends(self, session_history: list[SessionSummary]) -> str:
        """Compare the last N sessions to identify improvement or regression."""
        # Feed session-over-session stats to Claude
        # "Your face angle consistency improved from ±4.2° to ±2.8° over 3 weeks"
        # "Club speed trending up but carry isn't — check strike quality"
        ...
```

#### Key Design Decisions

- **Claude Sonnet for per-shot analysis** — good balance of vision capability and cost. Each 4-frame analysis costs roughly $0.01-0.02.
- **Session analysis is text-only** — no video frames needed, much cheaper (~$0.002 per session).
- **Analysis is async and non-blocking** — the UI doesn't wait for the API response. A coaching panel updates when the response arrives.
- **User controls when to analyze** — not every shot needs AI feedback. Options: "Analyze this shot", "Analyze session", or auto-analyze every Nth shot.
- **Store AI feedback in SQLite** — linked to shot/session records for historical reference.
- **API key management** — user provides their own Anthropic API key in settings (or we could bundle a limited key for demo purposes).

---

## Implementation Phases (for Claude Code)

### Phase 1: USB Communication Proof of Concept

**Goal:** Prove you can read data from the OptiShot 2 on macOS.

1. Install `hidapi` via pip
2. Enumerate USB devices, identify OptiShot 2 vendor/product IDs
3. Read raw data packets and log them
4. Cross-reference with RepliShot's parsing logic
5. Parse a swing event with club speed and face angle

- **Deliverable:** CLI script that prints shot data when you swing

### Phase 2: Camera + Swing Detection

**Goal:** Record synchronized video clips.

1. OpenCV webcam capture with circular buffer
2. Wire up USB swing event to trigger clip extraction
3. Save MP4 clips to disk

- **Deliverable:** Swing → MP4 clip saved automatically

### Phase 3: Ball Flight Model

**Goal:** Convert club data to ball flight.

1. Implement basic ball flight physics (projectile + drag)
2. Validate against known PGA averages
3. Tune smash factors and spin models

- **Deliverable:** Given club data → trajectory points array

### Phase 4: Basic UI + 3D Visualization

**Goal:** Unified interface with all components.

1. PyQt6 window layout (split view)
2. Three.js driving range scene (forked from jcole/golf-shot-simulation) in QWebEngineView
3. Python↔JS bridge for sending shot data to visualizer
4. Video playback panel with slow-motion
5. Shot data display
6. Session history

- **Deliverable:** Full working training app

### Phase 5: Polish

1. Shot comparison (overlay two trajectories)
2. Drawing tools on video
3. Session statistics / trends
4. Export to CSV
5. Package as standalone macOS app with py2app

### Phase 6: AI Swing Coach

**Prerequisite:** Phases 1-5 validated and working correctly.
**Goal:** Add Claude-powered swing analysis.

1. Implement per-shot video frame extraction (4 key frames)
2. Build Claude Vision API integration for single-swing analysis
3. Build session pattern analysis (text-only, aggregate stats)
4. Add coaching panel to UI (async, non-blocking)
5. Store AI feedback in SQLite linked to shots/sessions
6. Add user controls: "Analyze Shot" button, auto-analyze toggle
7. Trend analysis across sessions

- **Deliverable:** AI coaching tab that provides actionable feedback on swings and practice patterns

---

## Key Dependencies

```bash
# Core
pip install PyQt6 PyQt6-WebEngine opencv-python-headless hidapi numpy scipy

# Ball flight physics (fork cagrell/golfmodel or vendor it)
# Already pure Python + numpy, no extra deps

# AI Swing Coach (Phase 6)
pip install anthropic

# Data
# sqlite3 is built-in, no install needed

# Optional
pip install pyinstaller    # for packaging as macOS .app

# For the Three.js visualizer:
# No Python deps — it's vendored HTML/JS loaded via QWebEngineView
# Clone jcole/golf-shot-simulation into src/visualizer/ as starting point
```

---

## Key Risks & Mitigations

| Risk                                     | Impact | Mitigation                                                                                                         |
| ---------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------ |
| OptiShot 2 USB protocol not documented   | High   | RepliShot source code exists; use USB sniffing with Wireshark                                                      |
| macOS USB permissions (HID access)       | Medium | May need to sign app or adjust TCC/privacy settings; `hidapi` handles most cases                                   |
| Ball flight accuracy from club-only data | Medium | Start with published formulas; tune with real-world comparison; this is a training tool, not tournament-grade      |
| Camera latency vs swing timing           | Low    | Circular buffer approach eliminates this; 30fps gives ~33ms granularity                                            |
| AI analysis quality from low-res webcam  | Medium | Use 640x480 frames to balance quality vs token cost; prompt engineering to focus on body positions not fine detail |
| AI API cost at high usage                | Low    | Session analysis is text-only (~$0.002); per-shot video analysis ~$0.01-0.02; user controls frequency              |

---

## File Structure for Claude Code

```
ironsight-golf-simulator/
├── README.md
├── LICENSE
├── requirements.txt
├── setup.py
├── .env.example                # ANTHROPIC_API_KEY=sk-ant-...
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── usb_reader.py           # Module 1: OptiShot USB communication
│   ├── camera.py               # Module 2: Webcam capture + clip extraction
│   ├── ball_flight.py          # Module 3: Club → ball flight physics
│   │                           #   (forked from cagrell/golfmodel)
│   ├── main_window.py          # Module 5: PyQt6 UI
│   ├── ai_coach.py             # Module 6: Claude-powered swing analysis
│   ├── visualizer/             # Module 4: Three.js driving range
│   │   ├── index.html          #   (forked from jcole/golf-shot-simulation)
│   │   ├── driving-range.js    #   Scene: ground, markers, targets
│   │   ├── trajectory.js       #   Shot rendering + animation
│   │   ├── physics.js          #   JS-side physics (from jcole, kept for animation)
│   │   ├── camera-controls.js  #   Orbit controls
│   │   ├── api.js              #   Python↔JS bridge: addShot(), clearShots()
│   │   ├── styles.css          #   Overlay styling
│   │   └── lib/                #   Three.js + OrbitControls (vendored)
│   ├── models/
│   │   ├── shot.py             # Shot data model
│   │   ├── session.py          # Session model
│   │   └── club.py             # Club definitions (lofts, smash factors)
│   ├── database/
│   │   ├── db.py               # SQLite setup + queries
│   │   └── schema.sql          # Table definitions (incl. ai_feedback table)
│   └── utils/
│       ├── config.py           # App settings (incl. API key management)
│       └── constants.py        # Club data, physics constants
├── tests/
│   ├── test_usb_reader.py
│   ├── test_ball_flight.py
│   ├── test_ai_coach.py
└── resources/
    ├── icon.icns               # macOS app icon
    └── trackman_validation/    # PGA Tour / Trackman data for physics validation
```

---

## Claude Code Prompt Strategy

When working with Claude Code, tackle each module independently:

1. **Start each module** with: "Implement [module] according to the spec in `ironsight-project-plan.md`, Module [N] section"
2. **Test each module** in isolation before wiring them together
3. **For the USB module**, provide Claude Code with the RepliShot source as reference
4. **For ball flight**, provide PGA Tour average data as test fixtures
5. **Wire modules together** only after each works independently

The phased approach means you'll have a working (if basic) tool after Phase 2, and each subsequent phase adds value incrementally.
