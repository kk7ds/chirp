# Copyright 2026 Gary Krasovic <gkrasovic@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
"""ABBREE AR-7600 mobile radio driver.

Reverse-engineered from the vendor CPS (RwRadio.exe V1.1) by decompiling it and
decrypting its own model-config file. See PROTOCOL_NOTES.md (in the repo this
driver was developed in) for the full writeup with file:line citations.

Frequency, CTCSS/DCS tone, channel name, and every flag bit below have been
confirmed against real hardware via isolated single-variable diffs (change one
field via the vendor CPS, write, read back, repeat) -- see PROTOCOL_NOTES.md
for the full experiment log. The one exception is BCL value 3, and the
per-channel "SCR_CTDCS_SPE" auxiliary table, which are not implemented here.

Both download (sync_in) and upload (sync_out) are confirmed working
end-to-end against real hardware, including surviving a power cycle and
matching the vendor CPS's own display -- see PROTOCOL_NOTES.md's "Write
Support" section for the full writeup. sync_out() replicates the complete
region sequence a real "Write to Radio" performs (channel memory plus
several calibration/table regions, all round-tripped unmodified except the
edited channels), including one easy-to-miss commit flag byte that a naive
channel-only write would silently omit, causing writes to appear to succeed
(correct per-block device checksums) but vanish on the next power-up.
"""

import logging
import time

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp import util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wire-scramble tables. These are static, arbitrary substitution tables
# hardcoded in the vendor CPS -- NOT the output of a generator. The source
# routine modPcCom.InitCodeListRandom() (RwRadio.exe V1.1) is literally
# three `new byte[256] { ...literals... }` assignments and `return true;`,
# with no loop, seed, or key schedule; "Random" in its name just means "this
# looks random", not "computed at runtime".
#
# Verified properties (see the analysis in the ar7600-chirp-notes repo):
#   * all three are permutations of 0..255
#   * SECRET_CODE_DATA and its inverse permutation form an 8-bit S-box pair;
#     the CPS ships both, but we derive the inverse below instead of pasting
#     a second block of magic numbers
#   * SECRET_RANDOM is an independent permutation used as a position-
#     dependent additive mask
# The wire protocol (see _layer2_* below and PROTOCOL_NOTES.md) is a plain
# table-driven byte substitution plus additive whitening -- there is no
# deeper structure being glossed over here.
# ---------------------------------------------------------------------------

SECRET_CODE_DATA = [
    201, 33, 244, 0, 175, 145, 218, 31, 254, 38,
    247, 11, 161, 238, 195, 172, 187, 25, 43, 188,
    2, 28, 144, 57, 226, 208, 139, 196, 67, 245,
    118, 155, 86, 96, 98, 237, 189, 62, 164, 49,
    235, 147, 82, 242, 253, 79, 138, 248, 250, 255,
    246, 74, 22, 16, 41, 215, 122, 80, 225, 150,
    100, 71, 113, 107, 136, 83, 167, 159, 202, 40,
    210, 148, 185, 227, 177, 146, 63, 19, 124, 72,
    36, 46, 94, 102, 51, 209, 130, 112, 92, 123,
    99, 157, 73, 13, 132, 228, 6, 212, 87, 216,
    45, 64, 90, 23, 233, 121, 240, 169, 125, 197,
    55, 149, 192, 120, 252, 104, 85, 224, 231, 56,
    115, 126, 58, 171, 184, 30, 219, 135, 229, 134,
    52, 29, 15, 84, 78, 220, 108, 61, 47, 44,
    205, 178, 129, 27, 50, 165, 217, 204, 199, 59,
    101, 116, 183, 223, 213, 211, 8, 179, 81, 203,
    7, 97, 133, 156, 142, 221, 42, 4, 14, 251,
    174, 158, 32, 109, 75, 162, 193, 68, 106, 140,
    110, 243, 181, 190, 198, 93, 153, 131, 34, 60,
    141, 151, 170, 236, 152, 103, 143, 105, 168, 137,
    173, 95, 3, 5, 206, 222, 91, 24, 35, 37,
    26, 154, 166, 77, 182, 65, 114, 241, 20, 191,
    17, 54, 48, 88, 89, 207, 12, 111, 186, 239,
    180, 128, 18, 200, 119, 39, 9, 70, 214, 249,
    21, 69, 127, 163, 160, 176, 117, 53, 66, 76,
    232, 1, 194, 230, 10, 234,
]

# The CPS's second table (gbytSecretSeqList) is exactly the inverse
# permutation of SECRET_CODE_DATA -- the S-box's decode half. Derive it
# rather than pasting another 256 magic numbers; the assert below is also a
# sanity check that SECRET_CODE_DATA is a clean permutation.
SECRET_SEQ_LIST = [0] * 256
for _i, _v in enumerate(SECRET_CODE_DATA):
    SECRET_SEQ_LIST[_v] = _i
assert sorted(SECRET_SEQ_LIST) == list(range(256)), \
    "SECRET_CODE_DATA is not a permutation of 0..255"

SECRET_RANDOM = [
    74, 197, 46, 33, 235, 180, 136, 68, 242, 176,
    65, 123, 230, 191, 249, 246, 60, 6, 0, 25,
    106, 66, 177, 214, 141, 57, 97, 92, 121, 122,
    69, 152, 229, 24, 190, 204, 139, 232, 168, 216,
    87, 49, 3, 58, 20, 226, 47, 81, 170, 48,
    244, 174, 96, 79, 107, 112, 219, 59, 193, 224,
    201, 252, 73, 223, 240, 50, 76, 169, 7, 253,
    86, 160, 212, 245, 39, 215, 140, 185, 210, 89,
    255, 211, 238, 239, 195, 99, 218, 42, 162, 108,
    243, 254, 158, 119, 217, 13, 126, 213, 70, 64,
    93, 144, 45, 28, 115, 179, 171, 11, 132, 34,
    157, 198, 189, 30, 250, 222, 35, 178, 113, 206,
    175, 128, 109, 67, 147, 84, 150, 116, 146, 129,
    88, 26, 29, 135, 165, 145, 16, 104, 225, 61,
    110, 208, 54, 102, 125, 94, 103, 205, 183, 71,
    237, 127, 40, 18, 44, 251, 143, 14, 220, 120,
    130, 91, 105, 36, 164, 228, 137, 149, 247, 200,
    78, 31, 156, 19, 155, 10, 77, 63, 118, 227,
    142, 98, 43, 184, 100, 38, 209, 32, 75, 172,
    196, 231, 95, 236, 173, 117, 2, 138, 241, 23,
    90, 234, 56, 148, 233, 5, 55, 188, 154, 186,
    167, 37, 192, 52, 62, 203, 187, 80, 207, 133,
    114, 194, 17, 131, 166, 161, 134, 221, 15, 22,
    159, 248, 182, 153, 82, 163, 111, 9, 27, 8,
    181, 12, 21, 199, 41, 202, 124, 51, 53, 151,
    4, 101, 72, 1, 83, 85,
]

# ---------------------------------------------------------------------------
# Protocol constants (PROTOCOL_NOTES.md sections 2b/3a/3b/3c/4)
# ---------------------------------------------------------------------------

LEADCODE_TX = bytes([0x5A, 0x33, 0x57, 0x96, 0xAC, 0xBB])
LEADCODE_RX = bytes([0x5A, 0x33, 0x75, 0x69, 0xCA, 0xBB])
READFLASH_TX_MAGIC = bytes([0x5A, 0x46, 0x99, 0x8A, 0x6B, 0xA7])
READFLASH_RX_MAGIC = bytes([0x5A, 0x64, 0x99, 0xA8, 0xB6, 0x7A])
WRITEFLASH_TX_MAGIC = bytes([0x5A, 0x45, 0x88, 0x79, 0x52, 0x96])
WRITEFLASH_RX_MAGIC = bytes([0x5A, 0x54, 0x88, 0x97, 0x25, 0x69])
RESET_TX_MAGIC = bytes([0x5A, 0x13, 0x22, 0x43, 0x25, 0x57])
RESET_RX_MAGIC = bytes([0x5A, 0x31, 0x22, 0x34, 0x52, 0x75])
CHK_BASE = 23205  # 0x5AA5

CHANNEL_SIZE = 32
BLOCK_SIZE = 1024

# ---------------------------------------------------------------------------
# Full memory-region map, reverse-engineered from a live USB capture of a
# real "Write to Radio" (see PROTOCOL_NOTES.md "Live capture" section,
# 2026-09-05). Channel memory is NOT one contiguous 16384-byte block as
# earlier assumed -- it is split into two 251-channel groups with a gap,
# and a real write also touches several calibration/table regions (but,
# confirmed by inspecting every WRITEFLASH target in the capture, NEVER the
# IAP/APP firmware region below 0x40000). All of these are read on sync_in
# and written back byte-for-byte unmodified on sync_out, except the two
# CHINFO groups (which reflect the user's edits) and their backup mirrors
# (re-derived from the, possibly edited, primary groups).
# ---------------------------------------------------------------------------

CHANNELS_PER_GROUP = 251  # physical slots per group
REGULAR_PER_GROUP = 250   # the first 250 are normal numbered channels
CHINFO_GROUP_SIZE = CHANNELS_PER_GROUP * CHANNEL_SIZE  # 8032
PHYSICAL_CHANNELS = CHANNELS_PER_GROUP * 2  # 502 slots in the bitwise struct

# The 251st (last) physical slot of each group is that group's VFO memory,
# confirmed against the CPS UI (2026-09-05): its channel list runs 1-250,
# then a distinct "VFO-A"/"VFO-B" entry follows. Group A and Group B are
# exposed as separate CHIRP sub-devices (see get_sub_devices below, and
# e.g. drivers/bj9900.py for the same pattern on a radio with Left/Right
# VFO memory areas), each with its own "VFO" special channel via CHIRP's
# special-channel mechanism (see e.g. drivers/retevis_ha1g.py).

CHINFO_A_ADDR = 0x48000
CHINFO_B_ADDR = 0x4A000
CHINFO_A_BK_ADDR = 0x4C000
CHINFO_B_BK_ADDR = 0x4E000

SETMOMDE_ADDR = 0x44000
SETMOMDE_SIZE = 1280

ADJMOMDE_ADDR = 0x46000
ADJMOMDE_SIZE = 1280

# "Digital Config" user-name table (a DMR-style contact list this analog
# radio's shared OEM platform still carries under the hood). Only the head
# (first 4096 bytes, holding the visible preset entries), a handful of
# 16-byte markers spaced through the mostly-blank middle, and the tail
# (4096 bytes) are ever touched by a real write.
DIGITAL_USERNAME_ADDR = 0x420000
DIGITAL_USERNAME_SIZE = 4096
DIGITAL_USERNAME_MARKER_ADDRS = [
    0x421000, 0x422000, 0x423000, 0x424000, 0x425000, 0x426000, 0x427000,
]
DIGITAL_USERNAME_MARKER_SIZE = 16
DIGITAL_USERNAME_TAIL_ADDR = 0x428000
DIGITAL_USERNAME_TAIL_SIZE = 4096

CTDCS_WAVE_ADDR = 0x120000
CTDCS_WAVE_SIZE = 16384
CTDCS_WAVE_MIRROR_ADDR = 0x124000
# 16-byte "marker" writes into the primary, at the start of each 4096-byte
# quarter, observed alongside the full mirror write.
CTDCS_WAVE_MARKER_OFFSETS = [0x0000, 0x1000, 0x2000, 0x3000]
CTDCS_WAVE_MARKER_SIZE = 16

GRP_USER_NAME_ADDR = 0x62000
GRP_USER_NAME_SIZE = 4096

SCR_CTDCS_SPE_A_ADDR = 0x110000
SCR_CTDCS_SPE_A_SIZE = 4016
SCR_CTDCS_SPE_B_ADDR = 0x111000
SCR_CTDCS_SPE_B_SIZE = 4016

# Cheap identity/version re-check the real CPS performs right before writing
# (after LEADCODE+RESET). Not stored or written back -- just a sanity ping.
IDENTITY_CHECK_REGIONS = [
    (0x13F0, 16), (0x13F7, 9), (0x1FFF0, 16), (0x1FFF7, 9), (0x12FFF0, 16),
]

NO_TONE = 0xFFFF

_MEM_FORMAT = """
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  // Bytes 12-15: packed flag fields. Every bit assignment here was
  // confirmed by isolated single-variable hardware diffs (change exactly
  // one field via the vendor CPS, write, read back raw bytes, repeat) --
  // see PROTOCOL_NOTES.md. "unknownNN_*" bits are ones no CPS control was
  // found to touch; they are preserved on write.
  u8   unknown12_msb:1,
       spkunmute:2,       // Speaker Unmute (value 3 unreachable from CPS)
       bcl:2,             // Busy Channel Lockout (value 3 unreachable)
       sigtype_2t5t:1,    // Signal Type: 2 Tone & 5 Tone (one-hot with...
       sigtype_dtmf:1,    // ...Signal Type: DTMF; neither bit set = None)
       unknown12_lsb:1;
  u8   vox:1,
       unknown13:1,
       power:1,           // 1 = high, 0 = low
       wide:1,            // 1 = wide (FM), 0 = narrow (NFM)
       randomfre:1,       // Random Frequency (roam)
       digserve:1,        // Dig Serve (1 = Yes, the CPS default)
       pttid:2;           // Off/BOT/EOT/Both (only Both=3 directly confirmed)
  u8   unknown14_msb:3,
       jmppwd:1,          // Hop/Jump Password
       scan:1,            // 1 = included in scan, 0 = skipped
       comp:1,            // Compander
       scr:1,             // Scramble
       unknown14_lsb:1;
  u8   unknown15:3,
       ctdegree:2,        // CtDegree
       scramblefreq:3;    // Scramble Frequency group, raw = group - 1
  u8   offset_cache[4];
  char name[12];
} memory[%d];
""" % PHYSICAL_CHANNELS

BCL_OPTIONS = ["Off", "Carrier", "QT/DQT"]
SIGNAL_TYPE_OPTIONS = ["None", "DTMF", "2 Tone & 5 Tone"]
SPKUNMUTE_OPTIONS = ["QT/DQT", "QT/DQT and Signal", "QT/DQT or Signal"]
PTTID_OPTIONS = ["Off", "BOT", "EOT", "Both"]
CTDEGREE_OPTIONS = ["Off", "120", "180", "240"]
# Scramble Frequency: the 8 groups (2700-3400Hz in 100Hz steps per
# Config.def's "0_8Grp_2700_3400"). There is no "Off" in the CPS -- group 8
# (3400Hz) is the default and is effectively inaudible/off on real hardware
# (confirmed by ear against other radios, 2026-09-06).
SCRAMBLE_FREQ_OPTIONS = ["1-2700", "2-2800", "3-2900", "4-3000",
                         "5-3100", "6-3200", "7-3300", "8-3400"]

# flags12-15 values the CPS writes for a brand-new channel; used to seed a
# freshly-created memory instead of leaving unmapped bits at the 0xFF
# erased-flash value. (dict keyed by bitwise field name)
_NEW_CHANNEL_FLAG_DEFAULTS = {
    "unknown12_msb": 0, "spkunmute": 0, "bcl": 0, "sigtype_2t5t": 0,
    "sigtype_dtmf": 0, "unknown12_lsb": 0,
    "vox": 0, "unknown13": 0, "power": 1, "wide": 1, "randomfre": 0,
    "digserve": 1, "pttid": 0,
    "unknown14_msb": 0, "jmppwd": 0, "scan": 1, "comp": 0, "scr": 0,
    "unknown14_lsb": 0,
    "unknown15": 0, "ctdegree": 0, "scramblefreq": 7,
}

# SCR_CTDCS_SPE per-channel record (16 bytes; see PROTOCOL_NOTES.md).
# Signal Dec/Enc are the only fields decoded so far, packed into byte 0.
SCR_RECORD_SIZE = 16
SCR_SIGDEC_MASK = 0x0F
SCR_SIGENC_MASK = 0xF0
SCR_SIGENC_SHIFT = 4
SIGNAL_DEC_ENC_OPTIONS = [str(n) for n in range(1, 17)]  # displayed 1-16

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                chirp_common.PowerLevel("High", watts=25)]


def _layer1_encode(logical: bytes, seed: int) -> bytes:
    out = bytearray(len(logical) + 1)
    out[0] = seed
    idx = seed
    for i, b in enumerate(logical):
        out[i + 1] = (b + SECRET_RANDOM[idx % 256]) % 256
        idx += 1
    return bytes(out)


def _layer1_decode(wire_after_seed: bytes, seed: int) -> bytes:
    out = bytearray(len(wire_after_seed))
    idx = seed
    for i, b in enumerate(wire_after_seed):
        out[i] = (b + 256 - SECRET_RANDOM[idx % 256]) % 256
        idx += 1
    return bytes(out)


def _layer2_decode_payload(decoded_frame: bytes, payload_off: int,
                           length: int) -> bytes:
    rnd_byte = decoded_frame[payload_off + length]
    k = SECRET_CODE_DATA[rnd_byte]
    plain = bytearray(length)
    for j in range(length):
        t = (decoded_frame[payload_off + j] - SECRET_RANDOM[j % 256] +
             k + 256) % 256
        plain[j] = SECRET_CODE_DATA[t]
    return bytes(plain)


def _layer2_encode_payload(plain: bytes, rnd_byte: int) -> bytes:
    k = SECRET_CODE_DATA[rnd_byte]
    out = bytearray(len(plain))
    for i, pbyte in enumerate(plain):
        out[i] = (SECRET_SEQ_LIST[pbyte] - k +
                  SECRET_RANDOM[i % 256] + 256) % 256
    return bytes(out)


def _octal_digits_to_chirp_dtcs(raw_code: int) -> int:
    """raw_code is 0-511 (9 bits); DCS codes are conventionally written/stored
    in CHIRP as the decimal digits of the code's octal representation, e.g.
    octal 023 -> stored/looked-up as the integer 23."""
    return int(format(raw_code, "03o"))


def _chirp_dtcs_to_octal_digits(dtcs_code: int) -> int:
    return int(str(dtcs_code), 8)


@directory.register
class AbbreeAR7600Radio(chirp_common.CloneModeRadio):
    """ABBREE AR-7600"""
    VENDOR = "Abbree"
    MODEL = "AR-7600"
    BAUD_RATE = 115200
    NEEDS_COMPAT_SERIAL = False
    VARIANT = ""
    # CHINFO group A + group B combined -- the only part of the radio's
    # memory that lives in self._mmap (see sync_in below); everything else
    # (SETMOMDE, ADJMOMDE, etc.) is fetched separately during a live sync
    # and isn't part of the saved/loaded image.
    _memsize = CHINFO_GROUP_SIZE * 2
    # Physical slot offset of this variant's group within the shared,
    # combined Group A + Group B memory map. Only meaningful (and only
    # read) on the Group A/B sub-device variants below -- the root radio
    # (VARIANT == "") has sub-devices instead of its own channel list.
    _group_offset = 0

    def _pipe_flush(self):
        try:
            self.pipe.flushInput()
        except Exception as e:
            raise errors.RadioError("Error flushing radio port: %s" % e)

    def _pipe_write(self, data):
        try:
            self.pipe.write(data)
        except Exception as e:
            raise errors.RadioError("Error writing to radio: %s" % e)

    def _pipe_read(self, size):
        try:
            return self.pipe.read(size)
        except Exception as e:
            raise errors.RadioError("Error reading from radio: %s" % e)

    def _handshake(self, tries=15):
        for attempt in range(tries):
            self._pipe_flush()
            wire = _layer1_encode(LEADCODE_TX, seed=1 + (attempt % 254))
            self._pipe_write(wire)
            buf = b""
            deadline = time.time() + 0.5
            while time.time() < deadline and len(buf) < 7:
                chunk = self._pipe_read(7 - len(buf))
                if chunk:
                    buf += chunk
                else:
                    break
            if len(buf) < 7:
                continue
            seed = buf[0]
            decoded = _layer1_decode(buf[1:7], seed)
            if decoded == LEADCODE_RX:
                return True
        return False

    def _read_block(self, addr, length):
        body = bytearray()
        body += READFLASH_TX_MAGIC
        body += addr.to_bytes(4, "big")
        body += length.to_bytes(2, "big")
        chk = CHK_BASE + sum(body[6:12])
        body += chk.to_bytes(4, "big")
        seed = 1 + (int(time.time() * 1000) % 254)
        wire = _layer1_encode(bytes(body), seed)

        self._pipe_flush()
        self._pipe_write(wire)

        expected = 1 + 6 + 4 + 2 + length + 1 + 4
        buf = b""
        deadline = time.time() + 3.0
        while time.time() < deadline and len(buf) < expected:
            chunk = self._pipe_read(expected - len(buf))
            if chunk:
                buf += chunk
        if len(buf) < expected:
            raise errors.RadioError(
                "Short read response: got %d/%d bytes" % (len(buf), expected))

        rseed = buf[0]
        decoded = _layer1_decode(buf[1:], rseed)
        if decoded[0:6] != READFLASH_RX_MAGIC:
            raise errors.RadioError("Bad READFLASH ack magic: %s" %
                                    util.hexprint(decoded[0:6]))
        addr_echo = int.from_bytes(decoded[6:10], "big")
        rlen = int.from_bytes(decoded[10:12], "big")
        if rlen != length or addr_echo != addr:
            raise errors.RadioError(
                "Unexpected echo: addr=0x%X len=%d (wanted 0x%X/%d)" %
                (addr_echo, rlen, addr, length))
        chk_covered = decoded[6:12 + rlen + 1]
        chk_calc = CHK_BASE + sum(chk_covered)
        chk_wire = int.from_bytes(decoded[12 + rlen + 1:12 + rlen + 5], "big")
        if chk_calc != chk_wire:
            raise errors.RadioError("Checksum mismatch reading 0x%X" % addr)
        return _layer2_decode_payload(decoded, 12, rlen)

    def _write_block(self, addr, payload):
        length = len(payload)
        rnd_byte = 1 + (int(time.time() * 1000) % 254)
        enc_payload = _layer2_encode_payload(payload, rnd_byte)

        body = bytearray()
        body += WRITEFLASH_TX_MAGIC
        body += addr.to_bytes(4, "big")
        body += length.to_bytes(2, "big")
        body += enc_payload
        body += bytes([rnd_byte])
        chk = CHK_BASE + sum(body[6:12 + length + 1])
        body += chk.to_bytes(4, "big")

        seed = 1 + (int(time.time() * 1000 + 7) % 254)
        wire = _layer1_encode(bytes(body), seed)

        self._pipe_flush()
        self._pipe_write(wire)

        expected = 1 + 6 + 4  # seed + magic + 4-byte device checksum ack
        buf = b""
        deadline = time.time() + 3.0
        while time.time() < deadline and len(buf) < expected:
            chunk = self._pipe_read(expected - len(buf))
            if chunk:
                buf += chunk
        if len(buf) < expected:
            raise errors.RadioError(
                "Short write-ack response: got %d/%d bytes" %
                (len(buf), expected))
        rseed = buf[0]
        decoded = _layer1_decode(buf[1:], rseed)
        if decoded[0:6] != WRITEFLASH_RX_MAGIC:
            raise errors.RadioError("Bad WRITEFLASH ack magic: %s" %
                                    util.hexprint(decoded[0:6]))
        # decoded[6:10] is the device's own checksum (23205+sum) of the
        # plaintext bytes it decoded -- verify it matches what we intended
        # to send, so a corrupted/misdecoded write is never silently
        # accepted as successful.
        device_chk = int.from_bytes(decoded[6:10], "big")
        expected_chk = CHK_BASE + sum(payload)
        if device_chk != expected_chk:
            raise errors.RadioError(
                "Write checksum mismatch at 0x%X: device=%d expected=%d "
                "(radio may not have received the data correctly)" %
                (addr, device_chk, expected_chk))

    def _reset_radio(self):
        """Mirrors modSoftAdj.ComResetRadio: fresh handshake, then a bare
        RESET frame (no address/length/payload). Observed in a live capture
        between the read and write phases of a real "Write to Radio"."""
        if not self._handshake():
            raise errors.RadioError("Handshake failed before RESET")
        seed = 1 + (int(time.time() * 1000) % 254)
        wire = _layer1_encode(RESET_TX_MAGIC, seed)
        self._pipe_flush()
        self._pipe_write(wire)
        buf = b""
        deadline = time.time() + 2.0
        while time.time() < deadline and len(buf) < 7:
            chunk = self._pipe_read(7 - len(buf))
            if chunk:
                buf += chunk
        if len(buf) < 7:
            raise errors.RadioError("No reply to RESET")
        rseed = buf[0]
        decoded = _layer1_decode(buf[1:7], rseed)
        if decoded != RESET_RX_MAGIC:
            raise errors.RadioError(
                "Bad RESET ack: %s" % util.hexprint(decoded))

    def _read_region(self, addr, size, status=None):
        data = bytearray()
        off = 0
        while off < size:
            chunk_len = min(BLOCK_SIZE, size - off)
            data += self._read_block(addr + off, chunk_len)
            off += chunk_len
            if status is not None:
                status.cur += chunk_len
                self.status_fn(status)
        return bytes(data)

    def _write_region(self, addr, data, status=None):
        off = 0
        while off < len(data):
            chunk_len = min(BLOCK_SIZE, len(data) - off)
            self._write_block(addr + off, data[off:off + chunk_len])
            off += chunk_len
            if status is not None:
                status.cur += chunk_len
                self.status_fn(status)

    # Total bytes moved per full sync, for progress reporting.
    _SYNC_TOTAL = (SETMOMDE_SIZE + ADJMOMDE_SIZE + DIGITAL_USERNAME_SIZE +
                   DIGITAL_USERNAME_TAIL_SIZE + CTDCS_WAVE_SIZE * 2 +
                   GRP_USER_NAME_SIZE + SCR_CTDCS_SPE_A_SIZE +
                   SCR_CTDCS_SPE_B_SIZE + CHINFO_GROUP_SIZE * 4)

    def _read_passthrough_regions(self, status=None):
        """Fetches every region that gets written back byte-for-byte
        unmodified on sync_out() (i.e. everything except the CHINFO
        channel groups, which reflect the user's edits). Called from
        sync_in() for a normal live download, and also from sync_out()
        itself if this instance was instead populated from a saved image
        file (which only ever contains the CHINFO groups -- see
        get_mmap()/_memsize) and so never had a chance to fetch these."""
        self._setmomde = self._read_region(
            SETMOMDE_ADDR, SETMOMDE_SIZE, status)
        self._adjmomde = self._read_region(
            ADJMOMDE_ADDR, ADJMOMDE_SIZE, status)
        self._digital_username = self._read_region(
            DIGITAL_USERNAME_ADDR, DIGITAL_USERNAME_SIZE, status)
        self._digital_username_markers = [
            self._read_block(a, DIGITAL_USERNAME_MARKER_SIZE)
            for a in DIGITAL_USERNAME_MARKER_ADDRS]
        self._digital_username_tail = self._read_region(
            DIGITAL_USERNAME_TAIL_ADDR, DIGITAL_USERNAME_TAIL_SIZE, status)
        self._ctdcs_wave = self._read_region(
            CTDCS_WAVE_ADDR, CTDCS_WAVE_SIZE, status)
        self._grp_user_name = self._read_region(
            GRP_USER_NAME_ADDR, GRP_USER_NAME_SIZE, status)
        # Mutable bytearrays (not bytes): Group A/B sub-devices need to edit
        # individual channels' 16-byte records in place and have that
        # visible back on the root for sync_out(), the same way they share
        # self._mmap for CHINFO -- see get_sub_devices().
        self._scr_ctdcs_spe_a = bytearray(self._read_region(
            SCR_CTDCS_SPE_A_ADDR, SCR_CTDCS_SPE_A_SIZE, status))
        self._scr_ctdcs_spe_b = bytearray(self._read_region(
            SCR_CTDCS_SPE_B_ADDR, SCR_CTDCS_SPE_B_SIZE, status))

    def sync_in(self):
        if not self._handshake():
            raise errors.RadioError(
                "Could not connect to radio (LEADCODE handshake failed). "
                "Make sure the ABBREE CPS software is closed and the radio "
                "is powered on.")
        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        status.max = self._SYNC_TOTAL
        status.cur = 0

        self._read_passthrough_regions(status)

        group_a = self._read_region(CHINFO_A_ADDR, CHINFO_GROUP_SIZE, status)
        group_b = self._read_region(CHINFO_B_ADDR, CHINFO_GROUP_SIZE, status)
        # account for the backup groups in the progress bar even though we
        # don't fetch them (they're re-derived from A/B on write)
        status.cur += CHINFO_GROUP_SIZE * 2
        if self.status_fn:
            self.status_fn(status)

        self._mmap = memmap.MemoryMapBytes(group_a + group_b)
        self.process_mmap()

    def sync_out(self):
        self._reset_radio()
        time.sleep(1.5)  # let the radio settle after RESET before reconnecting
        if not self._handshake(tries=30):
            raise errors.RadioError("Handshake failed after RESET")
        for addr, size in IDENTITY_CHECK_REGIONS:
            self._read_block(addr, size)  # cheap sanity ping, matches real CPS

        if not hasattr(self, "_setmomde"):
            # This instance was populated from a saved image file (only
            # ever the CHINFO groups -- see get_mmap()/_memsize), not a
            # live sync_in(), so none of the pass-through regions below
            # have been fetched yet. Do that now, over the connection we
            # already just established above, from whatever radio is
            # actually connected: this preserves *that* radio's own
            # current general settings/calibration data rather than
            # crashing or guessing, e.g. when restoring a saved channel
            # backup onto a (possibly different) radio.
            self._read_passthrough_regions()

        status = chirp_common.Status()
        status.msg = "Uploading to radio"
        status.max = self._SYNC_TOTAL
        status.cur = 0

        # CRITICAL: byte 242 of SETMOMDE (physical 0x440F2) is a commit/
        # write-mode flag. A plain read-then-write-back of SETMOMDE leaves
        # it at the "read" value (0x00) and the whole write silently fails
        # to persist past a power cycle, even though every block's device
        # checksum verifies -- the radio quietly accepts and discards it.
        # Confirmed via live capture diff (a real "Write to Radio" always
        # sets this to 0x40) and validated end-to-end against real hardware
        # (2026-09-05): only setting this byte makes the write survive a
        # power cycle.
        setmomde = bytearray(self._setmomde)
        setmomde[242] = 0x40
        self._write_region(SETMOMDE_ADDR, bytes(setmomde), status)
        self._write_region(
            DIGITAL_USERNAME_ADDR, self._digital_username, status)
        for addr, chunk in zip(DIGITAL_USERNAME_MARKER_ADDRS,
                               self._digital_username_markers):
            self._write_block(addr, chunk)
        self._write_region(DIGITAL_USERNAME_TAIL_ADDR,
                           self._digital_username_tail, status)
        self._write_region(ADJMOMDE_ADDR, self._adjmomde, status)
        for off in CTDCS_WAVE_MARKER_OFFSETS:
            end = off + CTDCS_WAVE_MARKER_SIZE
            self._write_block(CTDCS_WAVE_ADDR + off,
                              self._ctdcs_wave[off:end])
        self._write_region(CTDCS_WAVE_MIRROR_ADDR, self._ctdcs_wave, status)

        data = self.get_mmap()
        group_a = bytes(data[0:CHINFO_GROUP_SIZE])
        group_b = bytes(data[CHINFO_GROUP_SIZE:CHINFO_GROUP_SIZE * 2])
        self._write_region(CHINFO_A_ADDR, group_a, status)
        self._write_region(CHINFO_B_ADDR, group_b, status)
        self._write_region(CHINFO_A_BK_ADDR, group_a, status)
        self._write_region(CHINFO_B_BK_ADDR, group_b, status)

        self._write_region(SCR_CTDCS_SPE_A_ADDR, self._scr_ctdcs_spe_a, status)
        self._write_region(SCR_CTDCS_SPE_B_ADDR, self._scr_ctdcs_spe_b, status)
        self._write_region(GRP_USER_NAME_ADDR, self._grp_user_name, status)

    def process_mmap(self):
        self._memobj = bitwise.parse(_MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = False
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        # Frequencies are stored as raw absolute values (packed BCD), not as
        # a step-multiplied index, so any frequency is representable.
        rf.has_nostep_tuning = True
        rf.has_bank = False
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone", "Tone->DTCS", "DTCS->Tone",
            "DTCS->", "->Tone", "->DTCS", "DTCS->DTCS",
        ]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 12
        rf.valid_characters = chirp_common.CHARSET_ASCII
        # No "off": the radio has no distinct "don't transmit" state for a
        # channel beyond txfreq == rxfreq (simplex), which is already "".
        rf.valid_duplexes = ["", "-", "+", "split"]
        rf.valid_bands = [(108000000, 174000000), (400000000, 520000000)]
        if self.VARIANT == "":
            # The root radio has no channel list of its own -- it exposes
            # Group A and Group B as separate sub-device tabs instead,
            # matching the CPS's own UI (which keeps two entirely separate
            # channel trees, each with its own VFO memory).
            rf.has_sub_devices = True
            rf.memory_bounds = (0, 0)
        else:
            rf.memory_bounds = (0, REGULAR_PER_GROUP - 1)
            rf.valid_special_chans = ["VFO"]
        return rf

    def get_sub_devices(self):
        subs = [AbbreeAR7600RadioGroupA(self._mmap),
                AbbreeAR7600RadioGroupB(self._mmap)]
        for sub in subs:
            # Share (not copy) the mutable SCR_CTDCS_SPE buffers so a
            # sub-device's per-channel edits (Signal Dec/Enc) are visible
            # back on the root for sync_out(), same as self._mmap already
            # is for CHINFO. These only exist after a real sync_in() --
            # when loaded from an image file (e.g. CHIRP's offline tests),
            # neither exists yet, so fall back to the same all-0xFF stand-in
            # _my_scr_ctdcs_spe() uses.
            sub._scr_ctdcs_spe_a = self._ensure_scr_ctdcs_spe(
                "_scr_ctdcs_spe_a")
            sub._scr_ctdcs_spe_b = self._ensure_scr_ctdcs_spe(
                "_scr_ctdcs_spe_b")
        return subs

    def _ensure_scr_ctdcs_spe(self, attr):
        """Returns self.<attr>, creating an all-0xFF stand-in bytearray of
        the right size first if it doesn't exist yet (i.e. this instance
        was loaded from an image file rather than a real sync_in())."""
        buf = getattr(self, attr, None)
        if buf is None:
            buf = bytearray(b"\xff" * SCR_CTDCS_SPE_A_SIZE)
            setattr(self, attr, buf)
        return buf

    def _my_scr_ctdcs_spe(self):
        """The SCR_CTDCS_SPE buffer for this instance's own group. Falls
        back to an all-0xFF stand-in if accessed outside a real sync_in()
        (e.g. in offline tests), so get_memory() never crashes."""
        attr = ("_scr_ctdcs_spe_a" if self._group_offset == 0
                else "_scr_ctdcs_spe_b")
        return self._ensure_scr_ctdcs_spe(attr)

    def _physical_index(self, number):
        """Maps this group's CHIRP-facing channel number (0..249) or the
        special name "VFO" to a physical slot index in the combined
        Group A + Group B array (0..501, 251 slots per group)."""
        if number == "VFO":
            return self._group_offset + CHANNELS_PER_GROUP - 1
        return self._group_offset + number

    @staticmethod
    def _decode_tone(value):
        """Returns (mode, tone_hz_or_None, dtcs_code_or_None, polarity) for
        one raw 16-bit Ctdcs field, per PROTOCOL_NOTES.md section 5. CTCSS
        confirmed against real hardware; DCS ranges are from the vendor
        source but unverified against a real DCS-programmed channel."""
        if value == NO_TONE or value == 0:
            return "", None, None, "N"
        if 100 <= value <= 2950:
            return "Tone", value / 10.0, None, "N"
        if 10240 <= value <= 10751:
            raw = value - 10240
            return "DTCS", None, _octal_digits_to_chirp_dtcs(raw), "N"
        if 43008 <= value <= 43519:
            raw = value - 43008
            return "DTCS", None, _octal_digits_to_chirp_dtcs(raw), "R"
        return "", None, None, "N"

    @staticmethod
    def _encode_ctcss(tone_hz):
        return int(round(tone_hz * 10))

    @staticmethod
    def _encode_dtcs(dtcs_code, polarity):
        raw = _chirp_dtcs_to_octal_digits(dtcs_code)
        return (43008 if polarity == "R" else 10240) + raw

    def get_memory(self, number):
        phys = self._physical_index(number)
        _mem = self._memobj.memory[phys]
        mem = chirp_common.Memory()
        if isinstance(number, str):
            mem.number = REGULAR_PER_GROUP
            mem.extd_number = number
        else:
            mem.number = number

        rxfreq_raw = _mem.rxfreq.get_raw(asbytes=True)
        if rxfreq_raw in (b"\xff\xff\xff\xff", b"\x00\x00\x00\x00"):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10
        txfreq = int(_mem.txfreq) * 10

        if txfreq == mem.freq:
            mem.duplex = ""
            mem.offset = 0
        elif abs(txfreq - mem.freq) > 70000000:
            mem.duplex = "split"
            mem.offset = txfreq
        else:
            mem.duplex = "+" if txfreq > mem.freq else "-"
            mem.offset = abs(txfreq - mem.freq)

        name_raw = str(_mem.name)
        mem.name = name_raw.rstrip("\xff\x00").rstrip()

        # Following the standard CHIRP convention (see e.g.
        # chirp/drivers/baofeng_common.py get_memory): rtone/dtcs are always
        # the TX-side values, ctone/rx_dtcs are always the RX-side values,
        # and cross_mode is "TXmode->RXmode".
        dtcs_pol = ["N", "N"]  # [tx, rx]

        tx_mode, tx_tone, tx_dtcs, tx_pol = self._decode_tone(int(_mem.txtone))
        if tx_mode == "Tone":
            mem.rtone = tx_tone
        elif tx_mode == "DTCS":
            mem.dtcs = tx_dtcs
            dtcs_pol[0] = tx_pol

        rx_mode, rx_tone, rx_dtcs, rx_pol = self._decode_tone(int(_mem.rxtone))
        if rx_mode == "Tone":
            mem.ctone = rx_tone
        elif rx_mode == "DTCS":
            mem.rx_dtcs = rx_dtcs
            dtcs_pol[1] = rx_pol

        if tx_mode == "Tone" and not rx_mode:
            mem.tmode = "Tone"
        elif tx_mode == rx_mode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif tx_mode == rx_mode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rx_mode or tx_mode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (tx_mode, rx_mode)
        else:
            mem.tmode = ""

        mem.dtcs_polarity = "".join(dtcs_pol)

        mem.mode = "FM" if _mem.wide else "NFM"
        mem.power = POWER_LEVELS[1] if _mem.power else POWER_LEVELS[0]
        mem.skip = "" if _mem.scan else "S"

        # clamped defensively: values outside what the CPS UI can actually
        # select shouldn't be reachable on real hardware, but a corrupted
        # or hand-edited image could still contain one.
        bcl_val = min(int(_mem.bcl), len(BCL_OPTIONS) - 1)
        spkunmute_val = min(int(_mem.spkunmute), len(SPKUNMUTE_OPTIONS) - 1)
        degree_val = int(_mem.ctdegree)
        pttid_val = int(_mem.pttid)
        scrfreq_val = int(_mem.scramblefreq)
        if _mem.sigtype_dtmf:
            sigtype_val = 1
        elif _mem.sigtype_2t5t:
            sigtype_val = 2
        else:
            sigtype_val = 0

        local_index = phys - self._group_offset
        scr_record = self._my_scr_ctdcs_spe()[
            local_index * SCR_RECORD_SIZE:(local_index + 1) * SCR_RECORD_SIZE]
        scr_byte0 = scr_record[0] if scr_record else 0xFF
        if scr_byte0 == 0xFF:
            # Untouched/blank record -- show the same "1" default a freshly
            # configured channel gets (see was_blank handling in
            # set_memory) rather than the misleading 0xFF-as-15 reading.
            sigdec_val = sigenc_val = 0
        else:
            sigdec_val = scr_byte0 & SCR_SIGDEC_MASK
            sigenc_val = (scr_byte0 & SCR_SIGENC_MASK) >> SCR_SIGENC_SHIFT

        mem.extra = RadioSettingGroup("Extra", "extra")
        mem.extra.append(RadioSetting(
            "bcl", "Busy Channel Lockout",
            RadioSettingValueList(BCL_OPTIONS, current_index=bcl_val)))
        mem.extra.append(RadioSetting(
            "ctdegree", "CtDegree",
            RadioSettingValueList(CTDEGREE_OPTIONS,
                                  current_index=degree_val)))
        mem.extra.append(RadioSetting(
            "vox", "VOX",
            RadioSettingValueBoolean(bool(_mem.vox))))
        mem.extra.append(RadioSetting(
            "randomfre", "Random Frequency (roam)",
            RadioSettingValueBoolean(bool(_mem.randomfre))))
        mem.extra.append(RadioSetting(
            "scr", "Scramble",
            RadioSettingValueBoolean(bool(_mem.scr))))
        mem.extra.append(RadioSetting(
            "comp", "Compander",
            RadioSettingValueBoolean(bool(_mem.comp))))
        mem.extra.append(RadioSetting(
            "jmppwd", "Hop/Jump Password",
            RadioSettingValueBoolean(bool(_mem.jmppwd))))
        mem.extra.append(RadioSetting(
            "signaltype", "Signal Type",
            RadioSettingValueList(SIGNAL_TYPE_OPTIONS,
                                  current_index=sigtype_val)))
        mem.extra.append(RadioSetting(
            "digserve", "Dig Serve",
            RadioSettingValueBoolean(bool(_mem.digserve))))
        mem.extra.append(RadioSetting(
            "pttid", "PTT ID",
            RadioSettingValueList(PTTID_OPTIONS, current_index=pttid_val)))
        mem.extra.append(RadioSetting(
            "spkunmute", "Speaker Unmute",
            RadioSettingValueList(SPKUNMUTE_OPTIONS,
                                  current_index=spkunmute_val)))
        mem.extra.append(RadioSetting(
            "scramblefreq", "Scramble Frequency",
            RadioSettingValueList(SCRAMBLE_FREQ_OPTIONS,
                                  current_index=scrfreq_val)))
        mem.extra.append(RadioSetting(
            "signaldec", "Signal Dec",
            RadioSettingValueList(SIGNAL_DEC_ENC_OPTIONS,
                                  current_index=sigdec_val)))
        mem.extra.append(RadioSetting(
            "signalenc", "Signal Enc",
            RadioSettingValueList(SIGNAL_DEC_ENC_OPTIONS,
                                  current_index=sigenc_val)))

        return mem

    def set_memory(self, mem):
        number = mem.extd_number if mem.extd_number == "VFO" else mem.number
        _mem = self._memobj.memory[self._physical_index(number)]

        if mem.empty:
            # 0xFF matches this radio's erased-flash / unprogrammed-channel
            # fill pattern, as observed on real hardware.
            _mem.set_raw(b"\xff" * (_mem.size() // 8))
            return

        if _mem.get_raw(asbytes=True)[12:16] == b"\xff\xff\xff\xff":
            # A freshly-created channel: seed bytes 12-15 with the same
            # defaults the CPS itself uses for a new channel (observed on
            # every untouched default channel on real hardware), rather
            # than leaving unmapped bits at the blank/erased 0xFF fill.
            for field, value in _NEW_CHANNEL_FLAG_DEFAULTS.items():
                setattr(_mem, field, value)

        _mem.rxfreq = mem.freq // 10
        if mem.duplex == "split":
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) // 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) // 10
        else:
            _mem.txfreq = mem.freq // 10

        name_bytes = mem.name.encode("ascii", errors="replace")[:12]
        name_bytes = name_bytes + b"\xff" * (12 - len(name_bytes))
        _mem.name = name_bytes

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            txmode = "Tone"
            _mem.txtone = self._encode_ctcss(mem.rtone)
            _mem.rxtone = NO_TONE
        elif mem.tmode == "TSQL":
            rxmode = txmode = "Tone"
            _mem.txtone = self._encode_ctcss(mem.ctone)
            _mem.rxtone = self._encode_ctcss(mem.ctone)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = self._encode_dtcs(mem.dtcs, mem.dtcs_polarity[0])
            _mem.rxtone = self._encode_dtcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = self._encode_ctcss(mem.rtone)
            elif txmode == "DTCS":
                _mem.txtone = self._encode_dtcs(mem.dtcs, mem.dtcs_polarity[0])
            else:
                _mem.txtone = NO_TONE
            if rxmode == "Tone":
                _mem.rxtone = self._encode_ctcss(mem.ctone)
            elif rxmode == "DTCS":
                _mem.rxtone = self._encode_dtcs(
                    mem.rx_dtcs, mem.dtcs_polarity[1])
            else:
                _mem.rxtone = NO_TONE
        else:
            _mem.txtone = NO_TONE
            _mem.rxtone = NO_TONE

        _mem.wide = mem.mode == "FM"
        _mem.power = mem.power == POWER_LEVELS[1]
        _mem.scan = mem.skip != "S"

        # Every "Extra" setting name below is also the bitwise field name.
        bool_fields = ("vox", "randomfre", "scr", "comp", "jmppwd",
                       "digserve")
        list_field_options = {"bcl": BCL_OPTIONS, "ctdegree": CTDEGREE_OPTIONS,
                              "pttid": PTTID_OPTIONS,
                              "spkunmute": SPKUNMUTE_OPTIONS,
                              "scramblefreq": SCRAMBLE_FREQ_OPTIONS}
        for setting in mem.extra:
            name = setting.get_name()
            if name in bool_fields:
                setattr(_mem, name, bool(setting.value))
            elif name in list_field_options:
                options = list_field_options[name]
                setattr(_mem, name, options.index(str(setting.value)))
            elif name == "signaltype":
                val = SIGNAL_TYPE_OPTIONS.index(str(setting.value))
                _mem.sigtype_dtmf = val == 1
                _mem.sigtype_2t5t = val == 2
            elif name in ("signaldec", "signalenc"):
                pass  # handled below via the SCR_CTDCS_SPE buffer

        local_index = self._physical_index(number) - self._group_offset
        scr = self._my_scr_ctdcs_spe()
        scr_off = local_index * SCR_RECORD_SIZE
        sig_byte0 = scr[scr_off] if scr[scr_off] != 0xFF else 0x00
        for setting in mem.extra:
            name = setting.get_name()
            if name == "signaldec":
                val = SIGNAL_DEC_ENC_OPTIONS.index(str(setting.value))
                sig_byte0 = ((sig_byte0 & ~SCR_SIGDEC_MASK) |
                             (val & SCR_SIGDEC_MASK))
            elif name == "signalenc":
                val = SIGNAL_DEC_ENC_OPTIONS.index(str(setting.value))
                sig_byte0 = (sig_byte0 & ~SCR_SIGENC_MASK) | \
                    ((val << SCR_SIGENC_SHIFT) & SCR_SIGENC_MASK)
        scr[scr_off] = sig_byte0 & 0xFF

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[self._physical_index(number)])


class AbbreeAR7600RadioGroupA(AbbreeAR7600Radio):
    """ABBREE AR-7600 Group A VFO sub-device"""
    VARIANT = "Group A"
    _group_offset = 0


class AbbreeAR7600RadioGroupB(AbbreeAR7600Radio):
    """ABBREE AR-7600 Group B VFO sub-device"""
    VARIANT = "Group B"
    _group_offset = CHANNELS_PER_GROUP
