# Copyright 2017 Jim Unroe <rock.unroe@gmail.com>
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

import time
import os
import struct
import re
import logging

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct memory {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  lbcd rxtone[2];
  lbcd txtone[2];
  u8 unknown1;
  u8 pttid:2,     // PTT-ID
     unknown2:1,
     signaling:1, // Signaling(ANI)
     unknown3:1,
     bcl:1,       // Busy Channel Lockout
     unknown4:2;
  u8 unknown5:3,
     highpower:1, // Power Level
     isnarrow:1,  // Bandwidth
     scan:1,      // Scan Add
     unknown6:2;
  u8 unknown7;
};

#seekto 0x0010;
struct memory channels[128];

#seekto 0x0810;
struct memory vfo_a;
struct memory vfo_b;

#seekto 0x0830;
struct {
  u8 unknown_0830_1:4,
     color:2,               // Background Color
     dst:1,                 // DTMF Side Tone
     txsel:1;               // Priority TX Channel Select
  u8 scans:2,               // Scan Mode
     unknown_0831:1,
     autolk:1,              // Auto Key Lock
     save:1,                // Battery Save
     beep:1,                // Key Beep
     voice:2;               // Voice Prompt
  u8 vfomr_fm:1,            // FM Radio Display Mode
     led:2,                 // Background Light
     unknown_0832_2:1,
     dw:1,                  // FM Radio Dual Watch
     name:1,                // Display Names
     vfomr_a:2;             // Display Mode A
  u8 opnset:2,              // Power On Message
     unknown_0833_1:3,
     dwait:1,               // Dual Standby
     vfomr_b:2;             // Display Mode B
  u8 mrcha;                 // mr a ch num
  u8 mrchb;                 // mr b ch num
  u8 fmch;                  // fm radio ch num
  u8 unknown_0837_1:1,
     ste:1,                 // Squelch Tail Eliminate
     roger:1,               // Roger Beep
     unknown_0837_2:1,
     vox:4;                 // VOX
  u8 step:4,                // Step
     unknown_0838_1:4;
  u8 squelch;               // Squelch
  u8 tot;                   // Time Out Timer
  u8 rptmod:1,              // Repeater Mode
     volmod:2,              // Volume Mode
     rptptt:1,              // Repeater PTT Switch
     rptspk:1,              // Repeater Speaker
     relay:3;               // Cross Band Repeater Enable
  u8 unknown_083C:4,        // 0x083C
     rptrl:4;               // Repeater TX Delay
  u8 pf1:4,                 // Function Key 1
     pf2:4;                 // Function Key 2
  u8 vot;                   // VOX Delay Time
} settings;

#seekto 0x0848;
struct {
  char line1[7];
} poweron_msg;

struct limit {
  bbcd lower[2];
  bbcd upper[2];
};

#seekto 0x0850;
struct {
  struct limit vhf;
  struct limit uhf;
} limits;

#seekto 0x08D0;
struct {
  char name[7];
  u8 unknown2[1];
} names[128];

#seekto 0x0D20;
u8 usedflags[16];
u8 scanflags[16];

#seekto 0x0FA0;
struct {
  u8 unknown_0FA0_1:4,
     dispab:1,              // select a/b
     unknown_0FA0_2:3;
} settings2;
"""

CMD_ACK = "\x06"
BLOCK_SIZE = 0x10

RT23_POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                     chirp_common.PowerLevel("High", watts=2.50)]


RT23_DTCS = sorted(chirp_common.DTCS_CODES +
                   [17, 50, 55, 135, 217, 254, 305, 645, 765])

RT23_CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + \
    ":;<=>?@ !\"#$%&'()*+,-./"

LIST_COLOR = ["Blue", "Orange", "Purple"]
LIST_LED = ["Off", "On", "Auto"]
LIST_OPNSET = ["Full", "Voltage", "Message"]
LIST_PFKEY = [
    "Radio",
    "Sub-channel Sent",
    "Scan",
    "Alarm",
    "DTMF",
    "Squelch Off Momentarily",
    "Battery Power Indicator",
    "Tone 1750",
    "Tone 2100",
    "Tone 1000",
    "Tone 1450"]
LIST_PTTID = ["Off", "BOT", "EOT", "Both"]
LIST_RPTMOD = ["Single", "Double"]
LIST_RPTRL = ["0.5S", "1.0S", "1.5S", "2.0S", "2.5S", "3.0S", "3.5S", "4.0S",
              "4.5S"]
LIST_SCANS = ["Time Operated", "Carrier Operated", "Search"]
LIST_SIGNALING = ["No", "DTMF"]
LIST_TOT = ["OFF"] + ["%s seconds" % x for x in range(30, 300, 30)]
LIST_TXSEL = ["Edit", "Busy"]
_STEP_LIST = [2.5, 5., 6.25, 10., 12.5, 20., 25., 50.]
LIST_STEP = ["{0:.2f}K".format(x) for x in _STEP_LIST]
LIST_VFOMR = ["VFO", "MR(Frequency)", "MR(Channel #/Name)"]
LIST_VFOMRFM = ["VFO", "Channel"]
LIST_VOICE = ["Off", "Chinese", "English"]
LIST_VOLMOD = ["Off", "Sub", "Main"]
LIST_VOT = ["0.5S", "1.0S", "1.5S", "2.0S", "3.0S"]
LIST_VOX = ["OFF"] + ["%s" % x for x in range(1, 6)]


def _rt23_enter_programming_mode(radio):
    serial = radio.pipe

    magic = "PROIUAM"
    exito = False
    for i in range(0, 5):
        for j in range(0, len(magic)):
            time.sleep(0.005)
            serial.write(magic[j])
        ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    try:
        serial.write("\x02")
        ident = serial.read(8)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ident.startswith("P31183"):
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _rt23_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write("E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _rt23_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, BLOCK_SIZE)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + BLOCK_SIZE + 1)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        chunk = response[4:]

        cs = 0
        for byte in chunk[:-1]:
            cs += ord(byte)
        if ord(chunk[-1]) != (cs & 0xFF):
            raise Exception("Block failed checksum!")

        block_data = chunk[:-1]
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _rt23_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, BLOCK_SIZE)
    data = radio.get_mmap()[block_addr:block_addr + BLOCK_SIZE]
    cs = 0
    for byte in data:
        cs += ord(byte)
    data += chr(cs & 0xFF)

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _rt23_enter_programming_mode(radio)

    data = ""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, BLOCK_SIZE):
        status.cur = addr + BLOCK_SIZE
        radio.status_fn(status)

        block = _rt23_read_block(radio, addr, BLOCK_SIZE)
        if addr == 0 and block.startswith("\xFF" * 6):
            block = "P31183" + "\xFF" * 10
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _rt23_exit_programming_mode(radio)

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _rt23_enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, BLOCK_SIZE):
            status.cur = addr + BLOCK_SIZE
            radio.status_fn(status)
            _rt23_write_block(radio, addr, BLOCK_SIZE)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if len(data) == 0x1000:
        rid = data[0x0000:0x0006]
        return rid == "P31183"
    else:
        return False


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return True


@directory.register
class RT23Radio(chirp_common.CloneModeRadio):
    """RETEVIS RT23"""
    VENDOR = "Retevis"
    MODEL = "RT23"
    BAUD_RATE = 9600

    _ranges = [
               (0x0000, 0x0EC0),
              ]
    _memsize = 0x1000

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_name_length = 7
        rf.valid_characters = RT23_CHARSET
        rf.has_name = True
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = RT23_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]  # 25 KHz, 12.5 KHz.
        rf.memory_bounds = (1, 128)
        rf.valid_tuning_steps = _STEP_LIST
        rf.valid_bands = [
            (136000000, 174000000),
            (400000000, 480000000)]

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        if val.get_raw() == "\xFF\xFF":
            return '', None, None

        val = int(val)
        if val >= 12000:
            a = val - 12000
            return 'DTCS', a, 'R'
        elif val >= 8000:
            a = val - 8000
            return 'DTCS', a, 'N'
        else:
            a = val / 10.0
            return 'Tone', a, None

    def encode_tone(self, memval, mode, value, pol):
        """Parse the tone data to encode from UI to mem"""
        if mode == '':
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            flag = 0x80 if pol == 'N' else 0xC0
            memval.set_value(value)
            memval[1].set_bits(flag)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        _mem = self._memobj.channels[number-1]
        _nam = self._memobj.names[number - 1]
        mem.number = number
        bitpos = (1 << ((number - 1) % 8))
        bytepos = ((number - 1) / 8)
        _scn = self._memobj.scanflags[bytepos]
        _usd = self._memobj.usedflags[bytepos]
        isused = bitpos & int(_usd)
        isscan = bitpos & int(_scn)

        if not isused:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == "\xFF\xFF\xFF\xFF":
            mem.empty = True
            return mem

        if _mem.get_raw() == ("\xFF" * 16):
            LOG.debug("Initializing empty memory")
            _mem.set_raw("\x00" * 16)

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if _mem.get_raw()[4] == "\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if _split(self.get_features(), mem.freq, int(_mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        mem.mode = _mem.isnarrow and "NFM" or "FM"

        rxtone = txtone = None
        txtone = self.decode_tone(_mem.txtone)
        rxtone = self.decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.power = RT23_POWER_LEVELS[_mem.highpower]

        if not isscan:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(
                              LIST_PTTID, LIST_PTTID[_mem.pttid]))
        mem.extra.append(rs)

        rs = RadioSetting("signaling", "Optional Signaling",
                          RadioSettingValueList(LIST_SIGNALING,
                              LIST_SIGNALING[_mem.signaling]))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
        _mem = self._memobj.channels[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]
        bitpos = (1 << ((mem.number - 1) % 8))
        bytepos = ((mem.number - 1) / 8)
        _scn = self._memobj.scanflags[bytepos]
        _usd = self._memobj.usedflags[bytepos]

        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            _nam.name = ("\xFF" * 7)
            _usd &= ~bitpos
            _scn &= ~bitpos
            return
        else:
            _usd |= bitpos

        if _mem.get_raw() == ("\xFF" * 16):
            LOG.debug("Initializing empty memory")
            _mem.set_raw("\x00" * 16)
            _scn |= bitpos

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
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

        _mem.scan = mem.skip != "S"
        if mem.skip == "S":
            _scn &= ~bitpos
        else:
            _scn |= bitpos
        _mem.isnarrow = mem.mode == "NFM"

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.txtone, txmode, txtone, txpol)
        self.encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        _mem.highpower = mem.power == RT23_POWER_LEVELS[1]

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        other = RadioSettingGroup("other", "Other Settings")
        workmode = RadioSettingGroup("workmode", "Workmode Settings")
        fmradio = RadioSettingGroup("fmradio", "FM Radio Settings")
        top = RadioSettings(basic, advanced, other, workmode, fmradio)

        save = RadioSetting("save", "Battery Saver",
                            RadioSettingValueBoolean(_settings.save))
        basic.append(save)

        vox = RadioSetting("vox", "VOX Gain",
                           RadioSettingValueList(
                               LIST_VOX, LIST_VOX[_settings.vox]))
        basic.append(vox)

        squelch = RadioSetting("squelch", "Squelch Level",
                               RadioSettingValueInteger(
                                   0, 9, _settings.squelch))
        basic.append(squelch)

        relay = RadioSetting("relay", "Repeater",
                             RadioSettingValueBoolean(_settings.relay))
        basic.append(relay)

        tot = RadioSetting("tot", "Time-out timer", RadioSettingValueList(
                           LIST_TOT, LIST_TOT[_settings.tot]))
        basic.append(tot)

        beep = RadioSetting("beep", "Key Beep",
                            RadioSettingValueBoolean(_settings.beep))
        basic.append(beep)

        color = RadioSetting("color", "Background Color", RadioSettingValueList(
                             LIST_COLOR, LIST_COLOR[_settings.color - 1]))
        basic.append(color)

        vot = RadioSetting("vot", "VOX Delay Time", RadioSettingValueList(
                           LIST_VOT, LIST_VOT[_settings.vot]))
        basic.append(vot)

        dwait = RadioSetting("dwait", "Dual Standby",
                             RadioSettingValueBoolean(_settings.dwait))
        basic.append(dwait)

        led = RadioSetting("led", "Background Light", RadioSettingValueList(
                           LIST_LED, LIST_LED[_settings.led]))
        basic.append(led)

        voice = RadioSetting("voice", "Voice Prompt", RadioSettingValueList(
                             LIST_VOICE, LIST_VOICE[_settings.voice]))
        basic.append(voice)

        roger = RadioSetting("roger", "Roger Beep",
                             RadioSettingValueBoolean(_settings.roger))
        basic.append(roger)

        autolk = RadioSetting("autolk", "Auto Key Lock",
                              RadioSettingValueBoolean(_settings.autolk))
        basic.append(autolk)

        opnset = RadioSetting("opnset", "Open Mode Set",
                              RadioSettingValueList(
                                  LIST_OPNSET, LIST_OPNSET[_settings.opnset]))
        basic.append(opnset)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        _msg = self._memobj.poweron_msg
        ponmsg = RadioSetting("poweron_msg.line1", "Power-On Message",
                              RadioSettingValueString(
                                  0, 7, _filter(_msg.line1)))
        basic.append(ponmsg)


        scans = RadioSetting("scans", "Scan Mode", RadioSettingValueList(
                             LIST_SCANS, LIST_SCANS[_settings.scans]))
        basic.append(scans)

        dw = RadioSetting("dw", "FM Radio Dual Watch",
                          RadioSettingValueBoolean(_settings.dw))
        basic.append(dw)

        name = RadioSetting("name", "Display Names",
                            RadioSettingValueBoolean(_settings.name))
        basic.append(name)

        rptrl = RadioSetting("rptrl", "Repeater TX Delay", 
                             RadioSettingValueList(LIST_RPTRL, LIST_RPTRL[
                                 _settings.rptrl]))
        basic.append(rptrl)

        rptspk = RadioSetting("rptspk", "Repeater Speaker",
                              RadioSettingValueBoolean(_settings.rptspk))
        basic.append(rptspk)

        rptptt = RadioSetting("rptptt", "Repeater PTT Switch",
                            RadioSettingValueBoolean(_settings.rptptt))
        basic.append(rptptt)

        rptmod = RadioSetting("rptmod", "Repeater Mode",
                              RadioSettingValueList(
                                  LIST_RPTMOD, LIST_RPTMOD[_settings.rptmod]))
        basic.append(rptmod)

        volmod = RadioSetting("volmod", "Volume Mode",
                              RadioSettingValueList(
                                  LIST_VOLMOD, LIST_VOLMOD[_settings.volmod]))
        basic.append(volmod)

        dst = RadioSetting("dst", "DTMF Side Tone",
                            RadioSettingValueBoolean(_settings.dst))
        basic.append(dst)

        txsel = RadioSetting("txsel", "Priority TX Channel",
                             RadioSettingValueList(
                                 LIST_TXSEL, LIST_TXSEL[_settings.txsel]))
        basic.append(txsel)

        ste = RadioSetting("ste", "Squelch Tail Eliminate",
                           RadioSettingValueBoolean(_settings.ste))
        basic.append(ste)

        #advanced
        if _settings.pf1 > 0x0A:
            val = 0x00
        else:
            val = _settings.pf1
        pf1 = RadioSetting("pf1", "PF1 Key",
                           RadioSettingValueList(
                               LIST_PFKEY, LIST_PFKEY[val]))
        advanced.append(pf1)

        if _settings.pf2 > 0x0A:
            val = 0x00
        else:
            val = _settings.pf2
        pf2 = RadioSetting("pf2", "PF2 Key",
                           RadioSettingValueList(
                               LIST_PFKEY, LIST_PFKEY[val]))
        advanced.append(pf2)

        # other
        _limit = str(int(_mem.limits.vhf.lower) / 10)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        rs = RadioSetting("limits.vhf.lower", "VHF low", val)
        other.append(rs)

        _limit = str(int(_mem.limits.vhf.upper) / 10)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        rs = RadioSetting("limits.vhf.upper", "VHF high", val)
        other.append(rs)

        _limit = str(int(_mem.limits.uhf.lower) / 10)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        rs = RadioSetting("limits.uhf.lower", "UHF low", val)
        other.append(rs)

        _limit = str(int(_mem.limits.uhf.upper) / 10)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        rs = RadioSetting("limits.uhf.upper", "UHF high", val)
        other.append(rs)

        #work mode
        vfomr_a = RadioSetting("vfomr_a", "Display Mode A",
                               RadioSettingValueList(
                                   LIST_VFOMR, LIST_VFOMR[_settings.vfomr_a]))
        workmode.append(vfomr_a)

        vfomr_b = RadioSetting("vfomr_b", "Display Mode B",
                               RadioSettingValueList(
                                   LIST_VFOMR, LIST_VFOMR[_settings.vfomr_b]))
        workmode.append(vfomr_b)

        mrcha = RadioSetting("mrcha", "Channel # A",
                             RadioSettingValueInteger(
                                 1, 128, _settings.mrcha))
        workmode.append(mrcha)

        mrchb = RadioSetting("mrchb", "Channel # B",
                             RadioSettingValueInteger(
                                 1, 128, _settings.mrchb))
        workmode.append(mrchb)

        #fm radio
        vfomr_fm = RadioSetting("vfomr_fm", "FM Radio Display Mode",
                                RadioSettingValueList(
                                    LIST_VFOMRFM, LIST_VFOMRFM[
                                        _settings.vfomr_fm]))
        fmradio.append(vfomr_fm)

        fmch = RadioSetting("fmch", "FM Radio Channel #",
                            RadioSettingValueInteger(
                                 1, 25, _settings.fmch))
        fmradio.append(fmch)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "color":
                        setattr(obj, setting, int(element.value) + 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) in [0x1000, ]:
            match_size = True

        # testing the model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False
