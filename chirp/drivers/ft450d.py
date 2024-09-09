# Copyright 2018 by Rick DeWitt (aa0rd@yahoo.com) V2.0
# PY3 Compliant release.
# Thanks to Filippi Marco <iz3gme.marco@gmail.com> for Yaesu processes
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

"""FT450D Yaesu Radio Driver"""

from chirp.drivers import yaesu_clone
from chirp import chirp_common, util, memmap, errors, directory, bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings
import time
import struct
import logging
import itertools

LOG = logging.getLogger(__name__)

CMD_ACK = b'\x06'
# can't update chirp_common data modes for this radio, so for weird
# data modes we will use main mode of DIG and then have these sub-modes
DATA_MODES = ["USER-L", "USER-U", "RTTY", "N/A"]
T_STEPS = sorted(list(chirp_common.TUNING_STEPS))
T_STEPS.remove(30.0)
T_STEPS.remove(100.0)
T_STEPS.remove(125.0)
T_STEPS.remove(200.0)


def filters_for_mode(mode):
    if mode in ("USB", "LSB"):
        return "sb_width", ["1.8 kHz", "2.4 kHz", "3.0 kHz"]
    elif mode in ("CW", "CWR"):
        return "cw_width", ["300 Hz", "500 kHz", "2.4 kHz"]
    elif mode == "DIG":
        return "sb_width", ["300 Hz", "2.4 kHz", "3.0 kHz"]
    elif mode == "AM":
        return "am_width", ["3.0 kHz", "6.0 kHz", "9.0 kHz"]
    elif mode in ("NFM", "FM"):
        return "fm_width", ["2.5 kHz", "5.0 kHz"]
    else:
        raise ValueError("Internal error: unknown mode %s" % mode)


def filter_to_hz(item):
    mag, units = item.split(' ')
    return float(mag) * (1000 if units == 'kHz' else 1)


def all_filters():
    options = list(itertools.chain.from_iterable(
        filterlist for k, filterlist in [
            filters_for_mode('CW'), filters_for_mode('USB'),
            filters_for_mode('DIG'), filters_for_mode('FM'),
            filters_for_mode('AM')]))
    return sorted(set(options), key=filter_to_hz)


def closest_filter(options, value):
    value = filter_to_hz(value)
    dists = [abs(value - filter_to_hz(o)) for o in options]
    closest = options[dists.index(min(dists))]
    LOG.debug('Chose %s as closest filter to %s from %s',
              closest, value, ','.join(options))
    return closest


@directory.register
class FT450DRadio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FT-450D"""
    FT450 = False
    BAUD_RATE = 38400
    COM_BITS = 8    # number of data bits
    COM_PRTY = 'N'   # parity checking
    COM_STOP = 1   # stop bits
    MODEL = "FT-450D"

    DUPLEX = ["", "-", "+"]
    MODES = ["LSB", "USB",  "CW",  "AM", "FM", "DIG",
             "NFM", "CWR"]
    TMODES = ["", "Tone", "TSQL"]
    STEPSFM = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
    STEPSAM = [2.5, 5.0, 9.0, 10.0, 12.5, 25.0]
    STEPSSSB = [1.0, 2.5, 5.0]
    VALID_BANDS = [(100000, 33000000), (33000000, 56000000)]
    FUNC_LIST = ['MONI', 'N/A', 'PBAK', 'PLAY1', 'PLAY2', 'PLAY3', 'QSPLIT',
                 'SPOT', 'SQLOFF', 'SWR', 'TXW', 'VCC', 'VOICE2', 'VM1MONI',
                 'VM1REC', 'VM1TX', 'VM2MONI', 'VM2REC', 'VM2TX', 'DOWN', 'FAST',
                 'UP', 'DSP', 'IPO/ATT', 'NB', 'AGC', 'MODEDN',  'MODEUP',
                 'DSP/SEL', 'KEYER', 'CLAR', 'BANDDN', 'BANDUP', 'A=B', 'A/B',
                 'LOCK', 'TUNE', 'VOICE', 'MW', 'V/M', 'HOME', 'RCL', 'VOX', 'STO',
                 'STEP', 'SPLIT', 'PMS', 'SCAN', 'MENU', 'DIMMER', 'MTR']
    CHARSET = list(chirp_common.CHARSET_ASCII)
    CHARSET.remove("\\")

    MEM_SIZE = 15017
    # block 9 (135 Bytes long) is to be repeated 101 times
    _block_lengths = [4, 84, 135, 162, 135, 162, 151, 130, 135, 127, 189, 103]

    MEM_FORMAT = """
        struct mem_struct {      // 27 bytes per channel
            u8  tag_on_off:2,    // @ Byte 0    1=Off, 2=On
                unk0:2,
                mode:4;
            u8  duplex:2,        // @ byte 1
                att:1,
                ipo:1,
                unka1:1,
                tunerbad:1,       // ?? Possible tuner failed
                unk1b:1,         // @@@???
                uprband:1;
            u8  cnturpk:1,       // @ Byte 2 Peak (clr), Null (set)
                cnturmd:3,       // Contour filter mode
                cnturgn:1,       // Contour filter gain Low/high
                mode2:3;         // When mode is data(5)
            u8  ssb_step:2,      // @ Byte 3
                am_step:3,
                fm_step:3;
            u8  tunerok:1,        // @ Byte 4 ?? Poss tuned ok
                cnturon:1,
                unk4b:1,
                dnr_on:1,
                notch:1,
                unk4c:1,
                tmode:2;         // Tone/Cross/etc as Off/Enc/Enc+Dec
            u8  unk5a:4,         // @ byte 5
                dnr_val:4;
            u8  cw_width:2,		 // # byte 6, Notch width indexes
                fm_width:2,
                am_width:2,
                sb_width:2;
            i8  notch_pos;	     // @ Byte 7   Signed: - 0 +
            u8  tone;       	 // @ Byte 8
            u8  unk9;       	 // @ Byte 9    Always set to 0
            u8  unkA;            // @ Byte A
            u8  unkB;            // @ Byte B
            u32 freq;            // @ C-F
            u32 offset;          // @ 10-13
            u8  name[7];         // @ 14-1A
        };

        struct model{
            u8  modname[4];
        };
        #seekto 0x04;
        struct {
            u8  set04;      // ?Checksum / Clone counter?
            u8  set05;      // Current VFO?
            u8  set06;
            u8  fast:1,
                lock:1,     // Inverted: 1 = Off
                nb:1,
                agc:5;
            u8  set08a:3,
                keyer:1,
                set08b:2,
                mtr_mode:2;
            u8  set09;
            u8  set0A;
            u8  set0B:2,
                clk_sft:1,
                cont:5;     // 1:1
            u8  beepvol_sgn:1,  // @x0C: set : Link @0x41, clear: fix @ 0x40
                set0Ca:3,
                clar_btn:1,     // 0 = Dial, 1= SEL
                cwstone_sgn:1,  // Set: Lnk @ x42, clear: Fixed at 0x43
                beepton:2;      // Index 0-3
            u8  set0Da:1,
                cw_key:1,
                set0Db:3,
                dialstp_mode:1,
                dialstp:2;
            u8  set0E:1,
                keyhold:1,
                lockmod:1,
                set0ea:1,
                amfmdial:1, // 0= Enabled. 1 = Disabled
                cwpitch:3;  // 0-based index
            u8  sql_rfg:1,
                set0F:2,
                cwweigt:5;  // Index 1:2.5=0 -> 1:4.5=20
            u8  cw_dly;     // @x10  ms = val * 10
            u8  set11;
            u8  cwspeed;    // val 4-60 is wpm, *5 is cpm
            u8  vox_gain;   // val 1:1
            u8  set14:2,
                emergen:1,
                vox_dly:5;    // ms = val * 100
            u8  set15a:1,
                stby_beep:1,
                set15b:1,
                mem_grp:1,
                apo:4;
            u8  tot;        // Byte x16, 1:1
            u8  micscan:1,
                set17:5,
                micgain:2;
            u8  cwpaddl:1,  // @x18  0=Key, 1=Mic
                set18:7;
            u8  set19;
            u8  set1A;
            u8  set1B;
            u8  set1C;
            u8  dig_vox;    // 1:1
            u8  set1E;
            i16 d_disp;     //  @ x1F,x20   signed 16bit
            u8  pnl_cs;     // 0-based index
            u8  pm_up;
            u8  pm_fst;
            u8  pm_dwn;
            u8  set25;
            u8  set26;
            u8  set27;
            u8  set28;
            u8  beacon_time;    // 1:1
            u8  set2A;
            u8  cat_rts:1,      // @x2b: Enable=0, Disable=1
                peakhold:1,
                set2B:4,
                cat_tot:2;      // Index 0-3
            u8  set2CA:2,
                rtyrpol:1,
                rtytpol:1,
                rty_sft:2,
                rty_ton:1,
                set2CC:1;
            u8  dig_vox_dupe;   // 1:1
            u8  ext_mnu:1,
                m_tune:1,
                set2E:2,
                scn_res:4;
            u8  cw_auto:1,      // Off=0, On=1
                cwtrain:2,      // Index
                set2F:1,
                cw_qsk:2,       // Index
                cw_bfo:2;       // Index
            u8  mic_eq;         // @x30  1:1
            u8  set31:5,
                catrate:3;      // Index 0-4
            u8  set32;
            u8  dimmer:4,
                set33:4;
            u8  set34;
            u8  set35;
            u8  set36;
            u8  set37;
            u8  set38a:1,
                rfpower:7;       // 1:1
            u8  set39a:2,
                tuner:3,        // Index 0-4
                seldial:3;      // Index 0-5
            u8  set3A;
            u8  set3B;
            u8  set3C;
            i8  qspl_f;         // Signed
            u8  set3E;
            u8  set3F;
            u8  beepvol_fix;        // 1:1
            i8  beepvol_lnk;        // SIGNED 2's compl byte
            u8  cwstone_fix;
            i8  cwstone_lnk;        // signed byte
            u8  set44:2,
                mym_data:1,         // My Mode: Data, set = OFF
                mym_fm:1,
                mym_am:1,
                mym_cw:1,
                mym_usb:1,
                mym_lsb:1;
            u8  myb_24:1,          // My Band: 24 MHz set = OFF
                myb_21:1,
                myb_18:1,
                myb_14:1,
                myb_10:1,
                myb_7:1,
                myb_3_5:1,
                myb_1_8:1;
            u8  set46:6,
                myb_28:1,
                myb_50:1;
            u8  set47;
            u8  set48;
            u8  set49;
            u8  set4A;
            u8  set4B;
            u8  set4C;
            u8  set4D;
            u8  set4E;
            u8  set4F;
            u8  set50;
            u8  set51;
            u8  set52;
            u8  set53;
            u8  set54;
            u8  set55;
            u8  set56a:3,
                split:1,
                set56b:4;
            u8  set57;
        } settings;

        //#seekto 0x58;
        struct mem_struct vfoa[11]; // The current cfgs for each vfo 'band'
        struct mem_struct vfob[11];
        struct mem_struct home[2];  // The 2 Home cfgs (HF and 6m)
        struct mem_struct qmb;      // The Quick Memory Bank STO/RCL
        struct mem_struct mtqmb;    // Last QMB-MemTune cfg (not displayed)
        struct mem_struct mtune;    // Last MemTune cfg (not displayed)

        #seekto 0x343;          // chan status
        u8 visible[63];         // 1 bit per channel
        u8 pmsvisible;          // @ 0x382

        //#seekto 0x383;
        u8 filled[63];
        u8 pmsfilled;           // @ 0x3c2

        //#seekto 0x3C3;
        struct mem_struct memory[500];
        struct mem_struct pms[4];       // Programmed Scan limits @ x387F

        #seekto 0x3906;
        struct {
            char t1[40];     // CW Beacon Text
            char t2[40];
            char t3[40];
            } beacontext;   // to 0x397E

        #seekto 0x3985;
        struct mem_struct m60[5];   // to 0x3A0B

        #seekto 0x03a45;
        struct mem_struct current;

    """
    _CALLSIGN_CHARSET = [chr(x) for x in list(range(ord("0"), ord("9") + 1)) +
                         list(range(ord("A"), ord("Z") + 1)) + [ord(" ")]]
    _CALLSIGN_CHARSET_REV = dict(zip(_CALLSIGN_CHARSET,
                                     range(0, len(_CALLSIGN_CHARSET))))

    # WARNING Indecis are hard wired in get/set_memory code !!!
    # Channels print in + increasing index order (PMS first)
    SPECIAL_MEMORIES = {
        "VFOa-1.8M": -27,
        "VFOa-3.5M": -26,
        "VFOa-7M": -25,
        "VFOa-10M": -24,
        "VFOa-14M": -23,
        "VFOa-18M": -22,
        "VFOa-21M": -21,
        "VFOa-24M": -20,
        "VFOa-28M": -19,
        "VFOa-50M": -18,
        "VFOa-HF": -17,
        "VFOb-1.8M": -16,
        "VFOb-3.5M": -15,
        "VFOb-7M": -14,
        "VFOb-10M": -13,
        "VFOb-14M": -12,
        "VFOb-18M": -11,
        "VFOb-21M": - 10,
        "VFOb-24M": -9,
        "VFOb-28M": -8,
        "VFOb-50M": -7,
        "VFOb-HF": -6,
        "HOME-HF": -5,
        "HOME-50M": -4,
        "QMB": -3,
        "QMB-MTune": -2,
        "Mem-Tune": -1,
    }
    FIRST_VFOB_INDEX = -6
    LAST_VFOB_INDEX = -16
    FIRST_VFOA_INDEX = -17
    LAST_VFOA_INDEX = -27

    SPECIAL_PMS = {
        "PMS1-L": -36,
        "PMS1-U": -35,
        "PMS2-L": -34,
        "PMS2-U": -33,
    }
    LAST_PMS_INDEX = -36
    SPECIAL_MEMORIES.update(SPECIAL_PMS)

    SPECIAL_60M = {
        "60m-Ch1": -32,
        "60m-Ch2": -31,
        "60m-Ch3": -30,
        "60m-Ch4": -29,
        "60m-Ch5": -28,
    }
    LAST_60M_INDEX = -32
    SPECIAL_MEMORIES.update(SPECIAL_60M)

    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = _(
            "The FT-450D radio driver loads the 'Special Channels' tab\n"
            "with the PMS scanning range memories (group 11), 60meter\n"
            "channels (group 12), the QMB (STO/RCL) memory, the HF and\n"
            "50m HOME memories and all the A and B VFO memories.\n"
            "There are VFO memories for the last frequency dialed in\n"
            "each band. The last mem-tune config is also stored.\n"
            "These Special Channels allow limited field editing.\n"
            "This driver also populates the 'Other' tab in the channel\n"
            "memory Properties window. This tab contains values for\n"
            "those channel memory settings that don't fall under the\n"
            "standard Chirp display columns. With FT450 support, the gui now\n"
            "uses the mode 'DIG' to represent data modes and a new column\n"
            "'DATA MODE' to select USER-U, USER-L and RTTY \n")
        rp.pre_download = _(
            "1. Turn radio off.\n"
            "2. Connect cable to ACC jack.\n"
            "3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys"
            " while\n"
            "     turning the radio on (\"CLONE MODE\" will appear on the\n"
            "     display).\n"
            "4. <b>After clicking OK</b> here, press the [C.S.] key to\n"
            "    send image.\n")
        rp.pre_upload = _(
            "1. Turn radio off.\n"
            "2. Connect cable to ACC jack.\n"
            "3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys"
            " while\n"
            "     turning the radio on (\"CLONE MODE\" will appear on the\n"
            "     display).\n"
            "4. Click OK here.\n"
            "    (\"Receiving\" will appear on the LCD).\n")
        return rp

    def _read(self, block, blocknum):
        # be very patient at first block
        if blocknum == 0:
            attempts = 60
        else:
            attempts = 5
        for _i in range(0, attempts):
            data = self.pipe.read(block + 2)    # Blocknum, data,checksum
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
            # Remove the block number and checksum
            data = data[1:block + 1]
        elif self.FT450:
            # unique FT450 (and 450AT?) vs D, only 2 bytes in first block
            if blocknum == 0 and len(data) == 4:
                checksum = yaesu_clone.YaesuChecksum(1, block - 2)
                if checksum.get_existing(data) != \
                    checksum.get_calculated(data):
                    raise Exception("Checksum Failed [%02X<>%02X] block %02X" %
                                   (checksum.get_existing(data),
                                   checksum.get_calculated(data), blocknum))
                # Remove the block number and checksum
                data = data[1:block - 2 + 1]
                # pad the data to the correct 450d size
                data += b"  "
            else:
                # FT450, but bad block
                raise Exception("Unable to read block %i expected %i got %i"
                               % (blocknum, block + 2, len(data)))
        else:
            # Use this info to decode a new Yaesu model
            # Not an old FT450 or 450AT
            raise Exception("Unable to read block %i expected %i got %i"
                            % (blocknum, block + 2, len(data)))
        return data

    def _clone_in(self):
        # Be very patient with the radio
        self.pipe.timeout = 2
        self.pipe.baudrate = self.BAUD_RATE
        self.pipe.bytesize = self.COM_BITS
        self.pipe.parity = self.COM_PRTY
        self.pipe.stopbits = self.COM_STOP
        self.pipe.rtscts = False

        start = time.time()

        data = b""
        blocks = 0
        status = chirp_common.Status()
        status.msg = _("Cloning from radio")
        nblocks = len(self._block_lengths) + 100    # Block 8 repeats
        status.max = nblocks
        for block in self._block_lengths:
            if blocks == 8:
                # repeated read of block 8 same size (chan memory area)
                repeat = 101
            else:
                repeat = 1
            for _i in range(0, repeat):
                data += self._read(block, blocks)
                self.pipe.write(CMD_ACK)
                blocks += 1
                status.cur = blocks
                self.status_fn(status)
        data += self.MODEL.encode()
        return memmap.MemoryMapBytes(data)

    def _clone_out(self):
        self.pipe.baudrate = self.BAUD_RATE
        self.pipe.bytesize = self.COM_BITS
        self.pipe.parity = self.COM_PRTY
        self.pipe.stopbits = self.COM_STOP
        self.pipe.rtscts = False
        delay = 0.5
        start = time.time()
        blocks = 0
        pos = 0
        status = chirp_common.Status()
        status.msg = _("Cloning to radio")
        status.max = len(self._block_lengths) + 100
        for block in self._block_lengths:
            if blocks == 8:
                repeat = 101
            else:
                repeat = 1
            for _i in range(0, repeat):
                time.sleep(0.01)
                # If this is a 450 model, we need to send just the first two model bytes
                # in block 0 and just checksum that part
                if self.FT450 and blocks == 0:
                    checksum = yaesu_clone.YaesuChecksum(pos, pos + block - 2 - 1)
                else:
                    checksum = yaesu_clone.YaesuChecksum(pos, pos + block - 1)
                LOG.debug("Sending block %s" % hex(blocks))
                self.pipe.write(struct.pack('B', blocks))
                if self.FT450 and blocks == 0:
                    blkdat = self.get_mmap()[pos:pos + block - 2]
                else:
                    blkdat = self.get_mmap()[pos:pos + block]
                LOG.debug("Sending %d bytes:\n%s"
                          % (len(blkdat), util.hexprint(blkdat)))
                self.pipe.write(blkdat)
                xs = checksum.get_calculated(self.get_mmap())
                LOG.debug("Sending checksum %s" % hex(xs))
                self.pipe.write(struct.pack('B', xs))
                buf = self.pipe.read(1)
                if not buf or buf[:1] != CMD_ACK:
                    time.sleep(delay)
                    buf = self.pipe.read(1)
                if not buf or buf[:1] != CMD_ACK:
                    raise Exception(_("Radio did not ack block %i") % blocks)
                pos += block
                blocks += 1
                status.cur = blocks
                self.status_fn(status)

    def sync_in(self):
        try:
            self._mmap = self._clone_in()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s"
                                    % e)
        self.process_mmap()

    def sync_out(self):
        try:
            self._clone_out()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s"
                                    % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_dtcs = False
        rf.valid_modes = [x for x in self.MODES if x in chirp_common.MODES]
        rf.valid_tmodes = list(self.TMODES)
        rf.valid_duplexes = list(self.DUPLEX)
        rf.valid_tuning_steps = list(T_STEPS)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_power_levels = []
        rf.valid_characters = "".join(self.CHARSET)
        rf.valid_name_length = 7
        rf.valid_skips = []
        rf.valid_special_chans = sorted(self.SPECIAL_MEMORIES.keys())
        rf.memory_bounds = (1, 500)
        rf.has_ctone = True
        rf.has_settings = True
        rf.has_cross = True
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tmode(self, mem, _mem):
        mem.tmode = self.TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.ctone = mem.rtone

    def _set_duplex(self, mem, _mem):
        _mem.duplex = self.DUPLEX.index(mem.duplex)

    def get_memory(self, number):
        if isinstance(number, str):
            return self._get_special(number)
        elif number < 0:
            # I can't stop delete operation from losing extd_number but
            # I know how to get it back
            return self._get_special(self.SPECIAL_MEMORIES_REV[number])
        else:
            return self._get_normal(number)

    def set_memory(self, memory):
        # If this is called due to a delete request on the gui,
        # then the memory passed might be passed as a str,
        # since the special memories have string tags on the GUI and not
        # numbers. Convert these back to the int for the specials
        if isinstance(memory.number, str):
            memory.number = self.SPECIAL_MEMORIES[memory.number]
            return self._set_special(memory)
        if memory.number < 0:
            return self._set_special(memory)
        else:
            return self._set_normal(memory)

    def _get_special(self, number):
        mem = chirp_common.Memory()
        mem.number = self.SPECIAL_MEMORIES[number]
        mem.extd_number = number

        if mem.number in range(self.FIRST_VFOA_INDEX,
                               self.LAST_VFOA_INDEX - 1, -1):
            _mem = self._memobj.vfoa[-self.LAST_VFOA_INDEX + mem.number]
            immutable = ["number", "extd_number", "name", "power"]
        elif mem.number in range(self.FIRST_VFOB_INDEX,
                                 self.LAST_VFOB_INDEX - 1, -1):
            _mem = self._memobj.vfob[-self.LAST_VFOB_INDEX + mem.number]
            immutable = ["number", "extd_number", "name", "power"]
        elif mem.number in range(-4, -6, -1):           # 2 Home Chans
            _mem = self._memobj.home[5 + mem.number]
            immutable = ["number", "extd_number", "name", "power"]
        elif mem.number == -3:
            _mem = self._memobj.qmb
            immutable = ["number", "extd_number", "name", "power"]
        elif mem.number == -2:
            _mem = self._memobj.mtqmb
            immutable = ["number", "extd_number", "name", "power"]
        elif mem.number == -1:
            _mem = self._memobj.mtune
            immutable = ["number", "extd_number", "name", "power"]
        elif mem.number in self.SPECIAL_PMS.values():
            # ft450 does NOT use the pmsvisible or pmsfilled fields,
            # it uses the next 4 bits after the 500 normal memories
            # in the main visible and filled settings area.
            if self.FT450:
                pmsnum = 501 + (-self.LAST_PMS_INDEX) + mem.number
                used = (self._memobj.visible[(pmsnum - 1) // 8] >> \
                        (pmsnum - 1) % 8) & 0x01
                valid = (self._memobj.filled[(pmsnum - 1) // 8] >> \
                        (pmsnum - 1) % 8) & 0x01
            else:
                bitindex = (-self.LAST_PMS_INDEX) + mem.number
                used = (self._memobj.pmsvisible >> bitindex) & 0x01
                valid = (self._memobj.pmsfilled >> bitindex) & 0x01
            # You can clear the PMS memories on the FT450
            # using the CLAR button and then they do not display.
            if not used:
                mem.empty = True
            if not valid:
                mem.empty = True
                return mem
            mx = (-self.LAST_PMS_INDEX) + mem.number
            _mem = self._memobj.pms[mx]
            mx = mx + 1
            immutable = ["number", "rtone", "ctone", "extd_number",
                         "tmode", "cross_mode",
                         "power", "duplex", "offset"]
        elif mem.number in self.SPECIAL_60M.values():
            mx = (-self.LAST_60M_INDEX) + mem.number
            _mem = self._memobj.m60[mx]
            mx = mx + 1
            immutable = ["number", "rtone", "ctone", "extd_number",
                         "tmode", "cross_mode",
                         "frequency", "power", "duplex", "offset"]
        else:
            raise Exception("Sorry, you can't edit that special"
                            " memory channel %i." % mem.number)

        mem = self._get_memory(mem, _mem)
        mem.immutable = immutable

        return mem

    def _set_special(self, mem):
        if mem.empty and mem.number not in self.SPECIAL_PMS.values():
            # can't delete special memories! But can delete PMS mems
            raise errors.RadioError("Sorry, special memory can't be deleted")

        cur_mem = self._get_special(self.SPECIAL_MEMORIES_REV[mem.number])

        if mem.number in range(self.FIRST_VFOA_INDEX,
                               self.LAST_VFOA_INDEX - 1, -1):
            _mem = self._memobj.vfoa[-self.LAST_VFOA_INDEX + mem.number]
        elif mem.number in range(self.FIRST_VFOB_INDEX,
                                 self.LAST_VFOB_INDEX - 1, -1):
            _mem = self._memobj.vfob[-self.LAST_VFOB_INDEX + mem.number]
        elif mem.number in range(-4, -6, -1):
            _mem = self._memobj.home[5 + mem.number]
        elif mem.number == -3:
            _mem = self._memobj.qmb
        elif mem.number == -2:
            _mem = self._memobj.mtqmb
        elif mem.number == -1:
            _mem = self._memobj.mtune
        elif mem.number in self.SPECIAL_PMS.values():
            # ft450 does NOT use the pmsvisible or pmsfilled fields,
            # it uses the next 4 bits after the 500 normal memories
            # in the main visible and filled settings area.
            if self.FT450:
                pmsnum = 501 + (-self.LAST_PMS_INDEX) + mem.number
                wasused = (self._memobj.visible[(pmsnum - 1) // 8] >>
                   (pmsnum - 1) % 8) & 0x01
                wasvalid = (self._memobj.filled[(pmsnum - 1) // 8] >>
                    (pmsnum - 1) % 8) & 0x01
                if mem.empty:
                    if wasvalid and not wasused:
                        self._memobj.filled[(pmsnum - 1) // 8] &= \
                            ~(1 << (pmsnum - 1) % 8)
                    self._memobj.visible[(pmsnum - 1) // 8] &= \
                        ~(1 << (pmsnum - 1) % 8)
                    return
                self._memobj.visible[(pmsnum - 1) // 8] |= 1 << (pmsnum - 1) \
                        % 8
                self._memobj.filled[(pmsnum - 1) // 8] |= 1 << (pmsnum - 1) \
                        % 8
                _mem = self._memobj.pms[-self.LAST_PMS_INDEX + mem.number]
            else:      #self.FT450
                bitindex = (-self.LAST_PMS_INDEX) + mem.number
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
            raise errors.RadioError("Sorry, you can't edit"
                                    " that special memory.")

        for key in cur_mem.immutable:
            if key != "extd_number":
                if cur_mem.__dict__[key] != mem.__dict__[key]:
                    raise errors.RadioError("Editing field `%s' " % key +
                                            "is not supported on this channel")
        self._set_memory(mem, _mem)

    def _get_normal(self, number):
        _mem = self._memobj.memory[number - 1]
        used = (self._memobj.visible[(number - 1) // 8] >> (number - 1) % 8) \
            & 0x01
        valid = (self._memobj.filled[(number - 1) // 8] >> (number - 1) % 8) \
            & 0x01

        mem = chirp_common.Memory()
        mem.number = number
        if not used:
            mem.empty = True
            if not valid or _mem.freq == 0xffffffff:
                return mem
        if mem.number == 1:
            mem.immutable = ['empty']
        return self._get_memory(mem, _mem)

    def _set_normal(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        wasused = (self._memobj.visible[(mem.number - 1) // 8] >>
                   (mem.number - 1) % 8) & 0x01
        wasvalid = (self._memobj.filled[(mem.number - 1) // 8] >>
                    (mem.number - 1) % 8) & 0x01

        if mem.empty:
            if mem.number == 1:
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

        self._memobj.visible[(mem.number - 1) // 8] |= 1 << (mem.number - 1) \
            % 8
        self._memobj.filled[(mem.number - 1) // 8] |= 1 << (mem.number - 1) \
            % 8
        self._set_memory(mem, _mem)

    def _get_memory(self, mem, _mem):
        mem.freq = int(_mem.freq)
        mem.offset = int(_mem.offset)
        mem.duplex = self.DUPLEX[_mem.duplex]
        # Mode gets tricky with dual (USB+DATA) options
        # WDC on FT450, the high bit of the nybble really
        # means something else, but I don't know
        # what it is. IE Sometimes LSB comes in as 1, sometime 8...
        vx = _mem.mode
        vx_data = 3   # Assume N/A unless reset below
        if vx == 0:   # LSB
            pass
        elif vx == 1:   # USB
            pass
        elif vx == 2:   # USB CW (CW)
            pass
        elif vx == 3:   # AM
            pass
        elif vx == 4:   # FM/NFM
            if _mem.mode2 == 1:
                vx = 6
            else:
                vx = 4
            pass
        elif vx == 5:   # USER\L
            # This looks different from FT450D
            if self.FT450:
                vx = 5      # set to new "DIG"
                vx_data = 1
            else:
                # on 450D only 5 used for dig modes, no 13
                if _mem.mode2 == 0:  # RTTY
                    vx = 5           # Set to new "DIG"
                    vx_data = 2      # RTTY
                elif _mem.mode2 == 1:  # USER-L
                    vx = 5           # set to new "DIG"
                    vx_data = 0
                elif _mem.mode2 == 2: # USER-U variant
                    vx = 5            # Set to new "DIG"
                    vx_data = 1       # USER-U with Split?
        elif vx == 8:   # LSB
            vx = 0
        elif vx == 9:   # USB
            vx = 1
        elif vx == 10:  # LSB CW (CWR)
            vx = 7      # CWR
        elif vx == 13:
            if _mem.mode2 == 0:   # RTTY
                vx = 5            # Set to new "DIG"
                vx_data = 2       # RTTY
            elif _mem.mode2 == 1: # USER-L
                vx = 5            # set to new "DIG"
                vx_data = 0
            elif _mem.mode2 == 2: # USER-U variant
                vx = 5            # Set to new "DIG"
                vx_data = 1       # USER-U with Split?
            else:
                LOG.error("unknown combo of mem.mode 13 and mem mode 2: %s %s",
                          vx,_mem.mode2)
        else:
            LOG.error("unknown _mem.mode value : %s", vx)
        try:
            mem.mode = self.MODES[vx]
        except ValueError:
            LOG.error('The FT-450 driver is broken for unsupported modes')
        if mem.mode == "FM" or mem.mode == "NFM":
            mem.tuning_step = self.STEPSFM[_mem.fm_step]
        elif mem.mode == "AM":
            mem.tuning_step = self.STEPSAM[_mem.am_step]
        elif mem.mode[:2] == "CW":
            mem.tuning_step = self.STEPSSSB[_mem.ssb_step]
        else:
            try:
                mem.tuning_step = self.STEPSSSB[_mem.ssb_step]
            except IndexError:
                pass
        self._get_tmode(mem, _mem)

        if _mem.tag_on_off == 2:
            for i in _mem.name:
                if i == 0xFF:
                    break
                if chr(i) in self.CHARSET:
                    mem.name += chr(i)
                else:
                    # radio has some graphical chars that are not supported
                    # we replace those with a *
                    LOG.info("Replacing char %x with *" % i)
                    mem.name += "*"
            mem.name = mem.name.rstrip()
        else:
            mem.name = ""

        mem.extra = RadioSettingGroup("extra", "Extra")

        # add a new field to handle the new sub-modes if dig
        options = DATA_MODES
        rs = RadioSetting("data_modes", "DATA MODE",
                          RadioSettingValueList(options,
                                                current_index=vx_data))
        rs.set_doc("Extended Data Modes")
        mem.extra.append(rs)

        rs = RadioSetting("ipo", "IPO",
                          RadioSettingValueBoolean(bool(_mem.ipo)))
        rs.set_doc("Bypass preamp")
        mem.extra.append(rs)

        rs = RadioSetting("att", "ATT",
                          RadioSettingValueBoolean(bool(_mem.att)))
        rs.set_doc("10dB front end attenuator")
        mem.extra.append(rs)

        rs = RadioSetting("cnturon", "Contour Filter",
                          RadioSettingValueBoolean(_mem.cnturon))
        rs.set_doc("Contour filter on/off")
        mem.extra.append(rs)

        options = ["Peak", "Null"]
        rs = RadioSetting("cnturpk", "Contour Filter Mode",
                          RadioSettingValueList(options,
                                                current_index=_mem.cnturpk))
        mem.extra.append(rs)

        options = ["Low", "High"]
        rs = RadioSetting("cnturgn", "Contour Filter Gain",
                          RadioSettingValueList(options,
                                                current_index=_mem.cnturgn))
        rs.set_doc("Filter gain/attenuation")
        mem.extra.append(rs)

        options = ["-2", "-1", "Center", "+1", "+2"]
        rs = RadioSetting("cnturmd", "Contour Filter Notch",
                          RadioSettingValueList(options,
                                                current_index=_mem.cnturmd))
        rs.set_doc("Filter notch offset")
        mem.extra.append(rs)

        rs = RadioSetting("notch", "Notch Filter",
                          RadioSettingValueBoolean(_mem.notch))
        rs.set_doc("IF bandpass filter")
        mem.extra.append(rs)

        vx = 1
        options = ["<-", "Center", "+>"]
        if _mem.notch_pos < 0:
            vx = 0
        if _mem.notch_pos > 0:
            vx = 2
        rs = RadioSetting("notch_pos", "Notch Position",
                          RadioSettingValueList(options, current_index=vx))
        rs.set_doc("IF bandpass filter shift")
        mem.extra.append(rs)

        stx, options = filters_for_mode(mem.mode)
        vx = getattr(_mem, stx)
        rs = RadioSetting("bpfilter", "IF Bandpass Filter Width",
                          RadioSettingValueList(all_filters(), options[vx]))
        rs.set_doc("DSP IF bandpass Notch width (Hz)")
        mem.extra.append(rs)

        rs = RadioSetting("dnr_on", "DSP Noise Reduction",
                          RadioSettingValueBoolean(bool(_mem.dnr_on)))
        rs.set_doc("Digital noise processing")
        mem.extra.append(rs)

        options = ["Off", "1", "2", "3", "4", "5", "6", "7",
                          "8", "9", "10", "11"]
        rs = RadioSetting("dnr_val", "DSP Noise Reduction Alg",
                          RadioSettingValueList(options,
                                                current_index=_mem.dnr_val))
        rs.set_doc("Digital noise reduction algorithm number (1-11)")
        mem.extra.append(rs)

        return mem          # end get_memory

    def _set_memory(self, mem, _mem):
        if len(mem.name) > 0:
            _mem.tag_on_off = 2
        else:
            _mem.tag_on_off = 1
        self._set_duplex(mem, _mem)
        _mem.mode2 = 0
        tmpmemmode = str(mem.mode)
        if mem.mode == "DIG":
            _mem.mode = 5        # We'll set _mode2 from extra data_modes
        elif tmpmemmode == "CWR":
            _mem.mode = 10
            # 450 looks different
            if self.FT450:
                _mem.mode2 = 2
            else:
                _mem.mode2 = 0
        elif tmpmemmode == "CW":
            _mem.mode = 2
            # 450 looks different
            if self.FT450:
                _mem.mode2 = 2
            else:
                _mem.mode2 = 0
        elif tmpmemmode == "NFM":
            _mem.mode = 4
            _mem.mode2 = 1
        elif tmpmemmode == "FM":
            _mem.mode = 4
            _mem.mode2 = 2
        elif tmpmemmode == "LSB":
            _mem.mode = 0
            # 450 looks different
            if self.FT450:
                _mem.mode2 = 2
            else:
                _mem.mode2 = 0
        elif tmpmemmode == "USB":
            _mem.mode = 1
            if self.FT450:
                _mem.mode2 = 2
            else:
                _mem.mode2 = 0
        elif tmpmemmode == "AM":
            _mem.mode = 3
            if self.FT450:
                _mem.mode2 = 2
            else:
                _mem.mode2 = 0
        else:           # SHOULD NOT OCCUR
            _mem.mode = self.MODES.index(mem.mode)
            _mem.mode2 = 0
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
        _mem.freq = mem.freq
        _mem.uprband = 0
        if mem.freq >= 33000000:
            _mem.uprband = 1
        _mem.offset = mem.offset
        _mem.tmode = self.TMODES.index(mem.tmode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.tunerok = 0            # Dont know what these two do...
        _mem.tunerbad = 0

        for i in range(0, 7):
            _mem.name[i] = ord(mem.name.ljust(7)[i])

        for setting in mem.extra:
            if setting.get_name() == "notch_pos":
                vx = 0          # Override list string with signed value
                stx = str(setting.value)
                if stx == "<-":
                    vx = -13
                if stx == "+>":
                    vx = 12
                setattr(_mem, "notch_pos", vx)
            elif setting.get_name() == "dnr_val":
                stx = str(setting.value)        # Convert string to int
                vx = 0
                if stx != "Off":
                    vx = int(stx)
                else:
                    setattr(_mem, "dnr_on", 0)
                setattr(_mem, setting.get_name(), vx)
            elif setting.get_name() == "data_modes":
                if tmpmemmode == "DIG":
                    stx = str(setting.value)
                    if stx == "USER-L":
                        if self.FT450:
                            _mem.mode = 13
                            _mem.mode2 = 1
                        else:
                            _mem.mode = 5
                            _mem.mode2 = 1
                    elif stx == "USER-U":
                        _mem.mode = 5
                        _mem.mode2 = 2
                    elif stx == "RTTY":
                        if self.FT450:
                            _mem.mode = 13
                            _mem.mode2 = 0
                        else:
                            _mem.mode = 5
                            _mem.mode2 = 0
                    elif stx == "N/A":
                        _mem.mode = 5
                        _mem.mode2 = 2
                    else:
                        LOG.error("In _set_memory invalid digital data type %s", stx)
            elif setting.get_name() == "bpfilter":
                element, options = filters_for_mode(mem.mode)
                if str(setting.value) in options:
                    setattr(_mem, element, options.index(str(setting.value)))
                else:
                    default = closest_filter(options, str(setting.value))
                    LOG.warning('Memory specified filter width of %s for '
                                'mode %s which is not in allowed list of '
                                '%s. Defaulting to %s',
                                str(setting.value), mem.mode,
                                ','.join(options), default)
                    setattr(_mem, element, options.index(default))
            else:
                setattr(_mem, setting.get_name(), setting.value)

    @classmethod
    def match_model(cls, filedata, filename):
        """Match the opened/downloaded image to the correct version"""
        if len(filedata) == cls.MEM_SIZE + 7:    # +7 bytes of model name
            rid = filedata[cls.MEM_SIZE:cls.MEM_SIZE + 7]
            if rid.startswith(cls.MODEL.encode()):
                return True
        else:
            return False

    def _invert_me(self, setting, obj, atrb):
        """Callback: from inverted logic 1-bit booleans"""
        invb = not setting.value
        setattr(obj, atrb, invb)
        return

    def _chars2str(self, cary, knt):
        """Convert raw memory char array to a string: NOT a callback."""
        stx = ""
        for char in cary[0:knt]:
            stx += chr(int(char))
        return stx

    def _my_str2ary(self, setting, obj, atrba, knt):
        """Callback: convert string to fixed-length char array.."""
        ary = ""
        for j in range(0, knt, 1):
            chx = ord(str(setting.value)[j])
            if chx < 32 or chx > 125:     # strip non-printing
                ary += " "
            else:
                ary += str(setting.value)[j]
        setattr(obj, atrba, ary)
        return

    def get_settings(self):
        _settings = self._memobj.settings
        _beacon = self._memobj.beacontext
        gen = RadioSettingGroup("gen", "General")
        cw = RadioSettingGroup("cw", "CW")
        pnlcfg = RadioSettingGroup("pnlcfg", "Panel buttons")
        pnlset = RadioSettingGroup("pnlset", "Panel settings")
        voxdat = RadioSettingGroup("voxdat", "VOX and Data")
        mic = RadioSettingGroup("mic", "Microphone")
        mybands = RadioSettingGroup("mybands", "My Bands")
        mymodes = RadioSettingGroup("mymodes", "My Modes")

        top = RadioSettings(gen,  cw, pnlcfg, pnlset, voxdat, mic,
                            mymodes, mybands)

        self._do_general_settings(gen)
        self._do_cw_settings(cw)
        self._do_panel_buttons(pnlcfg)
        self._do_panel_settings(pnlset)
        self._do_vox_settings(voxdat)
        self._do_mic_settings(mic)
        self._do_mymodes_settings(mymodes)
        self._do_mybands_settings(mybands)

        return top

    def _do_general_settings(self, tab):
        _settings = self._memobj.settings

        rs = RadioSetting("ext_mnu", "Extended menu",
                          RadioSettingValueBoolean(_settings.ext_mnu))
        rs.set_doc("Enables access to extended settings in the radio")
        tab.append(rs)
        # Issue #8183 bugfix
        rs = RadioSetting("apo", "APO time (Hrs)",
                          RadioSettingValueInteger(0, 12, _settings.apo))
        tab.append(rs)

        options = ["%i" % i for i in range(0, 21)]
        options[0] = "Off"
        rs = RadioSetting("tot", "TX 'TOT' time-out (mins)",
                          RadioSettingValueList(options,
                                                current_index=_settings.tot))
        tab.append(rs)

        bx = not _settings.cat_rts     # Convert from Enable=0
        rs = RadioSetting("cat_rts", "CAT RTS flow control",
                          RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "cat_rts")
        tab.append(rs)

        options = ["0", "100ms", "1000ms", "3000ms"]
        rs = RadioSetting("cat_tot", "CAT Timeout",
                          RadioSettingValueList(options,
                                                current_index=_settings.cat_tot))
        tab.append(rs)

        options = ["4800", "9600", "19200", "38400", "Data"]
        rs = RadioSetting("catrate", "CAT rate",
                          RadioSettingValueList(options,
                                                current_index=_settings.catrate))
        tab.append(rs)

        rs = RadioSetting("mem_grp", "Mem groups",
                          RadioSettingValueBoolean(_settings.mem_grp))
        tab.append(rs)

        rs = RadioSetting("scn_res", "Resume scan (secs)",
                          RadioSettingValueInteger(0, 10, _settings.scn_res))
        tab.append(rs)

        rs = RadioSetting("clk_sft", "CPU clock shift",
                          RadioSettingValueBoolean(_settings.clk_sft))
        tab.append(rs)

        rs = RadioSetting("split", "TX/RX Frequency Split",
                          RadioSettingValueBoolean(_settings.split))
        tab.append(rs)

        rs = RadioSetting("qspl_f", "Quick-Split freq offset (kHz)",
                          RadioSettingValueInteger(-20, 20, _settings.qspl_f))
        tab.append(rs)

        rs = RadioSetting("emergen", "Alaska Emergency Mem 5167.5 kHz",
                          RadioSettingValueBoolean(_settings.emergen))
        tab.append(rs)

        rs = RadioSetting("stby_beep", "PTT release 'Standby' beep",
                          RadioSettingValueBoolean(_settings.stby_beep))
        tab.append(rs)

        options = ["ATAS", "EXT ATU", "INT ATU", "INTRATU", "F-TRANS"]
        rs = RadioSetting("tuner", "Antenna Tuner",
                          RadioSettingValueList(options,
                                                current_index=_settings.tuner))
        tab.append(rs)

        rs = RadioSetting("rfpower", "RF power (watts)",
                          RadioSettingValueInteger(5, 100, _settings.rfpower))
        tab.append(rs)      # End of _do_general_settings

    def _do_cw_settings(self, cw):        # - - - CW - - -
        _settings = self._memobj.settings
        _beacon = self._memobj.beacontext

        rs = RadioSetting("cw_dly", "CW break-in delay (ms * 10)",
                          RadioSettingValueInteger(0, 300, _settings.cw_dly))
        cw.append(rs)

        options = ["%i Hz" % i for i in range(400, 801, 100)]
        rs = RadioSetting("cwpitch", "CW pitch",
                          RadioSettingValueList(options,
                                                current_index=_settings.cwpitch))
        cw.append(rs)

        rs = RadioSetting("cwspeed", "CW speed (wpm)",
                          RadioSettingValueInteger(4, 60, _settings.cwspeed))
        rs.set_doc("Cpm is Wpm * 5")
        cw.append(rs)

        options = ["1:%1.1f" % (i / 10) for i in range(25, 46, 1)]
        rs = RadioSetting("cwweigt", "CW weight",
                          RadioSettingValueList(options,
                                                current_index=_settings.cwweigt))
        cw.append(rs)

        options = ["15ms", "20ms", "25ms", "30ms"]
        rs = RadioSetting("cw_qsk", "CW delay before TX in QSK mode",
                          RadioSettingValueList(options,
                                                current_index=_settings.cw_qsk))
        cw.append(rs)

        rs = RadioSetting("cwstone_sgn", "CW sidetone volume Linked",
                          RadioSettingValueBoolean(_settings.cwstone_sgn))
        rs.set_doc("If set; volume is relative to AF Gain knob.")
        cw.append(rs)

        rs = RadioSetting("cwstone_lnk", "CW sidetone linked volume",
                          RadioSettingValueInteger(-50, 50,
                                                   _settings.cwstone_lnk))
        cw.append(rs)

        rs = RadioSetting("cwstone_fix", "CW sidetone fixed volume",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.cwstone_fix))
        cw.append(rs)

        options = ["Numeric", "Alpha", "Mixed"]
        rs = RadioSetting("cwtrain", "CW Training mode",
                          RadioSettingValueList(options,
                                                current_index=_settings.cwtrain))
        cw.append(rs)

        rs = RadioSetting("cw_auto", "CW key jack- auto CW mode",
                          RadioSettingValueBoolean(_settings.cw_auto))
        rs.set_doc("Enable for CW mode auto-set when keyer pluuged in.")
        cw.append(rs)

        options = ["Normal", "Reverse"]
        rs = RadioSetting("cw_key", "CW paddle wiring",
                          RadioSettingValueList(options,
                                                current_index=_settings.cw_key))
        cw.append(rs)

        rs = RadioSetting("beacon_time", "CW beacon Tx interval (secs)",
                          RadioSettingValueInteger(0, 255,
                                                   _settings.beacon_time))
        cw.append(rs)

        tmp = self._chars2str(_beacon.t1, 40)
        rs = RadioSetting("t1", "CW Beacon Line 1",
                          RadioSettingValueString(0, 40, tmp))
        rs.set_apply_callback(self._my_str2ary, _beacon, "t1", 40)
        cw.append(rs)

        tmp = self._chars2str(_beacon.t2, 40)
        rs = RadioSetting("t2", "CW Beacon Line 2",
                          RadioSettingValueString(0, 40, tmp))
        rs.set_apply_callback(self._my_str2ary, _beacon, "t2", 40)
        cw.append(rs)

        tmp = self._chars2str(_beacon.t3, 40)
        rs = RadioSetting("t3", "CW Beacon Line 3",
                          RadioSettingValueString(0, 40, tmp))
        rs.set_apply_callback(self._my_str2ary, _beacon, "t3", 40)
        cw.append(rs)       # END _do_cw_settings

    def _do_panel_settings(self, pnlset):    # - - - Panel settings
        _settings = self._memobj.settings

        bx = not _settings.amfmdial     # Convert from Enable=0
        rs = RadioSetting("amfmdial", "AM&FM Dial",
                          RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "amfmdial")
        pnlset.append(rs)

        options = ["440 Hz", "880 Hz", "1760 Hz"]
        rs = RadioSetting("beepton", "Beep frequency",
                          RadioSettingValueList(options,
                                                current_index=_settings.beepton))
        pnlset.append(rs)

        rs = RadioSetting("beepvol_sgn", "Beep volume Linked",
                          RadioSettingValueBoolean(_settings.beepvol_sgn))
        rs.set_doc("If set; volume is relative to AF Gain knob.")
        pnlset.append(rs)

        rs = RadioSetting("beepvol_lnk", "Linked beep volume",
                          RadioSettingValueInteger(-50, 50,
                                                   _settings.beepvol_lnk))
        rs.set_doc("Relative to AF-Gain setting.")
        pnlset.append(rs)

        rs = RadioSetting("beepvol_fix", "Fixed beep volume",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.beepvol_fix))
        rs.set_doc("When Linked setting is unchecked.")
        pnlset.append(rs)

        rs = RadioSetting("cont", "LCD Contrast",
                          RadioSettingValueInteger(1, 24, _settings.cont))
        rs.set_doc("This setting does not appear to do anything...")
        pnlset.append(rs)

        rs = RadioSetting("dimmer", "LCD Dimmer",
                          RadioSettingValueInteger(1, 8,  _settings.dimmer))
        pnlset.append(rs)

        options = ["RF-Gain", "Squelch"]
        rs = RadioSetting("sql_rfg", "Squelch/RF-Gain",
                          RadioSettingValueList(options,
                                                current_index=_settings.sql_rfg))
        pnlset.append(rs)

        options = ["Frequencies", "Panel", "All"]
        rs = RadioSetting("lockmod", "Lock Mode",
                          RadioSettingValueList(options,
                                                current_index=_settings.lockmod))
        pnlset.append(rs)

        options = ["Dial", "SEL"]
        rs = RadioSetting("clar_btn", "CLAR button control",
                          RadioSettingValueList(options,
                                                current_index=_settings.clar_btn))
        pnlset.append(rs)

        if _settings.dialstp_mode == 0:             # AM/FM
            options = ["SSB/CW:1Hz", "SSB/CW:10Hz", "SSB/CW:20Hz"]
        else:
            options = ["AM/FM:100Hz", "AM/FM:200Hz"]
        rs = RadioSetting("dialstp", "Dial tuning step",
                          RadioSettingValueList(options,
                                                current_index=_settings.dialstp))
        pnlset.append(rs)

        options = ["0.5secs", "1.0secs", "1.5secs", "2.0secs"]
        rs = RadioSetting("keyhold", "Buttons hold-to-activate time",
                          RadioSettingValueList(options,
                                                current_index=_settings.keyhold))
        pnlset.append(rs)

        rs = RadioSetting("m_tune", "Memory tune",
                          RadioSettingValueBoolean(_settings.m_tune))
        pnlset.append(rs)

        rs = RadioSetting("peakhold", "S-Meter display hold (1sec)",
                          RadioSettingValueBoolean(_settings.peakhold))
        pnlset.append(rs)

        options = ["CW Sidetone", "CW Speed", "100 kHz step", "1 MHz Step",
                   "Mic Gain", "RF Power"]
        rs = RadioSetting("seldial", "SEL dial 2nd function (push)",
                          RadioSettingValueList(options,
                                                current_index=_settings.seldial))
        pnlset.append(rs)
    # End _do_panel_settings

    def _do_panel_buttons(self, pnlcfg):      # - - - Current Panel Config
        _settings = self._memobj.settings

        rs = RadioSetting("pnl_cs", "C.S. Function",
                          RadioSettingValueList(self.FUNC_LIST,
                                                current_index=_settings.pnl_cs))
        pnlcfg.append(rs)

        rs = RadioSetting("nb", "Noise blanker",
                          RadioSettingValueBoolean(_settings.nb))
        pnlcfg.append(rs)

        # The old FT450 uses different codes for the AGC setting, and only uses the
        # last 3 bits of the AGC definition. The two upper bits appear to always be x"11"
        # We will mask this in the routine that processes the agc value
        if self.FT450:
            options = ["Auto", "Fast",  "Slow", "UNK3", "UNK4", "UNK5", "OFF", "UNK7"]
            # mask off the two upper bits of the agc settings value
            FT450agc = _settings.agc & int('0x7',16)
            rs = RadioSetting("agc", "AGC",
                              RadioSettingValueList(options,
                                                    current_index=FT450agc))
        else:
            options = ["Auto", "Fast",  "Slow", "Auto/Fast", "Auto/Slow", "?5?"]
            rs = RadioSetting("agc", "AGC",
                              RadioSettingValueList(options,
                                                    current_index=_settings.agc))
        pnlcfg.append(rs)

        rs = RadioSetting("keyer", "Keyer",
                          RadioSettingValueBoolean(_settings.keyer))
        pnlcfg.append(rs)

        rs = RadioSetting("fast", "Fast step",
                          RadioSettingValueBoolean(_settings.fast))
        pnlcfg.append(rs)

        rs = RadioSetting("lock", "Lock (per Lock Mode)",
                          RadioSettingValueBoolean(_settings.lock))
        pnlcfg.append(rs)

        options = ["PO",  "ALC", "SWR"]
        rs = RadioSetting("mtr_mode", "S-Meter mode",
                          RadioSettingValueList(options,
                                                current_index=_settings.mtr_mode))
        pnlcfg.append(rs)
        # End _do_panel_Buttons

    def _do_vox_settings(self, voxdat):     # - - VOX and DATA Settings
        _settings = self._memobj.settings

        rs = RadioSetting("vox_dly", "VOX delay (x 100 ms)",
                          RadioSettingValueInteger(1, 30, _settings.vox_dly))
        voxdat.append(rs)

        rs = RadioSetting("vox_gain", "VOX Gain",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.vox_gain))
        voxdat.append(rs)

        rs = RadioSetting("dig_vox", "Digital VOX Gain",
                          RadioSettingValueInteger(0, 100,
                                                   _settings.dig_vox))
        voxdat.append(rs)

        rs = RadioSetting("d_disp", "User-L/U freq offset (Hz)",
                          RadioSettingValueInteger(-3000, 30000,
                                                   _settings.d_disp, 10))
        voxdat.append(rs)

        options = ["170 Hz", "200 Hz", "425 Hz", "850 Hz"]
        rs = RadioSetting("rty_sft", "RTTY FSK Freq Shift",
                          RadioSettingValueList(options,
                                                current_index=_settings.rty_sft))
        voxdat.append(rs)

        options = ["1275 Hz", "2125 Hz"]
        rs = RadioSetting("rty_ton", "RTTY FSK Mark tone",
                          RadioSettingValueList(options,
                                                current_index=_settings.rty_ton))
        voxdat.append(rs)

        options = ["Normal", "Reverse"]
        rs = RadioSetting("rtyrpol", "RTTY Mark/Space RX polarity",
                          RadioSettingValueList(options,
                                                current_index=_settings.rtyrpol))
        voxdat.append(rs)

        rs = RadioSetting("rtytpol", "RTTY Mark/Space TX polarity",
                          RadioSettingValueList(options,
                                                current_index=_settings.rtytpol))
        voxdat.append(rs)
        # End _do_vox_settings

    def _do_mic_settings(self, mic):    # - - MIC Settings
        _settings = self._memobj.settings

        rs = RadioSetting("mic_eq", "Mic Equalizer",
                          RadioSettingValueInteger(0, 9, _settings.mic_eq))
        mic.append(rs)

        options = ["Low", "Normal", "High"]
        rs = RadioSetting("micgain", "Mic Gain",
                          RadioSettingValueList(options,
                                                current_index=_settings.micgain))
        mic.append(rs)

        rs = RadioSetting("micscan", "Mic scan enabled",
                          RadioSettingValueBoolean(_settings.micscan))
        rs.set_doc("Enables channel scanning via mic up/down buttons.")
        mic.append(rs)

        rs = RadioSetting("pm_dwn", "Mic Down button function",
                          RadioSettingValueList(self.FUNC_LIST,
                                                current_index=_settings.pm_dwn))
        mic.append(rs)

        rs = RadioSetting("pm_fst", "Mic Fast button function",
                          RadioSettingValueList(self.FUNC_LIST,
                                                current_index=_settings.pm_fst))
        mic.append(rs)

        rs = RadioSetting("pm_up", "Mic Up button function",
                          RadioSettingValueList(self.FUNC_LIST,
                                                current_index=_settings.pm_up))
        mic.append(rs)
        # End _do_mic_settings

    def _do_mymodes_settings(self, mymodes):    # - - MYMODES
        _settings = self._memobj.settings  # Inverted Logic requires callback

        bx = not _settings.mym_lsb
        rs = RadioSetting("mym_lsb", "LSB", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "mym_lsb")
        mymodes.append(rs)

        bx = not _settings.mym_usb
        rs = RadioSetting("mym_usb", "USB", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "mym_usb")
        mymodes.append(rs)

        bx = not _settings.mym_cw
        rs = RadioSetting("mym_cw", "CW", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "mym_cw")
        mymodes.append(rs)

        bx = not _settings.mym_am
        rs = RadioSetting("mym_am", "AM", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "mym_am")
        mymodes.append(rs)

        bx = not _settings.mym_fm
        rs = RadioSetting("mym_fm", "FM", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "mym_fm")
        mymodes.append(rs)

        bx = not _settings.mym_data
        rs = RadioSetting("mym_data", "DATA", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "mym_data")
        mymodes.append(rs)
        # End _do_mymodes_settings

    def _do_mybands_settings(self, mybands):    # - - MYBANDS Settings
        _settings = self._memobj.settings  # Inverted Logic requires callback

        bx = not _settings.myb_1_8
        rs = RadioSetting("myb_1_8", "1.8 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_1_8")
        mybands.append(rs)

        bx = not _settings.myb_3_5
        rs = RadioSetting("myb_3_5", "3.5 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_3_5")
        mybands.append(rs)

        bx = not _settings.myb_7
        rs = RadioSetting("myb_7", "7 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_7")
        mybands.append(rs)

        bx = not _settings.myb_10
        rs = RadioSetting("myb_10", "10 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_10")
        mybands.append(rs)

        bx = not _settings.myb_14
        rs = RadioSetting("myb_14", "14 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_14")
        mybands.append(rs)

        bx = not _settings.myb_18
        rs = RadioSetting("myb_18", "18 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_18")
        mybands.append(rs)

        bx = not _settings.myb_21
        rs = RadioSetting("myb_21", "21 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_21")
        mybands.append(rs)

        bx = not _settings.myb_24
        rs = RadioSetting("myb_24", "24 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_24")
        mybands.append(rs)

        bx = not _settings.myb_28
        rs = RadioSetting("myb_28", "28 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_28")
        mybands.append(rs)

        bx = not _settings.myb_50
        rs = RadioSetting("myb_50", "50 MHz", RadioSettingValueBoolean(bx))
        rs.set_apply_callback(self._invert_me, _settings, "myb_50")
        mybands.append(rs)
        # End _do_mybands_settings

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[: -1]:
                            if "/" in bit:
                                bit, index = bit.split("/", 1)
                                index = int(index)
                                obj = getattr(obj, bit)[index]
                            else:
                                obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if 'bpfilter' in mem.extra:
            _, options = filters_for_mode(mem.mode)
            bpfilter = str(mem.extra['bpfilter'].value)
            if bpfilter not in options:
                msgs.append(chirp_common.ValidationWarning(
                    ('Filter width %s is not allowed for mode %s - '
                     'the closest suitable option %s will be used') % (
                         bpfilter, mem.mode,
                         closest_filter(options, bpfilter))))
        return msgs


@directory.register
class FT450Radio(FT450DRadio):
    """Yaesu FT-450"""
    FT450 = True
    MODEL = "FT-450"

    @classmethod
    def match_model(cls, filedata, filename):
        return False
