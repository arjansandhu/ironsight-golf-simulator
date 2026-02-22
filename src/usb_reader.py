"""
OptiShot 2 USB HID communication module.

Reads raw sensor data from the OptiShot 2 swing pad over USB,
parses 60-byte HID packets, detects swing events, and computes
club speed, face angle, and swing path from IR sensor timing data.

Hardware: 32 IR sensors (16 front row + 16 back row) at 48 MHz.
Protocol: Based on RepliShot reverse engineering (zaren171/RepliShot).

Usage:
    reader = OptiShotReader()
    reader.swing_detected.connect(on_swing)
    reader.start()
"""

import logging
import math
import time
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from src.models.shot import ClubData
from src.utils.constants import (
    OPTISHOT_VID,
    OPTISHOT_PID,
    HID_PACKET_SIZE,
    HID_SUBPACKET_SIZE,
    SIGNATURE_BACK_SENSOR,
    SIGNATURE_FRONT_SENSOR,
    SIGNATURE_CONTINUED,
    CMD_ENABLE_SENSORS,
    CMD_LED_GREEN,
    CMD_LED_RED,
    CMD_SHUTDOWN,
    SENSOR_SPACING,
    LED_SPACING,
    SWING_COOLDOWN_MS,
    SPEED_CONVERSION_FACTOR,
    NUM_SENSORS_PER_ROW,
)

logger = logging.getLogger(__name__)


class OptiShotReader(QThread):
    """Reads swing data from OptiShot 2 over USB HID.

    Runs on a background QThread, continuously polling the device
    for sensor data. When a swing is detected, emits `swing_detected`
    with a ClubData object.

    Signals:
        swing_detected(ClubData): Emitted when a valid swing is detected.
        device_connected(): Emitted when the OptiShot is found and opened.
        device_disconnected(): Emitted when the device is lost.
        error_occurred(str): Emitted on USB errors.
        raw_data(bytes): Emitted for every raw packet (for debugging).
    """

    swing_detected = pyqtSignal(object)  # ClubData
    device_connected = pyqtSignal()
    device_disconnected = pyqtSignal()
    error_occurred = pyqtSignal(str)
    raw_data = pyqtSignal(bytes)

    def __init__(self, club_type: str = "7-Iron", parent=None):
        super().__init__(parent)
        self._running = False
        self._club_type = club_type
        self._device = None

        # Swing state tracking
        self._last_swing_time = 0.0
        self._reset_swing_state()

    def set_club(self, club_type: str):
        """Change the currently selected club."""
        self._club_type = club_type

    def _reset_swing_state(self):
        """Reset all swing detection accumulators."""
        self._front_triggered = False
        self._back_triggered = False
        self._back_orig = False

        # Sensor activation tracking for all 16 sensors per row
        # Each entry: (sensor_index, timestamp_ticks)
        self._front_activations: list[tuple[int, float]] = []
        self._back_activations: list[tuple[int, float]] = []

        # Min/max sensor indices hit (for face angle and path)
        self._min_front = NUM_SENSORS_PER_ROW
        self._max_front = -1
        self._min_back = NUM_SENSORS_PER_ROW
        self._max_back = -1

        # Timing accumulators
        self._elapsed_time = 0.0
        self._swing_packets = []

    def run(self):
        """Main thread loop: open device, poll for data, detect swings."""
        self._running = True
        logger.info("OptiShot reader thread starting")

        try:
            import hid
        except ImportError:
            self.error_occurred.emit(
                "hidapi not installed. Run: pip install hidapi"
            )
            return

        # Initialize HID on this thread (macOS requirement)
        while self._running:
            try:
                self._device = hid.device()
                self._device.open(OPTISHOT_VID, OPTISHOT_PID)
                self._device.set_nonblocking(True)
                logger.info(
                    f"OptiShot 2 connected "
                    f"(VID=0x{OPTISHOT_VID:04X}, PID=0x{OPTISHOT_PID:04X})"
                )
                self.device_connected.emit()

                # Enable sensors and set LED to green
                self._send_command(CMD_ENABLE_SENSORS)
                time.sleep(0.05)
                self._send_command(CMD_LED_GREEN)

                self._poll_loop()

            except OSError as e:
                logger.warning(f"OptiShot not found or connection lost: {e}")
                self.device_disconnected.emit()
                self._device = None

                # Wait before retrying
                for _ in range(50):  # 5 seconds in 100ms increments
                    if not self._running:
                        break
                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"OptiShot reader error: {e}", exc_info=True)
                self.error_occurred.emit(str(e))
                self._device = None
                time.sleep(1.0)

        # Cleanup
        if self._device:
            try:
                self._send_command(CMD_SHUTDOWN)
                self._device.close()
            except Exception:
                pass
        logger.info("OptiShot reader thread stopped")

    def _poll_loop(self):
        """Continuously read packets from the device."""
        while self._running and self._device:
            try:
                data = self._device.read(HID_PACKET_SIZE)
                if data:
                    self.raw_data.emit(bytes(data))
                    self._process_packet(data)
                else:
                    # No data available (non-blocking mode)
                    time.sleep(0.001)  # 1ms sleep to avoid busy-wait
            except OSError:
                logger.warning("Device read error — connection lost")
                self.device_disconnected.emit()
                break

    def _process_packet(self, data: list[int]):
        """Process a 60-byte HID packet, extracting sensor data.

        Each packet contains 12 x 5-byte sub-packets. Each sub-packet has:
          - Byte 0: Front sensor activation bits (low byte)
          - Byte 1: Back sensor activation bits (low byte) /
                     Front sensor activation bits (high byte)
          - Byte 2: Signature/type identifier
          - Byte 3-4: Timing data (high byte, low byte)

        For 16 sensors per row, we use 2 bytes: the low bits from byte 0/1
        and additional bits that may appear in the packet structure.
        """
        if len(data) < HID_PACKET_SIZE:
            return

        for i in range(0, HID_PACKET_SIZE, HID_SUBPACKET_SIZE):
            signature = data[i + 2]

            if signature == SIGNATURE_BACK_SENSOR:
                # Back sensor row triggered
                self._back_triggered = True
                if data[i] == 0 and data[i + 1] == 0:
                    self._back_orig = True

                self._parse_sensor_data(data, i, is_front=False)

                # Accumulate timing
                timing = (data[i + 3] * 256) + data[i + 4]
                self._elapsed_time += timing

            elif signature == SIGNATURE_FRONT_SENSOR:
                # Front sensor row triggered
                self._front_triggered = True
                self._parse_sensor_data(data, i, is_front=True)

                # Accumulate timing
                timing = (data[i + 3] * 256) + data[i + 4]
                self._elapsed_time += timing

            elif signature == SIGNATURE_CONTINUED:
                # Continued motion — additional data for current swing
                timing = (data[i + 3] * 256) + data[i + 4]
                self._elapsed_time += timing

        # Check if we have a complete swing (both front and back triggered)
        if self._front_triggered and self._back_triggered:
            now = time.time() * 1000  # ms
            if now - self._last_swing_time > SWING_COOLDOWN_MS:
                self._compute_swing()
                self._last_swing_time = now
            self._reset_swing_state()

    def _parse_sensor_data(self, data: list[int], offset: int, is_front: bool):
        """Parse sensor activation bits from a sub-packet.

        The OptiShot 2 has 16 sensors per row. We parse bits from
        the first two data bytes of each sub-packet.

        Args:
            data: Full 60-byte packet.
            offset: Starting index of this 5-byte sub-packet.
            is_front: True for front sensor row, False for back.
        """
        sensor_byte_0 = data[offset]      # Bits 0-7
        sensor_byte_1 = data[offset + 1]  # Bits 8-15
        timing = (data[offset + 3] * 256) + data[offset + 4]

        # Parse low 8 sensors (byte 0)
        for j in range(8):
            if (sensor_byte_0 >> j) & 0x01:
                sensor_index = j
                if is_front:
                    self._front_activations.append((sensor_index, timing))
                    self._min_front = min(self._min_front, sensor_index)
                    self._max_front = max(self._max_front, sensor_index)
                else:
                    self._back_activations.append((sensor_index, timing))
                    self._min_back = min(self._min_back, sensor_index)
                    self._max_back = max(self._max_back, sensor_index)

        # Parse high 8 sensors (byte 1)
        for j in range(8):
            if (sensor_byte_1 >> j) & 0x01:
                sensor_index = 8 + j
                if is_front:
                    self._front_activations.append((sensor_index, timing))
                    self._min_front = min(self._min_front, sensor_index)
                    self._max_front = max(self._max_front, sensor_index)
                else:
                    self._back_activations.append((sensor_index, timing))
                    self._min_back = min(self._min_back, sensor_index)
                    self._max_back = max(self._max_back, sensor_index)

    def _compute_swing(self):
        """Compute club speed, face angle, and path from sensor data.

        Speed: Derived from time elapsed between front and back sensor rows.
        Face angle: Arctangent of lateral vs longitudinal sensor displacement.
        Path: Difference in sensor spread between front and back rows.
        """
        if self._elapsed_time <= 0:
            return

        # --- Club head speed (mph) ---
        # Speed = distance / time, converted to mph
        speed_mph = (
            SENSOR_SPACING / (self._elapsed_time * 18)
        ) * SPEED_CONVERSION_FACTOR

        # Sanity check: reasonable club speeds are 30-140 mph
        if speed_mph < 30 or speed_mph > 140:
            logger.debug(f"Ignoring unreasonable speed: {speed_mph:.1f} mph")
            return

        # --- Face angle (degrees) ---
        # Computed from the lateral spread of sensors triggered
        x_travel_front = (self._max_front - self._min_front) * LED_SPACING
        x_travel_back = (self._max_back - self._min_back) * LED_SPACING
        y_travel = SENSOR_SPACING

        # Weight back sensors more (closer to ball contact)
        x_travel = (x_travel_front + 2 * x_travel_back) / 3

        if y_travel > 0:
            face_angle = math.atan2(x_travel, y_travel) * 180 / math.pi
        else:
            face_angle = 0.0

        # Determine sign: if more sensors triggered on the right side,
        # face is open (positive)
        avg_front = (
            sum(s[0] for s in self._front_activations) /
            len(self._front_activations)
            if self._front_activations else NUM_SENSORS_PER_ROW / 2
        )
        avg_back = (
            sum(s[0] for s in self._back_activations) /
            len(self._back_activations)
            if self._back_activations else NUM_SENSORS_PER_ROW / 2
        )
        center = NUM_SENSORS_PER_ROW / 2
        if avg_front < center:
            face_angle = -face_angle

        # --- Swing path (degrees) ---
        # Path is derived from the difference in sensor positions
        # between front and back rows
        path_raw = 0.0
        if self._max_front >= 0 and self._max_back >= 0:
            path_raw = (
                (self._max_front - self._max_back) +
                (self._min_front - self._min_back)
            )
        path_deg = path_raw * (LED_SPACING / SENSOR_SPACING) * 180 / math.pi

        # Classify path magnitude
        # Values > ±3: "Very Inside/Out" or "Very Outside/In"
        path_deg = max(-15, min(15, path_deg))  # Clamp to reasonable range

        # --- Contact point ---
        # Approximate from average sensor index relative to center
        contact_point = (avg_front + avg_back) / 2 - center

        logger.info(
            f"Swing detected: speed={speed_mph:.1f}mph, "
            f"face={face_angle:.1f}°, path={path_deg:.1f}°, "
            f"contact={contact_point:.1f}"
        )

        club_data = ClubData(
            club_speed_mph=round(speed_mph, 1),
            face_angle_deg=round(face_angle, 1),
            path_deg=round(path_deg, 1),
            contact_point=round(contact_point, 1),
            club_type=self._club_type,
        )
        self.swing_detected.emit(club_data)

    def _send_command(self, command: int):
        """Send a control command to the OptiShot device."""
        if self._device:
            try:
                # HID feature report: command byte padded to report size
                report = [0x00, command] + [0x00] * 14
                self._device.send_feature_report(report)
            except OSError as e:
                logger.warning(f"Failed to send command 0x{command:02X}: {e}")

    def stop(self):
        """Signal the thread to stop."""
        self._running = False

    def is_connected(self) -> bool:
        """Check if the device is currently connected."""
        return self._device is not None
