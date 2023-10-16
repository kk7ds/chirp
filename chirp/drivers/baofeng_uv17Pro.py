# Copyright 2023:
# * Sander van der Wel, <svdwel@icloud.com>
# this software is a modified version of the boafeng driver by:
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

import logging

from chirp import chirp_common, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings, \
    InvalidValueError, RadioSettingValue
import time
import struct
import logging
from chirp import errors, util

LOG = logging.getLogger(__name__)

# #### MAGICS #########################################################

# Baofeng UV-17L magic string
MSTRING_UV17L = b"PROGRAMBFNORMALU"
MSTRING_UV17PROGPS = b"PROGRAMCOLORPROU"

DTMF_CHARS = "0123456789 *#ABCD"
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]

LIST_AB = ["A", "B"]
LIST_ALMOD = ["Site", "Tone", "Code"]
LIST_BANDWIDTH = ["Wide", "Narrow"]
LIST_COLOR = ["Off", "Blue", "Orange", "Purple"]
LIST_DTMFSPEED = ["%s ms" % x for x in [50, 100, 200, 300, 500]]
LIST_HANGUPTIME = ["%s s" % x for x in [3, 4, 5, 6, 7, 8, 9, 10]]
LIST_DTMFST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
LIST_MODE = ["Channel", "Name", "Frequency"]
LIST_OFF1TO9 = ["Off"] + list("123456789")
LIST_OFF1TO10 = LIST_OFF1TO9 + ["10"]
LIST_OFFAB = ["Off"] + LIST_AB
LIST_RESUME = ["TO", "CO", "SE"]
LIST_PONMSG = ["Full", "Message"]
LIST_PTTID = ["Off", "BOT", "EOT", "Both"]
LIST_SCODE = ["%s" % x for x in range(1, 21)]
LIST_RPSTE = ["Off"] + ["%s" % x for x in range(1, 11)]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SHIFTD = ["Off", "+", "-"]
LIST_STEDELAY = ["Off"] + ["%s ms" % x for x in range(100, 1100, 100)]
LIST_STEP = [str(x) for x in STEPS]
LIST_TIMEOUT = ["%s sec" % x for x in range(15, 615, 15)]
LIST_TXPOWER = ["High", "Low"]
LIST_VOICE = ["Off", "English", "Chinese"]
LIST_WORKMODE = ["Frequency", "Channel"]

TXP_CHOICES = ["High", "Low"]
TXP_VALUES = [0x00, 0x02]

STIMEOUT = 1.5

def model_match(cls, data):
    """Match the opened image to the correct version"""
    return data[cls.MEM_TOTAL:] == bytes(cls.MODEL, 'utf-8')

    
def _crypt(symbolIndex, buffer):
    #Some weird encryption is used. From the table below, we only use "CO 7".
    tblEncrySymbol = [b"BHT ", b"CO 7", b"A ES", b" EIY", b"M PQ", 
                    b"XN Y", b"RVB ", b" HQP", b"W RC", b"MS N", 
                    b" SAT", b"K DH", b"ZO R", b"C SL", b"6RB ", 
                    b" JCG", b"PN V", b"J PK", b"EK L", b"I LZ"]
    tblEncrySymbols = tblEncrySymbol[symbolIndex]
    decBuffer=b""
    index1 = 0
    for index2 in range(len(buffer)):
        if ((tblEncrySymbols[index1] != 32) & (buffer[index2] != 0) & (buffer[index2] != 255) & 
            (buffer[index2] != tblEncrySymbols[index1]) & (buffer[index2] != (tblEncrySymbols[index1] ^ 255))):
            decByte = buffer[index2] ^ tblEncrySymbols[index1]
            decBuffer += decByte.to_bytes(1, 'big')
        else:
            decBuffer += buffer[index2].to_bytes(1, 'big')
        index1 = (index1 + 1) % 4
    return decBuffer

def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except:
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if len(data) != amount:
        msg = "Error reading data from radio: not the amount of data we want."
        raise errors.RadioError(msg)

    return data


def _rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        #print(data)
        #print(radio)
        radio.pipe.write(data)
    except:
        raise errors.RadioError("Error sending data to radio")

def _make_read_frame(addr, length):
    """Pack the info in the header format"""
    frame = _make_frame(b"\x52", addr, length)
    # Return the data

    return frame

def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the header format"""
    frame = cmd+struct.pack(">i",addr)[2:]+struct.pack("b", length)
    # add the data if set
    if len(data) != 0:
        frame += data
    # return the data
    return frame


def _recv(radio, addr, length):
    """Get data from the radio """
    # read 4 bytes of header
    hdr = _rawrecv(radio, 4)

    # read data
    data = _rawrecv(radio, length)

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(hdr + data))

    c, a, l = struct.unpack(">BHB", hdr)
    if a != addr or l != length or c != ord("X"):
        LOG.error("Invalid answer for block 0x%04x:" % addr)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Unknown response from the radio")

    return data


def _get_radio_firmware_version(radio):
    # There is a problem in new radios where a different firmware version is
    # received when directly reading a single block as compared to what is
    # received when reading sequential blocks. This causes a mismatch between
    # the image firmware version and the radio firmware version when uploading
    # an image that came from the same radio. The workaround is to read 1 or
    # more consecutive blocks prior to reading the block with the firmware
    # version.
    #
    # Read 2 consecutive blocks to get the radio firmware version.
    for addr in range(0x1E80, 0x1F00, radio._recv_block_size):
        frame = _make_frame("S", addr, radio._recv_block_size)

        # sending the read request
        _rawsend(radio, frame)

        if radio._ack_block and addr != 0x1E80:
            ack = _rawrecv(radio, 1)
            if ack != b"\x06":
                raise errors.RadioError(
                    "Radio refused to send block 0x%04x" % addr)

        # now we read
        block = _recv(radio, addr, radio._recv_block_size)

        _rawsend(radio, b"\x06")
        time.sleep(0.05)

    # get firmware version from the last block read
    version = block[48:64]
    return version


def _image_ident_from_data(data, start, stop):
    return data[start:stop]


def _get_image_firmware_version(radio):
    return _image_ident_from_data(radio.get_mmap(), radio._fw_ver_start,
                                  radio._fw_ver_start + 0x10)

def _sendmagic(radio, magic, response):
    _rawsend(radio, magic)
    ack = _rawrecv(radio, len(response))
    if ack != response:
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to enter read mode")
    
def _do_ident(radio):
    """Put the radio in PROGRAM mode & identify it"""
    radio.pipe.baudrate = radio.BAUDRATE
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # Flush input buffer
    _clean_buffer(radio)

    # Ident radio
    magic = radio._magic
    _rawsend(radio, magic)
    ack = _rawrecv(radio, radio._magic_response_length)

    if not ack.startswith(radio._fingerprint):
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond as expected (A)")

    return True


def _ident_radio(radio):
    for magic in radio._magic:
        error = None
        try:
            data = _do_ident(radio, magic)
            return data
        except errors.RadioError as e:
            print(e)
            error = e
            time.sleep(2)
    if error:
        raise error
    raise errors.RadioError("Radio did not respond")


def _download(radio):
    """Get the memory map"""

    # Put radio in program mode and identify it
    _do_ident(radio)
    for index in range(len(radio._magics)):
        _rawsend(radio, radio._magics[index])
        _rawrecv(radio, radio._magicResponseLengths[index])

    data = b""

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    for i in range(len(radio.MEM_SIZES)):
        MEM_SIZE = radio.MEM_SIZES[i]
        MEM_START = radio.MEM_STARTS[i]
        for addr in range(MEM_START, MEM_START + MEM_SIZE, radio.BLOCK_SIZE):
            frame = _make_read_frame(addr, radio.BLOCK_SIZE)
            # DEBUG
            LOG.debug("Frame=" + util.hexprint(frame))

            # Sending the read request
            _rawsend(radio, frame)

            # Now we read data
            d = _rawrecv(radio, radio.BLOCK_SIZE + 4)

            LOG.debug("Response Data= " + util.hexprint(d))
            d = _crypt(1, d[4:])

            # Aggregate the data
            data += d

            # UI Update
            status.cur = len(data) // radio.BLOCK_SIZE
            status.msg = "Cloning from radio..."
            radio.status_fn(status)
    data += bytes(radio.MODEL, 'utf-8')
    return data

def _upload(radio):
    # Put radio in program mode and identify it
    _do_ident(radio)
    for index in range(len(radio._magics)):
        _rawsend(radio, radio._magics[index])
        _rawrecv(radio, radio._magicResponseLengths[index])

    data = b""

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data_addr = 0x00
    for i in range(len(radio.MEM_SIZES)):
        MEM_SIZE = radio.MEM_SIZES[i]
        MEM_START = radio.MEM_STARTS[i]
        for addr in range(MEM_START, MEM_START + MEM_SIZE, radio.BLOCK_SIZE):
            data = radio.get_mmap()[data_addr:data_addr + radio.BLOCK_SIZE]
            data = _crypt(1, data)
            data_addr += radio.BLOCK_SIZE

            frame = _make_frame(b"W", addr, radio.BLOCK_SIZE, data)
            # DEBUG
            LOG.debug("Frame=" + util.hexprint(frame))
            #print()
            #print(hex(data_addr))
            #print(util.hexprint(frame))

            # Sending the read request
            _rawsend(radio, frame)

            # receiving the response
            ack = _rawrecv(radio, 1)
            #ack = b"\x06"
            if ack != b"\x06":
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            # UI Update
            status.cur = data_addr // radio.BLOCK_SIZE
            status.msg = "Cloning to radio..."
            radio.status_fn(status)
    data += bytes(radio.MODEL, 'utf-8')
    return data


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
    return True

@directory.register
class UV17Pro(chirp_common.CloneModeRadio, 
              chirp_common.ExperimentalRadio):
    """Baofeng UV-17Pro"""
    VENDOR = "Baofeng"
    MODEL = "UV-17Pro"
    NEEDS_COMPAT_SERIAL = False

    MEM_STARTS = [0x0000, 0x9000, 0xA000, 0xD000]
    MEM_SIZES =  [0x8040, 0x0040, 0x02C0, 0x0040]

    MEM_TOTAL = 0x8380
    BLOCK_SIZE = 0x40
    STIMEOUT = 2
    BAUDRATE = 115200

    _gmrs = False
    _bw_shift = False
    _support_banknames = False

    _tri_band = True
    _fileid = []
    _magic = MSTRING_UV17L
    _magic_response_length = 1
    _fingerprint = b"\x06"
    _magics = [b"\x46", b"\x4d", b"\x53\x45\x4E\x44\x21\x05\x0D\x01\x01\x01\x04\x11\x08\x05\x0D\x0D\x01\x11\x0F\x09\x12\x09\x10\x04\x00"]
    _magicResponseLengths = [16, 15, 1]
    _fw_ver_start = 0x1EF0
    _recv_block_size = 0x40
    _mem_size = MEM_TOTAL
    _ack_block = True
    _aniid = True
    _vfoscan = False

    MODES = ["NFM", "FM"]
    VALID_CHARS = chirp_common.CHARSET_ALPHANUMERIC + \
        "!@#$%^&*()+-=[]:\";'<>?,./"
    LENGTH_NAME = 12
    SKIP_VALUES = ["", "S"]
    DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))
    RXTX_CODES = ('Off', )
    for code in chirp_common.TONES:
        RXTX_CODES = (RXTX_CODES + (str(code), ))
    for code in DTCS_CODES:
        RXTX_CODES = (RXTX_CODES + ('D' + str(code) + 'N', ))
    for code in DTCS_CODES:
        RXTX_CODES = (RXTX_CODES + ('D' + str(code) + 'I', ))
    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low",  watts=1.00)]
    _airband = (108000000, 136000000)
    _vhf_range = (136000000, 174000000)
    _vhf2_range = (200000000, 260000000)
    _uhf_range = (400000000, 520000000)
    _uhf2_range = (350000000, 390000000)

    VALID_BANDS = [_vhf_range, _vhf2_range,
                   _uhf_range]
    PTTID_LIST = LIST_PTTID
    SCODE_LIST = LIST_SCODE

    MEM_FORMAT = """
    #seekto 0x0000;
    struct {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      ul16 rxtone;
      ul16 txtone;
      u8 scode:8;
      u8 pttid:8;
      u8 lowpower:8;
      u8 unknown1:1,
         wide:1,
         sqmode:2,
         bcl:1,
         scan:1,
         unknown2:1,
         fhss:1;
      u8 unknown3:8;
      u8 unknown4:8;
      u8 unknown5:8;
      u8 unknown6:8;
      char name[12];
    } memory[1000];

    #seekto 0x8080;
    struct {
      u8 code[5];
      u8 unknown[1];
      u8 unused1:6,
         aniid:2;
      u8 dtmfon;
      u8 dtmfoff;
    } ani;

    #seekto 0x80A0;
    struct {
      u8 code[5];
      u8 name[10];
      u8 unused:8;
    } pttid[20];

    
    #seekto 0x8280;
    struct {
      char name1[12];
      u32 unknown1;
      char name2[12];
      u32 unknown2;
      char name3[12];
      u32 unknown3;
      char name4[12];
      u32 unknown4;
      char name5[12];
      u32 unknown5;
      char name6[12];
      u32 unknown6;
      char name7[12];
      u32 unknown7;
      char name8[12];
      u32 unknown8;
      char name9[12];
      u32 unknown9;
      char name10[12];
      u32 unknown10;
    } bank_names;

    struct vfo {
      u8 freq[8];
      ul16 rxtone;
      ul16 txtone;
      u8 unknown0;
      u8 bcl;
      u8 sftd:3,
         scode:5;
      u8 unknown1;
      u8 lowpower;
      u8 unknown2:1, 
         wide:1,
         unknown3:5,
         fhss:1;
      u8 unknown4;
      u8 step;
      u8 offset[6];
      u8 unknown5[2];
      u8 sqmode;
      u8 unknown6[3];
    };

    #seekto 0x8000;
    struct {
      struct vfo a;
      struct vfo b;
    } vfo;

    #seekto 0x8040;
    struct {
      char unknown0[11];
      u8 pttid;
      char unknown02[3];
      u8 uknown2:7,
         bcl:1;
      char unknown5[28];
      ul16 vfoscanmin;
      ul16 vfoscanmax;
      char unknown3[9];
      u8 hangup;
      char unknown4[6];
    } settings;
    """

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = _(
            "Follow these instructions to download your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to upload your info:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def process_mmap(self):
        """Process the mem map into the mem object"""
        if (len(self._mmap) == self.MEM_TOTAL) or (len(self._mmap) == self.MEM_TOTAL + len(self.MODEL)):
            self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)
        else:
            raise errors.ImageDetectFailed('Image length mismatch.\nTry reloading the configuration'
                                           ' from the radio.')

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        other = RadioSettingGroup("other", "Other Settings")
        work = RadioSettingGroup("work", "Work Mode Settings")
        fm_preset = RadioSettingGroup("fm_preset", "FM Preset")
        dtmfe = RadioSettingGroup("dtmfe", "DTMF Encode Settings")
        service = RadioSettingGroup("service", "Service Settings")
        top = RadioSettings(basic, advanced, other, work, fm_preset, dtmfe,
                            service)
     
        def _filterName(name, zone):
            fname = ""
            charset=chirp_common.CHARSET_ASCII
            for char in name:
                if ord(str(char)) == 255:
                    break
                if str(char) not in charset:
                    char = "X"
                fname += str(char)
            if fname == "XXXXXX":
                fname = "ZONE" + zone
            return fname
        
        if self._support_banknames:
            _zone="01"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name1", "Bank name 1",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name1, _zone)))
            other.append(rs)

            _zone="02"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name2", "Bank name 2",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name2, _zone)))
            
            other.append(rs)
            _zone="03"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name3", "Bank name 3",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name3, _zone)))
            other.append(rs)

            _zone="04"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name4", "Bank name 4",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name4, _zone)))            
            other.append(rs)

            _zone="05"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name5", "Bank name 5",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name5, _zone)))
            other.append(rs)

            _zone="06"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name6", "Bank name 6",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name6, _zone)))
            other.append(rs)

            _zone="07"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name7", "Bank name 7",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name7, _zone)))
            other.append(rs)

            _zone="08"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name8", "Bank name 8",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name8, _zone)))
            other.append(rs)

            _zone="09"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name9", "Bank name 9",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name9, _zone)))
            other.append(rs)

            _zone="10"
            _msg = _mem.bank_names
            rs = RadioSetting("bank_names.name10", "Bank name 10",
                            RadioSettingValueString(
                                0, 12, _filterName(_msg.name10, _zone)))
            other.append(rs)

        _codeobj = self._memobj.ani.code
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("ani.code", "ANI Code", val)

        # DTMF settings
        def apply_code(setting, obj, length):
            code = []
            for j in range(0, length):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code

        for i in range(0, 20):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 5, _code, False)
            val.set_charset(DTMF_CHARS)
            pttid = RadioSetting("pttid/%i.code" % i,
                                 "Signal Code %i" % (i + 1), val)
            pttid.set_apply_callback(apply_code, self._memobj.pttid[i], 5)
            dtmfe.append(pttid)

        if _mem.ani.dtmfon > 0xC3:
            val = 0x03
        else:
            val = _mem.ani.dtmfon
        rs = RadioSetting("ani.dtmfon", "DTMF Speed (on)",
                          RadioSettingValueList(LIST_DTMFSPEED,
                                                LIST_DTMFSPEED[val]))
        dtmfe.append(rs)

        if _mem.ani.dtmfoff > 0xC3:
            val = 0x03
        else:
            val = _mem.ani.dtmfoff
        rs = RadioSetting("ani.dtmfoff", "DTMF Speed (off)",
                          RadioSettingValueList(LIST_DTMFSPEED,
                                                LIST_DTMFSPEED[val]))
        dtmfe.append(rs)

        _codeobj = self._memobj.ani.code
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("ani.code", "ANI Code", val)
        rs.set_apply_callback(apply_code, self._memobj.ani, 5)
        dtmfe.append(rs)

        if self._aniid:
            rs = RadioSetting("ani.aniid", "When to send ANI ID",
                            RadioSettingValueList(LIST_PTTID,
                                                    LIST_PTTID[_mem.ani.aniid]))
            dtmfe.append(rs)

        rs = RadioSetting("settings.hangup", "Hang-up time",
                        RadioSettingValueList(LIST_HANGUPTIME,
                                                LIST_HANGUPTIME[_mem.settings.hangup]))
        dtmfe.append(rs)

        def convert_bytes_to_freq(bytes):
            real_freq = 0
            for byte in bytes:
                real_freq = (real_freq * 10) + byte
            return chirp_common.format_freq(real_freq * 10)

        def my_validate(value):
            value = chirp_common.parse_freq(value)
            freqOk = False
            for band in self.VALID_BANDS:
                if value > band[0] and value < band[1]:
                    freqOk = True
            if not freqOk:
                raise InvalidValueError("Invalid frequency!")
            return chirp_common.format_freq(value)

        def apply_freq(setting, obj):
            value = chirp_common.parse_freq(str(setting.value)) / 10
            for i in range(7, -1, -1):
                obj.freq[i] = value % 10
                value /= 10

        val1a = RadioSettingValueString(0, 10,
                                        convert_bytes_to_freq(_mem.vfo.a.freq))
        val1a.set_validate_callback(my_validate)
        rs = RadioSetting("vfo.a.freq", "VFO A Frequency", val1a)
        rs.set_apply_callback(apply_freq, _mem.vfo.a)
        work.append(rs)

        val1b = RadioSettingValueString(0, 10,
                                        convert_bytes_to_freq(_mem.vfo.b.freq))
        val1b.set_validate_callback(my_validate)
        rs = RadioSetting("vfo.b.freq", "VFO B Frequency", val1b)
        rs.set_apply_callback(apply_freq, _mem.vfo.b)
        work.append(rs)

        rs = RadioSetting("vfo.a.sftd", "VFO A Offset dir",
                          RadioSettingValueList(
                              LIST_SHIFTD, LIST_SHIFTD[_mem.vfo.a.sftd]))
        work.append(rs)

        rs = RadioSetting("vfo.b.sftd", "VFO B Offset dir",
                          RadioSettingValueList(
                              LIST_SHIFTD, LIST_SHIFTD[_mem.vfo.b.sftd]))
        work.append(rs)


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

        val1a = RadioSettingValueString(
                    0, 10, convert_bytes_to_offset(_mem.vfo.a.offset))
        rs = RadioSetting("vfo.a.offset",
                          "VFO A Offset", val1a)
        rs.set_apply_callback(apply_offset, _mem.vfo.a)
        work.append(rs)

        val1b = RadioSettingValueString(
                    0, 10, convert_bytes_to_offset(_mem.vfo.b.offset))
        rs = RadioSetting("vfo.b.offset",
                          "VFO B Offset", val1b)
        rs.set_apply_callback(apply_offset, _mem.vfo.b)
        work.append(rs)

        def apply_txpower_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(
                      setting.value) + " from list")
            val = str(setting.value)
            index = TXP_CHOICES.index(val)
            val = TXP_VALUES[index]
            obj.set_value(val)

        rs = RadioSetting("vfo.a.lowpower", "VFO A Power",
                            RadioSettingValueList(
                                LIST_TXPOWER,
                                LIST_TXPOWER[min(_mem.vfo.a.lowpower, 0x02)]
                                            ))
        work.append(rs)

        rs = RadioSetting("vfo.b.lowpower", "VFO B Power",
                            RadioSettingValueList(
                                LIST_TXPOWER,
                                LIST_TXPOWER[min(_mem.vfo.b.lowpower, 0x02)]
                                            ))
        work.append(rs)

        rs = RadioSetting("vfo.a.wide", "VFO A Bandwidth",
                          RadioSettingValueList(
                              LIST_BANDWIDTH,
                              LIST_BANDWIDTH[_mem.vfo.a.wide]))
        work.append(rs)

        rs = RadioSetting("vfo.b.wide", "VFO B Bandwidth",
                          RadioSettingValueList(
                              LIST_BANDWIDTH,
                              LIST_BANDWIDTH[_mem.vfo.b.wide]))
        work.append(rs)

        rs = RadioSetting("vfo.a.scode", "VFO A S-CODE",
                          RadioSettingValueList(
                              LIST_SCODE,
                              LIST_SCODE[_mem.vfo.a.scode]))
        work.append(rs)

        rs = RadioSetting("vfo.b.scode", "VFO B S-CODE",
                          RadioSettingValueList(
                              LIST_SCODE,
                              LIST_SCODE[_mem.vfo.b.scode]))
        work.append(rs)

        rs = RadioSetting("vfo.a.step", "VFO A Tuning Step",
                          RadioSettingValueList(
                              LIST_STEP, LIST_STEP[_mem.vfo.a.step]))
        work.append(rs)
        rs = RadioSetting("vfo.b.step", "VFO B Tuning Step",
                          RadioSettingValueList(
                              LIST_STEP, LIST_STEP[_mem.vfo.b.step]))
        work.append(rs)

        rs = RadioSetting("vfo.a.fhss", "VFO A FHSS",
                          RadioSettingValueBoolean(_mem.vfo.a.fhss))
        work.append(rs)

        rs = RadioSetting("vfo.b.fhss", "VFO B FHSS",
                          RadioSettingValueBoolean(_mem.vfo.b.fhss))
        work.append(rs)

        rs = RadioSetting("settings.bcl", "BCL",
                          RadioSettingValueBoolean(_mem.settings.bcl))
        work.append(rs)

        rs = RadioSetting("settings.pttid", "PTT ID",
                          RadioSettingValueList(self.PTTID_LIST,
                                                self.PTTID_LIST[_mem.settings.pttid]))
        work.append(rs)
        
        def getToneIndex(tone):            
            if tone in [0, 0xFFFF]:
                index = 0
            elif tone >= 0x0258:
                index = self.RXTX_CODES.index(str(tone / 10.0))
            elif tone <= 0x0258:
                index = 50 + tone
                if tone > 0x69:
                    index = tone - 0x6A + 156
            return self.RXTX_CODES[index]
        
        def apply_rxtone(setting, obj):
            index = self.RXTX_CODES.index(str(setting.value))
            if index > 156:
                obj.rxtone = index - 156 + 0x6A
            elif index > 50:
                obj.rxtone = index - 50
            elif index == 0:
                obj.rxtone = 0
            else:
                obj.rxtone = int(float(setting.value)*10) 

        def apply_txtone(setting, obj):
            index = self.RXTX_CODES.index(str(setting.value))
            if index > 156:
                obj.txtone = index - 156 + 0x6A
            elif index > 50:
                obj.txtone = index - 50
            elif index == 0:
                obj.txtone = 0
            else:
                obj.txtone = int(float(setting.value)*10) 
        
        rs = RadioSetting("vfo.a.rxtone", "VFA A RX QT/DQT",
                          RadioSettingValueList(self.RXTX_CODES,
                                                getToneIndex(_mem.vfo.a.rxtone)))
        rs.set_apply_callback(apply_rxtone, _mem.vfo.a)
        work.append(rs)

        rs = RadioSetting("vfo.a.txtone", "VFA A TX QT/DQT",
                          RadioSettingValueList(self.RXTX_CODES,
                                                getToneIndex(_mem.vfo.a.txtone)))
        rs.set_apply_callback(apply_txtone, _mem.vfo.a)
        work.append(rs)

        rs = RadioSetting("vfo.b.rxtone", "VFA B RX QT/DQT",
                          RadioSettingValueList(self.RXTX_CODES,
                                                getToneIndex(_mem.vfo.b.rxtone)))
        rs.set_apply_callback(apply_rxtone, _mem.vfo.b)
        work.append(rs)

        rs = RadioSetting("vfo.b.txtone", "VFA B TX QT/DQT",
                          RadioSettingValueList(self.RXTX_CODES,
                                                getToneIndex(_mem.vfo.b.txtone)))
        rs.set_apply_callback(apply_txtone, _mem.vfo.b)
        work.append(rs)

        if self._vfoscan:
            def scan_validate(value):
                freqOk = False
                for band in self.VALID_BANDS:
                    print(band)
                    if value >= (band[0]/1000000) and value <= (band[1]/1000000):
                        freqOk = True
                if not freqOk:
                    raise InvalidValueError("Invalid frequency!")
                return value

            scanMin = RadioSettingValueInteger(0, 800,
                                            _mem.settings.vfoscanmin)
            scanMin.set_validate_callback(scan_validate)
            rs = RadioSetting("settings.vfoscanmin", "VFO scan range minimum", scanMin)
            work.append(rs)

            scanMax = RadioSettingValueInteger(0, 800,
                                            _mem.settings.vfoscanmax)
            scanMax.set_validate_callback(scan_validate)
            rs = RadioSetting("settings.vfoscanmax", "VFO scan range maximum", scanMax)
            work.append(rs)

        return top
    

    
        # TODO: implement settings 

    
    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = memmap.MemoryMapBytes(data)

        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_features(self):
        """Get the radio's features"""

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
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_name_length = self.LENGTH_NAME
        if self._gmrs:
            rf.valid_duplexes = ["", "+", "off"]
        else:
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
        rf.valid_skips = self.SKIP_VALUES
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (0, 999)
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = STEPS

        return rf

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        #_nam = self._memobj.names[number]
        #print(number)
        #print(_mem)
        #print(_nam)

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if _split(self.get_features(), mem.freq, int(
                          _mem.txfreq) * 10):
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
    
        for char in _mem.name:
            if str(char) == "\xFF":
                char = " "  # The OEM software may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        if not _mem.scan:
            mem.skip = "S"

        levels = self.POWER_LEVELS
        try:
            mem.power = levels[_mem.lowpower]
        except IndexError:
            LOG.error("Radio reported invalid power level %s (in %s)" %
                        (_mem.power, levels))
            mem.power = levels[0]

        mem.mode = _mem.wide and "NFM" or  "FM"

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = self.DTCS_CODES[index]
        else:
            LOG.warn("Bug: txtone is %04x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.rx_dtcs = self.DTCS_CODES[index]
        else:
            LOG.warn("Bug: rxtone is %04x" % _mem.rxtone)

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

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(self.PTTID_LIST,
                                                self.PTTID_LIST[_mem.pttid]))
        mem.extra.append(rs)

        rs = RadioSetting("scode", "S-CODE",
                          RadioSettingValueList(self.SCODE_LIST,
                                                self.SCODE_LIST[_mem.scode]))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]

        _mem.set_raw("\x00"*16 + "\xff" * 16)

        if mem.empty:
            _mem.set_raw("\xff" * 32)
            return

        _mem.rxfreq = mem.freq / 10
        
        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _mem.name[i] = mem.name[i]
            except IndexError:
                _mem.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = self.DTCS_CODES.index(mem.dtcs) + 1
            _mem.rxtone = self.DTCS_CODES.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = self.DTCS_CODES.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = self.DTCS_CODES.index(mem.rx_dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "NFM"

        if mem.power:
            _mem.lowpower = self.POWER_LEVELS.index(mem.power)
        else:
            _mem.lowpower = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                if setting.get_name() == "scode":
                    setattr(_mem, setting.get_name(), str(int(setting.value)))
                else:
                    setattr(_mem, setting.get_name(), setting.value)
        else:
            # there are no extra settings, load defaults
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.scode = 0

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
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
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _set_fm_preset(self, settings):
        for element in settings:
            try:
                val = element.value
                if self._memobj.fm_presets <= 108.0 * 10 - 650:
                    value = int(val.get_value() * 10 - 650)
                else:
                    value = int(val.get_value() * 10)
                LOG.debug("Setting fm_presets = %s" % (value))
                if self._bw_shift:
                    value = ((value & 0x00FF) << 8) | ((value & 0xFF00) >> 8)
                self._memobj.fm_presets = value
            except Exception:
                LOG.debug(element.get_name())
                raise

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) in [cls.MEM_TOTAL + len(cls.MODEL)]:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)
        if match_size and match_model:
            return True
        else:
            return False


@directory.register
class UV17ProGPS(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "UV-17ProGPS"
    _support_banknames = True
    _magic = MSTRING_UV17PROGPS
    _magics = [b"\x46", b"\x4d", b"\x53\x45\x4E\x44\x21\x05\x0D\x01\x01\x01\x04\x11\x08\x05\x0D\x0D\x01\x11\x0F\x09\x12\x09\x10\x04\x00"]
    _magicResponseLengths = [16, 7, 1]
    _aniid = False
    _vfoscan = True
    VALID_BANDS = [UV17Pro._airband, UV17Pro._vhf_range, UV17Pro._vhf2_range,
                   UV17Pro._uhf_range, UV17Pro._uhf2_range]

@directory.register
class UV17L(UV17Pro):
    VENDOR = "Baofeng"
    MODEL = "UV-17L"


