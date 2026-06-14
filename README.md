# sacoma

A small, focused Python library for the **SACOMA Ultra** 8-electrode body-composition scale
(ICOMON / Chipsea hardware, Fitdays app). Its single responsibility is **BLE bytes ⇄ values**:

1. **bytes → values** — decode the scale's notification frames into weight + impedances, and
   compute the full body composition (BMI, body-fat %, segmental fat/muscle, water, BMR, …).
2. **values → bytes** — build the command frames to send back to the scale.

The library performs **no I/O** — it never touches Bluetooth, files, or the network. Bring your
own BLE stack; feed it bytes and it returns values.

## Status

- ✅ Frame reassembly + decoding — A2 weight stream and A3 result (weight + 10 segmental impedances).
- ✅ Body-composition algorithm (`WLA25`) — bit-exact pure-Python port (`sacoma/wla25.py`).
- ✅ Command encoding (values → bytes) — `BA/BB/B0/BD` FFB1 frames (`sacoma/encoder.py`).

## Install

The distribution is **`sacoma-lib`**; the import package is **`sacoma`**.

```bash
pip install sacoma-lib        # from PyPI

pip install -e .              # from a checkout (pulls ezpacket from PyPI)
pip install -e ".[dev]"       # + pytest/ruff/build/twine for development
pip install -e ".[ble]"       # + bleak, only for the example runner
```

## Usage

**Decode** (scale → app):

```python
from sacoma import FrameAssembler, decode_frame

assembler = FrameAssembler()
for frame in notifications:               # raw 20-byte FFB2/FFB3 frames from your BLE stack
    measurement = decode_frame(frame, assembler)
    if measurement is not None:           # a complete result message arrived
        print(measurement.weight_kg, measurement.impedances_ohm)
```

**Compute** body composition from a result:

```python
from sacoma import calculations, UserProfile, Sex, PeopleType

profile = UserProfile(height_cm=165, age=30, sex=Sex.MALE, people_type=PeopleType.NORMAL)
body = calculations.compute(measurement, profile)   # BodyComposition: bmi, body_fat, segments, ...
```

**Encode** (app → scale): build the FFB1 command frames the scale expects.

```python
from sacoma import encoder

frames = encoder.encode_sync(sequence=0, weight_kg=64.9)   # list[bytes], ready to write to FFB1
for f in frames:
    ble_write("0000ffb1-...", f)
```

### Talking to a real scale (Windows)

`scripts/ble_test.py` is a tiny [bleak](https://github.com/hbldh/bleak) runner that uses only this
library for encode/decode:

```powershell
py -3 scripts\ble_test.py --scan                  # find the scale's BLE address
py -3 scripts\ble_test.py --address AA:BB:CC:..    # stream decoded weight + result
py -3 scripts\ble_test.py --address AA:BB:CC:.. --drive   # also push the handshake (experimental)
```

## Documentation

- **The wire protocol** (frame format, 5-bit checksum, the `BA/BB/B0/BD` commands, A2/A3
  layouts) is documented in `docs/protocol.md`. The encode/decode source in
  `sacoma/encoder.py` and `sacoma/protocol.py` is the authoritative spec.
- **The algorithm** (how impedances + profile become the reported values, with the formulas
  and clamps) is documented in `docs/algorithm.md`.

> **Note — the scale displays its own numbers.** Verified byte-for-byte across many captures:
> the phone never transmits computed body-composition to the scale. The scale computes the 6
> values on its own screen (fat %, BMI, muscle, water %, body age, bone) from the impedance it
> measures plus the profile/weight the phone syncs over `BA`/`BB`. So this library *drives* the
> scale (by syncing profile/weight); it cannot override what the scale chooses to display.

## Scope

Intentionally tiny: **BLE bytes ⇄ values**, nothing else. Device discovery, connection
management, retries, and Home Assistant wiring live outside the library.
