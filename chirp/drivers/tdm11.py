# Copyright 2025, 2026 Fred Trimble <chirpdriver@gmail.com>
# CHIRP driver for TIDRADIO TD-M11 22 FRS and TD-M11 16 PMR446 radios
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
    chirp_common,
    directory,
    errors,
    memmap,
)

from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueList,
    RadioSettingValueString,
    MemSetting,
)

import logging
import struct
import time
from textwrap import dedent
from datetime import datetime

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
// memmory channels: 16 bytes each * 22 channels == 352 bytes
//                                 * 16 channels == 256 bytes
#seekto 0x0000;
struct {
  lbcd rxfreq[4];   // RX freq
  lbcd txfreq[4];   // TX freq
  lbcd rxtone[2];   // RX tone
  lbcd txtone[2];   // TX tone
  u8 unknown0:2,
     jumpfreq:1,    // 1 bit freq hopping
     scan:1,        // 1 bit scan add
     txpower:1,     // 1 bit TX  power
     narrow:1,      // 1 bit bandwidth
     bcl:2;         // 1 bit busy lockout
  u8 unknown1:3,
     compand:1,     // 1 bit compander
     scramble:4;    // 4 bit scramble
  u8 unknown2;
  u8 unknown3;
} memory[%d];

// settings:
#seekto 0x0300;
struct {
  u8 unknown0:4,    // 0x0300
     squelch:4;     //        4 bit squelch level
  u8 unused1:6,     // 0x0301
     voice:2;       //        2 bit voice prompts, 0 Off, 1 Chinese, 2 English
  u8 channel;       // 0x0302 default channel on power up
  u8 unused2:4,     // 0x0303
     vox:4;         //        4 bit vox level
  u8 unused3:2,     // 0x0304
     tot:6;         //        6 bit TX time out timer
  u8 wxchannel;     // 0x0305
  u8 unused4:4,     // 0x0306
     sleep:4;       //        4 bit power saving mode
  u8 firmware[3];   // 0x0307 3 byte firmware version
  u8 unknown1;      // 0x030a
  u8 unused5:4,     // 0x030b
     sidekey1:4;    //
  u8 unknown4;      // 0x030c
  u8 unused6:4,     // 0x030d
     sidekey2:4;    //
  u8 unknown5[2];   // 0x030e
  u8 freqband[4];   // 0x0310 4 byte freb band
  u8 model;         // 0x0314
  u8 areacode;      // 0x0315
  u8 unknown7[10];  // 0x0316
  u8 password[6];   // 0x0320 6 byte radio programming mode password
} settings;

// program time
#seekto 0x0406;
struct {
  u8 time[6];       // [0]msb yr:,[1]lsb yr:,[2]:mon,[3]:day,[4]:hr,[5]:min
} progtime;
"""


CMD_ACK = b'A'
GET_RADIO_ID = b'\x52\x10\x03\x10'
NULL_PASSWORD = b'\xff\xff\xff\xff\xff\xff'
TIMEOUT = 0.5  # base serial timeout in seconds
TXPOWER_HIGH = 0x01
TXPOWER_LOW = 0x00


def get_default_features(self):
    rf = chirp_common.RadioFeatures()
    rf.has_settings = True
    rf.has_bank = False
    rf.has_ctone = True
    rf.has_cross = True
    rf.has_rx_dtcs = True
    rf.has_tuning_step = False
    rf.can_odd_split = True
    rf.has_name = False
    rf.valid_name_length = 0
    rf.valid_characters = self._valid_chars
    rf.valid_skips = ['', 'S']
    rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
    rf.valid_cross_modes = ['Tone->Tone', 'Tone->DTCS', 'DTCS->Tone',
                            '->Tone', '->DTCS', 'DTCS->', 'DTCS->DTCS']
    rf.valid_power_levels = self._power_levels
    rf.valid_duplexes = ['', '-', '+', 'split', 'off']
    rf.valid_modes = ['FM', 'NFM']  # 25 kHz, 12.5 kHz.
    rf.valid_dtcs_codes = chirp_common.DTCS_CODES
    rf.memory_bounds = (1, self._upper)
    rf.valid_tuning_steps = [2.5, 5., 6.25, 8.33, 10., 12.5, 20., 25., 50.]
    rf.valid_bands = self.VALID_BANDS
    return rf


def _enter_programming_mode(radio, write=False):
    serial = radio.pipe
    serial.timeout = TIMEOUT

    try:
        if _test_magic(radio):
            if not write:
                # store sucessful magic in img metadata
                radio.metadata = {'td-m11_magic': list(radio._magic)}
                LOG.info('Stored magic value %s in image metadata'
                         % radio._magic)
        else:
            raise errors.RadioError('Radio didn\'t accept Program Mode')

    except errors.RadioError as re:
        raise errors.RadioError(re)

    try:
        # if we get an ACK here the radio programming function
        # is not password protected
        serial.write(NULL_PASSWORD)
        ack = serial.read(0x01)

        if ack == CMD_ACK:
            LOG.info('Radio Programming function is NOT '
                     'password protected')
        else:
            msg = 'The radio Programming function is '\
                'password protected. Use the factory CPS to '\
                'remove the password to continue.'
            raise ValueError(msg)

    except ValueError as ex:
        raise errors.RadioError(ex)
    except Exception:
        raise errors.RadioError('Error communicating with radio')

    # if uploading to the radio we have to ask it for its fingerprint first
    if write:
        try:
            # ask radio for fingerprint
            serial.write(GET_RADIO_ID)
            ack = serial.read(0x11)
            ack2 = _get_checksum(ack[:-1], 0, 0x10)

            if ack[:-1] in radio._fingerprint and ack[-1] == ack2:
                LOG.info("Radio fingerprint 0x%s match" % ack[:-1].hex())
            else:
                LOG.error("Radio fingerprint 0x%s Mis-match" %
                          radio.ack[:-1].hex())
                msg = 'Radio Model mismatch'
                raise ValueError(msg)

        except ValueError as ex:
            raise errors.RadioError(ex)


def _exit_programming_mode(radio):
    serial = radio.pipe
    serial.timeout = TIMEOUT

    try:
        serial.write(b'E')
    except Exception:
        raise errors.RadioError('Radio refused to exit programming mode')


def _test_magic(radio, tries=5):
    serial = radio.pipe
    serial.timeout = TIMEOUT / 5.0
    rv = False
    delay = 0.0
    total_delay = 0.0
    try:
        for i in range(1, tries + 1):
            serial.write(radio._magic)
            ack = serial.read(0x01)
            if ack == CMD_ACK:
                LOG.info('Radio ack\'ed magic %s '
                         'during detection after %0.4f second '
                         'delay on try %d' %
                         (radio._magic, total_delay, i))
                rv = True
                break
            else:
                # adaptive delay to allow radio to settle
                delay = i ** 0.5
                total_delay += delay
                LOG.debug('Adaptive delay of: %0.4f seconds' % delay)
                time.sleep(delay)
        else:
            LOG.info('Raido didn\'t ack magic %s '
                     'during detection after %d trie(s) over %0.4f seconds' %
                     (radio._magic, i, total_delay))
            rv = False
    except Exception as ex:
        raise errors.RadioError(ex)
    finally:
        radio.pipe.flush()

    return rv


def _get_checksum(data, addr, len):
    checksum = 0
    for index in range(0, len):
        checksum += data[index + addr]
    return checksum & 0xff  # checksum is only low order byte


def _read_block(radio, block_addr, size):
    serial = radio.pipe
    serial.timeout = TIMEOUT

    cmd = struct.pack('<cHb', b'R', block_addr, size)
    expectedresponse = b''

    try:
        serial.write(cmd)
        response = serial.read(size)
        expectedresponse = serial.read(1)  # read 1 byte checksum
        checksum = _get_checksum(response, 0, size)
        if checksum != expectedresponse[0]:
            raise errors.RadioError('Checksum error reading block %04x.' %
                                    (block_addr))
        block_data = response

    except Exception:
        raise errors.RadioError('Failed to read block at %04x' % block_addr)

    return block_data


def _write_block(radio, block_addr, size):
    serial = radio.pipe
    serial.timeout = TIMEOUT

    cmd = struct.pack('<cH', b'W', block_addr)
    data = radio.get_mmap()[block_addr:block_addr + size]
    checksum = _get_checksum(data, 0, size)

    try:
        serial.write(cmd + data + bytes([checksum]))
        ack = serial.read(1)
        if ack != CMD_ACK:
            raise Exception('No ACK')
    except Exception:
        raise errors.RadioError('Failed to send block '
                                'to radio at %04x' % block_addr)


def do_download(radio):
    LOG.info('Downloading...')
    _enter_programming_mode(radio)

    data = b''
    status = chirp_common.Status()
    status.msg = 'Cloning from radio'
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr
        radio.status_fn(status)
        radio.pipe.log('Reading from address: 0x%04x' % addr)
        block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

    radio.pipe.log('Downloaded 0x%04x bytes from radio' % len(data))

    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    LOG.info('Uploading...')
    _enter_programming_mode(radio, write=True)

    status = chirp_common.Status()
    status.msg = 'Uploading to radio'
    status.max = radio._memsize
    bytesup = 0

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr
            radio.status_fn(status)
            radio.pipe.log('Writing to address:   0x%04x' % addr)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)
            bytesup += radio.BLOCK_SIZE_UP

    radio.pipe.log('Uploaded 0x%04x bytes to radio' % bytesup)


@directory.register
class TDM11_22(chirp_common.CloneModeRadio):
    # ==========
    # Notice to developers:
    # The TD-M11 22 for USA FRS/GMRS support in this driver is currently based
    # on Firmware v0.9.4
    # ==========
    # TD-M11 power-on key sequencies:
    #   Crack (freq sesrch): Set Ch to 1, power Off, [PTT] + power On
    #       Chan disp, Green LED flashes
    #   Wireless Copy transmit: Set Chan to 2 or 4, power Off, [PTT] + power On
    #       Full disp, Red LED flashes
    #   Wireless Copy receive: Set Chan to 3 or 5, power Off, [PTT] + power On
    #       Full disp, Green LED solid
    #   Change voice prompts: Set Chan to 15, power Off, [PTT] + power On
    #       Voice change is announced
    #   Firmware update mode: [Ch +] + [Ch -] + power On
    #       Disp off, Green LED solid
    #       Have 8 sec to start Fw update
    #           after 8 sec timeout turns on Bluetooth:
    #           Chan disp w/bluetooth icon, Red LED solid
    #           after Bluetooth paring, Yellow LED solid
    """TIDRADIO TD-M11 22"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-M11'
    VARIANT = '22 FRS'  # USA FRS/GMRS
    BAUD_RATE = 9600
    FORMATS = [directory.register_format('%s %s' %
                                         (VENDOR, MODEL), '*.mdt')]
    BLOCK_SIZE = 0x10
    BLOCK_SIZE_UP = 0x10
    VALID_BANDS = [(136000000, 174000001), (200000000, 260000001),
                   (350000000, 390000001), (400000000, 520000001),
                   ]
    _power_levels = [
        chirp_common.PowerLevel('Low', watts=0.50),
        chirp_common.PowerLevel('High', watts=2.00)
    ]

    _upper = 22
    _mem_params = (_upper)
    _memsize = 0x0450  # Including calibration data
    _ranges = [(0x0000, _memsize)]

    _magic_list = [b'STD-M11-',  # firmware 0.9.4
                   ]
    _magic = b''

    _fingerprint = [
        b'\x00\x40\x00\x52\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
        ]
    _mdt_file_header = b'TD-M11-22CLIENT'
    _mdt_offset = len(_mdt_file_header)  # offset of data in OEM .mdt file
    _valid_chars = chirp_common.CHARSET_ALPHANUMERIC
    _steps = [5.0, 6.25, 12.5, 25.0]
    # mem extra lists
    _bcl_list = ['Off', 'Carrier', 'QT/DTQ']
    _jumpfreq_list = ['Normal', 'Special']
    _compand_list = ['Off', 'On']
    _scramble_list = ['Off'] + ['Scramble %d' % x for x in range(1, 9)]
    # settings lists
    _voice_list = ['Off', 'Chinese', 'English']
    _tot_list = ['Off'] + ['%ds' % x for x in range(15, 315, 15)]
    _voxlevel_list = ['Off'] + ['%d' % x for x in range(1, 10)]
    _squelchlevel_list = ['%d' % x for x in range(0, 10)]
    _sleepmode_list = ['Off'] + ['1:%d' % x for x in range(1, 11)]
    _sidekey_list = ['None', 'Monitor', 'Scan',
                     'Alarm', 'Bluetooth', 'Weather']
    _channel_list = ['%d' % x for x in range(1, _upper + 1)]
    _wxchannel_list = ['WX %d' % x for x in range(1, 12)]
    _freqband_list = []

    @classmethod
    def detect_from_serial(cls, pipe):

        # build list of potential magics with their classes
        magics = {}
        for rcls in cls.detected_models():
            magics.setdefault(tuple(rcls._magic_list), [])
            magics[tuple(rcls._magic_list)].append(rcls)

        # try each class/magic and see which one responds first
        for magic_list, rclass in magics.items():
            for magic in magic_list:
                try:
                    radio = rclass[0](pipe)
                    radio._magic = magic
                    if _test_magic(radio, tries=1):
                        LOG.info('Radio detected '
                                 'using magic %s' % magic)
                        return rclass[0]
                    else:
                        LOG.info('Radio NOT detected '
                                 'using magic %s' % magic)
                except errors.RadioError:
                    pass
                except Exception as ex:
                    raise Exception(ex)
                finally:
                    _exit_programming_mode(radio)
        else:  # for
            raise errors.RadioError('No response from radio '
                                    'or unsupported model')

    def sync_in(self):
        """Download from radio"""
        for magic in self._magic_list:
            self._magic = magic
            try:
                data = do_download(self)
                LOG.info('Radio accepted Programming mode '
                         'using magic %s' % magic)
                self._mmap = data
                self.process_mmap()
                break
            except errors.RadioError:
                # log when radio does not accept magic
                LOG.info('Radio didn\'t accept Programming mode '
                         'using magic %s' % magic)
                pass
            except Exception as ex:
                # If anything unexpected happens, make sure we log the problem
                # and raise a RadioError
                LOG.exception('Unexpected error during download: %s' % ex)
                raise errors.RadioError('Unexpected error during download: %s'
                                        % ex)
            finally:
                _exit_programming_mode(self)
                self.pipe.flush()

        else:  # for
            raise errors.RadioError('No response from radio '
                                    'or unsupported model')

    def sync_out(self):
        """Upload to radio"""
        # use magic value, if any, stored in metadata
        meta_magic = bytes(self.metadata.get('td-m11_magic', []))
        if meta_magic:
            self._magic_list = list([meta_magic])
            LOG.info('Using magic value %s from image metadata' % meta_magic)

        for magic in self._magic_list:
            self._magic = magic
            try:
                _time = self._memobj.progtime
                _time.time = self._encode_current_time()
            except Exception:
                LOG.warning('image file too short, can\'t update '
                            'program-time timestamp')

            try:
                do_upload(self)
                LOG.info('Radio accepted Programming mode '
                         'using magic %s' % magic)
                break
            except errors.RadioError:
                # log when radio does not accept magic
                LOG.info('Radio didn\'t accept Programming mode '
                         'using magic %s' % magic)
                pass
            except Exception as ex:
                # If anything unexpected happens, make sure we log the problem
                # and raise a RadioError
                LOG.exception('Unexpected error during upload: %s' % ex)
                raise errors.RadioError('Unexpected error during upload: %s'
                                        % ex)
            finally:
                _exit_programming_mode(self)
                self.pipe.flush()
        else:  # for
            raise errors.RadioError('No response from radio '
                                    'or unsupported model')

    def load_mmap(self, filename):
        if filename.lower().endswith('.mdt'):
            with open(filename, 'rb') as f:

                if f.read(len(self._mdt_file_header)) != self._mdt_file_header:
                    raise errors.ImageDetectFailed("Unknown file header")

                self._mmap = memmap.MemoryMapBytes(f.read(self._memsize))
                LOG.info('Loaded TD-M11 .mdt file %s at offset 0x%04x' %
                         (filename, self._mdt_offset))
            self.process_mmap()
        else:
            chirp_common.CloneModeRadio.load_mmap(self, filename)

    def save_mmap(self, filename):
        if filename.lower().endswith('.mdt'):
            with open(filename, 'wb') as f:
                f.write(self._mdt_file_header)
                f.write(self._mmap.get_packed())
                LOG.info('Wrote TD-M11 .mdt file % s' % filename)
        else:
            chirp_common.CloneModeRadio.save_mmap(self, filename)

    def _decode_tone(self, val):
        if val == 16665 or val == 0:
            return '', None, None
        elif val >= 12000:
            return 'DTCS', val - 12000, 'R'
        elif val >= 8000:
            return 'DTCS', val - 8000, 'N'
        else:
            return 'Tone', val / 10.0, None

    def _encode_tone(self, memval, mode, value, pol):
        if mode == '':
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            flag = 0x80 if pol == 'N' else 0xC0
            memval.set_value(value)
            memval[1].set_bits(flag)
        else:
            raise Exception('Internal error: invalid mode ''%s''' % mode)

    def _decode_freqband(self, band):
        try:
            s = '%g-%g Mhz' % (
                float(str(band[1])[-2:] + str(band[0])[-2:]) / 10,
                float(str(band[3])[-2:] + str(band[2])[-2:]) / 10
            )
        except IndexError:
            s = '(unknown)'

        return s

    def _encode_current_time(self):
        now = datetime.now()
        time = [0] * 6
        time[0] = now.year & 0xff
        time[1] = now.year >> 8
        time[2] = now.month
        time[3] = now.day
        time[4] = now.hour
        time[5] = now.minute
        return time

    def get_settings(self):
        _settings = self._memobj.settings
        _time = self._memobj.progtime
        basic = RadioSettingGroup('basic', 'Settings')
        group = RadioSettings(basic)

        # format raw firmware ver for display
        def _fw(version):
            if bytes(version) == b'\xff\xff\xff':
                return '(none)'

            ver = 'v'
            try:
                for i in version:
                    ver += '%d' % i + '.'
                LOG.info('Firmware version: %s' % ver[:-1])
                return ver[:-1]
            except IndexError:
                return '(none)'

        # Firmware version, display only
        rs = RadioSettingValueString(0, 6, _fw(_settings.firmware))
        rs.set_mutable(False)
        rset = RadioSetting('settings.firmware', 'Firmware Version', rs)
        rset.set_doc('Radio Firmware Version (read only)')
        basic.append(rset)

        # Freq band, display only
        rs = RadioSettingValueString(0, 32,
                                     self._decode_freqband(_settings.freqband))
        rs.set_mutable(False)
        rset = RadioSetting('settings.freqband', 'Frequency Band', rs)
        rset.set_doc('Radio frequency band (read only)')
        basic.append(rset)

        # format raw date/time for display
        def _decode_time(time):
            try:
                y = time[0] + (time[1] << 8)
                mo = time[2]
                d = time[3]
                h = time[4]
                mi = time[5]
                s = '%04d-%02d-%02d  %02d:%02d' % (y, mo, d, h, mi)
            except IndexError:
                s = '(none)'
            return s

        # Program time, display only
        rs = RadioSettingValueString(0, 17,
                                     _decode_time(_time.time))
        rs.set_mutable(False)
        rset = RadioSetting('progtime.time', 'Program Time', rs)
        rset.set_doc('Date/Time radio was last programmed (read only)')
        basic.append(rset)

        # Voice prompts
        rs = RadioSettingValueList(self._voice_list,
                                   current_index=_settings.voice)
        rset = MemSetting('settings.voice', 'Voice Prompts', rs)
        rset.set_doc('Radio Voice Prompts spoken language')
        basic.append(rset)

        # TOT
        rs = RadioSettingValueList(self._tot_list,
                                   current_index=_settings.tot)
        rset = MemSetting('settings.tot', 'Time Out Timer', rs)
        rset.set_doc('Radio TX Time Out Timer value')
        basic.append(rset)

        # VOX level
        rs = RadioSettingValueList(self._voxlevel_list,
                                   current_index=_settings.vox)
        rset = MemSetting('settings.vox', 'VOX Level', rs)
        rset.set_doc('Radio VOX Level senesitivity value')
        basic.append(rset)

        # Squelch level
        rs = RadioSettingValueList(self._squelchlevel_list,
                                   current_index=_settings.squelch)
        rset = MemSetting('settings.squelch', 'Squelch Level', rs)
        rset.set_doc('Radio Squelch Level value')
        basic.append(rset)

        # Sleep mode
        rs = RadioSettingValueList(self._sleepmode_list,
                                   current_index=_settings.sleep)
        rset = MemSetting('settings.sleep', 'Sleep Mode', rs)
        rset.set_doc('Radio Sleep Mode power saving ratio value')
        basic.append(rset)

        # Sidekey 1
        rs = RadioSettingValueList(self._sidekey_list,
                                   current_index=_settings.sidekey1)
        rset = MemSetting('settings.sidekey1', 'Sidekey 1 Long Pess', rs)
        rset.set_doc('Radio Sidekey 1 Long Press assigned action value')
        basic.append(rset)

        # Sidekey 2
        rs = RadioSettingValueList(self._sidekey_list,
                                   current_index=_settings.sidekey2)
        rset = MemSetting('settings.sidekey2', 'Sidekey 2 Long Press', rs)
        rset.set_doc('Radio Sidekey 2 Long Press assigned action value')
        basic.append(rset)

        # Selected default channel (setting not in factory CPS)
        rs = RadioSettingValueList(self._channel_list,
                                   current_index=_settings.channel)
        rset = MemSetting('settings.channel', 'Default Channel', rs)
        rset.set_doc('Radio Channel that is selected by Default at power-on')
        basic.append(rset)

        # Selected default WX channel (setting not in factory CPS)
        rs = RadioSettingValueList(self._wxchannel_list,
                                   current_index=_settings.wxchannel)
        rset = MemSetting('settings.wxchannel', 'Default WX Channel', rs)
        rset.set_doc('NOAA Weather Channel that is '
                     'selected by Default at power-on')
        basic.append(rset)

        return group

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a BETA version ONLY for the TIDRADIO '
             'TD-M11 22 running Firmware v0.9.4\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
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
        rf = get_default_features(self)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_modes = ['FM', 'NFM']  # 25kHz, 12.5kHz
        rf.valid_tuning_steps = self._steps
        rf.has_name = False
        return rf

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number - 1]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if _mem.get_raw()[:1] == b'\xFF':
            mem.empty = True
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        if mem.freq == 0:
            mem.empty = True
        # tx freq can be blank
        if _mem.txfreq.get_raw() == b'\xFF\xFF\xFF\xFF':
            # TX freq not set
            mem.offset = 0
            mem.duplex = 'off'
        else:
            # TX freq set
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

        txtone = rxtone = None
        txtone = self._decode_tone(int(_mem.txtone))
        rxtone = self._decode_tone(int(_mem.rxtone))
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        if not _mem.scan:
            mem.skip = 'S'

        try:
            mem.power = self._power_levels[_mem.txpower]
        except IndexError:
            LOG.error('Channel %d: get_memory: unhandled power level: 0x%02x' %
                      (mem.number, _mem.txpower))

        mem.mode = _mem.narrow and 'NFM' or 'FM'

        mem.extra = RadioSettingGroup('Extra', 'extra')

        # BCL (Busy Channel Lockout)
        rs = RadioSettingValueList(self._bcl_list,
                                   current_index=_mem.bcl)
        rset = RadioSetting('bcl', 'BCL', rs)
        mem.extra.append(rset)

        # Jump Freq
        rs = RadioSettingValueList(
            self._jumpfreq_list,
            current_index=_mem.jumpfreq)
        rset = RadioSetting('jumpfreq', 'Jump Freq', rs)
        mem.extra.append(rset)

        # Compand
        rs = RadioSettingValueList(
            self._compand_list,
            current_index=_mem.compand)
        rset = RadioSetting('compand', 'Compand', rs)
        mem.extra.append(rset)

        # Scramble
        rs = RadioSettingValueList(self._scramble_list,
                                   current_index=_mem.scramble)
        rset = RadioSetting('scramble', 'Scramble', rs)
        mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            _mem.set_raw('\xff' * 16)
            return

        _mem.set_raw('\x00' * 16)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == 'off':
            _mem.txfreq.fill_raw(b'\xFF')
        elif mem.duplex == 'split':
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == '+':
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == '-':
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)

        _mem.scan = mem.skip != 'S'
        _mem.narrow = mem.mode == 'NFM'

        try:
            _mem.txpower = self._power_levels.index(mem.power)
        except ValueError:
            LOG.error('Channel %d: set_memory: unhandled power level: %s' %
                      (mem.number, mem.power))

        try:
            _mem.narrow = self.get_features().valid_modes.index(mem.mode)
        except IndexError:
            LOG.error('Channel %d: set_memory: unhandled mode: %s' %
                      (mem.number, mem.mode))

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)
            if setting.has_apply_callback():
                # use callbacks on mem.extra
                # Radiosettings that need postprocessing
                setting.run_apply_callback()

    def set_settings(self, settings):
        # apply all Memsettings
        all_other_settings = settings.apply_to(self._memobj)
        for setting in all_other_settings:
            if setting.has_apply_callback():
                # use callbacks on Radiosettings that need postprocessing
                setting.run_apply_callback()

    def process_mmap(self):
        mem_format = MEM_FORMAT % self._mem_params
        self._memobj = bitwise.parse(mem_format, self._mmap)

    @classmethod
    def match_model(cls, filedata, filename):
        if filename.lower().endswith('.mdt') and \
                filedata.startswith(cls._mdt_file_header):
            return True
        else:
            return False


@directory.register
@directory.detected_by(TDM11_22)
class TDM11_16(TDM11_22):
    # ==========
    # Notice to developers:
    # The TD-M11 16 for EU PMR446 support in this driver is currently based
    # on Firmware v0.9.5 and v1.0.3
    # ==========
    """TIDRADIO TD-M11 16"""
    VENDOR = 'TIDRADIO'
    MODEL = 'TD-M11'
    VARIANT = '16 PMR'

    # same freq range as ODMaster allows
    VALID_BANDS = [(136000000, 174000001), (400000000, 520000001),]
    _power_levels = [
        chirp_common.PowerLevel('Low', watts=0.50),
        chirp_common.PowerLevel('High', watts=2.00)
    ]

    _upper = 16
    _mem_params = (_upper)

    _magic_list = [b'STD-M12\xff',  # firmware 1.0.3
                   b'STD-M11\xff',  # firmware 0.9.5
                   ]
    _magic = ''
    _fingerprint = [
        b'\x00\x40\x00\x52\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
        ]
    _mdt_file_header = b'TD-M11CLIENT'
    _mdt_offset = len(_mdt_file_header)  # offset of data in OEM .mdt file
    _steps = [5.0, 6.25, 12.5]
    _channel_list = ['%d' % x for x in range(1, _upper + 1)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is a BETA version ONLY for the TIDRADIO '
             'TD-M11 16 PMR running Firmware v0.9.5 or v1.0.3\n'
             '\n'
             'Please save an unedited copy of your first successful\n'
             'download to a CHIRP Radio Images(*.img) file.\n\n'
             'PROCEED AT YOUR OWN RISK!'
             )
        return rp
