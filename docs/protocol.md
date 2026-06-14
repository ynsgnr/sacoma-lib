# The BLE wire protocol

The SACOMA Ultra speaks the icomon **"General scale"** protocol over GATT service **FFB0**:

| Characteristic | UUID (`0000xxxx-0000-1000-8000-00805f9b34fb`) | Direction | Purpose |
|---|---|---|---|
| FFB1 | `ffb1` | app → scale (write) | commands (`BA/BB/B0/BD`) |
| FFB2 | `ffb2` | scale → app (notify) | `A2` live weight stream |
| FFB3 | `ffb3` | scale → app (notify) | `A3` result, `A1`/`A0` status |

These commands are **plaintext** — no encryption. (`libICBleProtocol.so` contains XXTEA + a
Diffie-Hellman key exchange, but those are used by *other* protocol versions, not this one.)

## Frame format

Every BLE notification/write is a fixed **20-byte frame**:

```
[0]      sequence counter (0..255, wraps)
[1]      total payload length
[2]      fragment index (0, 1, ...)
[3..18]  payload chunk, zero-padded to 16 bytes
[19]     checksum
```

Messages longer than 16 payload bytes span multiple frames (same `sequence`, increasing
`fragment`); concatenate payload chunks until `length` bytes are collected.

### Checksum

```
checksum = sum(frame[3:19]) & 0x1F        # 5-bit additive over the 16 payload bytes
```

Validated against 153/153 captured frames in both directions. See
`sacoma.protocol.frame_checksum` / `frame_is_valid` and `sacoma.encoder.frame_checksum`.

## Scale → app messages

### `A2` — live weight stream (FFB2)

```
[0]   type 0xA2
[1]   state    0x01 live / 0x03 stabilized
[2]   marker   0x19
[3]   0x00
[4-5] weight   uint16 big-endian  -> /1000 = kg
[6]   0x00
```

### `A3` — BIA result (FFB3)

```
[0]    type 0xA3
[1]    marker 0x19
[2]    0x00
[3-4]  weight   uint16 big-endian -> /1000 = kg
[5]    0x00
[6..]  imp1..imp10   uint16 big-endian each -> /10 = ohms   (10 segmental impedances)
```

`A1` / `A0` are status/counter frames and are ignored.

## App → scale commands (FFB1)

| Cmd | Builder | Payload |
|---|---|---|
| `0xBA` | `encode_sync` | timestamp (BE u32) + stabilized weight — the periodic sync/heartbeat |
| `0xBB` | `encode_user_list` | count + two 8-byte user records (record 1 carries weight) |
| `0xB0` | `encode_reply` | `[reply_package_index][state]` — transport ack |
| `0xBD` | `encode_other` | `[sub_cmd]` (e.g. `0x09`) |

Example `BA` payload (16 bytes), weight 64.90 kg:

```
ba 6a2e4eaa 00 78 0605cf67a5 995a 9e 0f
│  └ time   │  │  └ token    │    │  └ tail
│           │  └ const       │    └ separator
cmd         const            weight = 0x8000 | round(kg*100) = 0x8000|6490
```

A few `BA`/`BB` bytes (`0605cf67a5`, `0605cfb2a51a5e9e`, `0078`, `9e`, `0f`) are **stable
constants** across every capture for the test device; their derivation from the user profile
is not yet reversed, so they are kept as observed constants. Frames are therefore byte-exact
for that device but may not generalize to a fresh pairing.

## What the app does *not* send

The phone never transmits computed body-composition to the scale. Comparing the `BA`/`BB`
writes immediately before and after the app computes a result, the payloads are
**byte-identical except the timestamp and weight**. The scale computes its own 6 displayed
values (fat %, BMI, muscle mass, water %, body age, bone mass) on-device from the impedance it
measured plus the profile/weight synced over `BA`/`BB`. This is why the scale shows only weight
with no phone connected: it has no profile to compute from.
