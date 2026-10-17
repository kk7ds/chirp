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

from chirp import chirp_common, directory, errors, memmap
from chirp.settings import (RadioSetting, RadioSettingGroup, RadioSettings,
                            RadioSettingValueBoolean, RadioSettingValueList,
                            RadioSettingValueString)


LOG = logging.getLogger(__name__)
IMAGE_SIZE = 1860
HEADER = bytes.fromhex('00 01 26 21 00')
MEMORY_BASES = {'Left': 0x409, 'Right': 0x21F}
WORKING_BASES = {'Left': 0x121, 'Right': 0x21}
SENTINELS = {'Left': 145000000, 'Right': 433000000}
TONES = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5,
         91.5, 94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8,
         118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2, 151.4,
         156.7, 162.2, 167.9, 173.8, 179.9, 186.2, 192.8, 203.5,
         210.7, 218.1, 225.7, 233.6, 241.8, 250.3]
DUPLEXES = ['', '+', '-', 'split']
TMODES = ['', 'Tone', 'TSQL']
SPECIALS = ['1L', '1U', '2L', '2U', 'HOME', 'VFO']
SPECIAL_BASES = {'Left': [0x5CB, 0x5D4, 0x5DD, 0x5E6, 0x133, 0x121],
                 'Right': [0x3E1, 0x3EA, 0x3F3, 0x3FC, 0x33, 0x21]}

# name, label, offset, mask, encoded choices, displayed choices (None = bool).
# Unmapped fields are retained when applying these settings.
SETTINGS = [
    ('apo', 'Auto power off', 0x12, 0xFF, list(range(13)),
     ['Off'] + ['%i hour(s)' % i for i in range(1, 13)]),
    ('tot', 'Transmit timeout', 0xD, 0xFFFF, [i * 60 for i in range(61)],
     ['Off'] + ['%i minute(s)' % i for i in range(1, 61)]),
    ('dimmer', 'Display brightness', 0xF, 0xFF, list(range(8)),
     ['0 (darkest)', '1', '2', '3', '4', '5', '6', '7 (lightest)']),
    ('mute_timeout', 'Reduced audio timeout', 0x11, 0xFF, list(range(60)),
     ['%i minute(s)' % i for i in range(1, 61)]),
    ('key_beep', 'Keypad beep', 0xB, 0x40, [0x40, 0], None),
    ('dtmf_beep', 'DTMF beep', 0xC, 8, [0, 8], None),
    ('ibd', 'Intelligent band display', 0x10, 8, [0, 8], None),
    ('ptt_lock', 'PTT lock', 0x10, 4, [0, 4], None),
    ('panel_lock', 'Panel lock', 0xB, 0x80, [0, 0x80], None),
    ('dtmf_speed', 'DTMF speed', 0xC, 1, [0, 1],
     ['Low (5 digits/second)', 'High (9 digits/second)']),
    ('sub_mute', 'Sub band mute', 0x10, 1, [0, 1], None),
    ('volts_offset', 'DC voltmeter correction', 0x13, 0xFF,
     [i & 0xFF for i in range(-30, 31)],
     ['%+.3f V' % (i * 0.066) for i in range(-30, 31)])]


def encode_frequency(freq):
    if not isinstance(freq, int) or not 0 <= freq <= 0xFFFFFF * 100:
        raise errors.InvalidValueError('Frequency is outside the image range')
    encoded = (freq // 100).to_bytes(3, 'big')
    if decode_frequency(encoded) != freq:
        raise errors.InvalidValueError('Frequency cannot be encoded exactly')
    return encoded


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
    freq = int.from_bytes(raw, 'big') * 100
    return freq + 500 if freq % 10000 in (2000, 7000) else freq


def frequency_code(freq):
    if freq < 280000000 and freq % 5000 == 0:
        return 0
    if freq % 6250 == 0:
        return 1
    if freq >= 280000000 and freq % 10000 == 0:
        return 0
    # The vendor converter returns 5 for these frequencies, then masks the
    # result to two bits. This is also code 1, including UHF 5 kHz endings.
    if freq % 2500 == 0:
        return 1
    raise errors.InvalidValueError('Unsupported FT-8000 frequency grid')


class FT8000REarlyAlias(chirp_common.Alias):
    """Read images saved under the initial development model name."""
    VENDOR = 'Yaesu'
    MODEL = 'FT-8000'


@directory.register
class FT8000RRadio(chirp_common.CloneModeRadio):
    VENDOR = 'Yaesu'
    MODEL = 'FT-8000R'
    ALIASES = [FT8000REarlyAlias]
    BAUD_RATE = 9600
    WANTS_DTR = False
    WANTS_RTS = True
    _memsize = IMAGE_SIZE

    @classmethod
    def get_prompts(cls):
        prompts = chirp_common.RadioPrompts()
        prompts.experimental = (
            'Development driver. Frequency upload/download is radio-tested; '
            'additional memory fields are under hardware validation. '
            'CTCSS decoding requires the optional FTS-22 board.')
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
        features.valid_tuning_steps = []
        features.has_nostep_tuning = True
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
        devices = [FT8000RLeftRadio(self._mmap), FT8000RRightRadio(self._mmap)]
        for device in devices:
            device.MODEL = self.MODEL
        return devices

    def validate_memory(self, memory):
        messages = super().validate_memory(memory)
        if memory.empty:
            return messages
        tx = memory.freq
        if memory.duplex == '+':
            tx += memory.offset
        elif memory.duplex == '-':
            tx -= memory.offset
        elif memory.duplex == 'split':
            tx = memory.offset
        try:
            for freq in (memory.freq, tx):
                encode_frequency(freq)
                frequency_code(freq)
        except errors.InvalidValueError as error:
            messages.append(chirp_common.ValidationError(str(error)))
        return messages

    def process_mmap(self):
        validate_image(self._mmap.get_packed())

    def _record_offset(self, number):
        if self.VARIANT not in MEMORY_BASES:
            raise errors.InvalidValueError('Select the Left or Right tab')
        number = self._memory_number(number)
        if 51 <= number <= 56:
            return SPECIAL_BASES[self.VARIANT][number - 51]
        if not 1 <= number <= 50:
            raise errors.InvalidMemoryLocation('Unknown FT-8000 memory')
        return MEMORY_BASES[self.VARIANT] + (number - 1) * 9

    @staticmethod
    def _memory_number(number):
        if isinstance(number, str) and number in SPECIALS:
            return 51 + SPECIALS.index(number)
        if not isinstance(number, int):
            raise errors.InvalidMemoryLocation('Unknown FT-8000 memory')
        return number

    @staticmethod
    def _memory_extra(raw):
        extra = RadioSettingGroup('extra', 'Extra')
        extra.append(RadioSetting('bell', 'CTCSS bell (requires TSQL/FTS-22)',
                                  RadioSettingValueBoolean(bool(raw[8] & 4))))
        extra.append(RadioSetting(
            'masked', 'Masked (hidden on radio)',
            RadioSettingValueBoolean(bool(raw[0] & 0x80))))
        return extra

    def get_memory(self, number):
        offset = self._record_offset(number)
        number = self._memory_number(number)
        raw = self._mmap[offset:offset + 9]
        rx = int.from_bytes(raw[2:5], 'big') * 100
        used = rx and (not raw[0] & 0x80 or
                       rx != SENTINELS[self.VARIANT])
        if number >= 55:
            used = bool(rx)
        memory = chirp_common.Memory(number, empty=not bool(used))
        memory.extra = self._memory_extra(raw)
        if number > 50:
            memory.extd_number = SPECIALS[number - 51]
        if number >= 55:
            memory.extra['masked'].value.set_mutable(False)
        if not used:
            memory.immutable = []
            if number >= 55:
                memory.immutable.append('empty')
            return memory
        memory.freq = decode_frequency(raw[2:5])
        memory.duplex = DUPLEXES[(raw[0] >> 4) & 3]
        memory.offset = (decode_frequency(raw[5:8])
                         if memory.duplex == 'split' else
                         int.from_bytes(raw[5:8], 'big') * 100)
        memory.mode = 'AM' if raw[8] & 2 else 'FM'
        memory.tmode = {0: '', 1: 'Tone', 2: '', 3: 'TSQL'}[raw[1] >> 6]
        tone_index = raw[1] & 0x3F
        if tone_index < len(TONES):
            memory.rtone = TONES[tone_index]
        memory.skip = 'S' if raw[0] & 0x40 else ''
        power_index = raw[8] >> 6
        memory.power = self._power_levels()[
            power_index if power_index < 3 else 0]
        memory.immutable = []
        if number >= 55:
            memory.immutable.append('empty')
        if tone_index >= len(TONES):
            LOG.warning('Unknown FT-8000 tone index %i in %s memory %i',
                        tone_index, self.VARIANT, number)
            memory.immutable.append('rtone')
        return memory

    def set_memory(self, memory):
        offset = self._record_offset(memory.number)
        existing = self.get_memory(memory.number)
        self.check_set_memory_immutable_policy(existing, memory)
        fields = ['empty', 'freq', 'duplex', 'offset', 'mode', 'tmode',
                  'rtone', 'skip', 'power']
        changed = {field for field in fields
                   if getattr(existing, field) != getattr(memory, field)}
        extra = {setting.get_name(): bool(setting.value)
                 for setting in memory.extra} if memory.extra else {}
        old_extra = {setting.get_name(): bool(setting.value)
                     for setting in existing.extra}
        extra_changed = {key for key in extra
                         if extra[key] != old_extra.get(key)}
        if not changed and not extra_changed:
            return
        if existing.empty and memory.empty:
            return
        data = bytearray(self._mmap.get_packed())
        if data[0xB] & 0x10:
            raise errors.InvalidValueError(
                'Editing VHF/VHF or UHF/UHF images is not yet supported')
        old = bytes(data[offset:offset + 9])
        raw = bytearray(old)
        if memory.empty:
            # Vendor sentinel plus mask marks an unused slot. Keep other bits.
            raw[0] |= 0x80
            raw[2:5] = encode_frequency(SENTINELS[self.VARIANT])
            data[offset:offset + 9] = raw
            # Deleting a stored memory leaves the live VFO tuned as it was.
            data[-1] = checksum(data)
            self._mmap[0] = bytes(data)
            return
        if existing.empty:
            changed.update(fields)
            raw[0] &= 0x7F
        if not isinstance(memory.freq, int) or not any(
                lo <= memory.freq < hi
                for lo, hi in self.get_features().valid_bands):
            raise errors.InvalidValueError('Frequency outside this side band')
        if memory.duplex not in DUPLEXES or memory.mode not in ('AM', 'FM'):
            raise errors.InvalidValueError('Unsupported mode or duplex')
        if memory.tmode not in TMODES or memory.skip not in ('', 'S'):
            raise errors.InvalidValueError('Unsupported tone mode or skip')
        tx = memory.freq
        if memory.duplex == '+':
            tx += memory.offset
        elif memory.duplex == '-':
            tx -= memory.offset
        elif memory.duplex == 'split':
            tx = memory.offset
        if changed & {'freq', 'duplex', 'offset', 'empty'}:
            raw[2:5] = encode_frequency(memory.freq)
            # Offsets are integer 100 Hz units; split stores an actual TX.
            if not isinstance(memory.offset, int) or memory.offset < 0:
                raise errors.InvalidValueError('Invalid offset')
            if memory.duplex == 'split':
                raw[5:8] = encode_frequency(memory.offset)
            else:
                if memory.offset % 100 or memory.offset > 0xFFFFFF * 100:
                    raise errors.InvalidValueError('Offset needs 100 Hz units')
                raw[5:8] = (memory.offset // 100).to_bytes(3, 'big')
            raw[0] = ((raw[0] & 0xC0) |
                      DUPLEXES.index(memory.duplex) << 4 |
                      frequency_code(memory.freq) | frequency_code(tx) << 2)
        if 'mode' in changed:
            raw[8] = (raw[8] & ~2) | (2 if memory.mode == 'AM' else 0)
        if 'tmode' in changed:
            raw[1] = ((raw[1] & 0x3F) |
                      {'': 0, 'Tone': 0x40, 'TSQL': 0xC0}[memory.tmode])
            # A changed tone mode clears the vendor's separate bell flag.
            raw[8] &= ~4
        if 'rtone' in changed:
            if memory.rtone not in TONES:
                raise errors.InvalidValueError('Unsupported CTCSS frequency')
            raw[1] = (raw[1] & 0xC0) | TONES.index(memory.rtone)
        if 'skip' in changed:
            raw[0] = (raw[0] & ~0x40) | (0x40 if memory.skip else 0)
        if 'power' in changed:
            levels = self._power_levels()
            if memory.power is not None and memory.power not in levels:
                raise errors.InvalidValueError('Unsupported power level')
            index = levels.index(memory.power) if memory.power else 0
            raw[8] = (raw[8] & 0x3F) | index << 6
        if 'bell' in extra_changed:
            if extra['bell'] and memory.tmode != 'TSQL':
                raise errors.InvalidValueError('CTCSS bell requires TSQL')
            raw[8] = (raw[8] & ~4) | (4 if extra['bell'] else 0)
        if 'masked' in extra_changed:
            if memory.number >= 55:
                raise errors.InvalidValueError('HOME/VFO cannot be masked')
            raw[0] = (raw[0] & ~0x80) | (0x80 if extra['masked'] else 0)
        data[offset:offset + 9] = raw
        working = WORKING_BASES[self.VARIANT]
        if (memory.number != 56 and not existing.empty and
                data[working:working + 9] == old):
            original = self._mmap.get_packed()
            # Factory HOME and memory 1 are identical. Only duplicate regular
            # memories make a regular memory's working-copy match ambiguous.
            candidates = (range(1, 51) if memory.number <= 50 else
                          range(51, 56))
            matches = sum(original[self._record_offset(i):
                                   self._record_offset(i) + 9] == old
                          for i in candidates)
            if matches != 1:
                raise errors.InvalidValueError(
                    'Duplicate memories match the working channel; '
                    'active selection is ambiguous')
            data[working:working + 9] = data[offset:offset + 9]
        data[-1] = checksum(data)
        # Mutate the existing map so parent and both subdevices stay linked.
        self._mmap[0] = bytes(data)

    def get_raw_memory(self, number):
        offset = self._record_offset(number)
        return '%04X: %s' % (offset, self._mmap[offset:offset + 9].hex(' '))

    def _settings_schema(self):
        schema = list(SETTINGS)
        for side, offset, squelch in [('left', 0x11D, 0x175),
                                      ('right', 0x1D, 0x75)]:
            label = side.title()
            schema.extend([
                (side + '_ars', label + ' auto repeater shift', offset, 2,
                 [0, 2], None),
                (side + '_search', label + ' smart search', offset, 1,
                 [0, 1], ['One time', 'Continuous']),
                (side + '_scan', label + ' scan resume', offset, 0x10,
                 [0, 0x10], ['Carrier drop', '5 seconds']),
                (side + '_rf_sql', label + ' RF squelch', squelch, 0xFF,
                 [0, 2, 4, 6, 11], ['Off', '2 units', '4 units', '6 units',
                                    'Full scale'])])
        return schema

    def get_settings(self):
        data = self._mmap.get_packed()
        common = RadioSettingGroup('common', 'Radio settings')
        for item in self._settings_schema():
            name, label, offset, mask, values, labels = item
            size = 2 if mask > 0xFF else 1
            raw = int.from_bytes(data[offset:offset + size], 'big') & mask
            if raw not in values:
                value = RadioSettingValueString(0, 64, 'Unknown: 0x%X' % raw)
                value.set_mutable(False)
            elif labels is None:
                value = RadioSettingValueBoolean(bool(values.index(raw)))
            else:
                value = RadioSettingValueList(
                    labels, current_index=values.index(raw))
            common.append(RadioSetting(name, label, value))
        mode = (0 if not data[0xB] & 0x10 else
                1 if data[0xB] & 4 else 2)
        value = RadioSettingValueString(
            0, 32, ['VHF/UHF', 'VHF/VHF', 'UHF/UHF'][mode])
        value.set_mutable(False)
        common.append(RadioSetting('receive_mode', 'Receive mode', value))
        sub_mode = (0 if not data[0xB] & 2 else
                    2 if data[0xC] & 2 else 1)
        common.append(RadioSetting(
            'sub_operation', 'Sub band operation', RadioSettingValueList(
                ['On', 'Off', 'Voltmeter'], current_index=sub_mode)))
        dtmf = RadioSettingGroup('dtmf', 'DTMF autodial')
        for side, offset in [('left', 0x143), ('right', 0x43)]:
            count = data[offset]
            digits = data[offset + 1:offset + 1 + min(count, 16)]
            if count <= 16 and all(x <= 16 for x in digits):
                text = ''.join('0123456789ABCD*#P'[x] for x in digits)
                value = RadioSettingValueString(0, 16, text, autopad=False)
                value.set_charset('0123456789ABCD*#P')
            else:
                value = RadioSettingValueString(
                    0, 80, 'Unknown: ' + digits.hex())
                value.set_mutable(False)
            dtmf.append(RadioSetting(side + '_dtmf', side.title() +
                                     ' DTMF digits (P = pause)', value))
        return RadioSettings(common, dtmf)

    def set_settings(self, settings):
        data = bytearray(self._mmap.get_packed())
        schema = {item[0]: item[1:] for item in self._settings_schema()}

        def apply(group):
            for setting in group:
                if not isinstance(setting, RadioSetting):
                    apply(setting)
                    continue
                if not setting.changed():
                    continue
                name = setting.get_name()
                if name in schema:
                    label, offset, mask, values, labels = schema[name]
                    value = values[int(setting.value)]
                    size = 2 if mask > 0xFF else 1
                    old = int.from_bytes(data[offset:offset + size], 'big')
                    data[offset:offset + size] = (
                        (old & ~mask) | value).to_bytes(size, 'big')
                elif name == 'sub_operation':
                    index = int(setting.value)
                    data[0xB] = (data[0xB] & ~2) | (2 if index else 0)
                    data[0xC] = (data[0xC] & ~2) | (2 if index == 2 else 0)
                elif name in ('left_dtmf', 'right_dtmf'):
                    digits = str(setting.value).strip().upper()
                    if len(digits) > 16 or any(
                            x not in '0123456789ABCD*#P' for x in digits):
                        raise errors.InvalidValueError('Invalid DTMF digits')
                    offset = 0x143 if name == 'left_dtmf' else 0x43
                    data[offset] = len(digits)
                    data[offset + 1:offset + 17] = bytes(
                        ['0123456789ABCD*#P'.index(x) for x in digits] +
                        [16] * (16 - len(digits)))
                else:
                    raise errors.InvalidValueError(
                        'Unsupported setting: ' + name)
        apply(settings)
        if data != self._mmap.get_packed():
            data[-1] = checksum(data)
            self._mmap[0] = bytes(data)

    def _configure_pipe(self):
        self.pipe.baudrate = 9600
        self.pipe.bytesize = 8
        self.pipe.parity = 'N'
        self.pipe.stopbits = 2
        self.pipe.xonxoff = False
        self.pipe.rtscts = False
        self.pipe.dsrdtr = False
        self.pipe.dtr = False
        self.pipe.rts = True
        self.pipe.timeout = 0.1
        self.pipe.write_timeout = 5

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
        start = last = time.monotonic()
        pending = bytearray()
        data = bytearray()
        found = False
        while len(data) < IMAGE_SIZE:
            count = min(64, IMAGE_SIZE - len(data))
            chunk = self.pipe.read(count)
            now = time.monotonic()
            if chunk:
                last = now
                if not found:
                    pending.extend(chunk)
                    index = pending.find(HEADER)
                    if index >= 0:
                        if index > 32:
                            raise errors.RadioError(
                                'Excess data before header')
                        prefix = bytes(pending[:index])
                        if prefix:
                            LOG.warning('FT-8000 pre-header bytes: %s',
                                        prefix.hex())
                        self._metadata['ft8000_download_prefix'] = prefix.hex()
                        data.extend(pending[index:])
                        found = True
                    elif len(pending) > 32 + len(HEADER):
                        raise errors.RadioError('FT-8000 header not found')
                else:
                    data.extend(chunk)
                self._status('Downloading from FT-8000', len(data))
            if not found and now - start > 60:
                raise errors.RadioNoResponse()
            if found and now - last > 3:
                raise errors.RadioError('Incomplete FT-8000 download')
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
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            echo = self.pipe.read(1)
            if echo:
                if echo != value:
                    raise errors.RadioError(
                        'Unexpected cable echo; upload stopped')
                return
        raise errors.RadioError('Missing cable echo; upload stopped')

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
        if self.pipe.in_waiting:
            raise errors.RadioError(
                'Unexpected incoming data; rearm clone receive')
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
