# Copyright 2024 Jim Unroe <rock.unroe@gmail.com>
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

import struct
import logging

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
struct mem {
    bbcd rxfreq[5];       // RX Frequency                            // 0-4
    u8   step:4,          // STEP                                    // 5
         unk1:2,
         duplex:2;        // Duplex 0: Simplex, 1: Plus, 2: Minus
    u8   unk2:3,                                                     // 6
         reverse:1,       // Reverse
         unk3:4;

    ul16 rxdtcs_pol:1,                                               // 7-8
         unk4:1,
         is_rxdigtone:1,
         unk5:1,
         rxtone:12;
    ul16 txdtcs_pol:1,                                               // 9-A
         unk6:1,
         is_txdigtone:1,
         unk7:1,
         txtone:12;

    u8   unknown1;                                                   // B
    bbcd offset[2];       // Offset 00.05 - 69.95 MHz                // C-D
    u8   unknown2;                                                   // E
    u8   unk8:7,                                                     // F
         narrow:1;        // FM Narrow

    u8   unk9:3,          //                                         // 0
         beatshift:1,     // Beat Shift
         unk10:4;
    bbcd txfreq[4];                                                  // 1-4
    u8   unk11:4,                                                    // 5
         txstep:4;        // TX STEP
    u8   unk12:1,                                                    // 6
         txpower:3,       // Power
         unk13:4;
    u8   unknown3;                                                   // 7
    u8   compand:1,       // Compand                                 // 8
         scramble:3,      // Scramble
         unk14:4;
    char name[6];         // Name                                    // 9-E
    u8   hide:1,          // Channel Hide 0: Show, 1: Hide           // F
         unk15:6,
         skip:1;          // Lock Out (skip when scanning)
};

// #seekto 0x0000;
struct mem left_memory[100];

#seekto 0x0D40;
struct mem right_memory[100];

#seekto 0x1C10;
struct {
    char lower[4];        // 0x1C10 Lower Band Limit
    char upper[4];        // 0x1C14 Upper Band Limit
    char ponmsg[6];       // 0x1C18 Power-On Message
    u8   unknown_1c1e[2]; // 0x1C1E
    u8   keyl;            // 0x1C20 Radio Key Lock
} settings2;

#seekto 0x1C42;
struct {
    u16 freq1;            // Scramble Freq 1
    u16 freq2;            // Scramble Freq 2
    u16 freq3;            // Scramble Freq 3
    u16 freq4;            // Scramble Freq 4
    u16 freq5;            // Scramble Freq 5
    u16 freq6;            // Scramble Freq 6
    u16 ufreq;            // Scramble User Freq
} scramble;

#seekto 0x1CC0;
struct {
    u8 unk1:7,            // 0x1CC0
       ani:1;             //        ANI
    u8 unk2:7,            // 0x1CC1
       tend:1;            //        Roger Beep
    u8 unknown_1cc2[5];   // 0x1CC2-0x1CC6
    u8 unk3:4,            // 0x1CC7
       sql:4;             //        Squelch
    u8 unk4:4,            // 0x1CC8
       sqh:4;             //        Squelch Hang Time
    u8 unknown_1cc9;      // 0x1CC9
    u8 unk5:7,            // 0x1CCA
       relay:1;           //        Relay
    u8 unk6:6,            // 0x1CCB
       scan:2;            //        Scan Resume Method
    u8 unknown_1ccc;      // 0x1CCC
    u8 unk7:7,           // 0x1CCD
       echo:1;            //        Echo
    u8 unknown_1cce;      // 0x1CCE
    u8 unk8:7,            // 0x1CCF
       mdf:1;             //        Memory Display Format
    u8 unk9:5,            // 0x1CD0
       apo:3;             //        Automatic Power Off
    u8 unk10:7,            // 0x1CD1
       ck:1;              //        Call Key
    u8 unk11:7,            // 0x1CD2
       hdl:1;             //        HDL
    u8 unk12:6,           // 0x1CC3
       tot:2;             //        Time-Out Timer
    u8 unk13:7,           // 0x1CD4
       bcl:1;             //        Busy Channel Lockout (global)
    u8 unknown_1cd5;      // 0x1CD5
    u8 unk14:7,           // 0x1CD6
       bp:1;              //        Key Beeps
    u8 unk15:7,           // 0x1CD7
       bs:1;              //        Beat Frequency Offset
    u8 unknown_1cd8;      // 0x1CD8
    u8 unk16:7,           // 0x1CD9
       enc:1;             //        Tuning Control Knob Enable
    u8 unknown_1cda;      // 0x1CDA
    u8 unk17:7,           // 0x1CDB
       spd:1;             //        DTMF Speed
    u8 unk18:7,           // 0x1CDC
       dth:1;             //        DTMF Hold
    u8 unk19:5,           // 0x1CDD
       pa:3;              //        DTMF Pause
    u8 unk20:7,           // 0x1CDE
       dtl:1;             //        DTMF Lock
    u8 unk21:7,           // 0x1CDF
       dtm:1;             //        DTMF Sidetone
    u8 unknown_1ce0[5];   // 0x1CE0-0x1CE4
    u8 unk22:7,           // 0x1CE5
       mcl:1;             //        Mic Key Lock
    u8 unk23:3,           // 0x1CE6
       pf1:5;             //        PF Key 1
    u8 unk24:3,           // 0x1CE7
       pf2:5;             //        PF Key 2
    u8 unk25:3,           // 0x1CE8
       pf3:5;             //        PF Key 3
    u8 unk26:3,           // 0x1CE9
       pf4:5;             //        PF Key 4
    u8 unk27:6,           // 0x1CEA
       llig:2;            //        LCD Light
    u8 unk28:4,           // 0x1CEB
       wfclr:4;           //        Background Color - Wait
    u8 unk29:4,           // 0x1CEC
       rxclr:4;           //        Background Color - RX
    u8 unk30:4,           // 0x1CED
       txclr:4;           //        Background Color - TX
    u8 unk31:4,           // 0x1CEE
       contr:4;           //        Contrast
    u8 unk32:6,           // 0x1CEF
       klig:2;            //        Keypad Light
    u8 unknown_1cf0[2];   // 0x1CF0-0x1CF1
    u8 unk33:7,           // 0x1CF2
       dani:1;            //        DTMF Decode ANI
    u8 unk34:4,           // 0x1CF3
       pttid:4;           //        PTT ID
    u8 unknown_1cf4[8];   // 0x1CF4-0x1CFB
    u8 unk35:3,           // 0x1CFC
       tvol:5;            //        Roger Beep Volume
    u8 unk36:7,           // 0x1CFD
       tail:1;            //        Squelch Tail Eliminate
} settings;

#seekto 0x1D00;
struct {
    u8 unknown_1d00[6];   // 0x1D00
    char idcode[10];      // 0x1D06 ID Code
    u8 unk37:4,           // 0x1D10
       grpcode:4;         //        Group Code
    u8 art;               // 0x1D11 Auto Reset Time
    u8 unknown_1d12[3];   // 0x1D12-0x1D14
    char stuncode[10];    // 0x1D15 ID Code
    u8 unk38:7,           // 0x1D1F
       stuntype:1;        //        Stun Type
} dtmfd;

#seekto 0x1D30;
struct {
  char code[16];          // Autodial Memories
} dtmf_codes[10];

//#seekto 0x1DD0;
struct {
    char bot[16];         // 0x1DD0 Beginning of Transmission
    char eot[16];         // 0x1DE0 End of Transmission
} dtmfe;
"""

CMD_ACK = b"\x06"

TXPOWER_LOW = 0x00
TXPOWER_LOW2 = 0x01
TXPOWER_LOW3 = 0x02
TXPOWER_MID = 0x03
TXPOWER_HIGH = 0x04

DUPLEX_NOSPLIT = 0x00
DUPLEX_POSSPLIT = 0x01
DUPLEX_NEGSPLIT = 0x02

VALID_CHARS = chirp_common.CHARSET_UPPER_NUMERIC + "-/"
DUPLEX = ["", "+", "-"]
TUNING_STEPS = [5., 6.25, 10., 12.5, 15., 20., 25., 30., 50., 100.]


def _enter_programming_mode_download(radio):
    serial = radio.pipe

    _magic = radio._magic

    try:
        serial.write(_magic)
        if radio._echo:
            serial.read(len(_magic))  # Chew the echo
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio")
    elif ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write(b"\x02")
        if radio._echo:
            serial.read(1)  # Chew the echo
        ident = serial.read(8)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    # check if ident is OK
    for fp in radio._fingerprint:
        if ident.startswith(fp):
            break
    else:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    try:
        serial.write(CMD_ACK)
        if radio._echo:
            serial.read(1)  # Chew the echo
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    # check if ident is OK
    for fp in radio._fingerprint:
        if ident.startswith(fp):
            break
    else:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    try:
        serial.write(CMD_ACK)
        serial.read(1)  # Chew the echo
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _enter_programming_mode_upload(radio):
    serial = radio.pipe

    _magic = radio._magic

    try:
        serial.write(_magic)
        if radio._echo:
            serial.read(len(_magic))  # Chew the echo
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioError("No response from radio")
    elif ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        serial.write(b"\x52\x1F\x05\x01")
        if radio._echo:
            serial.read(4)  # Chew the echo
        ident = serial.read(5)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if ident != b"\x57\x1F\x05\x01\xA5":
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    try:
        serial.write(CMD_ACK)
        if radio._echo:
            serial.read(1)  # Chew the echo
        ack = serial.read(1)
    except Exception:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(radio.CMD_EXIT)
        if radio._echo:
            serial.read(7)  # Chew the echo
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', block_addr, block_size)
    expectedresponse = b"W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        if radio._echo:
            serial.read(4)  # Chew the echo
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if radio._echo:
            serial.read(4 + len(data))  # Chew the echo
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except Exception:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _enter_programming_mode_download(radio)

    data = b""

    status = chirp_common.Status()
    status.msg = "Downloading from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    return data


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode_upload(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE):
            status.cur = addr + radio.BLOCK_SIZE
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE)

    _exit_programming_mode(radio)


class RA87StyleRadio(chirp_common.CloneModeRadio):
    """Retevis RA87"""
    VENDOR = "Retevis"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x40
    CMD_EXIT = b"EZ" + b"\xA5" + b"2#E" + b"\xF2"
    NAME_LENGTH = 6

    VALID_BANDS = [(400000000, 480000000)]

    _magic = b"PROGRAM"
    _fingerprint = [b"\xFF\xFF\xFF\xFF\xFF\xA5\x2C\xFF",
                    b"\xFF\xFF\xFF\xFF\xFF\xA5\x26\xFF",
                    ]
    _upper = 99
    _gmrs = True
    _echo = True

    _ranges = [
        (0x0000, 0x2000),
    ]
    _memsize = 0x2000

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_name = True
        rf.has_sub_devices = self.VARIANT == ""
        rf.has_tuning_step = True
        rf.has_rx_dtcs = True
        rf.has_settings = True
        rf.memory_bounds = (0, self._upper)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_characters = VALID_CHARS
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_duplexes = DUPLEX + ["split"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_modes = ["NFM", "FM"]  # 12.5 kHz, 25 kHz.
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_tuning_steps = TUNING_STEPS
        return rf

    def get_sub_devices(self):
        return [RA87RadioLeft(self._mmap), RA87RadioRight(self._mmap)]

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            data = do_download(self)
            self._mmap = memmap.MemoryMapBytes(data)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('General failure')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        finally:
            _exit_programming_mode(self)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('General failure')
            raise errors.RadioError('Failed to upload to radio: %s' % e)
        finally:
            _exit_programming_mode(self)

    def _get_dcs(self, val):
        return int(str(val)[2:-16])

    def _set_dcs(self, val):
        return int(str(val), 16)

    def _memory_obj(self, suffix=""):
        return getattr(self._memobj, "%s_memory%s" % (self._vfo, suffix))

    def get_memory(self, number):
        _mem = self._memory_obj()[number]

        mem = chirp_common.Memory()

        mem.number = number

        if _mem.rxfreq.get_raw() == b"\xFF\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq)

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if int(_mem.txfreq) != 0:  # DUPLEX_ODDSPLIT
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        elif _mem.duplex == DUPLEX_POSSPLIT:
            mem.duplex = '+'
            mem.offset = int(_mem.offset) * 1000
        elif _mem.duplex == DUPLEX_NEGSPLIT:
            mem.duplex = '-'
            mem.offset = int(_mem.offset) * 1000
        elif _mem.duplex == DUPLEX_NOSPLIT:
            mem.duplex = ''
            mem.offset = 0
        else:
            LOG.error('%s: get_mem: unhandled duplex: %02x' %
                      (mem.name, _mem.duplex))

        mem.tuning_step = TUNING_STEPS[_mem.step]

        mem.mode = not _mem.narrow and "FM" or "NFM"

        mem.skip = _mem.skip and "S" or ""

        mem.name = str(_mem.name).strip("\xFF")

        dtcs_pol = ["N", "N"]

        if _mem.rxtone == 0xFFF:
            rxmode = ""
        elif _mem.rxtone == 0x800 and _mem.is_rxdigtone == 0:
            rxmode = ""
        elif _mem.is_rxdigtone == 0:
            # CTCSS
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        else:
            # Digital
            rxmode = "DTCS"
            mem.rx_dtcs = self._get_dcs(_mem.rxtone)
            if _mem.rxdtcs_pol == 1:
                dtcs_pol[1] = "R"

        if _mem.txtone == 0xFFF:
            txmode = ""
        elif _mem.txtone == 0x08 and _mem.is_txdigtone == 0:
            txmode = ""
        elif _mem.is_txdigtone == 0:
            # CTCSS
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        else:
            # Digital
            txmode = "DTCS"
            mem.dtcs = self._get_dcs(_mem.txtone)
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

        _levels = self.POWER_LEVELS
        if _mem.txpower == TXPOWER_HIGH:
            mem.power = _levels[4]
        elif _mem.txpower == TXPOWER_MID:
            mem.power = _levels[3]
        elif _mem.txpower == TXPOWER_LOW3:
            mem.power = _levels[2]
        elif _mem.txpower == TXPOWER_LOW2:
            mem.power = _levels[1]
        elif _mem.txpower == TXPOWER_LOW:
            mem.power = _levels[0]
        else:
            LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                      (mem.name, _mem.txpower))

        mem.extra = RadioSettingGroup("Extra", "extra")
        rs = RadioSettingValueBoolean(_mem.beatshift)
        rset = RadioSetting("beatshift", "Beat Shift", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(_mem.compand)
        rset = RadioSetting("compand", "Compand", rs)
        mem.extra.append(rset)

        options = ['Off', 'Freq 1', 'Freq 2', 'Freq 3',
                   'Freq 4', 'Freq 5', 'Freq 6', 'User']
        rs = RadioSettingValueList(options, current_index=_mem.scramble)
        rset = RadioSetting("scramble", "Scramble", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(_mem.hide)
        rset = RadioSetting("hide", "Hide Channel", rs)
        mem.extra.append(rset)

        rs = RadioSettingValueBoolean(_mem.reverse)
        rset = RadioSetting("reverse", "Reverse", rs)
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memory_obj()[mem.number]

        if mem.empty:
            _mem.set_raw(b"\xFF" * 31 + b"\x80")

            return

        _mem.set_raw(b"\x00" * 25 + b"\xFF" * 6 + b"\x00")

        _mem.rxfreq = mem.freq

        if mem.duplex == 'split':
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == '+':
            _mem.duplex = DUPLEX_POSSPLIT
            _mem.offset = mem.offset / 1000
        elif mem.duplex == '-':
            _mem.duplex = DUPLEX_NEGSPLIT
            _mem.offset = mem.offset / 1000
        elif mem.duplex == '':
            _mem.duplex = DUPLEX_NOSPLIT
        else:
            LOG.error('%s: set_mem: unhandled duplex: %s' %
                      (mem.name, mem.duplex))

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
            _mem.rxdtcs_pol = 0
            _mem.is_rxdigtone = 0
            _mem.rxtone = 0x800
        elif rxmode == "Tone":
            _mem.rxdtcs_pol = 0
            _mem.is_rxdigtone = 0
            _mem.rxtone = int(mem.ctone * 10)
        elif rxmode == "DTCSSQL":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = self._set_dcs(mem.dtcs)
        elif rxmode == "DTCS":
            _mem.rxdtcs_pol = 1 if mem.dtcs_polarity[1] == "R" else 0
            _mem.is_rxdigtone = 1
            _mem.rxtone = self._set_dcs(mem.rx_dtcs)

        if txmode == "":
            _mem.txdtcs_pol = 0
            _mem.is_txdigtone = 0
            _mem.txtone = 0x08
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
            _mem.txtone = self._set_dcs(mem.dtcs)

        # name TAG of the channel
        _mem.name = mem.name.rstrip().ljust(6, "\xFF")

        _levels = self.POWER_LEVELS
        if mem.power is None:
            _mem.txpower = TXPOWER_LOW
        elif mem.power == _levels[0]:
            _mem.txpower = TXPOWER_LOW
        elif mem.power == _levels[1]:
            _mem.txpower = TXPOWER_LOW2
        elif mem.power == _levels[2]:
            _mem.txpower = TXPOWER_LOW3
        elif mem.power == _levels[3]:
            _mem.txpower = TXPOWER_MID
        elif mem.power == _levels[4]:
            _mem.txpower = TXPOWER_HIGH
        else:
            LOG.error('%s: set_mem: unhandled power level: %s' %
                      (mem.name, mem.power))

        _mem.narrow = 'N' in mem.mode
        _mem.skip = mem.skip == "S"
        _mem.step = TUNING_STEPS.index(mem.tuning_step)

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), int(setting.value))

    def get_settings(self):
        _dtmfe = self._memobj.dtmfe
        _dtmfd = self._memobj.dtmfd
        _scramble = self._memobj.scramble
        _settings = self._memobj.settings
        _settings2 = self._memobj.settings2
        basic = RadioSettingGroup("basic", "Basic Settings")
        pfkey = RadioSettingGroup("pfkey", "PF Key Settings")
        scramble = RadioSettingGroup("scramble", "Scramble Settings")
        lcd = RadioSettingGroup("lcd", "LCD Settings")

        dtmf_enc = RadioSettingGroup("dtmfenc", "Encode")
        dtmf_dec = RadioSettingGroup("dtmfdec", "Decode")
        dtmf_autodial = RadioSettingGroup("dtmfautodial", "Auto Dial")

        group_dtmf = RadioSettingGroup("group_dtmf", "DTMF Settings")
        group_dtmf.append(dtmf_enc)
        group_dtmf.append(dtmf_dec)
        group_dtmf.append(dtmf_autodial)

        top = RadioSettings(basic, pfkey, scramble, lcd, group_dtmf)

        # menu 08 - SQL
        options = ["Off"] + ["S%s" % x for x in range(0, 8)]
        rs = RadioSettingValueList(options, current_index=_settings.sql)
        rset = RadioSetting("sql", "S-Meter Squelch Level", rs)
        rset.set_doc("Menu 8 (Off, S1, S2, S3, S4, S5, S6, S7)")
        basic.append(rset)

        # menu 09 - SQH
        options = ["Off", "125", "250", "500"]
        rs = RadioSettingValueList(options, current_index=_settings.sqh)
        rset = RadioSetting("sqh", "Squelch Hang Time [ms]", rs)
        rset.set_doc("Menu 9 (Off, 125, 250, 500)")
        basic.append(rset)

        # menu 11 - RELAY
        rs = RadioSettingValueBoolean(_settings.relay)
        rset = RadioSetting("relay", "Relay", rs)
        rset.set_doc("Menu 11")
        basic.append(rset)

        # menu 12 - SCAN
        options = ["Time Operated (TO)", "Carrier Operated (CO)",
                   "SEarch (SE)"]
        rs = RadioSettingValueList(options, current_index=_settings.scan)
        rset = RadioSetting("scan", "Scan Resume Method", rs)
        rset.set_doc("Menu 12")
        basic.append(rset)

        # menu 14 - ECHO
        options = ["Auto (S/RX)", "Manual (D/RX)"]
        rs = RadioSettingValueList(options, current_index=_settings.echo)
        rset = RadioSetting("echo", "Response Mode", rs)
        rset.set_doc("Menu 14")
        basic.append(rset)

        # menu 16 - MDF
        options = ["Name", "Frequency"]
        rs = RadioSettingValueList(options, current_index=_settings.mdf)
        rset = RadioSetting("mdf", "Memory Display Format", rs)
        rset.set_doc("Menu 16")
        basic.append(rset)

        # menu 17 - APO
        options = ["Off", "30", "60", "90", "120", "180"]
        rs = RadioSettingValueList(options, current_index=_settings.apo)
        rset = RadioSetting("apo", "Automatic Power Off [min]", rs)
        rset.set_doc("Menu 17")
        basic.append(rset)

        # menu 18 - CK
        options = ["CALL", "1750"]
        rs = RadioSettingValueList(options, current_index=_settings.ck)
        rset = RadioSetting("ck", "CALL Key", rs)
        rset.set_doc("Menu 18")
        basic.append(rset)

        # menu 19 - HDL
        rs = RadioSettingValueBoolean(_settings.hdl)
        rset = RadioSetting("hdl", "1750 Hz Tone Hold", rs)
        rset.set_doc("Menu 19")
        basic.append(rset)

        # menu 20 - TOT
        options = ["3", "5", "10"]
        rs = RadioSettingValueList(options, current_index=_settings.tot)
        rset = RadioSetting("tot", "Time-Out Timer [min]", rs)
        rset.set_doc("Menu 20")
        basic.append(rset)

        # menu 21 - BCL
        rs = RadioSettingValueBoolean(_settings.bcl)
        rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
        rset.set_doc("Menu 21")
        basic.append(rset)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in VALID_CHARS:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        # menu 22 - P.ON.MSG
        name = str(_settings2.ponmsg).strip("\xFF")
        rs = RadioSettingValueString(0, 6, _filter(name))
        rs.set_charset(VALID_CHARS)
        rset = RadioSetting("settings2.ponmsg", "Power On Message", rs)
        rset.set_doc("Menu 22")
        basic.append(rset)

        # menu 23 - BP
        rs = RadioSettingValueBoolean(_settings.bp)
        rset = RadioSetting("bp", "Key Beeps", rs)
        rset.set_doc("Menu 23")
        basic.append(rset)

        # menu 24 - BS
        rs = RadioSettingValueBoolean(_settings.bs)
        rset = RadioSetting("bs", "Beat Frequency Offset", rs)
        rset.set_doc("Menu 24")
        basic.append(rset)

        # menu 26 - ENC
        rs = RadioSettingValueBoolean(_settings.enc)
        rset = RadioSetting("enc", "Tuning Control Enable", rs)
        rset.set_doc("Menu 26")
        basic.append(rset)

        # menu 38 - MC.L
        rs = RadioSettingValueBoolean(_settings.mcl)
        rset = RadioSetting("mcl", "Mic Key Lock", rs)
        basic.append(rset)

        # menu 51 - ANI
        rs = RadioSettingValueBoolean(_settings.ani)
        rset = RadioSetting("ani", "ANI", rs)
        basic.append(rset)

        # menu 60 - TEND
        rs = RadioSettingValueBoolean(_settings.tend)
        rset = RadioSetting("tend", "Roger Beep", rs)
        basic.append(rset)

        # menu 61 - TVOL
        rs = RadioSettingValueInteger(1, 25, _settings.tvol + 1)
        rset = RadioSetting("tvol", "Roger Beep Volume", rs)
        basic.append(rset)

        # menu 62 - TAIL
        rs = RadioSettingValueBoolean(_settings.tail)
        rset = RadioSetting("tail", "Squelch Tail Eliminate", rs)
        basic.append(rset)

        # Other
        rs = RadioSettingValueBoolean(_settings2.keyl)
        rset = RadioSetting("settings2.keyl", "Radio Key Lock", rs)
        basic.append(rset)

        name = str(_settings2.lower).strip("\xFF")
        rs = RadioSettingValueString(0, 4, _filter(name))
        rs.set_mutable(False)
        rset = RadioSetting("settings2.lower", "Lower Band Limit", rs)
        basic.append(rset)

        name = str(_settings2.upper).strip("\xFF")
        rs = RadioSettingValueString(0, 4, _filter(name))
        rs.set_mutable(False)
        rset = RadioSetting("settings2.upper", "Upper Band Limit", rs)
        basic.append(rset)

        # PF Key Options
        options = ["MONI", "ENTER", "1750", "VFO", "MR", "CALL", "MHZ", "REV",
                   "SQL", "M-V", "M.IN", "C IN", "MENU", "SHIFT", "LOW",
                   "CONTR", "LOCK", "STEP"]
        # menu 39: - PF 1
        rs = RadioSettingValueList(options, current_index=_settings.pf1)
        rset = RadioSetting("pf1", "PF Key 1", rs)
        pfkey.append(rset)

        # menu 40: - PF 2
        rs = RadioSettingValueList(options, current_index=_settings.pf2)
        rset = RadioSetting("pf2", "PF Key 2", rs)
        pfkey.append(rset)

        # menu 41: - PF 3
        rs = RadioSettingValueList(options, current_index=_settings.pf3)
        rset = RadioSetting("pf3", "PF Key 3", rs)
        pfkey.append(rset)

        # menu 42: - PF 4
        rs = RadioSettingValueList(options, current_index=_settings.pf4)
        rset = RadioSetting("pf4", "PF Key 4", rs)
        pfkey.append(rset)

        # Scramble
        tmpval = int(_scramble.freq1)
        if tmpval > 3800 or tmpval < 2700:
            tmpval = 3000
        rs = RadioSettingValueInteger(2700, 3800, tmpval, 10)
        rset = RadioSetting("scramble.freq1", "Freq 1", rs)
        scramble.append(rset)

        tmpval = int(_scramble.freq2)
        if tmpval > 3800 or tmpval < 2700:
            tmpval = 3100
        rs = RadioSettingValueInteger(2700, 3800, tmpval, 10)
        rset = RadioSetting("scramble.freq2", "Freq 2", rs)
        scramble.append(rset)

        tmpval = int(_scramble.freq3)
        if tmpval > 3800 or tmpval < 2700:
            tmpval = 3200
        rs = RadioSettingValueInteger(2700, 3800, tmpval, 10)
        rset = RadioSetting("scramble.freq3", "Freq 3", rs)
        scramble.append(rset)

        tmpval = int(_scramble.freq4)
        if tmpval > 3800 or tmpval < 2700:
            tmpval = 3300
        rs = RadioSettingValueInteger(2700, 3800, tmpval, 10)
        rset = RadioSetting("scramble.freq4", "Freq 4", rs)
        scramble.append(rset)

        tmpval = int(_scramble.freq5)
        if tmpval > 3800 or tmpval < 2700:
            tmpval = 3400
        rs = RadioSettingValueInteger(2700, 3800, tmpval, 10)
        rset = RadioSetting("scramble.freq5", "Freq 5", rs)
        scramble.append(rset)

        tmpval = int(_scramble.freq6)
        if tmpval > 3800 or tmpval < 2700:
            tmpval = 3450
        rs = RadioSettingValueInteger(2700, 3800, tmpval, 10)
        rset = RadioSetting("scramble.freq6", "Freq 6", rs)
        scramble.append(rset)

        tmpval = int(_scramble.ufreq)
        if tmpval > 3800 or tmpval < 2700:
            tmpval = 3300
        rs = RadioSettingValueInteger(2700, 3800, tmpval, 10)
        rset = RadioSetting("scramble.ufreq", "User Freq", rs)
        scramble.append(rset)

        # LCD Display
        # menu 43 - L.LIG
        options = ["Off", "On", "Auto"]
        rs = RadioSettingValueList(options, current_index=_settings.llig)
        rset = RadioSetting("llig", "LCD Light", rs)
        lcd.append(rset)

        # menu 44 - WF.CLR
        rs = RadioSettingValueInteger(1, 8, _settings.wfclr + 1)
        rset = RadioSetting("wfclr", "Background Color - Standby", rs)
        lcd.append(rset)

        # menu 45 - RX.CLR
        rs = RadioSettingValueInteger(1, 8, _settings.rxclr + 1)
        rset = RadioSetting("rxclr", "Background Color - RX", rs)
        lcd.append(rset)

        # menu 46 - TX.CLR
        rs = RadioSettingValueInteger(1, 8, _settings.txclr + 1)
        rset = RadioSetting("txclr", "Background Color - TX", rs)
        lcd.append(rset)

        # menu 47 - CONTR
        rs = RadioSettingValueInteger(0, 3, _settings.contr)
        rset = RadioSetting("contr", "LCD Contrast", rs)
        lcd.append(rset)

        # menu 48 - K.LIG
        options = ["Off", "On", "Auto"]
        rs = RadioSettingValueList(options, current_index=_settings.klig)
        rset = RadioSetting("klig", "Keypad Light", rs)
        lcd.append(rset)

        # DTMF
        LIST_DTMF_DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7",
                            "8", "9", "A", "B", "C", "D", "*", "#"]
        LIST_DTMF_VALUES = [0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37,
                            0x38, 0x39, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46]
        CHARSET_DTMF_DIGITS = "0123456789AaBbCcDd#*"
        CHARSET_NUMERIC = "0123456789"

        def apply_dmtf_frame(setting, obj, len_obj):
            LOG.debug("Setting DTMF-Code: " + str(setting.value))
            val_string = str(setting.value)
            for i in range(0, len_obj):
                obj[i] = 255
            i = 0
            for current_char in val_string:
                current_char = current_char.upper()
                index = LIST_DTMF_DIGITS.index(current_char)
                obj[i] = LIST_DTMF_VALUES[index]
                i = i + 1

        # DTMF - Encode
        # menu 52 - PTTID
        options = ["Off", "BOT", "EOT", "Both"]
        rs = RadioSettingValueList(options, current_index=_settings.pttid)
        rset = RadioSetting("pttid", "When to send PTT ID", rs)
        dtmf_enc.append(rset)

        tmp = (str(_dtmfe.bot)
               .strip("\xFF")
               .replace('E', '*')
               .replace('F', '#')
               )
        rs = RadioSettingValueString(0, 16, tmp, False, CHARSET_DTMF_DIGITS)
        rset = RadioSetting("dtmfe.bot", "BOT PTT-ID", rs)
        rset.set_apply_callback(apply_dmtf_frame, _dtmfe.bot, 16)
        dtmf_enc.append(rset)

        tmp = (str(_dtmfe.eot)
               .strip("\xFF")
               .replace('E', '*')
               .replace('F', '#')
               )
        rs = RadioSettingValueString(0, 16, tmp, False, CHARSET_DTMF_DIGITS)
        rset = RadioSetting("dtmfe.eot", "EOT PTT-ID", rs)
        rset.set_apply_callback(apply_dmtf_frame, _dtmfe.eot, 16)
        dtmf_enc.append(rset)

        # menu 32 - DT.M
        rs = RadioSettingValueBoolean(_settings.dtm)
        rset = RadioSetting("dtm", "DTMF Sidetone", rs)
        dtmf_enc.append(rset)

        # menu 31 - DT.L
        rs = RadioSettingValueBoolean(_settings.dtl)
        rset = RadioSetting("dtl", "DTMF Key Lock", rs)
        rset.set_doc("Menu 31")
        dtmf_enc.append(rset)

        # menu 29 - DT.H
        rs = RadioSettingValueBoolean(_settings.dth)
        rset = RadioSetting("dth", "DTMF Hold", rs)
        rset.set_doc("Menu 29")
        dtmf_enc.append(rset)

        # menu 30 - PA
        options = ["100", "250", "500", "750", "1000", "1500", "2000"]
        rs = RadioSettingValueList(options, current_index=_settings.pa)
        rset = RadioSetting("pa", "DTMF Pause [ms]", rs)
        rset.set_doc("Menu 30")
        dtmf_enc.append(rset)

        # menu 28 - SPD
        options = ["Fast", "Slow"]
        rs = RadioSettingValueList(options, current_index=_settings.spd)
        rset = RadioSetting("spd", "DTMF Speed", rs)
        rset.set_doc("Menu 28")
        dtmf_enc.append(rset)

        # DTMF - Decode
        tmp = (str(_dtmfd.idcode)
               .strip("\xFF")
               )
        rs = RadioSettingValueString(0, 16, tmp, False, CHARSET_NUMERIC)
        rset = RadioSetting("dtmfd.idcode", "ID Code", rs)
        rset.set_apply_callback(apply_dmtf_frame, _dtmfd.idcode, 10)
        dtmf_dec.append(rset)

        #
        options = ["Off", "A", "B", "C", "D", "*", "#"]
        rs = RadioSettingValueList(options, current_index=_dtmfd.grpcode)
        rset = RadioSetting("dtmfd.grpcode", "Group Code", rs)
        dtmf_dec.append(rset)

        #
        options = ["Off"] + ["%s" % x for x in range(1, 251)]
        rs = RadioSettingValueList(options, current_index=_dtmfd.art)
        rset = RadioSetting("dtmfd.art", "Auto Reset Time[s]", rs)
        dtmf_dec.append(rset)

        #
        rs = RadioSettingValueBoolean(_settings.dani)
        rset = RadioSetting("dani", "ANI", rs)
        dtmf_dec.append(rset)

        tmp = (str(_dtmfd.stuncode)
               .strip("\xFF")
               )
        rs = RadioSettingValueString(0, 16, tmp, False, CHARSET_NUMERIC)
        rset = RadioSetting("dtmfd.stuncode", "Stun Code", rs)
        rset.set_apply_callback(apply_dmtf_frame, _dtmfd.stuncode, 10)
        dtmf_dec.append(rset)

        #
        options = ["TX Inhibit", "TX/RX Inhibit"]
        rs = RadioSettingValueList(options, current_index=_dtmfd.stuntype)
        rset = RadioSetting("dtmfd.stuntype", "Stun Type", rs)
        dtmf_dec.append(rset)

        # DTMF - Autodial Memory
        codes = self._memobj.dtmf_codes
        i = 1
        for dtmfcode in codes:
            tmp = (str(dtmfcode.code)
                   .strip("\xFF")
                   .replace('E', '*')
                   .replace('F', '#')
                   )
            rs = RadioSettingValueString(0, 16, tmp, False,
                                         CHARSET_DTMF_DIGITS)
            rset = RadioSetting("dtmf_code_" + str(i) + "_code",
                                "Code " + str(i-1), rs)
            rset.set_apply_callback(apply_dmtf_frame, dtmfcode.code, 16)
            dtmf_autodial.append(rset)
            i = i + 1

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "line":
                        setattr(obj, setting, str(element.value).rstrip(
                            " ").ljust(6, "\xFF"))
                    elif setting == "bot":
                        setattr(obj, setting, str(element.value).rstrip(
                            " ").ljust(16, "\xFF"))
                    elif setting == "eot":
                        setattr(obj, setting, str(element.value).rstrip(
                            " ").ljust(16, "\xFF"))
                    elif setting == "wfclr":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "rxclr":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "txclr":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "tvol":
                        setattr(obj, setting, int(element.value) - 1)
                    else:
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RA87Radio(RA87StyleRadio):
    """Retevis RA87"""
    MODEL = "RA87"

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=5.00),
                    chirp_common.PowerLevel("Low2", watts=10.00),
                    chirp_common.PowerLevel("Low3", watts=15.00),
                    chirp_common.PowerLevel("Mid", watts=20.00),
                    chirp_common.PowerLevel("High", watts=40.00)]


class RA87RadioLeft(RA87Radio):
    """Retevis RA87 Left VFO subdevice"""
    VARIANT = "Left"
    _vfo = "left"


class RA87RadioRight(RA87Radio):
    """Retevis RA87 Right VFO subdevice"""
    VARIANT = "Right"
    _vfo = "right"
