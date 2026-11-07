# Copyright 2026 Michael Sasarak <mike@prepperevolution.com>
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
#
# BTECH UV-PRO (Benshi family) live-mode driver.
# Talks GAIA-framed commands over the radio's Bluetooth SPP serial port
# (Windows: the Outgoing "UV-PRO 'SPP Dev'" COM port). Baud rate is ignored.
#
# Protocol facts reimplemented (no code copied) from the Apache-2.0 projects
# HTCommander (Ylian Saint-Hilaire, KK7VZT, github.com/Ylianst/HTCommander)
# and benlink (github.com/khusmann/benlink); thank you to both.
#
# READS: GET_DEV_INFO (4), READ_RF_CH (13), and (read-only group info)
# GET_HT_STATUS (20) + READ_REGION_NAME (73) so Settings can show which
# group is active. Channel I/O is still only the radio's active group.
# WRITES (WRITE_RF_CH, 14) are sent when a memory is edited, and only when
# the radio reports the tested firmware (soft_ver 147). Never switches
# groups (SET_REGION / cmd 60 is not in the allowlist), never writes radio
# settings, never keys the transmitter.

import logging
import struct
import threading

from chirp import bitwise, chirp_common, directory, errors, memmap
from chirp.settings import (RadioSetting, RadioSettingGroup,
                            RadioSettings, RadioSettingValueString)

LOG = logging.getLogger(__name__)

GROUP_BASIC = 2
CMD_GET_DEV_INFO = 4
CMD_READ_RF_CH = 13
CMD_WRITE_RF_CH = 14
CMD_GET_HT_STATUS = 20       # read-only: curr_region (benlink status.py)
CMD_READ_REGION_NAME = 73    # read-only: 10-byte region name
# SET_REGION = 60 is intentionally NOT listed. Group switching needs Mike's
# OK and a PR discussion with the maintainers first.
ALLOWLIST = frozenset({CMD_GET_DEV_INFO, CMD_READ_RF_CH, CMD_WRITE_RF_CH,
                       CMD_GET_HT_STATUS, CMD_READ_REGION_NAME})
READ_ONLY_ALLOWLIST = frozenset({CMD_GET_DEV_INFO, CMD_READ_RF_CH,
                                 CMD_GET_HT_STATUS, CMD_READ_REGION_NAME})

STATUS_SUCCESS = 0
STATUS_OUT_OF_RANGE = 5   # INVALID_PARAMETER (benlink common.py:11)

TESTED_SOFT_VER = 147
CHANNELS_PER_GROUP = 30
NAME_LEN = 10
RFCH_LEN = 25
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.5),
                chirp_common.PowerLevel("Med", watts=2.0),
                chirp_common.PowerLevel("High", watts=5.0)]
MOD_FM, MOD_AM, MOD_DMR = 0, 1, 2   # benlink rf_ch.py:8-11 ModulationType
# AM airband, receive-only on the UV-PRO (BTECH product page and manual);
# HTCommander radio_channel_dialog.dart:301-305 uses the same AM limits.
AIRBAND = (108000000, 136000000)

# 25-byte RfCh record, big-endian bitfields: benlink rf_ch.py:44-66;
# HTCommander radio_models.dart:542-555 (decode) and :575-590 (encode).
# Bytes 15-24 are the name. One definition serves both read and write.
RF_CH_FORMAT = """
u8 id;
u32 tx_mod:2,
    tx_hz:30;
u32 rx_mod:2,
    rx_hz:30;
u16 tx_sub;
u16 rx_sub;
u8 scan:1,
   max_power:1,
   talk_around:1,
   wide:1,
   pre_de_emph_bypass:1,
   sign:1,
   med_power:1,
   tx_disable:1;
u8 fixed_freq:1,
   fixed_bw:1,
   fixed_power:1,
   mute:1,
   pad:4;
u8 name[10];
"""

# GET_DEV_INFO body. Bytes 6-7 are one big-endian word: region_count is
# the contiguous 6-bit field (low 2 bits of byte 6, then high 4 of byte 7)
# and support_dmr is the low bit of byte 7. HTCommander@bd1964d
# radio_models.dart:68-86; benlink@c4b9d22 dev_info.py.
DEV_INFO_LEN = 9
DEV_INFO_FORMAT = """
u8 vendor;
u16 product;
u8 hw_ver;
u16 soft_ver;
u16 dev_unused:6,
    region_count:6,
    flag_unused:3,
    support_dmr:1;
u8 channel_count;
"""
# First four bytes of StatusExt. curr_region is the contiguous 6-bit
# field across bytes 2-3. A shorter body is the plain Status form.
# HTCommander@bd1964d radio_models.dart:145-160; benlink status.py.
STATUS_EXT_LEN = 4
STATUS_EXT_FORMAT = """
u8 flags;
u8 ch_flags;
u16 rssi:4,
    curr_region:6,
    ch_hi:6;
"""
GAIA_HDR_FMT = '>BBBB'      # 0xFF 0x01 flags len
GAIA_CMD_FMT = '>HH'        # group, reply bit + command


def _parse_bits(fmt, data):
    return bitwise.parse(fmt, memmap.MemoryMapBytes(bytes(data)))


def parse_dev_info(body):
    """GET_DEV_INFO success body (no status byte) -> dict."""
    if len(body) < DEV_INFO_LEN:
        raise errors.RadioError('Short GET_DEV_INFO body (%i)' % len(body))
    d = _parse_bits(DEV_INFO_FORMAT, body[:DEV_INFO_LEN])
    return {
        'vendor': int(d.vendor),
        'product': int(d.product),
        'hw_ver': int(d.hw_ver),
        'soft_ver': int(d.soft_ver),
        'region_count': int(d.region_count),
        'support_dmr': bool(int(d.support_dmr)),
        'channel_count': int(d.channel_count),
    }


def parse_ht_status_curr_region(body):
    """GET_HT_STATUS success body -> curr_region, or None for short Status."""
    if len(body) < STATUS_EXT_LEN:
        return None
    status = _parse_bits(STATUS_EXT_FORMAT, body[:STATUS_EXT_LEN])
    return int(status.curr_region)


def parse_region_name(body):
    """READ_REGION_NAME success body: index u8 + 10-byte name.
    HTCommander@bd1964d radio.dart:3250-3264 / _regionNameLength=10."""
    if len(body) < 1:
        raise errors.RadioError('Short READ_REGION_NAME body')
    raw = bytes(body[1:1 + NAME_LEN]).ljust(NAME_LEN, b'\x00')
    idx, raw = struct.unpack('>B%is' % NAME_LEN, bytes(body[:1]) + raw)
    name = raw.split(bytes([0]))[0].decode('ascii', 'replace').rstrip()
    return idx, name


def build_frame(cmd, body=b''):
    """GAIA frame: FF 01 flags len | group(16) reply(1)+cmd(15) | body.
    flags is always 0 (no checksum) as in all verified traffic."""
    if cmd not in ALLOWLIST:
        raise errors.RadioError('Command %i refused: not in allowlist' % cmd)
    if cmd == CMD_WRITE_RF_CH:
        if len(body) != RFCH_LEN or body[0] >= CHANNELS_PER_GROUP:
            raise errors.RadioError('WRITE_RF_CH refused: only channels '
                                    '0-%i with a %i-byte record'
                                    % (CHANNELS_PER_GROUP - 1, RFCH_LEN))
    return (struct.pack(GAIA_HDR_FMT, 0xFF, 0x01, 0x00, len(body)) +
            struct.pack(GAIA_CMD_FMT, GROUP_BASIC, cmd) + bytes(body))


def parse_rf_ch(data):
    """25-byte record -> mutable bitwise object (RF_CH_FORMAT).
    Edit fields in place; rf_ch.get_raw() is the record to write."""
    if len(data) < RFCH_LEN:
        raise errors.RadioError('Short channel record (%i)' % len(data))
    return bitwise.parse(RF_CH_FORMAT,
                         memmap.MemoryMapBytes(bytes(data[:RFCH_LEN])))


def rf_ch_name(ch):
    return bytes(ch.name.get_raw()).split(b'\x00')[0].decode(
        'ascii', 'replace').rstrip()


def _sub_to_tone(raw):
    # 0 = none; < 6700 = DCS code; else CTCSS Hz*100 (hardware-verified).
    # DCS: the raw value is the code's digits read as a decimal number
    # (023 -> 23): benlink rf_ch.py:23-41 SubAudioMap, HTCommander
    # radio_channel_dialog.dart:816-823 ("DCS-023N -> 23"). Neither source
    # stores a polarity; HTCommander lists each code as "NNN-N / its
    # inverted twin" (dialog :880ff) and exports DtcsPolarity 'NN'
    # (channel_export.dart:124-127). So read as N. NOT hardware-verified (M8).
    if raw == 0:
        return (None, None, None)
    if raw < 6700:
        if raw not in chirp_common.DTCS_CODES:
            LOG.warning('Sub-audio %i is not a standard DCS code', raw)
        return ('DTCS', raw, 'N')
    return ('Tone', raw / 100.0, None)


def _tone_to_sub(spec):
    """(mode, value, polarity) from split_tone_encode -> raw u16."""
    mode, val, _pol = spec
    if not mode:
        return 0
    if mode == 'Tone':
        return int(round(val * 100))
    if mode == 'DTCS':
        # Reverse polarity is rejected by RadioFeatures.valid_dtcs_pols
        # before set_memory. The radio stores only the normal code.
        if val not in chirp_common.DTCS_CODES:
            raise errors.RadioError('Refused: DCS code %r' % val)
        return int(val)
    raise errors.RadioError('Refused: tone mode %r' % mode)


@directory.register
class BTECHUVPRORadio(chirp_common.LiveRadio):
    """BTECH UV-PRO (active group only)"""
    VENDOR = 'BTECH'
    MODEL = 'UV-PRO'
    BAUD_RATE = 115200     # ignored by Bluetooth SPP
    HARDWARE_FLOW = False
    TIMEOUT = 3.0

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        # Shown by CHIRP when the model is selected (wxui/clone.py:747-763)
        rp.experimental = (
            'Experimental BTECH UV-PRO driver. Edits are sent to the radio '
            'immediately. Channel read and write use only the group '
            'currently selected on the radio (shown in Settings after '
            'download). Switch groups on the radio, then Download again. '
            'Tested with the radio-reported soft_ver %i.'
            % TESTED_SOFT_VER)
        return rp

    def __init__(self, *args, **kwargs):
        chirp_common.LiveRadio.__init__(self, *args, **kwargs)
        self._memcache = {}
        # CHIRP gives each live-radio editor tab its own RadioThread on the
        # same driver object (chirp/wxui/main.py:359-364), so serialise all
        # serial I/O. get_settings itself does no I/O (uses values cached
        # at connect); set_settings never talks to the radio.
        self._io_lock = threading.RLock()
        self.dev_info = None
        self._curr_region = None          # int or None
        self._region_name = ''            # active group name, may be ''
        if self.pipe:
            # Read whole frames by length with a generous timeout instead
            # of polling. write_timeout comes from open_serial / chirpc.
            self.pipe.timeout = self.TIMEOUT
            self._connect()

    # ---- transport -----------------------------------------------------
    def _read_exact(self, count, cmd):
        data = self.pipe.read(count)
        if len(data) != count:
            raise errors.RadioError('No response from radio (cmd %i): got '
                                    '%i of %i bytes' % (cmd, len(data),
                                                        count))
        return data

    def _read_frame(self, cmd):
        """Read one GAIA frame: 4-byte header, then exactly the length it
        announces. Returns group/command header + body."""
        magic, version, flags, length = struct.unpack(
            GAIA_HDR_FMT, self._read_exact(4, cmd))
        if (magic, version) != (0xFF, 0x01):
            raise errors.RadioError('Unexpected data from radio (cmd %i): '
                                    '%02x %02x' % (cmd, magic, version))
        # 4 bytes group+command, body, optional checksum byte (flags & 1)
        msg = self._read_exact(4 + length + (flags & 1), cmd)
        return msg[:4 + length]

    def _request(self, cmd, body):
        with self._io_lock:
            return self._request_locked(cmd, body)

    def _request_locked(self, cmd, body):
        frame = build_frame(cmd, body)
        self.pipe.log('GAIA cmd %i' % cmd)
        self.pipe.write(frame)
        while True:
            msg = self._read_frame(cmd)
            grp, c = struct.unpack(GAIA_CMD_FMT, msg[:4])
            if grp == GROUP_BASIC and c == (0x8000 | cmd):
                return msg[4:]
            LOG.debug('Ignoring unrelated message %i/0x%04x', grp, c)

    def _connect(self):
        reply = self._request(CMD_GET_DEV_INFO, b'\x03')
        if not reply or reply[0] != STATUS_SUCCESS:
            raise errors.RadioError('GET_DEV_INFO failed')
        self.dev_info = parse_dev_info(reply[1:])
        LOG.info('UV-PRO dev info: %s', self.dev_info)
        if self.dev_info['soft_ver'] != TESTED_SOFT_VER:
            LOG.warning('UV-PRO firmware soft_ver=%i is untested '
                        '(tested: %i); writes are blocked',
                        self.dev_info['soft_ver'], TESTED_SOFT_VER)
        # Read-only group detection (no SET_REGION). Failures are soft: the
        # driver still works for the active group; Settings just won't show
        # a name.
        self._probe_active_group()

    def _probe_active_group(self):
        """Cache curr_region + its name via cmds 20 and 73 (read-only)."""
        self._curr_region = None
        self._region_name = ''
        try:
            reply = self._request(CMD_GET_HT_STATUS, b'')
            if not reply or reply[0] != STATUS_SUCCESS:
                LOG.debug('GET_HT_STATUS status %r',
                          reply[0] if reply else None)
                return
            self._curr_region = parse_ht_status_curr_region(reply[1:])
            if self._curr_region is None:
                return
            reply = self._request(CMD_READ_REGION_NAME,
                                  bytes([self._curr_region & 0xFF]))
            if not reply or reply[0] != STATUS_SUCCESS:
                LOG.debug('READ_REGION_NAME status %r',
                          reply[0] if reply else None)
                return
            idx, name = parse_region_name(reply[1:])
            if idx == self._curr_region:
                self._region_name = name
            LOG.info('UV-PRO active group %s %r',
                     self._curr_region, self._region_name)
        except errors.RadioError as e:
            LOG.debug('Active-group probe failed: %s', e)

    def _read_raw(self, number):
        reply = self._request(CMD_READ_RF_CH, bytes([number & 0xFF]))
        if reply[0] != STATUS_SUCCESS:
            return reply[0], None
        return STATUS_SUCCESS, bytes(reply[1:])

    def _write_raw(self, number, rec):
        reply = self._request(CMD_WRITE_RF_CH, rec)
        if reply[0] != STATUS_SUCCESS:
            raise errors.RadioError('Radio refused write to %i (status %i)'
                                    % (number, reply[0]))
        if len(reply) > 1 and reply[1] != number:
            raise errors.RadioError('Radio acknowledged channel %i, '
                                    'expected %i' % (reply[1], number))

    # ---- CHIRP API: read ------------------------------------------------
    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, CHANNELS_PER_GROUP - 1)
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        # DCS polarity is NN only. CHIRP's validate_memory rejects the rest
        # via valid_dtcs_pols (has_dtcs_polarity stays at its default).
        rf.has_dtcs = True
        rf.valid_dtcs_pols = ['NN']
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0,
                                 50.0]
        rf.has_settings = True           # driver-only write switch
        rf.has_name = True
        rf.valid_name_length = NAME_LEN
        rf.valid_characters = chirp_common.CHARSET_ASCII
        # AM: airband receive-only memories (duplex off). DMR: shown only so
        # a DMR record can be displayed; writing DMR is always refused.
        rf.valid_modes = ['FM', 'NFM', 'AM', 'DMR']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', '->Tone', 'DTCS->', '->DTCS',
                                'Tone->DTCS', 'DTCS->Tone', 'DTCS->DTCS']
        # 'off' = TX disabled (record byte 13 & 0x01)
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_bands = [AIRBAND, (136000000, 174000000),
                          (400000000, 520000000)]
        rf.can_odd_split = True
        rf.valid_skips = ['', 'S']
        return rf

    def get_memory(self, number):
        with self._io_lock:
            return self._get_memory_locked(number)

    def _get_memory_locked(self, number):
        if number in self._memcache:
            return self._memcache[number].dupe()
        mem = chirp_common.Memory()
        mem.number = number
        status, raw = self._read_raw(number)
        if status != STATUS_SUCCESS:
            LOG.debug('Channel %i status %i -> empty', number, status)
            mem.empty = True
            return mem
        ch = parse_rf_ch(raw)
        if ch.rx_hz == 0:
            mem.empty = True
            self._memcache[number] = mem
            return mem.dupe()
        mem.freq = int(ch.rx_hz)
        tx = int(ch.tx_hz)
        if ch.tx_disable or tx == 0:
            # tx 0: the radio zeroes TX freq on AM airband (2026-11-02)
            mem.duplex, mem.offset = 'off', 0
        elif tx == mem.freq:
            mem.duplex = ''
        elif abs(tx - mem.freq) > 70000000:
            mem.duplex, mem.offset = 'split', tx
        else:
            mem.duplex = '+' if tx > mem.freq else '-'
            mem.offset = abs(tx - mem.freq)
        if MOD_DMR in (ch.rx_mod, ch.tx_mod) or len(raw) != RFCH_LEN:
            mem.mode = 'DMR'
        elif ch.rx_mod == MOD_AM:
            mem.mode = 'AM'
        else:
            mem.mode = 'FM' if ch.wide else 'NFM'
        chirp_common.split_tone_decode(mem, _sub_to_tone(int(ch.tx_sub)),
                                       _sub_to_tone(int(ch.rx_sub)))
        # Power = 2 independent flags in byte 13: max 0x40, med 0x02; neither =
        # Low (HTCommander@0664721 src/lib/radio/radio_models.dart:543,550
        # read, :581,586 write; benlink rf_ch.py:53,58; HTCommander test
        # radio_channel_notification_test.dart:52-55: 1E=med, 5C=high, 1C=low)
        if ch.max_power:
            mem.power = POWER_LEVELS[2]
        elif ch.med_power:
            mem.power = POWER_LEVELS[1]
        else:
            mem.power = POWER_LEVELS[0]
        # scan bit set = in scan list (HTCommander radio_models.dart:542,
        # channel_export.dart:45); hardware-confirmed 2026-11-01
        mem.skip = '' if ch.scan else 'S'
        mem.name = rf_ch_name(ch)
        self._memcache[number] = mem
        return mem.dupe()

    # ---- CHIRP API: write (gated) ---------------------------------------
    # ---- driver setting: write switch (never sent to the radio) ---------
    def get_settings(self):
        # Pure in-memory: a fresh object tree every call, no radio I/O, no
        # locks, cannot raise (same shape as kenwood_live.py:1086-1092).
        # Group fields were cached at connect (_probe_active_group).
        grp = RadioSettingGroup('driver', 'Driver')
        info = self.dev_info or {}
        if self._curr_region is None:
            label = '(unknown - switch groups on the radio, then Download)'
        elif self._region_name:
            label = '%i (%s)' % (self._curr_region, self._region_name)
        else:
            label = '%i' % self._curr_region
        active = RadioSettingValueString(0, 40, label, autopad=False)
        active.set_mutable(False)
        grp.append(RadioSetting('active_group',
                                'Active group (read-only; change on radio)',
                                active))
        rc = RadioSettingValueString(
            0, 8, str(info.get('region_count', '?')), autopad=False)
        rc.set_mutable(False)
        grp.append(RadioSetting('region_count', 'Group count (from radio)',
                                rc))
        cc = RadioSettingValueString(
            0, 8, str(info.get('channel_count', CHANNELS_PER_GROUP)),
            autopad=False)
        cc.set_mutable(False)
        grp.append(RadioSetting('channel_count',
                                'Channels per group (from radio)', cc))
        return RadioSettings(grp)

    def set_settings(self, settings):
        # The settings shown here are read-only. Nothing is sent.
        return

    def _check_writable(self, number):
        if not self.dev_info or \
                self.dev_info.get('soft_ver') != TESTED_SOFT_VER:
            raise errors.RadioError(
                'Writes refused: firmware soft_ver %s is not the tested %i'
                % (self.dev_info and self.dev_info.get('soft_ver'),
                   TESTED_SOFT_VER))
        if not isinstance(number, int) or \
                not 0 <= number < CHANNELS_PER_GROUP:
            raise errors.RadioError('Writes refused: memory %r outside '
                                    '0-%i' % (number, CHANNELS_PER_GROUP - 1))

    @staticmethod
    def _tones(mem):
        """Return (tx_sub, rx_sub) raw values (CTCSS, or normal DCS)."""
        tx, rx = chirp_common.split_tone_encode(mem)
        return _tone_to_sub(tx), _tone_to_sub(rx)

    def _apply(self, ch, mem):
        """Edit only CHIRP-modelled fields of a decoded record."""
        if mem.mode == 'DMR':
            raise errors.RadioError('Refused: DMR is not supported (the '
                                    'UV-PRO is analog only)')
        if mem.mode not in ('FM', 'NFM', 'AM'):
            raise errors.RadioError('Refused: mode %s not supported'
                                    % mem.mode)
        airband = AIRBAND[0] <= mem.freq < AIRBAND[1]
        if mem.mode == 'AM':
            # Receive-only airband memory: AM both ways, TX disabled.
            # Any duplex is coerced to receive-only (M9): CHIRP band
            # defaults pick AM but leave duplex ''.
            if not airband or mem.tmode != '':
                raise errors.RadioError(
                    'Refused: AM is receive-only airband (108-136 MHz) '
                    'with no tone')
        elif airband:
            raise errors.RadioError('Refused: 108-136 MHz is AM airband '
                                    '(receive-only); use mode AM')
        tx_sub, rx_sub = self._tones(mem)
        ch.id = mem.number
        mod = MOD_AM if mem.mode == 'AM' else MOD_FM
        ch.tx_mod = mod
        ch.rx_mod = mod
        ch.rx_hz = mem.freq
        ch.tx_disable = 0
        duplex = 'off' if mem.mode == 'AM' else mem.duplex
        if duplex == '':
            ch.tx_hz = mem.freq
        elif duplex == '+':
            ch.tx_hz = mem.freq + mem.offset
        elif duplex == '-':
            ch.tx_hz = mem.freq - mem.offset
        elif duplex == 'split':
            ch.tx_hz = mem.offset
        elif duplex == 'off':
            # The radio stores AM airband with TX freq 0 (tx word
            # 0x40000000, AM bits kept); match it so read-back verifies.
            ch.tx_hz = 0 if mem.mode == 'AM' else mem.freq
            ch.tx_disable = 1
        else:
            raise errors.RadioError('Refused: duplex %r' % duplex)
        ch.tx_sub = tx_sub
        ch.rx_sub = rx_sub
        # AM: wide, as HTCommander's CSV import does (channel_import.dart)
        ch.wide = 1 if mem.mode in ('FM', 'AM') else 0
        level = str(mem.power) if mem.power else 'High'
        if level not in ('Low', 'Med', 'High'):
            raise errors.RadioError('Refused: power level %r' % level)
        ch.max_power = 1 if level == 'High' else 0
        ch.med_power = 1 if level == 'Med' else 0
        ch.scan = 0 if mem.skip == 'S' else 1
        name = mem.name.encode('ascii', 'replace')[:NAME_LEN]
        ch.name.set_raw(name.ljust(NAME_LEN, b'\x00'))
        return ch

    def validate_memory(self, mem):
        """Every set_memory refusal, as a ValidationError, so CHIRP's grid
        shows it (memedit _memory_edited) before any write job runs.
        set_memory/_apply keep the same guards as a backstop."""
        msgs = super().validate_memory(mem)
        if mem.empty:
            return msgs
        err = chirp_common.ValidationError
        try:
            self._check_writable(mem.number)
        except errors.RadioError as e:
            msgs.append(err(str(e)))
        old = self._memcache.get(mem.number)
        if old is not None and not old.empty and old.mode == 'DMR':
            msgs.append(err('Memory %i holds a DMR record; edit it in the '
                            'BTECH app' % mem.number))
        airband = AIRBAND[0] <= mem.freq < AIRBAND[1]
        if mem.mode == 'DMR':
            msgs.append(err('DMR is not supported (the UV-PRO is analog '
                            'only)'))
        elif mem.mode == 'AM':
            if not airband:
                msgs.append(err('AM is only allowed in the 108-136 MHz '
                                'airband'))
            if mem.tmode != '':
                msgs.append(err('AM airband is receive-only; tones are not '
                                'allowed'))
            if airband and mem.duplex != 'off':
                msgs.append(chirp_common.ValidationWarning(
                    'AM airband is receive-only; saved with Duplex off'))
        elif airband:
            msgs.append(err('108-136 MHz is AM airband (receive-only); use '
                            'mode AM'))
        try:
            self._tones(mem)
        except errors.RadioError as e:
            msgs.append(err(str(e).replace('Refused: ', '')))
        return msgs

    def _write_verify(self, number, before, rec):
        self._memcache.pop(number, None)
        if rec == before:
            LOG.info('Memory %i unchanged on radio; write skipped', number)
            return
        try:
            self._write_raw(number, rec)
            status, after = self._read_raw(number)
            if status != STATUS_SUCCESS or after != rec:
                raise errors.RadioError(
                    'Read-back mismatch on memory %i: sent %s got %s'
                    % (number, rec.hex(' '),
                       after.hex(' ') if after else 'status %i' % status))
        except errors.RadioError as e:
            msg = str(e)
            try:
                self._write_raw(number, before)
                status, again = self._read_raw(number)
                if again == before:
                    msg += '; original record restored and verified'
                else:
                    msg += ('; RESTORE NOT VERIFIED; read the channel '
                            'before another edit')
            except errors.RadioError as e2:
                msg += ('; restore failed (%s); read the channel before '
                        'another edit' % e2)
            LOG.error(msg)
            raise errors.RadioError(msg)
        LOG.info('Memory %i written and verified', number)

    def set_memory(self, memory):
        with self._io_lock:
            return self._set_memory_locked(memory)

    def _set_memory_locked(self, memory):
        self._check_writable(memory.number)
        if memory.empty:
            return self.erase_memory(memory.number)
        status, before = self._read_raw(memory.number)
        if status != STATUS_SUCCESS or len(before) != RFCH_LEN:
            raise errors.RadioError('Refused: could not read memory %i '
                                    'before writing (status %i, %i bytes; '
                                    'DMR records unsupported)'
                                    % (memory.number, status,
                                       len(before or b'')))
        old = parse_rf_ch(before)
        if MOD_DMR in (old['rx_mod'], old['tx_mod']):
            raise errors.RadioError('Refused: memory %i holds a DMR record; '
                                    'edit it in the BTECH app'
                                    % memory.number)
        ch = self._apply(old, memory)
        LOG.info('Memory %i: power=%s skip=%r -> byte13=0x%02x', memory.number,
                 memory.power, memory.skip, ch.get_raw()[13])
        self._write_verify(memory.number, before, ch.get_raw())

    def erase_memory(self, number):
        with self._io_lock:
            return self._erase_memory_locked(number)

    def _erase_memory_locked(self, number):
        self._check_writable(number)
        status, before = self._read_raw(number)
        if status != STATUS_SUCCESS:
            raise errors.RadioError('Refused: could not read memory %i '
                                    '(status %i)' % (number, status))
        # Empty = channel id byte then 24 zero bytes (hardware-verified
        # restore of index 29, 2026-11-01)
        self._write_verify(number, before, bytes([number]) + bytes(24))
