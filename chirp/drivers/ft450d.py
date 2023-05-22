# Copyright 2020 by Rick DeWitt (aa0rd@yahoo.com)   Vers 2.0
# Vers 2.0 removes all Special Channels references. Nobody cares.
# This version is Py3 Conpliant and supports FT-450 and 450AT aliases
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>

"""FT450D Yaesu Radio Driver"""

import os
import struct
import time
import logging

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.drivers import yaesu_clone
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings
from textwrap import dedent

LOG = logging.getLogger(__name__)

HAS_FUTURE = True
try:                         # PY3 compliance
    from builtins import bytes
except ImportError:
    HAS_FUTURE = False
    LOG.warning('python-future package is not '
                'available; %s requires it' % __name__)

CMD_ACK = 6
MEM_GRP_LBL = False     # To ignore Comment channel-tags for now

class FTX450Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FT-450 Base class"""
    BAUD_RATE = 38400
    COM_BITS = 8    # number of data bits
    COM_PRTY = 'N'   # parity checking
    COM_STOP = 1   # stop bits
    MODEL = "FT-X450"
    # MODES = ["LSB", "USB",  "CW",  "AM", "FM", "RTTY-L",
    #         "USER-L", "USER-U", "NFM", "CWR"]
    MODES = ["LSB", "USB",  "CW",  "AM", "FM", "RTTY",
            "PKT", "DIG", "NFM", "CWR"]
    T_STEPS = sorted(list(chirp_common.TUNING_STEPS))
    T_STEPS.remove(30.0)
    T_STEPS.remove(100.0)
    T_STEPS.remove(125.0)
    T_STEPS.remove(200.0)
    DUPLEX = ["", "-", "+"]
    TMODES = ["", "Tone", "TSQL"]
    STEPSFM = [5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
    STEPSAM = [2.5, 5.0, 9.0, 10.0, 12.5, 25.0]
    STEPSSSB = [1.0, 2.5, 5.0]
    VALID_BANDS = [(100000, 33000000), (33000000, 56000000)]
    FUNC_LIST = ['MONI', 'N/A', 'PBAK', 'PLAY1', 'PLAY2', 'PLAY3', 'QSPLIT',
                 'VM1REC', 'VM1TX', 'VM2MONI', 'VM2REC', 'VM2TX', 'DOWN',
                 'FAST', 'UP', 'DSP', 'IPO/ATT', 'NB', 'AGC', 'MODEDN',
                 'MODEUP', 'DSP/SEL', 'KEYER', 'CLAR', 'BANDDN', 'BANDUP',
                 'A=B', 'A/B', 'LOCK', 'TUNE', 'VOICE', 'MW', 'V/M', 'HOME',
                 'RCL', 'VOX', 'STO', 'STEP', 'SPLIT', 'PMS', 'SCAN', 'MENU',
                 'SPOT', 'SQLOFF', 'SWR', 'TXW', 'VCC', 'VOICE2', 'VM1MONI',
                 'DIMMER', 'MTR']
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
                dnr_on:1
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
            u8  sql_rfg:1
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
                stby_beep:1
                set15b:1
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
                rtytpol:1
                rty_sft:2,
                rty_ton:1,
                set2CC:1;
            u8  dig_vox;        // 1:1
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
            u8  myb_24:1,          // My Band: 24Mhz set = OFF
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

        #seekto 0x58;
        struct mem_struct vfoa[11]; // The current cfgs for each vfo 'band'
        struct mem_struct vfob[11];
        struct mem_struct home[2];  // The 2 Home cfgs (HF and 6m)
        struct mem_struct qmb;      // The Quick Memory Bank STO/RCL
        struct mem_struct mtqmb;    // Last QMB-MemTune cfg (not displayed)
        struct mem_struct mtune;    // Last MemTune cfg (not displayed)

        #seekto 0x343;          // chan status
        u8 visible[63];         // 1 bit per channel
        u8 pmsvisible;          // @ 0x382

        #seekto 0x383;
        u8 filled[63];
        u8 pmsfilled;           // @ 0x3c2

        #seekto 0x3C3;
        struct mem_struct memory[500];
        struct mem_struct pms[4];       // Programed Scan limits @ x387F

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
    _CALLSIGN_CHARSET = chirp_common.CHARSET_ASCII
    _CALLSIGN_CHARSET_REV = dict(zip(_CALLSIGN_CHARSET,
                                     range(0, len(_CALLSIGN_CHARSET))))

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = _(dedent("""
            The FT-450 radio driver uses CHIRP standard mode terminology.
                USER-U = DIG
                USER-L = PKT
                RTTY-L = RTTY
            This driver also populates the 'Other' tab in the channel
            memory Properties window. This tab contains values for
            those channel memory settings that don't fall under the
            standard Chirp display columns.
            """))
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to ACC jack.
            3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys while
                 turning the radio on ("CLONE MODE" will appear on the
                 display).
            4. <b>After clicking OK</b> here, press the [C.S.] key to
                send the image.
            5. Cycle power on the radio to exit clone mode."""))
        rp.pre_upload = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to ACC jack.
            3. Press and hold in the [MODE &lt;] and [MODE &gt;] keys while
                 turning the radio on ("CLONE MODE" will appear on the
                 display).
            4. Click OK here.
                ("Receiving" will appear on the LCD)."""))
        return rp

    def _read(self, block, blocknum):
        # be very patient at first block
        if blocknum == 0:
            attempts = 60
        else:
            attempts = 5
        for _i in range(0, attempts):
            LOG.debug("Block %d, asking for %d bytes." 
                      % (blocknum, block + 2))
            bdata = bytes(self.pipe.read(block + 2))
            if bdata:
                LOG.debug("Response was %d bytes:\n%s" 
                          % (len(bdata), util.hexprint(bdata)))
                break
            time.sleep(0.5)
        if len(bdata) == block + 2 and bdata[0] == blocknum:
            checksum = yaesu_clone.YaesuChecksum(1, block)
            if checksum.get_existing(bdata) != \
                    checksum.get_calculated(bdata):
                raise Exception("Checksum Failed [%02X<>%02X] block %02X" %
                                (checksum.get_existing(bdata),
                                 checksum.get_calculated(bdata), blocknum))
            # Remove the block number and checksum
            bdata = bdata[1:block + 1]
        else:   # Use this info to decode a new Yaesu model
            msg = "Unable to read block %i; expected %i bytes, got %i." \
                   % (blocknum, block + 2, len(bdata))
            raise Exception(msg)
        return bdata

    def _clone_in(self):
        # Be very patient with the radio
        self.pipe.timeout = 2
        self.pipe.baudrate = self.BAUD_RATE
        self.pipe.bytesize = self.COM_BITS
        self.pipe.parity = self.COM_PRTY
        self.pipe.stopbits = self.COM_STOP
        self.pipe.rtscts = False
        
        start = time.time()

        data = bytes(b"")
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
                chunk = self._read(block, blocks)    # returns bytes()
                data += chunk
                self.pipe.write(bytes(chr(CMD_ACK), encoding='utf8'))
                blocks += 1
                status.cur = blocks
                self.status_fn(status)
        data += bytes(self.MODEL, encoding='utf8')      # Append ID
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
                checksum = yaesu_clone.YaesuChecksum(pos,
                                                     pos + block - 1)                
                LOG.debug("Sending block %s" % hex(blocks))
                self.pipe.write(bytes(chr(blocks), encoding = 'latin-1'))
                blkdat = self.get_mmap()[pos:pos + block]
                LOG.debug("Sending %d bytes:\n%s" 
                          % (len(blkdat), util.hexprint(blkdat)))
                self.pipe.write(blkdat)
                # get_calculated uses mmap range set in YaesuChecksum
                xs = checksum.get_calculated(self.get_mmap())
                LOG.debug("Sending checksum %s" % hex(xs))
                self.pipe.write(bytes(chr(xs), encoding = 'latin-1'))
                buf = bytes(self.pipe.read(1))
                if not buf or buf[0] != CMD_ACK:
                    time.sleep(delay)
                    buf = bytes(self.pipe.read(1))
                if not buf or buf[0] != CMD_ACK:
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
            LOG.debug("\n---- Starting clone_out -----")
            self._clone_out()
            LOG.debug("---- clone_out complete -----\n")
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
        rf.has_nostep_tuning = True     # New
        rf.valid_modes = list(self.MODES)
        rf.valid_tmodes = list(self.TMODES)
        rf.valid_duplexes = list(self.DUPLEX)
        rf.valid_tuning_steps = list(self.T_STEPS)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_power_levels = []
        rf.valid_characters = "".join(self.CHARSET)
        rf.valid_name_length = 7
        rf.valid_skips = []
        rf.memory_bounds = (1, 500)
        rf.has_ctone = True
        rf.has_settings = True
        rf.has_cross = True
        if MEM_GRP_LBL:
            rf.has_comment = True   # Used for Mem-Grp number
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
        propflg = False
        if isinstance(number, int):     # Called by Properties
            if number > 500:
                propflg = True
        return self._get_normal(number)

    def set_memory(self, memory):
        return self._set_normal(memory)

    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)
        return msgs

    def _get_normal(self, number):
        _mem = self._memobj.memory[number - 1]
        used = (self._memobj.visible[(number - 1) // 8] >>
                (number - 1) % 8) & 0x01
        valid = (self._memobj.filled[(number - 1) // 8] >>
                 (number - 1) % 8) & 0x01

        mem = chirp_common.Memory()
        mem.number = number
        if not used:
            mem.empty = True
            if not valid or _mem.freq == 0xffffffff:
                return mem
        if MEM_GRP_LBL:
            mgrp = int((number - 1) // 50)
            mem.comment = "M-%02i-%02i" % (mgrp + 1, number - (mgrp * 50))

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

        return self._get_memory(mem, _mem)

    def _set_normal(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        wasused = (self._memobj.visible[(mem.number - 1) // 8] >>
                   (mem.number - 1) % 8) & 0x01
        wasvalid = (self._memobj.filled[(mem.number - 1) // 8] >>
                    (mem.number - 1) % 8) & 0x01

        if mem.empty:
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
        vx = _mem.mode
        if vx == 4:         # FM or NFM
            if _mem.mode2 == 2:
                vx = 4          # FM
            else:
                vx = 8          # NFM
        if vx == 10:         # CWR
                vx = 9
        if vx == 5:         # Data/Dual mode
            if _mem.mode2 == 0:          # RTTY-L (RTTY)
                vx = 5
            if _mem.mode2 == 1:     # USER-L (PKT)
                vx = 6
            if _mem.mode2 == 2:      # USER-U (DIG)
                vx = 7
        mem.mode = self.MODES[vx]
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
        mem.extra = RadioSettingGroup("extra", "Extra")

        rx = RadioSettingValueBoolean(bool(_mem.ipo))
        sx = "IPO"
        rs = RadioSetting("ipo", sx, rx)
        rs.set_doc("Bypass preamp")
        mem.extra.append(rs)

        rx = RadioSettingValueBoolean(bool(_mem.att))
        sx = "ATT"
        rs = RadioSetting("att", sx, rx)
        rs.set_doc("10dB front end attenuator")
        mem.extra.append(rs)

        rx = RadioSettingValueBoolean(_mem.cnturon)
        sx = "Contour Filter"
        rs = RadioSetting("cnturon", sx, rx)
        rs.set_doc("Contour filter on/off")
        mem.extra.append(rs)

        options = ["Peak", "Null"]
        rx = RadioSettingValueList(options, options[_mem.cnturpk])
        sx = "Contour Filter Mode"
        rs = RadioSetting("cnturpk", sx, rx)
        rs.set_doc("Contour Filter Type")
        mem.extra.append(rs)

        options = ["Low", "High"]
        rx = RadioSettingValueList(options, options[_mem.cnturgn])
        sx = "Contour Filter Gain"
        rs = RadioSetting("cnturgn", sx, rx)
        rs.set_doc("Filter gain/attenuation")
        mem.extra.append(rs)

        options = ["-2", "-1", "Center", "+1", "+2"]
        rx = RadioSettingValueList(options, options[_mem.cnturmd])
        sx = "Contour Filter Notch"
        rs = RadioSetting("cnturmd", sx, rx)
        rs.set_doc("Filter notch offset")
        mem.extra.append(rs)

        rx = RadioSettingValueBoolean(_mem.notch)
        sx = "Notch Filter"
        rs = RadioSetting("notch", sx, rx)
        rs.set_doc("IF bandpass filter")
        mem.extra.append(rs)

        vx = 1
        options = ["<-", "Center", "+>"]
        if _mem.notch_pos < 0:
            vx = 0
        if _mem.notch_pos > 0:
            vx = 2
        rx = RadioSettingValueList(options, options[vx])
        sx = "Notch Position"
        rs = RadioSetting("notch_pos", sx, rx)
        rs.set_doc("IF bandpass filter shift")
        mem.extra.append(rs)

        vx = 0
        if mem.mode[1:] == "SB":
            options = ["1.8kHz", "2.4kHz", "3.0kHz"]
            vx = _mem.sb_width
            stx = "sb_width"
        elif mem.mode[:1] == "CW":
            options = ["300Hz", "500 kHz", "2.4kHz"]
            vx = _mem.cw_width
            stx = "cw_width"
        elif mem.mode[:4] == "USER" or mem.mode[:4] == "RTTY":
            options = ["300Hz", "2.4kHz", "3.0kHz"]
            vx = _mem.sb_width
            stx = "sb_width"
        elif mem.mode == "AM":
            options = ["3.0kHz", "6.0kHz", "9.0 kHz"]
            vx = _mem.am_width
            stx = "am_width"
        else:
            options = ["2.5kHz", "5.0kHz"]
            vx = _mem.fm_width
            stx = "fm_width"
        rx = RadioSettingValueList(options, options[vx])
        sx = "IF Bandpass Filter Width"
        rs = RadioSetting(stx, sx, rx)
        rs.set_doc("DSP IF bandpass Notch width (Hz)")
        mem.extra.append(rs)

        rx = RadioSettingValueBoolean(bool(_mem.dnr_on))
        sx = "DSP Noise Reduction"
        rs = RadioSetting("dnr_on", sx, rx)
        rs.set_doc("Digital noise processing")
        mem.extra.append(rs)

        options = ["Off", "1", "2", "3", "4", "5", "6", "7",
                          "8", "9", "10", "11"]
        rx = RadioSettingValueList(options, options[_mem.dnr_val])
        sx = "DSP Noise Reduction Alg"
        rs = RadioSetting("dnr_val", sx, rx)
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
        if mem.mode == "PKt":       # USER-L
            _mem.mode = 5
            _mem.mode2 = 1
        elif mem.mode == "DIG":     # USER-U
            _mem.mode = 5
            _mem.mode2 = 2
        elif mem.mode == "RTTY":    # RTTY-L
            _mem.mode = 5
            _mem.mode2 = 0
        elif mem.mode == "CWR":
            _mem.mode = 10
            _mem.mode2 = 0
        elif mem.mode == "CW":
            _mem.mode = 2
            _mem.mode2 = 0
        elif mem.mode == "NFM":
            _mem.mode = 4
            _mem.mode2 = 1
        elif mem.mode == "FM":
            _mem.mode = 4
            _mem.mode2 = 2
        else:           # LSB, USB, AM
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
                vx = 0          # Overide list string with signed value
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
            else:
                setattr(_mem, setting.get_name(), setting.value)

    @classmethod
    def match_model(cls, filedata, filename):
        """Match the opened/downloaded image to the correct version"""
        if len(filedata) == cls.MEM_SIZE + 7:    # +7 bytes of model name
            rid = filedata[cls.MEM_SIZE:cls.MEM_SIZE + 7]
            if rid.startswith(bytes(cls.MODEL)):
                return True
        else:
            return False

    def _invert_me(self, setting, obj, atrb):
        """Callback: from inverted logic 1-bit booleans"""
        invb = not setting.value
        setattr(obj, atrb, invb)

    def _chars2str(self, cary, knt):
        """Convert raw memory char array to a string: NOT a callback."""
        stx = ""
        for j in range(0, knt, 1):
            stx += str(cary[j])
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

        top = RadioSettings(gen, cw, pnlcfg, pnlset, voxdat, mic,
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

        rx = RadioSettingValueBoolean(_settings.ext_mnu)
        tmp = "Extended menu"
        rs = RadioSetting("ext_mnu", tmp, rx)
        rs.set_doc("Enables access to extended settings in the radio")
        tab.append(rs)

        # Issue #8183 bugfix
        rx = RadioSettingValueInteger(0, 12, _settings.apo)
        tmp = "Auto Power Off time (Hrs)"
        rs = RadioSetting("apo", tmp, rx)
        tab.append(rs)

        options = ["%i" % i for i in range(0, 21)]
        options[0] = "Off"
        optn = options[_settings.tot]
        rx = RadioSettingValueList(options, optn)
        tmp = "TX 'TOT' time-out (mins)"
        rs = RadioSetting("tot", tmp, rx)
        tab.append(rs)

        bx = not _settings.cat_rts     # Convert from Enable=0
        rx = RadioSettingValueBoolean(bx)
        tmp = "CAT RTS flow control"
        rs = RadioSetting("cat_rts", tmp, rx)
        rs.set_apply_callback(self._invert_me, _settings, "cat_rts")
        tab.append(rs)

        options = ["0", "100ms", "1000ms", "3000ms"]
        optn = options[_settings.cat_tot]
        rx = RadioSettingValueList(options, optn)
        tmp = "CAT Timeout"
        rs = RadioSetting("cat_tot", tmp, rx)
        tab.append(rs)

        options = ["4800", "9600", "19200", "38400", "Data"]
        optn = options[_settings.catrate]
        rx = RadioSettingValueList(options, optn)
        tmp = "CAT rate"
        rs = RadioSetting("catrate", tmp, rx)
        tab.append(rs)

        rx = RadioSettingValueBoolean(_settings.mem_grp)
        tmp = "Mem groups"
        rs = RadioSetting("mem_grp", tmp, rx)
        tab.append(rs)

        val = _settings.scn_res
        rx = RadioSettingValueInteger(0, 10, val)
        tmp = "Resume scan (secs)"
        rs = RadioSetting("scn_res", tmp, rx)
        tab.append(rs)

        rx = RadioSettingValueBoolean(_settings.clk_sft)
        tmp = "CPU clock shift"
        rs = RadioSetting("clk_sft", tmp, rx)
        tab.append(rs)

        rx = RadioSettingValueBoolean(_settings.split)
        tmp = "TX/RX Frequency Split"
        rs = RadioSetting("split", tmp, rx)
        tab.append(rs)

        val = _settings.qspl_f
        rx = RadioSettingValueInteger(-20, 20, val)
        tmp = "Quick-Split freq offset (KHz)"
        rs = RadioSetting("qspl_f", tmp, rx)
        tab.append(rs)

        rx = RadioSettingValueBoolean(_settings.emergen)
        tmp = "Alaska Emergency Mem 5167.5KHz"
        rs = RadioSetting("emergen", tmp, rx)
        tab.append(rs)

        rx = RadioSettingValueBoolean(_settings.stby_beep)
        tmp = "PTT release 'Standby' beep"
        rs = RadioSetting("stby_beep", tmp, rx)
        tab.append(rs)

        if self.MODEL != "FT-450":
            options = ["ATAS", "EXT ATU", "INT ATU", "INTRATU", "F-TRANS"]
            optn = options[_settings.tuner]
            rx = RadioSettingValueList(options, optn)
            tmp = "Antenna Tuner"
            rs = RadioSetting("tuner", tmp, rx)
            tab.append(rs)

        val = _settings.rfpower
        rx = RadioSettingValueInteger(5, 100, val)
        tmp = "RF power (watts)"
        rs = RadioSetting("rfpower", tmp, rx)
        tab.append(rs)      # End of _do_general_settings


    def _do_cw_settings(self, cw):        # - - - CW - - -
        _settings = self._memobj.settings
        _beacon = self._memobj.beacontext

        val = _settings.cw_dly
        rx = RadioSettingValueInteger(0, 300, val)
        tmp = "CW break-in delay (ms * 10)"
        rs = RadioSetting("cw_dly", tmp, rx)
        cw.append(rs)

        options = ["%i Hz" % i for i in range(400, 801, 100)]
        optn = options[_settings.cwpitch]
        rx = RadioSettingValueList(options, optn)
        tmp = "CW pitch"
        rs = RadioSetting("cwpitch", tmp, rx)
        cw.append(rs)

        val = _settings.cwspeed
        rx = RadioSettingValueInteger(4, 60, val)
        tmp = "CW speed (wpm)"
        rs = RadioSetting("cwspeed", tmp, rx)
        rs.set_doc("Cpm is Wpm * 5")
        cw.append(rs)

        options = ["1:%1.1f" % (float(val)/10.0) for val in range(25, 46, 1)]
        optn = options[_settings.cwweigt]
        rx = RadioSettingValueList(options, optn)
        tmp = "CW weight"
        rs = RadioSetting("cwweigt", tmp, rx)
        cw.append(rs)

        options = ["15ms", "20ms", "25ms", "30ms"]
        optn = options[_settings.cw_qsk]
        rx = RadioSettingValueList(options, optn)
        tmp = "CW delay before TX in QSK mode"
        rs = RadioSetting("cw_qsk", tmp, rx)
        cw.append(rs)

        rx = RadioSettingValueBoolean(_settings.cwstone_sgn)
        tmp = "CW sidetone volume Linked"
        rs = RadioSetting("cwstone_sgn", tmp, rx)
        cw.append(rs)

        val = _settings.cwstone_lnk
        rx = RadioSettingValueInteger(-50, 50, val)
        tmp = "CW sidetone linked volume"                                             
        rs = RadioSetting("cwstone_lnk", tmp, rx)
        cw.append(rs)

        val = _settings.cwstone_fix
        rx = RadioSettingValueInteger(0, 100, val)
        tmp = "CW sidetone fixed volume"                                  
        rs = RadioSetting("cwstone_fix", tmp, rx)
        cw.append(rs)

        options = ["Numeric", "Alpha", "Mixed"]
        optn = options[_settings.cwtrain]
        rx = RadioSettingValueList(options, optn)
        tmp = "CW Training mode"
        rs = RadioSetting("cwtrain", tmp, rx)
        cw.append(rs)

        rx = RadioSettingValueBoolean(_settings.cw_auto)
        tmp = "CW key jack- auto CW mode"
        rs = RadioSetting("cw_auto", tmp, rx)
        rs.set_doc("Enable for CW mode auto-set when keyer plugged in.")
        cw.append(rs)

        options = ["Normal", "Reverse"]
        optn = options[_settings.cw_key]
        rx = RadioSettingValueList(options, optn)
        tmp = "CW paddle wiring"
        rs = RadioSetting("cw_key", tmp, rx)
        cw.append(rs)

        val = _settings.beacon_time
        rx = RadioSettingValueInteger(0, 255, val)
        tmp = "CW beacon Tx interval (secs)"                                                          
        rs = RadioSetting("beacon_time", tmp, rx)
        cw.append(rs)

        tmp = self._chars2str(_beacon.t1, 40)
        rx = RadioSettingValueString(0, 40, tmp)
        tmp = "CW Beacon Line 1"
        rs=RadioSetting("t1", tmp, rx)
        rs.set_apply_callback(self._my_str2ary, _beacon, "t1", 40)
        cw.append(rs)

        tmp = self._chars2str(_beacon.t2, 40)
        rx = RadioSettingValueString(0, 40, tmp)
        tmp = "CW Beacon Line 2"
        rs=RadioSetting("t2", tmp, rx)
        rs.set_apply_callback(self._my_str2ary, _beacon, "t2", 40)
        cw.append(rs)

        tmp = self._chars2str(_beacon.t3, 40)
        rx = RadioSettingValueString(0, 40, tmp)
        tmp = "CW Beacon Line 3"
        rs=RadioSetting("t3", tmp, rx)
        rs.set_apply_callback(self._my_str2ary, _beacon, "t3", 40)
        cw.append(rs)       # END _do_cw_settings


    def _do_panel_settings(self, pnlset):    # - - - Panel settings
        _settings = self._memobj.settings

        bx = not _settings.amfmdial     # Convert from Enable=0
        rx = RadioSettingValueBoolean(bx)
        tmp = "AM&FM Dial"
        rs = RadioSetting("amfmdial", tmp, rx)
        rs.set_apply_callback(self._invert_me, _settings, "amfmdial")
        pnlset.append(rs)

        options = ["440Hz", "880Hz", "1760Hz"]
        optn = options[_settings.beepton]
        rx = RadioSettingValueList(options, optn)
        tmp = "Beep frequency"
        rs = RadioSetting("beepton", tmp, rx)
        pnlset.append(rs)

        rx = RadioSettingValueBoolean(_settings.beepvol_sgn)
        tmp = "Beep volume Linked"
        rs = RadioSetting("beepvol_sgn", tmp, rx)
        rs.set_doc("If set; volume is relative to AF Gain knob.")
        pnlset.append(rs)

        val = _settings.beepvol_lnk
        rx = RadioSettingValueInteger(-50, 50, val)
        tmp = "Linked beep volume"
        rs = RadioSetting("beepvol_lnk", tmp, rx)
        rs.set_doc("Relative to AF-Gain setting.")
        pnlset.append(rs)

        val = _settings.beepvol_fix
        rx = RadioSettingValueInteger(0, 100, val)
        tmp = "Fixed beep volume"
        rs = RadioSetting("beepvol_fix", tmp, rx)
        rs.set_doc("When Linked setting is unchecked.")
        pnlset.append(rs)

        rx = RadioSettingValueInteger(1, 24, _settings.cont)
        tmp = "LCD Contrast"
        rs = RadioSetting("cont", tmp, rx)
        rs.set_doc("This setting does not appear to do anything...")
        pnlset.append(rs)

        rx = RadioSettingValueInteger(1, 8, _settings.dimmer)
        tmp = "LCD Dimmer"
        rs = RadioSetting("dimmer", tmp, rx)
        pnlset.append(rs)

        options = ["RF-Gain", "Squelch"]
        optn = options[_settings.sql_rfg]
        rx = RadioSettingValueList(options, optn)
        tmp = "Squelch/RF-Gain"
        rs = RadioSetting("sql_rfg", tmp, rx)
        pnlset.append(rs)

        options = ["Frequencies", "Panel", "All"]
        optn = options[_settings.lockmod]
        rx = RadioSettingValueList(options, optn)
        tmp = "Lock Mode"
        rs = RadioSetting("lockmod", tmp, rx)
        pnlset.append(rs)

        options = ["Dial", "SEL"]
        optn = options[_settings.clar_btn]
        rx = RadioSettingValueList(options, optn)
        tmp = "CLAR button control"
        rs = RadioSetting("clar_btn", tmp, rx)
        pnlset.append(rs)

        if _settings.dialstp_mode == 0:             # AM/FM
            options = ["SSB/CW:1Hz", "SSB/CW:10Hz", "SSB/CW:20Hz"]
        else:
            options = ["AM/FM:100Hz", "AM/FM:200Hz"]
        optn = options[_settings.dialstp]
        rx = RadioSettingValueList(options, optn)
        tmp = "Dial tuning step"
        rs = RadioSetting("dialstp", tmp, rx)
        pnlset.append(rs)

        options = ["0.5secs", "1.0secs", "1.5secs", "2.0secs"]
        optn = options[_settings.keyhold]
        rx = RadioSettingValueList(options, optn)
        tmp = "Buttons hold-to-activate time"
        rs = RadioSetting("keyhold", tmp, rx)
        pnlset.append(rs)

        rx = RadioSettingValueBoolean(_settings.m_tune)
        tmp = "Memory tune"
        rs = RadioSetting("m_tune", tmp, rx)
        pnlset.append(rs)

        rx = RadioSettingValueBoolean(_settings.peakhold)
        tmp = "S-Meter display hold (1sec)"
        rs = RadioSetting("peakhold", tmp, rx)
        pnlset.append(rs)

        options = ["CW Sidetone", "CW Speed", "100KHz step", "1MHz Step",
                   "Mic Gain", "RF Power"]
        optn = options[_settings.seldial]
        rx = RadioSettingValueList(options, optn)
        tmp = "SEL dial 2nd function (push)"
        rs = RadioSetting("seldial", tmp, rx)
        pnlset.append(rs)
    # End _do_panel_settings

    def _do_panel_buttons(self, pnlcfg):    # Current Panel Config
        _settings = self._memobj.settings

        optn = self.FUNC_LIST[_settings.pnl_cs]
        rx = RadioSettingValueList(self.FUNC_LIST, optn)
        tmp = "C.S. Function"
        rs = RadioSetting("pnl_cs", tmp, rx)
        pnlcfg.append(rs)

        rx = RadioSettingValueBoolean(_settings.nb)
        tmp = "Noise blanker"
        rs = RadioSetting("nb", tmp, rx)
        pnlcfg.append(rs)

        options = ["Auto", "Fast",  "Slow", "Auto/Fast", "Auto/Slow", "?5?"]
        optn = options[_settings.agc]
        rx = RadioSettingValueList(options, optn)
        tmp = "AGC"
        rs = RadioSetting("agc", tmp, rx)
        pnlcfg.append(rs)

        rx = RadioSettingValueBoolean(_settings.keyer)
        tmp = "Keyer"
        rs = RadioSetting("keyer", tmp, rx)
        pnlcfg.append(rs)

        rx = RadioSettingValueBoolean(_settings.fast)
        tmp = "Fast step"
        rs = RadioSetting("fast", tmp, rx)
        pnlcfg.append(rs)

        rx = RadioSettingValueBoolean(_settings.lock)
        tmp = "Lock (per Lock Mode)"
        rs = RadioSetting("lock", tmp, rx)
        pnlcfg.append(rs)

        options = ["PO",  "ALC", "SWR"]
        optn = options[_settings.mtr_mode]
        rx = RadioSettingValueList(options, optn)
        tmp = "S-Meter mode"
        rs = RadioSetting("mtr_mode", tmp, rx)
        pnlcfg.append(rs)
        # End _do_panel_Buttons

    def _do_vox_settings(self, voxdat):     # VOX and DATA Settings
        _settings = self._memobj.settings

        rx = RadioSettingValueInteger(1, 30, _settings.vox_dly)
        tmp = "VOX delay (x 100 ms)"
        rs = RadioSetting("vox_dly", tmp, rx)
        voxdat.append(rs)

        rx = RadioSettingValueInteger(0, 100, _settings.vox_gain)
        tmp = "VOX Gain"
        rs = RadioSetting("vox_gain", tmp, rx)
        voxdat.append(rs)

        rx = RadioSettingValueInteger(0, 100, _settings.dig_vox)
        tmp = "Digital VOX Gain"                                     
        rs = RadioSetting("dig_vox", tmp, rx)
        voxdat.append(rs)

        val = _settings.d_disp
        rx = RadioSettingValueInteger(-3000, 30000, val, 10)
        tmp = "User-L/U freq offset (Hz)"
        rs = RadioSetting("d_disp", tmp, rx)
        voxdat.append(rs)

        options = ["170Hz", "200Hz", "425Hz", "850Hz"]
        optn = options[_settings.rty_sft]
        rx = RadioSettingValueList(options, optn)
        tmp = "RTTY FSK Freq Shift"
        rs = RadioSetting("rty_sft", tmp, rx)
        voxdat.append(rs)

        options = ["1275Hz", "2125Hz"]
        optn = options[_settings.rty_ton]
        rx = RadioSettingValueList(options, optn)
        tmp = "RTTY FSK Mark tone"
        rs = RadioSetting("rty_ton", tmp, rx)
        voxdat.append(rs)

        options = ["Normal", "Reverse"]
        optn = options[_settings.rtyrpol]
        rx = RadioSettingValueList(options, optn)
        tmp = "RTTY Mark/Space RX polarity"
        rs = RadioSetting("rtyrpol", tmp, rx)
        voxdat.append(rs)

        optn = options[_settings.rtytpol]
        rx = RadioSettingValueList(options, optn)
        tmp = "RTTY Mark/Space TX polarity"
        rs = RadioSetting("rtytpol", tmp, rx)
        voxdat.append(rs)
        # End _do_vox_settings

    def _do_mic_settings(self, mic):    # - - MIC Settings
        _settings = self._memobj.settings

        rx = RadioSettingValueInteger(0, 9, _settings.mic_eq)
        tmp = "Mic Equalizer (0-9)"
        rs = RadioSetting("mic_eq", tmp, rx)
        mic.append(rs)

        options = ["Low", "Normal", "High"]
        optn = options[_settings.micgain]
        rx = RadioSettingValueList(options, optn)
        tmp = "Mic Gain"
        rs = RadioSetting("micgain", tmp, rx)
        mic.append(rs)

        rx = RadioSettingValueBoolean(_settings.micscan)
        tmp = "Mic scan enabled"
        rs = RadioSetting("micscan", tmp, rx)
        rs.set_doc("Enables channel scanning via mic up/down buttons.")
        mic.append(rs)

        optn = self.FUNC_LIST[_settings.pm_dwn]
        rx = RadioSettingValueList(self.FUNC_LIST, optn)
        tmp = "Mic Down button function"
        rs = RadioSetting("pm_dwn", tmp, rx)
        mic.append(rs)

        optn = self.FUNC_LIST[_settings.pm_fst]
        rx = RadioSettingValueList(self.FUNC_LIST, optn)
        tmp = "Mic Fast button function"
        rs = RadioSetting("pm_fst", tmp, rx)
        mic.append(rs)

        optn = self.FUNC_LIST[_settings.pm_up]
        rx = RadioSettingValueList(self.FUNC_LIST, optn)
        tmp = "Mic Up button function"
        rs = RadioSetting("pm_up", tmp, rx)
        mic.append(rs)
        # End _do_mic_settings

    def _do_mymodes_settings(self, mymodes):    # - - MYMODES
        _settings = self._memobj.settings # Inverted Logic requires callback

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
                except Exception as e:
                    LOG.debug(element.get_name())
                    raise


class FT450Alias(chirp_common.Alias):
    """ ALias for Yaesu FT-450 original radio """
    VENDOR = "Yaesu"
    MODEL = "FT-450"


class FT450ATAlias(chirp_common.Alias):
    """ ALias for Yaesu FT-450AT radio with tuner """
    VENDOR = "Yaesu"
    MODEL = "FT-450AT"


if HAS_FUTURE:    # Only register driver if environment is PY3 compliant
    @directory.register
    class FT450DRadio(FTX450Radio):
        """Yaesu FT-450D"""
        VENDOR = "Yaesu"
        MODEL = "FT-450D"
        ALIASES = [FT450Alias, FT450ATAlias, ]
