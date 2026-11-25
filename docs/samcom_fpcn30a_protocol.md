# Samcom FPCN30A serial programming protocol

This document describes the cable protocol used to read and write a Samcom
FPCN30A (model ID `ZW_U5W`). It was reverse engineered from the vendor
programming tool, *SAMCOM Radio FreqTools V1.2* (`PocTools.exe`, build
2023-12-12). It was then checked byte by byte against two real radios with
serial logging.

The CHIRP driver that implements it is
[`chirp/drivers/samcom_fpcn30a.py`](../chirp/drivers/samcom_fpcn30a.py).

Where the vendor tool and the radio disagree, this document follows the radio
and notes the difference.

---

## 1. Physical layer

| Setting | Value |
|---|---|
| Speed | 9600 baud |
| Format | 8 data bits, no parity, 1 stop bit |
| Flow control | none |
| DTR / RTS | both off when the port is opened (the vendor tool uses `DtrEnable = false`) |

The radio never sends anything unprompted. Every exchange starts with the
host.

---

## 2. Frames

There are two kinds of frame. Each kind is identified by its first byte.

### 2.1 Control frames (3 bytes)

| Bytes | Name | Meaning |
|---|---|---|
| `36 06 10` | ACK | Accepted, or "send the next one" |
| `36 05 10` | RESEND | Repeat the last frame. Defined by the vendor tool but never seen from the radio. |
| `36 07 10` | COMPLETE | End of session |

### 2.2 Data frames

```
offset  0     1     2     3     4     5      6     7 … 7+L-1   7+L
       ┌─────┬─────┬─────┬─────┬─────┬──────┬─────┬─────────┬─────┐
       │ 35  │ cmd │type │  value    │ csum │  L  │ payload │ 10  │
       └─────┴─────┴─────┴─────┴─────┴──────┴─────┴─────────┴─────┘
```

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | start | always `0x35` |
| 1 | 1 | command | `0x01` = read, `0x02` = write. The vendor tool accepts 1–3. |
| 2 | 1 | data type | `0x02` = settings, `0x03` = channel. The vendor tool accepts 2–7. |
| 3–4 | 2 | value | Big-endian, ≤ 1024. Its meaning depends on the frame (see below). |
| 5 | 1 | checksum | Low byte of the sum of **every other byte of the frame**, from the start byte through the terminator, skipping offset 5 itself |
| 6 | 1 | L | payload length |
| 7 … | L | payload | |
| 7+L | 1 | terminator | always `0x10` |

**Value field (offsets 3–4):**

| Frame | Value |
|---|---|
| Read request | `0x0100` (the vendor tool sends `01 00`) |
| Settings reply | `0x0000` |
| Channel reply | the channel number |
| Settings write | `0x0001` |
| Channel write | sequence number, starting at 2 (low byte only; the high byte is 0) |

**Checksum example.** For the read request
`35 01 02 01 00 __ 00 10`, the bytes other than offset 5 add up to
`0x35+0x01+0x02+0x01+0x00+0x00+0x10 = 0x49`. The frame is therefore
`35 01 02 01 00 49 00 10`.

A received frame is valid when:
- it starts with `0x35`;
- the byte at `7+L` is `0x10`;
- the command is 1–3 and the type is 2–7;
- the value is ≤ 1024;
- the checksum matches.

This mirrors the vendor tool's `Receive_PacketCheck`.

---

## 3. Payloads

### 3.1 Settings ("local info"): type `0x02`, 41 bytes

| Offset | Size | Field | Values |
|---|---|---|---|
| 0 | 6 | model | ASCII, `ZW_U5W` on both radios tested |
| 6 | 6 | unknown | ASCII `000000` on both radios |
| 12 | 10 | serial | `SC` followed by 8 bytes, all `00` on both radios (see §6.3) |
| 22 | 1 | frequency range | `0` = 134–176 MHz, `1` = 406.1–470 MHz |
| 23 | 1 | time-out timer | seconds, 30–180 in steps of 10 |
| 24 | 1 | VOX | `0` = off, `1`–`5` = level |
| 25 | 6 | user ID | ASCII digits, or `00` |
| 31 | 1 | group channel | channel number, 1-based. The radio displays channel 20 as **CH0**. |
| 32 | 1 | squelch | `1`–`9` |
| 33 | 1 | voice language | `0` = English, `1` = Chinese |
| 34 | 1 | scrambler | `0` / `1` |
| 35 | 1 | companding | `0` / `1` |
| 36 | 1 | power mode | `0`–`2` (meaning not established; the vendor tool's default is `1`) |
| 37 | 4 | reserved | the vendor tool writes `00` |

The radios report `0xFF` for every field they don't use. On the tested radios
those were frequency range, time-out timer, user ID, language, scrambler,
companding, power mode and the reserved bytes.

Settings block read from an unmodified radio:

```
5a 57 5f 55 35 57  30 30 30 30 30 30  53 43 00 00 00 00 00 00 00 00
ff ff 00 ff ff ff ff ff ff 14 03 ff ff ff ff ff ff ff ff
        ^^ VOX off           ^^ group 20 (shown as CH0)
                                ^^ squelch 3
```

### 3.2 Channel: type `0x03`, 27 bytes

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | channel number | 1-based |
| 1 | 1 | — | `00` |
| 2 | 4 | **RX** frequency | packed BCD, 10 Hz units |
| 6 | 4 | **TX** frequency | packed BCD, 10 Hz units |
| 10 | 2 | — | `00 00` |
| 12 | 1 | bandwidth | `0` = 25 kHz (wide), `1` = 12.5 kHz (narrow) |
| 13 | 1 | RX tone | tone index (§3.3) |
| 14 | 1 | TX tone | tone index (§3.3) |
| 15 | 1 | bandwidth (copy) | same value as offset 12 |
| 16 | 1 | power | the radios reported `01` |
| 17 | 1 | companding | stored per channel; the radios reported `00` |
| 18 | 1 | scrambler | stored per channel; the radios reported `00` |
| 19 | 8 | — | `00` |

**Frequency encoding.** `46 25 50 00` is the BCD digits `46255000`. In
units of 10 Hz that is 462 550 000 Hz, or 462.550 00 MHz.

**RX/TX order.** The radio reports RX first and stores what it is sent in
the same positions. The vendor tool writes **TX first**, which swaps RX and
TX on split (repeater) channels. Write RX first.

**Per-channel extras.** Offsets 16–18 are stored separately for each channel.
The vendor tool fills them from its global settings instead. Writing back
the values the radio reported keeps them unchanged.

Channel reply from a real radio (channel 9, RX 462.625, TX 467.625, tone index
13 on both RX and TX, narrow):

```
35 01 03 00 09 …  1b  09 00  46 26 25 00  46 76 25 00  00 00  01  0d 0d  01  01 00 00  00×8  10
                 L=27 ch     RX           TX                 bw  tones  bw  extras
```

### 3.3 Tone index

| Index | Meaning |
|---|---|
| `0` | off |
| `1`–`50` | the standard 50 CTCSS tones, in order (`1` = 67.0 Hz, `13` = 100.0 Hz, `50` = 254.1 Hz) |
| `51`–`154` | the standard 104 DCS codes, in order, normal polarity only (`51` = D023N, `154` = D754N) |

The vendor tool rejects values above 155.

---

## 4. Reading the radio

```
host                                   radio
 │  35 01 02 01 00 49 00 10  (read)      │
 │──────────────────────────────────────▶│
 │◀──────────────────────────────────────│  35 01 02 00 00 cs 29 <settings×41> 10
 │  36 06 10  (ACK)                      │
 │──────────────────────────────────────▶│
 │◀──────────────────────────────────────│  35 01 03 00 01 cs 1b <channel 1> 10
 │  36 06 10                             │
 │──────────────────────────────────────▶│
 │◀──────────────────────────────────────│  35 01 03 00 02 cs 1b <channel 2> 10
 │                 …                     │
 │  36 06 10                             │
 │──────────────────────────────────────▶│
 │◀──────────────────────────────────────│  36 07 10  (COMPLETE)
```

- The radio sends only the channels it has in use, one per ACK.
- **Timeouts:** the vendor tool waits 2000 ms for each reply. On a timeout or
  RESEND it repeats the request, up to 3 times, and it gives up after 30
  ACKs.
- Each read takes about 2 seconds for 20 channels.

---

## 5. Writing the radio

```
host                                             radio
 │  35 02 02 00 01 cs 29 <settings×41> 10           │
 │─────────────────────────────────────────────────▶│
 │◀─────────────────────────────────────────────────│  36 06 10
 │  35 02 03 00 02 cs 1b <channel> 10   (seq 2)     │
 │─────────────────────────────────────────────────▶│
 │◀─────────────────────────────────────────────────│  36 06 10
 │  35 02 03 00 03 cs 1b <channel> 10   (seq 3)     │
 │                 …                                │
 │◀─────────────────────────────────────────────────│  36 06 10
 │  36 07 10  (COMPLETE)                            │
 │─────────────────────────────────────────────────▶│
 │◀─────────────────────────────────────────────────│  36 06 10
```

- **Order:** one settings frame, then one frame per channel to keep, then
  COMPLETE.
- **ACK:** the radio acknowledges each frame. The vendor tool waits 1000 ms
  for each ACK and retries up to 3 times.
- **Sequence numbers:** the value field of channel frames starts at 2 and
  goes up by 1 for each frame. Channels are identified by payload byte 0, not
  by the sequence number.
- **Settings frame:** this is how the vendor tool builds it
  (`CreateLocalPara`):
  - ASCII `0` over the model, the unknown field and the serial (bytes
    0–21);
  - the current values in bytes 22–36;
  - `00` in the reserved bytes.

  A frame sent this way, accepted by both radios:

  ```
  35 02 02 00 01 d5 29
  30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30 30
  01 3c 00 00 00 00 00 00 00 01 03 00 00 00 01 00 00 00 00
  10
  ```

  The serial is part of the settings payload, but no frame changes it.

---

## 6. Radio behaviour observed in testing

These points come from logged sessions with two radios. The vendor tool does
not explain them, but any program writing to this radio has to respect them.

### 6.1 The settings frame is required but its values are ignored

- **Ignored values:** the radio ACKs the settings frame but does not apply any
  of its values: group, VOX, squelch and serial were all tested, from the
  vendor tool and from CHIRP. To change settings, use the radio's own menu.
- **Still required:** without a settings frame at the start of the session,
  the radio **ignores the TX frequency** in channel frames.
- **No `0xFF` bytes:** keep `0xFF` out of the settings frame. The only writes
  that left a radio with a persistently wrong group value carried `0xFF`
  there. The vendor tool never sends it.

### 6.2 Tone changes are ignored shortly after a read

- **Effect:** for a while after the radio has been read, it still ACKs channel
  frames but **ignores tone changes** in them. Frequency changes are applied
  either way.
- **Measured timings:**
  - Write starting about 1 s after a read: tone changes ignored, in every
    attempt.
  - Write starting 20 s, 60 s or 180 s after a read: tone changes applied.
- **Driver rule:** don't read the radio at the start of a write session, and
  wait at least 30 s after any read before writing. The CHIRP driver
  enforces this for its own reads.

### 6.3 Writes corrupt the radio's working copy of its settings until a power cycle

- **Every write session:** the 8 serial bytes after `SC` read back as `FF`.
- **A write that applies a channel change:** VOX and squelch also read back as
  `FF`, and the radio's display shows garbage for them.
- **Recovery:** turning the radio **off and on** restores all of these from
  storage. Nothing stored is damaged.

Always restart the radio after programming it.

### 6.4 Group channel display

The radio displays group channel 20 as **CH0**. Over the cable it is `0x14`
(20).

---

## 7. Vendor tool notes

| Item | Detail |
|---|---|
| Read request | `PttWRP.CreateReadLocalInfo_Cmd` |
| ACK | `PttWRP.CreateAck_Cmd` |
| Settings write | `Form_PocTool.CreateLocalPara` (49-byte frame) |
| Channel write | `Form_PocTool.CreateChannelParaData` (35-byte frame) |
| Frame check | `Form_PocTool.Receive_PacketCheck` |
| Read / write loops | `button_ReadThreadHandle`, `button_WriteThreadHandle` |
| Group menu | `CH1` … `CH16` or `CH22`, depending on the model's channel count |

- **Dealer/admin password:** the strings and config keys are present
  (`PTT_CFG_PSWD`, `PTT_CFG_PSWD_NEW`, `PTT_CFG_SERIAL_NUM`).
  - The handlers in this build are empty, and the "admin password mismatch"
    message is never shown.
  - No frame carries a password.
- **Write order bug:** the vendor tool writes TX before RX in channel frames
  (see §3.2).
