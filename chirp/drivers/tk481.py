# Copyright 2024 Dan Smith <chirp@f.danplanet.com>
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

from collections import namedtuple
import logging

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp.drivers import tk280
from chirp.settings import RadioSetting, RadioSettingSubGroup, MemSetting
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueString
from chirp.settings import RadioSettingValueInvertedBoolean
from chirp.settings import RadioSettingGroup

TRUNK_DEFS = """
struct trunk_settings {
    ul16 sys_start[32];
    u8 systems;
};
"""

MEM_FORMAT = tk280.DEFS + TRUNK_DEFS + """
struct trunk_settings trunk;

#seekto 0x004A;
lbit system_lockout[32];
lbit trunk_systems[32]; // 1 if system is trunking, 0 if conventional

#seekto 0x005C;
struct {
    u16 first_system;
    u16 last_system; // nope
} state;

#seekto 0x0082;
struct settings settings;

#seekto 0x0110;
struct keys keys;

#seekto 0x1E7;
struct misc misc;

struct system {
  u8 system;
  u8 channels;
  u8 unknown1;
  char name[10];
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5[16];
};

struct channel {
  u8 number;
  lbcd rxfreq[4];
  lbcd txfreq[4];
  u8 unknown_rx:4,
     rx_step:4; // 0x5
  u8 unknown_tx:4,
     tx_step:4; // 0x5
  ul16 rx_tone;
  ul16 tx_tone;
  char name[10];
  u8 unknown4; // 0xFF
  u8 unknown4_1:4,
     power:1, // 0=low, 1=high
     unknown4_2:3;
  u8 unknown5_1:2,
     talkaround:1, // 1=No, 0=Yes
     call:1,   // 1=No, 0=Yes
     unknown5_2:1,
     grouplockout:1, // 1=No, 0=Yes
     unknown5_3:2; //0xFB
  u8 unknown6[4]; // 0xFF
};
"""

LOG = logging.getLogger(__name__)
SystemDef = namedtuple('SystemDef', ('index', 'number'))


class TKx80_Trunked(tk280.KenwoodTKx80):
    _system = 0

    def process_mmap(self):
        memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        first = memobj.state.first_system

        my_format = MEM_FORMAT + '#seekto 0x%04x;\n' % first
        for i in range(32):
            start = memobj.trunk.sys_start[i]
            if start == 0xFFFF:
                # Not used
                continue
            # We need to know how many channels each system has in some easy-
            # to-calculate way without having to parse all the headers. To
            # avoid another intermediate parse, just grab the start and add
            # one for the number of channels count.
            count = self._mmap[start + 1][0]
            sys_format = (
                "struct { \n"
                "  struct system sys;\n"
                "  struct channel channels[0x%x];\n"
                "} system%i;\n") % (count, i)
            my_format += sys_format
        self._memobj = bitwise.parse(my_format, self._mmap)

    def _get_system_info(self, index):
        if self._memobj.trunk.sys_start[index] == 0xFFFF:
            raise IndexError('No such system')
        system = getattr(self._memobj, 'system%i' % index)
        system_start = self._memobj.trunk.sys_start[index]
        system_end = system_start + (32 * (system.sys.channels + 1))
        return system_start, system_end, system

    def _expand_system(self, system_number, amount=1):
        """Expand a system to make more room for memories"""

        my_index = system_number - 1
        try:
            system_start, system_end, system = self._get_system_info(my_index)
            system.sys.channels += amount
        except IndexError:
            system = None
            # If we're the first, we'll start at beginning of memory
            system_start = 0x0300
            # Find first used system before me, grab its start+size
            for i in range(my_index):
                try:
                    _, system_start, _ = self._get_system_info(i)
                except IndexError:
                    continue
            LOG.debug('Allocating new system %i at 0x%04x',
                      my_index, system_start)
            # An empty system has only the 32-byte header
            system_end = system_start + 32

        # Add space to all the system starts after this one
        for index in reversed(range(32)):
            if index > my_index:
                if self._memobj.trunk.sys_start[index] == 0xFFFF:
                    continue
                self._memobj.trunk.sys_start[index] += (amount * 32)
            elif index == my_index:
                self._memobj.trunk.sys_start[index] = system_start

        # Calculate the new end of the system we need to expand:
        # number of channels (plus one for the system header), 32 bytes each
        new_end = system_end + (amount * 32)

        # Copy everything to the new location
        self._mmap[new_end] = self._mmap[system_end:-(amount * 32)]

        # Clear the new hole and add to the channels
        self._mmap[system_end] = b'\xFF' * 32 * amount

        # If we allocated a new system, bootstrap the channel count, mark as
        # non-trunked, increase the total system count
        if system is None:
            self._mmap[system_start + 1] = amount
            self._memobj.trunk_systems[my_index] = 0
            self._memobj.trunk.systems += 1

        # Rebuild the internal memory object
        self.process_mmap()
        LOG.debug('Expanded system %i index %i to %i channels '
                  '(start 0x%04x new end %04x)',
                  system_number, my_index,
                  system and system.sys.channels or amount,
                  system_start, new_end)

        return getattr(self._memobj, 'system%i' % my_index)

    def _reduce_system(self, system_number, channel):
        """Remove a memory slot from a system"""

        my_index = system_number - 1
        system_start, system_end, system = self._get_system_info(my_index)

        # Shift memories up in the system, or fail before accounting if we
        # do not find the one specified
        found_channel = False
        for i in range(0, system.sys.channels):
            if system.channels[i].number == channel:
                found_channel = True
            elif found_channel:
                system.channels[i - 1].set_raw(system.channels[i].get_raw())
        if not found_channel:
            raise IndexError('Memory %i not mapped' % channel)

        # Remove space from all the system starts after this one
        for index in reversed(range(32)):
            if index > my_index:
                if self._memobj.trunk.sys_start[index] == 0xFFFF:
                    continue
                self._memobj.trunk.sys_start[index] -= 32

        # Calculate the new end of the system we need to expand:
        # number of channels (plus one for the system header), 32 bytes each
        new_end = system_end - 32

        # Copy everything to the new location
        self._mmap[new_end] = self._mmap[system_end:]

        # Clear the hole at the end (if necessary) and decrement the channels
        self._mmap[-32] = b'\xFF' * 32
        system.sys.channels -= 1

        # Rebuild the internal memory object
        self.process_mmap()
        LOG.debug('Reduced system %i index %i to %i channels '
                  '(start 0x%04x new end %04x)',
                  system_number, my_index,
                  system.sys.channels, system_start, new_end)

    def get_features(self):
        rf = super().get_features()
        rf.memory_bounds = (1, 250)
        # These are all NFM only?
        rf.valid_modes = ['NFM']
        rf.valid_skips = ['', 'S']
        return rf

    def get_sub_devices(self):
        # For the uninitialized case of just surveying the features
        if not self._memobj:
            return [TKx80System(self, 1)]
        to_copy = ('MODEL', 'TYPE', 'POWER_LEVELS', '_range', '_steps',
                   '_freqmult')
        return [
            tk280.TKx80SubdevMeta.make_subdev(
                self, TKx80System, i,
                to_copy,
                VARIANT=str(getattr(self._memobj,
                                    'system%i' % i).sys.name).strip())(
                    self, i + 1)
            for i in range(32)
            if self._memobj.trunk.sys_start[i] != 0xFFFF]

    def _get_memory(self, number):
        system = getattr(self._memobj, 'system%i' % (self._system - 1))
        for i in range(system.sys.channels):
            if int(system.channels[i].number) == number:
                return system.channels[i]
        raise IndexError('Memory %i not mapped' % number)

    def get_raw_memory(self, number):
        return repr(self._get_memory(number))

    def get_memory(self, number):
        mem = chirp_common.Memory()
        try:
            _mem = self._get_memory(number)
        except IndexError:
            mem.number = number
            mem.empty = True
            return mem
        self._get_memory_base(mem, _mem)
        mem.mode = 'NFM'
        mem.skip = '' if bool(_mem.grouplockout) else 'S'

        mem.extra = RadioSettingGroup('extra', 'Extra')
        rs = MemSetting('call', 'Call',
                        RadioSettingValueInvertedBoolean(not _mem.call))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        try:
            _mem = self._get_memory(mem.number)
        except IndexError:
            system = self._parent._expand_system(self._system)
            _mem = system.channels[system.sys.channels - 1]

        if mem.empty:
            self._parent._reduce_system(self._system, mem.number)
            return

        self._set_memory_base(mem, _mem)

        _mem.talkaround = 0 if not mem.duplex else 1
        _mem.grouplockout = 1 if mem.skip == '' else 0

        if mem.extra:
            mem.extra['call'].apply_to_memobj(_mem)

    def _set_settings_groups(self, settings):
        for i in range(32):
            try:
                enabled = settings['system-%i-enable' % i].value
            except KeyError:
                enabled = True
            try:
                name = str(settings['system-%i-name' % i].value)
            except KeyError:
                name = None
            try:
                _, _, system = self._get_system_info(i)
            except IndexError:
                if enabled:
                    new_system = self._expand_system(i + 1)
                    new_system.sys.name = ('System %i' % (i + 1)).ljust(10)
            else:
                if name is not None:
                    system.sys.name = name

    def _get_settings_groups(self, groups):
        groups.set_shortname('Systems')
        for i in range(32):
            rsg = RadioSettingSubGroup('system-%i' % i, 'System %i' % (i + 1))
            rse = RadioSetting('system-%i-enable' % i, 'Enabled',
                               RadioSettingValueBoolean(
                                   self._memobj.trunk.sys_start[i] != 0xFFFF))
            rse.set_volatile(True)
            rse.set_doc('Requires reload of file after changing!')
            if rse.value:
                # FIXME: Don't allow deleting systems yet
                rse.value.set_mutable(False)
            rsg.append(rse)
            if rse.value:
                _, _, system = self._get_system_info(i)
                name = str(system.sys.name)
            else:
                name = ''

            rs = RadioSetting('system-%i-name' % i, 'Name',
                              RadioSettingValueString(0, 10, name))
            rs.value.set_mutable(bool(rse.value))
            rsg.append(rs)

            rs = RadioSetting('system-%i-lockout' % i, 'Scan',
                              RadioSettingValueBoolean(
                                  self._memobj.system_lockout[i]))
            rs.value.set_mutable(bool(rse.value))
            rsg.append(rs)
            groups.append(rsg)

    # FIXME: Not yet decoded
    def _get_settings_fsync(self, optfeat2):
        return

    def _get_settings_ost(self, ost):
        return

    def _get_settings_format(self, optfeat1, optfeat2, scaninf):
        return


class TKx80System(TKx80_Trunked):
    def __init__(self, parent, system):
        self._system = system
        self._parent = parent

    @property
    def _memobj(self):
        return self._parent._memobj


@directory.register
class TK481(TKx80_Trunked):
    MODEL = 'TK-481'
    TYPE = b'PG481'
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                    chirp_common.PowerLevel("High", watts=2.5)]
    _range = [(896000000, 941000000)]
    _steps = chirp_common.COMMON_TUNING_STEPS + (6.25, 12.5)


@directory.register
class TK981(TKx80_Trunked):
    MODEL = 'TK-981'
    TYPE = b'M0981'
    POWER_LEVELS = []
    _range = [(896000000, 941000000)]
    _steps = chirp_common.COMMON_TUNING_STEPS + (6.25, 12.5)
