# Copyright 2026
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import struct

from chirp import bitwise, chirp_common, directory, errors, memmap, util
from chirp import kenwood_tone
from chirp.settings import MemSetting, RadioSettingGroup, RadioSettings
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueInteger
from chirp.settings import RadioSettingValueList

LOG = logging.getLogger("hyt_f3")

LAYOUT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 spare0:3, bcl:2, spare1:3;
  u8 spare2:2, highpower:1, wide:1, spare3:4;
  u8 trailer[2];
} memory[16];
#seekto 0x012F;
struct {
  u8 unused_voice:6,
     voice:2;
  u8 unused_tot:2,
     tot:6;
  u8 unused_totalert:4,
     totalert:4;
  u8 gap0[2];
  u8 unused_squelch:4,
     squelch:4;
  u8 unused_save:7,
     save:1;
  u8 unused_beep:7,
     beep:1;
  u8 gap1[2];
  u8 unused_vox:7,
     vox:1;
  u8 unused_voxgain:3,
     voxgain:5;
  u8 unused_voxdelay:5,
     voxdelay:3;
} settings;
#seekto 0x017E;
lbit skipflags[16];
"""

_ACK = b"\x06"
_IDENT = b"P32073"
_PIECE = 8
_PULL_END = 0x400
_PUSH_END = 0x330
_EMPTY4 = b"\xff" * 4
_SEED = bytes.fromhex("0000000000000000ffffffff00bfa0f8")
_TONES = kenwood_tone.KenwoodToneModel(
    dcs_base=0x2800, pol_mask=0x8000, tone_init=0xFFFF, tone_flag=0x0000)
_WATTS = [chirp_common.PowerLevel("Low", watts=1.00),
          chirp_common.PowerLevel("High", watts=5.00)]
_BCL = ("Off", "Carrier", "QT/DQT")
_TOT = ("Off",) + tuple("%s seconds" % sec for sec in range(15, 615, 15))
_PREALERT = ("Off",) + tuple("%s seconds" % sec for sec in range(1, 11))
_SPEECH = ("Off", "Chinese", "English")
_VOX_GAIN = ("Off",) + tuple(str(level) for level in range(1, 17))
_VOX_HANG = ("0.5", "1.0", "1.5", "2.0", "2.5", "3.0")
_DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
_CROSSES = ("Tone->Tone", "Tone->DTCS", "DTCS->Tone", "->Tone",
            "->DTCS", "DTCS->", "DTCS->DTCS")


def _write_read(radio, payload, count):
    radio.pipe.write(payload)
    return radio.pipe.read(count)


def _enter_program_mode(radio):
    reply = b""
    for _n in range(5):
        reply = _write_read(radio, b"PROGRAM", 1)
        if reply == _ACK:
            break
    if not reply:
        raise errors.RadioNoResponse()
    if reply != _ACK:
        raise errors.RadioError("HYT F3 ignored PROGRAM")
    ident = _write_read(radio, b"\x02", 8)
    if len(ident) != 8 or not ident.startswith(_IDENT):
        LOG.debug("ident %s", util.hexprint(ident))
        raise errors.RadioError(
            "HYT F3 ident %r lacks P32073" % (ident,))
    if _write_read(radio, _ACK, 1) != _ACK:
        raise errors.RadioError("HYT F3 rejected the ident handshake")
    return ident


def _exit_program_mode(radio):
    try:
        radio.pipe.write(b"E")
    except Exception:
        LOG.debug("HYT F3 stayed in programming mode")


def _read_block(radio, addr):
    frame = struct.pack(">cHb", b"R", addr, _PIECE)
    pkt = _write_read(radio, frame, 4 + _PIECE)
    good = pkt[:4] == b"W" + frame[1:] and _write_read(radio, _ACK, 1) == _ACK
    if not good or len(pkt) != 4 + _PIECE:
        LOG.debug("stall %04x %s", addr, util.hexprint(pkt))
        raise errors.RadioError("HYT F3 read stalled at %04x" % addr)
    return pkt[4:]


def _write_block(radio, addr):
    chunk = radio.get_mmap()[addr:addr + _PIECE]
    frame = struct.pack(">cHb", b"W", addr, _PIECE) + chunk
    if _write_read(radio, frame, 1) != _ACK:
        raise errors.RadioError("HYT F3 write stalled at %04x" % addr)


def _download(radio):
    _enter_program_mode(radio)
    try:
        blob = b""
        st = chirp_common.Status()
        st.msg = "Reading HYT F3"
        st.max = _PULL_END
        addr = 0
        while addr < _PULL_END:
            blob += _read_block(radio, addr)
            addr += _PIECE
            st.cur = addr
            radio.status_fn(st)
        return memmap.MemoryMapBytes(blob)
    finally:
        _exit_program_mode(radio)


def _upload(radio):
    _enter_program_mode(radio)
    try:
        st = chirp_common.Status()
        st.msg = "Writing HYT F3"
        st.max = _PUSH_END
        addr = 0
        while addr < _PUSH_END:
            _write_block(radio, addr)
            addr += _PIECE
            st.cur = addr
            radio.status_fn(st)
    finally:
        _exit_program_mode(radio)


def _list_setting(path, title, options, raw):
    return MemSetting(
        path, title,
        RadioSettingValueList(options, current_index=int(raw)))


@directory.register
class HYTF3Radio(chirp_common.CloneModeRadio,
                 chirp_common.ExperimentalRadio):
    """HYT F3"""
    VENDOR = "HYT"
    MODEL = "F3"
    BAUD_RATE = 9600

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = _(
            "This driver is in development and should be "
            "considered as experimental.")
        rp.pre_download = _(
            "Follow these instructions to download your radio:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio (unlock it if password protected)\n"
            "4 - Click OK to start\n")
        rp.pre_upload = _(
            "Follow these instructions to upload your radio:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio (unlock it if password protected)\n"
            "4 - Click OK to start\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        for name in ("has_settings", "has_ctone", "has_cross",
                     "has_rx_dtcs", "can_odd_split"):
            setattr(rf, name, True)
        for name in ("has_bank", "has_tuning_step", "has_name"):
            setattr(rf, name, False)
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = list(_CROSSES)
        rf.valid_power_levels = _WATTS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]
        rf.valid_dtcs_codes = _DTCS
        rf.memory_bounds = (1, 16)
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
        rf.valid_bands = [(400000000, 520000000)]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(LAYOUT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception as exc:
            LOG.exception("HYT F3 download failed: %s", exc)
            raise errors.RadioError("HYT F3 download failed")
        self.process_mmap()

    def sync_out(self):
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as exc:
            LOG.exception("HYT F3 upload failed: %s", exc)
            raise errors.RadioError("HYT F3 upload failed")

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _channel_template(self):
        for idx in range(16):
            raw = self._memobj.memory[idx].get_raw()
            if raw[:4] not in (_EMPTY4, b"\x00" * 4):
                return raw
        return _SEED

    def get_memory(self, number):
        slot = self._memobj.memory[number - 1]
        mem = chirp_common.Memory()
        mem.number = number
        rx = int(slot.rxfreq)
        mem.freq = rx * 10
        if rx == 0 or slot.rxfreq.get_raw() == _EMPTY4:
            mem.freq = 0
            mem.empty = True
            mem.skip = "S"
            return mem
        txraw = slot.txfreq.get_raw()
        tx = int(slot.txfreq)
        if txraw == _EMPTY4:
            mem.duplex, mem.offset = "off", 0
        elif rx == tx:
            mem.duplex, mem.offset = "", 0
        else:
            mem.duplex = "-" if rx > tx else "+"
            mem.offset = abs(tx - rx) * 10
        mem.mode = "FM" if slot.wide else "NFM"
        _TONES.get_tone(slot, mem)
        mem.power = _WATTS[int(slot.highpower)]
        mem.skip = "" if int(self._memobj.skipflags[number - 1]) else "S"
        mem.extra = RadioSettingGroup("Extra", "extra")
        mem.extra.append(_list_setting(
            "bcl", "Busy Channel Lockout", _BCL, slot.bcl))
        return mem

    def set_memory(self, mem):
        slot = self._memobj.memory[mem.number - 1]
        if mem.empty:
            slot.set_raw(b"\xff" * 16)
            self._memobj.skipflags[mem.number - 1] = 0
            return
        if slot.rxfreq.get_raw() in (_EMPTY4, b"\x00" * 4):
            slot.set_raw(self._channel_template())
        slot.rxfreq = mem.freq // 10
        if mem.duplex == "off":
            slot.txfreq.set_raw(_EMPTY4)
        elif mem.duplex == "split":
            slot.txfreq = mem.offset // 10
        elif mem.duplex == "+":
            slot.txfreq = (mem.freq + mem.offset) // 10
        elif mem.duplex == "-":
            slot.txfreq = (mem.freq - mem.offset) // 10
        else:
            slot.txfreq = mem.freq // 10
        slot.wide = mem.mode == "FM"
        _TONES.set_tone(mem, slot)
        try:
            slot.highpower = _WATTS.index(mem.power)
        except ValueError:
            slot.highpower = 1
        self._memobj.skipflags[mem.number - 1] = int(mem.skip != "S")
        for item in mem.extra:
            item.apply_to_memobj(slot)

    def get_settings(self):
        cfg = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        basic.append(MemSetting(
            "settings.squelch", "Squelch Level",
            RadioSettingValueInteger(0, 9, int(cfg.squelch))))
        basic.append(_list_setting(
            "settings.tot", "Time-out timer", _TOT, cfg.tot))
        basic.append(_list_setting(
            "settings.totalert", "TOT Pre-alert", _PREALERT, cfg.totalert))
        basic.append(_list_setting(
            "settings.voice", "Voice Prompts", _SPEECH, cfg.voice))
        basic.append(MemSetting(
            "settings.beep", "Beep",
            RadioSettingValueBoolean(bool(cfg.beep))))
        basic.append(MemSetting(
            "settings.save", "Battery Save",
            RadioSettingValueBoolean(bool(cfg.save))))
        basic.append(MemSetting(
            "settings.vox", "VOX",
            RadioSettingValueBoolean(bool(cfg.vox))))
        basic.append(_list_setting(
            "settings.voxgain", "VOX Gain", _VOX_GAIN, cfg.voxgain))
        basic.append(_list_setting(
            "settings.voxdelay", "VOX Delay", _VOX_HANG, cfg.voxdelay))
        return RadioSettings(basic)

    def set_settings(self, settings):
        settings.apply_to(self._memobj)
