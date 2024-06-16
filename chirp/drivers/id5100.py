# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
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

from chirp import chirp_common
from chirp import directory
from chirp.drivers import icf, id31
from chirp import errors
from chirp import bitwise

LOG = logging.getLogger(__name__)


MEM_FORMAT = """
struct {
  u24  mult1:3,
       mult2:3,
       freq:18;
  u16  offset;
  u16  rtone:6,
       ctone:6,
       unknown1:1,
       mode:3;
  u8   dtcs;
  u8   tuning_step:4,
       unknown2:4;
  u8   unknown3;
  u8   tmode:4,
       duplex:2,
       dtcs_polarity:2;
  char name[16];
  u8   dv_code;
  u8   urcall[7];
  u8   rpt1call[7];
  u8   rpt2call[7];
} memory[1004];

#seekto 0xC040;
u8 usedflags[125];
#seekto 0xC0BE;
u8 skipflags[125];
#seekto 0xC13B;
u8 pskipflags[125];

#seekto 0xC1C0;
struct {
  u8 bank;
  u8 index;
} bank_info[1000];

#seekto 0xC9C0;
char ICFComment[16];
struct {
  char name[16];
} bank_names[26];
"""

TUNE_STEPS = [5.0, 6.25, 8.33, 5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0,
              5.0, 5.0, 5.0, 5.0]
MODES = ['FM', 'NFM', '2??', 'AM', 'NAM', 'DV', '6??', '7??']
TMODES = ['', 'Tone', '2??', 'TSQL', '4??', 'DTCS', 'TSQL-R', 'DTCS-R',
          'DTCS-T', 'Tone->DTCS', 'DTCS->Tone', 'Tone->Tone']
DUPLEX = ['', '-', '+']
DTCS_POL = ['NN', 'NR', 'RN', 'RR']
SPECIALS = ['144-C0', '144-C1', '430-C0', '430-C1']
MULTS = [5000, 6250, 25000 / 3.0]


@directory.register
class ID4100Radio(icf.IcomCloneModeRadio, chirp_common.IcomDstarSupport):
    VENDOR = 'Icom'
    MODEL = 'ID-4100'

    _model = b'\x38\x66\x00\x01'
    _endframe = 'Icom Inc.8F'
    _memsize = 0x2A3C0
    _ranges = [(0, _memsize, 64)]
    _raw_frames = True
    _highbit_flip = True

    _num_banks = 26
    _bank_class = id31.ID31Bank

    _can_hispeed = True
    _icf_data = {
        'MapRev': 1,
        'EtcData': 0x400001,
    }

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_ctone = True
        rf.has_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_bank = True
        rf.has_bank_index = True
        rf.has_bank_names = True
        rf.requires_call_lists = False
        rf.valid_modes = [x for x in MODES
                          if '?' not in x]
        rf.valid_tmodes = [x for x in TMODES
                           if '-' not in x and '?' not in x] + ['Cross']
        rf.valid_cross_modes = [x for x in TMODES
                                if '->' in x]
        rf.memory_bounds = (0, 999)
        rf.valid_bands = [(118000000, 174000000),
                          (375000000, 550000000)]
        rf.valid_skips = ['', 'S', 'P']
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 16
        rf.valid_tuning_steps = list(sorted(set(TUNE_STEPS)))
        rf.valid_special_chans = list(SPECIALS)
        return rf

    def _get_bank(self, loc):
        _bank = self._memobj.bank_info[loc]
        _bank.bank &= 0x1F
        if _bank.bank == 0x1F:
            return None
        else:
            return _bank.bank

    def _set_bank(self, loc, bank):
        _bank = self._memobj.bank_info[loc]
        if bank is None:
            _bank.bank = 0x1F
        else:
            _bank.bank = bank

    def _get_bank_index(self, loc):
        _bank = self._memobj.bank_info[loc]
        return _bank.index

    def _set_bank_index(self, loc, index):
        _bank = self._memobj.bank_info[loc]
        _bank.index = index

    def _get_raw_memory(self, number):
        if isinstance(number, str):
            number = 1000 + SPECIALS.index(number)
        return number, self._memobj.memory[number]

    def get_raw_memory(self, number):
        num, mem = self._get_raw_memory(number)
        return repr(mem)

    def get_memory(self, number):
        num, _mem = self._get_raw_memory(number)
        m = chirp_common.DVMemory()
        m.number = num
        if isinstance(number, str):
            m.extd_number = number
        else:
            _flg = self._memobj.usedflags[num // 8]
            _skp = self._memobj.skipflags[num // 8]
            _pskp = self._memobj.pskipflags[num // 8]
            m.empty = bool(_flg & (1 << num % 8))
            if _pskp & 1 << (num % 8):
                m.skip = 'P'
            elif _skp & 1 << (num % 8):
                m.skip = 'S'
            else:
                m.skip = ''

        mult = MULTS[_mem.mult1]
        m.freq = int(_mem.freq * mult)
        m.offset = int(_mem.offset * mult)
        m.tuning_step = TUNE_STEPS[_mem.tuning_step]
        m.name = str(_mem.name).rstrip()
        m.mode = MODES[_mem.mode]
        m.rtone = chirp_common.TONES[_mem.rtone]
        m.ctone = chirp_common.TONES[_mem.ctone]
        m.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        m.dtcs_polarity = DTCS_POL[_mem.dtcs_polarity]
        tmode = TMODES[_mem.tmode]
        if '->' in tmode:
            m.tmode = 'Cross'
            m.cross_mode = tmode
        elif '-' in tmode and 0:
            # FIXME
            m.tmode, extra = tmode.split('-')
        else:
            m.tmode = tmode
        m.duplex = DUPLEX[_mem.duplex]

        m.dv_code = _mem.dv_code
        m.dv_urcall = ''.join(
            chr(x) for x in icf.warp_byte_size(_mem.urcall, 7, 8))
        m.dv_rpt1call = ''.join(
            chr(x) for x in icf.warp_byte_size(_mem.rpt1call, 7, 8))
        m.dv_rpt2call = ''.join(
            chr(x) for x in icf.warp_byte_size(_mem.rpt2call, 7, 8))

        return m

    def set_memory(self, mem):
        num, _mem = self._get_raw_memory(mem.number)
        if num < 1000:
            _flg = self._memobj.usedflags[num // 8]
            _skp = self._memobj.skipflags[num // 8]
            _pskp = self._memobj.pskipflags[num // 8]
            mybit = 1 << (num % 8)
            _flg |= mybit
            _skp &= ~mybit
            _pskp &= ~mybit

            if mem.empty:
                return

            _flg &= ~mybit
            if mem.skip == 'S':
                _skp |= mybit
            elif mem.skip == 'P':
                _pskp |= mybit

        if chirp_common.is_6_25(mem.freq):
            mult = MULTS[1]
        elif chirp_common.is_8_33(mem.freq):
            mult = MULTS[2]
        else:
            mult = MULTS[0]
        _mem.mult1 = _mem.mult2 = MULTS.index(mult)
        _mem.freq = mem.freq / mult
        _mem.offset = mem.offset / mult
        _mem.tuning_step = TUNE_STEPS.index(mem.tuning_step)
        _mem.name = mem.name.ljust(16)
        _mem.mode = MODES.index(mem.mode)
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.ctone = chirp_common.TONES.index(mem.ctone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.dtcs_polarity = DTCS_POL.index(mem.dtcs_polarity)
        if mem.tmode == 'Cross':
            _mem.tmode = TMODES.index(mem.cross_mode)
        else:
            _mem.tmode = TMODES.index(mem.tmode)
        _mem.duplex = DUPLEX.index(mem.duplex)

        _mem.unknown1 = 0
        _mem.unknown2 = 0
        _mem.unknown3 = 0

        if isinstance(mem, chirp_common.DVMemory):
            _mem.dv_code = mem.dv_code
            _mem.urcall = list(
                icf.warp_byte_size(mem.dv_urcall.ljust(8), 8, 7))
            _mem.rpt1call = list(
                icf.warp_byte_size(mem.dv_rpt1call.ljust(8), 8, 7))
            _mem.rpt2call = list(
                icf.warp_byte_size(mem.dv_rpt2call.ljust(8), 8, 7))


@directory.register
class ID5100Radio(ID4100Radio):
    MODEL = "ID-5100"

    _model = b'\x34\x84\x00\x01'

    # This is only for MapRev=1
    _endframe = "Icom Inc.EE"

    # MapRev=1 Size is 260928 0x3FB40
    # MapRev=2 Size is 148160 0x242C0
    # MapRev=3 Size is 172928 0x2A380
    _memsize = 0x3FB40

    _ranges = [(0, _memsize, 64)]
    _raw_frames = True
    _highbit_flip = True

    def process_mmap(self):
        was_memsize = self._memsize

        # Apparently the 5100 has different reported memory sizes
        # depending on firmware version. When we're loading an image,
        # we should adjust our MapRev and _ranges to be correct for
        # saving ICF files and uploading. This also means we should
        # try to detect which version we are talking to and refuse to
        # upload an image to a radio with a mismatch.

        self._memsize = len(self._mmap)
        self._ranges = [(0, self._memsize, 64)]

        # Major (memory-format-changing) firmware versions, which
        # correspond to MapRev in an ICF file.
        maprevs = {
            0x3FB40: 1,
            0x242C0: 2,
            0x2A380: 3,
        }

        # The 5100 seems to almost behave like three different radios,
        # depending on firmware version. These are the endframes that
        # are expected for a given MapRev.
        endframes = {
            1: 'Icom Inc.EE',
            2: 'Icom Inc.0C',
            3: 'Icom Inc.8E',
        }

        if self._memsize != was_memsize:
            self._icf_data['MapRev'] = maprevs.get(self._memsize, 0)
            if self._icf_data['MapRev'] == 0:
                LOG.error('Unknown memsize %06X!', self._memsize)
                raise errors.InvalidDataError('Unsupported memory format!')
            self._endframe = endframes[self._icf_data['MapRev']]
            LOG.info('Memory length changed from %06X to %06X; new MapRev=%i',
                     was_memsize, self._memsize, self._icf_data['MapRev'])
        else:
            LOG.debug('Unchanged memsize at %06X' % self._memsize)

        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = _('This driver has been tested with v3 of the ID-5100. '
                    'If your radio is not fully updated please help by '
                    'opening a bug report with a debug log so we can add '
                    'support for the other revisions.')

        rp.pre_upload = rp.info
        rp.experimental = rp.info
        return rp
