# Copyright 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Alinco DJ-VX50 / DJ-VX50HT.

Protocol and memory map reverse engineered from the factory programming
software (DJ-VX50HT.exe v1.00.0008, native Visual Basic 6) and verified
against a USB capture of a real programming session.

Wire protocol (9600 8N2, no flow control, DTR and RTS asserted).  Holding
RTS is what puts the radio into its "PC" state, where it locks the front
panel for the duration of the session; cloning works without it, but the
radio stays live.  All frames are
raw binary, fixed length -- no terminator and no checksum.  Every command
comes back echoed before the reply, so each exchange reads len(cmd) echo
bytes first.  (The echo persists with no radio attached, so it is almost
certainly the cable's half-duplex data line looping back rather than the
radio -- either way it must be consumed.)

    02 "PROGRA"            -> 06                     enter program mode
    52 <hi> <lo> 10        -> 57 <hi> <lo> 10 +16    read 16 bytes
    4D 02                  -> 46 03 01 25 48 02 01   identify / band info
    57 <hi> <lo> 10 +16    -> 06                     write 16 bytes
    45                     -> (nothing)              end session

Address is a 16-bit big-endian EEPROM address, always 16-byte aligned.
Note the inversion: you send 'R' to read, and the radio answers with 'W'.

PROTOCOL FAMILY.  This transport is not unique to Alinco.  The same
"\x02PROGRA" magic, the same M\x02 identify, and the same
struct.pack('>BHB', cmd, addr, length) read/write framing already appear
in fd268.py (Feidaxin) and th9800.py (TYT):

    driver        magic        ACK   ident      frame    block   memsize
    fd268.py      \x02PROGRA   0x06  M\x02 -> 8  >BHB     0x08    0x0800
    th9800.py     \x02PROGRA   'A'   M\x02 -> 16 >cHB     0x80   0x10000
    this driver   \x02PROGRA   0x06  M\x02 -> 7  >BHB     0x10    0x2000

No code is shared with them, deliberately.  fd268.py predates the py3
port -- it uses MemoryMap and str-based I/O throughout, which a new
driver may not do.  th9800.py's transport lives in module-level
functions hard-wired to that radio's ACK byte, block size and ENDR
terminator, with no reusable base.  Neither exposes a class a new model
could subclass, and the three memory maps have nothing in common beyond
the wire format.  If a shared transport base is wanted, it should be a
separate refactor across all three rather than a prerequisite here.

Memories are 0-based, matching the radio's own display.

Per-channel flags were decoded by toggling one attribute at a time on a
live radio and diffing re-reads.  Power spans two bytes (power_high plus
power_mid) to encode three levels.  The unknown1 bits shift when a channel
is front-panel edited but track no setting -- all four combinations were
observed on channels at identical settings -- so they are preserved
verbatim, never interpreted.

IMPORTANT: only the North American **HT** variant has been tested.  The
European DJ-VX50HE is believed to share this layout and protocol -- the
model ID at 0x0F80 reads "HBE" on the HT and the model check keys on that
rather than on the region suffix -- but no HE radio was available to
confirm it.  Treat HE support as untested.

Verified end to end against hardware (Alinco DJ-VX50HT, July 2026):
  - sync_in output matches a USB capture of the factory software byte
    for byte
  - get_memory/set_memory round-trips every populated channel of four
    separate codeplugs with zero byte changes
  - a single-block write landed exactly 16 bytes at the target address
    and nothing else
  - a full sync_out wrote all 370 blocks; re-reading afterwards showed
    zero differing bytes, and the frame sequence it emits (370 writes
    plus 4 control frames, with the same skipped regions) matches the
    factory software's captured session exactly
"""

import logging

from chirp import (bitwise, chirp_common, directory, errors, kenwood_tone,
                   memmap, util)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct memory {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown1:2,      // not deterministic; preserved, never interpreted
     power_high:1,
     wide:1,          // 1 = Wide, 0 = Narrow
     scan:1,          // 1 = scanned, 0 = skipped
     unknown2:1,
     bcl:1,           // busy channel lockout; not exposed in the UI
     unknown3:1;
  u8 unknown4:4,
     power_mid:1,     // with power_high clear, 1 = Mid, 0 = Low
     unknown5:3;
  u8 unknown6;
  u8 unknown7;
};

struct name {
  char name[6];
};

struct memory memory[200];

#seekto 0x1000;
struct name names[200];
"""

MEM_SIZE = 0x2000          # 8192 byte EEPROM
BLOCK = 0x10               # only block size the radio accepts
XFER_START = 0x0000
XFER_END = 0x1800          # the factory software never touches 0x1800-0x1FFF

# Regions the factory software deliberately refuses to write.  0x0ED0-0x0F8F
# holds per-radio TX power calibration and the model ID; overwriting it would
# be destructive and is not recoverable from a saved image.
WRITE_SKIP = [(0x0ED0, 0x0F8F), (0x14E0, 0x14FF)]

MAGIC = b"\x02PROGRA"
CMD_READ = 0x52            # 'R'
CMD_WRITE = 0x57           # 'W'
CMD_IDENT = b"\x4d\x02"    # 'M'
CMD_END = b"\x45"          # 'E'
ACK = 0x06

MODEL_ADDR = 0x0F80        # 6 bytes compared by the factory software
MODEL_LEN = 6

TONES = chirp_common.TONES
DTCS_CODES = chirp_common.DTCS_CODES

# All power levels come from published spec
POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=1),
    chirp_common.PowerLevel("Mid", watts=2),
    chirp_common.PowerLevel("High", watts=5),
]


def _skipped(addr):
    return any(lo <= addr <= hi for lo, hi in WRITE_SKIP)


def _configure_pipe(pipe):
    """Match the line settings the factory software uses.

    Two details matter here, both taken from a USB capture of the factory
    software rather than from its own configuration:

    Asserting RTS for the duration of the session is what puts the radio
    into its "PC" state -- it displays PC and locks the front panel, so a
    stray PTT press or knob turn cannot disturb a transfer in progress.
    Cloning works without it, but the radio stays live, so raise it.

    The factory app's MSComm string reads "9600,N,8,1", but what actually
    reaches the FTDI chip is SET_DATA 0x1008 -- eight data bits, no
    parity, and *two* stop bits. Match the wire, not the config string.
    """
    try:
        pipe.stopbits = 2
    except Exception as e:
        LOG.warning('Could not set two stop bits: %s', e)
    try:
        pipe.dtr = True
        pipe.rts = True
    except Exception as e:
        LOG.warning('Could not raise DTR/RTS: %s', e)


class _Proto:
    """Thin protocol helper bound to a pipe."""

    def __init__(self, pipe):
        self.pipe = pipe

    def _xfer(self, cmd, replylen):
        """Send cmd, consume the echo, return replylen bytes of reply."""
        self.pipe.write(cmd)
        echo = self.pipe.read(len(cmd))
        if echo != cmd:
            raise errors.RadioError(
                "No echo from radio (got %s, expected %s) -- check cable "
                "and that the radio is on" % (util.hexprint(echo),
                                              util.hexprint(cmd)))
        if not replylen:
            return b""
        data = self.pipe.read(replylen)
        if len(data) != replylen:
            raise errors.RadioError(
                "Short reply: wanted %i bytes, got %i" % (replylen, len(data)))
        return data

    def start(self):
        if self._xfer(MAGIC, 1)[0] != ACK:
            raise errors.RadioError("Radio did not acknowledge program mode")

    def ident(self):
        """Identify/band-info frame.  Reply is 7 bytes beginning with 'F'."""
        reply = self._xfer(CMD_IDENT, 7)
        if reply[0] != 0x46:
            raise errors.RadioError("Unexpected identify reply: %s"
                                    % util.hexprint(reply))
        # TODO(fields): only one sample of this frame has been observed
        # (46 03 01 25 48 02 01); the field layout is unknown.  The factory
        # software uses it to raise "Frequency not match!" on a band mismatch.
        LOG.debug("Identify: %s", util.hexprint(reply))
        return reply

    def read_block(self, addr):
        cmd = bytes([CMD_READ, addr >> 8, addr & 0xFF, BLOCK])
        reply = self._xfer(cmd, 4 + BLOCK)
        if reply[0] != CMD_WRITE:
            raise errors.RadioError(
                "Bad read header at 0x%04X: %s" % (addr, util.hexprint(reply)))
        got = (reply[1] << 8) | reply[2]
        if got != addr:
            raise errors.RadioError(
                "Radio returned address 0x%04X, expected 0x%04X" % (got, addr))
        return reply[4:4 + BLOCK]

    def write_block(self, addr, data):
        assert len(data) == BLOCK
        cmd = bytes([CMD_WRITE, addr >> 8, addr & 0xFF, BLOCK]) + bytes(data)
        if self._xfer(cmd, 1)[0] != ACK:
            raise errors.RadioError("Radio refused write at 0x%04X" % addr)

    def end(self):
        self._xfer(CMD_END, 0)


def _status(radio, addr, msg):
    s = chirp_common.Status()
    s.cur = addr
    s.max = XFER_END
    s.msg = msg
    radio.status_fn(s)


def _download(radio):
    _configure_pipe(radio.pipe)
    proto = _Proto(radio.pipe)
    proto.start()

    model = proto.read_block(MODEL_ADDR)[:MODEL_LEN]
    LOG.info("Model bytes at 0x%04X: %s", MODEL_ADDR, util.hexprint(model))
    if not radio._model_ok(model):
        raise errors.RadioError(
            "Model check failed (got %s).  This does not look like a "
            "DJ-VX50." % util.hexprint(model))

    proto.ident()

    data = bytearray(b"\xFF" * MEM_SIZE)
    for addr in range(XFER_START, XFER_END, BLOCK):
        data[addr:addr + BLOCK] = proto.read_block(addr)
        _status(radio, addr, "Cloning from radio")
    proto.end()
    return memmap.MemoryMapBytes(bytes(data))


def _upload(radio):
    _configure_pipe(radio.pipe)
    proto = _Proto(radio.pipe)
    proto.start()

    model = proto.read_block(MODEL_ADDR)[:MODEL_LEN]
    if not radio._model_ok(model):
        raise errors.RadioError(
            "Model check failed (got %s); refusing to write."
            % util.hexprint(model))

    proto.ident()

    data = radio.get_mmap().get_byte_compatible()
    for addr in range(XFER_START, XFER_END, BLOCK):
        if _skipped(addr):
            # Calibration / model ID.  The factory software skips these and
            # so do we -- writing them can brick the radio's calibration.
            continue
        proto.write_block(addr, data[addr:addr + BLOCK])
        _status(radio, addr, "Cloning to radio")
    proto.end()


@directory.register
class AlincoDJVX50Radio(chirp_common.CloneModeRadio):
    """Alinco DJ-VX50 / DJ-VX50HT"""

    VENDOR = "Alinco"
    MODEL = "DJ-VX50"
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = False

    _memsize = MEM_SIZE
    # The factory software compares 6 bytes at 0x0F80.  Observed on a US
    # (HT) radio: 14 14 48 42 45 00 -> ..'H''B''E'.  'HBE' appears on both
    # variants; the region-distinguishing 'T' sits at 0x0F86, outside the
    # compared range.  We therefore only require the 'HBE' signature.
    _model_signature = b"HBE"
    _tone_model = kenwood_tone.KenwoodToneModel(
        dcs_base=0x8000, pol_mask=0x4000,
        tone_init=0xFFFF, tone_flag=0x0000,
        tone_enc_base=16, dcs_enc_base=16)

    def _model_ok(self, model):
        return self._model_signature in bytes(model)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = False        # TODO(settings): blocks not decoded
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        # "Tone->" is deliberately absent: it is byte-identical to Tone and
        # could not survive a round trip.
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->"]
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_name_length = 6
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = list(POWER_LEVELS)
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 470000000)]
        rf.memory_bounds = (0, 199)
        rf.valid_tones = list(TONES)
        rf.valid_dtcs_codes = list(DTCS_CODES)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Download failed")
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception("Upload failed")
            raise errors.RadioError("Failed to upload to radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:4] == b"\xFF\xFF\xFF\xFF":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        # An all-0xFF tx frequency is the "transmit disabled" sentinel.  It
        # must be caught on the raw bytes -- 0xFF nibbles are not valid BCD
        # and decoding them first yields garbage.
        if bytes(_mem.txfreq.get_raw()) == b"\xFF\xFF\xFF\xFF":
            txfreq = None
        else:
            txfreq = int(_mem.txfreq) * 10

        if txfreq is None or txfreq == 0:
            mem.duplex = "off"
            mem.offset = 0
        elif txfreq == mem.freq:
            mem.duplex = ""
            mem.offset = 0
        else:
            delta = txfreq - mem.freq
            if abs(delta) < 70000000:
                mem.duplex = "-" if delta < 0 else "+"
                mem.offset = abs(delta)
            else:
                mem.duplex = "split"
                mem.offset = txfreq

        self._tone_model.get_tone(_mem, mem)

        if _mem.power_high:
            mem.power = POWER_LEVELS[2]
        elif _mem.power_mid:
            mem.power = POWER_LEVELS[1]
        else:
            mem.power = POWER_LEVELS[0]

        mem.mode = "FM" if _mem.wide else "NFM"
        mem.skip = "" if _mem.scan else "S"

        mem.name = str(_nam.name).rstrip("\xFF ").rstrip()
        return mem

    def set_memory(self, memory):
        _mem = self._memobj.memory[memory.number]
        _nam = self._memobj.names[memory.number]

        if memory.empty:
            _mem.set_raw(b"\xFF" * 16)
            _nam.set_raw(b"\xFF" * 6)
            return

        was_empty = _mem.get_raw()[:4] == b"\xFF\xFF\xFF\xFF"
        if was_empty:
            # Seed the pattern observed on every populated channel.
            _mem.set_raw(b"\xFF" * 12 + b"\xF9\x00\x00\xF0")

        _mem.rxfreq = memory.freq // 10

        if memory.duplex == "off":
            _mem.txfreq.set_raw(b"\xFF\xFF\xFF\xFF")
        elif memory.duplex == "split":
            _mem.txfreq = memory.offset // 10
        elif memory.duplex == "+":
            _mem.txfreq = (memory.freq + memory.offset) // 10
        elif memory.duplex == "-":
            _mem.txfreq = (memory.freq - memory.offset) // 10
        else:
            _mem.txfreq = memory.freq // 10

        self._tone_model.set_tone(memory, _mem)

        lvl = str(memory.power) if memory.power else "High"
        _mem.power_high = lvl == "High"
        _mem.power_mid = lvl == "Mid"
        _mem.wide = memory.mode == "FM"
        _mem.scan = memory.skip != "S"

        _nam.name = memory.name.ljust(6)[:6]

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) != MEM_SIZE:
            return False
        return cls._model_signature in bytes(
            filedata[MODEL_ADDR:MODEL_ADDR + MODEL_LEN])


# The radio ships as DJ-VX50HT (North America) and DJ-VX50HE (Europe).  The
# suffix appears in the model ID at 0x0F86.  A single driver class is
# intended to cover both, but ONLY THE HT HAS BEEN TESTED -- the HE is
# assumed to share the layout and protocol, not confirmed to.
