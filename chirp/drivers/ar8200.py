# Copyright 2026 Darius Rad <alpha@area49.net>
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

import logging
import re
import threading
import time

from chirp import chirp_common, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingSubGroup, RadioSettingValueBoolean, RadioSettingValueFloat, \
    RadioSettingValueInteger, RadioSettingValueList, RadioSettingValueMap, \
    RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

# CHANNEL NUMBERING
#
# CHIRP identifies memories with sequentially numbered indices.  The
# memory locations in the AR8200 are mapped to CHIRP memories as
# follows.
#
# Memories 0 through 999
#
#   Scan memories by bank: A, a, B, b, ... J, j.  Each pair of banks
#   (A and a, B and b, etc.) occupies 100 channels.  The split between
#   the banks in the pair is determined by the bank size configured
#   under settings.
#
# Memories 1000 through 1999
#
#   Scan pass frequencies by bank: A, a, B, b, ... J, j.  There are 50
#   pass frequencies per bank.
#
# Memories 2000 through 2099
#
#   VFO pass frequencies.
#
# Memories 2100 through 2139
#
#   One channel per search bank: A through T, then a through t.
#
# Special channels
#
#   VFO: Single VFO mode channel configuration
#   VFO-A and VFO-B: Twin VFO mode channel configuration
#   QM0 through QM9: VFO quick memories

# ISSUES AND LIMITATIONS
#
# After adjusting any of the following settings, it is necessary to
# refresh certain other memory locations:
#
#  - Bank split size
#  - Add or remove search pass frequencies
#  - Change offset frequencies
#  - Removing channels from select scan list
#
# The radio supports three AM modes, but CHIRP only knows about two.
# Mode is set to AM for all, and an extra field specifies which AM
# mode is used.
#
# Search pass frequencies cannot be modified, they can only be added
# or removed.  When a pass frequency is removed, all others in the
# same search bank are moved up.
#
# This driver does not provide a bank model because (1) CHIRP does not
# support banks for live radios, and (2) the banks on the radio don't
# easily map to the bank model provided by CHIRP.
#
# Quick memory channel details beyond the frequency are not available,
# as reading this from the serial port is not supported.
#
# Adding to the select scan list is not supported over the serial
# port.
#
# Auto mode also lets the radio control duplex and offset, tuning
# step, and step adjust.
#
# Radio must be power cycled after using CHIRP.  The serial protocol
# supports a command to terminate the session and release the keypad,
# but there is no suitable place in CHIRP to make this call.  By the
# time the __del__ method is called, the serial port is already
# closed.
#
# Radio supports additional characters not presently reflected in the
# valid character set, including arrows, Japanese characters (yen,
# katakana), Greek letters, other European letters and accents, and
# math symbols.


@directory.register
class AR8200Radio(chirp_common.LiveRadio):
    """AOR AR8200"""
    BAUD_RATE = 19200
    VENDOR = "AOR"
    MODEL = "AR8200"

    # These need to match the indices of the MD command.
    _MODES = [('WFM', 0), ('FM', 1), ('AM', 2), ('USB', 3), ('LSB', 4),
              ('CW', 5), ('NFM', 6), ('WAM', 7), ('NAM', 8), ('Auto', 0xf)]

    _AM_MODES = ['AM', 'WAM', 'NAM']

    _SCAN_MEMORIES = 1000
    _SEARCH_PASS_MEMORIES = 1100
    _SCAN_BANKS = 'AaBbCcDdEeFfGgHhIiJj'
    _SEARCH_BANKS = 'ABCDEFGHIJKLMNOPQRSTabcdefghijklmnopqrst'

    _SPECIAL_CHANS = {
        'VFO': -13,
        'VFO-A': -12,
        'VFO-B': -11,
        'QM0': -10,
        'QM1': -9,
        'QM2': -8,
        'QM3': -7,
        'QM4': -6,
        'QM5': -5,
        'QM6': -4,
        'QM7': -3,
        'QM8': -2,
        'QM9': -1}

    # Skip reading settings that require selecting each stored memory
    # channel, which significantly slows download time.
    _SKIP_SELECT = False

    _upper = _SCAN_MEMORIES + _SEARCH_PASS_MEMORIES + len(_SEARCH_BANKS) - 1

    _scan_bank_sizes = {}
    _GS = None
    _OL_LIST = None
    _GR_LIST = None
    _command_cache = {}

    _rf = None

    def __init__(self, *args, **kwargs):
        chirp_common.LiveRadio.__init__(self, *args, **kwargs)

        self._memcache = {}
        self.LOCK = threading.Lock()

        if self.pipe:
            self.pipe.timeout = 2
            self.pipe.stopbits = 2
            self._pipe_reset()
            if not self._connect():
                raise Exception("Error connecting to radio")

            # set VFO mode because documentation says not to run MX
            # command (write data) while scanning or searching
            self._command('VF')

            # set squelch closed to avoid noise while changing channels
            self._command('MC1')

    def get_features(self):
        if self._rf:
            return self._rf

        rf = chirp_common.RadioFeatures()
        rf.has_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_cross = False
        rf.has_nostep_tuning = True
        rf.has_settings = True

        rf.valid_modes = ['WFM', 'FM', 'AM', 'USB', 'LSB', 'CW', 'NFM', 'Auto']
        rf.valid_bands = [(100000, 2040000000)]
        rf.valid_skips = ['', 'S']
        rf.valid_characters = chirp_common.CHARSET_ASCII
        rf.valid_name_length = 12
        rf.valid_special_chans = list(self._SPECIAL_CHANS.keys())
        rf.valid_tones = []

        rf.memory_bounds = (0, self._upper)

        self._rf = rf
        return rf

    def _decode_number(self, number):
        if number < -10:
            if number in list(self._SPECIAL_CHANS.values()):
                return ('vfo', None, number)

            return (None, None, None)

        if number < 0:
            return ('qm', None, number + 10)

        if number < self._SCAN_MEMORIES:
            bank = (number // 100) * 2
            chan = number % 100

            if chan >= self._scan_bank_size(self._SCAN_BANKS[bank]):
                chan = chan - self._scan_bank_size(self._SCAN_BANKS[bank])
                bank += 1

            return ('scan', self._SCAN_BANKS[bank], chan)

        number -= self._SCAN_MEMORIES

        if number < self._SEARCH_PASS_MEMORIES:
            if number > len(self._SEARCH_BANKS) * 50:
                bank = 'V'
                chan = number - len(self._SEARCH_BANKS) * 50
            else:
                bank = self._SEARCH_BANKS[number // 50]
                chan = number % 50
            return ('pass', bank, chan)

        number -= self._SEARCH_PASS_MEMORIES

        if number < len(self._SEARCH_BANKS):
            return ('search', self._SEARCH_BANKS[number], None)

        return (None, None, None)

    def _encode_number(self, region, bank, chan):

        if region == 'vfo':
            return self._SPECIAL_CHANS.get(chan, None)

        elif region == 'qm':
            return chan - 10 if chan < 10 else None

        elif region == 'scan':
            if bank not in self._SCAN_BANKS or \
               chan >= self._scan_bank_size(bank):
                return None

            offset = 100 * (self._SCAN_BANKS.index(bank) // 2)
            if bank.islower():
                offset += self._scan_bank_size(bank.upper())

            return offset + chan

        elif region == 'pass':
            if bank == 'V':
                offset = self._SCAN_MEMORIES + len(self._SEARCH_BANKS) * 50
                size = 100
            elif bank in self._SEARCH_BANKS:
                offset = self._SCAN_MEMORIES + \
                    self._SEARCH_BANKS.index(bank) * 50
                size = 50

            return offset + chan if chan < size else None

        elif region == 'search':
            if bank not in self._SEARCH_BANKS:
                return None

            return self._SCAN_MEMORIES + self._SEARCH_PASS_MEMORIES + \
                self._SEARCH_BANKS.index(bank)

        return None

    def _connect(self):
        """Connect to the radio"""
        bauds = [19200, 9600, 4800]

        for b in bauds:
            self.pipe.baudrate = b

            self._command('', '[?]')

            # no real detection mechanism, to just try the VR command
            res = self._command('VR', 'VR([0-9]+)')
            if res:
                return True

        raise errors.RadioError("No response from radio")

    def _pipe_reset(self):
        self.pipe.reset_input_buffer()
        self.pipe.reset_output_buffer()
        self.pipe.write('\r'.encode('ascii'))
        self.pipe.readline()

    def _command(self, cmd, pattern='$', lines=1, cache=False,
                 varlist=False, retries=5, timeout=None):
        retry_wait = .25
        cmd += '\r'
        old_timeout = None

        if timeout is not None:
            old_timeout = self.pipe.timeout
            self.pipe.timeout = timeout

        if cache:
            pattern = '([A-Za-z0-9]+) (?:(?P<empty>---)$|.*)'

        for retry in range(retries):
            self.pipe.write(cmd.encode('ascii'))
            LOG.debug("tx {}".format(cmd.strip()))

            for n in range(lines if cache else 1):
                res = self.pipe.readline().decode('ascii', errors='replace')
                res = res.strip()
                LOG.debug("rx {}".format(res))

                m = re.match(pattern, res)
                if not m:
                    LOG.error("Unexpected response from radio: {} -> {}"
                              "".format(cmd.strip(), res))
                    break

                if cache:
                    if varlist and m['empty']:
                        m = True
                        break

                    if m.lastindex > 0:
                        LOG.debug("command cache {} -> {}".format(m[1], m[0]))
                        self._command_cache[m[1]] = m[0]
            else:
                if cache:
                    m = True

                else:
                    for n in range(lines - 1):
                        res = self.pipe.readline().strip()
                        LOG.debug("rx {}".format(res))

            if m:
                break

            LOG.debug("Retrying...")
            time.sleep(retry_wait)
            retry_wait *= 2
            retry_wait = min(retry_wait, 5)
            self._pipe_reset()
        else:
            m = None

        if old_timeout is not None:
            self.pipe.timeout = old_timeout

        return m

    def _command_read_WM(self, bank, retries=5):
        retry_wait = .25

        cmd = 'WM{}\r'.format(bank)

        for n in range(retries):
            self.pipe.write(cmd.encode('ascii'))
            LOG.debug("tx {}".format(cmd.strip()))

            ret = ()
            for b in (bank, bank.lower()):
                res = self.pipe.readline().decode('ascii', errors='replace')
                res = res.strip()
                LOG.debug("rx {}".format(res))

                mat = re.match('WM ([A-Ja-j])([01])', res)
                if not mat or mat[1] != b:
                    LOG.error("Unexpected response from radio: {} -> {}"
                              "".format(cmd.strip(), res))
                    break

                ret += (bool(int(mat[2])),)
            else:
                return ret

            LOG.debug("Retrying...")
            time.sleep(retry_wait)
            retry_wait *= 2
            retry_wait = min(retry_wait, 5)
            self._pipe_reset()

        return None

    def _command_update_cache(self, cmd, lines=10, varlist=False, retries=5):
        return self._command(cmd=cmd, lines=lines, cache=True,
                             varlist=varlist, retries=retries)

    def _command_delete_cache(self, key, pattern=False):
        if not pattern:
            self._command_cache.pop(key, None)

        else:
            r = re.compile(key)
            for k in list(filter(r.match, self._command_cache.keys())):
                self._command_cache.pop(k, None)

    def _command_cached(self, key, pattern, retries=5):
        retry_wait = .25

        for n in range(retries):
            if key not in self._command_cache:
                cmd = re.match('(OL|MX|QM|GM|GS|PR|GR)', key)
                if not cmd:
                    LOG.debug("Response not found in cache: {}".format(key))
                    return None

                if cmd[1] == 'OL':
                    for n in range(5):
                        self._command_update_cache('OL')

                elif cmd[1] == 'MX':
                    bank = key[2]
                    size = self._scan_bank_size(bank)
                    self._command_update_cache('MA{}'.format(bank))
                    for n in range(-(size // -10) - 1):
                        self._command_update_cache('MA')

                elif cmd[1] == 'QM':
                    self._command_update_cache('QM')

                elif cmd[1] in ('GM', 'GS'):
                    self._command_update_cache(cmd[1], 2)

                elif cmd[1] == 'PR':
                    for n in range(100 if key[2] == 'V' else 50):
                        cachekey = '{}{:02d}'.format(key[:3], n)
                        val = '{} ---'.format(cachekey)
                        self._command_cache[cachekey] = val

                    self._command_update_cache(
                        key[:3], 100 if key[2] == 'V' else 50, varlist=True)

                elif cmd[1] == 'GR':
                    self._command_update_cache('GR', 100, varlist=True)

                else:
                    LOG.debug("Response not found in cache: {}".format(key))
                    return None

            if key in self._command_cache:
                res = re.match(pattern, self._command_cache[key])
                if res:
                    return res

                LOG.debug("Unexpected result from radio {}"
                          "".format(self._command_cache[key]))
                del self._command_cache[key]
            else:
                LOG.debug("Response not found in cache: {}".format(key))

            LOG.debug("Retrying...")
            time.sleep(retry_wait)
            retry_wait *= 2

        return None

    def _scan_bank_size(self, bank):
        if bank not in self._SCAN_BANKS:
            return None

        if bank.upper() not in self._scan_bank_sizes:
            res = self._command('MW{}'.format(bank.upper()),
                                'MW [A-J]:([1-9]0) [a-j]:([1-9]0)')
            self._scan_bank_sizes[bank.upper()] = int(res[1])

        if bank.isupper():
            return self._scan_bank_sizes[bank]
        else:
            return 100 - self._scan_bank_sizes[bank.upper()]

    def _get_ol_list(self):
        if self._OL_LIST:
            return self._OL_LIST

        self._OL_LIST = [0]
        for n in range(1, 48):
            res = self._command_cached('OL{:02d}'.format(n),
                                       'OL([0-4][0-9]) RF(0[0-9]{7}00)')

            if n != int(res[1]):
                raise errors.RadioError(
                    "Unexpected result returned from radio")

            self._OL_LIST.append(int(res[2]))
            LOG.info("Offset frequency {} is {}".format(n, res[2]))

        return self._OL_LIST

    def _set_pp(self, number):
        (region, bank, chan) = self._decode_number(number)
        self._command('PP{}{:02d}'.format(bank, chan))

    def _get_gr_list(self):
        if isinstance(self._GR_LIST, list):
            return self._GR_LIST

        self._GR_LIST = []

        for n in range(100):
            res = self._command_cached(
                'GR{:02d}'.format(n),
                ('GR(?P<num>[0-9]{2}) (?:(?P<empty>---)$|'
                 'MX(?P<bank>[A-Ja-j])(?P<chan>[0-9]{2}))'))
            if not res:
                break

            if n != int(res['num']):
                raise errors.RadioError(
                    "Unexpected result returned from radio")

            self._GR_LIST.append((res['bank'], int(res['chan'])))
            LOG.info("Select scan entry {} is {}{:02d}"
                     "".format(n, res['bank'], int(res['chan'])))

        return self._GR_LIST

    def _save_gs(self):
        if self._GS:
            return

        res = self._command('GS', 'GS([0-9])', 2)
        self._GS = int(res[1])

    def _restore_gs(self):
        self._command('GS{}'.format(self._GS))

    def _invalidate_scan_bank_size(self):
        self._scan_bank_sizes = {}

    def _invalidate_ol_list(self):
        self._OL_LIST = None
        self._command_delete_cache('OL([0-9]{2})', True)

    def _invalidate_gr_list(self):
        self._GR_LIST = None
        self._command_delete_cache('GR([0-9]{2})', True)

    def _invalidate_memory(self, region=None, bank=None, chan=None,
                           number=None, emptyonly=False):

        if number is not None:
            (region, bank, chan) = self._decode_number(number)
        else:
            number = self._encode_number(region, bank, chan)

        if number in self._memcache:
            if emptyonly and not self._memcache[number].empty:
                return
            del self._memcache[number]

        if region == 'qm':
            self._command_delete_cache('QM{:1d}'.format(chan), True)

        elif region == 'scan':
            self._command_delete_cache('MX{}{:02d}'.format(bank, chan), True)

        elif region == 'pass':
            self._command_delete_cache('PR{}{:02d}'.format(bank, chan), True)

        elif region == 'search':
            # commands not cached
            pass

    def get_memory(self, number):
        if number in self._memcache:
            return self._memcache[number]

        with self.LOCK:
            return self._get_memory_unlocked(number)

    def _get_memory_unlocked(self, number):
        mem = chirp_common.Memory()

        mem.extra = RadioSettingGroup('extra', 'Extra')

        AM_LIST = ['AM', 'NAM', 'WAM']
        extra_am = RadioSettingValueList(AM_LIST)
        rs = RadioSetting('am', 'AM Mode', extra_am)
        mem.extra.append(rs)

        lv = min(list(zip(*self._rf.valid_bands))[0]) / 1000000
        uv = max(list(zip(*self._rf.valid_bands))[1]) / 1000000
        extra_upper = RadioSettingValueFloat(lv, uv, lv, 0.00005, 5)
        rs = RadioSetting('upper', 'Upper Frequency', extra_upper)
        mem.extra.append(rs)

        extra_adjust = RadioSettingValueFloat(0, 999.95, 0, 0.05, 2)
        rs = RadioSetting('adjust', 'Step Adjust', extra_adjust)
        mem.extra.append(rs)

        extra_att = RadioSettingValueBoolean(False)
        rs = RadioSetting('att', 'Attenuator', extra_att)
        mem.extra.append(rs)

        extra_limit = RadioSettingValueBoolean(False)
        rs = RadioSetting('limit', 'Noise Limiter', extra_limit)
        mem.extra.append(rs)

        extra_protect = RadioSettingValueBoolean(False)
        rs = RadioSetting('protect', 'Protect', extra_protect)
        mem.extra.append(rs)

        extra_select = RadioSettingValueBoolean(False)
        rs = RadioSetting('select', 'Select Scan', extra_select)
        mem.extra.append(rs)

        extra_selectindex = RadioSettingValueInteger(0, 99, 0)
        rs = RadioSetting('selectindex', 'Select Scan Index',
                          extra_selectindex)
        mem.extra.append(rs)

        if isinstance(number, str):
            mem.number = self._SPECIAL_CHANS[number]
            mem.extd_number = number
        else:
            mem.number = number

        (region, bank, chan) = self._decode_number(mem.number)
        if region is None:
            raise errors.InvalidMemoryLocation(
                "No such memory {}".format(number))

        if region == 'vfo':
            if chan == self._SPECIAL_CHANS['VFO']:
                self._command('VF')
                mem.name = 'VFO'
            elif chan == self._SPECIAL_CHANS['VFO-A']:
                self._command('VA')
                mem.name = 'VFO-A'
            elif chan == self._SPECIAL_CHANS['VFO-B']:
                self._command('VB')
                mem.name = 'VFO-B'

            ol_list = self._get_ol_list()

            res = self._command(
                'RX',
                ('V[ABF] RF(?P<freq>[0-9]{10}) '
                 'ST(?P<step>[0-9]{6})(?P<adjust>[+]?) AU(?P<auto>[01]) '
                 'MD(?P<mode>[0-8]) AT(?P<att>[01])'))
            if not res:
                pass
            else:
                mem.freq = int(res['freq'])

                if int(res['auto']):
                    mem.mode = 'Auto'
                else:
                    radio_mode = [mode[0] for mode in self._MODES
                                  if mode[1] == int(res['mode'])][0]
                    if radio_mode in self._AM_MODES:
                        mem.mode = 'AM'
                        extra_am.set_value(radio_mode)
                    else:
                        mem.mode = radio_mode

                mem.tuning_step = float(res['step']) / 1000

                extra_att.set_value(int(res['att']))

                res = self._command('OF', 'OF([0-4][0-9])([ +-])')
                mem.offset = ol_list[int(res[1])] if res else 0
                mem.duplex = res[2] if res and res[2] in ('+', '-') else ''

                res = self._command('SH', 'SH([0-9]{6})([+]?)')
                if res:
                    extra_adjust.set_value(
                        int(res[1]) / 1000 if res[2] == '+' else 0)

                res = self._command('NL', 'NL([01])')
                if res:
                    extra_limit.set_value(int(res[1]))

            extra_protect.set_mutable(False)
            extra_upper.set_mutable(False)

            mem.immutable += ['name', 'skip', 'extra.upper', 'extra.protect',
                              'extra.select']

        elif region == 'qm':
            res = self._command_cached('QM{:1d}'.format(chan),
                                       'QM([0-9]) RF([0-9]{10})')
            if not res:
                mem.empty = True
            else:
                if chan != int(res[1]):
                    raise errors.RadioError(
                        "Unexpected result returned from radio")

                mem.freq = int(res[2])
                mem.name = 'QM{:1d}'.format(chan)

            extra_am.set_mutable(False)
            extra_upper.set_mutable(False)
            extra_adjust.set_mutable(False)
            extra_att.set_mutable(False)
            extra_limit.set_mutable(False)
            extra_protect.set_mutable(False)

            mem.immutable += ['empty', 'freq', 'name', 'offset', 'mode',
                              'tuning_step', 'skip', 'duplex', 'extra.upper',
                              'extra.adjust', 'extra.att', 'extra.limit',
                              'extra.protect', 'extra.select']

        elif region == 'scan':
            ol_list = self._get_ol_list()
            gr_list = self._get_gr_list()

            res = self._command_cached(
                'MX{}{:02d}'.format(bank, chan),
                ('MX(?P<bank>[A-Ja-j])(?P<chan>[0-9]{2}) '
                 '(?:(?P<empty>---)$|MP(?P<pass>[01]) RF(?P<freq>[0-9]{10}) '
                 'ST(?P<step>[0-9]{6})(?P<adjust>[+]?) AU(?P<auto>[01]) '
                 'MD(?P<mode>[0-8]) AT(?P<att>[01]) TM(?P<name>.{0,12}))'))
            if not res:
                pass
            elif res['empty']:
                mem.empty = True
            else:
                if res['bank'] != bank or int(res['chan']) != chan:
                    raise errors.RadioError(
                        "Unexpected result returned from radio")

                mem.freq = int(res['freq'])
                mem.name = res['name']

                if int(res['auto']):
                    mem.mode = 'Auto'
                else:
                    radio_mode = [mode[0] for mode in self._MODES
                                  if mode[1] == int(res['mode'])][0]
                    if radio_mode in self._AM_MODES:
                        mem.mode = 'AM'
                        extra_am.set_value(radio_mode)
                    else:
                        mem.mode = radio_mode

                mem.tuning_step = float(res['step']) / 1000
                mem.skip = 'S' if int(res['pass']) else ''

                extra_att.set_value(int(res['att']))

                if not self._SKIP_SELECT:
                    self._command('MR{}{:02d}'.format(bank, chan))

                    res = self._command('OF', 'OF([0-4][0-9])([ +-])')
                    mem.offset = ol_list[int(res[1])] if res else 0
                    mem.duplex = res[2] if res and res[2] in ('+', '-') else ''

                    res = self._command('SH', 'SH([0-9]{6})([+]?)')
                    if res:
                        extra_adjust.set_value(
                            int(res[1]) / 1000 if res[2] == '+' else 0)

                    res = self._command('NL', 'NL([01])')
                    if res:
                        extra_limit.set_value(int(res[1]))

                    res = self._command('PC', 'PC([01])')
                    if res:
                        extra_protect.set_value(int(res[1]))

                    if (bank, chan) in gr_list:
                        extra_select.set_value(True)
                        extra_selectindex.set_value(
                            gr_list.index((bank, chan)))
                    else:
                        mem.immutable += ['extra.select']

                else:
                    extra_adjust.set_mutable(False)
                    extra_limit.set_mutable(False)
                    extra_protect.set_mutable(False)

                    mem.immutable += ['offset', 'duplex', 'extra.adjust',
                                      'extra.limit', 'extra.protect',
                                      'extra.select']

            extra_upper.set_mutable(False)

            mem.immutable += ['extra.upper']

        elif region == 'pass':
            res = self._command_cached(
                'PR{}{:02d}'.format(bank, chan),
                ('PR(?P<bank>[A-Ta-tV])(?P<chan>[0-9]{2}) '
                 '(?:(?P<empty>---)$|(?P<freq>[0-9]{10}))'))
            if not res or res['empty']:
                mem.empty = True
            else:
                if res['bank'] != bank or int(res['chan']) != chan:
                    raise errors.RadioError(
                        "Unexpected result returned from radio")

                mem.freq = int(res['freq'])
                mem.name = 'PR{}{:02d}'.format(bank, chan)
                mem.immutable += ['freq']

            mem.tuning_step = 20.0
            mem.skip = 'S'

            extra_am.set_mutable(False)
            extra_upper.set_mutable(False)
            extra_adjust.set_mutable(False)
            extra_att.set_mutable(False)
            extra_limit.set_mutable(False)
            extra_protect.set_mutable(False)

            mem.immutable += ['name', 'offset', 'mode', 'tuning_step', 'skip',
                              'duplex', 'extra.upper', 'extra.adjust',
                              'extra.att', 'extra.limit', 'extra.protect',
                              'extra.select']

        elif region == 'search':
            ol_list = self._get_ol_list()

            res = self._command(
                'SR{}'.format(bank),
                ('SR(?P<bank>[A-Ta-t]) (?:(?P<empty>---)$|'
                 'SL(?P<lower>[0-9]{10}) SU(?P<upper>[0-9]{10}) '
                 'ST(?P<step>[0-9]{6})(?P<adjust>[+]?) AU(?P<auto>[01]) '
                 'MD(?P<mode>[0-8]) AT(?P<att>[01]) TT(?P<name>.{0,12}))'))
            if not res:
                pass
            elif res['empty']:
                mem.empty = True
            else:
                if res['bank'] != bank:
                    raise errors.RadioError(
                        "Unexpected result returned from radio")

                mem.freq = int(res['lower'])
                mem.name = res['name']

                if int(res['auto']):
                    mem.mode = 'Auto'
                else:
                    radio_mode = [mode[0] for mode in self._MODES
                                  if mode[1] == int(res['mode'])][0]
                    if radio_mode in self._AM_MODES:
                        mem.mode = 'AM'
                        extra_am.set_value(radio_mode)
                    else:
                        mem.mode = radio_mode

                mem.tuning_step = float(res['step']) / 1000

                extra_upper.set_value(int(res['upper']) / 1000000)
                extra_att.set_value(int(res['att']))

                self._save_gs()

                self._command('GS0')
                self._command('SS{}'.format(bank))

                res = self._command('OF', 'OF([0-4][0-9])([ +-])')
                mem.offset = ol_list[int(res[1])] if res else 0
                mem.duplex = res[2] if res and res[2] in ('+', '-') else ''

                res = self._command('SH', 'SH([0-9]{6})([+]?)')
                if res:
                    v = int(res[1]) / 1000 if res[2] == '+' else 0
                    extra_adjust.set_value(v)

                res = self._command('NL', 'NL([01])')
                if res:
                    extra_limit.set_value(int(res[1]))

                res = self._command('BP', 'BP([01])')
                if res:
                    extra_protect.set_value(int(res[1]))

                self._restore_gs()
                self._command('VF')

            mem.immutable += ['skip', 'extra.select']

        else:
            mem.empty = True

        extra_select.set_mutable(False)

        mem.immutable += ['extra.selectindex', 'tmode', 'rtone']

        self._memcache[mem.number] = mem
        return mem

    def validate_memory(self, memory):
        with self.LOCK:
            return self._validate_memory_unlocked(memory)

    def _validate_memory_unlocked(self, memory):
        msgs = []

        ol_list = self._get_ol_list()
        (region, bank, chan) = self._decode_number(memory.number)

        if region in ('scan', 'search'):
            if memory.offset not in ol_list:
                msg = chirp_common.ValidationWarning(
                    "Offset frequency is not valid, see table in settings "
                    "for valid values")
                msgs.append(msg)

            if memory.tuning_step == 0.0 or memory.tuning_step >= 1000.0 or \
               (int(memory.tuning_step * 1000) % 50) != 0:
                msg = chirp_common.ValidationWarning(
                    "Tuning step must be non-zero, less than 1000 kHz, and "
                    "divisible by 0.05 kHz")
                msgs.append(msg)

            if 'adjust' in memory.extra:
                if float(memory.extra['adjust'].value) >= memory.tuning_step:
                    msg = chirp_common.ValidationWarning(
                        "Step adjust must be smaller than tuning step")
                    msgs.append(msg)

        if region == 'search' and 'upper' in memory.extra:
            upper = int(float(memory.extra['upper'].value) * 1000000)
            if memory.freq > upper:
                msg = chirp_common.ValidationWarning(
                    "Upper search frequency is not greater than lower "
                    "frequency")
                msgs.append(msg)

            valid = False
            for (lv, uv) in self._rf.valid_bands:
                if upper >= lv and upper <= uv:
                    valid = True
                    break

            if not valid:
                msg = chirp_common.ValidationError(
                    "Upper search frequency {} is not in a valid band"
                    "".format(float(memory.extra['upper'].value)))
                msgs.append(msg)

        if region == 'pass':
            if memory.skip != 'S':
                msg = chirp_common.ValidationWarning(
                    "Search pass frequencies must be marked skip")
                msgs.append(msg)

            msg = chirp_common.ValidationWarning(
                "Memories must be refreshed after modifying pass channels")
            msgs.append(msg)

        return msgs + super().validate_memory(memory)

    def set_memory(self, memory):
        with self.LOCK:
            return self._set_memory_unlocked(memory)

    def _set_memory_unlocked(self, memory):
        self._invalidate_memory(number=memory.number)

        (region, bank, chan) = self._decode_number(memory.number)
        if region is None:
            raise errors.InvalidMemoryLocation(
                "No such memory {}".format(memory.number))

        if region == 'vfo':
            if chan == self._SPECIAL_CHANS['VFO']:
                self._command('VF')
            elif chan == self._SPECIAL_CHANS['VFO-A']:
                self._command('VA')
            elif chan == self._SPECIAL_CHANS['VFO-B']:
                self._command('VB')

            ol_list = self._get_ol_list()

            freq = memory.freq
            auto = int(memory.mode == 'Auto')
            step = int(memory.tuning_step * 1000)

            if memory.mode == 'Auto':
                mode = 0
            elif memory.mode == 'AM':
                mode = [mode[1] for mode in self._MODES
                        if mode[0] == memory.extra['am']][0]
            else:
                mode = [mode[1] for mode in self._MODES
                        if mode[0] == memory.mode][0]

            att = int(memory.extra['att'].value) \
                if 'att' in memory.extra else 0
            duplex = memory.duplex if memory.duplex in ('+', '-') else ''
            offset = ol_list.index(memory.offset) \
                if duplex and memory.offset in ol_list else 0
            adjust = float(memory.extra['adjust'].value) \
                if 'adjust' in memory.extra else 0
            limit = int(memory.extra['limit'].value) \
                if 'limit' in memory.extra else 0

            self._command('RF{:010d}'.format(freq))
            self._command('AT{:1d}'.format(att))
            self._command('AU{:1d}'.format(auto))

            if not auto:
                self._command('MD{:1d}'.format(mode))
                self._command('ST{:06d}'.format(step))
                self._command('OF{:02d}{}'.format(offset, duplex))

                # step tuning enable can only be toggled, so get the
                # current value first
                toggle = ''
                res = self._command('SH', 'SH([0-9]{6})([+]?)')
                if res:
                    toggle = '+' if (res[2] == '+') != (adjust > 0) else ''

                self._command('SH{:06d}{}'.format(int(adjust * 1000), toggle))

            self._command('NL{:1d}'.format(limit))

        elif region == 'qm':
            raise errors.InvalidDataError(
                "Quick memory locations are read-only")

        elif region == 'scan':
            self._command_delete_cache('MX{:1}{:02d}'.format(bank, chan))
            ol_list = self._get_ol_list()
            gr_list = self._get_gr_list()

            freq = memory.freq
            auto = int(memory.mode == 'Auto')
            step = int(memory.tuning_step * 1000)

            if memory.mode == 'Auto':
                mode = 0
            elif memory.mode == 'AM':
                mode = [mode[1] for mode in self._MODES
                        if mode[0] == memory.extra['am']][0]
            else:
                mode = [mode[1] for mode in self._MODES
                        if mode[0] == memory.mode][0]

            att = int(memory.extra['att'].value) \
                if 'att' in memory.extra else 0
            duplex = memory.duplex if memory.duplex in ('+', '-') else ''
            offset = ol_list.index(memory.offset) \
                if duplex and memory.offset in ol_list else 0
            adjust = float(memory.extra['adjust'].value) \
                if 'adjust' in memory.extra else 0
            limit = int(memory.extra['limit'].value) \
                if 'limit' in memory.extra else 0
            protect = int(memory.extra['protect'].value) \
                if 'protect' in memory.extra else 0
            select = int(memory.extra['select'].value) \
                if 'select' in memory.extra else 0
            name = memory.name
            mp = 1 if memory.skip == 'S' else 0

            offsetstr = 'OF{:02d}{} '.format(offset, duplex) \
                if not self._SKIP_SELECT else ''
            res = self._command(
                ('MX{}{:02d} RF{:010d} MP{:1d} ST{:06d} MD{:1d} AT{:1d} '
                 '{}AU{:1d} TM{:12}'.format(bank, chan, freq, mp, step, mode,
                                            att, offsetstr, auto, name)),
                '(?:$|{:c}{:c})'.format(0x13, 0x11))
            if not res:
                raise errors.InvalidDataError(
                    "Radio refused {}".format(memory.number))

            if not self._SKIP_SELECT:
                self._command('MR{}{:02d}'.format(bank, chan))

                if not auto:
                    # step tuning enable can only be toggled, so get
                    # the current value first
                    toggle = ''
                    res = self._command('SH', 'SH([0-9]{6})([+]?)')
                    if res:
                        toggle = '+' if (res[2] == '+') != (adjust > 0) else ''

                    self._command(
                        'SH{:06d}{}'.format(int(adjust * 1000), toggle))

                self._command('NL{:1d}'.format(limit))
                self._command('PC{:1d}'.format(protect))

                if not select and (bank, chan) in gr_list:
                    self._command(
                        'GD{:02d}'.format(gr_list.index((bank, chan))))
                    self._invalidate_gr_list()

        elif region == 'pass':
            self._command_delete_cache('PR{}[0-9]{{2}}'.format(bank), True)

            freq = memory.freq

            res = self._command('PW{}{:010d}'.format(bank, freq))
            if not res:
                raise errors.InvalidDataError(
                    "Radio refused {}".format(memory.number))

            for n in range(100 if bank == 'V' else 50):
                self._invalidate_memory(region, bank, n, emptyonly=True)

        elif region == 'search':
            self._command_delete_cache('SR{}'.format(bank))
            ol_list = self._get_ol_list()

            lower = memory.freq
            upper = int(float(memory.extra['upper'].value) * 1000000) \
                if 'upper' in memory.extra else lower
            auto = int(memory.mode == 'Auto')
            step = int(memory.tuning_step * 1000)

            if memory.mode == 'Auto':
                mode = 0
            elif memory.mode == 'AM':
                mode = [mode[1] for mode in self._MODES
                        if mode[0] == memory.extra['am']][0]
            else:
                mode = [mode[1] for mode in self._MODES
                        if mode[0] == memory.mode][0]

            att = int(memory.extra['att'].value) \
                if 'att' in memory.extra else 0
            duplex = memory.duplex if memory.duplex in ('+', '-') else ''
            offset = ol_list.index(memory.offset) \
                if duplex and memory.offset in ol_list else 0
            adjust = float(memory.extra['adjust'].value) \
                if 'adjust' in memory.extra else 0
            limit = int(memory.extra['limit'].value) \
                if 'limit' in memory.extra else 0
            protect = int(memory.extra['protect'].value) \
                if 'protect' in memory.extra else 0
            name = memory.name

            # correct lower/upper out of order
            if lower > upper:
                (lower, upper) = (upper, lower)

            # fix out of range
            lower = max(lower, min(list(zip(*self._rf.valid_bands))[0]))
            upper = min(upper, max(list(zip(*self._rf.valid_bands))[1]))

            res = self._command(
                'SE{} SL{:010d} SU{:010d} ST{:06d} MD{:1d} AT{:1d} '
                'OF{:02d}{:1} AU{:1d} TT{:12}'.format(bank, lower, upper, step,
                                                      mode, att, offset,
                                                      duplex, auto, name))
            if not res:
                raise errors.InvalidDataError(
                    "Radio refused {}".format(memory.number))

            self._save_gs()

            self._command('GS0')
            self._command('SS{}'.format(bank))

            if not auto:
                # step tuning enable can only be toggled, so get the
                # current value first
                toggle = ''
                res = self._command('SH', 'SH([0-9]{6})([+]?)')
                if res:
                    toggle = '+' if (res[2] == '+') != (adjust > 0) else ''

                self._command('SH{:06d}{}'.format(int(adjust * 1000), toggle))

            self._command('NL{:1d}'.format(limit))
            self._command('BP{:1d}'.format(protect))

            self._restore_gs()
            self._command('VF')

    def erase_memory(self, number):
        with self.LOCK:
            return self._erase_memory_unlocked(number)

    def _erase_memory_unlocked(self, number):
        if isinstance(number, str):
            if number not in self._SPECIAL_CHANS:
                return

            number = self._SPECIAL_CHANS[number]

        if number not in self._memcache:
            return

        (region, bank, chan) = self._decode_number(number)

        if region == 'qm':
            raise errors.InvalidDataError(
                "Quick memory locations are read-only")

        elif region == 'scan':
            self._command_delete_cache('MX{}{:02d}'.format(bank, chan))
            self._command('MR{}{:02d}'.format(bank, chan))
            self._command('MQ{:02d}'.format(chan))

        elif region == 'pass':
            self._command_delete_cache('PR{}[0-9]{{2}}'.format(bank), True)
            self._command('PD{}{:02d}'.format(bank, chan))

            for n in range(chan, 100 if bank == 'V' else 50):
                self._invalidate_memory(region, bank, n)

        elif region == 'search':
            self._command_delete_cache('SR{}'.format(bank))
            self._command('QS{}'.format(bank))

        del self._memcache[number]

    def get_settings(self):
        with self.LOCK:
            return self._get_settings_unlocked()

    def _get_settings_unlocked(self):
        main = RadioSettingGroup('main', 'Main')
        vfo = RadioSettingGroup('vfo', 'VFO')
        freq = RadioSettingGroup('freq', 'Offset')
        scan = RadioSettingGroup('scan', 'Scan')
        search = RadioSettingGroup('search', 'Search')
        scanbankprotect = RadioSettingGroup('scanbankprotect',
                                            'Scan Bank Protect')
        top = RadioSettings(main, vfo, freq, scan, search, scanbankprotect)

        res = self._command('VR', 'VR([0-9]+)')
        rs = RadioSetting('VR', 'Firmware Version',
                          RadioSettingValueString(0, 4, res[1]))
        rs.value.set_mutable(False)
        main.append(rs)

        res = self._command('AF', 'AF([01])')
        rs = RadioSetting('AF', 'Automatic Frequency Control',
                          RadioSettingValueBoolean(int(res[1])))
        rs.set_apply_callback(
            lambda x: self._command('AF{}'.format(int(x.value))))
        main.append(rs)

        res = self._command('AP', 'AP([0-9][.][0-9])')
        rs = RadioSetting(
            'AP', 'Automatic Power Off (hours)',
            RadioSettingValueFloat(0, 9.5, float(res[1]), 0.5, 1))
        rs.set_apply_callback(
            lambda x: self._command('AP{}'.format(int(x.value))))
        main.append(rs)

        res = self._command('DT', 'DT([01])')
        rs = RadioSetting('DT', 'Display Frequency Text',
                          RadioSettingValueBoolean(int(res[1])))
        rs.set_apply_callback(
            lambda x: self._command('DT{}'.format(int(x.value))))
        main.append(rs)

        res = self._command('LB', 'LB([0-9]{2})')
        rs = RadioSetting('LB', 'LCD Contrast',
                          RadioSettingValueInteger(0, 31, res[1]))
        rs.set_apply_callback(
            lambda x: self._command('LB{:02d}'.format(int(x.value))))
        main.append(rs)

        # OM supports options for standard, no, and custom message,
        # but the code here always sets the configured text as a
        # custom message.
        res = self._command('OM', 'OM([012]) (.{0,48})')
        rs = RadioSetting('OM', 'Opening Message',
                          RadioSettingValueString(0, 48, res[2]))
        rs.set_apply_callback(
            lambda x: self._command('OM2 {}'.format(str(x.value))))
        main.append(rs)

        res = self._command('PA', 'PA([0-9]{2})')
        rs = RadioSetting('PA', 'Power Save Delay (seconds)',
                          RadioSettingValueInteger(0, 99, res[1]))
        rs.set_apply_callback(
            lambda x: self._command('PA{:02d}'.format(int(x.value))))
        main.append(rs)

        res = self._command('PI', 'PI([1-9].[05])')
        rs = RadioSetting(
            'PI', 'Power Save Interval (seconds)',
            RadioSettingValueFloat(1.0, 9.5, float(res[1]), 0.5, 1))
        rs.set_apply_callback(
            lambda x: self._command(
                'PI{:02d}'.format(int(float(x.value) * 10))))
        main.append(rs)

        res = self._command('PP', 'PP([A-Ja-j])([0-9]{2})')
        rs = RadioSetting(
            'PP', 'Priority Scan Channel',
            RadioSettingValueInteger(
                0, self._SCAN_MEMORIES - 1,
                self._encode_number('scan', res[1], int(res[2]))))
        rs.set_apply_callback(lambda x: self._set_pp(int(x.value)))
        main.append(rs)

        res = self._command('TI', 'TI([01][0-9])')
        rs = RadioSetting('TI', 'Priority Interval (seconds)',
                          RadioSettingValueInteger(1, 19, res[1]))
        rs.set_apply_callback(
            lambda x: self._command('TI{:02d}'.format(int(x.value))))
        main.append(rs)

        res = self._command('VL', 'VL([0-9])')
        rs = RadioSetting('VL', 'Beep Volume',
                          RadioSettingValueInteger(0, 9, res[1]))
        rs.set_apply_callback(
            lambda x: self._command('VL{}'.format(int(x.value))))
        main.append(rs)

        res = self._command('WP', 'WP([01])')
        rs = RadioSetting('WP', 'Write Protect',
                          RadioSettingValueBoolean(int(res[1])))
        rs.set_apply_callback(
            lambda x: self._command('WP{}'.format(int(x.value))))
        main.append(rs)

        # vfo settings

        res = self._command('DA', 'DA[ +]([012][0-9]{2})')
        rs = RadioSetting('DA', 'Dial Audio Squelch',
                          RadioSettingValueInteger(0, 255, res[1]))
        rs.set_apply_callback(
            lambda x: self._command('DA{:03d}'.format(int(x.value))))
        vfo.append(rs)

        res = self._command('DB', 'DB[ +]([012][0-9]{2})')
        rs = RadioSetting('DB', 'Dial Level Squelch',
                          RadioSettingValueInteger(0, 255, res[1]))
        rs.set_apply_callback(
            lambda x: self._command('DB{:03d}'.format(int(x.value))))
        vfo.append(rs)

        res = self._command('DD', 'DD([0-9][.][0-9])')

        rs = RadioSetting('DDFF', 'Dial Search Hold',
                          RadioSettingValueBoolean(res[1] == 'FF'))
        vfo.append(rs)

        value = float(res[1]) if res[1] != 'FF' else 0
        rs = RadioSetting('DD', 'Dial Delay (seconds)',
                          RadioSettingValueFloat(0, 9.9, value, 0.1, 1))
        vfo.append(rs)

        res = self._command('DP', 'DP([0-9]{2})')
        rs = RadioSetting('DP', 'Dial Pause (seconds)',
                          RadioSettingValueInteger(0, 60, res[1]))
        rs.set_apply_callback(
            lambda x: self._command('DP{:02d}'.format(int(x.value))))
        vfo.append(rs)

        VT_MAP = [('Off', 0), ('On, auto-store to bank J', 1),
                  ('On, erase bank J', 2)]
        res = self._command('VT', 'VT([012])')
        rs = RadioSetting('VT', 'VFO Auto-store',
                          RadioSettingValueMap(VT_MAP, int(res[1])))
        rs.set_apply_callback(
            lambda x: self._command('VT{}'.format(int(x.value))))
        vfo.append(rs)

        # frequency offsets

        # 0 means off, 20-47 are read-only
        ol_list = self._get_ol_list()
        for n in range(0, 48):
            rs = RadioSetting(
                'OL{:02d}'.format(n),
                'Offset Frequency {} (MHz)'.format(n),
                RadioSettingValueFloat(
                    0.0, 999.9999, ol_list[n] / 1000000, 0.0001, 4))
            rs.value.set_mutable(n > 0 and n < 20)
            rs.set_apply_callback(
                lambda x, y: self._command(
                    ('OL{:02d} {:010d}'
                     ''.format(y, int(float(x.value) * 1000000)))), n)
            rs.set_warning("Memories must be refreshed after changing "
                           "offset frequencies.")
            freq.append(rs)

        # scan settings

        grp = RadioSettingSubGroup('scan general', 'Scan General')
        scan.append(grp)

        res = self._command('GM', 'GM([0-9])', 2)
        sel = int(res[1])
        rs = RadioSetting('GM', 'Selected Scan Group',
                          RadioSettingValueInteger(0, 9, sel))
        rs.set_apply_callback(
            lambda x: self._command('GM{}'.format(int(x.value))))
        grp.append(rs)

        grp = RadioSettingSubGroup('TB', 'Scan Bank Name')
        scan.append(grp)

        for bank in self._SCAN_BANKS:
            res = self._command('TB{}'.format(bank), 'TB([A-Ja-j])(.{0,8})')
            rs = RadioSetting('TB{}'.format(bank), 'Bank {} Name'.format(bank),
                              RadioSettingValueString(0, 8, res[2]))
            rs.set_apply_callback(
                lambda x, y: self._command(
                    'TB{}{:8}'.format(y, str(x.value))), bank)
            grp.append(rs)

        grp = RadioSettingSubGroup('MW', 'Scan Bank Size')
        scan.append(grp)

        MW_MAP = [('10/90', 10), ('20/80', 20), ('30/70', 30), ('40/60', 40),
                  ('50/50', 50), ('60/40', 60), ('70/30', 70), ('80/20', 80),
                  ('90/10', 90)]

        for bank in self._SCAN_BANKS[::2]:
            rs = RadioSetting(
                'MW{}'.format(bank), 'Bank {}/{}'.format(bank, bank.lower()),
                RadioSettingValueMap(MW_MAP, self._scan_bank_size(bank)))
            rs.set_apply_callback(
                lambda x, y: self._command(
                    'MW{}{:2d}'.format(y, int(x.value)), timeout=600), bank)
            rs.set_warning("Resizing scan banks takes a significant amount of "
                           "time (one minute or longer).  Memories must be "
                           "refreshed after changing scan bank size.")
            grp.append(rs)

        for group in range(10):
            grp = RadioSettingSubGroup(
                'GM{}'.format(group), 'Scan Group {}'.format(group))
            scan.append(grp)

            self._command('GM{}'.format(group))

            res = self._command_cached(
                'GM{:1d}'.format(group),
                ('GM(?P<group>[0-9]) XD(?P<delay>[0-9][.][0-9]) '
                 'XB (?P<level>[012][0-9]{2}) XA (?P<audio>[012][0-9]{2}) '
                 'XP(?P<pause>[0-9]{2}) XM(?P<mode>[0-8F])'))
            if not res:
                continue

            rs = RadioSetting('XA{}'.format(group), 'Scan Audio Squelch',
                              RadioSettingValueInteger(0, 255, res['audio']))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            rs = RadioSetting('XB{}'.format(group), 'Scan Level Squelch',
                              RadioSettingValueInteger(0, 255, res['level']))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            rs = RadioSetting(
                'XD{}'.format(group), 'Scan Delay (seconds)',
                RadioSettingValueFloat(0, 9.9, float(res['delay']), 0.1, 1))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            rs = RadioSetting('XP{}'.format(group), 'Scan Pause (seconds)',
                              RadioSettingValueInteger(0, 99, res['pause']))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            rs = RadioSetting(
                'XM{}'.format(group), 'Scan Mode',
                RadioSettingValueMap(self._MODES, int(res['mode'], 16)))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            res = self._command_cached('BM', 'BM ([A-Ja-j-]{20})')

            for bank in self._SCAN_BANKS:
                rs = RadioSetting(
                    'BM{}{}'.format(group, bank), 'Bank {}'.format(bank),
                    RadioSettingValueBoolean(bank in res[1]))
                rs.value.set_mutable(group != 0)
                grp.append(rs)

        self._command('GM{}'.format(sel))

        # search settings

        grp = RadioSettingSubGroup('search general', 'Search General')
        search.append(grp)

        res = self._command('GS', 'GS([0-9])', 2)
        sel = int(res[1])
        rs = RadioSetting('GS', 'Selected Search Group',
                          RadioSettingValueInteger(0, 9, sel))
        rs.set_apply_callback(
            lambda x: self._command('GS{}'.format(int(x.value))))
        grp.append(rs)

        self._save_gs()

        for group in range(10):
            grp = RadioSettingSubGroup('GS{}'.format(group),
                                       'Search Group {}'.format(group))
            search.append(grp)

            self._command('GS{}'.format(group))

            res = self._command_cached(
                'GS{:1d}'.format(group),
                ('GS(?P<group>[0-9]) SD(?P<delay>[0-9][.][0-9]) '
                 'SB (?P<level>[012][0-9]{2}) SA (?P<audio>[012][0-9]{2}) '
                 'SP(?P<pause>[0-9]{2}) AS(?P<auto>[012])'))
            if not res:
                continue

            rs = RadioSetting('SA{}'.format(group), 'Search Audio Squelch',
                              RadioSettingValueInteger(0, 255, res['audio']))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            rs = RadioSetting('SB{}'.format(group), 'Search Level Squelch',
                              RadioSettingValueInteger(0, 255, res['level']))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            if group != 0:
                rs = RadioSetting(
                    'SD{}FF'.format(group), 'Search Hold',
                    RadioSettingValueBoolean(res['delay'] == 'FF'))
                grp.append(rs)

            value = float(res['delay']) if res['delay'] != 'FF' else 0
            rs = RadioSetting('SD{}'.format(group), 'Search Delay (seconds)',
                              RadioSettingValueFloat(0, 9.9, value, 0.1, 1))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            rs = RadioSetting('SP{}'.format(group), 'Search Pause (seconds)',
                              RadioSettingValueInteger(0, 99, res['pause']))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            rs = RadioSetting('AS{}'.format(group), 'Search Auto-store',
                              RadioSettingValueMap(VT_MAP, int(res['auto'])))
            rs.value.set_mutable(group != 0)
            grp.append(rs)

            res = self._command_cached('BS', 'BS ([A-Ta-t-]{40})')

            for bank in self._SEARCH_BANKS:
                rs = RadioSetting(
                    'BS{}{}'.format(group, bank), 'Bank {}'.format(bank),
                    RadioSettingValueBoolean(bank in res[1]))
                rs.value.set_mutable(group != 0)
                grp.append(rs)

        self._restore_gs()

        # scan bank protect

        for bank in self._SCAN_BANKS[::2]:
            res = self._command_read_WM(bank)

            for (b, v) in list(zip((bank, bank.lower()), res)):
                rs = RadioSetting(
                    'WM{}'.format(b), 'Scan Bank {} Protect'.format(b),
                    RadioSettingValueBoolean(v))
                rs.set_apply_callback(
                    lambda x, y: self._command(
                        'WM{}{}'.format(y, int(x.value))), b)
                scanbankprotect.append(rs)

        return top

    def _apply_settings_callbacks(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self._apply_settings_callbacks(element)
            elif element.changed() and element.has_apply_callback():
                LOG.debug("running callback for {}".format(element))
                element.run_apply_callback()

    def set_settings(self, settings):
        with self.LOCK:
            return self._set_settings_unlocked(settings)

    def _set_settings_unlocked(self, settings):
        self._apply_settings_callbacks(settings)

        setdict = {}
        for element in settings:
            if isinstance(element, RadioSettingGroup):
                setdict[element.get_name()] = element

        if setdict['vfo']['DDFF'].value.changed() or \
           setdict['vfo']['DD'].value.changed():
            if int(setdict['vfo']['DDFF'].value):
                self._command('DDFF')
            else:
                v = int(float(setdict['vfo']['DD'].value) * 10)
                self._command('DD{:02d}'.format(v))

        # BM/BS flags can only be cleared or toggled, so clear all
        # first, then toggle the flags which are set

        for group in range(1, 10):
            parent = setdict['scan']['GM{}'.format(group)]

            self._command('GM{}'.format(group))
            if parent['XA{}'.format(group)].value.changed():
                v = int(parent['XA{}'.format(group)].value)
                self._command('XA{:03d}'.format(v))
            if parent['XB{}'.format(group)].value.changed():
                v = int(parent['XB{}'.format(group)].value)
                self._command('XB{:03d}'.format(v))
            if parent['XD{}'.format(group)].value.changed():
                v = int(float(parent['XD{}'.format(group)].value) * 10)
                self._command('XD{:02d}'.format(v))
            if parent['XP{}'.format(group)].value.changed():
                v = int(parent['XP{}'.format(group)].value)
                self._command('XP{:02d}'.format(v))
            if parent['XM{}'.format(group)].value.changed():
                v = int(parent['XM{}'.format(group)].value)
                self._command('XM{:01x}'.format(v))

            if any(parent['BM{}{}'.format(group, bank)].value.changed()
                   for bank in self._SCAN_BANKS):

                v = ''
                for bank in self._SCAN_BANKS:
                    if int(parent['BM{}{}'.format(group, bank)].value):
                        v += bank

                self._command('BM%%')
                self._command('BM{}'.format(v), 'BM [A-Ja-j-]{20}')

        v = int(setdict['scan']['scan general']['GM'].value)
        self._command('GM{}'.format(v))

        for group in range(1, 10):
            parent = setdict['search']['GS{}'.format(group)]

            self._command('GS{}'.format(group))

            if parent['SA{}'.format(group)].value.changed():
                v = int(parent['SA{}'.format(group)].value)
                self._command('SA{:03d}'.format(v))
            if parent['SB{}'.format(group)].value.changed():
                v = int(parent['SB{}'.format(group)].value)
                self._command('SB{:03d}'.format(v))

            if parent['SD{}FF'.format(group)].value.changed() or \
               parent['SD{}'.format(group)].value.changed():
                if int(parent['SD{}FF'.format(group)].value):
                    self._command('SDFF')
                else:
                    v = int(float(parent['SD{}'.format(group)].value) * 10)
                    self._command('SD{:02d}'.format(v))

            if parent['SP{}'.format(group)].value.changed():
                v = int(parent['SP{}'.format(group)].value)
                self._command('SP{:02d}'.format(v))
            if parent['AS{}'.format(group)].value.changed():
                v = int(parent['AS{}'.format(group)].value)
                self._command('AS{}'.format(v))

            if any(parent['BS{}{}'.format(group, bank)].value.changed()
                   for bank in self._SEARCH_BANKS):

                v = ''
                for bank in self._SEARCH_BANKS:
                    if int(parent['BS{}{}'.format(group, bank)].value):
                        v += bank

                self._command('BS%%')
                self._command('BS{}'.format(v), 'BS [A-Ta-t-]{40}')

        v = int(setdict['search']['search general']['GS'].value)
        self._command('GS{}'.format(v))

        for n in range(1, 20):
            if setdict['freq']['OL{:02d}'.format(n)].value.changed():
                self._invalidate_ol_list()
                for n in range(self._SCAN_MEMORIES):
                    self._invalidate_memory(number=n)

                for bank in self._SEARCH_BANKS:
                    self._invalidate_memory('search', bank, None)

                break

        changed = False
        for bank in self._SCAN_BANKS[::2]:
            if setdict['scan']['MW']['MW{}'.format(bank)].value.changed():
                changed = True
                for b in (bank.upper(), bank.lower()):
                    for n in range(self._scan_bank_size(b)):
                        self._invalidate_memory('scan', b, n)

        if changed:
            self._invalidate_scan_bank_size()
