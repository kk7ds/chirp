# Copyright 2026 Fred Trimble <chirpdriver@gmail.com>
# CHIRP driver for the TIDRADIO TD-H8 Gen 2, 3 & 4, TD-H3 & Plus
# and TD-H9 radios
#
# This is a complete rewrite of the original tdh8.py to make it more
# maintainable and to support the newer radios. It is based on the
# original code by Fred Trimble and many previous contributors,
# but has been significantly modified and improved.
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

from chirp import (
    bitwise,
    bandplan_na,
    checksum,
    chirp_common,
    directory,
    errors,
    memmap,
    platform,
    util,
)

from chirp.settings import (
    RadioSetting,
    RadioSettings,
    RadioSettingGroup,
    RadioSettingSubGroup,
    RadioSettingValueBoolean,
    RadioSettingValueInvertedBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueMap,
    RadioSettingValueString,
    MemSetting,
)

from textwrap import dedent

import logging
import struct
from textwrap import dedent
from datetime import datetime

LOG = logging.getLogger(__name__)

CMD_ACK = b'\x06'

# magic strings used to put radio into programming mode
TD_H8 = b'\x50\x56\x4f\x4a\x48\x1c\x14'
TD_H3 = b'\x50\x56\x4f\x4a\x48\x5c\x14'  # used by H3, H3 Plus H8 G4 and H9
RT_730 = b'\x50\x47\x4f\x4a\x48\xc3\x44'
TD_H8_G3 = b'PVOJH<\x14'

TDH8_CHARSET = chirp_common.CHARSET_ALPHANUMERIC + \
    '!@#$%^&*()+-=[]:";\'<>?,./'
DTMF_CHARS = '0123456789 *#ABCD'
GMRS_FREQS = bandplan_na.ALL_GMRS_FREQS

def _do_status(radio, cur, max):
    status = chirp_common.Status()
    status.msg = 'Cloning %3i%%' % (round(cur / max * 100))
    status.cur = cur
    status.max = max
    radio.status_fn(status)

def _do_ident(serial, magic, secondack=True):
    serial.timeout = 1

    LOG.info('Sending Magic: %s' % util.hexprint(magic))
    serial.write(magic)
    ack = serial.read(1)

    if not ack:
        raise errors.RadioNoResponse()
    if ack != CMD_ACK:
        raise errors.RadioError('Radio refused to enter programming mode')

    serial.write(b'\x02')

    response = b''
    for i in range(1, 9):
        byte = serial.read(1)
        response += byte
        if byte == b'\xdd':
            break

    if len(response) in [8, 12]:
        LOG.info('Valid response, got this: %s' % util.hexprint(response))
        if len(response) == 12:
            ident = response[0] + response[3] + response[5] + response[7:]
        else:
            ident = response
    else:
        # bad response
        LOG.debug('Unexpected response, got this: %s' % util.hexprint(response))
        raise errors.RadioError('Unexpected response from radio.')

    if secondack:
        serial.write(CMD_ACK)
        ack = serial.read(1)
        if ack != CMD_ACK:
            raise errors.RadioError('Radio refused clone')

    return ident

def _read_block(radio, start, size):
    serial = radio.pipe

    cmd = struct.pack('>cHb', b'R', start, size)
    expectedresponse = b'W' + cmd[1:]

    try:
        serial.write(cmd)
        response = serial.read(5 + size)
        if not response:
            if start == 0:
                raise errors.RadioNoResponse()
            raise errors.RadioError('Failed to read block at 0x%04x' % start)
        if response[:4] != expectedresponse:
            raise errors.RadioError('Error reading block 0x%04x.' % (start))
        block_data = response[4:-1]

    except errors.RadioError:
        raise
    except Exception:
        raise errors.RadioError('Failed to read block at 0x%04x' % start)

    return block_data

def _do_download(radio):
    # Radio must have already been ident'd by detect_from_serial()
    data = radio.ident_mode
    LOG.info('Downloading...')

    _max = int(radio._memsize / radio.BLOCKSIZE)  # number of blocks
    _block_num = 0
    for addr in range(0, radio._memsize, radio.BLOCKSIZE):
        radio.pipe.log('Reading from address: 0x%04x' % addr)
        block = _read_block(radio, addr, radio.BLOCKSIZE)
        data += block
        _do_status(radio, _block_num, _max)
        _block_num += 1
    _do_status(radio, _max, _max) # show 100%
    LOG.info('Download done!')

    return memmap.MemoryMapBytes(data)

def _write_block(radio, block_addr, size):
    _channel_offset = 0x08  # byte offset in img file where channel data starts
    serial = radio.pipe
    cmd = struct.pack('>cHb', b'W', block_addr, radio.BLOCKSIZE_UP)
    data = radio.get_mmap()[block_addr + _channel_offset:block_addr + size +
                            _channel_offset]
    cs = checksum.checksum_8bit(data)
    frame = cmd + data + bytes([cs])
    serial.write(frame)

    ack = serial.read(1)
    if ack != CMD_ACK:
        raise errors.RadioError('Radio refused to accept block 0x%04x' %
                                block_addr)

def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write(b'E')
    except Exception:
        raise errors.RadioError('Radio refused to exit programming mode')

def _do_upload(radio):
    _, data = test_idents(radio, radio.pipe)
    if radio.ident_mode == data:
        LOG.info('Successful match during Upload.')
    else:
        LOG.error('Model mismatch during Upload!')
    LOG.info('Uploading...')

    _max = int(sum(abs(x -y) for x, y in radio._ranges_main) /
               radio.BLOCKSIZE_UP)  # number of blocks
    _block_num = 0
    for start_addr, end_addr in radio._ranges_main:
        for addr in range(start_addr, end_addr, radio.BLOCKSIZE_UP):
            radio.pipe.log('Writing to address: 0x%04x' % addr)
            _write_block(radio, addr, radio.BLOCKSIZE_UP)
            _do_status(radio, _block_num, _max)
            _block_num += 1
    _exit_programming_mode(radio)
    _do_status(radio, _max, _max)  # show 100%
    LOG.info('Upload done!')

def validate_gmrs_memory(mem):
    _lo = 1  # manditory GMRS channel numbers lower bound
    _hi = 54 #                "               upper bound
    msgs = []
    if _lo <= mem.number <= _hi:
        if mem.freq not in GMRS_FREQS:
            msgs.append(chirp_common.ValidationError(
                'The frequency in channels %d-%d must be a GMRS '
                'frequency between %0.5f-%0.5f in 0.025 increments.'
                % (_lo, _hi, min(GMRS_FREQS) / 1000000,
                   max(GMRS_FREQS) / 1000000)))
        if mem.duplex not in ('', '+', 'off') or (
                mem.duplex == '+' and mem.offset != 5000000):
            msgs.append(chirp_common.ValidationError(
                'Channels %d-%d must be a GMRS frequencies and '
                'either simplex or +5MHz offset' % (_lo, _hi)))
    return msgs

def test_idents(cls, pipe):
    """tests a list of idents (magics) to see if the radio responds,
    returns the class and ident (magic) of the responding device"""
    resp = False
    for rclass in cls.detected_models():
        for id in rclass._idents:  # iterate list of _idents (magics)
            try:
                ident = _do_ident(pipe, id)
                if rclass.ident_mode == ident:
                    return rclass, rclass.ident_mode
            except errors.RadioNoResponse:
                continue
            except errors.RadioNoResponse:
                resp = True
            except Exception:
                raise
            LOG.error('No model match found for %r', id)
    else:  # for
        if resp:
            raise errors.RadioError('Unexpected response from radio')
        else:
            raise errors.RadioError('Unsupported model')


@directory.register
class TDH8(chirp_common.CloneModeRadio):
    """TIDRADIO TD-H8 Normal"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8'
    ident_mode = b'P31183\xff\xff'
    _idents = [TD_H8]
    _gmrs = False
    _ham = False
    BAUD_RATE = 38400
    BLOCKSIZE = 0x20
    BLOCKSIZE_UP = 0x20
    _memsize = 0x1fef  # 0x1eef
    _ranges_main = [(0x0000, _memsize)]
    # _mmap = bytearray(_memsize)
    _memobj = bytearray(_memsize)
    _mem_params = {
        'channels': 200,
        'fmb_channels': 25,
        'dtmf_strings': 8,
        'dtmf_len': 16,
        'name_len': 8,
    }
    _txbands = [(136000000, 175000000), (400000000, 521000000)]
    _airband = []
    _rxbands = [] + _airband
    _special_channels = ['VFO A','VFO B']
    _modes = ['FM', 'NFM']  # TD-H8 Gen 1 & 2 don't have AM RX!
    _has_am = False
    _has_am_per_channel = False
    _has_offsetdir = True
    _has_scramble = False
    _has_pttid = True
    _has_bcl = True
    _has_freqhop = True
    _has_dtmf = True
    _has_stored_dtmf = False
    _has_dtmf_len = True
    _has_dtmf_terminated = not _has_dtmf_len
    _has_stuncode = False
    _has_killcode = False
    _has_dtmf_extra = False
    _has_scan_hangtime = False
    _has_freq_ranger = False
    _has_pf2_button = True
    _has_top_button = True
    _has_def_chan = True
    _has_bluetooth = True
    _has_brightness = False
    _has_pritx = True
    _has_spec= False

    _valid_chars = TDH8_CHARSET
    _tx_power = [chirp_common.PowerLevel('Low', watts=1.00),
                chirp_common.PowerLevel('Mid', watts=4.00),
                chirp_common.PowerLevel('High', watts=8.00),
                ]
    _steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0]
    # maps DTMF chars to binary values the radio uses
    _dtmf_code_dict = {
        0x00: '0', 0x01: '1', 0x02: '2', 0x03: '3',
        0x04: '4', 0x05: '5', 0x06: '6', 0x07: '7',
        0x08: '8', 0x09: '9', 0x0a: 'A', 0x0b: 'B',
        0x0c: 'C', 0x0d: 'D', 0x0e: '*', 0x0f: '#',
        0xff: ' ',
    }
    _inverted_dtmf_code_dict = {v: k for k, v in _dtmf_code_dict.items()}
    # maps for settings
    _groupcode_map = [('', 0x00), ('Off', 0xff), ('*', 0x0e), ('#', 0x0f),
                      ('A', 0x0a), ('B', 0x0b), ('C', 0x0c), ('D', 0x0d)]
    # one-based map of FM broadcast channels
    _fmchannels_map = [(str(x), x) for x in \
                       range(1, _mem_params.get('fmb_channels') + 1)]
    _lang_map = [('Chinese', 1), ('English', 3)]
    # lists for settings
    _operating_mode_list = ['NORMAL', 'GMRS', 'HAM']
    _squelch_list = ['%s' % x for x in range(0, 10)]
    _step_list = ['%2.2fK' % x for x in _steps]
    _pttid_list = ['Off', 'BOT', 'EOT', 'BOTH']
    _dtmf_reset_list = ['Off', '5s', '10s', '15s']
    _dtmf_resp_list = ['NULL', 'RING', 'REPLY', 'BOTH']
    _dtmf_speed_list = ['%ims' % x for x in range(80, 160, 10)]
    _pritx_list = ['MAIN', 'Busy']
    _scanmode_list = ['TO', 'CO', 'SE']
    _vfo_workmode_list = ['VFO', 'VFO+Channel', 'Channel']
    _fmworkmode_list = ['VFO', 'CH']
    _short_press_list =  ['None', 'FM Radio', 'Lamp', 'Monitor',
                          'TONE', 'Alarm', 'Weather',
                          ]
    _long_press_list = _short_press_list
    _micgain_list = ['%02d' % x for x in range(0, 33)]
    _voxgain_list = ['Off', '1', '2', '3', '4', '5']
    _voxdelay_list = ['1.0s', '2.0s', '3.0s']
    _tot_list = ['Off'] + ['%ds' % x for x in range(30, 240, 30)]
    _backlight_list = ['CONT', '5s', '10s', '15s', '30s']
    _breath_led_list = ['Off', '5s', '10s', '15s', '30s']
    _ponmsg_list = ['Off', 'Msg', 'Icon']

    _fmrec_shortname = 'Allow Receive'

    _mem_format = """
    // 16 byte memory channel
    struct memory_obj {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      lbcd rxtone[2];
      lbcd txtone[2];
      u8 scramble;        // (not used on TD-H8 Gen 2 & 3)
      u8 pttid:2,
        freqhop:1,
        deccode:1,
        unknown1:1,
        bcl:1,
        unknown2:1,
        unknown3:1;
      u8 unknown4:1,
        unknown5:1,
        power:2,
        narrow:1,
        unknown6:1,
        offsetdir:2;
      u8 unknown7:7,
        am_modulation:1; // Per chan AM modulation
                        // (Not used on TD-H8 Gen 2 & 3 & TD-H3)
    };
    """

    _common_format = """
    // vfo offset obj
    struct offset_obj {
      lbcd offset[4];
    };

    // FM broadcast channel obj
    struct fmb_obj {
      lbcd rxfreq[4];
    };

    // power on message obj
    struct poweron_msg_obj {
      char msg1[16];
      char msg2[16];
      char msg3[16];
    };

    // power on message 2 obj
    struct poweron_msg2_obj {
      char msg1[16];
      char msg2[16];
      char msg3[16];
      char msg4[16];
    };
    """

    _button_format = """
    // programmable button obj
    struct button_obj {
      u8 stopkey1;        // topkey  short press
      u8 ssidekey1;       // pf1 short press
      u8 ssidekey2;       // pf2 short press
      u8 ltopkey1;        // topkey long press
      u8 lsidekey1;       // pf1 long press
      u8 lsidekey2;       // pf2 long press
    };
    """

    _name_format = """
    // channel name
    struct name_obj {
      char name[%(name_len)i];
      u8 unknown1[8];
    };

    // dtmf string
    struct dtmf_obj {
      u8 code[%(dtmf_len)i];
    };
    """

    _settings_format = """
    struct settings_obj {
      u8 txled:1,
        rxled:1,
        unused11:1,
        mode:2, // Radio op mode: 0=Normal, 1=GMRS, 2=HAM, 3=unused
        //ham:1,
        //gmrs:1,
        unused14:1,
        dtmfst:1,
        pritx:1;
      u8 scanmode:2,
        unused16:1,
        keyautolock:1,
        unused17:1,
        beep:1,
        unknown18:1,
        voiceprompt:1;
      u8 fmworkmode:1,
        dualwatch:1,
        tonevoice:2,
        fmrec:1,
        mdfa:1,
        aworkmode:2;
      u8 ponmsg:2,
        unused19:1,
        mdfb:1,
        unused20:1,
        dbrx:1,
        bworkmode:2;
      u8 adefchan;
      u8 bdefchan;
      u8 fmdefch;
      u8 unused21:1,
        tailclean:1,
        rogerprompt:1,
        unused23:1,
        unused24:1,
        voxgain:3;
      u8 astep:4,
        bstep:4;
      u8 squelch;
      u8 tot;
      u8 lang;
      u8 save;
      u8 ligcon;
      u8 voxdelay;
      u8 onlychmode:1,
        breathled:3,
        unused:3,
        alarm:1;
    };
    """

    _end_fromat = """
    """

    #  TD-H8 Gen 2
    _memory_format = """
    // Memory channels
    #seekto 0x0008;
    struct memory_obj memory[%(channels)i];
    // Settings
    #seekto 0x0ca8;
    struct settings_obj settings;
    // freq offset for vfo a & b
    #seekto 0x0cb8;
    struct offset_obj vfo_offsets[2];
    // FM broadcast channels
    #seekto 0x0cd8;
    struct fmb_obj fmb[%(fmb_channels)i];
    // channel names
    #seekto 0x0d48;
    struct name_obj names[%(channels)i];
    // channel used flags
    #seekto 0x1a08;
    struct {
      lbit used[%(channels)i];
    } channelflags;
    // scan add list
    #seekto 0x1a28;
    lbit scanadd[%(channels)i];
    // fmb vfo
    #seekto 0x1b38;
    struct fmb_obj fmbvfo;
    // vfo a & b
    #seekto 0x1b58;
    struct memory_obj vfo[2];
    // fmb used flags
    #seekto 0x1b78;
    struct {
      lbit used[32];
      } fmbflags;
    // power on message
    #seekto 0x1c08;
    struct poweron_msg_obj poweron_msg;
    // programmable buttons
    #seekto 0x1cc8;
    struct button_obj button;
    // id code
    #seekto 0x1e28;
    struct {
      u8 code[3];
    } id;
    // DTMF strings
    #seekto 0x1e38;
    struct dtmf_obj dtmf[%(dtmf_strings)i];
    // Group Code
    #seekto 0x1e31;
    struct {
        u8 code;
    } group;
    // PTT ID Code
    #seekto 0x1ec8;
    struct {
        struct dtmf_obj bot;
        struct dtmf_obj eot;
    } pttid;
    // Repeater ste & ttd
    #seekto 0x1f0a;
    struct {
      u8 ste; // repeater squelch tail elimination
      u8 ttd; // repeater tail tone delay
    } repeater;
    // mic gain
    #seekto 0x1f28;
    struct {
      u8 gain;
    } mic;
    // bluetooth
    #seekto 0x1f38;
    struct {
      u8 unused0:7,
        on:1;
    } bluetooth;
    """

    @classmethod
    def detect_from_serial(cls, pipe):
        rclass, _ = test_idents(cls, pipe)
        return rclass

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a beta version.\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.'
             )
        rp.pre_download = (dedent("""\
            1. Turn radio off.
            2. Connect cable to mic/spkr connector.
            3. Make sure connector is firmly connected.
            4. Turn radio on (volume may need to be set at 100%).
            5. Ensure that the radio is tuned to channel with no activity.
            6. Click OK to download image from device."""))
        rp.pre_upload = (dedent("""\
            1. Turn radio off.
            2. Connect cable to mic/spkr connector.
            3. Make sure connector is firmly connected.
            4. Turn radio on (volume may need to be set at 100%).
            5. Ensure that the radio is tuned to channel with no activity.
            6. Click OK to upload image to device."""))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.has_ctone = True
        rf.can_odd_split = True
        rf.valid_name_length = self._mem_params.get('name_len')
        rf.valid_characters = self._valid_chars
        rf.valid_skips = ['', 'S']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            'Tone->Tone',
            'DTCS->',
            '->DTCS',
            'Tone->DTCS',
            'DTCS->Tone',
            '->Tone',
            'DTCS->DTCS']
        rf.valid_power_levels = [x for x in self._tx_power if x]
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_modes = self._modes
        rf.valid_tuning_steps = self._steps

        rf.valid_bands = self._txbands + self._rxbands
        rf.valid_bands.sort()
        rf.memory_bounds = (1, self._mem_params.get('channels') - 1)
        rf.valid_special_chans = self._special_channels
        rf.has_sub_devices = True  # FM broadcast radio
        return rf

    def process_mmap(self):
        """Process the mem map into the mem object"""
        fmt = (self._mem_format + self._common_format +
               self._name_format + self._button_format +
               self._settings_format + self._memory_format +
               self._end_fromat) % self._mem_params
        self._memobj = bitwise.parse(fmt, self._mmap)

    def sync_in(self):
        """Download from radio"""
        try:
            self._mmap = _do_download(self)
            self.process_mmap()
        except Exception as e:
            raise errors.RadioError('Failed to communicate with radio: %s' % e)
        finally:
            _exit_programming_mode(self)

    def sync_out(self):
        """Upload to radio"""
        try:
            _do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError('Failed to communicate with radio: %s' % e)
        finally:
            _exit_programming_mode(self)

    def get_raw_memory(self, number):
        """Display raw channel and name data from the radio image"""
        if isinstance(number, str):
            _vfo_idx = self._special_channels.index(number)
            return repr(self._memobj.vfo[_vfo_idx]) + \
                        repr(self._memobj.vfo_offsets[_vfo_idx])
        else:
            return repr(self._memobj.memory[number]) + \
                        repr(self._memobj.names[number - 1]) + \
                            repr(self._memobj.scanadd[number - 1]) + \
                                repr(self._memobj.channelflags.\
                                    used[number - 1])

    def _decode_tone(self, val):
        """decode CTCSS/DTCS values from the radio image"""
        if val == 16665 or val == 0:
            return '', None, None
        elif val >= 12000:
            return 'DTCS', val - 12000, 'R'
        elif val >= 8000:
            return 'DTCS', val - 8000, 'N'
        else:
            return 'Tone', val / 10.0, None

    def _encode_tone(self, memval, mode, value, pol):
        """encode CTCSS/DTCS values into binary form the radio understands"""
        match mode:
            case '':
                memval[0].set_raw(0xff)
                memval[1].set_raw(0xff)
            case 'Tone':
                memval.set_value(int(value * 10))
            case 'DTCS':
                flag = 0x80 if pol == 'N' else 0xC0
                memval.set_value(value)
                memval[1].set_bits(flag)
            case _:
                raise Exception("Internal error: invalid mode `%s'" % mode)

    def _get_tx_bands(self):
        return self._txbands

    def get_memory(self, number):
        """Get the CHIRP mem representation from the radio image"""
        mem = chirp_common.Memory()
        _is_vfo = False

        if isinstance(number, int) and number < 0:
            number = self._special_channels[number + \
                                            len(self._special_channels)]
        if isinstance(number, str):
            _is_vfo = True
            mem.number = -len(self._special_channels) + \
                self._special_channels.index(number)
            mem.extd_number = number
            _mem = self._memobj.vfo[self._special_channels.index(number)]
        else:
            mem.number = number
            _mem = self._memobj.memory[number]
            _name = str(self._memobj.names[number -1].name)

        if _mem.get_raw()[:1] == b'\xff':
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        if mem.freq == 0:
            mem.empty = True
        # check if tx freq is blank
        if _mem.txfreq.get_raw() == b'\xff\xff\xff\xff':
            # TX freq is not set
            mem.offset = 0
            mem.duplex = 'off'
        else:
            # TX freq is set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if chirp_common.is_split(self.get_features().valid_bands,
                                         mem.freq, int(_mem.txfreq) * 10):
                    mem.duplex = 'split'
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = '-'
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = '+'
            else:
                mem.offset = 0

        # channel name
        if not _is_vfo:
            mem.name = _name.strip('\x00\xff').rstrip()
        else:
            mem.name = ''  # no name for VFO A or B

        # tone
        rxtone = self._decode_tone(int(_mem.rxtone))
        txtone = self._decode_tone(int(_mem.txtone))
        if txtone[0] == 'Tone' and not rxtone[0]:
            mem.tmode = 'Tone'
        elif txtone[0] == rxtone[0] and txtone[0] == 'Tone' \
                and mem.rtone == mem.ctone:
            mem.tmode = 'TSQL'
        elif txtone[0] == rxtone[0] and txtone[0] == 'DTCS' \
                and mem.dtcs == mem.rx_dtcs:
            mem.tmode = 'DTCS'
        elif rxtone[0] or txtone[0]:
            mem.tmode = 'Cross'
            mem.cross_mode = '%s->%s' % (txtone[0], rxtone[0])

        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # mode and wide/narrow
        # check to see if _mem struct has am per-channel?
        try:  # check to see if _mem struct has am per-channel?
            _am = _mem.am_modulation
        except AttributeError:
            _am = False

        if (chirp_common.in_range(mem.freq, self._airband) or _am) and \
            self._has_am:
            if _mem.narrow:
                mem.mode = 'NAM'
            else:
                mem.mode = 'AM'
        elif _mem.narrow:
            mem.mode = 'NFM'
        else:
            mem.mode = 'FM'

        # scanadd
        if not _is_vfo:
            mem.skip = '' if self._memobj.scanadd[mem.number - 1] else 'S'
        else:
            mem.skip = ''  # No Skip for VFO A or B

        # power
        try:
            mem.power = self._tx_power[_mem.power]
            if mem.power is None:
                raise IndexError()
        except IndexError:
            LOG.error('Channel %d: Radio reported invalid power '
                      'level %s (in %s)'
                      % (mem.number, _mem.power, self._tx_power))
            mem.power = self._tx_power[0]

        # mem.extra
        mem.extra = RadioSettingGroup('Extra', 'extra')
        # spec
        if self._has_spec:
            rs = RadioSettingValueBoolean(_mem.spec)
            mset = MemSetting('spec', 'Spec', rs)
            mset.set_doc('Set if Channel \'Spec\' is enabled.')
            mem.extra.append(mset)
        # ptt id
        if self._has_pttid:
            rs = RadioSettingValueList(self._pttid_list,
                                       current_index=_mem.pttid)
            mset = MemSetting('pttid', 'PTT ID', rs)
            mset.set_doc('Set when PTT-ID is to be sent during TX. '
                         'Valid values are: ' + \
                            ', '.join(x for x in self._pttid_list))
            mem.extra.append(mset)
        # busy lock
        if self._has_bcl:
            rs = RadioSettingValueBoolean(_mem.bcl)
            mset = MemSetting('bcl', 'Busy Lock', rs)
            mset.set_doc('Set if TX Busy Lock during RX is enabled.')
            mem.extra.append(mset)
        # hopping rx
        if self._has_freqhop:
            rs = RadioSettingValueBoolean(_mem.freqhop)
            mset = MemSetting('freqhop', 'Hopping RX', rs)
            mset.set_doc('Set if frequency hopping is enabled during TX.')
            mem.extra.append(mset)
        # scramble
        if self._has_scramble:
            rs = RadioSettingValueList(self._scramble_list,
                                       current_index=_mem.scramble)
            mset = MemSetting('scramble', 'Scramble', rs)
            mset.set_doc('Enable Scramble on this frequency. '
                         'All devices must be set to the same '
                            'code to interoperate. '
                                'Valid values are: ' + \
                                    ', '.join(x for x in self._scramble_list))
            mem.extra.append(mset)

        return mem

    def set_memory(self, mem):
        """move the CHIRP mem representation into the radio image"""
        _is_vfo = False
        if mem.number < 0:
            _is_vfo = True
            number = self._special_channels[mem.number]
            _special_channel_index = self._special_channels.index(number)
            _mem = self._memobj.vfo[_special_channel_index]
        else:
            _mem = self._memobj.memory[mem.number]
            _name = self._memobj.names[mem.number -1]
            _is_vfo = False

        if not _is_vfo:
            self._memobj.channelflags.used[mem.number - 1] = int(not mem.empty)

        if mem.empty:
            _mem.fill_raw(b'\xff')
            return

        _mem.fill_raw(b'\x00')

        # tx freq
        match mem.duplex:
            case '':
                _mem.rxfreq = _mem.txfreq = mem.freq / 10
            case 'split':
                _mem.txfreq = mem.offset / 10
            case '+':
                _mem.txfreq = (mem.freq + mem.offset) / 10
            case '-':
                _mem.txfreq = (mem.freq - mem.offset) / 10
            case 'off':
                _mem.txfreq.fill_raw(b'\xff')
            case _:
                _mem.txfreq = mem.freq / 10

        if chirp_common.in_range(mem.freq, self._rxbands) and \
                not chirp_common.in_range(mem.freq, self._get_tx_bands()):
            _mem.txfreq.fill_raw(b'\xff')

        # rx freq
        _mem.rxfreq = mem.freq / 10

        if _is_vfo:
            if mem.duplex == '':
                _offset = 0
            else:
                _offset = mem.offset / 10

            self._memobj.vfo_offsets[_special_channel_index].offset = _offset

        # offset direction
        if self._has_offsetdir:
            _offset_list = ['', '-', '+']  # None/OFF, Minus/Negitive, Plus/Positive
            _mem.offsetdir = _offset_list.index(mem.duplex)
            if mem.duplex == '':
                _mem.offsetdir = 0

        # name
        if not _is_vfo:
            _name_len = self._mem_params.get('name_len')
            _name.name = \
                mem.name[:_name_len].ljust(_name_len, '\x00')

        # tone
        txtone, rxtone = chirp_common.split_tone_encode(mem)

        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)

        # modulation
        if self._has_am_per_channel and mem.mode in ['AM', 'NAM']:
            _mem.am_modulation = 0b1  # AM
        elif self._has_am_per_channel:
            _mem.am_modulation = 0b0  # FM

        # bandwidth
        if mem.mode in ['AM', 'FM']:
            _mem.narrow = 0b0  # wide
        else:
            _mem.narrow = 0b1  # narrow

        # scanadd
        if not _is_vfo:
            self._memobj.scanadd[mem.number - 1] = mem.skip != 'S'

        # power
        try:
            _mem.power = self._tx_power.index(mem.power or
                                                 self._tx_power[-1])
        except ValueError:
            _mem.power = 0
            LOG.warning('Unsupported power value %r', mem.power)

        # mem.extra
        for setting in mem.extra:
            setting.apply_to_memobj(_mem)

    def decode_dtmf(self, val, len_byte=False):
        """decode the binary coded DTMF value into a DTMF string"""
        dtmf = ''
        if len_byte:

            if all(x == 0xff for x in val):
                return ' ' * (len(val) - 1)

            for i in range(0, val[-1]):
                try:
                    dtmf += self._dtmf_code_dict.get(int(val[i]))
                except (ValueError, IndexError):
                    dtmf = ''
        else:
            for i in range(0, len(val)):
                if val[i] == 0xff:
                    break
                try:
                    dtmf += self._dtmf_code_dict.get(int(val[i]))
                except (ValueError, IndexError):
                    dtmf = ''
        return dtmf

    def encode_dtmf(self, val, len_byte=True, terminated=False):
        """encode the DTMF string into the binary value the radio expects"""
        _dtmf_list = [0xff] * len(val)
        x = 0
        for i in range(0, len(val)):
            _dtmf_list[i] = self._inverted_dtmf_code_dict.get(val[i])
            if _dtmf_list[i] != 0xff:
                x += 1
            else:
                break

        if len_byte:
            _dtmf_list.append(x)

        if terminated:
            _dtmf_list.append(0xff)

        return _dtmf_list

    def apply_dtmf_code(self, setting, obj, len_byte=True, terminated=False):
        obj.set_value(self.encode_dtmf(setting.value, len_byte, terminated))

    def get_settings_basic(self, basic_settings, settings_mem):
        """Basic Radio Settings Items"""
        # squelch
        rs = RadioSettingValueList(self._squelch_list,
                                   current_index=settings_mem.squelch)
        mset = MemSetting('settings.squelch', 'Squelch Level', rs)
        mset.set_doc('Set the radio squelch Level.')
        basic_settings.append(mset)
        # voice prompt
        rs = RadioSettingValueBoolean(settings_mem.voiceprompt)
        mset = MemSetting('settings.voiceprompt', 'Voice Prompt', rs)
        mset.set_doc('Set if radio button presses and menu items '
                     'are voice announced.')
        basic_settings.append(mset)
        # auto lock
        rs = RadioSettingValueBoolean(settings_mem.keyautolock)
        mset = MemSetting('settings.keyautolock', 'Keypad Lock', rs)
        mset.set_doc('Set to have radio keypad automatically locked '
                     'after a certian amount of time.')
        basic_settings.append(mset)
        # pri tx
        if self._has_pritx:
            rs = RadioSettingValueList(self._pritx_list,
                                    current_index=settings_mem.pritx)
            mset = MemSetting('settings.pritx', 'Priority TX', rs)
            mset.set_doc('Set the radio priority TX mode. '
                         'MAIN TXs on the current channel, '
                         'Busy TXs on the channel that had the last RX.')
            basic_settings.append(mset)
        # key beep
        rs = RadioSettingValueBoolean(settings_mem.beep)
        mset = MemSetting('settings.beep', 'Beep', rs)
        mset.set_doc('Set to have radio keypad beep with each key press.')
        basic_settings.append(mset)
        # vox gain
        rs = RadioSettingValueList(self._voxgain_list,
                                   current_index=settings_mem.voxgain)
        mset = MemSetting('settings.voxgain', 'VOX Gain', rs)
        mset.set_doc('Set the VOX gain level.')
        basic_settings.append(mset)
        # vox delay
        rs = RadioSettingValueList(self._voxdelay_list,
                                   current_index=settings_mem.voxdelay)
        mset = MemSetting('settings.voxdelay', 'VOX Delay', rs)
        mset.set_doc('Set the VOX delay time.')
        basic_settings.append(mset)
        # LED disp TX
        rs = RadioSettingValueBoolean(settings_mem.txled)
        mset = MemSetting('settings.txled', 'Screen Display-TX', rs)
        mset.set_doc('Set to have radio screen backlight display when '\
                     'TX is active.')
        basic_settings.append(mset)
        # LED disp RX
        rs = RadioSettingValueBoolean(settings_mem.rxled)
        mset = MemSetting('settings.rxled', 'Screen Display-RX', rs)
        mset.set_doc('Set to have radio screen backlight display when '\
                     'RX is active.')
        basic_settings.append(mset)
        # backlight control
        rs = RadioSettingValueList(self._backlight_list,
                                   current_index=settings_mem.ligcon)
        mset = MemSetting('settings.ligcon', 'Backlight Timer', rs)
        mset.set_doc('Set the how long the backlight stays on(s).')
        basic_settings.append(mset)
        # time-out-timer TOT
        rs = RadioSettingValueList(self._tot_list,
                                   current_index=settings_mem.tot)
        mset = MemSetting('settings.tot', 'Time-Out Timer', rs)
        mset.set_doc('Set the amount of time that TX can be continuous '\
                     'before timing out(s).')
        basic_settings.append(mset)
        # roger beep
        self.get_settings_roger(basic_settings, settings_mem)
        # language
        _lang_mem = self._memobj.menu.lang if hasattr(self._memobj, 'menu') \
            else self._memobj.settings.lang
        _lang_path = 'menu.lang' if hasattr(self._memobj, 'menu') \
            else 'settings.lang'
        rs = RadioSettingValueMap(self._lang_map, _lang_mem)
        mset = MemSetting(_lang_path, 'Language', rs)
        mset.set_doc('Set the radio language.')
        basic_settings.append(mset)

    def get_settings_fmb(self, fm_settings, settings_mem):
        """FM Broadcast Radio Settings"""
        # FM work mode
        rs = RadioSettingValueList(self._fmworkmode_list,
                                   current_index=settings_mem.fmworkmode)
        mset = MemSetting('settings.fmworkmode', 'FM Workmode', rs)
        mset.set_doc('Set the FM broadcast workmode.')
        fm_settings.append(mset)
        # default FM channel
        rs = RadioSettingValueMap(self._fmchannels_map, settings_mem.fmdefch)
        mset = MemSetting('settings.fmdefch', 'Default Channel', rs)
        mset.set_doc('Set the default FM broadcast channel '
                     'for \'CH\' workmode.')
        fm_settings.append(mset)
        # FM interrupt
        rs = RadioSettingValueBoolean(settings_mem.fmrec)
        mset = MemSetting('settings.fmrec', self._fmrec_shortname, rs)
        mset.set_doc('Set to allow radio RX to interrupt FM broadcast RX.')
        fm_settings.append(mset)

    def get_settings_scan(self, scan_settings,settings_mem):
        """Scan Settings Items"""
        if self._has_freq_ranger:
            _menu = self._memobj.menu
        # Scan mode
        rs = RadioSettingValueList(self._scanmode_list,
                                   current_index=settings_mem.scanmode)
        mset = MemSetting('settings.scanmode', 'Scan Mode', rs)
        mset.set_doc('Set the scan resume mode.')
        scan_settings.append(mset)
        # Scan hangtime
        if self._has_scan_hangtime:
            rs = RadioSettingValueList(self._hangtime_list,
                                    current_index=_menu.hangtime)
            mset = MemSetting('menu.hangtime', 'Scan Hang Time', rs)
            mset.set_doc('Set the scan resume mode timeout value(s).')
            scan_settings.append(mset)
        # Freq ranger
        if self._has_freq_ranger:
            # Freq ranger high
            rs = RadioSettingValueInteger(0, 999, _menu.ranger_high)
            mset = MemSetting('menu.ranger_high', 'Freq Ranger Upper Limit', rs)
            mset.set_doc('Set the VFO scan frequency ranger upper '
                         'limit value(MHz).')
            scan_settings.append(mset)
            # Freq ranger low
            rs = RadioSettingValueInteger(0, 999, _menu.ranger_low)
            mset = MemSetting('menu.ranger_low', 'Freq Ranger Lower Limit', rs)
            mset.set_doc('Set the VFO scan frequency ranger lower '
                         'limit value(Mhz).')
            scan_settings.append(mset)

    def get_settings_dtmf(self, dtmf_settings, dtmf_mem):
        """DTMF Settings Items"""
        _settingsobj = self._memobj.settings

        # Group Code
        _groupobj = self._memobj.group
        rs = RadioSettingValueMap(self._groupcode_map, _groupobj.code)
        mset = MemSetting('group.code', 'Group Code', rs)
        mset.set_doc('Set the radio DTMF Group Code.')
        dtmf_settings.append(mset)
        # ID Code
        _codeobj = self._memobj.id.code
        _code = self.decode_dtmf(_codeobj)
        rs = RadioSettingValueString(0, 3, _code)
        rs.set_charset(DTMF_CHARS)
        rset = RadioSetting('id.code', 'ID Code', rs)
        rset.set_apply_callback(self.apply_dtmf_code,
                                _codeobj, False)
        rset.set_doc('Set the radio DTMF ID Code.')
        dtmf_settings.append(rset)
        if self._has_stored_dtmf:
            # Stored DTMF Codes
            for i in range(0, self._mem_params.get('dtmf_strings')):
                _codeobj = dtmf_mem[i].code
                _code = self.decode_dtmf(_codeobj, self._has_dtmf_len)
                rs = RadioSettingValueString(0,
                                            self._mem_params.get('dtmf_len') - 1,
                                            _code, True)
                rs.set_charset(DTMF_CHARS)
                rset = RadioSetting('dtmf.%i.code' % i,
                                    'DTMF-%i' % (i + 1), rs)
                rset.set_apply_callback(self.apply_dtmf_code,
                                        _codeobj, self._has_dtmf_len,
                                        self._has_dtmf_terminated)
                rset.set_doc('Set the code sequence for stored DTMF-%i '
                            'sequence.' % (i + 1))
                dtmf_settings.append(rset)
        # PTT-ID BOT
        _codeobj = self._memobj.pttid.bot.code
        _code = self.decode_dtmf(_codeobj, True)
        rs = RadioSettingValueString(0, self._mem_params.get('dtmf_len') - 1,
                                     _code, True)
        rs.set_charset(DTMF_CHARS)
        rset = RadioSetting('pttid.bot.code',
                            'PTT ID BOT', rs)
        rset.set_apply_callback(self.apply_dtmf_code,
                                _codeobj, True)
        rset.set_doc('Set the DTMF sequence for the \'BOT\' PTT ID Code.')
        dtmf_settings.append(rset)
        # PTT-ID EOT
        _codeobj = self._memobj.pttid.eot.code
        _code = self.decode_dtmf(_codeobj, True)
        rs = RadioSettingValueString(0, self._mem_params.get('dtmf_len') - 1,
                                     _code, True)
        rs.set_charset(DTMF_CHARS)
        rset = RadioSetting('pttid.eot.code',
                            'PTT ID EOT', rs)
        rset.set_apply_callback(self.apply_dtmf_code,
                                _codeobj, True)
        rset.set_doc('Set the DTMF sequence for the \'EOT\' PTT ID Code.')
        dtmf_settings.append(rset)
        # Stun code
        if self._has_stuncode:
            _codeobj = self._memobj.remote.stun.code
            _code = _code = self.decode_dtmf(_codeobj, True)
            rs = RadioSettingValueString(0,
                                         self._mem_params.get('dtmf_len') - 1,
                                         _code, True)
            rs.set_charset(DTMF_CHARS)
            rset = RadioSetting('remote.stun.code',
                                'Stun Code', rs)
            rset.set_apply_callback(self.apply_dtmf_code,
                                    _codeobj, True)
            rset.set_doc('Set the DTMF sequence for the remote radio '\
                         '\'stun\' function.')
            dtmf_settings.append(rset)
        # Kill code
        if self._has_killcode:
            _codeobj = self._memobj.remote.kill.code
            _code = _code = self.decode_dtmf(_codeobj, True)
            rs = RadioSettingValueString(0,
                                         self._mem_params.get('dtmf_len') - 1,
                                         _code, True)
            rs.set_charset(DTMF_CHARS)
            rset = RadioSetting('remote.kill.code',
                                'Kill Code', rs)
            rset.set_apply_callback(self.apply_dtmf_code,
                                    _codeobj, True)
            rset.set_doc('Set the DTMF sequence for the remote radio '
                         '\'kill\' function.')
            dtmf_settings.append(rset)
        # DTMF side tones
        rs =  RadioSettingValueBoolean(_settingsobj.dtmfst)
        mset = MemSetting('settings.dtmfst', 'DTMF Side Tones', rs)
        mset.set_doc('Set to make DTMF side tones audible.')
        dtmf_settings.append(mset)
        # extra DTMF setttigs
        if self._has_dtmf_extra:
            # DTMF decode
            rs =  RadioSettingValueBoolean(_settingsobj.dtmfdecode)
            mset = MemSetting('settings.dtmfdecode', 'DTMF Decode', rs)
            mset.set_doc('Set to decode DTMF tones.')
            dtmf_settings.append(mset)
            # DTMF reset timer
            rs = RadioSettingValueList(self._dtmf_reset_list,
                                       current_index=_settingsobj.dtmfautorst)
            mset = MemSetting('settings.dtmfautorst', 'DTMF Reset Time', rs)
            mset.set_doc('Set the DTMF auto reset timer value(s).')
            dtmf_settings.append(mset)
            # DTMF decoding response
            rs = RadioSettingValueList(self._dtmf_resp_list,
                                       current_index=\
                                        _settingsobj.dtmfdecoderesp)
            mset = MemSetting('settings.dtmfdecoderesp',
                              'DTMF Decoding Response', rs)
            mset.set_doc('Set the response when a DTMF sequence is decoded.')
            dtmf_settings.append(mset)
            # DTMF speed
            rs = RadioSettingValueList(self._dtmf_speed_list,
                                       current_index=_settingsobj.dtmfspeed)
            mset = MemSetting('settings.dtmfspeed', 'DTMF Speed', rs)
            mset.set_doc('Set the time duration each DTMF '
                         'character of a sequence is transmitted(ms).')
            dtmf_settings.append(mset)

    def get_settings_bluetooth(self, bt_settings, bt_mem):
        """bluetooth radio settings"""
        # bluetooth on/off
        rs = RadioSettingValueBoolean(bt_mem.on)
        mset = MemSetting('bluetooth.on', 'Bluetooth Serial', rs)
        mset.set_doc('Set the Bluetooth Serial (BLE) connectivity On/Off.')
        bt_settings.append(mset)

    def get_settings_button(self, btn_settings, btn_mem):
        """programable button settings"""
        # pf1
        # short press
        rs = RadioSettingValueList(self._short_press_list,
                                    current_index=btn_mem.ssidekey1)
        mset = MemSetting('button.ssidekey1', 'PF1 - Short Press', rs)
        mset.set_doc('Select the action when the PF1 button is Short pressed.')
        btn_settings.append(mset)
       # long press
        rs = RadioSettingValueList(self._long_press_list,
                                    current_index=btn_mem.lsidekey1)
        mset = MemSetting('button.lsidekey1', 'PF1 - Long Press', rs)
        mset.set_doc('Select the action when the PF1 button is Long pressed.')
        btn_settings.append(mset)
        # pf2
        if self._has_pf2_button:
            # short press
            rs = RadioSettingValueList(self._short_press_list,
                                        current_index=btn_mem.ssidekey2)
            mset = MemSetting('button.ssidekey2', 'PF2 - Short Press', rs)
            mset.set_doc('Select the action when the PF2 button '
                         'is Short pressed.')
            btn_settings.append(mset)
            # long press
            rs = RadioSettingValueList(self._long_press_list,
                                        current_index=btn_mem.lsidekey2)
            mset = MemSetting('button.lsidekey2', 'PF2 - Long Press', rs)
            mset.set_doc('Select the action when the PF2 button '
                         'is Long pressed.')
            btn_settings.append(mset)
        # top
        if self._has_top_button:
            # short press
            rs = RadioSettingValueList(self._short_press_list,
                                       current_index=btn_mem.stopkey1)
            mset = MemSetting('button.stopkey1', 'Top Button - Short Press', rs)
            mset.set_doc('Select the action when the Top button is Short pressed.')
            btn_settings.append(mset)
            # long press
            rs = RadioSettingValueList(self._long_press_list,
                                       current_index=btn_mem.ltopkey1)
            mset = MemSetting('button.ltopkey1', 'Top Button - Long Press', rs)
            mset.set_doc('Select the action when the Top button is Long pressed.')
            btn_settings.append(mset)

    def get_settings_ab(self, ab_settings, settings_mem):
        """A/B Channel Settings"""
        # vfo a sub menu
        achan = RadioSettingSubGroup('achan', 'VFO A Channel')
        ab_settings.append(achan)
        # a work mode
        rs = RadioSettingValueList(self._vfo_workmode_list,
                                   current_index=settings_mem.aworkmode)
        mset = MemSetting('settings.aworkmode', 'Work Mode', rs)
        mset.set_doc('Set the VFO A channel Work Mode.')
        achan.append(mset)
        # a tuning step
        rs = RadioSettingValueList(self._step_list,
                                   current_index=settings_mem.astep)
        mset = MemSetting('settings.astep', 'Tuning Step', rs)
        mset.set_doc('Set the VFO A Tuning Step.')
        achan.append(mset)
        # a def channel
        if self._has_def_chan:
            rs = RadioSettingValueInteger(1,
                                          self._mem_params.get('channels') - 1,
                                        settings_mem.adefchan)
            mset = MemSetting('settings.adefchan', 'Default Channel', rs)
            mset.set_doc('Set the default A Channel Number.')
            achan.append(mset)
        # vfo b sub menu
        bchan = RadioSettingSubGroup('bchan', 'VFO B Channel')
        ab_settings.append(bchan)
        # b work mode
        rs = RadioSettingValueList(self._vfo_workmode_list,
                                   current_index=settings_mem.bworkmode)
        mset = MemSetting('settings.bworkmode', 'Work Mode', rs)
        mset.set_doc('Set the VFO B channel Work Mode.')
        bchan.append(mset)
        # b tuning step
        rs = RadioSettingValueList(self._step_list,
                                   current_index=settings_mem.bstep)
        mset = MemSetting('settings.bstep', 'Tuning Step', rs)
        mset.set_doc('Set the VFO B Tuning Step.')
        bchan.append(mset)
        # b def channel
        if self._has_def_chan:
            rs = RadioSettingValueInteger(1,
                                          self._mem_params.get('channels') - 1,
                                        settings_mem.bdefchan)
            mset = MemSetting('settings.bdefchan', 'Default Channel', rs)
            mset.set_doc('Set the default B Channel Number.')
            bchan.append(mset)

    def get_settings_roger(self, roger_settings, settings_mem):
        """Roger Beep Settings"""
        # roger beep
        rs = RadioSettingValueBoolean(settings_mem.rogerprompt)
        mset = MemSetting('settings.rogerprompt', 'Roger Beep', rs)
        mset.set_doc('Set to have a roger beep sound at the end of TX.')
        roger_settings.append(mset)

    def get_settings_spec(self, spec_settings, settings_mem):
        # radio operating mode
        self._ham = self._memobj.settings.mode == 2
        self._gmrs = self._memobj.settings.mode == 1
        rs = RadioSettingValueList(self._operating_mode_list,
                                   current_index=settings_mem.mode)
        mset = MemSetting('settings.mode', 'Operating Mode', rs)
        mset.set_doc('Set the Operating Mode of the radio. Operating '
            'Modes include HAM, GMRS or NORMAL (unlocked). Each mode has '
            'different frequency ranges and capibilities.')
        mset.set_warning(_(
            'This should only be used to change the operating MODE of your '
            'radio if you understand the legalities and implications of '
            'doing so. The change may enable the radio to transmit on '
            'frequencies it is not Type Accepted to do and my be in '
            'violation of FCC and other governing agency regulations.\n\n'
            'It may make your saved image files incompatible with the radio '
            'and non-usable until you change the radio MODE back to the '
            'MODE in effect when the image file was saved. After the '
            'changed image is uploaded, the radio may have to turned OFF '
            'and back ON to have the MODE changes take full effect.\n'
            'DO NOT attempt to edit any settings until uploading to and '
            'downloading from the radio with the new operating MODE.'))
        spec_settings.append(mset)
        # Bluetooth settings
        if self._has_bluetooth:
            self.get_settings_bluetooth(spec_settings, self._memobj.bluetooth)
        # dual watch mode
        rs = RadioSettingValueInvertedBoolean(not settings_mem.dualwatch)
        mset = MemSetting('settings.dualwatch', 'Dual Watch', rs)
        mset.set_doc('Set to put the radio in dual watch (aka \'SYNC\') mode.')
        spec_settings.append(mset)
        # mic gain
        rs = RadioSettingValueList(self._micgain_list,
                                   current_index=self._memobj.mic.gain)
        mset = MemSetting('mic.gain', 'Mic Gain', rs)
        mset.set_doc('Set the microphone gain level.')
        spec_settings.append(mset)
        # brightness
        if self._has_brightness:
            if settings_mem.brightness not in range(0, 5):
                LOG.warning(
                    'brightness out of range 1 to 5. Actual value: 0x%x. '
                    'Screen may not be visible',
                    settings_mem.brightness)
            rs = RadioSettingValueMap(self._brightness_map, settings_mem.brightness)
            mset = MemSetting('settings.brightness', 'Brightness', rs)
            mset.set_doc('Set the radio display brightness.')
            spec_settings.append(mset)
        # breath LED
        rs = RadioSettingValueList(self._breath_led_list,
                                    current_index=settings_mem.breathled)
        mset = MemSetting('settings.breathled', 'Breath LED', rs)
        mset.set_doc('Set the Breath LED timing behavior.')
        spec_settings.append(mset)
        # poweron message
        rs = RadioSettingValueList(self._ponmsg_list,
                                   current_index=settings_mem.ponmsg)
        mset = MemSetting('settings.ponmsg', 'Power-On Message', rs)
        mset.set_doc('Set what type of power-on message will be displayed.')
        spec_settings.append(mset)
        # power-on message text
        self.get_settings_pom(spec_settings, self._memobj.poweron_msg)
        # kill/stun
        if self._has_killcode:
            rs = RadioSettingValueBoolean(settings_mem.kill)
            mset = MemSetting('settings.kill', 'Kill', rs)
            mset.set_doc('Clear to remove the radio from the \'Kill\' State.')
            spec_settings.append(mset)
        if self._has_stuncode:
            rs = RadioSettingValueBoolean(settings_mem.stun)
            mset = MemSetting('settings.stun', 'Stun', rs)
            mset.set_doc('Clear to remove the radio from the \'Stun\' State.')
            spec_settings.append(mset)
        # Button settings
        self.get_settings_button(spec_settings, self._memobj.button)
        # DTMF Settings
        if self._has_dtmf:
            _dtmf_mem = self._memobj.dtmf
            dtmf = RadioSettingGroup('dtmf', 'DTMF')
            self.get_settings_dtmf(dtmf, _dtmf_mem)
            spec_settings.append(dtmf)
        # A/B Chan
        abchan = RadioSettingGroup('abchan', 'VFO A/B Channel')
        self.get_settings_ab(abchan,  settings_mem)
        spec_settings.append(abchan)
        # FM broadcast Settings
        fmb = RadioSettingGroup('fmb', 'FM Broadcast')
        self.get_settings_fmb(fmb, settings_mem)
        spec_settings.append(fmb)

    def _filter(self, name):  # remove invalid padding chars from the name string
        s = ''
        for c in str(name):
            if c in TDH8._valid_chars:
                s += c
            else:
                s += ' '
        return s

    def get_settings_pom(self, pom_settings, pom_mem):
        """Power-On Message Text Settings"""
        # power-on message text
        # msg 1
        rs = RadioSettingValueString(0, 16,
                                     self._filter(pom_mem.msg1))
        mset = MemSetting('poweron_msg.msg1', 'Power-On Message 1', rs)
        mset.set_doc('Set the radio power-on message text for Line 1.')
        pom_settings.append(mset)
        # msg 2
        rs = RadioSettingValueString(0, 16,
                                     self._filter(pom_mem.msg2))
        mset = MemSetting('poweron_msg.msg2', 'Power-On Message 2', rs)
        mset.set_doc('Set the radio power-on message text for Line 2.')
        pom_settings.append(mset)
        # msg 3
        rs = RadioSettingValueString(0, 16,
                                     self._filter(pom_mem.msg3))
        mset = MemSetting('poweron_msg.msg3', 'Power-On Message 3', rs)
        mset.set_doc('Set the radio power-on message text for Line 3.')
        pom_settings.append(mset)

    def get_settings(self):
        _settings_mem = self._memobj.settings

        supported = []
        # Basic Settings
        basic = RadioSettingGroup('basic', 'Basic Settings')
        self.get_settings_basic(basic, _settings_mem)
        supported.append(basic)
        # Scan Settings
        scan = RadioSettingGroup('scan', 'Scan')
        self.get_settings_scan(scan, _settings_mem)
        supported.append(scan)
        # model specfic
        spec = RadioSettingGroup('spec', self.MODEL + ' ' + self.VARIANT +
                                 ' Specific')
        self.get_settings_spec(spec, _settings_mem)
        supported.append(spec)

        return RadioSettings(*tuple(supported))

    def set_settings(self, settings):
        # apply all Memsettings
        all_other_settings = settings.apply_to(self._memobj)
        for setting in all_other_settings:
            if setting.has_apply_callback():
                # use callbacks on Radiosettings that need postprocessing
                setting.run_apply_callback()

    def get_sub_devices(self):
        return[TDH8VhfUhf(self._mmap),
               TDH8FM(self._mmap),
               ]


class TDH8VhfUhf(TDH8):
    """TIDRADIO TD-H8 VHF/UHF subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8'
    VARIANT = 'VHF/UHF'


class TDH8FM(TDH8):
    """TIDRADIO TD-H8 FM broadcast radio subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8'
    VARIANT = 'FM Broadcast'

    _mem_params = TDH8._mem_params

    _fmband =  [(76000000, 108000000)]  # in Mhz, 76.0-108.0 MHz
    _special_channels = ['VFO']

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_bands = self._fmband
        rf.memory_bounds = (1, self._mem_params.get('fmb_channels'))
        rf.can_delete = True
        rf.can_odd_split = False
        rf.has_bank = False
        rf.has_bank_index = False
        rf.has_bank_names = False
        rf.has_comment = False
        rf.has_cross = False
        rf.has_ctone = False
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_mode = True
        rf.has_offset = False
        rf.has_settings = False
        rf.has_sub_devices = False
        rf.has_tuning_step = False
        rf.valid_characters = TDH8._valid_chars
        rf.valid_cross_modes = []
        rf.valid_dtcs_codes = []
        rf.valid_dtcs_pols = []
        rf.valid_duplexes = []
        rf.valid_modes = ['WFM']  #  FM broadcast only
        rf.has_name = False
        rf.valid_name_length = 0
        rf.valid_skips = []
        rf.valid_special_chans = self._special_channels
        rf.valid_tuning_steps = [5.0]
        rf.valid_tmodes = []
        rf.valid_tones = []
        return rf

    def get_raw_memory(self, number):
        if isinstance(number, str):
            return repr(self._memobj.fmbvfo.rxfreq)
        else:
            return repr(self._memobj.fmb[number - 1])

    def get_memory(self, number):
        mem = chirp_common.Memory()

        if isinstance(number, int) and number < 0:
            number = self._special_channels[number + \
                                            len(self._special_channels)]
        if isinstance(number, str):
            mem.number = -len(self._special_channels) + \
                self._special_channels.index(number)
            mem.offset = 0
            mem.extd_number = number
            _mem = self._memobj.fmbvfo
        else:
            mem.number = number
            _mem = self._memobj.fmb[number - 1]

        if _mem.get_raw()[:1] == b'\xff':
            mem.empty = True
            return mem

        freq = int(_mem.rxfreq) * 100000

        if freq == 0:
            mem.empty = True

        mem.freq = freq
        mem.mode = 'WFM'
        mem.immutable += ['mode']

        return mem

    def set_memory(self, mem):
        if mem.number < 0:
            _mem = self._memobj.fmbvfo
        else:
            _mem = self._memobj.fmb[mem.number - 1]

            _fm_flag = self._memobj.fmbflags.used[mem.number - 1]
            if mem.freq > 0 or not mem.empty:
                _fm_flag.set_value(0b1)  # set the FMB used flag
            else:
                _fm_flag.set_value(0b0)  # clear the FMB used flag

        if mem.empty:
            _mem.rxfreq = 0
            return

        _mem.rxfreq = int(mem.freq / 100000)

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        return msgs


@directory.register
@directory.detected_by(TDH8)
class TDH8_HAM(TDH8):
    """TIDRADIO TD-H8 HAM"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8-HAM'
    ident_mode = b'P31185\xff\xff'
    _ham = True
    _gmrs = False
    _txbands = [(144000000, 149000000), (420000000, 451000000)]
    _rxbands = [(136000000, 143999000), (149000001, 174000000),
                (400000000, 419999000), (451000001, 521000000)]
    _tx220 = [(222000000, 225000000)]
    # leave out 219-220 sub-band because this radio doesn't do
    # fixed digital message forwarding
    # tx350 and tx500 bands unknown; add them if you are in a
    # legal locale and know their correct range

    def get_tx_bands(self):
        _settings = self._memobj.settings
        bands = []
        bands.extend(self._txbands)
        if _settings.tx220:
            bands.extend(self._tx220)
        return bands


@directory.register
@directory.detected_by(TDH8)
class TDH8_GMRS(TDH8):
    """TIDRADIO TD-H8 GMRS"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8-GMRS'
    ident_mode = b'P31184\xff\xff'
    _gmrs = True
    _ham = False
    _txbands = [(136000000, 175000000), (400000000, 521000000)]
    _tx_power = [chirp_common.PowerLevel('Low', watts=1.00),
                chirp_common.PowerLevel('Mid', watts=4.00),
                chirp_common.PowerLevel('High', watts=8.00),
                ]

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        msgs.extend(validate_gmrs_memory(mem))
        return msgs


@directory.register
class UV68(TDH8):
    VENDOR = 'TID'
    MODEL = 'TD-UV68'


@directory.register
class TDH3(TDH8):
    """TIDRADIO H-3 Normal"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3'
    ident_mode = b'P31183\xff\xff'
    _idents = [TD_H3]
    _gmrs = False
    _ham = False
    _memsize = 0x1fef
    _ranges_main = [(0x0000, _memsize)]
    _mmap = bytearray(_memsize)
    _mem_params = {
        'channels': 200,
        'fmb_channels': 25,
        'dtmf_strings': 8,
        'dtmf_len': 16,
        'name_len': 8,
    }
    _txbands = [(136000000, 600000000)]
    _airband = [(108000000, 135999999)]
    _rxbands = [(18000000, 107999000)] + _airband
    _modes = ['FM', 'NFM', 'AM', 'NAM']  # 25 kHz,12.5kHz, AM, NAM.
    _has_am = True
    _has_am_per_channel = False
    _has_scramble = True
    _has_pttid = True
    _has_bcl = True
    _has_freqhop = True
    _has_stored_dtmf = True
    _has_dtmf_len = True
    _has_dtmf_terminated = not _has_dtmf_len
    _has_stuncode = True
    _has_killcode = True
    _has_dtmf_extra = True
    _has_pf2_button = False
    _has_top_button = False
    _has_brightness = True

    _tx_power = [chirp_common.PowerLevel('Low', watts=2.00),
                 chirp_common.PowerLevel('High', watts=5.00),
                 ]
    _lang_map = [('Chinese', 0), ('English', 1)]
    _brightness_map = [("1", 4), ("2", 3), ("3", 2), ("4", 1), ("5", 0)]

    _steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 8.33]
    _step_list = ['%2.2fK' % x for x in _steps]
    _scramble_list = ['Off'] + ['%02d' % x for x in range(1, 17)]
    _short_press_list =  ['None', 'FM Radio', 'Lamp', 'Monitor',
                          'TONE', 'Alarm', 'Weather',
                          ]
    _long_press_list = _short_press_list
    _micgain_list = ['%02d' % x for x in range(0, 10)]
    _roger_list = ['Off', 'TONE1', 'TONE2']

    _name_format = """
    // channel name
    struct name_obj {
      char name[%(name_len)i];
    };

    // dtmf string
    struct dtmf_obj {
      u8 code[%(dtmf_len)i];
    };
    """

    _settings_format = """
    struct settings_obj {
      u8 unknown21:7,
        dtmfdecode:1;
      u8 unknown22:6,
        dtmfautorst:2;
      u8 unknown23:6,
        dtmfdecoderesp:2;
      u8 unknown24:5,
        dtmfspeed:3;
      u8 unknown25:4,
        scanband:4;
      u8 brightness:8;
      u8 unknown27:8;
      u8 unknown28:8;
      u8 txled:1,
        rxled:1,
        unused11:1,
        mode:2, // Radio op mode: 0=Normal, 1=GMRS, 2=HAM, 3=unused
        //ham:1,
        //gmrs:1,
        unused14:1,
        dtmfst:1,
        pritx:1;
      u8 scanmode:2,
        unused16:1,
        keyautolock:1,
        unused17:1,
        beep:1,
        unknown18:1,
        voiceprompt:1;
      u8 fmworkmode:1,
        dualwatch:1,
        tonevoice:2,
        fmrec:1,
        mdfa:1,
        aworkmode:2;
      u8 ponmsg:2,
        unused19:1,
        mdfb:1,
        unused20:1,
        dbrx:1,
        bworkmode:2;
      u8 adefchan;
      u8 bdefchan;
      u8 fmdefch;
      u8 unused21:1,
        tailclean:1,
        rogerprompt_:1,
        kill:1,
        stun:1,
        voxgain:3;
      u8 astep:4,
        bstep:4;
      u8 squelch;
      u8 tot;
      u8 rogerprompt:2,
        unused11_4:1,
        tx220:1,
        tx350:1,
        tx500:1,
        lang:1,
        unused11_1:1;
      u8 save;
      u8 ligcon;
      u8 voxdelay;
      u8 onlychmode:1,
        breathled:3,
        unused:2,
        amband:1,
        alarm:1;
    };
    """

    _end_fromat = """
    // bluetooth
    #seekto 0x1f38;
    struct {
      u8 unused0:7,
        on:1;
    } bluetooth;
    """

    #  TD-H3, H3 Plus, H9 & H8 Gen 3 & 4
    _memory_format = """
    // Memory channels
    #seekto 0x0008;
    struct memory_obj memory[%(channels)i];
    // programmable buttons
    #seekto 0x0c98;
    struct button_obj button;
    // Settings
    #seekto 0x0ca0;
    struct settings_obj settings;
    // freq offset for vfo a & b
    #seekto 0x0cb8;
    struct offset_obj vfo_offsets[2];
    // FM broadcast channels
    #seekto 0x0cd8;
    struct fmb_obj fmb[%(fmb_channels)i];
    // channel names
    #seekto 0x0d48;
    struct name_obj names[%(channels)i];
    // Remote Stun & Kill Codes
    #seekto 0x1808;
    struct {
      struct dtmf_obj stun;
      struct dtmf_obj kill;
    } remote;
    // id code
    #seekto 0x1828;
    struct {
      u8 code[3];
    } id;
    // Group Code
    #seekto 0x1831;
    struct {
      u8 code;
    } group;
    // DTMF strings
    #seekto 0x1838;
    struct dtmf_obj dtmf[%(dtmf_strings)i];
    // PTT ID Code
    #seekto 0x18c8;
    struct {
      struct dtmf_obj bot;
      struct dtmf_obj eot;
    } pttid;
    // channel used flags
    #seekto 0x1908;
    struct {
      lbit used[%(channels)i];
    } channelflags;
    // scanadd
    #seekto 0x1928;
    lbit scanadd[%(channels)i];
    // fmb used flags
    #seekto 0x1948;
    struct {
      lbit used[32];
      } fmbflags;
    // vfo a & b
    #seekto 0x1958;
    struct memory_obj vfo[2];
    // fmb vfo
    #seekto 0x1978;
    struct fmb_obj fmbvfo;
    // power on message
    #seekto 0x1c08;
    struct poweron_msg_obj poweron_msg;
    // Repeater ste & ttd
    #seekto 0x1f0a;
    struct {
      u8 ste; // repeater squelch tail elimination
      u8 ttd; // repeater tail tone delay
    } repeater;
    // mic gain
    #seekto 0x1f28;
    struct {
      u8 gain;
    } mic;
    """

    def get_features(self):
        rf = super().get_features()
        rf.valid_power_levels = [x for x in self._tx_power if x]
        rf.valid_modes = self._modes
        rf.valid_tuning_steps = self._steps
        return rf

    def get_settings_roger(self, roger_settings, settings_mem):
        """Roger Beep Settings"""
        # roger beep
        rs = RadioSettingValueList(self._roger_list,
                                   current_index=settings_mem.rogerprompt)
        mset = MemSetting('settings.rogerprompt', 'Roger Beep', rs)
        mset.set_doc('Set to have a roger beep sound at the end of TX.')
        roger_settings.append(mset)

    def get_sub_devices(self):
        return[TDH3VhfUhf(self._mmap),
               TDH3FM(self._mmap),
               ]


class TDH3VhfUhf(TDH3):
    """TIDRADIO TD-H3 VHF/UHF subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3'
    VARIANT = 'VHF/UHF'


class TDH3FM(TDH8FM, TDH3):
    """TIDRADIO TD-H3 FM broadcast radio subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3'
    VARIANT = 'FM Broadcast'
    _fmband =  [(65000000, 108000000)]  # in Mhz, 65.0-108.0 MH
    _mem_params = TDH3._mem_params

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = self._rxbands
        return rf


@directory.register
@directory.detected_by(TDH3)
class TDH3_HAM(TDH3):
    """TIDRADIO H-3 Ham"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3-HAM'
    ident_mode = b'P31185\xff\xff'
    _ham = True
    _gmrs = False
    _txbands = [(144000000, 149000000), (420000000, 451000000)]
    _rxbands = [(18000000, 107999000), (108000000, 136000000),
                (149990000, 419990000), (451000000, 600000000)]
    _tx220 = [(222000000, 225000000)]
    # leave out 219-220 sub-band because this radio doesn't do
    # fixed digital message forwarding
    # tx350 and tx500 bands unknown; add them if you are in a
    # legal locale and know their correct range

    def get_tx_bands(self):
        _settings = self._memobj.settings
        bands = []
        bands.extend(self._txbands)
        if _settings.tx220:
            bands.extend(self._tx220)
        return bands


@directory.register
@directory.detected_by(TDH3)
class TDH3_GMRS(TDH3):
    """TIDRADIO H-3 GMRS"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3-GMRS'
    ident_mode = b'P31184\xff\xff'
    _gmrs = True
    _ham = False
    _txbands = [(136000000, 175000000), (400000000, 521000000)]

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        msgs.extend(validate_gmrs_memory(mem))
        return msgs


@directory.register
class TDH3_Plus(TDH3):
    """TIDRADIO H-3 Plus Normal"""
    # This driver is based on Version 1.0.45 firmware
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3-Plus'
    ident_mode = TDH3.ident_mode
    _ham = False
    _gmrs = False
    # _memsize = 0x1fef
    # _memsize = 0x2000
    _memsize = 0x3140
    # _ranges_main = [(0x0000, _memsize)]
    _ranges_main = [(0x0000, 0x1f80),
                    (0x3000, 0x3140)]
    _mmap = bytearray(_memsize)
    FORMATS = [directory.register_format('%s %s' %
                                         (VENDOR, MODEL), '*.td')]
    _has_am = True
    _has_am_per_channel = True
    _has_scan_hangtime = True
    _has_freq_ranger = True
    _has_pf2_button = True
    _has_top_button = False
    _has_pritx = False
    _lang_map = [
        ('English', 0), ('中文', 1), ('Türkçe', 2), ('Pусский', 3),
        ('Deutsch', 4), ('Española', 5), ('Italiana', 6), ('Française', 7),
        ('แบบไทย', 8),
        ]
    _hangtime_list = ['%1.1fs' % (x / 2) for x in range(1, 21)]
    _rx_modulation_list = ['FM', 'AM']
    _dtmf_resp_list = ['None', 'Ring', 'Callback', 'Ring+Callback']
    _vfo_workmode_list = ['VFO', 'VFO+Channel', 'Channel']
    _short_press_list =  ['None', 'FM Radio', 'Lamp', 'None', 'Tone',
                          'Alarm', 'Weather', 'PTT2', 'OD PTT',
                          ]
    _long_press_list = ['None', 'FM Radio', 'Lamp', 'Cancel Sq', 'Tone',
                          'Alarm', 'Weather',
                          ]
    _ponmsg_list = ['Voltage', 'Message', 'Picture']
    _save_list = ['Off', 'Level 1(1:1)', 'Level 2(1:2)',
                  'Level 3(1:3)', 'Level 4(1:4)',
                  ]
    _steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0, 50.0, 0.5, 8.33]
    _step_list = ['%.3gK' % x for x in _steps]
    _display_list = ['Single', 'Dual', 'Classic']
    _menucolor_list = [
        'Blue', 'Red', 'Green', 'Yellow', 'Purple',
        'Orange', 'L. Blue', 'Cyan', 'Gray', 'D. Blue',
        'L. Green', 'Brown', 'Pink', 'B. Red', 'G. Blue',
        'L. Gray', 'LG. Blue', 'LB. Blue',
        ]
    _fmrec_shortname = 'FM Interrupt'
    _txbands = [(136000000, 174000000), (200000000, 600000000)]
    _rxbands = [(18000000, 600000000)]
    _tx220 = [(220000000, 299995000)]
    _tx350 = [(350000000, 350000000)]  # ???
    _tx500 = [(500000000, 520000000)]
    _mil_airband = [(220000000, 399998750)]
    _airband = TDH3._airband + _mil_airband
    _rxbands = TDH3._rxbands + _airband

    _td_file_header = b'MD-760P' + (b'\xff' * 9)  # OEM .td file header
    _td_file_offset = len(_td_file_header)  # offset of data in OEM .td file
    _img_file_header = ident_mode + (b'\xff' * 16)  # CHIRP .img file header
    _img_file_offset = len(_img_file_header)  # offset of data in CHIRP .img

    _end_fromat = """
    // bluetooth
    #seekto 0x1f29;
    struct {
      u8 unused0:7,
        on:1;
    } bluetooth;
    // H3 Plus, H9 radio menu items
    #seekto 0x1f30;
    struct {
      u8 lang;      // 0x1f30 radio menu lang
                    //  0: English, 1: Chinese, 2: Turkish, 3: Russian,
                    //  4: German, 5: Spanish, 6: Itialian, 7: French
                    //  8: Thai (not implemented yet)
      u8 display;   // 0x1f31 radio display mode 0: Single, 1: Dual, 2: Classic
      u8 color;     // 0x1f32 radio menu bg color
      ul16 ranger_high; // 0x1f33 H3+, H9 freq ranger high limit
      ul16 ranger_low;  // 0x1f35 H3+, H9 freq ranger low limit
      u8 hangtime;  // 0x1f37 H9, H3+ scan hangtime
    } menu;
    // SMS
    #seekto 0x3010;
    struct {
      u8 unknown0[13];
      u8 unknown:7, // 0x301d sms on/off
        on:1;
      u8 unknown1[18];
    } sms;
    """

    def load_mmap(self, filename):
        """Read/import TIDRADIO OEM CPS .td file into .img map.
        After removing .td file header and replacing with .img map header."""
        if filename.lower().endswith(".td"):
            with open(filename, 'rb') as f:
                if f.read(self._td_file_offset) != self._td_file_header:
                    raise errors.ImageDetectFailed('Unknown file header')

                self._mmap = memmap.MemoryMapBytes(self._img_file_header +
                                                   f.read(self._memsize))
                LOG.info('Loaded TIDRADIO OEM CPS .td file %s at offset '
                         '0x%04x for 0x%04x bytes' %
                         (filename, self._td_file_offset, self._memsize))
                self.process_mmap()
        else:
            chirp_common.CloneModeRadio.load_mmap(self, filename)

    def save_mmap(self, filename):
        """Save .img map bytes as H9 OEM CPS .td file.
        After replacing .img header with .td header and
        padding to full length"""
        if filename.lower().endswith('.td'):
            with open(filename, 'wb') as f:
                f.write(self._td_file_header)
                f.write(self._mmap.get_packed()[self._img_file_offset:-1])
                # pad to OEM CPS .td file specs
                f.write(b'\x00' * (0xea70 - f.tell()))
                f.write(b'\xff' * (0x10000 - f.tell()))
                LOG.info('Wrote TIDRADIO OEM CPS .td file %s for 0x%05x bytes' %
                         (filename, (f.tell() - 1)))
        else:
            chirp_common.CloneModeRadio.save_mmap(self, filename)

    @classmethod
    def match_model(cls, filedata, filename):
        if filename.lower().endswith('.td') and \
                filedata.startswith(cls._td_file_header):
            LOG.info('Idenitified TIDRADIO OEM CPS .td file %s' % filename)
            return True
        else:
            return False

    def get_sub_devices(self):
        return[TDH3_PlusVhfUhf(self._mmap),
               TDH3_PlusFM(self._mmap),
               ]


class TDH3_PlusVhfUhf(TDH3_Plus):
    """TIDRADIO TD-H3 Plus VHF/UHF subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3-Plus'
    VARIANT = 'VHF/UHF'


class TDH3_PlusFM(TDH3FM):
    """TIDRADIO TD-H3 Plus FM broadcast subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H3-Plus'
    VARIANT = 'FM Broadcast'
    _fmband = [(87000000, 108000000)]  # in Mhz, 87.0-108.0 MH


@directory.register
@directory.detected_by(TDH3_Plus)
class TDH3_Plus_HAM(TDH3_HAM, TDH3_Plus):
    """TIDRADIO H-3 Plus Ham"""
    MODEL = 'TD-H3-Plus-HAM'
    _ham = True
    _gmrs = False
    _txbands = [(144000000, 149000000), (420000000, 451000000)]
    _rxbands = [(18000000, 107999000), (108000000, 136000000),
                (149990000, 419990000), (451000000, 600000000)]
    _tx220 = [(222000000, 225000000)]
    # leave out 219-220 sub-band because this radio doesn't do
    # fixed digital message forwarding
    # tx350 and tx500 bands unknown; add them if you are in a
    # legal locale and know their correct range

    def get_tx_bands(self):
        _settings = self._memobj.settings
        bands = []
        bands.extend(self._txbands)
        if _settings.tx220:
            bands.extend(self._tx220)
        return bands


@directory.register
@directory.detected_by(TDH3_Plus)
class TDH3_Plus_GMRS(TDH3_GMRS, TDH3_Plus):
    """TIDRADIO H-3 Plus GMRS"""
    MODEL = 'TD-H3-Plus-GMRS'
    _gmrs = True
    _ham = False
    _txbands = [(136000000, 175000000), (400000000, 521000000)]

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        msgs.extend(validate_gmrs_memory(mem))
        return msgs


@directory.register
class TDH9(TDH3_Plus):
    """TIDRADIO H-9 Normal"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H9'
    ident_mode = b'TDH9\xff\xff\xff\x4e'
    _gmrs = False
    _ham = False
    # _memsize = 0x2000
    _memsize = 0x3140
    # _ranges_main = [(0x0000, _memsize)]
    _ranges_main = [(0x0000, 0x1f80),
                    (0x3000, 0x3140)]
    _mmap = bytearray(_memsize)
    _tx_power = [chirp_common.PowerLevel('Low',  watts=1.00),
                 chirp_common.PowerLevel('Mid',  watts=5.00),
                 chirp_common.PowerLevel('High', watts=10.00),
                 ]
    _has_dtmf_len = False
    _has_dtmf_terminated = not _has_dtmf_len
    _has_freq_ranger = True
    _has_pf2_button = True
    _has_top_button = True
    _short_press_list =  ['None', 'FM Radio', 'GNSS SW', 'None', 'Tone',
                          'Alarm', 'Weather', 'PTT2', 'OD PTT',
                          ]
    _long_press_list = ['None', 'FM Radio', 'GNSS SW', 'Cancel Sq', 'Tone',
                          'Alarm', 'Weather',
                          ]

    _end_fromat = TDH3_Plus._end_fromat + """
    // H9 GNSS
    #seekto 0x3066;
    struct { // GNSS config data, 0x15 bytes
      u8 region[1]; // 0x3066 GNSS region index
      u8 unknown0[0x07];
      u8 unsed0:7,  // 0x306e
        gps_on:1; // 1 bit GPS on/off
      u8 unknown1[0x0b];
      u8 type[1]; // 0x307a GNSS type index
    } gnss;
    // H9 APRS
    #seekto 0x307c;
    struct { // APRS config data, 0x98 bytes
      u8 unknown0[0x7b];
      u8 unused0:7,   // 0x30f7
        timed_beacon:1; // 1 bit timed beacon on/off
      u8 timing[1];   // 0x30f8 1 byte beacon timing in seconds
      u8 unknown1[0x1c];
    } aprs;
    """

    def get_features(self):
        rf = super().get_features()
        rf.valid_power_levels = [x for x in self._tx_power if x]
        rf.valid_modes = self._modes
        rf.valid_tuning_steps = self._steps
        return rf

    def get_sub_devices(self):
        return[TDH9VhfUhf(self._mmap),
               TDH9FM(self._mmap),
               ]


class TDH9VhfUhf(TDH9):
    """TIDRADIO H9 VHF/UHF subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H9'
    VARIANT = 'VHF/UHF'


class TDH9FM(TDH9, TDH8FM):
    """TIDRADIO H9 FM broadcast radio subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H9'
    VARIANT = 'FM Broadcast'
    _fmband = [(87000000, 108000000)]  # in Mhz, 87.0-108.0 MH

    def get_features(self):
        rf = TDH8FM.get_features(self)
        return rf


@directory.register
@directory.detected_by(TDH9)
class TDH9_HAM(TDH9, TDH3_Plus_HAM):
    """TIDRADIO H-9 Ham"""
    MODEL = 'TD-H9-HAM'
    ident_mode = b'TDH9\xff\xff\xff\x48'
    _ham = True
    _gmrs = False
    _txbands = [(144000000, 149000000), (420000000, 451000000)]
    _rxbands = [(18000000, 107999000), (108000000, 136000000),
                (149990000, 419990000), (451000000, 600000000)]
    _tx220 = [(222000000, 225000000)]
    # leave out 219-220 sub-band because this radio doesn't do
    # fixed digital message forwarding
    # tx350 and tx500 bands unknown; add them if you are in a
    # legal locale and know their correct range

    def get_tx_bands(self):
        _settings = self._memobj.settings
        bands = []
        bands.extend(self._txbands)
        if _settings.tx220:
            bands.extend(self._tx220)
        return bands


@directory.register
@directory.detected_by(TDH9)
class TDH9_GMRS(TDH9, TDH3_Plus_GMRS):
    """TIDRADIO H-9 GMRS"""
    MODEL = 'TD-H9-GMRS'
    ident_mode = b'TDH9\xff\xff\xff\x47'
    _gmrs = True
    _ham = False
    _txbands = [(136000000, 175000000), (400000000, 521000000)]

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        msgs.extend(validate_gmrs_memory(mem))
        return msgs


@directory.register
class RT730(TDH8):
    """Radtel RT-730"""
    VENDOR = 'Radtel'
    MODEL = 'RT-730'
    _idents = [RT_730]
    _gmrs = False
    _ham = False
    _memsize = 0x6400
    _ranges_main = [(0x0000, _memsize)]
    _mmap = bytearray(_memsize)
    _mem_params = {
        'channels': 200,
        'fmb_channels': 25,
        'dtmf_strings': 0,
        'dtmf_len': 0,
        'name_len': 8,
    }
    _txbands = [(136000000, 174000000), (174000000, 300000000),
                (300000000, 400000000), (400000000, 520000000),
                (520000000, 630000000)]
    _airband = [(108000000, 135975000)]
    _rxbands = [(10000000, 108000000)] + _airband
    _modes = ['FM', 'NFM', 'AM', 'NAM']  # 25 kHz,12.5kHz, AM, NAM.
    _has_am = True
    _has_am_per_channel = False
    _has_offsetdir = False
    _has_scramble = True
    _has_dtmf = False
    _has_pttid = False
    _has_dtmf_len = False
    _has_stored_dtmf = False
    _has_dtmf_terminated = False
    _has_stuncode = False
    _has_killcode = False
    _has_dtmf_extra = False
    _has_scan_hangtime = False
    _has_freq_ranger = False
    _has_pf2_button = True
    _has_top_button = False
    _has_def_chan = False
    _has_bluetooth = False
    _has_brightness = False
    _has_spec= True

    _lang_map = [('Chinese', 0), ('English', 1)]
    _scramble_list = ['Disabled', 'Enabled']
    _short_press_list = ['None', 'Scan', 'FM Radio', 'Warn', 'TONE',
                         'Weather', 'Copy CH',
                         ]
    _long_press_list = _short_press_list + ['Monitor']
    _voxgain_list = ['Off', '1', '2', '3']
    _voxdelay_list = ['0.5s', '1.0s', '2.0s', '3.0s']
    _backlight_list = ['CONT', '10s', '20s', '30s']
    _hop_list = ['A', 'B', 'C', 'D']

    _mem_format = """
    // 16 byte memory channel
    struct memory_obj {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      lbcd rxtone[2];
      lbcd txtone[2];
      u8 unused1;
      u8 unused2:4,
        spec:1,
        bcl:1,
        unused3:2;
      u8 scramble:1,
        freqhop:1,
        power:2,
        narrow:1,
        unused4:3;
      u8 unused5;
    };
    """

    _name_format = """
    // channel name
    struct name_obj {
      char name[%(name_len)i];
    };
    """

    _button_format = """
    // programmable button obj
    struct button_obj {
      u8 ssidekey1;       // pf1 short press
      u8 lsidekey1;       // pf1 long press
      u8 ssidekey2;       // pf2 short press
      u8 lsidekey2;       // pf2 long press
      u8 unused1:6,
      rogerprompt:2;
    };
    """

    _settings_format = """
    struct settings_obj {
      u8 txled:1,
        rxled:1,
        unused1:5,
        pritx:1;
      u8 scanmode:2,
        unused2:1,
        keyautolock:1,
        save:1,
        beep:1,
        unused3:1,
        voiceprompt:1;
      u8 fmworkmode:1,
        ligcon:2,
        unused4:1,
        fmrec:1,
        mdfa:1,
        aworkmode:2;
      u8 unused5:5,
        dbrx:1,
        bworkmode:2;
      u8 unused6;
      u8 unused7;
      u8 fmdefch;
      u8 unused8:1,
        tailclean:1,
        unused9:3,
        voxgain:3;
      u8 astep:4,
        bstep:4;
      u8 squelch;
      u8 tot;
      u8 unused10:6,
        lang:1,
        unused11:1;
      u8 unused12;
      u8 unused13;
      u8 voxdelay;
      u8 unused14:6,
        hoptype:2;
    };
    """

    _end_fromat = """
    """

    # RT-730
    _memory_format = """
    // Memory channels
    #seekto 0x0008;
    struct memory_obj memory[%(channels)i];
    // buttons
    #seekto 0x0c98;
    struct button_obj button;
    // Settings
    #seekto 0x0ca8;
    struct settings_obj settings;
    // freq offset for vfo a & b
    #seekto 0x0cb8;
    struct offset_obj vfo_offsets[2];
    // FM broadcast channels
    #seekto 0x0cd8;
    struct fmb_obj fmb[%(fmb_channels)i];
    // channel names
    #seekto 0x0d48;
    struct name_obj names[%(channels)i];
    // power on message
    #seekto 0x1398;
    struct poweron_msg2_obj poweron_msg;
    // channel used flags
    #seekto 0x1a08;
    struct{
      lbit used[%(channels)i];
    } channelflags;
    // scan add list
    #seekto 0x1a28;
    lbit scanadd[%(channels)i];
    // fmb vfo
    #seekto 0x1b38;
    struct fmb_obj fmbvfo;
    // vfo a & b
    #seekto 0x1b58;
    struct memory_obj vfo[2];
    // fmb used flags
    #seekto 0x1b78;
    struct {
      lbit used[32];
      } fmbflags;
    """

    def get_features(self):
        rf = super().get_features()
        rf.valid_modes = self._modes
        rf.valid_tuning_steps = self._steps
        return rf

    def get_settings_spec(self, spec_settings, settings_mem):
        # dual watch mode
        rs = RadioSettingValueBoolean(settings_mem.dbrx)
        mset = MemSetting('settings.dbrx', 'Dual Watch', rs)
        mset.set_doc('Set to put the radio in dual watch '\
                     '(aka \'Double RX\') mode.')
        spec_settings.append(mset)
        # power-on message text
        _pom_mem = self._memobj.poweron_msg
        TDH8.get_settings_pom(self, spec_settings, self._memobj.poweron_msg)
        # add msg 4 for rt-730
        rs = RadioSettingValueString(0, 16,
                                     self._filter(_pom_mem.msg4))
        mset = MemSetting('poweron_msg.msg4', 'Power-On Message 4', rs)
        mset.set_doc('Set the radio power-on message text for Line 4.')
        spec_settings.append(mset)
        # batt save
        rs = RadioSettingValueBoolean(settings_mem.save)
        mset = MemSetting('settings.save', 'Battery Save', rs)
        mset.set_doc('Set to enable battery save mode.')
        spec_settings.append(mset)
        # chan names
        rs = RadioSettingValueBoolean(settings_mem.mdfa)
        mset = MemSetting('settings.mdfa', 'Channel Names', rs)
        mset.set_doc('Set to display channel names.')
        spec_settings.append(mset)
        # hop type
        rs = RadioSettingValueList(self._hop_list,
                                   current_index=settings_mem.hoptype)
        mset = MemSetting('settings.hoptype', 'Hop Type', rs)
        mset.set_doc('Set the frequency Hop Type.')
        spec_settings.append(mset)
        # qt/dqt tail clean
        rs = RadioSettingValueBoolean(settings_mem.tailclean)
        mset = MemSetting('settings.tailclean', 'QT/DQT Tail Clean', rs)
        mset.set_doc('Set to enable Tail Clean mode.')
        spec_settings.append(mset)
        # button settings
        self.get_settings_button(spec_settings, self._memobj.button)
        # A/B Chan
        abchan = RadioSettingGroup('abchan', 'VFO A/B Channel')
        self.get_settings_ab(abchan,  settings_mem)
        spec_settings.append(abchan)
        # fm broadcast Settings
        fmb = RadioSettingGroup('fmb', 'FM Broadcast')
        self.get_settings_fmb(fmb, settings_mem)
        spec_settings.append(fmb)

    def get_settings_roger(self, roger_settings, settings_mem):
        """Roger Beep Settings"""
        _roger_mem = self._memobj.button.rogerprompt
        # roger beep
        rs = RadioSettingValueBoolean(_roger_mem)
        mset = MemSetting('button.rogerprompt', 'Roger Beep', rs)
        mset.set_doc('Set to have a roger beep sound at the end of TX.')
        roger_settings.append(mset)


    def get_sub_devices(self):
        return[RT730VhfUhf(self._mmap),
               RT730FM(self._mmap),
               ]


class RT730VhfUhf(RT730):
    """Radtel RT-730 VHF/UHF subdevice"""
    VENDOR = 'Radtel'
    MODEL = 'RT-730'
    VARIANT = 'VHF/UHF'


class RT730FM(RT730, TDH8FM):
    """Radtel RT-730 FM broadcast radio subdevice"""
    VENDOR = 'Radtel'
    MODEL = 'RT-730'
    VARIANT = 'FM Broadcast'

    def get_features(self):
        rf = TDH8FM.get_features(self)
        return rf


@directory.register
@directory.detected_by(TDH8)
class TDH8_3rd_Gen(TDH3):
    """TIDRADIO TD-H8 3rd Gen Normal"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8'
    VARIANT = 'G3'
    ident_mode = b'P31183\xff\xff'
    _idents = [TD_H3, TD_H8_G3]  # Fw 250905 and later uses H3 magic
    _ham = False
    _gmrs = False
    _has_brightness = True
    _tx_power = [chirp_common.PowerLevel('Low',  watts=1.00),
                 chirp_common.PowerLevel('Mid',  watts=5.00),
                 chirp_common.PowerLevel('High', watts=10.00),
                 ]
    _roger_list = ['Off', 'TONE1', 'TONE2']

    def get_features(self):
        rf = super().get_features()
        rf.valid_power_levels = [x for x in self._tx_power if x]
        rf.valid_modes = self._modes
        rf.valid_tuning_steps = self._steps
        return rf

    def get_settings_roger(self, roger_settings, settings_mem):
        """Roger Beep Settings"""
        # roger beep
        rs = RadioSettingValueList(self._roger_list,
                                   current_index=settings_mem.rogerprompt)
        mset = MemSetting('settings.rogerprompt', 'Roger Beep', rs)
        mset.set_doc('Set to have a roger beep sound at the end of TX.')
        roger_settings.append(mset)

    def get_sub_devices(self):
        return[TDH8G3VhfUhf(self._mmap),
               TDH8G3FM(self._mmap),
               ]


class TDH8G3VhfUhf(TDH8_3rd_Gen):
    """TIDRADIO TD-H8 3rd Gen VHF/UHF subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8 G3'
    VARIANT = 'VHF/UHF'


class TDH8G3FM(TDH8FM, TDH8_3rd_Gen):
    """TIDRADIO TD-H8 3rd Gen FM broadcast radio subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8 G3'
    VARIANT = 'FM Broadcast'
    _fmband = [(87000000, 108000000)]  # in Mhz, 87.0-108.0 MH

    def get_features(self):
        rf = TDH8FM.get_features(self)
        return rf


@directory.register
@directory.detected_by(TDH8)
class TDH8_3rd_Gen_HAM(TDH8_3rd_Gen):
    """TIDRADIO TD-H8 3rd Gen Ham"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8-HAM'
    ident_mode = b'P31185\xff\xff'
    _ham = True
    _gmrs = False
    _txbands = [(144000000, 149000000), (420000000, 451000000)]
    _rxbands = [(18000000, 107999000), (108000000, 136000000),
                (149990000, 419990000), (451000000, 600000000)]
    _tx220 = [(222000000, 225000000)]
    # leave out 219-220 sub-band because this radio doesn't do
    # fixed digital message forwarding
    # tx350 and tx500 bands unknown; add them if you are in a
    # legal locale and know their correct range

    def get_tx_bands(self):
        _settings = self._memobj.settings
        bands = []
        bands.extend(self._txbands)
        if _settings.tx220:
            bands.extend(self._tx220)
        return bands


@directory.register
@directory.detected_by(TDH8)
class TDH8_3rd_Gen_GMRS(TDH8_3rd_Gen):
    """TIDRADIO TD-H8 3rd Gen GMRS"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8-GMRS'
    ident_mode = b'P31184\xff\xff'
    _gmrs = True
    _ham = False

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        msgs.extend(validate_gmrs_memory(mem))
        return msgs


@directory.register
@directory.detected_by(TDH8)
# Appears to be similar to the TD-H3-Plus, but with a different ident_mode and some different features.
class TDH8_4th_Gen(TDH3_Plus):
    """TIDRADIO TD-H8 4th Gen Normal"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8 G4'
    ident_mode = b'TDH84GEN'
    _idents = [TD_H3]
    _ham = False
    _gmrs = False
    _tx_power = [chirp_common.PowerLevel('Low',  watts=1.00),
                 chirp_common.PowerLevel('Mid',  watts=5.00),
                 chirp_common.PowerLevel('High', watts=10.00),
                 ]
    _has_pf2_button = True
    _has_top_button = True

    def get_features(self):
        rf = super().get_features()
        rf.valid_power_levels = [x for x in self._tx_power if x]
        rf.valid_modes = self._modes
        rf.valid_tuning_steps = self._steps
        return rf

    def get_sub_devices(self):
        return[TDH8G4VhfUhf(self._mmap),
               TDH8G4FM(self._mmap),
               ]


class TDH8G4VhfUhf(TDH8_4th_Gen):
    """TIDRADIO TD-H8 4th Gen VHF/UHF subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8 G4'
    VARIANT = 'VHF/UHF'


class TDH8G4FM(TDH8FM, TDH8_4th_Gen):
    """TIDRADIO TD-H8 4th Gen FM broadcast radio subdevice"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8 G4'
    VARIANT = 'FM Broadcast'
    _fmband = [(87000000, 108000000)]  # in Mhz, 87.0-108.0 MH

    def get_features(self):
        rf = TDH8FM.get_features(self)
        return rf


@directory.register
@directory.detected_by(TDH8)
class TDH8_4th_Gen_Ham(TDH8_4th_Gen):
    """TIDRADIO TD-H8 4th Gen Ham"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8 G4 HAM'
    ident_mode = b'TDH84GEH'
    _ham = True
    _gmrs = False
    _txbands = [(144000000, 149000000), (420000000, 451000000)]
    _rxbands = [(18000000, 107999000), (108000000, 136000000),
                (149990000, 419990000), (451000000, 600000000)]
    _tx220 = [(222000000, 225000000)]
    # leave out 219-220 sub-band because this radio doesn't do
    # fixed digital message forwarding
    # tx350 and tx500 bands unknown; add them if you are in a
    # legal locale and know their correct range

    def get_tx_bands(self):
        _settings = self._memobj.settings
        bands = []
        bands.extend(self._txbands)
        if _settings.tx220:
            bands.extend(self._tx220)
        return bands


@directory.register
@directory.detected_by(TDH8)
class TDH8_4th_Gen_GMRS(TDH8_4th_Gen):
    """TIDRADIO TD-H8 4th Gen GMRS"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-H8 G4 GMRS'
    ident_mode = b'TDH84GEG'
    _gmrs = True
    _ham = False

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        msgs.extend(validate_gmrs_memory(mem))
        return msgs
