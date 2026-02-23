"""
Hardware constants, physics constants, and club data for IronSight.

OptiShot 2 hardware specs sourced from RepliShot reverse engineering
and verified against official specifications.
"""

import math

# =============================================================================
# OptiShot 2 USB Hardware Constants
# =============================================================================

OPTISHOT_VID = 0x0547          # USB Vendor ID
OPTISHOT_PID = 0x3294          # USB Product ID

# Sensor layout: The hardware has 16 physical IR LEDs per row, but the USB
# protocol exposes 8 sensors per row as single-byte bitmasks (8 bits each).
# Two rows: front (toward target) and back (toward golfer).
NUM_SENSORS_PER_ROW = 8        # 8 bits per bitmask in USB protocol
NUM_SENSOR_ROWS = 2            # front and back
TOTAL_SENSORS = NUM_SENSORS_PER_ROW * NUM_SENSOR_ROWS

# Physical spacing (in arbitrary hardware units from RepliShot)
SENSOR_SPACING = 185           # Distance between front and back sensor rows
LED_SPACING = 15               # Spacing between individual LED/sensor elements

# HID packet structure
HID_PACKET_SIZE = 60           # Bytes per USB HID report
HID_SUBPACKET_SIZE = 5         # Each report contains 12 x 5-byte sub-packets
SUBPACKETS_PER_REPORT = HID_PACKET_SIZE // HID_SUBPACKET_SIZE  # 12

# Sub-packet signature bytes (byte index 2 within each 5-byte sub-packet)
SIGNATURE_BACK_SENSOR = 0x81   # Back sensor row data
SIGNATURE_FRONT_SENSOR = 0x4A  # Front sensor row data
SIGNATURE_CONTINUED = 0x52     # Additional back sensor reading

# OptiShot control commands (sent to device)
CMD_ENABLE_SENSORS = 0x50      # Enable sensor scanning
CMD_LED_RED = 0x51             # Set LED to red (pause swing detection)
CMD_LED_GREEN = 0x52           # Set LED to green (enable swing detection)
CMD_SHUTDOWN = 0x80            # Shut down sensors and LED

# Swing detection
SWING_COOLDOWN_MS = 2500       # Minimum ms between valid swings
SPEED_CONVERSION_FACTOR = 2236.94  # Converts sensor units to mph

# =============================================================================
# Ball Physics Constants
# =============================================================================

# Air properties at standard conditions (sea level, 70°F / 21°C)
AIR_DENSITY = 1.225            # kg/m³
GRAVITY = 9.81                 # m/s²

# Golf ball properties
BALL_MASS = 0.04593            # kg (1.62 oz)
BALL_RADIUS = 0.02135          # m (1.68 inches diameter)
BALL_AREA = math.pi * BALL_RADIUS ** 2  # Cross-sectional area (m²)
BALL_CIRCUMFERENCE = 2 * math.pi * BALL_RADIUS  # m

# Aerodynamic coefficients (typical ranges — refined during trajectory simulation)
CD_BASELINE = 0.23             # Drag coefficient baseline for golf ball
CL_BASELINE = 0.15             # Lift coefficient baseline (Magnus effect)

# Unit conversions
MPH_TO_MS = 0.44704            # mph → m/s
MS_TO_MPH = 1.0 / MPH_TO_MS   # m/s → mph
METERS_TO_YARDS = 1.09361      # m → yards
YARDS_TO_METERS = 1.0 / METERS_TO_YARDS  # yards → m
RPM_TO_RAD_S = 2 * math.pi / 60  # RPM → rad/s

# Spin tilt factor: converts face-to-path angle to spin axis tilt
SPIN_TILT_FACTOR = 0.7

# =============================================================================
# Club Data: Lofts, Smash Factors, Typical Spin Rates
# =============================================================================

# Standard club lofts in degrees
CLUB_LOFTS = {
    "Driver":    10.5,
    "3-Wood":    15.0,
    "5-Wood":    18.0,
    "7-Wood":    21.0,
    "2-Hybrid":  17.0,
    "3-Hybrid":  19.0,
    "4-Hybrid":  22.0,
    "5-Hybrid":  25.0,
    "2-Iron":    17.0,
    "3-Iron":    20.0,
    "4-Iron":    23.0,
    "5-Iron":    26.0,
    "6-Iron":    30.0,
    "7-Iron":    34.0,
    "8-Iron":    38.0,
    "9-Iron":    42.0,
    "PW":        46.0,
    "GW":        50.0,
    "SW":        54.0,
    "LW":        58.0,
    "Putter":    3.0,
}

# Smash factor: ball_speed / club_speed (how efficiently energy transfers)
SMASH_FACTORS = {
    "Driver":    1.48,
    "3-Wood":    1.44,
    "5-Wood":    1.42,
    "7-Wood":    1.40,
    "2-Hybrid":  1.40,
    "3-Hybrid":  1.39,
    "4-Hybrid":  1.38,
    "5-Hybrid":  1.37,
    "2-Iron":    1.38,
    "3-Iron":    1.37,
    "4-Iron":    1.36,
    "5-Iron":    1.35,
    "6-Iron":    1.34,
    "7-Iron":    1.33,
    "8-Iron":    1.32,
    "9-Iron":    1.30,
    "PW":        1.28,
    "GW":        1.25,
    "SW":        1.22,
    "LW":        1.18,
    "Putter":    1.00,
}

# Typical backspin rates (RPM) at standard club speed
TYPICAL_BACKSPIN = {
    "Driver":    2700,
    "3-Wood":    3500,
    "5-Wood":    4300,
    "7-Wood":    4800,
    "2-Hybrid":  3800,
    "3-Hybrid":  4200,
    "4-Hybrid":  4600,
    "5-Hybrid":  5000,
    "2-Iron":    3800,
    "3-Iron":    4200,
    "4-Iron":    4700,
    "5-Iron":    5500,
    "6-Iron":    6200,
    "7-Iron":    7000,
    "8-Iron":    7800,
    "9-Iron":    8600,
    "PW":        9300,
    "GW":       10000,
    "SW":       10500,
    "LW":       11000,
    "Putter":     300,
}

# PGA Tour average carry distances (yards) for validation
PGA_AVERAGE_CARRY = {
    "Driver":    275,
    "3-Wood":    243,
    "5-Wood":    230,
    "3-Hybrid":  225,
    "4-Iron":    210,
    "5-Iron":    200,
    "6-Iron":    188,
    "7-Iron":    172,
    "8-Iron":    160,
    "9-Iron":    148,
    "PW":        136,
    "GW":        124,
    "SW":        112,
    "LW":         95,
}

# PGA Tour average club speeds (mph)
PGA_AVERAGE_CLUB_SPEED = {
    "Driver":    113,
    "3-Wood":    107,
    "5-Wood":    103,
    "3-Hybrid":  100,
    "4-Iron":     97,
    "5-Iron":     94,
    "6-Iron":     92,
    "7-Iron":     90,
    "8-Iron":     87,
    "9-Iron":     85,
    "PW":         83,
    "GW":         80,
    "SW":         78,
    "LW":         74,
}
