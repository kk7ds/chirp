#
# Copyright 2015 Marco Filippi IZ3GME <iz3gme.marco@gmail.com>
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

"""Baojie BJ-9900 management module"""

from chirp import chirp_common, util, memmap, errors, directory, bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
import struct
import time
import logging
from textwrap import dedent

LOG = logging.getLogger(__name__)

CMD_ACK = 0x06

@directory.register
class BJ9900Radio(chirp_common.CloneModeRadio,
        chirp_common.ExperimentalRadio):
    """Baojie BJ-9900"""
    VENDOR = "Baojie"
    MODEL = "BJ-9900"
    VARIANT = ""
    BAUD_RATE = 115200

    DUPLEX = ["", "-", "+", "split"]
    MODES = ["NFM", "FM"]
    TMODES = ["", "Tone", "TSQL", "DTCS", "Cross"]
    CROSS_MODES = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
        "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
    STEPS = [5.0, 6.25, 10.0, 12.5, 25.0]
    VALID_BANDS = [(109000000, 136000000), (136000000, 174000000),
        (400000000, 470000000)]

    CHARSET = list(chirp_common.CHARSET_ALPHANUMERIC)
    CHARSET.remove(" ")

    POWER_LEVELS = [
            chirp_common.PowerLevel("Low", watts=20.00),
            chirp_common.PowerLevel("High", watts=40.00)]

    _memsize = 0x18F1

    # dat file format is
    # 2 char per byte hex string
    # on CR LF terminated lines of 96 char
    # plus an empty line at the end
    _datsize = (_memsize * 2) / 96 * 98 + 2

    # block are read in same order as original sw eventhough they are not
    # in physical order
    _blocks = [
        (0x400, 0x1BFF, 0x30),
        (0x300, 0x32F, 0x30),
        (0x380, 0x3AF, 0x30),
        (0x200, 0x22F, 0x30),
        (0x240, 0x26F, 0x30),
        (0x270, 0x2A0, 0x31),
        ]

    MEM_FORMAT = """
        #seekto 0x%X;
        struct {
            u32 rxfreq;
            u16 is_rxdigtone:1,
                rxdtcs_pol:1,
                rxtone:14;
            u8  rxdtmf:4,
                spmute:4;
            u8  unknown1;
            u32 txfreq;
            u16 is_txdigtone:1,
                txdtcs_pol:1,
                txtone:14;
            u8  txdtmf:4
                pttid:4;
            u8  power:1,
                wide:1,
                compandor:1
                unknown3:5;
            u8  namelen;
            u8  name[7];
        } memory[128];
    """

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_upload = rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Remove front head.
            3. Connect data cable to radio, use the same connector where
                 head was connected to, <b>not the mic connector</b>.
            4. Click OK."""))
        rp.experimental = _(
         'This is experimental support for BJ-9900 '
         'which is still under development.\n'
         'Please ensure you have a good backup with OEM software.\n'
         'Also please send in bug and enhancement requests!\n'
         'You have been warned. Proceed at your own risk!')
        return rp

    def _read(self, addr, blocksize):
        # read a single block
        msg = struct.pack(">4sHH", "READ", addr, blocksize)
        LOG.debug("sending " + util.hexprint(msg))
        self.pipe.write(msg)
        block = self.pipe.read(blocksize)
        LOG.debug("received " + util.hexprint(block))
        if len(block) != blocksize:
            raise Exception("Unable to read block at addr %04X expected"
                            " %i got %i bytes" %
                            (addr, blocksize, len(block)))
        return block

    def _clone_in(self):
        start = time.time()

        data = ""
        status = chirp_common.Status()
        status.msg = _("Cloning from radio")
        status.max = self._memsize
        for addr_from, addr_to, blocksize in self._blocks:
            for addr in range(addr_from, addr_to, blocksize):
                data += self._read(addr, blocksize)
                status.cur = len(data)
                self.status_fn(status)

        LOG.info("Clone completed in %i seconds" % (time.time() - start))

        return memmap.MemoryMap(data)

    def _write(self, addr, block):
        # write a single block
        msg = struct.pack(">4sHH", "WRIE", addr, len(block)) + block
        LOG.debug("sending " + util.hexprint(msg))
        self.pipe.write(msg)
        data = self.pipe.read(1)
        LOG.debug("received " + util.hexprint(data))
        if ord(data) != CMD_ACK:
            raise errors.RadioError(
                "Radio refused to accept block 0x%04x" % addr)

    def _clone_out(self):
        start = time.time()

        status = chirp_common.Status()
        status.msg = _("Cloning to radio")
        status.max = self._memsize
        pos = 0
        for addr_from, addr_to, blocksize in self._blocks:
            for addr in range(addr_from, addr_to, blocksize):
                self._write(addr, self._mmap[pos:(pos + blocksize)])
                pos += blocksize
                status.cur = pos
                self.status_fn(status)

        LOG.info("Clone completed in %i seconds" % (time.time() - start))

    def sync_in(self):
        try:
            self._mmap = self._clone_in()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            self._clone_out()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        if len(self._mmap) == self._datsize:
            self._mmap = memmap.MemoryMap([
                    chr(int(self._mmap.get(i, 2), 16))
                    for i in range(0, self._datsize, 2)
                    if self._mmap.get(i, 2) != "\r\n"
                    ])
        try:
            self._memobj = bitwise.parse(
                self.MEM_FORMAT % self._memstart, self._mmap)
        except AttributeError:
            # main variant have no _memstart attribute
            return

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_dtcs_polarity = True
        rf.has_nostep_tuning = False
        rf.valid_modes = list(self.MODES)
        rf.valid_tmodes = list(self.TMODES)
        rf.valid_cross_modes = list(self.CROSS_MODES)
        rf.valid_duplexes = list(self.DUPLEX)
        rf.has_tuning_step = False
        # rf.valid_tuning_steps = list(self.STEPS)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_skips = [""]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = "".join(self.CHARSET)
        rf.valid_name_length = 7
        rf.memory_bounds = (1, 128)
        rf.can_odd_split = True
        rf.has_settings = False
        rf.has_cross = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_sub_devices = self.VARIANT == ""

        return rf

    def get_sub_devices(self):
        return [BJ9900RadioLeft(self._mmap), BJ9900RadioRight(self._mmap)]

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw("\xff" * (_mem.size() / 8))    # clean up
            _mem.namelen = 0
            return

        _mem.rxfreq = mem.freq / 10
        if mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.namelen = len(mem.name)
        for i in range(_mem.namelen):
                _mem.name[i] = ord(mem.name[i])

        rxmode = ""
        txmode = ""

        if mem.tmode == "Tone":
            txmode = "Tone"
        elif mem.tmode == "TSQL":
            rxmode = "Tone"
            txmode = "TSQL"
        elif mem.tmode == "DTCS":
            rxmode = "DTCSSQL"
            txmode = "DTCS"
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)

        if rxmode == "":
            _mem.rxdtcs_pol = 1
            _mem.is_rxdigtone = 1
            _mem.rxtone = 0x3FFF
        elif rxmode == "Tone":
            _mem.rxdtcs_pol = 0
            _mem.is_rxdigtone = 0
            _mem.rxtone = int(mem.ctone * 10)
        elif rxmode == "DTCSSQL":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = mem.dtcs
        elif rxmode == "DTCS":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = mem.rx_dtcs

        if txmode == "":
            _mem.txdtcs_pol = 1
            _mem.is_txdigtone = 1
            _mem.txtone = 0x3FFF
        elif txmode == "Tone":
            _mem.txdtcs_pol = 0
            _mem.is_txdigtone = 0
            _mem.txtone = int(mem.rtone * 10)
        elif txmode == "TSQL":
            _mem.txdtcs_pol = 0
            _mem.is_txdigtone = 0
            _mem.txtone = int(mem.ctone * 10)
        elif txmode == "DTCS":
            _mem.txdtcs_pol = 1 if mem.dtcs_polarity[0] == "R" else 0
            _mem.is_txdigtone = 1
            _mem.txtone = mem.dtcs

        if (mem.power):
            _mem.power = self.POWER_LEVELS.index(mem.power)
        _mem.wide = self.MODES.index(mem.mode)

        # not supported yet
        _mem.compandor = 0
        _mem.pttid = 0
        _mem.txdtmf = 0
        _mem.rxdtmf = 0
        _mem.spmute = 0

        # set to mimic radio behaviour
        _mem.unknown3 = 0

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if int(_mem.rxfreq) == int(_mem.txfreq) or _mem.txfreq == 0xFFFFFFFF:
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _mem.name[:_mem.namelen]:
            mem.name += chr(char)

        dtcs_pol = ["N", "N"]

        if _mem.rxtone == 0x3FFF:
            rxmode = ""
        elif _mem.is_rxdigtone == 0:
            # ctcss
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            # digital
            rxmode = "DTCS"
            mem.rx_dtcs = int(_mem.rxtone & 0x3FFF)
            if _mem.rxdtcs_pol == 1:
                dtcs_pol[1] = "R"

        if _mem.txtone == 0x3FFF:
            txmode = ""
        elif _mem.is_txdigtone == 0:
            # ctcss
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            # digital
            txmode = "DTCS"
            mem.dtcs = int(_mem.txtone & 0x3FFF)
            if _mem.txdtcs_pol == 1:
                dtcs_pol[0] = "R"

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        mem.power = self.POWER_LEVELS[_mem.power]
        mem.mode = self.MODES[_mem.wide]

        return mem

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize or \
            (len(filedata) == cls._datsize and filedata[-4:] == "\r\n\r\n")

class BJ9900RadioLeft(BJ9900Radio):
    """Baojie BJ-9900 Left VFO subdevice"""
    VARIANT = "Left"
    _memstart = 0x0


class BJ9900RadioRight(BJ9900Radio):
    """Baojie BJ-9900 Right VFO subdevice"""
    VARIANT = "Right"
    _memstart = 0xC00
