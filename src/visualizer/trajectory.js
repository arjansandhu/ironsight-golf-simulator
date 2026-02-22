/**
 * IronSight Trajectory Rendering
 *
 * Renders ball flight trajectories as colored arcs in the 3D scene.
 * Supports animated ball, persistent trail arcs, and landing markers.
 *
 * All trajectory points come from Python (pre-computed physics).
 * Points are in yards: (x=lateral, y=altitude, z=downrange).
 * Three.js Z is negated (our +z downrange = Three.js -z).
 */

// ============================================================
// Shot storage
// ============================================================

const MAX_TRAIL_SHOTS = 20;
const shotTrails = [];
let currentBall = null;
let landingMarkers = [];

// Color palette for shot trails (cycles through)
const TRAIL_COLORS = [
    0x4CAF50,  // Green
    0x2196F3,  // Blue
    0xFF9800,  // Orange
    0xE91E63,  // Pink
    0x00BCD4,  // Cyan
    0xFFEB3B,  // Yellow
    0x9C27B0,  // Purple
    0xFF5722,  // Deep Orange
];

// ============================================================
// Trajectory Arc Rendering
// ============================================================

/**
 * Render a trajectory arc from an array of (x, y, z) points.
 * Returns the Three.js Line object.
 */
function renderTrajectoryArc(points, color, opacity) {
    const vertices = [];
    for (const [x, y, z] of points) {
        vertices.push(x, y, -z);  // Negate z for Three.js
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',
        new THREE.Float32BufferAttribute(vertices, 3)
    );

    const material = new THREE.LineBasicMaterial({
        color: color,
        transparent: true,
        opacity: opacity,
        linewidth: 2,
    });

    const line = new THREE.Line(geometry, material);
    scene.add(line);
    return line;
}

/**
 * Add a landing marker (small sphere) at the landing point.
 */
function addLandingMarker(x, y, z, color) {
    const geo = new THREE.SphereGeometry(0.8, 12, 12);
    const mat = new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0.7,
    });
    const marker = new THREE.Mesh(geo, mat);
    marker.position.set(x, 0.5, -z);  // Negate z
    scene.add(marker);
    landingMarkers.push(marker);
    return marker;
}

// ============================================================
// Animated Ball
// ============================================================

/**
 * Animate a ball along a trajectory path.
 * @param {Array} points - Array of [x, y, z] positions (yards)
 * @param {number} flightTime - Total flight time in seconds
 * @param {Function} onComplete - Called when animation finishes
 */
function animateBall(points, flightTime, onComplete) {
    // Remove previous ball
    if (currentBall) {
        scene.remove(currentBall);
    }

    // Create ball
    const ballGeo = new THREE.SphereGeometry(0.5, 16, 16);
    const ballMat = new THREE.MeshPhongMaterial({
        color: 0xffffff,
        emissive: 0x444444,
    });
    currentBall = new THREE.Mesh(ballGeo, ballMat);
    currentBall.castShadow = true;
    scene.add(currentBall);

    // Animation state
    let elapsed = 0;
    const speed = Math.max(0.5, flightTime * 0.6); // Slightly faster than real-time

    window._activeBallAnimation = (dt) => {
        elapsed += dt;
        const t = Math.min(elapsed / speed, 1.0);

        // Interpolate position along trajectory
        const idx = Math.min(
            Math.floor(t * (points.length - 1)),
            points.length - 2
        );
        const localT = (t * (points.length - 1)) - idx;

        const p0 = points[idx];
        const p1 = points[idx + 1];

        const x = p0[0] + (p1[0] - p0[0]) * localT;
        const y = p0[1] + (p1[1] - p0[1]) * localT;
        const z = p0[2] + (p1[2] - p0[2]) * localT;

        currentBall.position.set(x, y, -z);

        if (t >= 1.0) {
            window._activeBallAnimation = null;
            if (onComplete) onComplete();
        }
    };
}

// ============================================================
// Shot Management
// ============================================================

/**
 * Add a new shot to the scene.
 * Called from Python via JS bridge.
 *
 * @param {Object} shotData - Shot data from Python:
 *   - points: Array of [x, y, z] trajectory points (yards)
 *   - carry: Carry distance (yards)
 *   - total: Total distance (yards)
 *   - apex: Max height (yards)
 *   - lateral: Lateral displacement (yards)
 *   - flightTime: Flight time (seconds)
 *   - clubSpeed: Club speed (mph)
 *   - ballSpeed: Ball speed (mph)
 *   - vla: Vertical launch angle (degrees)
 *   - backspin: Backspin (RPM)
 *   - clubType: Club name
 *   - shotShape: Shot shape description
 */
function addShot(shotData) {
    const colorIdx = shotTrails.length % TRAIL_COLORS.length;
    const color = TRAIL_COLORS[colorIdx];

    // Fade previous trails
    shotTrails.forEach((trail, i) => {
        const age = shotTrails.length - i;
        const opacity = Math.max(0.1, 0.8 - age * 0.05);
        trail.material.opacity = opacity;
    });

    // Remove oldest trails if over limit
    while (shotTrails.length >= MAX_TRAIL_SHOTS) {
        const old = shotTrails.shift();
        scene.remove(old);
    }

    // Render new trajectory arc
    const arc = renderTrajectoryArc(shotData.points, color, 0.9);
    shotTrails.push(arc);

    // Add landing marker
    const lastPt = shotData.points[shotData.points.length - 1];
    addLandingMarker(lastPt[0], lastPt[1], lastPt[2], color);

    // Animate ball along trajectory
    animateBall(shotData.points, shotData.flightTime, () => {
        // Ball has landed
    });

    // Update stats overlay
    updateStatsOverlay(shotData);

    // Update shot shape display
    updateShotShape(shotData.shotShape, color);

    // Update club info
    const clubInfo = document.getElementById('club-info');
    clubInfo.textContent = shotData.clubType + ' | Shot #' + (shotTrails.length);
}

/**
 * Clear all shots from the scene.
 */
function clearShots() {
    shotTrails.forEach(trail => scene.remove(trail));
    shotTrails.length = 0;

    landingMarkers.forEach(marker => scene.remove(marker));
    landingMarkers.length = 0;

    if (currentBall) {
        scene.remove(currentBall);
        currentBall = null;
    }

    window._activeBallAnimation = null;

    // Hide overlays
    document.getElementById('stats-overlay').classList.remove('visible');
    document.getElementById('shot-shape').classList.remove('visible');
}

// ============================================================
// UI Updates
// ============================================================

function updateStatsOverlay(data) {
    document.getElementById('stat-club-speed').textContent =
        (data.clubSpeed || '—') + ' mph';
    document.getElementById('stat-ball-speed').textContent =
        (data.ballSpeed || '—') + ' mph';
    document.getElementById('stat-launch').textContent =
        (data.vla || '—') + '\u00B0';
    document.getElementById('stat-spin').textContent =
        (data.backspin || '—') + ' rpm';
    document.getElementById('stat-carry').textContent =
        (data.carry || '—') + ' yd';
    document.getElementById('stat-total').textContent =
        (data.total || '—') + ' yd';
    document.getElementById('stat-apex').textContent =
        (data.apex || '—') + ' yd';

    const lat = data.lateral || 0;
    const latStr = Math.abs(lat).toFixed(1);
    const dir = lat > 0 ? 'R' : lat < 0 ? 'L' : '';
    document.getElementById('stat-lateral').textContent =
        latStr + ' yd ' + dir;

    document.getElementById('stats-overlay').classList.add('visible');
}

function updateShotShape(shape, color) {
    const el = document.getElementById('shot-shape');
    el.textContent = shape || '';
    el.style.color = '#' + color.toString(16).padStart(6, '0');
    el.classList.add('visible');
}

/**
 * Reset the camera to default view.
 */
function resetCamera() {
    controls.setTarget(0, 5, -100);
}
