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

from chirp import chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettingValueMap, RadioSettings

import struct
import logging

LOG = logging.getLogger(__name__)

SERIAL_TIMEOUT = 1.0

MEM_FORMAT = """
// #seekto 0x0000;
struct{
    char    model[8];
    u8      mode;
    char    ver[4];
    u8      ri_unk[2];
    u8      ack;
} radio_info;

struct{
    u8     vfo1[32];
    u8     vfo2[32];
} vfo;

struct{
    lbit      bitfield[256];
} chans_present[2];

struct{
    lbit      bitfield[256];
} chans_scanned[2];

struct {
    bbcd    freq[4];
    bbcd     tx_offset[4];
    u8      step;
    u8          unk_mem:1,
                nc:1,
                unk_mem2:2,
                compander:1,
                channel_width:1,
                reverse:1,
                tx_off:1;
    u8          unk_mem3:3,
                talkaround:1,
                txpower:2,
                duplex:2;
    u8      specdcs;
    u16     scramhz;
    u16     decode;
    u16     encode;
    u8      scrambler;
    char    name[8];
    u8      busychannellockout;
    u8      tone_id;
    u8      unk_mem4[3];
} memory[504];

struct{
    u8      dispmode;
    u8      unk_fs[7];
    u8      squelch;
    u8      scan_pause;
    u8      unk_fs1;
    u8      backlight;
    u8      unk_fs2;
    u8      vicedisp;
    u8      unk_fs3[2];
    u8          beep:1,
                alarm_off:1,
                main:1,
                unkfs4:4,
                moni_key:1;
    u8      unk_fs5;
    u8      tot;
    u8      unk_fs6[3];
    u8      dtmf_trans;
    u8      language;
    u8      tbst_freq;
    u8      vox_level;
    u8      vox_delay;
    u8      tail_elim_type;
    u8          unk_fs7:4,
                setup_inhib:1,
                unk_fs8:2,
                init_inhib:1;
    u8      unk_fs9;
    u8      dcs_tail_elim;
    u8      sql_tail_elim;
} func_settings;

struct{
    u8      m[16];
}dtmf_list[16];

struct{
    u8      interval_char;
    u8      group_code;
    u8      decoding;
    u8      pretime;
    u8      first_dig_tm;
    u8      autoreset_tm;
    u8      unk_dtmf;
    u8      self_id[3];
    u8      unk_dtmf1[3];
    u8      side_tone;
    u8      timelapse_enc;
    u8      pttid_pause;
}dtmf_menu;

struct{
    u8      unk_menu1[16];
} unk_menu1;

struct{
    u8      id[16];
} dtmf_start;

struct{
    u8      id[16];
} dtmf_end;

struct{
    u8      unk_menu2[16];
    u8      unk_menu3[16];
} unk_menu23;

struct{
    u8      id[16];
} remote_stun;

struct{
    u8      id[16];
} remote_kill;

struct{
    u8      unk_menu4[16];
    u8      emerg_menu[16];
} unk_menu4;

struct{
    u8      scanmode;
    u8      prio_chan;
    u8      revert_chan;
    u8      lookback_a;
    u8      lookback_b;
    u8      dropout_delay;
    u8      dwell;
    u8      unk_sm;
    u8      unused[8];
} scan_menu;

struct{
    char    message[16];
}startup_display;

struct{
    u8     notimpl[3107];
} notimpl;

struct{
    u8      unk_imm[16];
    char    serial_number[16];
} immut_1;

struct{
    char    prod_date[10];
    u8      unk_imm2[22];
} immut_2;
"""


# RADIO MODES
BAND_LABELS = [
    "UHF ( 400 - 490 MHz ) + VHF( 136 - 174 MHz )",
    "UHF ( 400 - 490 MHz ) + VHF( 144 - 146 MHz )",
    "UHF ( 430 - 440 MHz ) + VHF( 136 - 174 MHz )",
    "UHF ( 430 - 440 MHz ) + VHF( 144 - 146 MHz )",
    "UHF ( 430 - 440 MHz ) + VHF( 144 - 148 MHz )",
    "UHF ( 400 - 438 MHz ) + VHF( 136 - 174 MHz )",
    "UHF ( 420 - 450 MHz ) + VHF( 144 - 148 MHz )",
    "UHF ( 400 - 470 MHz ) + VHF( 136 - 174 MHz )",
    "European Version PMR",
    "US GMRS",
    "Australian UHF CB"
]
BAND_LIMITS = [
    [(136000000, 174000001), (400000000, 490000001)],
    [(144000000, 146000001), (400000000, 490000001)],
    [(136000000, 174000001), (430000000, 440000001)],
    [(144000000, 146000001), (430000000, 440000001)],
    [(144000000, 148000001), (430000000, 440000001)],
    [(136000000, 174000001), (400000000, 438000001)],
    [(144000000, 148000001), (420000000, 450000001)],
    [(136000000, 174000001), (400000000, 470000001)],
    [(446000000, 446200001)],
    [(462550000, 467725001)],
    [(476425000, 477412501)]
]

MEMORY_REGIONS = [
    (0x0002000, 1, 32, 'RO', 'vfo1', 'VFO1'),
    (0x0012000, 1, 32, 'RO', 'vfo2', 'VFO2'),
    (0x0022000, 2, 32, 'W', 'chans_present', 'Present Chan.'),
    (0x0032000, 2, 32, 'W', 'chans_scanned', 'Scanned Chan.'),
    (0x0042000, 200, 32, 'W', 'memory', 'Memory Chan. 1-200'),
    (0x0052000, 200, 32, 'W', 'memory', 'Memory Chan. 201-400'),
    (0x0062000, 104, 32, 'W', 'memory', 'Memory Chan. 401-500'),
    (0x1002000, 1, 32, 'W', 'func_settings', 'Function Menu'),
    (0x2001000, 16, 16, 'W', 'dtmf_list', 'DTMF Encode List'),
    (0x2011000, 1, 16, 'W', 'dtmf_menu', 'DTMF Menu'),
    (0x2021000, 1, 16, 'RO', 'unk_menu1', 'Unk Menu1'),
    (0x2031000, 1, 16, 'W', 'dtmf_start', 'DTMF PTT ID Start'),
    (0x2041000, 1, 16, 'W', 'dtmf_end', 'DTMF PTT ID End'),
    (0x2051000, 1, 16, 'RO', 'unk_menu2', 'Unk Menu2'),
    (0x2061000, 1, 16, 'RO', 'unk_menu3', 'Unk Menu3'),
    (0x2071000, 1, 16, 'W', 'remote_stun', 'DTMF Remote Stun'),
    (0x2081000, 1, 16, 'W', 'remote_kill', 'DTMF Remote Kill'),
    (0x2091000, 1, 16, 'RO', 'unk_menu4', 'Unk Menu4'),
    (0x3001000, 1, 16, 'RO', 'emerg_menu', 'Emerg Menu'),
    (0x3011000, 1, 16, 'W', 'scan_menu', 'Scan Menu'),
    (0x3021000, 1, 16, 'W', 'startup_display', 'Startup Display'),
    (0x3031000, 1, 16, 'RO', 'unknr1', 'Unknown NR'),
    (0x3041000, 1, 16, 'RO', 'unknr2', 'Unknown NR'),
    (0x3051000, 1, 16, 'RO', 'unknr3', 'Unknown NR'),
    (0x3061000, 1, 16, 'RO', 'unknr4', 'Unknown NR'),
    (0x3071000, 1, 16, 'RO', 'unknr5', 'Unknown NR'),
    (0x3081000, 1, 16, 'RO', 'unknr6', 'Unknown NR'),
    (0x3091000, 1, 16, 'RO', 'unknr7', 'Unknown NR'),
    (0x4000500, 127, 5, 'RO', 'commnote', 'Comm. ID'),
    (0x4010800, 127, 8, 'RO', 'commnote', 'Comm. Name'),
    (0x5001000, 32, 16, 'RO', '2tone', '2 Tone Data'),
    (0x5012000, 1, 32, 'RO', '2tonecfg', '2 Tone Config'),
    (0x5021000, 1, 16, 'RO', '2tonecfg2', '2 Tone Config'),
    (0x6002000, 16, 32, 'RO', '5tone', '5 Tone Data'),
    (0x6012000, 1, 32, 'RO', '5tonecfg', '5 Tone Config'),
    (0x6021000, 1, 16, 'RO', '5tonecfg2', '5 Tone Config'),
    (0x6032000, 7, 32, 'RO', 'unk_read', 'Unknown Read'),
    (0x8002000, 1, 32, 'RO', 'immut_1', 'Serial Number'),
    (0x8002001, 1, 32, 'RO', 'immut_2', 'Production Date')
]


def send_cmd(serial, cmd, length):
    try:
        resp = b''
        serial.write(cmd)
        serial.flush()
        resp = serial.read(length)
        if len(resp) != length:
            err = (f'Data send expected {length} got {len(resp)}')
            LOG.error(err)
            raise errors.RadioError(err)
    except Exception as e:
        raise errors.RadioError(f'Error sending to serial {e}')
    return resp


def start_programming(serial):
    try:
        r = send_cmd(serial, b'PROGRAM', 1)
        if r != b'\x06':
            err = (f'Enter Programming failed '
                   f'expected 0x06 got {hex(r[0])}')
            LOG.error(err)
            raise errors.RadioError(err)
    except Exception as e:
        raise errors.RadioError(f'Error Entering Program Mode {e}')
    return True


def end_programming(serial):
    try:
        r = send_cmd(serial, b'END', 1)
        if r != b'\x06':
            LOG.error(f'Error {hex(r[0])}')
    except Exception as e:
        raise errors.RadioError(f"Error {e}")


def parse_response(r):
    ck = sum(r[:-1]) % 256
    if ck != r[-1]:
        err = f'Data check sum failed calc {ck} got {r[-1]}'
        LOG.error(err)
    return r[5:-1]


def get_ident(radio):
    try:

        bs = send_cmd(radio.pipe, b'\x02', 16)
        model, mode, ver = struct.unpack('>x7sB4s3x', bs)
        print(radio.ALLOWED_RADIO_TYPES)
        if ver in radio.ALLOWED_RADIO_TYPES[model]:
            LOG.info(f'Model {model} Ver: {ver} is supported')
            return bs
        else:
            raise KeyError
    except KeyError:
        err = f'ERROR: Model: {model} Ver: {ver} is not supported!'
        LOG.error(err)
        raise errors.RadioError(err)

    except Exception as e:
        raise errors.RadioError(e)


def get_bands(mode):
    # Radio skips 0xA-0XF, 0x10 == 10 :/
    try:
        if mode < 0xA:
            idx = mode
        elif 0XF < mode < 0x12:
            idx = mode - 6
        valid_ranges = BAND_LIMITS[idx - 1]
    except IndexError:
        raise errors.RadioError("Unknown Radio Mode - Can't set Freq. Bands!")
    return valid_ranges


def do_download(radio):
    try:
        data = b''
        serial = radio.pipe
        serial.timeout = SERIAL_TIMEOUT
        status = chirp_common.Status()
        status.msg = "Connecting to Radio..."
        radio.status_fn(status)
        r = start_programming(serial)
        if not r:
            raise errors.RadioError('Failed to enter programming mode')
        ident_bytes = get_ident(radio)
        data = ident_bytes
        status.max = sum((t[1] * t[2]) for t in MEMORY_REGIONS)
        for reg in MEMORY_REGIONS:
            base, blocks, blk_sz, mod, struc, label = reg
            if mod != 'S':
                status.msg = f'Downloading: {label}...'
                addrs = [(base + i) for i in range(0, blocks)]
                for addr in addrs:
                    cmd = struct.pack('>BL', 0x52, addr)
                    r = send_cmd(serial, cmd, blk_sz + 6)
                    if r[0] != 0x57:
                        err = (f'Received bad ACK from Radio '
                               f'expect 0x57 got {hex(r[0])}')
                        LOG.error(err)
                        raise errors.RadioError(err)
                    data += parse_response(r)
                    status.cur += len(r[5:-1])
                    radio.status_fn(status)
    except Exception as e:
        raise errors.RadioError(f'Exception During Download: {e}')
    finally:
        end_programming(serial)
    return memmap.MemoryMapBytes(data)


def write_data(serial, addr, data):
    pfx = struct.pack('>BL', 0x57, addr)
    data = pfx + data
    chk_int = sum(data) % 256
    chk_byte = struct.pack('>B', chk_int)
    cmd = data + chk_byte
    r = send_cmd(serial, cmd, 1)
    if r != b'\x06':
        err = (f'Received bad ACK from Radio '
               f'expect 0x06 got {hex(r[0])}')
        LOG.error(err)
        raise errors.RadioError(err)


def do_upload(radio):
    try:
        serial = radio.pipe
        serial.timeout = SERIAL_TIMEOUT
        status = chirp_common.Status()
        r = start_programming(serial)
        if not r:
            raise errors.RadioError('Failed to enter programming mode')
        ident_bytes = get_ident(radio)
        mode = ident_bytes[8]
        if mode != radio._memobj.radio_info.mode:
            raise errors.RadioError('The Radio Mode does not match'
                                    ' [Settings]->[Radio Info]->Radio Mode')
        mrs = [t for t in MEMORY_REGIONS if t[3] != 'RO']
        status.max = sum((t[1]*t[2]) for t in mrs)
        for mr in mrs:
            base, blocks, blk_sz, mod, struc, label = mr
            status.msg = f"Uploading: {label}..."
            struc_data = radio._memobj[struc].get_raw()
            if struc == "memory":
                if base == 0x42000:
                    struc_data = struc_data[:200 * blk_sz]
                elif base == 0x52000:
                    struc_data = struc_data[200 * blk_sz: 400 * blk_sz]
                elif base == 0x62000:
                    struc_data = struc_data[400 * blk_sz: 504 * blk_sz]
            addrs = [base + n for n in range(0, blocks)]
            for j in range(blocks):
                si = j * blk_sz
                ei = (j+1) * blk_sz
                data = struc_data[si:ei]
                write_data(serial, addrs[j], data)
                status.cur += len(data)
                radio.status_fn(status)

    except Exception as e:
        raise errors.RadioError(f"Exception During Upload: {e}")
    finally:
        end_programming(serial)
    return


@directory.register
class RA25UVRadio(chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio):
    """Retevis RA-25 , Anytone AT-779UV, Radioddity DB20 are purported the same
        but this driver was developed/suports only the Retevis RA-25."""
    VENDOR = "Retevis"
    MODEL = "RA25"
    BAUD_RATE = 115200
    ALLOWED_RADIO_TYPES = {b'RA_25UV': [b'V200']}
    _file_ident = [b'RA_25UV']
    _image_size = 0x4EC3
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                    chirp_common.PowerLevel("Mid", watts=10.00),
                    chirp_common.PowerLevel("High", watts=25.00)]
    VALID_TONES = (62.5,) + chirp_common.TONES
    VALID_DCS = [i for i in range(
        0, 778) if '9' not in str(i) and '8' not in str(i)]
    VALID_TUNING_STEPS = [2.5, 5.0, 6.25, 10, 12.5, 20, 25, 30, 50]
    VALID_CHARSET = "".join(chr(i)
                            for i in range(32, 127) if chr(i) not in '\\`~')
    VALID_DTMF = [str(i) for i in range(0, 10)] + ['A', 'B',
                                                   'C', 'D', '*', '#']

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This Retevis RA-25 driver is experimental, '
             'please report bugs')
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        # chirp_common.TONE_MODES
        rf.valid_tmodes = ("", "Tone", "TSQL", "DTCS", "Cross")
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->Tone",
            "->DTCS",
            "DTCS->DTCS"
        ]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = self.POWER_LEVELS
        try:
            rf.valid_bands = get_bands(self._memobj.radio_info.mode)
        except AttributeError:
            # Widest setting for support matrix
            rf.valid_bands = get_bands(1)
        rf.valid_characters = self.VALID_CHARSET
        rf.valid_name_length = 8
        rf.valid_duplexes = ["", "+", "-"]
        rf.valid_tuning_steps = self.VALID_TUNING_STEPS
        rf.valid_tones = self.VALID_TONES
        rf.has_dtcs = True
        rf.has_dtcs_polarity = True
        rf.valid_dtcs_codes = self.VALID_DCS
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = True
        rf.has_bank = False
        rf.has_settings = True
        rf.memory_bounds = (1, 500)
        rf.can_odd_split = False
        rf.has_offset = True
        return rf

    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        do_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    # Populate the UI mem from _mem

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _mem_chans_scanned = self._memobj.chans_scanned
        _mem_chans_present = self._memobj.chans_present
        mem = chirp_common.Memory()

        mem.number = number              # Set the UI memory number
        mem.power = self.POWER_LEVELS[0]  # Set a default power level

        mem.empty = not self.get_chan_status(
            _mem_chans_present, mem.number - 1)

        if mem.empty:
            return mem

        valid_bands = get_bands(self._memobj.radio_info.mode)
        self.valid_bands = valid_bands

        mem.freq = int(_mem.freq) * 10
        _name = "".join(c for c in str(_mem.name)
                        if c in self.VALID_CHARSET)
        mem.name = _name.rstrip()
        mem.power = self.POWER_LEVELS[_mem.txpower]
        mem.mode = "FM" if _mem.channel_width == 0 else "NFM"
        self.get_tones(_mem, mem)
        self.get_duplex(_mem, mem)
        mem.offset = int(_mem.tx_offset) * 10

        mem.skip = '' if self.get_chan_status(
            _mem_chans_scanned, mem.number - 1) else 'S'

        mem.tuning_step = self.VALID_TUNING_STEPS[_mem.step]
        # Extra
        mem.extra = RadioSettingGroup("Extra", "extra")

        rstype = RadioSettingValueBoolean(_mem.tx_off)
        rs = RadioSetting("tx_off", "TX Disable", rstype)
        mem.extra.append(rs)

        # Busy channel lockout
        bcl_options = ['Off', 'Repeater', 'Busy']

        _current = _mem.busychannellockout.get_value()
        rstype = RadioSettingValueList(bcl_options, current_index=_current)
        rs = RadioSetting("busychannellockout",
                          "Busy Channel Lockout", rstype)
        mem.extra.append(rs)

        rstype = RadioSettingValueBoolean(_mem.talkaround)
        rs = RadioSetting("talkaround", "Talk Around", rstype)
        mem.extra.append(rs)

        rstype = RadioSettingValueBoolean(_mem.reverse)
        rs = RadioSetting("reverse", "Reverse", rstype)
        mem.extra.append(rs)

        rstype = RadioSettingValueBoolean(_mem.compander)
        rs = RadioSetting("compander", "Compander", rstype)
        mem.extra.append(rs)

        rstype = RadioSettingValueBoolean(_mem.nc)
        rs = RadioSetting("nc", "Noise Cancelation", rstype)
        mem.extra.append(rs)

        tid_options = ['Off', 'Begin', 'End', "Both"]
        _current = _mem.tone_id.get_value()
        rstype = RadioSettingValueList(tid_options, current_index=_current)
        rs = RadioSetting("tone_id", "DTMF PTT ID", rstype)
        mem.extra.append(rs)

        return mem

    # Called when a user edits UI mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _mem_chans_scanned = self._memobj.chans_scanned
        _mem_chans_present = self._memobj.chans_present

        if mem.empty:
            self.set_chan_status(_mem_chans_present, mem.number - 1, 0)
            self.set_chan_status(_mem_chans_scanned, mem.number - 1, 0)
            _mem.fill_raw(b'\x00')  # clear memory
            return
        else:
            # Determine if this is a new memory
            if not self.get_chan_status(_mem_chans_present, mem.number - 1):
                _mem.fill_raw(b'\x00')
                self.set_chan_status(_mem_chans_present, mem.number - 1, 1)

        _mem.freq = mem.freq // 10
        _mem.name = mem.name.ljust(8)[:8]
        _mem.txpower = self.POWER_LEVELS.index(mem.power) if mem.power else 0
        _mem.channel_width = 0 if mem.mode == "FM" else 1
        self.set_tones__mem(_mem, mem)
        self.set_duplex__mem(_mem, mem)
        _mem.tx_offset = mem.offset/10
        _mem.step = self.VALID_TUNING_STEPS.index(mem.tuning_step)

        # scan when set(1) skip when off(0)
        _value = 0 if mem.skip == 'S' else 1
        self.set_chan_status(_mem_chans_scanned, mem.number - 1, _value)

        # extra settings
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_chan_status(self, _mem_field, chan_n):
        if chan_n < 256:
            value = _mem_field[0]['bitfield'][chan_n].get_value()
        else:
            value = _mem_field[1]['bitfield'][chan_n - 256].get_value()
        return value

    def set_chan_status(self, _mem_field, chan_n, value):
        if chan_n < 256:
            _mem_field[0]['bitfield'][chan_n].set_value(value)
        else:
            _mem_field[1]['bitfield'][chan_n - 256].set_value(value)

    def get_duplex(self, _mem, mem):
        # get duplex from _mem for ui
        if _mem.duplex == 0x0:
            mem.duplex = ''
        elif _mem.duplex == 0x2:
            mem.duplex = '-'
        elif _mem.duplex == 0x3:
            mem.duplex = '+'

    def set_duplex__mem(self, _mem, mem):
        # sets duplex _mem from ui edit
        if mem.duplex == '':
            _mem.duplex = 0x0
            _mem.tx_offset = 0
        elif mem.duplex == '-':
            _mem.duplex = 0x2
        elif mem.duplex == '+':
            _mem.duplex = 0x3

    def get_tones(self, _mem, mem):
        # populate ui from _mem
        # parse decode/rtone/rx_dtcs
        if _mem.decode == 0xffff:
            # off
            rxtone = ("", 0, None)
        elif _mem.decode >= 0x1000 and _mem.decode < 0x2000:
            # ctcss tone
            rxtone = ("Tone", self.VALID_TONES[_mem.decode - 0x1000], None)
        elif _mem.decode >= 0x2000 and _mem.decode < 0x3000:
            # DCS Normal
            rxtone = ("DTCS", self.VALID_DCS[_mem.decode - 0x2000], "N")
        elif _mem.decode >= 0x3000 and _mem.decode <= 0x31ff:
            # DCS Inverted
            rxtone = ("DTCS", self.VALID_DCS[_mem.decode - 0x3000], "R")
        else:
            rxtone = ("", 0, None)
        # parse encode/dtcs/ctone
        if _mem.encode == 0xffff:
            # off
            txtone = ("", 0, None)
        elif _mem.encode >= 0x1000 and _mem.encode < 0x2000:
            # ctcss tone
            txtone = ("Tone", self.VALID_TONES[_mem.encode - 0x1000], None)
        elif _mem.encode >= 0x2000 and _mem.encode < 0x3000:
            # DCS Normal
            txtone = ("DTCS", self.VALID_DCS[_mem.encode - 0x2000], "N")
        elif _mem.encode >= 0x3000 and _mem.encode <= 0x31ff:
            # DCS Inverted
            txtone = ("DTCS", self.VALID_DCS[_mem.encode - 0x3000], "R")
        else:
            txtone = ("", 0, None)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

    def set_tones__mem(self, _mem, mem):
        # sets tones in _mem from ui edit
        ((txmode, txval, txpol),
         (rxmode, rxval, rxpol)) = chirp_common.split_tone_encode(mem)
        if txmode == "":
            _mem.encode = 0xffff
        if rxmode == "":
            _mem.decode = 0xffff
        if txmode == "Tone":
            _mem.encode = self.VALID_TONES.index(txval) + 0x1000
        if rxmode == "Tone":
            _mem.decode = self.VALID_TONES.index(rxval) + 0x1000
        if txmode == "DTCS" and txpol == "N":
            _mem.encode = self.VALID_DCS.index(txval) + 0x2000
        if rxmode == "DTCS" and rxpol == "N":
            _mem.decode = self.VALID_DCS.index(rxval) + 0x2000
        if txmode == "DTCS" and txpol == "R":
            _mem.encode = self.VALID_DCS.index(txval) + 0x3000
        if rxmode == "DTCS" and rxpol == "R":
            _mem.decode = self.VALID_DCS.index(rxval) + 0x3000

    def get_settings(self):

        _func_settings = self._memobj.func_settings
        _dtmf_menu = self._memobj.dtmf_menu
        _dtmf_list = self._memobj.dtmf_list
        _dtmf_start = self._memobj.dtmf_start
        _dtmf_end = self._memobj.dtmf_end
        _remote_kill = self._memobj.remote_kill
        _remote_stun = self._memobj.remote_stun
        _scan_menu = self._memobj.scan_menu
        _startup_display = self._memobj.startup_display
        _immut_1 = self._memobj.immut_1
        _immut_2 = self._memobj.immut_2
        _radio_info = self._memobj.radio_info

        function = RadioSettingGroup("function", "Function Setup")
        group = RadioSettings(function)

        rs = RadioSettingValueInteger(minval=0, maxval=9,
                                      current=_func_settings.squelch, step=1)
        rset = RadioSetting("func_settings.squelch", "Squelch Level", rs)
        function.append(rset)

        rs = RadioSettingValueInteger(minval=0, maxval=9,
                                      current=_func_settings.vox_level, step=1)
        rset = RadioSetting("func_settings.vox_level", "Vox Level", rs)
        function.append(rset)

        voxdelay_options = [str(i/10) for i in range(5, 31, 1)]
        rs = RadioSettingValueList(
            voxdelay_options, current_index=_func_settings.vox_delay)
        rset = RadioSetting("func_settings.vox_delay", "Vox Delay", rs)
        function.append(rset)

        scan_pause_options = ["5", "10",  "15",  "SCP2"]
        rs = RadioSettingValueList(
            scan_pause_options, current_index=_func_settings.scan_pause)
        rset = RadioSetting("func_settings.scan_pause", "Scan Pause (s)", rs)
        function.append(rset)

        main_options = ["Up", "Down"]
        rs = RadioSettingValueList(
            main_options, current_index=_func_settings.main)
        rset = RadioSetting("func_settings.main", "Main Direction", rs)
        function.append(rset)

        monikey_options = ["Squelch Off Momentary", "Squelch Off"]
        rs = RadioSettingValueList(
            monikey_options, current_index=_func_settings.moni_key)
        rset = RadioSetting("func_settings.moni_key", "[MON] Key", rs)
        function.append(rset)

        rs = RadioSettingValueInteger(minval=0, maxval=30,
                                      current=_func_settings.tot, step=1)
        rset = RadioSetting("func_settings.tot",
                            "Time Out Timer (minutes)", rs)
        function.append(rset)

        tbst_options = ["Off", "1750", "2100", "1000", "1450"]
        rs = RadioSettingValueList(
            tbst_options, current_index=_func_settings.tbst_freq)
        rset = RadioSetting("func_settings.tbst_freq",
                            "TBST Frequency (Hz)", rs)
        function.append(rset)

        tailelim_options = ["Off", "120 deg", "180 deg", "240 deg", "55hz"]
        rs = RadioSettingValueList(
            tailelim_options, current_index=_func_settings.tail_elim_type)
        rset = RadioSetting("func_settings.tail_elim_type",
                            "Tail Eliminator Type", rs)
        function.append(rset)

        dcstail_options = ["134.4", "55.0"]
        rs = RadioSettingValueList(
            dcstail_options, current_index=_func_settings.dcs_tail_elim)
        rset = RadioSetting("func_settings.dcs_tail_elim",
                            "DCS Tail Elimination", rs)
        function.append(rset)

        sqltail_options = ["Off", "55.2", "259.2"]
        rs = RadioSettingValueList(
            sqltail_options, current_index=_func_settings.sql_tail_elim)
        rset = RadioSetting("func_settings.sql_tail_elim",
                            "Squelch Tail Elimination (Hz)", rs)
        function.append(rset)

        disp_options = ["Frequency", "Channel", "Name"]
        rs = RadioSettingValueList(
            disp_options, current_index=_func_settings.dispmode)
        rset = RadioSetting("func_settings.dispmode", "Display Mode", rs)
        function.append(rset)

        vicedisp_options = ["Freq/Chan", "Battery Volt", "Off"]
        rs = RadioSettingValueList(
            vicedisp_options, current_index=_func_settings.vicedisp)
        rset = RadioSetting("func_settings.vicedisp", "Sub-Display", rs)
        function.append(rset)

        _current = "".join(c for c in str(
            _startup_display.message) if c in self.VALID_CHARSET)
        rs = RadioSettingValueString(minlength=0, maxlength=16,
                                     current=_current,
                                     charset=self.VALID_CHARSET,
                                     mem_pad_char=' ')
        rset = RadioSetting("startup_display.message",
                            "Startup Display Message", rs)
        function.append(rset)

        rs = RadioSettingValueInteger(
            minval=1, maxval=5, current=_func_settings.backlight, step=1)
        rset = RadioSetting("func_settings.backlight", "Backlight Level", rs)
        function.append(rset)

        rs = RadioSettingValueBoolean(
            current=_func_settings.beep, mem_vals=(0, 1))
        rset = RadioSetting("func_settings.beep", "Beep", rs)
        function.append(rset)

        rs = RadioSettingValueBoolean(
            current=_func_settings.alarm_off, mem_vals=(0, 1))
        rset = RadioSetting("func_settings.alarm_off", "Alarm Off", rs)
        function.append(rset)

        rs = RadioSettingValueBoolean(
            current=_func_settings.setup_inhib, mem_vals=(0, 1))
        rset = RadioSetting("func_settings.setup_inhib", "Setup Inhibit", rs)
        function.append(rset)

        rs = RadioSettingValueBoolean(
            current=_func_settings.init_inhib, mem_vals=(0, 1))
        rset = RadioSetting("func_settings.init_inhib",
                            "Initialization Inhibit", rs)
        function.append(rset)

        lang_options = ["Simplified Chinese", "English", "Traditional Chinese"]
        rs = RadioSettingValueList(
            lang_options, current_index=_func_settings.language)
        rset = RadioSetting("func_settings.language", "Language", rs)
        function.append(rset)

        # Scan Menu
        scan = RadioSettingGroup("scan", "Scan Menu")
        group.append(scan)

        rs = RadioSettingValueBoolean(current=_scan_menu.scanmode)
        rset = RadioSetting("scan_menu.scanmode", "Scan Mode", rs)
        scan.append(rset)

        _options = ["Off", "Chan 1", "Chan 2", "Chan 1 + Chan 2"]
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.prio_chan)
        rset = RadioSetting("scan_menu.prio_chan", "Priority Channel", rs)
        scan.append(rset)

        _options = ["Selected", "Selected + Talkback",
                    "Prio Ch 1", "Prio Ch 2", "Last Called",
                    "Last Used", "Prio Ch1 + Talkback", "Prio Ch2 + Talkback"]
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.revert_chan)
        rset = RadioSetting("scan_menu.revert_chan", "Revert Channel", rs)
        scan.append(rset)

        _options = [str(i/10) for i in range(5, 51, 1)]
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.lookback_a)
        rset = RadioSetting("scan_menu.lookback_a", "Look Back Time A (s)", rs)
        scan.append(rset)

        # Uses previous options
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.lookback_b)
        rset = RadioSetting("scan_menu.lookback_b", "Look Back Time B (s)", rs)
        scan.append(rset)

        _options = [str(i/10) for i in range(1, 51, 1)]
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.dropout_delay)
        rset = RadioSetting("scan_menu.dropout_delay", "Dropout Delay (s)", rs)
        scan.append(rset)

        # Uses previous options
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.dwell)
        rset = RadioSetting("scan_menu.dwell", "Dwell Time (s)", rs)
        scan.append(rset)

        # DTMF Menu
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        group.append(dtmf)

        def dtmf_xlate(setting):
            """ Translates * and # to ascii code E / F respectively"""
            s = ""
            for i in setting:
                if chr(i) == 'E':
                    s += '*'
                elif chr(i) == 'F':
                    s += '#'
                elif chr(i) in self.VALID_DTMF:
                    s += chr(i)
            return s

        _current = ''.join(str(int(i)) for i in _dtmf_menu.self_id)
        rs = RadioSettingValueString(
            minlength=0, maxlength=3, current=_current)
        rset = RadioSetting("dtmf_menu.self_id", "Self ID", rs)
        dtmf.append(rset)

        # DTMF Transmit time is in function memory but belongs here
        dtmftt_options = ["50", "100", "200", "300", "500"]
        rs = RadioSettingValueList(
            dtmftt_options, current_index=_func_settings.dtmf_trans)
        rset = RadioSetting("func_settings.dtmf_trans",
                            "DTMF Transmit Time (ms)", rs)
        dtmf.append(rset)

        _options_map = [('A', 10), ('B', 11), ('C', 12),
                        ('D', 13), ('*', 14), ('#', 15)]
        rs = RadioSettingValueMap(_options_map, _dtmf_menu.interval_char)
        rset = RadioSetting("dtmf_menu.interval_char", "Interval Char", rs)
        dtmf.append(rset)

        _options_map = [('Off', 0), ('A', 10), ('B', 11),
                        ('C', 12), ('D', 13), ('*', 14), ('#', 15)]
        rs = RadioSettingValueMap(_options_map, _dtmf_menu.group_code)
        rset = RadioSetting("dtmf_menu.group_code", "Group Code", rs)
        dtmf.append(rset)

        _options = ["None", "Beep Tone", "Beep Tone & Response"]
        rs = RadioSettingValueList(
            _options, current_index=_dtmf_menu.decoding)
        rset = RadioSetting("dtmf_menu.decoding", "Decoding", rs)
        dtmf.append(rset)

        _options = [str(i) for i in range(10, 2510, 10)]
        _mem_vals = [i for i in range(1, 251)]
        _options_map = list(zip(_options, _mem_vals))
        rs = RadioSettingValueMap(_options_map, _dtmf_menu.pretime)
        rset = RadioSetting("dtmf_menu.pretime", "Pretime (ms)", rs)
        dtmf.append(rset)

        # using same _options as pre-time
        rs = RadioSettingValueMap(_options_map, _dtmf_menu.timelapse_enc)
        rset = RadioSetting("dtmf_menu.timelapse_enc",
                            "Time Lapse After Encode (ms)", rs)
        dtmf.append(rset)

        _options = [str(i) for i in range(0, 2510, 10)]
        rs = RadioSettingValueList(
            _options, current_index=_dtmf_menu.first_dig_tm)
        rset = RadioSetting("dtmf_menu.first_dig_tm",
                            "First Digit Time (ms)", rs)
        dtmf.append(rset)

        _options = [str(i/10) for i in range(0, 251, 1)]
        rs = RadioSettingValueList(
            _options, current_index=_dtmf_menu.autoreset_tm)
        rset = RadioSetting("dtmf_menu.autoreset_tm",
                            "Auto Reset Time (ms)", rs)
        dtmf.append(rset)

        rs = RadioSettingValueBoolean(
            current=_dtmf_menu.side_tone, mem_vals=(0, 1))
        rset = RadioSetting("dtmf_menu.side_tone", "Side Tone", rs)
        dtmf.append(rset)

        _options_map = [("Off", 0)] + [(str(i), i) for i in range(5, 76, 1)]
        rs = RadioSettingValueMap(_options_map, _dtmf_menu.pttid_pause)
        rset = RadioSetting("dtmf_menu.pttid_pause",
                            "PTT ID Pause Time (s)", rs)
        dtmf.append(rset)

        rs = RadioSettingValueString(minlength=0, maxlength=16,
                                     current=dtmf_xlate(_dtmf_start.id),
                                     charset=self.VALID_DTMF + [' '])
        rset = RadioSetting("dtmf_start.id", "PTT ID Starting", rs)
        dtmf.append(rset)

        rs = RadioSettingValueString(minlength=0, maxlength=16,
                                     current=dtmf_xlate(_dtmf_end.id),
                                     charset=self.VALID_DTMF + [' '])
        rset = RadioSetting("dtmf_end.id", "PTT ID Ending", rs)
        dtmf.append(rset)

        rs = RadioSettingValueString(minlength=0, maxlength=16,
                                     current=dtmf_xlate(_remote_kill.id),
                                     charset=self.VALID_DTMF + [' '],)
        rset = RadioSetting("remote_kill.id", "Remote Kill", rs)
        dtmf.append(rset)

        rs = RadioSettingValueString(minlength=0, maxlength=16,
                                     current=dtmf_xlate(_remote_stun.id),
                                     charset=self.VALID_DTMF + [' '])
        rset = RadioSetting("remote_stun.id", "Remote Stun", rs)
        dtmf.append(rset)

        # DTMF Encode List
        dtmf_mem = RadioSettingGroup("dtmf_mem", "DTMF Encode List")
        group.append(dtmf_mem)

        for i in range(0, 16):  # M1-16
            rs = RadioSettingValueString(minlength=0, maxlength=16,
                                         current=dtmf_xlate(_dtmf_list[i].m),
                                         charset=self.VALID_DTMF + [' '])
            rset = RadioSetting(f"dtmf_list[{i}].m", f"M{i+1}", rs)
            dtmf_mem.append(rset)

        # Immutables Info
        info_menu = RadioSettingGroup("immut_info", "Radio Info")
        group.append(info_menu)

        _warning = ('To Upload to the Radio this setting must match '
                    'the Radio Mode. The Radio Mode can be changed by '
                    'holding down [V/M] during powerup. Note: Changing '
                    'the Radio Mode will set Radio memory to defaults.')

        mem_vals = [0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8, 0x9, 0x10, 0x11]
        _options_map = list(zip(BAND_LABELS, mem_vals))
        rs = RadioSettingValueMap(_options_map, _radio_info.mode)
        rset = RadioSetting("radio_info.mode", "Radio Mode", rs)
        rset.set_warning(_warning)
        info_menu.append(rset)

        _current = "".join(str(_radio_info.model[i])
                           for i in range(1, len(_radio_info.model)))
        rs = RadioSettingValueString(
            minlength=1, maxlength=8, current=_current)
        rs.set_mutable(False)
        rset = RadioSetting("radio_info.model", "Model", rs)
        info_menu.append(rset)

        _current = "".join(str(_radio_info.ver[i])
                           for i in range(len(_radio_info.ver)))
        rs = RadioSettingValueString(
            minlength=4, maxlength=4, current=_current)
        rs.set_mutable(False)
        rset = RadioSetting("radio_info.ver", "Version", rs)
        info_menu.append(rset)

        _current = "".join(str(_immut_1.serial_number[i]) for i in range(
            len(_immut_1.serial_number)))
        rs = RadioSettingValueString(
            minlength=0, maxlength=16, current=_current)
        rs.set_mutable(False)
        rset = RadioSetting("immut_1.serial_number", "Serial Number", rs)
        info_menu.append(rset)

        _current = "".join(str(_immut_2.prod_date[i]) for i in range(
            len(_immut_2.prod_date)) if int(_immut_2.prod_date[i]) >= 0x20)
        rs = RadioSettingValueString(
            minlength=0, maxlength=10, current=_current)
        rs.set_mutable(False)
        rset = RadioSetting("immut_2.prod_date", "Production Date", rs)
        info_menu.append(rset)
        return group

    def dtmf_set__mem(self, obj, setting, element):
        _val = [0] * len(obj[setting])
        _i = 0  # offset _mem setting idx for pad chars
        for i in range(len(element.value)):
            if element.value[i] == '*':
                _val[i - _i] = ord('E')
            elif element.value[i] == '#':
                _val[i - _i] = ord('F')
            elif element.value[i] in self.VALID_DTMF:
                _val[i - _i] = ord(element.value[i])
            else:
                _i += 1
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
                        if obj._name in ['dtmf_list', 'dtmf_start', 'dtmf_end',
                                         'remote_stun', 'remote_kill']:
                            self.dtmf_set__mem(obj, setting, element)
                        else:
                            setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        for _ident in cls._file_ident:
            if _ident in filedata[0x01:0x07]:
                if len(filedata) == cls._image_size:
                    return True
        return False


@directory.register
class AnyTone779UV(RA25UVRadio):
    VENDOR = "AnyTone"
    MODEL = "779UV"
    ALLOWED_RADIO_TYPES = {b'AT779UV': [b'V200']}
