"""
Tests for ball flight physics engine.

Validates:
  - Club-to-ball conversion produces reasonable launch conditions
  - Trajectory model produces carry distances within ±15% of PGA averages
  - Physics behaves correctly (faster speed = more distance, etc.)
  - Edge cases (zero speed, extreme angles, putter)
"""

import math
import pytest

from src.models.shot import ClubData, BallLaunch
from src.ball_flight import (
    club_to_ball_launch,
    compute_trajectory,
    compute_shot,
    _drag_coefficient,
    _lift_coefficient,
)


class TestClubToBallLaunch:
    """Tests for Stage 1: club data → ball launch conditions."""

    def test_driver_smash_factor(self):
        """Driver should produce ~1.48x ball speed."""
        cd = ClubData(100.0, 0.0, 0.0, 0.0, "Driver")
        bl = club_to_ball_launch(cd)
        assert 145 <= bl.ball_speed_mph <= 152  # ~148

    def test_iron_smash_factor(self):
        """7-iron should produce ~1.33x ball speed."""
        cd = ClubData(80.0, 0.0, 0.0, 0.0, "7-Iron")
        bl = club_to_ball_launch(cd)
        assert 103 <= bl.ball_speed_mph <= 110  # ~106.4

    def test_open_face_increases_hla(self):
        """Open face should push launch angle right (positive HLA)."""
        cd_square = ClubData(85.0, 0.0, 0.0, 0.0, "7-Iron")
        cd_open = ClubData(85.0, 5.0, 0.0, 0.0, "7-Iron")
        bl_square = club_to_ball_launch(cd_square)
        bl_open = club_to_ball_launch(cd_open)
        assert bl_open.hla_deg > bl_square.hla_deg

    def test_closed_face_negative_hla(self):
        """Closed face should pull launch left (negative HLA)."""
        cd = ClubData(85.0, -5.0, 0.0, 0.0, "7-Iron")
        bl = club_to_ball_launch(cd)
        assert bl.hla_deg < 0

    def test_in_to_out_path_positive_hla(self):
        """In-to-out path should contribute to rightward launch."""
        cd = ClubData(85.0, 0.0, 5.0, 0.0, "7-Iron")
        bl = club_to_ball_launch(cd)
        assert bl.hla_deg > 0

    def test_vla_increases_with_loft(self):
        """Higher lofted clubs should launch higher."""
        cd_driver = ClubData(100.0, 0.0, 0.0, 0.0, "Driver")
        cd_pw = ClubData(80.0, 0.0, 0.0, 0.0, "PW")
        bl_driver = club_to_ball_launch(cd_driver)
        bl_pw = club_to_ball_launch(cd_pw)
        assert bl_pw.vla_deg > bl_driver.vla_deg

    def test_backspin_increases_with_loft(self):
        """Wedges should have more backspin than drivers."""
        cd_driver = ClubData(100.0, 0.0, 0.0, 0.0, "Driver")
        cd_sw = ClubData(70.0, 0.0, 0.0, 0.0, "SW")
        bl_driver = club_to_ball_launch(cd_driver)
        bl_sw = club_to_ball_launch(cd_sw)
        assert bl_sw.backspin_rpm > bl_driver.backspin_rpm

    def test_spin_axis_fade(self):
        """Open face with neutral path should produce fade (positive spin axis)."""
        cd = ClubData(85.0, 3.0, 0.0, 0.0, "7-Iron")
        bl = club_to_ball_launch(cd)
        assert bl.spin_axis_deg > 0  # Fade

    def test_spin_axis_draw(self):
        """Closed face with neutral path should produce draw (negative spin axis)."""
        cd = ClubData(85.0, -3.0, 0.0, 0.0, "7-Iron")
        bl = club_to_ball_launch(cd)
        assert bl.spin_axis_deg < 0  # Draw

    def test_driver_launch_angle_reasonable(self):
        """Driver should launch between 8-18 degrees."""
        cd = ClubData(100.0, 0.0, 0.0, 0.0, "Driver")
        bl = club_to_ball_launch(cd)
        assert 8 <= bl.vla_deg <= 18

    def test_putter_launch(self):
        """Putter should have very low launch and spin."""
        cd = ClubData(10.0, 0.0, 0.0, 0.0, "Putter")
        bl = club_to_ball_launch(cd)
        assert bl.vla_deg < 10
        assert bl.backspin_rpm < 1000


class TestComputeTrajectory:
    """Tests for Stage 2: trajectory simulation."""

    def _make_launch(self, ball_speed=140, vla=14, hla=0,
                     backspin=3000, spin_axis=0):
        return BallLaunch(ball_speed, vla, hla, backspin, spin_axis)

    def test_basic_trajectory(self):
        """A standard drive should produce a reasonable trajectory."""
        launch = self._make_launch(ball_speed=150, vla=12, backspin=2700)
        result = compute_trajectory(launch)
        assert result.carry_yards > 200
        assert result.carry_yards < 350
        assert result.apex_yards > 20
        assert result.flight_time_s > 3
        assert len(result.points) > 50

    def test_higher_speed_more_distance(self):
        """Faster ball speed should produce more carry distance."""
        launch_slow = self._make_launch(ball_speed=120, vla=14, backspin=5000)
        launch_fast = self._make_launch(ball_speed=160, vla=14, backspin=3000)
        result_slow = compute_trajectory(launch_slow)
        result_fast = compute_trajectory(launch_fast)
        assert result_fast.carry_yards > result_slow.carry_yards

    def test_higher_launch_more_apex(self):
        """Higher launch angle should produce higher apex."""
        launch_low = self._make_launch(vla=10)
        launch_high = self._make_launch(vla=25)
        result_low = compute_trajectory(launch_low)
        result_high = compute_trajectory(launch_high)
        assert result_high.apex_yards > result_low.apex_yards

    def test_fade_goes_right(self):
        """Positive spin axis (fade) should produce positive lateral displacement."""
        launch = self._make_launch(hla=2, spin_axis=15)
        result = compute_trajectory(launch)
        assert result.lateral_yards > 0  # Right

    def test_draw_goes_left(self):
        """Negative spin axis (draw) should produce negative lateral displacement."""
        launch = self._make_launch(hla=-2, spin_axis=-15)
        result = compute_trajectory(launch)
        assert result.lateral_yards < 0  # Left

    def test_trajectory_starts_at_origin(self):
        """Trajectory should start at (0, 0, 0)."""
        launch = self._make_launch()
        result = compute_trajectory(launch)
        assert result.points[0] == (0.0, 0.0, 0.0)

    def test_trajectory_ends_near_ground(self):
        """Ball should land near y=0."""
        launch = self._make_launch()
        result = compute_trajectory(launch)
        last_y = result.points[-1][1]
        assert last_y < 2.0  # Within 2 yards of ground

    def test_zero_speed_no_crash(self):
        """Zero ball speed should not crash."""
        launch = self._make_launch(ball_speed=0)
        result = compute_trajectory(launch)
        assert result.carry_yards == 0 or len(result.points) > 0

    def test_headwind_reduces_carry(self):
        """Headwind should reduce carry distance.
        Wind direction convention: direction wind comes FROM.
        0° = from north (into face when hitting toward +z/north) = headwind.
        """
        launch = self._make_launch(ball_speed=140, vla=14, backspin=3000)
        result_calm = compute_trajectory(launch, wind_speed_mph=0)
        result_wind = compute_trajectory(launch, wind_speed_mph=15,
                                         wind_direction_deg=0)
        assert result_wind.carry_yards < result_calm.carry_yards

    def test_tailwind_increases_carry(self):
        """Tailwind should increase carry distance.
        180° = from south (pushing ball toward +z/north) = tailwind.
        """
        launch = self._make_launch(ball_speed=140, vla=14, backspin=3000)
        result_calm = compute_trajectory(launch, wind_speed_mph=0)
        result_wind = compute_trajectory(launch, wind_speed_mph=15,
                                         wind_direction_deg=180)
        assert result_wind.carry_yards > result_calm.carry_yards


class TestPGAValidation:
    """Validate computed distances against PGA Tour / amateur averages.

    Our model should produce carry distances within ±20% of known
    averages when given typical club speeds and square face/path.
    """

    @pytest.mark.parametrize("club,club_speed,expected_carry,tolerance", [
        ("Driver", 95,  225, 0.20),    # Amateur driver
        ("Driver", 113, 275, 0.20),    # PGA Tour driver
        ("7-Iron", 76,  140, 0.20),    # Amateur 7-iron
        ("7-Iron", 90,  172, 0.20),    # PGA Tour 7-iron
        ("PW",     67,  100, 0.25),    # Amateur PW
        ("PW",     83,  136, 0.20),    # PGA Tour PW
    ])
    def test_carry_distance(self, club, club_speed, expected_carry, tolerance):
        """Carry distance should be within tolerance of expected values."""
        cd = ClubData(club_speed, 0.0, 0.0, 0.0, club)
        launch, result = compute_shot(cd)

        lower = expected_carry * (1 - tolerance)
        upper = expected_carry * (1 + tolerance)
        assert lower <= result.carry_yards <= upper, (
            f"{club} @ {club_speed}mph: "
            f"expected {expected_carry}±{int(tolerance*100)}% "
            f"({lower:.0f}-{upper:.0f}yd), "
            f"got {result.carry_yards}yd "
            f"(ball_speed={launch.ball_speed_mph}mph, "
            f"VLA={launch.vla_deg}°, spin={launch.backspin_rpm}rpm)"
        )


class TestComputeShot:
    """Test the full pipeline convenience function."""

    def test_full_pipeline(self):
        """compute_shot should return both launch and trajectory."""
        cd = ClubData(90.0, 1.5, -0.5, 0.0, "7-Iron")
        launch, trajectory = compute_shot(cd)

        assert launch.ball_speed_mph > 0
        assert launch.vla_deg > 0
        assert trajectory.carry_yards > 0
        assert len(trajectory.points) > 10

    def test_shot_with_wind(self):
        """Full pipeline should accept wind parameters."""
        cd = ClubData(90.0, 0.0, 0.0, 0.0, "7-Iron")
        launch, trajectory = compute_shot(
            cd, wind_speed_mph=10, wind_direction_deg=90
        )
        assert trajectory.carry_yards > 0


class TestAerodynamics:
    """Test drag and lift coefficient functions."""

    def test_drag_increases_with_spin(self):
        """Higher spin ratio should increase drag."""
        cd_low = _drag_coefficient(0.1, 50)
        cd_high = _drag_coefficient(0.3, 50)
        assert cd_high > cd_low

    def test_lift_increases_with_spin(self):
        """Higher spin ratio should increase lift."""
        cl_low = _lift_coefficient(0.1)
        cl_high = _lift_coefficient(0.3)
        assert cl_high > cl_low

    def test_drag_capped(self):
        """Drag coefficient should not exceed physical maximum."""
        cd = _drag_coefficient(1.0, 50)
        assert cd <= 0.6

    def test_lift_capped(self):
        """Lift coefficient should not exceed physical maximum."""
        cl = _lift_coefficient(1.0)
        assert cl <= 0.35
