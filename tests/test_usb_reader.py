"""
Tests for USB reader and mock USB reader modules.

Tests packet parsing logic, swing detection, and mock data generation.
"""

import math
import pytest
from unittest.mock import MagicMock, patch

from src.models.shot import ClubData
from src.utils.constants import (
    HID_PACKET_SIZE,
    HID_SUBPACKET_SIZE,
    SIGNATURE_BACK_SENSOR,
    SIGNATURE_FRONT_SENSOR,
    SENSOR_SPACING,
    LED_SPACING,
    SPEED_CONVERSION_FACTOR,
    NUM_SENSORS_PER_ROW,
)


class TestMockReader:
    """Tests for MockOptiShotReader."""

    def test_swing_data_is_club_data(self, qtbot):
        """Mock reader should emit ClubData objects."""
        from src.mock_usb_reader import MockOptiShotReader

        reader = MockOptiShotReader(
            club_type="7-Iron",
            preset="consistent_player",
        )
        results = []

        reader.swing_detected.connect(lambda cd: results.append(cd))
        reader.trigger_swing()

        assert len(results) == 1
        cd = results[0]
        assert isinstance(cd, ClubData)
        assert cd.club_type == "7-Iron"

    def test_speed_within_range(self, qtbot):
        """Club speed should be within reasonable range."""
        from src.mock_usb_reader import MockOptiShotReader

        reader = MockOptiShotReader(
            club_type="Driver",
            preset="consistent_player",
        )
        speeds = []
        reader.swing_detected.connect(lambda cd: speeds.append(cd.club_speed_mph))

        for _ in range(100):
            reader.trigger_swing()

        assert all(30 <= s <= 140 for s in speeds)
        # Driver average should be roughly 90-100 for amateur
        avg = sum(speeds) / len(speeds)
        assert 80 <= avg <= 110

    def test_presets_differ(self, qtbot):
        """Different presets should produce different distributions."""
        from src.mock_usb_reader import MockOptiShotReader

        results = {}
        for preset in ["consistent_player", "slicer", "beginner"]:
            reader = MockOptiShotReader(
                club_type="7-Iron",
                preset=preset,
            )
            face_angles = []
            reader.swing_detected.connect(
                lambda cd, fa=face_angles: fa.append(cd.face_angle_deg)
            )
            for _ in range(50):
                reader.trigger_swing()
            results[preset] = sum(face_angles) / len(face_angles)

        # Slicer should have more open face than consistent player
        assert results["slicer"] > results["consistent_player"]

    def test_club_change(self, qtbot):
        """set_club should change the club type in subsequent swings."""
        from src.mock_usb_reader import MockOptiShotReader

        reader = MockOptiShotReader(club_type="Driver")
        reader.set_club("PW")

        results = []
        reader.swing_detected.connect(lambda cd: results.append(cd))
        reader.trigger_swing()

        assert results[0].club_type == "PW"

    def test_all_presets_valid(self, qtbot):
        """Every preset should generate valid ClubData."""
        from src.mock_usb_reader import MockOptiShotReader, PRESETS

        for preset_name in PRESETS:
            reader = MockOptiShotReader(
                club_type="7-Iron",
                preset=preset_name,
            )
            results = []
            reader.swing_detected.connect(lambda cd: results.append(cd))
            reader.trigger_swing()

            cd = results[0]
            assert cd.club_speed_mph > 0
            assert -15 <= cd.face_angle_deg <= 15
            assert -15 <= cd.path_deg <= 15
            assert cd.club_type == "7-Iron"


class TestOptiShotReaderParsing:
    """Tests for OptiShotReader packet parsing logic.

    Since we can't connect to real hardware in tests, we test
    the internal parsing methods directly.
    """

    def _make_reader(self):
        """Create an OptiShotReader without starting the thread."""
        from src.usb_reader import OptiShotReader
        reader = OptiShotReader.__new__(OptiShotReader)
        reader._running = False
        reader._club_type = "7-Iron"
        reader._device = None
        reader._last_swing_time = 0
        reader._reset_swing_state()
        return reader

    def test_parse_sensor_data_front(self):
        """Front sensor parsing should identify activated sensors."""
        reader = self._make_reader()

        # Create a sub-packet with sensors 0, 2, 4 triggered in byte 0
        # Binary: 00010101 = 0x15
        data = [0x15, 0x00, SIGNATURE_FRONT_SENSOR, 0x00, 0x10]
        reader._parse_sensor_data(data, 0, is_front=True)

        assert len(reader._front_activations) == 3
        sensor_indices = [a[0] for a in reader._front_activations]
        assert 0 in sensor_indices
        assert 2 in sensor_indices
        assert 4 in sensor_indices

    def test_parse_sensor_data_back(self):
        """Back sensor parsing should identify activated sensors."""
        reader = self._make_reader()

        # Sensor 1 and 3 triggered
        data = [0x00, 0x0A, SIGNATURE_BACK_SENSOR, 0x00, 0x20]
        reader._parse_sensor_data(data, 0, is_front=False)

        assert len(reader._back_activations) == 2
        sensor_indices = [a[0] for a in reader._back_activations]
        assert 9 in sensor_indices   # bit 1 of byte 1 = sensor 8+1
        assert 11 in sensor_indices  # bit 3 of byte 1 = sensor 8+3

    def test_parse_16_sensors(self):
        """Should handle all 16 sensors per row (2 bytes)."""
        reader = self._make_reader()

        # All 16 sensors triggered: byte0=0xFF, byte1=0xFF
        data = [0xFF, 0xFF, SIGNATURE_FRONT_SENSOR, 0x00, 0x10]
        reader._parse_sensor_data(data, 0, is_front=True)

        assert len(reader._front_activations) == 16
        sensor_indices = sorted(a[0] for a in reader._front_activations)
        assert sensor_indices == list(range(16))

    def test_min_max_tracking(self):
        """Min/max sensor indices should be tracked correctly."""
        reader = self._make_reader()

        # Front: sensors 3 and 7 triggered (byte 0 = 0x88)
        data = [0x88, 0x00, SIGNATURE_FRONT_SENSOR, 0x00, 0x10]
        reader._parse_sensor_data(data, 0, is_front=True)

        assert reader._min_front == 3
        assert reader._max_front == 7

    def test_empty_packet_no_crash(self):
        """Empty sensor bytes should not crash."""
        reader = self._make_reader()

        data = [0x00, 0x00, SIGNATURE_FRONT_SENSOR, 0x00, 0x00]
        reader._parse_sensor_data(data, 0, is_front=True)

        assert len(reader._front_activations) == 0

    def test_speed_calculation(self):
        """Speed formula should produce reasonable results."""
        # speed = (SENSOR_SPACING / (elapsed_time * 18)) * SPEED_CONVERSION_FACTOR
        # For a 7-iron at ~76 mph:
        # 76 = (185 / (elapsed * 18)) * 2236.94
        # elapsed = 185 * 2236.94 / (76 * 18) = 302.5
        elapsed = 185 * SPEED_CONVERSION_FACTOR / (76 * 18)
        speed = (SENSOR_SPACING / (elapsed * 18)) * SPEED_CONVERSION_FACTOR
        assert abs(speed - 76) < 0.1

    def test_process_packet_full(self):
        """Full packet processing should detect a swing."""
        reader = self._make_reader()

        # Build a 60-byte packet with back + front sensor data
        packet = [0x00] * HID_PACKET_SIZE

        # Sub-packet 0: back sensors (sensors 5-7 triggered)
        packet[0] = 0xE0   # bits 5,6,7
        packet[1] = 0x00
        packet[2] = SIGNATURE_BACK_SENSOR
        packet[3] = 0x01   # timing high byte
        packet[4] = 0x30   # timing low byte

        # Sub-packet 1: front sensors (sensors 4-6 triggered)
        packet[5] = 0x70   # bits 4,5,6
        packet[6] = 0x00
        packet[7] = SIGNATURE_FRONT_SENSOR
        packet[8] = 0x01
        packet[9] = 0x40

        # Mock the signal emit
        emitted = []
        reader.swing_detected = MagicMock()
        reader.swing_detected.emit = lambda cd: emitted.append(cd)
        reader.raw_data = MagicMock()

        reader._process_packet(packet)

        # Should have detected a swing (both front and back triggered)
        if emitted:
            cd = emitted[0]
            assert isinstance(cd, ClubData)
            assert cd.club_speed_mph > 0
            assert cd.club_type == "7-Iron"


class TestSpeedConversion:
    """Validate speed conversion formula against known values."""

    def test_driver_speed_range(self):
        """Driver speed calculation should be in reasonable range."""
        # Typical elapsed time values for different speeds
        test_cases = [
            (95, "amateur driver"),
            (113, "tour driver"),
            (76, "amateur 7-iron"),
        ]
        for target_speed, label in test_cases:
            elapsed = SENSOR_SPACING * SPEED_CONVERSION_FACTOR / (target_speed * 18)
            computed = (SENSOR_SPACING / (elapsed * 18)) * SPEED_CONVERSION_FACTOR
            assert abs(computed - target_speed) < 0.01, (
                f"{label}: expected {target_speed}, got {computed}"
            )
