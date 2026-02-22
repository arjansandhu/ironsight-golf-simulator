"""
Session model for IronSight.

A session represents one practice period — from when the user starts
hitting balls to when they stop. Contains multiple shots.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from statistics import mean, stdev

from src.models.shot import Shot


@dataclass
class Session:
    """A practice session containing multiple shots.

    Attributes:
        id: Database primary key (set after persistence).
        start_time: When the session started.
        end_time: When the session ended (None if still active).
        shots: List of shots in this session.
        notes: User notes about the session.
    """
    id: Optional[int] = None
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    shots: list[Shot] = field(default_factory=list)
    notes: str = ""

    def add_shot(self, shot: Shot):
        """Add a shot to this session."""
        shot.session_id = self.id
        self.shots.append(shot)

    def end(self):
        """Mark the session as ended."""
        self.end_time = datetime.now()

    @property
    def num_shots(self) -> int:
        return len(self.shots)

    @property
    def duration_minutes(self) -> float:
        """Duration of the session in minutes."""
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds() / 60

    def get_stats(self) -> dict:
        """Compute aggregate statistics for the session."""
        if not self.shots:
            return {}

        speeds = [s.club_data.club_speed_mph for s in self.shots]
        carries = [s.carry_yards for s in self.shots if s.carry_yards > 0]
        faces = [s.club_data.face_angle_deg for s in self.shots]
        paths = [s.club_data.path_deg for s in self.shots]

        stats = {
            "num_shots": len(self.shots),
            "duration_minutes": round(self.duration_minutes, 1),
            "avg_club_speed": round(mean(speeds), 1),
            "avg_carry": round(mean(carries), 1) if carries else 0,
            "avg_face_angle": round(mean(faces), 1),
            "avg_path": round(mean(paths), 1),
        }

        if len(speeds) > 1:
            stats["std_club_speed"] = round(stdev(speeds), 1)
        if len(carries) > 1:
            stats["std_carry"] = round(stdev(carries), 1)
        if len(faces) > 1:
            stats["std_face_angle"] = round(stdev(faces), 1)

        return stats
