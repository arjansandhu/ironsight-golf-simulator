"""
Mock OptiShot 2 reader for development and testing.

Generates statistically realistic swing data without requiring
the physical OptiShot hardware. Supports multiple player presets
to simulate different skill levels.

This is a first-class feature, not just a test utility — users
can demo and develop the full pipeline without the device.
"""

import logging
import random
import time

from PyQt6.QtCore import QThread, pyqtSignal

from src.models.shot import ClubData

logger = logging.getLogger(__name__)


# Player presets: (mean, std_dev) for each metric
PRESETS = {
    "consistent_player": {
        "description": "Low handicap player with tight dispersion",
        "speed_offset": 0,       # Added to club's typical speed
        "face_angle": (0.5, 1.5),   # Mean, StdDev (degrees)
        "path": (-0.5, 1.5),        # Slightly out-to-in
        "contact": (0.0, 0.3),      # Center contact
        "tempo": (3.0, 0.15),       # Consistent tempo
    },
    "beginner": {
        "description": "High handicap player with wide dispersion",
        "speed_offset": -10,
        "face_angle": (2.0, 4.0),   # Tends to leave face open
        "path": (-3.0, 4.0),        # Steep out-to-in
        "contact": (0.5, 1.0),      # Inconsistent contact
        "tempo": (2.5, 0.5),        # Inconsistent tempo
    },
    "slicer": {
        "description": "Player who consistently slices",
        "speed_offset": -5,
        "face_angle": (3.0, 2.0),   # Open face
        "path": (-4.0, 2.0),        # Out-to-in path
        "contact": (0.3, 0.5),      # Slightly toward heel
        "tempo": (2.8, 0.3),
    },
    "hooker": {
        "description": "Player who consistently hooks",
        "speed_offset": -3,
        "face_angle": (-2.0, 2.0),  # Closed face
        "path": (3.0, 2.0),         # In-to-out path
        "contact": (-0.3, 0.5),     # Slightly toward toe
        "tempo": (3.2, 0.3),
    },
    "tour_pro": {
        "description": "Tour-level player with tight stats",
        "speed_offset": 5,
        "face_angle": (0.2, 0.8),   # Nearly square
        "path": (0.5, 1.0),         # Slightly in-to-out
        "contact": (0.0, 0.15),     # Center contact
        "tempo": (3.0, 0.08),       # Very consistent
    },
}

# Typical club speeds by club type (mph) — amateur averages
TYPICAL_SPEEDS = {
    "Driver":    95,
    "3-Wood":    90,
    "5-Wood":    87,
    "7-Wood":    85,
    "2-Hybrid":  88,
    "3-Hybrid":  86,
    "4-Hybrid":  84,
    "5-Hybrid":  82,
    "2-Iron":    87,
    "3-Iron":    85,
    "4-Iron":    83,
    "5-Iron":    81,
    "6-Iron":    79,
    "7-Iron":    76,
    "8-Iron":    73,
    "9-Iron":    70,
    "PW":        67,
    "GW":        64,
    "SW":        62,
    "LW":        58,
    "Putter":    10,
}


class MockOptiShotReader(QThread):
    """Simulates OptiShot 2 swing data for development without hardware.

    Generates random but statistically realistic swing data on a timer.
    Uses the same signal interface as OptiShotReader for drop-in
    replacement.

    Signals:
        swing_detected(ClubData): Emitted when a simulated swing occurs.
        device_connected(): Emitted at startup (simulated connection).
        device_disconnected(): Emitted at shutdown.
        error_occurred(str): Never emitted (for interface compatibility).
        raw_data(bytes): Not used in mock mode.
    """

    swing_detected = pyqtSignal(object)  # ClubData
    device_connected = pyqtSignal()
    device_disconnected = pyqtSignal()
    error_occurred = pyqtSignal(str)
    raw_data = pyqtSignal(bytes)

    def __init__(
        self,
        club_type: str = "7-Iron",
        preset: str = "consistent_player",
        swing_interval: tuple[float, float] = (3.0, 8.0),
        parent=None,
    ):
        """
        Args:
            club_type: Initial club selection.
            preset: Player preset name (see PRESETS).
            swing_interval: (min, max) seconds between simulated swings.
        """
        super().__init__(parent)
        self._running = False
        self._club_type = club_type
        self._preset_name = preset
        self._preset = PRESETS.get(preset, PRESETS["consistent_player"])
        self._swing_interval = swing_interval
        self._swing_count = 0

    def set_club(self, club_type: str):
        """Change the currently selected club."""
        self._club_type = club_type

    def set_preset(self, preset: str):
        """Change the player preset."""
        if preset in PRESETS:
            self._preset_name = preset
            self._preset = PRESETS[preset]
            logger.info(f"Mock preset changed to: {preset}")

    def run(self):
        """Main thread loop: generate swings at random intervals."""
        self._running = True
        logger.info(
            f"Mock OptiShot reader started "
            f"(preset={self._preset_name}, club={self._club_type})"
        )
        self.device_connected.emit()

        while self._running:
            # Random delay between swings
            delay = random.uniform(*self._swing_interval)
            # Sleep in small increments so we can stop quickly
            elapsed = 0.0
            while elapsed < delay and self._running:
                time.sleep(0.1)
                elapsed += 0.1

            if not self._running:
                break

            self._generate_swing()

        self.device_disconnected.emit()
        logger.info("Mock OptiShot reader stopped")

    def _generate_swing(self):
        """Generate a single simulated swing with realistic data."""
        p = self._preset
        base_speed = TYPICAL_SPEEDS.get(self._club_type, 80)

        # Club speed: base + preset offset + random variation
        speed = base_speed + p["speed_offset"] + random.gauss(0, 3)
        speed = max(30, min(140, speed))  # Clamp

        # Face angle
        face_mean, face_std = p["face_angle"]
        face_angle = random.gauss(face_mean, face_std)
        face_angle = max(-15, min(15, face_angle))

        # Swing path
        path_mean, path_std = p["path"]
        path = random.gauss(path_mean, path_std)
        path = max(-15, min(15, path))

        # Contact point
        contact_mean, contact_std = p["contact"]
        contact = random.gauss(contact_mean, contact_std)
        contact = max(-2, min(2, contact))

        # Tempo
        tempo_mean, tempo_std = p["tempo"]
        tempo = random.gauss(tempo_mean, tempo_std)
        tempo = max(2.0, min(4.5, tempo))

        self._swing_count += 1
        club_data = ClubData(
            club_speed_mph=round(speed, 1),
            face_angle_deg=round(face_angle, 1),
            path_deg=round(path, 1),
            contact_point=round(contact, 2),
            club_type=self._club_type,
            tempo=round(tempo, 2),
        )

        logger.info(
            f"Mock swing #{self._swing_count}: "
            f"{club_data.club_type} @ {club_data.club_speed_mph}mph, "
            f"face={club_data.face_angle_deg}°, "
            f"path={club_data.path_deg}°"
        )
        self.swing_detected.emit(club_data)

    def trigger_swing(self):
        """Manually trigger a single swing (for UI button / testing)."""
        self._generate_swing()

    def stop(self):
        """Signal the thread to stop."""
        self._running = False

    def is_connected(self) -> bool:
        """Mock is always 'connected'."""
        return self._running
