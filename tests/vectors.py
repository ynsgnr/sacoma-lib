"""Test vectors: two real device measurements with expected outputs.

Subject: height 165 cm, age 30, male, athlete. ``DISPLAY`` carries app-rounded expected
values; ``EXACT`` carries full-precision expected values.
"""
from dataclasses import dataclass
from typing import List, Optional


def _frame(b: str) -> bytes:
    return bytes.fromhex(b.replace(" ", ""))


@dataclass
class Vector:
    name: str
    weight_kg: float
    impedances_ohm: List[float]
    a3_frames: Optional[List[bytes]] = None   # raw A3 frames (device captures only)
    # user profile
    height_cm: float = 165.0
    age: int = 30
    sex: int = 1                    # 0 = female, 1 = male
    people_type: int = 1            # 0 = normal, 1 = athlete
    bmi: Optional[float] = None
    body_fat_percent: Optional[float] = None
    muscle_percent: Optional[float] = None
    skeletal_muscle_percent: Optional[float] = None
    body_water_percent: Optional[float] = None
    protein_percent: Optional[float] = None
    bone_mass_kg: Optional[float] = None
    visceral_fat: Optional[float] = None
    bmr_kcal: Optional[int] = None
    metabolic_age: Optional[float] = None
    body_score: Optional[float] = None
    whr: Optional[float] = None
    # left_arm, right_arm, left_leg, right_leg, trunk
    segment_fat_kg: Optional[List[float]] = None
    segment_muscle_kg: Optional[List[float]] = None


DISPLAY = Vector(
    name="display",
    a3_frames=[
        _frame("01 1a 00 a3 19 00 fd 02 00 00 d3 0b 85 0b 4e 0a 74 0a f6 15"),
        _frame("01 1a 01 00 96 0a 0a 09 ec 09 2d 09 b6 00 00 00 00 00 00 14"),
    ],
    weight_kg=64.77,
    impedances_ohm=[21.1, 294.9, 289.4, 267.6, 280.6, 15.0, 257.0, 254.0, 234.9, 248.6],
    bmi=23.8,
    body_fat_percent=15.9,
    bone_mass_kg=3.7,
    visceral_fat=3.0,
    bmr_kcal=1547,
    metabolic_age=28,
    segment_fat_kg=[0.4, 0.4, 1.8, 1.8, 5.6],
)

EXACT = Vector(
    name="exact",
    a3_frames=[
        _frame("02 1a 00 a3 19 00 fe 06 00 00 cf 0b 26 0a f9 09 f3 0a 7d 0a"),
        _frame("02 1a 01 00 8c 09 a6 09 9e 08 c2 09 55 00 00 00 00 00 00 0a"),
    ],
    weight_kg=65.03,
    impedances_ohm=[20.7, 285.4, 280.9, 254.7, 268.5, 14.0, 247.0, 246.2, 224.2, 238.9],
    bmi=23.9,
    body_fat_percent=15.2,
    muscle_percent=79.1,
    skeletal_muscle_percent=47.8,
    body_water_percent=62.1,
    protein_percent=17.0,
    bone_mass_kg=3.7,
    visceral_fat=2.0,
    bmr_kcal=1560,
    metabolic_age=28.0,
    body_score=83.0,
    whr=0.89,
    segment_fat_kg=[0.3466890690242769, 0.3665922690242768,
                    1.7313771483345035, 1.7479206483345036, 5.444233703420809],
    segment_muscle_kg=[3.162521522394943, 3.1543956223949436,
                       8.988052167350006, 9.006102267350006, 23.987975009398394],
)

# Additional reference profiles (other heights / sexes / ages) with expected outputs.
_b = [20.7, 285.4, 280.9, 254.7, 268.5, 14.0, 247.0, 246.2, 224.2, 238.9]
_hi = [round(z * 1.18, 1) for z in _b]

PROFILES = [
    Vector("tall_male", 82.0, _b, height_cm=180, age=45, sex=1, people_type=0,
           bmi=25.3, body_fat_percent=16.8, bone_mass_kg=4.6, body_water_percent=61.1,
           muscle_percent=77.7),
    Vector("short_female", 55.0, _b, height_cm=158, age=25, sex=0, people_type=0,
           bmi=22.0, body_fat_percent=9.3, bone_mass_kg=3.3, body_water_percent=66.5,
           muscle_percent=84.6),
    Vector("mid_female", 68.0, _hi, height_cm=170, age=55, sex=0, people_type=1,
           bmi=23.5, body_fat_percent=17.9, bone_mass_kg=3.7, body_water_percent=60.1,
           muscle_percent=76.6),
    Vector("tall_lean", 72.0, _hi, height_cm=185, age=35, sex=1, people_type=1,
           bmi=21.0, body_fat_percent=10.4, bone_mass_kg=4.3, body_water_percent=65.7,
           muscle_percent=83.6),
]

CAPTURES = [DISPLAY, EXACT]   # have raw A3 frames (decode tests)
ALL = CAPTURES + PROFILES     # all have expected metrics (calculation tests)
