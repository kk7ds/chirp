# Copyright 2019 Dan Smith <dsmith@danplanet.com>
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
import os
import time
import logging
from collections import OrderedDict

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueList
from chirp.settings import RadioSettingValueString, RadioSettingValueInteger
from chirp.settings import RadioSettings

LOG = logging.getLogger(__name__)

# Gross hack to handle missing future module on un-updatable
# platforms like MacOS. Just avoid registering these radio
# classes for now.
try:
    from builtins import bytes
    has_future = True
except ImportError:
    has_future = False
    LOG.warning('python-future package is not '
                'available; %s requires it' % __name__)


HEADER_FORMAT = """
#seekto 0x0100;
struct {
  char sw_name[7];
  char sw_ver[5];
  u8 unknown1[4];
  char sw_key[12];
  u8 unknown2[4];
  char model[5];
  u8 variant;
  u8 unknown3[10];
} header;

#seekto 0x0140;
struct {
  // 0x0140
  u8 unknown1;
  u8 sublcd;
  u8 unknown2[30];

  // 0x0160
  char pon_msgtext[12];
  u8 min_volume;
  u8 max_volume;
  u8 lo_volume;
  u8 hi_volume;

  // 0x0170
  u8 tone_volume_offset;
  u8 poweron_tone;
  u8 control_tone;
  u8 warning_tone;
  u8 alert_tone;
  u8 sidetone;
  u8 locator_tone;
  u8 unknown3[2];
  u8 ignition_mode;
  u8 ignition_time;  // In tens of minutes (6 = 1h)
  u8 micsense;
  ul16 modereset;
  u8 min_vol_preset;
  u8 unknown4;

  // 0x0180
  u8 unknown5[16];

  // 0x0190
  u8 unknown6[3];
  u8 pon_msgtype;
  u8 unknown7[8];
  u8 unknown8_1:2,
     ssi:1,
     busy_led:1,
     power_switch_memory:1,
     scrambler_memory:1,
     unknown8_2:1,
     off_hook_decode:1;
  u8 unknown9_1:5,
     clockfmt:1,
     datefmt:1,
     ignition_sense:1;
  u8 unknownA[2];

  // 0x01A0
  u8 unknownB[8];
  u8 ptt_timer;
  u8 unknownB2[3];
  u8 ptt_proceed:1,
     unknownC_1:3,
     tone_off:1,
     ost_memory:1,
     unknownC_2:1,
     ptt_release:1;
  u8 unknownD[3];
} settings;

#seekto 0x01E0;
struct {
  char name[12];
  ul16 rxtone;
  ul16 txtone;
} ost_tones[40];

#seekto 0x0A00;
ul16 zone_starts[128];

struct zoneinfo {
  u8 number;
  u8 zonetype;
  u8 unknown1[2];
  u8 count;
  char name[12];
  u8 unknown2[2];
  ul16 timeout;    // 15-1200
  ul16 tot_alert;  // 10
  ul16 tot_rekey;  // 60
  ul16 tot_reset;  // 15
  u8 unknown3[3];
  u8 unknown21:2,
     bcl_override:1,
     unknown22:5;
  u8 unknown5;
};

struct memory {
  u8 number;
  lbcd rx_freq[4];
  lbcd tx_freq[4];
  u8 unknown1[2];
  ul16 rx_tone;
  ul16 tx_tone;
  char name[12];
  u8 unknown2[19];
  u8 unknown3_1:4,
     highpower:1,
     unknown3_2:1,
     wide:1,
     unknown3_3:1;
  u8 unknown4;
};

#seekto 0xC570;  // Fixme
u8 skipflags[64];
"""


SYSTEM_MEM_FORMAT = """
#seekto 0x%(addr)x;
struct {
  struct zoneinfo zoneinfo;
  struct memory memories[%(count)i];
} zone%(index)i;
"""

STARTUP_MODES = ['Text', 'Clock']

VOLUMES = OrderedDict([(str(x), x) for x in range(0, 30)])
VOLUMES.update({'Selectable': 0x30,
                'Current': 0xFF})
VOLUMES_REV = {v: k for k, v in VOLUMES.items()}

MIN_VOL_PRESET = {'Preset': 0x30,
                  'Lowest Limit': 0x31}
MIN_VOL_PRESET_REV = {v: k for k, v in MIN_VOL_PRESET.items()}

SUBLCD = ['Zone Number', 'CH/GID Number', 'OSD List Number']
CLOCKFMT = ['12H', '24H']
DATEFMT = ['Day/Month', 'Month/Day']
MICSENSE = ['On']
ONLY_MOBILE_SETTINGS = ['power_switch_memory', 'off_hook_decode',
                        'ignition_sense', 'mvp', 'it', 'ignition_mode']


POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5),
                chirp_common.PowerLevel("High", watts=50)]


def set_choice(setting, obj, key, choices, default='Off'):
    settingstr = str(setting.value)
    if settingstr == default:
        val = 0xFF
    else:
        val = choices.index(settingstr) + 0x30
    setattr(obj, key, val)


def get_choice(obj, key, choices, default='Off'):
    val = getattr(obj, key)
    if val == 0xFF:
        return default
    else:
        return choices[val - 0x30]


def make_frame(cmd, addr, data=b""):
    return struct.pack(">BH", ord(cmd), addr) + data


def send(radio, frame):
    # LOG.debug("%04i P>R:\n%s" % (len(frame), util.hexprint(frame)))
    radio.pipe.write(frame)


def do_ident(radio):
    radio.pipe.baudrate = 9600
    radio.pipe.stopbits = 2
    radio.pipe.timeout = 1
    send(radio, b'PROGRAM')
    ack = radio.pipe.read(1)
    LOG.debug('Read %r from radio' % ack)
    if ack != b'\x16':
        raise errors.RadioError('Radio refused hi-speed program mode')
    radio.pipe.baudrate = 19200
    ack = radio.pipe.read(1)
    if ack != b'\x06':
        raise errors.RadioError('Radio refused program mode')
    radio.pipe.write(b'\x02')
    ident = radio.pipe.read(8)
    LOG.debug('Radio ident is %r' % ident)
    radio.pipe.write(b'\x06')
    ack = radio.pipe.read(1)
    if ack != b'\x06':
        raise errors.RadioError('Radio refused program mode')
    if ident[:6] not in (radio._model,):
        model = ident[:5].decode()
        variants = {b'\x06': 'K, K1, K3 (450-520MHz)',
                    b'\x07': 'K2, K4 (400-470MHz)'}
        if model == 'P3180':
            model += ' ' + variants.get(ident[5], '(Unknown)')
        raise errors.RadioError('Unsupported radio model %s' % model)


def checksum_data(data):
    _chksum = 0
    for byte in data:
        _chksum = (_chksum + byte) & 0xFF
    return _chksum


def do_download(radio):
    do_ident(radio)

    data = bytes()

    def status():
        status = chirp_common.Status()
        status.cur = len(data)
        status.max = radio._memsize
        status.msg = "Cloning from radio"
        radio.status_fn(status)
        LOG.debug('Radio address 0x%04x' % len(data))

    # Addresses 0x0000-0xBF00 pulled by block number (divide by 0x100)
    for block in range(0, 0xBF + 1):
        send(radio, make_frame('R', block))
        cmd = radio.pipe.read(1)
        chunk = b''
        if cmd == b'Z':
            data += bytes(b'\xff' * 256)
            LOG.debug('Radio reports empty block %02x' % block)
        elif cmd == b'W':
            chunk = bytes(radio.pipe.read(256))
            if len(chunk) != 256:
                LOG.error('Received %i for block %02x' % (len(chunk), block))
                raise errors.RadioError('Radio did not send block')
            data += chunk
        else:
            LOG.error('Radio sent %r (%02x), expected W(0x57)' % (cmd,
                                                                  chr(cmd)))
            raise errors.RadioError('Radio sent unexpected response')

        LOG.debug('Read block index %02x' % block)
        status()

        chksum = radio.pipe.read(1)
        if len(chksum) != 1:
            LOG.error('Checksum was %r' % chksum)
            raise errors.RadioError('Radio sent invalid checksum')
        _chksum = checksum_data(chunk)

        if chunk and _chksum != ord(chksum):
            LOG.error(
                'Checksum failed for %i byte block 0x%02x: %02x != %02x' % (
                    len(chunk), block, _chksum, ord(chksum)))
            raise errors.RadioError('Checksum failure while reading block. '
                                    'Check serial cable.')

        radio.pipe.write(b'\x06')
        if radio.pipe.read(1) != b'\x06':
            raise errors.RadioError('Post-block exchange failed')

    # Addresses 0xC000 - 0xD1F0 pulled by address
    for block in range(0x0100, 0x1200, 0x40):
        send(radio, make_frame('S', block, b'\x40'))
        x = radio.pipe.read(1)
        if x != b'X':
            raise errors.RadioError('Radio did not send block')
        chunk = radio.pipe.read(0x40)
        data += chunk

        LOG.debug('Read memory address %04x' % block)
        status()

        radio.pipe.write(b'\x06')
        if radio.pipe.read(1) != b'\x06':
            raise errors.RadioError('Post-block exchange failed')

    radio.pipe.write(b'E')
    if radio.pipe.read(1) != b'\x06':
        raise errors.RadioError('Radio failed to acknowledge completion')

    LOG.debug('Read %i bytes total' % len(data))
    return data


def do_upload(radio):
    do_ident(radio)

    def status(addr):
        status = chirp_common.Status()
        status.cur = addr
        status.max = radio._memsize
        status.msg = "Cloning to radio"
        radio.status_fn(status)

    for block in range(0, 0xBF + 1):
        addr = block * 0x100
        chunk = bytes(radio._mmap[addr:addr + 0x100])
        if all(byte == b'\xff' for byte in chunk):
            LOG.debug('Sending zero block %i, range 0x%04x' % (block, addr))
            send(radio, make_frame('Z', block, b'\xFF'))
        else:
            checksum = checksum_data(chunk)
            send(radio, make_frame('W', block, chunk + chr(checksum)))

        ack = radio.pipe.read(1)
        if ack != b'\x06':
            LOG.error('Radio refused block 0x%02x with %r' % (block, ack))
            raise errors.RadioError('Radio refused data block')

        status(addr)

    addr_base = 0xC000
    for addr in range(addr_base, radio._memsize, 0x40):
        block_addr = addr - addr_base + 0x0100
        chunk = radio._mmap[addr:addr + 0x40]
        send(radio, make_frame('X', block_addr, b'\x40' + chunk))

        ack = radio.pipe.read(1)
        if ack != b'\x06':
            LOG.error('Radio refused address 0x%02x with %r' % (block_addr,
                                                                ack))
            raise errors.RadioError('Radio refused data block')

        status(addr)

    radio.pipe.write(b'E')
    if radio.pipe.read(1) != b'\x06':
        raise errors.RadioError('Radio failed to acknowledge completion')


def reset(self):
    try:
        self.pipe.baudrate = 9600
        self.pipe.write(b'E')
        time.sleep(0.5)
        self.pipe.baudrate = 19200
        self.pipe.write(b'E')
    except Exception:
        LOG.error('Unable to send reset sequence')


class KenwoodTKx180Radio(chirp_common.CloneModeRadio):
    """Kenwood TK-x180"""
    VENDOR = 'Kenwood'
    MODEL = 'TK-x180'
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = False

    _system_start = 0x0B00
    _memsize = 0xD100

    def __init__(self, *a, **k):
        self._zones = []
        chirp_common.CloneModeRadio.__init__(self, *a, **k)

    def sync_in(self):
        try:
            data = do_download(self)
            self._mmap = memmap.MemoryMapBytes(data)
        except errors.RadioError:
            reset(self)
            raise
        except Exception as e:
            reset(self)
            LOG.exception('General failure')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except Exception as e:
            reset(self)
            LOG.exception('General failure')
            raise errors.RadioError('Failed to upload to radio: %s' % e)

    @property
    def is_portable(self):
        return self._model.startswith(b'P')

    def probe_layout(self):
        start_addrs = []
        tmp_format = '#seekto 0x0A00; ul16 zone_starts[128];'
        mem = bitwise.parse(tmp_format, self._mmap)
        zone_format = """struct zoneinfo {
        u8 number;
        u8 zonetype;
        u8 unknown1[2];
        u8 count;
        char name[12];
        u8 unknown2[15];
        };"""

        zone_addresses = []
        for i in range(0, 128):
            if mem.zone_starts[i] == 0xFFFF:
                break
            zone_addresses.append(mem.zone_starts[i])
            zone_format += '#seekto 0x%x; struct zoneinfo zone%i;' % (
                mem.zone_starts[i], i)

        zoneinfo = bitwise.parse(zone_format, self._mmap)
        zones = []
        for i, addr in enumerate(zone_addresses):
            zone = getattr(zoneinfo, 'zone%i' % i)
            if zone.zonetype != 0x31:
                LOG.error('Zone %i is type 0x%02x; '
                          'I only support 0x31 (conventional)')
                raise errors.RadioError(
                    'Unsupported non-conventional zone found in radio; '
                    'Refusing to load to safeguard your data!')
            zones.append((addr, zone.count))

        LOG.debug('Zones: %s' % zones)
        return zones

    def process_mmap(self):
        self._zones = self.probe_layout()

        mem_format = HEADER_FORMAT
        for index, (addr, count) in enumerate(self._zones):
            mem_format += '\n\n' + (
                SYSTEM_MEM_FORMAT % {
                    'addr': addr,
                    'count': max(count, 2),   # bitwise bug, one-element array
                    'index': index})

        self._memobj = bitwise.parse(mem_format, self._mmap)

    def expand_mmap(self, zone_sizes):
        """Remap memory into zones of the specified sizes, copying things
        around to keep the contents, as appropriate."""
        old_zones = self._zones
        old_memobj = self._memobj

        self._mmap = memmap.MemoryMapBytes(bytes(self._mmap.get_packed()))

        new_format = HEADER_FORMAT
        addr = self._system_start
        self._zones = []
        for index, count in enumerate(zone_sizes):
            new_format += SYSTEM_MEM_FORMAT % {
                'addr': addr,
                'count': max(count, 2),  # bitwise bug
                'index': index}
            self._zones.append((addr, count))
            addr += 0x20 + (count * 0x30)

        self._memobj = bitwise.parse(new_format, self._mmap)

        # Set all known zone addresses and clear the rest
        for index in range(0, 128):
            try:
                self._memobj.zone_starts[index] = self._zones[index][0]
            except IndexError:
                self._memobj.zone_starts[index] = 0xFFFF

        for zone_number, count in enumerate(zone_sizes):
            dest_zone = getattr(self._memobj, 'zone%i' % zone_number)
            dest = dest_zone.memories
            dest_zoneinfo = dest_zone.zoneinfo

            if zone_number < len(old_zones):
                LOG.debug('Copying existing zone %i' % zone_number)
                _, old_count = old_zones[zone_number]
                source_zone = getattr(old_memobj, 'zone%i' % zone_number)
                source = source_zone.memories
                source_zoneinfo = source_zone.zoneinfo

                if old_count != count:
                    LOG.debug('Zone %i going from %i to %i' % (zone_number,
                                                               old_count,
                                                               count))

                # Copy the zone record from the source, but then update
                # the count
                dest_zoneinfo.set_raw(source_zoneinfo.get_raw())
                dest_zoneinfo.count = count

                source_i = 0
                for dest_i in range(0, min(count, old_count)):
                    dest[dest_i].set_raw(source[dest_i].get_raw())
            else:
                LOG.debug('New zone %i' % zone_number)
                dest_zone.zoneinfo.number = zone_number + 1
                dest_zone.zoneinfo.zonetype = 0x31
                dest_zone.zoneinfo.count = count
                dest_zone.zoneinfo.name = (
                    'Zone %i' % (zone_number + 1)).ljust(12)

    def shuffle_zone(self):
        """Sort the memories in the zone according to logical channel number"""
        # FIXME: Move this to the zone
        raw_memories = self.raw_memories
        memories = [(i, raw_memories[i].number)
                    for i in range(0, self.raw_zoneinfo.count)]
        current = memories[:]
        memories.sort(key=lambda t: t[1])
        if current == memories:
            LOG.debug('Shuffle not required')
            return
        raw_data = [raw_memories[i].get_raw() for i, n in memories]
        for i, raw_mem in enumerate(raw_data):
            raw_memories[i].set_raw(raw_mem)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = ('This radio is zone-based, which is different from how '
                   'most radios work (that CHIRP supports). The zone count '
                   'can be adjusted in the Settings tab, but you must save '
                   'and re-load the file after changing that value in order '
                   'to be able to add/edit memories there.')
        rp.experimental = ('This driver is very experimental. Every attempt '
                           'has been made to be overly pedantic to avoid '
                           'destroying data. However, you should use caution, '
                           'maintain backups, and proceed at your own risk.')
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_settings = True
        rf.has_bank = False
        rf.has_sub_devices = True
        rf.has_rx_dtcs = True
        rf.can_odd_split = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS', 'Tone->DTCS',
                                'DTCS->Tone', '->Tone', 'DTCS->DTCS']
        rf.valid_bands = self.VALID_BANDS
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 12.5, 10.0, 15.0, 20.0,
                                 25.0, 50.0, 100.0]
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_name_length = 12
        rf.valid_characters = ('ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                               'abcdefghijklmnopqrstuvwxyz'
                               '0123456789'
                               '!"#$%&\'()~+-,./:;<=>?@[\\]^`{}*| ')
        rf.memory_bounds = (1, 512)
        return rf

    @property
    def raw_zone(self):
        return getattr(self._memobj, 'zone%i' % self._zone)

    @property
    def raw_zoneinfo(self):
        return self.raw_zone.zoneinfo

    @property
    def raw_memories(self):
        return self.raw_zone.memories

    @property
    def max_mem(self):
        return self.raw_memories[self.raw_zoneinfo.count].number

    def _get_raw_memory(self, number):
        for i in range(0, self.raw_zoneinfo.count):
            if self.raw_memories[i].number == number:
                return self.raw_memories[i]
        return None

    def get_raw_memory(self, number):
        return repr(self._get_raw_memory(number))

    @staticmethod
    def _decode_tone(toneval):
        # DCS examples:
        # D024N - 2814 - 0010 1000 0001 0100
        #                  ^--DCS
        # D024I - A814 - 1010 1000 0001 0100
        #                ^----inverted
        # D754I - A9EC - 1010 1001 1110 1100
        #    code in octal-------^^^^^^^^^^^

        pol = toneval & 0x8000 and 'R' or 'N'
        if toneval == 0xFFFF:
            return '', None, None
        elif toneval & 0x2000:
            # DTCS
            code = int('%o' % (toneval & 0x1FF))
            return 'DTCS', code, pol
        else:
            return 'Tone', toneval / 10.0, None

    @staticmethod
    def _encode_tone(mode, val, pol):
        if not mode:
            return 0xFFFF
        elif mode == 'Tone':
            return int(val * 10)
        elif mode == 'DTCS':
            code = int('%i' % val, 8)
            code |= 0x2800
            if pol == 'R':
                code |= 0x8000
            return code
        else:
            raise errors.RadioError('Unsupported tone mode %r' % mode)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._get_raw_memory(number)
        if _mem is None:
            mem.empty = True
            return mem

        mem.name = str(_mem.name).rstrip('\x00')
        mem.freq = int(_mem.rx_freq) * 10
        chirp_common.split_tone_decode(mem,
                                       self._decode_tone(_mem.tx_tone),
                                       self._decode_tone(_mem.rx_tone))
        if _mem.wide:
            mem.mode = 'FM'
        else:
            mem.mode = 'NFM'

        mem.power = POWER_LEVELS[_mem.highpower]

        offset = (int(_mem.tx_freq) - int(_mem.rx_freq)) * 10
        if offset == 0:
            mem.duplex = ''
        elif abs(offset) < 10000000:
            mem.duplex = offset < 0 and '-' or '+'
            mem.offset = abs(offset)
        else:
            mem.duplex = 'split'
            mem.offset = int(_mem.tx_freq) * 10

        skipbyte = self._memobj.skipflags[(mem.number - 1) // 8]
        skipbit = skipbyte & (1 << (mem.number - 1) % 8)
        mem.skip = skipbit and 'S' or ''

        return mem

    def set_memory(self, mem):
        _mem = self._get_raw_memory(mem.number)
        if _mem is None:
            LOG.debug('Need to expand zone %i' % self._zone)

            # Calculate the new zone sizes and remap memory
            new_zones = [x[1] for x in self._parent._zones]
            new_zones[self._zone] = new_zones[self._zone] + 1
            self._parent.expand_mmap(new_zones)

            # Assign the new memory (at the end) to the desired
            # number
            _mem = self.raw_memories[self.raw_zoneinfo.count - 1]
            _mem.number = mem.number

            # Sort the memory into place
            self.shuffle_zone()

            # Now find it in the right spot
            _mem = self._get_raw_memory(mem.number)
            if _mem is None:
                raise errors.RadioError('Internal error after '
                                        'memory allocation')

            # Default values for unknown things
            _mem.unknown1[0] = 0x36
            _mem.unknown1[1] = 0x36
            _mem.unknown2 = [0xFF for i in range(0, 19)]
            _mem.unknown3_1 = 0xF
            _mem.unknown3_2 = 0x1
            _mem.unknown3_3 = 0x0
            _mem.unknown4 = 0xFF

        if mem.empty:
            LOG.debug('Need to shrink zone %i' % self._zone)
            # Make the memory sort to the end, and sort the zone
            _mem.number = 0xFF
            self.shuffle_zone()

            # Calculate the new zone sizes and remap memory
            new_zones = [x[1] for x in self._parent._zones]
            new_zones[self._zone] = new_zones[self._zone] - 1
            self._parent.expand_mmap(new_zones)
            return

        _mem.name = mem.name[:12].encode().rstrip().ljust(12, b'\x00')
        _mem.rx_freq = mem.freq // 10

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _mem.tx_tone = self._encode_tone(*txtone)
        _mem.rx_tone = self._encode_tone(*rxtone)

        _mem.wide = mem.mode == 'FM'
        _mem.highpower = mem.power == POWER_LEVELS[1]

        if mem.duplex == '':
            _mem.tx_freq = mem.freq // 10
        elif mem.duplex == 'split':
            _mem.tx_freq = mem.offset // 10
        elif mem.duplex == 'off':
            _mem.tx_freq.set_raw(b'\xff\xff\xff\xff')
        elif mem.duplex == '-':
            _mem.tx_freq = (mem.freq - mem.offset) // 10
        elif mem.duplex == '+':
            _mem.tx_freq = (mem.freq + mem.offset) // 10
        else:
            raise errors.RadioError('Unsupported duplex mode %r' % mem.duplex)

        skipbyte = self._memobj.skipflags[(mem.number - 1) // 8]
        if mem.skip == 'S':
            skipbyte |= (1 << (mem.number - 1) % 8)
        else:
            skipbyte &= ~(1 << (mem.number - 1) % 8)

    def _pure_choice_setting(self, settings_key, name, choices, default='Off'):
        if default is not None:
            ui_choices = [default] + choices
        else:
            ui_choices = choices
        s = RadioSetting(
            settings_key, name,
            RadioSettingValueList(
                ui_choices,
                get_choice(self._memobj.settings, settings_key,
                           choices, default)))
        s.set_apply_callback(set_choice, self._memobj.settings,
                             settings_key, choices, default)
        return s

    def _inverted_flag_setting(self, key, name, obj=None):
        if obj is None:
            obj = self._memobj.settings

        def apply_inverted(setting, key):
            setattr(obj, key, not int(setting.value))

        v = not getattr(obj, key)
        s = RadioSetting(
                key, name,
                RadioSettingValueBoolean(v))
        s.set_apply_callback(apply_inverted, key)
        return s

    def _get_common1(self):
        settings = self._memobj.settings
        common1 = RadioSettingGroup('common1', 'Common 1')

        common1.append(self._pure_choice_setting('sublcd',
                                                 'Sub LCD Display',
                                                 SUBLCD,
                                                 default='None'))

        def apply_clockfmt(setting):
            settings.clockfmt = CLOCKFMT.index(str(setting.value))

        clockfmt = RadioSetting(
            'clockfmt', 'Clock Format',
            RadioSettingValueList(CLOCKFMT,
                                  CLOCKFMT[settings.clockfmt]))
        clockfmt.set_apply_callback(apply_clockfmt)
        common1.append(clockfmt)

        def apply_datefmt(setting):
            settings.datefmt = DATEFMT.index(str(setting.value))

        datefmt = RadioSetting(
            'datefmt', 'Date Format',
            RadioSettingValueList(DATEFMT,
                                  DATEFMT[settings.datefmt]))
        datefmt.set_apply_callback(apply_datefmt)
        common1.append(datefmt)

        common1.append(self._pure_choice_setting('micsense',
                                                 'Mic Sense High',
                                                 MICSENSE))

        def apply_modereset(setting):
            val = int(setting.value)
            if val == 0:
                val = 0xFFFF
            settings.modereset = val

        _modereset = int(settings.modereset)
        if _modereset == 0xFFFF:
            _modereset = 0
        modereset = RadioSetting(
            'modereset', 'Mode Reset Timer',
            RadioSettingValueInteger(0, 300, _modereset))
        modereset.set_apply_callback(apply_modereset)
        common1.append(modereset)

        inverted_flags = [('power_switch_memory', 'Power Switch Memory'),
                          ('scrambler_memory', 'Scrambler Memory'),
                          ('off_hook_decode', 'Off-Hook Decode'),
                          ('ssi', 'Signal Strength Indicator'),
                          ('ignition_sense', 'Ingnition Sense')]
        for key, name in inverted_flags:
            if self.is_portable and key in ONLY_MOBILE_SETTINGS:
                # Skip settings that are not valid for portables
                continue
            common1.append(self._inverted_flag_setting(key, name))

        if not self.is_portable and 'ignition_mode' in ONLY_MOBILE_SETTINGS:
            common1.append(self._pure_choice_setting('ignition_mode',
                                                     'Ignition Mode',
                                                     ['Ignition & SW',
                                                      'Ignition Only'],
                                                     None))

        def apply_it(setting):
            settings.ignition_time = int(setting.value) / 600

        _it = int(settings.ignition_time) * 600
        it = RadioSetting(
            'it', 'Ignition Timer (s)',
            RadioSettingValueInteger(10, 28800, _it))
        it.set_apply_callback(apply_it)
        if not self.is_portable and 'it' in ONLY_MOBILE_SETTINGS:
            common1.append(it)

        return common1

    def _get_common2(self):
        settings = self._memobj.settings
        common2 = RadioSettingGroup('common2', 'Common 2')

        def apply_ponmsgtext(setting):
            settings.pon_msgtext = (
                str(setting.value)[:12].strip().ljust(12, '\x00'))

        common2.append(
            self._pure_choice_setting('pon_msgtype', 'Power On Message Type',
                                      STARTUP_MODES))

        _text = str(settings.pon_msgtext).rstrip('\x00')
        text = RadioSetting('settings.pon_msgtext',
                            'Power On Text',
                            RadioSettingValueString(
                                0, 12, _text))
        text.set_apply_callback(apply_ponmsgtext)
        common2.append(text)

        def apply_volume(setting, key):
            setattr(settings, key, VOLUMES[str(setting.value)])

        volumes = {'poweron_tone': 'Power-on Tone',
                   'control_tone': 'Control Tone',
                   'warning_tone': 'Warning Tone',
                   'alert_tone': 'Alert Tone',
                   'sidetone': 'Sidetone',
                   'locator_tone': 'Locator Tone'}
        for value, name in volumes.items():
            setting = getattr(settings, value)
            volume = RadioSetting('settings.%s' % value, name,
                                  RadioSettingValueList(
                                      VOLUMES.keys(),
                                      VOLUMES_REV.get(int(setting), 0)))
            volume.set_apply_callback(apply_volume, value)
            common2.append(volume)

        def apply_vol_level(setting, key):
            setattr(settings, key, int(setting.value))

        levels = {'lo_volume': 'Low Volume Level (Fixed Volume)',
                  'hi_volume': 'High Volume Level (Fixed Volume)',
                  'min_volume': 'Minimum Audio Volume',
                  'max_volume': 'Maximum Audio Volume'}
        for value, name in levels.items():
            setting = getattr(settings, value)
            if 'Audio' in name:
                minimum = 0
            else:
                minimum = 1
            volume = RadioSetting(
                'settings.%s' % value, name,
                RadioSettingValueInteger(minimum, 31, int(setting)))
            volume.set_apply_callback(apply_vol_level, value)
            common2.append(volume)

        def apply_vo(setting):
            val = int(setting.value)
            if val < 0:
                val = abs(val) | 0x80
            settings.tone_volume_offset = val

        _voloffset = int(settings.tone_volume_offset)
        if _voloffset & 0x80:
            _voloffset = abs(_voloffset & 0x7F) * -1
        voloffset = RadioSetting(
            'tvo', 'Tone Volume Offset',
            RadioSettingValueInteger(
                -5, 5,
                _voloffset))
        voloffset.set_apply_callback(apply_vo)
        common2.append(voloffset)

        def apply_mvp(setting):
            settings.min_vol_preset = MIN_VOL_PRESET[str(setting.value)]

        _volpreset = int(settings.min_vol_preset)
        volpreset = RadioSetting(
            'mvp', 'Minimum Volume Type',
            RadioSettingValueList(MIN_VOL_PRESET.keys(),
                                  MIN_VOL_PRESET_REV[_volpreset]))
        volpreset.set_apply_callback(apply_mvp)
        if not self.is_portable and 'mvp' in ONLY_MOBILE_SETTINGS:
            common2.append(volpreset)

        return common2

    def _get_conventional(self):
        settings = self._memobj.settings

        conv = RadioSettingGroup('conv', 'Conventional')
        inverted_flags = [('busy_led', 'Busy LED'),
                          ('ost_memory', 'OST Status Memory'),
                          ('tone_off', 'Tone Off'),
                          ('ptt_release', 'PTT Release tone'),
                          ('ptt_proceed', 'PTT Proceed Tone')]
        for key, name in inverted_flags:
            conv.append(self._inverted_flag_setting(key, name))

        def apply_pttt(setting):
            settings.ptt_timer = int(setting.value)

        pttt = RadioSetting(
            'pttt', 'PTT Proceed Tone Timer (ms)',
            RadioSettingValueInteger(0, 6000, int(settings.ptt_timer)))
        pttt.set_apply_callback(apply_pttt)
        conv.append(pttt)

        self._get_ost(conv)

        return conv

    def _get_zones(self):
        zones = RadioSettingGroup('zones', 'Zones')

        zone_count = RadioSetting('_zonecount',
                                  'Number of Zones',
                                  RadioSettingValueInteger(
                                      1, 128, len(self._zones)))
        zone_count.set_doc('Number of zones in the radio. '
                           'Requires a save and re-load of the '
                           'file to take effect. Reducing this number '
                           'will DELETE memories in affected zones!')
        zones.append(zone_count)

        for i in range(len(self._zones)):
            zone = RadioSettingGroup('zone%i' % i, 'Zone %i' % (i + 1))

            _zone = getattr(self._memobj, 'zone%i' % i).zoneinfo
            _name = str(_zone.name).rstrip('\x00')
            name = RadioSetting('name%i' % i, 'Name',
                                RadioSettingValueString(0, 12, _name))
            zone.append(name)

            def apply_timer(setting, key):
                val = int(setting.value)
                if val == 0:
                    val = 0xFFFF
                setattr(_zone, key, val)

            def collapse(val):
                val = int(val)
                if val == 0xFFFF:
                    val = 0
                return val

            timer = RadioSetting(
                'timeout', 'Time-out Timer',
                RadioSettingValueInteger(15, 1200, collapse(_zone.timeout)))
            timer.set_apply_callback(apply_timer, 'timeout')
            zone.append(timer)

            timer = RadioSetting(
                'tot_alert', 'TOT Pre-Alert',
                RadioSettingValueInteger(0, 10, collapse(_zone.tot_alert)))
            timer.set_apply_callback(apply_timer, 'tot_alert')
            zone.append(timer)

            timer = RadioSetting(
                'tot_rekey', 'TOT Re-Key Time',
                RadioSettingValueInteger(0, 60, collapse(_zone.tot_rekey)))
            timer.set_apply_callback(apply_timer, 'tot_rekey')
            zone.append(timer)

            timer = RadioSetting(
                'tot_reset', 'TOT Reset Time',
                RadioSettingValueInteger(0, 15, collapse(_zone.tot_reset)))
            timer.set_apply_callback(apply_timer, 'tot_reset')
            zone.append(timer)

            zone.append(self._inverted_flag_setting(
                'bcl_override', 'BCL Override',
                _zone))

            zones.append(zone)

        return zones

    def _get_ost(self, parent):
        tones = chirp_common.TONES[:]

        def apply_tone(setting, index, which):
            if str(setting.value) == 'Off':
                val = 0xFFFF
            else:
                val = int(float(str(setting.value)) * 10)
            setattr(self._memobj.ost_tones[index], '%stone' % which, val)

        def _tones():
            return ['Off'] + [str(x) for x in tones]

        for i in range(0, 40):
            _ost = self._memobj.ost_tones[i]
            ost = RadioSettingGroup('ost%i' % i,
                                    'OST %i' % (i + 1))

            cur = str(_ost.name).rstrip('\x00')
            name = RadioSetting('name%i' % i, 'Name',
                                RadioSettingValueString(0, 12, cur))
            ost.append(name)

            if _ost.rxtone == 0xFFFF:
                cur = 'Off'
            else:
                cur = round(int(_ost.rxtone) / 10.0, 1)
                if cur not in tones:
                    LOG.debug('Non-standard OST rx tone %i %s' % (i, cur))
                    tones.append(cur)
                    tones.sort()
            rx = RadioSetting('rxtone%i' % i, 'RX Tone',
                              RadioSettingValueList(_tones(),
                                                    str(cur)))
            rx.set_apply_callback(apply_tone, i, 'rx')
            ost.append(rx)

            if _ost.txtone == 0xFFFF:
                cur = 'Off'
            else:
                cur = round(int(_ost.txtone) / 10.0, 1)
                if cur not in tones:
                    LOG.debug('Non-standard OST tx tone %i %s' % (i, cur))
                    tones.append(cur)
                    tones.sort()
            tx = RadioSetting('txtone%i' % i, 'TX Tone',
                              RadioSettingValueList(_tones(),
                                                    str(cur)))
            tx.set_apply_callback(apply_tone, i, 'tx')
            ost.append(tx)

            parent.append(ost)

    def get_settings(self):
        settings = self._memobj.settings

        zones = self._get_zones()
        common1 = self._get_common1()
        common2 = self._get_common2()
        conv = self._get_conventional()
        top = RadioSettings(zones, common1, common2, conv)
        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            elif element.get_name() == '_zonecount':
                new_zone_count = int(element.value)
                zone_sizes = [x[1] for x in self._zones[:new_zone_count]]
                if len(self._zones) > new_zone_count:
                    self.expand_mmap(zone_sizes[:new_zone_count])
                elif len(self._zones) < new_zone_count:
                    self.expand_mmap(zone_sizes + (
                        [0] * (new_zone_count - len(self._zones))))
            elif element.has_apply_callback():
                element.run_apply_callback()

    def get_sub_devices(self):
        zones = []
        for i, _ in enumerate(self._zones):
            zone = getattr(self._memobj, 'zone%i' % i)

            class _Zone(KenwoodTKx180RadioZone):
                VENDOR = self.VENDOR
                MODEL = self.MODEL
                VALID_BANDS = self.VALID_BANDS
                VARIANT = 'Zone %s' % (
                    str(zone.zoneinfo.name).rstrip('\x00').rstrip())
                _model = self._model

            zones.append(_Zone(self, i))
        return zones


class KenwoodTKx180RadioZone(KenwoodTKx180Radio):
    _zone = None

    def __init__(self, parent, zone=0):
        if isinstance(parent, KenwoodTKx180Radio):
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

    def load_mmap(self, filename):
        self._parent.load_mmap(filename)

    def get_features(self):
        rf = KenwoodTKx180Radio.get_features(self)
        rf.has_sub_devices = False
        rf.memory_bounds = (1, 250)
        return rf

    def get_sub_devices(self):
        return []


if has_future:
    @directory.register
    class KenwoodTK7180Radio(KenwoodTKx180Radio):
        MODEL = 'TK-7180'
        VALID_BANDS = [(136000000, 174000000)]
        _model = b'M7180\x04'

    @directory.register
    class KenwoodTK8180Radio(KenwoodTKx180Radio):
        MODEL = 'TK-8180'
        VALID_BANDS = [(400000000, 520000000)]
        _model = b'M8180\x06'

    @directory.register
    class KenwoodTK2180Radio(KenwoodTKx180Radio):
        MODEL = 'TK-2180'
        VALID_BANDS = [(136000000, 174000000)]
        _model = b'P2180\x04'

    # K1,K3 are technically 450-470 (K3 == keypad)
    @directory.register
    class KenwoodTK3180K1Radio(KenwoodTKx180Radio):
        MODEL = 'TK-3180K'
        VALID_BANDS = [(400000000, 520000000)]
        _model = b'P3180\x06'

    # K2,K4 are technically 400-470 (K4 == keypad)
    @directory.register
    class KenwoodTK3180K2Radio(KenwoodTKx180Radio):
        MODEL = 'TK-3180K2'
        VALID_BANDS = [(400000000, 520000000)]
        _model = b'P3180\x07'
