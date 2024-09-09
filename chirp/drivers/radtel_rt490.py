# Copyright 2023 angeof9 angelof9@protonmail.com
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
# along with this program. If not, see http://www.gnu.org/licenses/.
#
# This file is dual-licensed by the copyright holder, under the GPLv3
# for inclusion in CHIRP here.
# The code is also available under the BSD 2-Clause "Simplified" License
# here:
# https://chirpmyradio.com/attachments/7833

#  Python3 byte clean by Darryl Pogue
#  Pep8 style compliant by Jim Unroe <rock.unroe@gmail.com>

import logging
import struct

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)

from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
    RadioSettingValueMap,
    RadioSettingValueFloat,
    InvalidValueError
)

LOG = logging.getLogger(__name__)

# 'True' or 'False'
# True unlocks:
# - FM preset
# - Channel memory  # preset
# - Killswitch (with revive killed radios)
# - Bands settings
# - Disable radio identification string verification
#   (good to recover from a bad state)
RT490_EXPERIMENTAL = True

MEM_FORMAT_RT490 = """
struct {                    // Memory settings
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 signal;                // int 0->14, Signal 1->15
  u8 pttid;                 // ['OFF', 'BOT', 'EOT', 'Both']
  u8 dcp:4,                 // What is DCP ? FHSS ? DC-FHSS ??? TODO
     power:4;               // POWER_LEVELS
  u8 unknown3_0:1,          // Used by the driver to store AM/NAM flag
                            // (thank you Radtel for free space)
     narrow:1,              // bool true=NFM false=FM (col[7] a)
     unknown3_1:1,
     unknown3_2:1,
     bcl:1,                 // bool (col[9] a2)
     scan:1,                // bool (col[10] a3)
     tx_enable:1,           // bool (col[1] a4)
     learn:1;               // bool ??? TODO (col[14] a5)
} memory[%(memsize)d];
// #seekto 0x1000;          // Memory names (@4096)
struct {
  char name[12];
  u8 ffpad[4];
} memname[%(memsize)d];
// #seekto 0x2000;          // GOOD DCP keys ??? TODO ?? (@8192)
struct {
  u8 code[4];
} memcode[%(memsize)d];     // up to @x2400
                            // Filled with xFF during download (=> no need to
                            // fill with xFF), ready to upload
#seekto 0x3400;             // Custom ANI Names (@13312)
struct {
  char name[10];
  u8 ffpad[6];
} custom_ani_names[10];
                            // Filled with xFF during download (=> no need to
                            // fill with xFF), ready to upload
#seekto 0x3500;             // ANI Codes (@13568)
struct {
  u8 anicode[6];
  u8 ffpad[10];
} anicodes[60];
                            // Filled with xFF during download (=> no need to
                            // fill with xFF), ready to upload
#seekto 0x3900;             // Custom channel names (@14592)
struct {
  char name[10];
  u8 ffpad[6];
} custom_channel_names[10];
                            // Filled with xFF during download (=> no need to
                            // fill with xFF), ready to upload
#seekto 0x3A00;             // Settings (@14848)
struct {
  u8 squelch;               // 0: int 0 -> 9
  u8 savemode;              // 1: ['OFF', 'Normal', 'Super', 'Deep']
  u8 vox;                   // 2: off=0, 1 -> 9
  u8 backlight;             // 3: ['OFF', '5s', '15s', '20s', '30s', '1m',
                            //     '2m', '3m']
  u8 tdr;                   // 4: bool
  u8 timeout;               // 5: n*30seconds, 0-240s
  u8 beep;                  // 6: bool
  u8 voice;                 // 7: bool
  u8 byte_not_used_10;      // 8: Always 1
  u8 dtmfst;                // 9: ['OFF', 'KB Side Tone', 'ANI Side Tone',
                            //     'KB ST + ANI ST']
  u8 scanmode;              // 10: ['TO', 'CO', 'SE']
  u8 pttid;                 // 11: ['OFF', 'BOT', 'EOT', 'Both']
  u8 pttiddelay;            // 12: ['0', '100ms', '200ms', '400ms', '600ms',
                            //      '800ms', '1000ms']
  u8 cha_disp;              // 13: ['Name', 'Freq', 'Channel ID']
  u8 chb_disp;              // 14: ['Name', 'Freq', 'Channel ID']
  u8 bcl;                   // 15: bool
  u8 autolock;              // 0: ['OFF', '5s', '10s', 15s']
  u8 alarm_mode;            // 1: ['Site', 'Tone', 'Code']
  u8 alarmsound;            // 2: bool
  u8 txundertdr;            // 3: ['OFF', 'A', 'B']
  u8 tailnoiseclear;        // 4: [off, on]
  u8 rptnoiseclear;         // 5: n*100ms, 0-1000
  u8 rptnoisedelay;         // 6: n*100ms, 0-1000
  u8 roger;                 // 7: bool
  u8 active_channel;        // 8: 0 or 1
  u8 fmradio;               // 9: boolean, inverted
  u8 workmodeb:4,           // 10:up    ['VFO', 'CH Mode']
     workmodea:4;           // 10:down  ['VFO', 'CH Mode']
  u8 kblock;                // 11: bool              // TODO TEST WITH autolock
  u8 powermsg;              // 12: 0=Image / 1=Voltage
  u8 byte_not_used_21;      // 13: Always 0
  u8 rpttone;               // 14: ['1000Hz', '1450Hz', '1750Hz', '2100Hz']
  u8 byte_not_used_22;      // 15: pad with xFF
  u8 vox_delay;             // 0: [str(float(a)/10)+'s' for a in range(5,21)]
                            //     '0.5s' to '2.0s'
  u8 timer_menu_quit;       // 1: ['5s', '10s', '15s', '20s', '25s', '30s',
                            //     '35s', '40s', '45s', '50s', '60s']
  u8 byte_not_used_30;      // 2: pad with xFF
  u8 byte_not_used_31;      // 3: pad with xFF
  u8 enable_killsw;         // 4: bool
  u8 display_ani;           // 5: bool
  u8 byte_not_used_32;      // 6: pad with xFF
  u8 enable_gps;            // 7: bool
  u8 scan_dcs;              // 8: ['All', 'Receive', 'Transmit']
  u8 ani_id;                // 9: int 0-59 (ANI 1-60)
  u8 rx_time;               // 10: bool
  u8 ffpad0[5];             // 11: Pad xFF
  u8 cha_memidx;            // 0: Memory index when channel A use memories
  u8 byte_not_used_40;
  u8 chb_memidx;            // 2: Memory index when channel B use memories
  u8 byte_not_used_41;
  u8 ffpad1[10];
  ul16 fmpreset;
} settings;
                            // Filled with xFF during download (=> no need to
                            // fill with xFF), ready to upload
struct settings_vfo_chan {
  u8   rxfreq[8];           // 0
  ul16 rxtone;              // 8
  ul16 txtone;              // 10
  ul16 byte_not_used0;      // 12 Pad xFF
  u8   sftd:4,              // 14 Shift dir ['OFF', '+', '-']
       signal:4;            // 14 int 0->14, Signal 1->15
  u8   byte_not_used1;      // 15 Pad xFF
  u8   power;               // 16:0 POWER_LEVELS
  u8   fhss:4,              // 17 ['OFF', 'FHSS 1', 'FHSS 2', 'FHSS 3',
                            //     'FHSS 4']
       narrow:4;            // 17 bool true=NFM false=FM
  u8   byte_not_used2;      // 18 Pad xFF but received 0x00 ???
  u8   freqstep;            // 19:3 ['2.5 KHz', '5.0 KHz', '6.25 KHz',
                            //       '10.0 KHz', '12.5 KHz', '20.0 KHz',
                            //       '25.0 KHz', '50.0 KHz']
  u8   byte_not_used3;      // 20:4 Pad xFF but received 0x00 ??? TODO
  u8   offset[6];           // 21:5 Freq NN.NNNN (without the dot) TEST TEST
  u8   byte_not_used4;      // 27:11   Pad xFF
  u8   byte_not_used5;      // 28      Pad xFF
  u8   byte_not_used6;      // 29      Pad xFF
  u8   byte_not_used7;      // 30      Pad xFF
  u8   byte_not_used8;      // 31:15   Pad xFF
};
// #seekto 0x3A40;          // VFO A/B (@14912)
struct {
  struct settings_vfo_chan vfo_a;
  struct settings_vfo_chan vfo_b;
} settings_vfo;
// #seekto 0x3A80;          // Side keys settings (@14976)
struct {                    // Values from Radio
  u8 pf2_short;             // { '7': 'FM', '10': 'Tx Power', '28': 'Scan',
                            //  '29': 'Search, '1': 'PPT B' }
  u8 pf2_long;              // { '7': 'FM', '10': 'Tx Power', '28': 'Scan',
                            //  '29': 'Search' }
  u8 pf3_short;             // {'7': 'FM', '10': 'Tx Power', '28': 'Scan',
                            //  '29': 'Search'}
  u8 ffpad;                 // Pad xFF
} settings_sidekeys;
struct dtmfcode {
  u8 code[5];               // 5 digits DTMF
  u8 ffpad[11];             // Pad xFF
};
                            // Filled with xFF during download (=> no need to
                            // fill with xFF), ready to upload
#seekto 0x3B00;             // DTMF (@15104)
struct dtmfcode settings_dtmfgroup[15];
struct {                    // @15296+3x16
  u8 byte_not_used1;        // 0: Pad xFF something here
  u8 byte_not_used2;        // 1: Pad xFF something here
  u8 byte_not_used3;        // 2: Pad xFF something here
  u8 byte_not_used4;        // 3: Pad xFF
  u8 byte_not_used5;        // 4: Pad xFF
  u8 unknown_dtmf;          // 5: 0 TODO ???? wtf is alarmcode/alarmcall TODO
  u8 pttid;                 // 6: [off, BOT, EOT, Both]
  u8 dtmf_speed_on;         // 7: ['50ms', '100ms', '200ms', '300ms', '500ms']
  u8 dtmf_speed_off;        // 8:0 ['50ms', '100ms', '200ms', '300ms', '500ms']
} settings_dtmf;
                            // Filled with xFF during download (=> no need to
                            // fill with xFF), ready to upload
#seekto 0x3C00;             // DTMF Kill/ReLive Codes (@15360)
struct {
  u8 kill_dtmf[6];          // 0: Kill DTMF
  u8 ffpad1[2];             // Pad xFF
  u8 revive_dtmf[6];        // 8: Revive DTMF
  u8 ffpad2[2];             // Pad xFF
} settings_killswitch;
                            // Some unknown data between 0x3E00 and 0x3F00
#seekto 0x3F80;             // Hmm hmm
struct {
  u8 unknown_data_0[16];
  u8 unknown_data_1;
  u8 active;                // Bool radio killed (killed=0, active=1)
  u8 unknown_data_2[46];
} management_settings;
struct band {
  u8 enable;                // 0 bool / enable-disable Tx on band
  bbcd freq_low[2];         // 1 lowest band frequency
  bbcd freq_high[2];        // 3 highest band frequency
};
// #seekto 0x3FC0;          // Bands settings (@16320)
struct {
  struct band band136;      // 0  Settings for 136MHz band
  struct band band400;      // 5  Settings for 400MHz band
  struct band band200;      // 10 Settings for 200MHz band
  u8 byte_not_used1;        // 15
  struct band band350;      // 0  Settings for 350MHz band
  u8 byte_not_used2[43];    // 5
} settings_bands;
"""

CMD_ACK = b"\x06"

DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

DTMFCHARS = '0123456789ABCD*#'


def _enter_programming_mode(radio):
    serial = radio.pipe

    exito = False
    for i in range(0, 5):
        serial.write(radio._magic)
        ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except Exception:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    try:
        serial.write(b"F")
        ident = serial.read(8)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if not ident.startswith(radio._fingerprint) and not RT490_EXPERIMENTAL:
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"R" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]
    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except Exception:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE):
            status.cur = addr + radio.BLOCK_SIZE
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE)

    _exit_programming_mode(radio)


@directory.register
class RT490Radio(chirp_common.CloneModeRadio):
    """RADTEL RT-490"""
    VENDOR = "Radtel"
    MODEL = "RT-490"
    BLOCK_SIZE = 0x40  # 64 bytes
    BAUD_RATE = 9600

    POWER_LEVELS = [chirp_common.PowerLevel("H", watts=5.00),
                    chirp_common.PowerLevel("L", watts=3.00)]

    # magic = progmode + modelType + garbage (works with any last char)
    _magic = b"PROGROMJJCCU"

    # fingerprint is default band ranges of the radio
    # the driver can change band ranges and fingerprint will
    # change accordingly, so it is not used to verify radio id.
    _fingerprint = b"\x01\x36\x01\x80\x04\x00\x05\x20"

    # Ranges of memory used when uploading data to radio
    # same as official software
    _ranges = [
               (0x0000, 0x2400),
               (0x3400, 0x3C40),
               (0x3FC0, 0x4000)
              ]

    _valid_chars = chirp_common.CHARSET_ALPHANUMERIC + \
        "`~!@#$%^&*()-=_+[]\\{}|;':\",./<>?"

    if RT490_EXPERIMENTAL:
        # Experimental driver (already heavily tested)
        _ranges = [(0x0000, 0x2400), (0x3400, 0x3C40), (0x3F80, 0x4000)]

    # Danger zone
    # _ranges = [(0x0000, 0x2500), (0x3400, 0x3C40), (0x3E00, 0x4000)]

    # 16KB of memory, download read everything
    # same as official software (remark: loops if overread :))
    _memsize = 16384

    POWER_LEVELS_LIST = [str(i) for i in POWER_LEVELS]
    FHSS_LIST = ['OFF', 'ENCRYPT 1', 'ENCRYPT 2', 'ENCRYPT 3', 'ENCRYPT 4']
    DCP_LIST = ['OFF', 'DCP1', 'DCP2', 'DCP3', 'DCP4']  # Same as FHSS ?
    #                                                   # Seems yes
    TUNING_STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
    TUNING_STEPS_LIST = [str(i)+' KHz' for i in TUNING_STEPS]
    SIGNAL = [str(i) for i in range(1, 16)]
    PTTID = ['OFF', 'BOT', 'EOT', 'Both']
    PTTIDDELAYS = ['0', '100ms', '200ms', '400ms', '600ms', '800ms', '1000ms']
    DTMF_SPEEDS = ['50ms', '100ms', '200ms', '300ms', '500ms']
    SIDEKEY_VALUEMAP = [('FM', 7), ('Tx Power', 10), ('Scan', 28),
                        ('Search', 29), ('PTT B', 1)]
    KEY_CHARS = '0123456789ABCDEF'
    FULL_CHARSET_ASCII = ("".join([chr(x) for x in range(ord(" "),
                          ord("~") + 1)] + [chr(x) for x in range(128, 255)] +
                              [chr(0)]))
    VFO_SFTD = ['OFF', '+', '-']
    WORKMODES = ['VFO', 'Memory Mode']
    SAVEMODES = ['OFF', 'Normal', 'Super', 'Deep']
    DISPLAYMODES = ['Name', 'Freq', 'Memory ID']
    SCANMODES = ['TO', 'CO', 'SE']
    ALARMMODES = ['On Site', 'Send Sound', 'Send Code']
    TDRTXMODES = ['OFF', 'A', 'B']
    SCANDCSMODES = ['All', 'Receive', 'Transmit']
    POWERMESSAGES = ['Image', 'Voltage']
    FMRADIO = ['ON', 'OFF']
    ENABLERADIO = ['Killed', 'Active']
    CHANNELS = ['A', 'B']
    TOT_LIST = ['OFF'] + [str(i*30) + "s" for i in range(1, 9)]
    VOX_LIST = ['OFF'] + [str(i) for i in range(1, 9)]
    BACKLIGHT_TO = ['OFF', '5s', '10s', '15s', '20s', '30s', '1m', '2m', '3m']
    AUTOLOCK_TO = ['OFF', '5s', '10s', '15s']
    MENUEXIT_TO = ['5s', '10s', '15s', '20s', '25s', '30s', '35s', '40s',
                   '45s', '50s', '60s']
    SQUELCHLVLS = [str(i) for i in range(10)]
    ANI_IDS = [str(i+1) for i in range(60)]
    VOXDELAYLIST = [str(float(a)/10)+'s' for a in range(5, 21)]
    DTMFSTLIST = ['OFF', 'DT Side Tone', 'ANI Side Tone', 'DT ST + ANI ST']
    RPTTONES = ['1000Hz', '1450Hz', '1750Hz', '2100Hz']
    RPTNOISE = [str(a)+'s' for a in range(11)]
    _memory_size = _upper = 256  # Number of memory slots
    _mem_params = (_upper-1)
    _frs = _murs = _pmr = _gmrs = True

    @classmethod
    def match_model(cls, filedata, filename):
        return False

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                self._set_setting(element)

    def _set_setting(self, setting):  # WIP
        _mem = self._memobj
        key = setting.get_name()
        val = setting.value
        if key.startswith('dummy'):
            return
        elif key.startswith('settings_dtmfgroup.'):
            if str(val) == "":
                setattr(_mem.settings_dtmfgroup[int(key.split('@')[1])-1],
                        'code', [0xFF]*5)
            else:
                tmp = [DTMFCHARS.index(c) for c in str(val)]
                tmp += [0xFF] * (5 - len(tmp))
                setattr(_mem.settings_dtmfgroup[int(key.split('@')[1])-1],
                        'code', tmp)
        elif key.startswith('settings.'):
            if key.endswith('_memidx'):
                val = int(val) - 1
            if key.endswith('fmpreset'):
                tmp = val.get_value() * 10
                setattr(_mem.settings, key.split('.')[1], tmp)
            else:
                setattr(_mem.settings, key.split('.')[1], int(val))
        elif key.startswith('settings_dtmf.'):
            attr = key.split('.')[1]
            setattr(_mem.settings_dtmf, attr, int(val))
            if attr.startswith('pttid'):
                setattr(_mem.settings, attr, int(val))
        elif key.startswith('settings_sidekeys.'):
            setattr(_mem.settings_sidekeys, key.split('.')[1], int(val))
        elif key.startswith('settings_vfo.'):  # TODO rx/tx tones
            tmp = key.split('.')
            attr = tmp[2]
            vfo = tmp[1]
            # LOG.debug(">>> PRE key '%s'" % key)
            # LOG.debug(">>> PRE val '%s'" % val)
            if attr.startswith('rxfreq'):
                value = chirp_common.parse_freq(str(val)) / 10
                for i in range(7, -1, -1):
                    _mem.settings_vfo[vfo].rxfreq[i] = value % 10
                    value /= 10
            elif attr.startswith('offset'):
                value = int(float(str(val)) * 10000)
                for i in range(5, -1, -1):
                    _mem.settings_vfo[vfo].offset[i] = value % 10
                    value /= 10
            else:
                setattr(_mem.settings_vfo[vfo], attr, int(val))
        elif key.startswith('settings_bands.'):
            tmp = key.split('.')
            attr = tmp[2]
            band = tmp[1]
            setattr(_mem.settings_bands[band], attr, int(val))
        elif key.startswith('settings_killswitch.'):
            attr = key.split('.')[1]
            if attr.endswith('dtmf'):
                if str(val) == "":
                    setattr(_mem.settings_killswitch, attr,
                            [0x01, 0x02, 0x01, 0x03, 0x01, 0x04])
                else:
                    setattr(_mem.settings_killswitch, attr,
                            [DTMFCHARS.index(c) for c in str(val)])
            elif attr.startswith('enable'):
                setattr(_mem.settings_killswitch, attr, int(val))
            else:
                LOG.debug(">>> TODO key '%s'" % key)
                LOG.debug(">>> TODO val '%s'" % val)
        elif key.startswith('custom_') or key.startswith('anicode') \
                or key.startswith('memcode'):
            tmp = key.split('@')
            if key.startswith('anicode'):
                val = [DTMFCHARS.index(c) for c in str(val)]
                val += [0xFF] * (6 - len(val))
                for i in range(10):
                    _mem[str(tmp[0])][int(tmp[2])]["ffpad"][i] = 0xFF
            elif key.startswith('memcode'):
                if len(str(val)) > 0:
                    tmpp = str(val).zfill(6)
                    val = self._encode_key(tmpp)
                else:
                    val = (0xFF, 0xFF, 0xFF, 0xFF)
            if key.startswith('custom_'):
                for i in range(6):
                    _mem[str(tmp[0])][int(tmp[2])]["ffpad"][i] = 0xFF
            setattr(_mem[str(tmp[0])][int(tmp[2])], str(tmp[1]), val)
        elif key.startswith('management_settings'):
            setattr(_mem.management_settings, key.split('.')[1], int(val))
        else:
            LOG.debug(">>> TODO _set_setting key '%s'" % key)
            LOG.debug(">>> TODO _set_setting val '%s'" % val)

    def _get_settings_bands(self):
        _mem = self._memobj
        ret = RadioSettingGroup('bands', 'Bands')
        bands = [('136', _mem.settings_bands.band136),
                 ('200', _mem.settings_bands.band200),
                 ('350', _mem.settings_bands.band350),
                 ('400', _mem.settings_bands.band400)]
        for label, band in bands:
            rs = RadioSetting('settings_bands.band%s.enable' % label,
                              'Enable Band %s' % label,
                              RadioSettingValueBoolean(band.enable))
            ret.append(rs)
            rsi = RadioSettingValueInteger(1, 1000, band.freq_low)
            # if label == '136' or label == '400':
            #     rsi.set_mutable(False)
            rs = RadioSetting("settings_bands.band%s.freq_low" % label,
                              "Band %s Lower Limit (MHz) (EXPERIMENTAL)"
                              % label, rsi)
            ret.append(rs)
            rsi = RadioSettingValueInteger(1, 1000, band.freq_high)
            # if label == '350':
            #     rsi.set_mutable(False)
            rs = RadioSetting("settings_bands.band%s.freq_high" % label,
                              "Band %s Upper Limit (MHz) (EXPERIMENTAL)"
                              % label, rsi)
            ret.append(rs)
        return ret

    def _get_settings_ks(self):
        _mem = self._memobj
        ret = RadioSettingGroup('killswitch', 'Killswitch')
        # Kill Enable/Disable enable_killsw
        rsvb = RadioSettingValueBoolean(_mem.settings.enable_killsw)
        ret.append(RadioSetting('settings.enable_killsw',
                                'Enable Killswitch', rsvb))
        # Kill DTMF
        cur = ''.join(
            DTMFCHARS[i]
            for i in _mem.settings_killswitch.kill_dtmf if int(i) < 0xF)
        ret.append(
            RadioSetting('settings_killswitch.kill_dtmf', 'DTMF Kill',
                         RadioSettingValueString(6, 6, cur,
                                                 autopad=False,
                                                 charset=DTMFCHARS)))
        # Revive DTMF
        cur = ''.join(
            DTMFCHARS[i]
            for i in _mem.settings_killswitch.revive_dtmf if int(i) < 0xF)
        ret.append(
            RadioSetting('settings_killswitch.revive_dtmf', 'DTMF Revive',
                         RadioSettingValueString(6, 6, cur,
                                                 autopad=False,
                                                 charset=DTMFCHARS)))
        # Enable/Disable entire radio
        rs = RadioSettingValueString(0, 255, "Can be used to revive radio")
        rs.set_mutable(False)
        ret.append(RadioSetting('dummy', 'Factory reserved', rs))
        tmp = 1 if int(_mem.management_settings.active) > 0 else 0
        ret.append(RadioSetting('management_settings.active', 'Radio Status',
                                RadioSettingValueList(self.ENABLERADIO,
                                                      current_index=tmp)))
        return ret

    def _get_settings_dtmf(self):
        _mem = self._memobj
        dtmf = RadioSettingGroup('dtmf', 'DTMF')
        # DTMF Group
        msgs = ["Allowed chars (%s)" % DTMFCHARS,
                "Input from 0 to 5 characters."
                ]
        for msg in msgs:
            rsvs = RadioSettingValueString(0, 255, msg, autopad=False)
            rsvs.set_mutable(False)
            rs = RadioSetting('dummy_dtmf_msg_%i' % msgs.index(msg),
                              'Input rule %i' % int(msgs.index(msg)+1), rsvs)
            dtmf.append(rs)
        for i in range(1, 16):
            cur = ''.join(
                DTMFCHARS[i]
                for i in _mem.settings_dtmfgroup[i - 1].code if int(i) < 0xF)
            dtmf.append(
                RadioSetting(
                    'settings_dtmfgroup.code@%i' % i, 'PTT ID Code %i' % i,
                    RadioSettingValueString(0, 5, cur,
                                            autopad=False,
                                            charset=DTMFCHARS)))
        # DTMF Speed (on time in ms)
        dtmf_speed_on = int(_mem.settings_dtmf.dtmf_speed_on)
        if dtmf_speed_on > len(self.DTMF_SPEEDS)-1:
            _mem.settings_dtmf.dtmf_speed_on = 0
            LOG.debug('DTMF Speed On overflow')
        cur = self.DTMF_SPEEDS[dtmf_speed_on]
        dtmf.append(
            RadioSetting(
                'settings_dtmf.dtmf_speed_on', 'DTMF Speed (on time in ms)',
                RadioSettingValueList(self.DTMF_SPEEDS, cur)))
        # DTMF Speed (on time in ms)
        dtmf_speed_off = int(_mem.settings_dtmf.dtmf_speed_off)
        if dtmf_speed_off > len(self.DTMF_SPEEDS)-1:
            _mem.settings_dtmf.dtmf_speed_off = 0
            LOG.debug('DTMF Speed Off overflow')
        cur = self.DTMF_SPEEDS[dtmf_speed_off]
        dtmf.append(
            RadioSetting(
                'settings_dtmf.dtmf_speed_off', 'DTMF Speed (off time in ms)',
                RadioSettingValueList(self.DTMF_SPEEDS, cur)))
        # PTT ID
        pttid = int(_mem.settings_dtmf.pttid)
        if pttid > len(self.PTTID)-1:
            _mem.settings_dtmf.pttid = 0
            LOG.debug('PTT ID overflow')
        cur = self.PTTID[pttid]
        dtmf.append(
            RadioSetting(
                'settings_dtmf.pttid', 'Send DTMF Code (PTT ID)',
                RadioSettingValueList(self.PTTID, cur)))
        # PTT ID Delay
        pttiddelay = int(_mem.settings.pttiddelay)
        if pttiddelay > len(self.PTTIDDELAYS)-1:
            _mem.settings.pttiddelay = 0
            LOG.debug('PTT ID  Delay overflow')
        cur = self.PTTIDDELAYS[pttiddelay]
        rsvl = RadioSettingValueList(self.PTTIDDELAYS, cur)
        dtmf.append(RadioSetting('settings.pttiddelay',
                    'PTT ID Delay', rsvl))
        rsvl = RadioSettingValueList(self.DTMFSTLIST,
                                     current_index=_mem.settings.dtmfst)
        dtmf.append(RadioSetting('settings.dtmfst',
                                 'DTMF Side Tone (Required for GPS ID)', rsvl))
        return dtmf

    def _get_settings_sidekeys(self):
        _mem = self._memobj
        ret = RadioSettingGroup('sidekeys', 'Side Keys')
        rsvm = RadioSettingValueMap(self.SIDEKEY_VALUEMAP,
                                    _mem.settings_sidekeys.pf2_short)
        ret.append(RadioSetting('settings_sidekeys.pf2_short',
                                'Side key 1 (PTT2) Short press', rsvm))
        rsvm = RadioSettingValueMap(self.SIDEKEY_VALUEMAP[:-1],
                                    _mem.settings_sidekeys.pf2_long)
        ret.append(RadioSetting('settings_sidekeys.pf2_long',
                                'Side key 1 (PTT2) Long press', rsvm))
        rsvm = RadioSettingValueMap(self.SIDEKEY_VALUEMAP[:-1],
                                    _mem.settings_sidekeys.pf3_short)
        ret.append(RadioSetting('settings_sidekeys.pf3_short',
                                'Side key 2 (PTT3) Short press', rsvm))
        rs = RadioSettingValueString(0, 255, "MONI")
        rs.set_mutable(False)
        ret.append(RadioSetting('dummy', 'Side key 2 (PTT3) Long press', rs))
        return ret

    def _get_settings_vfo(self, vfo, chan):  # WIP TODO Rx/Tx tones
        _mem = self._memobj
        ret = RadioSettingGroup('settings_vfo@%s' % chan.lower(),
                                'VFO %s Settings' % chan)
        rsvl = RadioSettingValueList(self.WORKMODES,
                                     current_index=_mem.settings[
                                         'workmode'+chan.lower()])
        ret.append(RadioSetting('settings.workmode%s' % chan.lower(),
                                'VFO %s Workmode' % chan, rsvl))
        tmp = ''.join(DTMFCHARS[i] for i in _mem.settings_vfo[
                      'vfo_'+chan.lower()].rxfreq if i < 0xFF)
        rsvf = RadioSettingValueFloat(66, 550, chirp_common.format_freq(
                                      int(tmp) * 10), resolution=0.00001,
                                      precision=5)
        ret.append(RadioSetting('settings_vfo.vfo_%s.rxfreq' % chan.lower(),
                                'Rx Frequency', rsvf))
        # TODO Rx/Tx tones
        rsvl = RadioSettingValueList(self.VFO_SFTD,
                                     current_index=_mem.settings_vfo[
                                         'vfo_'+chan.lower()].sftd)
        ret.append(RadioSetting('settings_vfo.vfo_%s.sftd' % chan.lower(),
                                'Freq offset direction', rsvl))
        tmp = ''.join(DTMFCHARS[i] for i in _mem.settings_vfo[
                      'vfo_'+chan.lower()].offset if i < 0xFF)
        rsvf = RadioSettingValueFloat(0, 99.9999, float(tmp) / 10000)
        ret.append(RadioSetting('settings_vfo.vfo_%s.offset' % chan.lower(),
                                'Tx Offset', rsvf))
        rsvl = RadioSettingValueList(self.SIGNAL,
                                     current_index=_mem.settings_vfo[
                                             'vfo_'+chan.lower()].signal)
        ret.append(RadioSetting('settings_vfo.vfo_%s.signal' % chan.lower(),
                                'PTT ID Code (S-Code)', rsvl))
        rsvl = RadioSettingValueList(self.POWER_LEVELS_LIST,
                                     current_index=_mem.settings_vfo[
                                             'vfo_'+chan.lower()].power)
        ret.append(RadioSetting('settings_vfo.vfo_%s.power' % chan.lower(),
                                'Tx Power', rsvl))
        rsvl = RadioSettingValueList(self.FHSS_LIST,
                                     current_index=_mem.settings_vfo[
                                             'vfo_'+chan.lower()].fhss)
        ret.append(RadioSetting('settings_vfo.vfo_%s.fhss' % chan.lower(),
                                'FHSS (Encryption)', rsvl))
        chanwidth = ['Wide', 'Narrow']
        rsvl = RadioSettingValueList(
            chanwidth,
            int(bool(_mem.settings_vfo['vfo_'+chan.lower()].narrow)))
        ret.append(RadioSetting('settings_vfo.vfo_%s.narrow' % chan.lower(),
                                'Wide / Narrow', rsvl))
        rsvl = RadioSettingValueList(self.TUNING_STEPS_LIST,
                                     current_index=_mem.settings_vfo[
                                             'vfo_'+chan.lower()].freqstep)
        ret.append(RadioSetting('settings_vfo.vfo_%s.freqstep' % chan.lower(),
                                'Tuning Step', rsvl))
        return ret

    def _get_custom_channel_names(self):
        _mem = self._memobj
        ret = RadioSettingGroup('ccn', 'Custom Channel Names')
        msgs = ["Add custom chan names to radio",
                "-> Menu 09 CH-NAME",
                "Allowed chars (ASCII only)",
                "Input from 0 to 10 characters."
                ]
        for msg in msgs:
            rsvs = RadioSettingValueString(0, 255, msg, autopad=False)
            rsvs.set_mutable(False)
            rs = RadioSetting('dummy_cnames_msg_%i' % msgs.index(msg),
                              'Input rule %i' % int(msgs.index(msg)+1), rsvs)
            ret.append(rs)
        for i in range(0, len(_mem.custom_channel_names)):
            tmp = ''.join([str(j) for j in _mem.custom_channel_names[i].name
                           if ord(str(j)) < 0xFF and ord(str(j)) > 0x00])
            rsvs = RadioSettingValueString(0, 10, tmp, autopad=True,
                                           charset=self.FULL_CHARSET_ASCII)
            ret.append(RadioSetting('custom_channel_names@name@%i' % i,
                                    'Custom Channel Name (%i)' % i, rsvs))
        return ret

    def _get_custom_ani_names(self):
        _mem = self._memobj
        ret = RadioSettingGroup('can', 'Custom ANI Names')
        msgs = ["Can be used as radio id in GPS.",
                "Allowed chars (ASCII only)",
                "Input from 0 to 10 characters."
                ]
        for msg in msgs:
            rsvs = RadioSettingValueString(0, 255, msg, autopad=False)
            rsvs.set_mutable(False)
            rs = RadioSetting('dummy_caninames_msg_%i' % msgs.index(msg),
                              'Input rule %i' % int(msgs.index(msg)+1), rsvs)
            ret.append(rs)
        for i in range(0, len(_mem.custom_ani_names)):
            tmp = ''.join([str(j) for j in
                           _mem.custom_ani_names[i].name
                           if ord(str(j)) < 0xFF and ord(str(j)) > 0x00])
            rsvs = RadioSettingValueString(0, 10, tmp, autopad=True,
                                           charset=self.FULL_CHARSET_ASCII)
            ret.append(RadioSetting('custom_ani_names@name@%i' % i,
                                    'Custom ANI Name (%i)' % (i+51), rsvs))
        return ret

    def _get_anicodes(self):
        _mem = self._memobj
        ret = RadioSettingGroup('ani', 'ANI Codes')
        split = len(_mem.anicodes) - len(_mem.custom_ani_names)
        msgs = ["Allowed chars (%s)" % DTMFCHARS,
                "Input from 0 to 6 characters."
                ]
        for msg in msgs:
            rsvs = RadioSettingValueString(0, 255, msg, autopad=False)
            rsvs.set_mutable(False)
            rs = RadioSetting('dummy_canic_msg_%i' % msgs.index(msg),
                              'Input rule %i' % int(msgs.index(msg)+1), rsvs)
            ret.append(rs)

        for i in range(0, split):
            tmp = ''.join([DTMFCHARS[int(j)] for j in
                           _mem.anicodes[i].anicode if int(j) < 0xFF])
            # LOG.debug("ANI Code (%i) '%s'" % (i, tmp))
            rsvs = RadioSettingValueString(0, 6, tmp, autopad=False,
                                           charset=DTMFCHARS)
            ret.append(RadioSetting('anicodes@anicode@%i' % i,
                                    'ANI-ID (%i) Code' % (i+1), rsvs))
        for i in range(split, len(_mem.anicodes)):
            tmp = ''.join([DTMFCHARS[int(j)] for j in
                          _mem.anicodes[i].anicode if int(j) < 0xFF])
            tmp2 = ''.join([str(j) for j in
                            _mem.custom_ani_names[i-split].name
                            if ord(str(j)) < 0xFF and ord(str(j)) > 0x00])
            # LOG.debug("ANI Code (%s) (%i) '%s'" % (tmp2, i, tmp))
            rsvs = RadioSettingValueString(0, 6, tmp, autopad=False,
                                           charset=DTMFCHARS)
            ret.append(RadioSetting('anicodes@anicode@%i' % i,
                       'ANI-ID (%s) (%i) Code' % (tmp2, i+1), rsvs))
        return ret

    def _get_settings_adv(self):
        _mem = self._memobj
        ret = RadioSettingGroup('advanced', 'Advanced')
        if RT490_EXPERIMENTAL:
            rsvi = RadioSettingValueInteger(
                1, self._memory_size, int(_mem.settings.cha_memidx)+1)
            ret.append(RadioSetting("settings.cha_memidx",
                                    "Channel A Memory index", rsvi))
            rsvi = RadioSettingValueInteger(1, self._memory_size,
                                            int(_mem.settings.chb_memidx)+1)
            ret.append(RadioSetting("settings.chb_memidx",
                       "Channel B Memory index", rsvi))
        ret.append(RadioSetting('settings.vox', 'VOX Sensitivity',
                   RadioSettingValueList(self.VOX_LIST,
                                         current_index=_mem.settings.vox)))
        ret.append(
                   RadioSetting(
                       'settings.vox_delay', 'VOX Delay',
                       RadioSettingValueList(
                           self.VOXDELAYLIST,
                           current_index=_mem.settings.vox_delay)))
        ret.append(RadioSetting('settings.tdr', 'Dual Receive (TDR)',
                   RadioSettingValueBoolean(_mem.settings.tdr)))
        ret.append(
                   RadioSetting(
                       'settings.txundertdr', 'Tx under TDR',
                       RadioSettingValueList(
                           self.TDRTXMODES,
                           current_index=_mem.settings.txundertdr)))
        ret.append(RadioSetting('settings.voice', 'Menu Voice Prompts',
                                RadioSettingValueBoolean(_mem.settings.voice)))
        ret.append(
            RadioSetting(
                'settings.scanmode', 'Scan Mode',
                RadioSettingValueList(
                    self.SCANMODES, current_index=_mem.settings.scanmode)))
        ret.append(RadioSetting('settings.bcl', 'Busy Channel Lockout',
                   RadioSettingValueBoolean(_mem.settings.bcl)))
        ret.append(RadioSetting('settings.display_ani', 'Display ANI ID',
                   RadioSettingValueBoolean(_mem.settings.display_ani)))
        ret.append(RadioSetting('settings.ani_id', 'ANI ID',
                   RadioSettingValueList(self.ANI_IDS,
                                         current_index=_mem.settings.ani_id)))
        ret.append(
                   RadioSetting(
                       'settings.alarm_mode', 'Alarm Mode',
                       RadioSettingValueList(
                           self.ALARMMODES,
                           current_index=_mem.settings.alarm_mode)))
        ret.append(RadioSetting('settings.alarmsound', 'Alarm Sound',
                   RadioSettingValueBoolean(_mem.settings.alarmsound)))
        ret.append(RadioSetting('settings.fmradio', 'Enable FM Radio',
                   RadioSettingValueList(self.FMRADIO,
                                         current_index=_mem.settings.fmradio)))
        if RT490_EXPERIMENTAL:
            tmp = _mem.settings.fmpreset / 10.0
            if tmp < 65.0 or tmp > 108.0:
                tmp = 80.0
            ret.append(RadioSetting("settings.fmpreset", "FM Radio Freq",
                       RadioSettingValueFloat(65, 108, tmp, resolution=0.1,
                                              precision=1)))
        ret.append(RadioSetting('settings.kblock', 'Enable Keyboard Lock',
                   RadioSettingValueBoolean(_mem.settings.kblock)))
        ret.append(
                   RadioSetting(
                       'settings.autolock', 'Autolock Keyboard',
                       RadioSettingValueList(
                           self.AUTOLOCK_TO,
                           current_index=_mem.settings.autolock)))
        ret.append(
            RadioSetting(
                'settings.timer_menu_quit', 'Menu Exit Time',
                RadioSettingValueList(
                    self.MENUEXIT_TO,
                    current_index=_mem.settings.timer_menu_quit)))
        ret.append(RadioSetting('settings.enable_gps', 'Enable GPS',
                   RadioSettingValueBoolean(_mem.settings.enable_gps)))
        ret.append(
                   RadioSetting(
                       'settings.scan_dcs', 'CDCSS Save Modes',
                       RadioSettingValueList(
                           self.SCANDCSMODES,
                           current_index=_mem.settings.scan_dcs)))
        ret.append(RadioSetting('settings.tailnoiseclear', 'Tail Noise Clear',
                   RadioSettingValueBoolean(_mem.settings.tailnoiseclear)))
        ret.append(
                   RadioSetting(
                       'settings.rptnoiseclear', 'Rpt Noise Clear',
                       RadioSettingValueList(
                           self.RPTNOISE,
                           current_index=_mem.settings.rptnoiseclear)))
        ret.append(
                   RadioSetting(
                       'settings.rptnoisedelay', 'Rpt Noise Delay',
                       RadioSettingValueList(
                           self.RPTNOISE,
                           current_index=_mem.settings.rptnoisedelay)))
        ret.append(RadioSetting('settings.rpttone', 'Rpt Tone',
                   RadioSettingValueList(self.RPTTONES,
                                         current_index=_mem.settings.rpttone)))
        return ret

    def _get_settings_basic(self):
        _mem = self._memobj
        ret = RadioSettingGroup('basic', 'Basic')
        ret.append(RadioSetting('settings.squelch', 'Carrier Squelch Level',
                   RadioSettingValueList(self.SQUELCHLVLS,
                                         current_index=_mem.settings.squelch)))
        ret.append(
            RadioSetting(
                'settings.savemode', 'Battery Savemode',
                RadioSettingValueList(
                    self.SAVEMODES, current_index=_mem.settings.savemode)))
        ret.append(
                   RadioSetting(
                       'settings.backlight', 'Backlight Timeout',
                       RadioSettingValueList(
                           self.BACKLIGHT_TO,
                           current_index=_mem.settings.backlight)))
        ret.append(RadioSetting('settings.timeout', 'Timeout Timer (TOT)',
                   RadioSettingValueList(self.TOT_LIST,
                                         current_index=_mem.settings.timeout)))
        ret.append(RadioSetting('settings.beep', 'Beep',
                   RadioSettingValueBoolean(_mem.settings.beep)))
        ret.append(
            RadioSetting(
                'settings.active_channel', 'Active Channel',
                RadioSettingValueList(
                    self.CHANNELS,
                    current_index=_mem.settings.active_channel)))
        ret.append(
                   RadioSetting(
                       'settings.cha_disp', 'Channel A Display Mode',
                       RadioSettingValueList(
                           self.DISPLAYMODES,
                           current_index=_mem.settings.cha_disp)))
        ret.append(
                   RadioSetting(
                       'settings.chb_disp', 'Channel B Display Mode',
                       RadioSettingValueList(
                           self.DISPLAYMODES,
                           current_index=_mem.settings.chb_disp)))
        ret.append(RadioSetting('settings.roger', 'Roger Beep',
                   RadioSettingValueBoolean(_mem.settings.roger)))
        ret.append(
                   RadioSetting(
                       'settings.powermsg', 'Power Message',
                       RadioSettingValueList(
                           self.POWERMESSAGES,
                           current_index=_mem.settings.powermsg)))
        ret.append(RadioSetting('settings.rx_time', 'Show RX Time',
                   RadioSettingValueBoolean(_mem.settings.rx_time)))
        return ret

    def _get_memcodes(self):
        ret = RadioSettingGroup('mc', 'Memory Channel Privacy Codes')
        msgs = ["Only hexadecimal chars accepted.",
                "Allowed chars (%s)" % self.KEY_CHARS,
                "Input from 0 to 6 characters. If code",
                "length is less than 6 chars it will be",
                "padded with leading zeros.",
                "Ex: 1D32EB or 0F12 or AB521, etc...",
                "Enable Code for the Location on the",
                "'Other' tab in 'Memory Properties'."
                ]
        for msg in msgs:
            rsvs = RadioSettingValueString(0, 255, msg, autopad=False)
            rsvs.set_mutable(False)
            rs = RadioSetting('dummy_memcodes_msg_%i' % msgs.index(msg),
                              'Input rule %i' % int(msgs.index(msg)+1), rsvs)
            ret.append(rs)
        for i in range(self._memory_size):
            code = ""
            if self._memobj.memcode[i].code[3] < 0xFF:
                code = self._decode_key(self._memobj.memcode[i].code)
                code = code.zfill(6)
            rsvs = RadioSettingValueString(0, 6, code, autopad=False,
                                           charset=self.KEY_CHARS)
            rs = RadioSetting('memcode@code@%i' % i,
                              'Memory Location (%i) Privacy Code' %
                              int(i+1), rsvs)
            ret.append(rs)
        return ret

    def get_settings(self):
        radio_settings = []
        basic = self._get_settings_basic()
        radio_settings.append(basic)
        adv = self._get_settings_adv()
        radio_settings.append(adv)
        vfoa = self._get_settings_vfo(self._memobj.settings_vfo.vfo_a, 'A')
        radio_settings.append(vfoa)
        vfob = self._get_settings_vfo(self._memobj.settings_vfo.vfo_b, 'B')
        radio_settings.append(vfob)
        sk = self._get_settings_sidekeys()
        radio_settings.append(sk)
        dtmf = self._get_settings_dtmf()
        radio_settings.append(dtmf)
        ccn = self._get_custom_channel_names()
        radio_settings.append(ccn)
        can = self._get_custom_ani_names()
        radio_settings.append(can)
        ani = self._get_anicodes()
        radio_settings.append(ani)
        mcodes = self._get_memcodes()
        radio_settings.append(mcodes)
        if RT490_EXPERIMENTAL:
            ks = self._get_settings_ks()
            radio_settings.append(ks)
            bands = self._get_settings_bands()
            radio_settings.append(bands)
        top = RadioSettings(*radio_settings)
        return top

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    # TODO Add Code when RadioSettingValueString is fixed
    def _get_extra(self, _mem, num):
        group = RadioSettingGroup('extra', 'Extra')
        # LOG.debug("Get extra %i" % num)

        s = RadioSetting('bcl', 'Busy Channel Lockout',
                         RadioSettingValueBoolean(_mem.bcl))
        group.append(s)

        dcp = int(_mem.dcp)
        if dcp > len(self.FHSS_LIST)-1:
            _mem.dcp = cur = 0
            LOG.debug('DCP ID / FHSS overflow for channel %d' % num)
        cur = self.FHSS_LIST[dcp]
        s = RadioSetting('dcp', 'FHSS (Encryption)',
                         RadioSettingValueList(self.FHSS_LIST, cur))
        group.append(s)

        # Does not work, no error, why ??? TODO
        """
        code = ""
        if self._memobj.memcode[num-1].code[3] < 0xFF:
            code = self._decode_key(self._memobj.memcode[num-1].code)
            code = code.zfill(6)
        LOG.debug('CODE "%s"' % code)
        s = RadioSetting('dcp_code', 'DCP code',
                         RadioSettingValueString(0, 6, code,
                                                autopad=False,
                                                charset=self.KEY_CHARS))
        group.append(s) """

        pttid = int(_mem.pttid)
        if pttid > len(self.PTTID)-1:
            _mem.pttid = cur = 0
            LOG.debug('PTTID overflow for channel %d' % num)
        cur = self.PTTID[pttid]
        s = RadioSetting('pttid', 'Send DTMF Code (PTT ID)',
                         RadioSettingValueList(self.PTTID, cur))
        group.append(s)

        cur = self.SIGNAL[int(_mem.signal)]
        s = RadioSetting('signal', 'PTT ID Code (S-Code)',
                         RadioSettingValueList(self.SIGNAL, cur))
        group.append(s)

        s = RadioSetting('learn',
                         'Use Memory Privacy Code as Tx/Rx DCS (Learn)',
                         RadioSettingValueBoolean(_mem.learn))
        group.append(s)

        return group

    # TODO Add Code when RadioSettingValueString is fixed
    def _set_extra(self, _mem, mem):
        # memidx = mem.number - 1  # commented because not used
        _mem.bcl = int(mem.extra['bcl'].value)
        _mem.dcp = int(mem.extra['dcp'].value)
        _mem.pttid = int(mem.extra['pttid'].value)
        _mem.signal = int(mem.extra['signal'].value)
        # self._memobj.memcode[mem.number].code = \
        #     self._encode_key(mem.extra['dcp_code'].value)
        if (int(mem.extra['learn'].value) > 0) and \
                (self._memobj.memcode[mem.number-1].code[3] == 0xA0):
            _mem.learn = 1
        elif (int(mem.extra['learn'].value) > 0) and \
                (self._memobj.memcode[mem.number-1].code[3] != 0xA0):
            _mem.learn = 0
            raise InvalidValueError(
                "Use Memory Privacy Code as Tx/Rx DCS (Learn) requires "
                "that a memory code has been previously set for this memory."
                "Go in 'Settings' -> 'Memory Channel Privacy Codes' and set "
                "a code for the current memory before enabling 'Learn'.")
        else:
            _mem.learn = 0

    def _is_txinh(self, _mem):
        raw_tx = b""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == b"\xFF\xFF\xFF\xFF"

    def get_memory(self, num):
        memidx = num - 1
        _mem = self._memobj.memory[memidx]
        _nam = self._memobj.memname[memidx]

        mem = chirp_common.Memory()
        mem.number = num
        if int(_mem.rxfreq) == 166666665:
            mem.empty = True
            return mem

        mem.name = ''.join([str(c) for c in _nam.name
                            if ord(str(c)) < 127]).rstrip()
        mem.freq = int(_mem.rxfreq) * 10
        offset = (int(_mem.txfreq) - int(_mem.rxfreq)) * 10
        if self._is_txinh(_mem) or _mem.tx_enable == 0:
            mem.duplex = 'off'
            # _mem.txfreq = _mem.rxfreq # TODO REMOVE (force fix broken saves)
        elif offset == 0:
            mem.duplex = ''
            mem.offset = 0
        elif abs(offset) < 100000000:
            mem.duplex = offset < 0 and '-' or '+'
            mem.offset = abs(offset)
        else:
            mem.duplex = 'split'
            mem.offset = int(_mem.txfreq) * 10

        mem.power = self.POWER_LEVELS[_mem.power]

        if _mem.unknown3_0 and _mem.narrow:
            mem.mode = 'NAM'
        elif _mem.unknown3_0 and not _mem.narrow:
            mem.mode = 'AM'
        elif not _mem.unknown3_0 and _mem.narrow:
            mem.mode = 'NFM'
        elif not _mem.unknown3_0 and not _mem.narrow:
            mem.mode = 'FM'
        else:
            LOG.exception('Failed to get mode for %i' % num)

        mem.skip = '' if _mem.scan else 'S'

        # LOG.warning('got txtone: %s' % repr(self._decode_tone(_mem.txtone)))
        # LOG.warning('got rxtone: %s' % repr(self._decode_tone(_mem.rxtone)))
        txtone = self._decode_tone(_mem.txtone)
        rxtone = self._decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)
        try:
            mem.extra = self._get_extra(_mem, num)
        except Exception:
            LOG.exception('Failed to get extra for %i' % num)
        return mem

    def set_memory(self, mem):
        memidx = mem.number - 1
        _mem = self._memobj.memory[memidx]
        _nam = self._memobj.memname[memidx]

        if mem.empty:
            _mem.set_raw(b'\xff' * 16)
            _nam.set_raw(b'\xff' * 16)
            return

        if int(_mem.rxfreq) == 166666665:
            LOG.debug('Initializing new memory %i' % memidx)
            _mem.set_raw(b'\x00' * 16)

        _nam.name = mem.name.ljust(12, chr(255))  # with xFF pad (mimic factory
        #                                           behavior)

        _mem.rxfreq = mem.freq / 10
        _mem.tx_enable = 1
        if mem.duplex == '':
            _mem.txfreq = mem.freq / 10
        elif mem.duplex == 'split':
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == 'off':
            _mem.tx_enable = 0
            _mem.txfreq = mem.freq / 10  # Optional but keeps compat with
            #                              vendor software
        elif mem.duplex == '-':
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == '+':
            _mem.txfreq = (mem.freq + mem.offset) / 10
        else:
            raise errors.RadioError('Unsupported duplex mode %r' % mem.duplex)

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        # LOG.warning('tx tone is %s' % repr(txtone))
        # LOG.warning('rx tone is %s' % repr(rxtone))
        _mem.txtone = self._encode_tone(*txtone)
        _mem.rxtone = self._encode_tone(*rxtone)

        try:
            _mem.power = self.POWER_LEVELS.index(mem.power)
        except ValueError:
            _mem.power = 0

        if int(_mem.rxfreq) < 30000000:
            _mem.unknown3_0 = mem.mode in ['AM', 'NAM']
        else:
            _mem.unknown3_0 = 0
        _mem.narrow = mem.mode[0] == 'N'

        _mem.scan = mem.skip != 'S'

        if mem.extra:
            self._set_extra(_mem, mem)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT490 %
                                     {"memsize": self._memory_size},
                                     self._mmap)

    def get_features(self):  # GOOD ?
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.valid_name_length = 12
        rf.valid_characters = self._valid_chars
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "DTCS->", "->DTCS", "Tone->DTCS",
                                "DTCS->Tone", "->Tone", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "+", "-", "split", "off"]
        rf.valid_modes = ["FM", "NFM", "AM", "NAM"]
        rf.memory_bounds = (1, 256)
        rf.valid_tuning_steps = self.TUNING_STEPS
        rf.valid_bands = [(108000000, 136000000),
                          (136000000, 180000000),
                          (200000000, 260000000),
                          (350000000, 400000000),
                          (400000000, 520000000)]
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_upload = _("This driver is in development and should be "
                          "considered as experimental.")
        rp.experimental = _("This driver is in development and should be "
                            "considered as experimental.")
        rp.info = _("This driver is in development and should be considered "
                    "as experimental.")
        return rp

    def _encode_key(self, key):
        arr = bytearray(4)
        arr[3] = 160
        arr[2] = self.KEY_CHARS.index(key[0])  # << 4
        arr[2] = arr[2] << 4
        arr[2] |= self.KEY_CHARS.index(key[1])
        arr[1] = self.KEY_CHARS.index(key[2])  # << 4
        arr[1] = arr[1] << 4
        arr[1] |= self.KEY_CHARS.index(key[3])
        arr[0] = self.KEY_CHARS.index(key[4])  # << 4
        arr[0] = arr[0] << 4
        arr[0] |= self.KEY_CHARS.index(key[5])
        return arr

    def _decode_key(self, key):
        ret = ""
        if key[3] == 0xA0:
            ret += self.KEY_CHARS[key[2] >> 4]
            ret += self.KEY_CHARS[key[2] & 0xF]
            ret += self.KEY_CHARS[key[1] >> 4]
            ret += self.KEY_CHARS[key[1] & 0xF]
            ret += self.KEY_CHARS[key[0] >> 4]
            ret += self.KEY_CHARS[key[0] & 0xF]
            LOG.debug('DCP Code: "%s"' % ret)
        return ret

    def _decode_tone(self, toneval):
        if toneval in (0, 0xFFFF):
            # LOG.debug('no tone value: %s' % toneval)
            return None, None, None
        elif toneval < 670:
            toneval = toneval - 1
            index = toneval % len(DTCS_CODES)
            if index != int(toneval):
                pol = 'R'
                # index -= 1
            else:
                pol = 'N'
            return 'DTCS', DTCS_CODES[index], pol
        else:
            return 'Tone', toneval / 10.0, 'N'

    def _encode_tone(self, mode, val, pol):
        if not mode:
            return 0x0000
        elif mode == 'Tone':
            return int(val * 10)
        elif mode == 'DTCS':
            index = DTCS_CODES.index(val)
            if pol == 'R':
                index += len(DTCS_CODES)
            index += 1
            # LOG.debug('Encoded dtcs %s/%s to %04x' % (val, pol, index))
            return index
        else:
            raise errors.RadioError('Unsupported tone mode %r' % mode)


@directory.register
class MML8629Radio(RT490Radio):
    """MMLradio JC-8629"""
    VENDOR = "MMLradio"
    MODEL = "JC-8629"


@directory.register
class JJCC8629Radio(RT490Radio):
    """JJCC JC-8629"""
    VENDOR = "JJCC"
    MODEL = "JC-8629"


@directory.register
class SocotranJC8629Radio(RT490Radio):
    """Socotran JC-8629"""
    VENDOR = "Socotran"
    MODEL = "JC-8629"


@directory.register
class SocotranFB8629Radio(RT490Radio):
    """Socotran FB-8629"""
    VENDOR = "Socotran"
    MODEL = "FB-8629"


@directory.register
class Jianpai8629Radio(RT490Radio):
    """Jianpai 8800 Plus"""
    VENDOR = "Jianpai"
    MODEL = "8800_Plus"


@directory.register
class Boristone8RSRadio(RT490Radio):
    """Boristone 8RS"""
    VENDOR = "Boristone"
    MODEL = "8RS"


@directory.register
class AbbreeAR869Radio(RT490Radio):
    """Abbree AR-869"""
    VENDOR = "Abbree"
    MODEL = "AR-869"


@directory.register
class HamGeekHG590Radio(RT490Radio):
    """HamGeek HG-590"""
    VENDOR = "HamGeek"
    MODEL = "HG-590"


IMHEX_DESC = """
// Perfect tool for binary reverse engineering
// https://github.com/WerWolv/ImHex
// Below is the pattern
"""
IMHEX_PATTERN = """
struct memory {                    // Memory settings
  u8 rxfreq[4];
  u8 txfreq[4];
  u16 rxtone;
  u16 txtone;
  u8 signal;            // int 0->14, Signal 1->15
  u8 pttid;             // ['OFF', 'BOT', 'EOT', 'Both']
  u8 dcp_power;           // POWER_LEVELS
  u8 unknown3_0_narrow_unknown3_1_bcl_scan_tx_enable_learn;    // bool ??? TODO
};
struct memname {
  char name[12];
  padding[4];
};
struct memcode {
  u8 code[4];
};
struct custom_ani_names {
  char name[12];
  padding[4];
};
struct anicodes {
  u8 anicode[6];
  padding[10];
};
struct custom_channel_names {
  char name[12];
  padding[4];
};
bitfield workmode {
  b : 4;
  a : 4;
};
struct settings {
  u8 squelch;           // 0: int 0 -> 9
  u8 savemode;          // 1: ['OFF', 'Normal', 'Super', 'Deep']
  u8 vox;               // 2: off=0, 1 -> 9
  u8 backlight;         // 3: ['OFF', '5s', '15s', '20s', '30s', '1m', '2m',
                        //      '3m']
  u8 tdr;               // 4: bool
  u8 timeout;           // 5: n*30seconds, 0-240s
  u8 beep;              // 6: bool
  u8 voice;             // 7: bool
  u8 byte_not_used_10;  // 8: Always 1
  u8 dtmfst;            // 9: ['OFF', 'KB Side Tone', 'ANI Side Tone',
                        //      'KB ST + ANI ST']
  u8 scanmode;          // 10: ['TO', 'CO', 'SE']
  u8 pttid;             // 11: ['OFF', 'BOT', 'EOT', 'Both']
  u8 pttiddelay;        // 12: ['0', '100ms', '200ms', '400ms', '600ms',
                        //      '800ms', '1000ms']
  u8 cha_disp;          // 13: ['Name', 'Freq', 'Channel ID']
  u8 chb_disp;          // 14: ['Name', 'Freq', 'Channel ID']
  u8 bcl;               // 15: bool
  u8 autolock;          // 0: ['OFF', '5s', '10s', 15s']
  u8 alarm_mode;        // 1: ['Site', 'Tone', 'Code']
  u8 alarmsound;        // 2: bool
  u8 txundertdr;        // 3: ['OFF', 'A', 'B']
  u8 tailnoiseclear;    // 4: [off, on]
  u8 rptnoiseclear;     // 5: n*100ms, 0-1000
  u8 rptnoisedelay;     // 6: n*100ms, 0-1000
  u8 roger;             // 7: bool
  u8 active_channel;    // 8: 0 or 1
  u8 fmradio;           // 9: boolean, inverted
  workmode _workmode;   // 10: up    ['VFO', 'CH Mode']
  u8 kblock;            // 11: bool                  // TODO TEST WITH autolock
  u8 powermsg;          // 12: 0=Image / 1=Voltage
  u8 byte_not_used_21;  // 13: Always 0
  u8 rpttone;           // 14: ['1000Hz', '1450Hz', '1750Hz', '2100Hz']
  u8 byte_not_used_22;  // 15: pad with xFF
  u8 vox_delay;         // 0: [str(float(a)/10)+'s' for a in range(5,21)]
                        //      '0.5s' to '2.0s'
  u8 timer_menu_quit;   // 1: ['5s', '10s', '15s', '20s', '25s', '30s',
                        //      '35s', '40s', '45s', '50s', '60s']
  u8 byte_not_used_30;  // 2: pad with xFF
  u8 byte_not_used_31;  // 3: pad with xFF
  u8 enable_killsw;     // 4: bool
  u8 display_ani;       // 5: bool
  u8 byte_not_used_32;  // 6: pad with xFF
  u8 enable_gps;        // 7: bool
  u8 scan_dcs;          // 8: ['All', 'Receive', 'Transmit']
  u8 ani_id;            // 9: int 0-59 (ANI 1-60)
  u8 rx_time;           // 10: bool
  padding[5];          // 11: Pad xFF
  u8 cha_memidx;        // 0: Memory index when channel A use memories
  u8 byte_not_used_40;
  u8 chb_memidx;        // 2: Memory index when channel B use memories
  u8 byte_not_used_41;
  padding[10];
  u16 fmpreset;
};
struct settings_vfo_chan {
  u8   rxfreq[8];       // 0
  u16 rxtone;          // 8
  u16 txtone;          // 10
  u16 byte_not_used0;  // 12 Pad xFF
  u8   sftd_signal;        // 14 int 0->14, Signal 1->15
  u8   byte_not_used1;  // 15 Pad xFF
  u8   power;           // 16:0 POWER_LEVELS
  u8   fhss_narrow;        // 17 bool true=NFM false=FM
  u8   byte_not_used2;  // 18 Pad xFF but received 0x00 ???
  u8   freqstep;        // 19:3 ['2.5 KHz', '5.0 KHz', '6.25 KHz',
                        //       '10.0 KHz', '12.5 KHz', '20.0 KHz',
                        //       '25.0 KHz', '50.0 KHz']
  u8   byte_not_used3;  // 20:4 Pad xFF but received 0x00 ??? TODO
  u8   offset[6];       // 21:5 Freq NN.NNNN (without the dot) TEST TEST
  u8   byte_not_used4;  // 27:11   Pad xFF
  u8   byte_not_used5;  // 28      Pad xFF
  u8   byte_not_used6;  // 29      Pad xFF
  u8   byte_not_used7;  // 30      Pad xFF
  u8   byte_not_used8;  // 31:15   Pad xFF
};
struct settings_vfo {
  settings_vfo_chan vfo_a;
  settings_vfo_chan vfo_b;
};
struct settings_sidekeys {                    // Values from Radio
  u8 pf2_short;         // { '7': 'FM', '10': 'Tx Power', '28': 'Scan',
                        //   '29': 'Search, '1': 'PPT B' }
  u8 pf2_long;          // { '7': 'FM', '10': 'Tx Power', '28': 'Scan',
                        //  '29': 'Search' }
  u8 pf3_short;         // { '7': 'FM', '10': 'Tx Power', '28': 'Scan',
                        //  '29': 'Search' }
  u8 ffpad;             // Pad xFF
};
struct dtmfcode {
  u8 code[5];           // 5 digits DTMF
  padding[11];         // Pad xFF
};
struct settings_dtmf {                // @15296+3x16
  u8 byte_not_used1;    // 0: Pad xFF
  u8 byte_not_used2;    // 1: Pad xFF
  u8 byte_not_used3;    // 2: Pad xFF
  u8 byte_not_used4;    // 3: Pad xFF
  u8 byte_not_used5;    // 4: Pad xFF
  u8 unknown_dtmf;      // 5: 0 TODO ???? wtf is alarmcode/alarmcall TODO
  u8 pttid;             // 6: [off, BOT, EOT, Both]
  u8 dtmf_speed_on;     // 7: ['50ms', '100ms', '200ms', '300ms', '500ms']
  u8 dtmf_speed_off;    // 8:0 ['50ms', '100ms', '200ms', '300ms', '500ms']
};
struct settings_dtmf_global {
  dtmfcode settings_dtmfgroup[15];
  settings_dtmf _settings_dtmf;
};
struct settings_killswitch {
  u8 kill_dtmf[6];      // 0: Kill DTMF
  padding[2];         // Pad xFF
  u8 revive_dtmf[6];    // 8: Revive DTMF
  padding[2];         // Pad xFF
};
struct management_settings {
  u8 unknown_data_0[16];
  u8 unknown_data_1;
  u8 active;            // Bool radio killed (killed=0, active=1)
  padding[46];
};
struct band {
  u8 enable;            // 0 bool / enable-disable Tx on band
  u8 freq_low[2];       // 1 lowest band frequency
  u8 freq_high[2];      // 3 highest band frequency
};
struct settings_bands {
  band band136;  // 0  Settings for 136MHz band
  band band400;  // 5  Settings for 400MHz band
  band band200;  // 10 Settings for 200MHz band
  padding[1];    // 15
  band band350;  // 0  Settings for 350MHz band
  padding[43];// 5
};

memory mem[256] @ 0x0000;
memname mname[256] @ 0x1000;
memcode mcode[256] @ 0x2000;
custom_ani_names caninames[10] @ 0x3400;
anicodes anic[60] @ 0x3500;
custom_channel_names ccnames[10] @ 0x3900;
settings _settings @ 0x3A00;
settings_vfo _settings_vfo @ 0x3A40;
settings_sidekeys _settings_sidekeys @ 0x3A80;
settings_dtmf_global _settings_dtmf_global @ 0x3B00;
settings_killswitch _settings_killswitch @ 0x3C00;
management_settings _management_settings @ 0x3F80;
settings_bands _settings_bands @ 0x3FC0;
"""
