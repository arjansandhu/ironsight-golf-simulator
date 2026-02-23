"""
OptiShot 2 USB HID communication module.

Reads raw sensor data from the OptiShot 2 swing pad over USB,
parses 60-byte HID packets, detects swing events, and computes
club speed, face angle, and swing path from IR sensor timing data.

Hardware: 2 rows of 8 IR sensors (front + back) at 48 MHz.
Protocol: Based on RepliShot reverse engineering (zaren171/RepliShot).

Packet structure (60 bytes = 12 x 5-byte sub-packets):
  Byte 0: Front sensor bitmask (8 sensors, bits 0-7)
  Byte 1: Back sensor bitmask (8 sensors, bits 0-7)
  Byte 2: Signature byte (0x81=origin, 0x4A=front, 0x52=back continued)
  Byte 3: Timing high byte
  Byte 4: Timing low byte

Swing detection:
  A valid swing requires both:
    - A 0x81 (origin) sub-packet with data[i]==0 (back sensor origin)
    - A 0x4A sub-packet (front sensor activation)
  This means the club traveled from the back row to the front row.

Usage:
    reader = OptiShotReader()
    reader.swing_detected.connect(on_swing)
    reader.start()
"""

import logging
import math
import time

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
)

logger = logging.getLogger(__name__)

# Number of sensors per row in the USB protocol (8-bit bitmask each)
SENSORS_PER_ROW = 8


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
        self._hid_module = None

        # Packet deduplication (RepliShot compares prev vs current)
        self._prev_data = None

        # Swing state
        self._collect_swing = True
        self._reset_swing_state()

    def set_club(self, club_type: str):
        """Change the currently selected club."""
        self._club_type = club_type

    def _reset_swing_state(self):
        """Reset all swing detection accumulators."""
        self._back_orig = False
        self._front_triggered = False

        # Per-row sensor tracking (8 sensors each, indexed 0-7)
        self._front_activations = []  # list of (sensor_index, timing)
        self._back_activations = []

        self._min_front = SENSORS_PER_ROW
        self._max_front = -1
        self._min_back = SENSORS_PER_ROW
        self._max_back = -1

        # Timing
        self._elapsed_time = 0
        self._first_front = False
        self._speed_elapsed = 0  # elapsed time at first front sensor hit

        # Ball detection
        self._potential_ball_read = False
        self._ball_timing_subtract = 0

        # Sub-packet data for face angle computation
        self._subpacket_history = []  # list of (sig, front_byte, back_byte, timing)

    def run(self):
        """Main thread loop: open device, poll for data, detect swings."""
        self._running = True
        logger.info("OptiShot reader thread starting")

        try:
            import hid
            self._hid_module = hid
        except ImportError:
            self.error_occurred.emit(
                "hidapi not installed. Run: pip install hidapi"
            )
            return

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

                # Initialize device (matches RepliShot opti_init sequence)
                self._send_command(CMD_ENABLE_SENSORS)
                time.sleep(0.05)
                self._send_command(CMD_LED_GREEN)
                time.sleep(0.01)
                # Cycle red/green like RepliShot
                self._send_command(CMD_LED_RED)
                time.sleep(0.01)
                self._send_command(CMD_LED_GREEN)

                self._collect_swing = True
                self._prev_data = None
                self._poll_loop()

            except OSError as e:
                logger.warning(f"OptiShot not found or connection lost: {e}")
                self.device_disconnected.emit()
                self._device = None

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
        packet_count = 0
        while self._running and self._device:
            try:
                data = self._device.read(HID_PACKET_SIZE)
                if data:
                    packet_count += 1
                    self.raw_data.emit(bytes(data))

                    # Log first few packets and then periodically for debugging
                    if packet_count <= 5 or packet_count % 500 == 0:
                        self._log_raw_packet(data, packet_count)

                    # Packet deduplication: only process if different from previous
                    if self._prev_data is not None and list(data) == self._prev_data:
                        continue
                    self._prev_data = list(data)

                    if self._collect_swing:
                        self._process_packet(data)
                else:
                    time.sleep(0.001)  # 1ms sleep to avoid busy-wait
            except OSError:
                logger.warning("Device read error — connection lost")
                self.device_disconnected.emit()
                break

    def _log_raw_packet(self, data, packet_num):
        """Log a raw packet in hex for debugging."""
        hex_str = ' '.join(f'{b:02X}' for b in data[:60])
        logger.debug(f"Packet #{packet_num} ({len(data)} bytes): {hex_str}")

        # Also decode sub-packets for readability
        for i in range(0, min(len(data), HID_PACKET_SIZE), HID_SUBPACKET_SIZE):
            front_byte = data[i]
            back_byte = data[i + 1]
            sig = data[i + 2]
            timing = (data[i + 3] * 256) + data[i + 4]
            sig_name = {0x81: "ORIGIN", 0x4A: "FRONT", 0x52: "BACK+"}.get(
                sig, f"0x{sig:02X}"
            )
            front_bits = f'{front_byte:08b}'
            back_bits = f'{back_byte:08b}'
            logger.debug(
                f"  sub[{i//5:2d}]: front={front_bits} back={back_bits} "
                f"sig={sig_name:6s} timing={timing:5d}"
            )

    def _process_packet(self, data):
        """Process a 60-byte HID packet per RepliShot protocol.

        Each packet contains 12 x 5-byte sub-packets:
          Byte 0: Front sensor bitmask (8 bits = 8 sensors)
          Byte 1: Back sensor bitmask (8 bits = 8 sensors)
          Byte 2: Signature (0x81=origin, 0x4A=front, 0x52=back continued)
          Byte 3-4: Timing (big-endian 16-bit tick count)

        Swing detection requires:
          - 0x81 sub-packet with data[i]==0 (back_orig: back sensors fired first)
          - 0x4A sub-packet (front sensors also fired)
        """
        if len(data) < HID_PACKET_SIZE:
            return

        for i in range(0, HID_PACKET_SIZE, HID_SUBPACKET_SIZE):
            front_byte = data[i]      # Front sensor bitmask
            back_byte = data[i + 1]   # Back sensor bitmask
            signature = data[i + 2]
            timing = (data[i + 3] * 256) + data[i + 4]

            self._subpacket_history.append(
                (signature, front_byte, back_byte, timing)
            )

            if signature == SIGNATURE_BACK_SENSOR:  # 0x81 = Origin
                # Origin sub-packet. If front_byte (data[i]) == 0,
                # this is a back-sensor origin (club hit back row first).
                if front_byte == 0:
                    self._back_orig = True
                    logger.debug(
                        f"ORIGIN (back): back_byte=0x{back_byte:02X} "
                        f"timing={timing}"
                    )
                else:
                    # Front sensors triggered in origin packet
                    logger.debug(
                        f"ORIGIN (front): front_byte=0x{front_byte:02X} "
                        f"timing={timing}"
                    )

                # Parse sensor bits from this sub-packet
                self._parse_front_sensors(front_byte, timing)
                self._parse_back_sensors(back_byte, timing)
                self._elapsed_time += timing

            elif signature == SIGNATURE_CONTINUED:  # 0x52 = Additional back
                # Additional back sensor reading
                if front_byte != 0:
                    logger.debug(
                        f"BACK+: unexpected front_byte=0x{front_byte:02X}"
                    )
                self._parse_back_sensors(back_byte, timing)
                self._elapsed_time += timing

            elif signature == SIGNATURE_FRONT_SENSOR:  # 0x4A = Front sensor
                self._front_triggered = True
                if back_byte != 0:
                    logger.debug(
                        f"FRONT: unexpected back_byte=0x{back_byte:02X}"
                    )
                self._parse_front_sensors(front_byte, timing)
                self._elapsed_time += timing

                # Speed is calculated at the FIRST front sensor crossing
                if not self._first_front:
                    self._first_front = True
                    self._speed_elapsed = self._elapsed_time
                    logger.debug(
                        f"First front crossing: elapsed={self._speed_elapsed}"
                    )

                # Ball detection: large timing gap followed by small one
                if timing > 0x25:
                    self._potential_ball_read = True
                elif self._potential_ball_read and timing < 0x20:
                    # Ball confirmed — subtract the ball gap from speed calc
                    prev_idx = len(self._subpacket_history) - 2
                    if prev_idx >= 0:
                        ball_timing = self._subpacket_history[prev_idx][3]
                        self._ball_timing_subtract = ball_timing
                        logger.debug(
                            f"Ball detected: subtracting {ball_timing} from speed"
                        )
                    self._potential_ball_read = False

        # Check for complete swing: back_orig AND front_triggered
        if self._back_orig and self._front_triggered:
            logger.info(
                f"Swing conditions met: back_orig={self._back_orig}, "
                f"front={self._front_triggered}, "
                f"elapsed={self._elapsed_time}, "
                f"front_acts={len(self._front_activations)}, "
                f"back_acts={len(self._back_activations)}"
            )

            # Pause collection (LED red) like RepliShot
            self._collect_swing = False
            self._send_command(CMD_LED_RED)

            self._compute_swing()

            # Cooldown: sleep, flush buffer, re-enable
            self._swing_cooldown()
            self._reset_swing_state()
        else:
            # If we got sensor data but no complete swing, log it
            has_any_data = (
                self._back_orig or self._front_triggered or
                self._elapsed_time > 0
            )
            if has_any_data:
                logger.debug(
                    f"Partial: back_orig={self._back_orig}, "
                    f"front={self._front_triggered}, "
                    f"elapsed={self._elapsed_time}"
                )

    def _parse_front_sensors(self, byte_val, timing):
        """Parse front sensor bitmask (8 sensors)."""
        if byte_val == 0:
            return
        for j in range(8):
            if (byte_val >> j) & 0x01:
                self._front_activations.append((j, timing))
                self._min_front = min(self._min_front, j)
                self._max_front = max(self._max_front, j)

    def _parse_back_sensors(self, byte_val, timing):
        """Parse back sensor bitmask (8 sensors)."""
        if byte_val == 0:
            return
        for j in range(8):
            if (byte_val >> j) & 0x01:
                self._back_activations.append((j, timing))
                self._min_back = min(self._min_back, j)
                self._max_back = max(self._max_back, j)

    def _compute_swing(self):
        """Compute club speed, face angle, and path from accumulated sensor data.

        Speed: distance / time at first front crossing, converted to mph.
        Face angle: weighted average of front/back lateral sensor displacement.
        Path: difference in sensor positions between front and back rows.
        Contact: average back sensor position relative to center.
        """
        speed_elapsed = self._speed_elapsed
        if speed_elapsed <= 0:
            logger.warning("No valid speed timing — skipping swing")
            return

        # Subtract ball timing if detected
        if self._ball_timing_subtract > 0:
            speed_elapsed -= self._ball_timing_subtract

        if speed_elapsed <= 0:
            logger.warning("Speed timing went negative after ball subtract")
            return

        # --- Club head speed (mph) ---
        speed_mph = (
            SENSOR_SPACING / (speed_elapsed * 18)
        ) * SPEED_CONVERSION_FACTOR

        logger.info(
            f"Speed calc: spacing={SENSOR_SPACING}, "
            f"elapsed={speed_elapsed}, speed={speed_mph:.1f} mph"
        )

        # Only reject physically impossible values (sensor noise / math errors).
        # Slow swings (chips, putts) are valid — they just produce short shots.
        if speed_mph < 1 or speed_mph > 160:
            logger.warning(f"Rejecting speed: {speed_mph:.1f} mph (likely noise)")
            return

        # --- Face angle (degrees) ---
        x_travel_front = (self._max_front - self._min_front) * LED_SPACING
        x_travel_back = (self._max_back - self._min_back) * LED_SPACING

        # Weight back sensors 2x (closer to ball contact per RepliShot)
        x_travel = (x_travel_front + 2 * x_travel_back) / 3
        y_travel = SENSOR_SPACING

        if y_travel > 0:
            face_angle = math.atan2(x_travel, y_travel) * 180 / math.pi
        else:
            face_angle = 0.0

        # Determine sign from average sensor position
        center = SENSORS_PER_ROW / 2  # 4.0
        avg_front = (
            sum(s[0] for s in self._front_activations) /
            len(self._front_activations)
            if self._front_activations else center
        )
        avg_back = (
            sum(s[0] for s in self._back_activations) /
            len(self._back_activations)
            if self._back_activations else center
        )
        if avg_front < center:
            face_angle = -face_angle

        # --- Swing path (degrees) ---
        path_raw = 0.0
        if self._max_front >= 0 and self._max_back >= 0:
            path_raw = (
                (self._max_front - self._max_back) +
                (self._min_front - self._min_back)
            )
        path_deg = path_raw * (LED_SPACING / SENSOR_SPACING) * 180 / math.pi
        path_deg = max(-15, min(15, path_deg))  # Clamp

        # --- Contact point ---
        # RepliShot uses back sensor row for contact (front reads after ball)
        contact_point = avg_back - center

        logger.info(
            f"Swing detected: speed={speed_mph:.1f}mph, "
            f"face={face_angle:.1f} deg, path={path_deg:.1f} deg, "
            f"contact={contact_point:.1f}, "
            f"front_range=[{self._min_front},{self._max_front}], "
            f"back_range=[{self._min_back},{self._max_back}]"
        )

        club_data = ClubData(
            club_speed_mph=round(speed_mph, 1),
            face_angle_deg=round(face_angle, 1),
            path_deg=round(path_deg, 1),
            contact_point=round(contact_point, 1),
            club_type=self._club_type,
        )
        self.swing_detected.emit(club_data)

    def _swing_cooldown(self):
        """Post-swing cooldown: sleep, flush buffer, re-enable sensors.

        Matches RepliShot's shot cycle:
        1. LED red (already sent before this call)
        2. Sleep 2500ms
        3. Flush any queued packets
        4. LED green (re-enable swing collection)
        """
        # Sleep in small increments so we can stop quickly
        cooldown_s = SWING_COOLDOWN_MS / 1000.0
        sleep_step = 0.1
        elapsed = 0.0
        while elapsed < cooldown_s and self._running:
            time.sleep(sleep_step)
            elapsed += sleep_step

        # Flush buffered packets
        if self._device:
            flush_count = 0
            try:
                while True:
                    pkt = self._device.read(HID_PACKET_SIZE)
                    if not pkt:
                        break
                    flush_count += 1
            except OSError:
                pass
            if flush_count > 0:
                logger.debug(f"Flushed {flush_count} packets after swing")

        # Re-enable collection
        self._send_command(CMD_LED_GREEN)
        self._collect_swing = True
        self._prev_data = None  # Reset dedup after flush
        logger.debug("Swing cooldown complete — sensors re-enabled")

    def _send_command(self, command: int):
        """Send a control command to the OptiShot device.

        RepliShot uses libusb interrupt transfer to endpoint 1 with a
        60-byte buffer. With hidapi, we use write() which sends an
        output report (interrupt OUT transfer).
        """
        if self._device:
            try:
                # Build a 60-byte report with command at byte 0
                # Byte 0 for hidapi write() is the report ID (0x00 for default)
                report = [0x00, command] + [0x00] * (HID_PACKET_SIZE - 1)
                self._device.write(report)
                logger.debug(f"Sent command 0x{command:02X}")
            except OSError as e:
                logger.warning(f"Failed to send command 0x{command:02X}: {e}")

    def stop(self):
        """Signal the thread to stop."""
        self._running = False

    def is_connected(self):
        """Check if the device is currently connected."""
        return self._device is not None
