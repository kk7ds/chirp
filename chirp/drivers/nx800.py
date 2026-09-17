# Copyright 2026 Dan Smith <dsmith@danplanet.com>
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

import logging
import time

from chirp import bitwise, util
from chirp import checksum
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import settings
from chirp.drivers import tk280
from chirp.drivers import tk8180


LOG = logging.getLogger(__name__)


POWER_LEVELS = [chirp_common.PowerLevel('Low', watts=5),
                chirp_common.PowerLevel('High', watts=50)]

CHANNEL_TYPES = ['Analog', 'NXDN', 'Mixed']
DISPLAY_FORMAT_VALUES = {
    'CH/GID Name': 0xFF,
    'Zone-CH/GID Number': 0x30,
}
SUBLCD_VALUES = {
    'None': 0xFF,
    'Zone Number': 0x30,
    'CH/GID Number': 0x31,
    'OST List Number': 0x32,
    'Site Number': 0x33,
}
TONE_VOLUME_VALUES = [('Off', 0x00), ('Selectable', 0x30), ('Current', 0xFF)]
TONE_VOLUME_VALUES += [('%i' % i, i) for i in range(1, 32)]
TIMED_POWER_OFF_VALUES = ['%ih%02dm' % divmod(i * 10, 60)
                          for i in range(0, 49)]
NX800_R_BLOCK_COUNT = 0x276
NX800_S_BLOCKS = [
    0x0000,
    0x0100, 0x0200, 0x0300, 0x0400, 0x0500, 0x0600, 0x0700,
    0x0800, 0x0900, 0x0A00, 0x0B00, 0x0C00, 0x0D00, 0x0E00,
    0x0F00, 0x1000, 0x1100,
    0x8300, 0x8600, 0x8700, 0x8800, 0x8900, 0x8A00,
    0x2D00, 0x2E00, 0x2F00,
]
NX800_S_BASE = 0x27600
NX800_X_BLOCKS = [
    0x0000,
    0x0100, 0x0200, 0x0300, 0x0400, 0x0500, 0x0600, 0x0700,
    0x0800, 0x0900, 0x0A00, 0x0B00, 0x0C00, 0x0D00, 0x0E00,
    0x0F00, 0x1000, 0x1100,
    0x2D00, 0x2E00, 0x2F00,
]
MODE_ANALOG = 0xFD
MODE_NXDN = 0xF8
MODE_MIXED_DIGITAL_PREF = 0xFA
MODE_MIXED_ANALOG_PREF = 0xFE
MODE_MIXED = (MODE_MIXED_DIGITAL_PREF, MODE_MIXED_ANALOG_PREF)


def _sanitize_ran(value):
    value = int(value)
    if value < 1:
        return 1
    if value > 63:
        return 63
    return value


def _xor_wire(data, key):
    return bytes([b ^ key for b in data])


def _send_xor(radio, data):
    radio.pipe.write(_xor_wire(data, radio._wire_xor_key))


def _read_xor(radio, count):
    data = radio.pipe.read(count)
    if len(data) != count:
        raise errors.RadioError('Short read from radio')
    return _xor_wire(data, radio._wire_xor_key)


def _exchange_xor_ack(radio):
    _send_xor(radio, b'\x06')
    if _read_xor(radio, 1) != b'\x06':
        raise errors.RadioError('Post-block exchange failed')


def do_ident(radio):
    radio.pipe.baudrate = 9600
    radio.pipe.stopbits = 2
    radio.pipe.timeout = 1

    radio.pipe.write(b'PROGRAM')
    ack = radio.pipe.read(1)
    if not ack:
        raise errors.RadioNoResponse()
    if ack != b'\x16':
        raise errors.RadioError('Radio refused hi-speed program mode')

    radio.pipe.baudrate = 19200
    ack = radio.pipe.read(1)
    if not ack:
        raise errors.RadioNoResponse()
    if ack != b'\x06':
        raise errors.RadioError('Radio refused program mode')

    radio.pipe.write(b'\x02')
    ident = radio.pipe.read(48)
    if len(ident) != 48:
        raise errors.RadioError('Radio did not return ident')
    if ident[:8] != radio._model:
        LOG.warning('Radio model mismatch:\n%s' % util.hexprint(ident))
        raise errors.RadioError('Unsupported radio model %r' % ident)

    # This can be anything. We choose it to be 0x00 so that the rest of the
    # communication happens in the clear for easier debugging of traces.
    # The OEM software seems to pick a random value for each session,
    # obfuscating the traces. Setting this differently would achieve the
    # same result here, but there is no reason for us to do that.
    radio._wire_xor_key = 0x00

    # We tell the radio what the key is by sending it XOR'd with magic
    # value 0xB2, followed by cleartext ACK (0x06). The radio will then
    # ack in the clear and all future communications will be XOR'd.
    radio.pipe.write(bytes([radio._wire_xor_key ^ 0xB2, 0x06]))
    if radio.pipe.read(1) != b'\x06':
        raise errors.RadioError('Radio refused obfuscated mode')

    # Initial exchange observed before first R/S requests.
    _send_xor(radio, b'P')
    _read_xor(radio, 12)
    _exchange_xor_ack(radio)

    # Optional model string read seen in OEM trace.
    _send_xor(radio, b'URK')
    _read_xor(radio, 34)
    _exchange_xor_ack(radio)


def do_download(radio):
    do_ident(radio)

    data = bytearray(b'\xFF' * radio._memsize)
    read_count = 0

    def status():
        st = chirp_common.Status()
        st.cur = read_count
        st.max = radio._memsize
        st.msg = 'Cloning from radio'
        radio.status_fn(st)

    for block in range(0, NX800_R_BLOCK_COUNT):
        _send_xor(radio, tk8180.make_frame('R', block))
        cmd = _read_xor(radio, 1)
        chunk = b''
        addr = block * 0x100
        if cmd == b'Z':
            read_count += 0x100
        elif cmd == b'W':
            chunk = _read_xor(radio, 256)
            data[addr:addr + 0x100] = chunk
            read_count += 0x100
        else:
            raise errors.RadioError('Unexpected response %r for block %02x' %
                                    (cmd, block))

        chksum = _read_xor(radio, 1)
        calc = checksum.checksum_8bit(chunk)
        if chunk and calc != chksum[0]:
            raise errors.RadioError('Checksum failure while reading block')

        _exchange_xor_ack(radio)
        status()

    s_index = {addr: idx for idx, addr in enumerate(NX800_S_BLOCKS)}
    for block in NX800_S_BLOCKS:
        _send_xor(radio, tk8180.make_frame('S', block, b'\x00'))
        cmd = _read_xor(radio, 1)
        if cmd != b'X':
            raise errors.RadioError('Radio did not send block for %04x' %
                                    block)
        chunk = _read_xor(radio, 256)
        soff = NX800_S_BASE + (s_index[block] * 0x100)
        data[soff:soff + 0x100] = chunk
        read_count += 0x100

        _exchange_xor_ack(radio)
        status()

    _send_xor(radio, b'E')
    if _read_xor(radio, 1) != b'\x06':
        raise errors.RadioError('Radio failed to acknowledge completion')

    return bytes(data)


def do_upload(radio):
    do_ident(radio)

    progress = 0

    def status(cur):
        st = chirp_common.Status()
        st.cur = cur
        st.max = radio._memsize
        st.msg = 'Cloning to radio'
        radio.status_fn(st)

    mmap = radio._mmap.get_packed()

    for block in range(0, NX800_R_BLOCK_COUNT):
        addr = block * 0x100
        chunk = mmap[addr:addr + 0x100]
        if len(chunk) != 0x100:
            raise errors.RadioError('Invalid memory map while uploading')

        if all(byte == 0xFF for byte in chunk):
            _send_xor(radio, tk8180.make_frame('Z', block, b'\xFF'))
        else:
            cs = checksum.checksum_8bit(chunk)
            _send_xor(radio, tk8180.make_frame(
                'W', block, chunk + bytes([cs])))

        if _read_xor(radio, 1) != b'\x06':
            raise errors.RadioError('Radio refused data block %04x' % block)
        progress += 0x100
        status(progress)

    for i, addr in enumerate(NX800_X_BLOCKS):
        src = NX800_S_BASE + (i * 0x100)
        chunk = mmap[src:src + 0x100]
        if len(chunk) != 0x100:
            raise errors.RadioError('Invalid memory map while uploading')

        _send_xor(radio, tk8180.make_frame('X', addr, b'\x00' + chunk))

        if _read_xor(radio, 1) != b'\x06':
            raise errors.RadioError('Radio refused data block %04x' % addr)
        progress += 0x100
        status(progress)

    _send_xor(radio, b'E')
    if _read_xor(radio, 1) != b'\x06':
        raise errors.RadioError('Radio failed to acknowledge completion')


def _best_effort_reset(radio):
    try:
        radio.pipe.baudrate = 9600
        radio.pipe.write(b'E')
        time.sleep(0.3)
        radio.pipe.baudrate = 19200
        radio.pipe.write(b'E')
    except Exception:
        LOG.exception('Unable to send reset sequence')


BASE_MEM_FORMAT = """
// No idea why, but if this is set to 0xFF KPG won't open it (but radio
// does not seem to care). Error is something about the missing/mismatched
// "system key", even for purely analog radios. Not sure when this would
// get unset or need to be reset, but enumerate it here for easy
// identification at least.
#seekto 0x0031;
u8 systemkey;

struct memory {
  u8 number;
  u8 unknown01_03[3];
  ul32 rx_freq;
  ul32 tx_freq;
  ul16 rx_tone;
  ul16 tx_tone;
  u8 ran_dec;
  u8 unknown12;
  u8 ran_enc;
  u8 unknown14;
  char name[14];
  u8 unknown22_3c[26];
  u8 tx_upper_f:5,
     analog_tx:1,
     mixed:1,
     analog_rx:1;
  u8 modeunknown:5,
     highpower:1,
     modeunknown2:2;
  u8 unknown3e_1:4,
     unknown3e_2:4;
  u8 unknown3f_1:3,  // always 0b111
     digital_narrow:1,
     unknown3f_2:2,  // always 0b11 on nx, 0b00 on analog
     analog_wide:1,
     unknown3f_3:1;  // always 1
};

#seekto 0x5D00;
ul16 zone_starts[128];

struct zoneinfo {
  u8 number;
  u8 zonetype;
  ul16 flagoffset;
  u8 count;
  u8 unknown06;
  char name[14];
  u8 unknown15_18[4];
  ul16 tot_timeout;
  ul16 tot_prealert;
  ul16 tot_rekey;
  ul16 tot_reset;
  u8 unknown21_2c[12];
  u8 unknown2d;
  u8 unknown2e_2f[2];
  u8 unknown30_3f[17];
};

#seekto 0x201;
u8 sublcd;

#seekto 0x220;
char pon_msgtext[14];

#seekto 0x22E;
u8 pon_msgtype;

#seekto 0x232;
u8 low_volume_level;

#seekto 0x233;
u8 high_volume_level;

#seekto 0x234;
u8 tone_volume_offset;

#seekto 0x235;
u8 poweron_tone;

#seekto 0x236;
u8 control_tone;

#seekto 0x237;
u8 warning_tone;

#seekto 0x238;
u8 alert_tone;

#seekto 0x239;
u8 sidetone;

#seekto 0x23A;
u8 locator_tone;

#seekto 0x23C;
u8 timed_power_off;

#seekto 0x23B;
u8 ignition_mode;

#seekto 0x26C;
struct {
  u8 ignition_sense:1,
     unknown26d_0:2,
     signal_strength_indicator:1,
     power_switch_memory:1,
     unknown26d_1:2,
     off_hook_decode:1;
} conv_settings;

#seekto 0x26E;
struct {
  u8 unknown26f_0:3,
     clone:1,
     firmware_programming:1,
     firmware_version_information:1,
     panel_tuning:1,
     panel_test:1;
} panel_settings;

#seekto 0x269;
struct {
  u8 unknown270_0:5,
     zone_name_display:1,
     unknown270_1:2;
} conv_settings2;

#seekto 0x28D;
struct {
  u8 unknown28e_0:6,
     tone_off:1,
     ost_memory:1;
} settings;

#seekto 0x2FF;
struct {
  u8 unknown00;
  char name[14];
  u8 unknown0f_10[2];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown15_1f[11];
} ost_tones[40];

#seekto 0x27A00;
u8 squelch;

#seekto 0x27A02;
u8 display_format;

#seekto 0x27A05;
u8 clock_display;

#seekto 0x27B00;
lbit skipflags[512];
"""


class KenwoodNXx00Radio(tk8180.ZoneMemoryMixin, tk8180.KenwoodOSTMixin,
                        chirp_common.CloneModeRadio):
    """Kenwood NX-x00 file-format bootstrap."""

    VENDOR = 'Kenwood'
    MODEL = 'NX-x00'
    BAUD_RATE = 9600
    FORMATS = [directory.register_format('Kenwood KPG-111D', '*.dat')]

    _dat_size = 0x40
    _dat_variant = None
    _default_dat_key = 0x00
    _memsize = 0x29100
    _system_start = 0x5E00
    _max_per_zone = 250
    _zone_header_size = 0x40
    _memory_size = 0x40
    OST_NAME_LENGTH = 14

    def _compute_zone_layout(self, zone_sizes):
        zones = []
        addr = self._system_start
        for count in zone_sizes:
            zones.append((addr, count))
            addr += self._zone_header_size + (count * self._memory_size)
        return zones

    def _set_zone_flagoffset(self, zoneinfo, scan_index):
        zoneinfo.flagoffset = scan_index

    def __init__(self, *a, **k):
        self._wire_xor_key = 0x00
        self._zones = []
        self._channel_map = []
        self._zone = None
        super().__init__(*a, **k)
        dat_variant = self._dat_variant
        if dat_variant is None:
            dat_variant = 0x06
        self._dat_header = (b'KPG111D\xFF\xFF\xFFV2.00\xFF' + self._model +
                            b'\xFF\xFF\x00' + bytes([dat_variant]) +
                            b'\xFF\xFF\xFF\xFFD' + (b'\xFF' * 31))

    @staticmethod
    def _xor_payload(payload, key):
        return bytes([byte ^ key for byte in payload])

    @classmethod
    def _get_dat_xor_key(cls, payload):
        if not payload:
            raise errors.RadioError('DAT file is empty')
        return payload[0] ^ 0xFF

    @classmethod
    def match_model(cls, filedata, filename):
        if filename.lower().endswith('.dat'):
            if len(filedata) < cls._dat_size + cls._memsize:
                return False
            if not filedata.startswith(b'KPG111D'):
                return False
            if filedata[0x10:0x18] != cls._model:
                return False
            if cls._dat_variant is None:
                return True
            return filedata[0x1B] == cls._dat_variant
        return False

    def sync_in(self):
        try:
            data = do_download(self)
            self._mmap = memmap.MemoryMapBytes(data)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('General failure')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        finally:
            _best_effort_reset(self)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            _best_effort_reset(self)
            raise
        except Exception as e:
            _best_effort_reset(self)
            LOG.exception('General failure')
            raise errors.RadioError('Failed to upload to radio: %s' % e)
        finally:
            _best_effort_reset(self)

    def load_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'rb') as f:
                self._dat_header = f.read(self._dat_size)
                obfuscated = f.read()
            if len(obfuscated) == self._memsize + 1:
                dat_xor_key = self._get_dat_xor_key(obfuscated)
                payload = self._xor_payload(obfuscated[1:], dat_xor_key)
            elif len(obfuscated) == self._memsize:
                dat_xor_key = obfuscated[-1] ^ 0xFF
                payload = self._xor_payload(obfuscated, dat_xor_key)
            else:
                raise errors.RadioError(
                    'Unexpected DAT payload size %i' % len(obfuscated))
            self._mmap = memmap.MemoryMapBytes(payload)
            self.process_mmap()
            LOG.info('Loaded DAT file with xor key 0x%02X',
                     dat_xor_key)
        else:
            super().load_mmap(filename)

    def save_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            # Per above, we choose a key of 0x00 so we end up with no
            # obfuscation in the DAT file for easier debugging. If we set
            # this to something non-zero we would obfuscate the file in the
            # same way OEM does.
            key = self._default_dat_key
            payload = self._mmap.get_packed()
            if len(payload) != self._memsize:
                raise errors.RadioError(
                    'Invalid memory size %i' % len(payload))
            obfuscated = bytes([0xFF ^ key]) + self._xor_payload(payload, key)
            with open(filename, 'wb') as f:
                f.write(self._dat_header)
                f.write(obfuscated)
            LOG.info('Wrote DAT file with xor key 0x%02X', key)
        else:
            super().save_mmap(filename)

    def process_mmap(self):
        self._zones = self.probe_layout()
        self._memobj = bitwise.parse(
            self._build_mem_format_from_zone_sizes(
                [x[1] for x in self._zones]),
            self._mmap)
        self._channel_map = []
        for zoneindex, (_addr, count) in enumerate(self._zones):
            for chanindex in range(count):
                self._channel_map.append((zoneindex, chanindex))

    def _build_mem_format_from_zone_sizes(self, zone_sizes):
        mem_format = BASE_MEM_FORMAT
        for index, (addr, count) in enumerate(self._compute_zone_layout(
                zone_sizes)):
            mem_format += tk8180.SYSTEM_MEM_FORMAT % {
                'addr': addr,
                'count': max(count, 1),
                'index': index,
            }
        return mem_format

    def probe_layout(self):
        static = bitwise.parse(BASE_MEM_FORMAT, self._mmap)

        zone_addresses = []
        for i in range(0, 128):
            addr = int(static.zone_starts[i])
            if addr == 0xFFFF:
                break
            zone_addresses.append(addr)

        probe_format = BASE_MEM_FORMAT
        for i, addr in enumerate(zone_addresses):
            probe_format += '#seekto 0x%x; struct zoneinfo zone%i;' % (addr, i)

        probe = bitwise.parse(probe_format, self._mmap)
        zones = []
        for i, addr in enumerate(zone_addresses):
            zone = getattr(probe, 'zone%i' % i)
            if int(zone.zonetype) != 0x31:
                LOG.warning(
                    'Unsupported non-conventional zone %i type %02x at 0x%04x',
                    i, int(zone.zonetype), addr)
                raise errors.RadioError('Unsupported non-conventional zone')
            zones.append((addr, int(zone.count)))

        LOG.debug('Zones: %s', zones)
        return zones

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_settings = self._zone is None
        if self._zone is None:
            rf.memory_bounds = (1, max(1, len(self._channel_map)))
            rf.has_sub_devices = True
            rf.has_dynamic_subdevices = True
        else:
            rf.memory_bounds = (1, self._max_per_zone)
            rf.has_sub_devices = False
            rf.has_dynamic_subdevices = False
        rf.can_odd_split = True
        rf.valid_modes = ['FM', 'NFM', 'NXDN']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS',
                                'Tone->DTCS', 'DTCS->Tone', '->Tone',
                                'DTCS->DTCS']
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_skips = ['', 'S']
        rf.valid_name_length = 14
        rf.valid_bands = self.VALID_BANDS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_tuning_steps = [5.0, 12.5, 6.25]
        return rf

    def _resolve_channel(self, number):
        if self._zone is None:
            if number < 1 or number > len(self._channel_map):
                return None
            return self._channel_map[number - 1]

        if number < 1 or number > self._max_per_zone:
            return None
        chanindex = self._get_zone_channel_index(self._zone, number)
        if chanindex is None:
            return None
        return self._zone, chanindex

    def _get_zone_channel_index(self, zoneindex, number):
        zone = getattr(self._memobj, 'zone%i' % zoneindex)
        count = self._zones[zoneindex][1]
        for i in range(count):
            if int(zone.memories[i].number) == number:
                return i
        return None

    def _init_new_zoneinfo(self, dest_zoneinfo, zone_number, count,
                           old_memobj):
        if self._zones:
            z0info = getattr(old_memobj, 'zone0').zoneinfo
            dest_zoneinfo.set_raw(z0info.get_raw())
        else:
            dest_zoneinfo.set_raw(b'\xFF' * 0x40)
        dest_zoneinfo.number = zone_number + 1
        dest_zoneinfo.zonetype = 0x31
        dest_zoneinfo.count = count
        dest_zoneinfo.name = ('  %i' % (zone_number + 1)).ljust(14, '\x00')

    def expand_mmap(self, zone_sizes):
        super().expand_mmap(zone_sizes)

    def get_raw_memory(self, number):
        resolved = self._resolve_channel(number)
        if resolved is None:
            raise errors.RadioError('Invalid memory %s' % number)
        zoneindex, chanindex = resolved
        zone = getattr(self._memobj, 'zone%i' % zoneindex)
        return repr(zone.memories[chanindex])

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number

        resolved = self._resolve_channel(number)
        if resolved is None:
            mem.empty = True
            return mem

        zoneindex, chanindex = resolved
        zobj = getattr(self._memobj, 'zone%i' % zoneindex)
        zone = zobj.zoneinfo
        _mem = zobj.memories[chanindex]

        if int(_mem.number) == 0xFF or int(_mem.rx_freq) in (0, 0xFFFFFFFF):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq)
        mem.name = str(_mem.name).rstrip('\x00').rstrip()

        chirp_common.split_tone_decode(
            mem,
            tk8180.KenwoodTKx180Radio._decode_tone(int(_mem.tx_tone)),
            tk8180.KenwoodTKx180Radio._decode_tone(int(_mem.rx_tone)))

        tx = int(_mem.tx_freq)
        if tx == 0xFFFFFFFF:
            mem.duplex = 'off'
            mem.offset = 0
        else:
            offset = tx - mem.freq
            if offset == 0:
                mem.duplex = ''
                mem.offset = 0
            elif abs(offset) < 10000000:
                mem.duplex = offset < 0 and '-' or '+'
                mem.offset = abs(offset)
            else:
                mem.duplex = 'split'
                mem.offset = tx

        verynarrow = not _mem.digital_narrow
        if _mem.mixed:
            channel_type = 'Mixed'
            if _mem.analog_tx:
                mem.mode = 'FM' if _mem.analog_wide else 'NFM'
            else:
                mem.mode = 'NXDN'
        elif _mem.analog_rx:
            # Analog only
            channel_type = 'Analog'
            mem.mode = 'FM' if _mem.analog_wide else 'NFM'
        else:
            # Digital only
            channel_type = 'NXDN'
            mem.mode = 'NXDN'

        ran_dec = _sanitize_ran(int(_mem.ran_dec))
        ran_enc = _sanitize_ran(int(_mem.ran_enc))

        mem.extra = settings.RadioSettingGroup('extra', 'Extra')
        val = settings.RadioSettingValueList(
            CHANNEL_TYPES,
            current_index=CHANNEL_TYPES.index(channel_type))
        mem.extra.append(settings.RadioSetting('channel_type',
                                               'Channel Type', val))

        val = settings.RadioSettingValueBoolean(_mem.analog_wide)
        val.set_mutable(channel_type == 'Mixed' and mem.mode == 'NXDN')
        mem.extra.append(settings.RadioSetting('analog_wide',
                                               'Analog Wide', val))

        val = settings.RadioSettingValueBoolean(verynarrow)
        val.set_mutable(channel_type != 'Analog')
        mem.extra.append(settings.RadioSetting('verynarrow',
                                               'NXDN Very Narrow', val))

        val = settings.RadioSettingValueInteger(1, 63, ran_dec)
        val.set_mutable(channel_type != 'Analog')
        mem.extra.append(settings.RadioSetting('ran_dec',
                                               'RAN Dec', val))

        val = settings.RadioSettingValueInteger(1, 63, ran_enc)
        val.set_mutable(channel_type != 'Analog')
        mem.extra.append(settings.RadioSetting('ran_enc',
                                               'RAN Enc', val))

        mem.power = POWER_LEVELS[int(_mem.highpower)]

        scan_index = int(zone.flagoffset) + chanindex - 1
        if 0 <= scan_index < len(self._memobj.skipflags):
            mem.skip = 'S' if bool(self._memobj.skipflags[scan_index]) else ''
        else:
            mem.skip = ''

        return mem

    def set_memory(self, mem):
        resolved = self._resolve_channel(mem.number)
        if resolved is None:
            if mem.empty:
                return
            if self._zone is None:
                raise errors.RadioError('Only discovered channels are '
                                        'writable')

            if mem.number > self._max_per_zone:
                raise errors.RadioError('Maximum channels per zone is %i' %
                                        self._max_per_zone)

            parent = getattr(self, '_parent', self)
            zoneindex = self._zone
            new_sizes = [x[1] for x in parent._zones]
            new_sizes[zoneindex] = new_sizes[zoneindex] + 1
            parent.expand_mmap(new_sizes)

            zobj = getattr(self._memobj, 'zone%i' % zoneindex)
            _mem = zobj.memories[parent._zones[zoneindex][1] - 1]
            _mem.number = mem.number
            self.shuffle_zone()

            chanindex = parent._get_zone_channel_index(zoneindex, mem.number)
            if chanindex is None:
                raise errors.RadioError('Failed to allocate memory')
            _mem = zobj.memories[chanindex]

            zone = zobj.zoneinfo
        else:
            zoneindex, chanindex = resolved
            zobj = getattr(self._memobj, 'zone%i' % zoneindex)
            zone = zobj.zoneinfo
            _mem = zobj.memories[chanindex]

        if mem.empty:
            parent = getattr(self, '_parent', self)
            _mem.number = 0xFF
            self.shuffle_zone()
            new_sizes = [x[1] for x in parent._zones]
            new_sizes[zoneindex] = new_sizes[zoneindex] - 1
            parent.expand_mmap(new_sizes)
            return

        _mem.number = mem.number
        _mem.rx_freq = mem.freq
        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _mem.tx_tone = tk8180.KenwoodTKx180Radio._encode_tone(*txtone)
        _mem.rx_tone = tk8180.KenwoodTKx180Radio._encode_tone(*rxtone)
        _mem.name = mem.name[:14].ljust(14)
        _mem.highpower = mem.power == POWER_LEVELS[1]

        # Default in case we don't have mem.extra:
        channel_type = 'NXDN' if mem.mode == 'NXDN' else 'Analog'
        verynarrow = False
        analog_wide = mem.mode == 'FM'
        ran_dec = ran_enc = 0

        for setting in mem.extra or []:
            if setting.get_name() == 'channel_type':
                value = str(setting.value)
                if value in CHANNEL_TYPES:
                    channel_type = value
                else:
                    try:
                        channel_type = CHANNEL_TYPES[int(setting.value)]
                    except (TypeError, ValueError, IndexError):
                        pass
            elif setting.get_name() == 'verynarrow':
                verynarrow = bool(int(setting.value))
            elif (setting.get_name() == 'analog_wide' and
                  channel_type == 'Mixed' and
                  mem.mode == 'NXDN'):
                analog_wide = bool(int(setting.value))
            elif setting.get_name() == 'ran_dec':
                ran_dec = _sanitize_ran(setting.value)
            elif setting.get_name() == 'ran_enc':
                ran_enc = _sanitize_ran(setting.value)

        _mem.analog_rx = channel_type == 'Analog'
        _mem.mixed = channel_type == 'Mixed'
        _mem.analog_tx = mem.mode != 'NXDN'
        _mem.digital_narrow = not verynarrow
        _mem.analog_wide = analog_wide
        _mem.unknown3f_2 = 0x3 if channel_type == 'NXDN' else 0
        _mem.unknown3f_1 = 0x0 if channel_type == 'NXDN' else 0x7

        if channel_type != 'Analog':
            _mem.ran_dec = ran_dec
            _mem.ran_enc = ran_enc
        else:
            _mem.ran_dec = 0xFF
            _mem.ran_enc = 0xFF

        if mem.duplex == '':
            _mem.tx_freq = mem.freq
        elif mem.duplex == 'split':
            _mem.tx_freq = mem.offset
        elif mem.duplex == 'off':
            _mem.tx_freq = 0xFFFFFFFF
        elif mem.duplex == '-':
            _mem.tx_freq = mem.freq - mem.offset
        elif mem.duplex == '+':
            _mem.tx_freq = mem.freq + mem.offset
        else:
            raise errors.RadioError('Unsupported duplex mode %r' % mem.duplex)

        scan_index = int(zone.flagoffset) + chanindex - 1
        if 0 <= scan_index < len(self._memobj.skipflags):
            self._memobj.skipflags[scan_index] = int(mem.skip == 'S')

    def get_sub_devices(self):
        zones = []
        to_copy = ('VENDOR', 'MODEL', 'VALID_BANDS', '_model')
        for i, _ in enumerate(self._zones):
            zone = getattr(self._memobj, 'zone%i' % i)
            zone_cls = tk280.TKx80SubdevMeta.make_subdev(
                self, KenwoodNXx00RadioZone, i, to_copy,
                VARIANT='Zone %s' % (
                    str(zone.zoneinfo.name).rstrip('\x00').rstrip()))
            zones.append(zone_cls(self, i))
        return zones

    def _get_zones(self):
        zones = settings.RadioSettingGroup('zones', 'Zones')

        zone_count = settings.RadioSetting(
            '_zonecount',
            'Number of Zones',
            settings.RadioSettingValueInteger(1, 128, len(self._zones)))
        zone_count.set_doc('Number of zones in the radio. Reducing this '
                           'number will DELETE memories in affected zones!')
        zone_count.set_volatile(True)
        zones.append(zone_count)

        for i in range(len(self._zones)):
            zone = settings.RadioSettingSubGroup('zone%i' % i,
                                                 'Zone %i' % (i + 1))
            _zone = getattr(self._memobj, 'zone%i' % i).zoneinfo

            _name = str(_zone.name).rstrip('\x00')
            name = settings.MemSetting(
                'zone%i.zoneinfo.name' % i,
                'Name',
                settings.RadioSettingValueString(0, 14, _name,
                                                 mem_pad_char='\x00'))
            zone.append(name)

            def apply_timer(setting, key, zone_number):
                val = int(setting.value)
                if key == 'tot_timeout':
                    if val < 15:
                        val = 15
                    elif val > 1200:
                        val = 1200
                    val = (val // 15) * 15
                elif val == 0:
                    val = 0xFFFF
                _zone = getattr(self._memobj,
                                'zone%i' % zone_number).zoneinfo
                setattr(_zone, key, val)

            def collapse_timer(val):
                val = int(val)
                if val == 0xFFFF:
                    val = 0
                return val

            timeout = settings.RadioSetting(
                'z%itot_timeout' % i,
                'Time-out Timer',
                settings.RadioSettingValueInteger(
                    15, 1200,
                    max(15, min(1200, int(_zone.tot_timeout))), 15))
            timeout.set_apply_callback(apply_timer, 'tot_timeout', i)
            zone.append(timeout)

            prealert = settings.RadioSetting(
                'z%itot_prealert' % i,
                'TOT Pre-Alert',
                settings.RadioSettingValueInteger(
                    0, 10, collapse_timer(_zone.tot_prealert)))
            prealert.set_apply_callback(apply_timer, 'tot_prealert', i)
            zone.append(prealert)

            rekey = settings.RadioSetting(
                'z%itot_rekey' % i,
                'TOT Re-Key Time',
                settings.RadioSettingValueInteger(
                    0, 60, collapse_timer(_zone.tot_rekey)))
            rekey.set_apply_callback(apply_timer, 'tot_rekey', i)
            zone.append(rekey)

            reset = settings.RadioSetting(
                'z%itot_reset' % i,
                'TOT Reset Time',
                settings.RadioSettingValueInteger(
                    0, 15, collapse_timer(_zone.tot_reset)))
            reset.set_apply_callback(apply_timer, 'tot_reset', i)
            zone.append(reset)

            zones.append(zone)

        return zones

    def _get_ost(self):
        ostgroup = super()._get_ost()

        for key, name in (('ost_memory', 'OST Status Memory'),
                          ('tone_off', 'Tone Off')):
            ostgroup.append(settings.MemSetting(
                'settings.%s' % key, name,
                settings.RadioSettingValueInvertedBoolean(
                    not bool(getattr(self._memobj.settings, key)))))

        # RadioSettingGroup only supports appending, so move the
        # settings we added to the front of the group, ahead of the
        # individual OSTs appended by the parent.
        for i, key in enumerate(('ost_memory', 'tone_off')):
            name = 'settings_%s' % key
            ostgroup.keys().remove(name)
            ostgroup.keys().insert(i, name)

        return ostgroup

    def _get_conventional(self):
        conv = settings.RadioSettingGroup('conv', 'Conventional')

        conv.append(settings.MemSetting(
            'conv_settings.power_switch_memory',
            'Power Switch Status Memory',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.conv_settings.power_switch_memory))))

        conv.append(settings.MemSetting(
            'conv_settings.ignition_sense', 'Ignition Sense',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.conv_settings.ignition_sense))))

        conv.append(settings.MemSetting(
            'conv_settings.signal_strength_indicator',
            'Signal Strength Indicator',
            settings.RadioSettingValueInvertedBoolean(
                not bool(
                    self._memobj.conv_settings.signal_strength_indicator))))

        conv.append(settings.MemSetting(
            'conv_settings2.zone_name_display', 'Zone Name Display',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.conv_settings2.zone_name_display))))

        conv.append(settings.MemSetting(
            'panel_settings.panel_test', 'Panel Test',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.panel_settings.panel_test))))

        conv.append(settings.MemSetting(
            'panel_settings.panel_tuning', 'Panel Tuning',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.panel_settings.panel_tuning))))

        conv.append(settings.MemSetting(
            'panel_settings.clone', 'Clone',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.panel_settings.clone))))

        conv.append(settings.MemSetting(
            'panel_settings.firmware_programming',
            'Firmware Programming',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.panel_settings.firmware_programming))))

        conv.append(settings.MemSetting(
            'panel_settings.firmware_version_information',
            'Firmware Version Information',
            settings.RadioSettingValueInvertedBoolean(
                not bool(
                    self._memobj.panel_settings.firmware_version_information)
                )))

        conv.append(settings.MemSetting(
            'conv_settings.off_hook_decode', 'Off-hook Decode',
            settings.RadioSettingValueInvertedBoolean(
                not bool(self._memobj.conv_settings.off_hook_decode))))

        conv.append(settings.MemSetting(
            'squelch', 'Squelch Level',
            settings.RadioSettingValueInteger(0, 9,
                                              int(self._memobj.squelch))))

        conv.append(settings.MemSetting(
            'display_format', 'Display Format',
            settings.RadioSettingValueMap(
                DISPLAY_FORMAT_VALUES.items(),
                int(self._memobj.display_format))))

        conv.append(settings.MemSetting(
            'sublcd', 'Sub-LCD Display',
            settings.RadioSettingValueMap(SUBLCD_VALUES.items(),
                                          int(self._memobj.sublcd))))

        conv.append(settings.MemSetting(
            'clock_display', 'Clock Display',
            settings.RadioSettingValueBoolean(
                bool(self._memobj.clock_display == 0),
                mem_vals=(0xFF, 0x00))))

        conv.append(settings.MemSetting(
            'low_volume_level', 'Low Volume Level (Fixed Volume)',
            settings.RadioSettingValueInteger(
                0, 30,
                int(self._memobj.low_volume_level))))

        conv.append(settings.MemSetting(
            'high_volume_level', 'High Volume Level (Fixed Volume)',
            settings.RadioSettingValueInteger(
                1, 31,
                int(self._memobj.high_volume_level))))

        conv.append(settings.MemSetting(
            'pon_msgtype', 'Power-on Message Type',
            settings.RadioSettingValueMap(
                [('Off', 0xFF), ('Text', 0x30), ('Clock', 0x31),
                 ('FleetSync ID', 0x32), ('NXDN Unit ID', 0x33),
                 ('NXDN Unit ID Name', 0x34)],
                int(self._memobj.pon_msgtype))))

        conv.append(settings.MemSetting(
            'pon_msgtext', 'Power-on Message Text',
            settings.RadioSettingValueString(
                0, 14, str(self._memobj.pon_msgtext).rstrip('\x00'))))

        _tvo = int(self._memobj.tone_volume_offset)
        if _tvo & 0x80:
            _tvo = _tvo - 0x100
        conv.append(settings.MemSetting(
            'tone_volume_offset', 'Tone Volume Offset',
            settings.RadioSettingValueInteger(-5, 5, _tvo)))

        conv.append(settings.MemSetting(
            'poweron_tone', 'Power-on Tone',
            settings.RadioSettingValueMap(
                TONE_VOLUME_VALUES,
                int(self._memobj.poweron_tone))))

        conv.append(settings.MemSetting(
            'control_tone', 'Control Tone',
            settings.RadioSettingValueMap(
                TONE_VOLUME_VALUES,
                int(self._memobj.control_tone))))

        conv.append(settings.MemSetting(
            'warning_tone', 'Warning Tone',
            settings.RadioSettingValueMap(
                TONE_VOLUME_VALUES,
                int(self._memobj.warning_tone))))

        conv.append(settings.MemSetting(
            'alert_tone', 'Alert Tone',
            settings.RadioSettingValueMap(
                TONE_VOLUME_VALUES,
                int(self._memobj.alert_tone))))

        conv.append(settings.MemSetting(
            'sidetone', 'Sidetone',
            settings.RadioSettingValueMap(
                TONE_VOLUME_VALUES,
                int(self._memobj.sidetone))))

        conv.append(settings.MemSetting(
            'locator_tone', 'Locator Tone',
            settings.RadioSettingValueMap(
                TONE_VOLUME_VALUES,
                int(self._memobj.locator_tone))))

        conv.append(settings.MemSetting(
            'ignition_mode', 'Ignition Sense Type',
            settings.RadioSettingValueMap(
                [('Ignition and Switch', 0x30), ('Ignition Only', 0x31)],
                int(self._memobj.ignition_mode))))

        conv.append(settings.MemSetting(
            'timed_power_off', 'Timed Power Off',
            settings.RadioSettingValueList(
                TIMED_POWER_OFF_VALUES,
                current_index=int(self._memobj.timed_power_off))))

        return conv

    def get_settings(self):
        return settings.RadioSettings(self._get_zones(), self._get_ost(),
                                      self._get_conventional())

    def set_settings(self, settings_obj):
        for element in settings_obj.apply_to(self._memobj):
            if not element.changed():
                continue
            if element.get_name() == '_zonecount':
                new_zone_count = int(element.value)
                zone_sizes = [x[1] for x in self._zones[:new_zone_count]]
                if len(self._zones) > new_zone_count:
                    self.expand_mmap(zone_sizes[:new_zone_count])
                elif len(self._zones) < new_zone_count:
                    self.expand_mmap(zone_sizes +
                                     ([0] * (new_zone_count -
                                             len(self._zones))))
            elif element.has_apply_callback():
                element.run_apply_callback()


class KenwoodNXx00RadioZone:
    _zone = None

    def __init__(self, parent, zone=0):
        if isinstance(parent, KenwoodNXx00Radio):
            self._parent = parent
        else:
            LOG.warning('Parent was not actually our parent, expect failure')
        self._zone = zone

    @property
    def _zones(self):
        return self._parent._zones

    @property
    def _memobj(self):
        return self._parent._memobj

    @property
    def _mmap(self):
        return self._parent._mmap

    def load_mmap(self, filename):
        self._parent.load_mmap(filename)

    def save_mmap(self, filename):
        self._parent.save_mmap(filename)

    def get_sub_devices(self):
        return []


# Need a test to confirm
# @directory.register
class KenwoodNX700Radio(KenwoodNXx00Radio):
    MODEL = 'NX-700'
    VALID_BANDS = [(136000000, 174000000)]
    _dat_variant = 0x04
    _model = b'MNX 0700'


@directory.register
class KenwoodNX800Radio(KenwoodNXx00Radio):
    MODEL = 'NX-800'
    VALID_BANDS = [(400000000, 520000000)]
    _dat_variant = 0x06
    _model = b'MNX 0800'
