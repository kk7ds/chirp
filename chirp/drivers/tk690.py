# TK-690 support and improvements added in 2024 by Patrick Leiser,
# based on the work of:
# Copyright 2016-2024 Pavel Milanes CO7WT, <pavelmc@gmail.com>
#
# And with the help of Tom Hayward, who gently provided me with a driver he
# started and never finished for this radio.
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

import logging
import struct

from chirp import chirp_common, directory, memmap, errors, util, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings, \
    RadioSettingValueBoolean, RadioSettingValueList, RadioSettingValueString, \
    RadioSettingValueMap, RadioSettingValueInteger

LOG = logging.getLogger(__name__)

# Note: the exported .dat files from the official KPG-44D software have a
# metadata preable for the first 64 bytes, then contain the desired image
# to export to the radio itself (which is what chirp handles).

# IMPORTANT MEM DATA #########################################
# This radios have a odd mem structure, it seems like you have to
# manage 3 memory sectors that we concatenate on just one big
# memmap, as follow
#
# Low memory (Main CPU)
#    0x0000 to 0x4000
# Mid memory (Unknown)
#    0x4000 to 0x4090
# High memory (Head)
#    0x4090 to 0x6090
###############################################################

MEM_FORMAT = """

//# seekto 0x0000;
struct {
    u8 unknown[16];
    u8 ch_name_length;
    u8 grp_name_length;
} settings;

#seekto 0x0300;
struct {
    u8 grp_up;        // functions: 0x0 through 0x2 = Aux A through C
    u8 grp_down;      //          0x3 through 0x7 = Ch 1 through 5 direct,
    u8 monitor;       //          0x8 = Ch down, 0x9 = Ch up, 0xA = ch name,
    u8 scan;          //          0xB = Ch recall, 0xC = Del/Add, 0xD = dimmer,
    u8 PF1;           //          0xE = Emergency Call, 0xF = Grp down,
    u8 PF2;           //          0x10 = Grp up, 0x11 = HC1 (fixed),
    u8 PF3;           //          0x12 = HC2 (toggle), 0x13 = Horn Alert
    u8 PF4;           //          0x16 = Monitor, 0x17 = Operator Sel tone
    u8 PF5;           //          0x19 = Public Address, 0x1A = Scan,
    u8 PF6;           //          0x1C = Speaker int/ext, 0x1D = Squelch,
    u8 PF7;           //          0x1E= Talk Around, 0xFF = no function
    u8 PF8;
    u8 PF9;
    u8 unknown1;             // 0x10 when full head used
    u8 unknown2;             // 0x0F when full head used
    u8 unknown3[12];         //all 0xFF
    u8 knob_control;            //00 = ch up/down, 01 = grp up/down
    u8 headUnitType;            //0x00 = full, 0xFF = basic
} button_assignments;

#seekto 0x0400;
struct {
    u8 tot;                     // * 10 seconds, 30 sec increments
    u8 tot_pre_alert;           // seconds, off - 10, default 5
    u8 tot_rekey_time;          // seconds, off - 60, default off
    u8 tot_reset_time;          // seconds, off - 15, default off
    u8 unknown[4];
} group_settings[160];

#seekto 0x1480;
struct {
    u8 index;          // the index in the group_belong where this group start
    u8 length;         // how many channels are in this group
} group_limits[160];

#seekto 0x1600;
struct {
    u8 number;         // CH number relative to the group, 1-160
    u8 index;          // index relative to the memory space memory[index]
} group_belong[160];

#seekto 0x1800;
struct {
  lbcd rxfreq[4];       // 00-03
  lbcd txfreq[4];       // 04-07
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:1,
     power:1,            // power 0 = high, 1 = low
     beatshift:1,        // beat shift, 1 = on
     bcl:1,              // busy channel lockout, 1 = on
     pttid:1,            // ptt id, 1 = on
     signal:3;           //off=0, 1=DTMF, 2,3,4 = "2-Tone 1,2,3"
  u8 unknown1:2,
     txdisable:1,        // 1=RX only, 0=RX/TX
     unknown7:1,
     add:1,              // scan add, 1 = add
     wide:1,             // Wide = 1, narrow = 0
     unknown2:1,
     unknown4:1;
  u8 unknown5;
  u8 unknown6:6,
     compander:1,     // 0 = compander active, only applicable on narrow band
     valid:1;        // 0 = valid entry, enabled; 1=invalid
} memory[160];

#seekto 0x3DF0;
char poweron_msg[14];

#seekto 0x3E80;
struct {
  char line1[32];
  char line2[32];
} embeddedMessage;

#seekto 0x3ED0;
struct {
  u8 unknown10[10];
  char soft[6];
  struct {
    char variant[5];
    u8 unknown1;
    u8 memorysource;  //0x50 if exported from KPG44D, 0x00 if cloned from radio
    u8 unknown2:5,
       headtype:1,    //0 = basic head, 4 = full head
       unknown3:2;
    u8 unknown4;
    u8 unknown5;
  } rid;
  u8 unknown11[6];
  u8 unknown12[11];
  char soft_ver[5];
} properties;

#seekto 0x40A0;
struct {
  char name[16];
} grp_names[160];

struct {
  char name[16];
} chs_names[160];

"""

MEM_SIZE = 0x60A0  # 24,736 bytes
DAT_FILE_SIZE = 0x60E0
ACK_CMD = b'\x06'
RX_BLOCK_SIZE_L = 128
MEM_LR = range(0x0380, 0x0400)
RX_BLOCK_SIZE_M = 16
MEM_MR = range(1, 11)
RX_BLOCK_SIZE_H = 32
MEM_HR = range(0, 0x2000, RX_BLOCK_SIZE_H)
EMPTY_BLOCK = b"\xFF" * 256
EMPTY_L = b"\xFF" * RX_BLOCK_SIZE_L
EMPTY_H = b"\xFF" * RX_BLOCK_SIZE_H
VALID_CHARS = chirp_common.CHARSET_UPPER_NUMERIC + "()/\\*@-+,.#_"
VALID_CHARS_UNCASED = VALID_CHARS+VALID_CHARS.lower()
SKIP_VALUES = ["S", ""]
TONES = chirp_common.TONES
DTCS_CODES = chirp_common.DTCS_CODES
OPTSIG_LIST = ["None", "DTMF", "2-Tone 1", "2-Tone 2", "2-Tone 3"]
HEAD_TYPES = ["Basic", "Full"]

BUTTON_FUNCTION_LIST = [
            ('Aux A', 0), ('Aux B', 1), ('Aux C', 2),
            ('Ch 1 direct', 3), ('Ch 2 direct', 4), ('Ch 3 direct', 5),
            ('Ch 4 direct', 6), ('Ch 5 direct', 7), ('Ch down', 8),
            ('Ch up', 9), ('Ch name', 10), ('Ch recall', 11), ('Del/Add', 12),
            ('Dimmer', 13), ('Emergency Call', 14), ('Grp down', 15),
            ('Grp up', 16), ('HC1 (fixed)', 17), ('HC2 (toggle)', 18),
            ('Horn Alert', 19), ('Monitor', 22), ('Operator Sel tone', 23),
            ('Public Address', 25), ('Scan', 26), ('Speaker int/ext', 28),
            ('Squelch', 29), ('Talk Around', 30), ('no function', 255)]

ASSIGNABLE_BUTTONS = ["grp_up", "grp_down", "monitor", "scan", "PF1", "PF2",
                      "PF3", "PF4", "PF5", "PF6", "PF7", "PF8", "PF9"]
FULL_HEAD_ONLY_BUTTONS = ["monitor", "scan", "PF6", "PF7", "PF8", "PF9"]


def _close_radio(radio):
    """Get the radio out of program mode"""
    try:
        radio.pipe.write(b"E")
    except Exception:
        LOG.debug("Failed to close radio, serial error")
        raise errors.RadioError("Serial Connection Error while closing radio")


def _checksum(data):
    """the radio block checksum algorithm"""
    cs = 0
    for byte in data:
        cs += byte
    return cs % 256


def _make_framel(cmd, addr):
    """Pack the info in the format it likes"""
    # x52 x0F (x0380-x0400)
    return struct.pack(">BBH", ord(cmd), 0x0F, addr)


def _make_framem(cmd, addr):
    """Pack the info in the format it likes"""
    # x54 x0F (x00-x0A)
    return struct.pack(">BBB", ord(cmd), 0x0F, addr)


def _make_frameh(cmd, addr):
    """Pack the info in the format it likes"""
    # x53 x8F (x0000-x2000) x20
    return struct.pack(">BBHB", ord(cmd), 0x8F, addr, RX_BLOCK_SIZE_H)


def _handshake(radio, msg="", full=True):
    """Make a full handshake"""
    if full is True:
        radio.pipe.write(ACK_CMD)

    ack = radio.pipe.read(1)
    if ack != ACK_CMD:
        mesg = "Handshake failed, got ack: '0x%02x': %s" % (ord(ack), msg)
        LOG.debug(mesg)
        raise errors.RadioError("Radio failed to acknowledge our command")


def _recvl(radio):
    """Receive low data block from the radio, 130 or 2 bytes"""
    rxdata = radio.pipe.read(2)
    if rxdata == b"\x5A\xFF":
        # when the RX block has 2 bytes and the paylod+CS is \x5A\xFF
        # then the block is all \xFF
        _handshake(radio, "short block")
        return False
    rxdata += radio.pipe.read(RX_BLOCK_SIZE_L)
    if len(rxdata) == RX_BLOCK_SIZE_L + 2 and rxdata[0] == b"W"[0]:
        # Data block is W + Data(128) + CS
        rcs = rxdata[-1]
        data = rxdata[1:-1]
        ccs = _checksum(data)

        if rcs != ccs:
            msg = "Block Checksum Error! real %02x, calculated %02x" % \
                  (rcs, ccs)
            LOG.error(msg)
            _handshake(radio)
            raise errors.RadioError("Error communicating with radio")

        _handshake(radio, "After checksum in Low Mem")
        return data
    else:
        raise errors.RadioError("Unexpected communication from radio")


def _recvh(radio):
    """Receive high data from the radio, 35 or 4 bytes"""
    rxdata = radio.pipe.read(4)
    # There are two valid options, the first byte is the content
    if (len(rxdata) == 4 and
            rxdata[0] == b"\x5B"[0] and
            rxdata[3] == b"\xFF"[0]):
        # 4 bytes, x5B = empty; payload = xFF (block is all xFF)
        _handshake(radio, "Short block in High Mem")
        return False
    rxdata += radio.pipe.read(RX_BLOCK_SIZE_H - 1)
    if len(rxdata) == RX_BLOCK_SIZE_H + 3 and rxdata[0] == b"\x58"[0]:
        # 35 bytes, x58 + address(2) + data(32), no checksum
        data = rxdata[3:]
        _handshake(radio, "After data in High Mem")
        return data
    else:
        raise errors.RadioError("Unexpected communication from radio")


def _open_radio(radio):
    """Open the radio into program mode and check if it's the correct model"""
    radio.pipe.baudrate = 9600
    radio.pipe.timeout = 1.0

    LOG.debug("Starting program mode.")
    try:
        radio.pipe.write(b"PROGRAM")
    except Exception:
        raise errors.RadioError("Serial Connection Error")

    ack = radio.pipe.read(10)
    if ack == ACK_CMD:
        pass
    elif ack.endswith(b'\xb5\x15\xc5m\xf5\x95\x01') or ack == b'':
        raise errors.RadioError("No response response from radio,"
                                " Is it connected and powered on?")
    else:
        raise errors.RadioError("Radio didn't acknowledge program mode.")

    LOG.debug("Radio entered Program mode.")

    radio.pipe.write(b"\x02\x0F")
    rid = radio.pipe.read(10)

    if not rid.startswith(radio.TYPE):
        LOG.debug("Incorrect model ID:")
        LOG.debug(util.hexprint(rid))
        LOG.debug("expected %s" % radio.TYPE)
        raise errors.RadioError("Radio Model Incorrect")

    LOG.debug("Full radio identity string is:\n%s" % util.hexprint(rid))

    _handshake(radio)


def do_download(radio):
    """ The download function """
    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE
    status.msg = ""
    radio.status_fn(status)

    _open_radio(radio)

    data = b""
    memory_index = 0

    for addr in MEM_LR:
        radio.pipe.write(_make_framel(b"R", addr))
        d = _recvl(radio)
        # if empty block, return false = full of xFF
        if d is False:
            d = EMPTY_L

        data += d

        memory_index += RX_BLOCK_SIZE_L
        status.cur = memory_index
        status.msg = "Cloning from Main MCU (Low mem)..."
        radio.status_fn(status)

    for addr in MEM_MR:
        radio.pipe.write(_make_framem(b"T", addr))
        d = radio.pipe.read(17)

        if len(d) != 17:
            raise errors.RadioError(
                "Problem receiving short block %d on mid mem" % addr)

        data += d[1:]
        _handshake(radio, "Middle mem ack error")

        memory_index += RX_BLOCK_SIZE_M
        status.cur = memory_index
        status.msg = "Cloning from 'unknown' (mid mem)..."
        radio.status_fn(status)

    for addr in MEM_HR:
        radio.pipe.write(_make_frameh(b"S", addr))
        d = _recvh(radio)
        # if empty block, return false = full of xFF
        if d is False:
            d = EMPTY_H

        data += d

        memory_index += RX_BLOCK_SIZE_H
        status.cur = memory_index
        status.msg = "Cloning from Head (High mem)..."
        radio.status_fn(status)

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    """ The upload function """
    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE
    status.msg = "Getting the radio into program mode."
    radio.status_fn(status)
    _open_radio(radio)

    memory_index = 0
    img = radio.get_mmap()

    for addr in MEM_LR:
        # this is the data to write
        data = img[memory_index:memory_index + RX_BLOCK_SIZE_L]
        # sdata is the full packet to send

        # flag
        short = False

        # building the data to send
        if data == EMPTY_L:
            # empty block
            sdata = _make_framel(b"Z", addr) + b"\xFF"
            short = True
        else:
            # normal
            cs = _checksum(data)
            sdata = _make_framel(b"W", addr) + data + bytes([cs])

        radio.pipe.write(sdata)

        msg = "Bad ACK on low block %04x" % addr
        _handshake(radio, msg, False)

        memory_index += RX_BLOCK_SIZE_L
        status.cur = memory_index
        status.msg = "Cloning to Main MCU (Low mem)..."
        radio.status_fn(status)

    for addr in MEM_MR:
        data = img[memory_index:memory_index + RX_BLOCK_SIZE_M]
        sdata = _make_framem(b"Y", addr) + b"\x00" + data

        radio.pipe.write(sdata)

        msg = "Bad ACK on mid block %04x" % addr
        _handshake(radio, msg, not short)

        memory_index += RX_BLOCK_SIZE_M
        status.cur = memory_index
        status.msg = "Cloning from middle mem..."
        radio.status_fn(status)

    for addr in MEM_HR:
        data = img[memory_index:memory_index + RX_BLOCK_SIZE_H]
        # sdata is the full packet to send

        # building the data to send
        if data == EMPTY_H:
            # empty block
            sdata = _make_frameh(b"[", addr) + b"\xFF"
        else:
            # normal
            sdata = _make_frameh(b"X", addr) + data

        radio.pipe.write(sdata)

        msg = "Bad ACK on low block %04x" % addr
        _handshake(radio, msg, False)

        memory_index += RX_BLOCK_SIZE_H
        status.cur = memory_index
        status.msg = "Cloning to Head MCU (high mem)..."
        radio.status_fn(status)


def _get_rid(data, index=0x03EE0):
    """Get the radio ID string from a mem string"""
    return data[index:index+6]


def _filter_settings_string(name):
    filtered = ""
    for char in str(name).upper():
        if char in VALID_CHARS:
            filtered += char
        else:
            filtered += " "
    return filtered


class Kenwoodx90BankModel(chirp_common.BankModel):
    """Testing the bank model on kenwood"""
    channelAlwaysHasBank = True

    def get_num_mappings(self):
        return self._radio._num_banks

    def get_mappings(self):
        banks = []
        for i in range(0, self._radio._num_banks):
            bindex = i + 1
            gname = self._radio.get_group_name(i)
            bank = self._radio._bclass(self, bindex, gname)
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_mapping(self, memory, bank):
        self._radio._set_bank(memory.number, bank.index)

    def remove_memory_from_mapping(self, memory, bank):
        if self._radio._get_bank(memory.number) != bank.index:
            raise Exception("Memory %i not in bank %s. Cannot remove." %
                            (memory.number, bank))

        # We can't "Remove" it for good, the kenwood paradigm doesn't allow it
        # instead we move it to bank 0
        self._radio._set_bank(memory.number, 0)

    def get_mapping_memories(self, bank):
        memories = []
        for i in range(0, self._radio._upper):
            if self._radio._get_bank(i) == bank.index:
                memories.append(self._radio.get_memory(i))
        return memories

    def get_memory_mappings(self, memory):
        index = self._radio._get_bank(memory.number)
        if index is None:
            return []
        return [self.get_mappings()[index]]


class MemBank(chirp_common.Bank):
    """A bank model for kenwood"""
    # Integral index of the bank, not to be confused with per-memory
    # bank indexes
    index = 0

    def get_name(self):
        return self._model._radio.get_group_name(self.index)

    def set_name(self, name):
        self._name = self._model._radio.set_group_name(self.index, name)


class Kenwoodx90(chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio):
    """Kenwood TK-790 radio base class"""
    VENDOR = "Kenwood"
    BAUD_RATE = 9600
    VARIANT = ""
    MODEL = ""
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=45),
                    chirp_common.PowerLevel("Low", watts=5)]
    MODES = ["NFM", "FM"]  # 12.5 / 25 Khz
    _name_chars = 8
    _group_name_chars = 8

    _memsize = MEM_SIZE
    _range = [136000000, 162000000]
    _upper = 160
    _banks = None
    _num_banks = 160
    _bclass = MemBank
    _kind = ""
    _head_type = 0
    FORMATS = [directory.register_format('Kenwood KPG-44D', '*.dat')]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            'This driver is experimental: Use at your own risk! '
        rp.pre_download = _(
            "Follow these instructions to download your radio:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio (unlock it if password protected)\n"
            "4 - Click OK to start\n")
        rp.pre_upload = _(
            "Follow these instructions to upload your radio:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio (unlock it if password protected)\n"
            "4 - Click OK to start\n")
        return rp

    def get_features(self):
        """Return information about this radio's features"""
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = True
        rf.has_tuning_step = False
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = self.MODES
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = VALID_CHARS
        rf.valid_skips = SKIP_VALUES
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_bands = [self._range]
        rf.valid_name_length = self._name_chars
        rf.memory_bounds = (1, self._upper)
        return rf

    def _fill(self, offset, data):
        """Fill an specified area of the memmap with the passed data"""
        for addr in range(0, len(data)):
            self._mmap[offset + addr] = data[addr]

    def _set_variant(self):
        """Select and set the correct variables for the class according
        to the identified variant of the radio, and other runtime data"""
        rid = _get_rid(self.get_mmap())
        self._banks = dict()
        try:
            self._upper, low, high, self._kind = self.VARIANTS[rid]
            self._range = [low * 1000000, high * 1000000]

        except KeyError:
            LOG.debug("Wrong Kenwood radio, ID or unknown variant")
            LOG.debug(util.hexprint(rid))
            raise errors.RadioError(
                "Wrong Kenwood radio, ID or unknown variant, see LOG output.")

        self._name_chars = int(self._memobj.settings.ch_name_length)
        self._group_name_chars = int(self._memobj.settings.grp_name_length)
        self._head_type = self._memobj.properties.rid.headtype.get_value()

    def sync_in(self):
        """Do a download of the radio eeprom"""
        try:
            self._mmap = do_download(self)
        finally:
            _close_radio(self)
        self.process_mmap()
        self._dat_header_mmap = None

    def sync_out(self):
        """Do an upload to the radio eeprom"""
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        finally:
            _close_radio(self)

    def _get_bank_struct(self):
        """Parse the bank data in the mem into the self.bank variable"""
        gl = self._memobj.group_limits
        gb = self._memobj.group_belong
        bank_count = 0

        for bg in gl:
            # check for empty banks
            if bg.index == 255 and bg.length == 255:
                self._banks[bank_count] = list()
                bank_count += 1
                continue

            for i in range(0, bg.length):
                position = bg.index + i
                index = int(gb[position].index)

                try:
                    self._banks[bank_count].append(index)
                except KeyError:
                    self._banks[bank_count] = list()
                    self._banks[bank_count].append(index)

            bank_count += 1

    def process_mmap(self):
        """Process the memory object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

        self._set_variant()

        self._get_bank_struct()

    def load_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, "rb") as f:
                self._dat_header_mmap = memmap.MemoryMapBytes(f.read(0x40))
                self._mmap = memmap.MemoryMapBytes(f.read())
            self.process_mmap()
        else:
            self._dat_header_mmap = None
            chirp_common.CloneModeRadio.load_mmap(self, filename)

    def save_mmap(self, filename):
        if filename.lower().endswith('.dat'):
            with open(filename, 'wb') as f:
                datHeader = self._prep_dat_header()
                f.write(datHeader.get_packed())
                f.write(self._mmap.get_packed())
        else:
            chirp_common.CloneModeRadio.save_mmap(self, filename)

    def _prep_dat_header(self):
        # if we changed head type, the RID changed too
        rid = self._mmap.get(0x3EE0, 10)
        # if dat header imported with file, use it
        if self._dat_header_mmap is not None:
            self._dat_header_mmap.set(0x0F, rid)
            return self._dat_header_mmap
        # otherwise build our own header
        dat_header_map = memmap.MemoryMapBytes(bytes([255]*0x40))
        softwareName = self._mmap.get(0x3EDA, 6)
        softwareVer = self._mmap.get(0x3EFB, 5)
        dat_header_map.set(0x00, softwareName)
        dat_header_map.set(0x0A, softwareVer)
        dat_header_map.set(0x0F, rid)
        return dat_header_map

    def get_raw_memory(self, number):
        """Return a raw representation of the memory object, which
        is very helpful for development"""
        return repr(self._memobj.memory[number])

    def _decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        val = int(val)
        if val == 65535:
            return '', None, None
        elif val >= 0x2800:
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return 'DTCS', code, pol
        else:
            a = val / 10.0
            return 'Tone', a, None

    def _encode_tone(self, memval, mode, value, pol):
        """Parse the tone data to encode from UI to mem"""
        if mode == '':
            memval.set_raw(b"\xff\xff")
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            val = int("%i" % value, 8) + 0x2800
            if pol == "R":
                val += 0xA000
            memval.set_value(val)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number - 1]

        _chs_names = self._memobj.chs_names[number-1]

        mem = chirp_common.Memory()

        # prevent error when auto-populating new memory (defaults to FM)
        if self.MODEL == "TK-690":
            mem.mode = "NFM"

        mem.number = number

        if _mem.get_raw()[0] == 0xFF:
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        # tx freq can be blank
        if _mem.get_raw()[4] == 0xFF:
            mem.offset = 0
            mem.duplex = "off"
        else:
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset < 0:
                mem.offset = abs(offset)
                mem.duplex = "-"
            elif offset > 0:
                mem.offset = offset
                mem.duplex = "+"
            else:
                mem.offset = 0

        mem.name = str(_chs_names.name).rstrip(" ")[:self._name_chars + 1]

        mem.power = self.POWER_LEVELS[int(_mem.power)]

        if self.MODEL == "TK-690" and int(_mem.wide) == 1:
            LOG.debug("Invalid bandwidth mode entry found for TK-690. Fixing")
            _mem.wide = 0
        mem.mode = self.MODES[int(_mem.wide)]

        mem.skip = SKIP_VALUES[int(_mem.add)]

        rxtone = txtone = None
        txtone = self._decode_tone(_mem.txtone)
        rxtone = self._decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.extra = RadioSettingGroup("extra", "Extra")

        bcl = RadioSetting("bcl", "Busy channel lockout",
                           RadioSettingValueBoolean(bool(_mem.bcl)))
        mem.extra.append(bcl)

        pttid = RadioSetting("pttid", "PTT ID",
                             RadioSettingValueBoolean(bool(_mem.pttid)))
        mem.extra.append(pttid)

        beat = RadioSetting("beatshift", "Beat Shift",
                            RadioSettingValueBoolean(bool(_mem.beatshift)))
        mem.extra.append(beat)

        optsig = RadioSetting("signal", "Optional Signalling",
                              RadioSettingValueList(
                                OPTSIG_LIST, current_index=_mem.signal))
        mem.extra.append(optsig)

        # only TK-790 and TK890 support compander, and only in narrow mode
        if self.MODEL != "TK-690":
            companderDisabled = _mem.wide or _mem.compander
            compander = RadioSetting("compander", "compander",
                                     RadioSettingValueBoolean(
                                         bool(not companderDisabled)))
            mem.extra.append(compander)

        return mem

    def set_memory(self, mem):
        """Set the memory data in the eeprom img from the UI"""
        _mem = self._memobj.memory[mem.number - 1]
        _ch_name = self._memobj.chs_names[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b"\xFF" * 16)

            for byte in _ch_name.name:
                byte.set_raw(b"\xFF")

            self._del_channel_from_bank(mem.number)

            return

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "off":
            for byte in _mem.txfreq:
                byte.set_raw(b"\xFF")
                _mem.txdisable = 1
        else:
            _mem.txfreq = mem.freq / 10
            _mem.txdisable = 0

        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.txtone, txmode, txtone, txpol)
        self._encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        _ch_name.name = str(mem.name).ljust(16, " ")

        if mem.power is None:
            _mem.power = 0
        else:
            self.POWER_LEVELS.index(mem.power)

        _mem.wide = self.MODES.index(mem.mode)

        _mem.add = SKIP_VALUES.index(mem.skip)

        # setting required but unknown value
        _mem.valid.set_raw(b'\x00')

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                if setting.get_name() == "compander":
                    # if width is not Narrow, disable compander
                    if _mem.wide:
                        _mem.compander = True

                    else:
                        _mem.compander = bool(not setting.value)
                else:
                    setattr(_mem, setting.get_name(), setting.value)
        else:
            msg = "Channel #%d has no extra data, loading defaults" % \
                  int(mem.number - 1)
            LOG.info(msg)
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.beatshift = 0
            _mem.compander = 1
            # unknowns
            _mem.signal = 0
            _mem.unknown1 = 0

        # If channel doesn't have any bank assigned, default to bank zero
        b = self._get_bank(mem.number)
        if b is None:
            self._set_bank(mem.number, 0)

        return mem

    @classmethod
    def match_model(cls, filedata, filename):

        # .dat file has constant size and specifies model type near start
        return (filename.lower().endswith('.dat')) and \
           (len(filedata) == DAT_FILE_SIZE) and \
           (_get_rid(filedata, 0x000F) in cls.VARIANTS)

    def get_bank_model(self):
        """Pass the bank model to the UI part"""
        return Kenwoodx90BankModel(self)

    def _get_bank(self, loc):
        """Get the bank data for a specific channel"""
        for k in self._banks:
            if (loc - 1) in self._banks[k]:
                LOG.info("Channel %d is in bank %d" % (loc, k))
                return k
        return None

    def _set_bank(self, loc, bank=0):
        """Set the bank data for a specific channel"""
        # no need to change bank if already set correctly
        b = self._get_bank(loc)
        if b == bank:
            return

        # if another bank already assigned, delete from old location
        if b is not None:
            self._del_channel_from_bank(loc, b)

        self._banks[bank].append(loc - 1)

        self._update_bank_memmap()

    def _del_channel_from_bank(self, loc, bank=None):
        """Remove a channel from a bank, if no bank is specified we find
        where it is"""

        # if we don't know what bank channel is in,
        if bank is None:
            bank = self._get_bank(loc)

        # in case memory entry isn't saved to any bank, no need to delete:
        if bank is not None:
            self._banks[bank].pop(self._banks[bank].index(loc - 1))

        self._update_bank_memmap()

    def _update_bank_memmap(self):
        """This function is called whatever a change is made to a channel
        or a bank, to update the memmap with the changes that was made"""

        bl = b""
        bb = b""

        # group_belong index
        gbi = 0
        # sort the banks for consistient memory entries
        self._banks = dict(sorted(self._banks.items()))
        for bank in self._banks:
            # check for empty banks
            if len(self._banks[bank]) == 0:
                bl += b"\xff\xff"
                continue

            # channel index inside the bank, starting at 1
            # aka channel group index
            cgi = 1
            for channel in range(0, len(self._banks[bank])):
                # update bb
                bb += bytes([cgi, self._banks[bank][channel]])
                # set the group limits for this group
                if cgi == 1:
                    bl += bytes([gbi, len(self._banks[bank])])

                gbi += 1
                cgi += 1

        # fill the gaps before writing
        bb += b"\xff" * 2 * int(self._num_banks - len(bb) / 2)
        bl += b"\xff" * 2 * int(self._num_banks - len(bl) / 2)

        self._fill(0x1480, bl)
        self._fill(0x1600, bb)

    def get_group_name(self, index):
        if self._memobj.grp_names[index].name.get_raw()[0] == (0xFF):
            return ""
        return self._memobj.grp_names[index].name.get_raw()\
            .decode("ascii")[0:self._group_name_chars]

    def set_group_name(self, index, name):
        name = name.upper()
        formatted_name = "".join([x for x in name[:self._group_name_chars]
                                  if x in VALID_CHARS]).ljust(16)[:16]
        self._memobj.grp_names[index].name = formatted_name
        return formatted_name[:self._group_name_chars]

    def get_max_display_length(self):
        max_length = 8
        if self._head_type:  # if full head
            max_length = 14
        return max_length

    def validate_name_lengths(self, new_length):
        max_length = self.get_max_display_length()
        if new_length > max_length:
            return max_length
        return new_length

    def apply_ch_name_length(self, new_length):
        new_length = self.validate_name_lengths(new_length)
        max_length = self.get_max_display_length()
        self._name_chars = new_length
        self._group_name_chars = max_length - new_length
        self._memobj.settings.ch_name_length = new_length
        self._memobj.settings.grp_name_length = max_length - new_length

    def get_settings(self):

        """Translate the MEM_FORMAT structs into the UI"""
        basic_settings = RadioSettingGroup("basic_settings",
                                           "Basic Settings")
        button_assignments = RadioSettingGroup("button_assignments",
                                               "Configurable Button Functions")
        group = RadioSettings(basic_settings, button_assignments)

        # Basic Settings:
        rs = RadioSetting("head_type",
                          "Type of control-head:",
                          RadioSettingValueList(
                              HEAD_TYPES,
                              current_index=self._memobj.
                              properties.rid.headtype))
        rs.set_volatile(True)
        basic_settings.append(rs)

        ch_len_setting = RadioSettingValueInteger(
            0, 14, self._memobj.settings.ch_name_length)

        rs = RadioSetting("ch_name_length", "Channel Name Length",
                          ch_len_setting)
        rs.set_volatile(True)
        basic_settings.append(rs)

        grp_len_setting = RadioSettingValueInteger(
            0, 14, self._memobj.settings.grp_name_length)
        grp_len_setting.set_mutable(False)

        rs = RadioSetting("grp_name_length", "Group Name Length",
                          grp_len_setting)
        basic_settings.append(rs)

        rs = RadioSetting("poweron_msg", "Power-On Message",
                          RadioSettingValueString(
                            0, 14, _filter_settings_string(
                                self._memobj.poweron_msg),
                            charset=VALID_CHARS_UNCASED))
        basic_settings.append(rs)

        # Button Function Configuration:
        for buttonName in ASSIGNABLE_BUTTONS:
            _fullHeadWarning = ""

            button_func_setting = RadioSettingValueMap(
                    BUTTON_FUNCTION_LIST,
                    self._memobj.button_assignments[buttonName])
            # disable configuring full_head buttons if basic head equipped
            if buttonName in FULL_HEAD_ONLY_BUTTONS and self._head_type == 0:
                _fullHeadWarning = "  (Unavailable on basic control head)"
                button_func_setting.set_mutable(False)

            rs = RadioSetting(
              buttonName,
              "Configured function for "+buttonName+" button"+_fullHeadWarning,
              button_func_setting)
            button_assignments.append(rs)
        return group

    def set_settings(self, settings):
        for group in settings:
            for button in group:
                groupKey = group.get_name()
                settingKey = button.get_name()
                if groupKey == "button_assignments":
                    self._memobj[groupKey][settingKey] = \
                        [value for (key, value) in BUTTON_FUNCTION_LIST
                            if key == button.value.get_value()][0]
                elif groupKey == "basic_settings":
                    if settingKey == "head_type":
                        self._memobj.properties.rid.headtype = \
                            int(button.value)
                        self._head_type = int(button.value)
                    elif settingKey == "ch_name_length":
                        self.apply_ch_name_length(int(button.value))
                    elif settingKey == "poweron_msg":
                        self._memobj.poweron_msg = _filter_settings_string(
                            button.value.get_value())


@directory.register
class TK690Radio(Kenwoodx90):
    """Kenwood TK-690 """
    MODEL = "TK-690"
    TYPE = b"M0690"
    MODES = ["NFM"]
    VARIANTS = {
        b"M0690\x01": (160, 28, 37, "K"),  # see note below
        b"M0690\x02": (160, 35, 43, "K2"),
        b"M0690\x03": (160, 136, 156, "K3")
    }


@directory.register
class TK790Radio(Kenwoodx90):
    """Kenwood TK-790 K/K2"""
    MODEL = "TK-790"
    TYPE = b"M0790"
    VARIANTS = {
        b"M0790\x04": (160, 144, 174, "K"),  # see note below
        b"M0790\x05": (160, 136, 156, "K2")
    }


@directory.register
class TK890Radio(Kenwoodx90):
    """Kenwood TK-890 """
    MODEL = "TK-890"
    TYPE = b"M0890"
    VARIANTS = {
        b"M0890\x06": (160, 450, 490, "K"),
        b"M0890\x07": (160, 480, 512, "K2"),
        b"M0890\x08": (160, 403, 430, "K3"),
        b"M0890\x09": (160, 450, 480, "K(H)")
    }

    # Note:
    # These radios originally are constrained to certain band segments but the
    # original software doesn't care about it, so in order to match a
    # feature many will miss from the factory software and to help
    # the use of this radios in the ham bands we expanded the range
    # of the "K" version of the TK-790 from 148 to 144, as well as the
    # range of the TK-690 "F1" (from 29.7 to 28) and "F3" (from 50 to 54)
    # versions (note that F3 also needs physical modifications for use with
    # Ham bands)
