# Copyright 2026 FT-8000 driver contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""FT-8000 clone transport and memory editing.

Validated with a physical radio and CH340 cable: 1860 bytes, 9600 8N2,
individual byte writes with 10 ms requested gaps and cable echo. The generic
Yaesu ACK/block transport is not applicable. Unmapped settings stay opaque.
"""

import logging
import time

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import (MemSetting, RadioSetting, RadioSettingGroup,
                            RadioSettings, RadioSettingValueMap,
                            RadioSettingValueBoolean, RadioSettingValueList,
                            RadioSettingValueString)


LOG = logging.getLogger(__name__)
IMAGE_SIZE = 1860
HEADER = bytes.fromhex('00 01 26 21 00')
SENTINELS = {'Left': 145000000, 'Right': 433000000}
TONES = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5,
         91.5, 94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8,
         118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2, 151.4,
         156.7, 162.2, 167.9, 173.8, 179.9, 186.2, 192.8, 203.5,
         210.7, 218.1, 225.7, 233.6, 241.8, 250.3]
DUPLEXES = ['', '+', '-', 'split']
TMODES = ['', 'Tone', 'TSQL']
SPECIALS = ['1L', '1U', '2L', '2U', 'HOME', 'VFO']

RECORD_FORMAT = """
struct channel {
  u8 masked:1,
     skip:1,
     duplex:2,
     tx_step:2,
     rx_step:2;
  u8 tone_mode:2,
     tone:6;
  u24 freq;
  u24 offset;
  u8 power:2,
     unknown1:3,
     bell:1,
     am:1,
     unknown2:1;
};
"""

MEM_FORMAT = RECORD_FORMAT + """
struct controls {
  u8 unknown1:3,
     scan:1,
     unknown2:2,
     ars:1,
     search:1;
};
struct autodial {
  u8 count;
  u8 digits[16];
};
struct band_state {
  u8 memory_mode:1,
     memory_tune:1,
     home_mode:1,
     unknown2:5;
  u8 unknown3;
  struct controls control;
  u8 unknown4[3];
  struct channel working;
  struct channel vfo;
  struct channel home;
  u8 current_memory;
  u8 unknown5[6];
  struct autodial dtmf;
  u8 unknown6[33];
  u8 rf_sql;
  u8 unknown7[4];
};
u8 header[5];
#seekto 0x000B;
struct {
  u8 panel_lock:1,
     key_beep:1,
     unknown1:1,
     same_band:1,
     unknown2:1,
     vhf_pair:1,
     sub_off:1,
     unknown3:1;
  u8 unknown4:4,
     dtmf_beep:1,
     unknown5:1,
     sub_voltmeter:1,
     dtmf_speed:1;
  u16 tot;
  u8 dimmer;
  u8 unknown6:4,
     ibd:1,
     ptt_lock:1,
     unknown7:1,
     sub_mute:1;
  u8 mute_timeout;
  u8 apo;
  u8 volts_offset;
} settings;
#seekto 0x001B;
struct band_state right;
struct band_state right_saved;
#seekto 0x011B;
struct band_state left;
struct band_state left_saved;
#seekto 0x021F;
struct channel right_memory[50];
struct channel right_pms[4];
#seekto 0x0409;
struct channel left_memory[50];
struct channel left_pms[4];
#seekto 0x0743;
u8 checksum;
"""

# Path, label, encoded choices, displayed choices (None = boolean).
SETTINGS = [
    ('settings.apo', 'Auto power off', list(range(13)),
     ['Off'] + ['%i hour(s)' % i for i in range(1, 13)]),
    ('settings.tot', 'Transmit timeout', [i * 60 for i in range(61)],
     ['Off'] + ['%i minute(s)' % i for i in range(1, 61)]),
    ('settings.dimmer', 'Display brightness', list(range(8)),
     ['0 (darkest)', '1', '2', '3', '4', '5', '6', '7 (lightest)']),
    ('settings.mute_timeout', 'Reduced audio timeout', list(range(60)),
     ['%i minute(s)' % i for i in range(1, 61)]),
    ('settings.key_beep', 'Keypad beep', [1, 0], None),
    ('settings.dtmf_beep', 'DTMF beep', [0, 1], None),
    ('settings.ibd', 'Intelligent band display', [0, 1], None),
    ('settings.ptt_lock', 'PTT lock', [0, 1], None),
    ('settings.panel_lock', 'Panel lock', [0, 1], None),
    ('settings.dtmf_speed', 'DTMF speed', [0, 1],
     ['Low (5 digits/second)', 'High (9 digits/second)']),
    ('settings.sub_mute', 'Sub band mute', [0, 1], None),
    ('settings.volts_offset', 'DC voltmeter correction',
     [i & 0xFF for i in range(-30, 31)],
     ['%+.3f V' % (i * 0.066) for i in range(-30, 31)])]


def checksum(data):
    return (sum(data[5:-1]) ^ 0xA5) & 0xFF


def validate_image(data):
    if len(data) != IMAGE_SIZE:
        raise errors.RadioError('Expected 1860 bytes, received %i' % len(data))
    if data[:5] != HEADER:
        raise errors.RadioError(
            'Unrecognized FT-8000 header; this development driver currently '
            'supports only the hardware-verified header 00 01 26 21 00')
    if data[-1] != checksum(data):
        raise errors.RadioError('FT-8000 image checksum mismatch')


def decode_frequency(raw):
    freq = raw * 100
    return freq + 500 if freq % 10000 in (2000, 7000) else freq


def frequency_code(freq):
    if freq < 280000000 and freq % 5000 == 0:
        return 0
    if freq % 6250 == 0:
        return 1
    if freq >= 280000000 and freq % 10000 == 0:
        return 0
    # Code 1 also covers 2.5 kHz and UHF 5 kHz endings.
    return 1


@directory.register
class FT8000RRadio(chirp_common.CloneModeRadio):
    VENDOR = 'Yaesu'
    MODEL = 'FT-8000R'
    BAUD_RATE = 9600
    WANTS_DTR = False
    WANTS_RTS = True
    _memsize = IMAGE_SIZE

    @classmethod
    def get_prompts(cls):
        prompts = chirp_common.RadioPrompts()
        prompts.experimental = (
            'CTCSS decoding and bell require the optional FTS-22 board. '
            'These functions have not been verified on the test radio.')
        prompts.pre_download = (
            '1. Turn radio OFF. Connect the rear DATA cable.\n'
            '2. Hold <b>F/W</b> (FIRST button below the LCD) while\n'
            '   turning radio ON. Release when all segments blink.\n'
            '3. <b>After clicking OK</b>, wait for download progress.\n'
            '   Press <b>RPT</b> (THIRD button below the LCD) once.\n'
            '4. After completion, turn OFF, then ON normally.\n'
            '   Hold no buttons. Turn OFF before unplugging cable.\n')
        prompts.pre_upload = (
            '1. Turn radio OFF. Connect the rear DATA cable.\n'
            '2. Hold <b>F/W</b> (FIRST button below the LCD) while\n'
            '   turning radio ON. Release when all segments blink.\n'
            '3. Press <b>REV</b> (SECOND button below the LCD) once.\n'
            '   The display stops blinking; radio is ready to receive.\n'
            '4. Click OK. Wait about 25-35 seconds for upload.\n'
            '   Radio restarts on success. If needed, power OFF/ON\n'
            '   normally without holding any buttons.\n'
            'If ERR appears, stop transfer and repeat from step 1.\n')
        return prompts

    def get_features(self):
        features = chirp_common.RadioFeatures()
        features.has_sub_devices = not bool(self.VARIANT)
        features.memory_bounds = (1, 50)
        features.has_bank = False
        features.has_name = False
        features.valid_name_length = 0
        features.valid_characters = ''
        features.has_settings = not bool(self.VARIANT)
        features.has_tuning_step = False
        features.valid_tuning_steps = [5, 10, 12.5, 15, 20, 25, 50, 100, 2.5]
        features.has_nostep_tuning = False
        features.has_ctone = False
        features.has_dtcs = False
        features.has_dtcs_polarity = False
        features.can_delete = True
        features.valid_tmodes = list(TMODES)
        features.valid_tones = list(TONES)
        features.valid_skips = ['', 'S']
        features.valid_modes = ['FM', 'AM']
        features.valid_duplexes = ['', '+', '-', 'split']
        features.can_odd_split = True
        features.valid_power_levels = self._power_levels()
        features.valid_special_chans = list(SPECIALS)
        features.valid_bands = ([(110000000, 280000000)]
                                if self.VARIANT == 'Left' else
                                [(280000000, 550000000),
                                 (750000000, 1000000000)])
        return features

    def _power_levels(self):
        return [chirp_common.PowerLevel('High', watts=(
                    50 if self.VARIANT == 'Left' else 35)),
                chirp_common.PowerLevel('Mid', watts=10),
                chirp_common.PowerLevel('Low', watts=5)]

    def get_sub_devices(self):
        return [FT8000RLeftRadio(self._mmap), FT8000RRightRadio(self._mmap)]

    def process_mmap(self):
        validate_image(self._mmap.get_packed())
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def _inactive_side(self):
        if not self._memobj.settings.same_band:
            return None
        return 'right' if self._memobj.settings.vhf_pair else 'left'

    def _saved_states(self):
        # Same-band reception uses both live receivers for one band. The
        # inactive band's state is preserved in two matching saved blocks.
        side = self._inactive_side()
        if side is None:
            return []
        other = 'left' if side == 'right' else 'right'
        return [getattr(self._memobj, s + '_saved') for s in (side, other)]

    def _working_records(self, number):
        side = self.VARIANT.lower()
        if side == self._inactive_side():
            states = self._saved_states()
        else:
            sides = (('left', 'right')
                     if self._inactive_side() and number != 56 else (side,))
            states = [getattr(self._memobj, s) for s in sides]
        working = []
        for state in states:
            if state.memory_tune:
                continue
            if state.home_mode:
                selected = 55
            elif state.memory_mode:
                selected = int(state.current_memory) + 1
            else:
                selected = 56
            if selected == number:
                working.append(state.working)
        return working

    def _get_record(self, number):
        number = self._memory_number(number)
        side = self.VARIANT.lower()
        if 1 <= number <= 50:
            return getattr(self._memobj, side + '_memory')[number - 1]
        if 51 <= number <= 54:
            return getattr(self._memobj, side + '_pms')[number - 51]
        if number in (55, 56):
            if side == self._inactive_side():
                state = self._saved_states()[0]
            else:
                state = getattr(self._memobj, side)
            return state.home if number == 55 else state.vfo
        raise errors.InvalidMemoryLocation('Unknown FT-8000 memory')

    @staticmethod
    def _memory_number(number):
        if isinstance(number, str) and number in SPECIALS:
            return 51 + SPECIALS.index(number)
        if not isinstance(number, int):
            raise errors.InvalidMemoryLocation('Unknown FT-8000 memory')
        return number

    @staticmethod
    def _memory_extra(record, empty=False):
        extra = RadioSettingGroup('extra', 'Extra')
        extra.append(MemSetting('bell', 'CTCSS bell (requires TSQL/FTS-22)',
                                RadioSettingValueBoolean(
                                    False if empty else record.bell)))
        extra.append(MemSetting(
            'masked', 'Masked (hidden on radio)',
            RadioSettingValueBoolean(False if empty else record.masked)))
        return extra

    def get_memory(self, number):
        record = self._get_record(number)
        number = self._memory_number(number)
        rx = int(record.freq) * 100
        used = rx and (not record.masked or rx != SENTINELS[self.VARIANT])
        if number >= 55:
            used = bool(rx)
        memory = chirp_common.Memory(number, empty=not bool(used))
        memory.extra = self._memory_extra(record, empty=memory.empty)
        if number > 50:
            memory.extd_number = SPECIALS[number - 51]
        if number >= 55:
            memory.immutable = ['empty']
            memory.extra['masked'].value.set_mutable(False)
        if not used:
            return memory
        memory.freq = decode_frequency(int(record.freq))
        memory.duplex = DUPLEXES[int(record.duplex)]
        memory.offset = (decode_frequency(int(record.offset))
                         if memory.duplex == 'split' else
                         int(record.offset) * 100)
        memory.mode = 'AM' if record.am else 'FM'
        memory.tmode = {0: '', 1: 'Tone', 2: '', 3: 'TSQL'}[
            int(record.tone_mode)]
        if int(record.tone) < len(TONES):
            memory.rtone = TONES[int(record.tone)]
        else:
            LOG.warning('Unknown FT-8000 tone index %i in %s memory %i',
                        int(record.tone), self.VARIANT, number)
        memory.skip = 'S' if record.skip else ''
        memory.power = self._power_levels()[
            int(record.power) if int(record.power) < 3 else 0]
        return memory

    def _update_checksum(self):
        self._memobj.checksum = checksum(self._mmap.get_packed())

    def set_memory(self, memory):
        record = self._get_record(memory.number)
        existing = self.get_memory(memory.number)
        self.check_set_memory_immutable_policy(existing, memory)
        if memory.empty:
            record.masked = True
            record.freq = SENTINELS[self.VARIANT] // 100
            self._update_checksum()
            return

        # The LCD uses a separate working record. Update only receivers whose
        # mode and channel index select this memory, even if others match it.
        working = self._working_records(memory.number)

        tx = memory.freq
        if memory.duplex == '+':
            tx += memory.offset
        elif memory.duplex == '-':
            tx -= memory.offset
        elif memory.duplex == 'split':
            tx = memory.offset
        record.freq = memory.freq // 100
        record.offset = memory.offset // 100
        record.duplex = DUPLEXES.index(memory.duplex)
        record.rx_step = frequency_code(memory.freq)
        record.tx_step = frequency_code(tx)
        record.am = memory.mode == 'AM'
        record.tone_mode = {'': 0, 'Tone': 1, 'TSQL': 3}[memory.tmode]
        record.tone = TONES.index(memory.rtone)
        record.skip = memory.skip == 'S'
        record.power = (self._power_levels().index(memory.power)
                        if memory.power else 0)
        record.masked = False
        record.bell = False
        if memory.extra:
            for setting in memory.extra:
                setting.apply_to_memobj(record)
        if memory.tmode != 'TSQL':
            record.bell = False
        for item in working:
            item.set_raw(record.get_raw())
        if memory.number in (55, 56):
            if self.VARIANT.lower() == self._inactive_side():
                for state in self._saved_states():
                    item = state.home if memory.number == 55 else state.vfo
                    item.set_raw(record.get_raw())
            elif memory.number == 55 and self._inactive_side():
                for side in ('left', 'right'):
                    getattr(self._memobj, side).home.set_raw(
                        record.get_raw())
        self._update_checksum()

    def get_raw_memory(self, number):
        return repr(self._get_record(number))

    def _settings_schema(self):
        schema = list(SETTINGS)
        for side in ('left', 'right'):
            label = side.title()
            control = (side + '_saved.control'
                       if side == self._inactive_side() else side + '.control')
            squelch = (side + '_saved.rf_sql'
                       if side == self._inactive_side() else side + '.rf_sql')
            schema.extend([
                (control + '.ars', label + ' auto repeater shift',
                 [0, 1], None),
                (control + '.search', label + ' smart search',
                 [0, 1], ['One time', 'Continuous']),
                (control + '.scan', label + ' scan resume',
                 [0, 1], ['Carrier drop', '5 seconds']),
                (squelch, label + ' RF squelch',
                 [0, 2, 4, 6, 11], ['Off', '2 units', '4 units', '6 units',
                                    'Full scale'])])
        return schema

    def get_settings(self):
        common = RadioSettingGroup('common', 'Radio settings')
        for path, label, values, labels in self._settings_schema():
            field = self._memobj
            for part in path.split('.'):
                field = getattr(field, part)
            raw = int(field)
            if raw not in values:
                value = RadioSettingValueString(0, 64, 'Unknown: 0x%X' % raw)
                value.set_mutable(False)
                setting = RadioSetting(path.replace('.', '_'), label, value)
            elif labels is None:
                value = RadioSettingValueBoolean(
                    bool(values.index(raw)), mem_vals=values)
                setting = MemSetting(path, label, value)
            else:
                value = RadioSettingValueMap(list(zip(labels, values)),
                                             mem_val=raw)
                setting = MemSetting(path, label, value)
            common.append(setting)
        obj = self._memobj.settings
        mode = (0 if not obj.same_band else 1 if obj.vhf_pair else 2)
        value = RadioSettingValueString(
            0, 32, ['VHF/UHF', 'VHF/VHF', 'UHF/UHF'][mode])
        value.set_mutable(False)
        common.append(RadioSetting('receive_mode', 'Receive mode', value))
        sub_mode = (0 if not obj.sub_off else
                    2 if obj.sub_voltmeter else 1)
        common.append(RadioSetting(
            'sub_operation', 'Sub band operation', RadioSettingValueList(
                ['On', 'Off', 'Voltmeter'], current_index=sub_mode)))
        dtmf = RadioSettingGroup('dtmf', 'DTMF autodial')
        for side in ('left', 'right'):
            obj = (self._saved_states()[0].dtmf
                   if side == self._inactive_side() else
                   getattr(self._memobj, side).dtmf)
            count = int(obj.count)
            digits = [int(x) for x in obj.digits[0:min(count, 16)]]
            if count <= 16 and all(x <= 16 for x in digits):
                text = ''.join('0123456789ABCD*#P'[x] for x in digits)
                value = RadioSettingValueString(0, 16, text, autopad=False)
                value.set_charset('0123456789ABCD*#P')
            else:
                value = RadioSettingValueString(
                    0, 80, 'Unknown: ' + bytes(digits).hex())
                value.set_mutable(False)
            dtmf.append(RadioSetting(side + '_dtmf', side.title() +
                                     ' DTMF digits (P = pause)', value))
        return RadioSettings(common, dtmf)

    def set_settings(self, settings):
        # Direct settings use MemSetting. Only multi-field/encoded settings
        # need special handling.
        obj = self._memobj
        for setting in settings.apply_to(obj):
            if not setting.changed():
                continue
            name = setting.get_name()
            if name == 'sub_operation':
                index = int(setting.value)
                obj.settings.sub_off = bool(index)
                obj.settings.sub_voltmeter = index == 2
            elif name in ('left_dtmf', 'right_dtmf'):
                digits = str(setting.value).strip().upper()
                dtmf = (self._saved_states()[0].dtmf
                        if name == str(self._inactive_side()) + '_dtmf' else
                        getattr(obj, name[:-5]).dtmf)
                dtmf.count = len(digits)
                dtmf.digits = (['0123456789ABCD*#P'.index(x) for x in digits] +
                               [16] * (16 - len(digits)))
            else:
                raise errors.InvalidValueError('Unsupported setting: ' + name)
        saved = self._saved_states()
        if saved:
            source, mirror = saved
            for field in ('ars', 'search', 'scan'):
                setattr(mirror.control, field, getattr(source.control, field))
            mirror.rf_sql = source.rf_sql
            mirror.dtmf.set_raw(source.dtmf.get_raw())
        self._update_checksum()

    def _configure_pipe(self):
        self.pipe.bytesize = 8
        self.pipe.parity = 'N'
        self.pipe.stopbits = 2
        self.pipe.xonxoff = False
        self.pipe.dsrdtr = False
        self.pipe.timeout = 3

    def _status(self, message, count):
        status = chirp_common.Status()
        status.msg = message
        status.cur = count
        status.max = IMAGE_SIZE
        self.status_fn(status)

    def sync_in(self):
        try:
            self._download()
        except errors.RadioError:
            raise
        except Exception as error:
            LOG.exception('FT-8000R download failed')
            raise errors.RadioError('Download failed: %s' % error) from error

    def _download(self):
        self._configure_pipe()
        # Yaesu requires the operator to start the transfer. Keep the same
        # serial timeout throughout: changing it may flush received data.
        for attempt in range(20):
            first = self.pipe.read(1)
            if first:
                break
        else:
            raise errors.RadioNoResponse()
        header = first + self.pipe.read(len(HEADER) - 1)
        # Some captures have this fixed two-byte preamble. Read its remaining
        # bytes directly; do not scan or poll an asynchronous receive buffer.
        prefix = b''
        if header.startswith(b'\x00\xfc'):
            prefix = header[:2]
            header = header[2:] + self.pipe.read(2)
        if header != HEADER:
            raise errors.RadioError(
                'Unrecognized or incomplete FT-8000 header')
        self._metadata['ft8000_download_prefix'] = prefix.hex()
        data = bytearray(header)
        self._status('Downloading from FT-8000', len(data))
        while len(data) < IMAGE_SIZE:
            count = min(64, IMAGE_SIZE - len(data))
            chunk = self.pipe.read(count)
            if len(chunk) != count:
                raise errors.RadioError('Incomplete FT-8000 download')
            data.extend(chunk)
            self._status('Downloading from FT-8000', len(data))
        validate_image(data)
        # No per-block or final ACK: passive download is hardware-verified.
        self._mmap = memmap.MemoryMapBytes(bytes(data))
        self.process_mmap()

    def _write_echo(self, value):
        # CHIRP's SerialTrace wrapper currently discards Serial.write's count.
        # In that case the required matching one-byte echo confirms the write.
        count = self.pipe.write(value)
        if count is not None and count != 1:
            raise errors.RadioError('Incomplete serial write; upload stopped')
        self.pipe.flush()
        echo = self.pipe.read(1)
        if not echo:
            raise errors.RadioError('Missing cable echo; upload stopped')
        if echo != value:
            raise errors.RadioError('Unexpected cable echo; upload stopped')

    def sync_out(self):
        try:
            self._upload()
        except errors.RadioError:
            raise
        except Exception as error:
            LOG.exception('FT-8000R upload failed')
            raise errors.RadioError('Upload failed: %s' % error) from error

    def _upload(self):
        data = self._mmap.get_packed()
        validate_image(data)  # Before touching the serial port.
        self._configure_pipe()
        self._status('Uploading to FT-8000', 0)
        for index, value in enumerate(data):
            time.sleep(0.150 if index == 0 else 0.010)
            self._write_echo(bytes([value]))
            if index % 16 == 0 or index == IMAGE_SIZE - 1:
                self._status('Uploading to FT-8000', index + 1)
        time.sleep(0.150)
        self._write_echo(b'\x06')
        LOG.info('FT-8000 writes and echo complete; '
                 'verify radio display/readback')


class FT8000RLeftRadio(FT8000RRadio):
    VARIANT = 'Left'


class FT8000RRightRadio(FT8000RRadio):
    VARIANT = 'Right'
