"""
Tests for AI swing coach.

Uses mocked Anthropic client to avoid real API calls in CI.
Tests frame extraction, data formatting, and response handling.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from src.models.shot import ClubData, BallLaunch, Shot


class TestFrameExtraction:
    """Test video frame extraction helpers."""

    def test_frame_to_base64(self):
        """Should encode a frame as a non-trivial base64 string."""
        from src.ai_coach import AISwingCoach
        coach = AISwingCoach.__new__(AISwingCoach)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        b64 = coach._frame_to_base64(frame)
        assert isinstance(b64, str)
        assert len(b64) > 100  # Non-trivial base64

    def test_extract_key_frames_missing_file(self):
        """Should return empty list for missing video file."""
        from src.ai_coach import AISwingCoach
        coach = AISwingCoach.__new__(AISwingCoach)
        frames = coach._extract_key_frames("/nonexistent/video.mp4")
        assert frames == []


class TestAnalyzeSwing:
    """Test per-shot analysis with mocked API."""

    def _make_shot(self, video_path=None):
        return Shot(
            club_data=ClubData(90.0, 1.0, 0.5, 0, "7-Iron"),
            ball_launch=BallLaunch(119.0, 16.3, 0.8, 7000, 0.4),
            carry_yards=172.0,
            total_yards=180.0,
            lateral_yards=3.5,
            apex_yards=28.0,
            shot_shape="Fade",
            video_path=video_path,
            id=1,
            session_id=1,
        )

    @patch("src.ai_coach.anthropic")
    def test_data_only_fallback(self, mock_anthropic):
        """When no video_path, should fall back to data-only analysis."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Good tempo, slight fade.")]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_client.messages.create.return_value = mock_response

        from src.ai_coach import AISwingCoach
        coach = AISwingCoach.__new__(AISwingCoach)
        coach.client = mock_client
        coach.db = None

        shot = self._make_shot(video_path=None)
        result = coach._analyze_data_only(shot)

        assert result == "Good tempo, slight fade."
        mock_client.messages.create.assert_called_once()

        # Check prompt includes shot data
        call_args = mock_client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "7-Iron" in prompt
        assert "90.0" in prompt


class TestAnalyzeSession:
    """Test session analysis with mocked API."""

    def _make_shots(self, n=5):
        shots = []
        for i in range(n):
            shots.append(Shot(
                club_data=ClubData(85 + i, 1.0 + i * 0.5, -0.5, 0, "7-Iron"),
                ball_launch=BallLaunch(112 + i, 16, 0.8 + i * 0.3, 7000, 0.4 + i * 0.1),
                carry_yards=165 + i * 3,
                total_yards=175 + i * 3,
                lateral_yards=2.0 + i,
                apex_yards=25,
                shot_shape="Fade",
                session_id=1,
            ))
        return shots

    def test_minimum_shots_required(self):
        """Should require at least 3 shots for session analysis."""
        from src.ai_coach import AISwingCoach
        coach = AISwingCoach.__new__(AISwingCoach)
        coach.client = MagicMock()
        coach.db = None

        shots = self._make_shots(2)
        result = coach.analyze_session(shots)
        assert "at least 3" in result.lower()

    @patch("src.ai_coach.anthropic")
    def test_session_analysis_calls_api(self, mock_anthropic):
        """Session analysis with 5+ shots should call the API."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Pattern: open face.")]
        mock_response.usage.input_tokens = 200
        mock_response.usage.output_tokens = 100
        mock_client.messages.create.return_value = mock_response

        from src.ai_coach import AISwingCoach
        coach = AISwingCoach.__new__(AISwingCoach)
        coach.client = mock_client
        coach.db = None

        shots = self._make_shots(5)
        result = coach.analyze_session(shots)

        assert result == "Pattern: open face."
        mock_client.messages.create.assert_called_once()

        # Check the prompt includes stats
        call_args = mock_client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "avg_club_speed" in prompt
        assert "7-Iron" in prompt


class TestAnalyzeTrends:
    """Test trend analysis with mocked API."""

    def test_minimum_sessions_required(self):
        """Should require at least 2 sessions for trend analysis."""
        from src.ai_coach import AISwingCoach
        coach = AISwingCoach.__new__(AISwingCoach)
        coach.client = MagicMock()

        result = coach.analyze_trends([{"avg_carry": 170}])
        assert "at least 2" in result.lower()
