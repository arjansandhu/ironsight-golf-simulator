/**
 * IronSight Driving Range - Three.js Scene Setup
 *
 * Creates a 3D driving range environment with:
 * - Green ground plane with distance markers
 * - Target circles at key distances
 * - Orbit camera controls
 * - Lighting for good visibility
 *
 * Coordinate system (yards):
 *   x = lateral (right is positive)
 *   y = vertical (up)
 *   z = downrange (toward targets, negative in Three.js)
 *
 * Note: Three.js uses a right-handed coordinate system where
 * -Z is "forward". Our ball flight data uses +Z as downrange,
 * so we negate Z when rendering.
 */

// ============================================================
// Scene, Camera, Renderer
// ============================================================

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a2a1a); // Dark green
scene.fog = new THREE.Fog(0x1a2a1a, 250, 400);

const camera = new THREE.PerspectiveCamera(
    60, window.innerWidth / window.innerHeight, 0.1, 1000
);
// Default camera: behind and above the hitting position
camera.position.set(-20, 25, 30);
camera.lookAt(0, 5, -100);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.getElementById('canvas-container').appendChild(renderer.domElement);

// ============================================================
// Orbit Controls (inline, no external dependency)
// ============================================================

const controls = new function() {
    this.target = new THREE.Vector3(0, 5, -100);
    this.enabled = true;

    let isMouseDown = false;
    let prevMouseX = 0, prevMouseY = 0;
    let spherical = { theta: 2.5, phi: 1.2, radius: 140 };

    const updateCamera = () => {
        const x = spherical.radius * Math.sin(spherical.phi) * Math.cos(spherical.theta);
        const y = spherical.radius * Math.cos(spherical.phi);
        const z = spherical.radius * Math.sin(spherical.phi) * Math.sin(spherical.theta);
        camera.position.set(
            this.target.x + x,
            Math.max(2, this.target.y + y),
            this.target.z + z
        );
        camera.lookAt(this.target);
    };

    renderer.domElement.addEventListener('mousedown', (e) => {
        if (!this.enabled) return;
        isMouseDown = true;
        prevMouseX = e.clientX;
        prevMouseY = e.clientY;
    });

    renderer.domElement.addEventListener('mousemove', (e) => {
        if (!isMouseDown || !this.enabled) return;
        const dx = e.clientX - prevMouseX;
        const dy = e.clientY - prevMouseY;
        spherical.theta -= dx * 0.005;
        spherical.phi = Math.max(0.1, Math.min(Math.PI * 0.48, spherical.phi + dy * 0.005));
        prevMouseX = e.clientX;
        prevMouseY = e.clientY;
        updateCamera();
    });

    renderer.domElement.addEventListener('mouseup', () => { isMouseDown = false; });
    renderer.domElement.addEventListener('mouseleave', () => { isMouseDown = false; });

    renderer.domElement.addEventListener('wheel', (e) => {
        if (!this.enabled) return;
        spherical.radius = Math.max(20, Math.min(400, spherical.radius + e.deltaY * 0.15));
        updateCamera();
    });

    updateCamera();
    this.update = updateCamera;
    this.setTarget = (x, y, z) => {
        this.target.set(x, y, z);
        updateCamera();
    };
}();

// ============================================================
// Lighting
// ============================================================

// Ambient light for base visibility
const ambient = new THREE.AmbientLight(0x404040, 0.6);
scene.add(ambient);

// Directional light (sun-like, from above-left)
const sunLight = new THREE.DirectionalLight(0xfff5e6, 1.0);
sunLight.position.set(-50, 100, -50);
sunLight.castShadow = true;
sunLight.shadow.mapSize.width = 2048;
sunLight.shadow.mapSize.height = 2048;
sunLight.shadow.camera.near = 0.5;
sunLight.shadow.camera.far = 500;
sunLight.shadow.camera.left = -200;
sunLight.shadow.camera.right = 200;
sunLight.shadow.camera.top = 200;
sunLight.shadow.camera.bottom = -200;
scene.add(sunLight);

// Hemisphere light for sky/ground color blending
const hemiLight = new THREE.HemisphereLight(0x87CEEB, 0x2d5a1e, 0.4);
scene.add(hemiLight);

// ============================================================
// Ground Plane - Driving Range
// ============================================================

function createRange() {
    // Main ground (dark green, fairway-like)
    const groundGeo = new THREE.PlaneGeometry(200, 350);
    const groundMat = new THREE.MeshLambertMaterial({
        color: 0x2d6a1e,
        side: THREE.DoubleSide,
    });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(0, -0.1, -150);
    ground.receiveShadow = true;
    scene.add(ground);

    // Hitting area (lighter green mat)
    const matGeo = new THREE.PlaneGeometry(8, 6);
    const matMaterial = new THREE.MeshLambertMaterial({
        color: 0x3d8b2e,
        side: THREE.DoubleSide,
    });
    const mat = new THREE.Mesh(matGeo, matMaterial);
    mat.rotation.x = -Math.PI / 2;
    mat.position.set(0, 0.01, 0);
    scene.add(mat);

    // Distance markers and target circles
    const distances = [50, 100, 150, 200, 250, 300];
    distances.forEach(dist => {
        // Distance ring
        const ringGeo = new THREE.RingGeometry(4, 5, 32);
        const ringMat = new THREE.MeshBasicMaterial({
            color: 0xffffff,
            side: THREE.DoubleSide,
            transparent: true,
            opacity: 0.25,
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.set(0, 0.05, -dist);
        scene.add(ring);

        // Target center dot
        const dotGeo = new THREE.CircleGeometry(1, 16);
        const dotMat = new THREE.MeshBasicMaterial({
            color: dist <= 150 ? 0x4CAF50 : 0xFFC107,
            side: THREE.DoubleSide,
            transparent: true,
            opacity: 0.4,
        });
        const dot = new THREE.Mesh(dotGeo, dotMat);
        dot.rotation.x = -Math.PI / 2;
        dot.position.set(0, 0.06, -dist);
        scene.add(dot);

        // Distance label (using sprite)
        const canvas = document.createElement('canvas');
        canvas.width = 128;
        canvas.height = 64;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'rgba(0,0,0,0)';
        ctx.fillRect(0, 0, 128, 64);
        ctx.font = 'bold 36px Arial';
        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'center';
        ctx.fillText(dist + '', 64, 42);

        const texture = new THREE.CanvasTexture(canvas);
        const spriteMat = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            opacity: 0.6,
        });
        const sprite = new THREE.Sprite(spriteMat);
        sprite.position.set(0, 3, -dist);
        sprite.scale.set(12, 6, 1);
        scene.add(sprite);
    });

    // Side boundary lines (dashed feel)
    for (let z = 0; z > -320; z -= 10) {
        const lineGeo = new THREE.PlaneGeometry(0.3, 8);
        const lineMat = new THREE.MeshBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.08,
            side: THREE.DoubleSide,
        });
        // Left line
        const lineL = new THREE.Mesh(lineGeo, lineMat);
        lineL.rotation.x = -Math.PI / 2;
        lineL.position.set(-60, 0.02, z);
        scene.add(lineL);

        // Right line
        const lineR = new THREE.Mesh(lineGeo, lineMat);
        lineR.rotation.x = -Math.PI / 2;
        lineR.position.set(60, 0.02, z);
        scene.add(lineR);
    }
}

createRange();

// ============================================================
// Window Resize Handler
// ============================================================

window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});

// ============================================================
// Animation Loop
// ============================================================

const clock = new THREE.Clock();

function animate() {
    requestAnimationFrame(animate);

    // Update any active ball animations
    if (window._activeBallAnimation) {
        window._activeBallAnimation(clock.getDelta());
    }

    renderer.render(scene, camera);
}

animate();
