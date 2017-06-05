# Copyright 2016 Pavel Milanes, CO7WT, <pavelmc@gmail.com>
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
import time
import sys

from chirp import chirp_common, directory, memmap, errors, util, bitwise
from textwrap import dedent
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettings

LOG = logging.getLogger(__name__)

##### IMPORTANT DATA ##########################################
# This radios have a span of
# 0x00000 - 0x08000 => Radio Memory / Settings data
# 0x08000 - 0x10000 => FIRMWARE... hum...
###############################################################

MEM_FORMAT = """
#seekto 0x0000;
struct {
  u8 unknown0[14];          // x00-x0d unknown
  u8 banks;                 // x0e how many banks are programmed
  u8 channels;              // x0f how many total channels are programmed
  // --
  ul16 tot;                 // x10 TOT value: range(15, 600, 15); x04b0 = off
  u8 tot_rekey;             // x12 TOT Re-key value range(0, 60); off= 0
  u8 unknown1;              // x13 unknown
  u8 tot_reset;             // x14 TOT Re-key value range(0, 60); off= 0
  u8 unknown2;              // x15 unknows
  u8 tot_alert;             // x16 TOT pre alert: range(0,10); 0 = off
  u8 unknown3[7];           // x17-x1d unknown
  u8 sql_level;             // x1e  SQ reference level
  u8 battery_save;          // Only for portable: FF = off, x32 = on
  // --
  u8 unknown4[10];          // x20
  u8 unknown5:3,            // x2d
     c2t:1,                 // 1 bit clear to transpond: 1-off
                            // This is relative to DTMF / 2-Tone settings
     unknown6:4;
  u8 unknown7[5];           // x2b-x2f
  // --
  u8 unknown8[16];          // x30 ?
  u8 unknown9[16];          // x40 ?
  u8 unknown10[16];          // x50 ?
  u8 unknown11[16];         // x60 ?
  // --
  u8 add[16];               // x70-x7f 128 bits corresponding add/skip values
  // --
  u8 unknown12:4,           // x80
     off_hook_decode:1,     // 1 bit off hook decode enabled: 1-off
     off_hook_horn_alert:1, // 1 bit off hook horn alert: 1-off
     unknown13:2;
  u8 unknown14;             // x81
  u8 unknown15:3,           // x82
     self_prog:1,           // 1 bit Self programming enabled: 1-on
     clone:1,               // 1 bit clone enabled: 1-on
     firmware_prog:1,       // 1 bit firmware programming enabled: 1-on
     unknown16:1,
     panel_test:1;          // 1 bit panel test enabled
  u8 unknown17;             // x83
  u8 unknown18:5,           // x84
     warn_tone:1,           // 1 bit warning tone, enabled: 1-on
     control_tone:1,        // 1 bit control tone (key tone), enabled: 1-on
     poweron_tone:1;        // 1 bit power on tone, enabled: 1-on
  u8 unknown19[5];          // x85-x89
  u8 min_vol;               // minimum volume posible: range(0,32); 0 = off
  u8 tone_vol;              // minimum tone volume posible:
                                // xff = continous, range(0, 31)
  u8 unknown20[4];          // x8c-x8f
  // --
  u8 unknown21[4];          // x90-x93
  char poweronmesg[8];      // x94-x9b power on mesg 8 bytes, off is "\FF" * 8
  u8 unknown22[4];          // x9c-x9f
  // --
  u8 unknown23[7];          // xa0-xa6
  char ident[8];            // xa7-xae radio identification string
  u8 unknown24;             // xaf
  // --
  u8 unknown26[11];         // xaf-xba
  char lastsoftversion[5];  // software version employed to program the radio
} settings;

#seekto 0xd0;
struct {
  u8 unknown[4];
  char radio[6];
  char data[6];
} passwords;

#seekto 0x0110;
struct {
  u8 kA;                // Portable > Closed circle
  u8 kDA;               // Protable > Triangle to Left
  u8 kGROUP_DOWN;       // Protable > Triangle to Right
  u8 kGROUP_UP;         // Protable > Side 1
  u8 kSCN;              // Portable > Open Circle
  u8 kMON;              // Protable > Side 2
  u8 kFOOT;
  u8 kCH_UP;
  u8 kCH_DOWN;
  u8 kVOL_UP;
  u8 kVOL_DOWN;
  u8 unknown30[5];
  // --
  u8 unknown31[4];
  u8 kP_KNOB;           // Just portable: channel knob
  u8 unknown32[11];
} keys;

#seekto 0x0140;
struct {
  lbcd tf01_rx[4];
  lbcd tf01_tx[4];
  u8 tf01_u_rx;
  u8 tf01_u_tx;
  lbcd tf02_rx[4];
  lbcd tf02_tx[4];
  u8 tf02_u_rx;
  u8 tf02_u_tx;
  lbcd tf03_rx[4];
  lbcd tf03_tx[4];
  u8 tf03_u_rx;
  u8 tf03_u_tx;
  lbcd tf04_rx[4];
  lbcd tf04_tx[4];
  u8 tf04_u_rx;
  u8 tf04_u_tx;
  lbcd tf05_rx[4];
  lbcd tf05_tx[4];
  u8 tf05_u_rx;
  u8 tf05_u_tx;
  lbcd tf06_rx[4];
  lbcd tf06_tx[4];
  u8 tf06_u_rx;
  u8 tf06_u_tx;
  lbcd tf07_rx[4];
  lbcd tf07_tx[4];
  u8 tf07_u_rx;
  u8 tf07_u_tx;
  lbcd tf08_rx[4];
  lbcd tf08_tx[4];
  u8 tf08_u_rx;
  u8 tf08_u_tx;
  lbcd tf09_rx[4];
  lbcd tf09_tx[4];
  u8 tf09_u_rx;
  u8 tf09_u_tx;
  lbcd tf10_rx[4];
  lbcd tf10_tx[4];
  u8 tf10_u_rx;
  u8 tf10_u_tx;
  lbcd tf11_rx[4];
  lbcd tf11_tx[4];
  u8 tf11_u_rx;
  u8 tf11_u_tx;
  lbcd tf12_rx[4];
  lbcd tf12_tx[4];
  u8 tf12_u_rx;
  u8 tf12_u_tx;
  lbcd tf13_rx[4];
  lbcd tf13_tx[4];
  u8 tf13_u_rx;
  u8 tf13_u_tx;
  lbcd tf14_rx[4];
  lbcd tf14_tx[4];
  u8 tf14_u_rx;
  u8 tf14_u_tx;
  lbcd tf15_rx[4];
  lbcd tf15_tx[4];
  u8 tf15_u_rx;
  u8 tf15_u_tx;
  lbcd tf16_rx[4];
  lbcd tf16_tx[4];
  u8 tf16_u_rx;
  u8 tf16_u_tx;
} test_freq;

#seekto 0x200;
struct {
  char line1[32];
  char line2[32];
} message;

#seekto 0x2000;
struct {
  u8 bnumb;             // mem number
  u8 bank;              // to which bank it belongs
  char name[8];         // name 8 chars
  u8 unknown20[2];      // unknown yet
  lbcd rxfreq[4];       // rx freq
  // --
  lbcd txfreq[4];       // tx freq
  u8 rx_unkw;           // unknown yet
  u8 tx_unkw;           // unknown yet
  ul16 rx_tone;         // rx tone
  ul16 tx_tone;         // tx tone
  u8 unknown23[5];      // unknown yet
  u8 signaling;         // xFF = off, x30 DTMF, x31 2-Tone
                        // See the zone on x7000
  // --
  u8 ptt_id:2,       // ??? BOT = 0, EOT = 1, Both = 2, NONE = 3
     beat_shift:1,      // 1 = off
     unknown26:2        // ???
     power:1,           // power: 0 low / 1 high
     compander:1,       // 1 = off
     wide:1;            // wide 1 / 0 narrow
  u8 unknown27:6,       // ???
     busy_lock:1,       // 1 = off
     unknown28:1;       // ???
  u8 unknown29[14];     // unknown yet
} memory[128];

#seekto 0x5900;
struct {
  char model[8];
  u8 unknown50[4];
  char type[2];
  u8 unknown51[2];
    // --
  char serial[8];
  u8 unknown52[8];
} id;

#seekto 0x6000;
struct {
  u8 code[8];
  u8 unknown60[7];
  u8 count;
} bot[128];

#seekto 0x6800;
struct {
  u8 code[8];
  u8 unknown61[7];
  u8 count;
} eot[128];

#seekto 0x7000;
struct {
  lbcd dt2_id[5];       // DTMF lbcd ID (000-9999999999)
                        // 2-Tone = "11 f1 ff ff ff" ???
                        // None = "00 f0 ff ff ff"
} dtmf;
"""

MEM_SIZE = 0x8000  # 32,768 bytes
BLOCK_SIZE = 256
BLOCKS = MEM_SIZE / BLOCK_SIZE
MEM_BLOCKS = range(0, BLOCKS)

# define and empty block of data, as it will be used a lot in this code
EMPTY_BLOCK = "\xFF" * 256

RO_BLOCKS = range(0x10, 0x1F) + range(0x59, 0x5f)
ACK_CMD = "\x06"

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                chirp_common.PowerLevel("High", watts=5)]

MODES = ["NFM", "FM"]  # 12.5 / 25 Khz
VALID_CHARS = chirp_common.CHARSET_UPPER_NUMERIC + "_-*()/\-+=)"
SKIP_VALUES = ["", "S"]

TONES = chirp_common.TONES
# TONES.remove(254.1)
DTCS_CODES = chirp_common.DTCS_CODES

TOT = ["off"] + ["%s" % x for x in range(15, 615, 15)]
TOT_PRE = ["off"] + ["%s" % x for x in range(1, 11)]
TOT_REKEY = ["off"] + ["%s" % x for x in range(1, 61)]
TOT_RESET = ["off"] + ["%s" % x for x in range(1, 16)]
VOL = ["off"] + ["%s" % x for x in range(1, 32)]
TVOL = ["%s" % x for x in range(0, 33)]
TVOL[32] = "Continous"
SQL = ["off"] + ["%s" % x for x in range(1, 10)]

## BOT = 0, EOT = 1, Both = 2, NONE = 3
#PTTID = ["BOT", "EOT", "Both", "none"]

# For debugging purposes
debug = False

KEYS = {
    0x33: "Display character",
    0x35: "Home Channel",                   # Posible portable only, chek it
    0x37: "CH down",
    0x38: "CH up",
    0x39: "Key lock",
    0x3a: "Lamp",                           # Portable only
    0x3b: "Public address",
    0x3c: "Reverse",                        # Just in updated firmwares (768G)
    0x3d: "Horn alert",
    0x3e: "Selectable QT",                  # Just in updated firmwares (768G)
    0x3f: "2-tone encode",
    0x40: "Monitor A: open mommentary",
    0x41: "Monitor B: Open Toggle",
    0x42: "Monitor C: Carrier mommentary",
    0x43: "Monitor D: Carrier toogle",
    0x44: "Operator selectable tone",
    0x45: "Redial",
    0x46: "RF Power Low",                   # portable only ?
    0x47: "Scan",
    0x48: "Scan del/add",
    0x4a: "GROUP down",
    0x4b: "GROUP up",
    #0x4e: "Tone off (Experimental)",       # undocumented !!!!
    0x4f: "None",
    0x50: "VOL down",
    0x51: "VOL up",
    0x52: "Talk around",
    0x5d: "AUX",
    0xa1: "Channel Up/Down"                 # Knob for portables only
    }


def _raw_recv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except:
        raise errors.RadioError("Error reading data from radio")

    # DEBUG
    if debug is True:
        LOG.debug("<== (%d) bytes:\n\n%s" % (len(data), util.hexprint(data)))

    return data


def _raw_send(radio, data):
    """Raw send to the radio device"""
    try:
        radio.pipe.write(data)
    except:
        raise errors.RadioError("Error sending data to radio")

    # DEBUG
    if debug is True:
        LOG.debug("==> (%d) bytes:\n\n%s" % (len(data), util.hexprint(data)))


def _close_radio(radio):
    """Get the radio out of program mode"""
    _raw_send(radio, "\x45")


def _checksum(data):
    """the radio block checksum algorithm"""
    cs = 0
    for byte in data:
            cs += ord(byte)
    return cs % 256


def _send(radio, frame):
    """Generic send data to the radio"""
    _raw_send(radio, frame)


def _make_frame(cmd, addr):
    """Pack the info in the format it likes"""
    return struct.pack(">BH", ord(cmd), addr)


def _handshake(radio, msg=""):
    """Make a full handshake"""
    # send ACK
    _raw_send(radio, ACK_CMD)
    # receive ACK
    ack = _raw_recv(radio, 1)
    # check ACK
    if ack != ACK_CMD:
        _close_radio(radio)
        mesg = "Handshake failed " + msg
        # DEBUG
        LOG.debug(mesg)
        raise Exception(mesg)


def _check_write_ack(r, ack, addr):
    """Process the ack from the write process
    this is half handshake needed in tx data block"""
    # all ok
    if ack == ACK_CMD:
        return True

    # Explicit BAD checksum
    if ack == "\x15":
        _close_radio(r)
        raise errors.RadioError(
            "Bad checksum in block %02x write" % addr)

    # everything else
    _close_radio(r)
    raise errors.RadioError(
        "Problem with the ack to block %02x write, ack %03i" %
        (addr, int(ack)))


def _recv(radio):
    """Receive data from the radio, 258 bytes split in (cmd, data, checksum)
    checking the checksum to be correct, and returning just
    256 bytes of data or false if short empty block"""
    rxdata = _raw_recv(radio, BLOCK_SIZE + 2)
    # when the RX block has two bytes and the first is \x5A
    # then the block is all \xFF
    if len(rxdata) == 2 and rxdata[0] == "\x5A":
        # fast work in linux has to make the handshake, slow windows don't
        if not sys.platform in ["win32", "cygwin"]:
            _handshake(radio, "short block")
        return False
    elif len(rxdata) != 258:
        # not the amount of data we want
        msg = "The radio send %d bytes, we need 258" % len(rxdata)
        # DEBUG
        LOG.error(msg)
        raise errors.RadioError(msg)
    else:
        rcs = ord(rxdata[-1])
        data = rxdata[1:-1]
        ccs = _checksum(data)

        if rcs != ccs:
            _close_radio(radio)
            raise errors.RadioError(
                "Block Checksum Error! real %02x, calculated %02x" %
                (rcs, ccs))

        _handshake(radio, "after checksum")
        return data


def _open_radio(radio, status):
    """Open the radio into program mode and check if it's the correct model"""
    # linux min is 0.13, win min is 0.25; set to bigger to be safe
    radio.pipe.timeout = 0.4
    radio.pipe.parity = "E"

    # DEBUG
    LOG.debug("Entering program mode.")
    # max tries
    tries = 10

    # UI
    status.cur = 0
    status.max = tries
    status.msg = "Entering program mode..."

    # try a few times to get the radio into program mode
    exito = False
    for i in range(0, tries):
        _raw_send(radio, "PROGRAM")
        ack = _raw_recv(radio, 1)

        if ack != ACK_CMD:
            # DEBUG
            LOG.debug("Try %s failed, traying again..." % i)
            time.sleep(0.25)
        else:
            exito = True
            break

        status.cur += 1
        radio.status_fn(status)


    if exito is False:
        _close_radio(radio)
        LOG.debug("Radio did not accepted PROGRAM command in %s atempts" % tries)
        raise errors.RadioError("The radio doesn't accept program mode")

    # DEBUG
    LOG.debug("Received ACK to the PROGRAM command, send ID query.")

    _raw_send(radio, "\x02")
    rid = _raw_recv(radio, 8)

    if not (radio.TYPE in rid):
        # bad response, properly close the radio before exception
        _close_radio(radio)

        # DEBUG
        LOG.debug("Incorrect model ID:")
        LOG.debug(util.hexprint(rid))

        raise errors.RadioError(
            "Incorrect model ID, got %s, it not contains %s" %
            (rid.strip("\xff"), radio.TYPE))

    # DEBUG
    LOG.debug("Full ident string is:")
    LOG.debug(util.hexprint(rid))
    _handshake(radio)

    status.msg = "Radio ident success!"
    radio.status_fn(status)
    # a pause
    time.sleep(1)


def do_download(radio):
    """ The download function """
    # UI progress
    status = chirp_common.Status()
    data = ""
    count = 0

    # open the radio
    _open_radio(radio, status)

    # reset UI data
    status.cur = 0
    status.max = MEM_SIZE / 256
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    # set the timeout and if windows keep it bigger
    if sys.platform in ["win32", "cygwin"]:
        # bigger timeout
        radio.pipe.timeout = 0.55
    else:
        # Linux can keep up, MAC?
        radio.pipe.timeout = 0.05

    # DEBUG
    LOG.debug("Starting the download from radio")

    for addr in MEM_BLOCKS:
        # send request, but before flush the rx buffer
        radio.pipe.flush()
        _send(radio, _make_frame("R", addr))

        # now we get the data
        d = _recv(radio)
        # if empty block, it return false
        # aka we asume a empty 256 xFF block
        if d is False:
            d = EMPTY_BLOCK

        data += d

        # UI Update
        status.cur = count
        radio.status_fn(status)

        count += 1

    _close_radio(radio)
    return memmap.MemoryMap(data)


def do_upload(radio):
    """ The upload function """
    # UI progress
    status = chirp_common.Status()
    data = ""
    count = 0

    # open the radio
    _open_radio(radio, status)

    # update UI
    status.cur = 0
    status.max = MEM_SIZE / 256
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the default for the original soft as measured
    radio.pipe.timeout = 0.5

    # DEBUG
    LOG.debug("Starting the upload to the radio")

    count = 0
    raddr = 0
    for addr in MEM_BLOCKS:
        # this is the data block to write
        data = radio.get_mmap()[raddr:raddr+BLOCK_SIZE]

        # The blocks from x59-x5F are NOT programmable
        # The blocks from x11-x1F are writed only if not empty
        if addr in RO_BLOCKS:
            # checking if in the range of optional blocks
            if addr >= 0x10 and addr <= 0x1F:
                # block is empty ?
                if data == EMPTY_BLOCK:
                    # no write of this block
                    # but we have to continue updating the counters
                    count += 1
                    raddr = count * 256
                    continue
            else:
                count += 1
                raddr = count * 256
                continue

        if data == EMPTY_BLOCK:
            frame = _make_frame("Z", addr) + "\xFF"
        else:
            cs = _checksum(data)
            frame = _make_frame("W", addr) + data + chr(cs)

        _send(radio, frame)

        # get the ACK
        ack = _raw_recv(radio, 1)
        _check_write_ack(radio, ack, addr)

        # DEBUG
        LOG.debug("Sending block %02x" % addr)

        # UI Update
        status.cur = count
        radio.status_fn(status)

        count += 1
        raddr = count * 256

    _close_radio(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0xA7:0xAE]
    if (rid in cls.VARIANTS):
        # correct model
        return True
    else:
        return False


class Kenwood60GBankModel(chirp_common.BankModel):
    """Testing the bank model on kennwood"""
    channelAlwaysHasBank = True

    def get_num_mappings(self):
        return self._radio._num_banks

    def get_mappings(self):
        banks = []
        for i in range(0, self._radio._num_banks):
            bindex = i + 1
            bank = self._radio._bclass(self, i, "%03i" % bindex)
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_mapping(self, memory, bank):
        self._radio._set_bank(memory.number, bank.index)

    def remove_memory_from_mapping(self, memory, bank):
        if self._radio._get_bank(memory.number) != bank.index:
            raise Exception("Memory %i not in bank %s. Cannot remove." %
                            (memory.number, bank))

        # We can't "Remove" it for good
        # the kenwood paradigm don't allow it
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
        return [self.get_mappings()[index]]


class memBank(chirp_common.Bank):
    """A bank model for kenwood"""
    # Integral index of the bank (not to be confused with per-memory
    # bank indexes
    index = 0


class Kenwood_Serie_60G(chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio):
    """Kenwood Serie 60G Radios base class"""
    VENDOR = "Kenwood"
    BAUD_RATE = 9600
    _memsize = MEM_SIZE
    NAME_LENGTH = 8
    _range = [136000000, 162000000]
    _upper = 128
    _chs_progs = 0
    _num_banks = 128
    _bclass = memBank
    _kind = ""
    VARIANT = ""
    MODEL = ""

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is experimental; not all features have been '
            'implemented, but it has those features most used by hams.\n'
             '\n'
             'This radios are able to work slightly outside the OEM '
             'frequency limits. After testing, the limit in Chirp has '
             'been set 4% outside the OEM limit. This allows you to use '
             'some models on the ham bands.\n'
             '\n'
             'Nevertheless, each radio has its own hardware limits and '
             'your mileage may vary.\n'
             )
        rp.pre_download = _(dedent("""\
            Follow this instructions to download your info:
            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio (unblock it if password protected)
            4 - Do the download of your radio data
            """))
        rp.pre_upload = _(dedent("""\
            Follow this instructions to upload your info:
            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio (unblock it if password protected)
            4 - Do the upload of your radio data
            """))
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
        rf.valid_modes = MODES
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
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = VALID_CHARS
        rf.valid_skips = SKIP_VALUES
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_bands = [self._range]
        rf.valid_name_length = 8
        rf.memory_bounds = (1, self._upper)
        return rf

    def _fill(self, offset, data):
        """Fill an specified area of the memmap with the passed data"""
        for addr in range(0, len(data)):
            self._mmap[offset + addr] = data[addr]

    def _prep_data(self):
        """Prepare the areas in the memmap to do a consistend write
        it has to make an update on the x300 area with banks and channel
        info; other in the x1000 with banks and channel counts
        and a last one in x7000 with flag data"""
        rchs = 0
        data = dict()

        # sorting the data
        for ch in range(0, self._upper):
            mem = self._memobj.memory[ch]
            bnumb = int(mem.bnumb)
            bank = int(mem.bank)
            if bnumb != 255 and (bank != 255 and bank != 0):
                try:
                    data[bank].append(ch)
                except:
                    data[bank] = list()
                    data[bank].append(ch)
                data[bank].sort()
                # counting the real channels
                rchs = rchs + 1

        # updating the channel/bank count
        self._memobj.settings.channels = rchs
        self._chs_progs = rchs
        self._memobj.settings.banks = len(data)

        # building the data for the memmap
        fdata = ""

        for k, v in data.iteritems():
            # posible bad data
            if k == 0:
                k = 1
                raise errors.InvalidValueError(
                    "Invalid bank value '%k', bad data in the image? \
                    Trying to fix this, review your bank data!" % k)
            c = 1
            for i in v:
                fdata += chr(k) + chr(c) + chr(k - 1) + chr(i)
                c = c + 1

        # fill to match a full 256 bytes block
        fdata += (len(fdata) % 256) * "\xFF"

        # updating the data in the memmap [x300]
        self._fill(0x300, fdata)

        # update the info in x1000; it has 2 bytes with
        # x00 = bank , x01 = bank's channel count
        # the rest of the 14 bytes are \xff
        bdata = ""
        for i in range(1, len(data) + 1):
            line = chr(i) + chr(len(data[i]))
            line += "\xff" * 14
            bdata += line

        # fill to match a full 256 bytes block
        bdata += (256 - (len(bdata)) % 256) * "\xFF"

        # fill to match the whole area
        bdata += (16 - len(bdata) / 256) * EMPTY_BLOCK

        # updating the data in the memmap [x1000]
        self._fill(0x1000, bdata)

        # DTMF id for each channel, 5 bytes lbcd at x7000
        # ############## TODO ###################
        fldata = "\x00\xf0\xff\xff\xff" * self._chs_progs + \
            "\xff" * (5 * (self._upper - self._chs_progs))

        # write it
        # updating the data in the memmap [x7000]
        self._fill(0x7000, fldata)

    def _set_variant(self):
        """Select and set the correct variables for the class acording
        to the correct variant of the radio"""
        rid = self._mmap[0xA7:0xAE]

        # indentify the radio variant and set the enviroment to it's values
        try:
            self._upper, low, high, self._kind = self.VARIANTS[rid]

            # Frequency ranges: some model/variants are able to work the near
            # ham bands, even if they are outside the OEM ranges.
            # By experimentation we found that 4% at the edges is in most
            # cases safe and will cover the near ham bands in full
            self._range = [low * 1000000 * 0.96, high * 1000000 * 1.04]

            # setting the bank data in the features, 8 & 16 CH dont have banks
            if self._upper < 32:
                rf = chirp_common.RadioFeatures()
                rf.has_bank = False

            # put the VARIANT in the class, clean the model / CHs / Type
            # in the same layout as the KPG program
            self._VARIANT = self.MODEL + " [" + str(self._upper) + "CH]: "
            # In the OEM string we show the real OEM ranges
            self._VARIANT += self._kind + ", %d - %d MHz" % (low, high)

        except KeyError:
            LOG.debug("Wrong Kenwood radio, ID or unknown variant")
            LOG.debug(util.hexprint(rid))
            raise errors.RadioError(
                "Wrong Kenwood radio, ID or unknown variant, see LOG output.")
            return False

    def sync_in(self):
        """Do a download of the radio eeprom"""
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        """Do an upload to the radio eeprom"""

        # chirp signature on the eprom ;-)
        sign = "Chirp"
        self._fill(0xbb, sign)

        try:
            self._prep_data()
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        """Process the memory object"""
        # how many channels are programed
        self._chs_progs = ord(self._mmap[15])

        # load the memobj
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

        # to set the vars on the class to the correct ones
        self._set_variant()

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
            memval.set_raw("\xff\xff")
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            val = int("%i" % value, 8) + 0x2800
            if pol == "R":
                val += 0xA000
            memval.set_value(val)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def _get_scan(self, chan):
        """Get the channel scan status from the 16 bytes array on the eeprom
        then from the bits on the byte, return '' or 'S' as needed"""
        result = "S"
        byte = int(chan/8)
        bit = chan % 8
        res = self._memobj.settings.add[byte] & (pow(2, bit))
        if res > 0:
            result = ""

        return result

    def _set_scan(self, chan, value):
        """Set the channel scan status from UI to the mem_map"""
        byte = int(chan/8)
        bit = chan % 8

        # get the actual value to see if I need to change anything
        actual = self._get_scan(chan)
        if actual != value:
            # I have to flip the value
            rbyte = self._memobj.settings.add[byte]
            rbyte = rbyte ^ pow(2, bit)
            self._memobj.settings.add[byte] = rbyte

    def get_memory(self, number):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[number - 1]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        # this radio has a setting about the amount of real chans of the 128
        # olso in the channel has xff on the Rx freq it's empty
        if (number > (self._chs_progs + 1)) or (_mem.get_raw()[0] == "\xFF"):
            mem.empty = True
            # but is not enough, you have to crear the memory in the mmap
            # to get it ready for the sync_out process
            _mem.set_raw("\xFF" * 48)
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if _mem.get_raw()[16] == "\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX feq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset < 0:
                mem.offset = abs(offset)
                mem.duplex = "-"
            elif offset > 0:
                mem.offset = offset
                mem.duplex = "+"
            else:
                mem.offset = 0

        # name TAG of the channel
        mem.name = str(_mem.name).rstrip()

        # power
        mem.power = POWER_LEVELS[_mem.power]

        # wide/marrow
        mem.mode = MODES[_mem.wide]

        # skip
        mem.skip = self._get_scan(number - 1)

        # tone data
        rxtone = txtone = None
        txtone = self._decode_tone(_mem.tx_tone)
        rxtone = self._decode_tone(_mem.rx_tone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # Extra
        # bank and number in the channel
        mem.extra = RadioSettingGroup("extra", "Extra")

        # validate bank
        b = int(_mem.bank)
        if b > 127 or b == 0:
            _mem.bank = b = 1

        bank = RadioSetting("bank", "Bank it belongs",
                            RadioSettingValueInteger(1, 128, b))
        mem.extra.append(bank)

        # validate bnumb
        if int(_mem.bnumb) > 127:
            _mem.bank = mem.number

        bnumb = RadioSetting("bnumb", "Ch number in the bank",
                             RadioSettingValueInteger(0, 127, _mem.bnumb))
        mem.extra.append(bnumb)

        bs = RadioSetting("beat_shift", "Beat shift",
                          RadioSettingValueBoolean(
                              not bool(_mem.beat_shift)))
        mem.extra.append(bs)

        cp = RadioSetting("compander", "Compander",
                          RadioSettingValueBoolean(
                              not bool(_mem.compander)))
        mem.extra.append(cp)

        bl = RadioSetting("busy_lock", "Busy Channel lock",
                          RadioSettingValueBoolean(
                              not bool(_mem.busy_lock)))
        mem.extra.append(bl)

        return mem

    def set_memory(self, mem):
        """Set the memory data in the eeprom img from the UI
        not ready yet, so it will return as is"""

        # get the eprom representation of this channel
        _mem = self._memobj.memory[mem.number - 1]

        # if empty memmory
        if mem.empty:
            _mem.set_raw("\xFF" * 48)
            return

        # frequency
        _mem.rxfreq = mem.freq / 10

        # this are a mistery yet, but so falr there is no impact
        # whit this default values for new channels
        if int(_mem.rx_unkw) == 0xff:
            _mem.rx_unkw = 0x35
            _mem.tx_unkw = 0x32

        # duplex
        if mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "off":
            for byte in _mem.txfreq:
                byte.set_raw("\xFF")
        else:
            _mem.txfreq = mem.freq / 10

        # tone data
        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.tx_tone, txmode, txtone, txpol)
        self._encode_tone(_mem.rx_tone, rxmode, rxtone, rxpol)

        # name TAG of the channel
        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _mem.name[i] = mem.name[i]
            except IndexError:
                _mem.name[i] = "\x20"

        # power
        # default power is low
        if mem.power is None:
            mem.power = POWER_LEVELS[0]

        _mem.power = POWER_LEVELS.index(mem.power)

        # wide/marrow
        _mem.wide = MODES.index(mem.mode)

        # scan add property
        self._set_scan(mem.number - 1, mem.skip)

        # bank and number in the channel
        if int(_mem.bnumb) == 0xff:
            _mem.bnumb = mem.number - 1
            _mem.bank = 1

        # extra settings
        for setting in mem.extra:
            if setting != "bank" or setting != "bnumb":
                setattr(_mem, setting.get_name(), not bool(setting.value))

        # all data get sync after channel mod
        self._prep_data()

        return mem

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) == MEM_SIZE:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        sett = self._memobj.settings
        mess = self._memobj.message
        keys = self._memobj.keys
        idm = self._memobj.id
        passwd = self._memobj.passwords

        # basic features of the radio
        basic = RadioSettingGroup("basic", "Basic Settings")
        # dealer settings
        dealer = RadioSettingGroup("dealer", "Dealer Settings")
        # buttons
        fkeys = RadioSettingGroup("keys", "Front keys config")

        # TODO / PLANED
        # adjust feqs
        #freqs = RadioSettingGroup("freqs", "Adjust Frequencies")

        top = RadioSettings(basic, dealer, fkeys)

        # Basic
        tot = RadioSetting("settings.tot", "Time Out Timer (TOT)",
                           RadioSettingValueList(TOT, TOT[
                           TOT.index(str(int(sett.tot)))]))
        basic.append(tot)

        totalert = RadioSetting("settings.tot_alert", "TOT pre alert",
                                RadioSettingValueList(TOT_PRE,
                                TOT_PRE[int(sett.tot_alert)]))
        basic.append(totalert)

        totrekey = RadioSetting("settings.tot_rekey", "TOT re-key time",
                                RadioSettingValueList(TOT_REKEY,
                                TOT_REKEY[int(sett.tot_rekey)]))
        basic.append(totrekey)

        totreset = RadioSetting("settings.tot_reset", "TOT reset time",
                                RadioSettingValueList(TOT_RESET,
                                TOT_RESET[int(sett.tot_reset)]))
        basic.append(totreset)

        # this feature is for mobile only
        if self.TYPE[0] == "M":
            minvol = RadioSetting("settings.min_vol", "Minimum volume",
                                  RadioSettingValueList(VOL,
                                  VOL[int(sett.min_vol)]))
            basic.append(minvol)

            tv = int(sett.tone_vol)
            if tv == 255:
                tv = 32
            tvol = RadioSetting("settings.tone_vol", "Minimum tone volume",
                                RadioSettingValueList(TVOL, TVOL[tv]))
            basic.append(tvol)

        sql = RadioSetting("settings.sql_level", "SQL Ref Level",
                           RadioSettingValueList(
                           SQL, SQL[int(sett.sql_level)]))
        basic.append(sql)

        #c2t = RadioSetting("settings.c2t", "Clear to Transpond",
                           #RadioSettingValueBoolean(not sett.c2t))
        #basic.append(c2t)

        ptone = RadioSetting("settings.poweron_tone", "Power On tone",
                             RadioSettingValueBoolean(sett.poweron_tone))
        basic.append(ptone)

        ctone = RadioSetting("settings.control_tone", "Control (key) tone",
                             RadioSettingValueBoolean(sett.control_tone))
        basic.append(ctone)

        wtone = RadioSetting("settings.warn_tone", "Warning tone",
                             RadioSettingValueBoolean(sett.warn_tone))
        basic.append(wtone)

        # Save Battery only for portables?
        if self.TYPE[0] == "P":
            bs = int(sett.battery_save) == 0x32 and True or False
            bsave = RadioSetting("settings.battery_save", "Battery Saver",
                                 RadioSettingValueBoolean(bs))
            basic.append(bsave)

        ponm = str(sett.poweronmesg).strip("\xff")
        pom = RadioSetting("settings.poweronmesg", "Power on message",
                           RadioSettingValueString(0, 8, ponm, False))
        basic.append(pom)

        # dealer
        valid_chars = ",-/:[]" + chirp_common.CHARSET_ALPHANUMERIC
        mstr = "".join([c for c in self._VARIANT if c in valid_chars])

        val = RadioSettingValueString(0, 35, mstr)
        val.set_mutable(False)
        mod = RadioSetting("not.mod", "Radio Version", val)
        dealer.append(mod)

        sn = str(idm.serial).strip(" \xff")
        val = RadioSettingValueString(0, 8, sn)
        val.set_mutable(False)
        serial = RadioSetting("not.serial", "Serial number", val)
        dealer.append(serial)

        svp = str(sett.lastsoftversion).strip(" \xff")
        val = RadioSettingValueString(0, 5, svp)
        val.set_mutable(False)
        sver = RadioSetting("not.softver", "Software Version", val)
        dealer.append(sver)

        l1 = str(mess.line1).strip(" \xff")
        line1 = RadioSetting("message.line1", "Comment 1",
                           RadioSettingValueString(0, 32, l1))
        dealer.append(line1)

        l2 = str(mess.line2).strip(" \xff")
        line2 = RadioSetting("message.line2", "Comment 2",
                             RadioSettingValueString(0, 32, l2))
        dealer.append(line2)

        sprog = RadioSetting("settings.self_prog", "Self program",
                             RadioSettingValueBoolean(sett.self_prog))
        dealer.append(sprog)

        clone = RadioSetting("settings.clone", "Allow clone",
                             RadioSettingValueBoolean(sett.clone))
        dealer.append(clone)

        panel = RadioSetting("settings.panel_test", "Panel Test",
                             RadioSettingValueBoolean(sett.panel_test))
        dealer.append(panel)

        fmw = RadioSetting("settings.firmware_prog", "Firmware program",
                           RadioSettingValueBoolean(sett.firmware_prog))
        dealer.append(fmw)

        # front keys
        # The Mobile only parameters are wraped here
        if self.TYPE[0] == "M":
            vu = RadioSetting("keys.kVOL_UP", "VOL UP",
                              RadioSettingValueList(KEYS.values(),
                              KEYS.values()[KEYS.keys().index(
                                  int(keys.kVOL_UP))]))
            fkeys.append(vu)

            vd = RadioSetting("keys.kVOL_DOWN", "VOL DOWN",
                              RadioSettingValueList(KEYS.values(),
                              KEYS.values()[KEYS.keys().index(
                                  int(keys.kVOL_DOWN))]))
            fkeys.append(vd)

            chu = RadioSetting("keys.kCH_UP", "CH UP",
                               RadioSettingValueList(KEYS.values(),
                               KEYS.values()[KEYS.keys().index(
                                   int(keys.kCH_UP))]))
            fkeys.append(chu)

            chd = RadioSetting("keys.kCH_DOWN", "CH DOWN",
                               RadioSettingValueList(KEYS.values(),
                               KEYS.values()[KEYS.keys().index(
                                   int(keys.kCH_DOWN))]))
            fkeys.append(chd)

            foot = RadioSetting("keys.kFOOT", "Foot switch",
                               RadioSettingValueList(KEYS.values(),
                               KEYS.values()[KEYS.keys().index(
                                   int(keys.kCH_DOWN))]))
            fkeys.append(foot)

        # this is the common buttons for all

        # 260G model don't have the front keys
        if not "P2600" in self.TYPE:
            scn_name = "SCN"
            if self.TYPE[0] == "P":
                scn_name = "Open Circle"

            scn = RadioSetting("keys.kSCN", scn_name,
                               RadioSettingValueList(KEYS.values(),
                               KEYS.values()[KEYS.keys().index(
                                   int(keys.kSCN))]))
            fkeys.append(scn)

            a_name = "A"
            if self.TYPE[0] == "P":
                a_name = "Closed circle"

            a = RadioSetting("keys.kA", a_name,
                             RadioSettingValueList(KEYS.values(),
                             KEYS.values()[KEYS.keys().index(
                                 int(keys.kA))]))
            fkeys.append(a)

            da_name = "D/A"
            if self.TYPE[0] == "P":
                da_name = "< key"

            da = RadioSetting("keys.kDA", da_name,
                              RadioSettingValueList(KEYS.values(),
                              KEYS.values()[KEYS.keys().index(
                                  int(keys.kDA))]))
            fkeys.append(da)

            gu_name = "Triangle up"
            if self.TYPE[0] == "P":
                gu_name = "Side 1"

            gu = RadioSetting("keys.kGROUP_UP", gu_name,
                              RadioSettingValueList(KEYS.values(),
                              KEYS.values()[KEYS.keys().index(
                                  int(keys.kGROUP_UP))]))
            fkeys.append(gu)

        # Side keys on portables
        gd_name = "Triangle Down"
        if self.TYPE[0] == "P":
            gd_name = "> key"

        gd = RadioSetting("keys.kGROUP_DOWN", gd_name,
                          RadioSettingValueList(KEYS.values(),
                          KEYS.values()[KEYS.keys().index(
                              int(keys.kGROUP_DOWN))]))
        fkeys.append(gd)

        mon_name = "MON"
        if self.TYPE[0] == "P":
            mon_name = "Side 2"

        mon = RadioSetting("keys.kMON", mon_name,
                           RadioSettingValueList(KEYS.values(),
                           KEYS.values()[KEYS.keys().index(
                               int(keys.kMON))]))
        fkeys.append(mon)

        return top

    def set_settings(self, settings):
        """Translate the settings in the UI into bit in the mem_struct
        I don't understand well the method used in many drivers
        so, I used mine, ugly but works ok"""

        mobj = self._memobj

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            # Let's roll the ball
            if "." in element.get_name():
                inter, setting = element.get_name().split(".")
                # you must ignore the settings with "not"
                # this are READ ONLY attributes
                if inter == "not":
                    continue

                obj = getattr(mobj, inter)
                value = element.value

                # integers case + special case
                if setting in ["tot", "tot_alert", "min_vol", "tone_vol",
                               "sql_level", "tot_rekey", "tot_reset"]:
                    # catching the "off" values as zero
                    try:
                        value = int(value)
                    except:
                        value = 0

                    # tot case step 15
                    if setting == "tot":
                        value = value * 15
                        # off is special
                        if value == 0:
                            value = 0x4b0

                    # Caso tone_vol
                    if setting == "tone_vol":
                        # off is special
                        if value == 32:
                            value = 0xff

                # Bool types + inverted
                if setting in ["c2t", "poweron_tone", "control_tone",
                               "warn_tone", "battery_save", "self_prog",
                               "clone", "panel_test"]:
                    value = bool(value)

                    # this cases are inverted
                    if setting == "c2t":
                        value = not value

                    # case battery save is special
                    if setting == "battery_save":
                        if bool(value) is True:
                            value = 0x32
                        else:
                            value = 0xff

                # String cases
                if setting in ["poweronmesg", "line1", "line2"]:
                    # some vars
                    value = str(value)
                    just = 8
                    # lines with 32
                    if "line" in setting:
                        just = 32

                    # empty case
                    if len(value) == 0:
                        value = "\xff" * just
                    else:
                        value = value.ljust(just)

                # case keys, with special config
                if inter == "keys":
                    value = KEYS.keys()[KEYS.values().index(str(value))]

            # Apply al configs done
            setattr(obj, setting, value)

    def get_bank_model(self):
        """Pass the bank model to the UI part"""
        rf = self.get_features()
        if rf.has_bank is True:
            return Kenwood60GBankModel(self)
        else:
            return None

    def _get_bank(self, loc):
        """Get the bank data for a specific channel"""
        mem = self._memobj.memory[loc - 1]
        bank = int(mem.bank) - 1

        if bank > self._num_banks or bank < 1:
            # all channels must belong to a bank, even with just 1 bank
            return 0
        else:
            return bank

    def _set_bank(self, loc, bank):
        """Set the bank data for a specific channel"""
        try:
            b = int(bank)
            if b > 127:
                b = 0
            mem = self._memobj.memory[loc - 1]
            mem.bank = b + 1
        except:
            msg = "You can't have a channel without a bank, click another bank"
            raise errors.InvalidDataError(msg)


# This kenwwood family is known as "60-G Serie"
# all this radios ending in G are compatible:
#
# Portables VHF TK-260G/270G/272G/278G
# Portables UHF TK-360G/370G/372G/378G/388G
#
# Mobiles VHF TK-760G/762G/768G
# Mobiles VHF TK-860G/862G/868G
#
# WARNING !!!! Radios With Password in the data section ###############
#
# When a radio has a data password (aka to program it) the last byte (#8)
# in the id code change from \xf1 to \xb1; so we remove this last byte
# from the identification procedures and variants.
#
# This effectively render the data password USELESS even if set.
# Translation: Chirps will read and write password protected radios
# with no problem.


@directory.register
class TK868G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-868G Radio M/C"""
    MODEL = "TK-868G"
    TYPE = "M8680"
    VARIANTS = {
        "M8680\x18\xff":    (8, 400, 490, "M"),
        "M8680;\xff":       (128, 350, 390, "C1"),
        "M86808\xff":       (128, 400, 430, "C2"),
        "M86806\xff":       (128, 450, 490, "C3"),
        }


@directory.register
class TK862G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-862G Radio K/E/(N)E"""
    MODEL = "TK-862G"
    TYPE = "M8620"
    VARIANTS = {
        "M8620\x06\xff":    (8, 450, 490, "K"),
        "M8620\x07\xff":    (8, 485, 512, "K2"),
        "M8620&\xff":       (8, 440, 470, "E"),
        "M8620V\xff":       (8, 440, 470, "(N)E"),
        }


@directory.register
class TK860G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-860G Radio K"""
    MODEL = "TK-860G"
    TYPE = "M8600"
    VARIANTS = {
        "M8600\x08\xff":    (128, 400, 430, "K"),
        "M8600\x06\xff":    (128, 450, 490, "K1"),
        "M8600\x07\xff":    (128, 485, 512, "K2"),
        "M8600\x18\xff":    (128, 400, 430, "M"),
        "M8600\x16\xff":    (128, 450, 490, "M1"),
        "M8600\x17\xff":    (128, 485, 520, "M2"),
        }


@directory.register
class TK768G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-768G Radios [M/C]"""
    MODEL = "TK-768G"
    TYPE = "M7680"
    # Note that 8 CH don't have banks
    VARIANTS = {
        "M7680\x15\xff": (8, 136, 162, "M2"),
        "M7680\x14\xff": (8, 148, 174, "M"),
        "M76805\xff":    (128, 136, 162, "C2"),
        "M76804\xff":    (128, 148, 174, "C"),
        }


@directory.register
class TK762G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-762G Radios [K/E/NE]"""
    MODEL = "TK-762G"
    TYPE = "M7620"
    # Note that 8 CH don't have banks
    VARIANTS = {
        "M7620\x05\xff": (8, 136, 162, "K2"),
        "M7620\x04\xff": (8, 148, 172, "K"),
        "M7620$\xff":    (8, 148, 172, "E"),
        "M7620T\xff":    (8, 148, 172, "NE"),
        }


@directory.register
class TK760G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-760G Radios [K/M/(N)E]"""
    MODEL = "TK-760G"
    TYPE = "M7600"
    VARIANTS = {
        "M7600\x05\xff": (128, 136, 162, "K2"),
        "M7600\x04\xff": (128, 148, 174, "K"),
        "M7600\x14\xff": (128, 148, 174, "M"),
        "M7600T\xff":    (128, 148, 174, "NE")
        }


@directory.register
class TK388G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-388 Radio [K/E/M/NE]"""
    MODEL = "TK-388G"
    TYPE = "P3880"
    VARIANTS = {
        "P3880\x1b\xff": (128, 350, 370, "M")
        }


@directory.register
class TK378G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-378 Radio [K/E/M/NE]"""
    MODEL = "TK-378G"
    TYPE = "P3780"
    VARIANTS = {
        "P3780\x16\xff": (16, 450, 470, "M"),
        "P3780\x17\xff": (16, 400, 420, "M1"),
        "P3780\x36\xff": (128, 490, 512, "C"),
        "P3780\x39\xff": (128, 403, 430, "C1")
        }


@directory.register
class TK372G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-372 Radio [K/E/M/NE]"""
    MODEL = "TK-372G"
    TYPE = "P3720"
    VARIANTS = {
        "P3720\x06\xff": (32, 450, 470, "K"),
        "P3720\x07\xff": (32, 470, 490, "K1"),
        "P3720\x08\xff": (32, 490, 512, "K2"),
        "P3720\x09\xff": (32, 403, 430, "K3")
        }


@directory.register
class TK370G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-370 Radio [K/E/M/NE]"""
    MODEL = "TK-370G"
    TYPE = "P3700"
    VARIANTS = {
        "P3700\x06\xff": (128, 450, 470, "K"),
        "P3700\x07\xff": (128, 470, 490, "K1"),
        "P3700\x08\xff": (128, 490, 512, "K2"),
        "P3700\x09\xff": (128, 403, 430, "K3"),
        "P3700\x16\xff": (128, 450, 470, "M"),
        "P3700\x17\xff": (128, 470, 490, "M1"),
        "P3700\x18\xff": (128, 490, 520, "M2"),
        "P3700\x19\xff": (128, 403, 430, "M3"),
        "P3700&\xff": (128, 440, 470, "E"),
        "P3700V\xff": (128, 440, 470, "NE")
        }


@directory.register
class TK360G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-360 Radio [K/E/M/NE]"""
    MODEL = "TK-360G"
    TYPE = "P3600"
    VARIANTS = {
        "P3600\x06\xff": (8, 450, 470, "K"),
        "P3600\x07\xff": (8, 470, 490, "K1"),
        "P3600\x08\xff": (8, 490, 512, "K2"),
        "P3600\x09\xff": (8, 403, 430, "K3"),
        "P3600&\xff": (8, 440, 470, "E"),
        "P3600)\xff": (8, 406, 430, "E1"),
        "P3600\x16\xff": (8, 450, 470, "M"),
        "P3600\x17\xff": (8, 470, 490, "M1"),
        "P3600\x19\xff": (8, 403, 430, "M2"),
        "P3600V\xff": (8, 440, 470, "NE"),
        "P3600Y\xff": (8, 403, 430, "NE1")
        }


@directory.register
class TK278G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-278G Radio C/C1/M/M1"""
    MODEL = "TK-278G"
    TYPE = "P2780"
    # Note that 16 CH don't have banks
    VARIANTS = {
        "P27805\xff":    (128, 136, 150, "C1"),
        "P27804\xff":    (128, 150, 174, "C"),
        "P2780\x15\xff": (16,  136, 150, "M1"),
        "P2780\x14\xff": (16,  150, 174, "M")
        }


@directory.register
class TK272G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-272G Radio K/K1"""
    MODEL = "TK-272G"
    TYPE = "P2720"
    VARIANTS = {
        "P2720\x05\xfb": (32, 136, 150, "K1"),
        "P2720\x04\xfb": (32, 150, 174, "K")
        }


@directory.register
class TK270G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-270G Radio K/K1/M/E/NE/NT"""
    MODEL = "TK-270G"
    TYPE = "P2700"
    VARIANTS = {
        "P2700T\xff":    (128, 146, 174, "NE/NT"),
        "P2700$\xff":    (128, 146, 174, "E"),
        "P2700\x14\xff": (128, 150, 174, "M"),
        "P2700\x05\xff": (128, 136, 150, "K1"),
        "P2700\x04\xff": (128, 150, 174, "K")
        }


@directory.register
class TK260G_Radios(Kenwood_Serie_60G):
    """Kenwood TK-260G Radio K/K1/M/E/NE/NT"""
    MODEL = "TK-260G"
    _hasbanks = False
    TYPE = "P2600"
    VARIANTS = {
        "P2600U\xff":    (8, 136, 150, "N1"),
        "P2600T\xff":    (8, 146, 174, "N"),
        "P2600$\xff":    (8, 150, 174, "E"),
        "P2600\x14\xff": (8, 150, 174, "M"),
        "P2600\x05\xff": (8, 136, 150, "K1"),
        "P2600\x04\xff": (8, 150, 174, "K")
        }
