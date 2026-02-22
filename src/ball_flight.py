"""
Ball flight physics engine for IronSight.

Two-stage model:
  1. Club data → ball launch conditions (club_to_ball_launch)
  2. Ball launch → 3D trajectory via ODE integration (compute_trajectory)

Physics based on:
  - MacDonald & Hanzely (1991) — drag and lift on a spinning sphere
  - cagrell/golfmodel — Python implementation reference
  - D-Plane model for face/path → launch direction and spin axis

Uses scipy.integrate.solve_ivp for trajectory simulation with:
  - Gravitational force
  - Aerodynamic drag (Reynolds-number dependent)
  - Magnus lift (spin-dependent)
"""

import math
import logging
from typing import Optional

import numpy as np
from scipy.integrate import solve_ivp

from src.models.shot import ClubData, BallLaunch, TrajectoryResult
from src.utils.constants import (
    AIR_DENSITY,
    GRAVITY,
    BALL_MASS,
    BALL_RADIUS,
    BALL_AREA,
    CD_BASELINE,
    CL_BASELINE,
    MPH_TO_MS,
    MS_TO_MPH,
    METERS_TO_YARDS,
    YARDS_TO_METERS,
    RPM_TO_RAD_S,
    SPIN_TILT_FACTOR,
    CLUB_LOFTS,
    SMASH_FACTORS,
    TYPICAL_BACKSPIN,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Stage 1: Club Data → Ball Launch Conditions
# =============================================================================

def club_to_ball_launch(club_data: ClubData) -> BallLaunch:
    """Convert raw club measurements to estimated ball launch conditions.

    Uses the D-Plane model:
    - Ball speed = club speed × smash factor
    - Launch direction: ~75% face, ~25% path (for irons)
    - Vertical launch: function of dynamic loft
    - Spin: function of ball speed, dynamic loft, and club type
    - Spin axis: derived from face-to-path angle

    Args:
        club_data: Raw club measurements from OptiShot.

    Returns:
        BallLaunch with estimated ball conditions.
    """
    club = club_data.club_type
    club_speed = club_data.club_speed_mph
    face_angle = club_data.face_angle_deg
    path = club_data.path_deg

    # Smash factor: how efficiently club speed transfers to ball speed
    smash = SMASH_FACTORS.get(club, 1.35)
    ball_speed = club_speed * smash

    # Dynamic loft: static loft adjusted by face angle
    base_loft = CLUB_LOFTS.get(club, 30.0)
    dynamic_loft = base_loft + (face_angle * 0.7)

    # Vertical launch angle: percentage of dynamic loft
    # Higher lofted clubs launch a higher % of their loft
    loft_ratio = 0.75 + (base_loft / 200)  # ~0.80 for driver, ~0.92 for LW
    vla = dynamic_loft * loft_ratio

    # Clamp VLA to reasonable range
    vla = max(2.0, min(55.0, vla))

    # Horizontal launch angle (D-Plane)
    # For irons: ~75% face, ~25% path
    # For driver: ~85% face, ~15% path (gear effect)
    if club == "Driver":
        face_contrib = 0.85
    elif club == "Putter":
        face_contrib = 0.90
    else:
        face_contrib = 0.75
    path_contrib = 1.0 - face_contrib

    hla = face_angle * face_contrib + path * path_contrib

    # Face-to-path angle determines spin axis (curve direction)
    face_to_path = face_angle - path

    # Backspin estimation
    backspin = _estimate_backspin(ball_speed, dynamic_loft, club)

    # Spin axis from face-to-path
    # Positive = tilted right (fade/slice), Negative = tilted left (draw/hook)
    if backspin > 0:
        spin_axis = math.degrees(
            math.atan2(
                face_to_path * SPIN_TILT_FACTOR * backspin / 3000,
                backspin / 1000
            )
        )
    else:
        spin_axis = 0.0

    # Clamp spin axis
    spin_axis = max(-45, min(45, spin_axis))

    return BallLaunch(
        ball_speed_mph=round(ball_speed, 1),
        vla_deg=round(vla, 1),
        hla_deg=round(hla, 1),
        backspin_rpm=round(backspin),
        spin_axis_deg=round(spin_axis, 1),
    )


def _estimate_backspin(ball_speed_mph: float, dynamic_loft: float,
                       club: str) -> float:
    """Estimate backspin RPM from ball speed and dynamic loft.

    Higher loft and lower ball speed → more backspin.
    Based on empirical relationships from launch monitor data.

    Args:
        ball_speed_mph: Ball speed in mph.
        dynamic_loft: Dynamic loft at impact in degrees.
        club: Club name string.

    Returns:
        Estimated backspin in RPM.
    """
    # Base spin from club type
    base_spin = TYPICAL_BACKSPIN.get(club, 5000)

    # Adjust for dynamic loft deviation from standard
    standard_loft = CLUB_LOFTS.get(club, 30.0)
    loft_delta = dynamic_loft - standard_loft
    spin_adjust = loft_delta * 200  # ~200 RPM per degree of added loft

    # Adjust for ball speed (faster = less spin for same club)
    # Normalized around typical amateur speeds
    typical_speed = SMASH_FACTORS.get(club, 1.35) * 85  # rough amateur baseline
    speed_ratio = ball_speed_mph / max(typical_speed, 1.0)
    speed_factor = 1.0 + (1.0 - speed_ratio) * 0.3  # ±30% adjustment

    backspin = (base_spin + spin_adjust) * speed_factor
    return max(500, min(14000, backspin))  # Clamp to physical range


# =============================================================================
# Stage 2: Trajectory Simulation (ODE Integration)
# =============================================================================

def compute_trajectory(
    launch: BallLaunch,
    wind_speed_mph: float = 0.0,
    wind_direction_deg: float = 0.0,
    dt_max: float = 0.01,
    t_max: float = 15.0,
) -> TrajectoryResult:
    """Simulate full 3D ball flight trajectory.

    Integrates the equations of motion for a spinning golf ball
    under gravity, aerodynamic drag, and Magnus lift.

    Coordinate system (yards):
        x = lateral (positive = right of target)
        y = vertical (altitude above ground)
        z = downrange (positive = toward target)

    Args:
        launch: Ball launch conditions.
        wind_speed_mph: Wind speed in mph.
        wind_direction_deg: Wind coming FROM this direction (0=N, 90=E).
        dt_max: Maximum time step for ODE solver.
        t_max: Maximum simulation time in seconds.

    Returns:
        TrajectoryResult with trajectory points and summary stats.
    """
    # Convert launch conditions to SI units (m, m/s, rad/s)
    v0 = launch.ball_speed_mph * MPH_TO_MS
    vla_rad = math.radians(launch.vla_deg)
    hla_rad = math.radians(launch.hla_deg)

    # Initial velocity components
    vx0 = v0 * math.cos(vla_rad) * math.sin(hla_rad)  # lateral
    vy0 = v0 * math.sin(vla_rad)                        # vertical
    vz0 = v0 * math.cos(vla_rad) * math.cos(hla_rad)   # downrange

    # Spin: decompose into components using spin axis
    total_spin_rps = launch.backspin_rpm / 60.0  # rev/s
    spin_axis_rad = math.radians(launch.spin_axis_deg)

    # Backspin is around the horizontal axis perpendicular to flight
    # Sidespin from spin axis tilt
    omega_backspin = total_spin_rps * math.cos(spin_axis_rad) * 2 * math.pi
    omega_sidespin = total_spin_rps * math.sin(spin_axis_rad) * 2 * math.pi

    # Wind in m/s (wind_direction is where it comes FROM)
    wind_v = wind_speed_mph * MPH_TO_MS
    wind_rad = math.radians(wind_direction_deg)
    wind_x = -wind_v * math.sin(wind_rad)  # lateral
    wind_z = -wind_v * math.cos(wind_rad)  # downrange

    # State vector: [x, y, z, vx, vy, vz]
    y0 = [0.0, 0.0, 0.0, vx0, vy0, vz0]

    # Spin decay rate (exponential, ~1% per second)
    spin_decay_rate = 0.01

    def derivatives(t, state):
        """ODE right-hand side: equations of motion for a spinning golf ball."""
        x, y, z, vx, vy, vz = state

        # Velocity relative to air (accounting for wind)
        vrel_x = vx - wind_x
        vrel_y = vy
        vrel_z = vz - wind_z
        v_rel = math.sqrt(vrel_x**2 + vrel_y**2 + vrel_z**2)

        if v_rel < 0.1:
            return [vx, vy, vz, 0, -GRAVITY, 0]

        # Unit velocity vector
        ux = vrel_x / v_rel
        uy = vrel_y / v_rel
        uz = vrel_z / v_rel

        # Current spin rate with decay
        current_spin_rps = total_spin_rps * math.exp(-spin_decay_rate * t)

        # --- Drag force ---
        # Spin ratio = surface speed / translational speed
        spin_ratio = (current_spin_rps * 2 * math.pi * BALL_RADIUS) / v_rel
        cd = _drag_coefficient(spin_ratio, v_rel)
        F_drag = 0.5 * cd * AIR_DENSITY * BALL_AREA * v_rel**2

        drag_x = -F_drag * ux / BALL_MASS
        drag_y = -F_drag * uy / BALL_MASS
        drag_z = -F_drag * uz / BALL_MASS

        # --- Magnus lift force ---
        # The Magnus force acts perpendicular to both velocity and spin axis.
        # For backspin: creates upward lift.
        # For tilted spin axis: creates lateral force (curve).
        #
        # Spin vector in body frame (backspin = rotation around lateral axis):
        #   omega = (omega_side, 0, omega_back) approximately
        # We use the cross product omega × v to get lift direction.

        cl = _lift_coefficient(spin_ratio)
        F_lift = 0.5 * cl * AIR_DENSITY * BALL_AREA * v_rel**2

        # Decompose lift based on spin axis angle:
        # spin_axis = 0° → pure backspin → all lift is upward
        # spin_axis = ±45° → mix of backspin and sidespin
        backspin_fraction = math.cos(spin_axis_rad)
        sidespin_fraction = math.sin(spin_axis_rad)

        # Backspin component: lift perpendicular to velocity in the
        # vertical plane (upward when ball is moving forward)
        # We need the lift to be perpendicular to velocity, not just "up"
        v_horiz = math.sqrt(vrel_x**2 + vrel_z**2)
        if v_horiz > 0.1:
            # Upward component of backspin lift
            lift_y = F_lift * backspin_fraction * v_horiz / v_rel / BALL_MASS
            # The backspin lift also has a small backward component
            # (it's perpendicular to velocity, not purely vertical)
        else:
            lift_y = F_lift * backspin_fraction / BALL_MASS

        # Sidespin component: lateral force
        lift_x = F_lift * sidespin_fraction / BALL_MASS

        # Total accelerations
        ax = drag_x + lift_x
        ay = drag_y + lift_y - GRAVITY
        az = drag_z

        return [vx, vy, vz, ax, ay, az]

    def hit_ground(t, state):
        """Event: ball returns to ground level (y = 0)."""
        return state[1]

    hit_ground.terminal = True
    hit_ground.direction = -1  # Only trigger when y is decreasing

    # Integrate
    sol = solve_ivp(
        derivatives,
        [0, t_max],
        y0,
        method="RK45",
        max_step=dt_max,
        events=[hit_ground],
        dense_output=True,
    )

    if not sol.success:
        logger.warning(f"ODE integration failed: {sol.message}")
        return TrajectoryResult(
            points=[(0, 0, 0)],
            carry_yards=0,
            total_yards=0,
            apex_yards=0,
            lateral_yards=0,
            flight_time_s=0,
        )

    # Extract trajectory points in yards
    points = []
    apex = 0.0
    for i in range(len(sol.t)):
        x_yd = sol.y[0][i] * METERS_TO_YARDS
        y_yd = sol.y[1][i] * METERS_TO_YARDS
        z_yd = sol.y[2][i] * METERS_TO_YARDS
        points.append((round(x_yd, 1), round(max(0, y_yd), 1), round(z_yd, 1)))
        apex = max(apex, y_yd)

    # Landing point
    if points:
        landing_x = points[-1][0]
        landing_z = points[-1][2]
    else:
        landing_x = 0
        landing_z = 0

    carry = math.sqrt(landing_x**2 + landing_z**2)

    # Estimate roll (simplified: percentage of carry based on launch angle)
    # Low launch + low spin = more roll
    roll_factor = max(0.02, 0.15 - launch.vla_deg / 200 - launch.backspin_rpm / 100000)
    total = carry + carry * roll_factor

    flight_time = sol.t[-1] if len(sol.t) > 0 else 0

    return TrajectoryResult(
        points=points,
        carry_yards=round(carry, 1),
        total_yards=round(total, 1),
        apex_yards=round(apex, 1),
        lateral_yards=round(landing_x, 1),
        flight_time_s=round(flight_time, 2),
    )


def _drag_coefficient(spin_ratio: float, velocity: float) -> float:
    """Compute drag coefficient based on spin ratio and velocity.

    Based on experimental data for dimpled golf balls. The drag crisis
    occurs around Re ~ 1e5, where C_D drops from ~0.5 to ~0.25 due
    to the dimples tripping the boundary layer to turbulent.

    Args:
        spin_ratio: Dimensionless spin parameter (omega * R / v).
        velocity: Ball velocity in m/s.

    Returns:
        Drag coefficient C_D.
    """
    # Reynolds number
    Re = (AIR_DENSITY * velocity * 2 * BALL_RADIUS) / 1.81e-5

    # Base Cd for dimpled ball
    if Re > 1e5:
        cd_base = 0.225  # Post-critical (turbulent BL from dimples)
    else:
        cd_base = 0.40   # Pre-critical (rare in golf, very slow ball)

    # Spin increases drag slightly
    cd = cd_base + 0.10 * spin_ratio
    return min(cd, 0.55)


def _lift_coefficient(spin_ratio: float) -> float:
    """Compute lift coefficient (Magnus effect) for a dimpled golf ball.

    The relationship between spin ratio and C_L for a golf ball is
    approximately linear at low spin ratios and saturates at higher
    values. Based on Bearman & Harvey (1976) and Smits & Smith (1994)
    wind tunnel data for dimpled spheres.

    Typical golf ball spin ratios: 0.08 (driver) to 0.25 (wedge).
    Corresponding C_L values: ~0.18 to ~0.28.

    Args:
        spin_ratio: Dimensionless spin parameter (omega * R / v).

    Returns:
        Lift coefficient C_L.
    """
    # Piecewise linear fit to experimental data:
    # - At spin_ratio = 0.1: C_L ≈ 0.18
    # - At spin_ratio = 0.2: C_L ≈ 0.25
    # - Saturates around C_L = 0.32
    if spin_ratio < 0.01:
        return 0.0
    cl = 0.12 + 0.8 * spin_ratio
    return min(cl, 0.32)


# =============================================================================
# Convenience: Full pipeline from club data to trajectory
# =============================================================================

def compute_shot(club_data: ClubData,
                 wind_speed_mph: float = 0.0,
                 wind_direction_deg: float = 0.0) -> tuple[BallLaunch, TrajectoryResult]:
    """Full pipeline: club data → ball launch → trajectory.

    This is the main entry point for computing a shot from raw
    OptiShot sensor data.

    Args:
        club_data: Raw club measurements.
        wind_speed_mph: Wind speed.
        wind_direction_deg: Wind direction (FROM).

    Returns:
        Tuple of (BallLaunch, TrajectoryResult).
    """
    launch = club_to_ball_launch(club_data)
    trajectory = compute_trajectory(
        launch,
        wind_speed_mph=wind_speed_mph,
        wind_direction_deg=wind_direction_deg,
    )

    logger.info(
        f"Shot computed: {club_data.club_type} "
        f"ball_speed={launch.ball_speed_mph}mph, "
        f"VLA={launch.vla_deg}°, "
        f"carry={trajectory.carry_yards}yd, "
        f"apex={trajectory.apex_yards}yd"
    )

    return launch, trajectory
