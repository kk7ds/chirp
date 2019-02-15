# Copyright 2015 Lepik.stv <lepik.stv@gmail.com>
# based on modification of Dan Smith's and Jim Unroe original work
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

"""KYD IP-620 radios management module"""

# TODO: Power on message
# TODO: Channel name
# TODO: Tuning step

import struct
import time
import os
import logging
from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
                RadioSettingValueBoolean, RadioSettingValueList, \
                RadioSettingValueInteger, RadioSettingValueString, \
                RadioSettings

LOG = logging.getLogger(__name__)

IP620_MEM_FORMAT = """
#seekto 0x0000;
struct {           // Channel memory structure
  lbcd rx_freq[4]; // RX frequency
  lbcd tx_freq[4]; // TX frequency
  ul16 rx_tone;    // RX tone
  ul16 tx_tone;    // TX tone
  u8 unknown_1:4   // n-a
     busy_loc:2,   // NO-00, Crrier wave-01, SM-10
     n_a:2;        // n-a
  u8 unknown_2:1   // n-a
     scan_add:1,   // Scan add
     n_a:1,        // n-a
     w_n:1,        // Narrow-0 Wide-1
     lout:1,       // LOCKOUT OFF-0 ON-1
     n_a_:1,       // n-a
     power:2;      // Power  low-00 middle-01 high-10
  u8 unknown_3;    // n-a
  u8 unknown_4;    // n-a
} memory[200];

#seekto 0x1000;
struct {
  u8 chan_name[6];  //Channel name
  u8 unknown_1[10];
} chan_names[200];

#seekto 0x0C80;
struct {           // Settings memory structure ( A-Frequency mode )
  lbcd freq_a_rx[4];
  lbcd freq_a_tx[4];
  ul16 freq_a_rx_tone;    // RX tone
  ul16 freq_a_tx_tone;    // TX tone
  u8 unknown_1_5:4
  freq_a_busy_loc:2,
  n_a:2;
  u8 unknown_1_6:3
  freq_a_w_n:1,
  n_a:1,
  na:1,
  freq_a_power:2;
  u8 unknown_1_7;
  u8 unknown_1_8;
} settings_freq_a;

#seekto 0x0E20;
struct {
  u8 chan_disp_way;  // Channel display way
  u8 step_freq;      // Step frequency KHz
  u8 rf_sql;         // Squelch level
  u8 bat_save;       // Battery Saver
  u8 chan_pri;       // Channel PRI
  u8 end_beep;       // End beep
  u8 tot;            // Time-out timer
  u8 vox;            // VOX Gain
  u8 chan_pri_num;   // Channel PRI time Sec
  u8 n_a_2;
  u8 ch_mode;        // CH mode
  u8 n_a_3;
  u8 call_tone;      // Call tone
  u8 beep;           // Beep
  u8 unknown_1_1[2];
  u8 unknown_1_2[8];
  u8 scan_rev;       // Scan rev
  u8 unknown_1_3[2];
  u8 enc;            // Frequency lock
  u8 vox_dly;        // VOX Delay
  u8 wait_back_light;// Wait back light
  u8 unknown_1_4[2];
} settings;

#seekto 0x0E40;
struct {
  u8 fm_radio;        // FM radio
  u8 auto_lock;       // Auto lock
  u8 unknown_1[8];
  u8 pon_msg[6];      //Power on msg
} settings_misc;

#seekto 0x1C80;
struct {
  u8 unknown_1[16];
  u8 unknown_2[16];
} settings_radio_3;
"""

CMD_ACK = "\x06"
WRITE_BLOCK_SIZE = 0x10
READ_BLOCK_SIZE = 0x40

CHAR_LENGTH_MAX = 6

OFF_ON_LIST = ["OFF", "ON"]
ON_OFF_LIST = ["ON", "OFF"]
NO_YES_LIST = ["NO", "YES"]
STEP_LIST = ["5.0", "6.25", "10.0", "12.5", "25.0"]
BAT_SAVE_LIST = ["OFF", "0.2 Sec", "0.4 Sec", "0.6 Sec", "0.8 Sec","1.0 Sec"]
SHIFT_LIST = ["", "-", "+"]
SCANM_LIST = ["Time", "Carrier wave", "Search"]
ENDBEEP_LIST = ["OFF", "Begin", "End", "Begin/End"]
POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=1.00), chirp_common.PowerLevel("Medium", watts=2.50), chirp_common.PowerLevel("High", watts=5.00)]
TIMEOUT_LIST = ["OFF", "1 Min", "3 Min", "10 Min"]
TOTALERT_LIST = ["", "OFF"] + ["%s seconds" % x for x in range(1, 11)]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 17)]
VOXDELAY_LIST = ["0.3 Sec", "0.5 Sec", "1.0 Sec", "1.5 Sec", "2.0 Sec", "3.0 Sec", "4.0 Sec", "5.0 Sec"]
PRI_NUM = [3, 5, 8, 10]
PRI_NUM_LIST = [str(x) for x in PRI_NUM]
CH_FLAG_LIST = ["Channel+Freq", "Channel+Name"]
BACKLIGHT_LIST = ["Always Off", "Auto", "Always On"]
BUSYLOCK_LIST = ["NO", "Carrier", "SM"]
KEYBLOCK_LIST = ["Manual", "Auto"]
CALLTONE_LIST = ["OFF", "1", "2", "3", "4", "5", "6", "7", "8", "1750"]
RFSQL_LIST = ["OFF", "S-1", "S-2", "S-3", "S-4", "S-5", "S-6","S-7", "S-8", "S-FULL"]

IP620_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ?+-* "

IP620_BANDS = [
    (136000000, 174000000),
    (200000000, 260000000),
    (300000000, 340000000),  # <--- this band supports only Russian model (ARGUT A-36)
    (350000000, 390000000),
    (400000000, 480000000),
    (420000000, 510000000),
    (450000000, 520000000),
]

@directory.register
class IP620Radio(chirp_common.CloneModeRadio,
                chirp_common.ExperimentalRadio):
    """KYD IP-620"""
    VENDOR = "KYD"
    MODEL = "IP-620"
    BAUD_RATE = 9600

    _ranges = [
               (0x0000, 0x2000),
              ]
    _memsize = 0x2000

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize and \
            filedata[0xF7E:0xF80] == "\x01\xE2"

    def _ip620_exit_programming_mode(self):
        try:
            self.pipe.write("\x06")
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Radio refused to exit programming mode: %s" % e)

    def _ip620_enter_programming_mode(self):
        try:
            self.pipe.write("iUHOUXUN")
            self.pipe.write("\x02")
            time.sleep(0.2)
            _ack = self.pipe.read(1)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Error communicating with radio: %s" % e)
        if not _ack:
            raise errors.RadioError("No response from radio")
        elif _ack != CMD_ACK:
            raise errors.RadioError("Radio refused to enter programming mode")
        try:
            self.pipe.write("\x02")
            _ident = self.pipe.read(8)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Error communicating with radio: %s" % e)
        if not _ident.startswith("\x06\x4B\x47\x36\x37\x01\x56\xF8"):
            print util.hexprint(_ident)
            raise errors.RadioError("Radio returned unknown identification string")
        try:
            self.pipe.write(CMD_ACK)
            _ack = self.pipe.read(1)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Error communicating with radio: %s" % e)
        if _ack != CMD_ACK:
            raise errors.RadioError("Radio refused to enter programming mode")

    def _ip620_write_block(self, block_addr):
        _cmd = struct.pack(">cHb", 'W', block_addr, WRITE_BLOCK_SIZE)
        _data = self.get_mmap()[block_addr:block_addr + WRITE_BLOCK_SIZE]
        LOG.debug("Writing Data:")
        LOG.debug(util.hexprint(_cmd + _data))
        try:
            self.pipe.write(_cmd + _data)
            if self.pipe.read(1) != CMD_ACK:
                raise Exception("No ACK")
        except:
            raise errors.RadioError("Failed to send block "
                                    "to radio at %04x" % block_addr)

    def _ip620_read_block(self, block_addr):
        _cmd = struct.pack(">cHb", 'R', block_addr, READ_BLOCK_SIZE)
        _expectedresponse = "W" + _cmd[1:]
        LOG.debug("Reading block %04x..." % (block_addr))
        try:
            self.pipe.write(_cmd)
            _response = self.pipe.read(4 + READ_BLOCK_SIZE)
            if _response[:4] != _expectedresponse:
                raise Exception("Error reading block %04x." % (block_addr))
            _block_data = _response[4:]
            self.pipe.write(CMD_ACK)
            _ack = self.pipe.read(1)
        except:
            raise errors.RadioError("Failed to read block at %04x" % block_addr)
        if _ack != CMD_ACK:
            raise Exception("No ACK reading block %04x." % (block_addr))
        return _block_data

    def _do_download(self):
        self._ip620_enter_programming_mode()
        _data = ""
        _status = chirp_common.Status()
        _status.msg = "Cloning from radio"
        _status.cur = 0
        _status.max = self._memsize
        for _addr in range(0, self._memsize, READ_BLOCK_SIZE):
            _status.cur = _addr + READ_BLOCK_SIZE
            self.status_fn(_status)
            _block = self._ip620_read_block(_addr)
            _data += _block
            LOG.debug("Address: %04x" % _addr)
            LOG.debug(util.hexprint(_block))
        self._ip620_exit_programming_mode()
        return memmap.MemoryMap(_data)

    def _do_upload(self):
        _status = chirp_common.Status()
        _status.msg = "Uploading to radio"
        self._ip620_enter_programming_mode()
        _status.cur = 0
        _status.max = self._memsize
        for _start_addr, _end_addr in self._ranges:
            for _addr in range(_start_addr, _end_addr, WRITE_BLOCK_SIZE):
                _status.cur = _addr + WRITE_BLOCK_SIZE
                self.status_fn(_status)
                self._ip620_write_block(_addr)
        self._ip620_exit_programming_mode()

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("This radio driver is currently under development. "
                           "There are no known issues with it, but you should "
                           "proceed with caution. However, proceed at your own risk!")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = False
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = False
        rf.has_name = False
        rf.valid_skips = []
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = SHIFT_LIST
        rf.valid_modes = ["FM", "NFM"]
        rf.memory_bounds = (1, 200)
        rf.valid_bands = IP620_BANDS
        rf.valid_characters = ''.join(set(IP620_CHARSET))
        rf.valid_name_length = CHAR_LENGTH_MAX
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(IP620_MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = self._do_download()
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        self._do_upload()

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol

        if _mem.tx_tone != 0xFFFF and _mem.tx_tone > 0x2800:
            tcode, tpol = _get_dcs(_mem.tx_tone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.tx_tone != 0xFFFF:
            mem.rtone = _mem.tx_tone / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        if _mem.rx_tone != 0xFFFF and _mem.rx_tone > 0x2800:
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

        LOG.debug("Got TX %s (%i) RX %s (%i)" % (txmode, _mem.tx_tone,
                                              rxmode, _mem.rx_tone))

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.chan_names[number - 1]

        def _is_empty():
            for i in range(0, 4):
                if _mem.rx_freq[i].get_raw() != "\xFF":
                    return False
            return True

        mem = chirp_common.Memory()
        mem.number = number

        if _is_empty():
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        if int(_mem.rx_freq) == int(_mem.tx_freq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rx_freq) > int(_mem.tx_freq) and "-" or "+"
            mem.offset = abs(int(_mem.rx_freq) - int(_mem.tx_freq)) * 10

        mem.mode = _mem.w_n and "FM" or "NFM"
        self._get_tone(_mem, mem)
        mem.power = POWER_LEVELS[_mem.power]

        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSetting("lout", "Lock out",
                          RadioSettingValueList(OFF_ON_LIST,
                          OFF_ON_LIST[_mem.lout]))
        mem.extra.append(rs)

        rs = RadioSetting("busy_loc", "Busy lock",
                          RadioSettingValueList(BUSYLOCK_LIST,
                          BUSYLOCK_LIST[_mem.busy_loc]))
        mem.extra.append(rs)

        rs = RadioSetting("scan_add", "Scan add",
                          RadioSettingValueList(NO_YES_LIST,
                          NO_YES_LIST[_mem.scan_add]))
        mem.extra.append(rs)
        #TODO: Show name channel
##        count = 0
##        for i in _nam.chan_name:
##            if i == 0xFF:
##                break
##            try:
##                mem.name += IP620_CHARSET[i]
##            except Exception:
##                LOG.error("Unknown name char %i: 0x%02x (mem %i)" %
##                          (count, i, number - 1))
##                mem.name += " "
##            count += 1
##        mem.name = mem.name.rstrip()

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
        _mem = self._memobj.memory[mem.number - 1]
        if mem.empty:
            _mem.set_raw("\xFF" * (_mem.size() / 8))
            return

        _mem.rx_freq = mem.freq / 10
        if mem.duplex == "OFF":
            for i in range(0, 4):
                _mem.tx_freq[i].set_raw("\xFF")
        elif mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        _mem.w_n = mem.mode == "FM"
        self._set_tone(mem, _mem)
        _mem.power = mem.power == POWER_LEVELS[1]

        for setting in ('lout', 'busy_loc', 'scan_add'):
            setattr(_mem, setting, 0)
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        _settings_misc = self._memobj.settings_misc
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        rs = RadioSetting("rf_sql", "Squelch level (SQL)",
                          RadioSettingValueList(RFSQL_LIST,
                          RFSQL_LIST[_settings.rf_sql]))
        basic.append(rs)

        rs = RadioSetting("step_freq", "Step frequency KHz (STP)",
                          RadioSettingValueList(STEP_LIST,
                          STEP_LIST[_settings.step_freq]))
        basic.append(rs)

        rs = RadioSetting("fm_radio", "FM radio (DW)",
                          RadioSettingValueList(OFF_ON_LIST,
                          OFF_ON_LIST[_settings_misc.fm_radio]))
        basic.append(rs)

        rs = RadioSetting("call_tone", "Call tone (CK)",
                          RadioSettingValueList(CALLTONE_LIST,
                          CALLTONE_LIST[_settings.call_tone]))
        basic.append(rs)

        rs = RadioSetting("tot", "Time-out timer (TOT)",
                          RadioSettingValueList(TIMEOUT_LIST,
                          TIMEOUT_LIST[_settings.tot]))
        basic.append(rs)

        rs = RadioSetting("chan_disp_way", "Channel display way",
                          RadioSettingValueList(CH_FLAG_LIST,
                          CH_FLAG_LIST[_settings.chan_disp_way]))
        basic.append(rs)

        rs = RadioSetting("vox", "VOX Gain (VOX)",
                          RadioSettingValueList(VOX_LIST,
                          VOX_LIST[_settings.vox]))
        basic.append(rs)

        rs = RadioSetting("vox_dly", "VOX Delay",
                          RadioSettingValueList(VOXDELAY_LIST,
                          VOXDELAY_LIST[_settings.vox_dly]))
        basic.append(rs)

        rs = RadioSetting("beep", "Beep (BP)",
                          RadioSettingValueList(OFF_ON_LIST,
                          OFF_ON_LIST[_settings.beep]))
        basic.append(rs)

        rs = RadioSetting("auto_lock", "Auto lock (KY)",
                          RadioSettingValueList(NO_YES_LIST,
                          NO_YES_LIST[_settings_misc.auto_lock]))
        basic.append(rs)

        rs = RadioSetting("bat_save", "Battery Saver (SAV)",
                          RadioSettingValueList(BAT_SAVE_LIST,
                          BAT_SAVE_LIST[_settings.bat_save]))
        basic.append(rs)

        rs = RadioSetting("chan_pri", "Channel PRI (PRI)",
                          RadioSettingValueList(OFF_ON_LIST,
                          OFF_ON_LIST[_settings.chan_pri]))
        basic.append(rs)

        rs = RadioSetting("chan_pri_num", "Channel PRI time Sec (PRI)",
                          RadioSettingValueList(PRI_NUM_LIST,
                          PRI_NUM_LIST[_settings.chan_pri_num]))
        basic.append(rs)

        rs = RadioSetting("end_beep", "End beep (ET)",
                          RadioSettingValueList(ENDBEEP_LIST,
                          ENDBEEP_LIST[_settings.end_beep]))
        basic.append(rs)

        rs = RadioSetting("ch_mode", "CH mode",
                          RadioSettingValueList(ON_OFF_LIST,
                          ON_OFF_LIST[_settings.ch_mode]))
        basic.append(rs)

        rs = RadioSetting("scan_rev", "Scan rev (SCAN)",
                          RadioSettingValueList(SCANM_LIST,
                          SCANM_LIST[_settings.scan_rev]))
        basic.append(rs)

        rs = RadioSetting("enc", "Frequency lock (ENC)",
                          RadioSettingValueList(OFF_ON_LIST,
                          OFF_ON_LIST[_settings.enc]))
        basic.append(rs)

        rs = RadioSetting("wait_back_light", "Wait back light (LED)",
                          RadioSettingValueList(BACKLIGHT_LIST,
                          BACKLIGHT_LIST[_settings.wait_back_light]))
        basic.append(rs)

        return top

    def _set_misc_settings(self, settings):
        for element in settings:
            try:
                setattr(self._memobj.settings_misc,
                        element.get_name(),
                        element.value)
            except Exception, e:
                LOG.debug(element.get_name())
                raise

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _settings_misc = self._memobj.settings_misc
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                setting = element.get_name()
                if setting in ["auto_lock","fm_radio"]:
                    oldval = getattr(_settings_misc, setting)
                else:
                    oldval = getattr(_settings, setting)

                newval = element.value

                LOG.debug("Setting %s(%s) <= %s" % (setting, oldval, newval))
                if setting in ["auto_lock","fm_radio"]:
                    setattr(_settings_misc, setting, newval)
                else:
                    setattr(_settings, setting, newval)
            except Exception, e:
                LOG.debug(element.get_name())
                raise
