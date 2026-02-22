"""
Data models for swing/shot data in IronSight.

ClubData: Raw measurements from the OptiShot 2 sensors.
BallLaunch: Estimated ball launch conditions (derived from ClubData).
TrajectoryResult: Full trajectory computation output.
Shot: Complete shot record combining all data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ClubData:
    """Raw club data as measured by the OptiShot 2 sensors.

    Attributes:
        club_speed_mph: Club head speed at impact (mph).
        face_angle_deg: Face angle at impact (degrees, positive = open).
        path_deg: Swing path (degrees, positive = in-to-out).
        contact_point: Face contact point (0 = center, negative = toe,
                       positive = heel). Unitless sensor value.
        club_type: Name of the selected club (e.g. "7-Iron").
        tempo: Backswing-to-downswing time ratio (optional).
    """
    club_speed_mph: float
    face_angle_deg: float
    path_deg: float
    contact_point: float
    club_type: str
    tempo: Optional[float] = None


@dataclass
class BallLaunch:
    """Estimated ball launch conditions derived from club data.

    These are computed from ClubData using the club-to-ball conversion
    model, not directly measured by the OptiShot.

    Attributes:
        ball_speed_mph: Ball speed off the face (mph).
        vla_deg: Vertical launch angle (degrees).
        hla_deg: Horizontal launch angle (degrees, positive = right).
        backspin_rpm: Backspin rate (RPM).
        spin_axis_deg: Spin axis tilt (degrees, positive = right/fade).
    """
    ball_speed_mph: float
    vla_deg: float
    hla_deg: float
    backspin_rpm: float
    spin_axis_deg: float


@dataclass
class TrajectoryResult:
    """Complete ball flight trajectory output.

    Attributes:
        points: List of (x, y, z) positions in yards.
                x = lateral (positive = right), y = altitude, z = downrange.
        carry_yards: Carry distance (where ball lands).
        total_yards: Total distance including roll (estimated).
        apex_yards: Maximum height of ball flight.
        lateral_yards: Lateral displacement at landing
                       (positive = right).
        flight_time_s: Total flight time in seconds.
    """
    points: list[tuple[float, float, float]]
    carry_yards: float
    total_yards: float
    apex_yards: float
    lateral_yards: float
    flight_time_s: float


@dataclass
class Shot:
    """Complete shot record combining sensor data, launch, and trajectory.

    Attributes:
        id: Database primary key (set after persistence).
        session_id: ID of the session this shot belongs to.
        timestamp: When the shot was taken.
        club_data: Raw sensor measurements from OptiShot.
        ball_launch: Computed ball launch conditions.
        trajectory: Full trajectory result (may be None before computation).
        carry_yards: Carry distance shortcut.
        total_yards: Total distance shortcut.
        lateral_yards: Lateral displacement shortcut.
        apex_yards: Max height shortcut.
        shot_shape: Descriptive shot shape ("Fade", "Draw", "Straight", etc.).
        video_path: Path to the swing video clip (if camera was active).
        ai_feedback: AI coaching feedback text (if analyzed).
    """
    club_data: ClubData
    ball_launch: Optional[BallLaunch] = None
    trajectory: Optional[TrajectoryResult] = None
    carry_yards: float = 0.0
    total_yards: float = 0.0
    lateral_yards: float = 0.0
    apex_yards: float = 0.0
    shot_shape: str = ""
    video_path: Optional[str] = None
    ai_feedback: Optional[str] = None
    id: Optional[int] = None
    session_id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def classify_shot_shape(self) -> str:
        """Classify the shot shape based on launch angle and spin axis."""
        if self.ball_launch is None:
            return "Unknown"

        hla = self.ball_launch.hla_deg
        spin_axis = self.ball_launch.spin_axis_deg

        # Determine curvature from spin axis
        if abs(spin_axis) < 2:
            curve = "Straight"
        elif spin_axis > 0:
            curve = "Fade" if spin_axis < 8 else "Slice"
        else:
            curve = "Draw" if spin_axis > -8 else "Hook"

        # Determine start direction from HLA
        if abs(hla) < 2:
            start = "center"
        elif hla > 0:
            start = "right"
        else:
            start = "left"

        # Combine for full shape description
        if curve == "Straight" and start == "center":
            return "Straight"
        elif curve == "Straight":
            return f"Push" if start == "right" else "Pull"
        else:
            return curve

    def compute_shape(self):
        """Compute and store the shot shape."""
        self.shot_shape = self.classify_shot_shape()
