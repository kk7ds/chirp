import logging
import threading

from chirp import chirp_common, directory, errors

from chirp.drivers.kenwood_live import KenwoodLiveRadio, NOCACHE, RADIO_IDS

LOG = logging.getLogger(__name__)

TS790E_DUPLEX = ["", "split", "+", "-"]
TS790E_TMODES = ["", "Tone"]
TS790E_SKIP = ["", "S"]

TS790E_MODES = {
    "LSB": "1",
    "USB": "2",
    "CW":  "3",
    "FM":  "4",
    "CWN": "7",
}
TS790E_MODES_REV = {val: mode for mode, val in TS790E_MODES.items()}

TS790E_TONES = list(chirp_common.OLD_TONES)
TS790E_TONES.remove(69.3)
TS790E_TONES.remove(97.4)
TS790E_OFFSETS = ["", "+", "-"]

TS790E_BANDS = [
    (135000000, 173999900),
    (300000000, 949999900),
    (1200000000, 1304957000),
]

TS790E_SHIFTS = [600000, 1600000, 35000000]

TS790E_SPECIALS = ["P1", "P2", "P3", "A1", "A2", "A3", "C1", "C2", "C3"]


def get_band(freq):
    i = 0
    for band in TS790E_BANDS:
        if freq >= band[0] and freq <= band[1]:
            return i
        i += 1
    return None


@directory.register
class TS790ERadio(KenwoodLiveRadio):
    """Kenwood TS-790E"""
    MODEL = "TS-790E"
    BAUD_RATE = 4800
    HARDWARE_FLOW = False
    COMMAND_DELIMITER = (";", "")

    _upper = 49
    _kenwood_valid_tones = list(TS790E_TONES)

    def command_no_output(self, ser, cmd, *args):
        """Send @cmd to radio via @ser"""
        with self.LOCK:
            cmd += "".join(args) + ";"

            LOG.debug("PC->RADIO: %s" % cmd.strip())
            ser.write(cmd.encode('cp1252'))

    def __init__(self, *args, **kwargs):
        chirp_common.LiveRadio.__init__(self, *args, **kwargs)
        self._memcache = {}
        self.LOCK = threading.Lock()
        self.LAST_BAUD = self.BAUD_RATE
        self.LAST_DELIMITER = self.COMMAND_DELIMITER

        if self.pipe:
            self.pipe.timeout = 0.1
            self.pipe.baudrate = 4800
            try:
                resp = self.command(self.pipe, "ID")
            except UnicodeDecodeError:
                raise Exception("Radio is likely not %s" % (self.MODEL))
            radio_id = resp.split(";")[0]
            if RADIO_IDS[radio_id] != \
                    self.MODEL.split(" ")[0]:
                raise Exception("Radio reports %s (not %s)" % (radio_id,
                                                               self.MODEL))
            self.command_no_output(self.pipe, "AI", "0")

    def get_features(self):
        rf = chirp_common.RadioFeatures()

        rf.can_odd_split = True

        rf.has_bank = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_name = False
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.memory_bounds = (0, self._upper)

        rf.valid_bands = TS790E_BANDS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC
        rf.valid_duplexes = TS790E_DUPLEX
        rf.valid_modes = list(TS790E_MODES.keys())
        rf.valid_skips = TS790E_SKIP
        rf.valid_tmodes = TS790E_TMODES
        rf.valid_special_chans = list(TS790E_SPECIALS)

        return rf

    def get_memory(self, number):
        if isinstance(number, str):
            number = 50 + TS790E_SPECIALS.index(number)
        if number < 0 or number > (self._upper + len(TS790E_SPECIALS)):
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % (
                    self._upper + len(TS790E_SPECIALS)))
        if number in self._memcache and not NOCACHE:
            return self._memcache[number]

        result = self.command(
            self.pipe, *self._cmd_get_memory(number))
        if result.endswith("00000000000000000") or result.endswith("?"):
            mem = chirp_common.Memory()
            if number >= 30:
                mem.duplex = TS790E_DUPLEX[1]
            if number >= 50:
                mem.extd_number = TS790E_SPECIALS[number - 50]
            mem.number = number
            mem.offset = None
            mem.empty = True
            mem.skip = TS790E_SKIP[0]
            self._memcache[number] = mem
            return mem

        mem = self._parse_mem_spec(result)
        if number >= 30:  # check for split frequency operation
            result = self.command(
                self.pipe, *self._cmd_get_split(number))
            self._parse_split_spec(mem, result)
        self._memcache[number] = mem

        return mem

    def set_memory(self, memory):
        LOG.debug("set_memory(%s)" % repr(memory))
        if memory.extd_number:
            real_number = 50 + TS790E_SPECIALS.index(memory.extd_number)
        else:
            real_number = memory.number
        if real_number < 0 or real_number > (self._upper +
                                             len(TS790E_SPECIALS)):
            raise errors.InvalidMemoryLocation(
                "Number must be between 0 and %i" % (
                    self._upper + len(TS790E_SPECIALS)))

        if memory.extd_number and (memory.extd_number[0] in ["A", "C", "P"]):
            band = get_band(memory.freq)
            supposed_band = int(memory.extd_number[1]) - 1
            if band != supposed_band:
                raise errors.InvalidMemoryLocation(
                        "%s frequency must be between %f and %f " %
                        (memory.extd_number, *TS790E_BANDS[supposed_band]))

        del self._memcache[real_number]

        # If we have a split set the transmit frequency first.
        if real_number >= 30 and memory.offset is not None:
            spec = self._make_base_spec(memory, memory.offset)
            self.command_no_output(
                self.pipe, *self._cmd_set_split(real_number, spec))

        spec = self._make_base_spec(memory, memory.freq)
        self.command_no_output(self.pipe,
                               *self._cmd_set_memory(real_number, spec))

    def erase_memory(self, number):
        if number not in self._memcache and not NOCACHE:
            return
        self.command_no_output(self.pipe, *self._cmd_erase_memory(number))
        del self._memcache[number]

    def _cmd_get_memory(self, number):
        return "MR0 %02i" % number

    def _cmd_get_split(self, number):
        return "MR1 %02i" % number

    def _cmd_set_memory(self, number, spec):
        return "MW0 %02i%s" % (number, spec)

    def _cmd_set_split(self, number, spec):
        return "MW1 %02i%s" % (number, spec)

    def _cmd_erase_memory(self, number):
        return "MW0 %02i%017i" % (number, 0)

    def _parse_mem_spec(self, spec):
        mem = chirp_common.Memory()

        # pad string so indexes match Kenwood docs
        spec = " " + spec   # Param Format Function

        _p3 = spec[5:7]     # P3    7      Memory Channel
        _p4 = spec[7:18]    # P4    4      Frequency
        _p5 = spec[18]      # P5    2      Mode
        _p6 = spec[19]      # P6    10     Memory Lockout
        if len(spec) == 24:
            _p7 = spec[20]      # P7    1      Tone On/Off
            _p8 = spec[21:23]   # P8    14     Tone Frequency
            _p9 = spec[23]      # P9    13     Offset

        if not TS790E_MODES_REV[_p5]:
            return mem
        mem.number = int(_p3)
        mem.duplex = TS790E_DUPLEX[0]
        mem.freq = int(_p4)
        mem.mode = TS790E_MODES_REV[_p5]
        if mem.number < 30 and mem.mode == "FM":
            mem.duplex = TS790E_OFFSETS[int(_p9)]
            if mem.duplex != TS790E_OFFSETS[0]:
                cur_band = get_band(mem.freq)
                mem.offset = TS790E_SHIFTS[cur_band]
            else:
                mem.offset = None

        mem.skip = TS790E_SKIP[int(_p6)]
        if mem.mode == "FM":
            mem.tmode = TS790E_TMODES[int(_p7)]
            if mem.tmode == TS790E_TMODES[1]:
                mem.rtone = TS790E_TONES[int(_p8)-1]
        if mem.number >= 50:
            mem.extd_number = TS790E_SPECIALS[mem.number - 50]
        return mem

    def _parse_split_spec(self, mem, spec):
        split_freq_bytes = spec[7:17]  # P4
        if len(split_freq_bytes) > 0:
            split_freq = int(split_freq_bytes)
            if mem.freq != 0:
                mem.duplex = "split"
                mem.offset = split_freq
        return mem

    def _make_base_spec(self, mem, freq):
        if mem.mode == "FM" \
                and mem.tmode == TS790E_TMODES[1]:
            tmode = "1"
            tone = "%02i" % (TS790E_TONES.index(mem.rtone)+1)
        else:
            tmode = "0"
            tone = "01"
        if not mem.offset or mem.offset not in TS790E_OFFSETS:
            offset = "0"
        else:
            offset = str(TS790E_OFFSETS.index(mem.offset))
        return "%011i%s%i%s%s%s" % (            # P# Format Function
                   freq,                        # P4 4      Frequency
                   TS790E_MODES[mem.mode],      # P5 2      Mode
                   mem.skip == TS790E_SKIP[1],  # P6 10     Memory Lockout
                   tmode,                       # P7 1      Tone On/Off
                   tone,                        # P8 14     Tone Frequency
                   offset)                      # P9 13     Offset
