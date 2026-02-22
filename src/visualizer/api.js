/**
 * IronSight Python-JS Bridge API
 *
 * These functions are called from Python via QWebEngineView's
 * page().runJavaScript(). They provide the interface between
 * the Python ball flight engine and the Three.js visualization.
 *
 * Usage from Python:
 *   self.web_view.page().runJavaScript(f"window.addShot({json})")
 *   self.web_view.page().runJavaScript("window.clearShots()")
 *   self.web_view.page().runJavaScript("window.resetCamera()")
 */

// Expose API globally for Python bridge
window.addShot = addShot;
window.clearShots = clearShots;
window.resetCamera = resetCamera;

// Also expose for testing/debugging in browser console
window.debugShot = function() {
    // Generate a sample shot for testing the visualization
    const points = [];
    const carry = 250;
    const apex = 35;
    const lateral = 8;

    for (let t = 0; t <= 1; t += 0.01) {
        const z = carry * t;
        const y = apex * 4 * t * (1 - t);  // Parabolic arc
        const x = lateral * t * t;           // Curved lateral
        points.push([x, y, z]);
    }

    window.addShot({
        points: points,
        carry: carry,
        total: 270,
        apex: apex,
        lateral: lateral,
        flightTime: 6.5,
        clubSpeed: 95,
        ballSpeed: 141,
        vla: 12.5,
        backspin: 2800,
        clubType: 'Driver',
        shotShape: 'Fade',
    });
};

// Ready signal for Python
window._ironsightReady = true;
console.log('IronSight visualization ready');
