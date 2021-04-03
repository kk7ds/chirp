# Copyright 2021 Jim Unroe <rock.unroe@gmail.com>
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
import logging

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
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];       // RX Frequency           0-3
  lbcd txfreq[4];       // TX Frequency           4-7
  ul16 rx_tone;         // PL/DPL Decode          8-9
  ul16 tx_tone;         // PL/DPL Encode          A-B
  u8 unknown1:3,        //                        C
     bcl:2,             // Busy Lock
     unknown2:3;
  u8 unknown3:2,        //                        D
     highpower:1,       // Power Level
     wide:1,            // Bandwidth
     unknown4:4;
  u8 scramble_type:4,   // Scramble Type          E
     unknown5:4;
  u8 unknown6:4,
     scramble_type2:4;  // Scramble Type 2        F
} memory[16];

#seekto 0x011D;
struct {
  u8 unused:4,
     pf1:4;             // Programmable Function Key 1
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;      // Scramble Enable
  u8 unknown1[2];
  u8 voice;             // Voice Annunciation
  u8 tot;               // Time-out Timer
  u8 totalert;          // Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;           // Squelch Level
  u8 save;              // Battery Saver
  u8 unknown3[3];
  u8 use_vox;           // VOX Enable
  u8 vox;               // VOX Gain
} settings;

#seekto 0x017E;
u8 skipflags[2];       // SCAN_ADD
"""

MEM_FORMAT_RB17A = """
struct memory {
  lbcd rxfreq[4];      // 0-3
  lbcd txfreq[4];      // 4-7
  ul16 rx_tone;        // 8-9
  ul16 tx_tone;        // A-B
  u8 unknown1:1,       // C
     compander:1,      // Compand
     bcl:2,            // Busy Channel Lock-out
     cdcss:1,          // Cdcss Mode
     scramble_type:3;  // Scramble Type
  u8 unknown2:4,       // D
     middlepower:1,    // Power Level-Middle
     unknown3:1,       //
     highpower:1,      // Power Level-High/Low
     wide:1;           // Bandwidth
  u8 unknown4;         // E
  u8 unknown5;         // F
};

#seekto 0x0010;
  struct memory lomems[16];

#seekto 0x0200;
  struct memory himems[14];

#seekto 0x011D;
struct {
  u8 pf1;              // 011D PF1 Key
  u8 topkey;           // 011E Top Key
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;     // 012C Scramble Enable
  u8 channel;          // 012D Channel Number
  u8 alarm;            // 012E Alarm Type
  u8 voice;            // 012F Voice Annunciation
  u8 tot;              // 0130 Time-out Timer
  u8 totalert;         // 0131 Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;          // 0134 Squelch Level
  u8 save;             // 0135 Battery Saver
  u8 unknown3[3];
  u8 use_vox;          // 0139 VOX Enable
  u8 vox;              // 013A VOX Gain
} settings;

#seekto 0x017E;
u8 skipflags[4];       // Scan Add
"""

CMD_ACK = "\x06"

ALARM_LIST = ["Local Alarm", "Remote Alarm"]
BCL_LIST = ["Off", "Carrier", "QT/DQT"]
CDCSS_LIST = ["Normal Code", "Special Code 2", "Special Code 1"]
SCRAMBLE_LIST = ["%s" % x for x in range(1, 9)]
TIMEOUTTIMER_LIST = ["%s seconds" % x for x in range(15, 615, 15)]
TOTALERT_LIST = ["Off"] + ["%s seconds" % x for x in range(1, 11)]
VOICE_LIST = ["Off", "Chinese", "English"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 17)]
PF1_CHOICES = ["None", "Monitor", "Scan", "Scramble", "Alarm"]
PF1_VALUES = [0x0F, 0x04, 0x06, 0x08, 0x0C]
TOPKEY_CHOICES = ["None", "Alarming"]
TOPKEY_VALUES = [0xFF, 0x0C]

SETTING_LISTS = {
    "alarm": ALARM_LIST,
    "bcl": BCL_LIST,
    "cdcss": CDCSS_LIST,
    "scramble": SCRAMBLE_LIST,
    "tot": TIMEOUTTIMER_LIST,
    "totalert": TOTALERT_LIST,
    "voice": VOICE_LIST,
    "vox": VOX_LIST,
    }

GMRS_FREQS1 = [462.5625, 462.5875, 462.6125, 462.6375, 462.6625,
               462.6875, 462.7125]
GMRS_FREQS2 = [467.5625, 467.5875, 467.6125, 467.6375, 467.6625,
               467.6875, 467.7125]
GMRS_FREQS3 = [462.5500, 462.5750, 462.6000, 462.6250, 462.6500,
               462.6750, 462.7000, 462.7250]
GMRS_FREQS = GMRS_FREQS1 + GMRS_FREQS2 + GMRS_FREQS3 * 2


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

    if not ident == radio._fingerprint:
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write("E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

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
    _enter_programming_mode(radio)

    data = ""

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

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)

    _exit_programming_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x01B8:0x01BE]

    return rid.startswith("P3207")


@directory.register
class RT21Radio(chirp_common.CloneModeRadio):
    """RETEVIS RT21"""
    VENDOR = "Retevis"
    MODEL = "RT21"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x10
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("High", watts=2.50)]

    _magic = "PRMZUNE"
    _fingerprint = "P3207s\xF8\xFF"
    _upper = 16
    _skipflags = True
    _reserved = False
    _gmrs = False

    _ranges = [
               (0x0000, 0x0400),
              ]
    _memsize = 0x0400

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
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]  # 12.5 KHz, 25 kHz.
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = [(400000000, 480000000)]

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def validate_memory(self, mem):
        msgs = ""
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)

        _msg_freq = 'Memory location cannot change frequency'
        _msg_simplex = 'Memory location only supports Duplex:(None)'
        _msg_duplex = 'Memory location only supports Duplex: +'
        _msg_offset = 'Memory location only supports Offset: 5.000000'
        _msg_nfm = 'Memory location only supports Mode: NFM'
        _msg_txp = 'Memory location only supports Power: Low'

        # GMRS models
        if self._gmrs:
            # range of memories with values set by FCC rules
            if mem.freq != int(GMRS_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 22 are simplex only
            if mem.number <= 22:
                if str(mem.duplex) != "":
                    # warn user can't change duplex
                    msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 23 - 30 are +5 MHz duplex only
            if mem.number >= 23:
                if str(mem.duplex) != "+":
                    # warn user can't change duplex
                    msgs.append(chirp_common.ValidationError(_msg_duplex))

                if str(mem.offset) != "5000000":
                    # warn user can't change offset
                    msgs.append(chirp_common.ValidationError(_msg_offset))

            # channels 8 - 14 are low power NFM only
            if mem.number >= 8 and mem.number <= 14:
                if mem.mode != "NFM":
                    # warn user can't change mode
                    msgs.append(chirp_common.ValidationError(_msg_nfm))

                if mem.power != "Low":
                    # warn user can't change power
                    msgs.append(chirp_common.ValidationError(_msg_txp))

        return msgs

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

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol

        if _mem.tx_tone != 0xFFFF and _mem.tx_tone > 0x2000:
            tcode, tpol = _get_dcs(_mem.tx_tone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.tx_tone != 0xFFFF:
            mem.rtone = _mem.tx_tone / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        if _mem.rx_tone != 0xFFFF and _mem.rx_tone > 0x2000:
            rcode, rpol = _get_dcs(_mem.rx_tone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rx_tone != 0xFFFF:
            mem.ctone = _mem.rx_tone / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        if mem.tmode == "DTCS":
            mem.dtcs_polarity = "%s%s" % (tpol, rpol)

        LOG.debug("Got TX %s (%i) RX %s (%i)" %
                  (txmode, _mem.tx_tone, rxmode, _mem.rx_tone))

    def get_memory(self, number):
        if self._skipflags:
            bitpos = (1 << ((number - 1) % 8))
            bytepos = ((number - 1) / 8)
            LOG.debug("bitpos %s" % bitpos)
            LOG.debug("bytepos %s" % bytepos)
            _skp = self._memobj.skipflags[bytepos]

        mem = chirp_common.Memory()

        mem.number = number

        if self.MODEL == "RB17A":
            if mem.number < 17:
                _mem = self._memobj.lomems[number - 1]
            else:
                _mem = self._memobj.himems[number - 17]
        else:
            _mem = self._memobj.memory[number - 1]

        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == "\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if _mem.get_raw() == ("\xFF" * 16):
            LOG.debug("Initializing empty memory")
            if self.MODEL == "RB17A":
                _mem.set_raw("\x00" * 13 + "\x04\xFF\xFF")
            else:
                _mem.set_raw("\x00" * 13 + "\x30\x8F\xF8")

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        self._get_tone(_mem, mem)

        mem.power = self.POWER_LEVELS[_mem.highpower]

        mem.skip = "" if (_skp & bitpos) else "S"
        LOG.debug("mem.skip %s" % mem.skip)

        mem.extra = RadioSettingGroup("Extra", "extra")

        if self.MODEL == "RT21" or self.MODEL == "RB17A":
            rs = RadioSettingValueList(BCL_LIST, BCL_LIST[_mem.bcl])
            rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueList(SCRAMBLE_LIST,
                                       SCRAMBLE_LIST[_mem.scramble_type - 8])
            rset = RadioSetting("scramble_type", "Scramble Type", rs)
            mem.extra.append(rset)

            if self.MODEL == "RB17A":
                rs = RadioSettingValueList(CDCSS_LIST, CDCSS_LIST[_mem.cdcss])
                rset = RadioSetting("cdcss", "Cdcss Mode", rs)
                mem.extra.append(rset)

        if self._gmrs:
            GMRS_IMMUTABLE = ["freq", "duplex", "offset"]
            if mem.number >= 8 and mem.number <= 14:
                mem.immutable = GMRS_IMMUTABLE + ["power", "mode"]
            else:
                mem.immutable = GMRS_IMMUTABLE

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0x8000
            return val

        rx_mode = tx_mode = None
        rx_tone = tx_tone = 0xFFFF

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            tx_tone = int(mem.rtone * 10)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rx_tone = tx_tone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                tx_tone = int(mem.rtone * 10)
            if rx_mode == "DTCS":
                rx_tone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rx_tone = int(mem.ctone * 10)

        _mem.rx_tone = rx_tone
        _mem.tx_tone = tx_tone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.tx_tone, rx_mode, _mem.rx_tone))

    def set_memory(self, mem):
        if self._skipflags:
            bitpos = (1 << ((mem.number - 1) % 8))
            bytepos = ((mem.number - 1) / 8)
            LOG.debug("bitpos %s" % bitpos)
            LOG.debug("bytepos %s" % bytepos)
            _skp = self._memobj.skipflags[bytepos]

        if self.MODEL == "RB17A":
            if mem.number < 17:
                _mem = self._memobj.lomems[mem.number - 1]
            else:
                _mem = self._memobj.himems[mem.number - 17]
        else:
            _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            if self.MODEL == "RB17A":
                _mem.set_raw("\xFF" * 12 + "\x00\x00\xFF\xFF")
            else:
                _mem.set_raw("\xFF" * (_mem.size() / 8))

            if self._gmrs:
                GMRS_FREQ = int(GMRS_FREQS[mem.number - 1] * 100000)
                if mem.number > 22:
                    _mem.rxfreq = GMRS_FREQ
                    _mem.txfreq = int(_mem.rxfreq) + 500000
                    _mem.wide = True
                else:
                    _mem.rxfreq = _mem.txfreq = GMRS_FREQ
                if mem.number >= 8 and mem.number <= 14:
                    _mem.wide = False
                    _mem.highpower = False
                else:
                    _mem.wide = True
                    _mem.highpower = True

            return

        if self.MODEL == "RB17A":
            _mem.set_raw("\x00" * 13 + "\x00\xFF\xFF")
        else:
            _mem.set_raw("\x00" * 13 + "\x30\x8F\xF8")

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

        _mem.wide = mem.mode == "FM"

        self._set_tone(mem, _mem)

        _mem.highpower = mem.power == self.POWER_LEVELS[1]

        if mem.skip != "S":
            _skp |= bitpos
        else:
            _skp &= ~bitpos
        LOG.debug("_skp %s" % _skp)

        for setting in mem.extra:
            if setting.get_name() == "scramble_type":
                setattr(_mem, setting.get_name(), int(setting.value) + 8)
                setattr(_mem, "scramble_type2", int(setting.value) + 8)
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        if self.MODEL == "RT21" or self.MODEL == "RB17A":
            _keys = self._memobj.keys

            rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                       TIMEOUTTIMER_LIST[_settings.tot - 1])
            rset = RadioSetting("tot", "Time-out timer", rs)
            basic.append(rset)

            rs = RadioSettingValueList(TOTALERT_LIST,
                                       TOTALERT_LIST[_settings.totalert])
            rset = RadioSetting("totalert", "TOT Pre-alert", rs)
            basic.append(rset)

            rs = RadioSettingValueInteger(0, 9, _settings.squelch)
            rset = RadioSetting("squelch", "Squelch Level", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOICE_LIST, VOICE_LIST[_settings.voice])
            rset = RadioSetting("voice", "Voice Annumciation", rs)
            basic.append(rset)

            if self.MODEL == "RB17A":
                rs = RadioSettingValueList(ALARM_LIST,
                                           ALARM_LIST[_settings.alarm])
                rset = RadioSetting("alarm", "Alarm Type", rs)
                basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.save)
            rset = RadioSetting("save", "Battery Saver", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.use_scramble)
            rset = RadioSetting("use_scramble", "Scramble", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.use_vox)
            rset = RadioSetting("use_vox", "VOX", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOX_LIST, VOX_LIST[_settings.vox])
            rset = RadioSetting("vox", "VOX Gain", rs)
            basic.append(rset)

            def apply_pf1_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(
                          setting.value) + " from list")
                val = str(setting.value)
                index = PF1_CHOICES.index(val)
                val = PF1_VALUES[index]
                obj.set_value(val)

            if _keys.pf1 in PF1_VALUES:
                idx = PF1_VALUES.index(_keys.pf1)
            else:
                idx = LIST_DTMF_SPECIAL_VALUES.index(0x04)
            rs = RadioSettingValueList(PF1_CHOICES, PF1_CHOICES[idx])
            rset = RadioSetting("keys.pf1", "PF1 Key Function", rs)
            rset.set_apply_callback(apply_pf1_listvalue, _keys.pf1)
            basic.append(rset)

            def apply_topkey_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = TOPKEY_CHOICES.index(val)
                val = TOPKEY_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RB17A":
                if _keys.topkey in TOPKEY_VALUES:
                    idx = TOPKEY_VALUES.index(_keys.topkey)
                else:
                    idx = TOPKEY_VALUES.index(0x0C)
                rs = RadioSettingValueList(TOPKEY_CHOICES, TOPKEY_CHOICES[idx])
                rset = RadioSetting("keys.topkey", "Top Key Function", rs)
                rset.set_apply_callback(apply_topkey_listvalue, _keys.topkey)
                basic.append(rset)

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
                    elif setting == "channel":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "tot":
                        setattr(obj, setting, int(element.value) + 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise


@directory.register
class RB17ARadio(RT21Radio):
    """RETEVIS RB17A"""
    VENDOR = "Retevis"
    MODEL = "RB17A"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=5.00)]

    _magic = "PROA8US"
    _fingerprint = "P3217s\xF8\xFF"
    _upper = 30
    _skipflags = True
    _reserved = False
    _gmrs = True

    _ranges = [
               (0x0000, 0x0300),
              ]
    _memsize = 0x0300

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB17A, self._mmap)

    @classmethod
    def match_model(cls, filedata, filename):
        if cls.MODEL == "RT21":
            # The RT21 is pre-metadata, so do old-school detection
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
        else:
            # Radios that have always been post-metadata, so never do
            # old-school detection
            return False
