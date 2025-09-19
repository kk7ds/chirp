# Copyright 2016-2023:
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

import struct
import logging

from time import sleep
from chirp.drivers import baofeng_common as bfc
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, InvalidValueError
from chirp import settings

LOG = logging.getLogger(__name__)

# A note about the memory in these radios
#
# The real memory of these radios extends to 0x4000
# On read the factory software only uses up to 0x3200
# On write it just uploads the contents up to 0x3100
#
# The mem beyond 0x3200 holds the ID data

MEM_SIZE = 0x4000
BLOCK_SIZE = 0x40
TX_BLOCK_SIZE = 0x10
ACK_CMD = 0x06
MODES = ["FM", "NFM"]
SKIP_VALUES = ["S", ""]
TONES = chirp_common.TONES
DTCS = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

# lists related to "extra" settings
PTTID_LIST = ["OFF", "BOT", "EOT", "BOTH"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 16)]
OPTSIG_LIST = ["OFF", "DTMF", "2TONE", "5TONE"]
SPMUTE_LIST = ["Tone/DTCS", "Tone/DTCS and Optsig", "Tone/DTCS or Optsig"]

# lists
LIST_AB = ["A", "B"]
LIST_ABC = LIST_AB + ["C"]
LIST_ABCD = LIST_AB + ["C", "D"]
LIST_ANIL = ["3", "4", "5"]
LIST_APO = ["Off"] + ["%s minutes" % x for x in range(30, 330, 30)]
LIST_COLOR4 = ["Off", "Blue", "Orange", "Purple"]
LIST_COLOR8 = ["White", "Red", "Blue", "Green", "Yellow", "Indigo",
               "Purple", "Gray"]
LIST_COLOR9 = ["Black"] + LIST_COLOR8
LIST_DTMFST = ["OFF", "Keyboard", "ANI", "Keyboard + ANI"]
LIST_EARPH = ["Off", "Earphone", "Earphone + Speaker"]
LIST_EMCTP = ["TX alarm sound", "TX ANI", "Both"]
LIST_EMCTPX = ["Off"] + LIST_EMCTP
LIST_LANGUA = ["English", "Chinese"]
LIST_MDF = ["Frequency", "Channel", "Name"]
LIST_OFF1TO9 = ["Off"] + ["%s seconds" % x for x in range(1, 10)]
LIST_OFF1TO10 = ["Off"] + ["%s seconds" % x for x in range(1, 11)]
LIST_OFF1TO50 = ["Off"] + ["%s seconds" % x for x in range(1, 51)]
LIST_OFF1TO60 = ["Off"] + ["%s seconds" % x for x in range(1, 61)]
LIST_PONMSG = ["Full", "Message", "Battery voltage"]
LIST_REPM = ["Off", "Carrier", "CTCSS or DCS", "Tone", "DTMF"]
LIST_REPS = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
LIST_REPSW = ["Off", "RX", "TX"]
LIST_RPTDL = ["Off"] + ["%s ms" % x for x in range(1, 11)]
LIST_SCMODE = ["Off", "PTT-SC", "MEM-SC", "PON-SC"]
LIST_SHIFT = ["Off", "+", "-"]
LIST_SKIPTX = ["Off", "Skip 1", "Skip 2"]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
LIST_STEP = [str(x) for x in STEPS]
LIST_SYNC = ["Off", "AB", "CD", "AB+CD"]
LIST_SYNCV2 = ["Off", "AB", "AC", "BC", "ABC"]
# the first 12 TMR choices common to all 4-line color display mobile radios
LIST_TMR12 = ["OFF", "M+A", "M+B", "M+C", "M+D", "M+A+B", "M+A+C", "M+A+D",
              "M+B+C", "M+B+D", "M+C+D", "M+A+B+C"]
# the 16 choice list for color display mobile radios that correctly implement
# the full 16 TMR choices
LIST_TMR16 = LIST_TMR12 + ["M+A+B+D", "M+A+C+D", "M+B+C+D", "A+B+C+D"]
# the 15 choice list for color mobile radios that are missing the M+A+B+D
# choice in the TMR menu
LIST_TMR15 = LIST_TMR12 + ["M+A+C+D", "M+B+C+D", "A+B+C+D"]
# the 7 TMR choices for the 3-line color display mobile radios
LIST_TMR7 = ["OFF", "M+A", "M+B", "M+C", "M+AB", "M+AC", "M+BC", "M+ABC"]
LIST_TMRTX = ["Track", "Fixed"]
LIST_TOT = ["%s sec" % x for x in range(15, 615, 15)]
LIST_TXDISP = ["Power", "Mic Volume"]
LIST_TXP = ["High", "Low"]
LIST_TXP3 = ["High", "Mid", "Low"]
LIST_SCREV = ["TO (timeout)", "CO (carrier operated)", "SE (search)"]
LIST_VFOMR = ["Frequency", "Channel"]
LIST_VOICE = ["Off"] + LIST_LANGUA
LIST_VOX = ["Off"] + ["%s" % x for x in range(1, 11)]
LIST_VOXT = ["%s seconds" % x for x in range(0, 21)]
LIST_WIDE = ["Wide", "Narrow"]

# lists related to DTMF, 2TONE and 5TONE settings
LIST_5TONE_STANDARDS = ["CCIR1", "CCIR2", "PCCIR", "ZVEI1", "ZVEI2", "ZVEI3",
                        "PZVEI", "DZVEI", "PDZVEI", "EEA", "EIA", "EURO",
                        "CCITT", "NATEL", "MODAT", "none"]
LIST_5TONE_STANDARDS_without_none = ["CCIR1", "CCIR2", "PCCIR", "ZVEI1",
                                     "ZVEI2", "ZVEI3",
                                     "PZVEI", "DZVEI", "PDZVEI", "EEA", "EIA",
                                     "EURO", "CCITT", "NATEL", "MODAT"]
LIST_5TONE_STANDARD_PERIODS = ["20", "30", "40", "50", "60", "70", "80", "90",
                               "100", "110", "120", "130", "140", "150", "160",
                               "170", "180", "190", "200"]
LIST_5TONE_DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "A",
                     "B", "C", "D", "E", "F"]
LIST_5TONE_DELAY = ["%s ms" % x for x in range(0, 1010, 10)]
LIST_5TONE_RESET = ["%s ms" % x for x in range(100, 8100, 100)]
LIST_5TONE_RESET_COLOR = ["%s ms" % x for x in range(100, 20100, 100)]
LIST_DTMF_SPEED = ["%s ms" % x for x in range(50, 2010, 10)]
LIST_DTMF_DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B",
                    "C", "D", "#", "*"]
LIST_DTMF_VALUES = [0x0A, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09,
                    0x0D, 0x0E, 0x0F, 0x00, 0x0C, 0x0B]
LIST_DTMF_SPECIAL_DIGITS = ["*", "#", "A", "B", "C", "D"]
LIST_DTMF_SPECIAL_VALUES = [0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x00]
LIST_DTMF_DELAY = ["%s ms" % x for x in range(100, 4100, 100)]
CHARSET_DTMF_DIGITS = "0123456789AaBbCcDd#*"
LIST_2TONE_DEC = ["A-B", "A-C", "A-D",
                  "B-A", "B-C", "B-D",
                  "C-A", "C-B", "C-D",
                  "D-A", "D-B", "D-C"]
LIST_2TONE_RESPONSE = ["None", "Alert", "Transpond", "Alert+Transpond"]

# This is a general serial timeout for all serial read functions.
STIMEOUT = 0.25

# this var controls the verbosity in the debug and by default it's low (False)
# make it True and you will to get a very verbose debug.log
debug = False

# valid chars on the LCD, Note that " " (space) is stored as "\xFF"
VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
    "`{|}!\"#$%&'()*+,-./:;<=>?@[]^_"

GMRS_FREQS1 = [462562500, 462587500, 462612500, 462637500, 462662500,
               462687500, 462712500]
GMRS_FREQS2 = [467562500, 467587500, 467612500, 467637500, 467662500,
               467687500, 467712500]
GMRS_FREQS3 = [462550000, 462575000, 462600000, 462625000, 462650000,
               462675000, 462700000, 462725000]
GMRS_FREQS = GMRS_FREQS1 + GMRS_FREQS2 + GMRS_FREQS3 * 2


# #### ID strings #####################################################

# BTECH UV2501 pre-production units
UV2501pp_fp = b"M2C294"
# BTECH UV2501 pre-production units 2 + and 1st Gen radios
UV2501pp2_fp = b"M29204"
# B-TECH UV-2501 second generation (2G) radios
UV2501G2_fp = b"BTG214"
# B-TECH UV-2501 third generation (3G) radios
UV2501G3_fp = b"BTG324"

# B-TECH UV-2501+220 pre-production units
UV2501_220pp_fp = b"M3C281"
# B-TECH UV-2501+220
UV2501_220_fp = b"M3G201"
# new variant, let's call it Generation 2
UV2501_220G2_fp = b"BTG211"
# B-TECH UV-2501+220 third generation (3G)
UV2501_220G3_fp = b"BTG311"

# B-TECH UV-5001 pre-production units + 1st Gen radios
UV5001pp_fp = b"V19204"
# B-TECH UV-5001 alpha units
UV5001alpha_fp = b"V28204"
# B-TECH UV-5001 second generation (2G) radios
UV5001G2_fp = b"BTG214"
# B-TECH UV-5001 second generation (2G2)
UV5001G22_fp = b"V2G204"
# B-TECH UV-5001 third generation (3G)
UV5001G3_fp = b"BTG304"

# B-TECH UV-25X2
UV25X2_fp = b"UC2012"

# B-TECH UV-25X2 Second Generation (G2)
UV25X2G2_fp = b"UCB282"

# B-TECH UV-25X4
UV25X4_fp = b"UC4014"

# B-TECH UV-25X4 Second Generation (G2)
UV25X4G2_fp = b"UCB284"

# B-TECH UV-50X2
UV50X2_fp = b"UC2M12"

# B-TECH GMRS-50X1
GMRS50X1_fp = b"NC1802"
GMRS50X1_fp1 = b"NC1932"

# B-TECH GMRS-20V2
GMRS20V2_fp = b"WP4204"
GMRS20V2_fp1 = b"VW2112"
GMRS20V2_fp2 = b"VWG728"

# special var to know when we found a BTECH Gen 3
BTECH3 = [UV2501G3_fp, UV2501_220G3_fp, UV5001G3_fp]


# WACCOM Mini-8900
MINI8900_fp = b"M28854"


# QYT KT-UV980
KTUV980_fp = b"H28854"

# QYT KT8900
KT8900_fp = b"M29154"
# New generations KT8900
KT8900_fp1 = b"M2C234"
KT8900_fp2 = b"M2G1F4"
KT8900_fp3 = b"M2G2F4"
KT8900_fp4 = b"M2G304"
KT8900_fp5 = b"M2G314"
KT8900_fp6 = b"M2G424"
KT8900_fp7 = b"M27184"
KT8900_fp8 = b"M2C194"

# KT8900R
KT8900R_fp = b"M3G1F4"
# Second Generation
KT8900R_fp1 = b"M3G214"
# another model
KT8900R_fp2 = b"M3C234"
# another model G4?
KT8900R_fp3 = b"M39164"
# another model
KT8900R_fp4 = b"M3G314"
# AC3MB: another id
KT8900R_fp5 = b"M3B064"

# KT7900D (quad band)
KT7900D_fp = b"VC4004"
KT7900D_fp1 = b"VC4284"
KT7900D_fp2 = b"VC4264"
KT7900D_fp3 = b"VC4114"
KT7900D_fp4 = b"VC4104"
KT7900D_fp5 = b"VC4254"
KT7900D_fp6 = b"VC5264"
KT7900D_fp7 = b"VC9204"
KT7900D_fp8 = b"VC9214"
KT7900D_fp9 = b"VC5302"
KT7900D_fp10 = b"VC5254"

# QB25 (quad band) - a clone of KT7900D
QB25_fp = b"QB-25"

# KT8900D (dual band)
KT8900D_fp = b"VC2002"
KT8900D_fp1 = b"VC8632"
KT8900D_fp2 = b"VC3402"
KT8900D_fp3 = b"VC7062"
KT8900D_fp4 = b"VC3062"
KT8900D_fp5 = b"VC8192"

# LUITON LT-588UV
LT588UV_fp = b"V2G1F4"
# Added by rstrickoff gen 2 id
LT588UV_fp1 = b"V2G214"

# QYT KT-8R (quad band ht)
KT8R_fp = b"MCB264"
KT8R_fp1 = b"MCB284"
KT8R_fp2 = b"MC5264"
KT8R_fp3 = b"MCB254"

# QYT KT5800 (dual band)
KT5800_fp = b"VCB222"

# QYT KT980Plus (dual band)
KT980PLUS_fp = b"VC2002"
KT980PLUS_fp1 = b"VC6042"

# Radioddity DB25-G (gmrs)
DB25G_fp = b"VC6182"
DB25G_fp1 = b"VC7062"

# QYT KT-WP12 and KT-9900
KTWP12_fp = b"WP3094"

# Anysecu WP-9900
WP9900_fp = b"WP3094"

# QYT KT-5000
KT5000_fp = b"WP9114"


# ### MAGICS
# for the Waccom Mini-8900
MSTRING_MINI8900 = b"\x55\xA5\xB5\x45\x55\x45\x4d\x02"
# for the B-TECH UV-2501+220 (including pre production ones)
MSTRING_220 = b"\x55\x20\x15\x12\x12\x01\x4d\x02"
# for the QYT KT8900 & R
MSTRING_KT8900 = b"\x55\x20\x15\x09\x16\x45\x4D\x02"
MSTRING_KT8900R = b"\x55\x20\x15\x09\x25\x01\x4D\x02"
# magic string for all other models
MSTRING = b"\x55\x20\x15\x09\x20\x45\x4d\x02"
# for the QYT KT7900D & KT8900D
MSTRING_KT8900D = b"\x55\x20\x16\x08\x01\xFF\xDC\x02"
# for the BTECH UV-25X2 and UV-50X2
MSTRING_UV25X2 = b"\x55\x20\x16\x12\x28\xFF\xDC\x02"
# for the BTECH UV-25X4
MSTRING_UV25X4 = b"\x55\x20\x16\x11\x18\xFF\xDC\x02"
# for the BTECH GMRS-50X1
MSTRING_GMRS50X1 = b"\x55\x20\x18\x10\x18\xFF\xDC\x02"
# for the BTECH GMRS-20V2
MSTRING_GMRS20V2 = b"\x55\x20\x21\x03\x27\xFF\xDC\x02"
# for the QYT KT-8R
MSTRING_KT8R = b"\x55\x20\x17\x07\x03\xFF\xDC\x02"
# for the QYT KT-WP12, KT-9900 and Anysecu WP-9900
MSTRING_KTWP12 = b"\x55\x20\x18\x11\x02\xFF\xDC\x02"
# for the QYT KT-5000
MSTRING_KT5000 = b"\x55\x20\x21\x01\x23\xFF\xDC\x02"


def _clean_buffer(radio):
    """Cleaning the read serial buffer, hard timeout to survive an infinite
    data stream"""

    # touching the serial timeout to optimize the flushing
    # restored at the end to the default value
    radio.pipe.timeout = 0.1
    dump = b"1"
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
        radio.pipe.timeout = STIMEOUT

    except Exception:
        raise errors.RadioError("Unknown error cleaning the serial buffer")


def _rawrecv(radio, amount):
    """Raw read from the radio device, less intensive way"""

    data = b""

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
        radio.pipe.write(bytes(data))

        # DEBUG
        if debug is True:
            LOG.debug("==> (%d) bytes:\n\n%s" %
                      (len(data), util.hexprint(data)))
    except:
        raise errors.RadioError("Error sending data to radio")


def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the header format"""
    frame = b"\x06" + struct.pack(">BHB", ord(cmd), addr, length)
    # add the data if set
    if len(data) != 0:
        frame += data

    return frame


def _recv(radio, addr):
    """Get data from the radio all at once to lower syscalls load"""

    # Get the full 69 bytes at a time to reduce load
    # 1 byte ACK + 4 bytes header + 64 bytes of data (BLOCK_SIZE)

    # get the whole block Bug #11851 BLOCKSIZE fix for KT-8900D
    block = _rawrecv(radio, radio._block_size + 5)

    # basic check Bug #11851 BLOCKSIZE fix for KT-8900D
    if len(block) < (radio._block_size + 5):
        raise errors.RadioError("Short read of the block 0x%04x" % addr)

    # checking for the ack
    if block[0] != ACK_CMD:
        raise errors.RadioError("Bad ack from radio in block 0x%04x" % addr)

    # header validation
    c, a, l = struct.unpack(">BHB", block[1:5])
    if a != addr or l != radio._block_size or c != ord("X"):
        LOG.debug("Invalid header for block 0x%04x" % addr)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Invalid header for block 0x%04x:" % addr)

    # return the data
    return block[5:]


def _do_ident(radio, status, upload=False):
    """Put the radio in PROGRAM mode & identify it"""
    #  set the serial discipline
    radio.pipe.baudrate = 9600
    radio.pipe.parity = "N"

    # lengthen the timeout here as these radios are resetting due to timeout
    radio.pipe.timeout = 0.75

    # send the magic word
    _send(radio, radio._magic)

    # Now you get a 50 byte reply if all goes well
    ident = _rawrecv(radio, 50)

    # checking for the ack
    if ident[0] != ACK_CMD:
        raise errors.RadioError("Bad ack from radio")

    # basic check for the ident block
    if len(ident) != 50:
        raise errors.RadioError("Radio send a short ident block.")

    # check if ident is OK
    itis = False
    for fp in radio._fileid:
        if fp in ident:
            # got it!
            itis = True
            # checking if we are dealing with a Gen 3 BTECH
            if radio.VENDOR == "BTECH" and fp in BTECH3:
                radio.btech3 = True

            break

    if itis is False:
        LOG.debug("Incorrect model ID, got this:\n\n" + util.hexprint(ident))
        raise errors.RadioError("Radio identification failed.")

    # pause here for the radio to catch up
    sleep(0.1)

    # the OEM software reads this additional block, so we will, too

    # Get the full 21 bytes at a time to reduce load
    # 1 byte ACK + 4 bytes header + 16 bytes of data (BLOCK_SIZE)
    frame = _make_frame("S", 0x3DF0, 16)
    _send(radio, frame)
    id2 = _rawrecv(radio, 21)

    # restore the default serial timeout
    radio.pipe.timeout = STIMEOUT

    # checking for the ack
    if id2[:1] not in b"\x06\x05":
        raise errors.RadioError("Bad ack from radio")

    # basic check for the additional block
    if len(id2) < 21:
        raise errors.RadioError("The extra ID is short, aborting.")

    # this radios need a extra request/answer here on the upload
    # the amount of data received depends of the radio type
    #
    # also the first block of TX must no have the ACK at the beginning
    # see _upload for this.
    if upload is True:
        # send an ACK
        _send(radio, b"\x06")

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
        if len(ack) == 0 or ack[-1] != ACK_CMD:
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

    # reset the progress bar in the UI Bug #11851 BLOCKSIZE fix for KT-8900D
    status.max = MEM_SIZE // radio._block_size
    status.msg = "Cloning from radio..."
    status.cur = 0
    radio.status_fn(status)

    data = b""
    for addr in range(0, MEM_SIZE, radio._block_size):
        # sending the read request
        _send(radio, _make_frame("S", addr, radio._block_size))

        # read
        d = _recv(radio, addr)

        # aggregate the data
        data += d

        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    return data


def _upload(radio):
    """Upload procedure"""

    # The UPLOAD mem is restricted to lower than 0x3100,
    # so we will override that here locally
    MEM_SIZE = radio.UPLOAD_MEM_SIZE

    # UI progress
    status = chirp_common.Status()

    # put radio in program mode and identify it
    _do_ident(radio, status, True)

    # get the data to upload to radio
    data = radio.get_mmap().get_byte_compatible()

    # Reset the UI progress
    status.max = MEM_SIZE // TX_BLOCK_SIZE
    status.cur = 0
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the fun start here
    for addr in range(0, MEM_SIZE, TX_BLOCK_SIZE):
        # getting the block of data to send
        d = data[addr:addr + TX_BLOCK_SIZE]

        # build the frame to send
        frame = _make_frame("X", addr, TX_BLOCK_SIZE, d)

        # first block must not send the ACK at the beginning for the
        # ones that has the extra id, since this have to do a extra step
        if addr == 0:
            frame = frame[1:]

        # send the frame
        _send(radio, frame)

        # receiving the response
        ack = _rawrecv(radio, 1)

        # basic check
        if len(ack) != 1:
            raise errors.RadioError("No ACK when writing block 0x%04x" % addr)

        if ack not in bytes(b"\x06\x05"):
            raise errors.RadioError("Bad ACK writing block 0x%04x:" % addr)

        # UI Update
        status.cur = addr // TX_BLOCK_SIZE
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
    a tuple with the integer corresponding to the MHz it means"""
    ilow = int(low[0]) * 100 + int(low[1]) * 10 + int(low[2])
    ihigh = int(high[0]) * 100 + int(high[1]) * 10 + int(high[2])
    ilow *= 1000000
    ihigh *= 1000000

    return (ilow, ihigh)


class BTechMobileCommon(chirp_common.CloneModeRadio,
                        chirp_common.ExperimentalRadio):
    """BTECH's UV-5001 and alike radios"""
    VENDOR = "BTECH"
    MODEL = ""
    _block_size = BLOCK_SIZE  # Bug 11851 should default to BLOCK_SIZE
    IDENT = ""
    BANDS = 2
    COLOR_LCD = False
    COLOR_LCD2 = False  # BTech Original GMRS Radios
    COLOR_LCD3 = False  # Color HT Radios
    COLOR_LCD4 = False  # Waterproof Mobile Radios
    NAME_LENGTH = 6
    UPLOAD_MEM_SIZE = 0X3100
    _power_levels = [chirp_common.PowerLevel("High", watts=25),
                     chirp_common.PowerLevel("Low", watts=10)]
    _vhf_range = (130000000, 180000000)
    _220_range = (200000000, 271000000)
    _uhf_range = (400000000, 521000000)
    _350_range = (350000000, 391000000)
    _upper = 199
    _magic = MSTRING
    _fileid = []
    _id2 = False
    btech3 = False
    _gmrs = False

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
        rp.pre_download = _(
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow these instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
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
        rf.valid_name_length = self.NAME_LENGTH
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
        rf.valid_tuning_steps = STEPS
        rf.memory_bounds = (0, self._upper)

        # power levels
        POWER_LEVELS = self._power_levels
        rf.valid_power_levels = POWER_LEVELS

        # normal dual bands
        rf.valid_bands = [self._vhf_range, self._uhf_range]

        # 220 band
        if self.BANDS == 3 or self.BANDS == 4:
            rf.valid_bands.append(self._220_range)

        # 350 band
        if self.BANDS == 4:
            rf.valid_bands.append(self._350_range)

        return rf

    def sync_in(self):
        """Download from radio"""
        data = _download(self)
        self._mmap = memmap.MemoryMapBytes(data)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Error: %s" % e)

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
                msg = "Digital Tone '%d' is not supported" % val
                LOG.error(msg)
                raise errors.RadioError(msg)
        else:
            msg = "Internal error: invalid mode '%s'" % mode
            LOG.error(msg)
            raise errors.InvalidDataError(msg)

    def _is_txinh(self, _mem):
        raw_tx = b""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == b"\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number]
        _names = self._memobj.names[number]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if _mem.get_raw()[:1] == b"\xFF":
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if self._is_txinh(_mem):
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if chirp_common.is_split(self.get_features().valid_bands,
                                         mem.freq, int(_mem.txfreq) * 10):
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

        if not self.COLOR_LCD or \
                (self.COLOR_LCD and not self.VENDOR == "BTECH"):
            scramble = RadioSetting("scramble", "Scramble",
                                    RadioSettingValueBoolean(bool(
                                        _mem.scramble)))
            mem.extra.append(scramble)

        bcl = RadioSetting("bcl", "Busy channel lockout",
                           RadioSettingValueBoolean(bool(_mem.bcl)))
        mem.extra.append(bcl)

        pttid = RadioSetting("pttid", "PTT ID",
                             RadioSettingValueList(PTTID_LIST,
                                                   current_index=_mem.pttid))
        mem.extra.append(pttid)

        # validating scode
        scode = _mem.scode if _mem.scode != 15 else 0
        pttidcode = RadioSetting("scode", "PTT ID signal code",
                                 RadioSettingValueList(
                                     PTTIDCODE_LIST,
                                     current_index=scode))
        mem.extra.append(pttidcode)

        optsig = RadioSetting("optsig", "Optional signaling",
                              RadioSettingValueList(
                                  OPTSIG_LIST,
                                  current_index=_mem.optsig))
        mem.extra.append(optsig)

        spmute = RadioSetting("spmute", "Speaker mute",
                              RadioSettingValueList(
                                  SPMUTE_LIST,
                                  current_index=_mem.spmute))
        mem.extra.append(spmute)

        immutable = []

        if self._gmrs:
            if self.MODEL == "GMRS-50X1":
                if mem.number >= 1 and mem.number <= 30:
                    if mem.freq in GMRS_FREQS:
                        GMRS_FREQ = GMRS_FREQS[mem.number - 1]
                        mem.freq = GMRS_FREQ
                        immutable = ["empty", "freq"]
                    if mem.number >= 1 and mem.number <= 7:
                        mem.duplex = ''
                        mem.offset = 0
                        mem.power = POWER_LEVELS[2]
                        immutable += ["duplex", "offset", "power"]
                    elif mem.number >= 8 and mem.number <= 14:
                        mem.duplex = 'off'
                        mem.offset = 0
                        immutable += ["duplex", "offset"]
                    elif mem.number >= 15 and mem.number <= 22:
                        mem.duplex = ''
                        mem.offset = 0
                        immutable += ["duplex", "offset"]
                    elif mem.number >= 23 and mem.number <= 30:
                        mem.duplex = '+'
                        mem.offset = 5000000
                        immutable += ["duplex", "offset"]
                else:
                    # Not a GMRS channel, so restrict duplex since it will be
                    # forced to off.
                    mem.duplex = 'off'
                    mem.offset = 0
                    immutable = ["duplex", "offset"]
            elif self.MODEL in ["GMRS-20V2", "GMRS-50V2"]:
                if mem.freq in GMRS_FREQS:
                    if mem.freq in GMRS_FREQS1:
                        # Non-repeater GMRS channels (limit duplex)
                        mem.duplex = ''
                        mem.offset = 0
                        mem.power = POWER_LEVELS[2]
                        immutable = ["duplex", "offset", "power"]
                    elif mem.freq in GMRS_FREQS2:
                        # Non-repeater FRS channels (receive only)
                        mem.duplex = 'off'
                        mem.offset = 0
                        immutable = ["duplex", "offset"]
                    elif mem.freq in GMRS_FREQS3:
                        # GMRS repeater channels, always either simplex or
                        # +5 MHz
                        if mem.duplex != '+':
                            mem.duplex = ''
                            mem.offset = 0
                        else:
                            mem.offset = 5000000
                else:
                    # Not a GMRS channel, so restrict duplex since it will be
                    # forced to off.
                    mem.duplex = 'off'
                    mem.offset = 0
                    immutable = ["duplex", "offset"]
            elif self.MODEL == "DB25-G":
                if mem.freq in GMRS_FREQS:
                    if mem.freq in GMRS_FREQS1:
                        # Non-repeater GMRS channels (limit duplex)
                        mem.duplex = ''
                        mem.offset = 0
                        immutable = ["duplex", "offset"]
                    elif mem.freq in GMRS_FREQS2:
                        # Non-repeater FRS channels (receive only)
                        mem.duplex = 'off'
                        mem.offset = 0
                        immutable = ["duplex", "offset"]
                    elif mem.freq in GMRS_FREQS3:
                        # GMRS repeater channels, always either simplex or
                        # +5 MHz
                        if mem.duplex != '+':
                            mem.duplex = ''
                            mem.offset = 0
                        else:
                            mem.offset = 5000000

        mem.immutable = immutable

        return mem

    def set_memory(self, mem):
        """Set the memory data in the eeprom img from the UI"""
        # get the eprom representation of this channel
        _mem = self._memobj.memory[mem.number]
        _names = self._memobj.names[mem.number]

        mem_was_empty = False
        # same method as used in get_memory for determining if mem is empty
        # doing this BEFORE overwriting it with new values ...
        if _mem.get_raw(asbytes=False)[0] == "\xFF":
            LOG.debug("This mem was empty before")
            mem_was_empty = True

        # if empty memory
        if mem.empty:
            # the channel itself
            _mem.set_raw("\xFF" * 16)
            # the name tag
            _names.set_raw("\xFF" * 16)
            return

        if mem_was_empty:
            # Zero the whole memory if we're making it unempty for
            # the first time
            LOG.debug('Zeroing new memory')
            _mem.set_raw('\x00' * 16)

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
        _names.name = mem.name.rstrip(' ').ljust(self.NAME_LENGTH, "\xFF")

        # power, # default power level is high
        _mem.power = 0 if mem.power is None else POWER_LEVELS.index(mem.power)

        # wide/narrow
        _mem.wide = MODES.index(mem.mode)

        # scan add property
        _mem.add = SKIP_VALUES.index(mem.skip)

        # resetting unknowns, this have to be set by hand
        _mem.unknown0 = 0
        _mem.unknown1 = 0
        _mem.unknown2 = 0
        _mem.unknown3 = 0
        _mem.unknown4 = 0
        _mem.unknown5 = 0
        _mem.unknown6 = 0

        def _zero_settings():
            _mem.spmute = 0
            _mem.optsig = 0
            _mem.scramble = 0
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.scode = 0

        if self.COLOR_LCD and _mem.scramble:
            LOG.info('Resetting scramble bit for BTECH COLOR_LCD variant')
            _mem.scramble = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            LOG.debug("Extra-Setting supplied. Setting them.")
            # Zero them all first so any not provided by model don't
            # stay set
            _zero_settings()
            for setting in mem.extra:
                setattr(_mem, setting.get_name(), setting.value)
        else:
            if mem.empty:
                LOG.debug("New mem is empty.")
            else:
                LOG.debug("New mem is NOT empty")
                # set extra-settings to default ONLY when a previously empty or
                # deleted memory was edited to prevent errors such as #4121
                if mem_was_empty:
                    LOG.debug("old mem was empty. Setting default for extras.")
                    _zero_settings()

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
        if self.COLOR_LCD:
            val = min(_mem.settings.tmr, len(self.LIST_TMR) - 1)
            rs = RadioSettingValueList(self.LIST_TMR, current_index=val)
            tmr = RadioSetting("settings.tmr", "Transceiver multi-receive", rs)
            basic.append(tmr)
        else:
            tdr = RadioSetting("settings.tdr", "Transceiver dual receive",
                               RadioSettingValueBoolean(_mem.settings.tdr))
            basic.append(tdr)

        val = min(_mem.settings.sql, 9)
        rs = RadioSettingValueInteger(0, 9, val)
        sql = RadioSetting("settings.sql", "Squelch level", rs)
        basic.append(sql)

        if self.MODEL == "GMRS-50X1" or self.MODEL == "GMRS-50V2":
            rs = RadioSettingValueBoolean(_mem.settings.autolk)
            autolk = RadioSetting("settings.autolk", "Auto keylock", rs)
            basic.append(autolk)

        if self.MODEL == "DB25-G":
            val = min(_mem.settings.mgain2, 127)
            rs = RadioSettingValueInteger(0, 127, val)
            mgain2 = RadioSetting("settings.mgain2", "Mic gain", rs)
            basic.append(mgain2)

        val = min(_mem.settings.tot, len(LIST_TOT) - 1)
        rs = RadioSettingValueList(LIST_TOT, current_index=val)
        tot = RadioSetting("settings.tot", "Time out timer", rs)
        basic.append(tot)

        if self.MODEL == "KT-8R":
            rs = RadioSettingValueBoolean(_mem.settings.save)
            save = RadioSetting("settings.save", "Battery Save", rs)
            basic.append(save)

        model_list = ["KT-8R", "KT-WP12", "WP-9900"]
        if self.MODEL not in model_list:
            if self.VENDOR == "BTECH" or self.COLOR_LCD:
                val = min(_mem.settings.apo, len(LIST_APO) - 1)
                rs = RadioSettingValueList(LIST_APO, current_index=val)
                apo = RadioSetting("settings.apo", "Auto power off timer", rs)
                basic.append(apo)
            else:
                val = min(_mem.settings.apo, len(LIST_OFF1TO10) - 1)
                rs = RadioSettingValueList(LIST_OFF1TO10, current_index=val)
                toa = RadioSetting("settings.apo", "Time out alert timer", rs)
                basic.append(toa)

        val = min(_mem.settings.abr, len(LIST_OFF1TO50) - 1)
        rs = RadioSettingValueList(LIST_OFF1TO50, current_index=val)
        abr = RadioSetting("settings.abr", "Backlight timer", rs)
        basic.append(abr)

        rs = RadioSettingValueBoolean(_mem.settings.beep)
        beep = RadioSetting("settings.beep", "Key beep", rs)
        basic.append(beep)

        if self.MODEL == "GMRS-20V2":
            val = min(_mem.settings.volume, 58)
            rs = RadioSettingValueInteger(0, 58, val)
            volume = RadioSetting("settings.volume", "Volume", rs)
            basic.append(volume)

        if self.MODEL == "KT-WP12" or self.MODEL == "WP-9900":
            val = min(_mem.settings.volume, 50)
            rs = RadioSettingValueInteger(1, 51, val + 1)
            volume = RadioSetting("settings.volume", "Volume", rs)
            basic.append(volume)

        if self.MODEL == "KT-8R":
            rs = RadioSettingValueBoolean(_mem.settings.dsub)
            dsub = RadioSetting("settings.dsub", "CTCSS/DCS code display", rs)
            basic.append(dsub)

        if self.MODEL == "KT-8R" or self.COLOR_LCD4:
            rs = RadioSettingValueBoolean(_mem.settings.dtmfst)
            dtmfst = RadioSetting("settings.dtmfst", "DTMF side tone", rs)
            basic.append(dtmfst)
        else:
            val = min(_mem.settings.dtmfst, len(LIST_DTMFST) - 1)
            rs = RadioSettingValueList(LIST_DTMFST, current_index=val)
            dtmfst = RadioSetting("settings.dtmfst", "DTMF side tone", rs)
            basic.append(dtmfst)

        if not self.COLOR_LCD:
            rs = RadioSettingValueBoolean(_mem.settings.prisc)
            prisc = RadioSetting("settings.prisc", "Priority scan", rs)
            basic.append(prisc)

            val = min(_mem.settings.prich, self._upper)
            rs = RadioSettingValueInteger(0, self._upper, val)
            prich = RadioSetting("settings.prich", "Priority channel", rs)
            basic.append(prich)

        val = min(_mem.settings.screv, len(LIST_SCREV) - 1)
        rs = RadioSettingValueList(LIST_SCREV, current_index=val)
        screv = RadioSetting("settings.screv", "Scan resume method", rs)
        basic.append(screv)

        val = min(_mem.settings.pttlt, 30)
        rs = RadioSettingValueInteger(0, 30, val)
        pttlt = RadioSetting("settings.pttlt", "PTT transmit delay", rs)
        basic.append(pttlt)

        if self.VENDOR == "BTECH" and self.COLOR_LCD and not \
                self.MODEL == "GMRS-20V2":
            val = min(_mem.settings.emctp, len(LIST_EMCTPX) - 1)
            rs = RadioSettingValueList(LIST_EMCTPX, current_index=val)
            emctp = RadioSetting("settings.emctp", "Alarm mode", rs)
            basic.append(emctp)
        else:
            val = min(_mem.settings.emctp, len(LIST_EMCTP) - 1)
            rs = RadioSettingValueList(LIST_EMCTP, current_index=val)
            emctp = RadioSetting("settings.emctp", "Alarm mode", rs)
            basic.append(emctp)

        val = min(_mem.settings.emcch, self._upper)
        rs = RadioSettingValueInteger(0, self._upper, val)
        emcch = RadioSetting("settings.emcch", "Alarm channel", rs)
        basic.append(emcch)

        if self.COLOR_LCD:
            rs = RadioSettingValueBoolean(_mem.settings.sigbp)
            sigbp = RadioSetting("settings.sigbp", "Signal beep", rs)
            basic.append(sigbp)
        else:
            val = min(_mem.settings.ringt, len(LIST_OFF1TO9) - 1)
            rs = RadioSettingValueList(LIST_OFF1TO9, current_index=val)
            ringt = RadioSetting("settings.ringt", "Ring time", rs)
            basic.append(ringt)

        val = min(_mem.settings.camdf, len(LIST_MDF) - 1)
        rs = RadioSettingValueList(LIST_MDF, current_index=val)
        camdf = RadioSetting("settings.camdf", "Display mode A", rs)
        basic.append(camdf)

        val = min(_mem.settings.cbmdf, len(LIST_MDF) - 1)
        rs = RadioSettingValueList(LIST_MDF, current_index=val)
        cbmdf = RadioSetting("settings.cbmdf", "Display mode B", rs)
        basic.append(cbmdf)

        if self.COLOR_LCD:
            val = min(_mem.settings.ccmdf, len(LIST_MDF) - 1)
            rs = RadioSettingValueList(LIST_MDF, current_index=val)
            ccmdf = RadioSetting("settings.ccmdf", "Display mode C", rs)
            basic.append(ccmdf)

            if not self.COLOR_LCD4:
                val = min(_mem.settings.cdmdf, len(LIST_MDF) - 1)
                rs = RadioSettingValueList(LIST_MDF, current_index=val)
                cdmdf = RadioSetting("settings.cdmdf", "Display mode D", rs)
                basic.append(cdmdf)

                if self.MODEL in ["UV-50X2_G2", "UV-25X2_G2", "UV-25X4_G2"]:
                    val = min(_mem.settings.langua, len(LIST_VOX) - 1)
                    rs = RadioSettingValueList(LIST_VOX, current_index=val)
                    vox = RadioSetting("settings.langua", "VOX", rs)
                    basic.append(vox)
                elif self.MODEL == "GMRS-50V2":
                    val = min(_mem.settings.vox, len(LIST_VOX) - 1)
                    rs = RadioSettingValueList(LIST_VOX, current_index=val)
                    vox = RadioSetting("settings.vox", "VOX", rs)
                    basic.append(vox)
                else:
                    val = min(_mem.settings.langua, len(LIST_LANGUA) - 1)
                    rs = RadioSettingValueList(LIST_LANGUA, current_index=val)
                    langua = RadioSetting("settings.langua", "Language", rs)
                    basic.append(langua)
        if self.MODEL == "KT-8R":
            val = min(_mem.settings.voice, len(LIST_VOICE) - 1)
            rs = RadioSettingValueList(LIST_VOICE, current_index=val)
            voice = RadioSetting("settings.voice", "Voice prompt", rs)
            basic.append(voice)

        if self.MODEL == "KT-8R" or self.COLOR_LCD4:
            val = min(_mem.settings.vox, len(LIST_VOX) - 1)
            rs = RadioSettingValueList(LIST_VOX, current_index=val)
            vox = RadioSetting("settings.vox", "VOX", rs)
            basic.append(vox)

            val = min(_mem.settings.voxt, len(LIST_VOX) - 1)
            rs = RadioSettingValueList(LIST_VOXT, current_index=val)
            voxt = RadioSetting("settings.voxt", "VOX delay time", rs)
            basic.append(voxt)

        if self.VENDOR == "BTECH":
            if self.COLOR_LCD:
                if self.MODEL == "GMRS-20V2":
                    val = min(_mem.settings.sync, len(LIST_SYNCV2) - 1)
                    rs = RadioSettingValueList(LIST_SYNCV2, current_index=val)
                    sync = RadioSetting("settings.sync",
                                        "Channel display sync", rs)
                    basic.append(sync)
                else:
                    val = min(_mem.settings.sync, len(LIST_SYNC) - 1)
                    rs = RadioSettingValueList(LIST_SYNC, current_index=val)
                    sync = RadioSetting("settings.sync",
                                        "Channel display sync", rs)
                    basic.append(sync)
            else:
                rs = RadioSettingValueBoolean(_mem.settings.sync)
                sync = RadioSetting("settings.sync", "A/B channel sync", rs)
                basic.append(sync)

        if self.COLOR_LCD4:
            rs = RadioSettingValueBoolean(_mem.settings.autolock)
            autolk = RadioSetting("settings.autolock", "Auto keylock", rs)
            basic.append(autolk)

        if not self.COLOR_LCD:
            val = min(_mem.settings.ponmsg, len(LIST_PONMSG) - 1)
            rs = RadioSettingValueList(LIST_PONMSG, current_index=val)
            ponmsg = RadioSetting("settings.ponmsg", "Power-on message", rs)
            basic.append(ponmsg)

        if self.COLOR_LCD and not (self.COLOR_LCD2 or self.COLOR_LCD3 or
                                   self.COLOR_LCD4):
            val = min(_mem.settings.mainfc, len(LIST_COLOR9) - 1)
            rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
            mainfc = RadioSetting("settings.mainfc",
                                  "Main LCD foreground color", rs)
            basic.append(mainfc)

            if not self.COLOR_LCD4:
                val = min(_mem.settings.mainbc, len(LIST_COLOR9) - 1)
                rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
                mainbc = RadioSetting("settings.mainbc",
                                      "Main LCD background color", rs)
                basic.append(mainbc)

            val = min(_mem.settings.menufc, len(LIST_COLOR9) - 1)
            rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
            menufc = RadioSetting("settings.menufc",
                                  "Menu foreground color", rs)
            basic.append(menufc)

            if not self.COLOR_LCD4:
                val = min(_mem.settings.menubc, len(LIST_COLOR9) - 1)
                rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
                menubc = RadioSetting("settings.menubc",
                                      "Menu background color", rs)
                basic.append(menubc)

            val = min(_mem.settings.stafc, len(LIST_COLOR9) - 1)
            rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
            stafc = RadioSetting("settings.stafc",
                                 "Top status foreground color", rs)
            basic.append(stafc)

            if not self.COLOR_LCD4:
                val = min(_mem.settings.stabc, len(LIST_COLOR9) - 1)
                rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
                stabc = RadioSetting("settings.stabc",
                                     "Top status background color", rs)
                basic.append(stabc)

            val = min(_mem.settings.sigfc, len(LIST_COLOR9) - 1)
            rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
            sigfc = RadioSetting("settings.sigfc",
                                 "Bottom status foreground color", rs)
            basic.append(sigfc)

            if not self.COLOR_LCD4:
                val = min(_mem.settings.sigbc, len(LIST_COLOR9) - 1)
                rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
                sigbc = RadioSetting("settings.sigbc",
                                     "Bottom status background color", rs)
                basic.append(sigbc)

            val = min(_mem.settings.rxfc, len(LIST_COLOR9) - 1)
            rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
            rxfc = RadioSetting("settings.rxfc",
                                "Receiving character color", rs)
            basic.append(rxfc)

            val = min(_mem.settings.txfc, len(LIST_COLOR9) - 1)
            rs = RadioSettingValueList(LIST_COLOR9, current_index=val)
            txfc = RadioSetting("settings.txfc",
                                "Transmitting character color", rs)
            basic.append(txfc)

            if not self.COLOR_LCD4:
                val = min(_mem.settings.txdisp, len(LIST_TXDISP) - 1)
                rs = RadioSettingValueList(LIST_TXDISP, current_index=val)
                txdisp = RadioSetting("settings.txdisp",
                                      "Transmitting status display", rs)
                basic.append(txdisp)

        elif self.COLOR_LCD2 or self.COLOR_LCD3:
            val = min(_mem.settings.stfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            stfc = RadioSetting("settings.stfc", "ST-FC", rs)
            basic.append(stfc)

            val = min(_mem.settings.mffc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            mffc = RadioSetting("settings.mffc", "MF-FC", rs)
            basic.append(mffc)

            val = min(_mem.settings.sfafc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            sfafc = RadioSetting("settings.sfafc", "SFA-FC", rs)
            basic.append(sfafc)

            val = min(_mem.settings.sfbfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            sfbfc = RadioSetting("settings.sfbfc", "SFB-FC", rs)
            basic.append(sfbfc)

            val = min(_mem.settings.sfcfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            sfcfc = RadioSetting("settings.sfcfc", "SFC-FC", rs)
            basic.append(sfcfc)

            val = min(_mem.settings.sfdfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            sfdfc = RadioSetting("settings.sfdfc", "SFD-FC", rs)
            basic.append(sfdfc)

            val = min(_mem.settings.subfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            subfc = RadioSetting("settings.subfc", "SUB-FC", rs)
            basic.append(subfc)

            val = min(_mem.settings.fmfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            fmfc = RadioSetting("settings.fmfc", "FM-FC", rs)
            basic.append(fmfc)

            val = min(_mem.settings.sigfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            sigfc = RadioSetting("settings.sigfc", "SIG-FC", rs)
            basic.append(sigfc)

            if not self.MODEL == "KT-8R":
                val = min(_mem.settings.modfc, len(LIST_COLOR8) - 1)
                rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
                modfc = RadioSetting("settings.modfc", "MOD-FC", rs)
                basic.append(modfc)

            val = min(_mem.settings.menufc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            menufc = RadioSetting("settings.menufc", "MENUFC", rs)
            basic.append(menufc)

            val = min(_mem.settings.txfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            txfc = RadioSetting("settings.txfc", "TX-FC", rs)
            basic.append(txfc)

            if self.MODEL == "KT-8R":
                val = min(_mem.settings.rxfc, len(LIST_COLOR8) - 1)
                rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
                rxfc = RadioSetting("settings.rxfc", "RX-FC", rs)
                basic.append(rxfc)

            if not self.MODEL == "KT-8R" and not self.MODEL == "GMRS-50V2":
                val = min(_mem.settings.txdisp, len(LIST_TXDISP) - 1)
                rs = RadioSettingValueList(LIST_TXDISP, current_index=val)
                txdisp = RadioSetting("settings.txdisp",
                                      "Transmitting status display", rs)
                basic.append(txdisp)
        elif self.COLOR_LCD4:
            val = min(_mem.settings.asfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            asfc = RadioSetting("settings.asfc", "Above Stat fore color", rs)
            basic.append(asfc)

            val = min(_mem.settings.mainfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            mainfc = RadioSetting("settings.mainfc", "Main fore color", rs)
            basic.append(mainfc)

            val = min(_mem.settings.a_fc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            a_fc = RadioSetting("settings.a_fc", "A - fore color", rs)
            basic.append(a_fc)

            val = min(_mem.settings.b_fc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            b_fc = RadioSetting("settings.b_fc", "B - fore color", rs)
            basic.append(b_fc)

            val = min(_mem.settings.c_fc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            c_fc = RadioSetting("settings.c_fc", "C - fore color", rs)
            basic.append(c_fc)

            val = min(_mem.settings.subfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            subfc = RadioSetting("settings.subfc", "Sub fore color", rs)
            basic.append(subfc)

            val = min(_mem.settings.battfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            battfc = RadioSetting("settings.battfc", "Battery fore color", rs)
            basic.append(battfc)

            val = min(_mem.settings.sigfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            sigfc = RadioSetting("settings.sigfc", "Signal fore color", rs)
            basic.append(sigfc)

            val = min(_mem.settings.menufc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            menufc = RadioSetting("settings.menufc", "Menu fore color", rs)
            basic.append(menufc)

            val = min(_mem.settings.txfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            txfc = RadioSetting("settings.txfc", "TX fore color", rs)
            basic.append(txfc)

            val = min(_mem.settings.rxfc, len(LIST_COLOR8) - 1)
            rs = RadioSettingValueList(LIST_COLOR8, current_index=val)
            rxfc = RadioSetting("settings.rxfc", "RX fore color", rs)
            basic.append(rxfc)
        else:
            val = min(_mem.settings.wtled, len(LIST_COLOR4) - 1)
            rs = RadioSettingValueList(LIST_COLOR4, current_index=val)
            wtled = RadioSetting("settings.wtled",
                                 "Standby backlight Color", rs)
            basic.append(wtled)

            val = min(_mem.settings.rxled, len(LIST_COLOR4) - 1)
            rs = RadioSettingValueList(LIST_COLOR4, current_index=val)
            rxled = RadioSetting("settings.rxled", "RX backlight Color", rs)
            basic.append(rxled)

            val = min(_mem.settings.txled, len(LIST_COLOR4) - 1)
            rs = RadioSettingValueList(LIST_COLOR4, current_index=val)
            txled = RadioSetting("settings.txled", "TX backlight Color", rs)
            basic.append(txled)

        val = min(_mem.settings.anil, len(LIST_ANIL) - 1)
        rs = RadioSettingValueList(LIST_ANIL, current_index=val)
        anil = RadioSetting("settings.anil", "ANI length", rs)
        basic.append(anil)

        val = min(_mem.settings.reps, len(LIST_REPS) - 1)
        rs = RadioSettingValueList(LIST_REPS, current_index=val)
        reps = RadioSetting("settings.reps", "Relay signal (tone burst)", rs)
        basic.append(reps)

        if self.COLOR_LCD4:
            rs = RadioSettingValueBoolean(_mem.settings.dsub)
            dsub = RadioSetting("settings.dsub", "Subtone display", rs)
            basic.append(dsub)

        if self.MODEL == "GMRS-20V2":
            val = min(_mem.settings.repsw, len(LIST_REPSW) - 1)
            rs = RadioSettingValueList(LIST_REPSW, current_index=val)
            repsw = RadioSetting("settings.repsw", "Repeater SW", rs)
            basic.append(repsw)

        model_list = ["KT-8R", "KT-WP12", "WP-9900"]
        if self.MODEL not in model_list:
            val = min(_mem.settings.repm, len(LIST_REPM) - 1)
            rs = RadioSettingValueList(LIST_REPM, current_index=val)
            repm = RadioSetting("settings.repm", "Relay condition", rs)
            basic.append(repm)

        if self.VENDOR == "BTECH" or self.COLOR_LCD:
            if self.COLOR_LCD:
                val = min(_mem.settings.tmrmr, len(LIST_OFF1TO50) - 1)
                rs = RadioSettingValueList(LIST_OFF1TO50, current_index=val)
                tmrmr = RadioSetting("settings.tmrmr", "TMR return time", rs)
                basic.append(tmrmr)
            else:
                val = min(_mem.settings.tdrab, len(LIST_OFF1TO50) - 1)
                rs = RadioSettingValueList(LIST_OFF1TO50, current_index=val)
                tdrab = RadioSetting("settings.tdrab", "TDR return time", rs)
                basic.append(tdrab)

            rs = RadioSettingValueBoolean(_mem.settings.ste)
            ste = RadioSetting("settings.ste", "Squelch tail eliminate", rs)
            basic.append(ste)

            if self.COLOR_LCD4:
                val = min(_mem.settings.rpste, len(LIST_OFF1TO10) - 1)
                rs = RadioSettingValueList(LIST_OFF1TO10, current_index=val)
                rpste = RadioSetting("settings.rpste", "Repeater STE", rs)
                basic.append(rpste)
            else:
                val = min(_mem.settings.rpste, len(LIST_OFF1TO9) - 1)
                rs = RadioSettingValueList(LIST_OFF1TO9, current_index=val)
                rpste = RadioSetting("settings.rpste", "Repeater STE", rs)
                basic.append(rpste)

            if self.COLOR_LCD4:
                val = min(_mem.settings.rptdl, len(LIST_OFF1TO60) - 1)
                rs = RadioSettingValueList(LIST_OFF1TO60, current_index=val)
                rptdl = RadioSetting("settings.rptdl",
                                     "Repeater STE delay", rs)
                basic.append(rptdl)
            else:
                val = min(_mem.settings.rptdl, len(LIST_RPTDL) - 1)
                rs = RadioSettingValueList(LIST_RPTDL, current_index=val)
                rptdl = RadioSetting("settings.rptdl",
                                     "Repeater STE delay", rs)
                basic.append(rptdl)

        if self.MODEL == "DB25-G":
            val = min(_mem.settings.mgain, 1)
            rs = RadioSettingValueBoolean(val)
            mgain = RadioSetting("settings.mgain", "Auto power-on", rs)
            basic.append(mgain)

        if str(_mem.fingerprint.fp) in BTECH3:
            val = min(_mem.settings.mgain, 120)
            rs = RadioSettingValueInteger(0, 120, val)
            mgain = RadioSetting("settings.mgain", "Mic gain", rs)
            basic.append(mgain)

        if str(_mem.fingerprint.fp) in BTECH3 or self.COLOR_LCD:
            val = min(_mem.settings.dtmfg, 60)
            rs = RadioSettingValueInteger(0, 60, val)
            dtmfg = RadioSetting("settings.dtmfg", "DTMF gain", rs)
            basic.append(dtmfg)

        if self.VENDOR == "BTECH" and self.COLOR_LCD:
            val = min(_mem.settings.mgain, 127)
            rs = RadioSettingValueInteger(0, 127, val)
            mgain = RadioSetting("settings.mgain", "Mic gain", rs)
            basic.append(mgain)

            val = min(_mem.settings.skiptx, len(LIST_SKIPTX) - 1)
            rs = RadioSettingValueList(LIST_SKIPTX, current_index=val)
            skiptx = RadioSetting("settings.skiptx", "Skip TX", rs)
            basic.append(skiptx)

            val = min(_mem.settings.scmode, len(LIST_SCMODE) - 1)
            rs = RadioSettingValueList(LIST_SCMODE, current_index=val)
            scmode = RadioSetting("settings.scmode", "Scan mode", rs)
            basic.append(scmode)

        if self.MODEL in ["KT-8R", "UV-25X2", "UV-25X4", "UV-50X2",
                          "GMRS-20V2", "UV-50X2_G2", "GMRS-50V2",
                          "UV-25X2_G2", "UV-25X4_G2"]:
            val = min(_mem.settings.tmrtx, len(LIST_TMRTX) - 1)
            rs = RadioSettingValueList(LIST_TMRTX, current_index=val)
            tmrtx = RadioSetting("settings.tmrtx", "TX in multi-standby", rs)
            basic.append(tmrtx)

        if self.MODEL in ["UV-50X2_G2", "GMRS-50V2", "UV-25X2_G2",
                          "UV-25X4_G2"]:
            val = min(_mem.settings.earpho, len(LIST_EARPH) - 1)
            rs = RadioSettingValueList(LIST_EARPH, current_index=val)
            earpho = RadioSetting("settings.earpho", "Earphone", rs)
            basic.append(earpho)

        # Advanced
        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in VALID_CHARS:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        if self.COLOR_LCD and not (self.COLOR_LCD2 or self.COLOR_LCD3 or
                                   self.COLOR_LCD4):
            _msg = self._memobj.poweron_msg
            line1 = RadioSetting("poweron_msg.line1",
                                 "Power-on message line 1",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line1)))
            advanced.append(line1)
            line2 = RadioSetting("poweron_msg.line2",
                                 "Power-on message line 2",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line2)))
            advanced.append(line2)
            line3 = RadioSetting("poweron_msg.line3",
                                 "Power-on message line 3",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line3)))
            advanced.append(line3)
            line4 = RadioSetting("poweron_msg.line4",
                                 "Power-on message line 4",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line4)))
            advanced.append(line4)
            line5 = RadioSetting("poweron_msg.line5",
                                 "Power-on message line 5",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line5)))
            advanced.append(line5)
            line6 = RadioSetting("poweron_msg.line6",
                                 "Power-on message line 6",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line6)))
            advanced.append(line6)
            line7 = RadioSetting("poweron_msg.line7",
                                 "Power-on message line 7",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line7)))
            advanced.append(line7)
            line8 = RadioSetting("poweron_msg.line8", "Static message",
                                 RadioSettingValueString(0, 8, _filter(
                                                         _msg.line8)))
            advanced.append(line8)
        elif self.COLOR_LCD2 or self.COLOR_LCD3 or self.COLOR_LCD4:
            _msg = self._memobj.static_msg
            line = RadioSetting("static_msg.line", "Static message",
                                RadioSettingValueString(0, 16, _filter(
                                    _msg.line)))
            advanced.append(line)
        else:
            _msg = self._memobj.poweron_msg
            line1 = RadioSetting("poweron_msg.line1",
                                 "Power-on message line 1",
                                 RadioSettingValueString(0, 6, _filter(
                                                         _msg.line1)))
            advanced.append(line1)
            line2 = RadioSetting("poweron_msg.line2",
                                 "Power-on message line 2",
                                 RadioSettingValueString(0, 6, _filter(
                                                         _msg.line2)))
            advanced.append(line2)

        if self.MODEL in ("UV-2501", "UV-5001"):
            vfomren = RadioSetting("settings2.vfomren", "VFO/MR switching",
                                   RadioSettingValueBoolean(
                                       _mem.settings2.vfomren))
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

        if self.MODEL in ["UV-2501+220", "KT8900R"]:
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

        if self.BANDS == 3 or self.BANDS == 4:
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

        if self.BANDS == 4:
            _limit = convert_bytes_to_limit(_ranges.uhf2_low)
            val = RadioSettingValueString(0, 3, _limit)
            val.set_mutable(False)
            uhf2_low = RadioSetting("%s.uhf2_low" % ranges, "UHF2 low", val)
            other.append(uhf2_low)

            _limit = convert_bytes_to_limit(_ranges.uhf2_high)
            val = RadioSettingValueString(0, 3, _limit)
            val.set_mutable(False)
            uhf2_high = RadioSetting("%s.uhf2_high" % ranges, "UHF2 high", val)
            other.append(uhf2_high)

        val = RadioSettingValueString(0, 6, _filter(_mem.fingerprint.fp))
        val.set_mutable(False)
        fp = RadioSetting("fingerprint.fp", "Fingerprint", val)
        other.append(fp)

        # Work
        if self.COLOR_LCD4:
            val = min(_mem.settings2.dispab, len(LIST_ABC) - 1)
            rs = RadioSettingValueList(LIST_ABC, current_index=val)
            dispab = RadioSetting("settings2.dispab", "Display", rs)
            work.append(dispab)
        elif self.COLOR_LCD:
            val = min(_mem.settings2.dispab, len(LIST_ABCD) - 1)
            rs = RadioSettingValueList(LIST_ABCD, current_index=val)
            dispab = RadioSetting("settings2.dispab", "Display", rs)
            work.append(dispab)
        else:
            val = min(_mem.settings2.dispab, len(LIST_AB) - 1)
            rs = RadioSettingValueList(LIST_AB, current_index=val)
            dispab = RadioSetting("settings2.dispab", "Display", rs)
            work.append(dispab)

        if self.COLOR_LCD:
            val = min(_mem.settings2.vfomra, len(LIST_VFOMR) - 1)
            rs = RadioSettingValueList(LIST_VFOMR, current_index=val)
            vfomra = RadioSetting("settings2.vfomra", "VFO/MR A mode", rs)
            work.append(vfomra)

            val = min(_mem.settings2.vfomrb, len(LIST_VFOMR) - 1)
            rs = RadioSettingValueList(LIST_VFOMR, current_index=val)
            vfomrb = RadioSetting("settings2.vfomrb", "VFO/MR B mode", rs)
            work.append(vfomrb)

            val = min(_mem.settings2.vfomrc, len(LIST_VFOMR) - 1)
            rs = RadioSettingValueList(LIST_VFOMR, current_index=val)
            vfomrc = RadioSetting("settings2.vfomrc", "VFO/MR C mode", rs)
            work.append(vfomrc)

            if not self.COLOR_LCD4:
                val = min(_mem.settings2.vfomrd, len(LIST_VFOMR) - 1)
                rs = RadioSettingValueList(LIST_VFOMR, current_index=val)
                vfomrd = RadioSetting("settings2.vfomrd", "VFO/MR D mode", rs)
                work.append(vfomrd)
        else:
            val = min(_mem.settings2.vfomr, len(LIST_VFOMR) - 1)
            rs = RadioSettingValueList(LIST_VFOMR, current_index=val)
            vfomr = RadioSetting("settings2.vfomr", "VFO/MR mode", rs)
            work.append(vfomr)

        rs = RadioSettingValueBoolean(_mem.settings2.keylock)
        keylock = RadioSetting("settings2.keylock", "Keypad lock", rs)
        work.append(keylock)

        val = min(_mem.settings2.mrcha, self._upper)
        rs = RadioSettingValueInteger(0, self._upper, val)
        mrcha = RadioSetting("settings2.mrcha", "MR A channel", rs)
        work.append(mrcha)

        val = min(_mem.settings2.mrchb, self._upper)
        rs = RadioSettingValueInteger(0, self._upper, val)
        mrchb = RadioSetting("settings2.mrchb", "MR B channel", rs)
        work.append(mrchb)

        if self.COLOR_LCD:
            val = min(_mem.settings2.mrchc, self._upper)
            rs = RadioSettingValueInteger(0, self._upper, val)
            mrchc = RadioSetting("settings2.mrchc", "MR C channel", rs)
            work.append(mrchc)

            if not self.COLOR_LCD4:
                val = min(_mem.settings2.mrchd, self._upper)
                rs = RadioSettingValueInteger(0, self._upper, val)
                mrchd = RadioSetting("settings2.mrchd", "MR D channel", rs)
                work.append(mrchd)

        def my_validate(value):
            _vhf_lower = int(convert_bytes_to_limit(_ranges.vhf_low))
            _vhf_upper = int(convert_bytes_to_limit(_ranges.vhf_high))
            _uhf_lower = int(convert_bytes_to_limit(_ranges.uhf_low))
            _uhf_upper = int(convert_bytes_to_limit(_ranges.uhf_high))
            if self.BANDS == 3 or self.BANDS == 4:
                _vhf2_lower = int(convert_bytes_to_limit(_ranges.vhf2_low))
                _vhf2_upper = int(convert_bytes_to_limit(_ranges.vhf2_high))
            if self.BANDS == 4:
                _uhf2_lower = int(convert_bytes_to_limit(_ranges.uhf2_low))
                _uhf2_upper = int(convert_bytes_to_limit(_ranges.uhf2_high))

            value = chirp_common.parse_freq(value)
            msg = ("Can't be less then %i.0000")
            if value > 99000000 and value < _vhf_lower * 1000000:
                raise InvalidValueError(msg % (_vhf_lower))
            msg = ("Can't be betweeb %i.9975-%i.0000")
            if self.BANDS == 2:
                if (_vhf_upper + 1) * 1000000 <= value and \
                        value < _uhf_lower * 1000000:
                    raise InvalidValueError(msg % (_vhf_upper, _uhf_lower))
            if self.BANDS == 3:
                if (_vhf_upper + 1) * 1000000 <= value and \
                        value < _vhf2_lower * 1000000:
                    raise InvalidValueError(msg % (_vhf_upper, _vhf2_lower))
                if (_vhf2_upper + 1) * 1000000 <= value and \
                        value < _uhf_lower * 1000000:
                    raise InvalidValueError(msg % (_vhf2_upper, _uhf_lower))
            if self.BANDS == 4:
                if (_vhf_upper + 1) * 1000000 <= value and \
                        value < _vhf2_lower * 1000000:
                    raise InvalidValueError(msg % (_vhf_upper, _vhf2_lower))
                if (_vhf2_upper + 1) * 1000000 <= value and \
                        value < _uhf2_lower * 1000000:
                    raise InvalidValueError(msg % (_vhf2_upper, _uhf2_lower))
                if (_uhf2_upper + 1) * 1000000 <= value and \
                        value < _uhf_lower * 1000000:
                    raise InvalidValueError(msg % (_uhf2_upper, _uhf_lower))
            msg = ("Can't be greater then %i.9975")
            if value > 99000000 and value >= _uhf_upper * 1000000:
                raise InvalidValueError(msg % (_uhf_upper))
            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        _vhf_upper = (convert_bytes_to_limit(_ranges.vhf_high))
        _uhf_lower = (convert_bytes_to_limit(_ranges.uhf_low))

        val1a = RadioSettingValueString(0, 10,
                                        bfc.bcd_decode_freq(_mem.vfo.a.freq))
        val1a.set_validate_callback(my_validate)
        vfoafreq = RadioSetting("vfo.a.freq", "VFO A frequency", val1a)
        vfoafreq.set_apply_callback(apply_freq, _mem.vfo.a)
        work.append(vfoafreq)

        val = bfc.bcd_decode_freq(_mem.vfo.b.freq)
        if self.MODEL in ["GMRS-50V2", "GMRS-50X1"]:
            if val[:3] > _vhf_upper and val[:3] < _uhf_lower:
                val = "462.562500"
        val1b = RadioSettingValueString(0, 10, val)
        val1b.set_validate_callback(my_validate)
        vfobfreq = RadioSetting("vfo.b.freq", "VFO B frequency", val1b)
        vfobfreq.set_apply_callback(apply_freq, _mem.vfo.b)
        work.append(vfobfreq)

        if self.COLOR_LCD:
            val1c = RadioSettingValueString(0, 10,
                                            bfc.bcd_decode_freq(
                                                _mem.vfo.c.freq))
            val1c.set_validate_callback(my_validate)
            vfocfreq = RadioSetting("vfo.c.freq", "VFO C frequency", val1c)
            vfocfreq.set_apply_callback(apply_freq, _mem.vfo.c)
            work.append(vfocfreq)

            if not self.COLOR_LCD4:
                val = bfc.bcd_decode_freq(_mem.vfo.d.freq)
                if self.MODEL in ["GMRS-50V2", "GMRS-50X1"]:
                    if val[:3] > _vhf_upper and val[:3] < _uhf_lower:
                        val = "462.562500"
                val1d = RadioSettingValueString(0, 10, val)
                val1d.set_validate_callback(my_validate)
                vfodfreq = RadioSetting("vfo.d.freq", "VFO D frequency", val1d)
                vfodfreq.set_apply_callback(apply_freq, _mem.vfo.d)
                work.append(vfodfreq)

        if not self.MODEL == "GMRS-50X1":
            val = min(_mem.vfo.a.shiftd, len(LIST_SHIFT) - 1)
            rs = RadioSettingValueList(LIST_SHIFT, current_index=val)
            vfoashiftd = RadioSetting("vfo.a.shiftd", "VFO A shift", rs)
            work.append(vfoashiftd)

            val = min(_mem.vfo.b.shiftd, len(LIST_SHIFT) - 1)
            rs = RadioSettingValueList(LIST_SHIFT, current_index=val)
            vfobshiftd = RadioSetting("vfo.b.shiftd", "VFO B shift", rs)
            work.append(vfobshiftd)

            if self.COLOR_LCD:
                val = min(_mem.vfo.c.shiftd, len(LIST_SHIFT) - 1)
                rs = RadioSettingValueList(LIST_SHIFT, current_index=val)
                vfocshiftd = RadioSetting("vfo.c.shiftd", "VFO C shift", rs)
                work.append(vfocshiftd)

                if not self.COLOR_LCD4:
                    val = min(_mem.vfo.d.shiftd, len(LIST_SHIFT) - 1)
                    rs = RadioSettingValueList(LIST_SHIFT, current_index=val)
                    vfodshiftd = RadioSetting("vfo.d.shiftd",
                                              "VFO D shift", rs)
                    work.append(vfodshiftd)

        def convert_bytes_to_offset(bytes):
            real_offset = 0
            for byte in bytes:
                real_offset = (real_offset * 10) + byte
            return chirp_common.format_freq(real_offset * 1000)

        def apply_offset(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 1000
            for i in range(5, -1, -1):
                obj.offset[i] = value % 10
                value /= 10

        if not self.MODEL == "GMRS-50X1":
            if self.COLOR_LCD:
                val1a = RadioSettingValueString(0, 10, convert_bytes_to_offset(
                                                _mem.vfo.a.offset))
                vfoaoffset = RadioSetting("vfo.a.offset",
                                          "VFO A offset (0.000-999.999)",
                                          val1a)
                vfoaoffset.set_apply_callback(apply_offset, _mem.vfo.a)
                work.append(vfoaoffset)

                val1b = RadioSettingValueString(0, 10, convert_bytes_to_offset(
                                                _mem.vfo.b.offset))
                vfoboffset = RadioSetting("vfo.b.offset",
                                          "VFO B offset (0.000-999.999)",
                                          val1b)
                vfoboffset.set_apply_callback(apply_offset, _mem.vfo.b)
                work.append(vfoboffset)

                val1c = RadioSettingValueString(0, 10, convert_bytes_to_offset(
                                                _mem.vfo.c.offset))
                vfocoffset = RadioSetting("vfo.c.offset",
                                          "VFO C offset (0.000-999.999)",
                                          val1c)
                vfocoffset.set_apply_callback(apply_offset, _mem.vfo.c)
                work.append(vfocoffset)

                if not self.COLOR_LCD4:
                    val1d = RadioSettingValueString(0, 10,
                                                    convert_bytes_to_offset(
                                                        _mem.vfo.d.offset))
                    vfodoffset = RadioSetting("vfo.d.offset",
                                              "VFO D offset (0.000-999.999)",
                                              val1d)
                    vfodoffset.set_apply_callback(apply_offset, _mem.vfo.d)
                    work.append(vfodoffset)
            else:
                val1a = RadioSettingValueString(0, 10, convert_bytes_to_offset(
                                                _mem.vfo.a.offset))
                vfoaoffset = RadioSetting("vfo.a.offset",
                                          "VFO A offset (0.000-99.999)", val1a)
                vfoaoffset.set_apply_callback(apply_offset, _mem.vfo.a)
                work.append(vfoaoffset)

                val1b = RadioSettingValueString(0, 10, convert_bytes_to_offset(
                                                _mem.vfo.b.offset))
                vfoboffset = RadioSetting("vfo.b.offset",
                                          "VFO B offset (0.000-99.999)", val1b)
                vfoboffset.set_apply_callback(apply_offset, _mem.vfo.b)
                work.append(vfoboffset)

        if not self.MODEL == "GMRS-50X1":
            val = min(_mem.vfo.a.power, len(LIST_TXP) - 1)
            rs = RadioSettingValueList(LIST_TXP, current_index=val)
            vfoatxp = RadioSetting("vfo.a.power", "VFO A power", rs)
            work.append(vfoatxp)

            val = min(_mem.vfo.b.power, len(LIST_TXP) - 1)
            rs = RadioSettingValueList(LIST_TXP, current_index=val)
            vfobtxp = RadioSetting("vfo.b.power", "VFO B power", rs)
            work.append(vfobtxp)

            if self.COLOR_LCD:
                val = min(_mem.vfo.c.power, len(LIST_TXP) - 1)
                rs = RadioSettingValueList(LIST_TXP, current_index=val)
                vfoctxp = RadioSetting("vfo.c.power", "VFO C power", rs)
                work.append(vfoctxp)

                if not self.COLOR_LCD4:
                    val = min(_mem.vfo.d.power, len(LIST_TXP) - 1)
                    rs = RadioSettingValueList(LIST_TXP, current_index=val)
                    vfodtxp = RadioSetting("vfo.d.power", "VFO D power", rs)
                    work.append(vfodtxp)

        if not self.MODEL == "GMRS-50X1":
            val = min(_mem.vfo.a.wide, len(LIST_WIDE) - 1)
            rs = RadioSettingValueList(LIST_WIDE, current_index=val)
            vfoawide = RadioSetting("vfo.a.wide", "VFO A bandwidth", rs)
            work.append(vfoawide)

            val = min(_mem.vfo.b.wide, len(LIST_WIDE) - 1)
            rs = RadioSettingValueList(LIST_WIDE, current_index=val)
            vfobwide = RadioSetting("vfo.b.wide", "VFO B bandwidth", rs)
            work.append(vfobwide)

            if self.COLOR_LCD:
                val = min(_mem.vfo.c.wide, len(LIST_WIDE) - 1)
                rs = RadioSettingValueList(LIST_WIDE, current_index=val)
                vfocwide = RadioSetting("vfo.c.wide", "VFO C bandwidth", rs)
                work.append(vfocwide)

                if not self.COLOR_LCD4:
                    val = min(_mem.vfo.d.wide, len(LIST_WIDE) - 1)
                    rs = RadioSettingValueList(LIST_WIDE, current_index=val)
                    vfodwide = RadioSetting("vfo.d.wide",
                                            "VFO D bandwidth", rs)
                    work.append(vfodwide)

        val = min(_mem.vfo.a.step, len(LIST_STEP) - 1)
        rs = RadioSettingValueList(LIST_STEP, current_index=val)
        vfoastep = RadioSetting("vfo.a.step", "VFO A step", rs)
        work.append(vfoastep)

        val = min(_mem.vfo.b.step, len(LIST_STEP) - 1)
        rs = RadioSettingValueList(LIST_STEP, current_index=val)
        vfobstep = RadioSetting("vfo.b.step", "VFO B step", rs)
        work.append(vfobstep)

        if self.COLOR_LCD:
            val = min(_mem.vfo.c.step, len(LIST_STEP) - 1)
            rs = RadioSettingValueList(LIST_STEP, current_index=val)
            vfocstep = RadioSetting("vfo.c.step", "VFO C step", rs)
            work.append(vfocstep)

            if not self.COLOR_LCD4:
                val = min(_mem.vfo.d.step, len(LIST_STEP) - 1)
                rs = RadioSettingValueList(LIST_STEP, current_index=val)
                vfodstep = RadioSetting("vfo.d.step", "VFO D step", rs)
                work.append(vfodstep)

        val = min(_mem.vfo.a.optsig, len(OPTSIG_LIST) - 1)
        rs = RadioSettingValueList(OPTSIG_LIST, current_index=val)
        vfoaoptsig = RadioSetting("vfo.a.optsig", "VFO A optional signal", rs)
        work.append(vfoaoptsig)

        val = min(_mem.vfo.b.optsig, len(OPTSIG_LIST) - 1)
        rs = RadioSettingValueList(OPTSIG_LIST, current_index=val)
        vfoboptsig = RadioSetting("vfo.b.optsig", "VFO B optional signal", rs)
        work.append(vfoboptsig)

        if self.COLOR_LCD:
            val = min(_mem.vfo.c.optsig, len(OPTSIG_LIST) - 1)
            rs = RadioSettingValueList(OPTSIG_LIST, current_index=val)
            vfocoptsig = RadioSetting("vfo.c.optsig",
                                      "VFO C optional signal", rs)
            work.append(vfocoptsig)

            if not self.COLOR_LCD4:
                val = min(_mem.vfo.d.optsig, len(OPTSIG_LIST) - 1)
                rs = RadioSettingValueList(OPTSIG_LIST, current_index=val)
                vfodoptsig = RadioSetting("vfo.d.optsig",
                                          "VFO D optional signal", rs)
                work.append(vfodoptsig)

        val = min(_mem.vfo.a.spmute, len(SPMUTE_LIST) - 1)
        rs = RadioSettingValueList(SPMUTE_LIST, current_index=val)
        vfoaspmute = RadioSetting("vfo.a.spmute", "VFO A speaker mute", rs)
        work.append(vfoaspmute)

        val = min(_mem.vfo.b.spmute, len(SPMUTE_LIST) - 1)
        rs = RadioSettingValueList(SPMUTE_LIST, current_index=val)
        vfobspmute = RadioSetting("vfo.b.spmute", "VFO B speaker mute", rs)
        work.append(vfobspmute)

        if self.COLOR_LCD:
            val = min(_mem.vfo.c.spmute, len(SPMUTE_LIST) - 1)
            rs = RadioSettingValueList(SPMUTE_LIST, current_index=val)
            vfocspmute = RadioSetting("vfo.c.spmute", "VFO C speaker mute", rs)
            work.append(vfocspmute)

            if not self.COLOR_LCD4:
                val = min(_mem.vfo.d.spmute, len(SPMUTE_LIST) - 1)
                rs = RadioSettingValueList(SPMUTE_LIST, current_index=val)
                vfodspmute = RadioSetting("vfo.d.spmute",
                                          "VFO D speaker mute", rs)
                work.append(vfodspmute)

        if not self.COLOR_LCD or \
                (self.COLOR_LCD and not self.VENDOR == "BTECH"):
            rs = RadioSettingValueBoolean(_mem.vfo.a.scramble)
            vfoascr = RadioSetting("vfo.a.scramble", "VFO A scramble", rs)
            work.append(vfoascr)

            rs = RadioSettingValueBoolean(_mem.vfo.b.scramble)
            vfobscr = RadioSetting("vfo.b.scramble", "VFO B scramble", rs)
            work.append(vfobscr)

        if self.COLOR_LCD and not self.VENDOR == "BTECH":
            rs = RadioSettingValueBoolean(_mem.vfo.c.scramble)
            vfocscr = RadioSetting("vfo.c.scramble", "VFO C scramble", rs)
            work.append(vfocscr)

            rs = RadioSettingValueBoolean(_mem.vfo.d.scramble)
            vfodscr = RadioSetting("vfo.d.scramble", "VFO D scramble", rs)
            work.append(vfodscr)

        if not self.MODEL == "GMRS-50X1":
            val = min(_mem.vfo.a.scode, len(PTTIDCODE_LIST) - 1)
            rs = RadioSettingValueList(PTTIDCODE_LIST, current_index=val)
            vfoascode = RadioSetting("vfo.a.scode", "VFO A PTT-ID", rs)
            work.append(vfoascode)

            val = min(_mem.vfo.b.scode, len(PTTIDCODE_LIST) - 1)
            rs = RadioSettingValueList(PTTIDCODE_LIST, current_index=val)
            vfobscode = RadioSetting("vfo.b.scode", "VFO B PTT-ID", rs)
            work.append(vfobscode)

            if self.COLOR_LCD:
                val = min(_mem.vfo.c.scode, len(PTTIDCODE_LIST) - 1)
                rs = RadioSettingValueList(PTTIDCODE_LIST, current_index=val)
                vfocscode = RadioSetting("vfo.c.scode", "VFO C PTT-ID", rs)
                work.append(vfocscode)

                if not self.COLOR_LCD4:
                    val = min(_mem.vfo.d.scode, len(PTTIDCODE_LIST) - 1)
                    rs = RadioSettingValueList(PTTIDCODE_LIST,
                                               current_index=val)
                    vfodscode = RadioSetting("vfo.d.scode", "VFO D PTT-ID", rs)
                    work.append(vfodscode)

        if not self.MODEL == "GMRS-50X1":
            val = min(_mem.settings.pttid, len(PTTID_LIST) - 1)
            rs = RadioSettingValueList(PTTID_LIST, current_index=val)
            pttid = RadioSetting("settings.pttid", "PTT ID", rs)
            work.append(pttid)

        if not self.COLOR_LCD:
            # FM presets
            fm_presets = RadioSettingGroup("fm_presets", "FM Presets")
            top.append(fm_presets)

            def fm_validate(value):
                if value == 0:
                    return chirp_common.format_freq(value)
                if not (87.5 <= value and value <= 108.0):  # 87.5-108 MHz
                    msg = ("FM-Preset-Frequency: " +
                           "Must be between 87.5 and 108 MHz")
                    raise InvalidValueError(msg)
                return value

            def apply_fm_preset_name(setting, obj):
                valstring = str(setting.value)
                for i in range(0, 6):
                    if valstring[i] in VALID_CHARS:
                        obj[i] = valstring[i]
                    else:
                        obj[i] = '0xff'

            def apply_fm_freq(setting, obj):
                value = chirp_common.parse_freq(str(setting.value)) / 10
                for i in range(7, -1, -1):
                    obj.freq[i] = value % 10
                    value /= 10

            _presets = self._memobj.fm_radio_preset
            i = 1
            for preset in _presets:
                line = RadioSetting("fm_presets_" + str(i),
                                    "Station name " + str(i),
                                    RadioSettingValueString(0, 6, _filter(
                                        preset.broadcast_station_name)))
                line.set_apply_callback(apply_fm_preset_name,
                                        preset.broadcast_station_name)

                try:
                    presetval = bfc.bcd_decode_freq(preset.freq)
                except settings.InternalError:
                    presetval = ''

                val = RadioSettingValueFloat(0, 108, presetval)
                fmfreq = RadioSetting("fm_presets_" + str(i) + "_freq",
                                      "Frequency " + str(i), val)
                val.set_validate_callback(fm_validate)
                fmfreq.set_apply_callback(apply_fm_freq, preset)
                fm_presets.append(line)
                fm_presets.append(fmfreq)

                i = i + 1

        # DTMF-Setting
        dtmf_enc_settings = RadioSettingGroup("dtmf_enc_settings",
                                              "DTMF Encoding Settings")
        dtmf_dec_settings = RadioSettingGroup("dtmf_dec_settings",
                                              "DTMF Decoding Settings")
        top.append(dtmf_enc_settings)
        top.append(dtmf_dec_settings)
        txdisable = RadioSetting("dtmf_settings.txdisable",
                                 "TX-Disable",
                                 RadioSettingValueBoolean(
                                     _mem.dtmf_settings.txdisable))
        dtmf_enc_settings.append(txdisable)

        rxdisable = RadioSetting("dtmf_settings.rxdisable",
                                 "RX-Disable",
                                 RadioSettingValueBoolean(
                                     _mem.dtmf_settings.rxdisable))
        dtmf_enc_settings.append(rxdisable)

        if _mem.dtmf_settings.dtmfspeed_on > 0x0F:
            val = 0x03
        else:
            val = _mem.dtmf_settings.dtmfspeed_on
        dtmfspeed_on = RadioSetting(
            "dtmf_settings.dtmfspeed_on",
            "DTMF Speed (On Time)",
            RadioSettingValueList(LIST_DTMF_SPEED,
                                  current_index=val))
        dtmf_enc_settings.append(dtmfspeed_on)

        if _mem.dtmf_settings.dtmfspeed_off > 0x0F:
            val = 0x03
        else:
            val = _mem.dtmf_settings.dtmfspeed_off
        dtmfspeed_off = RadioSetting(
            "dtmf_settings.dtmfspeed_off",
            "DTMF Speed (Off Time)",
            RadioSettingValueList(LIST_DTMF_SPEED,
                                  current_index=val))
        dtmf_enc_settings.append(dtmfspeed_off)

        def memory2string(dmtf_mem):
            dtmf_string = ""
            for digit in dmtf_mem:
                if digit != 255:
                    index = LIST_DTMF_VALUES.index(digit)
                    dtmf_string = dtmf_string + LIST_DTMF_DIGITS[index]
            return dtmf_string

        def apply_dmtf_frame(setting, obj):
            LOG.debug("Setting DTMF-Code: " + str(setting.value))
            val_string = str(setting.value)
            for i in range(0, 16):
                obj[i] = 255
            i = 0
            for current_char in val_string:
                current_char = current_char.upper()
                index = LIST_DTMF_DIGITS.index(current_char)
                obj[i] = LIST_DTMF_VALUES[index]
                i = i + 1

        codes = self._memobj.dtmf_codes
        i = 1
        for dtmfcode in codes:
            val = RadioSettingValueString(0, 16, memory2string(
                                              dtmfcode.code),
                                          False, CHARSET_DTMF_DIGITS)
            line = RadioSetting("dtmf_code_" + str(i) + "_code",
                                "DMTF Code " + str(i), val)
            line.set_apply_callback(apply_dmtf_frame, dtmfcode.code)
            dtmf_enc_settings.append(line)
            i = i + 1

        line = RadioSetting("dtmf_settings.mastervice",
                            "Master and Vice ID",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.mastervice))
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.masterid),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.masterid",
                            "Master Control ID ", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.masterid)
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.minspection",
                            "Master Inspection",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.minspection))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.mmonitor",
                            "Master Monitor",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.mmonitor))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.mstun",
                            "Master Stun",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.mstun))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.mkill",
                            "Master Kill",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.mkill))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.mrevive",
                            "Master Revive",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.mrevive))
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.viceid),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.viceid",
                            "Vice Control ID ", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.viceid)
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.vinspection",
                            "Vice Inspection",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.vinspection))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.vmonitor",
                            "Vice Monitor",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.vmonitor))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.vstun",
                            "Vice Stun",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.vstun))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.vkill",
                            "Vice Kill",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.vkill))
        dtmf_dec_settings.append(line)

        line = RadioSetting("dtmf_settings.vrevive",
                            "Vice Revive",
                            RadioSettingValueBoolean(
                                _mem.dtmf_settings.vrevive))
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.inspection),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.inspection",
                            "Inspection", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.inspection)
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.alarmcode),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.alarmcode",
                            "Alarm", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.alarmcode)
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.kill),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.kill",
                            "Kill", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.kill)
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.monitor),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.monitor",
                            "Monitor", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.monitor)
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.stun),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.stun",
                            "Stun", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.stun)
        dtmf_dec_settings.append(line)

        val = RadioSettingValueString(0, 16, memory2string(
                                          _mem.dtmf_settings.revive),
                                      False, CHARSET_DTMF_DIGITS)
        line = RadioSetting("dtmf_settings.revive",
                            "Revive", val)
        line.set_apply_callback(apply_dmtf_frame,
                                _mem.dtmf_settings.revive)
        dtmf_dec_settings.append(line)

        def apply_dmtf_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) + " from list")
            val = str(setting.value)
            index = LIST_DTMF_SPECIAL_DIGITS.index(val)
            val = LIST_DTMF_SPECIAL_VALUES[index]
            obj.set_value(val)

        if _mem.dtmf_settings.groupcode not in LIST_DTMF_SPECIAL_VALUES:
            val = 0x0B
        else:
            val = _mem.dtmf_settings.groupcode
        idx = LIST_DTMF_SPECIAL_VALUES.index(val)
        line = RadioSetting(
            "dtmf_settings.groupcode",
            "Group Code",
            RadioSettingValueList(LIST_DTMF_SPECIAL_DIGITS,
                                  current_index=idx))
        line.set_apply_callback(apply_dmtf_listvalue,
                                _mem.dtmf_settings.groupcode)
        dtmf_dec_settings.append(line)

        if _mem.dtmf_settings.spacecode not in LIST_DTMF_SPECIAL_VALUES:
            val = 0x0C
        else:
            val = _mem.dtmf_settings.spacecode
        idx = LIST_DTMF_SPECIAL_VALUES.index(val)
        line = RadioSetting(
            "dtmf_settings.spacecode",
            "Space Code",
            RadioSettingValueList(LIST_DTMF_SPECIAL_DIGITS,
                                  current_index=idx))
        line.set_apply_callback(apply_dmtf_listvalue,
                                _mem.dtmf_settings.spacecode)
        dtmf_dec_settings.append(line)

        if self.COLOR_LCD:
            if _mem.dtmf_settings.resettime > 0x63:
                val = 0x4F
            else:
                val = _mem.dtmf_settings.resettime
            line = RadioSetting(
                "dtmf_settings.resettime",
                "Reset time",
                RadioSettingValueList(LIST_5TONE_RESET_COLOR,
                                      current_index=val))
            dtmf_dec_settings.append(line)
        else:
            if _mem.dtmf_settings.resettime > 0x4F:
                val = 0x4F
            else:
                val = _mem.dtmf_settings.resettime
            line = RadioSetting(
                "dtmf_settings.resettime",
                "Reset time",
                RadioSettingValueList(LIST_5TONE_RESET,
                                      current_index=val))
            dtmf_dec_settings.append(line)

        if _mem.dtmf_settings.delayproctime > 0x27:
            val = 0x04
        else:
            val = _mem.dtmf_settings.delayproctime
        line = RadioSetting(
            "dtmf_settings.delayproctime",
            "Delay processing time",
            RadioSettingValueList(LIST_DTMF_DELAY,
                                  current_index=val))
        dtmf_dec_settings.append(line)

        # 5 Tone Settings
        stds_5tone = RadioSettingGroup("stds_5tone", "Standards")
        codes_5tone = RadioSettingGroup("codes_5tone", "Codes")

        group_5tone = RadioSettingGroup("group_5tone", "5 Tone Settings")
        group_5tone.append(stds_5tone)
        group_5tone.append(codes_5tone)

        top.append(group_5tone)

        def apply_list_value(setting, obj):
            options = setting.value.get_options()
            obj.set_value(options.index(str(setting.value)))

        _5tone_standards = self._memobj._5tone_std_settings
        i = 0
        for standard in _5tone_standards:
            std_5tone = RadioSettingGroup("std_5tone_" + str(i),
                                          LIST_5TONE_STANDARDS[i])
            stds_5tone.append(std_5tone)

            period = standard.period
            if period == 255:
                LOG.debug("Period for " + LIST_5TONE_STANDARDS[i] +
                          " is not yet configured. Setting to 70ms.")
                period = 5

            if period <= len(LIST_5TONE_STANDARD_PERIODS):
                line = RadioSetting(
                    "_5tone_std_settings_" + str(i) + "_period",
                    "Period (ms)", RadioSettingValueList
                    (LIST_5TONE_STANDARD_PERIODS,
                     current_index=period))
                line.set_apply_callback(apply_list_value, standard.period)
                std_5tone.append(line)
            else:
                LOG.debug("Invalid value for 5tone period! Disabling.")

            group_tone = standard.group_tone
            if group_tone == 255:
                LOG.debug("Group-Tone for " + LIST_5TONE_STANDARDS[i] +
                          " is not yet configured. Setting to A.")
                group_tone = 10

            if group_tone <= len(LIST_5TONE_DIGITS):
                line = RadioSetting(
                    "_5tone_std_settings_" + str(i) + "_grouptone",
                    "Group Tone",
                    RadioSettingValueList(LIST_5TONE_DIGITS,
                                          current_index=group_tone))
                line.set_apply_callback(apply_list_value,
                                        standard.group_tone)
                std_5tone.append(line)
            else:
                LOG.debug("Invalid value for 5tone digit! Disabling.")

            repeat_tone = standard.repeat_tone
            if repeat_tone == 255:
                LOG.debug("Repeat-Tone for " + LIST_5TONE_STANDARDS[i] +
                          " is not yet configured. Setting to E.")
                repeat_tone = 14

            if repeat_tone <= len(LIST_5TONE_DIGITS):
                line = RadioSetting(
                    "_5tone_std_settings_" + str(i) + "_repttone",
                    "Repeat Tone",
                    RadioSettingValueList(LIST_5TONE_DIGITS,
                                          current_index=repeat_tone))
                line.set_apply_callback(apply_list_value,
                                        standard.repeat_tone)
                std_5tone.append(line)
            else:
                LOG.debug("Invalid value for 5tone digit! Disabling.")
            i = i + 1

        def my_apply_5tonestdlist_value(setting, obj):
            if LIST_5TONE_STANDARDS.index(str(setting.value)) == 15:
                obj.set_value(0xFF)
            else:
                obj.set_value(LIST_5TONE_STANDARDS.
                              index(str(setting.value)))

        def apply_5tone_frame(setting, obj):
            LOG.debug("Setting 5 Tone: " + str(setting.value))
            valstring = str(setting.value)
            if len(valstring) == 0:
                for i in range(0, 5):
                    obj[i] = 255
            else:
                validFrame = True
                for i in range(0, 5):
                    currentChar = valstring[i].upper()
                    if currentChar in LIST_5TONE_DIGITS:
                        obj[i] = LIST_5TONE_DIGITS.index(currentChar)
                    else:
                        validFrame = False
                        LOG.debug("invalid char: " + str(currentChar))
                if not validFrame:
                    LOG.debug("setting whole frame to FF")
                    for i in range(0, 5):
                        obj[i] = 255

        def validate_5tone_frame(value):
            if (len(str(value)) != 5) and (len(str(value)) != 0):
                msg = ("5 Tone must have 5 digits or 0 digits")
                raise InvalidValueError(msg)
            for digit in str(value):
                if digit.upper() not in LIST_5TONE_DIGITS:
                    msg = (str(digit) + " is not a valid digit for 5tones")
                    raise InvalidValueError(msg)
            return value

        def frame2string(frame):
            frameString = ""
            for digit in frame:
                if digit != 255:
                    frameString = frameString + LIST_5TONE_DIGITS[digit]
            return frameString

        _5tone_codes = self._memobj._5tone_codes
        i = 1
        for code in _5tone_codes:
            code_5tone = RadioSettingGroup("code_5tone_" + str(i),
                                           "5 Tone code " + str(i))
            codes_5tone.append(code_5tone)
            if (code.standard == 255):
                currentVal = 15
            else:
                currentVal = code.standard
            line = RadioSetting(
                "_5tone_code_" + str(i) + "_std", " Standard",
                RadioSettingValueList(
                    LIST_5TONE_STANDARDS, current_index=currentVal))
            line.set_apply_callback(my_apply_5tonestdlist_value,
                                    code.standard)
            code_5tone.append(line)

            val = RadioSettingValueString(0, 6,
                                          frame2string(code.frame1), False)
            line = RadioSetting("_5tone_code_" + str(i) + "_frame1",
                                " Frame 1", val)
            val.set_validate_callback(validate_5tone_frame)
            line.set_apply_callback(apply_5tone_frame, code.frame1)
            code_5tone.append(line)

            val = RadioSettingValueString(0, 6,
                                          frame2string(code.frame2), False)
            line = RadioSetting("_5tone_code_" + str(i) + "_frame2",
                                " Frame 2", val)
            val.set_validate_callback(validate_5tone_frame)
            line.set_apply_callback(apply_5tone_frame, code.frame2)
            code_5tone.append(line)

            val = RadioSettingValueString(0, 6,
                                          frame2string(code.frame3), False)
            line = RadioSetting("_5tone_code_" + str(i) + "_frame3",
                                " Frame 3", val)
            val.set_validate_callback(validate_5tone_frame)
            line.set_apply_callback(apply_5tone_frame, code.frame3)
            code_5tone.append(line)
            i = i + 1

        _5_tone_decode1 = RadioSetting(
            "_5tone_settings._5tone_decode_call_frame1",
            "5 Tone decode call Frame 1",
            RadioSettingValueBoolean(
                _mem._5tone_settings._5tone_decode_call_frame1))
        group_5tone.append(_5_tone_decode1)

        _5_tone_decode2 = RadioSetting(
            "_5tone_settings._5tone_decode_call_frame2",
            "5 Tone decode call Frame 2",
            RadioSettingValueBoolean(
                _mem._5tone_settings._5tone_decode_call_frame2))
        group_5tone.append(_5_tone_decode2)

        _5_tone_decode3 = RadioSetting(
            "_5tone_settings._5tone_decode_call_frame3",
            "5 Tone decode call Frame 3",
            RadioSettingValueBoolean(
                _mem._5tone_settings._5tone_decode_call_frame3))
        group_5tone.append(_5_tone_decode3)

        _5_tone_decode_disp1 = RadioSetting(
            "_5tone_settings._5tone_decode_disp_frame1",
            "5 Tone decode disp Frame 1",
            RadioSettingValueBoolean(
                _mem._5tone_settings._5tone_decode_disp_frame1))
        group_5tone.append(_5_tone_decode_disp1)

        _5_tone_decode_disp2 = RadioSetting(
            "_5tone_settings._5tone_decode_disp_frame2",
            "5 Tone decode disp Frame 2",
            RadioSettingValueBoolean(
                _mem._5tone_settings._5tone_decode_disp_frame2))
        group_5tone.append(_5_tone_decode_disp2)

        _5_tone_decode_disp3 = RadioSetting(
            "_5tone_settings._5tone_decode_disp_frame3",
            "5 Tone decode disp Frame 3",
            RadioSettingValueBoolean(
                _mem._5tone_settings._5tone_decode_disp_frame3))
        group_5tone.append(_5_tone_decode_disp3)

        decode_standard = _mem._5tone_settings.decode_standard
        if decode_standard == 255:
            decode_standard = 0
        if decode_standard <= len(LIST_5TONE_STANDARDS_without_none):
            line = RadioSetting("_5tone_settings.decode_standard",
                                "5 Tone-decode Standard",
                                RadioSettingValueList(
                                    LIST_5TONE_STANDARDS_without_none,
                                    current_index=decode_standard))
            group_5tone.append(line)
        else:
            LOG.debug("Invalid decode std...")

        _5tone_delay1 = _mem._5tone_settings._5tone_delay1
        if _5tone_delay1 == 255:
            _5tone_delay1 = 20

        if _5tone_delay1 <= len(LIST_5TONE_DELAY):
            list = RadioSettingValueList(LIST_5TONE_DELAY,
                                         current_index=_5tone_delay1)
            line = RadioSetting("_5tone_settings._5tone_delay1",
                                "5 Tone Delay Frame 1", list)
            group_5tone.append(line)
        else:
            LOG.debug(
                "Invalid value for 5tone delay (frame1) ! Disabling.")

        _5tone_delay2 = _mem._5tone_settings._5tone_delay2
        if _5tone_delay2 == 255:
            _5tone_delay2 = 20
            LOG.debug("5 Tone delay unconfigured! Resetting to 200ms.")

        if _5tone_delay2 <= len(LIST_5TONE_DELAY):
            list = RadioSettingValueList(LIST_5TONE_DELAY,
                                         current_index=_5tone_delay2)
            line = RadioSetting("_5tone_settings._5tone_delay2",
                                "5 Tone Delay Frame 2", list)
            group_5tone.append(line)
        else:
            LOG.debug("Invalid value for 5tone delay (frame2)! Disabling.")

        _5tone_delay3 = _mem._5tone_settings._5tone_delay3
        if _5tone_delay3 == 255:
            _5tone_delay3 = 20
            LOG.debug("5 Tone delay unconfigured! Resetting to 200ms.")

        if _5tone_delay3 <= len(LIST_5TONE_DELAY):
            list = RadioSettingValueList(LIST_5TONE_DELAY,
                                         current_index=_5tone_delay3)
            line = RadioSetting("_5tone_settings._5tone_delay3",
                                "5 Tone Delay Frame 3", list)
            group_5tone.append(line)
        else:
            LOG.debug("Invalid value for 5tone delay (frame3)! Disabling.")

        ext_length = _mem._5tone_settings._5tone_first_digit_ext_length
        if ext_length == 255:
            ext_length = 0
            LOG.debug("1st Tone ext length unconfigured! Resetting to 0")

        if ext_length <= len(LIST_5TONE_DELAY):
            list = RadioSettingValueList(
                LIST_5TONE_DELAY,
                current_index=ext_length)
            line = RadioSetting(
                "_5tone_settings._5tone_first_digit_ext_length",
                "First digit extend length", list)
            group_5tone.append(line)
        else:
            LOG.debug("Invalid value for 5tone ext length! Disabling.")

        decode_reset_time = _mem._5tone_settings.decode_reset_time
        if decode_reset_time == 255:
            decode_reset_time = 59
            LOG.debug("Decode reset time unconfigured. resetting.")
        if decode_reset_time <= len(LIST_5TONE_RESET):
            list = RadioSettingValueList(
                LIST_5TONE_RESET,
                current_index=decode_reset_time)
            line = RadioSetting("_5tone_settings.decode_reset_time",
                                "Decode reset time", list)
            group_5tone.append(line)
        else:
            LOG.debug("Invalid value decode reset time! Disabling.")

        # 2 Tone
        encode_2tone = RadioSettingGroup("encode_2tone", "2 Tone Encode")
        decode_2tone = RadioSettingGroup("decode_2tone", "2 Code Decode")

        top.append(encode_2tone)
        top.append(decode_2tone)

        duration_1st_tone = self._memobj._2tone.duration_1st_tone
        if duration_1st_tone == 255:
            LOG.debug("Duration of first 2 Tone digit is not yet " +
                      "configured. Setting to 600ms")
            duration_1st_tone = 60

        if duration_1st_tone <= len(LIST_5TONE_DELAY):
            val = RadioSettingValueList(LIST_5TONE_DELAY,
                                        current_index=duration_1st_tone)
            line = RadioSetting("_2tone.duration_1st_tone",
                                "Duration 1st Tone", val)
            encode_2tone.append(line)

        duration_2nd_tone = self._memobj._2tone.duration_2nd_tone
        if duration_2nd_tone == 255:
            LOG.debug("Duration of second 2 Tone digit is not yet " +
                      "configured. Setting to 600ms")
            duration_2nd_tone = 60

        if duration_2nd_tone <= len(LIST_5TONE_DELAY):
            val = RadioSettingValueList(LIST_5TONE_DELAY,
                                        current_index=duration_2nd_tone)
            line = RadioSetting("_2tone.duration_2nd_tone",
                                "Duration 2nd Tone", val)
            encode_2tone.append(line)

        duration_gap = self._memobj._2tone.duration_gap
        if duration_gap == 255:
            LOG.debug("Duration of gap is not yet " +
                      "configured. Setting to 300ms")
            duration_gap = 30

        if duration_gap <= len(LIST_5TONE_DELAY):
            line = RadioSetting(
                "_2tone.duration_gap", "Duration of gap",
                RadioSettingValueList(
                    LIST_5TONE_DELAY, current_index=duration_gap))
            encode_2tone.append(line)

        def _2tone_validate(value):
            if value == 0:
                return 65535
            if value == 65535:
                return value
            if not (300 <= value and value <= 3000):
                msg = ("2 Tone Frequency: Must be between 300 and 3000 Hz")
                raise InvalidValueError(msg)
            return value

        def apply_2tone_freq(setting, obj):
            val = int(setting.value)
            if (val == 0) or (val == 65535):
                obj.set_value(65535)
            else:
                obj.set_value(val)

        i = 1
        for code in self._memobj._2tone._2tone_encode:
            code_2tone = RadioSettingGroup("code_2tone_" + str(i),
                                           "Encode Code " + str(i))
            encode_2tone.append(code_2tone)

            tmp = code.freq1
            if tmp == 65535:
                tmp = 0
            val1 = RadioSettingValueInteger(0, 65535, tmp)
            freq1 = RadioSetting("2tone_code_" + str(i) + "_freq1",
                                 "Frequency 1", val1)
            val1.set_validate_callback(_2tone_validate)
            freq1.set_apply_callback(apply_2tone_freq, code.freq1)
            code_2tone.append(freq1)

            tmp = code.freq2
            if tmp == 65535:
                tmp = 0
            val2 = RadioSettingValueInteger(0, 65535, tmp)
            freq2 = RadioSetting("2tone_code_" + str(i) + "_freq2",
                                 "Frequency 2", val2)
            val2.set_validate_callback(_2tone_validate)
            freq2.set_apply_callback(apply_2tone_freq, code.freq2)
            code_2tone.append(freq2)

            i = i + 1

        decode_reset_time = _mem._2tone.reset_time
        if decode_reset_time == 255:
            decode_reset_time = 59
            LOG.debug("Decode reset time unconfigured. resetting.")
        if decode_reset_time <= len(LIST_5TONE_RESET):
            list = RadioSettingValueList(
                LIST_5TONE_RESET,
                current_index=decode_reset_time)
            line = RadioSetting("_2tone.reset_time",
                                "Decode reset time", list)
            decode_2tone.append(line)
        else:
            LOG.debug("Invalid value decode reset time! Disabling.")

        def apply_2tone_freq_pair(setting, obj):
            val = int(setting.value)
            derived_val = 65535
            frqname = str(setting._name[-5:])
            derivedname = "derived_from_" + frqname

            if (val == 0):
                val = 65535
                derived_val = 65535
            else:
                derived_val = int(round(2304000.0/val))

            obj[frqname].set_value(val)
            obj[derivedname].set_value(derived_val)

            LOG.debug("Apply " + frqname + ": " + str(val) + " | " +
                      derivedname + ": " + str(derived_val))

        i = 1
        for decode_code in self._memobj._2tone._2tone_decode:
            _2tone_dec_code = RadioSettingGroup("code_2tone_" + str(i),
                                                "Decode Code " + str(i))
            decode_2tone.append(_2tone_dec_code)

            j = 1
            for dec in decode_code.decs:
                val = dec.dec
                if val == 255:
                    LOG.debug("Dec for Code " + str(i) + " Dec " + str(j) +
                              " is not yet configured. Setting to 0.")
                    val = 0

                if val <= len(LIST_2TONE_DEC):
                    line = RadioSetting(
                        "_2tone_dec_settings_" + str(i) + "_dec_" + str(j),
                        "Dec " + str(j), RadioSettingValueList
                        (LIST_2TONE_DEC,
                         current_index=val))
                    line.set_apply_callback(apply_list_value, dec.dec)
                    _2tone_dec_code.append(line)
                else:
                    LOG.debug("Invalid value for 2tone dec! Disabling.")

                val = dec.response
                if val == 255:
                    LOG.debug("Response for Code " +
                              str(i) + " Dec " + str(j) +
                              " is not yet configured. Setting to 0.")
                    val = 0

                if val <= len(LIST_2TONE_RESPONSE):
                    line = RadioSetting(
                        "_2tone_dec_settings_" +
                        str(i) + "_resp_" + str(j),
                        "Response " + str(j), RadioSettingValueList
                        (LIST_2TONE_RESPONSE,
                         current_index=val))
                    line.set_apply_callback(apply_list_value, dec.response)
                    _2tone_dec_code.append(line)
                else:
                    LOG.debug(
                        "Invalid value for 2tone response! Disabling.")

                val = dec.alert
                if val == 255:
                    LOG.debug("Alert for Code " +
                              str(i) + " Dec " + str(j) +
                              " is not yet configured. Setting to 0.")
                    val = 0

                if val <= len(PTTIDCODE_LIST):
                    line = RadioSetting(
                        "_2tone_dec_settings_" +
                        str(i) + "_alert_" + str(j),
                        "Alert " + str(j), RadioSettingValueList
                        (PTTIDCODE_LIST,
                         current_index=val))
                    line.set_apply_callback(apply_list_value, dec.alert)
                    _2tone_dec_code.append(line)
                else:
                    LOG.debug("Invalid value for 2tone alert! Disabling.")
                j = j + 1

            freq = self._memobj._2tone.freqs[i-1]
            for char in ['A', 'B', 'C', 'D']:
                setting_name = "freq" + str(char)

                tmp = freq[setting_name]
                if tmp == 65535:
                    tmp = 0
                if tmp != 0:
                    expected = int(round(2304000.0/int(tmp)))
                    from_mem = freq["derived_from_" + setting_name]
                    if expected != from_mem:
                        LOG.error("Expected " + str(expected) +
                                  " but read " + str(from_mem) +
                                  ". Disabling 2Tone Decode Freqs!")
                        break
                val = RadioSettingValueInteger(0, 65535, tmp)
                frq = RadioSetting("2tone_dec_" + str(i) +
                                   "_freq" + str(char),
                                   ("Decode Frequency " + str(char)), val)
                val.set_validate_callback(_2tone_validate)
                frq.set_apply_callback(apply_2tone_freq_pair, freq)
                _2tone_dec_code.append(frq)

            i = i + 1

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
                    elif setting == "volume" and self.MODEL == "KT-WP12":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "volume" and self.MODEL == "WP-9900":
                        setattr(obj, setting, int(element.value) - 1)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
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


MEM_FORMAT = """
// #seekto 0x0000;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:4,
     scode:4;
  u8 unknown1:2,
     spmute:2,
     unknown2:2,
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
  u8 unusedE00:7,
     tdr:1;
  u8 unknown1;
  u8 sql;
  u8 unknown2[2];
  u8 tot;
  u8 apo;           // BTech radios use this as the Auto Power Off time
                    // other radios use this as pre-Time Out Alert
  u8 unknown3;
  u8 abr;
  u8 unusedE09:7,
     beep:1;
  u8 unknown4[4];
  u8 dtmfst;
  u8 unknown5[2];
  u8 unusedE11:7,
     prisc:1;
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
  u8 unusedE1F:7,
     sync:1;        // BTech radios use this as the display sync setting
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
  u8 unusedE2D:7,
     ste:1;
  u8 rpste;
  u8 rptdl;
  u8 mgain;
  u8 dtmfg;
} settings;

#seekto 0x0E80;
struct {
  u8 unknown1;
  u8 vfomr;
  u8 unusedE82:7,
     keylock:1;
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
  u8 offset[6];
  u8 unknown2[2];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 spmute;
  u8 optsig;
  u8 unused1:7,
     scramble:1;
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

#seekto 0x2400;
struct {
  u8 period; // one out of LIST_5TONE_STANDARD_PERIODS
  u8 group_tone;
  u8 repeat_tone;
  u8 unused[13];
} _5tone_std_settings[15];

#seekto 0x2500;
struct {
  u8 frame1[5];
  u8 frame2[5];
  u8 frame3[5];
  u8 standard;   // one out of LIST_5TONE_STANDARDS
} _5tone_codes[15];

// #seekto 0x25F0;
struct {
  u8 _5tone_delay1; // * 10ms
  u8 _5tone_delay2; // * 10ms
  u8 _5tone_delay3; // * 10ms
  u8 _5tone_first_digit_ext_length;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 decode_standard;
  u8 unknown5:5,
     _5tone_decode_call_frame3:1,
     _5tone_decode_call_frame2:1,
     _5tone_decode_call_frame1:1;
  u8 unknown6:5,
     _5tone_decode_disp_frame3:1,
     _5tone_decode_disp_frame2:1,
     _5tone_decode_disp_frame1:1;
  u8 decode_reset_time; // * 100 + 100ms
} _5tone_settings;

#seekto 0x2900;
struct {
  u8 code[16]; // 0=x0A, A=0x0D, B=0x0E, C=0x0F, D=0x00, #=0x0C *=0x0B
} dtmf_codes[15];

// #seekto 0x29F0;
struct {
  u8 dtmfspeed_on;  //list with 50..2000ms in steps of 10
  u8 dtmfspeed_off; //list with 50..2000ms in steps of 10
  u8 unknown0[14];
  u8 inspection[16];
  u8 monitor[16];
  u8 alarmcode[16];
  u8 stun[16];
  u8 kill[16];
  u8 revive[16];
  u8 unknown1[16];
  u8 unknown2[16];
  u8 unknown3[16];
  u8 unknown4[16];
  u8 unknown5[16];
  u8 unknown6[16];
  u8 unknown7[16];
  u8 masterid[16];
  u8 viceid[16];
  u8 unused01:7,
     mastervice:1;
  u8 unused02:3,
     mrevive:1,
     mkill:1,
     mstun:1,
     mmonitor:1,
     minspection:1;
  u8 unused03:3,
     vrevive:1,
     vkill:1,
     vstun:1,
     vmonitor:1,
     vinspection:1;
  u8 unused04:6,
     txdisable:1,
     rxdisable:1;
  u8 groupcode;
  u8 spacecode;
  u8 delayproctime; // * 100 + 100ms
  u8 resettime;     // * 100 + 100ms
} dtmf_settings;

#seekto 0x2D00;
struct {
  struct {
    ul16 freq1;
    u8 unused01[6];
    ul16 freq2;
    u8 unused02[6];
  } _2tone_encode[15];
  u8 duration_1st_tone; // *10ms
  u8 duration_2nd_tone; // *10ms
  u8 duration_gap;      // *10ms
  u8 unused03[13];
  struct {
    struct {
      u8 dec;      // one out of LIST_2TONE_DEC
      u8 response; // one out of LIST_2TONE_RESPONSE
      u8 alert;    // 1-16
    } decs[4];
    u8 unused04[4];
  } _2tone_decode[15];
  u8 unused05[16];

  struct {
    ul16 freqA;
    ul16 freqB;
    ul16 freqC;
    ul16 freqD;
    // unknown what those values mean, but they are
    // derived from configured frequencies
    ul16 derived_from_freqA; // 2304000/freqA
    ul16 derived_from_freqB; // 2304000/freqB
    ul16 derived_from_freqC; // 2304000/freqC
    ul16 derived_from_freqD; // 2304000/freqD
  }freqs[15];
  u8 reset_time;  // * 100 + 100ms - 100-8000ms
} _2tone;

#seekto 0x3000;
struct {
  u8 freq[8];
  char broadcast_station_name[6];
  u8 unknown[2];
} fm_radio_preset[16];

#seekto 0x3C90;
struct {
  u8 vhf_low[3];
  u8 vhf_high[3];
  u8 uhf_low[3];
  u8 uhf_high[3];
} ranges;

// the UV-2501+220 & KT8900R has different zones for storing ranges

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


class BTech(BTechMobileCommon):
    """BTECH's UV-5001 and alike radios"""
    BANDS = 2
    COLOR_LCD = False
    NAME_LENGTH = 6

    def set_options(self):
        """This is to read the options from the image and set it in the
        environment, for now just the limits of the freqs in the VHF/UHF
        ranges"""

        # setting the correct ranges for each radio type
        if self.MODEL in ["UV-2501+220", "KT8900R"]:
            # the model 2501+220 has a segment in 220
            # and a different position in the memmap
            # also the QYT KT8900R
            ranges = self._memobj.ranges220
        else:
            ranges = self._memobj.ranges

        # the normal dual bands
        vhf = _decode_ranges(ranges.vhf_low, ranges.vhf_high)
        uhf = _decode_ranges(ranges.uhf_low, ranges.uhf_high)

        # DEBUG
        LOG.info("Radio ranges: VHF %d to %d" % vhf)
        LOG.info("Radio ranges: UHF %d to %d" % uhf)

        # 220 MHz radios case
        if self.MODEL in ["UV-2501+220", "KT8900R"]:
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


# Declaring Aliases (Clones of the real radios)
class JT2705M(chirp_common.Alias):
    VENDOR = "Jetstream"
    MODEL = "JT2705M"


class JT6188Mini(chirp_common.Alias):
    VENDOR = "Juentai"
    MODEL = "JT-6188 Mini"


class JT6188Plus(chirp_common.Alias):
    VENDOR = "Juentai"
    MODEL = "JT-6188 Plus"


class SSGT890(chirp_common.Alias):
    VENDOR = "Sainsonic"
    MODEL = "GT-890"


class ZastoneMP300(chirp_common.Alias):
    VENDOR = "Zastone"
    MODEL = "MP-300"


# real radios
@directory.register
class UV2501(BTech):
    """Baofeng Tech UV2501"""
    MODEL = "UV-2501"
    _fileid = [UV2501G3_fp,
               UV2501G2_fp,
               UV2501pp2_fp,
               UV2501pp_fp]


@directory.register
class UV2501_220(BTech):
    """Baofeng Tech UV2501+220"""
    MODEL = "UV-2501+220"
    BANDS = 3
    _magic = MSTRING_220
    _fileid = [UV2501_220G3_fp,
               UV2501_220G2_fp,
               UV2501_220_fp,
               UV2501_220pp_fp]


@directory.register
class UV5001(BTech):
    """Baofeng Tech UV5001"""
    MODEL = "UV-5001"
    _fileid = [UV5001G3_fp,
               UV5001G22_fp,
               UV5001G2_fp,
               UV5001alpha_fp,
               UV5001pp_fp]
    _power_levels = [chirp_common.PowerLevel("High", watts=50),
                     chirp_common.PowerLevel("Low", watts=10)]


@directory.register
class MINI8900(BTech):
    """WACCOM MINI-8900"""
    VENDOR = "WACCOM"
    MODEL = "MINI-8900"
    _magic = MSTRING_MINI8900
    _fileid = [MINI8900_fp]
    # Clones
    ALIASES = [JT6188Plus]


@directory.register
class KTUV980(BTech):
    """QYT KT-UV980"""
    VENDOR = "QYT"
    MODEL = "KT-UV980"
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_MINI8900
    _fileid = [KTUV980_fp]
    # Clones
    ALIASES = [JT2705M]

# Please note that there is a version of this radios that is a clone of the
# Waccom Mini8900, maybe an early version?


class OTGRadioV1(chirp_common.Alias):
    VENDOR = 'OTGSTUFF'
    MODEL = 'OTG Radio v1'


@directory.register
class KT9800(BTech):
    """QYT KT8900"""
    VENDOR = "QYT"
    MODEL = "KT8900"
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900
    _fileid = [KT8900_fp,
               KT8900_fp1,
               KT8900_fp2,
               KT8900_fp3,
               KT8900_fp4,
               KT8900_fp5,
               KT8900_fp6,
               KT8900_fp7,
               KT8900_fp8]
    # Clones
    ALIASES = [JT6188Mini, SSGT890, ZastoneMP300]


@directory.register
class KT9800R(BTech):
    """QYT KT8900R"""
    VENDOR = "QYT"
    MODEL = "KT8900R"
    BANDS = 3
    _vhf_range = (136000000, 175000000)
    _220_range = (240000000, 271000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900R
    _fileid = [KT8900R_fp,
               KT8900R_fp1,
               KT8900R_fp2,
               KT8900R_fp3,
               KT8900R_fp4,
               KT8900R_fp5]


@directory.register
class LT588UV(BTech):
    """LUITON LT-588UV"""
    VENDOR = "LUITON"
    MODEL = "LT-588UV"
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900
    _fileid = [LT588UV_fp,
               LT588UV_fp1]
    _power_levels = [chirp_common.PowerLevel("High", watts=60),
                     chirp_common.PowerLevel("Low", watts=10)]


COLOR_MEM_FORMAT = """
// #seekto 0x0000;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:4,
     scode:4;
  u8 unknown1:2,
     spmute:2,
     unknown2:2,
     optsig:2;
  u8 unknown3:3,
     scramble:1,
     unknown4:2,
     power:2;
  u8 unknown5:1,
     wide:1,
     unknown6:2,
     bcl:1,
     add:1,
     pttid:2;
} memory[200];

#seekto 0x0E00;
struct {
  u8 tmr;
  u8 unknown1;
  u8 sql;
  u8 unknown2;
  u8 mgain2;
  u8 tot;
  u8 apo;
  u8 unknown3;
  u8 abr;
  u8 unusedE09:7,
     beep:1;
  u8 unknown4[4];
  u8 dtmfst;
  u8 unknown5[2];
  u8 screv;
  u8 unknown6[2];
  u8 pttid;
  u8 pttlt;
  u8 unknown7;
  u8 emctp;
  u8 emcch;
  u8 unusedE19:7,
     sigbp:1;
  u8 unknown8;
  u8 camdf;
  u8 cbmdf;
  u8 ccmdf;
  u8 cdmdf;
  u8 langua;        // BTech Gen2 radios have removed the Language setting
                    // use this as the VOX setting
  u8 sync;          // BTech radios use this as the display sync
                    // setting, other radios use this as the auto
                    // keypad lock setting
  u8 mainfc;
  u8 mainbc;
  u8 menufc;
  u8 menubc;
  u8 stafc;
  u8 stabc;
  u8 sigfc;
  u8 sigbc;
  u8 rxfc;
  u8 txfc;
  u8 txdisp;
  u8 unknown9[5];
  u8 anil;
  u8 reps;
  u8 repm;
  u8 tmrmr;
  u8 unusedE35:7,
     ste:1;
  u8 rpste;
  u8 rptdl;
  u8 dtmfg;
  u8 mgain;         // used by db25-g for ponyey
  u8 skiptx;
  u8 scmode;
  u8 tmrtx;
  u8 earpho;
} settings;

#seekto 0x0E80;
struct {
  u8 unknown1;
  u8 vfomr;
  u8 unusedE82:7,
     keylock:1;
  u8 unknown2;
  u8 unknown3:4,
     vfomren:1,
     unknown4:1,
     reseten:1,
     menuen:1;
  u8 unknown5[11];
  u8 dispab;
  u8 unknown6[2];
  u8 menu;
  u8 unknown7[7];
  u8 vfomra;
  u8 vfomrb;
  u8 vfomrc;
  u8 vfomrd;
  u8 mrcha;
  u8 mrchb;
  u8 mrchc;
  u8 mrchd;
} settings2;

struct settings_vfo {
  u8 freq[8];
  u8 offset[6];
  u8 unknown2[2];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 spmute;
  u8 optsig;
  u8 unused1:7,
     scramble:1;
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
  struct settings_vfo c;
  struct settings_vfo d;
} vfo;

// #seekto 0x0F80;
struct {
  char line1[8];
  char line2[8];
  char line3[8];
  char line4[8];
  char line5[8];
  char line6[8];
  char line7[8];
  char line8[8];
} poweron_msg;

#seekto 0x1000;
struct {
  char name[8];
  u8 unknown1[8];
} names[200];

#seekto 0x2400;
struct {
  u8 period; // one out of LIST_5TONE_STANDARD_PERIODS
  u8 group_tone;
  u8 repeat_tone;
  u8 unused[13];
} _5tone_std_settings[15];

#seekto 0x2500;
struct {
  u8 frame1[5];
  u8 frame2[5];
  u8 frame3[5];
  u8 standard;   // one out of LIST_5TONE_STANDARDS
} _5tone_codes[15];

// #seekto 0x25F0;
struct {
  u8 _5tone_delay1; // * 10ms
  u8 _5tone_delay2; // * 10ms
  u8 _5tone_delay3; // * 10ms
  u8 _5tone_first_digit_ext_length;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 decode_standard;
  u8 unknown5:5,
     _5tone_decode_call_frame3:1,
     _5tone_decode_call_frame2:1,
     _5tone_decode_call_frame1:1;
  u8 unknown6:5,
     _5tone_decode_disp_frame3:1,
     _5tone_decode_disp_frame2:1,
     _5tone_decode_disp_frame1:1;
  u8 decode_reset_time; // * 100 + 100ms
} _5tone_settings;

#seekto 0x2900;
struct {
  u8 code[16]; // 0=x0A, A=0x0D, B=0x0E, C=0x0F, D=0x00, #=0x0C *=0x0B
} dtmf_codes[15];

// #seekto 0x29F0;
struct {
  u8 dtmfspeed_on;  //list with 50..2000ms in steps of 10
  u8 dtmfspeed_off; //list with 50..2000ms in steps of 10
  u8 unknown0[14];
  u8 inspection[16];
  u8 monitor[16];
  u8 alarmcode[16];
  u8 stun[16];
  u8 kill[16];
  u8 revive[16];
  u8 unknown1[16];
  u8 unknown2[16];
  u8 unknown3[16];
  u8 unknown4[16];
  u8 unknown5[16];
  u8 unknown6[16];
  u8 unknown7[16];
  u8 masterid[16];
  u8 viceid[16];
  u8 unused01:7,
     mastervice:1;
  u8 unused02:3,
     mrevive:1,
     mkill:1,
     mstun:1,
     mmonitor:1,
     minspection:1;
  u8 unused03:3,
     vrevive:1,
     vkill:1,
     vstun:1,
     vmonitor:1,
     vinspection:1;
  u8 unused04:6,
     txdisable:1,
     rxdisable:1;
  u8 groupcode;
  u8 spacecode;
  u8 delayproctime; // * 100 + 100ms
  u8 resettime;     // * 100 + 100ms
} dtmf_settings;

#seekto 0x2D00;
struct {
  struct {
    ul16 freq1;
    u8 unused01[6];
    ul16 freq2;
    u8 unused02[6];
  } _2tone_encode[15];
  u8 duration_1st_tone; // *10ms
  u8 duration_2nd_tone; // *10ms
  u8 duration_gap;      // *10ms
  u8 unused03[13];
  struct {
    struct {
      u8 dec;      // one out of LIST_2TONE_DEC
      u8 response; // one out of LIST_2TONE_RESPONSE
      u8 alert;    // 1-16
    } decs[4];
    u8 unused04[4];
  } _2tone_decode[15];
  u8 unused05[16];

  struct {
    ul16 freqA;
    ul16 freqB;
    ul16 freqC;
    ul16 freqD;
    // unknown what those values mean, but they are
    // derived from configured frequencies
    ul16 derived_from_freqA; // 2304000/freqA
    ul16 derived_from_freqB; // 2304000/freqB
    ul16 derived_from_freqC; // 2304000/freqC
    ul16 derived_from_freqD; // 2304000/freqD
  }freqs[15];
  u8 reset_time;  // * 100 + 100ms - 100-8000ms
} _2tone;

#seekto 0x3D80;
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
  u8 unknown5[4];
  u8 unknown6[6];
  u8 uhf2_low[3];
  u8 uhf2_high[3];
} ranges;

#seekto 0x3F70;
struct {
  char fp[6];
} fingerprint;

"""


class BTechColor(BTechMobileCommon):
    """BTECH's Color LCD Mobile and alike radios"""
    COLOR_LCD = True
    NAME_LENGTH = 8
    LIST_TMR = LIST_TMR16

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        self._memobj = bitwise.parse(COLOR_MEM_FORMAT, self._mmap)

        # load specific parameters from the radio image
        self.set_options()

    def set_options(self):
        """This is to read the options from the image and set it in the
        environment, for now just the limits of the freqs in the VHF/UHF
        ranges"""

        # setting the correct ranges for each radio type
        ranges = self._memobj.ranges

        # the normal dual bands
        vhf = _decode_ranges(ranges.vhf_low, ranges.vhf_high)
        uhf = _decode_ranges(ranges.uhf_low, ranges.uhf_high)

        # DEBUG
        LOG.info("Radio ranges: VHF %d to %d" % vhf)
        LOG.info("Radio ranges: UHF %d to %d" % uhf)

        # the additional bands
        if self.MODEL in ["UV-25X4", "KT7900D"]:
            # 200 MHz band
            vhf2 = _decode_ranges(ranges.vhf2_low, ranges.vhf2_high)
            LOG.info("Radio ranges: VHF(220) %d to %d" % vhf2)
            self._220_range = vhf2

            # 350 MHz band
            uhf2 = _decode_ranges(ranges.uhf2_low, ranges.uhf2_high)
            LOG.info("Radio ranges: UHF(350) %d to %d" % uhf2)
            self._350_range = uhf2

        # set the class with the real data
        self._vhf_range = vhf
        self._uhf_range = uhf


# Declaring Aliases (Clones of the real radios)
class SKT8900D(chirp_common.Alias):
    VENDOR = "Surecom"
    MODEL = "S-KT8900D"


class QB25(chirp_common.Alias):
    VENDOR = "Radioddity"
    MODEL = "QB25"


# real radios
@directory.register
class UV25X2(BTechColor):
    """Baofeng Tech UV25X2"""
    MODEL = "UV-25X2"
    BANDS = 2
    _vhf_range = (130000000, 180000000)
    _uhf_range = (400000000, 521000000)
    _magic = MSTRING_UV25X2
    _fileid = [UV25X2_fp]


@directory.register
class UV25X2_G2(UV25X2):
    """Baofeng Tech UV25X2_G2"""
    MODEL = "UV-25X2_G2"
    _fileid = [UV25X2G2_fp]


@directory.register
class UV25X4(BTechColor):
    """Baofeng Tech UV25X4"""
    MODEL = "UV-25X4"
    BANDS = 4
    _vhf_range = (130000000, 180000000)
    _220_range = (200000000, 271000000)
    _uhf_range = (400000000, 521000000)
    _350_range = (350000000, 391000000)
    _magic = MSTRING_UV25X4
    _fileid = [UV25X4_fp]


@directory.register
class UV25X4_G2(UV25X4):
    """Baofeng Tech UV25X4_G2"""
    MODEL = "UV-25X4_G2"
    _fileid = [UV25X4G2_fp]


@directory.register
class UV50X2(BTechColor):
    """Baofeng Tech UV50X2"""
    MODEL = "UV-50X2"
    BANDS = 2
    _vhf_range = (130000000, 180000000)
    _uhf_range = (400000000, 521000000)
    _magic = MSTRING_UV25X2
    _fileid = [UV50X2_fp]
    _power_levels = [chirp_common.PowerLevel("High", watts=50),
                     chirp_common.PowerLevel("Low", watts=10)]


@directory.register
class UV50X2_G2(BTechColor):
    """Baofeng Tech UV50X2_G2"""
    MODEL = "UV-50X2_G2"
    BANDS = 2
    _vhf_range = (130000000, 180000000)
    _uhf_range = (400000000, 521000000)
    _magic = MSTRING_UV25X2
    _fileid = [UV50X2_fp]
    _power_levels = [chirp_common.PowerLevel("High", watts=50),
                     chirp_common.PowerLevel("Low", watts=10)]

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class KT7900D(BTechColor):
    """QYT KT7900D"""
    VENDOR = "QYT"
    MODEL = "KT7900D"
    BANDS = 4
    LIST_TMR = LIST_TMR15
    _vhf_range = (136000000, 175000000)
    _220_range = (200000000, 271000000)
    _uhf_range = (400000000, 481000000)
    _350_range = (350000000, 371000000)
    _magic = MSTRING_KT8900D
    _fileid = [KT7900D_fp, KT7900D_fp1, KT7900D_fp2, KT7900D_fp3, KT7900D_fp4,
               KT7900D_fp5, KT7900D_fp6, KT7900D_fp7, KT7900D_fp8, KT7900D_fp9,
               QB25_fp, KT7900D_fp10]
    # Clones
    ALIASES = [SKT8900D, QB25]


@directory.register
class KT8900D(BTechColor):
    """QYT KT8900D"""
    VENDOR = "QYT"
    MODEL = "KT8900D"
    _block_size = 0x10   # Bug 11851 BLOCKSIZE fix for KT-8900D
    BANDS = 2
    LIST_TMR = LIST_TMR15
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900D
    _fileid = [KT8900D_fp5, KT8900D_fp4, KT8900D_fp3, KT8900D_fp2, KT8900D_fp1,
               KT8900D_fp]

    # Clones
    ALIASES = [OTGRadioV1]


@directory.register
class KT5800(BTechColor):
    """QYT KT5800"""
    VENDOR = "QYT"
    MODEL = "KT5800"
    BANDS = 2
    LIST_TMR = LIST_TMR15
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900D
    _fileid = [KT5800_fp]


@directory.register
class KT980PLUS(BTechColor):
    """QYT KT980PLUS"""
    VENDOR = "QYT"
    MODEL = "KT980PLUS"
    BANDS = 2
    LIST_TMR = LIST_TMR15
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900D
    _fileid = [KT980PLUS_fp1, KT980PLUS_fp]
    _power_levels = [chirp_common.PowerLevel("High", watts=75),
                     chirp_common.PowerLevel("Low", watts=55)]

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class DB25G(BTechColor):
    """Radioddity DB25-G"""
    VENDOR = "Radioddity"
    MODEL = "DB25-G"
    BANDS = 2
    LIST_TMR = LIST_TMR15
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 481000000)
    _magic = MSTRING_KT8900D
    _fileid = [DB25G_fp1, DB25G_fp]
    _gmrs = True
    _power_levels = [chirp_common.PowerLevel("High", watts=25),
                     chirp_common.PowerLevel("Mid", watts=15),
                     chirp_common.PowerLevel("Low", watts=5)]

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        _msg_duplex = 'Duplex must be "off" for this frequency'
        _msg_offset = 'Only simplex or +5 MHz offset allowed on GMRS'

        if mem.freq in GMRS_FREQS3:
            if mem.duplex and mem.offset != 5000000:
                msgs.append(chirp_common.ValidationWarning(_msg_offset))
            if mem.duplex and mem.duplex != "+":
                msgs.append(chirp_common.ValidationWarning(_msg_offset))

        return msgs

    def check_set_memory_immutable_policy(self, existing, new):
        existing.immutable = []
        super().check_set_memory_immutable_policy(existing, new)

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


GMRS_MEM_FORMAT = """
// #seekto 0x0000;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:4,
     scode:4;
  u8 unknown1:2,
     spmute:2,
     unknown2:2,
     optsig:2;
  u8 unknown3:3,
     scramble:1,
     unknown4:2,
     power:2;
  u8 unknown5:1,
     wide:1,
     unknown6:2,
     bcl:1,
     add:1,
     pttid:2;
} memory[256];

// #seekto 0x1000;
struct {
  char name[7];
  u8 unknown1[9];
} names[256];

#seekto 0x2400;
struct {
  u8 period; // one out of LIST_5TONE_STANDARD_PERIODS
  u8 group_tone;
  u8 repeat_tone;
  u8 unused[13];
} _5tone_std_settings[15];

#seekto 0x2500;
struct {
  u8 frame1[5];
  u8 frame2[5];
  u8 frame3[5];
  u8 standard;   // one out of LIST_5TONE_STANDARDS
} _5tone_codes[15];

// #seekto 0x25F0;
struct {
  u8 _5tone_delay1; // * 10ms
  u8 _5tone_delay2; // * 10ms
  u8 _5tone_delay3; // * 10ms
  u8 _5tone_first_digit_ext_length;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 decode_standard;
  u8 unknown5:5,
     _5tone_decode_call_frame3:1,
     _5tone_decode_call_frame2:1,
     _5tone_decode_call_frame1:1;
  u8 unknown6:5,
     _5tone_decode_disp_frame3:1,
     _5tone_decode_disp_frame2:1,
     _5tone_decode_disp_frame1:1;
  u8 decode_reset_time; // * 100 + 100ms
} _5tone_settings;

// #seekto 0x2900;
struct {
  u8 code[16]; // 0=x0A, A=0x0D, B=0x0E, C=0x0F, D=0x00, #=0x0C *=0x0B
} dtmf_codes[15];

#seekto 0x29F0;
struct {
  u8 dtmfspeed_on;  //list with 50..2000ms in steps of 10
  u8 dtmfspeed_off; //list with 50..2000ms in steps of 10
  u8 unknown0[14];
  u8 inspection[16];
  u8 monitor[16];
  u8 alarmcode[16];
  u8 stun[16];
  u8 kill[16];
  u8 revive[16];
  u8 unknown1[16];
  u8 unknown2[16];
  u8 unknown3[16];
  u8 unknown4[16];
  u8 unknown5[16];
  u8 unknown6[16];
  u8 unknown7[16];
  u8 masterid[16];
  u8 viceid[16];
  u8 unused01:7,
     mastervice:1;
  u8 unused02:3,
     mrevive:1,
     mkill:1,
     mstun:1,
     mmonitor:1,
     minspection:1;
  u8 unused03:3,
     vrevive:1,
     vkill:1,
     vstun:1,
     vmonitor:1,
     vinspection:1;
  u8 unused04:6,
     txdisable:1,
     rxdisable:1;
  u8 groupcode;
  u8 spacecode;
  u8 delayproctime; // * 100 + 100ms
  u8 resettime;     // * 100 + 100ms
} dtmf_settings;

#seekto 0x2D00;
struct {
  struct {
    ul16 freq1;
    u8 unused01[6];
    ul16 freq2;
    u8 unused02[6];
  } _2tone_encode[15];
  u8 duration_1st_tone; // *10ms
  u8 duration_2nd_tone; // *10ms
  u8 duration_gap;      // *10ms
  u8 unused03[13];
  struct {
    struct {
      u8 dec;      // one out of LIST_2TONE_DEC
      u8 response; // one out of LIST_2TONE_RESPONSE
      u8 alert;    // 1-16
    } decs[4];
    u8 unused04[4];
  } _2tone_decode[15];
  u8 unused05[16];

  struct {
    ul16 freqA;
    ul16 freqB;
    ul16 freqC;
    ul16 freqD;
    // unknown what those values mean, but they are
    // derived from configured frequencies
    ul16 derived_from_freqA; // 2304000/freqA
    ul16 derived_from_freqB; // 2304000/freqB
    ul16 derived_from_freqC; // 2304000/freqC
    ul16 derived_from_freqD; // 2304000/freqD
  }freqs[15];
  u8 reset_time;  // * 100 + 100ms - 100-8000ms
} _2tone;

#seekto 0x3000;
struct {
  u8 freq[8];
  char broadcast_station_name[6];
  u8 unknown[2];
} fm_radio_preset[16];
"""

GMRS_MEM_FORMAT_PT2 = """
#seekto 0x3280;
struct {
  u8 unknown1;
  u8 vfomr;
  u8 unused3281:7,
     keylock:1;
  u8 unknown2;
  u8 unknown3:4,
     vfomren:1,
     unknown4:1,
     reseten:1,
     menuen:1;
  u8 unknown5[11];
  u8 dispab;
  u8 unknown6[2];
  u8 smenu;
  u8 unknown7[7];
  u8 vfomra;
  u8 vfomrb;
  u8 vfomrc;
  u8 vfomrd;
  u8 mrcha;
  u8 mrchb;
  u8 mrchc;
  u8 mrchd;
} settings2;

struct settings_vfo {
  u8 freq[8];
  u8 offset[6];
  u8 unknown2[2];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 spmute;
  u8 optsig;
  u8 unused1:7,
     scramble:1;
  u8 wide;
  u8 power;
  u8 shiftd;
  u8 step;
  u8 unknown3[4];
};

#seekto 0x3300;
struct {
  struct settings_vfo a;
  struct settings_vfo b;
  struct settings_vfo c;
  struct settings_vfo d;
} vfo;

#seekto 0x33B0;
struct {
  char line[16];
} static_msg;

#seekto 0x3D80;
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
  u8 unknown5[4];
  u8 unknown6[6];
  u8 uhf2_low[3];
  u8 uhf2_high[3];
} ranges;

#seekto 0x3F70;
struct {
  char fp[6];
} fingerprint;

"""


GMRS_ORIG_MEM_FORMAT = """
#seekto 0x3200;
struct {
  u8 tmr;
  u8 unknown1;
  u8 sql;
  u8 unknown2;
  u8 unused3204:7,
     autolk:1;
  u8 tot;
  u8 apo;
  u8 unknown3;
  u8 abr;
  u8 unused3209:7,
     beep:1;
  u8 unknown4[4];
  u8 dtmfst;
  u8 unknown5[2];
  u8 screv;
  u8 unknown6[2];
  u8 pttid;
  u8 pttlt;
  u8 unknown7;
  u8 emctp;
  u8 emcch;
  u8 unusedE19:7,
     sigbp:1;
  u8 vox;
  u8 camdf;
  u8 cbmdf;
  u8 ccmdf;
  u8 cdmdf;
  u8 langua;
  u8 sync;
  u8 stfc;
  u8 mffc;
  u8 sfafc;
  u8 sfbfc;
  u8 sfcfc;
  u8 sfdfc;
  u8 subfc;
  u8 fmfc;
  u8 sigfc;
  u8 modfc;
  u8 menufc;
  u8 txfc;
  u8 txdisp;
  u8 unknown9[5];
  u8 anil;
  u8 reps;
  u8 repm;
  u8 tmrmr;
  u8 unusedE37:7,
     ste:1;
  u8 rpste;
  u8 rptdl;
  u8 dtmfg;
  u8 mgain;
  u8 skiptx;
  u8 scmode;
  u8 tmrtx;
  u8 unknown10;
  u8 earpho;
} settings;
"""


GMRS_V2_MEM_FORMAT = """
#seekto 0x3200;
struct {
  u8 tmr;
  u8 unknown1;
  u8 sql;
  u8 unknown2;
  u8 unused3204:7,
     autolk:1;
  u8 tot;
  u8 apo;
  u8 unknown3;
  u8 abr;
  u8 unused3209:7,
     beep:1;
  u8 unknown4[4];
  u8 dtmfst;
  u8 unknown5[2];
  u8 screv;
  u8 unknown6[2];
  u8 pttid;
  u8 pttlt;
  u8 unknown7;
  u8 emctp;
  u8 emcch;
  u8 unusedE19:7,
     sigbp:1;
  u8 unknown8;   // vox
  u8 camdf;
  u8 cbmdf;
  u8 ccmdf;
  u8 cdmdf;
  u8 vox;        // langua
  u8 sync;
  u8 stfc;
  u8 mffc;
  u8 sfafc;
  u8 sfbfc;
  u8 sfcfc;
  u8 sfdfc;
  u8 subfc;
  u8 fmfc;
  u8 sigfc;
  u8 modfc;
  u8 menufc;
  u8 txfc;
  u8 unknown9[5];
  u8 anil;
  u8 reps;
  u8 repm;
  u8 tmrmr;
  u8 unusedE37:7,
     ste:1;
  u8 rpste;
  u8 rptdl;
  u8 dtmfg;
  u8 mgain;
  u8 skiptx;
  u8 scmode;
  u8 tmrtx;
  u8 unknown10[2];
  u8 earpho;
} settings;
"""


class BTechGMRS(BTechMobileCommon):
    """BTECH's GMRS Mobile"""
    COLOR_LCD = True
    COLOR_LCD2 = True
    NAME_LENGTH = 7
    UPLOAD_MEM_SIZE = 0X3400

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        mem_format = GMRS_MEM_FORMAT + GMRS_ORIG_MEM_FORMAT + \
            GMRS_MEM_FORMAT_PT2
        self._memobj = bitwise.parse(mem_format, self._mmap)

        # load specific parameters from the radio image
        self.set_options()

    def set_options(self):
        """This is to read the options from the image and set it in the
        environment, for now just the limits of the freqs in the VHF/UHF
        ranges"""

        # setting the correct ranges for each radio type
        ranges = self._memobj.ranges

        # the normal dual bands
        vhf = _decode_ranges(ranges.vhf_low, ranges.vhf_high)
        uhf = _decode_ranges(ranges.uhf_low, ranges.uhf_high)

        # DEBUG
        LOG.info("Radio ranges: VHF %d to %d" % vhf)
        LOG.info("Radio ranges: UHF %d to %d" % uhf)

        # set the class with the real data
        self._vhf_range = vhf
        self._uhf_range = uhf


# real radios
@directory.register
class GMRS50X1(BTechGMRS):
    """Baofeng Tech GMRS50X1"""
    MODEL = "GMRS-50X1"
    BANDS = 2
    LIST_TMR = LIST_TMR16
    _power_levels = [chirp_common.PowerLevel("High", watts=50),
                     chirp_common.PowerLevel("Mid", watts=10),
                     chirp_common.PowerLevel("Low", watts=5)]
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 521000000)
    _upper = 255
    _magic = MSTRING_GMRS50X1
    _fileid = [GMRS50X1_fp1, GMRS50X1_fp]
    _gmrs = True

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        _msg_duplex = 'Duplex must be "off" for this frequency'
        _msg_offset = 'Only simplex or +5 MHz offset allowed on GMRS'

        if not (mem.number >= 1 and mem.number <= 30):
            if mem.duplex != "off":
                msgs.append(chirp_common.ValidationWarning(_msg_duplex))

        return msgs

    def check_set_memory_immutable_policy(self, existing, new):
        if not (new.number >= 1 and new.number <= 30):
            existing.immutable = []
        super().check_set_memory_immutable_policy(existing, new)


@directory.register
class GMRS50V2(BTechGMRS):
    """Baofeng Tech GMRS50V2"""
    MODEL = "GMRS-50V2"
    BANDS = 2
    LIST_TMR = LIST_TMR16
    _power_levels = [chirp_common.PowerLevel("High", watts=50),
                     chirp_common.PowerLevel("Mid", watts=10),
                     chirp_common.PowerLevel("Low", watts=5)]
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 521000000)
    _upper = 255
    _magic = MSTRING_GMRS50X1
    _fileid = [GMRS50X1_fp1, GMRS50X1_fp]
    _gmrs = True

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        mem_format = GMRS_MEM_FORMAT + GMRS_V2_MEM_FORMAT + \
            GMRS_MEM_FORMAT_PT2
        self._memobj = bitwise.parse(mem_format, self._mmap)

        # load specific parameters from the radio image
        self.set_options()

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        _msg_duplex = 'Duplex must be "off" for this frequency'
        _msg_offset = 'Only simplex or +5 MHz offset allowed on GMRS'

        if mem.freq not in GMRS_FREQS:
            if mem.duplex != "off":
                msgs.append(chirp_common.ValidationWarning(_msg_duplex))
        elif mem.duplex:
            if mem.duplex and mem.offset != 5000000:
                msgs.append(chirp_common.ValidationWarning(_msg_offset))

        return msgs

    def check_set_memory_immutable_policy(self, existing, new):
        existing.immutable = []
        super().check_set_memory_immutable_policy(existing, new)

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


COLORHT_MEM_FORMAT = """
// #seekto 0x0000;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:4,
     scode:4;
  u8 unknown1:2,
     spmute:2,
     unknown2:2,
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
  u8 tmr;
  u8 unknownE01;
  u8 sql;
  u8 unknownE03[2];
  u8 tot;
  u8 unusedE06:7,
     save:1;
  u8 unknownE07;
  u8 abr;
  u8 unusedE09:7,
     beep:1;
  u8 unknownE0A[4];
  u8 unusedE0E:7,
     dsub:1;
  u8 unusedE0F:7,
     dtmfst:1;
  u8 screv;
  u8 unknownE11[3];
  u8 pttid;
  u8 unknownE15;
  u8 pttlt;
  u8 unknownE17;
  u8 emctp;
  u8 emcch;
  u8 unusedE1A:7,
     sigbp:1;
  u8 unknownE1B;
  u8 camdf;
  u8 cbmdf;
  u8 ccmdf;
  u8 cdmdf;
  u8 langua;
  u8 voice;
  u8 vox;
  u8 voxt;
  u8 sync;          // BTech radios use this as the display sync setting
                    // other radios use this as the auto keypad lock setting
  u8 stfc;
  u8 mffc;
  u8 sfafc;
  u8 sfbfc;
  u8 sfcfc;
  u8 sfdfc;
  u8 subfc;
  u8 fmfc;
  u8 sigfc;
  u8 menufc;
  u8 txfc;
  u8 rxfc;
  u8 unknownE31[5];
  u8 anil;
  u8 reps;
  u8 tmrmr;
  u8 unusedE39:7,
     ste:1;
  u8 rpste;
  u8 rptdl;
  u8 dtmfg;
  u8 tmrtx;
} settings;

#seekto 0x0E80;
struct {
  u8 unknown1;
  u8 vfomr;
  u8 unusedE82:7,
     keylock:1;
  u8 unknown2;
  u8 unknown3:4,
     vfomren:1,
     unknown4:1,
     reseten:1,
     menuen:1;
  u8 unknown5[11];
  u8 dispab;
  u8 unknown6[2];
  u8 menu;
  u8 unknown7[7];
  u8 vfomra;
  u8 vfomrb;
  u8 vfomrc;
  u8 vfomrd;
  u8 mrcha;
  u8 mrchb;
  u8 mrchc;
  u8 mrchd;
} settings2;

struct settings_vfo {
  u8 freq[8];
  u8 offset[6];
  u8 unknown2[2];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 spmute;
  u8 optsig;
  u8 unused1:7,
     scramble:1;
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
  struct settings_vfo c;
  struct settings_vfo d;
} vfo;

#seekto 0x0FE0;
struct {
  char line[16];
} static_msg;

#seekto 0x1000;
struct {
  char name[8];
  u8 unknown1[8];
} names[200];

#seekto 0x2400;
struct {
  u8 period; // one out of LIST_5TONE_STANDARD_PERIODS
  u8 group_tone;
  u8 repeat_tone;
  u8 unused[13];
} _5tone_std_settings[15];

#seekto 0x2500;
struct {
  u8 frame1[5];
  u8 frame2[5];
  u8 frame3[5];
  u8 standard;   // one out of LIST_5TONE_STANDARDS
} _5tone_codes[15];

// #seekto 0x25F0;
struct {
  u8 _5tone_delay1; // * 10ms
  u8 _5tone_delay2; // * 10ms
  u8 _5tone_delay3; // * 10ms
  u8 _5tone_first_digit_ext_length;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 decode_standard;
  u8 unknown5:5,
     _5tone_decode_call_frame3:1,
     _5tone_decode_call_frame2:1,
     _5tone_decode_call_frame1:1;
  u8 unknown6:5,
     _5tone_decode_disp_frame3:1,
     _5tone_decode_disp_frame2:1,
     _5tone_decode_disp_frame1:1;
  u8 decode_reset_time; // * 100 + 100ms
} _5tone_settings;

#seekto 0x2900;
struct {
  u8 code[16]; // 0=x0A, A=0x0D, B=0x0E, C=0x0F, D=0x00, #=0x0C *=0x0B
} dtmf_codes[15];

// #seekto 0x29F0;
struct {
  u8 dtmfspeed_on;  //list with 50..2000ms in steps of 10
  u8 dtmfspeed_off; //list with 50..2000ms in steps of 10
  u8 unknown0[14];
  u8 inspection[16];
  u8 monitor[16];
  u8 alarmcode[16];
  u8 stun[16];
  u8 kill[16];
  u8 revive[16];
  u8 unknown1[16];
  u8 unknown2[16];
  u8 unknown3[16];
  u8 unknown4[16];
  u8 unknown5[16];
  u8 unknown6[16];
  u8 unknown7[16];
  u8 masterid[16];
  u8 viceid[16];
  u8 unused01:7,
     mastervice:1;
  u8 unused02:3,
     mrevive:1,
     mkill:1,
     mstun:1,
     mmonitor:1,
     minspection:1;
  u8 unused03:3,
     vrevive:1,
     vkill:1,
     vstun:1,
     vmonitor:1,
     vinspection:1;
  u8 unused04:6,
     txdisable:1,
     rxdisable:1;
  u8 groupcode;
  u8 spacecode;
  u8 delayproctime; // * 100 + 100ms
  u8 resettime;     // * 100 + 100ms
} dtmf_settings;

#seekto 0x2D00;
struct {
  struct {
    ul16 freq1;
    u8 unused01[6];
    ul16 freq2;
    u8 unused02[6];
  } _2tone_encode[15];
  u8 duration_1st_tone; // *10ms
  u8 duration_2nd_tone; // *10ms
  u8 duration_gap;      // *10ms
  u8 unused03[13];
  struct {
    struct {
      u8 dec;      // one out of LIST_2TONE_DEC
      u8 response; // one out of LIST_2TONE_RESPONSE
      u8 alert;    // 1-16
    } decs[4];
    u8 unused04[4];
  } _2tone_decode[15];
  u8 unused05[16];

  struct {
    ul16 freqA;
    ul16 freqB;
    ul16 freqC;
    ul16 freqD;
    // unknown what those values mean, but they are
    // derived from configured frequencies
    ul16 derived_from_freqA; // 2304000/freqA
    ul16 derived_from_freqB; // 2304000/freqB
    ul16 derived_from_freqC; // 2304000/freqC
    ul16 derived_from_freqD; // 2304000/freqD
  }freqs[15];
  u8 reset_time;  // * 100 + 100ms - 100-8000ms
} _2tone;

#seekto 0x3D80;
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
  u8 unknown5[4];
  u8 unknown6[6];
  u8 uhf2_low[3];
  u8 uhf2_high[3];
} ranges;

#seekto 0x3F70;
struct {
  char fp[6];
} fingerprint;

"""


class QYTColorHT(BTechMobileCommon):
    """QTY's Color LCD Handheld and alike radios"""
    COLOR_LCD = True
    COLOR_LCD3 = True
    NAME_LENGTH = 8
    LIST_TMR = LIST_TMR15

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        self._memobj = bitwise.parse(COLORHT_MEM_FORMAT, self._mmap)

        # load specific parameters from the radio image
        self.set_options()

    def set_options(self):
        """This is to read the options from the image and set it in the
        environment, for now just the limits of the freqs in the VHF/UHF
        ranges"""

        # setting the correct ranges for each radio type
        ranges = self._memobj.ranges

        # the normal dual bands
        vhf = _decode_ranges(ranges.vhf_low, ranges.vhf_high)
        uhf = _decode_ranges(ranges.uhf_low, ranges.uhf_high)

        # DEBUG
        LOG.info("Radio ranges: VHF %d to %d" % vhf)
        LOG.info("Radio ranges: UHF %d to %d" % uhf)

        # the additional bands
        if self.MODEL in ["KT-8R"]:
            # 200 MHz band
            vhf2 = _decode_ranges(ranges.vhf2_low, ranges.vhf2_high)
            LOG.info("Radio ranges: VHF(220) %d to %d" % vhf2)
            self._220_range = vhf2

            # 350 MHz band
            uhf2 = _decode_ranges(ranges.uhf2_low, ranges.uhf2_high)
            LOG.info("Radio ranges: UHF(350) %d to %d" % uhf2)
            self._350_range = uhf2

        # set the class with the real data
        self._vhf_range = vhf
        self._uhf_range = uhf


# real radios
@directory.register
class KT8R(QYTColorHT):
    """QYT KT8R"""
    VENDOR = "QYT"
    MODEL = "KT-8R"
    BANDS = 4
    LIST_TMR = LIST_TMR16
    _vhf_range = (136000000, 175000000)
    _220_range = (200000000, 261000000)
    _uhf_range = (400000000, 481000000)
    _350_range = (350000000, 391000000)
    _magic = MSTRING_KT8R
    _fileid = [KT8R_fp2, KT8R_fp1, KT8R_fp, KT8R_fp3]
    _power_levels = [chirp_common.PowerLevel("High", watts=5),
                     chirp_common.PowerLevel("Low", watts=1)]


COLOR9900_MEM_FORMAT = """
// #seekto 0x0000;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:4,
     scode:4;
  u8 unknown1:2,
     spmute:2,
     unknown2:2,
     optsig:2;
  u8 unknown3:3,
     scramble:1,
     unknown4:2,
     power:2;
  u8 unknown5:1,
     wide:1,
     unknown6:2,
     bcl:1,
     add:1,
     pttid:2;
} memory[200];

#seekto 0x0E00;
struct {
  u8 tmr;
  u8 unknown1;
  u8 sql;
  u8 unknown2[2];
  u8 tot;
  u8 volume;
  u8 unknown3;
  u8 abr;
  u8 unusedE09:7,
     beep:1;
  u8 unknown4[4];
  u8 unusedE0E:7,
     dsub:1;
  u8 unusedE0F:7,
     dtmfst:1;
  u8 unknown_e10;
  u8 unknown_e11;
  u8 screv;
  u8 unknown_e13;
  u8 unknown_e14;
  u8 pttid;
  u8 pttlt;
  u8 unknown7;
  u8 emctp;
  u8 emcch;
  u8 unusedE1A:7,
     sigbp:1;
  u8 unknown8;
  u8 camdf;
  u8 cbmdf;
  u8 ccmdf;
  u8 language;
  u8 tmrtx;
  u8 vox;
  u8 voxt;
  u8 unusedE23:7,
     autolock:1;
  u8 asfc;
  u8 mainfc;
  u8 a_fc;
  u8 b_fc;
  u8 c_fc;
  u8 subfc;
  u8 battfc;
  u8 sigfc;
  u8 menufc;
  u8 txfc;
  u8 rxfc;
  u8 unknown_e2f;
  u8 unknown_e30;
  u8 unknown9[3];
  u8 anil;
  u8 reps;
  u8 tmrmr;
  u8 unusedE37:7,
     ste:1;
  u8 rpste;
  u8 rptdl;
  u8 dtmfg;
} settings;

#seekto 0x0E80;
struct {
  u8 unknown1;
  u8 vfomr;
  u8 unusedE82:7,
     keylock:1;
  u8 unknown2;
  u8 unknown3:4,
     vfomren:1,
     unknown4:1,
     reseten:1,
     menuen:1;
  u8 unknown5[11];
  u8 dispab;
  u8 unknown6[2];
  u8 menu;
  u8 unknown7[7];
  u8 vfomra;
  u8 vfomrb;
  u8 vfomrc;
  u8 vfomrd;
  u8 mrcha;
  u8 mrchb;
  u8 mrchc;
  u8 mrchd;
} settings2;

struct settings_vfo {
  u8 freq[8];
  u8 offset[6];
  u8 unknown2[2];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 spmute;
  u8 optsig;
  u8 unused1:7,
     scramble:1;
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
  struct settings_vfo c;
  struct settings_vfo d;
} vfo;

// #seekto 0x0F80;
struct {
  char line1[8];
  char line2[8];
  char line3[8];
  char line4[8];
  char line5[8];
  char line6[8];
  char line7[8];
  char line8[8];
} poweron_msg;

#seekto 0x0FE0;
struct {
  char line[16];
} static_msg;

#seekto 0x1000;
struct {
  char name[7];
  u8 unknown1[9];
} names[200];

#seekto 0x2400;
struct {
  u8 period; // one out of LIST_5TONE_STANDARD_PERIODS
  u8 group_tone;
  u8 repeat_tone;
  u8 unused[13];
} _5tone_std_settings[15];

#seekto 0x2500;
struct {
  u8 frame1[5];
  u8 frame2[5];
  u8 frame3[5];
  u8 standard;   // one out of LIST_5TONE_STANDARDS
} _5tone_codes[15];

// #seekto 0x25F0;
struct {
  u8 _5tone_delay1; // * 10ms
  u8 _5tone_delay2; // * 10ms
  u8 _5tone_delay3; // * 10ms
  u8 _5tone_first_digit_ext_length;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 decode_standard;
  u8 unknown5:5,
     _5tone_decode_call_frame3:1,
     _5tone_decode_call_frame2:1,
     _5tone_decode_call_frame1:1;
  u8 unknown6:5,
     _5tone_decode_disp_frame3:1,
     _5tone_decode_disp_frame2:1,
     _5tone_decode_disp_frame1:1;
  u8 decode_reset_time; // * 100 + 100ms
} _5tone_settings;

#seekto 0x2900;
struct {
  u8 code[16]; // 0=x0A, A=0x0D, B=0x0E, C=0x0F, D=0x00, #=0x0C *=0x0B
} dtmf_codes[15];

// #seekto 0x29F0;
struct {
  u8 dtmfspeed_on;  //list with 50..2000ms in steps of 10      // 9f0
  u8 dtmfspeed_off; //list with 50..2000ms in steps of 10      // 9f1
  u8 unknown0[14];                                             // 9f2-9ff
  u8 inspection[16];                                           // a00-a0f
  u8 monitor[16];                                              // a10-a1f
  u8 alarmcode[16];                                            // a20-a2f
  u8 stun[16];                                                 // a30-a3f
  u8 kill[16];                                                 // a40-a4f
  u8 revive[16];                                               // a50-a5f
  u8 unknown1[16];                                             // a60-a6f
  u8 unknown2[16];                                             // a70-a7f
  u8 unknown3[16];                                             // a80-a8f
  u8 unknown4[16];                                             // a90-a9f
  u8 unknown5[16];                                             // aa0-aaf
  u8 unknown6[16];                                             // ab0-abf
  u8 unknown7[16];                                             // ac0-acf
  u8 masterid[16];                                             // ad0-adf
  u8 viceid[16];                                               // ae0-aef
  u8 unused01:7,                                               // af0
     mastervice:1;
  u8 unused02:3,                                               // af1
     mrevive:1,
     mkill:1,
     mstun:1,
     mmonitor:1,
     minspection:1;
  u8 unused03:3,                                               // af2
     vrevive:1,
     vkill:1,
     vstun:1,
     vmonitor:1,
     vinspection:1;
  u8 unused04:6,                                               // af3
     txdisable:1,
     rxdisable:1;
  u8 groupcode;                                                // af4
  u8 spacecode;                                                // af5
  u8 delayproctime; // * 100 + 100ms                           // af6
  u8 resettime;     // * 100 + 100ms                           // af7
} dtmf_settings;

#seekto 0x2D00;
struct {
  struct {
    ul16 freq1;
    u8 unused01[6];
    ul16 freq2;
    u8 unused02[6];
  } _2tone_encode[15];
  u8 duration_1st_tone; // *10ms
  u8 duration_2nd_tone; // *10ms
  u8 duration_gap;      // *10ms
  u8 unused03[13];
  struct {
    struct {
      u8 dec;      // one out of LIST_2TONE_DEC
      u8 response; // one out of LIST_2TONE_RESPONSE
      u8 alert;    // 1-16
    } decs[4];
    u8 unused04[4];
  } _2tone_decode[15];
  u8 unused05[16];

  struct {
    ul16 freqA;
    ul16 freqB;
    ul16 freqC;
    ul16 freqD;
    // unknown what those values mean, but they are
    // derived from configured frequencies
    ul16 derived_from_freqA; // 2304000/freqA
    ul16 derived_from_freqB; // 2304000/freqB
    ul16 derived_from_freqC; // 2304000/freqC
    ul16 derived_from_freqD; // 2304000/freqD
  }freqs[15];
  u8 reset_time;  // * 100 + 100ms - 100-8000ms
} _2tone;

#seekto 0x3D80;
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
  u8 unknown5[4];
  u8 unknown6[6];
  u8 uhf2_low[3];
  u8 uhf2_high[3];
} ranges;

#seekto 0x3F70;
struct {
  char fp[6];
} fingerprint;

"""


COLOR20V2_MEM_FORMAT = """
// #seekto 0x0000;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown0:4,
     scode:4;
  u8 unknown1:2,
     spmute:2,
     unknown2:2,
     optsig:2;
  u8 unknown3:3,
     scramble:1,
     unknown4:2,
     power:2;
  u8 unknown5:1,
     wide:1,
     unknown6:2,
     bcl:1,
     add:1,
     pttid:2;
} memory[200];

#seekto 0x0E00;
struct {
  u8 tmr;
  u8 unknown1;
  u8 sql;
  u8 unknown2;
  u8 unusedE04:7,
     autolock:1;
  u8 tot;
  u8 apo;
  u8 unknown3;
  u8 abr;
  u8 unusedE09:7,
     beep:1;
  u8 unknown4[4];
  u8 unusedE0E:7,
     dtmfst:1;
  u8 unknown5[2];
  u8 screv;
  u8 unknown6[2];
  u8 pttid;
  u8 pttlt;
  u8 unknown7;
  u8 emctp;
  u8 emcch;
  u8 unusedE19:7,
     sigbp:1;
  u8 unknown8;
  u8 camdf;
  u8 cbmdf;
  u8 ccmdf;
  u8 vox;
  u8 voxt;
  u8 sync;
  u8 asfc;
  u8 mainfc;
  u8 a_fc;
  u8 b_fc;
  u8 c_fc;
  u8 subfc;
  u8 battfc;
  u8 sigfc;
  u8 menufc;
  u8 txfc;
  u8 rxfc;
  u8 repsw;
  u8 unusedE2D:7,
     dsub:1;
  u8 unknown9[5];
  u8 anil;
  u8 reps;
  u8 repm;
  u8 tmrmr;
  u8 unusedE37:7,
     ste:1;
  u8 rpste;
  u8 rptdl;
  u8 dtmfg;
  u8 mgain;
  u8 skiptx;
  u8 scmode;
  u8 tmrtx;
  u8 volume;
  u8 unknown_10;
  u8 unusedE41:7,
     save:1;
} settings;

#seekto 0x0E80;
struct {
  u8 unknown1;
  u8 vfomr;
  u8 unusedE82:7,
     keylock:1;
  u8 unknown2;
  u8 unknown3:4,
     vfomren:1,
     unknown4:1,
     reseten:1,
     menuen:1;
  u8 unknown5[11];
  u8 dispab;
  u8 unknown6[2];
  u8 menu;
  u8 unknown7[7];
  u8 vfomra;
  u8 vfomrb;
  u8 vfomrc;
  u8 vfomrd;
  u8 mrcha;
  u8 mrchb;
  u8 mrchc;
  u8 mrchd;
} settings2;

struct settings_vfo {
  u8 freq[8];
  u8 offset[6];
  u8 unknown2[2];
  ul16 rxtone;
  ul16 txtone;
  u8 scode;
  u8 spmute;
  u8 optsig;
  u8 unused1:7,
     scramble:1;
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
  struct settings_vfo c;
  struct settings_vfo d;
} vfo;

// #seekto 0x0F80;
struct {
  char line1[8];
  char line2[8];
  char line3[8];
  char line4[8];
  char line5[8];
  char line6[8];
  char line7[8];
  char line8[8];
} poweron_msg;

#seekto 0x0FE0;
struct {
  char line[16];
} static_msg;

#seekto 0x1000;
struct {
  char name[7];
  u8 unknown1[9];
} names[200];

#seekto 0x2400;
struct {
  u8 period; // one out of LIST_5TONE_STANDARD_PERIODS
  u8 group_tone;
  u8 repeat_tone;
  u8 unused[13];
} _5tone_std_settings[15];

#seekto 0x2500;
struct {
  u8 frame1[5];
  u8 frame2[5];
  u8 frame3[5];
  u8 standard;   // one out of LIST_5TONE_STANDARDS
} _5tone_codes[15];

// #seekto 0x25F0;
struct {
  u8 _5tone_delay1; // * 10ms
  u8 _5tone_delay2; // * 10ms
  u8 _5tone_delay3; // * 10ms
  u8 _5tone_first_digit_ext_length;
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 decode_standard;
  u8 unknown5:5,
     _5tone_decode_call_frame3:1,
     _5tone_decode_call_frame2:1,
     _5tone_decode_call_frame1:1;
  u8 unknown6:5,
     _5tone_decode_disp_frame3:1,
     _5tone_decode_disp_frame2:1,
     _5tone_decode_disp_frame1:1;
  u8 decode_reset_time; // * 100 + 100ms
} _5tone_settings;

#seekto 0x2900;
struct {
  u8 code[16]; // 0=x0A, A=0x0D, B=0x0E, C=0x0F, D=0x00, #=0x0C *=0x0B
} dtmf_codes[15];

// #seekto 0x29F0;
struct {
  u8 dtmfspeed_on;  //list with 50..2000ms in steps of 10      // 9f0
  u8 dtmfspeed_off; //list with 50..2000ms in steps of 10      // 9f1
  u8 unknown0[14];                                             // 9f2-9ff
  u8 inspection[16];                                           // a00-a0f
  u8 monitor[16];                                              // a10-a1f
  u8 alarmcode[16];                                            // a20-a2f
  u8 stun[16];                                                 // a30-a3f
  u8 kill[16];                                                 // a40-a4f
  u8 revive[16];                                               // a50-a5f
  u8 unknown1[16];                                             // a60-a6f
  u8 unknown2[16];                                             // a70-a7f
  u8 unknown3[16];                                             // a80-a8f
  u8 unknown4[16];                                             // a90-a9f
  u8 unknown5[16];                                             // aa0-aaf
  u8 unknown6[16];                                             // ab0-abf
  u8 unknown7[16];                                             // ac0-acf
  u8 masterid[16];                                             // ad0-adf
  u8 viceid[16];                                               // ae0-aef
  u8 unused01:7,                                               // af0
     mastervice:1;
  u8 unused02:3,                                               // af1
     mrevive:1,
     mkill:1,
     mstun:1,
     mmonitor:1,
     minspection:1;
  u8 unused03:3,                                               // af2
     vrevive:1,
     vkill:1,
     vstun:1,
     vmonitor:1,
     vinspection:1;
  u8 unused04:6,                                               // af3
     txdisable:1,
     rxdisable:1;
  u8 groupcode;                                                // af4
  u8 spacecode;                                                // af5
  u8 delayproctime; // * 100 + 100ms                           // af6
  u8 resettime;     // * 100 + 100ms                           // af7
} dtmf_settings;

#seekto 0x2D00;
struct {
  struct {
    ul16 freq1;
    u8 unused01[6];
    ul16 freq2;
    u8 unused02[6];
  } _2tone_encode[15];
  u8 duration_1st_tone; // *10ms
  u8 duration_2nd_tone; // *10ms
  u8 duration_gap;      // *10ms
  u8 unused03[13];
  struct {
    struct {
      u8 dec;      // one out of LIST_2TONE_DEC
      u8 response; // one out of LIST_2TONE_RESPONSE
      u8 alert;    // 1-16
    } decs[4];
    u8 unused04[4];
  } _2tone_decode[15];
  u8 unused05[16];

  struct {
    ul16 freqA;
    ul16 freqB;
    ul16 freqC;
    ul16 freqD;
    // unknown what those values mean, but they are
    // derived from configured frequencies
    ul16 derived_from_freqA; // 2304000/freqA
    ul16 derived_from_freqB; // 2304000/freqB
    ul16 derived_from_freqC; // 2304000/freqC
    ul16 derived_from_freqD; // 2304000/freqD
  }freqs[15];
  u8 reset_time;  // * 100 + 100ms - 100-8000ms
} _2tone;

#seekto 0x3D80;
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
  u8 unknown5[4];
  u8 unknown6[6];
  u8 uhf2_low[3];
  u8 uhf2_high[3];
} ranges;

#seekto 0x3F70;
struct {
  char fp[6];
} fingerprint;

"""


class BTechColorWP(BTechMobileCommon):
    """BTECH's Color WP Mobile and alike radios"""
    COLOR_LCD = True
    COLOR_LCD4 = True
    NAME_LENGTH = 7
    LIST_TMR = LIST_TMR7

    def set_options(self):
        """This is to read the options from the image and set it in the
        environment, for now just the limits of the freqs in the VHF/UHF
        ranges"""

        # setting the correct ranges for each radio type
        ranges = self._memobj.ranges

        # the normal dual bands
        vhf = _decode_ranges(ranges.vhf_low, ranges.vhf_high)
        uhf = _decode_ranges(ranges.uhf_low, ranges.uhf_high)

        # DEBUG
        LOG.info("Radio ranges: VHF %d to %d" % vhf)
        LOG.info("Radio ranges: UHF %d to %d" % uhf)

        # set the class with the real data
        self._vhf_range = vhf
        self._uhf_range = uhf


# real radios
@directory.register
class KTWP12(BTechColorWP):
    """QYT KT-WP12"""
    VENDOR = "QYT"
    MODEL = "KT-WP12"
    BANDS = 2
    UPLOAD_MEM_SIZE = 0X3100
    _power_levels = [chirp_common.PowerLevel("High", watts=25),
                     chirp_common.PowerLevel("Low", watts=5)]
    _upper = 199
    _magic = MSTRING_KTWP12
    _fileid = [KTWP12_fp]
    _gmrs = False

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        self._memobj = bitwise.parse(COLOR9900_MEM_FORMAT, self._mmap)

        # load specific parameters from the radio image
        self.set_options()


@directory.register
class WP9900(BTechColorWP):
    """Anysecu WP-9900"""
    VENDOR = "Anysecu"
    MODEL = "WP-9900"
    BANDS = 2
    UPLOAD_MEM_SIZE = 0X3100
    _power_levels = [chirp_common.PowerLevel("High", watts=25),
                     chirp_common.PowerLevel("Low", watts=5)]
    _upper = 199
    _magic = MSTRING_KTWP12
    _fileid = [WP9900_fp]
    _gmrs = False

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        self._memobj = bitwise.parse(COLOR9900_MEM_FORMAT, self._mmap)

        # load specific parameters from the radio image
        self.set_options()


@directory.register
class KT5000(BTechColorWP):
    """QYT KT-5000"""
    # TODO: memory map is not EXACTLY the same as in WP12. E.g. setting
    #       "C display mode" overwrites VOX setting
    VENDOR = "QYT"
    MODEL = "KT-5000"
    BANDS = 2
    UPLOAD_MEM_SIZE = 0X3100
    _power_levels = [chirp_common.PowerLevel("High", watts=25),
                     chirp_common.PowerLevel("Low", watts=5)]
    _upper = 199
    _magic = MSTRING_KT5000
    _fileid = [KT5000_fp]
    _gmrs = False

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        self._memobj = bitwise.parse(COLOR9900_MEM_FORMAT, self._mmap)

        # load specific parameters from the radio image
        self.set_options()

    def get_features(self):
        rf = super().get_features()
        rf.has_settings = False
        return rf


@directory.register
class GMRS20V2(BTechColorWP):
    """Baofeng Tech GMRS-20V2"""
    MODEL = "GMRS-20V2"
    BANDS = 2
    UPLOAD_MEM_SIZE = 0X3100
    _power_levels = [chirp_common.PowerLevel("High", watts=20),
                     chirp_common.PowerLevel("", watts=6),
                     chirp_common.PowerLevel("Low", watts=5)]
    _upper = 199
    _magic = MSTRING_GMRS20V2
    _fileid = [GMRS20V2_fp2, GMRS20V2_fp1, GMRS20V2_fp]
    _gmrs = True

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)

        _msg_duplex = 'Duplex must be "off" for this frequency'
        _msg_offset = 'Only simplex or +5 MHz offset allowed on GMRS'

        if mem.freq not in GMRS_FREQS:
            if mem.duplex != "off":
                msgs.append(chirp_common.ValidationWarning(_msg_duplex))
        elif mem.duplex:
            if mem.duplex and mem.offset != 5000000:
                msgs.append(chirp_common.ValidationWarning(_msg_offset))

        return msgs

    def check_set_memory_immutable_policy(self, existing, new):
        existing.immutable = []
        super().check_set_memory_immutable_policy(existing, new)

    def process_mmap(self):
        """Process the mem map into the mem object"""

        # Get it
        self._memobj = bitwise.parse(COLOR20V2_MEM_FORMAT, self._mmap)

        # load specific parameters from the radio image
        self.set_options()
