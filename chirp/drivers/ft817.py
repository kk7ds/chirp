#
# Copyright 2012 Filippi Marco <iz3gme.marco@gmail.com>
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

"""FT817 - FT817ND - FT817ND/US management module"""

from builtins import bytes
from chirp.drivers import yaesu_clone
from chirp import chirp_common, util, memmap, errors, directory, bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
import time
import logging
from textwrap import dedent

LOG = logging.getLogger(__name__)

CMD_ACK = 0x06


@directory.register
class FT817Radio(yaesu_clone.YaesuCloneModeRadio):

    """Yaesu FT-817"""
    BAUD_RATE = 9600
    MODEL = "FT-817"
    NEEDS_COMPAT_SERIAL = False
    _model = ""
    _US_model = False

    DUPLEX = ["", "-", "+", "split"]
    # narrow modes has to be at end
    MODES = ["LSB", "USB", "CW", "CWR", "AM", "FM", "DIG", "PKT", "NCW",
             "NCWR", "NFM"]
    TMODES = ["", "Tone", "TSQL", "DTCS"]
    STEPSFM = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
    STEPSAM = [2.5, 5.0, 9.0, 10.0, 12.5, 25.0]
    STEPSSSB = [1.0, 2.5, 5.0]

    # warning ranges has to be in this exact order
    VALID_BANDS = [(100000, 33000000), (33000000, 56000000),
                   (76000000, 108000000), (108000000, 137000000),
                   (137000000, 154000000), (420000000, 470000000)]

    CHARSET = list(chirp_common.CHARSET_ASCII)
    CHARSET.remove("\\")

    _memsize = 6509
    # block 9 (130 Bytes long) is to be repeted 40 times
    _block_lengths = [2, 40, 208, 182, 208, 182, 198, 53, 130, 118, 118]

    MEM_FORMAT = """
        struct mem_struct {
            u8  tag_on_off:1,
                tag_default:1,
                unknown1:3,
                mode:3;
            u8  duplex:2,
                is_duplex:1,
                is_cwdig_narrow:1,
                is_fm_narrow:1,
                freq_range:3;
            u8  skip:1,
                unknown2:1,
                ipo:1,
                att:1,
                unknown3:4;
            u8  ssb_step:2,
                am_step:3,
                fm_step:3;
            u8  unknown4:6,
                tmode:2;
            u8  unknown5:2,
                tx_mode:3,
                tx_freq_range:3;
            u8  unknown6:1,
                unknown_toneflag:1,
                tone:6;
            u8  unknown7:1,
                dcs:7;
            ul16 rit;
            u32 freq;
            u32 offset;
            u8  name[8];
        };

        #seekto 0x4;
        struct {
            u8  fst:1,
                lock:1,
                nb:1,
                pbt:1,
                unknownb:1,
                dsp:1,
                agc:2;
            u8  vox:1,
                vlt:1,
                bk:1,
                kyr:1,
                unknown5:1,
                cw_paddle:1,
                pwr_meter_mode:2;
            u8  vfob_band_select:4,
                vfoa_band_select:4;
            u8  unknowna;
            u8  backlight:2,
                color:2,
                contrast:4;
            u8  beep_freq:1,
                beep_volume:7;
            u8  arts_beep:2,
                main_step:1,
                cw_id:1,
                scope:1,
                pkt_rate:1,
                resume_scan:2;
            u8  op_filter:2,
                lock_mode:2,
                cw_pitch:4;
            u8  sql_rf_gain:1,
                ars_144:1,
                ars_430:1,
                cw_weight:5;
            u8  cw_delay;
            u8  unknown8:1,
                sidetone:7;
            u8  batt_chg:2,
                cw_speed:6;
            u8  disable_amfm_dial:1,
                vox_gain:7;
            u8  cat_rate:2,
                emergency:1,
                vox_delay:5;
            u8  dig_mode:3,
                mem_group:1,
                unknown9:1,
                apo_time:3;
            u8  dcs_inv:2,
                unknown10:1,
                tot_time:5;
            u8  mic_scan:1,
                ssb_mic:7;
            u8  mic_key:1,
                am_mic:7;
            u8  unknown11:1,
                fm_mic:7;
            u8  unknown12:1,
                dig_mic:7;
            u8  extended_menu:1,
                pkt_mic:7;
            u8  unknown14:1,
                pkt9600_mic:7;
            il16 dig_shift;
            il16 dig_disp;
            i8  r_lsb_car;
            i8  r_usb_car;
            i8  t_lsb_car;
            i8  t_usb_car;
            u8  unknown15:2,
                menu_item:6;
            u8  unknown16:4,
                menu_sel:4;
            u16 unknown17;
            u8  art:1,
                scn_mode:2,
                dw:1,
                pri:1,
                unknown18:1,
                tx_power:2;
            u8  spl:1,
                unknown:1,
                uhf_antenna:1,
                vhf_antenna:1,
                air_antenna:1,
                bc_antenna:1,
                sixm_antenna:1,
                hf_antenna:1;
        } settings;

        #seekto 0x2A;
        struct mem_struct vfoa[15];
        struct mem_struct vfob[15];
        struct mem_struct home[4];
        struct mem_struct qmb;
        struct mem_struct mtqmb;
        struct mem_struct mtune;

        #seekto 0x3FD;
        u8 visible[25];
        u8 pmsvisible;

        #seekto 0x417;
        u8 filled[25];
        u8 pmsfilled;

        #seekto 0x431;
        struct mem_struct memory[200];
        struct mem_struct pms[2];

        #seekto 0x18cf;
        u8 callsign[7];

        #seekto 0x1979;
        struct mem_struct sixtymeterchannels[5];
    """
    _CALLSIGN_CHARSET = [chr(x) for x in list(range(ord("0"), ord("9") + 1)) +
                         list(range(ord("A"), ord("Z") + 1)) + [ord(" ")]]
    _CALLSIGN_CHARSET_REV = dict(
        list(zip(_CALLSIGN_CHARSET,
                 list(range(0, len(_CALLSIGN_CHARSET))))))

    # WARNING Index are hard wired in memory management code !!!
    SPECIAL_MEMORIES = {
        "VFOa-1.8M": -35,
        "VFOa-3.5M": -34,
        "VFOa-7M": -33,
        "VFOa-10M": -32,
        "VFOa-14M": -31,
        "VFOa-18M": -30,
        "VFOa-21M": -29,
        "VFOa-24M": -28,
        "VFOa-28M": -27,
        "VFOa-50M": -26,
        "VFOa-FM": -25,
        "VFOa-AIR": -24,
        "VFOa-144": -23,
        "VFOa-430": -22,
        "VFOa-HF": -21,
        "VFOb-1.8M": -20,
        "VFOb-3.5M": -19,
        "VFOb-7M": -18,
        "VFOb-10M": -17,
        "VFOb-14M": -16,
        "VFOb-18M": -15,
        "VFOb-21M": -14,
        "VFOb-24M": -13,
        "VFOb-28M": -12,
        "VFOb-50M": -11,
        "VFOb-FM": -10,
        "VFOb-AIR": -9,
        "VFOb-144M": -8,
        "VFOb-430M": -7,
        "VFOb-HF": -6,
        "HOME HF": -5,
        "HOME 50M": -4,
        "HOME 144M": -3,
        "HOME 430M": -2,
        "QMB": -1,
    }
    FIRST_VFOB_INDEX = -6
    LAST_VFOB_INDEX = -20
    FIRST_VFOA_INDEX = -21
    LAST_VFOA_INDEX = -35

    SPECIAL_PMS = {
        "PMS-L": -37,
        "PMS-U": -36,
    }
    LAST_PMS_INDEX = -37

    SPECIAL_MEMORIES.update(SPECIAL_PMS)

    SPECIAL_MEMORIES_REV = dict(list(zip(list(SPECIAL_MEMORIES.values()),
                                         list(SPECIAL_MEMORIES.keys()))))

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to ACC jack.
            3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys while
                 turning the radio on ("CLONE MODE" will appear on the
                 display).
            4. <b>After clicking OK</b>, press the [A] key to send image."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to ACC jack.
            3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys while
                 turning the radio on ("CLONE MODE" will appear on the
                 display).
            4. Press the [C] key ("RX" will appear on the LCD)."""))
        return rp

    def _read(self, block, blocknum, lastblock):
        # be very patient at first block
        if blocknum == 0:
            attempts = 60
        else:
            attempts = 5
        for _i in range(0, attempts):
            data = self.pipe.read(block + 2)
            if data:
                break
            time.sleep(0.5)
        if len(data) == block + 2 and data[0] == blocknum:
            checksum = yaesu_clone.YaesuChecksum(1, block)
            if checksum.get_existing(data) != \
                    checksum.get_calculated(data):
                raise Exception("Checksum Failed [%02X<>%02X] block %02X" %
                                (checksum.get_existing(data),
                                 checksum.get_calculated(data), blocknum))
            # Chew away the block number and the checksum
            data = data[1:block + 1]
        else:
            if lastblock and self._US_model:
                raise Exception(_("Unable to read last block. "
                                  "This often happens when the selected model "
                                  "is US but the radio is a non-US one (or "
                                  "widebanded). Please choose the correct "
                                  "model and try again."))
            else:
                raise Exception("Unable to read block %02X expected %i got %i"
                                % (blocknum, block + 2, len(data)))

        LOG.debug("Read %i" % len(data))
        return data

    def _clone_in(self):
        # Be very patient with the radio
        self.pipe.timeout = 2

        start = time.time()

        data = bytes(b"")
        blocks = 0
        status = chirp_common.Status()
        status.msg = _("Cloning from radio")
        nblocks = len(self._block_lengths) + 39
        status.max = nblocks
        for block in self._block_lengths:
            if blocks == 8:
                # repeated read of 40 block same size (memory area)
                repeat = 40
            else:
                repeat = 1
            for _i in range(0, repeat):
                data += self._read(block, blocks, blocks == nblocks - 1)
                self.pipe.write(bytes([CMD_ACK]))
                blocks += 1
                status.cur = blocks
                self.status_fn(status)

        if not self._US_model:
            status.msg = _("Clone completed, checking for spurious bytes")
            self.status_fn(status)
            moredata = self.pipe.read(2)
            if moredata:
                raise Exception(
                    _("Radio sent data after the last awaited block, "
                      "this happens when the selected model is a non-US "
                      "but the radio is a US one. "
                      "Please choose the correct model and try again."))

        LOG.info("Clone completed in %i seconds" % (time.time() - start))

        return memmap.MemoryMapBytes(data)

    def _clone_out(self):
        delay = 0.5
        start = time.time()

        blocks = 0
        pos = 0
        status = chirp_common.Status()
        status.msg = _("Cloning to radio")
        status.max = len(self._block_lengths) + 39
        mmap = self.get_mmap().get_byte_compatible()
        for block in self._block_lengths:
            if blocks == 8:
                # repeated read of 40 block same size (memory area)
                repeat = 40
            else:
                repeat = 1
            for _i in range(0, repeat):
                time.sleep(0.01)
                checksum = yaesu_clone.YaesuChecksum(pos, pos + block - 1)
                LOG.debug("Block %i - will send from %i to %i byte " %
                          (blocks, pos, pos + block))
                LOG.debug(util.hexprint(chr(blocks)))
                LOG.debug(util.hexprint(self.get_mmap()[pos:pos + block]))
                LOG.debug(util.hexprint(chr(checksum.get_calculated(mmap))))
                self.pipe.write(bytes([blocks]))
                self.pipe.write(mmap[pos:pos + block])
                self.pipe.write(bytes([checksum.get_calculated(
                    self.get_mmap())]))
                buf = self.pipe.read(1)
                if not buf or buf[0] != CMD_ACK:
                    time.sleep(delay)
                    buf = self.pipe.read(1)
                if not buf or buf[0] != CMD_ACK:
                    LOG.debug(util.hexprint(buf))
                    raise Exception(_("Radio did not ack block %i") % blocks)
                pos += block
                blocks += 1
                status.cur = blocks
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
        self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_dtcs_polarity = False
        rf.has_nostep_tuning = True
        rf.valid_modes = list(set(self.MODES))
        rf.valid_tmodes = list(self.TMODES)
        rf.valid_duplexes = list(self.DUPLEX)
        rf.valid_tuning_steps = list(self.STEPSFM)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_skips = ["", "S"]
        rf.valid_power_levels = []
        rf.valid_characters = "".join(self.CHARSET)
        rf.valid_name_length = 8
        rf.valid_special_chans = sorted(self.SPECIAL_MEMORIES.keys())
        rf.memory_bounds = (1, 200)
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_settings = True
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_duplex(self, mem, _mem):
        if _mem.is_duplex == 1:
            mem.duplex = self.DUPLEX[_mem.duplex]
        else:
            mem.duplex = ""

    def _get_tmode(self, mem, _mem):
        mem.tmode = self.TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]

    def _set_duplex(self, mem, _mem):
        _mem.duplex = self.DUPLEX.index(mem.duplex)
        _mem.is_duplex = mem.duplex != ""

    def _set_tmode(self, mem, _mem):
        _mem.tmode = self.TMODES.index(mem.tmode)
        # have to put this bit to 0 otherwise we get strange display in tone
        # frequency (menu 83). See bug #88 and #163
        _mem.unknown_toneflag = 0
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)

    def get_memory(self, number):
        if isinstance(number, str):
            return self._get_special(number)
        elif number < 0:
            # I can't stop delete operation from loosing extd_number but
            # I know how to get it back
            return self._get_special(self.SPECIAL_MEMORIES_REV[number])
        else:
            return self._get_normal(number)

    def set_memory(self, memory):
        if memory.number < 0:
            return self._set_special(memory)
        else:
            return self._set_normal(memory)

    def _get_special(self, number):
        mem = chirp_common.Memory()
        mem.number = self.SPECIAL_MEMORIES[number]
        mem.extd_number = number

        if mem.number in range(self.FIRST_VFOA_INDEX,
                               self.LAST_VFOA_INDEX - 1,
                               -1):
            _mem = self._memobj.vfoa[-self.LAST_VFOA_INDEX + mem.number]
            immutable = ["number", "skip", "extd_number",
                         "name", "dtcs_polarity", "power", "comment"]
        elif mem.number in range(self.FIRST_VFOB_INDEX,
                                 self.LAST_VFOB_INDEX - 1,
                                 -1):
            _mem = self._memobj.vfob[-self.LAST_VFOB_INDEX + mem.number]
            immutable = ["number", "skip", "extd_number",
                         "name", "dtcs_polarity", "power", "comment"]
        elif mem.number in range(-2, -6, -1):
            _mem = self._memobj.home[5 + mem.number]
            immutable = ["number", "skip", "extd_number",
                         "name", "dtcs_polarity", "power", "comment"]
        elif mem.number == -1:
            _mem = self._memobj.qmb
            immutable = ["number", "skip", "extd_number",
                         "name", "dtcs_polarity", "power", "comment"]
        elif mem.number in list(self.SPECIAL_PMS.values()):
            bitindex = -self.LAST_PMS_INDEX + mem.number
            used = (self._memobj.pmsvisible >> bitindex) & 0x01
            valid = (self._memobj.pmsfilled >> bitindex) & 0x01
            if not used:
                mem.empty = True
            if not valid:
                mem.empty = True
                return mem
            _mem = self._memobj.pms[-self.LAST_PMS_INDEX + mem.number]
            immutable = ["number", "skip", "rtone", "ctone", "extd_number",
                         "dtcs", "tmode", "cross_mode", "dtcs_polarity",
                         "power", "duplex", "offset", "comment"]
        else:
            raise Exception("Sorry, special memory index %i " % mem.number +
                            "unknown you hit a bug!!")

        mem = self._get_memory(mem, _mem)
        mem.immutable = immutable

        return mem

    def _set_special(self, mem):
        if mem.empty and mem.number not in list(self.SPECIAL_PMS.values()):
            # can't delete special memories!
            raise Exception("Sorry, special memory can't be deleted")

        cur_mem = self._get_special(self.SPECIAL_MEMORIES_REV[mem.number])

        # TODO add frequency range check for vfo and home memories
        if mem.number in range(self.FIRST_VFOA_INDEX,
                               self.LAST_VFOA_INDEX - 1,
                               -1):
            _mem = self._memobj.vfoa[-self.LAST_VFOA_INDEX + mem.number]
        elif mem.number in range(self.FIRST_VFOB_INDEX,
                                 self.LAST_VFOB_INDEX - 1,
                                 -1):
            _mem = self._memobj.vfob[-self.LAST_VFOB_INDEX + mem.number]
        elif mem.number in range(-2, -6, -1):
            _mem = self._memobj.home[5 + mem.number]
        elif mem.number == -1:
            _mem = self._memobj.qmb
        elif mem.number in list(self.SPECIAL_PMS.values()):
            # this case has to be last because 817 pms keys overlap with
            # 857 derived class other special memories
            bitindex = -self.LAST_PMS_INDEX + mem.number
            wasused = (self._memobj.pmsvisible >> bitindex) & 0x01
            wasvalid = (self._memobj.pmsfilled >> bitindex) & 0x01
            if mem.empty:
                if wasvalid and not wasused:
                    # pylint get confused by &= operator
                    self._memobj.pmsfilled = self._memobj.pmsfilled & \
                        ~ (1 << bitindex)
                # pylint get confused by &= operator
                self._memobj.pmsvisible = self._memobj.pmsvisible & \
                    ~ (1 << bitindex)
                return
            # pylint get confused by |= operator
            self._memobj.pmsvisible = self._memobj.pmsvisible | 1 << bitindex
            self._memobj.pmsfilled = self._memobj.pmsfilled | 1 << bitindex
            _mem = self._memobj.pms[-self.LAST_PMS_INDEX + mem.number]
        else:
            raise Exception("Sorry, special memory index %i " % mem.number +
                            "unknown you hit a bug!!")

        for key in cur_mem.immutable:
            if key != "extd_number":
                if cur_mem.__dict__[key] != mem.__dict__[key]:
                    raise errors.RadioError("Editing field `%s' " % key +
                                            "is not supported on this channel")

        self._set_memory(mem, _mem)

    def _get_normal(self, number):
        _mem = self._memobj.memory[number - 1]
        used = (self._memobj.visible[(number - 1) / 8] >> (number - 1) % 8) \
            & 0x01
        valid = (self._memobj.filled[(number - 1) / 8] >> (number - 1) % 8) \
            & 0x01

        mem = chirp_common.Memory()
        mem.number = number
        if not used:
            mem.empty = True
            if not valid or _mem.freq == 0xffffffff:
                return mem

        return self._get_memory(mem, _mem)

    def _set_normal(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        wasused = (self._memobj.visible[(mem.number - 1) / 8] >>
                   (mem.number - 1) % 8) & 0x01
        wasvalid = (self._memobj.filled[(mem.number - 1) / 8] >>
                    (mem.number - 1) % 8) & 0x01

        if mem.empty:
            if mem.number == 1:
                # as Dan says "yaesus are not good about that :("
                # if you ulpoad an empty image you can brick your radio
                raise Exception("Sorry, can't delete first memory")
            if wasvalid and not wasused:
                self._memobj.filled[(mem.number - 1) // 8] &= \
                    ~(1 << (mem.number - 1) % 8)
                _mem.set_raw("\xFF" * (_mem.size() // 8))    # clean up
            self._memobj.visible[(mem.number - 1) // 8] &= \
                ~(1 << (mem.number - 1) % 8)
            return
        if not wasvalid:
            _mem.set_raw("\x00" * (_mem.size() // 8))    # clean up

        self._memobj.visible[(mem.number - 1) // 8] |= (
            1 << (mem.number - 1) % 8)
        self._memobj.filled[(mem.number - 1) // 8] |= (
            1 << (mem.number - 1) % 8)
        self._set_memory(mem, _mem)

    def _get_memory(self, mem, _mem):
        mem.freq = int(_mem.freq) * 10
        mem.offset = int(_mem.offset) * 10
        self._get_duplex(mem, _mem)
        mem.mode = self.MODES[_mem.mode]
        if mem.mode == "FM":
            if _mem.is_fm_narrow == 1:
                mem.mode = "NFM"
            mem.tuning_step = self.STEPSFM[_mem.fm_step]
        elif mem.mode == "AM":
            mem.tuning_step = self.STEPSAM[_mem.am_step]
        elif mem.mode == "CW" or mem.mode == "CWR":
            if _mem.is_cwdig_narrow == 1:
                mem.mode = "N" + mem.mode
            mem.tuning_step = self.STEPSSSB[_mem.ssb_step]
        else:
            try:
                mem.tuning_step = self.STEPSSSB[_mem.ssb_step]
            except IndexError:
                pass
        mem.skip = _mem.skip and "S" or ""
        self._get_tmode(mem, _mem)

        if _mem.tag_on_off == 1:
            for i in _mem.name:
                if i == 0xFF:
                    break
                if chr(i) in self.CHARSET:
                    mem.name += chr(i)
                else:
                    # radio have some graphical chars that are not supported
                    # we replace those with a *
                    LOG.info("Replacing char %x with *" % i)
                    mem.name += "*"
            mem.name = mem.name.rstrip()
        else:
            mem.name = ""

        mem.extra = RadioSettingGroup("extra", "Extra")
        ipo = RadioSetting("ipo", "IPO",
                           RadioSettingValueBoolean(bool(_mem.ipo)))
        ipo.set_doc("Bypass preamp")
        mem.extra.append(ipo)

        att = RadioSetting("att", "ATT",
                           RadioSettingValueBoolean(bool(_mem.att)))
        att.set_doc("10dB front end attenuator")
        mem.extra.append(att)

        return mem

    def _set_memory(self, mem, _mem):
        if len(mem.name) > 0:   # not supported in chirp
                                # so I make label visible if have one
            _mem.tag_on_off = 1
        else:
            _mem.tag_on_off = 0
        _mem.tag_default = 0       # never use default label "CH-nnn"
        self._set_duplex(mem, _mem)
        if mem.mode[0] == "N":    # is it narrow?
            _mem.mode = self.MODES.index(mem.mode[1:])
            # here I suppose it's safe to set both
            _mem.is_fm_narrow = _mem.is_cwdig_narrow = 1
        else:
            _mem.mode = self.MODES.index(mem.mode)
            # here I suppose it's safe to set both
            _mem.is_fm_narrow = _mem.is_cwdig_narrow = 0
        i = 0
        for lo, hi in self.VALID_BANDS:
            if mem.freq > lo and mem.freq < hi:
                break
            i += 1
        _mem.freq_range = i
        # all this should be safe also when not in split but ...
        if mem.duplex == "split":
            _mem.tx_mode = _mem.mode
            i = 0
            for lo, hi in self.VALID_BANDS:
                if mem.offset >= lo and mem.offset < hi:
                    break
                i += 1
            _mem.tx_freq_range = i
        _mem.skip = mem.skip == "S"
        self._set_tmode(mem, _mem)
        try:
            _mem.ssb_step = self.STEPSSSB.index(mem.tuning_step)
        except ValueError:
            pass
        try:
            _mem.am_step = self.STEPSAM.index(mem.tuning_step)
        except ValueError:
            pass
        try:
            _mem.fm_step = self.STEPSFM.index(mem.tuning_step)
        except ValueError:
            pass
        _mem.rit = 0    # not supported in chirp
        _mem.freq = mem.freq / 10
        _mem.offset = mem.offset / 10
        # there are ft857D that have problems with short labels, see bug #937
        # some of the radio fill with 0xff and some with blanks
        # the latter is safe for all ft8x7 radio
        # so why should i do it only for some?
        for i in range(0, 8):
            _mem.name[i] = ord(mem.name.ljust(8)[i])

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)

        lo, hi = self.VALID_BANDS[2]    # this is fm broadcasting
        if mem.freq >= lo and mem.freq <= hi:
            if mem.mode != "FM":
                msgs.append(chirp_common.ValidationError(
                    "Only FM is supported in this band"))
        # TODO check that step is valid in current mode
        return msgs

    @classmethod
    def match_model(cls, filedata, filename):
        return len(filedata) == cls._memsize

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        cw = RadioSettingGroup("cw", "CW")
        packet = RadioSettingGroup("packet", "Digital & packet")
        panel = RadioSettingGroup("panel", "Panel settings")
        extended = RadioSettingGroup("extended", "Extended")
        antenna = RadioSettingGroup("antenna", "Antenna selection")
        panelcontr = RadioSettingGroup("panelcontr", "Panel controls")

        top = RadioSettings(basic, cw, packet,
                            panelcontr, panel, extended, antenna)

        rs = RadioSetting("ars_144", "144 ARS",
                          RadioSettingValueBoolean(_settings.ars_144))
        basic.append(rs)
        rs = RadioSetting("ars_430", "430 ARS",
                          RadioSettingValueBoolean(_settings.ars_430))
        basic.append(rs)
        rs = RadioSetting("pkt9600_mic", "Paket 9600 mic level",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.pkt9600_mic))
        packet.append(rs)
        options = ["enable", "disable"]
        rs = RadioSetting("disable_amfm_dial", "AM&FM Dial",
                          RadioSettingValueList(options,
                                                options[
                                                    _settings.disable_amfm_dial
                                                ]))
        panel.append(rs)
        rs = RadioSetting("am_mic", "AM mic level",
                          RadioSettingValueInteger(0, 100, _settings.am_mic))
        basic.append(rs)
        options = ["OFF", "1h", "2h", "3h", "4h", "5h", "6h"]
        rs = RadioSetting("apo_time", "APO time",
                          RadioSettingValueList(options,
                                                options[_settings.apo_time]))
        basic.append(rs)
        options = ["OFF", "Range", "All"]
        rs = RadioSetting("arts_beep", "ARTS beep",
                          RadioSettingValueList(options,
                                                options[_settings.arts_beep]))
        basic.append(rs)
        options = ["OFF", "ON", "Auto"]
        rs = RadioSetting("backlight", "Backlight",
                          RadioSettingValueList(options,
                                                options[_settings.backlight]))
        panel.append(rs)
        options = ["6h", "8h", "10h"]
        rs = RadioSetting("batt_chg", "Battery charge",
                          RadioSettingValueList(options,
                                                options[_settings.batt_chg]))
        basic.append(rs)
        options = ["440Hz", "880Hz"]
        rs = RadioSetting("beep_freq", "Beep frequency",
                          RadioSettingValueList(options,
                                                options[_settings.beep_freq]))
        panel.append(rs)
        rs = RadioSetting("beep_volume", "Beep volume",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.beep_volume))
        panel.append(rs)
        options = ["4800", "9600", "38400"]
        rs = RadioSetting("cat_rate", "CAT rate",
                          RadioSettingValueList(options,
                                                options[_settings.cat_rate]))
        basic.append(rs)
        options = ["Blue", "Amber", "Violet"]
        rs = RadioSetting("color", "Color",
                          RadioSettingValueList(options,
                                                options[_settings.color]))
        panel.append(rs)
        rs = RadioSetting("contrast", "Contrast",
                          RadioSettingValueInteger(1, 12,
                                                   _settings.contrast - 1))
        panel.append(rs)
        rs = RadioSetting("cw_delay", "CW delay (*10 ms)",
                          RadioSettingValueInteger(1, 250,
                                                   _settings.cw_delay))
        cw.append(rs)
        rs = RadioSetting("cw_id", "CW id",
                          RadioSettingValueBoolean(_settings.cw_id))
        cw.append(rs)
        options = ["Normal", "Reverse"]
        rs = RadioSetting("cw_paddle", "CW paddle",
                          RadioSettingValueList(options,
                                                options[_settings.cw_paddle]))
        cw.append(rs)
        options = ["%i Hz" % i for i in range(300, 1001, 50)]
        rs = RadioSetting("cw_pitch", "CW pitch",
                          RadioSettingValueList(options,
                                                options[_settings.cw_pitch]))
        cw.append(rs)
        options = ["%i wpm" % i for i in range(4, 61)]
        rs = RadioSetting("cw_speed", "CW speed",
                          RadioSettingValueList(options,
                                                options[_settings.cw_speed]))
        cw.append(rs)
        options = ["1:%1.1f" % (i / 10) for i in range(25, 46, 1)]
        rs = RadioSetting("cw_weight", "CW weight",
                          RadioSettingValueList(options,
                                                options[_settings.cw_weight]))
        cw.append(rs)
        rs = RadioSetting("dig_disp", "Dig disp (*10 Hz)",
                          RadioSettingValueInteger(-300, 300,
                                                   _settings.dig_disp))
        packet.append(rs)
        rs = RadioSetting("dig_mic", "Dig mic",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.dig_mic))
        packet.append(rs)
        options = ["RTTY", "PSK31-L", "PSK31-U", "USER-L", "USER-U"]
        rs = RadioSetting("dig_mode", "Dig mode",
                          RadioSettingValueList(options,
                                                options[_settings.dig_mode]))
        packet.append(rs)
        rs = RadioSetting("dig_shift", "Dig shift (*10 Hz)",
                          RadioSettingValueInteger(-300, 300,
                                                   _settings.dig_shift))
        packet.append(rs)
        rs = RadioSetting("fm_mic", "FM mic",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.fm_mic))
        basic.append(rs)
        options = ["Dial", "Freq", "Panel"]
        rs = RadioSetting("lock_mode", "Lock mode",
                          RadioSettingValueList(options,
                                                options[_settings.lock_mode]))
        panel.append(rs)
        options = ["Fine", "Coarse"]
        rs = RadioSetting("main_step", "Main step",
                          RadioSettingValueList(options,
                                                options[_settings.main_step]))
        panel.append(rs)
        rs = RadioSetting("mem_group", "Mem group",
                          RadioSettingValueBoolean(_settings.mem_group))
        basic.append(rs)
        rs = RadioSetting("mic_key", "Mic key",
                          RadioSettingValueBoolean(_settings.mic_key))
        cw.append(rs)
        rs = RadioSetting("mic_scan", "Mic scan",
                          RadioSettingValueBoolean(_settings.mic_scan))
        basic.append(rs)
        options = ["Off", "SSB", "CW"]
        rs = RadioSetting("op_filter", "Optional filter",
                          RadioSettingValueList(options,
                                                options[_settings.op_filter]))
        basic.append(rs)
        rs = RadioSetting("pkt_mic", "Packet mic",
                          RadioSettingValueInteger(0, 100, _settings.pkt_mic))
        packet.append(rs)
        options = ["1200", "9600"]
        rs = RadioSetting("pkt_rate", "Packet rate",
                          RadioSettingValueList(options,
                                                options[_settings.pkt_rate]))
        packet.append(rs)
        options = ["Off", "3 sec", "5 sec", "10 sec"]
        rs = RadioSetting("resume_scan", "Resume scan",
                          RadioSettingValueList(options,
                                                options[_settings.resume_scan])
                          )
        basic.append(rs)
        options = ["Cont", "Chk"]
        rs = RadioSetting("scope", "Scope",
                          RadioSettingValueList(options,
                                                options[_settings.scope]))
        basic.append(rs)
        rs = RadioSetting("sidetone", "Sidetone",
                          RadioSettingValueInteger(0, 100, _settings.sidetone))
        cw.append(rs)
        options = ["RF-Gain", "Squelch"]
        rs = RadioSetting("sql_rf_gain", "Squelch/RF-Gain",
                          RadioSettingValueList(options,
                                                options[_settings.sql_rf_gain])
                          )
        panel.append(rs)
        rs = RadioSetting("ssb_mic", "SSB Mic",
                          RadioSettingValueInteger(0, 100, _settings.ssb_mic))
        basic.append(rs)
        options = ["%i" % i for i in range(0, 21)]
        options[0] = "Off"
        rs = RadioSetting("tot_time", "Time-out timer",
                          RadioSettingValueList(options,
                                                options[_settings.tot_time]))
        basic.append(rs)
        rs = RadioSetting("vox_delay", "VOX delay (*100 ms)",
                          RadioSettingValueInteger(1, 25, _settings.vox_delay))
        basic.append(rs)
        rs = RadioSetting("vox_gain", "VOX Gain",
                          RadioSettingValueInteger(0, 100, _settings.vox_gain))
        basic.append(rs)
        rs = RadioSetting("extended_menu", "Extended menu",
                          RadioSettingValueBoolean(_settings.extended_menu))
        extended.append(rs)
        options = ["Tn-Rn", "Tn-Riv", "Tiv-Rn", "Tiv-Riv"]
        rs = RadioSetting("dcs_inv", "DCS coding",
                          RadioSettingValueList(options,
                                                options[_settings.dcs_inv]))
        extended.append(rs)
        rs = RadioSetting("r_lsb_car", "LSB Rx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.r_lsb_car))
        extended.append(rs)
        rs = RadioSetting("r_usb_car", "USB Rx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.r_usb_car))
        extended.append(rs)
        rs = RadioSetting("t_lsb_car", "LSB Tx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.t_lsb_car))
        extended.append(rs)
        rs = RadioSetting("t_usb_car", "USB Tx carrier point (*10 Hz)",
                          RadioSettingValueInteger(-30, 30,
                                                   _settings.t_usb_car))
        extended.append(rs)

        options = ["Hi", "L3", "L2", "L1"]
        rs = RadioSetting("tx_power", "TX power",
                          RadioSettingValueList(options,
                                                options[_settings.tx_power]))
        basic.append(rs)

        options = ["Front", "Rear"]
        rs = RadioSetting("hf_antenna", "HF",
                          RadioSettingValueList(options,
                                                options[_settings.hf_antenna]))
        antenna.append(rs)
        rs = RadioSetting("sixm_antenna", "6M",
                          RadioSettingValueList(options,
                                                options[_settings.sixm_antenna]
                                                ))
        antenna.append(rs)
        rs = RadioSetting("bc_antenna", "Broadcasting",
                          RadioSettingValueList(options,
                                                options[_settings.bc_antenna]))
        antenna.append(rs)
        rs = RadioSetting("air_antenna", "Air band",
                          RadioSettingValueList(options,
                                                options[_settings.air_antenna])
                          )
        antenna.append(rs)
        rs = RadioSetting("vhf_antenna", "VHF",
                          RadioSettingValueList(options,
                                                options[_settings.vhf_antenna])
                          )
        antenna.append(rs)
        rs = RadioSetting("uhf_antenna", "UHF",
                          RadioSettingValueList(options,
                                                options[_settings.uhf_antenna])
                          )
        antenna.append(rs)

        st = RadioSettingValueString(0, 7, ''.join([self._CALLSIGN_CHARSET[x]
                                                   for x in self._memobj.
                                                   callsign]))
        st.set_charset(self._CALLSIGN_CHARSET)
        rs = RadioSetting("callsign", "Callsign", st)
        cw.append(rs)

        rs = RadioSetting("spl", "Split",
                          RadioSettingValueBoolean(_settings.spl))
        panelcontr.append(rs)
        options = ["None", "Up", "Down"]
        rs = RadioSetting("scn_mode", "Scan mode",
                          RadioSettingValueList(options,
                                                options[_settings.scn_mode]))
        panelcontr.append(rs)
        rs = RadioSetting("pri", "Priority",
                          RadioSettingValueBoolean(_settings.pri))
        panelcontr.append(rs)
        rs = RadioSetting("dw", "Dual watch",
                          RadioSettingValueBoolean(_settings.dw))
        panelcontr.append(rs)
        rs = RadioSetting("art", "Auto-range transponder",
                          RadioSettingValueBoolean(_settings.art))
        panelcontr.append(rs)
        rs = RadioSetting("nb", "Noise blanker",
                          RadioSettingValueBoolean(_settings.nb))
        panelcontr.append(rs)
        options = ["Auto", "Fast", "Slow", "Off"]
        rs = RadioSetting("agc", "AGC",
                          RadioSettingValueList(options, options[_settings.agc]
                                                ))
        panelcontr.append(rs)
        options = ["PWR", "ALC", "SWR", "MOD"]
        rs = RadioSetting("pwr_meter_mode", "Power meter mode",
                          RadioSettingValueList(options,
                                                options[
                                                    _settings.pwr_meter_mode
                                                ]))
        panelcontr.append(rs)
        rs = RadioSetting("vox", "Vox",
                          RadioSettingValueBoolean(_settings.vox))
        panelcontr.append(rs)
        rs = RadioSetting("bk", "Semi break-in",
                          RadioSettingValueBoolean(_settings.bk))
        cw.append(rs)
        rs = RadioSetting("kyr", "Keyer",
                          RadioSettingValueBoolean(_settings.kyr))
        cw.append(rs)
        options = ["enabled", "disabled"]
        rs = RadioSetting("fst", "Fast",
                          RadioSettingValueList(options, options[_settings.fst]
                                                ))
        panelcontr.append(rs)
        options = ["enabled", "disabled"]
        rs = RadioSetting("lock", "Lock",
                          RadioSettingValueList(options,
                                                options[_settings.lock]))
        panelcontr.append(rs)

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            try:
                if "." in element.get_name():
                    bits = element.get_name().split(".")
                    obj = self._memobj
                    for bit in bits[:-1]:
                        obj = getattr(obj, bit)
                    setting = bits[-1]
                else:
                    obj = _settings
                    setting = element.get_name()
                try:
                    LOG.debug("Setting %s(%s) <= %s" % (setting,
                                                        getattr(obj, setting),
                                                        element.value))
                except AttributeError:
                    LOG.debug("Setting %s <= %s" % (setting, element.value))
                if setting == "contrast":
                    setattr(obj, setting, int(element.value) + 1)
                elif setting == "callsign":
                    self._memobj.callsign = \
                        [self._CALLSIGN_CHARSET_REV[x] for x in
                         str(element.value)]
                else:
                    setattr(obj, setting, element.value)
            except:
                LOG.debug(element.get_name())
                raise


@directory.register
class FT817NDRadio(FT817Radio):

    """Yaesu FT-817ND"""
    MODEL = "FT-817ND"

    _model = ""
    _memsize = 6521
    # block 9 (130 Bytes long) is to be repeted 40 times
    _block_lengths = [2, 40, 208, 182, 208, 182, 198, 53, 130, 118, 130]


@directory.register
class FT817NDUSRadio(FT817Radio):

    """Yaesu FT-817ND (US version)"""
    # seems that radios configured for 5MHz operations send one paket
    # more than others so we have to distinguish sub models
    MODEL = "FT-817ND (US)"

    _model = ""
    _US_model = True
    _memsize = 6651
    # block 9 (130 Bytes long) is to be repeted 40 times
    _block_lengths = [2, 40, 208, 182, 208, 182, 198, 53, 130, 118, 130, 130]

    SPECIAL_60M = {
        "M-601": -42,
        "M-602": -41,
        "M-603": -40,
        "M-604": -39,
        "M-605": -38,
    }
    LAST_SPECIAL60M_INDEX = -42

    SPECIAL_MEMORIES = dict(FT817Radio.SPECIAL_MEMORIES)
    SPECIAL_MEMORIES.update(SPECIAL_60M)

    SPECIAL_MEMORIES_REV = dict(list(zip(list(SPECIAL_MEMORIES.values()),
                                         list(SPECIAL_MEMORIES.keys()))))

    def _get_special_60m(self, number):
        mem = chirp_common.Memory()
        mem.number = self.SPECIAL_60M[number]
        mem.extd_number = number

        _mem = self._memobj.sixtymeterchannels[-self.LAST_SPECIAL60M_INDEX +
                                               mem.number]

        mem = self._get_memory(mem, _mem)

        mem.immutable = ["number", "rtone", "ctone",
                         "extd_number", "name", "dtcs", "tmode", "cross_mode",
                         "dtcs_polarity", "power", "duplex", "offset",
                         "comment", "empty"]

        return mem

    def _set_special_60m(self, mem):
        if mem.empty:
            # can't delete 60M memories!
            raise Exception("Sorry, 60M memory can't be deleted")

        cur_mem = self._get_special_60m(self.SPECIAL_MEMORIES_REV[mem.number])

        for key in cur_mem.immutable:
            if cur_mem.__dict__[key] != mem.__dict__[key]:
                raise errors.RadioError("Editing field `%s' " % key +
                                        "is not supported on M-60x channels")

        if mem.mode not in ["USB", "LSB", "CW", "CWR", "NCW", "NCWR", "DIG"]:
            raise errors.RadioError("Mode {mode} is not valid "
                                    "in 60m channels".format(mode=mem.mode))
        _mem = self._memobj.sixtymeterchannels[-self.LAST_SPECIAL60M_INDEX +
                                               mem.number]
        self._set_memory(mem, _mem)

    def get_memory(self, number):
        if number in list(self.SPECIAL_60M.keys()):
            return self._get_special_60m(number)
        elif (number < 0 and
              self.SPECIAL_MEMORIES_REV[number] in
              list(self.SPECIAL_60M.keys())):
            # I can't stop delete operation from loosing extd_number but
            # I know how to get it back
            return self._get_special_60m(self.SPECIAL_MEMORIES_REV[number])
        else:
            return FT817Radio.get_memory(self, number)

    def set_memory(self, memory):
        if memory.number in list(self.SPECIAL_60M.values()):
            return self._set_special_60m(memory)
        else:
            return FT817Radio.set_memory(self, memory)

    def get_settings(self):
        top = FT817Radio.get_settings(self)
        basic = top[0]
        rs = RadioSetting("emergency", "Emergency",
                          RadioSettingValueBoolean(
                              self._memobj.settings.emergency))
        basic.append(rs)
        return top
