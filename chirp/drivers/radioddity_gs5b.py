# Modified  2023 Dave Liske <dave@micuisine.com> for Radioddity GS-5B
# from ga510.py, copyright 2011 Dan Smith <dsmith@danplanet.com>
# Memory map and some code snippets from senhaix_8800.py Python 2.7 script,
# developed 2020 by Jiauxn Yang <jiaxun.yang@flygoat.com>
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

import logging
import struct

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import RadioSetting, RadioSettingGroup, RadioSettings
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueList
from chirp.settings import RadioSettingValueInteger, RadioSettingValueString
from chirp.settings import RadioSettingValueFloat, RadioSettingValueMap, RadioSettings

LOG = logging.getLogger(__name__)

try:
    from builtins import bytes
    has_future = True
except ImportError:
    has_future = False
    LOG.debug('python-future package is not available; '
              '%s requires it' % __name__)

# GS-5B also has DTCS code 645
DTCS_CODES = list(sorted(chirp_common.DTCS_CODES + [645]))

DTMFCHARS = '0123456789ABCD*#'

MEM_SIZE = 0x1c00
CMD_ACK = "\x06"
ACK_RETRY = 10
BLOCK_SIZE_RX = 64
BLOCK_SIZE_TX = 32
EEPROM_TX_SKIP = [(0x820, 0xc00), (0x1400, 0x1a00)]


def reset(radio):
    radio.pipe.write(b'E')
    

def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the header format"""
    frame = struct.pack(">BHB", ord(cmd), addr, length)
    # add the data if set
    if len(data) != 0:
        frame += data

    return frame


def _recv_block(radio, addr, blocksize):
    """Receive a block from the radio ROM"""
    radio.pipe.read(_make_frame(b'R', addr, blocksize))

    # read 4 bytes of header
    hdr = radio.pipe.read(4)

    # read data
    data = radio.pipe.read(blocksize)

    # DEBUG
    LOG.debug("Response:")
    LOG.debug("\n " + util.hexprint(data))

    c, a, l = struct.unpack(">BHB", hdr)
    if a != addr or l != blocksize or c != ord("R"):
        LOG.error("Invalid answer for block 0x%04x:" % addr)
        LOG.error("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Unknown response from the radio")

    return data
    

def start_program(radio):
    reset(radio)
    radio.pipe.read(256)
    radio.pipe.write(radio._magic)
    ack = radio.pipe.read(256)
    if not ack.endswith(b'\x06'):
        LOG.debug('Ack was %r' % ack)
        raise errors.RadioError('Radio did not respond to clone request. Please try again.')

    radio.pipe.write(b'F')

    ident = radio.pipe.read(8)
    LOG.debug('Radio ident string is %r' % ident)

    return ident


def do_download(radio):
    ident = start_program(radio)

    s = chirp_common.Status()
    s.msg = 'Downloading'
    s.max = 0x1c00

    data = bytes()
    for addr in range(0, 0x1c40, 0x40):
        cmd = struct.pack('>cHB', b'R', addr, 0x40)
        LOG.debug('Reading block at %04x: %r' % (addr, cmd))
        radio.pipe.write(cmd)

        block = radio.pipe.read(0x44)
        header = block[:4]
        rcmd, raddr, rlen = struct.unpack('>BHB', header)
        block = block[4:]
        if raddr != addr:
            raise errors.RadioError('Radio send address %04x, expected %04x' %
                                    (raddr, addr))
        if rlen != 0x40 or len(block) != 0x40:
            raise errors.RadioError('Radio sent %02x (%02x) bytes, '
                                    'expected %02x' % (rlen, len(block), 0x40))

        data += block

        s.cur = addr
        radio.status_fn(s)

    reset(radio)

    return data


def do_upload(radio):
    ident = start_program(radio)

    s = chirp_common.Status()
    s.msg = 'Uploading'
    s.max = 0x1C00

    # The factory software downloads 0x40 for the block
    # at 0x1C00, but only uploads 0x20 there. Mimic that
    # here.
    for addr in range(0, 0x1C20, 0x20):
        cmd = struct.pack('>cHB', b'W', addr, 0x20)
        LOG.debug('Writing block at %04x: %r' % (addr, cmd))
        block = radio._mmap[addr:addr + 0x20]
        radio.pipe.write(cmd)
        radio.pipe.write(block)

        ack = radio.pipe.read(1)
        if ack != b'\x06':
            raise errors.RadioError('Radio refused block at addr %04x' % addr)

        s.cur = addr
        radio.status_fn(s)

MEM_FORMAT = """
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 pttid;
  u8 power_lvl;
  u8 spare1:1,
     narrow:1,
     spare0:2,
     bcl:1,
     scan:1,
     allow_tx:1,
     fhss:1;
} memory[128];

#seekto 0xc00;
struct {
  char name[16];
} names[128];

#seekto 0x1a00;
struct {
  u8 squelch;
  u8 battery_saver;
  u8 vox;
  u8 auto_bl;
  u8 tdr;
  u8 tot;
  u8 beep;
  u8 voice;
  u8 power_on;
  u8 dtmfst;
  u8 scan_mode;
  u8 pttid;
  u8 pttlt;
  u8 mdfa;
  u8 mdfb;
  u8 bcl;

  u8 autolk;
  u8 almod;
  u8 alsnd;
  u8 tx_under_tdr_start;
  u8 ste;
  u8 rpste;
  u8 rptrl;
  u8 roger;
  u8 unknown;
  u8 fmradio;
  u8 workmodeb:4,
     workmodea:4;
  u8 keylock;
  u8 unknown1[4];

  u8 voxdelay;
  u8 menu_timeout;
  u8 micgain;
} settings;

#seekto 0x1a40;
struct {
  u8 freq[8];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown[2];
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown1;
  u8 txpower;
  u8 widenarr:1,
     unknown2:4,
     fhss:1,
     unknown3:2;
  u8 band;
  u8 unknown4:5,
     step:3;
  u8 unknown5;
  u8 offset[6];
} vfoa;

#seekto 0x1a60;
struct {
  u8 freq[8];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown[2];
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown1;
  u8 txpower;
  u8 widenarr:1,
     unknown2:4,
     fhss:1,
     unknown3:2;
  u8 band;
  u8 unknown4:5,
     step:3;
  u8 unknown5;
  u8 offset[6];
} vfob;

#seekto 0x1a80;
struct {
    u8 sidekey;
    u8 sidekeyl;
} keymaps;

#seekto 0x1b00;
struct {
  u8 code[5];
  u8 unused[11];
} pttid[15];

struct {
  u8 code[5];
  u8 groupcode;
  u8 aniid;
  u8 dtmfon;
  u8 dtmfoff;
} anicode;

"""

POWER_LEVELS = [chirp_common.PowerLevel("High (5W)", watts=5.00),
                     chirp_common.PowerLevel("Low (1W)",  watts=1.00)]

DTCS = sorted(chirp_common.DTCS_CODES + [645])

AUTOBL_LIST = ["OFF", "5 sec", "10 sec", "15 sec", "20 sec", "30 sec", "1 min", "2 min", "3 min"]
TOT_LIST = ["OFF"] + ["%s sec" % x for x in range(30, 270, 30)]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 4)]
BANDWIDTH_LIST = ["Wide", "Narrow"]
POWER_ON_LIST = ["Radioddity Logo", "Welcome", "Default Character"]
DTMFST_LIST = ["OFF", "DT-ST", "ANI-ST", "DT+ANI"]
SCAN_MODE_LIST = ["TO", "CO", "SE"]
PTTID_LIST = ["OFF", "BOT", "EOT", "Both"]
PTTLT_LIST = ["%s ms" % x for x in range(0, 31)]
MODE_LIST = ["CH + Name", "CH + Frequency"]
ALMOD_LIST = ["SITE", "TOME", "CODE"]
RPSTE_LIST = ["OFF"] + ["%s" % x for x in range(1, 11)]
STEDELAY_LIST = ["%s ms" % x for x in range(0, 1100, 100)]
WORKMODE_LIST = ["VFO", "CH"]
VOX_DELAY_LIST = ["%s ms" % x for x in range(500, 2100, 100)]
MENU_TIMEOUT_LIST = ["%s sec" % x for x in range(5, 65, 5)]
MICGAIN_LIST = ["%s" % x for x in range(1, 6, 1)]
DTMFSPEED_LIST = ["%s ms" % x for x in range(60, 2000, 20)]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 128)]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
STEP_LIST = [str(x) for x in STEPS]
TXPOWER_LIST = ["High (5W)", "Low (1W)"]
SHIFTD_LIST = ["Off", "+", "-"]
KEY_FUNCTIONS = [("Monitor", 5), ("Broadcast FM Radio", 7), ("Tx Power Switch", 10), ("Scan", 28), ("Match", 29)]


@directory.register
class RadioddityGS5BRadio(chirp_common.CloneModeRadio):
    VENDOR = 'Radioddity'
    MODEL = 'GS-5B'
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = False
    POWER_LEVELS = [
        chirp_common.PowerLevel('L', watts=1),
        chirp_common.PowerLevel('H', watts=5)]

    _magic = b'PROGROMSHXU'

    _gmrs = False

    def sync_in(self):
        try:
            data = do_download(self)
            self._mmap = memmap.MemoryMapBytes(data)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('General failure')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('General failure')
            raise errors.RadioError('Failed to upload to radio: %s' % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 127)
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_settings = True
        rf.has_bank = False
        rf.has_sub_devices = False
        rf.has_dtcs_polarity = True
        rf.has_rx_dtcs = True
        rf.can_odd_split = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS', 'Tone->DTCS',
                                'DTCS->Tone', '->Tone', 'DTCS->DTCS']
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 12.5, 10.0, 15.0, 20.0,
                                 25.0, 50.0, 100.0]
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 10
        rf.valid_characters = ('ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                               'abcdefghijklmnopqrstuvwxyz'
                               '0123456789'
                               '!"#$%&\'()~+-,./:;<=>?@[\\]^`{}*| ')
                               
        """ A valid_band of (0, 0.1) prevents an out-of-range error on the """
        """ Memory tab if the frequency is set to 0.000000 by another field. """
        """ The GS-5B is VHF/UHF, and cannot be tuned < 100kHz regardless """
        rf.valid_bands = [(0, 0.1),
                          (136000000, 174000000),
                          (400000000, 480000000)]
        return rf

    def get_raw_memory(self, num):
        return repr(self._memobj.memories[num]) + repr(self._memobj.names[num])

    @staticmethod
    def _decode_tone(toneval):
        if toneval in (0, 0xFFFF):
            LOG.debug('no tone value: %s' % toneval)
            return '', None, None
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

    @staticmethod
    def _encode_tone(mode, val, pol):
        if not mode:
            return 0x0000
        elif mode == 'Tone':
            return int(val * 10)
        elif mode == 'DTCS':
            index = DTCS_CODES.index(val)
            if pol == 'R':
                index += len(DTCS_CODES)
            index += 1
            LOG.debug('Encoded dtcs %s/%s to %04x' % (val, pol, index))
            return index
        else:
            raise errors.RadioError('Unsupported tone mode %r' % mode)

    def _is_txinh(self, _mem):
        return _mem.allow_tx == False

    def _get_mem(self, number):
        return self._memobj.memory[number]

    def _get_nam(self, number):
        return self._memobj.names[number]

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        _mem = self._get_mem(number)
        _nam = self._get_nam(number)

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = DTCS[index]
        else:
            LOG.warn("Bug: txtone is %04x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.rx_dtcs = DTCS[index]
        else:
            LOG.warn("Bug: rxtone is %04x" % _mem.rxtone)

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        mem.power = POWER_LEVELS[_mem.power_lvl]

        mem.mode = _mem.narrow and "NFM" or "FM"

        return mem

    def _set_mem(self, number):
        return self._memobj.memories[number]

    def _set_nam(self, number):
        return self._memobj.names[number]

    def set_memory(self, mem):
        _mem = self._get_mem(mem.number)
        _nam = self._get_nam(mem.number)

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

        was_empty = False
        # same method as used in get_memory to find
        # out whether a raw memory is empty
        if _mem.get_raw()[0] == "\xff":
            was_empty = True
            LOG.debug("Radioddity GS-5B: this mem was empty")
        else:
            LOG.debug("mMm was not empty, memorize extra-settings")
            prev_bcl = _mem.bcl.get_value()
            prev_scode = _mem.scode.get_value()
            prev_pttid = _mem.pttid.get_value()

        _mem.set_raw("\x00" * 16)

        _mem.rxfreq = mem.freq / 10

        _mem.allow_tx = True
        if mem.duplex == "off":
            _mem.allow_tx = False
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = DTCS.index(mem.dtcs) + 1
            _mem.rxtone = DTCS.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = DTCS.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = DTCS.index(mem.rx_dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.narrow = mem.mode == "NFM"
        _mem.power_lvl = POWER_LEVELS.index(mem.power)

        if not was_empty:
            # restoring old extra-settings
            _mem.bcl.set_value(prev_bcl)
            _mem.scode.set_value(prev_scode)
            _mem.pttid.set_value(prev_pttid)

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        _ani = self._memobj.anicode
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _keymaps = self._memobj.keymaps

        basic = RadioSettingGroup('basic', 'Basic')
        adv = RadioSettingGroup('advanced', 'Advanced')
        vfo = RadioSettingGroup('vfo', 'VFOs')
        dtmf = RadioSettingGroup('dtmf', 'DTMF')

        group = RadioSettings(basic, adv, vfo, dtmf)

        basic.append(RadioSetting('tot', "TOT (Timeout)",
                            RadioSettingValueList(
                                TOT_LIST,
                                TOT_LIST[_settings.tot])))
        basic.append(
            RadioSetting('squelch', 'Squelch Level',
                         RadioSettingValueInteger(0, 9, int(_settings.squelch))))

        basic.append(RadioSetting('vox', "VOX",
                            RadioSettingValueList(
                                VOX_LIST,
                                VOX_LIST[_settings.vox])))

        basic.append(RadioSetting('voxdelay', "VOX Delay",
                            RadioSettingValueList(
                                VOX_DELAY_LIST,
                                VOX_DELAY_LIST[_settings.voxdelay])))
                                
        basic.append(
            RadioSetting('voice', 'Voice Prompt',
                         RadioSettingValueBoolean(
                             int(_settings.voice))))

        basic.append(RadioSetting('auto_bl', "Auto Backlight",
                            RadioSettingValueList(
                                AUTOBL_LIST,
                                AUTOBL_LIST[_settings.auto_bl])))

        basic.append(RadioSetting("workmodea", "Work Mode (A)",
                            RadioSettingValueList(
                                WORKMODE_LIST,
                                WORKMODE_LIST[_settings.workmodea])))

        basic.append(RadioSetting("workmodeb", "Work Mode (B)",
                            RadioSettingValueList(
                                WORKMODE_LIST,
                                WORKMODE_LIST[_settings.workmodeb])))

        basic.append(RadioSetting("dtmfst", "DTMF ST",
                            RadioSettingValueList(
                                DTMFST_LIST,
                                DTMFST_LIST[_settings.dtmfst])))

        basic.append(RadioSetting("scan_mode", "Scan Mode",
                            RadioSettingValueList(
                                SCAN_MODE_LIST,
                                SCAN_MODE_LIST[_settings.scan_mode])))
                                
        basic.append(RadioSetting('battery_saver', 'Battery Save',
                         RadioSettingValueBoolean(
                             int(_settings.battery_saver))))

        basic.append(RadioSetting('mdfa', "CH A Display",
                            RadioSettingValueList(
                                MODE_LIST,
                                MODE_LIST[_settings.mdfa])))

        basic.append(RadioSetting('mdfb', "CH B Display",
                            RadioSettingValueList(
                                MODE_LIST,
                                MODE_LIST[_settings.mdfb])))

        adv.append(
            RadioSetting('pttid', "PTT-ID",
                            RadioSettingValueList(
                                PTTID_LIST,
                                PTTID_LIST[_settings.pttid])))
                                
        adv.append(
            RadioSetting('pttlt', "PTT Delay",
                            RadioSettingValueList(
                                PTTLT_LIST,
                                PTTLT_LIST[_settings.pttlt])))

        for entry in KEY_FUNCTIONS:
            if entry[1] == _keymaps.sidekey:
                rs = RadioSetting('keymaps.sidekey', "Side Key Short Press",
                                    RadioSettingValueMap(KEY_FUNCTIONS, _keymaps.sidekey))
        adv.append(rs)

        for entry in KEY_FUNCTIONS:
            if entry[1] == _keymaps.sidekeyl:
                rs = RadioSetting('keymaps.sidekeyl', "Side Key Long Press",
                                RadioSettingValueMap(KEY_FUNCTIONS, _keymaps.sidekeyl))
                adv.append(rs)
        
        adv.append(
            RadioSetting('ste', 'Tail Noise Clear',
                         RadioSettingValueBoolean(
                             int(_settings.ste))))

        adv.append(
            RadioSetting('rpste', "RPT Noise Clear(ms)",
                            RadioSettingValueList(
                                RPSTE_LIST,
                                RPSTE_LIST[_settings.rpste])))

        adv.append(
            RadioSetting('rptrl', "RPT Noise Delay(ms)",
                            RadioSettingValueList(
                                STEDELAY_LIST,
                                STEDELAY_LIST[_settings.rptrl])))

        adv.append(
            RadioSetting('power_on', "Power-On Icon",
                            RadioSettingValueList(
                                POWER_ON_LIST,
                                POWER_ON_LIST[_settings.power_on])))

        adv.append(
            RadioSetting('menu_timeout', "Menu Timeout",
                            RadioSettingValueList(
                                MENU_TIMEOUT_LIST,
                                MENU_TIMEOUT_LIST[_settings.menu_timeout])))

        adv.append(
            RadioSetting('micgain', "Mic Gain",
                            RadioSettingValueList(
                                MICGAIN_LIST,
                                MICGAIN_LIST[_settings.micgain])))
        adv.append(
            RadioSetting('alsnd', 'Alarm Sound',
                         RadioSettingValueBoolean(
                             int(_settings.alsnd))))

        adv.append(
            RadioSetting('almod', "Alarm Mode",
                            RadioSettingValueList(
                                ALMOD_LIST,
                                ALMOD_LIST[_settings.almod])))
                                
        adv.append(
            RadioSetting('roger', 'Roger',
                         RadioSettingValueBoolean(
                             int(_settings.roger))))
                
        adv.append(
            RadioSetting('tdr', 'TDR',
                         RadioSettingValueBoolean(
                             int(_settings.tdr))))
                             
        adv.append(
            RadioSetting('keylock', 'KB Lock',
                         RadioSettingValueBoolean(
                             int(_settings.keylock))))
                             
        adv.append(
            RadioSetting('autolk', 'Auto Lock',
                         RadioSettingValueBoolean(
                             int(_settings.autolk))))
                             
        adv.append(
            RadioSetting('fmradio', 'FM Radio Disabled',
                         RadioSettingValueBoolean(
                             int(_settings.fmradio))))
                             
        adv.append(
            RadioSetting('bcl', 'BCL',
                         RadioSettingValueBoolean(
                             int(_settings.bcl))))
                             
        adv.append(
            RadioSetting('beep', 'Beep',
                         RadioSettingValueBoolean(
                             int(_settings.beep))))
        
        def convert_bytes_to_freq(bytes):
            real_freq = 0
            for byte in bytes:
                real_freq = (real_freq * 10) + byte
            return chirp_common.format_freq(real_freq * 10)

        def my_validate(value):
            value = chirp_common.parse_freq(value)
            if 17400000 <= value and value < 40000000:
                msg = ("Can't be between 174.00000-400.00000")
                raise InvalidValueError(msg)
            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            obj.band = value >= 40000000
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(0, 10,
                                        convert_bytes_to_freq(_vfoa.freq))
        val1a.set_validate_callback(my_validate)
        rs = RadioSetting("vfoa.freq", "VFO A Frequency", val1a)
        rs.set_apply_callback(apply_freq, _vfoa)
        
        vfo.append(rs)

        val1b = RadioSettingValueString(0, 10,
                                        convert_bytes_to_freq(_vfob.freq))
        val1b.set_validate_callback(my_validate)
        rs = RadioSetting("vfob.freq", "VFO B Frequency", val1b)
        rs.set_apply_callback(apply_freq, _vfob)
        
        vfo.append(rs)
        
        """ Do we need txtone and rxtone here? """

        rs = RadioSetting("vfoa.sftd", "VFO A Shift",
                            RadioSettingValueList(
                                SHIFTD_LIST, SHIFTD_LIST[_vfoa.sftd]))
        vfo.append(rs)

        rs = RadioSetting("vfob.sftd", "VFO B Shift",
                            RadioSettingValueList(
                                SHIFTD_LIST, SHIFTD_LIST[_vfob.sftd]))
        vfo.append(rs)

        def convert_bytes_to_offset(bytes):
            real_offset = 0
            for byte in bytes:
                real_offset = (real_offset * 10) + byte
            return chirp_common.format_freq(real_offset * 100)

        def apply_offset(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 100
            for i in range(5, -1, -1):
                obj.offset[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(
            0, 10, convert_bytes_to_offset(_vfoa.offset))
        rs = RadioSetting("vfoa.offset",
                            "VFO A Offset (0.0-999.999)", val1a)
        rs.set_apply_callback(apply_offset, _vfoa)
        
        vfo.append(rs)

        val1b = RadioSettingValueString(
            0, 10, convert_bytes_to_offset(_vfob.offset))
        rs = RadioSetting("vfob.offset",
                            "VFO B Offset (0.0-999.999)", val1b)
        rs.set_apply_callback(apply_offset, _vfob)
        
        vfo.append(rs)

        rs = RadioSetting("vfoa.txpower", "VFO A Power",
                            RadioSettingValueList(
                                TXPOWER_LIST,
                                TXPOWER_LIST[_vfoa.txpower]))
        vfo.append(rs)

        rs = RadioSetting("vfob.txpower", "VFO B Power",
                            RadioSettingValueList(
                                TXPOWER_LIST,
                                TXPOWER_LIST[_vfob.txpower]))
        vfo.append(rs)

        rs = RadioSetting("vfoa.widenarr", "VFO A Bandwidth",
                            RadioSettingValueList(
                                BANDWIDTH_LIST,
                                BANDWIDTH_LIST[_vfoa.widenarr]))
        vfo.append(rs)

        rs = RadioSetting("vfob.widenarr", "VFO B Bandwidth",
                            RadioSettingValueList(
                                BANDWIDTH_LIST,
                                BANDWIDTH_LIST[_vfob.widenarr]))
        vfo.append(rs)

        rs = RadioSetting("vfoa.scode", "VFO A PTT-ID",
                            RadioSettingValueList(
                                PTTIDCODE_LIST, PTTIDCODE_LIST[_vfoa.scode]))
        vfo.append(rs)

        rs = RadioSetting("vfob.scode", "VFO B PTT-ID",
                            RadioSettingValueList(
                                PTTIDCODE_LIST, PTTIDCODE_LIST[_vfob.scode]))
        vfo.append(rs)

        rs = RadioSetting("vfoa.step", "VFO A Tuning Step",
                            RadioSettingValueList(
                                STEP_LIST, STEP_LIST[_vfoa.step]))
        vfo.append(rs)
        
        rs = RadioSetting("vfob.step", "VFO B Tuning Step",
                            RadioSettingValueList(
                                STEP_LIST, STEP_LIST[_vfob.step]))
        vfo.append(rs)
                             
        vfo.append(
            RadioSetting('vfoa.fhss', 'VFO A FHSS',
                         RadioSettingValueBoolean(
                             int(_vfoa.fhss))))
                             
        vfo.append(
            RadioSetting('vfob.fhss', 'VFO B FHSS',
                         RadioSettingValueBoolean(
                             int(_vfob.fhss))))

        for i in range(1, 16):
            cur = ''.join(
                DTMFCHARS[i]
                for i in self._memobj.pttid[i - 1].code if int(i) < 0xF)
            dtmf.append(
                RadioSetting(
                    'pttid.code@%i' % i, 'DTMF Group %i' % i,
                    RadioSettingValueString(0, 5, cur,
                                            autopad=False,
                                            charset=DTMFCHARS)))
                                            
        cur = ''.join(
            '%X' % i
            for i in self._memobj.anicode.code if int(i) < 0xE)

        anicode = self._memobj.anicode
        
        _codeobj = self._memobj.anicode.code
        _code = "".join([DTMFCHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(DTMFCHARS)
        rs = RadioSetting("anicode.code", "ANI Code", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 5):
                try:
                    code.append(DTMFCHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code
        rs.set_apply_callback(apply_code, _ani)
        
        dtmf.append(rs)

        dtmf.append(
            RadioSetting(
                "anicode.groupcode", "Group Code",
                RadioSettingValueList(
                    list(DTMFCHARS),
                    DTMFCHARS[int(anicode.groupcode)])))
                    
        cur = int(anicode.dtmfon) * 10 + 80
        
        dtmf.append(
            RadioSetting(
                "anicode.dtmfon", "DTMF Speed (on time in ms)",
                RadioSettingValueInteger(60, 2000, cur, 10)))
                
        cur = int(anicode.dtmfoff) * 10 + 80
        
        dtmf.append(
            RadioSetting(
                "anicode.dtmfoff", "DTMF Speed (off time in ms)",
                RadioSettingValueInteger(60, 2000, cur, 10)))

        top = RadioSettings(basic, adv, vfo, dtmf)
        
        return top
    

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                    self.set_settings(element)
                    continue
            else:
                try:
                    name = element.get_name()
                    LOG.debug("Setting %s" % (name))
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
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise

    def _set_setting(self, setting):
        key = setting.get_name()
        val = setting.value

        setattr(self._memobj.settings, key, val)

    def _set_anicode(self, setting):
        name = setting.get_name().split('.', 1)[1]
        if name == 'code':
            val = [DTMFCHARS.index(c) for c in str(setting.value)]
            for i in range(0, 5):
                try:
                    value = val[i]
                except IndexError:
                    value = 0xFF
                self._memobj.anicode.code[i] = value
        elif name.startswith('dtmfo'):
            setattr(self._memobj.anicode, name,
                    (int(setting.value) - 80) // 10)
        else:
            setattr(self._memobj.anicode, name, int(setting.value))

    def _set_dtmfcode(self, setting):
        index = int(setting.get_name().split('@', 1)[1]) - 1
        val = [DTMFCHARS.index(c) for c in str(setting.value)]
        for i in range(0, 5):
            try:
                value = val[i]
            except IndexError:
                value = 0xFF
            self._memobj.anicode[index].code[i] = value

    def _set_skey(self, setting):
        if setting.has_apply_callback():
            LOG.debug("Using apply callback")
            setting.run_apply_callback()

@directory.register
class Senhaix8800Radio(RadioddityGS5BRadio):
    """Senhaix 8800"""
    VENDOR = "Senhaix"
    MODEL = "8800"
    
@directory.register
class SignusXTR5Radio(RadioddityGS5BRadio):
    """Signus XTR-5"""
    VENDOR = "Signus"
    MODEL = "XTR-5"
    
@directory.register
class AnysecuAC580Radio(RadioddityGS5BRadio):
    """Anysecu AC-580"""
    VENDOR = "Anysecu"
    MODEL = "AC-580"