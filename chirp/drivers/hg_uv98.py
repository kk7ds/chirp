# -*- coding: utf-8 -*-
# Copyright 2022 Masen Furer <kf7hvm@0x26.net>
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
#
# Lanchonlh HG-UV98 driver written by
#   Masen Furer <kf7hvm@0x26.net>
# With assistance from
#  KG7KMV and Bartłomiej Zieliński
# Based on the implementation of Kenwood TK-8102

import logging
import struct

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueList
from chirp.settings import RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct {
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  ul16 rx_tone;
  ul16 tx_tone;
  u8 unknown1:6,
     wide:1,
     highpower:1;
  u8 unknown2:5,
     bcl:1,
     scan:1,
     unknown3:1;
  u8 unknown4[2];
} memory[130];

#seekto 0x0a00;
struct {
  u8 abr;  // 0x0a00
  u8 save;
  u8 ch_a_step;
  u8 ch_b_step;
  u8 vox_grd;
  u8 ch_a_sql;
  u8 ch_b_sql;
  u8 roger;
  u8 ch_a_v_m;
  u8 ch_b_v_m;
  u8 ch_a_ch_mdf;
  u8 ch_b_ch_mdf;
  u8 tdr;
  u8 unknown5[3];
  u8 unknown6[5];  // 0x0a10
  u8 english;
  u8 beep;
  u8 voice;
  u8 night_mode;
  u8 abr_lv;  // backlight level
  u8 tot;
  u8 toa;
  u8 vox_dly;
  u8 sc_rev;
  u8 lockmode;
  u8 autolock;
  u8 unknown7;  // 0x0a20
  u8 pf1_short;
  u8 pf1_long;
  u8 pf2_short;
  u8 pf2_long;
  u8 top_short;
  u8 top_long;
  u8 rpt_rct;
  u8 sc_qt;
  u8 pri_ch;
  u8 pri_scn;
  u8 unknown8;
  u8 aprs_rx_band;
  u8 ch_a_mute;
  u8 ch_b_mute;
  u8 unknown9[7];  // 0x0a30
  u8 tx_priority;
  u8 aprs_rx_popup;
  u8 aprs_rx_tone;
  u8 aprs_tx_tone;
  u8 unknown10;
  u8 auto_lock_dly;
  u8 menu_dly;
  u8 beacon_exit_dly;
  u8 unknown11;
  u8 unknown12[2];        // 0x0a40
  u8 ch_a_mem_ch;
  u8 ch_b_mem_ch;
  u8 unknown13[12];
} settings;

#seekto 0x1000;
struct {
  char name[11];
  u8 unknown[5];
} name[128];

struct {
    char callsign[9];
    u8 null;
} aprs;

#seekto 0x1f80;
struct {
  ul32 unknown[8];
} unknown_settings;

"""

BOUNDS = [(136000000, 174000000), (400000000, 500000000)]
OFFSETS = [600000, 5000000]
MAX_CHANNELS = 128
MAX_NAME = 8
NAME_FIELD_SIZE = 11
CHUNK_SIZE = 64
MAX_ADDR = 0x2000
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                chirp_common.PowerLevel("High", watts=5)]
MODES = ["FM", "NFM"]
SPECIAL_CHANNELS = ['VFO-A', 'VFO-B']

# Settings maps
ABR_LIST = [str(v) for v in range(0, 151, 5)]
STEP_LIST = ["5.0", "6.25", "10.0", "12.5", "25.0", "50.0", "100.0"]
VOX_LIST = ["OFF", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
SQL_LIST = [str(v) for v in range(0, 10)]
ROGER_LIST = ["OFF", "BEGIN", "END", "BOTH"]
MDF_LIST = ["NUM+FREQ", "NUMBER", "NAME"]
VM_LIST = ["VFO", "MEMORY"]
LANG_LIST = ["CHINESE", "ENGLISH"]
ABR_LV_LIST = [str(v) for v in range(1, 11)]
TOT_LIST = [str(v) for v in range(0, 601, 15)]
TOA_LIST = ["OFF"] + ["{} S".format(v) for v in range(1, 11)]
VOX_DLY_LIST = [str(v) for v in range(1, 11)]
SC_REV_LIST = ["TIME", "BUSY", "HOLD"]
LOCKMODE_LIST = ["KEY", "KEY+DIAL", "KEY+DIAL+PTT"]
AUTOLOCK_LIST = ["AUTO", "Manual"]
PF1_LIST = ["BACK LIGHT", "SCAN", "SQUELCH", "TORCH", "BAND A/B"]
PF2_LIST = ["BEACON", "LIST", "TORCH", "BACK LIGHT"]
TOP_LIST = ["ALERT", "REMOTE ALERT", "TORCH", "TXP", "CH MDF", "OFF_NET_KEY"]
SC_QT_LIST = ["Decode", "Encode", "Decode+Encode"]
APRS_RX_LIST = ["OFF", "BAND A", "BAND B"]
TX_PRIORITY_LIST = ["VOICE", "APRS"]
AUTOLOCK_DLY_LIST = ["{} S".format(v) for v in range(5, 31)]
BEACON_EXIT_DLY_LIST = MENU_DLY_LIST = AUTOLOCK_DLY_LIST


def make_frame(cmd, addr, length, data=b""):
    if not isinstance(data, bytes):
        data = data.decode("ascii")
    return struct.pack(">BHB", ord(cmd), addr, length) + data


def send(radio, frame):
    LOG.debug("%04i P>R: %s" % (len(frame), util.hexprint(frame)))
    radio.pipe.write(frame)


def recv(radio, readdata=True):
    hdr = radio.pipe.read(4)
    cmd, addr, length = struct.unpack(">BHB", hdr)
    if readdata:
        data = radio.pipe.read(length)
        LOG.debug("     P<R: %s" % util.hexprint(hdr + data))
        if len(data) != length:
            raise errors.RadioError("Radio sent %i bytes (expected %i)" % (
                    len(data), length))
    else:
        data = b""
    radio.pipe.write(b"\x06")
    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise errors.RadioError("Radio didn't ack our read ack")
    return addr, bytes(data)


def do_ident(radio):
    send(radio, b"NiNHSG0N")
    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise errors.RadioError("Radio refused program mode: {}".format(ack))
    radio.pipe.write(b"\x02")
    ident = radio.pipe.read(8)
    LOG.debug('ident string was %r' % ident)
    if ident != radio.IDENT:
        raise errors.RadioError(
            "Incorrect model: %s, expected %r" % (
                util.hexprint(ident), radio.IDENT))
    LOG.info("Model: %s (%s)" % (radio.MODEL, util.hexprint(ident)))
    radio.pipe.write(b"\x06")
    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise errors.RadioError("Radio entered program mode, but didn't ack our ack")


def do_download(radio):
    radio.pipe.parity = "E"
    radio.pipe.timeout = 1
    do_ident(radio)

    data = bytes(b"")
    for addr in range(0, MAX_ADDR, CHUNK_SIZE):
        send(radio, make_frame(bytes(b"R"), addr, CHUNK_SIZE))
        _addr, _data = recv(radio)
        if _addr != addr:
            raise errors.RadioError("Radio sent unexpected address")
        data += _data
        radio.pipe.write(b"\x06")
        ack = radio.pipe.read(1)
        if ack != b"\x06":
            raise errors.RadioError("Radio refused block at %04x" % addr)

        status = chirp_common.Status()
        status.cur = addr
        status.max = MAX_ADDR
        status.msg = "Cloning from radio"
        radio.status_fn(status)

    radio.pipe.write(b"\x45")
    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    radio.pipe.parity = "E"
    radio.pipe.timeout = 1
    do_ident(radio)

    mmap = radio._mmap
    for addr in range(0, MAX_ADDR, CHUNK_SIZE):
        send(radio, make_frame(b"W", addr, CHUNK_SIZE, mmap[addr:addr + CHUNK_SIZE]))
        ack = radio.pipe.read(1)
        if ack != b"\x06":
            raise errors.RadioError("Radio refused block at %04x" % addr)
        radio.pipe.write(b"\x06")
        ack = radio.pipe.read(1)
        if ack != b"\x06":
            raise errors.RadioError("Radio didn't ack our read ack")

        status = chirp_common.Status()
        status.cur = addr
        status.max = MAX_ADDR
        status.msg = "Cloning to radio"
        radio.status_fn(status)

    radio.pipe.write(b"\x45")


def offset_for(freq):
    for bounds, offset in zip(BOUNDS, OFFSETS):
        if bounds[0] <= freq <= bounds[1]:
            return offset
    return 0


class RadioSettingValueChannel(RadioSettingValueList):
    """A setting that points to a defined channel."""
    def __init__(self, radio, current_raw):
        current = int(current_raw)
        current_mem = radio.get_memory(current)
        lo, hi = radio.get_features().memory_bounds
        options = [
            self._format_memory(mem)
            for mem in [radio.get_memory(n)
                        for n in range(lo, hi + 1)]]
        RadioSettingValueList.__init__(self, options,
                                       self._format_memory(current_mem))

    @staticmethod
    def _format_memory(m):
        if m.empty:
            return str(int(m.number))
        return "%i %.4f %s" % (m.number, m.freq / 1e6, m.name)

    def __int__(self):
        return int(self.get_value().partition(" ")[0])


@directory.register
class LanchonlhHG_UV98(chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio):
    """
    Lanchonlh HG-UV98

    Memory map decoding by KG7KMV
    Chirp integration by KF7HVM
    """
    VENDOR = "Lanchonlh"
    MODEL = "HG-UV98"
    IDENT = b"P3107\0\0\0"
    BAUD_RATE = 9600

    _upper = MAX_CHANNELS

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            "This Lanchonlh HG-UV98 driver is an alpha version. "
            "Proceed with Caution and backup your data. "
            "Always confirm the correctness of your settings with the "
            "official programming tool.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_cross = False
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = True
        rf.has_rx_dtcs = True
        rf.valid_characters = chirp_common.CHARSET_ALPHANUMERIC
        rf.valid_tuning_steps = [5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0, 100.0]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_modes = MODES
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = ["", "S"]
        rf.valid_bands = [(136000000, 174000000), (400000000, 500000000)]
        rf.valid_name_length = 8
        rf.valid_special_chans = SPECIAL_CHANNELS
        rf.memory_bounds = (1, self._upper)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            self.pipe.write(b"\x45")
            raise
        except Exception as e:
            raise errors.RadioError("Failed to download from radio: %s" % e)
        self.process_mmap()

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            self.pipe.write(b"\x45")
            raise
        except Exception as e:
            raise errors.RadioError("Failed to upload to radio: %s" % e)

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

    def get_memory(self, number):

        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.number = MAX_CHANNELS + SPECIAL_CHANNELS.index(number) + 1
            mem.extd_number = number
        elif number > MAX_CHANNELS:
            mem.number = number
        else:
            mem.number = number
            _name = self._memobj.name[mem.number - 1]

        _mem = self._memobj.memory[mem.number - 1]

        if mem.number > MAX_CHANNELS:
            mem.immutable = ['name']
        else:
            mem.name, _, _ = _name.name.get_raw().partition(b"\xFF")
            mem.name = mem.name.decode('ascii').rstrip()

        if _mem.get_raw()[:4] == b"\xFF\xFF\xFF\xFF":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        offset = (int(_mem.tx_freq) * 10) - mem.freq
        if offset < 0:
            mem.offset = abs(offset)
            mem.duplex = "-"
        elif offset > 0:
            mem.offset = offset
            mem.duplex = "+"
        else:
            mem.offset = 0

        self._get_tone(_mem, mem)
        mem.power = POWER_LEVELS[_mem.highpower]
        mem.mode = MODES[_mem.wide]
        mem.skip = not _mem.scan and "S" or ""

        mem.extra = RadioSettingGroup("all", "All Settings")

        bcl = RadioSetting("bcl", "Busy Channel Lockout",
                           RadioSettingValueBoolean(bool(_mem.bcl)))
        mem.extra.append(bcl)

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0xA000
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
            _mem.set_raw(b"\xFF" * 16)
            return

        if mem.number < 129:
            _name = self._memobj.name[mem.number - 1]
            _namelength = self.get_features().valid_name_length
            for i in range(NAME_FIELD_SIZE):
                try:
                    _name.name[i] = mem.name[i]
                except IndexError:
                    _name.name[i] = "\xFF"

        # clear reserved fields
        _mem.unknown1 = 0xFF
        _mem.unknown2 = 0xFF
        _mem.unknown3 = 0xFF
        _mem.unknown4 = (0xFF, 0xFF)
        _mem.rx_freq = mem.freq / 10
        mem_offset = mem.offset or offset_for(mem.freq)
        if mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem_offset) / 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem_offset) / 10
        else:
            _mem.tx_freq = mem.freq / 10

        self._set_tone(mem, _mem)

        _mem.highpower = mem.power == POWER_LEVELS[1]
        _mem.wide = mem.mode == "NFM"
        _mem.scan = mem.skip != "S"

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _mem = self._memobj
        _settings = _mem.settings
        basic = RadioSettingGroup("basic", "Basic")
        display = RadioSettingGroup("display", "Display")
        scan = RadioSettingGroup("scan", "Scan")
        buttons = RadioSettingGroup("buttons", "Buttons")
        vfo = RadioSettingGroup("vfo", "VFO")
        advanced = RadioSettingGroup("advanced", "Advanced")
        aprs = RadioSettingGroup("aprs", "APRS")
        top = RadioSettings(basic, display, scan, buttons, vfo, advanced, aprs)

        basic.append(
            RadioSetting("save", "Power Save",
                         RadioSettingValueBoolean(_settings.save)))
        basic.append(
            RadioSetting("roger", "Roger Beep",
                         RadioSettingValueList(ROGER_LIST,
                                               current_index=_settings.roger)))
        basic.append(
            RadioSetting("beep", "System Beep",
                         RadioSettingValueBoolean(_settings.beep)))
        basic.append(
            RadioSetting("tot", "Timeout Timer (sec)",
                         RadioSettingValueList(TOT_LIST,
                                               current_index=_settings.tot)))
        basic.append(
            RadioSetting("toa", "Timeout Timer Alarm",
                         RadioSettingValueList(TOA_LIST,
                                               current_index=_settings.toa)))
        basic.append(
            RadioSetting("lockmode", "Lock Mode",
                         RadioSettingValueList(
                            LOCKMODE_LIST,
                            current_index=_settings.lockmode)))
        basic.append(
            RadioSetting("autolock", "Auto Lock",
                         RadioSettingValueList(
                            AUTOLOCK_LIST,
                            current_index=_settings.autolock)))
        basic.append(
            RadioSetting("auto_lock_dly", "Auto Lock Delay",
                         RadioSettingValueList(
                            AUTOLOCK_DLY_LIST,
                            current_index=_settings.auto_lock_dly)))
        display.append(
            RadioSetting("abr", "Screen Save",
                         RadioSettingValueList(ABR_LIST,
                                               current_index=_settings.abr)))
        display.append(
            RadioSetting("abr_lv", "Back Light Brightness",
                         RadioSettingValueList(ABR_LV_LIST,
                                               current_index=_settings.abr_lv)))
        display.append(
            RadioSetting("night_mode", "Night Mode (Light on Dark)",
                         RadioSettingValueBoolean(_settings.night_mode)))
        display.append(
            RadioSetting("menu_dly", "Menu Delay",
                         RadioSettingValueList(
                            MENU_DLY_LIST,
                            current_index=_settings.menu_dly)))
        display.append(
            RadioSetting("english", "Language",
                         RadioSettingValueList(LANG_LIST,
                                               current_index=_settings.english)))
        scan.append(
            RadioSetting("pri_scn", "Priority Scan",
                         RadioSettingValueBoolean(_settings.pri_scn)))
        scan.append(
            RadioSetting("pri_ch", "Priority Channel",
                         RadioSettingValueChannel(self, _settings.pri_ch)))
        scan.append(
            RadioSetting("sc_rev", "Scan Resume",
                         RadioSettingValueList(SC_REV_LIST,
                                               current_index=_settings.sc_rev)))
        scan.append(
            RadioSetting("sc_qt", "Code Save",
                         RadioSettingValueList(SC_QT_LIST,
                                               current_index=_settings.sc_qt)))
        buttons.append(
            RadioSetting("pf1_short", "PF1 (Side, Upper) Button Short Press",
                         RadioSettingValueList(PF1_LIST,
                                               current_index=_settings.pf1_short)))
        buttons.append(
            RadioSetting("pf1_long", "PF1 (Side, Upper) Button Long Press",
                         RadioSettingValueList(PF1_LIST,
                                               current_index=_settings.pf1_long)))
        buttons.append(
            RadioSetting("pf2_short", "PF2 (Side, Lower) Button Short Press",
                         RadioSettingValueList(PF2_LIST,
                                               current_index=_settings.pf2_short)))
        buttons.append(
            RadioSetting("pf2_long", "PF2 (Side, Lower) Button Long Press",
                         RadioSettingValueList(PF2_LIST,
                                               current_index=_settings.pf2_long)))
        buttons.append(
            RadioSetting("top_short", "Top Button Short Press",
                         RadioSettingValueList(TOP_LIST,
                                               current_index=_settings.top_short)))
        buttons.append(
            RadioSetting("top_long", "Top Button Long Press",
                         RadioSettingValueList(TOP_LIST,
                                               current_index=_settings.top_long)))
        vfo.append(
            RadioSetting("tdr", "VFO B Enabled",
                         RadioSettingValueBoolean(_settings.tdr)))
        vfo.append(
            RadioSetting("ch_a_step", "VFO Frequency Step (A)",
                         RadioSettingValueList(
                            STEP_LIST,
                            current_index=_settings.ch_a_step)))
        vfo.append(
            RadioSetting("ch_b_step", "VFO Frequency Step (B)",
                         RadioSettingValueList(
                            STEP_LIST,
                            current_index=_settings.ch_b_step)))
        vfo.append(
            RadioSetting("ch_a_sql", "Squelch (A)",
                RadioSettingValueList(SQL_LIST,
                                      current_index=_settings.ch_a_sql)))
        vfo.append(
            RadioSetting("ch_b_sql", "Squelch (B)",
                         RadioSettingValueList(SQL_LIST,
                                               current_index=_settings.ch_b_sql)))
        vfo.append(
            RadioSetting("ch_a_mem_ch", "Memory Channel (A)",
                         RadioSettingValueChannel(self,
                                                  _settings.ch_a_mem_ch)))
        vfo.append(
            RadioSetting("ch_b_mem_ch", "Memory Channel (B)",
                         RadioSettingValueChannel(self,
                                                  _settings.ch_b_mem_ch)))
        vfo.append(
            RadioSetting("ch_a_ch_mdf", "Memory Display Format (A)",
                         RadioSettingValueList(
                            MDF_LIST,
                            current_index=_settings.ch_a_ch_mdf)))
        vfo.append(
            RadioSetting("ch_b_ch_mdf", "Memory Display Format (B)",
                         RadioSettingValueList(
                            MDF_LIST,
                            current_index=_settings.ch_b_ch_mdf)))
        vfo.append(
            RadioSetting("ch_a_v_m", "VFO/MEM (A)",
                         RadioSettingValueList(
                             VM_LIST, current_index=_settings.ch_a_v_m)))
        vfo.append(
            RadioSetting("ch_b_v_m", "VFO/MEM (B)",
                         RadioSettingValueList(
                             VM_LIST, current_index=_settings.ch_b_v_m)))
        advanced.append(
            RadioSetting("vox_grd", "VOX Sensitivity",
                         RadioSettingValueList(
                             VOX_LIST, current_index=_settings.vox_grd)))
        advanced.append(
            RadioSetting("vox_dly", "VOX Delay",
                         RadioSettingValueList(
                             VOX_DLY_LIST, current_index=_settings.vox_dly)))
        advanced.append(
            RadioSetting("voice", "Voice Assist",
                         RadioSettingValueBoolean(_settings.voice)))
        advanced.append(
            RadioSetting("rpt_rct", "RPT Roger",
                         RadioSettingValueBoolean(_settings.rpt_rct)))
        aprs.append(
            RadioSetting("aprs_rx_band", "RX Band",
                         RadioSettingValueList(
                             APRS_RX_LIST,
                             current_index=_settings.aprs_rx_band)))
        aprs.append(
            RadioSetting("ch_a_mute", "Band A Mute",
                         RadioSettingValueBoolean(_settings.ch_a_mute)))
        aprs.append(
            RadioSetting("ch_b_mute", "Band B Mute",
                         RadioSettingValueBoolean(_settings.ch_b_mute)))
        aprs.append(
            RadioSetting("tx_priority", "TX Priority",
                RadioSettingValueList(
                    TX_PRIORITY_LIST,
                    current_index=_settings.tx_priority)))
        aprs.append(
            RadioSetting("aprs_rx_popup", "APRS Popup",
                         RadioSettingValueBoolean(_settings.aprs_rx_popup)))
        aprs.append(
            RadioSetting("aprs_rx_tone", "RX Tone",
                         RadioSettingValueBoolean(_settings.aprs_rx_tone)))
        aprs.append(
            RadioSetting("aprs_tx_tone", "TX Tone",
                         RadioSettingValueBoolean(_settings.aprs_tx_tone)))
        aprs.append(
            RadioSetting("beacon_exit_dly", "Beacon Message Delay",
                         RadioSettingValueList(
                             BEACON_EXIT_DLY_LIST,
                             current_index=_settings.beacon_exit_dly)))

        return top

    def set_settings(self, settings):
        _mem = self._memobj
        _settings = _mem.settings

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            name = element.get_name()
            value = element.value

            if hasattr(_settings, name):
                setattr(_settings, name, value)
