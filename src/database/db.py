"""
SQLite database manager for IronSight.

Handles persistence of sessions, shots, and AI feedback.
Database file: ~/.ironsight/ironsight.db
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.shot import ClubData, BallLaunch, Shot, TrajectoryResult
from src.models.session import Session
from src.utils.config import Config

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


class Database:
    """SQLite database wrapper for IronSight data persistence."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Config.get_db_path()
        self.conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        """Initialize database connection and create tables."""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

        # Create tables from schema
        schema = SCHEMA_FILE.read_text()
        self.conn.executescript(schema)
        self.conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    # =========================================================================
    # Sessions
    # =========================================================================

    def create_session(self, session: Session) -> int:
        """Create a new session and return its ID."""
        cur = self.conn.execute(
            "INSERT INTO sessions (start_time, notes) VALUES (?, ?)",
            (session.start_time.isoformat(), session.notes),
        )
        self.conn.commit()
        session.id = cur.lastrowid
        logger.info(f"Session created: id={session.id}")
        return session.id

    def end_session(self, session_id: int):
        """Mark a session as ended."""
        self.conn.execute(
            "UPDATE sessions SET end_time = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id),
        )
        self.conn.commit()

    def get_sessions(self, limit: int = 20) -> list[dict]:
        """Get recent sessions with shot counts."""
        rows = self.conn.execute("""
            SELECT s.id, s.start_time, s.end_time, s.notes,
                   COUNT(sh.id) as num_shots
            FROM sessions s
            LEFT JOIN shots sh ON sh.session_id = s.id
            GROUP BY s.id
            ORDER BY s.start_time DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # Shots
    # =========================================================================

    def save_shot(self, shot: Shot) -> int:
        """Save a shot to the database and return its ID."""
        cd = shot.club_data
        bl = shot.ball_launch
        tr = shot.trajectory

        traj_json = None
        if tr and tr.points:
            traj_json = json.dumps(tr.points)

        cur = self.conn.execute("""
            INSERT INTO shots (
                session_id, timestamp,
                club_type, club_speed_mph, face_angle_deg, path_deg,
                contact_point, tempo,
                ball_speed_mph, vla_deg, hla_deg, backspin_rpm, spin_axis_deg,
                carry_yards, total_yards, apex_yards, lateral_yards,
                flight_time_s, shot_shape, video_path, trajectory_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            shot.session_id, shot.timestamp.isoformat(),
            cd.club_type, cd.club_speed_mph, cd.face_angle_deg, cd.path_deg,
            cd.contact_point, cd.tempo,
            bl.ball_speed_mph if bl else None,
            bl.vla_deg if bl else None,
            bl.hla_deg if bl else None,
            bl.backspin_rpm if bl else None,
            bl.spin_axis_deg if bl else None,
            shot.carry_yards, shot.total_yards, shot.apex_yards,
            shot.lateral_yards,
            tr.flight_time_s if tr else None,
            shot.shot_shape, shot.video_path, traj_json,
        ))
        self.conn.commit()
        shot.id = cur.lastrowid
        return shot.id

    def get_shots(self, session_id: int) -> list[Shot]:
        """Get all shots for a session."""
        rows = self.conn.execute(
            "SELECT * FROM shots WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()

        shots = []
        for r in rows:
            cd = ClubData(
                club_speed_mph=r["club_speed_mph"],
                face_angle_deg=r["face_angle_deg"],
                path_deg=r["path_deg"],
                contact_point=r["contact_point"] or 0,
                club_type=r["club_type"],
                tempo=r["tempo"],
            )
            bl = None
            if r["ball_speed_mph"] is not None:
                bl = BallLaunch(
                    ball_speed_mph=r["ball_speed_mph"],
                    vla_deg=r["vla_deg"],
                    hla_deg=r["hla_deg"],
                    backspin_rpm=r["backspin_rpm"],
                    spin_axis_deg=r["spin_axis_deg"],
                )
            tr = None
            if r["trajectory_json"]:
                points = json.loads(r["trajectory_json"])
                points = [tuple(p) for p in points]
                tr = TrajectoryResult(
                    points=points,
                    carry_yards=r["carry_yards"],
                    total_yards=r["total_yards"],
                    apex_yards=r["apex_yards"],
                    lateral_yards=r["lateral_yards"],
                    flight_time_s=r["flight_time_s"] or 0,
                )
            shot = Shot(
                club_data=cd,
                ball_launch=bl,
                trajectory=tr,
                carry_yards=r["carry_yards"],
                total_yards=r["total_yards"],
                lateral_yards=r["lateral_yards"],
                apex_yards=r["apex_yards"],
                shot_shape=r["shot_shape"] or "",
                video_path=r["video_path"],
                id=r["id"],
                session_id=r["session_id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            shots.append(shot)
        return shots

    def get_session_stats(self, session_id: int) -> dict:
        """Get aggregate stats for a session."""
        row = self.conn.execute("""
            SELECT
                COUNT(*) as num_shots,
                AVG(club_speed_mph) as avg_club_speed,
                AVG(carry_yards) as avg_carry,
                AVG(face_angle_deg) as avg_face_angle,
                AVG(path_deg) as avg_path,
                MIN(carry_yards) as min_carry,
                MAX(carry_yards) as max_carry
            FROM shots WHERE session_id = ?
        """, (session_id,)).fetchone()
        return dict(row) if row else {}

    # =========================================================================
    # AI Feedback
    # =========================================================================

    def save_ai_feedback(
        self,
        shot_id: Optional[int],
        session_id: Optional[int],
        feedback_type: str,
        prompt: str,
        response: str,
        model: str = "claude-sonnet-4-20250514",
        tokens: int = 0,
    ) -> int:
        """Save AI coaching feedback."""
        cur = self.conn.execute("""
            INSERT INTO ai_feedback
                (shot_id, session_id, feedback_type, prompt, response, model, tokens_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (shot_id, session_id, feedback_type, prompt, response, model, tokens))
        self.conn.commit()
        return cur.lastrowid

    def get_ai_feedback(self, shot_id: Optional[int] = None,
                        session_id: Optional[int] = None) -> list[dict]:
        """Get AI feedback for a shot or session."""
        if shot_id:
            rows = self.conn.execute(
                "SELECT * FROM ai_feedback WHERE shot_id = ? ORDER BY created_at DESC",
                (shot_id,),
            ).fetchall()
        elif session_id:
            rows = self.conn.execute(
                "SELECT * FROM ai_feedback WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = []
        return [dict(r) for r in rows]
