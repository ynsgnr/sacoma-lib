# The body-composition algorithm

The scale measures **weight** and **10 segmental impedances** (in ohms); everything else is
computed from them with **bioelectrical impedance analysis (BIA)**.

## Why impedance predicts body composition

A tiny alternating current is passed through the body. Lean tissue (muscle, water) is
conductive → **low impedance**; fat is a poor conductor → **high impedance**. The key
predictor is the **impedance index**:

```
impedance_index = height_cm**2 / Z          # Z = impedance (ohms)
```

which is proportional to fat-free mass and total body water. An 8-electrode scale measures
each limb and the trunk separately, so the same idea is applied **per segment**.

## Formula shape

Each metric is a clamped linear regression over the impedance index and the user profile:

```
metric = clamp( c0 + c1*(height**2/Z) + c2*weight + c3*age + c4*sex (+ c5*Z + ...), lo, hi )
```

with sex- and body-type-specific coefficient sets. Examples of this exact form in the
published literature:

- Total body water: `TBW = 5.68 + 0.267*(height**2/R) + 4.42*sex + 0.225*weight - 0.052*age`
- Skeletal muscle (Janssen): `SMM = 0.401*(height**2/R) + 3.825*sex - 0.071*age + 5.102`
- Fat-free mass → body fat: `body_fat = weight - FFM`, with `FFM = TBW / 0.732` (hydration).

The scale uses its own (manufacturer-tuned) coefficient sets of this shape.

## Reported values

Whole body: BMI, body-fat %, subcutaneous fat %, visceral fat, muscle %, skeletal-muscle %,
body-water %, protein %, bone mass, BMR, metabolic age, body score, WHR. Per segment
(left/right arm, left/right leg, trunk): fat % / fat kg and muscle % / muscle kg.

All reported values are rounded to one decimal (half-up at the second decimal).

## BMI

```
BMI = weight_kg / (height_cm/100)**2 = weight_kg * 10000 / height_cm**2
```

## Metrics derived from body-fat %

Most whole-body metrics are transforms of body-fat % via the BIA composition model, so they
do not need their own impedance regression:

```
fat_free_fraction = (100 - body_fat_percent)
body_water_percent = fat_free_fraction * 0.732          # 0.732 = hydration of lean mass
muscle_percent     = fat_free_fraction - bone_percent   # bone_percent = bone_kg/weight*100
fat_mass_kg        = weight_kg * body_fat_percent/100
```

Body-fat % itself is the core impedance regression (segmental impedance terms); bone is its
own small regression. The rest follow from the relations above.

## References

- ESPEN BIA guidelines (Kyle et al., 2004).
- Janssen et al., 2000 — skeletal muscle mass by BIA.
- Bosy-Westphal et al., 2017 — whole-body and segmental skeletal muscle by phase-sensitive
  8-electrode BIA.

## Status

BMI is implemented and validated. The impedance-derived metrics are being ported and
validated metric-by-metric against reference measurements.
