"""
Club definitions for IronSight.

Provides club type enumeration and lookup of loft, smash factor,
and typical spin rates used in ball flight calculations.
"""

from dataclasses import dataclass
from enum import Enum
from src.utils.constants import CLUB_LOFTS, SMASH_FACTORS, TYPICAL_BACKSPIN


class ClubType(str, Enum):
    """Supported golf club types."""
    DRIVER = "Driver"
    WOOD_3 = "3-Wood"
    WOOD_5 = "5-Wood"
    WOOD_7 = "7-Wood"
    HYBRID_2 = "2-Hybrid"
    HYBRID_3 = "3-Hybrid"
    HYBRID_4 = "4-Hybrid"
    HYBRID_5 = "5-Hybrid"
    IRON_2 = "2-Iron"
    IRON_3 = "3-Iron"
    IRON_4 = "4-Iron"
    IRON_5 = "5-Iron"
    IRON_6 = "6-Iron"
    IRON_7 = "7-Iron"
    IRON_8 = "8-Iron"
    IRON_9 = "9-Iron"
    PW = "PW"
    GW = "GW"
    SW = "SW"
    LW = "LW"
    PUTTER = "Putter"


@dataclass(frozen=True)
class Club:
    """Golf club with physical properties used in ball flight computation."""

    club_type: ClubType
    loft_deg: float
    smash_factor: float
    typical_backspin_rpm: float

    @classmethod
    def from_type(cls, club_type: ClubType | str) -> "Club":
        """Create a Club from its type, looking up standard properties."""
        if isinstance(club_type, str):
            club_type = ClubType(club_type)
        name = club_type.value
        return cls(
            club_type=club_type,
            loft_deg=CLUB_LOFTS[name],
            smash_factor=SMASH_FACTORS[name],
            typical_backspin_rpm=TYPICAL_BACKSPIN[name],
        )

    @property
    def name(self) -> str:
        return self.club_type.value
