# Copyright 2013 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# This driver was derived from the:
# Quansheng TG-UV2 Utility by Mike Nix <mnix@wanm.com.au>
# (So thanks Mike!)

import struct
import logging
import serial
from chirp import chirp_common, directory, bitwise, memmap, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
                RadioSettingValueBoolean, RadioSettingValueList, \
                RadioSettingValueInteger, RadioSettingValueFloat, \
                RadioSettingValueMap, RadioSettings

LOG = logging.getLogger(__name__)

mem_format = """
struct memory {
  bbcd freq[4];
  bbcd offset[4];
  u8 rxtone;
  u8 txtone;
  u8 unknown1:2,
     txtmode:2,
     unknown2:2,
     rxtmode:2;
  u8 duplex;
  u8 unknown3:3,
     isnarrow:1,
     unknown4:2,
     not_scramble:1,
     not_revfreq:1;
  u8 flag3;
  u8 step;
  u8 power;
};

struct bandflag {
    u8 scanadd:1,
        unknown1:3,
        band:4;
};

struct tguv2_config {
    u8 unknown1;
    u8 squelch;
    u8 time_out_timer;
    u8 priority_channel;

    u8 unknown2:7,
        keyunlocked:1;
    u8 busy_lockout;
    u8 vox;
    u8 unknown3;

    u8 beep_tone_disabled;
    u8 display;
    u8 step;
    u8 unknown4;

    u8 unknown5;
    u8 rxmode;
    u8 unknown6:7,
        not_end_tone_elim:1;
    u8 vfo_mode;
};

struct vfo {
    u8 current;
    u8 chan;
    u8 memno;
};

struct name {
  u8 name[6];
  u8 unknown1[10];
};

#seekto 0x0000;
char ident[32];
u8 blank[16];

struct memory channels[200];
struct memory bands[5];

#seekto 0x0D30;
struct bandflag bandflags[200];

#seekto 0x0E30;
struct tguv2_config settings;
struct vfo vfos[2];
u8 unk5;
u8 reserved2[9];
u8 band_restrict;
u8 txen350390;

#seekto 0x0F30;
struct name names[200];

"""


def do_program_mode(radio):
    radio.pipe.write(b"\x02PnOGdAM")
    for x in range(10):
        ack = radio.pipe.read(1)
        if ack == b'\x06':
            break
    else:
        raise errors.RadioError("Radio did not ack programming mode")


def do_ident(radio):
    radio.pipe.timeout = 3
    radio.pipe.stopbits = serial.STOPBITS_TWO
    do_program_mode(radio)
    radio.pipe.write(b"\x4D\x02")
    ident = radio.pipe.read(8)
    LOG.debug(util.hexprint(ident))
    if not ident.startswith(b'P5555'):
        LOG.debug("First ident attempt (x4D, x02) failed trying 0x40,x02")
        do_program_mode(radio)
        radio.pipe.write(b"\x40\x02")
        ident = radio.pipe.read(8)
        LOG.debug(util.hexprint(ident))
        if not ident.startswith(b'P5555'):
            raise errors.RadioError("Unsupported model")
    radio.pipe.write(b"\x06")
    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise errors.RadioError("Radio did not ack ident")


def do_status(radio, direction, addr):
    status = chirp_common.Status()
    status.msg = "Cloning %s radio" % direction
    status.cur = addr
    status.max = 0x2000
    radio.status_fn(status)


def do_download(radio):
    do_ident(radio)
    data = b"TG-UV2+ Radio Program Data v1.0\x00"
    data += (b"\x00" * 16)

    firstack = None
    for i in range(0, 0x2000, 8):
        frame = struct.pack(">cHB", b"R", i, 8)
        radio.pipe.write(frame)
        result = radio.pipe.read(12)
        if not (result[0:1] == b"W" and frame[1:4] == result[1:4]):
            LOG.debug(util.hexprint(result))
            raise errors.RadioError("Invalid response for address 0x%04x" % i)
        radio.pipe.write(b"\x06")
        ack = radio.pipe.read(1)
        if not firstack:
            firstack = ack
        else:
            if not ack == firstack:
                LOG.debug("first ack: %s ack received: %s",
                          util.hexprint(firstack), util.hexprint(ack))
                raise errors.RadioError("Unexpected response")
        data += result[4:]
        do_status(radio, "from", i)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    do_ident(radio)
    data = radio._mmap[0x0030:]

    for i in range(0, 0x2000, 8):
        frame = struct.pack(">cHB", b"W", i, 8)
        frame += data[i:i + 8]
        radio.pipe.write(frame)
        ack = radio.pipe.read(1)
        if ack != b"\x06":
            LOG.debug("Radio NAK'd block at address 0x%04x" % i)
            raise errors.RadioError(
                    "Radio NAK'd block at address 0x%04x" % i)
        LOG.debug("Radio ACK'd block at address 0x%04x" % i)
        do_status(radio, "to", i)


DUPLEX = ["", "+", "-"]
TGUV2P_STEPS = [5, 6.25, 10, 12.5, 15, 20, 25, 30, 50, 100]
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_|* +-"
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=10),
                chirp_common.PowerLevel("Med", watts=5),
                chirp_common.PowerLevel("Low", watts=1)]
POWER_LEVELS_STR = ["High", "Med", "Low"]
VALID_BANDS = [(88000000, 108000000),
               (136000000, 174000000),
               (350000000, 390000000),
               (400000000, 470000000),
               (470000000, 520000000)]


@directory.register
class QuanshengTGUV2P(chirp_common.CloneModeRadio,
                      chirp_common.ExperimentalRadio):
    """Quansheng TG-UV2+"""
    VENDOR = "Quansheng"
    MODEL = "TG-UV2+"
    BAUD_RATE = 9600

    _memsize = 0x2000

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('Experimental version for TG-UV2/2+ radios '
             'Proceed at your own risk!')
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Turn radio on.\n"
            "5. Ensure that the radio is tuned to channel with no"
            " activity.\n"
            "6. Click OK to download image from device.\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect cable to mic/spkr connector.\n"
            "3. Make sure connector is firmly connected.\n"
            "4. Turn radio on.\n"
            "5. Ensure that the radio is tuned to channel with no"
            " activity.\n"
            "6. Click OK to upload image to device.\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_duplexes = DUPLEX
        rf.can_odd_split = False
        rf.valid_skips = ["", "S"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 6
        rf.valid_tuning_steps = TGUV2P_STEPS
        rf.valid_bands = VALID_BANDS

        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = POWER_LEVELS
        rf.has_ctone = True
        rf.has_bank = False
        rf.has_tuning_step = True
        rf.memory_bounds = (0, 199)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.channels[number])

    def _decode_tone(self, _mem, which):
        def _get(field):
            return getattr(_mem, "%s%s" % (which, field))

        value = _get('tone')
        tmode = _get('tmode')

        if (value <= 104) and (tmode <= 3):
            if tmode == 0:
                mode = val = pol = None
            elif tmode == 1:
                mode = 'Tone'
                val = chirp_common.TONES[value]
                pol = None
            else:
                mode = 'DTCS'
                val = chirp_common.DTCS_CODES[value]
                pol = "N" if (tmode == 2) else "R"
        else:
            mode = val = pol = None

        return mode, val, pol

    def _encode_tone(self, _mem, which, mode, val, pol):
        def _set(field, value):
            setattr(_mem, "%s%s" % (which, field), value)

        if (mode == "Tone"):
            _set("tone", chirp_common.TONES.index(val))
            _set("tmode", 0x01)
        elif mode == "DTCS":
            _set("tone", chirp_common.DTCS_CODES.index(val))
            if pol == "N":
                _set("tmode", 0x02)
            else:
                _set("tmode", 0x03)
        else:
            _set("tone", 0)
            _set("tmode", 0)

    def _get_memobjs(self, number):
        if isinstance(number, str):
            return (getattr(self._memobj, number.lower()), None)

        else:
            return (self._memobj.channels[number],
                    self._memobj.bandflags[number],
                    self._memobj.names[number].name)

    def get_memory(self, number):
        _mem, _bf, _nam = self._get_memobjs(number)
        mem = chirp_common.Memory()
        if isinstance(number, str):
            mem.extd_number = number
        else:
            mem.number = number

        if ((_mem.freq.get_raw(asbytes=False)[0] == "\xFF") or
                (_bf.band == "\x0F")):
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 10

        if _mem.offset.get_raw(asbytes=False)[0] == "\xFF":
            mem.offset = 0
        else:
            mem.offset = int(_mem.offset) * 10

        chirp_common.split_tone_decode(
            mem,
            self._decode_tone(_mem, "tx"),
            self._decode_tone(_mem, "rx"))

        if 'step' in _mem and _mem.step > len(TGUV2P_STEPS):
            _mem.step = 0x00
        mem.tuning_step = TGUV2P_STEPS[_mem.step]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.mode = _mem.isnarrow and "NFM" or "FM"
        mem.skip = "" if bool(_bf.scanadd) else "S"
        mem.power = POWER_LEVELS[_mem.power]

        if _nam:
            for char in _nam:
                try:
                    mem.name += CHARSET[char]
                except IndexError:
                    break
            mem.name = mem.name.rstrip()

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("not_scramble", "(not)SCRAMBLE",
                          RadioSettingValueBoolean(_mem.not_scramble))
        mem.extra.append(rs)

        rs = RadioSetting("not_revfreq", "(not)Reverse Duplex",
                          RadioSettingValueBoolean(_mem.not_revfreq))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem, _bf, _nam = self._get_memobjs(mem.number)

        _bf.set_raw("\xFF")

        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            return

        _mem.set_raw("\x00" * 12 + "\xFF" * 2 + "\x00"*2)

        _bf.scanadd = int(mem.skip != "S")
        _bf.band = 0x0F
        for idx, ele in enumerate(VALID_BANDS):
            if mem.freq >= ele[0] and mem.freq <= ele[1]:
                _bf.band = idx

        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 10

        tx, rx = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem, 'tx', *tx)
        self._encode_tone(_mem, 'rx', *rx)

        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.isnarrow = mem.mode == "NFM"
        _mem.step = TGUV2P_STEPS.index(mem.tuning_step)

        if mem.power is None:
            _mem.power = 0
        else:
            _mem.power = POWER_LEVELS.index(mem.power)

        if _nam:
            for i in range(0, 6):
                try:
                    _nam[i] = CHARSET.index(mem.name[i])
                except IndexError:
                    _nam[i] = 0xFF

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        _vfoa = self._memobj.vfos[0]
        _vfob = self._memobj.vfos[1]
        _bandsettings = self._memobj.bands

        cfg_grp = RadioSettingGroup("cfg_grp", "Configuration")
        vfoa_grp = RadioSettingGroup(
            "vfoa_grp", "VFO A Settings\n  (Current Status, Read Only)")
        vfob_grp = RadioSettingGroup(
            "vfob_grp", "VFO B Settings\n  (Current Status, Read Only)")

        group = RadioSettings(cfg_grp, vfoa_grp, vfob_grp)
        #
        # Configuration Settings
        #

        # TX time out timer:
        options = ["Off"] + ["%s min" % x for x in range(1, 10)]
        rs = RadioSetting("time_out_timer", "TX Time Out Timer",
                          RadioSettingValueList(
                              options, current_index=_settings.time_out_timer))
        cfg_grp.append(rs)

        # Display mode
        options = ["Frequency", "Channel", "Name"]
        rs = RadioSetting("display", "Channel Display Mode",
                          RadioSettingValueList(
                              options, current_index=_settings.display))
        cfg_grp.append(rs)

        # Squelch level
        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        cfg_grp.append(rs)

        # Vox level
        mem_vals = list(range(10))
        user_options = [str(x) for x in mem_vals]
        user_options[0] = "Off"
        options_map = list(zip(user_options, mem_vals))

        rs = RadioSetting("vox", "VOX Level",
                          RadioSettingValueMap(options_map, _settings.vox))
        cfg_grp.append(rs)

        # Keypad beep
        rs = RadioSetting("beep_tone_disabled", "Beep Prompt",
                          RadioSettingValueBoolean(
                               not _settings.beep_tone_disabled))
        cfg_grp.append(rs)

        # Dual watch/crossband
        options = ["Dual Watch", "CrossBand", "Normal"]
        if _settings.rxmode >= 2:
            _rxmode = 2
        else:
            _rxmode = _settings.rxmode
        rs = RadioSetting("rxmode", "Dual Watch/CrossBand Monitor",
                          RadioSettingValueList(
                            options, current_index=_rxmode))
        cfg_grp.append(rs)

        # Busy channel lock
        rs = RadioSetting("busy_lockout", "Busy Channel Lock",
                          RadioSettingValueBoolean(
                             not _settings.busy_lockout))
        cfg_grp.append(rs)

        # Keypad lock
        rs = RadioSetting("keyunlocked", "Keypad Lock",
                          RadioSettingValueBoolean(
                              not _settings.keyunlocked))
        cfg_grp.append(rs)

        # Priority channel
        mem_vals = list(range(200))
        user_options = [str(x) for x in mem_vals]
        mem_vals.insert(0, 0xFF)
        user_options.insert(0, "Not Set")
        options_map = list(zip(user_options, mem_vals))
        if _settings.priority_channel >= 200:
            _priority_ch = 0xFF
        else:
            _priority_ch = _settings.priority_channel
        rs = RadioSetting(
            "priority_channel",
            "Priority Channel \n"
            "Note: Unused channels,\nor channels "
            "in the\nbroadcast FM band,\nwill not be set",
            RadioSettingValueMap(options_map, _priority_ch))
        cfg_grp.append(rs)

        # Step
        mem_vals = list(range(0, len(TGUV2P_STEPS)))
        mem_vals.append(0xFF)
        user_options = [(str(x) + " kHz") for x in TGUV2P_STEPS]
        user_options.append("Unknown")
        options_map = list(zip(user_options, mem_vals))

        rs = RadioSetting("step", "Current (VFO?) step size",
                          RadioSettingValueMap(options_map, _settings.step))
        cfg_grp.append(rs)

        # End (Tail) tone elimination
        mem_vals = [0, 1]
        user_options = ["Tone Elimination On", "Tone Elimination Off"]
        options_map = list(zip(user_options, mem_vals))

        rs = RadioSetting("not_end_tone_elim", "Tx End Tone Elimination",
                          RadioSettingValueMap(options_map,
                                               _settings.not_end_tone_elim))
        cfg_grp.append(rs)

        # VFO mode

        if _settings.vfo_mode >= 1:
            _vfo_mode = 0xFF
        else:
            _vfo_mode = _settings.vfo_mode
        mem_vals = [0xFF, 0]
        user_options = ["VFO Mode Enabled", "VFO Mode Disabled"]
        options_map = list(zip(user_options, mem_vals))

        rs = RadioSetting("vfo_mode", "VFO (CH only) mode",
                          RadioSettingValueMap(options_map, _vfo_mode))
        cfg_grp.append(rs)

        #
        # VFO Settings
        #

        vfo_groups = [vfoa_grp, vfob_grp]
        vfo_mem = [_vfoa, _vfob]
        vfo_lower = ["vfoa", "vfob"]
        vfo_upper = ["VFOA", "VFOB"]

        for idx, vfo_group in enumerate(vfo_groups):

            options = ["Channel", "Frequency"]
            tempvar = 0 if (vfo_mem[idx].current < 200) else 1
            rs = RadioSetting(vfo_lower[idx] + "_mode", vfo_upper[idx]+" Mode",
                              RadioSettingValueList(
                                  options, current_index=tempvar))
            vfo_group.append(rs)

            if tempvar == 0:
                rs = RadioSetting(vfo_lower[idx] + "_ch",
                                  vfo_upper[idx] + " Channel",
                                  RadioSettingValueInteger(
                                      0, 199, vfo_mem[idx].current))
                vfo_group.append(rs)
            else:
                band_num = vfo_mem[idx].current - 200
                freq = int(_bandsettings[band_num].freq) * 10
                offset = int(_bandsettings[band_num].offset) * 10
                txtmode = _bandsettings[band_num].txtmode
                rxtmode = _bandsettings[band_num].rxtmode

                rs = RadioSetting(vfo_lower[idx] + "_freq",
                                  vfo_upper[idx] + " Frequency",
                                  RadioSettingValueFloat(
                                      0.0, 520.0, freq / 1000000.0,
                                      precision=6))
                vfo_group.append(rs)

                if offset > 70e6:
                    offset = 0
                rs = RadioSetting(vfo_lower[idx] + "_offset",
                                  vfo_upper[idx] + " Offset",
                                  RadioSettingValueFloat(
                                      0.0, 69.995, offset / 100000.0,
                                      resolution=0.005))
                vfo_group.append(rs)

                rs = RadioSetting(
                    vfo_lower[idx] + "_duplex", vfo_upper[idx] + " Shift",
                    RadioSettingValueList(
                        DUPLEX, current_index=_bandsettings[band_num].duplex))
                vfo_group.append(rs)

                rs = RadioSetting(
                    vfo_lower[idx] + "_step",
                    vfo_upper[idx] + " Step",
                    RadioSettingValueFloat(
                        0.0, 1000.0,
                        TGUV2P_STEPS[_bandsettings[band_num].step],
                        resolution=0.25))
                vfo_group.append(rs)

                rs = RadioSetting(
                    vfo_lower[idx] + "_pwr",
                    vfo_upper[idx] + " Power",
                    RadioSettingValueList(
                        POWER_LEVELS_STR,
                        current_index=_bandsettings[band_num].power))
                vfo_group.append(rs)

                options = ["None", "Tone", "DTCS-N", "DTCS-I"]
                rs = RadioSetting(vfo_lower[idx] + "_ttmode",
                                  vfo_upper[idx]+" TX tone mode",
                                  RadioSettingValueList(
                                      options, current_index=txtmode))
                vfo_group.append(rs)
                if txtmode == 1:
                    rs = RadioSetting(
                        vfo_lower[idx] + "_ttone",
                        vfo_upper[idx] + " TX tone",
                        RadioSettingValueFloat(
                            0.0, 1000.0,
                            chirp_common.TONES[_bandsettings[band_num].txtone],
                            resolution=0.1))
                    vfo_group.append(rs)
                elif txtmode >= 2:
                    txtone = _bandsettings[band_num].txtone
                    rs = RadioSetting(
                        vfo_lower[idx] + "_tdtcs",
                        vfo_upper[idx] + " TX DTCS",
                        RadioSettingValueInteger(
                            0, 1000, chirp_common.DTCS_CODES[txtone]))
                    vfo_group.append(rs)

                options = ["None", "Tone", "DTCS-N", "DTCS-I"]
                rs = RadioSetting(vfo_lower[idx] + "_rtmode",
                                  vfo_upper[idx] + " RX tone mode",
                                  RadioSettingValueList(options,
                                                        current_index=rxtmode))
                vfo_group.append(rs)

                if rxtmode == 1:
                    rs = RadioSetting(
                        vfo_lower[idx] + "_rtone",
                        vfo_upper[idx] + " RX tone",
                        RadioSettingValueFloat(
                            0.0, 1000.0,
                            chirp_common.TONES[_bandsettings[band_num].rxtone],
                            resolution=0.1))
                    vfo_group.append(rs)
                elif rxtmode >= 2:
                    rxtone = _bandsettings[band_num].rxtone
                    rs = RadioSetting(vfo_lower[idx] + "_rdtcs",
                                      vfo_upper[idx] + " TX rTCS",
                                      RadioSettingValueInteger(
                                          0, 1000,
                                          chirp_common.DTCS_CODES[rxtone]))
                    vfo_group.append(rs)

                options = ["FM", "NFM"]
                rs = RadioSetting(
                    vfo_lower[idx] + "_fm",
                    vfo_upper[idx] + " FM BW ",
                    RadioSettingValueList(
                        options,
                        current_index=_bandsettings[band_num].isnarrow))
                vfo_group.append(rs)

        return group

    def _validate_priority_ch(self, ch_num):
        if ch_num == 0xFF:
            return True
        _mem, _bf, _nam = self._get_memobjs(ch_num)
        if ((_mem.freq.get_raw(asbytes=False)[0] == "\xFF") or
                (_bf.band == "\x0F")):
            return False
        elif _bf.band == 0x00:
            return False
        else:
            return True

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "vfoa" in element.get_name():
                        continue
                    if "vfob" in element.get_name():
                        continue
                    elif "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("using apply callback")
                        element.run_apply_callback()
                    elif setting == "beep_tone_disabled":
                        LOG.debug("Setting %s = %s" % (setting,
                                                       not int(element.value)))
                        setattr(obj, setting, not int(element.value))
                    elif setting == "busy_lockout":
                        LOG.debug("Setting %s = %s" % (setting,
                                                       not int(element.value)))
                        setattr(obj, setting, not int(element.value))
                    elif setting == "keyunlocked":
                        # keypad currently unlocked being set to locked
                        # and rx_mode is currently not "Normal":
                        if getattr(obj, "keyunlocked") and int(element.value) \
                                and (getattr(obj, "rxmode") != 0x02):
                            raise errors.InvalidValueError(
                                "Keypad lock not allowed in "
                                "Dual-Watch or CrossBand")
                        LOG.debug("Setting %s = %s" % (setting,
                                                       not int(element.value)))
                        setattr(obj, setting, not int(element.value))
                    elif setting == "rxmode":
                        # rx_mode was normal, now being set otherwise
                        # and keypad is locked:
                        if (getattr(obj, "rxmode") == 0x02) \
                                and (int(element.value) != 2) \
                                and not (getattr(obj, "keyunlocked")):
                            raise errors.InvalidValueError(
                                "Dual-Watch or CrossBand can not be set "
                                "when keypad is locked")
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                    elif setting == "priority_channel":
                        _check = self._validate_priority_ch(int(element.value))
                        if _check:
                            LOG.debug("Setting %s = %s" % (setting,
                                                           element.value))
                            setattr(obj, setting, element.value)
                        else:
                            raise errors.InvalidValueError(
                                "Please select a valid priority channel:\n"
                                "A used memory channel which is not "
                                "in the Broadcast FM band (88-108 MHz),\n"
                                "Or select 'Not Used'")
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        return (filedata.startswith(b"TG-UV2+ Radio Program Data") and
                len(filedata) == (cls._memsize + 0x30))
