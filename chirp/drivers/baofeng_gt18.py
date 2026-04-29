# Copyright 2024 Campbell Reed
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

"""Driver for the Baofeng GT-18 FRS radio.

The GT-18 belongs to the PROGRAL handshake family (radtel_t18.py).  It
subclasses RB18Radio and reuses _t18_read_block / _t18_write_block /
_t18_exit_programming_mode directly.  The only protocol addition over the
standard RB18 handshake is a password challenge/response that follows the
ident exchange (steps 7-9 below); write-mode entry also adds a b'E'->b'F'
exchange before re-handshaking.

Tone encoding: CTCSS is BCD-compatible with the T18 family.  DCS uses raw
binary for the code value rather than packed BCD (e.g. code 23 -> 0x17, not
0x23), so get_memory / set_memory are overridden to use the local helpers.
"""

import logging
import struct

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
)
from chirp.drivers.radtel_t18 import (
    RB18Radio,
    _t18_enter_programming_mode,
    _t18_exit_programming_mode,
    _t18_read_block,
    _t18_write_block,
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

# -- Protocol constants -------------------------------------------------------

CMD_ACK = b'\x06'
CMD_END = b'\x45'   # 'E' — matches RB18Radio.CMD_EXIT

REQ_PWD_CMD = bytes([0x52, 0x07, 0xB0, 0x10])  # R, addr=0x07B0, len=16
MASTER_PWD = 'BF666S'                           # bypass all password checks

WRITE_SIZE = 8   # bytes per write block (reads use inherited BLOCK_SIZE=16)

# -- Memory format ------------------------------------------------------------

MEM_FORMAT = """
struct {
  u8 rxfreq[4];    // BCD-hex LE (see _decode_freq / _encode_freq)
  u8 txfreq[4];
  u8 rx_tonelo;    // CTCSS/DCS low byte
  u8 rx_tonehi;    // high byte: bit[7]=DCS bit[6]=Inverted [2:0]=MSBs
  u8 tx_tonelo;
  u8 tx_tonehi;
  u8 flags;        // [4]=~scan_add [3]=pwr [2]=nfm [0]=~busy
  u8 unknown[3];
} memory[99];

struct {
  u8 voicesw;
  u8 voicesel;
  u8 scansw;
  u8 voxsw;
  u8 voxgain;      // 1-9
  u8 sidetone;
  u8 lowtxdis;
  u8 hightxdis;
} settings1;

#seekto 0x0640;
struct {
  u8 sysflags;     // bit[2]=txendtone bit[1]=save bit[0]=beep
  u8 squelch;      // 0-9
  u8 emergmode;
  u8 tot;          // index into TOT_LIST
  u8 tail;
} settings2;

#seekto 0x07B0;
struct {
  u8 password[6];  // ASCII, 0xFF-padded; all-0xFF = no password set
  u8 pad[2];
} pwdsettings;
"""

# -- FRS / NOAA frequency tables ----------------------------------------------

FRS_FREQS = [
    462562500, 462587500, 462612500, 462637500,
    462662500, 462687500, 462712500,
    467562500, 467587500, 467612500, 467637500,
    467662500, 467687500, 467712500,
    462550000, 462575000, 462600000, 462625000,
    462650000, 462675000, 462700000, 462725000,
]

NOAA_FREQS = [
    162550000, 162400000, 162475000, 162425000, 162450000,
    162500000, 162525000, 161650000, 161775000, 163275000,
]

# -- Settings value lists -----------------------------------------------------

TOT_LIST = ['Off', '30s', '60s', '90s', '120s',
            '150s', '180s', '210s', '240s', '270s']
VOICE_LIST = ['English', 'Chinese']
EMERG_LIST = ['Local Alarm (radio only)', 'Remote Alarm (transmit)']
VOX_LIST = [str(i) for i in range(1, 10)]


# -- Frequency encode / decode ------------------------------------------------

def _decode_freq(raw4):
    """4 LE bytes to CHIRP frequency in Hz.  Returns 0 for blank (0xFF...)."""
    if raw4[3] == 0xFF:
        return 0
    val = struct.unpack('<I', bytes(raw4))[0]
    dec = int(format(val, '08x'))
    return dec * 10


def _encode_freq(hz):
    """CHIRP Hz to 4 LE bytes.  hz=0 encodes as blank 0xFFFFFFFF."""
    if hz == 0:
        return b'\xff\xff\xff\xff'
    dec = hz // 10
    val = int(str(dec), 16)
    return struct.pack('<I', val)


# -- Sub-audio encode / decode ------------------------------------------------

def _tone_type(hi):
    if hi == 0xFF:
        return 'off'
    if hi & 0x80:
        return 'dcs'
    return 'ctcss'


def _decode_ctcss(lo, hi):
    if hi == 0x00:
        return None
    bcd = (hi << 8) | lo
    s = format(bcd, 'x')
    return float(s[:-1] + '.' + s[-1])


def _encode_ctcss(tone):
    s = '{:.1f}'.format(tone).replace('.', '')
    bcd = int(s, 16)
    return bcd & 0xFF, (bcd >> 8) & 0xFF


def _decode_dcs(lo, hi):
    if hi == 0xFF:
        return None
    inverted = (hi & 0xC0) == 0xC0
    code = ((hi & 0x07) << 8) | lo
    return code, ('R' if inverted else 'N')


def _encode_dcs(code, pol):
    lo = code & 0xFF
    hi = (code >> 8) & 0x07
    hi |= 0xC0 if pol == 'R' else 0x80
    return lo, hi


# -- Protocol helpers ---------------------------------------------------------

def _check_password(radio, raw6):
    opt = getattr(radio, '_opt_pwd', '').strip()
    if not opt or opt == MASTER_PWD:
        return
    expected = opt.encode('ascii').ljust(6, b'\xff')
    if bytes(raw6) != expected:
        raise errors.RadioError(
            'Radio password does not match the "Current Password" entered '
            'in Settings.  Enter the correct password and try again.')


def _gt18_password_exchange(radio):
    """GT-18 password challenge/response (steps 7-9 of handshake)."""
    serial = radio.pipe
    serial.write(REQ_PWD_CMD)
    pwd_resp = serial.read(20)
    if len(pwd_resp) < 20:
        raise errors.RadioError('Radio returned a short password response.')
    _check_password(radio, pwd_resp[4:10])
    serial.write(CMD_ACK)
    ack = serial.read(1)
    if ack != CMD_ACK:
        raise errors.RadioError('Radio did not ACK after password exchange.')


def _gt18_enter_programming_mode(radio, write=False):
    """GT-18 handshake: standard T18 ident exchange + password extension.

    For write sessions, appends the b'E'->b'F' write-mode entry and
    re-handshakes (second pass skips password exchange).
    """
    serial = radio.pipe
    serial.timeout = 2
    _t18_enter_programming_mode(radio)   # steps 1-6: magic + ident exchange
    _gt18_password_exchange(radio)        # steps 7-9: password challenge

    if write:
        serial.write(CMD_END)
        resp = serial.read(1)
        if resp != b'\x46':   # 'F'
            raise errors.RadioError('Radio refused write-mode entry.')
        # Re-handshake for write mode; radio does not expect password here
        _t18_enter_programming_mode(radio)


def _apply_new_password(radio):
    new_pwd = getattr(radio, '_new_pwd', '').strip()
    if not new_pwd:
        return
    pw = radio._memobj.pwdsettings
    for i in range(6):
        pw.password[i] = ord(new_pwd[i]) if i < len(new_pwd) else 0xFF
    pw.pad[0] = 0xFF
    pw.pad[1] = 0xFF


def do_download(radio):
    _gt18_enter_programming_mode(radio, write=False)
    data = bytearray(b'\xff' * radio._memsize)
    status = chirp_common.Status()
    status.msg = 'Cloning from radio'
    status.max = sum(end - start for start, end in radio._ranges)
    status.cur = 0
    try:
        for start, end in radio._ranges:
            for addr in range(start, end, radio.BLOCK_SIZE):
                block = _t18_read_block(radio, addr, radio.BLOCK_SIZE)
                data[addr:addr + radio.BLOCK_SIZE] = block
                status.cur += radio.BLOCK_SIZE
                radio.status_fn(status)
    except errors.RadioError:
        raise
    except Exception:
        LOG.exception('Unexpected error during download')
        raise errors.RadioError('Unexpected error communicating with radio')
    finally:
        _t18_exit_programming_mode(radio)
    return memmap.MemoryMapBytes(bytes(data))


def do_upload(radio):
    _apply_new_password(radio)
    _gt18_enter_programming_mode(radio, write=True)
    status = chirp_common.Status()
    status.msg = 'Uploading to radio'
    status.max = sum(end - start for start, end in radio._ranges)
    status.cur = 0
    try:
        for start, end in radio._ranges:
            for addr in range(start, end, WRITE_SIZE):
                _t18_write_block(radio, addr, WRITE_SIZE)
                status.cur += WRITE_SIZE
                radio.status_fn(status)
    except errors.RadioError:
        raise
    except Exception:
        LOG.exception('Unexpected error during upload')
        raise errors.RadioError('Unexpected error communicating with radio')
    finally:
        _t18_exit_programming_mode(radio)


# -- Main class ---------------------------------------------------------------

@directory.register
class BaofengGT18(RB18Radio):
    """Baofeng GT-18 FRS"""
    VENDOR = 'Baofeng'
    MODEL = 'GT-18'

    NEEDS_COMPAT_SERIAL = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.0),
        chirp_common.PowerLevel('Low', watts=0.5),
    ]

    VALID_BANDS = [(162000000, 164000000),   # NOAA weather
                   (461000000, 468000000)]   # FRS / GMRS

    _upper = 32
    _memsize = 0x07B8
    _ranges = [(0x0000, 0x0660), (0x07B0, 0x07B8)]
    _mem_params = (99,)

    # GT-18 ident not yet confirmed from hardware; accept any 8-byte response
    _fingerprint = [b'']

    # Instance-level state (not in mmap)
    _opt_pwd = ''
    _new_pwd = ''

    # -- CHIRP boilerplate ----------------------------------------------------

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_name = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = False
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            'Tone->Tone', 'Tone->DTCS', 'DTCS->Tone',
            '->Tone', '->DTCS', 'DTCS->', 'DTCS->DTCS',
        ]
        rf.valid_dtcs_codes = sorted(chirp_common.DTCS_CODES)
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ['']
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_skips = ['', 'S']
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = self.VALID_BANDS
        rf.memory_bounds = (1, self._upper)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            data = do_download(self)
        except errors.RadioError:
            raise
        except Exception:
            LOG.exception('Unexpected error during download')
            raise errors.RadioError(
                'Unexpected error communicating with radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception:
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError(
                'Unexpected error communicating with radio')

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    @classmethod
    def match_model(cls, filedata, filename):
        return False

    # -- Sub-audio helpers ----------------------------------------------------

    def _get_tone(self, mem, _mem):
        tx_lo = int(_mem.tx_tonelo)
        tx_hi = int(_mem.tx_tonehi)
        rx_lo = int(_mem.rx_tonelo)
        rx_hi = int(_mem.rx_tonehi)

        tx_type = _tone_type(tx_hi)
        rx_type = _tone_type(rx_hi)

        if tx_type == 'ctcss':
            tx_tmode = 'Tone'
            tx_tone = _decode_ctcss(tx_lo, tx_hi)
            tx_pol = 'N'
        elif tx_type == 'dcs':
            code, pol = _decode_dcs(tx_lo, tx_hi)
            tx_tmode, tx_tone, tx_pol = 'DTCS', code, pol
        else:
            tx_tmode, tx_tone, tx_pol = '', None, 'N'

        if rx_type == 'ctcss':
            rx_tmode = 'Tone'
            rx_tone = _decode_ctcss(rx_lo, rx_hi)
            rx_pol = 'N'
        elif rx_type == 'dcs':
            code, pol = _decode_dcs(rx_lo, rx_hi)
            rx_tmode, rx_tone, rx_pol = 'DTCS', code, pol
        else:
            rx_tmode, rx_tone, rx_pol = '', None, 'N'

        chirp_common.split_tone_decode(
            mem,
            (tx_tmode, tx_tone, tx_pol),
            (rx_tmode, rx_tone, rx_pol))

    def _set_tone(self, mem, _mem):
        ((tx_tmode, tx_tone, tx_pol),
         (rx_tmode, rx_tone, rx_pol)) = chirp_common.split_tone_encode(mem)

        if tx_tmode == 'Tone':
            _mem.tx_tonelo, _mem.tx_tonehi = _encode_ctcss(tx_tone)
        elif tx_tmode == 'DTCS':
            _mem.tx_tonelo, _mem.tx_tonehi = _encode_dcs(tx_tone, tx_pol)
        else:
            _mem.tx_tonelo = 0xFF
            _mem.tx_tonehi = 0xFF

        if rx_tmode == 'Tone':
            _mem.rx_tonelo, _mem.rx_tonehi = _encode_ctcss(rx_tone)
        elif rx_tmode == 'DTCS':
            _mem.rx_tonelo, _mem.rx_tonehi = _encode_dcs(rx_tone, rx_pol)
        else:
            _mem.rx_tonelo = 0xFF
            _mem.rx_tonehi = 0xFF

    # -- Memory read ----------------------------------------------------------

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        mem = chirp_common.Memory(number)

        if bytes(_mem.rxfreq) == b'\xff\xff\xff\xff':
            mem.empty = True
            return mem

        mem.freq = _decode_freq(bytes(_mem.rxfreq))
        mem.duplex = ''
        mem.offset = 0

        flags = int(_mem.flags)
        mem.mode = 'NFM' if (flags & 0x04) else 'FM'
        mem.skip = 'S' if (flags & 0x10) else ''
        mem.power = (self.POWER_LEVELS[0] if (flags & 0x08)
                     else self.POWER_LEVELS[1])

        self._get_tone(mem, _mem)

        mem.extra = RadioSettings()
        rs = RadioSetting(
            'busylock', 'Busy Channel Lock',
            RadioSettingValueBoolean(not bool(flags & 0x01)))
        mem.extra.append(rs)

        mem.immutable = self._get_immutable(number, mem)
        return mem

    def _get_immutable(self, number, mem):
        if 1 <= number <= 7:
            mem.freq = FRS_FREQS[number - 1]
            mem.duplex = ''
            mem.offset = 0
            mem.mode = 'NFM'
            return ['empty', 'freq', 'duplex', 'offset', 'mode']

        if 8 <= number <= 14:
            mem.freq = FRS_FREQS[number - 1]
            mem.duplex = ''
            mem.offset = 0
            mem.power = self.POWER_LEVELS[1]
            mem.mode = 'NFM'
            return ['empty', 'freq', 'duplex', 'offset', 'power', 'mode']

        if 15 <= number <= 22:
            mem.freq = FRS_FREQS[number - 1]
            mem.duplex = ''
            mem.offset = 0
            mem.mode = 'NFM'
            return ['empty', 'freq', 'duplex', 'offset', 'mode']

        if 23 <= number <= 32:
            mem.freq = NOAA_FREQS[number - 23]
            mem.duplex = ''
            mem.offset = 0
            mem.mode = 'NFM'
            mem.power = None
            return ['empty', 'freq', 'duplex', 'offset', 'mode', 'power',
                    'tmode', 'ctone', 'rtone', 'dtcs', 'rx_dtcs',
                    'dtcs_polarity', 'skip', 'extra']

        return []

    # -- Memory write ---------------------------------------------------------

    def set_memory(self, mem):
        if 23 <= mem.number <= 32:
            _mem = self._memobj.memory[mem.number - 1]
            _mem.flags = int(_mem.flags) | 0x04
            return

        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b'\xff' * 16)
            return

        if 1 <= mem.number <= 22:
            hz = FRS_FREQS[mem.number - 1]
        else:
            hz = mem.freq

        rx_bytes = _encode_freq(hz)
        tx_bytes = _encode_freq(hz)
        for i in range(4):
            _mem.rxfreq[i] = rx_bytes[i]
            _mem.txfreq[i] = tx_bytes[i]

        self._set_tone(mem, _mem)

        busylock = False
        if mem.extra:
            for setting in mem.extra:
                if setting.get_name() == 'busylock':
                    busylock = bool(setting.value)

        flags = 0
        flags |= 0x10 if mem.skip == 'S' else 0
        flags |= 0x08 if str(mem.power) == 'High' else 0
        flags |= 0x04 if mem.mode == 'NFM' else 0
        flags |= 0x00 if busylock else 0x01
        _mem.flags = flags

        for i in range(3):
            _mem.unknown[i] = 0x00

    # -- Settings -------------------------------------------------------------

    def get_settings(self):
        s1 = self._memobj.settings1
        s2 = self._memobj.settings2

        basic = RadioSettingGroup('basic', 'Basic Settings')
        pwd_grp = RadioSettingGroup('password', 'Password')
        top = RadioSettings(basic, pwd_grp)

        basic.append(RadioSetting(
            'settings2.squelch', 'Squelch Level',
            RadioSettingValueInteger(0, 9, min(int(s2.squelch), 9))))

        tot_idx = min(int(s2.tot), len(TOT_LIST) - 1)
        basic.append(RadioSetting(
            'settings2.tot', 'Time-Out Timer',
            RadioSettingValueList(TOT_LIST, current_index=tot_idx)))

        basic.append(RadioSetting(
            'settings1.voicesw', 'Voice Prompts',
            RadioSettingValueBoolean(bool(s1.voicesw))))

        voice_idx = min(int(s1.voicesel), len(VOICE_LIST) - 1)
        basic.append(RadioSetting(
            'settings1.voicesel', 'Voice Language',
            RadioSettingValueList(VOICE_LIST, current_index=voice_idx)))

        basic.append(RadioSetting(
            'settings1.scansw', 'Scan',
            RadioSettingValueBoolean(bool(s1.scansw))))

        basic.append(RadioSetting(
            'settings1.sidetone', 'Side Tone (Monitor)',
            RadioSettingValueBoolean(bool(s1.sidetone))))

        basic.append(RadioSetting(
            'settings2.tail', 'Roger / Tail Tone',
            RadioSettingValueBoolean(bool(s2.tail))))

        sysflags = int(s2.sysflags)
        basic.append(RadioSetting(
            'settings2.txendtone', 'TX End Tone',
            RadioSettingValueBoolean(bool((sysflags >> 2) & 1))))

        basic.append(RadioSetting(
            'settings2.beep', 'Key Beep',
            RadioSettingValueBoolean(bool(sysflags & 0x01))))

        basic.append(RadioSetting(
            'settings2.save', 'Battery Save',
            RadioSettingValueBoolean(bool((sysflags >> 1) & 1))))

        basic.append(RadioSetting(
            'settings1.voxsw', 'VOX',
            RadioSettingValueBoolean(bool(s1.voxsw))))

        vox_idx = max(0, min(int(s1.voxgain) - 1, len(VOX_LIST) - 1))
        basic.append(RadioSetting(
            'settings1.voxgain', 'VOX Gain',
            RadioSettingValueList(VOX_LIST, current_index=vox_idx)))

        basic.append(RadioSetting(
            'settings1.lowtxdis', 'Low Battery TX Inhibit',
            RadioSettingValueBoolean(bool(s1.lowtxdis))))

        basic.append(RadioSetting(
            'settings1.hightxdis', 'High Battery TX Inhibit',
            RadioSettingValueBoolean(bool(s1.hightxdis))))

        emerg_idx = min(int(s2.emergmode), len(EMERG_LIST) - 1)
        basic.append(RadioSetting(
            'settings2.emergmode', 'Emergency Mode',
            RadioSettingValueList(EMERG_LIST, current_index=emerg_idx)))

        pwd_grp.append(RadioSetting(
            '_opt_pwd', 'Current Radio Password (for download)',
            RadioSettingValueString(0, 6,
                                    getattr(self, '_opt_pwd', ''),
                                    False)))

        pwd_grp.append(RadioSetting(
            '_new_pwd', 'New Password (blank = no change)',
            RadioSettingValueString(0, 6,
                                    getattr(self, '_new_pwd', ''),
                                    False)))

        return top

    def set_settings(self, settings):
        s1 = self._memobj.settings1
        s2 = self._memobj.settings2

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            name = element.get_name()

            if name == '_opt_pwd':
                self._opt_pwd = str(element.value).strip()
                continue
            if name == '_new_pwd':
                self._new_pwd = str(element.value).strip()
                continue

            if name == 'settings2.beep':
                sf = int(s2.sysflags)
                s2.sysflags = (sf | 0x01) if bool(element.value) else (sf & ~0x01)
                continue
            if name == 'settings2.save':
                sf = int(s2.sysflags)
                s2.sysflags = (sf | 0x02) if bool(element.value) else (sf & ~0x02)
                continue
            if name == 'settings2.txendtone':
                sf = int(s2.sysflags)
                s2.sysflags = (sf | 0x04) if bool(element.value) else (sf & ~0x04)
                continue

            if name == 'settings2.tot':
                s2.tot = TOT_LIST.index(str(element.value))
                continue
            if name == 'settings1.voicesel':
                s1.voicesel = VOICE_LIST.index(str(element.value))
                continue
            if name == 'settings2.emergmode':
                s2.emergmode = EMERG_LIST.index(str(element.value))
                continue
            if name == 'settings1.voxgain':
                s1.voxgain = int(str(element.value))
                continue

            try:
                if '.' in name:
                    parts = name.split('.')
                    obj = self._memobj
                    for part in parts[:-1]:
                        obj = getattr(obj, part)
                    setattr(obj, parts[-1], element.value)
                else:
                    LOG.warning('GT-18: unknown setting %s', name)
            except Exception:
                LOG.debug('GT-18: failed to set %s', name)
                raise
