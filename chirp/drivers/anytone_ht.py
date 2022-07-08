# Copyright 2015 Jim Unroe <rock.unroe@gmail.com>
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

import os
import struct
import time
import logging

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, InvalidValueError, RadioSettings

LOG = logging.getLogger(__name__)

mem_format = """
struct memory {
  bbcd freq[4];
  bbcd offset[4];     
  u8 unknown1:4,      
     tune_step:4;
  u8 unknown2:2,      
     txdcsextra:1,
     txinv:1,
     channel_width:2,
     unknown3:1,
     tx_off:1;
  u8 unknown4:2,      
     rxdcsextra:1,
     rxinv:1,
     power:2,
     duplex:2;
  u8 unknown5:4,      
     rxtmode:2,
     txtmode:2;
  u8 unknown6:2,      
     txtone:6;
  u8 unknown7:2,      
     rxtone:6;
  u8 txcode;          
  u8 rxcode;          
  u8 unknown8[3];     
  char name[6];       
  u8 squelch:4,       
     unknown9:2,
     bcl:2;
  u8 unknownA;        
  u8 unknownB:7,      
     sqlmode:1;
  u8 unknownC[4];
};

#seekto 0x0010;
struct {
    u8 unknown1;
    u8 unknown2:5,     
       bands1:3;
    char model[7];     
    u8 unknown3:5,     
       bands2:3;
    u8 unknown4[6];    
    u8 unknown5[16];   
    char date[9];      
    u8 unknown6[7];    
    u8 unknown7[16];   
    u8 unknown8[16];   
    char dealer[16];   
    char stockdate[9]; 
    u8 unknown9[7];    
    char selldate[9];  
    u8 unknownA[7];    
    char seller[16];
} oem_info;

#seekto 0x0100;
u8 used_flags[50];

#seekto 0x0120;
u8 skip_flags[50];

#seekto 0x0220;
struct {
  u8 unknown220:6,
     display:2;
  u8 unknown221:7,
     upvfomr:1;
  u8 unknown222:7,
     dnvfomr:1;
  u8 unknown223:7,
     fmvfomr:1;
  u8 upmrch;
  u8 dnmrch;
  u8 unknown226:1,
     fmmrch:7;
  u8 unknown227;
  u8 unknown228:7,
     fastscano:1;       // obltr-8r only
  u8 unknown229:6,
     pause:2;
  u8 unknown22A:5,
     stop:3;
  u8 unknown22B:6,
     backlight:2;
  u8 unknown22C:6,
     color:2;
  u8 unknown22D:6,
     vdisplay:2;
  u8 unknown22E;
  u8 unknown22F:5,
     pf1key:3;
  u8 beep:1,
     alarmoff:1,
     main:1,
     radio:1,
     unknown230:1,
     allband:1,
     elimtail:1,
     monikey:1;
  u8 fastscan:1,        // termn-8r only
     keylock:1,
     unknown231:2,
     lwenable:1,
     swenable:1,
     fmenable:1,
     amenable:1;
  u8 unknown232:3,
     tot:5;
  u8 unknown233:7,
     amvfomr:1;
  u8 unknown234:3,
     apo:5;
  u8 unknown235:5,
     pf2key:3;          // keylock for obltr-8r
  u8 unknown236;
  u8 unknown237:4,
     save:4;
  u8 unknown238:5,
     tbst:3;
  u8 unknown239:4,
     voxlevel:4;
  u8 unknown23A:3,
     voxdelay:5;
  u8 unknown23B:5,
     tail:3;
  u8 unknown23C;
  u8 unknown23D:1,
     ammrch:7;
  u8 unknown23E:5,
     vvolume:3;
  u8 unknown23F:5,
     fmam:3;
  u8 unknown240:4,
     upmrbank:4;
  u8 unknown241:7,
     upwork:1;
  u8 unknown242:7,
     uplink:1;
  u8 unknown243:4,
     dnmrbank:4;
  u8 unknown244:7,
     dnwork:1;
  u8 unknown245:7,
     downlink:1;
  u8 unknown246:7,
     banklink1:1;
  u8 unknown247:7,
     banklink2:1;
  u8 unknown248:7,
     banklink3:1;
  u8 unknown249:7,
     banklink4:1;
  u8 unknown24A:7,
     banklink5:1;
  u8 unknown24B:7,
     banklink6:1;
  u8 unknown24C:7,
     banklink7:1;
  u8 unknown24D:7,
     banklink8:1;
  u8 unknown24E:7,
     banklink9:1;
  u8 unknown24F:7,
     banklink0:1;
  u8 unknown250:6,
     noaa:2;
  u8 unknown251:5,
     noaach:3;
  u8 unknown252:6,
     part95:2;
  u8 unknown253:3,
     gmrs:5;
  u8 unknown254:5,
     murs:3;
  u8 unknown255:5,
     amsql:3;
} settings;

#seekto 0x0246;
struct {
  u8 unused:7,
     bank:1;
} banklink[10];

#seekto 0x03E0;
struct {
  char line1[6];
  char line2[6];
} welcome_msg;

#seekto 0x2000;
struct memory memory[200];
"""


def _echo_write(radio, data):
    try:
        radio.pipe.write(data)
    except Exception as e:
        LOG.error("Error writing to radio: %s" % e)
        raise errors.RadioError("Unable to write to radio")


def _read(radio, length):
    try:
        data = radio.pipe.read(length)
    except Exception as e:
        LOG.error("Error reading from radio: %s" % e)
        raise errors.RadioError("Unable to read from radio")

    if len(data) != length:
        LOG.error("Short read from radio (%i, expected %i)" %
                  (len(data), length))
        LOG.debug(util.hexprint(data))
        raise errors.RadioError("Short read from radio")
    return data

valid_model = ['TERMN8R', 'OBLTR8R']


def _ident(radio):
    radio.pipe.timeout = 1
    _echo_write(radio, "PROGRAM")
    response = radio.pipe.read(3)
    if response != "QX\x06":
        LOG.debug("Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Radio did not respond. Check connection.")
    _echo_write(radio, "\x02")
    response = radio.pipe.read(16)
    LOG.debug(util.hexprint(response))
    if radio._file_ident not in response:
        LOG.debug("Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Unsupported model")


def _finish(radio):
    endframe = "\x45\x4E\x44"
    _echo_write(radio, endframe)
    result = radio.pipe.read(1)
    if result != "\x06":
        LOG.debug("Got:\n%s" % util.hexprint(result))
        raise errors.RadioError("Radio did not finish cleanly")


def _checksum(data):
    cs = 0
    for byte in data:
        cs += ord(byte)
    return cs % 256


def _send(radio, cmd, addr, length, data=None):
    frame = struct.pack(">cHb", cmd, addr, length)
    if data:
        frame += data
        frame += chr(_checksum(frame[1:]))
        frame += "\x06"
    _echo_write(radio, frame)
    LOG.debug("Sent:\n%s" % util.hexprint(frame))
    if data:
        result = radio.pipe.read(1)
        if result != "\x06":
            LOG.debug("Ack was: %s" % repr(result))
            raise errors.RadioError(
                "Radio did not accept block at %04x" % addr)
        return
    result = _read(radio, length + 6)
    LOG.debug("Got:\n%s" % util.hexprint(result))
    header = result[0:4]
    data = result[4:-2]
    ack = result[-1]
    if ack != "\x06":
        LOG.debug("Ack was: %s" % repr(ack))
        raise errors.RadioError("Radio NAK'd block at %04x" % addr)
    _cmd, _addr, _length = struct.unpack(">cHb", header)
    if _addr != addr or _length != _length:
        LOG.debug("Expected/Received:")
        LOG.debug(" Length: %02x/%02x" % (length, _length))
        LOG.debug(" Addr: %04x/%04x" % (addr, _addr))
        raise errors.RadioError("Radio send unexpected block")
    cs = _checksum(result[1:-2])
    if cs != ord(result[-2]):
        LOG.debug("Calculated: %02x" % cs)
        LOG.debug("Actual:     %02x" % ord(result[-2]))
        raise errors.RadioError("Block at 0x%04x failed checksum" % addr)
    return data


def _download(radio):
    _ident(radio)

    memobj = None

    data = ""
    for start, end in radio._ranges:
        for addr in range(start, end, 0x10):
            block = _send(radio, 'R', addr, 0x10)
            data += block

            status = chirp_common.Status()
            status.cur = len(data)
            status.max = end
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    _finish(radio)

    return memmap.MemoryMap(data)


def _upload(radio):
    _ident(radio)

    for start, end in radio._ranges:
        for addr in range(start, end, 0x10):
            if addr < 0x0100:
                continue
            block = radio._mmap[addr:addr + 0x10]
            _send(radio, 'W', addr, len(block), block)

            status = chirp_common.Status()
            status.cur = addr
            status.max = end
            status.msg = "Cloning to radio"
            radio.status_fn(status)

    _finish(radio)


APO = ['Off', '30 Minutes', '1 Hour', '2 Hours']
BACKLIGHT = ['Off', 'On', 'Auto']
BCLO = ['Off', 'Repeater', 'Busy']
CHARSET = chirp_common.CHARSET_ASCII
COLOR = ['Blue', 'Orange', 'Purple']
DISPLAY = ['Frequency', 'N/A', 'Name']
DUPLEXES = ['', 'N/A', '-', '+', 'split', 'off']
GMRS = ['GMRS %s' % x for x in range(1, 8)] + \
       ['GMRS %s' % x for x in range(15, 23)] + \
       ['GMRS Repeater %s' % x for x in range(15, 23)]
MAIN = ['Up', 'Down']
MODES = ['FM', 'NFM']
MONI = ['Squelch Off Momentarily', 'Squelch Off']
MRBANK = ['Bank %s' % x for x in range(1, 10)] + ['Bank 0']
MURS = ['MURS %s' % x for x in range(1, 6)]
NOAA = ['Weather Off', 'Weather On', 'Weather Alerts']
NOAACH = ['WX %s' % x for x in range(1, 8)]
PART95 = ['Normal(Part 90)', 'GMRS(Part 95A)', 'MURS(Part 95J)']
PAUSE = ['%s Seconds (TO)' % x for x in range(5, 20, 5)] + ['2 Seconds (CO)']
PFKEYT = ['Off', 'VOLT', 'CALL', 'FHSS', 'SUB PTT', 'ALARM', 'MONI']
PFKEYO = ['Off', 'VOLT', 'CALL', 'SUB PTT', 'ALARM', 'MONI']
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5),
                chirp_common.PowerLevel("Mid", watts=2),
                chirp_common.PowerLevel("Low", watts=1)]
SAVE = ['Off', '1:2', '1:3', '1:5', '1:8', 'Auto']
SQUELCH = ['%s' % x for x in range(0, 10)]
STOP = ['%s Seconds' % x for x in range(0, 4)] + ['Manual']
TAIL = ['Off', '120 Degree', '180 Degree', '240 Degree']
TBST = ['Off', '1750 Hz', '2100 Hz', '1000 Hz', '1450 Hz']
TMODES = ['', 'Tone', 'DTCS', '']
TONES = [62.5] + list(chirp_common.TONES)
TOT = ['Off'] + ['%s Seconds' % x for x in range(10, 280, 10)]
VDISPLAY = ['Frequency/Channel', 'Battery Voltage', 'Off']
VFOMR = ["VFO", "MR"]
VOXLEVEL = ['Off'] + ['%s' % x for x in range(1, 11)]
VOXDELAY = ['%.1f Seconds' % (0.1 * x) for x in range(5, 31)]
WORKMODE = ["Channel", "Bank"]


@directory.register
class AnyToneTERMN8RRadio(chirp_common.CloneModeRadio,
                         chirp_common.ExperimentalRadio):
    """AnyTone TERMN-8R"""
    VENDOR = "AnyTone"
    MODEL = "TERMN-8R"
    BAUD_RATE = 9600
    _file_ident = "TERMN8R"

    # May try to mirror the OEM behavior later
    _ranges = [
        (0x0000, 0x8000),
        ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("The Anytone driver is currently experimental. "
                           "There are no known issues with it, but you should "
                           "proceed with caution.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_rx_dtcs = True
        rf.valid_skips = ["", "S"]
        rf.valid_modes = MODES
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 520000000)]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 6
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = DUPLEXES
        rf.can_odd_split = True
        rf.memory_bounds = (0, 199)
        return rf
                        
    def sync_in(self):
        self._mmap = _download(self)
        self.process_mmap()

    def sync_out(self):
        _upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def _get_dcs_index(self, _mem, which):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        return (int(extra) << 8) | int(base)

    def _set_dcs_index(self, _mem, which, index):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        base.set_value(index & 0xFF)
        extra.set_value(index >> 8)

    def get_memory(self, number):
        bitpos = (1 << (number % 8))
        bytepos = (number / 8)

        _mem = self._memobj.memory[number]
        _skp = self._memobj.skip_flags[bytepos]
        _usd = self._memobj.used_flags[bytepos]

        mem = chirp_common.Memory()
        mem.number = number

        if _usd & bitpos:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 100
        mem.offset = int(_mem.offset) * 100
        mem.name = self.filter_name(str(_mem.name).rstrip())
        mem.duplex = DUPLEXES[_mem.duplex]
        mem.mode = MODES[_mem.channel_width]

        if _mem.tx_off == True:
            mem.duplex = "off"
            mem.offset = 0

        rxtone = txtone = None
        rxmode = TMODES[_mem.rxtmode]
        txmode = TMODES[_mem.txtmode]
        if txmode == "Tone":
            txtone = TONES[_mem.txtone]
        elif txmode == "DTCS":
            txtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'tx')]
        if rxmode == "Tone":
            rxtone = TONES[_mem.rxtone]
        elif rxmode == "DTCS":
            rxtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,
                                                                     'rx')]

        rxpol = _mem.rxinv and "R" or "N"
        txpol = _mem.txinv and "R" or "N"

        chirp_common.split_tone_decode(mem,
                                       (txmode, txtone, txpol),
                                       (rxmode, rxtone, rxpol))

        if _skp & bitpos:
            mem.skip = "S"

        mem.power = POWER_LEVELS[_mem.power]

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueList(BCLO,
                                                BCLO[_mem.bcl]))
        mem.extra.append(rs)

        rs = RadioSetting("squelch", "Squelch",
                          RadioSettingValueList(SQUELCH,
                                                SQUELCH[_mem.squelch]))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        bitpos = (1 << (mem.number % 8))
        bytepos = (mem.number / 8)

        _mem = self._memobj.memory[mem.number]
        _skp = self._memobj.skip_flags[bytepos]
        _usd = self._memobj.used_flags[bytepos]

        if mem.empty:
            _usd |= bitpos
            _skp |= bitpos
            _mem.set_raw("\xFF" * 32)
            return
        _usd &= ~bitpos

        if _mem.get_raw() == ("\xFF" * 32):
            LOG.debug("Initializing empty memory")
            _mem.set_raw("\x00" * 32)
            _mem.squelch = 3

        _mem.freq = mem.freq / 100

        if mem.duplex == "off":
            _mem.duplex = DUPLEXES.index("")
            _mem.offset = 0
            _mem.tx_off = True
        elif mem.duplex == "split":
            diff = mem.offset - mem.freq
            _mem.duplex = DUPLEXES.index("-") if diff < 0 \
                else DUPLEXES.index("+")
            _mem.offset = abs(diff) / 100
        else:
            _mem.offset = mem.offset / 100
            _mem.duplex = DUPLEXES.index(mem.duplex)

        _mem.name = mem.name.ljust(6)

        try:
            _mem.channel_width = MODES.index(mem.mode)
        except ValueError:
            _mem.channel_width = 0

        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.txtmode = TMODES.index(txmode)
        _mem.rxtmode = TMODES.index(rxmode)
        if txmode == "Tone":
            _mem.txtone = TONES.index(txtone)
        elif txmode == "DTCS":
            self._set_dcs_index(_mem, 'tx',
                                chirp_common.ALL_DTCS_CODES.index(txtone))
        if rxmode == "Tone":
            _mem.sqlmode = 1
            _mem.rxtone = TONES.index(rxtone)
        elif rxmode == "DTCS":
            _mem.sqlmode = 1
            self._set_dcs_index(_mem, 'rx',
                                chirp_common.ALL_DTCS_CODES.index(rxtone))
        else:
            _mem.sqlmode = 0

        _mem.txinv = txpol == "R"
        _mem.rxinv = rxpol == "R"

        if mem.skip:
            _skp |= bitpos
        else:
            _skp &= ~bitpos

        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _msg = self._memobj.welcome_msg
        _oem = self._memobj.oem_info
        _settings = self._memobj.settings
        cfg_grp = RadioSettingGroup("cfg_grp", "Function Setup")
        oem_grp = RadioSettingGroup("oem_grp", "OEM Info")

        group = RadioSettings(cfg_grp,
                              oem_grp)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        #
        # Function Setup
        #

        rs = RadioSetting("welcome_msg.line1", "Welcome Message 1",
                          RadioSettingValueString(
                              0, 6, _filter(_msg.line1)))
        cfg_grp.append(rs)

        rs = RadioSetting("welcome_msg.line2", "Welcome Message 2",
                          RadioSettingValueString(
                              0, 6, _filter(_msg.line2)))
        cfg_grp.append(rs)

        rs = RadioSetting("display", "Display Mode",
                          RadioSettingValueList(DISPLAY,
                                                DISPLAY[_settings.display]))
        cfg_grp.append(rs)

        rs = RadioSetting("upvfomr", "Up VFO/MR",
                          RadioSettingValueList(VFOMR,
                                                VFOMR[_settings.upvfomr]))
        cfg_grp.append(rs)

        rs = RadioSetting("dnvfomr", "Down VFO/MR",
                          RadioSettingValueList(VFOMR,
                                                VFOMR[_settings.dnvfomr]))
        cfg_grp.append(rs)

        rs = RadioSetting("upwork", "Up Work Mode",
                          RadioSettingValueList(WORKMODE,
                                                WORKMODE[_settings.upwork]))
        cfg_grp.append(rs)

        rs = RadioSetting("upmrbank", "Up MR Bank",
                          RadioSettingValueList(MRBANK,
                                                MRBANK[_settings.upmrbank]))
        cfg_grp.append(rs)

        rs = RadioSetting("upmrch", "Up MR Channel",
                          RadioSettingValueInteger(0, 200, _settings.upmrch))
        cfg_grp.append(rs)

        rs = RadioSetting("dnwork", "Down Work Mode",
                          RadioSettingValueList(WORKMODE,
                                                WORKMODE[_settings.dnwork]))
        cfg_grp.append(rs)

        rs = RadioSetting("dnmrbank", "Down MR Bank",
                          RadioSettingValueList(MRBANK,
                                                MRBANK[_settings.dnmrbank]))
        cfg_grp.append(rs)

        rs = RadioSetting("dnmrch", "Down MR Channel",
                          RadioSettingValueInteger(0, 200, _settings.dnmrch))
        cfg_grp.append(rs)

        rs = RadioSetting("main", "Main",
                          RadioSettingValueList(MAIN,
                                                MAIN[_settings.main]))
        cfg_grp.append(rs)

        rs = RadioSetting("pause", "Scan Pause Time",
                          RadioSettingValueList(PAUSE,
                                                PAUSE[_settings.pause]))
        cfg_grp.append(rs)

        rs = RadioSetting("stop", "Function Keys Stop Time",
                          RadioSettingValueList(STOP,
                                                STOP[_settings.stop]))
        cfg_grp.append(rs)

        rs = RadioSetting("backlight", "Backlight",
                          RadioSettingValueList(BACKLIGHT,
                                                BACKLIGHT[_settings.backlight]))
        cfg_grp.append(rs)

        rs = RadioSetting("color", "Backlight Color",
                          RadioSettingValueList(COLOR,
                                                COLOR[_settings.color]))
        cfg_grp.append(rs)

        rs = RadioSetting("vdisplay", "Vice-Machine Display",
                          RadioSettingValueList(VDISPLAY,
                                                VDISPLAY[_settings.vdisplay]))
        cfg_grp.append(rs)

        rs = RadioSetting("voxlevel", "Vox Level",
                          RadioSettingValueList(VOXLEVEL,
                                                VOXLEVEL[_settings.voxlevel]))
        cfg_grp.append(rs)

        rs = RadioSetting("voxdelay", "Vox Delay",
                          RadioSettingValueList(VOXDELAY,
                                                VOXDELAY[_settings.voxdelay]))
        cfg_grp.append(rs)

        rs = RadioSetting("tot", "Time Out Timer",
                          RadioSettingValueList(TOT,
                                                TOT[_settings.tot]))
        cfg_grp.append(rs)

        rs = RadioSetting("tbst", "Tone Burst",
                          RadioSettingValueList(TBST,
                                                TBST[_settings.tbst]))
        cfg_grp.append(rs)

        rs = RadioSetting("monikey", "MONI Key Function",
                          RadioSettingValueList(MONI,
                                                MONI[_settings.monikey]))
        cfg_grp.append(rs)

        if self.MODEL == "TERMN-8R":
            rs = RadioSetting("pf1key", "PF1 Key Function",
                              RadioSettingValueList(PFKEYT,
                                                    PFKEYT[_settings.pf1key]))
            cfg_grp.append(rs)

            rs = RadioSetting("pf2key", "PF2 Key Function",
                              RadioSettingValueList(PFKEYT,
                                                    PFKEYT[_settings.pf2key]))
            cfg_grp.append(rs)

        if self.MODEL == "OBLTR-8R":
            rs = RadioSetting("pf1key", "PF1 Key Function",
                              RadioSettingValueList(PFKEYO,
                                                    PFKEYO[_settings.pf1key]))
            cfg_grp.append(rs)

            rs = RadioSetting("fmam", "PF2 Key Function",
                              RadioSettingValueList(PFKEYO,
                                                    PFKEYO[_settings.fmam]))
            cfg_grp.append(rs)

        rs = RadioSetting("apo", "Automatic Power Off",
                          RadioSettingValueList(APO,
                                                APO[_settings.apo]))
        cfg_grp.append(rs)

        rs = RadioSetting("save", "Power Save",
                          RadioSettingValueList(SAVE,
                                                SAVE[_settings.save]))
        cfg_grp.append(rs)

        rs = RadioSetting("tail", "Tail Eliminator Type",
                          RadioSettingValueList(TAIL,
                                                TAIL[_settings.tail]))
        cfg_grp.append(rs)

        rs = RadioSetting("fmvfomr", "FM VFO/MR",
                          RadioSettingValueList(VFOMR,
                                                VFOMR[_settings.fmvfomr]))
        cfg_grp.append(rs)

        rs = RadioSetting("fmmrch", "FM MR Channel",
                          RadioSettingValueInteger(0, 100, _settings.fmmrch))
        cfg_grp.append(rs)

        rs = RadioSetting("noaa", "NOAA",
                          RadioSettingValueList(NOAA,
                                                NOAA[_settings.noaa]))
        cfg_grp.append(rs)

        rs = RadioSetting("noaach", "NOAA Channel",
                          RadioSettingValueList(NOAACH,
                                                NOAACH[_settings.noaach]))
        cfg_grp.append(rs)

        rs = RadioSetting("part95", "PART95",
                          RadioSettingValueList(PART95,
                                                PART95[_settings.part95]))
        cfg_grp.append(rs)

        rs = RadioSetting("gmrs", "GMRS",
                          RadioSettingValueList(GMRS,
                                                GMRS[_settings.gmrs]))
        cfg_grp.append(rs)

        rs = RadioSetting("murs", "MURS",
                          RadioSettingValueList(MURS,
                                                MURS[_settings.murs]))
        cfg_grp.append(rs)

        for i in range(0, 9):
            val = self._memobj.banklink[i].bank
            rs = RadioSetting("banklink/%i.bank" % i,
                              "Bank Link %i" % (i + 1),
                              RadioSettingValueBoolean(val))
            cfg_grp.append(rs)

        val = self._memobj.banklink[9].bank
        rs = RadioSetting("banklink/9.bank", "Bank Link 0",
                          RadioSettingValueBoolean(val))
        cfg_grp.append(rs)

        rs = RadioSetting("allband", "All Band",
                          RadioSettingValueBoolean(_settings.allband))
        cfg_grp.append(rs)

        rs = RadioSetting("alarmoff", "Alarm Function Off",
                          RadioSettingValueBoolean(_settings.alarmoff))
        cfg_grp.append(rs)

        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
        cfg_grp.append(rs)

        rs = RadioSetting("radio", "Radio",
                          RadioSettingValueBoolean(_settings.radio))
        cfg_grp.append(rs)

        if self.MODEL == "TERMN-8R":
            rs = RadioSetting("keylock", "Keylock",
                              RadioSettingValueBoolean(_settings.keylock))
            cfg_grp.append(rs)

            rs = RadioSetting("fastscan", "Fast Scan",
                              RadioSettingValueBoolean(_settings.fastscan))
            cfg_grp.append(rs)

        if self.MODEL == "OBLTR-8R":
            # "pf2key" is used for OBLTR-8R "keylock"
            rs = RadioSetting("pf2key", "Keylock",
                              RadioSettingValueBoolean(_settings.pf2key))
            cfg_grp.append(rs)

            rs = RadioSetting("fastscano", "Fast Scan",
                              RadioSettingValueBoolean(_settings.fastscano))
            cfg_grp.append(rs)

        rs = RadioSetting("uplink", "Up Bank Link Select",
                          RadioSettingValueBoolean(_settings.uplink))
        cfg_grp.append(rs)

        rs = RadioSetting("downlink", "Down Bank Link Select",
                          RadioSettingValueBoolean(_settings.downlink))
        cfg_grp.append(rs)

        #
        # OEM info
        #

        val = RadioSettingValueString(0, 7, _filter(_oem.model))
        val.set_mutable(False)
        rs = RadioSetting("oem_info.model", "Model", val)
        oem_grp.append(rs)

        val = RadioSettingValueString(0, 9, _filter(_oem.date))
        val.set_mutable(False)
        rs = RadioSetting("oem_info.date", "Date", val)
        oem_grp.append(rs)

        val = RadioSettingValueString(0, 16, _filter(_oem.dealer))
        val.set_mutable(False)
        rs = RadioSetting("oem_info.dealer", "Dealer Code", val)
        oem_grp.append(rs)

        val = RadioSettingValueString(0, 9, _filter(_oem.stockdate))
        val.set_mutable(False)
        rs = RadioSetting("oem_info.stockdate", "Stock Date", val)
        oem_grp.append(rs)

        val = RadioSettingValueString(0, 9, _filter(_oem.selldate))
        val.set_mutable(False)
        rs = RadioSetting("oem_info.selldate", "Sell Date", val)
        oem_grp.append(rs)

        return group

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        return cls._file_ident in filedata[0x10:0x20]

@directory.register
class AnyToneOBLTR8RRadio(AnyToneTERMN8RRadio):
    """AnyTone OBLTR-8R"""
    VENDOR = "AnyTone"
    MODEL = "OBLTR-8R"
    _file_ident = "OBLTR8R"
