# Copyright 2016:
# * Pavel Milanes CO7WT, <pavelmc@gmail.com>
# * Jim Unroe KC9HI, <rock.unroe@gmail.com>
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

import time
import struct
import logging

LOG = logging.getLogger(__name__)

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettings, InvalidValueError
from textwrap import dedent

MEM_FORMAT = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:4,
     scode:4;
  u8 unknown1:2,
     spmute:1,
     unknown2:3,
     optsig:2;
  u8 unknown3:3,
     scramble:1,
     unknown4:3,
     power:1;
  u8 unknown5:1,
     wide:1,
     unknown6:2,
     bcl:1,
     add:1,
     pttid:2;
} memory[200];

#seekto 0x0E00;
struct {
  u8 tdr;
  u8 unknown1;
  u8 sql;
  u8 unknown2[2];
  u8 tot;
  u8 apo;           // BTech radios use this as the Auto Power Off time
                    // other radios use this as pre-Time Out Alert
  u8 unknown3;
  u8 abr;
  u8 beep;
  u8 unknown4[4];
  u8 dtmfst;
  u8 unknown5[2];
  u8 prisc;
  u8 prich;
  u8 screv;
  u8 unknown6[2];
  u8 pttid;
  u8 pttlt;
  u8 unknown7;
  u8 emctp;
  u8 emcch;
  u8 ringt;
  u8 unknown8;
  u8 camdf;
  u8 cbmdf;
  u8 sync;          // BTech radios use this as the display sync setting
                    // other radios use this as the auto keypad lock setting
  u8 ponmsg;
  u8 wtled;
  u8 rxled;
  u8 txled;
  u8 unknown9[5];
  u8 anil;
  u8 reps;
  u8 repm;
  u8 tdrab;
  u8 ste;
  u8 rpste;
  u8 rptdl;
} settings;

#seekto 0x0E80;
struct {
  u8 unknown1;
  u8 vfomr;
  u8 keylock;
  u8 unknown2;
  u8 unknown3:4,
     vfomren:1,
     unknown4:1,
     reseten:1,
     menuen:1;
  u8 unknown5[11];
  u8 dispab;
  u8 mrcha;
  u8 mrchb;
  u8 menu;
} settings2;

#seekto 0x0EC0;
struct {
  char line1[6];
  char line2[6];
} poweron_msg;

struct settings_vfo {
  u8 freq[8];
  u8 unknown1;
  u8 offset[4];
  u8 unknown2[3];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 spmute;
  u8 optsig;
  u8 scramble;
  u8 wide;
  u8 power;
  u8 shiftd;
  u8 step;
  u8 unknown3[4];
};

#seekto 0x0F00;
struct {
  struct settings_vfo a;
  struct settings_vfo b;
} vfo;

#seekto 0x1000;
struct {
  char name[6];
  u8 unknown1[10];
} names[200];

#seekto 0x3C90;
struct {
  u8 vhf_low[3];
  u8 vhf_high[3];
  u8 uhf_low[3];
  u8 uhf_high[3];
} ranges;

// the 2501+220 has a different zone for storing ranges

#seekto 0x3CD0;
struct {
  u8 vhf_low[3];
  u8 vhf_high[3];
  u8 unknown1[4];
  u8 unknown2[6];
  u8 vhf2_low[3];
  u8 vhf2_high[3];
  u8 unknown3[4];
  u8 unknown4[6];
  u8 uhf_low[3];
  u8 uhf_high[3];
} ranges220;

#seekto 0x3F70;
struct {
  char fp[6];
} fingerprint;

"""

# A note about the memmory in these radios
#
# The real memory of these radios extends to 0x4000
# On read the factory software only uses up to 0x3200
# On write it just uploads the contents up to 0x3100
#
# The mem beyond 0x3200 holds the ID data

MEM_SIZE = 0x4000
BLOCK_SIZE = 0x40
TX_BLOCK_SIZE = 0x10
ACK_CMD = "\x06"
MODES = ["FM", "NFM"]
SKIP_VALUES = ["S", ""]
TONES = chirp_common.TONES
DTCS = sorted(chirp_common.DTCS_CODES + [645])
NAME_LENGTH = 6
PTTID_LIST = ["OFF", "BOT", "EOT", "BOTH"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 16)]
OPTSIG_LIST = ["OFF", "DTMF", "2TONE", "5TONE"]
SPMUTE_LIST = ["Tone/DTCS", "Tone/DTCS and Optsig", "Tone/DTCS or Optsig"]

LIST_TOT = ["%s sec" % x for x in range(15, 615, 15)]
LIST_TOA = ["Off"] + ["%s seconds" % x for x in range(1, 11)]
LIST_APO = ["Off"] + ["%s minutes" % x for x in range(30, 330, 30)]
LIST_ABR = ["Off"] + ["%s seconds" % x for x in range(1, 51)]
LIST_DTMFST = ["OFF", "Keyboard", "ANI", "Keyboad + ANI"]
LIST_SCREV = ["TO (timeout)", "CO (carrier operated)", "SE (search)"]
LIST_EMCTP = ["TX alarm sound", "TX ANI", "Both"]
LIST_RINGT = ["Off"] + ["%s seconds" % x for x in range(1, 10)]
LIST_MDF = ["Frequency", "Channel", "Name"]
LIST_PONMSG = ["Full", "Message", "Battery voltage"]
LIST_COLOR = ["Off", "Blue", "Orange", "Purple"]
LIST_REPS = ["1000 Hz", "1450 Hz", "1750 Hz", "2100Hz"]
LIST_REPM = ["Off", "Carrier", "CTCSS or DCS", "Tone", "DTMF"]
LIST_RPTDL = ["Off"] + ["%s ms" % x for x in range(1, 10)]
LIST_ANIL = ["3", "4", "5"]
LIST_AB = ["A", "B"]
LIST_VFOMR = ["Frequency", "Channel"]
LIST_SHIFT = ["Off", "+", "-"]
LIST_TXP = ["High", "Low"]
LIST_WIDE = ["Wide", "Narrow"]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
LIST_STEP = [str(x) for x in STEPS]

# This is a general serial timeout for all serial read functions.
# Practice has show that about 0.7 sec will be enough to cover all radios.
STIMEOUT = 0.7

# this var controls the verbosity in the debug and by default it's low (False)
# make it True and you will to get a very verbose debug.log
debug = False

# Power Levels
NORMAL_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=25),
                       chirp_common.PowerLevel("Low", watts=10)]
UV5001_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=50),
                       chirp_common.PowerLevel("Low", watts=10)]

# this must be defined globaly
POWER_LEVELS = None

# valid chars on the LCD, Note that " " (space) is stored as "\xFF"
VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
    "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"


##### ID strings #####################################################

# BTECH UV2501 pre-production units
UV2501pp_fp = "M2C294"
# BTECH UV2501 pre-production units 2 + and 1st Gen radios
UV2501pp2_fp = "M29204"
# B-TECH UV-2501 second generation (2G) radios
UV2501G2_fp = "BTG214"


# B-TECH UV-2501+220 pre-production units
UV2501_220pp_fp = "M3C281"
# extra block read for the 2501+220 pre-production units
# the same for all of this radios so far
UV2501_220pp_id = "      280528"
# B-TECH UV-2501+220
UV2501_220_fp = "M3G201"
# new variant, let's call it Generation 2
UV2501_220G2_fp = "BTG211"


# B-TECH UV-5001 pre-production units + 1st Gen radios
UV5001pp_fp = "V19204"
# B-TECH UV-5001 alpha units
UV5001alpha_fp = "V28204"
# B-TECH UV-5001 second generation (2G) radios
UV5001G2_fp = "BTG214"
# B-TECH UV-5001 second generation (2G2)
UV5001G22_fp = "V2G204"


# WACCOM Mini-8900
MINI8900_fp = "M28854"


# QYT KT-UV980 & JetStream JT2705M
KTUV980_fp = "H28854"


# QYT KT8900 & Juentai JT-6188
KT8900_fp = "M29154"
# this radio has an extra ID
KT8900_id = "      303688"


# Sainsonic GT890
GT890_fp = "M2G1F4"
# this need a second id
# and is the same of the QYT KT8900


#### MAGICS
# for the Waccom Mini-8900
MSTRING_MINI8900 = "\x55\xA5\xB5\x45\x55\x45\x4d\x02"
# for the B-TECH UV-2501+220 (including pre production ones)
MSTRING_220 = "\x55\x20\x15\x12\x12\x01\x4d\x02"
# for the QYT KT8900
MSTRING_KT8900 = "\x55\x20\x15\x09\x16\x45\x4D\x02"
# magic string for all other models
MSTRING = "\x55\x20\x15\x09\x20\x45\x4d\x02"


def _clean_buffer(radio):
    """Cleaning the read serial buffer, hard timeout to survive an infinite
    data stream"""

    # touching the serial timeout to optimize the flushing
    # restored at the end to the default value
    radio.pipe.setTimeout(0.1)
    dump = "1"
    datacount = 0

    try:
        while len(dump) > 0:
            dump = radio.pipe.read(100)
            datacount += len(dump)
            # hard limit to survive a infinite serial data stream
            # 5 times bigger than a normal rx block (69 bytes)
            if datacount > 345:
                seriale = "Please check your serial port selection."
                raise errors.RadioError(seriale)

        # restore the default serial timeout
        radio.pipe.setTimeout(STIMEOUT)

    except Exception:
        raise errors.RadioError("Unknown error cleaning the serial buffer")


def _rawrecv(radio, amount):
    """Raw read from the radio device, less intensive way"""

    data = ""

    try:
        data = radio.pipe.read(amount)

        # DEBUG
        if debug is True:
            LOG.debug("<== (%d) bytes:\n\n%s" %
                      (len(data), util.hexprint(data)))

        # fail if no data is received
        if len(data) == 0:
            raise errors.RadioError("No data received from radio")

        # notice on the logs if short
        if len(data) < amount:
            LOG.warn("Short reading %d bytes from the %d requested." %
                     (len(data), amount))

    except:
        raise errors.RadioError("Error reading data from radio")

    return data


def _send(radio, data):
    """Send data to the radio device"""

    try:
        for byte in data:
            radio.pipe.write(byte)

        # DEBUG
        if debug is True:
            LOG.debug("==> (%d) bytes:\n\n%s" %
                      (len(data), util.hexprint(data)))
    except:
        raise errors.RadioError("Error sending data to radio")


def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the headder format"""
    frame = "\x06" + struct.pack(">BHB", ord(cmd), addr, length)
    # add the data if set
    if len(data) != 0:
        frame += data

    return frame


def _recv(radio, addr):
    """Get data from the radio all at once to lower syscalls load"""

    # Get the full 69 bytes at a time to reduce load
    # 1 byte ACK + 4 bytes header + 64 bytes of data (BLOCK_SIZE)

    # get the whole block
    block = _rawrecv(radio, BLOCK_SIZE + 5)

    # basic check
    if len(block) < (BLOCK_SIZE + 5):
        raise errors.RadioError("Short read of the block 0x%04x" % addr)

    # checking for the ack
    if block[0] != ACK_CMD:
        raise errors.RadioError("Bad ack from radio in block 0x%04x" % addr)

    # header validation
    c, a, l = struct.unpack(">BHB", block[1:5])
    if a != addr or l != BLOCK_SIZE or c != ord("X"):
        LOG.debug("Invalid header for block 0x%04x" % addr)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Invalid header for block 0x%04x:" % addr)

    # return the data
    return block[5:]


def _start_clone_mode(radio, status):
    """Put the radio in clone mode and get the ident string, 3 tries"""

    # cleaning the serial buffer
    _clean_buffer(radio)

    # prep the data to show in the UI
    status.cur = 0
    status.msg = "Identifying the radio..."
    status.max = 3
    radio.status_fn(status)

    try:
        for a in range(0, status.max):
            # Update the UI
            status.cur = a + 1
            radio.status_fn(status)

            # send the magic word
            _send(radio, radio._magic)

            # Now you get a x06 of ACK if all goes well
            ack = radio.pipe.read(1)

            if ack == "\x06":
                # DEBUG
                LOG.info("Magic ACK received")
                status.cur = status.max
                radio.status_fn(status)

                return True

        return False

    except errors.RadioError:
        raise
    except Exception, e:
        raise errors.RadioError("Error sending Magic to radio:\n%s" % e)


def _do_ident(radio, status, upload=False):
    """Put the radio in PROGRAM mode & identify it"""
    #  set the serial discipline
    radio.pipe.setBaudrate(9600)
    radio.pipe.setParity("N")

    # open the radio into program mode
    if _start_clone_mode(radio, status) is False:
        raise errors.RadioError("Radio didn't entered in the clone mode")

    # Ok, get the ident string
    ident = _rawrecv(radio, 49)

    # basic check for the ident
    if len(ident) != 49:
        raise errors.RadioError("Radio send a short ident block.")

    # check if ident is OK
    itis = False
    for fp in radio._fileid:
        if fp in ident:
            itis = True
            break

    if itis is False:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    # some radios needs a extra read and check for a code on it, this ones
    # has the check value in the _id2 var, others simply False
    if radio._id2 is not False:
        # lower the timeout here as this radios are reseting due to timeout
        radio.pipe.setTimeout(0.05)

        # query & receive the extra ID
        _send(radio, _make_frame("S", 0x3DF0, 16))
        id2 = _rawrecv(radio, 21)

        # WARNING !!!!!!
        # different radios send a response with a different amount of data
        # it seems that it's padded with \xff, \x20 and some times with \x00
        # we just care about the first 16, our magic string is in there
        if len(id2) < 16:
            raise errors.RadioError("The extra ID is short, aborting.")

        # ok, the correct string must be in the received data
        if radio._id2 not in id2:
            LOG.debug("Full *BAD* extra ID on the %s is: \n%s" %
                      (radio.MODEL, util.hexprint(id2)))
            raise errors.RadioError("The extra ID is wrong, aborting.")

        # this radios need a extra request/answer here on the upload
        # the amount of data received depends of the radio type
        #
        # also the first block of TX must no have the ACK at the beginning
        # see _upload for this.
        if upload is True:
            # send an ACK
            _send(radio, ACK_CMD)

            # the amount of data depend on the radio, so far we have two radios
            # reading two bytes with an ACK at the end and just ONE with just
            # one byte (QYT KT8900)
            # the JT-6188 appears a clone of the last, but reads TWO bytes.
            #
            # we will read two bytes with a custom timeout to not penalize the
            # users for this.
            #
            # we just check for a response and last byte being a ACK, that is
            # the common stone for all radios (3 so far)
            ack = _rawrecv(radio, 2)

            # checking
            if len(ack) == 0 or ack[-1:] != ACK_CMD:
                raise errors.RadioError("Radio didn't ACK the upload")

            # restore the default serial timeout
            radio.pipe.setTimeout(STIMEOUT)

    # DEBUG
    LOG.info("Positive ident, this is a %s %s" % (radio.VENDOR, radio.MODEL))

    return True


def _download(radio):
    """Get the memory map"""

    # UI progress
    status = chirp_common.Status()

    # put radio in program mode and identify it
    _do_ident(radio, status)

    # the models that doesn't have the extra ID have to make a dummy read here
    if radio._id2 is False:
        _send(radio, _make_frame("S", 0, BLOCK_SIZE))
        discard = _rawrecv(radio, BLOCK_SIZE + 5)

        if debug is True:
            LOG.info("Dummy first block read done, got this:\n\n %s",
                     util.hexprint(discard))

    # reset the progress bar in the UI
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning from radio..."
    status.cur = 0
    radio.status_fn(status)

    # cleaning the serial buffer
    _clean_buffer(radio)

    data = ""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        # sending the read request
        _send(radio, _make_frame("S", addr, BLOCK_SIZE))

        # read
        d = _recv(radio, addr)

        # aggregate the data
        data += d

        # UI Update
        status.cur = addr / BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    return data


def _upload(radio):
    """Upload procedure"""

    # The UPLOAD mem is restricted to lower than 0x3100,
    # so we will overide that here localy
    MEM_SIZE = 0x3100

    # UI progress
    status = chirp_common.Status()

    # put radio in program mode and identify it
    _do_ident(radio, status, True)

    # get the data to upload to radio
    data = radio.get_mmap()

    # Reset the UI progress
    status.max = MEM_SIZE / TX_BLOCK_SIZE
    status.cur = 0
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the radios that doesn't have the extra ID 'may' do a dummy write, I found
    # that leveraging the bad ACK and NOT doing the dummy write is ok, as the
    # dummy write is accepted (it actually writes to the mem!) by the radio.

    # cleaning the serial buffer
    _clean_buffer(radio)

    # the fun start here
    for addr in range(0, MEM_SIZE, TX_BLOCK_SIZE):
        # getting the block of data to send
        d = data[addr:addr + TX_BLOCK_SIZE]

        # build the frame to send
        frame = _make_frame("X", addr, TX_BLOCK_SIZE, d)

        # first block must not send the ACK at the beginning for the
        # ones that has the extra id, since this have to do a extra step
        if addr == 0 and radio._id2 is not False:
            frame = frame[1:]

        # send the frame
        _send(radio, frame)

        # receiving the response
        ack = _rawrecv(radio, 1)

        # basic check
        if len(ack) != 1:
            raise errors.RadioError("No ACK when writing block 0x%04x" % addr)

        if not ack in "\x06\x05":
            raise errors.RadioError("Bad ACK writing block 0x%04x:" % addr)

         # UI Update
        status.cur = addr / TX_BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x3f70:0x3f76]

    if rid in cls._fileid:
        return True

    return False


def _decode_ranges(low, high):
    """Unpack the data in the ranges zones in the memmap and return
    a tuple with the integer corresponding to the Mhz it means"""
    ilow = int(low[0]) * 100 + int(low[1]) * 10 + int(low[2])
    ihigh = int(high[0]) * 100 + int(high[1]) * 10 + int(high[2])
    ilow *= 1000000
    ihigh *= 1000000

    return (ilow, ihigh)


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return False


class BTech(chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio):
    """BTECH's UV-5001 and alike radios"""
    VENDOR = "BTECH"
    MODEL = ""
    IDENT = ""
    _vhf_range = (130000000, 180000000)
    _220_range = (210000000, 231000000)
    _uhf_range = (400000000, 521000000)
    _upper = 199
    _magic = MSTRING
    _fileid = None
    _id2 = False

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is experimental.\n'
             '\n'
             'Please keep a copy of your memories with the original software '
             'if you treasure them, this driver is new and may contain'
             ' bugs.\n'
             '\n'
             )
        rp.pre_download = _(dedent("""\
            Follow these instructions to download your info:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio
            4 - Do the download of your radio data

            """))
        rp.pre_upload = _(dedent("""\
            Follow these instructions to upload your info:

            1 - Turn off your radio
            2 - Connect your interface cable
            3 - Turn on your radio
            4 - Do the upload of your radio data

            """))
        return rp

    def get_features(self):
        """Get the radio's features"""

        # we will use the following var as global
        global POWER_LEVELS

        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = MODES
        rf.valid_characters = VALID_CHARS
        rf.valid_name_length = NAME_LENGTH
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_skips = SKIP_VALUES
        rf.valid_dtcs_codes = DTCS
        rf.memory_bounds = (0, self._upper)

        # power levels
        if self.MODEL == "UV-5001":
            POWER_LEVELS = UV5001_POWER_LEVELS  # Higher power (50W)
        else:
            POWER_LEVELS = NORMAL_POWER_LEVELS  # Lower power (25W)

        rf.valid_power_levels = POWER_LEVELS

        # bands
        rf.valid_bands = [self._vhf_range, self._uhf_range]

        # 2501+220
        if self.MODEL == "UV-2501+220":
            rf.valid_bands.append(self._220_range)

        return rf

    def sync_in(self):
        """Download from radio"""
        data = _download(self)
        self._mmap = memmap.MemoryMap(data)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Error: %s" % e)

    def set_options(self):
        """This is to read the options from the image and set it in the
        environment, for now just the limits of the freqs in the VHF/UHF
        ranges"""

        # setting the correct ranges for each radio type
        if "+220" in self.MODEL:
            # the model 2501+220 has a segment in 220
            # and a different position in the memmap
            ranges = self._memobj.ranges220
        else:
            ranges = self._memobj.ranges

        # the normal dual bands
        vhf = _decode_ranges(ranges.vhf_low, ranges.vhf_high)
        uhf = _decode_ranges(ranges.uhf_low, ranges.uhf_high)

        # DEBUG
        LOG.info("Radio ranges: VHF %d to %d" % vhf)
        LOG.info("Radio ranges: UHF %d to %d" % uhf)

        # 220Mhz case
        if "+220" in self.MODEL:
            vhf2 = _decode_ranges(ranges.vhf2_low, ranges.vhf2_high)
            LOG.info("Radio ranges: VHF(220) %d to %d" % vhf2)
            self._220_range = vhf2

        # set the class with the real data
        self._vhf_range = vhf
        self._uhf_range = uhf

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

        # load specific parameters from the radio image
        self.set_options()

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        pol = None

        if val in [0, 65535]:
            return '', None, None
        elif val > 0x0258:
            a = val / 10.0
            return 'Tone', a, pol
        else:
            if val > 0x69:
                index = val - 0x6A
                pol = "R"
            else:
                index = val - 1
                pol = "N"

            tone = DTCS[index]
            return 'DTCS', tone, pol

    def _encode_tone(self, memval, mode, val, pol):
        """Parse the tone data to encode from UI to mem"""
        if mode == '' or mode is None:
            memval.set_raw("\x00\x00")
        elif mode == 'Tone':
            memval.set_value(val * 10)
        elif mode == 'DTCS':
            # detect the index in the DTCS list
            try:
                index = DTCS.index(val)
                if pol == "N":
                    index += 1
                else:
                    index += 0x6A
                memval.set_value(index)
            except:
                msg = "Digital Tone '%d' is not supported" % value
                LOG.error(msg)
                raise errors.RadioError(msg)
        else:
            msg = "Internal error: invalid mode '%s'" % mode
            LOG.error(msg)
            raise errors.InvalidDataError(msg)

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number]
        _names = self._memobj.names[number]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if _mem.get_raw()[0] == "\xFF":
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if _mem.get_raw()[4] == "\xFF":
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if _split(self.get_features(), mem.freq, int(_mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        # name TAG of the channel
        mem.name = str(_names.name).rstrip("\xFF").replace("\xFF", " ")

        # power
        mem.power = POWER_LEVELS[int(_mem.power)]

        # wide/narrow
        mem.mode = MODES[int(_mem.wide)]

        # skip
        mem.skip = SKIP_VALUES[_mem.add]

        # tone data
        rxtone = txtone = None
        txtone = self._decode_tone(_mem.txtone)
        rxtone = self._decode_tone(_mem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # Extra
        mem.extra = RadioSettingGroup("extra", "Extra")

        scramble = RadioSetting("scramble", "Scramble",
                                RadioSettingValueBoolean(bool(_mem.scramble)))
        mem.extra.append(scramble)

        bcl = RadioSetting("bcl", "Busy channel lockout",
                           RadioSettingValueBoolean(bool(_mem.bcl)))
        mem.extra.append(bcl)

        pttid = RadioSetting("pttid", "PTT ID",
                             RadioSettingValueList(PTTID_LIST,
                                                   PTTID_LIST[_mem.pttid]))
        mem.extra.append(pttid)

        # validating scode
        scode = _mem.scode if _mem.scode != 15 else 0
        pttidcode = RadioSetting("scode", "PTT ID signal code",
                                 RadioSettingValueList(
                                     PTTIDCODE_LIST,
                                     PTTIDCODE_LIST[scode]))
        mem.extra.append(pttidcode)

        optsig = RadioSetting("optsig", "Optional signaling",
                              RadioSettingValueList(
                                  OPTSIG_LIST,
                                  OPTSIG_LIST[_mem.optsig]))
        mem.extra.append(optsig)

        spmute = RadioSetting("spmute", "Speaker mute",
                              RadioSettingValueList(
                                  SPMUTE_LIST,
                                  SPMUTE_LIST[_mem.spmute]))
        mem.extra.append(spmute)

        return mem

    def set_memory(self, mem):
        """Set the memory data in the eeprom img from the UI"""
        # get the eprom representation of this channel
        _mem = self._memobj.memory[mem.number]
        _names = self._memobj.names[mem.number]

        # if empty memmory
        if mem.empty:
            # the channel itself
            _mem.set_raw("\xFF" * 16)
            # the name tag
            _names.set_raw("\xFF" * 16)
            return

        # frequency
        _mem.rxfreq = mem.freq / 10

        # duplex
        if mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "off":
            for i in _mem.txfreq:
                i.set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        else:
            _mem.txfreq = mem.freq / 10

        # tone data
        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.txtone, txmode, txtone, txpol)
        self._encode_tone(_mem.rxtone, rxmode, rxtone, rxpol)

        # name TAG of the channel
        if len(mem.name) < NAME_LENGTH:
            # we must pad to NAME_LENGTH chars, " " = "\xFF"
            mem.name = str(mem.name).ljust(NAME_LENGTH, " ")
        _names.name = str(mem.name).replace(" ", "\xFF")

        # power, # default power level is high
        _mem.power = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        # wide/narrow
        _mem.wide = MODES.index(mem.mode)

        # scan add property
        _mem.add = SKIP_VALUES.index(mem.skip)

        # reseting unknowns, this have to be set by hand
        _mem.unknown0 = 0
        _mem.unknown1 = 0
        _mem.unknown2 = 0
        _mem.unknown3 = 0
        _mem.unknown4 = 0
        _mem.unknown5 = 0
        _mem.unknown6 = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                setattr(_mem, setting.get_name(), setting.value)
        else:
            # there is no extra settings, load defaults
            _mem.spmute = 0
            _mem.optsig = 0
            _mem.scramble = 0
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.scode = 0

        return mem

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        other = RadioSettingGroup("other", "Other Settings")
        work = RadioSettingGroup("work", "Work Mode Settings")
        top = RadioSettings(basic, advanced, other, work)

        # Basic
        tdr = RadioSetting("settings.tdr", "Transceiver dual receive",
                           RadioSettingValueBoolean(_mem.settings.tdr))
        basic.append(tdr)

        sql = RadioSetting("settings.sql", "Squelch level",
                           RadioSettingValueInteger(0, 9, _mem.settings.sql))
        basic.append(sql)

        tot = RadioSetting("settings.tot", "Time out timer",
                           RadioSettingValueList(LIST_TOT, LIST_TOT[
                               _mem.settings.tot]))
        basic.append(tot)

        if self.MODEL in ("UV-2501", "UV-2501+220", "UV-5001"):
            apo = RadioSetting("settings.apo", "Auto power off timer",
                               RadioSettingValueList(LIST_APO, LIST_APO[
                                   _mem.settings.apo]))
            basic.append(apo)
        else:
            toa = RadioSetting("settings.apo", "Time out alert timer",
                               RadioSettingValueList(LIST_TOA, LIST_TOA[
                                   _mem.settings.apo]))
            basic.append(toa)

        abr = RadioSetting("settings.abr", "Backlight timer",
                           RadioSettingValueList(LIST_ABR, LIST_ABR[
                               _mem.settings.abr]))
        basic.append(abr)

        beep = RadioSetting("settings.beep", "Key beep",
                            RadioSettingValueBoolean(_mem.settings.beep))
        basic.append(beep)

        dtmfst = RadioSetting("settings.dtmfst", "DTMF side tone",
                              RadioSettingValueList(LIST_DTMFST, LIST_DTMFST[
                                  _mem.settings.dtmfst]))
        basic.append(dtmfst)

        prisc = RadioSetting("settings.prisc", "Priority scan",
                             RadioSettingValueBoolean(_mem.settings.prisc))
        basic.append(prisc)

        prich = RadioSetting("settings.prich", "Priority channel",
                             RadioSettingValueInteger(0, 199,
                                 _mem.settings.prich))
        basic.append(prich)

        screv = RadioSetting("settings.screv", "Scan resume method",
                             RadioSettingValueList(LIST_SCREV, LIST_SCREV[
                                 _mem.settings.screv]))
        basic.append(screv)

        pttlt = RadioSetting("settings.pttlt", "PTT transmit delay",
                             RadioSettingValueInteger(0, 30,
                                 _mem.settings.pttlt))
        basic.append(pttlt)

        emctp = RadioSetting("settings.emctp", "Alarm mode",
                             RadioSettingValueList(LIST_EMCTP, LIST_EMCTP[
                                 _mem.settings.emctp]))
        basic.append(emctp)

        emcch = RadioSetting("settings.emcch", "Alarm channel",
                             RadioSettingValueInteger(0, 199,
                                 _mem.settings.emcch))
        basic.append(emcch)

        ringt = RadioSetting("settings.ringt", "Ring time",
                             RadioSettingValueList(LIST_RINGT, LIST_RINGT[
                                 _mem.settings.ringt]))
        basic.append(ringt)

        camdf = RadioSetting("settings.camdf", "Display mode A",
                             RadioSettingValueList(LIST_MDF, LIST_MDF[
                                 _mem.settings.camdf]))
        basic.append(camdf)

        cbmdf = RadioSetting("settings.cbmdf", "Display mode B",
                             RadioSettingValueList(LIST_MDF, LIST_MDF[
                                 _mem.settings.cbmdf]))
        basic.append(cbmdf)

        if self.MODEL in ("UV-2501", "UV-2501+220", "UV-5001"):
           sync = RadioSetting("settings.sync", "A/B channel sync",
                               RadioSettingValueBoolean(_mem.settings.sync))
           basic.append(sync)
        else:
           autolk = RadioSetting("settings.sync", "Auto keylock",
                                 RadioSettingValueBoolean(_mem.settings.sync))
           basic.append(autolk)

        ponmsg = RadioSetting("settings.ponmsg", "Power-on message",
                              RadioSettingValueList(LIST_PONMSG, LIST_PONMSG[
                                  _mem.settings.ponmsg]))
        basic.append(ponmsg)

        wtled = RadioSetting("settings.wtled", "Standby backlight Color",
                             RadioSettingValueList(LIST_COLOR, LIST_COLOR[
                                 _mem.settings.wtled]))
        basic.append(wtled)

        rxled = RadioSetting("settings.rxled", "RX backlight Color",
                             RadioSettingValueList(LIST_COLOR, LIST_COLOR[
                                 _mem.settings.rxled]))
        basic.append(rxled)

        txled = RadioSetting("settings.txled", "TX backlight Color",
                             RadioSettingValueList(LIST_COLOR, LIST_COLOR[
                                 _mem.settings.txled]))
        basic.append(txled)

        anil = RadioSetting("settings.anil", "ANI length",
                            RadioSettingValueList(LIST_ANIL, LIST_ANIL[
                                _mem.settings.anil]))
        basic.append(anil)

        reps = RadioSetting("settings.reps", "Relay signal (tone burst)",
                            RadioSettingValueList(LIST_REPS, LIST_REPS[
                                _mem.settings.reps]))
        basic.append(reps)

        repm = RadioSetting("settings.repm", "Relay condition",
                            RadioSettingValueList(LIST_REPM, LIST_REPM[
                                _mem.settings.repm]))
        basic.append(repm)

        if self.MODEL in ("UV-2501", "UV-2501+220", "UV-5001"):
            tdrab = RadioSetting("settings.tdrab", "TDR return time",
                                 RadioSettingValueList(LIST_ABR, LIST_ABR[
                                     _mem.settings.tdrab]))
            basic.append(tdrab)

            ste = RadioSetting("settings.ste", "Squelch tail eliminate",
                               RadioSettingValueBoolean(_mem.settings.ste))
            basic.append(ste)

            rpste = RadioSetting("settings.rpste", "Repeater STE",
                                 RadioSettingValueList(LIST_RINGT, LIST_RINGT[
                                     _mem.settings.rpste]))
            basic.append(rpste)

            rptdl = RadioSetting("settings.rptdl", "Repeater STE delay",
                                 RadioSettingValueList(LIST_RPTDL, LIST_RPTDL[
                                     _mem.settings.rptdl]))
            basic.append(rptdl)

        # Advanced
        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in VALID_CHARS:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        _msg = self._memobj.poweron_msg
        line1 = RadioSetting("poweron_msg.line1", "Power-on message line 1",
                             RadioSettingValueString(0, 6, _filter(
                                 _msg.line1)))
        advanced.append(line1)
        line2 = RadioSetting("poweron_msg.line2", "Power-on message line 2",
                             RadioSettingValueString(0, 6, _filter(
                                 _msg.line2)))
        advanced.append(line2)

        if self.MODEL in ("UV-2501", "UV-5001"):
            vfomren = RadioSetting("settings2.vfomren", "VFO/MR switching",
                                   RadioSettingValueBoolean(
                                       not _mem.settings2.vfomren))
            advanced.append(vfomren)

            reseten = RadioSetting("settings2.reseten", "RESET",
                                   RadioSettingValueBoolean(
                                       _mem.settings2.reseten))
            advanced.append(reseten)

            menuen = RadioSetting("settings2.menuen", "Menu",
                                  RadioSettingValueBoolean(
                                      _mem.settings2.menuen))
            advanced.append(menuen)

        # Other
        def convert_bytes_to_limit(bytes):
            limit = ""
            for byte in bytes:
                if byte < 10:
                    limit += chr(byte + 0x30)
                else:
                    break
            return limit

        if "+220" in self.MODEL:
            _ranges = self._memobj.ranges220
            ranges = "ranges220"
        else:
            _ranges = self._memobj.ranges
            ranges = "ranges"

        _limit = convert_bytes_to_limit(_ranges.vhf_low)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        vhf_low = RadioSetting("%s.vhf_low" % ranges, "VHF low", val)
        other.append(vhf_low)

        _limit = convert_bytes_to_limit(_ranges.vhf_high)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        vhf_high = RadioSetting("%s.vhf_high" % ranges, "VHF high", val)
        other.append(vhf_high)

        if "+220" in self.MODEL:
            _limit = convert_bytes_to_limit(_ranges.vhf2_low)
            val = RadioSettingValueString(0, 3, _limit)
            val.set_mutable(False)
            vhf2_low = RadioSetting("%s.vhf2_low" % ranges, "VHF2 low", val)
            other.append(vhf2_low)

            _limit = convert_bytes_to_limit(_ranges.vhf2_high)
            val = RadioSettingValueString(0, 3, _limit)
            val.set_mutable(False)
            vhf2_high = RadioSetting("%s.vhf2_high" % ranges, "VHF2 high", val)
            other.append(vhf2_high)

        _limit = convert_bytes_to_limit(_ranges.uhf_low)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        uhf_low = RadioSetting("%s.uhf_low" % ranges, "UHF low", val)
        other.append(uhf_low)

        _limit = convert_bytes_to_limit(_ranges.uhf_high)
        val = RadioSettingValueString(0, 3, _limit)
        val.set_mutable(False)
        uhf_high = RadioSetting("%s.uhf_high" % ranges, "UHF high", val)
        other.append(uhf_high)

        val = RadioSettingValueString(0, 6, _filter(_mem.fingerprint.fp))
        val.set_mutable(False)
        fp = RadioSetting("fingerprint.fp", "Fingerprint", val)
        other.append(fp)

        # Work
        dispab = RadioSetting("settings2.dispab", "Display",
                              RadioSettingValueList(LIST_AB,LIST_AB[
                                  _mem.settings2.dispab]))
        work.append(dispab)

        vfomr = RadioSetting("settings2.vfomr", "VFO/MR mode",
                             RadioSettingValueList(LIST_VFOMR,LIST_VFOMR[
                                 _mem.settings2.vfomr]))
        work.append(vfomr)

        keylock = RadioSetting("settings2.keylock", "Keypad lock",
                           RadioSettingValueBoolean(_mem.settings2.keylock))
        work.append(keylock)

        mrcha = RadioSetting("settings2.mrcha", "MR A channel",
                             RadioSettingValueInteger(0, 199,
                                 _mem.settings2.mrcha))
        work.append(mrcha)

        mrchb = RadioSetting("settings2.mrchb", "MR B channel",
                             RadioSettingValueInteger(0, 199,
                                 _mem.settings2.mrchb))
        work.append(mrchb)

        def convert_bytes_to_freq(bytes):
            real_freq = 0
            for byte in bytes:
                real_freq = (real_freq * 10) + byte
            return chirp_common.format_freq(real_freq * 10)

        def my_validate(value):
            value = chirp_common.parse_freq(value)
            print value
            if 180000000 <= value and value < 210000000:
                msg = ("Can't be between 180.00000-210.00000")
                raise InvalidValueError(msg)
            elif 231000000 <= value and value < 400000000:
                msg = ("Can't be between 231.00000-400.00000")
                raise InvalidValueError(msg)
            elif 210000000 <= value and value < 231000000 \
                and "+220" not in self.MODEL:
                msg = ("Can't be between 180.00000-400.00000")
                raise InvalidValueError(msg)
            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(0, 10, convert_bytes_to_freq(
                                        _mem.vfo.a.freq))
        val1a.set_validate_callback(my_validate)
        vfoafreq = RadioSetting("vfo.a.freq", "VFO A frequency", val1a)
        vfoafreq.set_apply_callback(apply_freq, _mem.vfo.a)
        work.append(vfoafreq)

        val1b = RadioSettingValueString(0, 10, convert_bytes_to_freq(
                                        _mem.vfo.b.freq))
        val1b.set_validate_callback(my_validate)
        vfobfreq = RadioSetting("vfo.b.freq", "VFO B frequency", val1b)
        vfobfreq.set_apply_callback(apply_freq, _mem.vfo.b)
        work.append(vfobfreq)

        vfoashiftd = RadioSetting("vfo.a.shiftd", "VFO A shift",
                                  RadioSettingValueList(LIST_SHIFT, LIST_SHIFT[
                                      _mem.vfo.a.shiftd]))
        work.append(vfoashiftd)

        vfobshiftd = RadioSetting("vfo.b.shiftd", "VFO B shift",
                                  RadioSettingValueList(LIST_SHIFT, LIST_SHIFT[
                                      _mem.vfo.b.shiftd]))
        work.append(vfobshiftd)

        def convert_bytes_to_offset(bytes):
            real_offset = 0
            for byte in bytes:
                real_offset = (real_offset * 10) + byte
            return chirp_common.format_freq(real_offset * 10000)

        def apply_offset(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10000
            for i in range(3, -1, -1):
                obj.offset[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(0, 10, convert_bytes_to_offset(
                                        _mem.vfo.a.offset))
        vfoaoffset = RadioSetting("vfo.a.offset",
                                  "VFO A offset (0.00-99.95)", val1a)
        vfoaoffset.set_apply_callback(apply_offset, _mem.vfo.a)
        work.append(vfoaoffset)

        val1b = RadioSettingValueString(0, 10, convert_bytes_to_offset(
                                        _mem.vfo.b.offset))
        vfoboffset = RadioSetting("vfo.b.offset",
                                  "VFO B offset (0.00-99.95)", val1b)
        vfoboffset.set_apply_callback(apply_offset, _mem.vfo.b)
        work.append(vfoboffset)

        vfoatxp = RadioSetting("vfo.a.power", "VFO A power",
                                RadioSettingValueList(LIST_TXP,LIST_TXP[
                                    _mem.vfo.a.power]))
        work.append(vfoatxp)

        vfobtxp = RadioSetting("vfo.b.power", "VFO B power",
                                RadioSettingValueList(LIST_TXP,LIST_TXP[
                                    _mem.vfo.b.power]))
        work.append(vfobtxp)

        vfoawide = RadioSetting("vfo.a.wide", "VFO A bandwidth",
                                RadioSettingValueList(LIST_WIDE,LIST_WIDE[
                                    _mem.vfo.a.wide]))
        work.append(vfoawide)

        vfobwide = RadioSetting("vfo.b.wide", "VFO B bandwidth",
                                RadioSettingValueList(LIST_WIDE,LIST_WIDE[
                                    _mem.vfo.b.wide]))
        work.append(vfobwide)

        vfoastep = RadioSetting("vfo.a.step", "VFO A step",
                                RadioSettingValueList(LIST_STEP,LIST_STEP[
                                    _mem.vfo.a.step]))
        work.append(vfoastep)

        vfobstep = RadioSetting("vfo.b.step", "VFO B step",
                                RadioSettingValueList(LIST_STEP,LIST_STEP[
                                    _mem.vfo.b.step]))
        work.append(vfobstep)

        vfoaoptsig = RadioSetting("vfo.a.optsig", "VFO A optional signal",
                                  RadioSettingValueList(OPTSIG_LIST,
                                      OPTSIG_LIST[_mem.vfo.a.optsig]))
        work.append(vfoaoptsig)

        vfoboptsig = RadioSetting("vfo.b.optsig", "VFO B optional signal",
                                  RadioSettingValueList(OPTSIG_LIST,
                                      OPTSIG_LIST[_mem.vfo.b.optsig]))
        work.append(vfoboptsig)

        vfoaspmute = RadioSetting("vfo.a.spmute", "VFO A speaker mute",
                                  RadioSettingValueList(SPMUTE_LIST,
                                      SPMUTE_LIST[_mem.vfo.a.spmute]))
        work.append(vfoaspmute)

        vfobspmute = RadioSetting("vfo.b.spmute", "VFO B speaker mute",
                                  RadioSettingValueList(SPMUTE_LIST,
                                      SPMUTE_LIST[_mem.vfo.b.spmute]))
        work.append(vfobspmute)

        vfoascr = RadioSetting("vfo.a.scramble", "VFO A scramble",
                               RadioSettingValueBoolean(_mem.vfo.a.scramble))
        work.append(vfoascr)

        vfobscr = RadioSetting("vfo.b.scramble", "VFO B scramble",
                               RadioSettingValueBoolean(_mem.vfo.b.scramble))
        work.append(vfobscr)

        vfoascode = RadioSetting("vfo.a.scode", "VFO A PTT-ID",
                                 RadioSettingValueList(PTTIDCODE_LIST,
                                     PTTIDCODE_LIST[_mem.vfo.a.scode]))
        work.append(vfoascode)

        vfobscode = RadioSetting("vfo.b.scode", "VFO B PTT-ID",
                                 RadioSettingValueList(PTTIDCODE_LIST,
                                     PTTIDCODE_LIST[_mem.vfo.b.scode]))
        work.append(vfobscode)

        pttid = RadioSetting("settings.pttid", "PTT ID",
                             RadioSettingValueList(PTTID_LIST,
                                 PTTID_LIST[_mem.settings.pttid]))
        work.append(pttid)

        return top

    def set_settings(self, settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() == "fm_preset":
                    self._set_fm_preset(element)
                else:
                    self.set_settings(element)
                    continue
            else:
                try:
                    name = element.get_name()
                    if "." in name:
                        bits = name.split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
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
                    elif setting == "vfomren":
                        setattr(obj, setting, not int(element.value))
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

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


@directory.register
class UV2501(BTech):
    """Baofeng Tech UV2501"""
    MODEL = "UV-2501"
    _fileid = [UV2501G2_fp, UV2501pp2_fp, UV2501pp_fp]


@directory.register
class UV2501_220(BTech):
    """Baofeng Tech UV2501+220"""
    MODEL = "UV-2501+220"
    _magic = MSTRING_220
    _fileid = [UV2501_220G2_fp, UV2501_220_fp, UV2501_220pp_fp]
    _id2 = UV2501_220pp_id


@directory.register
class UV5001(BTech):
    """Baofeng Tech UV5001"""
    MODEL = "UV-5001"
    _fileid = [UV5001G22_fp, UV5001G2_fp, UV5001alpha_fp, UV5001pp_fp]


@directory.register
class MINI8900(BTech):
    """WACCOM MINI-8900"""
    VENDOR = "WACCOM"
    MODEL = "MINI-8900"
    _magic = MSTRING_MINI8900
    _fileid = [MINI8900_fp, ]


@directory.register
class KTUV980(BTech):
    """QYT KT-UV980"""
    VENDOR = "QYT"
    MODEL = "KT-UV980"
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_MINI8900
    _fileid = [KTUV980_fp, ]


@directory.register
class KT9800(BTech):
    """QYT KT8900"""
    VENDOR = "QYT"
    MODEL = "KT8900"
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900
    _fileid = [KT8900_fp, ]
    _id2 = KT8900_id


@directory.register
class GT890(BTech):
    """Sainsonic GT890"""
    VENDOR = "Sainsonic"
    MODEL = "GT-890"
    # ranges are the same as btech's defaults
    _magic = MSTRING_KT8900
    _fileid = [GT890_fp, ]
    _id2 = KT8900_id
