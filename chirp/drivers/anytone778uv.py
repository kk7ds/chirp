# Copyright 2020 Joe Milbourn <joe@milbourn.org.uk>
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
#
# TODO use the band field from ver_response
# TODO handle radio settings
#
# Supported features
# * Read and write memory access for 200 normal memories
# * CTCSS and DTCS for transmit and receive
# * Scan list
# * Tx off
# * Duplex (+ve, -ve, odd, and off splits)
# * Transmit power
# * Channel width (25kHz and 12.5kHz)
# * Retevis RT95, CRT Micron UV, and Midland DBR2500 radios
# * Full range of frequencies for tx and rx, supported band read from radio
#   during download, not verified on upload.  Radio will refuse to TX if out of
#   band.
#
# Unsupported features
# * VFO1, VFO2, and TRF memories
# * custom CTCSS tones
# * Any non-memory radio settings
# * Reverse, talkaround, scramble
# * busy channel lock out
# * probably other things too - like things encoded by the unknown bits in the
#   memory struct

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise

import struct
import time
import logging

LOG = logging.getLogger(__name__)

# Gross hack to handle missing future module on un-updatable
# platforms like MacOS. Just avoid registering these radio
# classes for now.
try:
    from builtins import bytes
    has_future = True
except ImportError:
    has_future = False
    LOG.warning('python-future package is not '
                'available; %s requires it' % __name__)


# Here is where we define the memory map for the radio. Since
# We often just know small bits of it, we can use #seekto to skip
# around as needed.

MEM_FORMAT = '''
#seekto 0x0000;
struct {
  bbcd freq[4];
  bbcd offset[4];
  u8 unknown1;
  u8 talkaround:1,
     scramble:1,
     unknown:2,
     txpower:2,
     duplex:2;
  u8 unknown_bits1:4,
     channel_width:2,
     reverse:1,
     tx_off:1;
  u8 unknown_bits2:4,
     dtcs_decode_en:1,
     ctcss_decode_en:1,
     dtcs_encode_en:1,
     ctcss_encode_en:1;
  u8 ctcss_dec_tone;
  u8 ctcss_enc_tone;
  u8 dtcs_decode_code;
  u8 unknown_bits6:6,
     dtcs_decode_invert:1,
     dtcs_decode_code_highbit:1;
  u8 dtcs_encode_code;
  u8 unknown_bits7:6,
     dtcs_encode_invert:1,
     dtcs_encode_code_highbit:1;
  u8 unknown_bits4:6,
     busy_channel_lockout:2;
  u8 unknown6;
  u8 unknown_bits5:7,
     tone_squelch_en:1;
  u8 unknown7;
  u8 unknown8;
  u8 unknown9;
  u8 unknown10;
  char name[5];
  ul16 customctcss;
} memory[200];
#seekto 0x1940;
struct {
  u8 occupied_bitfield[32];
  u8 scan_enabled_bitfield[32];
} memory_status;
#seekto 0x3260;
struct {
  u8 vfoa_current_channel; // 0
  u8 unknown1;
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5;
  u8 unknown6;
  u8 scan_channel;        // 7
  u8 unknown8_0:4,     // 8
     scan_active:1,
     unknown8_1:3;
  u8 unknown9;
  u8 unknowna;
  u8 unknownb;
  u8 unknownc;
  u8 bandlimit;       // d
  u8 unknownd;
  u8 unknowne;
  u8 unknownf;
} radio_settings;
'''

# Format for the version messages returned by the radio
VER_FORMAT = '''
u8 hdr;
char model[7];
u8 bandlimit;
char version[6];
u8 ack;
'''

TXPOWER_LOW = 0x00
TXPOWER_MED = 0x01
TXPOWER_HIGH = 0x02

DUPLEX_NOSPLIT = 0x00
DUPLEX_POSSPLIT = 0x01
DUPLEX_NEGSPLIT = 0x02
DUPLEX_ODDSPLIT = 0x03

CHANNEL_WIDTH_25kHz = 0x02
CHANNEL_WIDTH_20kHz = 0x01
CHANNEL_WIDTH_12d5kHz = 0x00

BUSY_CHANNEL_LOCKOUT_OFF = 0x00
BUSY_CHANNEL_LOCKOUT_REPEATER = 0x01
BUSY_CHANNEL_LOCKOUT_BUSY = 0x02

MEMORY_ADDRESS_RANGE = (0x0000, 0x3290)
MEMORY_RW_BLOCK_SIZE = 0x10
MEMORY_RW_BLOCK_CMD_SIZE = 0x16

POWER_LEVELS = [chirp_common.PowerLevel('Low', dBm=37),
                chirp_common.PowerLevel('Medium', dBm=40),
                chirp_common.PowerLevel('High', dBm=44)]

# CTCSS Tone definitions
TONE_CUSTOM_CTCSS = 0x33
TONE_MAP_VAL_TO_TONE = {0x00: 62.5, 0x01: 67.0, 0x02: 69.3,
                        0x03: 71.9, 0x04: 74.4, 0x05: 77.0,
                        0x06: 79.7, 0x07: 82.5, 0x08: 85.4,
                        0x09: 88.5, 0x0a: 91.5, 0x0b: 94.8,
                        0x0c: 97.4, 0x0d: 100.0, 0x0e: 103.5,
                        0x0f: 107.2, 0x10: 110.9, 0x11: 114.8,
                        0x12: 118.8, 0x13: 123.0, 0x14: 127.3,
                        0x15: 131.8, 0x16: 136.5, 0x17: 141.3,
                        0x18: 146.2, 0x19: 151.4, 0x1a: 156.7,
                        0x1b: 159.8, 0x1c: 162.2, 0x1d: 165.5,
                        0x1e: 167.9, 0x1f: 171.3, 0x20: 173.8,
                        0x21: 177.3, 0x22: 179.9, 0x23: 183.5,
                        0x24: 186.2, 0x25: 189.9, 0x26: 192.8,
                        0x27: 196.6, 0x28: 199.5, 0x29: 203.5,
                        0x2a: 206.5, 0x2b: 210.7, 0x2c: 218.1,
                        0x2d: 225.7, 0x2e: 229.1, 0x2f: 233.6,
                        0x30: 241.8, 0x31: 250.3, 0x32: 254.1}

TONE_MAP_TONE_TO_VAL = {TONE_MAP_VAL_TO_TONE[val]: val
                        for val in TONE_MAP_VAL_TO_TONE}

TONES_EN_TXTONE = (1 << 3)
TONES_EN_RXTONE = (1 << 2)
TONES_EN_TXCODE = (1 << 1)
TONES_EN_RXCODE = (1 << 0)
TONES_EN_NO_TONE = 0

# Radio supports upper case and symbols
CHARSET_ASCII_PLUS = chirp_common.CHARSET_UPPER_NUMERIC + '- '

# Band limits as defined by the band byte in ver_response, defined in Hz, for
# VHF and UHF, used for RX and TX.
BAND_LIMITS = {0x00: [(144000000, 148000000), (430000000, 440000000)],
               0x01: [(134000000, 174000000), (400000000, 490000000)],
               0x02: [(144000000, 146000000), (430000000, 440000000)]}


# Get band limits from a band limit value
def get_band_limits_Hz(limit_value):
    if limit_value not in BAND_LIMITS:
        limit_value = 0x01
        LOG.warning('Unknown band limit value 0x%02x, default to 0x01')
    bandlimitfrequencies = BAND_LIMITS[limit_value]
    return bandlimitfrequencies


# Calculate the checksum used in serial packets
def checksum(message_bytes):
    mask = 0xFF
    checksum = 0
    for b in message_bytes:
        checksum = (checksum + b) & mask
    return checksum


# Send a command to the radio, return any reply stripping the echo of the
# command (tx and rx share a single pin in this radio)
def send_serial_command(serial, command, expectedlen=None):
    ''' send a command to the radio, and return any response.
    set expectedlen to return as soon as that many bytes are read.
    '''
    serial.write(command)
    serial.flush()

    response = b''
    tout = time.time() + 0.5
    while time.time() < tout:
        if serial.inWaiting():
            response += serial.read()
        # remember everything gets echo'd back
        if len(response) - len(command) == expectedlen:
            break

    # cut off what got echo'd back, we don't need to see it again
    if response.startswith(command):
        response = response[len(command):]

    return response


# strip trailing 0x00 to convert a string returned by bitwise.parse into a
# python string
def cstring_to_py_string(cstring):
    return "".join(c for c in cstring if c != '\x00')


# Check the radio version reported to see if it's one we support,
# returns bool version supported, and the band index
def check_ver(ver_response, allowed_types):
    ''' Check the returned radio version is one we approve of '''

    LOG.debug('ver_response = ')
    LOG.debug(util.hexprint(ver_response))

    resp = bitwise.parse(VER_FORMAT, ver_response)
    verok = False

    if resp.hdr == 0x49 and resp.ack == 0x06:
        model, version = [cstring_to_py_string(bitwise.get_string(s)).strip()
                          for s in (resp.model, resp.version)]
        LOG.debug('radio model: \'%s\' version: \'%s\'' %
                  (model, version))
        LOG.debug('allowed_types = %s' % allowed_types)

        if model in allowed_types:
            LOG.debug('model in allowed_types')

            if version in allowed_types[model]:
                LOG.debug('version in allowed_types[model]')
                verok = True
    else:
        raise errors.RadioError('Failed to parse version response')

    return verok, int(resp.bandlimit)


# Put the radio in programming mode, sending the initial command and checking
# the response.  raise RadioError if there is no response (500ms timeout), and
# if the returned version isn't matched by check_ver
def enter_program_mode(radio):
    serial = radio.pipe
    # place the radio in program mode, and confirm
    program_response = send_serial_command(serial, b'PROGRAM')

    if program_response != b'QX\x06':
        raise errors.RadioError('No initial response from radio.')
    LOG.debug('entered program mode')

    # read the radio ID string, make sure it matches one we know about
    ver_response = send_serial_command(serial, b'\x02')

    verok, bandlimit = check_ver(ver_response, radio.ALLOWED_RADIO_TYPES)
    if not verok:
        exit_program_mode(radio)
        raise errors.RadioError(
            'Radio version not in allowed list for %s-%s: %s' %
            (radio.VENDOR, radio.MODEL, util.hexprint(ver_response)))

    return bandlimit


# Exit programming mode
def exit_program_mode(radio):
    send_serial_command(radio.pipe, b'END')


# Parse a packet from the radio returning the header (R/W, address, data, and
# checksum valid
def parse_read_response(resp):
    addr = resp[:4]
    data = bytes(resp[4:-2])
    cs = checksum(ord(d) for d in resp[1:-2])
    valid = cs == ord(resp[-2])
    if not valid:
        LOG.error('checksumfail: %02x, expected %02x' % (cs, ord(resp[-2])))
        LOG.error('msg data: %s' % util.hexprint(resp))
    return addr, data, valid


# Download data from the radio and populate the memory map
def do_download(radio):
    '''Download memories from the radio'''

    # Get the serial port connection
    serial = radio.pipe

    try:
        enter_program_mode(radio)

        memory_data = bytes()

        # status info for the UI
        status = chirp_common.Status()
        status.cur = 0
        status.max = (MEMORY_ADDRESS_RANGE[1] -
                      MEMORY_ADDRESS_RANGE[0])/MEMORY_RW_BLOCK_SIZE
        status.msg = 'Cloning from radio...'
        radio.status_fn(status)

        for addr in range(MEMORY_ADDRESS_RANGE[0],
                          MEMORY_ADDRESS_RANGE[1] + MEMORY_RW_BLOCK_SIZE,
                          MEMORY_RW_BLOCK_SIZE):
            read_command = struct.pack('>BHB', 0x52, addr,
                                       MEMORY_RW_BLOCK_SIZE)
            read_response = send_serial_command(serial, read_command,
                                                MEMORY_RW_BLOCK_CMD_SIZE)
            # LOG.debug('read response:\n%s' % util.hexprint(read_response))

            address, data, valid = parse_read_response(read_response)
            memory_data += data

            # update UI
            status.cur = (addr - MEMORY_ADDRESS_RANGE[0])\
                / MEMORY_RW_BLOCK_SIZE
            radio.status_fn(status)

        exit_program_mode(radio)
    except errors.RadioError as e:
        raise e
    except Exception as e:
        raise errors.RadioError('Failed to download from radio: %s' % e)

    return memmap.MemoryMapBytes(memory_data)


# Build a write data command to send to the radio
def make_write_data_cmd(addr, data, datalen):
    cmd = struct.pack('>BHB', 0x57, addr, datalen)
    cmd += data
    cs = checksum(ord(c) for c in cmd[1:])
    cmd += struct.pack('>BB', cs, 0x06)
    return cmd


# Upload a memory map to the radio
def do_upload(radio):
    try:
        bandlimit = enter_program_mode(radio)

        if bandlimit != radio._memobj.radio_settings.bandlimit:
            LOG.warning('radio and image bandlimits differ'
                        ' some channels many not work'
                        ' (img:0x%02x radio:0x%02x)' %
                        (int(bandlimit),
                         int(radio._memobj.radio_settings.bandlimit)))
            LOG.warning('radio bands: %s' % get_band_limits_Hz(
                         int(radio._memobj.radio_settings.bandlimit)))
            LOG.warning('img bands: %s' % get_band_limits_Hz(bandlimit))

        serial = radio.pipe

        # send the initial message, radio responds with something that looks a
        # bit like a bitfield, but I don't know what it is yet.
        read_command = struct.pack('>BHB', 0x52, 0x3b10, MEMORY_RW_BLOCK_SIZE)
        read_response = send_serial_command(serial, read_command,
                                            MEMORY_RW_BLOCK_CMD_SIZE)
        address, data, valid = parse_read_response(read_response)
        LOG.debug('Got initial response from radio: %s' %
                  util.hexprint(read_response))

        bptr = 0

        memory_addrs = range(MEMORY_ADDRESS_RANGE[0],
                             MEMORY_ADDRESS_RANGE[1] + MEMORY_RW_BLOCK_SIZE,
                             MEMORY_RW_BLOCK_SIZE)

        # status info for the UI
        status = chirp_common.Status()
        status.cur = 0
        status.max = len(memory_addrs)
        status.msg = 'Cloning to radio...'
        radio.status_fn(status)

        for idx, addr in enumerate(memory_addrs):
            write_command = make_write_data_cmd(
                addr, radio._mmap[bptr:bptr+MEMORY_RW_BLOCK_SIZE],
                MEMORY_RW_BLOCK_SIZE)
            # LOG.debug('write data:\n%s' % util.hexprint(write_command))
            write_response = send_serial_command(serial, write_command, 0x01)
            bptr += MEMORY_RW_BLOCK_SIZE

            if write_response == '\x0a':
                # NACK from radio, e.g. checksum wrongn
                LOG.debug('Radio returned 0x0a - NACK:')
                LOG.debug(' * write cmd:\n%s' % util.hexprint(write_command))
                LOG.debug(' * write response:\n%s' %
                          util.hexprint(write_response))
                exit_program_mode(radio)
                raise errors.RadioError('Radio NACK\'d write command')

            # update UI
            status.cur = idx
            radio.status_fn(status)
        exit_program_mode(radio)
    except errors.RadioError:
        raise
    except Exception as e:
        raise errors.RadioError('Failed to download from radio: %s' % e)


# Get the value of @bitfield @number of bits in from 0
def get_bitfield(bitfield, number):
    ''' Get the value of @bitfield @number of bits in '''
    byteidx = number//8
    bitidx = number - (byteidx * 8)
    return bitfield[byteidx] & (1 << bitidx)


# Set the @value of @bitfield @number of bits in from 0
def set_bitfield(bitfield, number, value):
    ''' Set the @value of @bitfield @number of bits in '''
    byteidx = number//8
    bitidx = number - (byteidx * 8)
    if value is True:
        bitfield[byteidx] |= (1 << bitidx)
    else:
        bitfield[byteidx] &= ~(1 << bitidx)
    return bitfield


# Translate the radio's version of a code as stored to a real code
def dtcs_code_bits_to_val(highbit, lowbyte):
    return chirp_common.ALL_DTCS_CODES[highbit*256 + lowbyte]


# Translate the radio's version of a tone as stored to a real tone
def ctcss_tone_bits_to_val(tone_byte):
    # TODO use the custom setting 0x33 and ref the custom ctcss
    # field
    tone_byte = int(tone_byte)
    if tone_byte in TONE_MAP_VAL_TO_TONE:
        return TONE_MAP_VAL_TO_TONE[tone_byte]
    elif tone_byte == TONE_CUSTOM_CTCSS:
        LOG.info('custom ctcss not implemented (yet?).')
    else:
        raise errors.UnsupportedToneError('unknown ctcss tone value: %02x' %
                                          tone_byte)


# Translate a real tone to the radio's version as stored
def ctcss_code_val_to_bits(tone_value):
    if tone_value in TONE_MAP_TONE_TO_VAL:
        return TONE_MAP_TONE_TO_VAL[tone_value]
    else:
        raise errors.UnsupportedToneError('Tone %f not supported' % tone_value)


# Translate a real code to the radio's version as stored
def dtcs_code_val_to_bits(code):
    val = chirp_common.ALL_DTCS_CODES.index(code)
    return (val & 0xFF), ((val >> 8) & 0x01)


class AnyTone778UVBase(chirp_common.CloneModeRadio,
                       chirp_common.ExperimentalRadio):
    '''AnyTone 778UV and probably Retivis RT95 and others'''
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = False

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()

        rp.experimental = \
            ('This is experimental support for the %s %s.  '
             'Please send in bug and enhancement requests!' %
             (cls.VENDOR, cls.MODEL))

        return rp

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_settings = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.valid_name_length = 5
        rf.valid_duplexes = ['', '+', '-', 'split', 'off']
        rf.valid_characters = CHARSET_ASCII_PLUS

        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone',
                                'Tone->DTCS',
                                'DTCS->Tone',
                                'DTCS->DTCS',
                                'DTCS->',
                                '->DTCS',
                                '->Tone']

        rf.memory_bounds = (1, 200)  # This radio supports memories 1-200
        try:
            rf.valid_bands = get_band_limits_Hz(
                int(self._memobj.radio_settings.bandlimit))
        except TypeError as e:
            # If we're asked without memory loaded, assume the most permissive
            rf.valid_bands = get_band_limits_Hz(1)
        except Exception as e:
            LOG.error('Failed to get band limits for anytone778uv: %s' % e)
            rf.valid_bands = get_band_limits_Hz(1)
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tuning_steps = [2.5, 5, 6.25, 10, 12.5, 20, 25, 30, 50]
        rf.has_tuning_step = False
        return rf

    # Do a download of the radio from the serial port
    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    # Do an upload of the radio to the serial port
    def sync_out(self):
        do_upload(self)

    # Convert the raw byte array into a memory object structure
    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # Return a raw representation of the memory object, which
    # is very helpful for development
    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number):
        number -= 1
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[number]
        _mem_status = self._memobj.memory_status

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()
        mem.number = number + 1           # Set the memory number

        # Check if this memory is present in the occupied list
        mem.empty = get_bitfield(_mem_status.occupied_bitfield, number) == 0

        if not mem.empty:
            # Check if this memory is in the scan enabled list
            mem.skip = ''
            if get_bitfield(_mem_status.scan_enabled_bitfield, number) == 0:
                mem.skip = 'S'

            # set the name
            mem.name = str(_mem.name).rstrip()  # Set the alpha tag

            # Convert your low-level frequency and offset to Hertz
            mem.freq = int(_mem.freq) * 10
            mem.offset = int(_mem.offset) * 10

            # Set the duplex flags
            if _mem.duplex == DUPLEX_POSSPLIT:
                mem.duplex = '+'
            elif _mem.duplex == DUPLEX_NEGSPLIT:
                mem.duplex = '-'
            elif _mem.duplex == DUPLEX_NOSPLIT:
                mem.duplex = ''
            elif _mem.duplex == DUPLEX_ODDSPLIT:
                mem.duplex = 'split'
            else:
                LOG.error('%s: get_mem: unhandled duplex: %02x' %
                          (mem.name, _mem.duplex))

            # handle tx off
            if _mem.tx_off:
                mem.duplex = 'off'

            # Set the channel width
            if _mem.channel_width == CHANNEL_WIDTH_25kHz:
                mem.mode = 'FM'
            elif _mem.channel_width == CHANNEL_WIDTH_20kHz:
                LOG.info(
                    '%s: get_mem: promoting 20kHz channel width to 25kHz' %
                    mem.name)
                mem.mode = 'FM'
            elif _mem.channel_width == CHANNEL_WIDTH_12d5kHz:
                mem.mode = 'NFM'
            else:
                LOG.error('%s: get_mem: unhandled channel width: 0x%02x' %
                          (mem.name, _mem.channel_width))

            # set the power level
            if _mem.txpower == TXPOWER_LOW:
                mem.power = POWER_LEVELS[0]
            elif _mem.txpower == TXPOWER_MED:
                mem.power = POWER_LEVELS[1]
            elif _mem.txpower == TXPOWER_HIGH:
                mem.power = POWER_LEVELS[2]
            else:
                LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                          (mem.name, _mem.txpower))

            # CTCSS Tones
            # TODO support custom ctcss tones here
            txtone = None
            rxtone = None
            rxcode = None
            txcode = None

            # check if dtcs tx is enabled
            if _mem.dtcs_encode_en:
                txcode = dtcs_code_bits_to_val(_mem.dtcs_encode_code_highbit,
                                               _mem.dtcs_encode_code)

            # check if dtcs rx is enabled
            if _mem.dtcs_decode_en:
                rxcode = dtcs_code_bits_to_val(_mem.dtcs_decode_code_highbit,
                                               _mem.dtcs_decode_code)

            if txcode is not None:
                LOG.debug('%s: get_mem dtcs_enc: %d' % (mem.name, txcode))
            if rxcode is not None:
                LOG.debug('%s: get_mem dtcs_dec: %d' % (mem.name, rxcode))

            # tsql set if radio squelches on tone
            tsql = _mem.tone_squelch_en

            # check if ctcss tx is enabled
            if _mem.ctcss_encode_en:
                txtone = ctcss_tone_bits_to_val(_mem.ctcss_enc_tone)

            # check if ctcss rx is enabled
            if _mem.ctcss_decode_en:
                rxtone = ctcss_tone_bits_to_val(_mem.ctcss_dec_tone)

            # Define this here to allow a readable if-else tree enabling tone
            # options
            enabled = 0
            enabled |= (txtone is not None) * TONES_EN_TXTONE
            enabled |= (rxtone is not None) * TONES_EN_RXTONE
            enabled |= (txcode is not None) * TONES_EN_TXCODE
            enabled |= (rxcode is not None) * TONES_EN_RXCODE

            # Add some debugging output for the tone bitmap
            enstr = []
            if enabled & TONES_EN_TXTONE:
                enstr += ['TONES_EN_TXTONE']
            if enabled & TONES_EN_RXTONE:
                enstr += ['TONES_EN_RXTONE']
            if enabled & TONES_EN_TXCODE:
                enstr += ['TONES_EN_TXCODE']
            if enabled & TONES_EN_RXCODE:
                enstr += ['TONES_EN_RXCODE']
            if enabled == 0:
                enstr = ['TONES_EN_NOTONE']
            LOG.debug('%s: enabled = %s' % (
                mem.name, '|'.join(enstr)))

            mem.tmode = ''
            if enabled == TONES_EN_NO_TONE:
                mem.tmode = ''
            elif enabled == TONES_EN_TXTONE:
                mem.tmode = 'Tone'
                mem.rtone = txtone
            elif enabled == TONES_EN_RXTONE and tsql:
                mem.tmode = 'Cross'
                mem.cross_mode = '->Tone'
                mem.ctone = rxtone
            elif enabled == (TONES_EN_TXTONE | TONES_EN_RXTONE) and tsql:
                if txtone == rxtone:  # TSQL
                    mem.tmode = 'TSQL'
                    mem.ctone = txtone
                else:  # Tone->Tone
                    mem.tmode = 'Cross'
                    mem.cross_mode = 'Tone->Tone'
                    mem.ctone = rxtone
                    mem.rtone = txtone
            elif enabled == TONES_EN_TXCODE:
                mem.tmode = 'Cross'
                mem.cross_mode = 'DTCS->'
                mem.dtcs = txcode
            elif enabled == TONES_EN_RXCODE and tsql:
                mem.tmode = 'Cross'
                mem.cross_mode = '->DTCS'
                mem.rx_dtcs = rxcode
            elif enabled == (TONES_EN_TXCODE | TONES_EN_RXCODE) and tsql:
                if rxcode == txcode:
                    mem.tmode = 'DTCS'
                    mem.rx_dtcs = rxcode
                else:
                    mem.tmode = 'Cross'
                    mem.cross_mode = 'DTCS->DTCS'
                    mem.rx_dtcs = rxcode
                    mem.dtcs = txcode
            elif enabled == (TONES_EN_TXCODE | TONES_EN_RXTONE) and tsql:
                mem.tmode = 'Cross'
                mem.cross_mode = 'DTCS->Tone'
                mem.dtcs = txcode
                mem.ctone = rxtone
            elif enabled == (TONES_EN_TXTONE | TONES_EN_RXCODE) and tsql:
                mem.tmode = 'Cross'
                mem.cross_mode = 'Tone->DTCS'
                mem.rx_dtcs = rxcode
                mem.rtone = txtone
            else:
                LOG.error('%s: Unhandled tmode enabled = %d.' % (
                    mem.name, enabled))

            # set the dtcs polarity
            dtcs_pol_bit_to_str = {0: 'N', 1: 'R'}
            mem.dtcs_polarity = '%s%s' %\
                (dtcs_pol_bit_to_str[_mem.dtcs_encode_invert == 1],
                 dtcs_pol_bit_to_str[_mem.dtcs_decode_invert == 1])

        return mem

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]
        _mem_status = self._memobj.memory_status

        # set the occupied bitfield
        _mem_status.occupied_bitfield = \
            set_bitfield(_mem_status.occupied_bitfield, mem.number - 1,
                         not mem.empty)

        # set the scan add bitfield
        _mem_status.scan_enabled_bitfield = \
            set_bitfield(_mem_status.scan_enabled_bitfield, mem.number - 1,
                         (not mem.empty) and (mem.skip != 'S'))

        if mem.empty:
            # Set the whole memory to 0xff
            _mem.set_raw('\xff' * (_mem.size() / 8))
        else:
            _mem.set_raw('\x00' * (_mem.size() / 8))

            _mem.freq = int(mem.freq / 10)
            _mem.offset = int(mem.offset / 10)

            _mem.name = mem.name.ljust(5)[:5]  # Store the alpha tag

            # TODO support busy channel lockout - disabled for now
            _mem.busy_channel_lockout = BUSY_CHANNEL_LOCKOUT_OFF

            # Set duplex bitfields
            if mem.duplex == '+':
                _mem.duplex = DUPLEX_POSSPLIT
            elif mem.duplex == '-':
                _mem.duplex = DUPLEX_NEGSPLIT
            elif mem.duplex == '':
                _mem.duplex = DUPLEX_NOSPLIT
            elif mem.duplex == 'split':
                # TODO: this is an unverified punt!
                _mem.duplex = DUPLEX_ODDSPLIT
            else:
                LOG.error('%s: set_mem: unhandled duplex: %s' %
                          (mem.name, mem.duplex))

            # handle tx off
            _mem.tx_off = 0
            if mem.duplex == 'off':
                _mem.tx_off = 1

            # Set the channel width - remember we promote 20kHz channels to FM
            # on import
            # , so don't handle them here
            if mem.mode == 'FM':
                _mem.channel_width = CHANNEL_WIDTH_25kHz
            elif mem.mode == 'NFM':
                _mem.channel_width = CHANNEL_WIDTH_12d5kHz
            else:
                LOG.error('%s: set_mem: unhandled mode: %s' % (
                    mem.name, mem.mode))

            # set the power level
            if mem.power == POWER_LEVELS[0]:
                _mem.txpower = TXPOWER_LOW
            elif mem.power == POWER_LEVELS[1]:
                _mem.txpower = TXPOWER_MED
            elif mem.power == POWER_LEVELS[2]:
                _mem.txpower = TXPOWER_HIGH
            else:
                LOG.error('%s: set_mem: unhandled power level: %s' %
                          (mem.name, mem.power))

            # TODO set the CTCSS values
            # TODO support custom ctcss tones here
            # Default - tones off, carrier sql
            _mem.ctcss_encode_en = 0
            _mem.ctcss_decode_en = 0
            _mem.tone_squelch_en = 0
            _mem.ctcss_enc_tone = 0x00
            _mem.ctcss_dec_tone = 0x00
            _mem.customctcss = 0x00
            _mem.dtcs_encode_en = 0
            _mem.dtcs_encode_code_highbit = 0
            _mem.dtcs_encode_code = 0
            _mem.dtcs_encode_invert = 0
            _mem.dtcs_decode_en = 0
            _mem.dtcs_decode_code_highbit = 0
            _mem.dtcs_decode_code = 0
            _mem.dtcs_decode_invert = 0

            dtcs_pol_str_to_bit = {'N': 0, 'R': 1}
            _mem.dtcs_encode_invert = dtcs_pol_str_to_bit[mem.dtcs_polarity[0]]
            _mem.dtcs_decode_invert = dtcs_pol_str_to_bit[mem.dtcs_polarity[1]]

            if mem.tmode == 'Tone':
                _mem.ctcss_encode_en = 1
                _mem.ctcss_enc_tone = ctcss_code_val_to_bits(mem.rtone)
            elif mem.tmode == 'TSQL':
                _mem.ctcss_encode_en = 1
                _mem.ctcss_enc_tone = ctcss_code_val_to_bits(mem.ctone)
                _mem.ctcss_decode_en = 1
                _mem.tone_squelch_en = 1
                _mem.ctcss_dec_tone = ctcss_code_val_to_bits(mem.ctone)
            elif mem.tmode == 'DTCS':
                _mem.dtcs_encode_en = 1
                _mem.dtcs_encode_code, _mem.dtcs_encode_code_highbit = \
                    dtcs_code_val_to_bits(mem.rx_dtcs)
                _mem.dtcs_decode_en = 1
                _mem.dtcs_decode_code, _mem.dtcs_decode_code_highbit = \
                    dtcs_code_val_to_bits(mem.rx_dtcs)
                _mem.tone_squelch_en = 1
            elif mem.tmode == 'Cross':
                txmode, rxmode = mem.cross_mode.split('->')

                if txmode == 'Tone':
                    _mem.ctcss_encode_en = 1
                    _mem.ctcss_enc_tone = ctcss_code_val_to_bits(mem.rtone)
                elif txmode == '':
                    pass
                elif txmode == 'DTCS':
                    _mem.dtcs_encode_en = 1
                    _mem.dtcs_encode_code, _mem.dtcs_encode_code_highbit = \
                        dtcs_code_val_to_bits(mem.dtcs)
                else:
                    LOG.error('%s: unhandled cross TX mode: %s' % (
                        mem.name, mem.cross_mode))

                if rxmode == 'Tone':
                    _mem.ctcss_decode_en = 1
                    _mem.tone_squelch_en = 1
                    _mem.ctcss_dec_tone = ctcss_code_val_to_bits(mem.ctone)
                elif rxmode == '':
                    pass
                elif rxmode == 'DTCS':
                    _mem.dtcs_decode_en = 1
                    _mem.dtcs_decode_code, _mem.dtcs_decode_code_highbit = \
                        dtcs_code_val_to_bits(mem.rx_dtcs)
                    _mem.tone_squelch_en = 1
                else:
                    LOG.error('%s: unhandled cross RX mode: %s' % (
                        mem.name, mem.cross_mode))
            else:
                LOG.error('%s: Unhandled tmode/cross %s/%s.' %
                          (mem.name, mem.tmode, mem.cross_mode))
            LOG.debug('%s: tmode=%s, cross=%s, rtone=%f, ctone=%f' % (
                mem.name, mem.tmode, mem.cross_mode, mem.rtone, mem.ctone))
            LOG.debug('%s: CENC=%d, CDEC=%d, t(enc)=%02x, t(dec)=%02x' % (
                mem.name,
                _mem.ctcss_encode_en,
                _mem.ctcss_decode_en,
                ctcss_code_val_to_bits(mem.rtone),
                ctcss_code_val_to_bits(mem.ctone)))

            # set unknown defaults, based on reading memory set by vendor tool
            _mem.unknown1 = 0x00
            _mem.unknown6 = 0x00
            _mem.unknown7 = 0x00
            _mem.unknown8 = 0x00
            _mem.unknown9 = 0x00
            _mem.unknown10 = 0x00


if has_future:
    @directory.register
    class AnyTone778UV(AnyTone778UVBase):
        VENDOR = "AnyTone"
        MODEL = "778UV"
        # Allowed radio types is a dict keyed by model of a list of version
        # strings
        ALLOWED_RADIO_TYPES = {'AT778UV': ['V100', 'V200']}

    @directory.register
    class RetevisRT95(AnyTone778UVBase):
        VENDOR = "Retevis"
        MODEL = "RT95"
        # Allowed radio types is a dict keyed by model of a list of version
        # strings
        ALLOWED_RADIO_TYPES = {'RT95': ['V100']}

    @directory.register
    class CRTMicronUV(AnyTone778UVBase):
        VENDOR = "CRT"
        MODEL = "Micron UV"
        # Allowed radio types is a dict keyed by model of a list of version
        # strings
        ALLOWED_RADIO_TYPES = {'MICRON': ['V100']}

    @directory.register
    class MidlandDBR2500(AnyTone778UVBase):
        VENDOR = "Midland"
        MODEL = "DBR2500"
        # Allowed radio types is a dict keyed by model of a list of version
        # strings
        ALLOWED_RADIO_TYPES = {'DBR2500': ['V100']}
