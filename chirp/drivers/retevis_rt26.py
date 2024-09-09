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

import struct
import logging
import re

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  lbcd rxtone[2];
  lbcd txtone[2];
  u8 unknown1:1,
     pttid:2,       // PTT ID
     skip:1,        // Scan Add
     wide:1,        // Bandwidth
     bcl:1,         // Busy Lock
     epilogue:1,    // Epilogue (STE)
     highpower:1;   // Power Level
  u8 unknown2[3];
} memory[16];

#seekto 0x0120;
struct {
  u8 hivoltnotx:1,  // TX Inhibit when voltage too high
     lovoltnotx:1,  // TX Inhibit when voltage too low
     unknown1:1,
     fmradio:1,     // Broadcast FM Radio
     unknown2:1,
     tone:1,        // Tone
     voice:2;       // Voice
  u8 unknown3:1,
     save:3,        // Battery Save
     squelch:4;     // Squelch
  u8 tot;           // Time Out Timer
  u8 voxi:1,        // VOX Inhibit on Receive
     voxd:2,        // VOX Delay
     vox:1,         // VOX
     voxg:4;        // VOX Gain
  u8 unknown4;
  u8 unknown5:4,
     scanspeed:4;   // Scan Speed
  u8 unknown6:3,
     scandelay:5;   // Scan Delay
  u8 k1longp:4,     // Key 1 Long Press
     k1shortp:4;    // Key 1 Short Press
  u8 k2longp:4,     // Key 2 Long Press
     k2shortp:4;    // Key 2 Short Press
  u8 unknown7:4,
     ssave:4;       // Super Battery Save
} settings;

#seekto 0x0140;
struct {
  u8 unknown1:4,
     dtmfspd:4;     // DTMF Speed
  u8 digdelay:4,    // 1st Digit Delay
     digtime:4;     // 1st Digit Time
  u8 stuntype:1,    // Stun Type
     sidetone:1,    // DTMF Sidetone
     starhash:2,    // * and # Time
     decodetone:1,  // Decode Tone
     txdecode:1,    // TX Decode
     unknown2:2;
  u8 unknown3;
  u8 unknown4:4,
     groupcode:4;   // Group Code
  u8 unknown5:1,
     resettone:1,   // Reset Tone
     resettime:6;   // Reset Time
  u8 codespace:4,   // Code Space Time
     decodeto:4;    // Decode Tome Out
  u8 unknown6;
  u8 idcode[3];     // ID Code
  u8 unknown7[2];
  u8 code1_len;     // PTT ID length(begging of TX)
  u8 code2_len;     // PTT ID length(end of TX)
  u8 unknown8;
  u8 code3_len;     // Stun Code length
  u8 code3[5];      // Stun Code
  u8 unknown9[10];
  u8 code1[8];      // PTT ID(beginning of TX)
  u8 code2[8];      // PTT ID(end of TX)
} dtmf;

#seekto 0x0170;
struct {
  char fp[8];
} fingerprint;
"""

CMD_ACK = b"\x06"

NUMERIC_CHARSET = list("0123456789")
DTMF_CHARSET = NUMERIC_CHARSET + list("ABCD*#")

RT26_POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=5.00),
                     chirp_common.PowerLevel("High", watts=10.00)]

RT26_DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

LIST_PTTID = ["Off", "BOT", "EOT", "Both"]
LIST_SHORT_PRESS = ["Off", "Monitor On/Off", "", "Scan", "Alarm",
                    "Power High/Low"]
LIST_LONG_PRESS = ["Off", "Monitor On/Off", "Monitor(momentary)",
                   "Scan", "Alarm", "Power High/Low"]
LIST_VOXDELAY = ["0.5", "1.0", "2.0", "3.0"]
LIST_VOICE = ["Off", "English", "Chinese"]
LIST_TIMEOUTTIMER = ["Off"] + ["%s" % x for x in range(15, 615, 15)]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SSAVE = ["Off"] + ["%s" % x for x in range(1, 10)]
LIST_SCANSPEED = ["%s" % x for x in range(100, 550, 50)]
LIST_SCANDELAY = ["%s" % x for x in range(3, 31)]
LIST_DIGTIME = ["%s" % x for x in range(0, 1100, 100)]
LIST_DIGDELAY = ["%s" % x for x in range(100, 1100, 100)]
LIST_STARHASH = ["100", "500", "1000", "0"]
LIST_CODESPACE = ["None"] + ["%s" % x for x in range(600, 2100, 100)]
LIST_GROUPCODE = ["Off", "A", "B", "C", "D", "#", "*"]
LIST_RESETTIME = ["Off"] + ["%s" % x for x in range(1, 61)]
LIST_DECODETO = ["%s" % x for x in range(500, 1000, 50)] + \
                ["%s" % x for x in range(1000, 1600, 100)]
LIST_STUNTYPE = ["TX/RX Inhibit", "TX Inhibit"]

# Retevis RT26 fingerprints
RT26_UHF_fp = b"PDK80" + b"\xF3\x00\x00"   # RT26 UHF model

MODELS = [RT26_UHF_fp, ]


def _model_from_data(data):
    return data[0x0170:0x0178]


def _model_from_image(radio):
    return _model_from_data(radio.get_mmap())


def _get_radio_model(radio):
    block = _rt26_read_block(radio, 0x0170, 0x10)
    version = block[0:8]
    return version


def _rt26_enter_programming_mode(radio):
    serial = radio.pipe

    magic = [b"PROGRAMa", b"PROGRAMb"]
    for i in range(0, 2):

        try:
            LOG.debug("sending " + magic[i].decode())
            serial.write(magic[i])
            ack = serial.read(1)
        except:
            _rt26_exit_programming_mode(radio)
            raise errors.RadioError("Error communicating with radio")

        if not ack:
            _rt26_exit_programming_mode(radio)
            raise errors.RadioError("No response from radio")
        elif ack != CMD_ACK:
            LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
            _rt26_exit_programming_mode(radio)
            raise errors.RadioError("Radio refused to enter programming mode")

    try:
        LOG.debug("sending " + util.hexprint("\x02"))
        serial.write(b"\x02")
        ident = serial.read(16)
    except:
        _rt26_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if not ident.startswith(b"PDK80"):
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ident))
        _rt26_exit_programming_mode(radio)
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        LOG.debug("sending " + util.hexprint("MDK8ECUMHS1X7BN/"))
        serial.write(b"MXT8KCUMHS1X7BN/")
        ack = serial.read(1)
    except:
        _rt26_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != b"\xB2":
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
        _rt26_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        LOG.debug("sending " + util.hexprint(CMD_ACK))
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _rt26_exit_programming_mode(radio)
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        LOG.debug("Incorrect response, got this:\n\n" + util.hexprint(ack))
        _rt26_exit_programming_mode(radio)
        raise errors.RadioError("Radio refused to enter programming mode")

    # DEBUG
    LOG.info("Positive ident, this is a %s %s" % (radio.VENDOR, radio.MODEL))


def _rt26_exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _rt26_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)

        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            _rt26_exit_programming_mode(radio)
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        _rt26_exit_programming_mode(radio)
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        _rt26_exit_programming_mode(radio)
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _rt26_write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        _rt26_exit_programming_mode(radio)
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _rt26_enter_programming_mode(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio._block_size):
        status.cur = addr + radio._block_size
        radio.status_fn(status)

        block = _rt26_read_block(radio, addr, radio._block_size)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _rt26_exit_programming_mode(radio)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _rt26_enter_programming_mode(radio)

    status.cur = 0
    status.max = 0x0190

    for start_addr, end_addr, block_size in radio._ranges:
        for addr in range(start_addr, end_addr, block_size):
            status.cur = addr + block_size
            radio.status_fn(status)
            _rt26_write_block(radio, addr, block_size)

    _rt26_exit_programming_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x0170:0x0176]

    return rid.startswith(b"PDK80")


@directory.register
class RT26Radio(chirp_common.CloneModeRadio):
    """Retevis RT26"""
    VENDOR = "Retevis"
    MODEL = "RT26"
    BAUD_RATE = 4800

    _ranges = [
               (0x0000, 0x0190, 0x10),
              ]
    _memsize = 0x0400
    _block_size = 0x10

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = RT26_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]  # 12.5 kHz, 25 kHz.
        rf.valid_dtcs_codes = RT26_DTCS
        rf.memory_bounds = (1, 16)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = [(400000000, 520000000)]

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        if val.get_raw(asbytes=False) == "\xFF\xFF":
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

    def _my_band(self):
        model_tag = _model_from_image(self)
        return model_tag

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()

        mem.number = number
        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif _mem.txfreq.get_raw() == b"\xFF\xFF\xFF\xFF":
            mem.duplex = "off"
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        rxtone = txtone = None
        txtone = self.decode_tone(_mem.txtone)
        rxtone = self.decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.power = RT26_POWER_LEVELS[_mem.highpower]

        if _mem.skip:
            mem.skip = "S"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(not _mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("epilogue", "Epilogue(STE)",
                          RadioSettingValueBoolean(_mem.epilogue))
        mem.extra.append(rs)

        val = 3 - _mem.pttid
        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(
                              LIST_PTTID, current_index=val))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xFF" * (_mem.size() // 8))
            return

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            _mem.txfreq.fill_raw(b"\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.wide = mem.mode == "FM"

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.txtone, txmode, txtone, txpol)
        self.encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        _mem.highpower = mem.power == RT26_POWER_LEVELS[1]

        _mem.skip = mem.skip == "S"

        for setting in mem.extra:
            if setting.get_name() == "bcl":
                setattr(_mem, setting.get_name(), not int(setting.value))
            elif setting.get_name() == "pttid":
                setattr(_mem, setting.get_name(), 3 - int(setting.value))
            else:
                setattr(_mem, setting.get_name(), int(setting.value))

    def _bbcd2dtmf(self, bcdarr, strlen=16):
        # doing bbcd, but with support for ABCD*#
        LOG.debug(bcdarr.get_value())
        string = ''.join("%02X" % b for b in bcdarr)
        LOG.debug("@_bbcd2dtmf, received: %s" % string)
        string = string.replace('E', '#').replace('F', '*')
        if strlen <= 16:
            string = string[:strlen]
        return string

    def _dtmf2bbcd(self, value, strlen):
        dtmfstr = value.get_value()
        dtmfstr = dtmfstr.replace('#', 'E').replace('*', 'F')
        dtmfstr = str.ljust(dtmfstr.strip(), strlen, "F")
        bcdarr = list(bytearray.fromhex(dtmfstr))
        LOG.debug("@_dtmf2bbcd, sending: %s" % bcdarr)
        return bcdarr

    def _bbcd2num(self, bcdarr, strlen=6):
        # doing bbcd
        LOG.debug(bcdarr.get_value())
        string = ''.join("%02X" % b for b in bcdarr)
        LOG.debug("@_bbcd2num, received: %s" % string)
        if strlen <= 6:
            string = string[:strlen]
        return string

    def _num2bbcd(self, value):
        numstr = value.get_value()
        numstr = str.ljust(numstr.strip(), 6, "F")
        bcdarr = list(bytearray.fromhex(numstr))
        LOG.debug("@_num2bbcd, sending: %s" % bcdarr)
        return bcdarr

    def get_settings(self):
        _settings = self._memobj.settings
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        top = RadioSettings(basic, dtmf)

        if _settings.k1shortp > 5:
            val = 4
        else:
            val = _settings.k1shortp
        rs = RadioSetting("k1shortp", "Key 1 Short Press",
                          RadioSettingValueList(
                              LIST_SHORT_PRESS,
                              current_index=val))
        basic.append(rs)

        if _settings.k1longp > 5:
            val = 5
        else:
            val = _settings.k1longp
        rs = RadioSetting("k1longp", "Key 1 Long Press",
                          RadioSettingValueList(
                              LIST_LONG_PRESS,
                              current_index=val))
        basic.append(rs)

        if _settings.k2shortp > 5:
            val = 1
        else:
            val = _settings.k2shortp
        rs = RadioSetting("k2shortp", "Key 2 Short Press",
                          RadioSettingValueList(
                              LIST_SHORT_PRESS,
                              current_index=val))
        basic.append(rs)

        if _settings.k2longp > 5:
            val = 3
        else:
            val = _settings.k2longp
        rs = RadioSetting("k2longp", "Key 2 Long Press",
                          RadioSettingValueList(
                              LIST_LONG_PRESS,
                              current_index=val))
        basic.append(rs)

        rs = RadioSetting("vox", "VOX",
                          RadioSettingValueBoolean(not _settings.vox))
        basic.append(rs)

        if _settings.voxg > 8:
            val = 4
        else:
            val = _settings.voxg + 1
        rs = RadioSetting("voxg", "VOX Gain",
                          RadioSettingValueInteger(1, 9, val))
        basic.append(rs)

        rs = RadioSetting("voxd", "VOX Delay Time",
                          RadioSettingValueList(
                              LIST_VOXDELAY,
                              current_index=_settings.voxd))
        basic.append(rs)

        rs = RadioSetting("voxi", "VOX Inhibit on Receive",
                          RadioSettingValueBoolean(_settings.voxi))
        basic.append(rs)

        if _settings.squelch > 9:
            val = 5
        else:
            val = _settings.squelch
        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueInteger(0, 9, val))
        basic.append(rs)

        if _settings.voice == 3:
            val = 1
        else:
            val = _settings.voice
        rs = RadioSetting("voice", "Voice Prompts",
                          RadioSettingValueList(
                              LIST_VOICE,
                              current_index=val))
        basic.append(rs)

        rs = RadioSetting("tone", "Tone",
                          RadioSettingValueBoolean(_settings.tone))
        basic.append(rs)

        rs = RadioSetting("lovoltnotx", "TX Inhibit (when battery < 6 volts)",
                          RadioSettingValueBoolean(_settings.lovoltnotx))
        basic.append(rs)

        rs = RadioSetting("hivoltnotx", "TX Inhibit (when battery > 9 volts)",
                          RadioSettingValueBoolean(_settings.hivoltnotx))
        basic.append(rs)

        if _settings.tot > 0x28:
            val = 6
        else:
            val = _settings.tot
        rs = RadioSetting("tot", "Time-out Timer[s]",
                          RadioSettingValueList(
                              LIST_TIMEOUTTIMER,
                              current_index=val))
        basic.append(rs)

        if _settings.save < 3:
            val = 0
        else:
            val = _settings.save - 3
        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueList(
                              LIST_SAVE,
                              current_index=val))
        basic.append(rs)

        rs = RadioSetting("ssave", "Super Battery Saver[s]",
                          RadioSettingValueList(
                              LIST_SSAVE,
                              current_index=_settings.ssave))
        basic.append(rs)

        rs = RadioSetting("fmradio", "Broadcast FM",
                          RadioSettingValueBoolean(_settings.fmradio))
        basic.append(rs)

        if _settings.scanspeed > 8:
            val = 4
        else:
            val = _settings.scanspeed
        rs = RadioSetting("scanspeed", "Scan Speed[ms]",
                          RadioSettingValueList(
                              LIST_SCANSPEED,
                              current_index=val))
        basic.append(rs)

        if _settings.scandelay > 27:
            val = 12
        else:
            val = _settings.scandelay
        rs = RadioSetting("scandelay", "Scan Droupout Delay Time[s]",
                          RadioSettingValueList(
                              LIST_SCANDELAY,
                              current_index=val))
        basic.append(rs)

        if _mem.dtmf.dtmfspd > 11:
            val = 2
        else:
            val = _mem.dtmf.dtmfspd + 4
        rs = RadioSetting("dtmf.dtmfspd", "DTMF Speed[digit/s]",
                          RadioSettingValueInteger(4, 15, val))
        dtmf.append(rs)

        if _mem.dtmf.digtime > 10:
            val = 0
        else:
            val = _mem.dtmf.digtime
        rs = RadioSetting("dtmf.digtime", "1st Digit Time[ms]",
                          RadioSettingValueList(
                              LIST_DIGTIME,
                              current_index=val))
        dtmf.append(rs)

        if _mem.dtmf.digdelay > 9:
            val = 0
        else:
            val = _mem.dtmf.digdelay
        rs = RadioSetting("dtmf.digdelay", "1st Digit Delay[ms]",
                          RadioSettingValueList(
                              LIST_DIGDELAY,
                              current_index=val))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.starhash", "* and # Time[ms]",
                          RadioSettingValueList(
                              LIST_STARHASH,
                              current_index=_mem.dtmf.starhash))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.codespace", "Code Space Time[ms]",
                          RadioSettingValueList(
                              LIST_CODESPACE,
                              current_index=_mem.dtmf.codespace))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.sidetone", "DTMF Sidetone",
                          RadioSettingValueBoolean(_mem.dtmf.sidetone))
        dtmf.append(rs)

        # setup pttid entries
        for i in range(0, 2):
            objname = "code" + str(i + 1)
            names = ["PTT ID(BOT)", "PTT ID(EOT)"]
            strname = str(names[i])
            dtmfsetting = getattr(_mem.dtmf, objname)
            dtmflen = getattr(_mem.dtmf, objname + "_len")
            dtmfstr = self._bbcd2dtmf(dtmfsetting, dtmflen)
            code = RadioSettingValueString(0, 16, dtmfstr)
            code.set_charset(DTMF_CHARSET + list(" "))
            rs = RadioSetting("dtmf." + objname, strname, code)
            dtmf.append(rs)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in NUMERIC_CHARSET:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        # setup id code entry
        codesetting = getattr(_mem.dtmf, "idcode")
        codestr = self._bbcd2num(codesetting, 6)
        code = RadioSettingValueString(0, 6, _filter(codestr))
        code.set_charset(NUMERIC_CHARSET + list(" "))
        rs = RadioSetting("dtmf.idcode", "ID Code", code)
        dtmf.append(rs)

        if _mem.dtmf.groupcode > 6:
            val = 0
        else:
            val = _mem.dtmf.groupcode
        rs = RadioSetting("dtmf.groupcode", "Group Code",
                          RadioSettingValueList(
                              LIST_GROUPCODE,
                              current_index=val))
        dtmf.append(rs)

        if _mem.dtmf.resettime > 60:
            val = 0
        else:
            val = _mem.dtmf.resettime
        rs = RadioSetting("dtmf.resettime", "Auto Reset Time[s]",
                          RadioSettingValueList(
                              LIST_RESETTIME,
                              current_index=_mem.dtmf.resettime))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.txdecode", "TX Decode",
                          RadioSettingValueBoolean(_mem.dtmf.txdecode))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.decodeto", "Decode Time Out[ms]",
                          RadioSettingValueList(
                              LIST_DECODETO,
                              current_index=_mem.dtmf.decodeto))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.decodetone", "Decode Tone",
                          RadioSettingValueBoolean(_mem.dtmf.decodetone))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.resettone", "Reset Tone",
                          RadioSettingValueBoolean(_mem.dtmf.resettone))
        dtmf.append(rs)

        rs = RadioSetting("dtmf.stuntype", "Stun Type",
                          RadioSettingValueList(
                              LIST_STUNTYPE,
                              current_index=_mem.dtmf.stuntype))
        dtmf.append(rs)

        # setup stun entry
        objname = "code3"
        strname = "Stun Code"
        dtmfsetting = getattr(_mem.dtmf, objname)
        dtmflen = getattr(_mem.dtmf, objname + "_len")
        dtmfstr = self._bbcd2dtmf(dtmfsetting, dtmflen)
        code = RadioSettingValueString(0, 10, dtmfstr)
        code.set_charset(DTMF_CHARSET + list(" "))
        rs = RadioSetting("dtmf." + objname, strname, code)
        dtmf.append(rs)

        return top

    def set_settings(self, settings):
        _mem = self._memobj
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

                    if setting == "vox":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "voxg":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "save":
                        setattr(obj, setting, int(element.value) + 3)
                    elif setting == "dtmfspd":
                        setattr(obj, setting, int(element.value) - 4)
                    elif re.match(r'code\d', setting):
                        # set dtmf length field and then get bcd dtmf
                        if setting == "code3":
                            strlen = 10
                        else:
                            strlen = 16
                        codelen = len(str(element.value).strip())
                        setattr(_mem.dtmf, setting + "_len", codelen)
                        dtmfstr = self._dtmf2bbcd(element.value, strlen)
                        setattr(_mem.dtmf, setting, dtmfstr)
                    elif setting == "idcode":
                        numstr = self._num2bbcd(element.value)
                        setattr(_mem.dtmf, setting, numstr)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) in [0x0400, ]:
            match_size = True

        # testing the model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False
