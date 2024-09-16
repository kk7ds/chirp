# Copyright 2010 Eric Allen <eric@hackerengineer.net>
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import time

from chirp import chirp_common, directory, bitwise, errors
from chirp.drivers import yaesu_clone

LOG = logging.getLogger(__name__)

TONES = chirp_common.OLD_TONES
TMODES = ["", "Tone"]
MODES = ['FM', 'AM']
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
DUPLEX = ["", "-", "+", "split"]
# "M" for masked memories, which are invisible until un-masked
SKIPS = ["", "S", "M"]
POWER_LEVELS_VHF = [chirp_common.PowerLevel("Low", watts=5),
                    chirp_common.PowerLevel("Mid", watts=20),
                    chirp_common.PowerLevel("High", watts=50)]
POWER_LEVELS_UHF = [chirp_common.PowerLevel("Low", watts=5),
                    chirp_common.PowerLevel("Mid", watts=20),
                    chirp_common.PowerLevel("High", watts=35)]
SPECIALS = {'1L': -1,
            '1U': -2,
            '2L': -3,
            '2U': -4,
            'Home': -5}

MEM_FORMAT = """
#seekto 0x{skips:X};
u8 skips[13];

#seekto 0x{enables:X};
u8 enables[13];

struct mem_struct {{
    u8 unknown4:2,
       baud9600:1,
       am:1,
       unknown4b:4;
    u8 power:2,
       duplex:2,
       unknown1b:4;
    u8 unknown2:1,
       tone_enable:1,
       tone:6;
    bbcd freq[3];
    bbcd offset[3];
}};

#seekto 0x{memories:X};
struct mem_struct memory[99];
"""


@directory.register
class FT8100Radio(yaesu_clone.YaesuCloneModeRadio):
    """Implementation for Yaesu FT-8100"""
    MODEL = "FT-8100"

    _memstart = 0
    _memsize = 2968
    _block_lengths = [10, 32, 114, 101, 101, 97, 128, 128, 128, 128, 128, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                      9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 1]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn Radio off.\n"
            "2. Connect data cable.\n"
            "3. While holding \"F/W\" button, turn radio on.\n"
            "4. <b>After clicking OK</b>, press \"RPT\" to send image.\n")
        rp.pre_upload = _(
            "1. Turn Radio off.\n"
            "2. Connect data cable.\n"
            "3. While holding \"F/W\" button, turn radio on.\n"
            "4. Press \"REV\" to receive image.\n"
            "5. Click OK to start transfer.\n")
        return rp

    @classmethod
    def match_model(cls, data, path):
        if (len(data) == cls._memsize and
                data[1:10] == b'\x01\x01\x07\x08\x02\x01\x01\x00\x01'):
            return True

        return False

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 99)
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_name = False

        rf.valid_tones = list(TONES)
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_power_levels = POWER_LEVELS_VHF
        rf.has_sub_devices = self.VARIANT == ''

        rf.valid_tuning_steps = list(STEPS)
        # This is not implemented properly, so don't expose it
        rf.valid_tuning_steps.remove(12.5)

        # This driver doesn't properly support the upper bound of 1300MHz
        # so limit us to 999MHz
        if self.VARIANT == 'VHF':
            rf.valid_bands = [(110000000, 280000000)]
        else:
            rf.valid_bands = [(280000000, 550000000),
                              (750000000, 999000000)]

        # This is not actually implemented, so don't expose it
        # rf.valid_skips = SKIPS
        rf.valid_skips = []

        # TODO
        # rf.valid_special_chans = SPECIALS.keys()
        # TODO
        # rf.has_tuning_step = False

        rf.can_odd_split = True

        return rf

    def sync_in(self):
        super(FT8100Radio, self).sync_in()
        self.pipe.write(bytes([yaesu_clone.CMD_ACK]))
        self.pipe.read(1)

    def sync_out(self):
        self.update_checksums()
        return _clone_out(self)

    def process_mmap(self):
        if not self._memstart:
            return

        mem_format = MEM_FORMAT.format(memories=self._memstart,
                                       skips=self._skipstart,
                                       enables=self._enablestart)

        self._memobj = bitwise.parse(mem_format, self._mmap)

    def get_sub_devices(self):
        return [FT8100RadioVHF(self._mmap), FT8100RadioUHF(self._mmap)]

    def get_memory(self, number):
        bit, byte = self._bit_byte(number)

        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        mem.freq = int(_mem.freq) * 1000
        if _mem.tone >= len(TONES) or _mem.duplex >= len(DUPLEX):
            mem.empty = True
            return mem
        else:
            mem.rtone = TONES[_mem.tone]
        mem.tmode = TMODES[_mem.tone_enable]
        mem.mode = MODES[_mem.am]
        mem.duplex = DUPLEX[_mem.duplex]
        mem.offset = int(_mem.offset) * 1000

        if mem.freq // 100 == 4:
            mem.power = POWER_LEVELS_UHF[_mem.power]
        else:
            mem.power = POWER_LEVELS_VHF[_mem.power]

        # M01 can't be disabled
        if not self._memobj.enables[byte] & bit and number != 1:
            mem.empty = True
        elif number == 1:
            mem.immutable = ['empty']

        return mem

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def set_memory(self, mem):
        bit, byte = self._bit_byte(mem.number)

        _mem = self._memobj.memory[mem.number - 1]

        _mem.freq = mem.freq // 1000
        _mem.tone = TONES.index(mem.rtone)
        _mem.tone_enable = TMODES.index(mem.tmode)
        _mem.am = MODES.index(mem.mode)
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.offset = mem.offset // 1000

        if mem.power:
            _mem.power = POWER_LEVELS_VHF.index(mem.power)
        else:
            _mem.power = 0

        if mem.empty:
            self._memobj.enables[byte] &= ~bit
        else:
            self._memobj.enables[byte] |= bit

        # TODO expose these options
        _mem.baud9600 = 0

        # These need to be cleared, otherwise strange things happen
        _mem.unknown4 = 0
        _mem.unknown4b = 0
        _mem.unknown1b = 0
        _mem.unknown2 = 0

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, 0x0B96)]

    # I didn't believe this myself, but it seems that there's a bit for
    # enabling VHF M01, but no bit for UHF01, and the enables are shifted down,
    # so that the first bit is for M02
    def _bit_byte(self, number):
        if self.VARIANT == 'VHF':
            bit = 1 << ((number - 1) % 8)
            byte = (number - 1) // 8
        else:
            bit = 1 << ((number - 2) % 8)
            byte = (number - 2) // 8

        return bit, byte


class FT8100RadioVHF(FT8100Radio):
    """Yaesu FT-8100 VHF subdevice"""
    VARIANT = "VHF"
    _memstart = 0x447
    _skipstart = 0x02D
    _enablestart = 0x04D


class FT8100RadioUHF(FT8100Radio):
    """Yaesu FT-8100 UHF subdevice"""
    VARIANT = "UHF"
    _memstart = 0x7E6
    _skipstart = 0x03A
    _enablestart = 0x05A


def _clone_out(radio):
    try:
        return __clone_out(radio)
    except Exception as e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


def __clone_out(radio):
    pipe = radio.pipe
    block_lengths = radio._block_lengths
    total_written = 0

    def _status():
        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        status.max = sum(block_lengths)
        status.cur = total_written
        radio.status_fn(status)

    start = time.time()

    pos = 0
    for block in radio._block_lengths:
        LOG.debug("\nSending %i-%i" % (pos, pos + block))
        out = radio.get_mmap()[pos:pos + block]

        # need to chew byte-by-byte here or else we lose the ACK...not sure why
        for b in out:
            pipe.write(bytes([b]))
            pipe.read(1)  # chew the echo

        ack = pipe.read(1)

        if ack[0] != yaesu_clone.CMD_ACK:
            raise Exception("block not ack'ed: %s" % repr(ack))

        total_written += len(out)
        _status()

        pos += block

    LOG.debug("Clone completed in %i seconds" % (time.time() - start))

    return True
