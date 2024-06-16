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

import collections
import logging
import struct

from chirp import chirp_common
from chirp import bitwise
from chirp import directory
from chirp.drivers import tk8160
from chirp.drivers import tk8180
from chirp import errors
from chirp import memmap
from chirp import settings
from chirp import util

LOG = logging.getLogger(__name__)


IndexEntry = collections.namedtuple('IndexEntry', 'zone memory zoneindex slot')
EMPTY_INDEX_ENTRY = IndexEntry(0xFF, 0xFF, 0xFF, 0xFF)


def send(radio, frame):
    LOG.debug("%04i P>R:\n%s" % (len(frame), util.hexprint(frame)))
    radio.pipe.write(frame)


def recv(radio, count):
    buf = radio.pipe.read(count)
    LOG.debug('%04i: R>P:\n%s' % (len(buf), util.hexprint(buf)))
    return buf


def do_ident(radio):
    radio.pipe.baudrate = 9600
    radio.pipe.databits = 8
    radio.pipe.stopbits = 2
    radio.pipe.parity = 'N'
    radio.pipe.timeout = 1
    send(radio, b'PROGRAM')
    ack = recv(radio, 1)
    if ack != b'\x06':
        LOG.error('Expected ACK, got %r' % ack)
        raise errors.RadioError('Radio failed to ack program mode')
    send(radio, b'\x02')
    model = recv(radio, 8)
    if model != radio._model:
        raise errors.RadioError('Incorrect model')
    send(radio, b'\x06')
    ack = recv(radio, 1)
    if ack != b'\x06':
        raise errors.RadioError('No ack after model probe')
    send(radio, b'P')
    resp = recv(radio, 10)
    LOG.debug('Radio ident:\n%s' % util.hexprint(resp))
    send(radio, b'\x06')
    ack = recv(radio, 1)
    if ack != b'\x06':
        raise errors.RadioError('No ack after version probe')


def status(radio, block, msg):
    s = chirp_common.Status()
    s.cur = block
    s.max = 0x7F
    s.msg = msg
    radio.status_fn(s)


def do_download(radio):
    do_ident(radio)

    data = b''
    for block in range(0x80):
        send(radio, struct.pack('>cBB', b'R', 0, block))
        cmd = recv(radio, 1)
        if cmd == b'Z':
            fillbyte = recv(radio, 1)
            if len(fillbyte) != 1:
                LOG.error('Expected fill byte after Z but got none')
                raise errors.RadioError('Failed to communicate')
            chunk = fillbyte * 256
        elif cmd == b'W':
            chunk = recv(radio, 256)
            cs = recv(radio, 1)
            ccs = sum(chunk) % 256
            if cmd != b'Z' and cs[0] != ccs:
                LOG.error('Checksum mismatch %02x!=%02x at block %02x',
                          cs[0], ccs, block)
                raise errors.RadioError(
                    'Checksum mismatch at block %02i' % block)
        else:
            LOG.error('Unsupported command %r' % cmd)
            raise errors.RadioError('Invalid command')

        data += chunk
        send(radio, b'\x06')
        ack = recv(radio, 1)
        if ack != b'\x06':
            LOG.error('Expected ACK got %r' % ack)
            raise errors.RadioError('Failed at block %02x' % block)
        status(radio, block, 'Receiving from radio')

    # This is a separate region at the end, read and written in a different
    # way. Only contains the scan bits (that we know of)
    for addr in range(0x0320, 0x0340, 0x10):
        hdr = struct.pack('>cHB', b'S', addr, 0x10)
        send(radio, hdr)
        cmd = recv(radio, 1)
        if cmd != b'X':
            LOG.error('Unsupported command %r' % cmd)
            raise errors.RadioError('Invalid command')
        chunk = recv(radio, 0x10)
        if len(chunk) == 0x10:
            send(radio, b'\x06')
            recv(radio, 1)
        else:
            LOG.error('Got short read at %04x:\n%s',
                      addr, util.hexprint(chunk))
            raise errors.RadioError('Short read at %04x' % addr)
        data += chunk

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    do_ident(radio)

    data = radio._mmap.get_packed()
    for block in range(0x80):
        if 0x54 <= block < 0x60:
            LOG.debug('Skipping block 0x%02x' % block)
            continue
        addr = block * 256
        chunk = data[addr:addr + 256]
        if len(set(chunk)) == 1:
            hdr = struct.pack('cBBB', b'Z', 0, block, chunk[0])
            send(radio, hdr)
        else:
            hdr = struct.pack('cBB', b'W', 0, block)
            send(radio, hdr)
            send(radio, chunk)
            cs = sum(chunk) % 256
            send(radio, bytes([cs]))
        ack = recv(radio, 1)
        if ack != b'\x06':
            LOG.error('Expected ACK but got %r' % ack)
            raise errors.RadioError('Radio NAKd block %i' % block)
        status(radio, block, 'Sending to radio')

    for i in range(2):
        radio_addr = 0x0320 + i * 0x10
        memory_addr = 0x8000 + i * 0x10
        chunk = data[memory_addr:memory_addr + 0x10]
        hdr = struct.pack('>cHB', b'X', radio_addr, 0x10)
        send(radio, hdr)
        send(radio, chunk)
        send(radio, bytes([sum(chunk) % 255]))
        ack = recv(radio, 1)
        if ack != b'\x06':
            LOG.error('Expected ACK at %04x, got %r', radio_addr, ack)
            raise errors.RadioError('Radio NAKd block')
        send(radio, ack)


def exit_program(radio):
    try:
        send(radio, b'E')
    except Exception:
        pass


KEYS = {
    0x31: 'DTMF ID (BOT)',
    0x32: 'DTMF ID (EOT)',
    0x33: 'Display Character',
    0x35: 'Home Channel',
    0x37: 'Channel Down',
    0x38: 'Channel Up',
    0x39: 'Key Lock',
    0x3A: 'Lamp',
    0x3C: 'Memory RCL/STO',
    0x3E: 'Memory RCL',
    0x3F: 'Memory STO',
    0x40: 'Squelch Off Momentary',
    0x41: 'Squelch Off Toggle',
    0x42: 'Monitor Momentary',
    0x43: 'Monitor Toggle',
    0x45: 'Redial',
    0x46: 'Low RF Power',
    0x47: 'Scan',
    0x48: 'Scan Add/Del',
    0x4A: 'Group Down',
    0x4B: 'Group Up',
    0x4E: 'OST',
    0x4F: 'None',
    0x52: 'Talk Around',
    0x60: 'Squelch Level',
    }

KEY_NAMES = {
    'A': 'akey',
    'B': 'bkey',
    'C': 'ckey',
    'S': 'skey',
    'Side 1': 'side1',
    'Side 2': 'side2',
    'Aux': 'aux',
    'Mic PF1': 'pf1',
    'Mic PF2': 'pf2',
}

KNOB = {
    0x00: 'None',
    0x01: 'Channel Up/Down',
    0x02: 'Group Up/Down',
}

BATTSAVE = {
    0xFF: 'Off',
    0x30: 'Short',
    0x31: 'Medium',
    0x32: 'Long',
}

mem_format = """
#seekto 0x00E;
u8 zone_count;
u8 memory_count;

#seekto 0x01F;
// 0xFF=off, 0x30=short, 0x31=med, 0x32=long
u8 battsave;

#seekto 0x110;
// 4F=none 31=dtmfidbot 32=dmtfideot 33=chup 35=home 37=chandn 38=dispchr
// 39=keylock 3A=lamp 3C=memrclsto 3E=memrcl 3F=memsto 40=sqlmon 41=sqltog
// 42=monmom 43=montog 45=redial 46=lowpower 47=scan 48=scanadd 60=sqllev 52=ta
// 4A=grpdn 4B=grpup 4E=OST
struct {
    u8 akey;
    u8 bkey;
    u8 ckey;
    u8 side2;
    u8 skey;
    u8 side1;
    u8 aux;
    u8 pf1;
    u8 pf2;
} keys;
#seekto 0x124;
// A1=cha A2=group 4F=none
u8 unknown1:6,
   knob:2;

#seekto 0x300;
struct {
    u8 zone;
    u8 memory;
    u8 zoneinfo_index;
    u8 slot;
} index[250];

#seekto 0x1000;
struct {
    u8 zone;
    u8 count;
    char name[10];
    u8 unknown[4];
} zoneinfo[250];

#seekto 0x2000;
struct {
    u8 memory;
    u8 zone;
    char name[10];
    lbcd rx_freq[4];
    lbcd tx_freq[4];
    u8 rxsomething;
    u8 txsomething;
    ul16 rxtone;
    ul16 txtone;
    u8 unknown2[5];
    u8 optsig;            // ff=None 31=2tone 30=DTMF 32=MSK
    u8 unknown2_1:1,
       pttid:1,           // 0=on 1=off
       beatshift:1,       // 0=on 1=off
       bcl:1,             // 1=none 0=QT/DQT
       unknown1_2:1,
       highpower:1,
       compander:1,       //0=on 1=off
       wide:1;
    u8 unknown3_1:4,
       bcl_optsig:2,      // 0 if bcl=carrier 1 if bcl=optsig 3 otherwise
       mode2tone:2;       // F=off C=2tone1 D=2tone2 E=2tone3
    u8 unknown4[14];
} memories[250];

#seekto 0x8000;
u8 scanbits[32];
"""


POWER_LEVELS = [chirp_common.PowerLevel('Low', watts=1),
                chirp_common.PowerLevel('High', watts=5)]


class KenwoodTKx140Radio(chirp_common.CloneModeRadio):
    VENDOR = 'Kenwood'
    FORMATS = [directory.register_format('Kenwood KPG-74D', '*.dat')]

    def sync_in(self):
        try:
            self._mmap = do_download(self)
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Failed to download: %s' % e)
            raise errors.RadioError('Failed to download from radio')
        finally:
            exit_program(self)

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('Failed to upload: %s' % e)
            raise errors.RadioError('Failed to upload to radio')
        finally:
            exit_program(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 250)
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_rx_dtcs = True
        rf.has_settings = True
        rf.can_odd_split = True
        rf.valid_bands = self._valid_bands
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 10
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS', "Tone->DTCS",
                                'DTCS->Tone', '->Tone', 'DTCS->DTCS']
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_power_levels = list(POWER_LEVELS)
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 12.5, 10.0, 15.0, 20.0,
                                 25.0, 50.0, 100.0]

        rf.has_sub_devices = not self.VARIANT
        return rf

    def _get_zone(self, zone):
        class TKx140Zone(self.__class__):
            MODEL = self.MODEL
            VARIANT = 'Group %i' % zone
            _valid_bands = self._valid_bands

            def __init__(self, parent, zone):
                self._memobj = parent._memobj
                self._zone = zone

        return TKx140Zone(self, zone)

    def _get_zone_info(self):
        zones = collections.defaultdict(int)
        for i in range(250):
            zone_obj = self._memobj.zoneinfo[i]
            if int(zone_obj.zone) != 0xFF:
                zones[int(zone_obj.zone)] = int(zone_obj.count)
        return zones

    def _set_num_zones(self, count):
        zones = self._get_zone_info()
        available = [x + 1 for x in range(250) if x + 1 not in zones]
        for i in range(250):
            zoneinfo_obj = self._memobj.zoneinfo[i]
            if i >= count:
                if i > 0 and zoneinfo_obj.zone != 0xFF:
                    LOG.debug('Deleting zone %i index %i',
                              zoneinfo_obj.zone, i)
                zoneinfo_obj.set_raw(b'\xFF' * 16)
            elif zoneinfo_obj.zone == 0xFF:
                next_zone = available.pop(0)
                LOG.debug('Adding zone %i index %i', next_zone, i)
                zoneinfo_obj.zone = next_zone
                zoneinfo_obj.count = 0
                zoneinfo_obj.name = ('Group %i' % next_zone).ljust(10)
            else:
                LOG.debug('Keeping existing zone %i index %i',
                          zoneinfo_obj.zone, i)
        self.sort_index()

    def get_sub_devices(self):
        if not self._memobj:
            return [self._get_zone(1)]
        return [self._get_zone(zone)
                for zone, count in self._get_zone_info().items()]

    def check_index(self, number):
        for i in range(250):
            index_obj = self._memobj.index[i]
            if index_obj.zone == self._zone and index_obj.memory == number:
                return i, index_obj.slot
            elif index_obj.zone == 0xFF:
                # KPG-74D keeps these compacted so that there are no empties
                # until the end
                break
        return None, None

    def next_slot(self, number):
        for i in range(250):
            if self._memobj.memories[i].memory == 0xFF:
                return i

    def sort_index(self):
        zones = []
        for i in range(250):
            zoneinfo_obj = self._memobj.zoneinfo[i]
            if zoneinfo_obj.zone == 0xFF:
                break
            zones.append(int(zoneinfo_obj.zone))

        LOG.debug('Enabled zones: %s' % zones)

        index_entries = []
        for i in range(250):
            mem_obj = self._memobj.memories[i]
            if mem_obj.zone == 0xFF:
                # Empty
                continue
            if int(mem_obj.zone) not in zones:
                LOG.debug('Erasing %i:%i from slot %i because zone disabled',
                          mem_obj.zone, mem_obj.memory, i)
                mem_obj.set_raw(b'\xFF' * 48)
                continue
            index_entries.append(IndexEntry(int(mem_obj.zone),
                                            int(mem_obj.memory),
                                            zones.index(int(mem_obj.zone)),
                                            i))

        index_entries.sort()
        zone_counts = collections.defaultdict(int)
        for i in range(250):
            try:
                entry = index_entries[i]
                zone_counts[entry.zone] += 1
            except IndexError:
                entry = EMPTY_INDEX_ENTRY
            index_obj = self._memobj.index[i]
            index_obj.zone = entry.zone
            index_obj.memory = entry.memory
            index_obj.zoneinfo_index = entry.zoneindex
            index_obj.slot = entry.slot

        for zone_index, zone in enumerate(zones):
            LOG.debug('Zone %i count %i' % (zone, zone_counts[zone]))
            self._memobj.zoneinfo[zone_index].count = zone_counts[zone]
        self._memobj.memory_count = sum(zone_counts.values())
        self._memobj.zone_count = len(zones)

        LOG.debug('Sorted index, %i memories' % self._memobj.memory_count)

    def get_raw_memory(self, number):
        _index_entry, slot = self.check_index(number)
        if slot is not None:
            return '\n'.join(repr(x) for x in [
                self._memobj.memories[slot],
                self._memobj.index[_index_entry]])

    def get_memory(self, number):
        m = chirp_common.Memory(number)
        _index_entry, slot = self.check_index(number)
        if slot is None:
            m.empty = True
            return m

        _mem = self._memobj.memories[slot]
        _scn = self._memobj.scanbits[slot // 8]
        mask = 1 << (slot % 8)
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
        m.skip = '' if _scn & mask else 'S'

        return m

    def set_memory(self, mem):
        index_entry, slot = self.check_index(mem.number)
        if mem.empty:
            if slot is not None:
                self._memobj.memories[slot].set_raw(b'\xFF' * 48)
                self.sort_index()
            return
        if slot is None:
            slot = self.next_slot(mem.number)
        _mem = self._memobj.memories[slot]
        _scn = self._memobj.scanbits[slot // 8]
        mask = 1 << (slot % 8)

        # Everything seems to default to 0xFF for "off"
        _mem.set_raw(b'\xFF' * 48)
        _mem.memory = mem.number
        _mem.zone = self._zone
        self.sort_index()
        _mem.rxsomething = 0x35
        _mem.txsomething = 0x35

        _mem.rx_freq = mem.freq // 10
        if mem.duplex == '':
            _mem.tx_freq = mem.freq // 10
        elif mem.duplex == 'split':
            _mem.tx_freq = mem.offset // 10
        elif mem.duplex == 'off':
            _mem.tx_freq.fill_raw(b'\xFF')
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
        _mem.name = mem.name[:10].ljust(10)
        if mem.skip == 'S':
            _scn &= ~mask
        else:
            _scn |= mask

    def load_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'rb') as f:
                header = f.read(0x40)
                LOG.debug('DAT header:\n%s' % util.hexprint(header))
                self._mmap = memmap.MemoryMapBytes(f.read())
                LOG.info('Loaded DAT file')
            self.process_mmap()
        else:
            super().load_mmap(filename)

    def save_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'wb') as f:
                f.write(b'KPG74D\xff\xff\xff\xffV1.10P')
                f.write(self._model[1:] + (b'\xff' * 9))
                f.write(b'\xff' * 32)
                f.write(self._mmap.get_packed())
                LOG.info('Wrote DAT file')
        else:
            super().save_mmap(filename)

    @classmethod
    def match_model(cls, filedata, filename):
        if (filename.lower().endswith('.dat') and
                filedata.startswith(b'KPG74D') and
                filedata[0xE7:0xEF] == cls._model):
            return True
        return super().match_model(filedata, filename)

    def get_settings(self):
        num_zones = len(self._get_zone_info())
        zones = settings.RadioSettingGroup('zones', 'Zones')
        zone_count = settings.RadioSetting(
            'zonecount', 'Number of Zones',
            settings.RadioSettingValueInteger(1, 250, num_zones))
        zone_count.set_doc('Number of zones in the radio. '
                           'Requires a save and re-load of the file to take '
                           'effect. Reducing this number will DELETE '
                           'memories in the affected zones!')
        zones.append(zone_count)

        keys = tk8160.TKx160Radio.make_key_group(self._memobj.keys,
                                                 KEY_NAMES,
                                                 KEYS)

        def apply_knob(setting):
            rev = {v: k for k, v in KNOB.items()}
            self._memobj.knob = rev[str(setting.value)]

        knob = settings.RadioSetting(
            'knob', 'Knob',
            settings.RadioSettingValueList(
                KNOB.values(), current_index=self._memobj.knob))
        knob.set_apply_callback(apply_knob)
        keys.append(knob)

        def apply_battsave(setting):
            rev = {v: k for k, v in BATTSAVE.items()}
            self._memobj.battsave = rev[str(setting.value)]

        general = settings.RadioSettingGroup('general', 'General')
        battsave = settings.RadioSetting(
            'battsave', 'Battery Save',
            settings.RadioSettingValueList(
                BATTSAVE.values(),
                BATTSAVE[int(self._memobj.battsave)]))
        battsave.set_apply_callback(apply_battsave)
        general.append(battsave)

        return settings.RadioSettings(zones, keys, general)

    def set_settings(self, _settings):
        for element in _settings:
            if not isinstance(element, settings.RadioSetting):
                self.set_settings(element)
            elif element.get_name() == 'zonecount':
                self._set_num_zones(int(element.value))
            elif element.has_apply_callback():
                element.run_apply_callback()


@directory.register
class KenwoodTK2140KRadio(KenwoodTKx140Radio):
    MODEL = 'TK-2140K'
    _valid_bands = [(136000000, 174000000)]
    _model = b'P2140\x04\xFF\xF1'


@directory.register
class KenwoodTK3140KRadio(KenwoodTKx140Radio):
    MODEL = 'TK-3140K'
    _valid_bands = [(400000000, 520000000)]
    _model = b'P3140\x06\xFF\xF1'


@directory.register
class KenwoodTK3140K2Radio(KenwoodTKx140Radio):
    MODEL = 'TK-3140K2'
    _valid_bands = [(400000000, 520000000)]
    _model = b'P3140\x07\xFF\xF1'


@directory.register
class KenwoodTK3140K3Radio(KenwoodTKx140Radio):
    MODEL = 'TK-3140K3'
    _valid_bands = [(400000000, 520000000)]
    _model = b'P3140\x08\xFF\xF1'
