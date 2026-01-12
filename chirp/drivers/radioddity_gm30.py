# Copyright 2025 Mike Iacovacci <ascendr@linuxmail.org>
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

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct{
    u8     unknown02[256];
} unknown02[16];
struct{
    u8      bootscrmode;
    u8      bsmodepad[15];
    u8      bootscreen1[10];
    u8      bs1pad[6];
    u8      bootscreen2[10];
    u8      bs2pad[6];
    u8      unused[16];
    u8      timeout;
    u8      squelch;
    u8      vox_level;
    u8      batt_save:4,
            unk_bits:2,
            work_mode:1,
            voice_alert:1;
    u8      backlight;
    u8      beep_tone:1,
            auto_key_lock:1,
            unk_bit_2:1,
            ctcss_revert:1,
            scan_type:2,
            side_tone:2;
    u8      unk_bit_3:1,
            standby:1,
            roger:1,
            alarm_mode:2,
            alarm_sound:1,
            fm_radio:1,
            unk_bit_4:1;
    u8      tail_revert;
    u8      tail_delay;
    u8      tbst;
    u8      unk_sett[6];
    u8      unk_bits_5:6,
            b_ch_disp:1,
            a_ch_disp:1;
    u8      unk_sett_2[24];
    u8      passw_w_ena;
    u8      passw_r_ena;
    u8      passw_w_val[8];
    u8      passw_r_val[8];
    u8      unk_sett_3[5];
} settings;
struct{
    u8     unusedsettings[32];
} unusedsettings[124];
struct{
    u8     entry[5];
} dtmf_list[15];
struct{
    u8      dtmf_l_pad[5];
    u8      radio_id[5];
    u8      unk_dtmf[11];
    u8      unk_dtmf_bits:6,
            press_send:1,
            release_send:1;
    u8      delay_time;
    u8      digit_dur;
    u8      inter_dur;
    u8      unk_dtmf_2[28];
} dtmf;
struct{
    u8     unkdtmf[128];
} unuseddtmf[31];
struct{
    u8        unk_mem[16];
} tuning;
struct {
    lbcd      rx_freq[4];
    lbcd      tx_freq[4];
    u8        mem_changed;
    lbcd      rx_tone[2];
    lbcd      tx_tone[2];
    u8      unk_mem2:1,
            busy_lock:1,
            ptt_id:2,
            unk_mem3:1,
            mode:1,
            power:1,
            unk_mem4:1;
            u8 signal:4,
            unk_mem5:2,
            freq_hop:1,
            scan:1;
            u8 step;
} vfomemory[2];
struct {
    lbcd      rx_freq[4];
    lbcd      tx_freq[4];
    u8        mem_changed;
    lbcd      rx_tone[2];
    lbcd      tx_tone[2];
    u8      unk_mem2:1,
            busy_lock:1,
            ptt_id:2,
            unk_mem3:1,
            mode:1,
            power:1,
            unk_mem4:1;
            u8 signal:4,
            unk_mem5:2,
            freq_hop:1,
            scan:1;
            u8 step;
} memory[250];
struct{
    u8      unused_memch[16];
} unused_mem[3];
struct{
    u8     unknown17[256];
} unknown17[16];
struct{
    u8     unknown18[256];
} unknown18[16];
struct{
    u8     unknown19[256];
} unknown19[16];
struct{
    char      name[6];
    u8      pad[5];
} memnames[250];
struct{
    u8      unknames[64];
} unknownnames [21];
struct{
    u8      unknown25[256];
} unknown25[16];
struct{
    u8      unknown26[256];
} unknown26[16];
"""
# radio defines these types
# query each type to retrieve
# the mem location it is stored
TYPE_MAP = [
    (0x02, "unknown02"),
    (0x04, "settings"),
    (0x06, "dtmf"),
    (0x16, "memories"),
    (0x17, "unknown17"),
    (0x18, "unknown18"),
    (0x19, "unknown19"),
    (0x24, "chan_names"),
    (0x25, "unknown25"),
    (0x26, "unknown26")
]

# we only write these data types
# back to the radio. The 3rd tuple
# being the offset in _memobj
WRITE_MAP = [
    (0x04, "settings", 0x1000),
    (0x06, "dtmf", 0x2000),
    (0x16, "memories", 0x3000),
    (0x24, "chan_names", 0x7000)
]


def do_ack_ack(serial):
    serial.write(b'\x06')
    ack = serial.read(1)
    if ack != b'\x06':
        err = f"Error expected 06 ack got {ack}"
        LOG.debug(err)
        raise errors.RadioError(err)


def raw_send(serial, data, exlen):
    serial.write(data)
    return serial.read(exlen)


def do_read_cmd(serial, cmd, exlen):
    echo_ack = len(cmd) + 1  # ack 0x57 + echo of cmd
    resp = raw_send(serial, b'\x52' + cmd, exlen + echo_ack)
    if resp[0] != 0x57:
        raise errors.RadioError(f"Read CMD resp failed got {resp}")
    if len(resp[echo_ack:]) != exlen:
        raise errors.RadioError(f"Read CMD resp expect len={exlen} got {resp}")
    do_ack_ack(serial)
    return resp[echo_ack:]


def enter_prog(serial):
    resp = raw_send(serial, b'PSEARCH', 8)
    if len(resp) != 8:
        err = ("Enter programming failed" +
               f" Resp : {resp}")
        raise errors.RadioError(err)
    if resp[0] != 0x06:
        raise errors.RadioError("Enter programming: " +
                                f"Radio Bad Ack: {resp}")
    return resp[1:]


def exit_prog(serial):
    try:
        serial.write(b'\x06')
        serial.write(b'\x06')
        serial.write(b'\x00')
        serial.close()
        LOG.debug("Exited programming")
    except Exception as e:
        raise errors.RadioError(f"Error exiting programming {e}")


def check_ident(data):
    if data == b'P13GMRS':
        LOG.info(f"Radio is: {data}")
    else:
        err = (f"Ident returned unknown Radio: {data}")
        LOG.debug(err)
        raise errors.RadioError(err)


def do_sysinfo(serial):
    resp = raw_send(serial, b'PASSSTA', 3)
    if resp != b'\x50\x00\x00':
        raise errors.RadioError(f"Expected 0x500000 got {resp}")
    resp = raw_send(serial, b'SYSINFO', 1)
    if resp != b'\x06':
        raise errors.RadioError(f"ACK expected got {resp}")
    LOG.debug(f"SYSINFO: {resp}")


def do_readconfig(serial):
    # cmds start with 56, and expect 06 ack after recv ack
    for addr, _len in [(0x00000a0d, 13), (0x00100a0d, 13),
                       (0x00200a0d, 13), (0x0000000a, 11)]:
        cmd = struct.pack('>BL', 0x56, addr)
        resp = raw_send(serial, cmd, _len)
        if len(resp) != _len:
            raise errors.RadioError(f"Expected (_len) Bytes got {resp}")
        do_ack_ack(serial)
    return True


def do_prog2(serial):
    cmd = struct.pack('>LB', 0xffffffff, 0x0c)
    serial.write(cmd)  # no resp expected
    resp = raw_send(serial, b'P13GMRS', 1)
    if resp != b'\x06':
        raise errors.RadioError(f"Error expected 06 ack got {resp}")
    resp = raw_send(serial, b'\x02', 8)
    if len(resp) != 8:
        raise errors.RadioError(f"Error expected len 8 got {resp}")
    do_ack_ack(serial)


def do_read_tlmap(serial):
    """ The radio has defined types of config data.
        Before reading or writing, we ask the radio where
        The data type is stored in memory. The radio
        moves memory locations possibly for durability
        Build ephemeral map of type to location """
    tl_map = {m[0]: 0 for m in TYPE_MAP}
    for i in range(1, 16):
        addr = (i << 4 | 0x0f)
        # ask the radio where each data type is in mem
        cmd = struct.pack('>4B', 0xff, addr, 0x00, 0x01)
        resp = do_read_cmd(serial, cmd, 1)
        # mem location is for this prog session only
        r_int = struct.unpack('>B', resp)[0]
        if r_int in tl_map:
            tl_map[r_int] = (i << 4)
    return tl_map


def do_read_ranges(serial, loc, radio, status):
    # read each data/config type from the (loc)ation
    # obtained by tlmap query. each loc has 4 (pre)fix
    # block numbers. Each block is 64 bytes
    data = b''
    for i in range(16):
        for pre in range(0x0, 0xc1, 0x40):
            addr = struct.pack('>BBBB', pre, loc + i, 0x00, 0x40)
            data += do_read_cmd(serial, addr, 0x40)
            status.cur += 0x40
            radio.status_fn(status)
    return data


def do_upload_block(serial, loc, offset, radio, status):
    # write each config type to loc retrieved from tlmap
    # 4 defined (pre)fixes/blocks per (loc)ation
    # pre = 0x00 , 0x40 , 0x80, 0xc0
    # full command example  [57][80][4d]0040
    # 57 = write , 80 prefix/block , 4d location to write
    _mem = radio._memobj.get_raw()
    for i in range(16):
        for pre in range(0x0, 0xc1, 0x40):
            x = offset + (i * 0x100) + pre
            block = _mem[x:x + 0x40]
            addr = struct.pack('>BBBBB', 0x57, pre, loc + i, 0x00, 0x40)
            data = addr + block
            ack = raw_send(serial, data, 1)
            if ack != b'\x06':
                err = f"Bad ack on write expect 0x06 got {ack}"
                LOG.debug(err)
                raise errors.RadioError(err)
            status.cur += len(block)
            radio.status_fn(status)


def do_download(radio):
    data = b''
    try:
        status = chirp_common.Status()
        serial = radio.pipe
        serial.flush()
        ident = enter_prog(serial)
        check_ident(ident)
        do_sysinfo(serial)
        do_readconfig(serial)
        do_prog2(serial)
        tl_map = do_read_tlmap(serial)
        status.max = len(tl_map) * 0x1000
        status.msg = "Downloading..."
        for t, loc in tl_map.items():
            if loc == 0:
                raise errors.RadioError(f"TL Map failed {t} {loc}")
            data += do_read_ranges(serial, loc, radio, status)
    except Exception as e:
        raise errors.RadioError(f"Error during download {e}")
    finally:
        exit_prog(serial)
    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    try:
        status = chirp_common.Status()
        status.max = len(WRITE_MAP) * 0x1000
        serial = radio.pipe
        serial.flush()
        ident = enter_prog(serial)
        check_ident(ident)
        do_sysinfo(serial)
        do_readconfig(serial)
        do_prog2(serial)
        tl_map = do_read_tlmap(serial)
        for wt, label, offset in WRITE_MAP:
            status.msg = f"Uploading: {label}..."
            loc = tl_map[wt]
            do_upload_block(serial, loc, offset, radio, status)
    except errors.RadioError:
        raise
    except Exception as e:
        raise errors.RadioError(f"Error during upload {e}")
    finally:
        exit_prog(serial)


@directory.register
class RadioddityGM30(chirp_common.CloneModeRadio):
    """Radioddity GM-30"""
    VENDOR = "Radioddity"
    MODEL = "GM-30"
    BAUD_RATE = 57600
    POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=0.50),
                    chirp_common.PowerLevel("High", watts=3.00)]
    VALID_MODES = ["NFM", "FM"]
    _range = [(136000000, 174000000), (400000000, 470000000)]
    GMRS_RPTR = [462550000, 462575000, 462600000, 462625000, 462650000,
                 462675000, 462700000, 462725000]

    VALID_TONES = chirp_common.TONES
    VALID_DCS = [i for i in range(
        0, 778) if '9' not in str(i) and '8' not in str(i)]
    DCS_N = 0x80
    DCS_R = 0x40
    VALID_CHARSET = chirp_common.CHARSET_ASCII
    VALID_DTMF = [str(i) for i in range(0, 10)] + \
        ["A", "B", "C", "D", "*", "#"]
    ASCII_NUM = [str(i) for i in range(10)] + [' ']

    VALID_STEPS = [2.5, 5.0, 6.25, 10, 12.5, 20, 25, 50]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.valid_tuning_steps = self.VALID_STEPS
        rf.has_name = True
        rf.valid_characters = self.VALID_CHARSET
        rf.valid_name_length = 6
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.can_odd_split = False
        rf.can_delete = True
        rf.valid_modes = self.VALID_MODES
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "Tone->Tone",
            "->DTCS",
            "DTCS->",
            "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_skips = ["", "S"]
        rf.valid_bands = self._range
        rf.memory_bounds = (1, 250)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            data = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            err = f'Error during download {e}'
            LOG.error(err)
            raise errors.RadioError(err)
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except Exception as e:
            err = f'Error during upload {e}'
            LOG.error(err)
            raise errors.RadioError(err)

    def val_or_def(self, memidx, _list):
        try:
            return _list[memidx]
        except IndexError:
            return _list[0]

    def idx_or_def(self, memitem, _list):
        try:
            return _list.index(memitem)
        except ValueError:
            return 0

    def get_str_name(self, _name):
        return ''.join(filter
                       (lambda x: x in self.VALID_CHARSET,
                        str(_name)))

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._memobj.memory[number-1]
        _name = self._memobj.memnames[number-1]["name"]
        str_name = self.get_str_name(_name)
        mem.name = str_name.rstrip()

        if _mem.rx_freq.get_raw() == b'\xff\xff\xff\xff':
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10

        if _mem.tx_freq.get_raw() == b'\xff\xff\xff\xff':
            mem.duplex = 'off'
        elif int(_mem.tx_freq) - int(_mem.rx_freq) > 0:
            # '+' duplex
            mem.duplex = '+'
            mem.offset = (int(_mem.tx_freq) - int(_mem.rx_freq)) * 10
        elif int(_mem.tx_freq) - int(_mem.rx_freq) < 0:
            # '-' duplex
            mem.duplex = '-'
            mem.offset = (int(_mem.rx_freq) - int(_mem.tx_freq)) * 10

        mem.mode = self.val_or_def(_mem.mode, self.VALID_MODES)
        mem.power = self.val_or_def(_mem.power, self.POWER_LEVELS)
        mem.skip = "" if _mem.scan else "S"

        if 1 <= mem.number <= 7 or 15 <= mem.number <= 22:
            mem.duplex = ""
            mem.immutable = ['duplex', 'offset', 'empty']
        elif 8 <= mem.number <= 14:
            mem.duplex = "off"
            mem.immutable += ['duplex', 'offset', 'empty', 'mode', 'power']
        elif 23 <= mem.number <= 54:
            mem.offset = 5 * 1000000
            mem.duplex = '+'
            mem.immutable = ['duplex', 'offset', 'empty']
        else:
            mem.offset = 0
            mem.duplex = "off"
            mem.immutable += ['offset', 'duplex']
        if 0 < mem.number <= 30:
            mem.immutable = mem.immutable + ['freq']

        txtone = self.get_tone(_mem.tx_tone)
        rxtone = self.get_tone(_mem.rx_tone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSettingValueBoolean(_mem.busy_lock)
        rset = RadioSetting("busy_lock", "Busy Lock", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(_mem.freq_hop)
        rset = RadioSetting("freq_hop", "Freq. Hop", rs)
        mem.extra.append(rset)

        _current = _mem.signal if _mem.signal else 1
        rs = RadioSettingValueInteger(1, 15, current=_current)
        rset = RadioSetting("signal", "DTMF ID", rs)
        mem.extra.append(rset)

        options = ['Off', 'BOT', 'EOT', 'BOTH']
        rs = RadioSettingValueList(options, current_index=_mem.ptt_id)
        rset = RadioSetting("ptt_id", "PTT ID", rs)
        mem.extra.append(rset)

        return mem

    def validate_memory(self, mem):
        if 31 <= mem.number <= 54:
            if mem.freq not in self.GMRS_RPTR:
                return [chirp_common.ValidationError(
                    'Only GMRS repeater freq. permitted'
                    ' on channels 31 - 54')]
        return super().validate_memory(mem)

    def set_memory(self, mem):
        number = mem.number
        _mem = self._memobj.memory[number-1]
        _name = self._memobj.memnames[number-1]
        newname = [str(c) for c in mem.name]
        _name.name = "".join(newname).ljust(6, '\x00')

        if mem.empty:
            _mem.set_raw(b'\xff' * 13 + b'\x06\x11\x00')
            return

        _mem.rx_freq = mem.freq // 10

        if mem.duplex == "+":
            _mem.tx_freq = (mem.freq + mem.offset) // 10
        elif mem.duplex == "-":
            _mem.tx_freq = (mem.freq - mem.offset) // 10
        elif mem.duplex == "":
            _mem.tx_freq = _mem.rx_freq
        elif mem.duplex == "off":
            _mem.tx_freq.fill_raw(b'\xff')

        _mem.mode = self.idx_or_def(mem.mode, self.VALID_MODES)
        _mem.power = self.idx_or_def(mem.power, self.POWER_LEVELS)
        _mem.scan = False if mem.skip == "S" else True

        ((txmode, txval, txpol),
         (rxmode, rxval, rxpol)) = chirp_common.split_tone_encode(mem)
        self.set_tone(_mem.tx_tone, txmode, txval, txpol)
        self.set_tone(_mem.rx_tone, rxmode, rxval, rxpol)

        # extra settings
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_tone(self, _memval):
        _memval[1].ignore_bits(self.DCS_N | self.DCS_R)
        dcsn = _memval[1].get_bits(self.DCS_N)
        dcsr = _memval[1].get_bits(self.DCS_R)
        rb = _memval[1].get_raw()
        if rb == b'\xff' or rb == b'\x00':
            return "", 0, None
        elif dcsn:
            pol = "R" if dcsr else "N"
            return "DTCS", int(_memval), pol
        else:
            return "Tone",  int(_memval) / 10, None

    def set_tone(self, _memval, mode, val, pol):
        # sets tones in _mem from ui edit
        _memval[1].ignore_bits(self.DCS_N | self.DCS_R)
        if mode == "":
            _memval.set_raw(b'\xff\xff')
        if mode == "Tone":
            _memval[1].clr_bits(self.DCS_N | self.DCS_R)
            _memval.set_value(val * 10)
        if mode == "DTCS":
            _memval[1].set_bits(self.DCS_N)
            if pol == 'R':
                _memval[1].set_bits(self.DCS_R)
            else:
                _memval[1].clr_bits(self.DCS_R)
            _memval.set_value(val)

    def get_settings(self):
        _settings = self._memobj.settings
        _dtmf = self._memobj.dtmf
        _dtmf_list = self._memobj.dtmf_list

        gsettings = RadioSettingGroup("gsettings", "General Settings")
        group = RadioSettings(gsettings)

        _options = ["Logo", "Message", "Voltage"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.bootscrmode)
        rset = RadioSetting("settings.bootscrmode", "Boot Screen Mode", rs)
        gsettings.append(rset)

        _current = "".join(chr(i) for i in _settings.bootscreen1
                           if chr(i) in self.VALID_CHARSET)
        rs = RadioSettingValueString(minlength=0, maxlength=10,
                                     current=_current,
                                     charset=self.VALID_CHARSET,
                                     mem_pad_char=' ')
        rset = RadioSetting("settings.bootscreen1",
                            "Boot Screen 1", rs)
        gsettings.append(rset)

        _current = "".join(chr(i) for i in _settings.bootscreen2
                           if chr(i) in self.VALID_CHARSET)
        rs = RadioSettingValueString(minlength=0, maxlength=10,
                                     current=_current,
                                     charset=self.VALID_CHARSET,
                                     mem_pad_char=' ')
        rset = RadioSetting("settings.bootscreen2",
                            "Boot Screen 2", rs)
        gsettings.append(rset)

        _options = [str(i) for i in range(0, 601, 15)]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.timeout)
        rset = RadioSetting("settings.timeout", "Timeout (s)", rs)
        gsettings.append(rset)

        rs = RadioSettingValueInteger(minval=0, maxval=9,
                                      current=_settings.squelch, step=1)
        rset = RadioSetting("settings.squelch", "Squelch Level", rs)
        gsettings.append(rset)

        rs = RadioSettingValueInteger(minval=0, maxval=9,
                                      current=_settings.vox_level, step=1)
        rset = RadioSetting("settings.vox_level", "Vox Level", rs)
        gsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.voice_alert, mem_vals=(0, 1))
        rset = RadioSetting("settings.voice_alert", "Voice Alert", rs)
        gsettings.append(rset)

        _options = ["Freq. Mode", "Ch. Mode"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.work_mode)
        rset = RadioSetting("settings.work_mode", "Display Mode", rs)
        gsettings.append(rset)

        _options = ["None", "1:1", "1:2", "1:3", "1:4"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.batt_save)
        rset = RadioSetting("settings.batt_save", "Battery Save Mode", rs)
        gsettings.append(rset)

        _options = ["Bright", "1", "2", "3", "4", "5",
                    "6", "7", "8", "9", "10"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.backlight)
        rset = RadioSetting("settings.backlight", "Backlight", rs)
        gsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.auto_key_lock, mem_vals=(0, 1))
        rset = RadioSetting("settings.auto_key_lock", "Auto Key Lock", rs)
        gsettings.append(rset)

        _options = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.side_tone)
        rset = RadioSetting("settings.side_tone", "DTMF Side Tone", rs)
        gsettings.append(rset)

        _options = ["Time", "Carrier", "Search"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.scan_type)
        rset = RadioSetting("settings.scan_type", "Scan Type", rs)
        gsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.ctcss_revert, mem_vals=(0, 1))
        rset = RadioSetting("settings.ctcss_revert", "CTCSS Tail Revert", rs)
        gsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.beep_tone, mem_vals=(0, 1))
        rset = RadioSetting("settings.beep_tone", "Beep Tone", rs)
        gsettings.append(rset)

        _options = ["On Site", "Send Sound", "Send Code"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.alarm_mode)
        rset = RadioSetting("settings.alarm_mode", "Alarm Mode", rs)
        gsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.fm_radio, mem_vals=(0, 1))
        rset = RadioSetting("settings.fm_radio", "FM Radio", rs)
        gsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.roger, mem_vals=(0, 1))
        rset = RadioSetting("settings.roger", "Roger Beep", rs)
        gsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.standby, mem_vals=(0, 1))
        rset = RadioSetting("settings.standby", "Dual Standby", rs)
        gsettings.append(rset)

        _options = [str(i) for i in range(0, 1001, 100)]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.tail_revert)
        rset = RadioSetting("settings.tail_revert",
                            "Repeater Tail Revert (ms)", rs)
        gsettings.append(rset)

        # same options as tail_rvt
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.tail_delay)
        rset = RadioSetting("settings.tail_delay",
                            "Repeater Tail Delay (ms)", rs)
        gsettings.append(rset)

        _options = ["1000", "1450", "1750", "2100"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.tbst)
        rset = RadioSetting("settings.tbst", "Tone Burst", rs)
        gsettings.append(rset)

        _options = ["Name + Number", "Freq. + Number"]
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.a_ch_disp)
        rset = RadioSetting("settings.a_ch_disp", "A Channel Display Type", rs)
        gsettings.append(rset)

        # same options as a_chan_disp
        rs = RadioSettingValueList(_options,
                                   current_index=_settings.b_ch_disp)
        rset = RadioSetting("settings.b_ch_disp", "B Channel Display Type", rs)
        gsettings.append(rset)

        # DTMF Menu
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        group.append(dtmf)

        def _dtmf_decode(setting, pad_len):
            _map = list(range(10)) + ['A', 'B', 'C', 'D', '*', '#']
            s = ""
            for i in setting:
                _i = int(i)
                if _i < len(_map):
                    s += str(_map[_i])
            return s.ljust(pad_len)

        _current = _dtmf_decode(_dtmf.radio_id, 5)
        rs = RadioSettingValueString(
            minlength=5, maxlength=5, current=_current)
        rset = RadioSetting("dtmf.radio_id", "Radio ID", rs)
        dtmf.append(rset)

        rs = RadioSettingValueBoolean(
            current=_dtmf.press_send, mem_vals=(0, 1))
        rset = RadioSetting("dtmf.press_send", "PTT Press Send", rs)
        dtmf.append(rset)

        rs = RadioSettingValueBoolean(
            current=_dtmf.release_send, mem_vals=(0, 1))
        rset = RadioSetting("dtmf.release_send", "PTT Release Send", rs)
        dtmf.append(rset)

        _options = [str(i) for i in range(100, 1010, 50)]
        rs = RadioSettingValueList(_options,
                                   current_index=_dtmf.delay_time)
        rset = RadioSetting("dtmf.delay_time", "Delay Time (ms)", rs)
        dtmf.append(rset)

        _options = [str(i) for i in range(80, 2010, 10)]
        rs = RadioSettingValueList(_options,
                                   current_index=_dtmf.digit_dur)
        rset = RadioSetting("dtmf.digit_dur", "Digit Duration (ms)", rs)
        dtmf.append(rset)

        # uses same options as digit_dur
        rs = RadioSettingValueList(_options,
                                   current_index=_dtmf.inter_dur)
        rset = RadioSetting(
            "dtmf.inter_dur", "Digit Interval Duration (ms)", rs)
        dtmf.append(rset)

        # DTMF Entries List
        dtmflist = RadioSettingGroup("dtmflist", "DTMF List")
        group.append(dtmflist)
        for i in range(0, 15):  # Entries # 1-15
            rs = RadioSettingValueString(
                minlength=0, maxlength=5,
                current=_dtmf_decode(_dtmf_list[i].entry, 5),
                autopad=False,
                charset=self.VALID_DTMF + [' '])
            rset = RadioSetting(f"dtmf_list[{i}].entry", f"Entry {i+1}", rs)
            dtmflist.append(rset)

        # Password Menu
        pro = RadioSettingGroup("protect", "Protect")
        group.append(pro)

        def _ascii_num_filter(setting):
            s = ""
            for i in setting:
                if chr(i) in self.ASCII_NUM:
                    s += str(chr(i))
            return s

        rs = RadioSettingValueBoolean(
            current=_settings.passw_w_ena, mem_vals=(0, 1))
        rs.set_mutable(False)
        rset = RadioSetting("settings.passw_w_ena", "Write Protect", rs)
        pro.append(rset)

        _current = _ascii_num_filter(_settings.passw_w_val)
        rs = RadioSettingValueString(
            minlength=0, maxlength=8, current=_current,
            charset=self.ASCII_NUM)
        rs.set_mutable(False)
        rset = RadioSetting("settings.passw_w_val", "Write Password", rs)
        pro.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.passw_r_ena, mem_vals=(0, 1))
        rs.set_mutable(False)
        rset = RadioSetting("settings.passw_r_ena", "Read Protect", rs)
        pro.append(rset)

        _current = _ascii_num_filter(_settings.passw_r_val)
        rs = RadioSettingValueString(
            minlength=0, maxlength=8, current=_current,
            charset=self.ASCII_NUM)
        rs.set_mutable(False)
        rset = RadioSetting("settings.passw_r_val", "Read Password", rs)
        pro.append(rset)

        return group

    def _ff_pad__mem(self, obj, setting, element, charset, allow_space=False):
        """ set_settings helper for 0xff padded elements
            optional remove space chars
        """
        _charset = [c for c in list(charset)]
        if not allow_space:
            _charset = [c for c in list(charset) if c != ' ']
        _val = [0xff] * len(obj[setting])
        _i = 0  # offset for invalid chars
        for i in range(len(obj[setting])):
            if element.value[i] in _charset:
                _val[i - _i] = ord(element.value[i])
            else:
                _i += 1
        setattr(obj, setting, _val)

    def _dtmf_set__mem(self, obj, setting, element):
        _dtmf_map = [str(i) for i in range(10)]
        _dtmf_map += ['A', 'B', 'C', 'D', '*', '#']
        _val = [0xff] * len(obj[setting])
        _os = 0  # offset _mem setting idx for pad chars
        for i in range(len(element.value)):
            if element.value[i] in _dtmf_map:
                _val[i - _os] = _dtmf_map.index(element.value[i])
            else:
                _os += 1
        setattr(obj, setting, _val)

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        toks = element.get_name().split(".")
                        obj = self._memobj
                        for tok in toks[:-1]:
                            if '[' in tok:
                                t, i = tok.split("[")
                                i = int(i[:-1])
                                obj = getattr(obj, t)[i]
                            else:
                                obj = getattr(obj, tok)
                        setting = toks[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("applying callback")
                        element.run_apply_callback()

                    if element.value.get_mutable():
                        if setting in ['passw_w_val', 'passw_r_val']:
                            self._ff_pad__mem(
                                obj, setting, element, self.ASCII_NUM)
                        elif setting in ['bootscreen1', 'bootscreen2']:
                            self._ff_pad__mem(
                                obj, setting, element, self.VALID_CHARSET,
                                allow_space=True)
                        elif setting == 'entry':
                            self._dtmf_set__mem(
                                obj, setting, element)
                        else:
                            setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise


@directory.register
class RadioddityMU5(RadioddityGM30):
    """Radioddity MU-5 (MURS)

    Identical to Radioddity GM-30 except for the following:

    MURS channels 1-20 are fixed to the 5 MURS frequencies in a repeating
    pattern. Frequency in EEPROM is ignored for 1-20. Channels 21-250 are
    user-programmable RX-only channels. Changing power level is not allowed
    on 1-20. It is possible to set power level on 21-250, but it is not used
    (radio forces RX-only).
    """
    VENDOR = "Radioddity"
    MODEL = "MU-5"

    # MU-5 does not actually support variable power levels
    # MURS channels are fixed to "Low" power which is presumably 2W
    POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=2.00),
                    chirp_common.PowerLevel("High", watts=2.00)]

    MURS_FREQS = [151820000, 151880000, 151940000, 154570000, 154600000]

    def _get_murs_freq(self, channel):
        return self.MURS_FREQS[(channel - 1) % 5]

    def _is_murs_narrowband(self, channel):
        return ((channel - 1) % 5) < 3

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._memobj.memory[number-1]
        _name = self._memobj.memnames[number-1]["name"]
        str_name = self.get_str_name(_name)
        mem.name = str_name.rstrip()

        # 1-20 always exist and may have 0xFFFFFFFF for freq
        # other channels with 0xFFFFFFFF for freq are empty
        if _mem.rx_freq.get_raw() == b'\xff\xff\xff\xff':
            if not (1 <= number <= 20):
                mem.empty = True
                return mem

        mem.freq = int(_mem.rx_freq) * 10

        if _mem.tx_freq.get_raw() == b'\xff\xff\xff\xff':
            mem.duplex = 'off'
        elif int(_mem.tx_freq) - int(_mem.rx_freq) > 0:
            mem.duplex = '+'
            mem.offset = (int(_mem.tx_freq) - int(_mem.rx_freq)) * 10
        elif int(_mem.tx_freq) - int(_mem.rx_freq) < 0:
            mem.duplex = '-'
            mem.offset = (int(_mem.rx_freq) - int(_mem.tx_freq)) * 10

        mem.mode = self.val_or_def(_mem.mode, self.VALID_MODES)
        mem.power = self.val_or_def(_mem.power, self.POWER_LEVELS)
        mem.skip = "" if _mem.scan else "S"

        # MURS channels 1-20: fixed freq, simplex, fixed power
        if 1 <= mem.number <= 20:
            mem.freq = self._get_murs_freq(mem.number)
            mem.duplex = ""
            mem.offset = 0
            mem.immutable = ['freq', 'duplex', 'offset', 'power', 'empty']
            # Narrowband channels have fixed mode
            if self._is_murs_narrowband(mem.number):
                mem.mode = "NFM"
                mem.immutable = mem.immutable + ['mode']
        # Channels 21-250: RX-only user channels
        elif mem.number > 20:
            mem.duplex = "off"
            mem.immutable = ['duplex', 'offset']

        txtone = self.get_tone(_mem.tx_tone)
        rxtone = self.get_tone(_mem.rx_tone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSettingValueBoolean(_mem.busy_lock)
        rset = RadioSetting("busy_lock", "Busy Lock", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(_mem.freq_hop)
        rset = RadioSetting("freq_hop", "Freq. Hop", rs)
        mem.extra.append(rset)

        _current = _mem.signal if _mem.signal else 1
        rs = RadioSettingValueInteger(1, 15, current=_current)
        rset = RadioSetting("signal", "DTMF ID", rs)
        mem.extra.append(rset)

        options = ['Off', 'BOT', 'EOT', 'BOTH']
        rs = RadioSettingValueList(options, current_index=_mem.ptt_id)
        rset = RadioSetting("ptt_id", "PTT ID", rs)
        mem.extra.append(rset)

        return mem

    def validate_memory(self, mem):
        if 1 <= mem.number <= 20:
            expected_freq = self._get_murs_freq(mem.number)
            if mem.freq != expected_freq:
                return [chirp_common.ValidationError(
                    f'MURS Channel {mem.number} must be '
                    f'{expected_freq / 1000000:.3f} MHz')]
            if self._is_murs_narrowband(mem.number) and mem.mode != "NFM":
                return [chirp_common.ValidationError(
                    f'MURS Channel {mem.number} must be narrowband (NFM)')]
        return chirp_common.CloneModeRadio.validate_memory(self, mem)

    def set_memory(self, mem):
        # For MURS channels 1-20, write 0xFFFFFFFF for rx/tx freq
        # The radio firmware hardcodes the actual MURS frequency
        # This is what the official CPS does
        if 1 <= mem.number <= 20:
            number = mem.number
            _mem = self._memobj.memory[number-1]
            _name = self._memobj.memnames[number-1]
            newname = [str(c) for c in mem.name]
            _name.name = "".join(newname).ljust(6, '\x00')

            if mem.empty:
                _mem.set_raw(b'\xff' * 13 + b'\x06\x11\x00')
                return

            _mem.rx_freq.fill_raw(b'\xff')
            _mem.tx_freq.fill_raw(b'\xff')

            _mem.mode = self.idx_or_def(mem.mode, self.VALID_MODES)
            _mem.power = self.idx_or_def(mem.power, self.POWER_LEVELS)
            _mem.scan = False if mem.skip == "S" else True

            ((txmode, txval, txpol),
             (rxmode, rxval, rxpol)) = chirp_common.split_tone_encode(mem)
            self.set_tone(_mem.tx_tone, txmode, txval, txpol)
            self.set_tone(_mem.rx_tone, rxmode, rxval, rxpol)

            for setting in mem.extra:
                setattr(_mem, setting.get_name(), setting.value)
        else:
            super().set_memory(mem)
