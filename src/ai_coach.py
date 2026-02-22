"""
AI Swing Coach for IronSight.

Uses Anthropic's Claude API to analyze golf swings through:
  A) Per-shot analysis: video frames + shot data → coaching tips
  B) Session analysis: aggregate stats → pattern identification
  C) Trend analysis: multi-session comparison → progress tracking

All analysis runs asynchronously (via QThread) to keep the UI responsive.
"""

import base64
import json
import logging
from statistics import mean, stdev
from typing import Optional

import cv2
import anthropic

from src.models.shot import Shot
from src.database.db import Database

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"


class AISwingCoach:
    """Claude-powered golf swing analysis engine.

    Provides per-shot video analysis, session pattern analysis,
    and multi-session trend tracking.

    Attributes:
        client: Anthropic API client.
        db: Database instance for persisting feedback.
    """

    def __init__(self, api_key: Optional[str] = None,
                 db: Optional[Database] = None):
        """
        Args:
            api_key: Anthropic API key. If None, uses ANTHROPIC_API_KEY env var.
            db: Database for persisting AI feedback.
        """
        if api_key:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self.client = anthropic.Anthropic()  # Uses env var
        self.db = db

    def analyze_swing(self, shot: Shot) -> str:
        """Analyze a single swing using video frames + shot data.

        Extracts 4 key frames from the swing video (address, top of
        backswing, impact, follow-through) and sends them alongside
        shot data to Claude for visual swing analysis.

        If no video is available, falls back to data-only analysis.

        Args:
            shot: Complete shot record with club data and optionally video.

        Returns:
            Coaching feedback text from Claude.
        """
        if not shot.video_path:
            return self._analyze_data_only(shot)

        frames = self._extract_key_frames(shot.video_path)
        if not frames:
            return self._analyze_data_only(shot)

        # Build multimodal content with labeled frames
        content = []
        labels = ["Address", "Top of backswing", "Impact", "Follow-through"]

        for frame, label in zip(frames, labels):
            b64 = self._frame_to_base64(frame)
            content.append({"type": "text", "text": f"**{label}:**"})
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            })

        cd = shot.club_data
        bl = shot.ball_launch
        face_label = "open" if cd.face_angle_deg > 0 else "closed"
        path_label = "in-to-out" if cd.path_deg > 0 else "out-to-in"

        content.append({
            "type": "text",
            "text": (
                f"Analyze this golf swing. Shot data from the launch monitor:\n\n"
                f"Club: {cd.club_type}\n"
                f"Club Speed: {cd.club_speed_mph} mph\n"
                f"Face Angle: {cd.face_angle_deg}° ({face_label})\n"
                f"Club Path: {cd.path_deg}° ({path_label})\n"
                f"Face-to-Path: {cd.face_angle_deg - cd.path_deg:.1f}°\n"
                f"Carry Distance: {shot.carry_yards} yards\n"
                f"Shot Shape: {shot.shot_shape}\n\n"
                f"Based on the video frames and data:\n"
                f"1. What is the golfer doing well?\n"
                f"2. What is the primary swing fault visible in the video?\n"
                f"3. Give ONE specific drill or feel to fix it.\n\n"
                f"Be concise and specific. Reference what you see in the frames."
            ),
        })

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": content}],
        )

        feedback = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens

        # Persist to database
        if self.db and shot.id:
            self.db.save_ai_feedback(
                shot_id=shot.id,
                session_id=shot.session_id,
                feedback_type="per_shot",
                prompt="(video + data analysis)",
                response=feedback,
                model=MODEL,
                tokens=tokens,
            )

        return feedback

    def _analyze_data_only(self, shot: Shot) -> str:
        """Fallback: analyze shot data without video frames."""
        cd = shot.club_data
        prompt = (
            f"You are a PGA-certified golf coach. Analyze this shot:\n\n"
            f"Club: {cd.club_type}, Speed: {cd.club_speed_mph}mph\n"
            f"Face: {cd.face_angle_deg}°, Path: {cd.path_deg}°\n"
            f"Face-to-Path: {cd.face_angle_deg - cd.path_deg:.1f}°\n"
            f"Carry: {shot.carry_yards}yd, Shape: {shot.shot_shape}\n\n"
            f"What does this data suggest about the swing? "
            f"Give one specific tip to improve."
        )
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        feedback = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens

        if self.db and shot.id:
            self.db.save_ai_feedback(
                shot_id=shot.id,
                session_id=shot.session_id,
                feedback_type="per_shot",
                prompt=prompt,
                response=feedback,
                model=MODEL,
                tokens=tokens,
            )

        return feedback

    def analyze_session(self, shots: list[Shot]) -> str:
        """Analyze patterns across a practice session (text-only).

        Computes aggregate statistics and sends them to Claude for
        pattern identification. Much cheaper than per-shot video
        analysis (~$0.002 per session).

        Args:
            shots: List of shots from the session (minimum 3).

        Returns:
            Session coaching feedback text.
        """
        if len(shots) < 3:
            return "Need at least 3 shots for session analysis."

        speeds = [s.club_data.club_speed_mph for s in shots]
        faces = [s.club_data.face_angle_deg for s in shots]
        paths = [s.club_data.path_deg for s in shots]
        carries = [s.carry_yards for s in shots if s.carry_yards > 0]
        laterals = [s.lateral_yards for s in shots]

        stats = {
            "club": shots[0].club_data.club_type,
            "num_shots": len(shots),
            "avg_club_speed": round(mean(speeds), 1),
            "std_club_speed": round(stdev(speeds), 1) if len(speeds) > 1 else 0,
            "avg_face_angle": round(mean(faces), 1),
            "std_face_angle": round(stdev(faces), 1) if len(faces) > 1 else 0,
            "avg_path": round(mean(paths), 1),
            "avg_carry": round(mean(carries), 1) if carries else 0,
            "std_carry": round(stdev(carries), 1) if len(carries) > 1 else 0,
            "miss_left_pct": round(
                sum(1 for l in laterals if l < -5) / len(laterals) * 100
            ),
            "miss_right_pct": round(
                sum(1 for l in laterals if l > 5) / len(laterals) * 100
            ),
        }

        prompt = (
            f"You are a PGA-certified golf coach. "
            f"Analyze this practice session data:\n\n"
            f"{json.dumps(stats, indent=2)}\n\n"
            f"Provide:\n"
            f"1. The primary consistency issue you see\n"
            f"2. What this pattern usually indicates about the swing\n"
            f"3. Two specific practice drills to address it\n"
            f"4. What to focus on next session\n\n"
            f"Be direct and actionable, not generic."
        )

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        feedback = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens

        if self.db and shots[0].session_id:
            self.db.save_ai_feedback(
                shot_id=None,
                session_id=shots[0].session_id,
                feedback_type="session",
                prompt=prompt,
                response=feedback,
                model=MODEL,
                tokens=tokens,
            )

        return feedback

    def analyze_trends(self, session_summaries: list[dict]) -> str:
        """Compare multiple sessions to identify improvement or regression.

        Args:
            session_summaries: List of dicts from db.get_session_stats(),
                               ordered chronologically.

        Returns:
            Trend analysis feedback text.
        """
        if len(session_summaries) < 2:
            return "Need at least 2 sessions for trend analysis."

        prompt = (
            f"You are a PGA-certified golf coach tracking a student's "
            f"progress over {len(session_summaries)} practice sessions.\n\n"
            f"Session data (oldest to newest):\n"
            f"{json.dumps(session_summaries, indent=2)}\n\n"
            f"Provide:\n"
            f"1. What has improved\n"
            f"2. What has regressed or stalled\n"
            f"3. Specific focus for the next session\n\n"
            f"Be data-driven and reference specific numbers."
        )

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    # =========================================================================
    # Frame extraction helpers
    # =========================================================================

    def _extract_key_frames(self, video_path: str,
                            num_frames: int = 4) -> list:
        """Extract key frames from swing video.

        Positions: 10%, 35%, 50%, 75% through the clip, corresponding
        roughly to address, top of backswing, impact, follow-through.

        Frames are resized to 640x480 to reduce API token cost.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Cannot open video: {video_path}")
            return []

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total < 10:
            cap.release()
            return []

        positions = [0.10, 0.35, 0.50, 0.75]
        frames = []
        for pos in positions[:num_frames]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * pos))
            ret, frame = cap.read()
            if ret:
                frame = cv2.resize(frame, (640, 480))
                frames.append(frame)

        cap.release()
        return frames

    def _frame_to_base64(self, frame) -> str:
        """Encode an OpenCV frame as base64 JPEG."""
        _, buffer = cv2.imencode(
            '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
        )
        return base64.b64encode(buffer).decode('utf-8')
