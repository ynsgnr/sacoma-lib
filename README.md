# sacoma

A small, focused Python library for the **SACOMA Ultra** 8-electrode body-composition scale
(ICOMON / Chipsea hardware, Fitdays app). Its single responsibility is **BLE bytes ⇄ values**:

1. **bytes → values** — decode the scale's notification frames into weight + impedances, and
   compute the full body composition (BMI, body-fat %, segmental fat/muscle, water, BMR, …).
2. **values → bytes** — build the command frames to send back to the scale.

The library performs **no I/O** — it never touches Bluetooth, files, or the network. Bring your
own BLE stack; feed it bytes and it returns values.

## Status

- ✅ Frame reassembly + result (A3) decoding — weight and the 10 segmental impedances.
- 🚧 Body-composition algorithm (`WLA25`) — in progress.
- 🚧 Command encoding (values → bytes).

## Install

```bash
pip install -e .            # library (pulls ezpacket from PyPI)
pip install -e ".[dev]"     # + pytest/ruff for development
pip install -e ".[ble]"     # + bleak, only for the example runner
```

## Usage

```python
from sacoma import FrameAssembler, decode_frame

assembler = FrameAssembler()
for frame in notifications:               # raw 20-byte FFB2/FFB3 frames from your BLE stack
    measurement = decode_frame(frame, assembler)
    if measurement is not None:           # a complete result message arrived
        print(measurement.weight_kg, measurement.impedances_ohm)
```

## Documentation

- **Packet structure** is declared directly as `ez-packet` `Section` definitions in
  `sacoma/protocol.py` — those definitions are the spec.
- **The algorithm** (how impedances + profile become the reported values, with the formulas
  and clamps) is documented in `docs/algorithm.md`.

## Scope

Intentionally tiny: **BLE bytes ⇄ values**, nothing else. Device discovery, connection
management, retries, and Home Assistant wiring live outside the library.
