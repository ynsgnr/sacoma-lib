"""Pure-Python port of ICBodyFatAlgorithmWLA25::calc (SACOMA WLA25).

The binary computes in 32-bit float at many steps; `f32()` reproduces that so
results match the device exactly (including its half-up-at-1-decimal rounding,
the `ceil` helper below).
"""
import math
import struct

__all__ = ["calc", "Metrics"]


def f32(x):
    """Coerce to IEEE-754 binary32, matching the binary's float storage."""
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def ceil(x):
    """ICAlgCommon rounding: round to 1 decimal, half-up, in float32.

    Mirrors the ~30 inlined fmodf blocks in calc() and ICAlgCommon::ceil.
    """
    x = float(x)
    ip = math.trunc(x)                       # (int)x  -- truncates toward zero
    fr = f32(math.fmod(f32(x), 1.0))         # fmodf((float)x, 1.0)
    fr = f32(fr * 10.0)
    fr2 = f32(math.fmod(fr, 1.0))
    up = f32(fr + 1.0)
    if fr2 <= 0.5:
        up = fr
    up = f32(f32(math.trunc(up)) / 10.0)
    if up == 0.0 and (x - float(ip)) > 0.99:  # carry on x.99xxx
        up = 1.0
    return float(f32(up + f32(ip)))


# ---- per-sex / per-people constants (extracted from .rodata) ----
FFM_FACTOR = (0.77, 0.85)          # DAT_00199e98, index = (sex == 1)
BFM_FACTOR = (0.23, 0.15)          # DAT_00199e88
SCORE_CORR = (-0.958, 0.983)       # DAT_00199ea8, index = (residual < 0)


def get_standard_bmi(height, age, sex, people):
    """ICAlgCommon::getStandardBMI -> reference BMI (float).

    For adults (age >= 18) this collapses to a per-sex constant (22 male /
    21 female), independent of height/people_type.

    UNDER-18 IS NOT IMPLEMENTED (intentionally). In the device library, for
    age < 18 getStandardBMI is instead a height-indexed decision tree: it keys
    on ``(int)height - 1`` and returns a hard-coded percentile reference BMI for
    each ~1 cm bracket (roughly the 85th-percentile growth curve, ~120 branches
    spanning ~85-171 cm; outside that range it falls back to the adult
    constant). To add it, transcribe that tree from the decompiled
    getStandardBMI, or sweep the binary over integer heights and bake a lookup
    table. Note the same applies to getStandardSMM (its own under-18 height
    table), though SMM only feeds the reference block we don't compute here.

    Impact of the gap: only minors are affected, and only the metrics that
    depend on the reference values -- segment percentages and body score (via
    getStandardFFM/BFM and getScore). The impedance-derived absolute metrics
    (body fat %, masses, water %, ...) do not use this and would be correct.
    """
    if age >= 18:
        return 22.0 if sex == 1 else 21.0
    raise NotImplementedError("under-18 standard-BMI height tree not ported (see docstring)")


def _std_weight(height, age, sex, people):
    bmi = f32(get_standard_bmi(height, age, sex, people))
    return f32(f32(f32(height) / 100.0) * f32(f32(height) / 100.0) * bmi)


def get_standard_ffm(height, age, sex, people):
    return f32(FFM_FACTOR[sex == 1] * _std_weight(height, age, sex, people))


def get_standard_bfm(height, age, sex, people):
    return f32(BFM_FACTOR[sex == 1] * _std_weight(height, age, sex, people))


def get_score(height, weight, age, sex, bodyfat_pct, people):
    """ICAlgCommon::getScore -> integer body score."""
    bmi = f32(get_standard_bmi(height, age, sex, people))
    fat_kg = f32(f32(bodyfat_pct / 100.0) * weight)
    sw = f32(f32(f32(height) / 100.0) * f32(f32(height) / 100.0) * bmi)
    resid = f32(fat_kg - f32(BFM_FACTOR[sex == 1] * sw))
    return int((weight - fat_kg) - f32(FFM_FACTOR[sex == 1] * sw)
               + 80.0 + SCORE_CORR[resid < 0.0] * resid)


def _metabolic_age(age, bodyfat_pct, sex):
    """Lines 561-632: age + a fat%/sex-bucketed delta."""
    if age < 10:
        return age
    bf = bodyfat_pct
    if sex == 1:                       # male (no 0 bucket; jumps -1 -> +1 at 24%)
        if bf < 14:   d = -3
        elif bf < 19: d = -2
        elif bf < 24: d = -1
        elif bf < 27: d = 1
        elif bf < 30: d = 2
        elif bf < 33: d = 3
        elif bf < 36: d = 4
        else:         d = 5
    else:                              # female
        if bf < 24:   d = -3
        elif bf < 28: d = -2
        elif bf < 32: d = -1
        elif bf < 35: d = 1
        elif bf < 38: d = 2
        elif bf < 42: d = 3
        elif bf < 45: d = 4
        elif bf < 46: d = 0
        else:         d = 5
    return age + d


class Metrics:
    """Measured WLA25 outputs."""
    __slots__ = ("bmi", "body_fat_percent", "muscle_percent",
                 "subcutaneous_fat_percent", "visceral_fat", "bone_mass_kg",
                 "body_water_percent", "protein_percent",
                 "skeletal_muscle_percent", "bmr_kcal", "metabolic_age",
                 "body_score", "raw")

    def __repr__(self):
        return "Metrics(" + ", ".join(
            f"{k}={getattr(self, k)}" for k in self.__slots__ if k != "raw") + ")"


# impedance-channel gate thresholds (this+0x48 .. +0x90)
_IMP_MIN = (1.0, 100.0, 100.0, 100.0, 100.0, 1.0, 100.0, 100.0, 100.0, 100.0)

# result-struct double-slot indices per segment: (fat_kg, fat_pct, muscle_kg, muscle_pct)
SEGMENT_SLOTS = {
    "left_arm": (0x13, 0x12, 0x15, 0x14),
    "right_arm": (0x17, 0x16, 0x19, 0x18),
    "left_leg": (0x0b, 0x0a, 0x0d, 0x0c),
    "right_leg": (0x0f, 0x0e, 0x11, 0x10),
    "trunk": (0x1b, 0x1a, 0x1d, 0x1c),
}


def calc(weight, height, sex, age, people, imps):
    """Port of WLA25::calc. `imps` = 10 impedances (ohms).

    Returns Metrics (with .raw = the full result-struct double array), or None
    if the input fails one of the binary's validation gates.
    """
    iVar6 = int(height); iVar1 = int(sex); iVar2 = int(age); iVar8 = int(people)
    dVar33 = float(weight)

    # ---- BMI (always computed) ----
    dVar32 = ceil(dVar33 * 10000.0 / (iVar6 * iVar6))

    p = [0.0] * 0x42
    ints = {}
    p[0] = dVar32

    # ---- reference values that survive into the measured math ----
    dVar27 = ceil(get_standard_bfm(iVar6, iVar2, iVar1, iVar8))   # std BFM (rounded)
    dVar40 = ceil(get_standard_ffm(iVar6, iVar2, iVar1, iVar8))   # std FFM (rounded)
    dVar29 = float(iVar6)

    # ---- validation gates (lines 479-513) ----
    if not (100 <= iVar6 <= 220):
        return None
    if dVar33 < 20.0 or dVar33 > 200.0:
        return None
    for z, lo in zip(imps, _IMP_MIN):
        if z < lo:
            return None
    dVar26 = imps[0]; dVar34 = imps[1]; dVar41 = imps[2]; dVar31 = imps[3]
    dVar36 = imps[4]; dVar28 = imps[5]; dVar38 = imps[6]; dVar45 = imps[7]
    dVar30 = imps[8]; dVar43 = imps[9]
    dVar44 = dVar26 * 0.826
    dVar37 = dVar28 * 0.826 if dVar28 <= dVar26 else dVar44 - 3.0
    if dVar44 < 0.0 or dVar37 < 0.0:
        return None

    # ---- core body-fat regression (515-536) ----
    dVar39 = (dVar30 * 0.07 + dVar43 * 0.153 + dVar37 * 0.439 + dVar38 * 0.019
              + dVar45 * 0.07 + dVar29 * 0.164 + dVar33 * -0.138 + dVar32 * 2.657
              + dVar41 * -0.053 + dVar34 * -0.000491 + dVar44 * -0.03
              + dVar36 * -0.127 + dVar31 * -0.052 + -88.052)
    dVar26 = (dVar39 / dVar33) * 100.0
    if dVar26 < 3.0:
        dVar39 = dVar33 * 0.03; dVar26 = 3.0
    elif dVar26 > 60.0:
        dVar39 = dVar33 * 0.6; dVar26 = 60.0
    dVar28 = ceil(dVar39)              # fat mass kg (rounded)
    fVar11 = ceil(dVar26)             # body fat % (rounded)

    iVar5 = _metabolic_age(iVar2, fVar11, iVar1)
    iVar6_score = get_score(iVar6, dVar33, iVar2, iVar1, fVar11, iVar8)
    if iVar6_score < 21:
        iVar6_score = 20

    # ---- segmental masses (638-714) ----
    local_110 = dVar38 * 0.007476 + (dVar28 * 0.081201 - dVar34 * 0.005752) + -0.662152
    local_108 = dVar45 * 0.007476 + (dVar28 * 0.081201 - dVar41 * 0.005752) + -0.662152
    local_c0 = dVar43 * 0.008645 + (dVar28 * 0.135438 - dVar36 * 0.00801) + 0.492479
    local_c8 = dVar30 * 0.008645 + (dVar28 * 0.135438 - dVar31 * 0.00801) + 0.492479

    if 0.3 < abs(local_108 - local_110):
        if local_108 <= local_110:
            t = (dVar41 + dVar45) / 20213.0
            local_108 = (t if dVar41 <= dVar34 else -t) + local_110
        else:
            t = (dVar34 + dVar38) / 20213.0
            local_110 = (t if dVar34 <= dVar41 else -t) + local_108
    if 0.5 < abs(local_c0 - local_c8):
        if local_c0 <= local_c8:
            t = (dVar36 + dVar43) / 20213.0
            local_c0 = (t if dVar36 <= dVar31 else -t) + local_c8
        else:
            t = (dVar31 + dVar30) / 20213.0
            local_c8 = (t if dVar31 <= dVar36 else -t) + local_c0

    dVar26 = dVar33 - dVar28          # lean mass = weight - fat mass
    if local_108 < 0.1:
        local_108 = (dVar41 + dVar45) / 20213.0 + 0.1
    dVar39 = dVar44 * 0.068621 + dVar28 * 0.552545 + dVar37 * -0.131612 + 0.322704
    if local_110 < 0.1:
        local_110 = (dVar34 + dVar38) / 20113.0 + 0.1
    if dVar39 < 0.1:
        dVar39 = (dVar37 + dVar44) / 20203.0 + 0.1
    if local_c0 < 0.1:
        local_c0 = (dVar36 + dVar43) / 20213.0 + 0.1
    local_d0 = ((dVar41 * 0.002847 + dVar26 * 0.058707) - dVar45 * 0.005857) + 0.561911
    if local_c8 < 0.1:
        local_c8 = (dVar31 + dVar30) / 20113.0 + 0.1
    local_f0 = ((dVar34 * 0.002847 + dVar26 * 0.058707) - dVar38 * 0.005857) + 0.561911
    if local_d0 < 0.2:
        local_d0 = (dVar41 + dVar45) / 20213.0 + 0.2
    dVar41 = dVar44 * 0.005246 + dVar26 * 0.440922 + dVar37 * -0.010469 + -0.275461
    if local_f0 < 0.2:
        local_f0 = (dVar34 + dVar38) / 20113.0 + 0.2
    local_f8 = dVar43 * 0.008157 + (dVar26 * 0.176554 - dVar36 * 0.007381) + -0.688932
    if dVar41 < 0.7:
        dVar41 = (dVar37 + dVar44) / 20203.0 + 0.7
    local_100 = dVar30 * 0.008157 + (dVar26 * 0.176554 - dVar31 * 0.007381) + -0.688932
    if local_f8 < 0.2:
        local_f8 = (dVar36 + dVar43) / 20213.0 + 0.2
    if local_100 < 0.2:
        local_100 = (dVar31 + dVar30) / 20113.0 + 0.2

    # ---- whole-body metrics (715-913) ----
    dVar34 = float(fVar11)                       # body fat %
    dVar31 = dVar27 - dVar28                      # std BFM - fat mass
    iVar8v = int(dVar28 * 0.502 + dVar26 * -0.029 + -0.477)   # visceral fat
    if iVar8v > 0x13:
        iVar8v = 0x14
    dVar36 = dVar40 - dVar26                       # std FFM - lean
    if iVar8v < 2:
        iVar8v = 1
    dVar28 = dVar26 * 0.733                         # lean * hydration
    # note: param_1[0x3e] (a segment-ratio slot) is written 0.0 here in the
    # original but never read as a headline metric, so it is not ported.
    dVar38 = (dVar34 * -0.0002 + 0.72) * dVar34     # subcutaneous fat %

    dVar45 = ((dVar28 + dVar26 * 0.2) / dVar33) * 100.0   # muscle %
    p[1] = ceil(dVar34)                               # body fat %
    p[3] = ceil(dVar38)                               # subcutaneous fat %
    p[2] = ceil(dVar45)                               # muscle %
    dVar38 = dVar26 * 0.067                            # bone mass kg
    dVar36 = ceil(dVar36)
    dVar45 = (dVar28 / dVar33) * 100.0                # body water %
    p[4] = float(iVar8v)                              # visceral fat
    dVar31 = ceil(dVar31)
    if dVar36 <= 0.0:
        dVar36 = 0.0
    dVar44 = dVar33 * 0.02 + dVar40 * 0.102 + dVar29 * -0.045 + 3.752
    dVar42 = dVar33 * 0.059 + dVar40 * 0.168 + dVar29 * -0.056 + 4.775
    dVar43 = dVar27 * 0.101 + dVar29 * -0.004 + 0.331
    dVar37 = dVar27 * 0.215 + dVar29 * -0.005 + 0.391
    dVar30 = ((dVar26 * 0.2) / dVar33) * 100.0        # protein %
    p[5] = ceil(dVar38)                               # bone mass kg
    dVar38 = dVar36 + dVar31
    dVar28 = ((dVar28 * 0.834 + -2.627) / dVar33) * 100.0   # skeletal muscle %
    p[6] = ceil(dVar45)                               # body water %
    p[7] = ceil(dVar30)                               # protein %
    p[8] = ceil(dVar28)                               # skeletal muscle %

    # segmental fat/muscle (masses + percents)
    p[0x13] = local_110; p[0x17] = local_108; p[0x1b] = dVar39
    p[0x0b] = local_c8; p[0x0f] = local_c0
    p[0x15] = local_f0; p[0x19] = local_d0
    p[0x11] = local_f8; p[0x0d] = local_100; p[0x1d] = dVar41
    p[0x12] = (local_110 / dVar43) * 100.0
    p[0x0a] = (local_c8 / dVar37) * 100.0
    p[0x16] = (local_108 / dVar43) * 100.0
    p[0x1a] = (dVar39 / (dVar29 * 0.006 + dVar27 * 0.389 + -0.683)) * 100.0
    p[0x0e] = (local_c0 / dVar37) * 100.0
    p[0x14] = (local_f0 / dVar44) * 100.0
    p[0x18] = (local_d0 / dVar44) * 100.0
    p[0x1c] = (dVar41 / (dVar33 * 0.166 + dVar40 * 0.485 + dVar29 * -0.16 + 13.595)) * 100.0
    p[0x0c] = (local_100 / dVar42) * 100.0
    p[0x10] = (local_f8 / dVar42) * 100.0
    p[0x1f] = dVar33 + dVar38; p[0x20] = dVar31; p[0x21] = dVar36; p[0x22] = dVar38
    p[0x1e] = float(iVar6_score)                      # body score

    ints[0x48] = int(dVar26 * 21.6 + 370.0)           # BMR
    ints[0x4c] = iVar5                                # metabolic age

    m = Metrics()
    m.bmi = p[0]
    m.body_fat_percent = p[1]
    m.muscle_percent = p[2]
    m.subcutaneous_fat_percent = p[3]
    m.visceral_fat = p[4]
    m.bone_mass_kg = p[5]
    m.body_water_percent = p[6]
    m.protein_percent = p[7]
    m.skeletal_muscle_percent = p[8]
    m.bmr_kcal = ints[0x48]
    m.metabolic_age = ints[0x4c]
    m.body_score = p[0x1e]
    m.raw = p
    return m
