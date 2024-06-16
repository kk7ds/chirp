# Copyright 2023 Dan Smith <chirp@f.danplanet.com>
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

import functools
import logging
import struct

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp.drivers import tk8180
from chirp import errors
from chirp import memmap
from chirp import settings
from chirp import util

LOG = logging.getLogger(__name__)

mem_format = """
// Bitmask for zone in use
#seekto 0x0020;
u8 zoneflag[16];

// (identical?) bitmask for index spot in use
#seekto 0x0030;
u8 flag1[16];
#seekto 0x0050;
u8 flag2[16];

// This is filled in order, regardless of the ordering of the memories or
// their positions
#seekto 0x00E0;
struct {
    u8 zone;   // Zone number
    u8 memory; // Channel number
    u8 zero;
    u8 slot;  // Index into the memory array
} index[128];

#seekto 0x02E0;
struct {
    u8 used:1,
       unknown1:4, // Always 0x71?
       zoneaudiomode:2, // 00=QT/DQT 01=QT/DQT+OptSig 02 QT/DQTorOptSig
       optsigdecode:1;  // 0=Carrier 1=QT/DQT
    u8 count; // Number of memories in the zone
} zoneinfo[128];

#seekto 0x03E0;
struct {
    u8 number;
    u8 zone;
    lbcd rx_freq[4];
    lbcd tx_freq[4];
    u8 unknown1[2];
    ul16 rxtone;
    ul16 txtone;
    // BCL 0:no 1: carrier
    u8 unknown2_0:4,
       bcl:2, // 0:no 1:carrier 2:tone 3:optsig
       unknown2_01:1,
       wide:1;
    u8 beatshift:1,
       unknown2_1:1,
       highpower:1,
       scanadd:1,
       unknown2_2:4;
    u8 unknown2_3:6,
       pttid:2; // 0:off 1:BOT 2:EOT 3:Both
    char name[8];
    u8 unknown3_0:7,
       compander:1;
    u8 unknown3_1:7,
       pttidmute:1;
    u8 optsig:3, // 0:none 1:DTMF 2:2tone1 3:2tone2 4:2tone3 5:FleetSync
       unknown4:5;
    u8 unknown5[2];
} memories[128];

#seekto 0x14F0;
struct {
    char message1[32];
    char message2[32];
} messages;

#seekto 0x1730;
struct {
  char model[5];
  u8 variant;
} model;

// 28=volup 2A=None 15=2-tone 8=AUX 16=Call1 17=Call2 13=ChDn 12=ChUp
// 0B=DisplayCh 09=HornAlert 03=KeyLock 14=Brightness 02=Monitor 25=MonMom
// 0C=OST 19=PA 1A=SquelchLevel 05=Scan 06=ScanAdd 0A=Scrambler 18=Selcall
// 27=SendGPS 04=TA 28=VolUp 29=VolDn 00=ZoneUp 24=SqlOff 26=SqlOffMom
// 1C=Status 1D=SelCall+Status 01=ZoneDn
#seekto 0x1820;
struct {
  u8 skey;
  u8 akey;
  u8 bkey;
  u8 ckey;
  u8 triangle;
  u8 rightup;
  u8 rightdn;
  u8 leftup;
  u8 leftdn;
} keys;
"""

_KEYS = [
    'Zone Up',
    'Zone Down',
    'Monitor',
    'Key Lock',
    'Talk Around',
    'Scan',
    'Scan Add',
    '?',
    'AUX',
    'Horn Alert',
    'Scrambler',
    'Display Character',
    'OST',
    '?',  # 0D
    '?',  # 0E
    '?',  # 0F
    '?',  # 10
    '?',  # 11
    'Channel Up',
    'Channel Down',
    'Brightness',
    '2-Tone',
    'Call 1',
    'Call 2',
    'Selcall',
    'Public Address',
    'Squelch Level',
    '?',
    'Status',
    'Selcall+Status',
    '?',  # 1E
    '?',  # 1F
    '?',  # 20
    '?',  # 21
    '?',  # 22
    '?',  # 23
    'Squelch Off',
    'Monitor Momentary',
    'Squelch Off Momentary',
    'Send the GPS',
    'Volume Up',
    'Volume Down',
    'None',
    ]

KEYS = {i: key for i, key in enumerate(_KEYS)
        if not key.startswith('?')}

KEY_NAMES = {
    'A': 'akey',
    'B': 'bkey',
    'C': 'ckey',
    'S': 'skey',
    'Triangle': 'triangle',
    'Right Up': 'rightup',
    'Right Down': 'rightdn',
    'Left Up': 'leftup',
    'Left Down': 'leftdn',
}

POWER_LEVELS = [chirp_common.PowerLevel('Low', watts=25),
                chirp_common.PowerLevel('High', watts=50)]


def ends_program(fn):
    @functools.wraps(fn)
    def wrapper(radio):
        try:
            return fn(radio)
        finally:
            radio.pipe.write(b'E')
            ack = radio.pipe.read(1)
            if ack != b'\x06':
                LOG.warning('Radio did not ACK exiting program mode')

    return wrapper


@ends_program
def do_download(radio):
    tk8180.do_ident(radio)

    data = b''

    def status():
        status = chirp_common.Status()
        status.cur = len(data)
        status.max = radio._memsize
        status.msg = 'Cloning from radio'
        radio.status_fn(status)
        LOG.debug('Radio address 0x%04x' % len(data))

    # This seems to be "give me the whole thing"
    LOG.debug('Requesting clone image')
    radio.pipe.write(b'hRDA')
    ack = radio.pipe.read(1)
    if ack != b'\x06':
        LOG.error('No ack from radio; got %r' % ack)
        raise errors.RadioError('Radio refused to send memory')

    while len(data) < radio._memsize:
        cmd = radio.pipe.read(1)
        if cmd == b'E':
            LOG.debug('Got clone end')
            break
        elif cmd not in b'ZW':
            LOG.error('Unsupported command %r' % cmd)
            raise errors.RadioError('Radio sent unknown message')

        hdr = radio.pipe.read(3)
        addr, length = struct.unpack('>HB', hdr)
        LOG.debug('Radio: %r %04x %02x' % (cmd, addr, length))
        if cmd == b'Z':
            data += b'\xFF' * length
        elif cmd == b'W':
            block = radio.pipe.read(length)
            data += block
        radio.pipe.write(b'\x06')
        status()

    return memmap.MemoryMapBytes(data)


@ends_program
def do_upload(radio):
    tk8180.do_ident(radio)

    data = radio._mmap.get_packed()

    def status(addr):
        status = chirp_common.Status()
        status.cur = addr
        status.max = radio._memsize
        status.msg = "Cloning to radio"
        radio.status_fn(status)
        LOG.debug('Radio address 0x%04x' % addr)

    for addr in range(0, 0x30E0, 0x40):
        block = data[addr:addr + 0x40]
        hdr = struct.pack('>cHB', b'W', addr, 0x40)
        radio.pipe.write(hdr + block)
        ack = radio.pipe.read(1)
        if ack != b'\x06':
            LOG.error('Expected ack, got %r' % ack)
            raise errors.RadioError('Radio did not ACK block')
        status(addr)


class TKx160Radio(chirp_common.CloneModeRadio):
    VENDOR = 'Kenwood'
    FORMATS = [directory.register_format('Kenwood KPG-99D', '*.dat')]
    _memsize = 0x4000

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Failed download: %s' % e)
            raise errors.RadioError('Failed to communicate with radio')
        self.process_mmap()

    def sync_out(self):
        try:
            self._mmap = do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Failed upload: %s' % e)
            raise errors.RadioError('Failed to communicate with radio')

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    @classmethod
    def match_model(cls, filedata, filename):
        return (filename.endswith('.dat') and
                filedata[0x1740:0x1746] == cls._model)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 128)
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_sub_devices = not self.VARIANT
        rf.has_tuning_step = False
        rf.has_rx_dtcs = True
        rf.has_settings = True
        rf.can_odd_split = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS', "Tone->DTCS",
                                'DTCS->Tone', '->Tone', 'DTCS->DTCS']
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 12.5, 10.0, 15.0, 20.0,
                                 25.0, 50.0, 100.0]
        rf.valid_bands = self.VALID_BANDS
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC
        rf.valid_name_length = 8
        rf.valid_power_levels = list(reversed(POWER_LEVELS))
        rf.valid_skips = ['', 'S']
        return rf

    def _get_zone_info(self):
        zones = {}
        for i in range(128):
            info = self._memobj.zoneinfo[i]
            if info.used:
                zones[i + 1] = int(info.count)
        if not zones:
            LOG.warning('No zones defined, defaulting to 1')
            # Default to at least one zone so we have *something*
            zones[1] = 0
        return zones

    def _set_num_zones(self, count):
        LOG.debug('Setting zones to %i' % count)
        for i in range(128):
            index_obj = self._memobj.index[i]
            if index_obj.zone != 0xFF and index_obj.zone > count:
                LOG.debug('Deleting memory %i:%i to delete zone',
                          index_obj.zone, index_obj.memory)
                self._delete_entry_from_index(i)

        # This will disable zones with no memories, so do it after deletion
        # but before we may expand (if we're increasing)
        self.recalculate_index_entry_bitmask()

        unused_zones = []
        for i in range(128):
            info = self._memobj.zoneinfo[i]
            info.used = i < count
            if not info.used:
                unused_zones.append(i + 1)

    def _get_zone(self, zone):
        class TKx160Zone(self.__class__):
            MODEL = self.MODEL
            VARIANT = 'Zone %i' % zone
            VALID_BANDS = self.VALID_BANDS

            def __init__(self, parent, zone):
                self._memobj = parent._memobj
                self._zone = zone

        return TKx160Zone(self, zone)

    def get_sub_devices(self):
        if not self._memobj:
            return [self._get_zone(1)]
        return [self._get_zone(zone)
                for zone, count in self._get_zone_info().items()]

    def get_raw_memory(self, number):
        index_entry, slot = self.check_index(number)
        return (repr(self._memobj.index[index_entry]) +
                repr(self._memobj.memories[slot]))

    def check_index(self, number):
        """Return the index entry and slot for a channel in our zone"""
        for i in range(128):
            index_obj = self._memobj.index[i]
            if index_obj.zone == self._zone and index_obj.memory == number:
                LOG.debug('Found %i:%i in slot %i',
                          self._zone, number,
                          index_obj.slot)
                return i, index_obj.slot
        return None, None

    def next_slot(self, number):
        """Claim the next available slot entry for channel."""
        for next_index in range(128):
            index_obj = self._memobj.index[next_index]
            if index_obj.zone == 0xFF:
                break
        else:
            raise errors.RadioError('Radio is out if index memory')

        for next_slot in range(128):
            if self._memobj.memories[next_slot].number == 0xFF:
                break
        else:
            raise errors.RadioError('Radio is out of memory slots')

        LOG.debug('Putting channel %i in index spot %i',
                  number, next_index)
        index_obj = self._memobj.index[next_index]
        index_obj.zone = self._zone
        index_obj.memory = number
        index_obj.zero = 0
        index_obj.slot = next_slot

        self.recalculate_index_entry_bitmask()

        return next_slot

    def _delete_entry_from_index(self, index_entry):
        last_entry = index_entry

        # Find the last index entry
        for i in reversed(range(0, 128)):
            mask = 1 << (i % 8)
            if self._memobj.flag1[i // 8] & mask:
                last_entry = i
                break

        src_obj = self._memobj.index[last_entry]
        dst_obj = self._memobj.index[index_entry]
        if index_entry != last_entry:
            LOG.debug('Moving index entry %i to %i for delete of %i:%i',
                      last_entry, index_entry,
                      dst_obj.zone, dst_obj.memory)
            # Move last to current
            dst_obj.zone = src_obj.zone
            dst_obj.memory = src_obj.memory
            dst_obj.zero = src_obj.zero
            dst_obj.slot = src_obj.slot

        # Clear out the entry we moved, which may be the last and only one
        src_obj.set_raw(b'\xFF' * 4)

    def delete_from_index(self, number):
        """Delete the index entry for number"""
        # Find the index entry to delete
        index_entry, _slot = self.check_index(number)
        self._delete_entry_from_index(index_entry)
        self.recalculate_index_entry_bitmask()

    def recalculate_index_entry_bitmask(self):
        # Recalculate the pins. This is more laborious than needed, but should
        # also clean up residue.
        zone_counts = [0] * 128
        mem_flags = [0] * 16
        for i in range(128):
            index_obj = self._memobj.index[i]
            byte = i // 8
            mask = 1 << (i % 8)
            if index_obj.memory != 0xFF:
                mem_flags[byte] |= mask
                zone_counts[index_obj.zone - 1] += 1

        for i, byte in enumerate(mem_flags):
            self._memobj.flag1[i] = byte
            self._memobj.flag2[i] = byte

        zone_flags = [0] * 16
        # Update zoneinfo
        for i, count in enumerate(zone_counts):
            self._memobj.zoneinfo[i].used = bool(count)
            self._memobj.zoneinfo[i].count = count
            if count:
                zone_flags[i // 8] |= (1 << (i % 8))
                LOG.debug('Zone %i count is %i', i + 1, count)

        for i, byte in enumerate(zone_flags):
            self._memobj.zoneflag[i] = byte

    def get_memory(self, number):
        m = chirp_common.Memory(number)
        _index_entry, slot = self.check_index(number)
        if slot is None:
            m.empty = True
            return m

        _mem = self._memobj.memories[slot]

        m.freq = int(_mem.rx_freq) * 10
        offset = int(_mem.tx_freq) * 10 - m.freq
        if _mem.tx_freq.get_raw() == b'\xFF\xFF\xFF\xFF':
            m.offset = 0
            m.duplex = 'off'
        elif offset < 0:
            m.offset = abs(offset)
            m.duplex = '-'
        elif offset > 0:
            m.offset = offset
            m.duplex = '+'
        else:
            m.offset = 0

        rxtone = tk8180.KenwoodTKx180Radio._decode_tone(
            _mem.rxtone)
        txtone = tk8180.KenwoodTKx180Radio._decode_tone(
            _mem.txtone)
        chirp_common.split_tone_decode(m, txtone, rxtone)

        m.name = str(_mem.name).rstrip()
        m.power = POWER_LEVELS[int(_mem.highpower)]
        m.mode = 'FM' if _mem.wide else 'NFM'
        m.skip = '' if _mem.scanadd else 'S'

        return m

    def set_memory(self, mem):
        _index_entry, slot = self.check_index(mem.number)
        if mem.empty:
            if slot is not None:
                self._memobj.memories[slot].set_raw(b'\xFF' * 32)
                self.delete_from_index(mem.number)
            return
        elif slot is None:
            slot = self.next_slot(mem.number)

        _mem = self._memobj.memories[slot]
        _mem.number = mem.number
        _mem.zone = self._zone

        LOG.debug('Setting memory %i in slot %i', mem.number, slot)

        _mem.rx_freq = mem.freq // 10
        if mem.duplex == '':
            _mem.tx_freq = mem.freq // 10
        elif mem.duplex == 'split':
            _mem.tx_freq = mem.offset // 10
        elif mem.duplex == 'off':
            _mem.tx_freq.set_raw(b'\xFF' * 4)
        elif mem.duplex == '-':
            _mem.tx_freq = (mem.freq - mem.offset) // 10
        elif mem.duplex == '+':
            _mem.tx_freq = (mem.freq + mem.offset) // 10
        else:
            raise errors.RadioError('Unsupported duplex mode %r' % mem.duplex)

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        _mem.rxtone = tk8180.KenwoodTKx180Radio._encode_tone(*rxtone)
        _mem.txtone = tk8180.KenwoodTKx180Radio._encode_tone(*txtone)

        _mem.wide = mem.mode == 'FM'
        _mem.highpower = mem.power == POWER_LEVELS[1]
        _mem.scanadd = mem.skip == ''
        _mem.name = mem.name[:8].ljust(8)

        # Set the flags we don't support
        _mem.bcl = 0
        _mem.beatshift = 0
        _mem.pttid = 0
        _mem.compander = 0
        _mem.pttidmute = 0
        _mem.optsig = 0

        # Set the unknowns
        _mem.unknown1[0] = 0x02
        _mem.unknown1[1] = 0x02
        _mem.unknown2_0 = 0x0F
        _mem.unknown2_01 = 0x00
        _mem.unknown2_1 = 0x00
        _mem.unknown2_2 = 0x00
        _mem.unknown2_3 = 0x00
        _mem.unknown3_0 = 0x00
        _mem.unknown3_1 = 0x00
        _mem.unknown4 = 0x1F
        _mem.unknown5[0] = 0xFF
        _mem.unknown5[1] = 0xFF

    @staticmethod
    def make_key_group(keysobj, keynames, keyvals):
        keyvals_by_label = {v: k for k, v in keyvals.items()}

        def applycb(setting):
            element = setting.get_name()
            value = keyvals_by_label[str(setting.value)]
            LOG.debug('Setting %s=%s (0x%02x)', element, setting.value, value)
            setattr(keysobj, element, value)

        group = settings.RadioSettingGroup('keys', 'Keys')
        for name, element in keynames.items():
            current = keyvals[int(getattr(keysobj, element))]
            val = settings.RadioSettingValueList(keyvals.values(), current)
            keysetting = settings.RadioSetting(element, name, val)
            keysetting.set_apply_callback(applycb)
            group.append(keysetting)
        return group

    def get_settings(self):
        num_zones = len(self._get_zone_info())
        zones = settings.RadioSettingGroup('zones', 'Zones')
        zone_count = settings.RadioSetting(
            'zonecount', 'Number of Zones',
            settings.RadioSettingValueInteger(1, 128, num_zones))
        zone_count.set_doc('Number of zones in the radio. '
                           'Requires a save and re-load of the file to take '
                           'effect. Reducing this number will DELETE '
                           'memories in the affected zones!')
        zones.append(zone_count)
        keys = self.make_key_group(self._memobj.keys,
                                   KEY_NAMES,
                                   KEYS)
        return settings.RadioSettings(zones, keys)

    def set_settings(self, _settings):
        for element in _settings:
            if not isinstance(element, settings.RadioSetting):
                self.set_settings(element)
            elif element.get_name() == 'zonecount':
                self._set_num_zones(int(element.value))

    def save_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'wb') as f:
                f.write(b'EX3774'.ljust(16, b'\xFF'))
                f.write(self._mmap.get_packed())
                LOG.info('Wrote DAT file')
        else:
            super().save_mmap(filename)

    def load_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'rb') as f:
                header = f.read(16)
                LOG.debug('DAT header:\n%s' % util.hexprint(header))
                self._mmap = memmap.MemoryMapBytes(f.read())
                LOG.info('Loaded DAT file')
            self.process_mmap()
        else:
            super().load_mmap(filename)


@directory.register
class TK7160RadioM(TKx160Radio):
    MODEL = 'TK-7160M'
    VALID_BANDS = [(136000000, 174000000)]
    _model = b'M66- \x04'


@directory.register
class TK7160RadioK(TKx160Radio):
    MODEL = 'TK-7160K'
    VALID_BANDS = [(136000000, 174000000)]
    _model = b'M66- \x02'


@directory.register
class TK8160RadioK(TKx160Radio):
    MODEL = 'TK-8160K'
    VALID_BANDS = [(400000000, 520000000)]
    _model = b'M67- "'


@directory.register
class TK8160RadioM(TKx160Radio):
    MODEL = 'TK-8160M'
    VALID_BANDS = [(400000000, 520000000)]
    _model = b'M67- D'
