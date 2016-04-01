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
    RadioSettings
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
UV2501_220pp_id = "      280528"
# B-TECH UV-2501+220
UV2501_220_fp = "M3G201"
# extra block read for the 2501+220
# the extra block is the same as the pp unit


# B-TECH UV-5001 pre-production units + 1st Gen radios
UV5001pp_fp = "V19204"
# B-TECH UV-5001 alpha units
UV5001alpha_fp = "V28204"
# B-TECH UV-5001 second generation (2G) radios
# !!!! This is the same as the UV-2501 (2G) Radios !!!!
UV5001G2_fp = "BTG214"
# B-TECH UV-5001 second generation (2G2)
UV5001G22_fp = "V2G204"


# WACCOM Mini-8900
MINI8900_fp = "M28854"


# QYT KT UV-980
KTUV980_fp = "H28854"

#### MAGICS
# for the Waccom Mini-8900
MSTRING_MINI8900 = "\x55\xA5\xB5\x45\x55\x45\x4d\x02"
# for the B-TECH UV-2501+220 (including pre production ones)
MSTRING_220 = "\x55\x20\x15\x12\x12\x01\x4d\x02"
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

        # the BTECH UV2501+220 have a trick only the upload, they must send
        # a ACK_CMD and read two bytes always ending on an ACK
        #
        # also the first block of TX must no have the ACK at the beginning
        # see _upload for this.
        if upload is True:
            # send a ACK, capture the answer
            _send(radio, ACK_CMD)
            ack = _rawrecv(radio, 2)

            if len(ack) != 2 or ack[1] != ACK_CMD:
                raise errors.RadioError("Radio didn't ACK the upload")

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
        rf.has_settings = False
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

        spmute = RadioSetting("spmute", "Speaker mute",
                              RadioSettingValueBoolean(bool(_mem.spmute)))
        mem.extra.append(spmute)

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
    _fileid = [UV2501_220_fp, UV2501_220pp_fp]
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
