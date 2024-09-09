# Copyright 2020 Joe Milbourn <joe@milbourn.org.uk>
# Copyright 2021 Jim Unroe <rock.unroe@gmail.com>
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
# * Channel width (25 kHz and 12.5 kHz)
# * Retevis RT95, CRT Micron UV, and Midland DBR2500 radios
# * Full range of frequencies for tx and rx, supported band read from radio
#   during download, not verified on upload.  Radio will refuse to TX if out of
#   band.
# * Busy channel lock out (for each memory)
#
# Unsupported features
# * VFO1, VFO2, and TRF memories
# * custom CTCSS tones
# * Any non-memory radio settings
# * Reverse, talkaround, scramble
# * probably other things too - like things encoded by the unknown bits in the
#   memory struct

from chirp import chirp_common, directory, memmap, errors, util
from chirp import bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettings

import struct
import time
import logging

LOG = logging.getLogger(__name__)

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
  char name[6];           // the VOX models have 6-character names
                          // the original models only have 5-character names
                          // the 1st byte is not used and will always be 0x00
  ul16 customctcss;
} memory[200];
#seekto 0x1940;
struct {
  u8 occupied_bitfield[32];
  u8 scan_enabled_bitfield[32];
} memory_status;

#seekto 0x1980;
struct {
  char line[7];           // starting display
} starting_display;

#seekto 0x1990;
struct {
  u8 code[16];            // DTMF Encode M1-M16
} pttid[16];

#seekto 0x1A90;
struct {
  u8 pttIdStart[16];      // 0x1A90 ptt id starting
  u8 pttIdEnd[16];        // 0x1AA0 ptt id ending
  u8 remoteStun[16];      // 0x1AB0 remotely stun
  u8 remoteKill[16];      // 0x1AC0 remotely kill
  u8 intervalChar;        // 0x1AD0 dtmf interval character
  u8 groupCode;           // 0x1AD1 group code
  u8 unk1ad2:6,           // 0x1AD2
     decodingResponse:2;  //        decoding response
  u8 pretime;             // 0x1AD3 pretime
  u8 firstDigitTime;      // 0x1AD4 first digit time
  u8 autoResetTime;       // 0x1AD5 auto reset time
  u8 selfID[3];           // 0x1AD6 dtmf self id
  u8 unk1ad9:7,           // 0x1AD9
     sideTone:1;          //        side tone
  u8 timeLapse;           // 0x1ADA time-lapse after encode
  u8 pauseTime;           // 0x1ADB ptt id pause time
} dtmf;

#seekto 0x3200;
struct {
  u8 unk3200:5,           // 0x3200
     beepVolume:3;        //        beep volume
  u8 unk3201:4,           // 0x3201
     frequencyStep:4;     //        frequency step
  u8 unk3202:6,           // 0x3202
     displayMode:2;       // display mode
  u8 unk0x3203;
  u8 unk3204:4,           // 0x3204
     squelchLevelA:4;     //        squelch level a
  u8 unk3205:4,           // 0x3205
     squelchLevelB:4;     //        squelch level b
  u8 unk3206:2,           // 0x3206
     speakerVol:6;        //        speaker volume
  u8 unk3207:7,           // 0x3207
     powerOnPasswd:1;     //        power-on password
  u8 unk3208:6,           // 0x3208
     scanType:2;          //        scan type
  u8 unk3209:6,           // 0x3209
     scanRecoveryT:2;     //        scan recovery time
  u8 unk320a:7,           // 0x320A
     autoPowerOn:1;       //        auto power on
  u8 unk320b:7,           // 0x320B
     main:1;              //        main
  u8 unk320c:7,           // 0x320C
     dualWatch:1;         //        dual watch (rx way select)
  u8 unk320d:5,           // 0x320D
     backlightBr:3;       //        backlight brightness
  u8 unk320e:3,           // 0x320E
     timeOutTimer:5;      //        time out timer
  u8 unk320f:6,           // 0x320F
     autoPowerOff:2;      //        auto power off
  u8 unk3210:6,           // 0x3210
     tbstFrequency:2;     //        tbst frequency
  u8 unk3211:7,           // 0x3211
     screenDir:1;         //        screen direction
  u8 unk3212:2,           // 0x3212
     micKeyBrite:6;       //        hand mic key brightness
  u8 unk3213:6,           // 0x3213
     speakerSwitch:2;     //        speaker switch
  u8 keyPA;               // 0x3214 key pa
  u8 keyPB;               // 0x3215 key pb
  u8 keyPC;               // 0x3216 key pc
  u8 keyPD;               // 0x3217 key pd
  u8 unk3218:5,           // 0x3218
     steType:3;           //        ste type
  u8 unk3219:6,           // 0x3219
     steFrequency:2;      //        ste frequency
  u8 unk321a:5,           // 0x321A
     dtmfTxTime:3;        //        dtmf transmitting time
  u8 unk_bit7_6:2,        // 0x321B
     monKeyFunction:1,    //        mon key function
     channelLocked:1,     //        channel locked
     saveChParameter:1,   //        save channel parameter
     powerOnReset:1,      //        power on reset
     trfEnable:1,         //        trf enable
     knobMode:1;          //        knob mode
  u8 unk321c:7,           // 0x321C
     voxOnOff:1;          //        vox on/off
  u8 voxLevel;            // 0x321D vox level
  u8 voxDelay;            // 0x321E vox delay
} settings;

#seekto 0x3240;
struct {
  char digits[6];         // password
} password;

#seekto 0x3250;
struct {
  u8 keyMode1P1;          // 0x3250 key mode 1 p1
  u8 keyMode1P2;          // 0x3251 key mode 1 p2
  u8 keyMode1P3;          // 0x3252 key mode 1 p3
  u8 keyMode1P4;          // 0x3253 key mode 1 p4
  u8 keyMode1P5;          // 0x3254 key mode 1 p5
  u8 keyMode1P6;          // 0x3255 key mode 1 p6
  u8 keyMode2P1;          // 0x3256 key mode 2 p1
  u8 keyMode2P2;          // 0x3257 key mode 2 p2
  u8 keyMode2P3;          // 0x3258 key mode 2 p3
  u8 keyMode2P4;          // 0x3259 key mode 2 p4
  u8 keyMode2P5;          // 0x325A key mode 2 p5
  u8 keyMode2P6;          // 0x325B key mode 2 p6
} pfkeys;

#seekto 0x3260;
struct {
  u8 mrChanA;             // 0x3260 mr channel a
  u8 unknown1_0:7,        // 0x3261
     vfomrA:1;            //        vfo/mr mode a
  u8 unknown2;
  u8 unknown3;
  u8 unknown4;
  u8 unknown5;
  u8 unknown6;
  u8 mrChanB;             // 0x3267 mr channel b
  u8 unknown8_0:4,        // 0x3268
     scan_active:1,
     unknown8_1:2,
     vfomrB:1;            //        vfo/mr mode b
  u8 unknown9;
  u8 unknowna;
  u8 unknownb;
  u8 unknownc;
  u8 bandlimit;           // 0x326D mode
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
               0x01: [(136000000, 174000000), (400000000, 490000000)],
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
# returns bool version supported, the band index, and has_vox
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
def enter_program_mode(serial):
    # place the radio in program mode, and confirm
    program_response = send_serial_command(serial, b'PROGRAM')

    if program_response != b'QX\x06':
        raise errors.RadioError('No initial response from radio.')
    LOG.debug('entered program mode')

    # read the radio ID string, make sure it matches one we know about
    return send_serial_command(serial, b'\x02')


def get_bandlimit_from_ver(radio, ver_response):
    verok, bandlimit, = check_ver(ver_response,
                                  radio.ALLOWED_RADIO_TYPES)
    if not verok:
        LOG.debug('Radio version response not allowed for %s-%s: %s',
                  radio.VENDOR, radio.MODEL, ver_response)
        raise errors.RadioError('Radio model/version mismatch')

    return bandlimit


# Exit programming mode
def exit_program_mode(serial):
    try:
        send_serial_command(serial, b'END')
    except Exception as e:
        LOG.error('Failed to exit programming mode: %s', e)


# Parse a packet from the radio returning the header (R/W, address, data, and
# checksum valid
def parse_read_response(resp):
    addr = resp[:4]
    data = bytes(resp[4:-2])
    cs = checksum(d for d in resp[1:-2])
    valid = cs == resp[-2]
    if not valid:
        LOG.error('checksumfail: %02x, expected %02x' % (cs, resp[-2]))
        LOG.error('msg data: %s' % util.hexprint(resp))
    return addr, data, valid


# Download data from the radio and populate the memory map
def do_download(radio):
    '''Download memories from the radio'''

    # NOTE: The radio is already in programming mode because of
    # detect_from_serial()

    # Get the serial port connection
    serial = radio.pipe

    try:
        memory_data = bytes()

        # status info for the UI
        status = chirp_common.Status()
        status.cur = 0
        status.max = (MEMORY_ADDRESS_RANGE[1] -
                      MEMORY_ADDRESS_RANGE[0]) // MEMORY_RW_BLOCK_SIZE
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
            if not valid:
                raise errors.RadioError('Invalid response received from radio')
            memory_data += data

            # update UI
            status.cur = (addr - MEMORY_ADDRESS_RANGE[0])\
                // MEMORY_RW_BLOCK_SIZE
            radio.status_fn(status)

    except errors.RadioError as e:
        raise e
    except Exception as e:
        raise errors.RadioError('Failed to download from radio: %s' % e)
    finally:
        exit_program_mode(radio.pipe)

    return memmap.MemoryMapBytes(memory_data)


# Build a write data command to send to the radio
def make_write_data_cmd(addr, data, datalen):
    cmd = struct.pack('>BHB', 0x57, addr, datalen)
    cmd += data
    cs = checksum(c for c in cmd[1:])
    cmd += struct.pack('>BB', cs, 0x06)
    return cmd


# Upload a memory map to the radio
def do_upload(radio):
    try:
        ver_response = enter_program_mode(radio.pipe)
        bandlimit = get_bandlimit_from_ver(radio, ver_response)

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

        memory_addrs = list(range(MEMORY_ADDRESS_RANGE[0],
                                  MEMORY_ADDRESS_RANGE[1] +
                                  MEMORY_RW_BLOCK_SIZE,
                                  MEMORY_RW_BLOCK_SIZE))

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
                # NACK from radio, e.g. checksum wrong
                LOG.debug('Radio returned 0x0a - NACK:')
                LOG.debug(' * write cmd:\n%s' % util.hexprint(write_command))
                LOG.debug(' * write response:\n%s' %
                          util.hexprint(write_response))
                exit_program_mode(radio.pipe)
                raise errors.RadioError('Radio NACK\'d write command')

            # update UI
            status.cur = idx
            radio.status_fn(status)
    except errors.RadioError:
        raise
    except Exception as e:
        raise errors.RadioError('Failed to download from radio: %s' % e)
    finally:
        exit_program_mode(radio.pipe)


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
    '''AnyTone 778UV and probably Retevis RT95 and others'''
    BAUD_RATE = 9600
    NAME_LENGTH = 5
    HAS_VOX = False

    @classmethod
    def detect_from_serial(cls, pipe):
        ver_response = enter_program_mode(pipe)
        for radio_cls in cls.detected_models():
            ver_ok, _ = check_ver(ver_response, radio_cls.ALLOWED_RADIO_TYPES)
            if ver_ok:
                return radio_cls
        LOG.warning('No match for ver_response: %s',
                    util.hexprint(ver_response))
        raise errors.RadioError('Incorrect radio model')

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
        rf.has_settings = True
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.valid_name_length = self.NAME_LENGTH
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
        except AttributeError:
            # If we're asked without memory loaded, assume the most permissive
            rf.valid_bands = get_band_limits_Hz(1)
        except Exception as e:
            LOG.exception(
                'Failed to get band limits for anytone778uv: %s' % e)
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
            if self.NAME_LENGTH == 5:
                # original models with 5-character name length
                temp_name = str(_mem.name)
                # Strip the first character and set the alpha tag
                mem.name = str(temp_name[1:6]).rstrip()
            else:
                # new VOX models with 6-character name length
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
                    '%s: get_mem: promoting 20 kHz channel width to 25 kHz' %
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
                    # #8327 Not sure this is the correct interpretation of
                    # DevelopersToneModes, but it seems to make it work round
                    # tripping with the Anytone software.  DTM implies that we
                    # might not need to set mem.dtcs, but if we do it only DTCS
                    # rx works (as if we were Cross:None->DTCS).
                    mem.dtcs = rxcode
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

                # Can get here if e.g. TONE_EN_RXCODE is set and tsql isn't
                # In that case should we perhaps store the tone and code values
                # if they're present and then setup tmode and cross_mode as
                # appropriate later?

            # set the dtcs polarity
            dtcs_pol_bit_to_str = {0: 'N', 1: 'R'}
            mem.dtcs_polarity = '%s%s' %\
                (dtcs_pol_bit_to_str[_mem.dtcs_encode_invert == 1],
                 dtcs_pol_bit_to_str[_mem.dtcs_decode_invert == 1])

            # Extra
            mem.extra = RadioSettingGroup("Extra", "extra")

            # Busy channel lockout
            bcl_options = ['Off', 'Repeater', 'Busy']
            bcl_option = bcl_options[_mem.busy_channel_lockout]
            rs = RadioSetting("busy_channel_lockout", "Busy Channel Lockout",
                              RadioSettingValueList(bcl_options, bcl_option))
            mem.extra.append(rs)

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
            _mem.set_raw('\xff' * (_mem.size() // 8))
        else:
            _mem.set_raw('\x00' * (_mem.size() // 8))

            _mem.freq = int(mem.freq / 10)
            _mem.offset = int(mem.offset / 10)

            # Store the alpha tag
            if self.NAME_LENGTH == 5:
                # original models with 5-character name length
                temp_name = mem.name.ljust(self.NAME_LENGTH)[:self.NAME_LENGTH]
                # prefix the 5-character name with 0x00 to fit structure
                _mem.name = temp_name.rjust(6, chr(00))
            else:
                # new VOX models with 6-character name length
                _mem.name = mem.name.ljust(self.NAME_LENGTH)[:self.NAME_LENGTH]

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

            # Set the channel width - remember we promote 20 kHz channels to FM
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
                    dtcs_code_val_to_bits(mem.dtcs)
                _mem.dtcs_decode_en = 1
                _mem.dtcs_decode_code, _mem.dtcs_decode_code_highbit = \
                    dtcs_code_val_to_bits(mem.dtcs)
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

            # Extra settings (eg. Busy channel lockout)
            for setting in mem.extra:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        """Translate the MEM_FORMAT structs into setstuf in the UI"""
        _settings = self._memobj.settings
        _radio_settings = self._memobj.radio_settings
        _password = self._memobj.password
        _pfkeys = self._memobj.pfkeys
        _dtmf = self._memobj.dtmf

        # Function Setup
        function = RadioSettingGroup("function", "Function Setup")
        group = RadioSettings(function)

        # MODE SET
        # Channel Locked
        rs = RadioSettingValueBoolean(_settings.channelLocked)
        rset = RadioSetting("settings.channelLocked", "Channel locked", rs)
        function.append(rset)

        # Menu 3 - Display Mode
        options = ["Frequency", "Channel", "Name"]
        rs = RadioSettingValueList(
            options, current_index=_settings.displayMode)
        rset = RadioSetting("settings.displayMode", "Display Mode", rs)
        function.append(rset)

        # VFO/MR A
        options = ["MR", "VFO"]
        rs = RadioSettingValueList(
            options, current_index=_radio_settings.vfomrA)
        rset = RadioSetting("radio_settings.vfomrA", "VFO/MR mode A", rs)
        function.append(rset)

        # MR Channel A
        options = ["%s" % x for x in range(1, 201)]
        rs = RadioSettingValueList(
            options, current_index=_radio_settings.mrChanA)
        rset = RadioSetting("radio_settings.mrChanA", "MR channel A", rs)
        function.append(rset)

        # VFO/MR B
        options = ["MR", "VFO"]
        rs = RadioSettingValueList(
            options, current_index=_radio_settings.vfomrB)
        rset = RadioSetting("radio_settings.vfomrB", "VFO/MR mode B", rs)
        function.append(rset)

        # MR Channel B
        options = ["%s" % x for x in range(1, 201)]
        rs = RadioSettingValueList(
            options, current_index=_radio_settings.mrChanB)
        rset = RadioSetting("radio_settings.mrChanB", "MR channel B", rs)
        function.append(rset)

        # DISPLAY SET
        # Starting Display
        name = ""
        for i in range(7):  # 0 - 7
            name += chr(int(self._memobj.starting_display.line[i]))
        name = name.upper().rstrip()  # remove trailing spaces

        rs = RadioSettingValueString(0, 7, name)
        rs.set_charset(chirp_common.CHARSET_ALPHANUMERIC)
        rset = RadioSetting("starting_display.line", "Starting display", rs)
        function.append(rset)

        # Menu 11 - Backlight Brightness
        options = ["%s" % x for x in range(1, 4)]
        rs = RadioSettingValueList(
            options, current_index=_settings.backlightBr - 1)
        rset = RadioSetting("settings.backlightBr", "Backlight brightness", rs)
        function.append(rset)

        # Menu 15 - Screen Direction
        options = ["Positive", "Inverted"]
        rs = RadioSettingValueList(options, current_index=_settings.screenDir)
        rset = RadioSetting("settings.screenDir", "Screen direction", rs)
        function.append(rset)

        # Hand Mic Key Brightness
        options = ["%s" % x for x in range(1, 32)]
        rs = RadioSettingValueList(
            options, current_index=_settings.micKeyBrite - 1)
        rset = RadioSetting("settings.micKeyBrite",
                            "Hand mic key brightness", rs)
        function.append(rset)

        # VOL SET
        # Menu 1 - Beep Volume
        options = ["OFF"] + ["%s" % x for x in range(1, 6)]
        rs = RadioSettingValueList(options, current_index=_settings.beepVolume)
        rset = RadioSetting("settings.beepVolume", "Beep volume", rs)
        function.append(rset)

        # Menu 5 - Volume level Setup
        options = ["%s" % x for x in range(1, 37)]
        rs = RadioSettingValueList(
            options, current_index=_settings.speakerVol - 1)
        rset = RadioSetting("settings.speakerVol", "Speaker volume", rs)
        function.append(rset)

        # Menu 16 - Speaker Switch
        options = ["Host on | Hand mic off", "Host on | Hand mic on",
                   "Host off | Hand mic on"]
        rs = RadioSettingValueList(
            options, current_index=_settings.speakerSwitch)
        rset = RadioSetting("settings.speakerSwitch", "Speaker switch", rs)
        function.append(rset)

        # STE SET
        # STE Frequency
        options = ["Off", "55.2 Hz", "259.2 Hz"]
        rs = RadioSettingValueList(
            options, current_index=_settings.steFrequency)
        rset = RadioSetting("settings.steFrequency", "STE frequency", rs)
        function.append(rset)

        # STE Type
        options = ["Off", "Silent", "120 degrees", "180 degrees",
                   "240 degrees"]
        rs = RadioSettingValueList(options, current_index=_settings.steType)
        rset = RadioSetting("settings.steType", "STE type", rs)
        function.append(rset)

        # ON/OFF SET
        # The Power-on Password feature is not available on models with VOX
        if not self.HAS_VOX:
            # Power-on Password
            rs = RadioSettingValueBoolean(_settings.powerOnPasswd)
            rset = RadioSetting("settings.powerOnPasswd", "Power-on Password",
                                rs)
            function.append(rset)

            # Password
            def _char_to_str(chrx):
                """ Remove ff pads from char array """
                #  chrx is char array
                str1 = ""
                for sx in chrx:
                    if int(sx) > 31 and int(sx) < 127:
                        str1 += chr(int(sx))
                return str1

            def _pswd_vfy(setting, obj, atrb):
                """ Verify password is 1-6 chars, numbers 1-5 """
                str1 = str(setting.value).strip()  # initial
                # valid chars
                str2 = ''.join([c for c in str1 if c in '0123456789'])
                if str1 != str2:
                    # Two lines due to python 73 char limit
                    sx = "Bad characters in Password"
                    raise errors.RadioError(sx)
                str2 = str1.ljust(6, chr(00))  # pad to 6 with 00's
                setattr(obj, atrb, str2)
                return

            sx = _char_to_str(_password.digits).strip()
            rx = RadioSettingValueString(0, 6, sx)
            sx = "Password (numerals 0-9)"
            rset = RadioSetting("password.digits", sx, rx)
            rset.set_apply_callback(_pswd_vfy, _password, "digits")
            function.append(rset)

        # Menu 9 - Auto Power On
        rs = RadioSettingValueBoolean(_settings.autoPowerOn)
        rset = RadioSetting("settings.autoPowerOn", "Auto power on", rs)
        function.append(rset)

        # Menu 13 - Auto Power Off
        options = ["Off", "30 minutes", "60 minutes", "120 minutes"]
        rs = RadioSettingValueList(
            options, current_index=_settings.autoPowerOff)
        rset = RadioSetting("settings.autoPowerOff", "Auto power off", rs)
        function.append(rset)

        # Power On Reset Enable
        rs = RadioSettingValueBoolean(_settings.powerOnReset)
        rset = RadioSetting("settings.powerOnReset", "Power on reset", rs)
        function.append(rset)

        # FUNCTION SET
        # Menu 4 - Squelch Level A
        options = ["OFF"] + ["%s" % x for x in range(1, 10)]
        rs = RadioSettingValueList(
            options, current_index=_settings.squelchLevelA)
        rset = RadioSetting("settings.squelchLevelA", "Squelch level A", rs)
        function.append(rset)

        # Squelch Level B
        options = ["OFF"] + ["%s" % x for x in range(1, 10)]
        rs = RadioSettingValueList(
            options, current_index=_settings.squelchLevelB)
        rset = RadioSetting("settings.squelchLevelB", "Squelch level B", rs)
        function.append(rset)

        # Menu 7 - Scan Type
        options = ["Time operated (TO)", "Carrier operated (CO)",
                   "Search (SE)"]
        rs = RadioSettingValueList(options, current_index=_settings.scanType)
        rset = RadioSetting("settings.scanType", "Scan mode", rs)
        function.append(rset)

        # Menu 8 - Scan Recovery Time
        options = ["%s seconds" % x for x in range(5, 20, 5)]
        rs = RadioSettingValueList(
            options, current_index=_settings.scanRecoveryT)
        rset = RadioSetting("settings.scanRecoveryT", "Scan recovery time", rs)
        function.append(rset)

        # Main
        options = ["A", "B"]
        rs = RadioSettingValueList(options, current_index=_settings.main)
        rset = RadioSetting("settings.main", "Main", rs)
        function.append(rset)

        # Menu 10 - Dual Watch (RX Way Select)
        rs = RadioSettingValueBoolean(_settings.dualWatch)
        rset = RadioSetting("settings.dualWatch", "Dual watch", rs)
        function.append(rset)

        # Menu 12 - Time Out Timer
        options = ["OFF"] + ["%s minutes" % x for x in range(1, 31)]
        rs = RadioSettingValueList(
            options, current_index=_settings.timeOutTimer)
        rset = RadioSetting("settings.timeOutTimer", "Time out timer", rs)
        function.append(rset)

        # TBST Frequency
        options = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
        rs = RadioSettingValueList(
            options, current_index=_settings.tbstFrequency)
        rset = RadioSetting("settings.tbstFrequency", "TBST frequency", rs)
        function.append(rset)

        # Save Channel Parameter
        rs = RadioSettingValueBoolean(_settings.saveChParameter)
        rset = RadioSetting("settings.saveChParameter",
                            "Save channel parameter", rs)
        function.append(rset)

        # MON Key Function
        options = ["Squelch off momentary", "Squelch off"]
        rs = RadioSettingValueList(
            options, current_index=_settings.monKeyFunction)
        rset = RadioSetting("settings.monKeyFunction", "MON key function", rs)
        function.append(rset)

        # Frequency Step
        options = ["2.5 kHz", "5 kHz", "6.25 kHz", "10 kHz", "12.5 kHz",
                   "20 kHz", "25 kHz", "30 kHz", "50 kHz"]
        rs = RadioSettingValueList(
            options, current_index=_settings.frequencyStep)
        rset = RadioSetting("settings.frequencyStep", "Frequency step", rs)
        function.append(rset)

        # Knob Mode
        options = ["Volume", "Channel"]
        rs = RadioSettingValueList(options, current_index=_settings.knobMode)
        rset = RadioSetting("settings.knobMode", "Knob mode", rs)
        function.append(rset)

        # TRF Enable
        rs = RadioSettingValueBoolean(_settings.trfEnable)
        rset = RadioSetting("settings.trfEnable", "TRF enable", rs)
        function.append(rset)

        if self.HAS_VOX:
            # VOX On/Off
            rs = RadioSettingValueBoolean(_settings.voxOnOff)
            rset = RadioSetting("settings.voxOnOff",
                                "VOX", rs)
            function.append(rset)

            # VOX Delay
            options = ["0.5 S", "1.0 S", "1.5 S", "2.0 S", "2.5 S",
                       "3.0 S", "3.5 S", "4.0 S", "4.5 S"]
            rs = RadioSettingValueList(
                options, current_index=_settings.voxDelay)
            rset = RadioSetting("settings.voxDelay", "VOX delay", rs)
            function.append(rset)

            # VOX Level
            options = ["%s" % x for x in range(1, 10)]
            rs = RadioSettingValueList(
                options, current_index=_settings.voxLevel)
            rset = RadioSetting("settings.voxLevel", "VOX Level", rs)
            function.append(rset)

        # Key Assignment
        pfkeys = RadioSettingGroup("pfkeys", "Key Assignment")
        group.append(pfkeys)

        options = ["A/B", "V/M", "SQL", "VOL", "POW", "CDT", "REV", "SCN",
                   "CAL", "TALK", "BND", "SFT", "MON", "DIR", "TRF", "RDW",
                   "NULL"]

        if self.HAS_VOX:
            options.insert(16, "VOX")

        # Key Mode 1
        # P1
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode1P1 - 1)
        rset = RadioSetting("pfkeys.keyMode1P1",
                            "Key mode 1 P1", rs)
        pfkeys.append(rset)

        # P2
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode1P2 - 1)
        rset = RadioSetting("pfkeys.keyMode1P2",
                            "Key mode 1 P2", rs)
        pfkeys.append(rset)

        # P3
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode1P3 - 1)
        rset = RadioSetting("pfkeys.keyMode1P3",
                            "Key mode 1 P3", rs)
        pfkeys.append(rset)

        # P4
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode1P4 - 1)
        rset = RadioSetting("pfkeys.keyMode1P4",
                            "Key mode 1 P4", rs)
        pfkeys.append(rset)

        # P5
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode1P5 - 1)
        rset = RadioSetting("pfkeys.keyMode1P5",
                            "Key mode 1 P5", rs)
        pfkeys.append(rset)

        # P6
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode1P6 - 1)
        rset = RadioSetting("pfkeys.keyMode1P6",
                            "Key mode 1 P6", rs)
        pfkeys.append(rset)

        # Key Mode 2
        # P1
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode2P1 - 1)
        rset = RadioSetting("pfkeys.keyMode2P1",
                            "Key mode 2 P1", rs)
        pfkeys.append(rset)

        # P2
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode2P2 - 1)
        rset = RadioSetting("pfkeys.keyMode2P2",
                            "Key mode 2 P2", rs)
        pfkeys.append(rset)

        # P3
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode2P3 - 1)
        rset = RadioSetting("pfkeys.keyMode2P3",
                            "Key mode 2 P3", rs)
        pfkeys.append(rset)

        # P4
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode2P4 - 1)
        rset = RadioSetting("pfkeys.keyMode2P4",
                            "Key mode 2 P4", rs)
        pfkeys.append(rset)

        # P5
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode2P5 - 1)
        rset = RadioSetting("pfkeys.keyMode2P5",
                            "Key mode 2 P5", rs)
        pfkeys.append(rset)

        # P6
        rs = RadioSettingValueList(
            options, current_index=_pfkeys.keyMode2P6 - 1)
        rset = RadioSetting("pfkeys.keyMode2P6",
                            "Key mode 2 P6", rs)
        pfkeys.append(rset)

        options = ["V/M", "SQL", "VOL", "POW", "CDT", "REV", "SCN", "CAL",
                   "TALK", "BND", "SFT", "MON", "DIR", "TRF", "RDW"]

        if self.HAS_VOX:
            options.insert(15, "VOX")

        # PA
        rs = RadioSettingValueList(options, current_index=_settings.keyPA - 2)
        rset = RadioSetting("settings.keyPA",
                            "Key PA", rs)
        pfkeys.append(rset)

        # PB
        rs = RadioSettingValueList(options, current_index=_settings.keyPB - 2)
        rset = RadioSetting("settings.keyPB",
                            "Key PB", rs)
        pfkeys.append(rset)

        # PC
        rs = RadioSettingValueList(options, current_index=_settings.keyPC - 2)
        rset = RadioSetting("settings.keyPC",
                            "Key PC", rs)
        pfkeys.append(rset)

        # PD
        rs = RadioSettingValueList(options, current_index=_settings.keyPD - 2)
        rset = RadioSetting("settings.keyPD",
                            "Key PD", rs)
        pfkeys.append(rset)

        # DTMF
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        group.append(dtmf)

        # DTMF Transmitting Time
        options = ["50 milliseconds", "100 milliseconds", "200 milliseconds",
                   "300 milliseconds", "500 milliseconds"]
        rs = RadioSettingValueList(options, current_index=_settings.dtmfTxTime)
        rset = RadioSetting("settings.dtmfTxTime",
                            "DTMF transmitting time", rs)
        dtmf.append(rset)

        # DTMF Self ID

        # DTMF Interval Character
        IC_CHOICES = ["A", "B", "C", "D", "*", "#"]
        IC_VALUES = [0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F]

        def apply_ic_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) + " from list")
            val = str(setting.value)
            index = IC_CHOICES.index(val)
            val = IC_VALUES[index]
            obj.set_value(val)

        if _dtmf.intervalChar in IC_VALUES:
            idx = IC_VALUES.index(_dtmf.intervalChar)
        else:
            idx = IC_VALUES.index(0x0E)
        rs = RadioSetting("dtmf.intervalChar", "DTMF interval character",
                          RadioSettingValueList(IC_CHOICES,
                                                current_index=idx))
        rs.set_apply_callback(apply_ic_listvalue, _dtmf.intervalChar)
        dtmf.append(rs)

        # Group Code
        GC_CHOICES = ["Off", "A", "B", "C", "D", "*", "#"]
        GC_VALUES = [0xFF, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F]

        def apply_gc_listvalue(setting, obj):
            LOG.debug("Setting value: " + str(setting.value) + " from list")
            val = str(setting.value)
            index = GC_CHOICES.index(val)
            val = GC_VALUES[index]
            obj.set_value(val)

        if _dtmf.groupCode in GC_VALUES:
            idx = GC_VALUES.index(_dtmf.groupCode)
        else:
            idx = GC_VALUES.index(0x0A)
        rs = RadioSetting("dtmf.groupCode", "DTMF interval character",
                          RadioSettingValueList(GC_CHOICES,
                                                current_index=idx))
        rs.set_apply_callback(apply_gc_listvalue, _dtmf.groupCode)
        dtmf.append(rs)

        # Decoding Response
        options = ["None", "Beep tone", "Beep tone & respond"]
        rs = RadioSettingValueList(
            options, current_index=_dtmf.decodingResponse)
        rset = RadioSetting("dtmf.decodingResponse", "Decoding response", rs)
        dtmf.append(rset)

        # First Digit Time
        options = ["%s" % x for x in range(0, 2510, 10)]
        rs = RadioSettingValueList(options, current_index=_dtmf.firstDigitTime)
        rset = RadioSetting("dtmf.firstDigitTime", "First Digit Time(ms)", rs)
        dtmf.append(rset)

        # First Digit Time
        options = ["%s" % x for x in range(10, 2510, 10)]
        rs = RadioSettingValueList(options, current_index=_dtmf.pretime - 1)
        rset = RadioSetting("dtmf.pretime", "Pretime(ms)", rs)
        dtmf.append(rset)

        # Auto Reset Time
        options = ["%s" % x for x in range(0, 25100, 100)]
        rs = RadioSettingValueList(options, current_index=_dtmf.autoResetTime)
        rset = RadioSetting("dtmf.autoResetTime", "Auto Reset time(ms)", rs)
        dtmf.append(rset)

        # Time-Lapse After Encode
        options = ["%s" % x for x in range(10, 2510, 10)]
        rs = RadioSettingValueList(options, current_index=_dtmf.timeLapse - 1)
        rset = RadioSetting("dtmf.timeLapse",
                            "Time-lapse after encode(ms)", rs)
        dtmf.append(rset)

        # PTT ID Pause Time
        options = ["Off", "-", "-", "-", "-"] + [
                   "%s" % x for x in range(5, 76)]
        rs = RadioSettingValueList(options, current_index=_dtmf.pauseTime)
        rset = RadioSetting("dtmf.pauseTime", "PTT ID pause time(s)", rs)
        dtmf.append(rset)

        # Side Tone
        rs = RadioSettingValueBoolean(_dtmf.sideTone)
        rset = RadioSetting("dtmf.sideTone", "Side tone", rs)
        dtmf.append(rset)

        # PTT ID Starting
        DTMF_CHARS = "0123456789ABCD*# "
        _codeobj = _dtmf.pttIdStart
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 16, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("dtmf.pttIdStart", "PTT ID starting", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 16):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.pttIdStart = code
        rs.set_apply_callback(apply_code, _dtmf)
        dtmf.append(rs)

        # PTT ID Ending
        _codeobj = _dtmf.pttIdEnd
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 16, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("dtmf.pttIdEnd", "PTT ID ending", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 16):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.pttIdEnd = code
        rs.set_apply_callback(apply_code, _dtmf)
        dtmf.append(rs)

        # Remotely Kill
        _codeobj = _dtmf.remoteKill
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 16, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("dtmf.remoteKill", "Remotely kill", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 16):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.remoteKill = code
        rs.set_apply_callback(apply_code, _dtmf)
        dtmf.append(rs)

        # Remotely Stun
        _codeobj = _dtmf.remoteStun
        _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 16, _code, False)
        val.set_charset(DTMF_CHARS)
        rs = RadioSetting("dtmf.remoteStun", "Remotely stun", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 16):
                try:
                    code.append(DTMF_CHARS.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.remoteStun = code
        rs.set_apply_callback(apply_code, _dtmf)
        dtmf.append(rs)

        # DTMF Encode
        # M1 - M16
        for i in range(0, 16):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([DTMF_CHARS[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 16, _code, False)
            val.set_charset(DTMF_CHARS)
            rs = RadioSetting("pttid/%i.code" % i,
                              "DTMF encode M%i" % (i + 1), val)

            def apply_code(setting, obj):
                code = []
                for j in range(0, 16):
                    try:
                        code.append(DTMF_CHARS.index(str(setting.value)[j]))
                    except IndexError:
                        code.append(0xFF)
                obj.code = code
            rs.set_apply_callback(apply_code, self._memobj.pttid[i])
            dtmf.append(rs)

        return group

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
                    elif setting == "timeLapse":
                        setattr(obj, setting, int(element.value) + 1)
                    elif setting == "pretime":
                        setattr(obj, setting, int(element.value) + 1)
                    elif setting == "backlightBr":
                        setattr(obj, setting, int(element.value) + 1)
                    elif setting == "micKeyBrite":
                        setattr(obj, setting, int(element.value) + 1)
                    elif setting == "speakerVol":
                        setattr(obj, setting, int(element.value) + 1)
                    elif "keyMode" in setting:
                        setattr(obj, setting, int(element.value) + 1)
                    elif "keyP" in setting:
                        setattr(obj, setting, int(element.value) + 2)
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise


# Original non-VOX models
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


@directory.register
class YedroYCM04vus(AnyTone778UVBase):
    VENDOR = "Yedro"
    MODEL = "YC-M04VUS"
    # Allowed radio types is a dict keyed by model of a list of version
    # strings
    ALLOWED_RADIO_TYPES = {'YCM04UV': ['V100']}


class AnyTone778UVvoxBase(AnyTone778UVBase):
    '''AnyTone 778UV VOX, Retevis RT95 VOX and others'''
    NAME_LENGTH = 6
    HAS_VOX = True


# New VOX models
@directory.register
@directory.detected_by(AnyTone778UV)
class AnyTone778UVvox(AnyTone778UVvoxBase):
    VENDOR = "AnyTone"
    MODEL = "778UV VOX"
    # Allowed radio types is a dict keyed by model of a list of version
    # strings
    ALLOWED_RADIO_TYPES = {'778UV-P': ['V100']}


@directory.register
@directory.detected_by(RetevisRT95)
class RetevisRT95vox(AnyTone778UVvoxBase):
    VENDOR = "Retevis"
    MODEL = "RT95 VOX"
    # Allowed radio types is a dict keyed by model of a list of version
    # strings
    ALLOWED_RADIO_TYPES = {'RT95-P': ['V100']}


@directory.register
@directory.detected_by(CRTMicronUV)
class CRTMicronUVvox(AnyTone778UVvoxBase):
    VENDOR = "CRT"
    MODEL = "Micron UV V2"
    # Allowed radio types is a dict keyed by model of a list of version
    # strings
    ALLOWED_RADIO_TYPES = {'MICRONP': ['V100']}
