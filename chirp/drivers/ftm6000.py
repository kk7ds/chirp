# Copyright 2018 by Rick DeWitt (aa0rd@yahoo.com) V1.0
# Issues 9719 for FTM-6000 and 11137 for FTM-200
# Note: 'TESTME' flags are intended for use with future sub-models
# FTM-100, FTM-300 and FTM-500 can probably be supported
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

"""FTM-6000 Yaesu Radio Driver"""

from chirp.drivers import yaesu_clone
from chirp import chirp_common, util, memmap, errors, directory, bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings
import time
import struct
import logging
import math
import sys

LOG = logging.getLogger(__name__)
CMD_ACK = b'\x06'


class Ftm6000RAlias(chirp_common.Alias):
    Vendor = "Yaesu"
    MODEL = "FTM-6000R"


@directory.register
class FTM6000Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FTM-6000"""
    FTM200 = False
    TESTME = False
    NEEDS_COMPAT_SERIAL = False
    BAUD_RATE = 38400
    COM_BITS = 8
    COM_PRTY = 'N'
    COM_STOP = 1
    MODEL = "FTM-6000"
    NAME_LEN = 6        # Valid Name Length
    ALIASES = [Ftm6000RAlias]
    MODES = ["FM", "AM", "NFM"]
    TMODES = ["", "Tone", "TSQL", "TSQL-R", "DTCS", "Cross"]
    CROSS_MODES = ["->DTCS", "Tone->DTCS", "DTCS->Tone"]
    DUPLEX = ["", "off", "-", "+", "split"]
    T_STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
    VALID_BANDS = [(108000000, 137000000),
                   (137000000, 174000000),
                   (174000000, 400000000),
                   (400000000, 480000000),
                   (480000000, 999999999)]
    POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=50),
                    chirp_common.PowerLevel("Mid", watts=20),
                    chirp_common.PowerLevel("Low", watts=5)]
    SKIPS = ["", "S"]
    # No lowercase,{} or ~
    CHARSET = [chr(x) for x in list(range(ord(" "), ord("_") + 1)) +
               [ord("|")]]
    DTMF_CHARS = list("0123456789ABCD*#")
    MEM_FORMAT = """
        struct memdat {         // 16 bytes per chan
          u8 used:1,            // 00
             skip:2,
             unk1:2,
             band:3;
          u8 clks:1,            // 01
             xx:1,
             mode:2,
             duplex:4;
          u24 freq;            // 02-04
          u8 tmode:4,           // 05
             step:4;
          u24 frqtx;            // 06-08
          u8 power:2,           // 09
             rtone:6;
          u8 clktyp:1,          // 0A,
             dtcs:7;
          u8 prfreq;            // 0B
          u16 offset;           // 0C-0D 0-99.95 MHz in 0.5 steps 06.0 is 00 0c
          u8 unk3;              // 0E
          u8 unk4;              // 0F
        };

        struct tag {
          u8 chname[16];
        };

        struct pmgx {
          u8 za;                // 0x00
          u8 fb;                // 0xff
          u16 chnp;             // 0-based pmg channel number
        };

        struct {                // In 1st block
            u8 id[6];
        } model;
        #seekto 0x080;
        struct memdat vfo_air;      // 080
        struct memdat vfo_144;      // 090
        struct memdat vfo_vhf;      // 0a0
        struct memdat vfo_430;      // 0b0
        struct memdat vfo_uhf;      // 0c0
        struct memdat unkc1[5];     // 0d0 - 0110  repeats vfo entries
        u8 120[16];                 // 0x120  all ff
        struct memdat home;         // 0x130
        u8 ff2[64];                 // 0x140 - 0x17f; ff's'
        struct memdat unkc2;        // 0x180 possible last chan accessed?
        #seekto 0x200;
        struct {
            u8 20axd[14];           // 0x200 - 0x20d
            u8 xm0au:5,             // 0x20e
               bell:3;
            u8 xm0bu:6,             // 020f
               lcd:2;
            u8 210xd[14];           // 0210 - 021d
            u8 21ea:5,
               bellb:3;
            u8 wrxdid;              // 21f
            u8 220x1[2];            // 220 -221
            u8 fkp1;                // 0x222: FTM-200 keypad quick access 1
            u8 fhm1;                // 0x223: FTM-200 home qa 1
            u8 fkp2;
            u8 fhm2;
            u8 fkp3;
            u8 fhm3;
            u8 fkp4;
            u8 fhm4;                // 0x229
            u8 22axf[6];
            u8 230x7[8];            // 230-237
            u24 wrxvfrq;
            u8 23b;
            u24 wrxufrq;
            u8 23f;
            u8 240a:6,
               wrxbsel:1,
               240b:1;
            u8 241x7[7];            // 24-247
            u8 csign[10];           // 248 - 251
            u8 pgrcdr1;             // 0252
            u8 pgrcdr2;
            u8 pgrcdt1;
            u8 pgrcdt2;             // 0255
            u8 256a:7,
               compass:1;
            u8 257a:7,
               usbcamsz:1;
            u8 258a:6,
               usbcamql:2;
            u8 259;
            u8 25a;
            u8 25ba:4,
               wrxpop:4;
            u8 25c;
            u8 micgain;             // 25d
            u8 25e;
            u8 micp1;               // 25f
            u8 micp2;               // 260
            u8 micp3;
            u8 micp4;
            u8 263xf[13];           // 0x263 - 026f
            u8 270xf[16];           // 0x270 - 27f
        } micset;
        struct {
            u8 codes[16];            // 0x280-30f
        } dtmfcode[9];
        #seekto 0x400;
        struct {
            u8 400a:7,               // 0400
               aprbupo:1;
            u8 401a:7,
              aprbudi:1;
            u8 402a:6,
               aprbusp:2;
            u8 403a:7,              // 0403
               aprbual:1;
            u8 404a:5,
               aprbubo:3;
            u8 405a:7,
               aprbutp:1;
            u8 406a:7,
               aprburn:1;
            u8 407a:5,
               aprbuwd:3;
            u8 aprcsgn[6];          // 0408-040d
            u8 aprcsfx;
            u8 400f;
            u8 410a:3,
              aprltns:1,
              410b:4;
            u8 aprlad;              // 0411
            u8 aprlam;
            u16 aprlas;             // 0413-0414
            u8 415a:3,
               aprlgew:1,
               415b:4;
            u8 aprlgd;
            u8 aprlgm;
            u16 aprlgs;
            u8 aprrcsn[6];          // 041a-41f
            u8 aprrcfx;             // 0420
            u8 421;
            u8 aprsym1[2];          // 0422, 423
            u8 aprsym2[2];
            u8 aprsym3[2];
            u8 aprsym4a;
            u8 aprsym4b;            // 0429
            u16 aprbfrl;            // 042a & 042b
            u8 42ca:4,
               aprsym:4;
            u8 42da:4,              // 042d
               aprdig:4;
            u8 42ea:4,
               aprstxi:4;
            u8 aprsrate;            // 042f
            u8 aprslow;             // 0430
            u8 431a:5,
               aprbamb:3;
            u8 432a:4,
               aprcmt:4;
            u8 aprspro:1,           // 0433
               aprbaut:1,
               433b:1,
               aprsdcy:1,
               aprspdc:1,
               aprsalt:1,
               433c:1,
               aprrply:1;
            u8 434a:1,              // 0434
               dspda:1,             // FTM-200 APRS
               pktspd:1,            // Both
               434b:3,
               aprmut:1,
               aprson:1;
            u8 435a:2,
               datsql:1,
               435b:5;
            u8 436a:5,
               bcnstat:3;
            u8 437a:4,            // 0x437
               bcntxra:4;
            u8 438a:1,
               aprbfot:1,
               aprbfst:1,
               aprbfit:1,
               aprbfob:1,
               aprbfwx:1,
               aprbfpo:1,
               aprbfme:1;
            u8 439a:7,
               aprbrtb:1;
            u8 43aa:7,
               aprbrtm:1;
            u8 43ba:7,
               aprbrrb:1;
            u8 43ca:7,
               aprbrrm:1;
            u8 43da:7,
               aprbrmp:1;
            u8 43ea:7,
               aprbrcr:1;
            u8 aprbrrr;             // 043f
            u8 440a:7,
               aprbrmv:1;
            u8 441a:7,
               aprmpos:1;
            u8 442;
            u8 443a:4,
               dbsela:4;
            u8 444a:4,
               dbseld:4;
            u8 aprpopb;              // 0445
            u8 aprpopm;
            u8 447a:4,
               aprtxd:4;
            u8 448a:4,
               comout:4;
            u8 449a:4,
               comspd:4;
            u8 44aa:5,
               bcnsmart:3;
            u8 typ1val0;            // 044b -> 045f
            u8 typ1val1;            // Smart Beaconing type settings
            u8 typ1val2;
            u8 typ1val3;
            u8 typ1val4;
            u8 typ1val5;
            u8 typ1val6;
            u8 typ2val0;
            u8 typ2val1;
            u8 typ2val2;
            u8 typ2val3;
            u8 typ2val4;
            u8 typ2val5;
            u8 typ2val6;
            u8 typ3val0;
            u8 typ3val1;
            u8 typ3val2;
            u8 typ3val3;
            u8 typ3val4;
            u8 typ3val5;
            u8 typ3val6;        // 045f
            u8 460a:4,
               aprstxn:4;
            u8 461a:1,
               aprmpkt:1,
               aprbfan:1,
               461b:5;
            u8 462a:4,
               comwpf:4;
            u8 463a:4,
                comflt:4;
            u8 464;
            u8 465;
            u8 466;
            u8 467;
            u8 468;
            u8 469;
            u8 46a;
            u8 46b;
            u8 46c;
            u8 46da:5,
               aprvlrt:3;
            u8 aprtsql;
            u8 aprvdcs;             // 046f
            u8 470a:6,
               aprsfs:2;
            u8 471a:4,
               aprsff:4;
            u8 472xf[14];           // -> 047f
            u8 aprrtxt[64];         // 0480 - 04BF
        } wierd;
        #seekto 0x500;
        struct {
            u8 grp1[9];
            u8 509;
            u8 grp2[9];
            u8 514;
            u8 grp3[9];
            u8 51d;
            u8 grp4[9];
            u8 527;
            u8 grp5[9];
            u8 532;
            u8 grp6[9];
            u8 53b;
            u8 blt1[9];
            u8 545;
            u8 blt2[9];
            u8 554;
            u8 blt3[9];
            u8 559;
        } aprsmsg;
        #seekto 0x580;
        struct {          // FMT-6000 Menu item Fntcn mode set table
            u8 shbyt;     // FTM-200 Digipath, RingerCS data
        } share1[256];    // -> 0x67f
        struct {            // 0x680
            u8 txt1[16];
            u8 txt2[16];
            u8 txt3[16];
            u8 txt4[16];
            u8 txt5[16];
            u8 txt6[16];
            u8 txt7[16];
            u8 txt8[16];
        } aprstxt;
        struct memdat main[999];    // 0x700 16 bytes each, up to 4570
        struct memdat pms[100];     // up to 0x4bb0
        struct memdat unkc3[5];     // unknown, up to 0x4c00
        #seekto 0x4c10;
        struct pmgx pmg[6];         // 6th element is change record
        #seekto 0x6980;
        struct {                    // WIRES-X Messages
            u8 msg01[128];
            u8 msg02[128];
            u8 msg03[128];
            u8 msg04[128];
            u8 msg05[128];
            u8 msg06[128];
            u8 msg07[128];
            u8 msg08[128];
            u8 msg09[128];
            u8 msg10[128];
        } wrxmsg;
        struct {                    // 0x6e80
            u8 c1[16];
            u8 c2[16];
            u8 c3[16];
            u8 c4[16];
            u8 c5[16];
        } wrxcat;
        #seekto 0x7d00;
        struct {                    // --> 07e3f
            u8 msg[60];
            u8 mode;
            u8 nax[3];
        } bcntxt[5];
        #seekto 0xff00;
        struct tag names[999];      // 16 bytes each, up to 0x13d6f (83055.)
        struct tag pms_name[100];   // 13d70 - 143af
        #seekto 0x17f00;
        struct {                    // Settings
            u8 f00xf[16];           // 17f00-0f
            u8 f10xf[16];           // 17f10-1f
            u8 f20;                 // 17f20
            u8 f21a:7,
               unit:1;
            u8 f22;
            u8 f23;
            u8 f24a:2,              // 17f24
                apo:5,
                apo1:1;
            u8 bclo:1,              // 17f25
                f25a:4,
                arts_int:1,
                arts_mode:2;
            u8 f26:4,              // 17f26
                airb:1,
                vhfb:1,
                uhfb:1,
                otrb:1;
            u8 f27;
            u8 tzone;
            u8 f29a:6,
               fvsvol:2;
            u8 f2au:4,              // 17f2a
               tot:4;
            u8 f2b;
            u8 f2c;
            u8 f2d:6,
               dspmode:2;
            u8 f2ea:6,
               fvsanc:2;
            u8 f2fa:6,              // 17f2f
               gpsdtm:1,
               f2fb:1;
            u8 lastmnu;             // 17f30
            u8 f31;                 // 17f31
            u8 f1key;               // 17f32
            u8 f33;
            u8 f34;
            u8 f35a:4,
               gpslog:4;
            u8 f36a:6,
               voxsen:2;            // FTM-200
            u8 f37a:5,
               voxdly:3;
            u8 f38a:6,              // 17f38
               audrec:2;
            u8 lastfunc;            // 17f39
            u8 f3a:6,               // 17f3a
               lcd_clr:2;
            u8 f3bxf[5];            // 17f3b-3f
            u8 f40x2[3];            // 7f40-42
            u8 a_chan;              // FTM-200 17f43
            u8 f44;
            u8 f45u:5,              // 17f45
               scnrsm:3;
            u8 f46;
            u8 f47;
            u8 f48u:4,              // 17f48
                sql:4;
            u8 f49:4,
                scnrsm2a:4;         // FTM-200 A
            u8 f4a;                 // 17f4a
            u8 f4ba:4,
               scndria:4;
            u8 f4c;
            u8 f4d;
            u8 f4e;
            u8 f4f;
            u8 f50x2[3];            // 17f50-52
            u8 b_chan;              // FTM-200 17f53
            u8 f54;
            u8 f55;
            u8 f56;
            u8 f57;
            u8 f58;
            u8 f59:4,
               scnrsm2b:4;         // FTM-200 B
            u8 f5a;                // 17f5a
            u8 f5ba:4,
               scndrib:4;
            u8 f5c;
            u8 f5d;
            u8 f5e;
            u8 f5f;
            u8 f60;                 // 17f60
            u8 f61;
            u8 scndrm1:1,           // 17f62
               wxalrt:1,
               f62b:5,
               dwrvt:1;
            u8 f63a:7,              // 17f63
               sqlexp1:1;
            u8 f64a:5,              // 17f64
               rpt_ars:1,
               f64b:2;
            u8 f65a:2,
               bscope:1,
               f65b:5;
            u8 f66;
            u8 f67;
            u8 f68a:3,
               wrxstb:1,
               f68b:1,
               locinfo:1,
               wrxdvw:1,
               f68c:1;
            u8 f69;
            u8 f6aa:4,
               audmic:1,
               f6ab:2,
               btsave:1;
            u8 wrxloc:1,            // 17f6b
               fvslan:1,
               f6bb:2,
               beep1:1,            // Stupid split beep: this is Off/Low
               fvsrxm:1,
               f6bc:2;
            u8 gpsdev:1,            // 17f6c
               memlist:1,
               wrxrng:1,
               wrxrwf:1,
               wrxsrch:1,
               f6cb:2,
               scndrm2:1;
            u8 bskpax:3,           // 17f6d
               bskpa0:1,
               bskpa4:1,
               bskpa3:1,
               bskpa2:1,
               bskpa1:1;
            u8 f6e;
            u8 f6f;
            u8 f70;                // 17f70
            u8 f71;
            u8 f72a:7,
               dwrvtb:1;
            u8 f73a:7,
               sqlexp2:1;
            u8 f74a:5,
               rpt_arsb:1,
               f74b:2;
            u8 f75a:2,
                bscopeb:1,
                f75b:5;
            u8 f76;
            u8 f77;
            u8 f78a:5,              // 17f78
               dtmf_auto:1,
               bton:1,
               btaud:1;
            u8 f79a:3,              // 17f79
               timefmt:1,
               datefmt:4;
            u8 f7aa:3,
               beep2:1,             // Split beep: High
               f7ab:3,
               fvsrec:1;
            u8 f7ba:6,
               wrxams:2;
            u8 f7c;
            u8 bskpbx:3,           // 17f7d
               bskpb0:1,
               bskpb4:1,
               bskpb3:1,
               bskpb2:1,
               bskpb1:1;
            u8 f7e;
            u8 f7f;
            u8 f80[16];             // 17f80
            u8 f90[16];             // 17f90
            u8 fA0[16];             // 17fA0
            u8 fB0[16];             // 17fB0
            u8 FC0[16];             // 17fC0
            u8 FD0[16];             // 17fD0
            u8 FE0[16];             // 17fE0
            u8 FF0[16];             // 17fF0
        } setts;
    """

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.info = (
            "The duplex setting 'split' allows for non-standard offsets "
            "by configuring both a\n"
            "receive and transmit frequency. Set the receive frequency, "
            "then the duplex mode,\n"
            "then the desired transmit frequency as the offset.\n"
            "The offset value of a split channel is the transmit frequency, "
            "and can be modified.\n"
            "PMS (Programmable Memory Channel Scan) pairs are displayed "
            "as memory channels 1000-1099.\n"
            "The Clock Shift Function can be set in the Properties "
            "> Extra tab.\n"
            "The radio special tone modes (REV, PR, PAGER) can also be set "
            "in the Properties > Extra tab,\n"
            "but will be displayed as Tone in CHIRP.")
        if cls.FTM200:
            rp.pre_download = (
                "(OK then TX)\n"
                "With the USB cable connected to the radio rear data port, "
                "and the radio powered off-\n"
                "1. Long-Press F-Menu.\n"
                "2. Rotate the dial knob to menu 116: 'This -> Other'.\n"
                "3. Press the dial knob.\n"
                "4. Rotate to select OK, but don't press yet.\n"
                "5. Press the OK button below.\n"
                "6. Press the dial knob to begin sending data.\n"
                "7. Wait for Complete.\n")
            rp.pre_upload = (
                "(Rx then OK)\n"
                "With the USB cable connected to the radio rear data port, "
                "and the radio powered off-\n"
                "1. Long-Press F-Menu.\n"
                "2. Rotate the dial knob to menu 117: 'Other -> This'.\n"
                "3. Press the dial knob.\n"
                "4. Rotate to select OK, and press the knob.\n"
                "5. Press the OK button below.\n"
                "6. Wait for Complete.\n")
        else:
            rp.pre_download = (
                "(OK then TX)\n"
                "With the USB cable connected to the radio rear data port, "
                "and the radio powered off-\n"
                "1. Press both the power ON and F1 keys.\n"
                "2. Press the dial knob.\n"
                "3. Rotate the dial to show CLN TX.\n"
                "4. Press the OK button below/\n"
                "5. Press the dial knob to begin sending data.\n"
                "6. Wait for Complete.\n"
                "7. Long-press the power On button to leave the clone mode.")
            rp.pre_upload = (
                "(Rx then OK)\n"
                "With the USB cable connected to the radio rear data port, "
                "and the radio powered off-\n"
                "1. Press both the power ON and F1 keys.\n"
                "2. Press the dial knob, CLN RX is displayed.\n"
                "3. Press the dial knob again to put the radio in the "
                "receiving state.\n"
                "4. Press the OK button below.\n"
                "5. Wait for Complete.\n"
                "6. Long-press the power On button to leave the clone mode.")
        return rp

    def _read(self, blck, blsz):
        # be very patient at first block
        if blck == 0:
            attempts = 60
        else:
            attempts = 5
        for _i in range(0, attempts):
            data = self.pipe.read(blsz)
            if data:
                break
            time.sleep(0.5)
        if len(data) == blsz:
            LOG.debug("Received block %s, sub %s" % (hex(data[0]),
                      hex(data[1])))
            checksum = data[blsz - 1]
            cs = 0
            for i in data[:-1]:
                cs = (cs + i) % 256
            if cs != checksum:
                raise Exception("Checksum Failed [%02X<>%02X] block %02X" %
                                (checksum, cs, blck))
            # Remove the 2-byte block header and checksum
            data = data[2:blsz - 1]
        else:
            raise Exception("Unable to read block %i expected %i got %i"
                            % (blck, blsz, len(data)))
        return data

    def _clone_in(self):
        # Be very patient with the radio
        self.pipe.timeout = 2
        self.pipe.baudrate = self.BAUD_RATE
        self.pipe.bytesize = self.COM_BITS
        self.pipe.parity = self.COM_PRTY
        self.pipe.stopbits = self.COM_STOP
        self.pipe.rtscts = False
        data = b""
        status = chirp_common.Status()
        status.msg = "Cloning from radio"
        nblocks = 768
        status.max = nblocks - 1
        blksz = 131
        for block in range(0, nblocks):     # SPS - reads to nblocks-1
            LOG.debug("Reading packet %d" % block)
            data += self._read(block, blksz)
            self.pipe.write(CMD_ACK)
            status.cur = block
            self.status_fn(status)
        return memmap.MemoryMapBytes(data)

    def _write(self, nblk, nsub, pntr, bksz, zblk):
        LOG.debug("Block %02X %02X" % (nblk, nsub))
        if self.TESTME:
            LOG.warning("Block %02X %02X" % (nblk, nsub))
        data = struct.pack('B', nblk)
        data += struct.pack('B', nsub)
        if zblk:
            blkdat = bytearray(bksz)    # All Zeros
        else:
            blkdat = self.get_mmap()[pntr:pntr + bksz]
        data += blkdat
        cs = 0
        for i in data:
            cs = (cs + i) % 256
        LOG.debug("Checksum %s" % hex(cs))
        if self.TESTME:
            LOG.warning("Checksum %s" % hex(cs))
        data += struct.pack('B', cs)
        LOG.debug("Writing %d bytes:\n%s" % (len(data),
                                             util.hexprint(data)))
        if self.TESTME:      # Dont send data yet
            LOG.warning("Writing %d bytes:\n%s" % (len(data),
                                                   util.hexprint(data)))
            buf = CMD_ACK
        else:
            self.pipe.write(data)
            buf = self.pipe.read(1)
        if not buf or buf[:1] != CMD_ACK:
            time.sleep(0.5)
            buf = self.pipe.read(1)
        if not buf or buf[:1] != CMD_ACK:
            return False
        return True

    def _clone_out(self):
        self.pipe.baudrate = self.BAUD_RATE
        self.pipe.bytesize = self.COM_BITS
        self.pipe.parity = self.COM_PRTY
        self.pipe.stopbits = self.COM_STOP
        self.pipe.rtscts = False

        status = chirp_common.Status()
        status.msg = "Cloning to radio"
        blksz = 128     # actual data; excluding block, sub, checksum
        pkt = 0
        pos = 0
        block = 0
        wrtzero = False        # Special last block flag
        nblocks = 767          # last block number
        status.max = nblocks - 2
        # This sucker took FOREVER to figure out the repeating block
        # + sub-block + special EoD numbering!
        while pkt <= nblocks:
            LOG.debug("Writing packet #: %d." % pkt)
            if self.TESTME:
                LOG.warning("Writing packet #: %d , pos %x." % (pkt, pos))
            time.sleep(0.01)
            sub2 = True
            sublk = 0
            if pkt == 0:
                block = pkt
                sub2 = False
            elif pkt == 1:
                block = pkt
            elif pkt == 7:          # Block 04 00 is skipped !!??
                block = 0x04
                sublk = 0x80
                sub2 = False        # block increments to 05 00
            elif pkt == 510:        # Reset to block 0
                block = 0
            elif pkt == 766:
                block = 0xff
                sublk = 0xfd
                sub2 = False
            elif pkt == 767:
                block = 0xff
                sublk = 0xfe
                sub2 = False
                # pkt 767, block ff fe must be all zeros!!???
                wrtzero = True
            rslt = self._write(block, sublk, pos, blksz, wrtzero)
            if rslt and sub2:       # write same block, new sublk
                sublk = 0x80
                pkt += 1
                pos += blksz
                LOG.debug("Writing packet #: %.d" % pkt)
                if self.TESTME:
                    LOG.warning("Writing packet #: %d , pos %x." % (pkt, pos))
                rslt = self._write(block, sublk, pos, blksz, wrtzero)
            if not rslt:
                raise Exception("Radio did not ack block %i %i" %
                                (block, sublk))
            pos += blksz
            block += 1
            pkt += 1
            status.cur = pkt
            self.status_fn(status)
        return

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
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = True
        rf.has_ctone = False                    # Common Tones
        rf.has_rx_dtcs = False                  # Common codes
        rf.has_settings = True
        rf.can_odd_split = True
        rf.valid_modes = [x for x in self.MODES if x in chirp_common.MODES]
        rf.valid_tmodes = self.TMODES
        rf.valid_cross_modes = self.CROSS_MODES
        rf.valid_duplexes = self.DUPLEX
        rf.valid_tuning_steps = self.T_STEPS
        rf.valid_bands = self.VALID_BANDS
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = "".join(self.CHARSET)
        rf.valid_name_length = self.NAME_LEN
        rf.memory_bounds = (1, 1099)
        rf.valid_skips = self.SKIPS
        return rf

    def get_raw_memory(self, number):
        return repr(self._memobj.main[number - 1])

    def validate_memory(self, mem):
        msgs = yaesu_clone.YaesuCloneModeRadio.validate_memory(self, mem)
        return msgs

    def filter_name(self, namsx):
        """Name must be <= NAME_LEN and contain only CHARSET chars"""
        tx = namsx.strip()
        sx = ""
        if self.FTM200 is False:
            tx = tx.upper()
        for i in range(0, len(tx)):
            if i >= self.NAME_LEN:
                break
            if tx[i] in self.CHARSET:
                sx += tx[i]
            else:
                sx = "?"
        return sx

    def _freqdcode(self, frqb):
        """Decode .0025 Mhz upper 2 MSB of freq"""
        # frqb is u24: 2bits suffix, 22 bits bcd
        sx = "%06X" % frqb
        v0 = int(sx[0], 16) * 625
        v1 = int(sx[1])     # 100 Mhz
        v2 = int(sx[2:4])   # 10 Mhz
        v3 = int(sx[4:])    # 100 Khz
        vx = (v1 * 10000) + (v2 * 100) + v3
        vx = vx * 10000 + v0
        return vx

    def _freqncode(self, frq):
        """Encode .0625 Mhz in upper MSB of u24 bcd freq"""
        v0 = frq % 10000    # .025 value
        bx = v0 // 625
        bx = bx * 0x100000
        vx = int((frq - v0) / 10000)
        sx = "%06d" % vx    # Ex: 012345 for frq = 123.45 MHz
        v1 = int("0x" + sx[0:2], 16)
        v2 = int("0x" + sx[2:4], 16)
        v3 = int("0x" + sx[4:], 16)
        frqb = bx + v1 * 0x10000 + v2 * 0x100 + v3
        return frqb

    def _b2s(self, bary, term=0xff):
        """Convert byte array into string """
        strx = ""
        for i in bary:
            if i == term:
                break
            strx += chr(i)
        return strx

    def _s2b(self, setting, obj, atrb, mxk, pad=0xff, upc=True):
        """Callback: Convert string to byte array, pad to mxk chars"""
        sx = str(setting.value)
        sx = sx.strip()
        if upc:
            sx = sx.upper()
        ary = b""
        v1 = len(sx)
        for vx in range(0, mxk):
            if vx < v1:
                ary += bytes(sx[vx], 'utf-8')
            else:
                ary += pad.to_bytes(1, sys.byteorder)
        setattr(obj, atrb, ary)
        return

    def _c2u8(self, setting, obj, atrb):
        """Callback: Convert single char string to u8"""
        b0 = str(setting.value)
        vx = ord(b0)
        setattr(obj, atrb, vx)
        return

    def get_memory(self, number):
        mem = chirp_common.Memory()
        if number < 1000:      # channel memory
            _mem = self._memobj.main[number - 1]
            _tag = self._memobj.names[number - 1]
        else:
            _mem = self._memobj.pms[number - 1000]
            _tag = self._memobj.pms_name[number - 1000]
        mem.number = number
        if mem.number == 1:
            mem.immutable += ["empty"]
        if not _mem.used:
            mem.empty = True
            return mem
        mem.freq = self._freqdcode(_mem.freq)
        mem.rtone = chirp_common.TONES[_mem.rtone]
        mem.mode = self.MODES[_mem.mode]
        mem.duplex = self.DUPLEX[_mem.duplex]
        if (_mem.duplex == 4):          # Split mode
            mem.offset = self._freqdcode(_mem.frqtx)
        else:
            mem.offset = int(_mem.offset) * 50000
        # Re-map funky radio tone and cross-modes
        tmd = _mem.tmode   # 0,1,2
        cmx = 0
        if _mem.tmode == 3:     # DCS
            tmd = 5             # Cross
            cmx = 0             # -> DTCS
        if _mem.tmode == 4:     # Rev Tone
            tmd = 3             # TSQL-R
        if _mem.tmode == 5:     # PR Freq
            tmd = 1
        if _mem.tmode == 6:     # Pager
            tmd = 1
        if _mem.tmode == 7:     # Tx DTCS, Open RX
            tmd = 4             # DTCS
        elif _mem.tmode == 8:   # Tone - DCS
            tmd = 5             # Cross
            cmx = 1             # Tone -> DTCS
        elif _mem.tmode == 9:   # D CD-> Tone
            tmd = 5             # Cross
            cmx = 2             # DTCS->Tone
        mem.tmode = self.TMODES[tmd]
        mem.cross_mode = self.CROSS_MODES[cmx]
        mem.skip = self.SKIPS[_mem.skip]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        vx = _mem.power
        mem.power = self.POWER_LEVELS[vx]
        mem.tuning_step = self.T_STEPS[_mem.step]
        tx = self._b2s(_tag.chname, 0xff).strip()
        if self.FTM200 is False:
            tx = tx.upper()
        mem.name = tx
        # Echo name string back into memory.
        # In case it got loaded flakey in radio; trailing spaces
        for i in range(0, self.NAME_LEN):
            if i < len(mem.name):
                _tag.chname[i] = ord(mem.name[i])
            else:
                _tag.chname[i] = 0xff
        # mem.extra: Clock Type A/B
        mem.extra = RadioSettingGroup("extra", "Extra")
        options = ["Auto", "On"]
        rx = RadioSettingValueList(options, options[_mem.clktyp])
        rs = RadioSetting("clktyp", "Clock Shift (CLK.TYP)", rx)
        mem.extra.append(rs)

        options = ["None", "REV Tone", "PR Freq", "Pager"]
        tmd = _mem.tmode - 3
        if _mem.tmode < 4:
            tmd = 0
        if _mem.tmode > 6:
            tmd = 0
        rx = RadioSettingValueList(options, options[tmd])
        rs = RadioSetting("spclmode", "Radio Special Tone Mode", rx)
        mem.extra.append(rs)

        options = []
        for vx in range(300, 3100, 100):
            sx = str(vx)
            options.append(sx)
        if _mem.prfreq > 30:
            _mem.prfreq = 30       # Can get loaded wrong...?
        if _mem.prfreq < 3:
            _mem.prfreq = 3
        v0 = _mem.prfreq * 100       # .prfreq is 0x03 - 0x1E (3 -30 decimal)
        sx = str(v0)
        rx = RadioSettingValueList(options, sx)
        rs = RadioSetting("prfreq", "PR (User) Freq Htz", rx)
        mem.extra.append(rs)
        return mem

    def set_memory(self, mem):
        if mem.number < 1000:
            _mem = self._memobj.main[mem.number - 1]
            _tag = self._memobj.names[mem.number - 1]
        else:
            _mem = self._memobj.pms[mem.number - 1000]
            _tag = self._memobj.pms_name[mem.number - 1000]
        if mem.empty:       # Chan 1 is immutable for empty
            _mem.used = 0
            return mem
        _mem.used = 1
        _mem.freq = self._freqncode(mem.freq)
        _mem.mode = self.MODES.index(mem.mode)
        _mem.duplex = self.DUPLEX.index(mem.duplex)
        if _mem.duplex == 4:         # split mode
            _mem.frqtx = self._freqncode(mem.offset)
        else:
            _mem.offset = mem.offset / 50000
        tmd = 0     # no tone
        sqlx = 0
        # Re-map Tmode and Cross mode to radio combined
        # Using MY TMODE list index
        tx = mem.tmode.strip()
        cmx = mem.cross_mode.strip()
        if tx == "Cross":
            if cmx == "->DTCS":
                tmd = 3
            if cmx == "Tone->DTCS":
                tmd = 8
            if cmx == "DTCS->Tone":
                tmd = 9
            sqlx = 1
        else:
            if tx == "Tone":
                tmd = 1
            if tx == "TSQL":
                tmd = 2
            if tx == "TSQL-R":
                tmd = 4
            if tx == "DTCS":
                tmd = 7
        _mem.tmode = tmd
        _mem.rtone = chirp_common.TONES.index(mem.rtone)
        _mem.step = self.T_STEPS.index(mem.tuning_step)
        _mem.skip = self.SKIPS.index(mem.skip)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        sx = mem.power
        if sx is None:
            sx = self.POWER_LEVELS[1]    # Mid
        _mem.power = self.POWER_LEVELS.index(sx)
        setattr(self._memobj.setts, "sqlexp1", sqlx)
        setattr(self._memobj.setts, "sqlexp2", sqlx)
        tx = self.filter_name(mem.name)
        for i in range(0, self.NAME_LEN):
            if i < len(tx):
                _tag.chname[i] = ord(tx[i])
            else:
                _tag.chname[i] = 0xff
        for setting in mem.extra:
            if setting.get_name() == "clktyp":
                sx = str(setting.value)
                vx = 0
                if sx == "On":
                    vx = 1
                setattr(_mem, "clktyp", vx)
            if setting.get_name() == "spclmode":
                sx = str(setting.value)
                tmd = 0
                tx = mem.tmode
                if sx == "None":
                    if tx == "PR Freq" or tx == "Pager":
                        tmd = 0      # Reset from special to none
                    else:
                        tmd = _mem.tmode    # no change
                        if sx == "PR Freq":
                            tmd = 5
                        if sx == "Pager":
                            tmd = 6
                setattr(_mem, "tmode",  tmd)
            if setting.get_name() == "prfreq":
                sx = str(setting.value)
                vx = int(sx) // 100
                setattr(_mem, "prfreq", vx)
        return

    def _micpkey(self, setting, obj, atrb, opts):
        """Callback: Adjust stored value for microphone P keys"""
        sx = str(setting.value)      # the list string
        v0 = opts.index(sx)     # the options array index, 0-based
        v1 = v0 + 0xdc
        if self.FTM200 is False:
            v1 = v0 + 0xdd
            if v1 == 0xe6:
                v1 = 0xe7        # skip e6
        setattr(obj, atrb, v1)
        return

    def _setfunc(self, setting, obj, atrb, ndx):
        """Callback: Convert boolean to function setting"""
        # Stored in shared memory 'share1' as 2 bytes.
        # When set: first byte is menu number, 2nd is 00
        # Unset: ff, ff
        bx = bool(setting.value)      # boolean
        # ndx is 0-based menu number
        x1 = ndx * 2    # _shr index of first byte
        v0 = 0xff       # disabled
        v1 = 0xff
        if bx:
            v0 = ndx
            v1 = 0
        setattr(obj[x1], atrb, v0)
        setattr(obj[x1 + 1], atrb, v1)
        return

    def _setQA(self, setting, obj, atrb, opts):
        """Callback: FTM-200 menu list selection to menu code"""
        sx = str(setting.value)
        v0 = opts.index(sx)
        setattr(obj, atrb, v0)
        return

    def _sqlexp1(self, setting, obj, atrb):
        """ Callback: SQL.EXP requires setting two objects """
        sx = str(setting.value)
        bx = False
        if sx == "On":
            bx = True
        setattr(obj, atrb, bx)      # sqlexp1
        setattr(obj, "sqlexp2", bx)
        return

    def _settot(self, setting, obj, atrb, opts):
        """Callback: convert non-linear TOT values"""
        sx = str(setting.value)
        v0 = opts.index(sx)
        v1 = v0
        if v0 > 0:
            v1 = v0 + 5
        if v0 > 3:
            v1 = v0 - 3
        setattr(obj, atrb, v1)
        return

    def _adjint(self, setting, obj, atrb):
        """Callback: decrement integer value to 0-based"""
        v0 = int(setting.value)
        v1 = v0 - 1
        setattr(obj, atrb, v1)
        return

    def _unpack_str(self, codestr):
        """Convert u8 DTMF array to a string: NOT a callback."""
        sx = ""
        for i in range(0, 16):    # unpack up to ff
            if codestr[i] != 0xff:
                if codestr[i] == 0x0E:
                    sx += "*"
                elif codestr[i] == 0x0F:
                    sx += "#"
                else:
                    sx += format(int(codestr[i]), '0X')
        return sx

    def _pack_chars(self, setting, obj, atrb, ndx):
        """Callback to build 0-9,A-D,*# nibble array from string"""
        # String will be ff padded to 16 bytes
        # Chars are stored as hex values
        ary = []
        sx = str(setting.value).upper().strip()
        sx = sx.strip()       # trim spaces
        # Remove illegal characters first
        sty = ""
        for j in range(0, len(sx)):
            if sx[j] in self.DTMF_CHARS:
                sty += sx[j]
        for j in range(0, 16):
            if j < len(sty):
                if sty[j] == "*":
                    chrv = 0xE
                elif sty[j] == "#":
                    chrv = 0xF
                else:
                    chrv = int(sty[j], 16)
            else:   # pad to 16 bytes
                chrv = 0xFF
            ary.append(chrv)    # append byte
        setattr(obj[ndx], atrb, ary)
        return

    def _pmgset(self, setting, obj, ndx):
        """Callback: Convert pmg chan to 0-based, and store """
        v0 = int(setting.value)
        if v0 == 0:     # Deleted
            setattr(obj[ndx], "za", 0xff)
            setattr(obj[ndx], "fb", 0xff)
            setattr(obj[ndx], "chnp", 0)
            return
        v1 = v0 - 1     # 0-based
        setattr(obj[ndx], "za", 0)
        setattr(obj[ndx], "fb", 0xff)
        setattr(obj[ndx], "chnp", v1)
        return

    def _adjlist(self, setting, obj, atrb, opts, ofst):
        """Callback: Universal add/subtract list index"""
        sx = str(setting.value)      # the list string
        vx = opts.index(sx) + ofst
        if atrb == "tzone":             # special case for time zone
            if vx < 0:
                vx = abs(vx) + 0x80
        setattr(obj, atrb, vx)
        return

    def _ft2apo(self, setting, obj):
        """Callback: Set FTM-200 APO coded decimal in 2 bytes"""
        sx = str(setting.value)     # Ex '1.5 Hours'
        if sx == "Off":
            setattr(obj, "apo", 0)
            setattr(obj, "apo1", 0)
            return
        if "." in sx:
            vx = sx.index(".")
            v1 = int("0x" + sx[:vx], 16)  # encode as hcd
            v2 = 1
        else:
            vx = sx.index(" H")
            v1 = int(sx[:vx])
            v2 = 0
        setattr(obj, "apo", v1)
        setattr(obj, "apo1", v2)
        return

    def _ft2lcd(self, setting, obj, atrb):
        """Callback: to set LCD Display Brightness"""
        sx = str(setting.value)
        v0 = 3
        if sx == "Mid":
            v0 = 1
        if sx == "Full":
            v0 = 2
        setattr(obj, atrb, v0)
        return

    def _scndrm(self, setting, obj):
        """Callback:FTM-200 Scan Dual Rcv Mode """
        # Requires setting a bit in 2 bytes
        sx = str(setting.value)
        v0 = 0
        v1 = 0
        if "Pri" in sx:
            v0 = 1
        if "A-B" in sx:
            v1 = 1
        setattr(obj, "scndrm1", v0)
        setattr(obj, "scndrm2", v1)
        return

    def _skp_other(self, setting, obj, bnd, opts):
        """Callback: FTM-200 Band Skip Other requires 2 bits"""
        sx = str(setting.value)     # Off/On
        v0 = 0
        if "On" in sx:
            v0 = 1
        b0 = "bskpa0"
        b3 = "bskpa3"
        if "B" in bnd:
            b0 = "bskpb0"
            b3 = "bskpb3"
        setattr(obj, b0, v0)
        setattr(obj, b3, v0)
        return

    def _beepset(self, setting, obj, optns):
        """Callback: Stupid split-beep"""
        sx = str(setting.value)
        vx = optns.index(sx)    # 0,1,2
        v0 = vx & 1       # Off/Low
        v1 = 0            # High
        if vx == 2:
            v0 = 1
            v1 = 1
        setattr(obj, "beep1", v0)
        setattr(obj, "beep2", v1)
        return

    def _xmsg(self, setting, obj, indx, xmp, mode=0):
        """Callback: Wires-X message # indx, text encoder """
        # mode=0 is GM Message, mode=1 is Category
        sx = str(setting.value).strip()
        tx = b""
        v0 = 128
        v1 = 0xff
        hx = "msg%02d" % indx
        if mode == 1:
            v0 = 16
            v1 = 0xca
            hx = "c%d" % indx
        for cx in range(0, v0):
            if cx < len(sx):
                vx = sx[cx]
                try:
                    v2 = xmp.index(vx)
                except Exception:
                    raise Exception("Unable to decode character hex %x at "
                                    "index %d of %s" % (vx, cx, hx))
                tx += util.int_to_byte(v2)
            else:
                tx += util.int_to_byte(v1)    # pad
        setattr(obj, hx, tx)
        return

    def _wrxfrq(self, setting, obj, atrb):
        """Callback: Encode the 3-byte non-mem channel frequency"""
        vx = float(setting.value) * 1000000
        bx = self._freqncode(vx)
        setattr(obj, atrb, bx)
        return

    def _aprsfx(self, setting, obj, atrb, pad):
        """Callback: Trap the APRS callsign SSID"""
        v0 = int(setting.value)
        vx = v0
        if (pad == 0xca) and (v0 == 0):
            vx = pad
        if (pad == 0x2a) and (v0 == 16):
            vx = pad
        setattr(obj, atrb, vx)
        return

    def _aprspop(self, setting, obj, atrb):
        """Callback: APRS Beacon and Message Popup times; not 1:1"""
        # Can these radiso get any wierder?
        vx = int(setting.value)
        v0 = 0          # Off
        if vx == 1:
            v0 = 3
        if vx == 2:
            v0 = 5
        if vx == 3:
            v0 = 10
        if vx == 4:
            v0 = 0xff   # Hold
        setattr(obj, atrb, v0)
        return

    def _enchcd(self, setting, obj, atrb):
        """Callback: Generic convert 1-byte decimal value to hex-coded"""
        sx = str(setting.value)    # Decimal value, Ex: "33"
        v0 = int("0x" + sx, 16)    # encode as hcd 0x33
        setattr(obj, atrb, v0)
        return

    def _mdot(self, setting, obj, atrb1, atrb2):
        """Callback: Convert lat/long mm/mm to  u8 and u16"""
        # Half as hex coded decimal, half as binary !!??
        vx = float(setting.value)   # mm.mm
        tx = math.modf(vx)
        sx = str(int(tx[1]))
        v0 = int("0x" + sx, 16)     # hcd
        v1 = int(tx[0] * 1000)      # 2-byte binary
        setattr(obj, atrb1, v0)
        setattr(obj, atrb2, v1)
        return

    def _getdgpath(self, pn):
        """Method for extracting Digipeater route paths"""
        # pn is path number 0 - 5
        _shr = self._memobj.share1
        sx = ""
        x1 = pn * 8
        for i in range(x1, x1 + 6):   # route name: 6 bytes
            v0 = _shr[i].shbyt
            if v0 != 0xca:
                sx += chr(v0)
        vx = _shr[x1 + 6].shbyt     # route suffix 0-15
        if vx == 0xca:
            vx = 0
        return sx, vx

    def _putdgpname(self, setting, pn):
        """Callback: store Digipath name"""
        # Stored in 'share1' shared memory
        # pn is path number 0-5
        _shr = self._memobj.share1
        sx = str(setting.value)     # modified path name; 0-6 chars
        sx = sx.upper().strip()
        x1 = pn * 8                 # starting position in _shr
        sp = 0
        for i in range(x1, x1 + 6):
            if sp >= len(sx):
                v1 = 0xca
            else:
                v1 = ord(sx[sp])
            setattr(_shr[i], "shbyt", v1)
            sp += 1
        return

    def _putdgpsfx(self, setting, pn):
        """Callback: Digipath, Ringer SSID"""
        _shr = self._memobj.share1
        v1 = int(setting.value)
        x1 = pn * 8 + 6
        setattr(_shr[x1], "shbyt", v1)
        return

    def _rnglmt(self, setting, obj, atrb):
        """Callback: APRS Beacon Range Limits"""
        v1 = int(setting.value)      # index
        vx = v1         # for 0, 1
        if atrb == "aprbrrr":     # Range Ringer
            if v1 == 2:
                vx = 5
            if v1 == 3:
                vx = 10
            if v1 == 4:
                vx = 50
            if v1 == 5:
                vx = 100
        else:                     # Filter Range
            if v1 == 2:
                vx = 10
            if v1 == 3:
                vx = 100
            if v1 == 4:
                vx = 1000
            if v1 == 5:
                vx = 3000
        setattr(obj, atrb, vx)
        return

    def _datefmt(self, setting, obj, atrb):
        """Callback: Stupid index jump in date format list"""
        vx = int(setting.value)
        if vx == 3:
            vx = 4
        setattr(obj, atrb, vx)
        return

    def get_settings(self):
        _setx = self._memobj.setts
        _mic = self._memobj.micset
        _wierd = self._memobj.wierd
        _dtm = self._memobj.dtmfcode

        cfg = RadioSettingGroup("cfg", "Config")
        dsp = RadioSettingGroup("dsp", "Display")
        fmenu = RadioSettingGroup("fmnu", "Quick Functions")
        mic = RadioSettingGroup("mic", "Microphone")
        sig = RadioSettingGroup("sig", "Signalling")
        opts = RadioSettingGroup("opts", "Options")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        scan = RadioSettingGroup("scan", "Scanning")
        other = RadioSettingGroup("other", "Other")

        if self.FTM200:
            dat = RadioSettingGroup("dat", "Data")
            wires = RadioSettingGroup("wires", "GM/WIRES-X")
            aprscom = RadioSettingGroup("aprscom", "APRS Settings")
            aprsdgp = RadioSettingGroup("aprsdgp", "APRS Digipeater")
            aprsmsg = RadioSettingGroup("aprsmsg", "APRS Messages")
            bcnfltr = RadioSettingGroup("bcnfltr", "APRS Beacon Filter")
            bcnunit = RadioSettingGroup("bcnunit", "APRS Beacon Units")
            bcnrngr = RadioSettingGroup("bcnrngr", "APRS Beacon Ringer")
            bcnstat = RadioSettingGroup("bcnstat", "APRS Beacon Status")
            bcnsmrt = RadioSettingGroup("bcnsmrt", "APRS Smart Beaconing")
            group = RadioSettings(cfg, dsp, fmenu, mic, sig, opts, dtmf,
                                  scan, dat, wires, aprscom, aprsmsg,
                                  aprsdgp, bcnfltr, bcnunit, bcnrngr,
                                  bcnstat, bcnsmrt, other)
        else:
            group = RadioSettings(cfg, dsp, fmenu, mic, sig, opts, dtmf,
                                  scan, other)

        menu_items = ["01: Auto Power Off (APO)", "02: ARTS Mode",
                      "03: ARTS Interval", "04: Busy Channel Lockout (BCLO)",
                      "05: Beep", "06: Bell", "07: Clock Type",
                      "08: LCD Dimmer", "09: DTMF Manual/Auto",
                      "10: DTMF TX", "11:DTMF Codes", "12: Home",
                      "13: Microphone Gain", "14: Microphone P Keys",
                      "15: Pager TX/RX", "16: Packet Speed", "17:RX Mode",
                      "18: Band Select", "19: Repeater Reverse",
                      "20: Repeater Set", "21: Repeater Other", "22: Scan On",
                      "23: Scan Type", "24: Squelch Type", "25:Squelch Code",
                      "26: Squelch Expansion", "27: Step",
                      "28: Radio Temperature", "29: Time Out Timer (TOT)",
                      "30: TX Power", "31: Version", "32: Voltage",
                      "33: Width", "34: Weather Alert", "35: Bluetooth"]
        offon = ["Off", "On"]
        onoff = ["On", "Off"]     # Inverted logic

        # Begin Config settings
        if self.FTM200:
            sx = self._b2s(_mic.csign, 0xff)
            rx = RadioSettingValueString(0, 10, sx, False)
            rs = RadioSetting("micset.csign", "Call Sign Label", rx)
            rs.set_apply_callback(self._s2b, _mic, "csign", 10)
            cfg.append(rs)

            options = ["yyyy/mmm/dd", "yyyy/dd/mmm", "mmm/dd/yyyy",
                       "dd/mmm/yyyy"]
            vx = _setx.datefmt
            if vx == 4:
                vx = 3      # Just to make my life difficult!
            rx = RadioSettingValueList(options, options[vx])
            rs = RadioSetting("setts.datefmt", "Date Format", rx)
            rs.set_apply_callback(self._datefmt, _setx, "datefmt")
            cfg.append(rs)

            options = ["24 Hour", "12 Hour"]
            rx = RadioSettingValueList(options, options[_setx.timefmt])
            rs = RadioSetting("setts.timefmt", "Time Format", rx)
            cfg.append(rs)

            options = []
            v0 = -14.0
            for vx in range(0, 57):
                options.append(str(v0))
                v0 += 0.5
            v0 = _setx.tzone
            v1 = v0 + 28       # positive offset; index 28 is GMT
            if v0 & 0x80:      # negative, before GMT
                v1 = 28 - (v0 & 0x1f)
            rx = RadioSettingValueList(options, options[v1])
            rs = RadioSetting("setts.tzone", "Time Zone GMT +/- hours", rx)
            rs.set_apply_callback(self._adjlist, _setx, "tzone", options, -28)
            cfg.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.rpt_ars])
            rs = RadioSetting("setts.rpt_ars",
                              "A: Repeater Auto Offset Enabled", rx)
            cfg.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.rpt_arsb])
            rs = RadioSetting("setts.rpt_arsb",
                              "B: Repeater Auto Offset Enabled", rx)
            cfg.append(rs)

            options = ["Off", "0.5 Hours", "1 Hours", "1.5 Hours", "2 Hours",
                       "3 Hours", "4 Hours", "5 Hours", "6 Hours", "7 Hours",
                       "8 Hours", "9 Hours", "10 Hours", "11 Hours",
                       "12 Hours"]
            v0 = _setx.apo      # Hours BCD
            v1 = _setx.apo1     # 0.5 hours yes/no
            sx = "%d" % v0
            if v1:
                sx += ".5"
            if sx == "0":
                sx = "Off"
            else:
                sx += " Hours"
            rx = RadioSettingValueList(options, sx.strip())
            rs = RadioSetting("setts.apo", "Auto Power Off time (APO)", rx)
            rs.set_apply_callback(self._ft2apo, _setx)
            cfg.append(rs)

        else:       # FTM-6000, different than 200
            rx = RadioSettingValueList(menu_items, menu_items[_setx.f1key])
            rs = RadioSetting("setts.f1key", "F1 Key Assignment", rx)
            cfg.append(rs)

            options = ["Off", "1 Hours", "1.5 Hours", "2 Hours", "3 Hours",
                       "4 Hours", "5 Hours", "6 Hours", "7 Hours", "8 Hours",
                       "9 Hours", "10 Hours", "11 Hours", "12 Hours"]
            rx = RadioSettingValueList(options, options[_setx.apo])
            rs = RadioSetting("setts.apo", "Auto Power Off time (APO)", rx)
            cfg.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.rpt_ars])
            rs = RadioSetting("setts.rpt_ars", "Repeater Auto Offset Enabled",
                              rx)
            cfg.append(rs)

        # Config - Common to all radios

        options = ["Off", "Low", "High"]
        # Yaesu splits the beep!!!
        vx = _setx.beep1        # Off/Low
        if _setx.beep2:
            vx = 2  # High
        rx = RadioSettingValueList(options, options[vx])
        rs = RadioSetting("setts.beep1", "Beep", rx)
        rs.set_apply_callback(self._beepset, _setx, options)
        cfg.append(rs)

        options = ["Off", "1 minute", "2 minutes", "3 minutes", "5 minutes",
                   "10 minutes", "15 minutes", "20 minutes", "30 minutes"]
        vx = _setx.tot      # non-sequential index
        if vx >= 6:
            bx = vx - 5
        if vx >= 1:
            bx = vx + 3
        if vx == 0:
            bx = 0
        rx = RadioSettingValueList(options, options[bx])
        rs = RadioSetting("setts.tot", "Transmit Time Out Timer (TOT)", rx)
        rs.set_apply_callback(self._settot, _setx, "tot", options)
        cfg.append(rs)

        if self.FTM200:     # Stuff at the end of Config
            options = ["Metric", "Imperial (Inch)"]
            rx = RadioSettingValueList(options, options[_setx.unit])
            rs = RadioSetting("setts.unit", "Units", rx)
            cfg.append(rs)

            options = ["WGS 84", "Tokyo Mean"]
            rx = RadioSettingValueList(options, options[_setx.gpsdtm])
            rs = RadioSetting("setts.gpsdtm", "GPS Datum", rx)
            cfg.append(rs)

            options = ["Internal", "External"]
            rx = RadioSettingValueList(options, options[_setx.gpsdev])
            rs = RadioSetting("setts.gpsdev", "GPS Device", rx)
            cfg.append(rs)

            options = ["Off", "1 second", "2 sec", "5 sec", "10 sec",
                       "30 sec", "60 sec"]
            rx = RadioSettingValueList(options, options[_setx.gpslog])
            rs = RadioSetting("setts.gpslog", "GPS Log Interval", rx)
            cfg.append(rs)

        else:
            options = ["30 Seconds", "1 Minute"]
            rx = RadioSettingValueList(options, options[_setx.arts_int])
            rs = RadioSetting("setts.arts_int", "ARTS Interval", rx)
            cfg.append(rs)

            options = ["Off", "In Range", "Out Range"]
            rx = RadioSettingValueList(options, options[_setx.arts_mode])
            rs = RadioSetting("setts.arts_mode", "ARTS Mode", rx)
            cfg.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.bclo])
            rs = RadioSetting("setts.bclo", "Busy Channel Lockout (BCLO)",
                              rx)
            cfg.append(rs)

        # End of Config settings

        # Start of Display settings
        if self.FTM200:
            options = ["Backtrack", "Altitude", "Timer/Clock", "GPS Info"]
            rx = RadioSettingValueList(options, options[_setx.dspmode])
            rs = RadioSetting("setts.dspmode", "Display Select", rx)
            dsp.append(rs)

            options = ["Compass", "Numeric Lat/Long"]
            rx = RadioSettingValueList(options, options[_setx.locinfo])
            rs = RadioSetting("setts.locinfo", "Location Info", rx)
            dsp.append(rs)

            options = ["North Up", "Heading Up"]
            rx = RadioSettingValueList(options, options[_mic.compass])
            rs = RadioSetting("micset.compass", "Compass Display", rx)
            dsp.append(rs)

            options = ["Wide", "Narrow"]
            rx = RadioSettingValueList(options, options[_setx.bscope])
            rs = RadioSetting("setts.bscope", "A: Display Scope", rx)
            dsp.append(rs)
            rx = RadioSettingValueList(options, options[_setx.bscopeb])
            rs = RadioSetting("setts.bscopeb", "B: Display Scope", rx)
            dsp.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.memlist])
            rs = RadioSetting("setts.memlist", "Memory List Mode", rx)
            dsp.append(rs)

            options = ["Dim", "Mid", "Full"]
            vx = _mic.lcd       # stupid indexing: 3,1,2
            v0 = vx      # Mid: vx = 1, Max: vx = 2
            if vx == 3:
                v0 = 0
            rx = RadioSettingValueList(options, options[v0])
            rs = RadioSetting("micset.lcd", "Display Brightness", rx)
            rs.set_apply_callback(self._ft2lcd, _mic, "lcd")
            dsp.append(rs)

            options = ["White", "Blue", "Red"]
            rx = RadioSettingValueList(options, options[_setx.lcd_clr])
            rs = RadioSetting("setts.lcd_clr", "LCD Upper Band Color", rx)
            dsp.append(rs)

        else:       # FTM-6000
            options = ["Dim", "Mid", "Full"]
            rx = RadioSettingValueList(options, options[_mic.lcd])
            rs = RadioSetting("micset.lcd", "Display Brightness", rx)
            dsp.append(rs)

        # End of Display settings

        # Start of Signalling settings
        options = ["Off", "1 Time", "3 Times", "5 Times", "8 Times",
                   "Continous"]
        if self.FTM200:
            rx = RadioSettingValueList(options, options[_mic.bell])
            rs = RadioSetting("micset.bell",
                              "A: Remote Station Calling Bell", rx)
            sig.append(rs)
            rx = RadioSettingValueList(options, options[_mic.bellb])
            rs = RadioSetting("micset.bellb",
                              "B: Remote Station Calling Bell", rx)
            sig.append(rs)
        else:
            rx = RadioSettingValueList(options, options[_mic.bell])
            rs = RadioSetting("micset.bell", "Remote Station Calling Bell",
                              rx)
            sig.append(rs)

        # All radios, Signalling opetions
        vx = _mic.pgrcdr1 + 1
        rx = RadioSettingValueInteger(1, 50, vx)
        rs = RadioSetting("micset.pcrcdr1", "Pager Receive First Code", rx)
        rs.set_apply_callback(self._adjint, _mic, "pgrcdr1")
        sig.append(rs)

        vx = _mic.pgrcdr2 + 1
        rx = RadioSettingValueInteger(1, 50, vx)
        rs = RadioSetting("micset.pcrcdr2", "Pager Receive Second Code", rx)
        rs.set_apply_callback(self._adjint, _mic, "pgrcdr2")
        sig.append(rs)

        rx = RadioSettingValueInteger(1, 50, vx)
        rs = RadioSetting("micset.pgrcdt1", "Pager Transmit First Code", rx)
        rs.set_apply_callback(self._adjint, _mic, "pgrcdt1")
        sig.append(rs)

        vx = _mic.pgrcdt2 + 1
        rx = RadioSettingValueInteger(1, 50, vx)
        rs = RadioSetting("micset.pgrcdt2", "Pager Transmit Second Code", rx)
        rs.set_apply_callback(self._adjint, _mic, "pgrcdt2")
        sig.append(rs)

        rx = RadioSettingValueList(offon, offon[_setx.wxalrt])
        rs = RadioSetting("setts.wxalrt", "Weather Alert Enabled", rx)
        sig.append(rs)

        # End of Signalling settings

        # Begin fmenu settings      For each entry in menu_Items
        if self.FTM200:     # 124 menu options possible
            options = ["1:Freq Input", "2:LCD Brightness", "3:Freq Color",
                       "4:Band Scope", "5:Location Info", "6:Compass",
                       "7:Display Mode"]
            more = ("8:TX Power", "9:AMS TX Mode", "10:Mic Gain", "11:VOX",
                    "12:Auto Dialer", "13:Time Out Timer (TOT)",
                    "14:Digital VW")
            options.extend(more)
            more = ("15:FM Bandwidth", "16:RX Mode", "17:Home",
                    "18:Memory List", "19:Memory List Mode", "20:PMG Clear")
            options.extend(more)
            more = ("21:Beep", "22:Band Skip", "23:RPT ARS", "24:RPT Shift",
                    "25:RPT Shift Freq", "26:Rpt Reverse", "27:Mic P Key",
                    "28:Date & Time Adjust", "29:Date  &Time Format",
                    "30:Time Zone", "31:Step", "32:Clock Type", "33:Unit",
                    "34:Auto Power Off (APO)", "35:GPS Datum",
                    "36:GPS Device", "37:GPS Log")
            options.extend(more)
            more = ("38:Audio Recording", "39:Audio Rec Stop")
            options.extend(more)
            more = ("40:DTMF Mode", "41:DTMF Memory", "42:SQL Type",
                    "43:Tone Freq / DCS Code", "44:SQL Expansion",
                    "45:Pager Code", "46:PR Freq", "47:Bell Ringer",
                    "48:WX Alert")
            options.extend(more)
            more = ("49:Scan", "50:Dual Rcv Mode", "51:Dual Rx Interval",
                    "52:Priority Revert", "53:Scan Resume")
            options.extend(more)
            more = ("54:Digital Popup", "55:Location Service",
                    "56:Standy Beep", "57:GM FP-ID List", "58:Range Ringer",
                    "59:Radio ID", "60:Log List", "61:Rpt / WIRES Freq",
                    "62:Search Step", "63:Edit Category Tag",
                    "64:Delete Room/Mode", "65:WIRES Dg-ID", "66:Com Port",
                    "67:Data Band", "68:Data Speed", "69:Data SQL")
            options.extend(more)
            more = ("70:APRS Destination", "71:Filter", "72:Msg Text",
                    "73:APRS On/Off", "74:Mute", "75:Popup", "76:Ringer",
                    "77:Ringer CS", "78:TX Delay", "79:Units",
                    "80:Beacon Info", "81:Beacon Status Txt",
                    "82:Beacon TX Set", "83:DIGI Path", "84:DIGI Path 1",
                    "85:DIGI Path 2", "86:DIGI Path 3", "87:DIGI Path 4",
                    "88:DIGI Path Full 1", "89: DIGI Path Full 2")
            options.extend(more)
            more = ("90:APRS Call Sign", "91:Msg Group", "92:Msg Reply",
                    "93:My Position Set", "94:My Position", "95:My Symbol",
                    "96:Position Comment", "97:Smart Beaconing",
                    "98:Sort Filter", "99:Voice alert", "100:Station List",
                    "101:Msg List", "102:Beacon TX Select", "103:Beacon TX")
            options.extend(more)
            more = ("104:SD Card Backup", "105:SD Card Mem Info",
                    "106:SD Card Format", "107:Bluetooth", "108:Voice Memory",
                    "109:FVS Rec", "110:Track Select", "111:Play",
                    "112:Stop", "113:Clear", "114:Voice Guide",
                    "115:USB Camera")
            options.extend(more)
            more = ("116:This->Other", "117:Other->This", "118:Call Sign",
                    "119:Mem Chn Reset", "120:APRS Reset", "121:Config Set",
                    "122:Config Recall", "123:SW Version",
                    "124:Factory Reset")
            options.extend(more)
            rx = RadioSettingValueList(options, options[_mic.fkp1])
            rs = RadioSetting("micset.fkp1", "Keypad Slot 1", rx)
            rs.set_apply_callback(self._setQA, _mic, "fkp1", options)
            fmenu.append(rs)
            rx = RadioSettingValueList(options, options[_mic.fkp2])
            rs = RadioSetting("micset.fkp2", "Keypad Slot 2", rx)
            rs.set_apply_callback(self._setQA, _mic, "fkp2", options)
            fmenu.append(rs)
            rx = RadioSettingValueList(options, options[_mic.fkp3])
            rs = RadioSetting("micset.fkp3", "Keypad Slot 3", rx)
            rs.set_apply_callback(self._setQA, _mic, "fkp3", options)
            fmenu.append(rs)
            rx = RadioSettingValueList(options, options[_mic.fkp4])
            rs = RadioSetting("micset.fkp4", "Keypad Slot 4", rx)
            rs.set_apply_callback(self._setQA, _mic, "fkp4", options)
            fmenu.append(rs)

            rx = RadioSettingValueList(options, options[_mic.fhm1])
            rs = RadioSetting("micset.fhm1", "Home Slot 1", rx)
            rs.set_apply_callback(self._setQA, _mic, "fhm1", options)
            fmenu.append(rs)
            rx = RadioSettingValueList(options, options[_mic.fhm2])
            rs = RadioSetting("micset.fhm2", "Home Slot 2", rx)
            rs.set_apply_callback(self._setQA, _mic, "fhm2", options)
            fmenu.append(rs)
            rx = RadioSettingValueList(options, options[_mic.fhm3])
            rs = RadioSetting("micset.fhm3", "Home Slot 3", rx)
            rs.set_apply_callback(self._setQA, _mic, "fhm3", options)
            fmenu.append(rs)
            rx = RadioSettingValueList(options, options[_mic.fhm4])
            rs = RadioSetting("micset.fhm4", "Home Slot 4", rx)
            rs.set_apply_callback(self._setQA, _mic, "fhm4", options)
            fmenu.append(rs)
        else:           # FTM-6000
            _shr = self._memobj.share1
            for mnu in range(0, 35):
                x1 = mnu * 2    # _shr index of first byte
                vx = _shr[x1].shbyt
                bx = False
                if vx != 0xff:
                    bx = True
                sx = "share1/%d.shbyt" % mnu
                rx = RadioSettingValueBoolean(bx)
                rs = RadioSetting(sx, menu_items[mnu], rx)
                fmenu.append(rs)
                rs.set_apply_callback(self._setfunc, _shr, "shbyt", mnu)
        # End fmenu settings

        # Begin microphone settings
        options = ["Min", "Low", "Normal", "High", "Max"]
        rx = RadioSettingValueList(options, options[_mic.micgain])
        rs = RadioSetting("micset.micgain", "Microphone Gain", rx)
        mic.append(rs)

        options = ["ARTS", "SCAN On", "HOME Recall", "Repeater Duplex",
                   "Repeater Reverse", "Transmit Power", "Squelch Off",
                   "T-Call", "Dual Watch", "Weather Channel"]
        if self.FTM200:
            options = ["Off", "Band Scope", "Scan", "Home", "Rpt Shift",
                       "Reverse", "TX Power", "SQL Off", "T-Call", "Voice",
                       "D_X", "WX", "Stn_List", "Msg List", "Reply",
                       "M-Edit"]

        else:               # FTM200- P1 is fixed as GM, immutable
            vx = _mic.micp1 - 0xdd
            if vx == 10:
                vx = 9     # stupid index jump
            rx = RadioSettingValueList(options, options[vx])
            rs = RadioSetting("micset.micp1", "Microphone Key P1", rx)
            rs.set_apply_callback(self._micpkey, _mic, "micp1", options)
            mic.append(rs)

        vx = _mic.micp2 - 0xdd
        if vx == 10:
            vx = 9
        if self.FTM200:
            vx = _mic.micp2 - 0xdc
        rx = RadioSettingValueList(options, options[vx])
        rs = RadioSetting("micset.micp2", "Microphone Key P2", rx)
        rs.set_apply_callback(self._micpkey, _mic, "micp2",  options)
        mic.append(rs)

        vx = _mic.micp3 - 0xdd
        if vx == 10:
            vx = 9
        if self.FTM200:
            vx = _mic.micp3 - 0xdc
        rx = RadioSettingValueList(options, options[vx])
        rs = RadioSetting("micset.micp3", "Microphone Key P3", rx)
        rs.set_apply_callback(self._micpkey, _mic, "micp3",  options)
        mic.append(rs)

        vx = _mic.micp4 - 0xdd
        if vx == 10:
            vx = 9
        if self.FTM200:
            vx = _mic.micp4 - 0xdc
        rx = RadioSettingValueList(options, options[vx])
        rs = RadioSetting("micset.micp4", "Microphone Key P4", rx)
        rs.set_apply_callback(self._micpkey, _mic, "micp4",  options)
        mic.append(rs)
        # End mic settings

        # Begin DTMF settings
        options = ["Manual", "Auto"]
        rx = RadioSettingValueList(options, options[_setx.dtmf_auto])
        rs = RadioSetting("setts.dtmf_auto", "DTMF Transmit Mode", rx)
        dtmf.append(rs)

        for kx in range(0, 9):
            sx = self._unpack_str(_dtm[kx].codes)
            rx = RadioSettingValueString(0, 16, sx, False)
            # NOTE the / to indicate indexed array
            vx = kx + 1
            rs = RadioSetting("dtmfcode/%d.codes" % kx,
                              "DTMF Code %d" % vx, rx)
            rs.set_apply_callback(self._pack_chars, _dtm, "codes", kx)
            dtmf.append(rs)
        # End of dtmf settings

        # Begin Scan settings
        if self.FTM200:
            options = ["Busy", "Hold", "1 Second", "3 Seconds", "5 Seconds"]
            rx = RadioSettingValueList(options, options[_setx.scnrsm2a])
            rs = RadioSetting("setts.scnrsm2a", "A: Scan Resume Mode", rx)
            scan.append(rs)
            rx = RadioSettingValueList(options, options[_setx.scnrsm2b])
            rs = RadioSetting("setts.scnrsm2b", "B: Scan Resume Mode", rx)
            scan.append(rs)

            options = ["0.5 seconds", "1 sec", "2 sec", "3 sec", "5 sec",
                       "7 sec", "10 secs"]
            rx = RadioSettingValueList(options, options[_setx.scndria])
            rs = RadioSetting("setts.scndria", "A: Dual Receive Interval",
                              rx)
            scan.append(rs)
            rx = RadioSettingValueList(options, options[_setx.scndrib])
            rs = RadioSetting("setts.scndrib", "B: Dual Receive Interval",
                              rx)
            scan.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.dwrvt])
            rs = RadioSetting("setts.dwrvt", "A: Priority Revert", rx)
            scan.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.dwrvtb])
            rs = RadioSetting("setts.dwrvtb", "B: Priority Revert", rx)
            scan.append(rs)

            options = ["Off", "Priority Scan", "A-B Dual Receive"]
            # unbelievable 2- byte configuration
            v0 = _setx.scndrm1      # at 17f62 bit 8
            v1 = _setx.scndrm2      # at 17f6b bit 1
            vx = 0
            if v0 == 1:
                vx = 1
            elif v1 == 1:
                vx = 2
            rx = RadioSettingValueList(options, options[vx])
            rs = RadioSetting("setts.scndrm1", "Scan Dual Receive Mode", rx)
            rs.set_apply_callback(self._scndrm, _setx)
            scan.append(rs)

        else:
            options = ["Busy", "Hold", "1 Second", "3 Seconds", "5 Seconds"]
            rx = RadioSettingValueList(options, options[_setx.scnrsm])
            rs = RadioSetting("setts.scnrsm", "Scan Resume Mode", rx)
            scan.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.dwrvt])
            rs = RadioSetting("setts.dwrvt", "Dual Watch Revert", rx)
            scan.append(rs)
        # End of Scan settings

        # Begin Data settings
        if self.FTM200:
            options = ["4700 bps", "9600 bps", "19200 bps", "38400 bps",
                       "57600 bps"]
            rx = RadioSettingValueList(options, options[_wierd.comspd])
            rs = RadioSetting("wierd.comspd", "COM Port Speed", rx)
            dat.append(rs)

            options = ["Off", "GPS Out", "Packet", "Waypoint"]
            rx = RadioSettingValueList(options, options[_wierd.comout])
            rs = RadioSetting("wierd.comout", "COM Port Output", rx)
            dat.append(rs)

            options = ["NMEA9", "NMEA8", "NMEA7", "NMEA6"]
            rx = RadioSettingValueList(options, options[_wierd.comwpf])
            rs = RadioSetting("wierd.comwpf", "COM Port Waypoint Format", rx)
            dat.append(rs)

            options = ["All", "Mobile", "Frequency", "Object/Item",
                       "Digipeater", "VoIP", "Weather", "Yaesu",
                       "Call Ringer", "Rng Ringer"]
            rx = RadioSettingValueList(options, options[_wierd.comflt])
            rs = RadioSetting("wierd.comflt", "COM Port Waypoint Filter", rx)
            dat.append(rs)

            options = ["Main Band", "Sub Band", "A-Band Fix", "B-Band Fix"]
            rx = RadioSettingValueList(options, options[_wierd.dbsela])
            rs = RadioSetting("wierd.dbsela", "Data Band Select: APRS", rx)
            dat.append(rs)
            rx = RadioSettingValueList(options, options[_wierd.dbseld])
            rs = RadioSetting("wierd.dbseld", "Data Band Select: Data", rx)
            dat.append(rs)

            options = ["1200 bps", "9600 bps"]
            rx = RadioSettingValueList(options, options[_wierd.dspda])
            rs = RadioSetting("wierd.dspda", "Data Speed: APRS", rx)
            dat.append(rs)
            rx = RadioSettingValueList(options, options[_wierd.pktspd])
            rs = RadioSetting("wierd.pktspd", "Data Speed: Data", rx)
            dat.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.datsql])
            rs = RadioSetting("wierd.datsql", "Data Squelch", rx)
            dat.append(rs)
        # End of Data Settings

        # Begin Options settings
        if self.FTM200:
            options = ["FREE 5 min", "LAST 30 sec"]
            rx = RadioSettingValueList(options, options[_setx.fvsrec])
            rs = RadioSetting("setts.fvsrec", "FVS-2: Play/Record", rx)
            opts.append(rs)

            options = ["Off", "Manual", "Auto"]
            rx = RadioSettingValueList(options, options[_setx.fvsanc])
            rs = RadioSetting("setts.fvsanc", "FVS-2: Announce Mode", rx)
            opts.append(rs)

            options = ["English", "Japanese"]
            rx = RadioSettingValueList(options, options[_setx.fvslan])
            rs = RadioSetting("setts.fvslan", "FVS-2: Language", rx)
            opts.append(rs)

            options = ["Low", "Mid", "High"]
            rx = RadioSettingValueList(options, options[_setx.fvsvol])
            rs = RadioSetting("setts.fvsvol", "FVS-2: Volume", rx)
            opts.append(rs)

            # Yaesu split the FTM-200 BEEP 0/1/2 into 2 byte locations!!
            # and assigned this bit to the upper Beep of the FTM-6000!!
            rx = RadioSettingValueList(onoff, onoff[_setx.fvsrxm])
            rs = RadioSetting("setts.fvsrxm", "FVS-2: RX Mute", rx)
            opts.append(rs)

        # Common Options - BLUETOOTH
        rx = RadioSettingValueList(offon, offon[_setx.bton])
        rs = RadioSetting("setts.bton", "Bluetooth: Enabled", rx)
        opts.append(rs)

        rx = RadioSettingValueList(offon, offon[_setx.btsave])
        rs = RadioSetting("setts.btsave", "Bluetooth: Save", rx)
        opts.append(rs)

        options = ["Auto", "Fix"]
        rx = RadioSettingValueList(options, options[_setx.btaud])
        rs = RadioSetting("setts.btaud", "Bluetooth: Audio", rx)
        opts.append(rs)

        if self.FTM200:
            options = ["320 x 240", "160 x 120"]
            rx = RadioSettingValueList(options, options[_mic.usbcamsz])
            rs = RadioSetting("micset.usbcamsz", "USB Camera: Image Size", rx)
            opts.append(rs)

            options = ["Low", "Normal", "High"]
            rx = RadioSettingValueList(options, options[_mic.usbcamql])
            rs = RadioSetting("micset.usbcamql", "USB Camera: Image Quality",
                              rx)
            opts.append(rs)

        # End of Options settings

        # Begin Other settings

        if self.FTM200:
            options = ["A", "B", "A+B"]
            rx = RadioSettingValueList(options, options[_setx.audrec - 1])
            rs = RadioSetting("setts.audrec", "Audio Recording Band", rx)
            rs.set_apply_callback(self._adjlist, _setx, "audrec", options,
                                  1)
            other.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.audmic])
            rs = RadioSetting("setts.audmic", "Microphone", rx)
            other.append(rs)

            options = ["Off", "Low", "High"]
            rx = RadioSettingValueList(options, options[_setx.voxsen])
            rs = RadioSetting("setts.voxsen", "VOX Sensitivity", rx)
            other.append(rs)
            options = ["0.5 seconds", "1 sec", "1.5 sec", "2.0 sec",
                       "2.5sec", "3 sec"]
            rx = RadioSettingValueList(options, options[_setx.voxdly])
            rs = RadioSetting("setts.voxdly", "VOX Delay", rx)
            other.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.bskpa1])
            rs = RadioSetting("setts.bskpa1", "A: Air Band Enabled", rx)
            other.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.bskpa2])
            rs = RadioSetting("setts.bskpa2", "A: VHF Band Enabled", rx)
            other.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.bskpa4])
            rs = RadioSetting("setts.bskpa4", "A: UHF Band Enabled", rx)
            other.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.bskpa3])
            rs = RadioSetting("setts.bskpa3", "A: Other Band Enabled", rx)
            rs.set_apply_callback(self._skp_other, _setx, "A", options)
            other.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.bskpb1])
            rs = RadioSetting("setts.bskpb1", "B: Air Band Enabled", rx)
            other.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.bskpb2])
            rs = RadioSetting("setts.bskpb2", "B: VHF Band Enabled", rx)
            other.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.bskpb4])
            rs = RadioSetting("setts.bskpb4", "B: UHF Band Enabled", rx)
            other.append(rs)
            rx = RadioSettingValueList(offon, offon[_setx.bskpb3])
            rs = RadioSetting("setts.bskpb3", "B: Other Band Enabled", rx)
            rs.set_apply_callback(self._skp_other, _setx, "B", options)
            other.append(rs)

        else:
            options = ["1200 bps", "9600 bps"]
            rx = RadioSettingValueList(options, options[_wierd.pktspd])
            rs = RadioSetting("wierd.pktspd", "Data Port Packet Baud Rate",
                              rx)
            other.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.airb])
            rs = RadioSetting("setts.airb", "Air Band Enabled", rx)
            other.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.vhfb])
            rs = RadioSetting("setts.vhfb", "VHF Band Enabled", rx)
            other.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.uhfb])
            rs = RadioSetting("setts.uhfb", "UHF Band Enabled", rx)
            other.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.otrb])
            rs = RadioSetting("setts.otrb", "Other Band Enabled", rx)
            other.append(rs)
        # End of Other Settings

        # Start FTM200 Unique settings
        if self.FTM200:
            _wrx = self._memobj.wrxmsg
            xmap = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop"
            xmap += "qrstuvwxyz!\"#$%&\\()*+,-./:;<=>?@[']^_`{|}~****** "
            # NOTE: Unknown characters at index 94-99; replaced with *
            for ix in range(1, 11):
                atr = "msg%02d" % ix
                sx = getattr(_wrx, atr)
                tx = ""
                for cx in sx:
                    if cx == 0xff:
                        break
                    tx += xmap[cx]
                tx = tx.strip()
                rx = RadioSettingValueString(0, 128, tx, False)
                atr = "wrxmsg.msg%02d" % ix
                rs = RadioSetting(atr, "Message M%02d" % ix, rx)
                rs.set_apply_callback(self._xmsg, _wrx, ix, xmap)
                wires.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.wrxrng])
            rs = RadioSetting("setts.wrxrng", "Range Ringer", rx)
            wires.append(rs)

            options = ["Auto", "TX FM Fixed", "TX DN Fixed"]
            rx = RadioSettingValueList(options, options[_setx.wrxams])
            rs = RadioSetting("setts.wrxams", "AMS TX Mode", rx)
            wires.append(rs)

            options = ["Off", "2 seconds", "4 sec", "6 sec", "8 sec",
                       "10 sec", "20 sec", "30 sec", "60 sec", "Continuous"]
            rx = RadioSettingValueList(options, options[_mic.wrxpop])
            rs = RadioSetting("micset.wrxpop", "Digital Popup", rx)
            wires.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.wrxloc])
            rs = RadioSetting("setts.wrxloc", "Location Service", rx)
            wires.append(rs)

            rx = RadioSettingValueList(onoff, onoff[_setx.wrxstb])
            rs = RadioSetting("setts.wrxstb", "Standby Beep", rx)
            wires.append(rs)

            rx = RadioSettingValueList(offon, offon[_setx.wrxdvw])
            rs = RadioSetting("setts.wrxdvw", "Digital VW Enable", rx)
            wires.append(rs)

            options = ["Manual", "Preset"]
            rx = RadioSettingValueList(options, options[_setx.wrxrwf])
            rs = RadioSetting("setts.wrxrwf", "RPT/WIRES Frequency Mode", rx)
            wires.append(rs)

            options = ["VHF Preset", "UHF Preset"]
            rx = RadioSettingValueList(options, options[_mic.wrxbsel])
            rs = RadioSetting("micset.wrxbsel", "RPT/WIRES Preset Band Select",
                              rx)
            wires.append(rs)

            vx = self._freqdcode(_mic.wrxvfrq) / 1000000
            rx = RadioSettingValueFloat(144.0, 149.0, vx, 0.001, 3)
            rs = RadioSetting("micset.wrxvfrq", "RPT/WIRES VHF Preset Freq",
                              rx)
            rs.set_apply_callback(self._wrxfrq, _mic, "wrxvfrq")
            wires.append(rs)

            vx = self._freqdcode(_mic.wrxufrq) / 1000000
            rx = RadioSettingValueFloat(420.0, 460.0, vx, 0.001, 3)
            rs = RadioSetting("micset.wrxufrq", "RPT/WIRES UHF Preset Freq",
                              rx)
            rs.set_apply_callback(self._wrxfrq, _mic, "wrxufrq")
            wires.append(rs)

            options = ["History", "Activity"]
            rx = RadioSettingValueList(options, options[_setx.wrxsrch])
            rs = RadioSetting("setts.wrxsrch", "RPT/WIRES Search Setup", rx)
            wires.append(rs)

            options = ["Auto"]
            for vx in range(1, 100):
                options.append("%02d" % vx)
            rx = RadioSettingValueList(options, options[_mic.wrxdid])
            rs = RadioSetting("micset.wrxdid", "RPT/WIRES Radio Digital ID",
                              rx)
            wires.append(rs)

            _wrxc = self._memobj.wrxcat
            for ix in range(1, 6):
                atr = "c%d" % ix
                sx = getattr(_wrxc, atr)
                tx = ""
                for cx in sx:
                    if cx == 0xca:
                        break
                    tx += xmap[cx]
                tx = tx.strip()
                rx = RadioSettingValueString(0, 16, tx, False)
                atr = "wrxcat.c%d" % ix
                rs = RadioSetting(atr, "Category Text C%d" % ix, rx)
                rs.set_apply_callback(self._xmsg, _wrxc, ix, xmap, 1)
                wires.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprson])
            rs = RadioSetting("wierd.aprson", "APRS Enabled", rx)
            aprscom.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprmut])
            rs = RadioSetting("wierd.aprmut", "Mute", rx)
            aprscom.append(rs)

            options = ["100ms", "150ms", "200ms", "250ms", "300ms", "400ms",
                       "500ms", "750ms", "1000ms"]
            rx = RadioSettingValueList(options, options[_wierd.aprtxd])
            rs = RadioSetting("wierd.aprtxd", "TX Delay", rx)
            aprscom.append(rs)

            options = ["Off", "1 digit", "2 digits", "3 digits", "4 digits"]
            rx = RadioSettingValueList(options, options[_wierd.aprbamb])
            rs = RadioSetting("wierd.aprbamb", "Beacon Ambiguity", rx)
            aprscom.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprspdc])
            rs = RadioSetting("wierd.aprspdc", "Beacon Speed/Course", rx)
            aprscom.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprsalt])
            rs = RadioSetting("wierd.aprsalt", "Beacon Altitude", rx)
            aprscom.append(rs)

            options = ["Off", "On", "Smart"]
            rx = RadioSettingValueList(options, options[_wierd.aprbaut])
            rs = RadioSetting("wierd.aprbaut", "Beacon TX Mode", rx)
            aprscom.append(rs)

            options = ["30 sec", "1 minute", "2 mins", "3 mins", "5 mins",
                       "10 mins", "15 mins", "20 mins", "30 mins", "60 mins"]
            rx = RadioSettingValueList(options, options[_wierd.aprstxi])
            rs = RadioSetting("wierd.aprstxi", "Beacon TX Interval", rx)
            aprscom.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprspro])
            rs = RadioSetting("wierd.aprspro", "Beacon TX Proportional", rx)
            aprscom.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprsdcy])
            rs = RadioSetting("wierd.aprsdcy", "Beacon TX Decay", rx)
            aprscom.append(rs)

            # Lets try using integer values instead of list; just for kicks
            rx = RadioSettingValueInteger(1, 99, _wierd.aprslow)
            rs = RadioSetting("wierd.aprslow", "TX Low Speed (mph)", rx)
            aprscom.append(rs)

            rx = RadioSettingValueInteger(5, 180, _wierd.aprsrate)
            rs = RadioSetting("wierd.aprsrate", "TX Rate Limit (secs)", rx)
            aprscom.append(rs)

            sx = self._b2s(_wierd.aprcsgn, 0xca)
            rx = RadioSettingValueString(0, 6, sx, False)
            rs = RadioSetting("wierd.aprcsgn", "APRS Callsign", rx)
            rs.set_apply_callback(self._s2b, _wierd, "aprcsgn", 6, 0xca)
            aprscom.append(rs)

            options = [""]
            for i in range(1, 16):
                options.append("-%d" % i)
            vx = _wierd.aprcsfx
            if vx == 0xca:
                vx = 0
            rx = RadioSettingValueList(options, options[vx])
            rs = RadioSetting("wierd.aprcsfx", "Call Sign SSID ", rx)
            rs.set_apply_callback(self._aprsfx, _wierd, "aprcsfx", 0xca)
            aprscom.append(rs)

            options = ["Off Duty", "En Route", "In Service", "Returning",
                       "Committed", "Special", "Priority", "Sustom 0",
                       "Custom 1", "Custom 2", "Custom 3", "Custom 4",
                       "Custom 5", "Custom 6", "EMERGENCY!"]
            rx = RadioSettingValueList(options, options[_wierd.aprcmt])
            rs = RadioSetting("wierd.aprcmt", "Position Comment", rx)
            aprscom.append(rs)

            options = ["Off", "3 secs", " 5 secs", "10 secs", "HOLD"]
            vx = _wierd.aprpopb    # hex encoded decimal plus ff= hold
            v1 = 0
            if vx == 3:
                v1 = 1
            if vx == 5:
                v1 = 2
            if vx == 10:
                v1 = 3
            if vx == 0xff:
                v1 = 4
            rx = RadioSettingValueList(options, options[v1])
            rs = RadioSetting("wierd.aprpopb", "Beacon Popup Display Time",
                              rx)
            rs.set_apply_callback(self._aprspop, _wierd, "aprpopb")
            aprscom.append(rs)

            vx = _wierd.aprpopm
            v1 = 0
            if vx == 3:
                v1 = 1
            if vx == 5:
                v1 = 2
            if vx == 10:
                v1 = 3
            if vx == 0xff:
                v1 = 4
            rx = RadioSettingValueList(options, options[v1])
            rs = RadioSetting("wierd.aprpopm",
                              "Message Popup Display Time", rx)
            rs.set_apply_callback(self._aprspop, _wierd, "aprpopm")
            aprscom.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprmpkt])
            rs = RadioSetting("wierd.aprmpkt", "My Packet", rx)
            aprscom.append(rs)

            options = ["Time", "Call Sign", "Distance"]
            rx = RadioSettingValueList(options, options[_wierd.aprsfs])
            rs = RadioSetting("wierd.aprsfs", "Sort Filter: Sort By", rx)
            aprscom.append(rs)

            options = ["All", "Mobile", "Frequency", "Object/Item",
                       "Digipeater", "VoIP", "Weather", "Yaesu",
                       "Other Packet", " Call Ringer", "Range Ringer",
                       "1200 bps", "9600 bps"]
            rx = RadioSettingValueList(options, options[_wierd.aprsff])
            rs = RadioSetting("wierd.aprsff", "Sort Filter: Filter Type", rx)
            aprscom.append(rs)

            options = ["Normal", "Tone-SQL", "DCS", "Rx-TSQL", "Rx-DCS"]
            rx = RadioSettingValueList(options, options[_wierd.aprvlrt])
            rs = RadioSetting("wierd.aprvlrt", "Voice Alert: Mode", rx)
            aprscom.append(rs)

            options = []
            for vx in chirp_common.TONES:
                options.append("%.1f" % vx)
            rx = RadioSettingValueList(options, options[_wierd.aprtsql])
            rs = RadioSetting("wierd.aprtsql", "Voice Alert: TSQL Tone", rx)
            aprscom.append(rs)

            options = []
            for vx in chirp_common.DTCS_CODES:
                options.append("%03d" % vx)
            rx = RadioSettingValueList(options, options[_wierd.aprvdcs])
            rs = RadioSetting("wierd.aprvdcs", "Voice Alert: DCS Code", rx)
            aprscom.append(rs)

            options = ["GPS", "Manual"]
            rx = RadioSettingValueList(options, options[_wierd.aprmpos])
            rs = RadioSetting("wierd.aprmpos", "My Position Mode", rx)
            aprscom.append(rs)

            optns = ["North", "South"]
            rx = RadioSettingValueList(optns, optns[_wierd.aprltns])
            rs = RadioSetting("wierd.aprltns",
                              "My Position Manual Lat N/S", rx)
            aprscom.append(rs)

            v0 = int("%X" % _wierd.aprlad)      # Hex coded Decimal
            rx = RadioSettingValueInteger(0, 90, v0)
            rs = RadioSetting("wierd.aprlad",
                              "My Position Manual Lat Degrees", rx)
            rs.set_apply_callback(self._enchcd, _wierd, "aprlad")
            aprscom.append(rs)

            v0 = int("%X" % _wierd.aprlam)      # Whole Minutes, HCD
            v1 = _wierd.aprlas
            v1 = v1 / 1000
            vx = v0 + v1
            rx = RadioSettingValueFloat(0, 59.99, vx, 0.01, 2)
            rs = RadioSetting("wierd.aprlas",
                              "My Position Manual Lat Minutes", rx)
            rs.set_apply_callback(self._mdot, _wierd, "aprlam", "aprlas")
            aprscom.append(rs)

            optns = ["East", "West"]
            rx = RadioSettingValueList(optns, optns[_wierd.aprlgew])
            rs = RadioSetting("wierd.aprlgew",
                              "My Position Manual Long N/S", rx)
            aprscom.append(rs)

            v0 = int("%X" % _wierd.aprlgd)
            rx = RadioSettingValueInteger(0, 180, v0)
            rs = RadioSetting("wierd.aprlgd",
                              "My Position Manual Long Degrees", rx)
            rs.set_apply_callback(self._enchcd, _wierd, "aprlgd")
            aprscom.append(rs)

            v0 = int("%X" % _wierd.aprlgm)
            v1 = _wierd.aprlgs
            v1 = v1 / 1000
            vx = v0 + v1
            rx = RadioSettingValueFloat(0, 59.99, vx, 0.01, 2)
            rs = RadioSetting("wierd.aprlgs",
                              "My Position Manual Long Minutes", rx)
            rs.set_apply_callback(self._mdot, _wierd, "aprlgm", "aprlgs")
            aprscom.append(rs)

            # APRS Digipeater Settings

            options = ["Off", "Wide 1-1", "Wide 1-1, 1-2", "Path 1",
                       "Path 2", "Path 3", "Path 4", "Full 1", "Full2"]
            rx = RadioSettingValueList(options, options[_wierd.aprdig])
            rs = RadioSetting("wierd.aprdig", "Digipeater Route Selection",
                              rx)
            aprsdgp.append(rs)

            # Using shared memory 'share1'; extracting Digipath data
            _shr = self._memobj.share1
            optsfx = [""]           # List for path suffix
            for i in range(1, 16):
                optsfx.append("-%d" % i)
            py = 0                  # route index 0-7 for 'paths'
            pz = 0                  # index to _shr array for dummy memobj
            for px in range(0, 4):      # Path 1 - 4
                sx, sfx = self._getdgpath(py)
                rx = RadioSettingValueString(0, 6, sx, False)
                tx = "Path-%d First Route Callsign" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpname, py)
                aprsdgp.append(rs)
                pz += 1
                rx = RadioSettingValueList(optsfx, optsfx[sfx])
                tx = "Path-%d First Route SSID" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpsfx, py)
                aprsdgp.append(rs)
                py += 1
                pz += 1
                sx, sfx = self._getdgpath(py)
                rx = RadioSettingValueString(0, 6, sx, False)
                tx = "Path-%d Second Route Callsign" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpname, py)
                aprsdgp.append(rs)
                pz += 1
                rx = RadioSettingValueList(optsfx, optsfx[sfx])
                tx = "Path-%d Second Route SSID" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpsfx, py)
                aprsdgp.append(rs)
                py += 1
                pz += 1
            # Now 8 routes for 'Full1'
            for px in range(0, 8):
                sx, sfx = self._getdgpath(py)
                rx = RadioSettingValueString(0, 6, sx, False)
                tx = "Full-1 Route %d Callsign" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpname, py)
                aprsdgp.append(rs)
                pz += 1
                rx = RadioSettingValueList(optsfx, optsfx[sfx])
                tx = "Full-1 Route %d SSID" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpsfx, py)
                aprsdgp.append(rs)
                py += 1
                pz += 1
            # and 8 more for 'Full2'
            for px in range(0, 8):
                sx, sfx = self._getdgpath(py)
                rx = RadioSettingValueString(0, 6, sx, False)
                tx = "Full-2 Route %d Callsign" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpname, py)
                aprsdgp.append(rs)
                pz += 1
                rx = RadioSettingValueList(optsfx, optsfx[sfx])
                tx = "Full-2 Route %d SSID" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpsfx, py)
                aprsdgp.append(rs)
                py += 1
                pz += 1

            # --- APRS Messages =====

            _apmsg = self._memobj.aprsmsg
            for vx in range(1, 7):
                tx = "grp%d" % vx
                bx = getattr(_apmsg, tx)
                sx = self._b2s(bx, 0xca)
                qx = "aprsmsg.grp%d" % vx
                rx = RadioSettingValueString(0, 9, sx, False)
                rs = RadioSetting(qx, "Message Group %d Text" % vx, rx)
                rs.set_apply_callback(self._s2b, _apmsg, tx, 9, 0xca)
                aprsmsg.append(rs)

            for vx in range(1, 4):
                tx = "blt%d" % vx
                bx = getattr(_apmsg, tx)
                sx = self._b2s(bx, 0xca)
                qx = "aprsmsg.blt%d" % vx
                rx = RadioSettingValueString(0, 9, sx, False)
                rs = RadioSetting(qx, "Message Bulletin %d Text" % vx, rx)
                rs.set_apply_callback(self._s2b, _apmsg, tx, 9, 0xca)
                aprsmsg.append(rs)

            _aptxt = self._memobj.aprstxt
            for vx in range(1, 9):
                tx = "txt%d" % vx
                bx = getattr(_aptxt, tx)
                sx = self._b2s(bx, 0xca)
                qx = "aprstxt.txt%d" % vx
                rx = RadioSettingValueString(0, 16, sx, False)
                rs = RadioSetting(qx, "Message %d Text" % vx, rx)
                rs.set_apply_callback(self._s2b, _aptxt, tx, 16, 0xca)
                aprsmsg.append(rs)

            options = []
            for i in range(1, 9):
                options.append("%d" % i)
            rx = RadioSettingValueList(options, options[_wierd.aprstxn])
            rs = RadioSetting("wierd.aprstxn", "Message # Selected", rx)
            aprsmsg.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprrply])
            rs = RadioSetting("wierd.aprrply", "Message Reply Enabled", rx)
            aprsmsg.append(rs)

            sx = self._b2s(_wierd.aprrcsn, 0x2a)
            rx = RadioSettingValueString(0, 6, sx, False)
            rs = RadioSetting("wierd.aprrcsn", "Message Reply Callsign", rx)
            rs.set_apply_callback(self._s2b, _wierd, "aprrcsn", 6, 0x2a)
            aprsmsg.append(rs)

            options = [" "]
            for i in range(1, 16):
                options.append("-%d" % i)
            options.append("-**")       # index 16
            vx = _wierd.aprrcfx
            if vx == 0x2a:
                vx = 16
            rx = RadioSettingValueList(options, options[vx])
            rs = RadioSetting("wierd.aprrcfx", "Reply Call Sign SSID", rx)
            rs.set_apply_callback(self._aprsfx, _wierd, "aprrcfx", 0x2a)
            aprsmsg.append(rs)

            sx = self._b2s(_wierd.aprrtxt, 0xca)
            rx = RadioSettingValueString(0, 64, sx, False)
            rs = RadioSetting("wierd.aprrtxt", "Message Reply Text", rx)
            rs.set_apply_callback(self._s2b, _wierd, "aprrtxt", 64, 0xca)
            aprsmsg.append(rs)

            options = ["/#", "/&", "/'", "/-", "/.", "/0", "/:", "/;", "/<",
                       "/=", "/>", "/C", "/E", "/I", "/K", "/O", "/P", "/R",
                       "/T", "/U", "/V", "/W", "/X", "Y", "/[", "/\\", "/^",
                       "/_", "/a", "/b", "/f", "/g", "/j", "/k", "/m", "/r",
                       "/s", "/u", "/v", "/y", "\\#", "\\&", "\\-", "\\.",
                       "\\0", "E0", "IO", "W0", "\\;", "\\>", "\\A", "\\K",
                       "\\W", "\\Y", "KY", "YY", "\\^", "\\_", "\\m", "\\n",
                       "\\s", "\\u", "\\v", "\\x"]
            for i in range(1, 4):
                tx = "aprsym%d" % i
                bx = getattr(_wierd, tx)
                sx = self._b2s(bx, 0)           # 2-byte char string
                qx = "wierd.aprsym%d" % i
                rx = RadioSettingValueList(options, sx)
                rs = RadioSetting(qx, "My Symbol #%d" % i, rx)
                rs.set_apply_callback(self._s2b, _wierd, tx, 2, 0)
                aprsmsg.append(rs)

            options = ["/"]
            for i in range(48, 58):
                options.append(chr(i))   # numerals
            for i in range(65, 91):
                options.append(chr(i))   # Cap letters
            options.append("\\")
            sx = chr(_wierd.aprsym4a)
            rx = RadioSettingValueList(options, sx)
            rs = RadioSetting("wierd.aprsym4a", "My Symbol #4 First Value",
                              rx)
            rs.set_apply_callback(self._c2u8, _wierd, "aprsym4a")
            aprsmsg.append(rs)

            options = []
            for i in range(33, 127):
                options.append(chr(i))   # full ascii
            sx = chr(_wierd.aprsym4b)
            rx = RadioSettingValueList(options, sx)
            rs = RadioSetting("wierd.aprsym4b", "My Symbol #4 Second Value",
                              rx)
            rs.set_apply_callback(self._c2u8, _wierd, "aprsym4b")
            aprsmsg.append(rs)

            options = ["#1", "#2", "#3", "#4"]
            rx = RadioSettingValueList(options, options[_wierd.aprsym])
            rs = RadioSetting("wierd.aprsym", "My Symbol Selected", rx)
            aprsmsg.append(rs)

            # --- APRS Beacon Settings -----
            rx = RadioSettingValueList(offon, offon[_wierd.aprbfme])
            rs = RadioSetting("wierd.aprbfme", "Filter: MIC-E", rx)
            bcnfltr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbfpo])
            rs = RadioSetting("wierd.aprbfpo", "Filter: Position", rx)
            bcnfltr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbfwx])
            rs = RadioSetting("wierd.aprbfwx", "Filter: Weather", rx)
            bcnfltr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbfob])
            rs = RadioSetting("wierd.aprbfob", "Filter: Object", rx)
            bcnfltr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbfit])
            rs = RadioSetting("wierd.aprbfit", "Filter: Item", rx)
            bcnfltr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbfst])
            rs = RadioSetting("wierd.aprbfst", "Filter: Status", rx)
            bcnfltr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbfot])
            rs = RadioSetting("wierd.aprbfot", "Filter: Other", rx)
            bcnfltr.append(rs)

            options = ["Off", "1", "10", "100", "1000", "3000"]
            v0 = int(_wierd.aprbfrl)     # u16 int: 0,1,10,100,1000,3000
            if v0 == 0:
                vx = 0
            else:
                vx = options.index(str(v0))
            rx = RadioSettingValueList(options, options[vx])
            rs = RadioSetting("wierd.aprbfrl",
                              "Filter: Range Limit (km:miles)", rx)
            rs.set_apply_callback(self._rnglmt, _wierd, "aprbfrl")
            bcnfltr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbfan])
            rs = RadioSetting("wierd.aprbfan", "Filter: AltNet", rx)
            bcnfltr.append(rs)

            options = ["dd mm ss", "dd mm.mm"]
            rx = RadioSettingValueList(options, options[_wierd.aprbupo])
            rs = RadioSetting("wierd.aprbupo", "Units: Position Format", rx)
            bcnunit.append(rs)

            options = ["kilometers", "miles"]
            rx = RadioSettingValueList(options, options[_wierd.aprbudi])
            rs = RadioSetting("wierd.aprbudi", "Units: Distance", rx)
            bcnunit.append(rs)

            options = ["km/h", "mph", "knots"]
            rx = RadioSettingValueList(options, options[_wierd.aprbusp])
            rs = RadioSetting("wierd.aprbusp", "Units: Speed", rx)
            bcnunit.append(rs)

            options = ["meters", "feet"]
            rx = RadioSettingValueList(options, options[_wierd.aprbual])
            rs = RadioSetting("wierd.aprbual", "Units: Altitude", rx)
            bcnunit.append(rs)

            options = ["hPa", "mb", "mmHg", "inHg"]
            rx = RadioSettingValueList(options, options[_wierd.aprbubo])
            rs = RadioSetting("wierd.aprbubo", "Units: Barometric Pressure",
                              rx)
            bcnunit.append(rs)

            options = ["Celsius", "Farenheit"]
            rx = RadioSettingValueList(options, options[_wierd.aprbutp])
            rs = RadioSetting("wierd.aprbutp", "Units: Temperature", rx)
            bcnunit.append(rs)

            options = ["mm", "inch"]
            rx = RadioSettingValueList(options, options[_wierd.aprburn])
            rs = RadioSetting("wierd.aprburn", "Units: Rain", rx)
            bcnunit.append(rs)

            options = ["m/s", "mph", "knots"]
            rx = RadioSettingValueList(options, options[_wierd.aprbuwd])
            rs = RadioSetting("wierd.aprbuwd", "Units: Wind Speed", rx)
            bcnunit.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbrtb])
            rs = RadioSetting("wierd.aprbrtb", "Ringer: TX Beacon", rx)
            bcnrngr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbrtm])
            rs = RadioSetting("wierd.aprbrtm", "Ringer: TX Message", rx)
            bcnrngr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbrrb])
            rs = RadioSetting("wierd.aprbrrb", "Ringer: RX Beacon", rx)
            bcnrngr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbrrm])
            rs = RadioSetting("wierd.aprbrrm", "Ringer: RX Message", rx)
            bcnrngr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbrmp])
            rs = RadioSetting("wierd.aprbrmp", "Ringer: My Packet", rx)
            bcnrngr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbrcr])
            rs = RadioSetting("wierd.aprbrcr", "Ringer: Call Ringer", rx)
            bcnrngr.append(rs)

            options = ["Off", "1", "5", "10", "50", "100"]
            v0 = int(_wierd.aprbrrr)     # u8 int: 0,1,5,10,50,100
            if v0 == 0:
                vx = 0
            else:
                vx = options.index(str(v0))
            rx = RadioSettingValueList(options, options[vx])
            rs = RadioSetting("wierd.aprbrrr", "Ringer: Range Ringer", rx)
            rs.set_apply_callback(self._rnglmt, _wierd, "aprbrrr")
            bcnrngr.append(rs)

            rx = RadioSettingValueList(offon, offon[_wierd.aprbrmv])
            rs = RadioSetting("wierd.aprbrmv", "Ringer: Message Voice", rx)
            bcnrngr.append(rs)

            # --- APRS Ringer Call Signs and SSID Suffix ---
            py = 0x18                  # Share1 cs index
            pz = 0x30                  # dummy share1 index
            for px in range(0, 8):      # Calls 1-8
                sx, sfx = self._getdgpath(py)
                rx = RadioSettingValueString(0, 6, sx, False)
                tx = "Ringer Callsign %d" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpname, py)
                bcnrngr.append(rs)
                pz += 1
                rx = RadioSettingValueList(optsfx, optsfx[sfx])
                tx = "Ringer Callsign %d SSID" % (px + 1)
                rs = RadioSetting("share1/%d.shbyte" % pz, tx, rx)
                rs.set_apply_callback(self._putdgpsfx, py)
                bcnrngr.append(rs)
                py += 1
                pz += 1

            # --- Beacon Status Text ----
            _bstat = self._memobj.bcntxt
            options = ["Off", "Text 1", "Text 2", "Text 3", "Text 4",
                       "Text 5"]
            rx = RadioSettingValueList(options, options[_wierd.bcnstat])
            rs = RadioSetting("wierd.bcnstat", "APRS Beacon Text Select", rx)
            bcnstat.append(rs)

            options = ["1/1", "1/2", "1/3", "1/4", "1/5", "1/6", "1/7", "1/8",
                       "1/2(Freq)", "1/3(Freq)", "1/4(Freq)", "1/5(Freq)",
                       "1/6(Freq)", "1/7(Freq)", "1/8(Freq)"]
            rx = RadioSettingValueList(options, options[_wierd.bcntxra])
            rs = RadioSetting("wierd.bcntxra", "Beacon Text Rate", rx)
            bcnstat.append(rs)

            options = ["None", "Frequency", "Freq & SQL & Shift"]

            for i in range(0, 5):
                vx = i + 1
                sx = self._b2s(_bstat[i].msg, 0xca)
                rx = RadioSettingValueString(0, 60, sx)
                rs = RadioSetting("bcntxt/%d.msg" % i,
                                  "Status Text %d" % vx, rx)
                rs.set_apply_callback(self._s2b, _bstat[i], "msg", 60, 0xca)
                bcnstat.append(rs)

                rx = RadioSettingValueList(options, options[_bstat[i].mode])
                rs = RadioSetting("bcntxt/%d.mode" % i,
                                  "Status Text %d Mode" % vx, rx)
                bcnstat.append(rs)

            # --- Smart Beaconing

            options = ["Off", "Type 1", "Type 2", "Type 3"]
            rx = RadioSettingValueList(options, options[_wierd.bcnsmart])
            rs = RadioSetting("wierd.bcnsmart", "Smart Beaconing Status", rx)
            bcnsmrt.append(rs)

            labls = ["Low Speed (2-30)", "High Speed (3-90)",
                     "Slow Rate (1-100 min)", "Fast Rate (10-180 sec)",
                     "Turn Angle (5-90 deg)", "Turn Slope (1-255)",
                     "Turn Time (5-180 sec)"]
            minvals = [2, 3, 1, 10, 5, 1, 5]
            maxvals = [30, 90, 100, 180, 90, 255, 180]
            for v0 in range(1, 4):       # Type
                sx = "Type %d" % v0
                for v1 in range(0, 7):  # Parameters
                    v2 = getattr(_wierd, "typ%dval%d" % (v0, v1))
                    rx = RadioSettingValueInteger(minvals[v1], maxvals[v1], v2)
                    rs = RadioSetting("wierd.typ%dval%d" % (v0, v1),
                                      "%s %s" % (sx, labls[v1]), rx)
                    bcnsmrt.append(rs)
        # End If FTM-200 Unique settings
        return group       # End get_settings()

    def set_settings(self, settings):
        # _setx = self._memobj.setts
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
                        # obj = _setx
                        obj = self._memobj
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


class Ftm200dAlias(chirp_common.Alias):
    VENDOR = "Yaesu"
    MODEL = "FTM-200D"


@directory.register
class FTM200radio(FTM6000Radio):
    """Yaesu FTM-200"""
    FTM200 = True
    MODEL = "FTM-200"
    NAME_LEN = 16       # Valid name length
    ALIASES = [Ftm200dAlias]
    CHARSET = list(chirp_common.CHARSET_ASCII)
    MODES = ["AM", "FM", "NFM", "DN"]
    NEEDS_COMPAT_SERIAL = False
    TESTME = False
