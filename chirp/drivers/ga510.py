# Copyright 2024 Dan Smith <dsmith@danplanet.com>
# Portions copyright 2023 Dave Liske <dave@micuisine.com>
# Portions copyright 2020 by Jiauxn Yang <jiaxun.yang@flygoat.com>
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
import struct

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp.drivers import baofeng_uv17
from chirp.drivers import baofeng_uv17Pro
from chirp import errors
from chirp import memmap
from chirp.settings import RadioSetting, RadioSettingGroup, RadioSettings
from chirp.settings import RadioSettingValueBoolean, RadioSettingValueList
from chirp.settings import RadioSettingValueInteger, RadioSettingValueString

LOG = logging.getLogger(__name__)

# GA510 and SHX8800 also have DTCS code 645
DTCS_CODES = tuple(sorted(chirp_common.DTCS_CODES + (645,)))

DTMFCHARS = '0123456789ABCD*#'
AIRBAND = (108000000, 136000000)


def reset(radio):
    try:
        radio.pipe.write(b'E')
    except Exception as e:
        LOG.error('Failed to reset radio: %s' % e)


def start_program(radio):
    reset(radio)
    radio.pipe.read(256)
    radio.pipe.write(radio._magic)
    ack = radio.pipe.read(256)
    if not ack.endswith(b'\x06'):
        LOG.debug('Ack was %r' % ack)
        raise errors.RadioError('Radio did not respond to clone request')

    radio.pipe.write(b'F')

    ident = radio.pipe.read(8)
    LOG.debug('Radio ident string is %r' % ident)

    return ident


def do_download(radio):
    # No start_program() here because it was done in detect_from_serial()

    s = chirp_common.Status()
    s.msg = 'Downloading'
    s.max = 0x1C00

    data = bytes()
    for addr in range(0, 0x1C40, 0x40):
        cmd = struct.pack('>cHB', b'R', addr, 0x40)
        LOG.debug('Reading block at %04x: %r' % (addr, cmd))
        radio.pipe.write(cmd)

        block = radio.pipe.read(0x44)
        header = block[:4]
        rcmd, raddr, rlen = struct.unpack('>BHB', header)
        block = block[4:]
        if raddr != addr:
            raise errors.RadioError('Radio send address %04x, expected %04x' %
                                    (raddr, addr))
        if rlen != 0x40 or len(block) != 0x40:
            raise errors.RadioError('Radio sent %02x (%02x) bytes, '
                                    'expected %02x' % (rlen, len(block), 0x40))

        data += block

        s.cur = addr
        radio.status_fn(s)

    return data


def do_upload(radio):
    ident = start_program(radio)

    s = chirp_common.Status()
    s.msg = 'Uploading'
    s.max = 0x1C00

    # The factory software downloads 0x40 for the block
    # at 0x1C00, but only uploads 0x20 there. Mimic that
    # here.
    for addr in range(0, 0x1C20, 0x20):
        cmd = struct.pack('>cHB', b'W', addr, 0x20)
        LOG.debug('Writing block at %04x: %r' % (addr, cmd))
        block = radio._mmap[addr:addr + 0x20]
        radio.pipe.write(cmd)
        radio.pipe.write(block)

        ack = radio.pipe.read(1)
        if ack != b'\x06':
            raise errors.RadioError('Radio refused block at addr %04x' % addr)

        s.cur = addr
        radio.status_fn(s)


BASE_FORMAT = """
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 signal;
  u8 unknown1:6,
     pttid:2;
  u8 unknown2:6,
     power:2;
  u8 unknown3_0:1,
     narrow:1,
     unknown3_1:2,
     bcl:1,
     scan:1,
     allow_tx:1,	// SHX8800 FAMILY ONLY (unknown3_2 for GA-510)
     fhss:1;
} memories[128];

#seekto 0x0C00;
struct {
  char name[10];
  u8 pad[6];
} names[128];

"""

MODEL_GA510_FORMAT = """
#seekto 0x1A00;
struct {
  // 0x1A00
  u8 squelch;
  u8 savemode; // [off, mode1, mode2, mode3]
  u8 vox; // off=0
  u8 backlight;
  u8 tdr; // bool
  u8 timeout; // n*15 = seconds
  u8 beep; // bool
  u8 voice;

  // 0x1A08
  u8 language; // [eng, chin]
  u8 dtmfst;
  u8 scanmode; // [TO, CO, SE]
  u8 pttid; // [off, BOT, EOT, Both]
  u8 pttdelay; // 0-30
  u8 cha_disp; // [ch-name, ch-freq]
               // [ch, ch-name]; retevis
  u8 chb_disp;
  u8 bcl; // bool

  // 0x1A10
  u8 autolock; // bool
  u8 alarm_mode; // [site, tone, code]
  u8 alarmsound; // bool
  u8 txundertdr; // [off, bandA, bandB]
  u8 tailnoiseclear; // [off, on]
  u8 rptnoiseclr; // 10*ms, 0-1000
  u8 rptnoisedet;
  u8 roger; // bool

  // 0x1A18
  u8 unknown1a10;
  u8 fmradio; // boolean, inverted
  u8 workmode; // [vfo, chan]; 1A30-1A31 related?
  u8 kblock; // boolean
} settings;

#seekto 0x1A80;
struct {
  u8 skey1sp; // [off, lamp, sos, fm, noaa, moni, search]
  u8 skey1lp; // [off, lamp, sos, fm, noaa, moni, search]
  u8 skey2sp; // [off, lamp, sos, fm, noaa, moni, search]
  u8 skey2lp; // [off, lamp, sos, fm, noaa, moni, search]
} skey;

struct dtmfcode {
  u8 code[5];
  u8 ffpad[11]; // always 0xFF
};
#seekto 0x1B00;
struct dtmfcode dtmfgroup[15];
struct {
  u8 code[5];
  u8 groupcode; // 0->D, *, #
  u8 nothing:6,
     releasetosend:1,
     presstosend:1;
  u8 dtmfspeedon; // 80 + n*10, up to [194]
  u8 dtmfspeedoff;
} anicode;

//dtmf on -> 90ms
//dtmf off-> 120ms
//group code *->0
//press 0->1
//release 1->0

"""

MODEL_SHX8800_FORMAT = """
#seekto 0x1A00;
struct {
  // 0x1A00
  u8 squelch;
  u8 savemode; // [off, mode1, mode2, mode3]
  u8 vox; // off=0
  u8 backlight;
  u8 tdr; // bool
  u8 timeout; // n*15 = seconds
  u8 beep; // bool
  u8 voice;

  // 0x1A08
  u8 language; // [inop in 8800]
  u8 dtmfst;
  u8 scanmode; // [TO, CO, SE]
  u8 pttid; // [off, BOT, EOT, Both]
  u8 pttdelay; // 0-30
  u8 cha_disp; // [ch-name, ch-freq]
               // [ch, ch-name]; retevis
  u8 chb_disp;
  u8 bcl; // bool

  // 0x1A10
  u8 autolock; // bool
  u8 alarm_mode; // [site, tone, code]
  u8 alarmsound; // bool
  u8 txundertdr; // [off, bandA, bandB]
  u8 tailnoiseclear; // [off, on]
  u8 rptnoiseclr; // 10*ms, 0-1000
  u8 rptnoisedet;
  u8 roger; // bool

  // 0x1A18
  u8 unknown1a10;
  u8 fmradio; // boolean, inverted
  u8 workmodeb:4,
     workmodea:4;
  u8 kblock;
  u8 unknown2[4];
  u8 voxdelay;
  u8 menu_timeout;
  u8 micgain;
} settings;

#seekto 0x1a40;
struct {
  u8 freq[8];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown[2];
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown1;
  u8 txpower;
  u8 widenarr:1,
     unknown2:4,
     fhss:1,
     unknown3:2;
  u8 band;
  u8 unknown4:5,
     step:3;
  u8 unknown5;
  u8 offset[6];
} vfoa;			// displays in Browser tab

#seekto 0x1a60;
struct {
  u8 freq[8];
  ul16 rxtone;
  ul16 txtone;
  u8 unknown[2];
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown1;
  u8 txpower;
  u8 widenarr:1,
     unknown2:4,
     fhss:1,
     unknown3:2;
  u8 band;
  u8 unknown4:5,
     step:3;
  u8 unknown5;
  u8 offset[6];
} vfob;			// displays in Browser tab

#seekto 0x1a80;
struct {
    u8 sidekey;
    u8 sidekeyl;
} keymaps;

#seekto 0x1b00;
struct {
  u8 code[5];
  u8 unused[11];
} dtmfgroup[15];

struct {
  u8 code[5];
  u8 groupcode;
  u8 aniid;
  u8 dtmfspeedon;
  u8 dtmfspeedoff;
} anicode;

"""

PTTID = ['Off', 'BOT', 'EOT', 'Both']
SIGNAL = [str(i) for i in range(1, 16)]
WORKMODE_LIST = ["VFO", "CH"]
SHIFTD_LIST = ["Off", "+", "-"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 128)]
STEPS = [6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
STEP_LIST = [str(x) for x in STEPS]
TXPOWER_LIST = ["High (5W)", "Low (1W)"]
BANDWIDTH_LIST = ["Wide", "Narrow"]


@directory.register
class RadioddityGA510Radio(chirp_common.CloneModeRadio):
    VENDOR = 'Radioddity'
    MODEL = 'GA-510'
    BAUD_RATE = 9600
    POWER_LEVELS = [
        chirp_common.PowerLevel('H', watts=10),
        chirp_common.PowerLevel('L', watts=1),
        chirp_common.PowerLevel('M', watts=5)]

    _mem_format = MODEL_GA510_FORMAT
    _magic = (b'PROGROMBFHU')

    _gmrs = False

    @classmethod
    def detect_from_serial(cls, pipe):
        for rcls in reversed(cls.detected_models()):
            pipe.baudrate = rcls.BAUD_RATE
            radio = rcls(pipe)
            try:
                if isinstance(radio, baofeng_uv17Pro.UV17Pro):
                    ident = baofeng_uv17Pro._do_ident(radio)
                else:
                    ident = start_program(radio)
            except errors.RadioError:
                LOG.debug('No response from radio with %s', rcls)
                pipe.read(256)
                continue
            if ident:
                return rcls
        raise errors.RadioError('No response from radio')

    def sync_in(self):
        try:
            data = do_download(self)
            self._mmap = memmap.MemoryMapBytes(data)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('General failure')
            raise errors.RadioError('Failed to download from radio: %s' % e)
        finally:
            reset(self)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception('General failure')
            raise errors.RadioError('Failed to upload to radio: %s' % e)
        finally:
            reset(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(BASE_FORMAT + self._mem_format,
                                     self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, 127)
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_settings = True
        rf.has_bank = False
        rf.has_sub_devices = False
        rf.has_dtcs_polarity = True
        rf.has_rx_dtcs = True
        rf.can_odd_split = True
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = ['Tone->Tone', 'DTCS->', '->DTCS', 'Tone->DTCS',
                                'DTCS->Tone', '->Tone', 'DTCS->DTCS']
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 12.5, 10.0, 15.0, 20.0,
                                 25.0, 50.0, 100.0]
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_name_length = 10
        rf.valid_characters = ('ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                               'abcdefghijklmnopqrstuvwxyz'
                               '0123456789'
                               '!"#$%&\'()~+-,./:;<=>?@[\\]^`{}*| ')
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 480000000)]
        return rf

    def get_raw_memory(self, num):
        return repr(self._memobj.memories[num]) + repr(self._memobj.names[num])

    @staticmethod
    def _decode_tone(toneval):
        if toneval in (0, 0xFFFF):
            LOG.debug('no tone value: %s' % toneval)
            return '', None, None
        elif toneval < 670:
            toneval = toneval - 1
            index = toneval % len(DTCS_CODES)
            if index != int(toneval):
                pol = 'R'
                # index -= 1
            else:
                pol = 'N'
            return 'DTCS', DTCS_CODES[index], pol
        else:
            return 'Tone', toneval / 10.0, 'N'

    @staticmethod
    def _encode_tone(mode, val, pol):
        if not mode:
            return 0x0000
        elif mode == 'Tone':
            return int(val * 10)
        elif mode == 'DTCS':
            index = DTCS_CODES.index(val)
            if pol == 'R':
                index += len(DTCS_CODES)
            index += 1
            LOG.debug('Encoded dtcs %s/%s to %04x' % (val, pol, index))
            return index
        else:
            raise errors.RadioError('Unsupported tone mode %r' % mode)

    def _get_extra(self, _mem):
        group = RadioSettingGroup('extra', 'Extra')

        s = RadioSetting('bcl', 'Busy Channel Lockout',
                         RadioSettingValueBoolean(_mem.bcl))
        group.append(s)

        s = RadioSetting('fhss', 'FHSS',
                         RadioSettingValueBoolean(_mem.fhss))
        group.append(s)

        # pttid, signal

        s = RadioSetting('pttid', 'PTTID',
                         RadioSettingValueList(PTTID, int(_mem.pttid)))
        group.append(s)

        s = RadioSetting('signal', 'Signal',
                         RadioSettingValueList(SIGNAL, int(_mem.signal)))
        group.append(s)

        return group

    def _set_extra(self, _mem, mem):
        _mem.bcl = int(mem.extra['bcl'].value)
        _mem.fhss = int(mem.extra['fhss'].value)
        _mem.pttid = int(mem.extra['pttid'].value)
        _mem.signal = int(mem.extra['signal'].value)

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw(asbytes=False)
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def _get_mem(self, num):
        return self._memobj.memories[num]

    def _get_nam(self, num):
        return self._memobj.names[num]

    def get_memory(self, num):
        _mem = self._get_mem(num)
        _nam = self._get_nam(num)
        mem = chirp_common.Memory()
        mem.number = num
        if int(_mem.rxfreq) == 166666665:
            mem.empty = True
            return mem

        mem.name = ''.join([str(c) for c in _nam.name
                            if ord(str(c)) < 127]).rstrip()
        mem.freq = int(_mem.rxfreq) * 10
        offset = (int(_mem.txfreq) - int(_mem.rxfreq)) * 10
        if self._is_txinh(_mem):
            mem.duplex = 'off'
            mem.offset = 0
        elif offset == 0:
            mem.duplex = ''
        elif abs(offset) < 100000000:
            mem.duplex = offset < 0 and '-' or '+'
            mem.offset = abs(offset)
        else:
            mem.duplex = 'split'
            mem.offset = int(_mem.txfreq) * 10

        mem.power = self.POWER_LEVELS[_mem.power]
        mem.mode = 'NFM' if _mem.narrow else 'FM'
        mem.skip = '' if _mem.scan else 'S'

        LOG.debug('got txtone: %s' % repr(self._decode_tone(_mem.txtone)))
        LOG.debug('got rxtone: %s' % repr(self._decode_tone(_mem.rxtone)))
        chirp_common.split_tone_decode(mem,
                                       self._decode_tone(_mem.txtone),
                                       self._decode_tone(_mem.rxtone))
        try:
            mem.extra = self._get_extra(_mem)
        except:
            LOG.exception('Failed to get extra for %i' % num)

        return mem

    def _set_mem(self, number):
        return self._memobj.memories[number]

    def _set_nam(self, number):
        return self._memobj.names[number]

    def set_memory(self, mem):
        _mem = self._set_mem(mem.number)
        _nam = self._set_nam(mem.number)

        if mem.empty:
            _mem.set_raw(b'\xff' * 16)
            _nam.set_raw(b'\xff' * 16)
            return

        if int(_mem.rxfreq) == 166666665:
            LOG.debug('Initializing new memory %i' % mem.number)
            _mem.set_raw(b'\x00' * 16)

        _nam.name = mem.name.ljust(10)

        if isinstance(self, Senhaix8800Radio):
            _mem.allow_tx = True

        _mem.rxfreq = mem.freq // 10
        if mem.duplex == '':
            _mem.txfreq = mem.freq // 10
        elif mem.duplex == 'split':
            _mem.txfreq = mem.offset // 10
        elif mem.duplex == 'off':
            if isinstance(self, Senhaix8800Radio):
                _mem.allow_tx = False
            for i in range(0, 4):
                _mem.txfreq[i].set_raw(b'\xFF')
        elif mem.duplex == '-':
            _mem.txfreq = (mem.freq - mem.offset) // 10
        elif mem.duplex == '+':
            _mem.txfreq = (mem.freq + mem.offset) // 10
        else:
            raise errors.RadioError('Unsupported duplex mode %r' % mem.duplex)

        txtone, rxtone = chirp_common.split_tone_encode(mem)
        LOG.debug('tx tone is %s' % repr(txtone))
        LOG.debug('rx tone is %s' % repr(rxtone))
        _mem.txtone = self._encode_tone(*txtone)
        _mem.rxtone = self._encode_tone(*rxtone)

        try:
            _mem.power = self.POWER_LEVELS.index(mem.power)
        except ValueError:
            _mem.power = 0
        _mem.narrow = mem.mode == 'NFM'
        _mem.scan = mem.skip != 'S'
        if mem.extra:
            self._set_extra(_mem, mem)

    def get_settings(self):
        _set = self._memobj.settings

        basic = RadioSettingGroup('basic', 'Basic')
        adv = RadioSettingGroup('advanced', 'Advanced')
        dtmf = RadioSettingGroup('dtmf', 'DTMF')

        radioddity_settings = {
            'savemode': ['Off', 'Mode 1', 'Mode 2', 'Mode 3'],
            'cha_disp': ['CH+Name', 'CH+Freq'],
            'chb_disp': ['CH+Name', 'CH+Freq'],
            'txundertdr': ['Off', 'Band A', 'Band B'],
            'rptnoiseclr': ['Off'] + ['%i' % i for i in range(100, 1001, 100)],
            'rptnoisedet': ['Off'] + ['%i' % i for i in range(100, 1001, 100)],
        }

        retevis_settings = {
            'savemode': ['Off', 'On'],
            'cha_disp': ['CH', 'CH+Name'],
            'chb_disp': ['CH', 'CH+Name'],
        }

        language_setting = {
            'language': ['English', 'Chinese'],
        }

        ga_workmode = {
            'workmode': ['VFO', 'Chan'],
        }

        shx_workmode = {
            'workmodea': ['VFO', 'Chan'],
            'workmodeb': ['VFO', 'Chan'],
        }

        choice_settings = {
            'vox': ['Off'] + ['%i' % i for i in range(1, 11)],
            'backlight': ['Off'] + ['%i' % i for i in range(1, 11)],
            'timeout': ['Off'] + ['%i' % i for i in range(15, 615, 15)],
            'dtmfst': ['OFF', 'KB Side Tone', 'ANI Side Tone',
                       'KB ST+ANI ST', 'Both'],
            'scanmode': ['TO', 'CO', 'SE'],
            'pttid': ['Off', 'BOT', 'EOT', 'Both'],
            'alarm_mode': ['Site', 'Tone', 'Code'],
        }

        if isinstance(self, Senhaix8800Radio):
            choice_settings.update(shx_workmode)
        else:
            choice_settings.update(language_setting)
            choice_settings.update(ga_workmode)

        if self.VENDOR == "Retevis":
            choice_settings.update(retevis_settings)
        else:
            choice_settings.update(radioddity_settings)

        if isinstance(self, Senhaix8800Radio):
            basic_settings = ['timeout', 'vox', 'backlight',
                              'cha_disp', 'chb_disp', 'workmodea',
                              'workmodeb']
        else:
            basic_settings = ['timeout', 'vox', 'backlight', 'language',
                              'cha_disp', 'chb_disp', 'workmode']
        titles = {
            'savemode': 'Save Mode',
            'vox': 'VOX',
            'backlight': 'Auto Backlight',
            'timeout': 'Time Out Timer (s)',
            'language': 'Language',
            'dtmfst': 'DTMF-ST',
            'scanmode': 'Scan Mode',
            'pttid': 'PTT-ID',
            'cha_disp': 'Channel A Display',
            'chb_disp': 'Channel B Display',
            'alarm_mode': 'Alarm Mode',
            'txundertdr': 'TX Under TDR',
            'rptnoiseclr': 'RPT Noise Clear (ms)',
            'rptnoisedet': 'RPT Noise Detect (ms)',
            'workmode': 'Work Mode',
            'workmodea': 'Work Mode A',
            'workmodeb': 'Work Mode B',
        }

        basic.append(
            RadioSetting('squelch', 'Squelch Level',
                         RadioSettingValueInteger(0, 9, int(_set.squelch))))
        adv.append(
            RadioSetting('pttdelay', 'PTT Delay',
                         RadioSettingValueInteger(0, 30, int(_set.pttdelay))))
        adv.append(
            RadioSetting('tdr', 'TDR',
                         RadioSettingValueBoolean(
                             int(_set.tdr))))
        adv.append(
            RadioSetting('beep', 'Beep',
                         RadioSettingValueBoolean(
                             int(_set.beep))))
        basic.append(
            RadioSetting('voice', 'Voice Enable',
                         RadioSettingValueBoolean(
                             int(_set.voice))))
        adv.append(
            RadioSetting('bcl', 'BCL',
                         RadioSettingValueBoolean(
                             int(_set.bcl))))
        adv.append(
            RadioSetting('autolock', 'Auto Lock',
                         RadioSettingValueBoolean(
                             int(_set.autolock))))
        adv.append(
            RadioSetting('alarmsound', 'Alarm Sound',
                         RadioSettingValueBoolean(
                             int(_set.alarmsound))))
        adv.append(
            RadioSetting('tailnoiseclear', 'Tail Noise Clear',
                         RadioSettingValueBoolean(
                             int(_set.tailnoiseclear))))
        adv.append(
            RadioSetting('roger', 'Roger',
                         RadioSettingValueBoolean(
                             int(_set.roger))))
        adv.append(
            RadioSetting('fmradio', 'FM Radio Disabled',
                         RadioSettingValueBoolean(
                             int(_set.fmradio))))
        adv.append(
            RadioSetting('kblock', 'KB Lock',
                         RadioSettingValueBoolean(
                             int(_set.kblock))))

        for key in sorted(choice_settings):
            choices = choice_settings[key]
            title = titles[key]
            if key in basic_settings:
                group = basic
            else:
                group = adv

            val = int(getattr(_set, key))
            try:
                cur = choices[val]
            except IndexError:
                LOG.error('Value %i for %s out of range for list (%i): %s' % (
                    val, key, len(choices), choices))
                raise
            group.append(
                RadioSetting(key, title,
                             RadioSettingValueList(
                                 choices,
                                 current_index=val)))

        if self.VENDOR == "Retevis":
            # Side Keys
            _skey = self._memobj.skey
            SK_CHOICES = ['OFF', 'LAMP', 'SOS', 'FM', 'NOAA', 'MONI', 'SEARCH']
            SK_VALUES = [0xFF, 0x08, 0x03, 0x07, 0x0C, 0x05, 0x1D]

            def apply_sk_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = SK_CHOICES.index(val)
                val = SK_VALUES[index]
                obj.set_value(val)

            # Side Key 1 - Short Press
            if _skey.skey1sp in SK_VALUES:
                idx = SK_VALUES.index(_skey.skey1sp)
            else:
                idx = SK_VALUES.index(0xFF)
            rs = RadioSetting('skey.skey1sp', 'Side Key 1 - Short Press',
                              RadioSettingValueList(SK_CHOICES,
                                                    current_index=idx))
            rs.set_apply_callback(apply_sk_listvalue, _skey.skey1sp)
            adv.append(rs)

            # Side Key 1 - Long Press
            if _skey.skey1lp in SK_VALUES:
                idx = SK_VALUES.index(_skey.skey1lp)
            else:
                idx = SK_VALUES.index(0xFF)
            rs = RadioSetting('skey.skey1lp', 'Side Key 1 - Long Press',
                              RadioSettingValueList(SK_CHOICES,
                                                    current_index=idx))
            rs.set_apply_callback(apply_sk_listvalue, _skey.skey1lp)
            adv.append(rs)

            # Side Key 2 - Short Press
            if _skey.skey2sp in SK_VALUES:
                idx = SK_VALUES.index(_skey.skey2sp)
            else:
                idx = SK_VALUES.index(0xFF)
            rs = RadioSetting('skey.skey2sp', 'Side Key 2 - Short Press',
                              RadioSettingValueList(SK_CHOICES,
                                                    current_index=idx))
            rs.set_apply_callback(apply_sk_listvalue, _skey.skey2sp)
            adv.append(rs)

            # Side Key 1 - Long Press
            if _skey.skey2lp in SK_VALUES:
                idx = SK_VALUES.index(_skey.skey2lp)
            else:
                idx = SK_VALUES.index(0xFF)
            rs = RadioSetting('skey.skey2lp', 'Side Key 2 - Long Press',
                              RadioSettingValueList(SK_CHOICES,
                                                    current_index=idx))
            rs.set_apply_callback(apply_sk_listvalue, _skey.skey2lp)
            adv.append(rs)

        for i in range(1, 16):
            cur = ''.join(
                DTMFCHARS[i]
                for i in self._memobj.dtmfgroup[i - 1].code if int(i) < 0xF)
            dtmf.append(
                RadioSetting(
                    'dtmf.code@%i' % i, 'DTMF Group %i' % i,
                    RadioSettingValueString(0, 5, cur,
                                            autopad=False,
                                            charset=DTMFCHARS)))
        cur = ''.join(
            '%X' % i
            for i in self._memobj.anicode.code if int(i) < 0xE)

        anicode = self._memobj.anicode

        if isinstance(self, Senhaix8800Radio):
            _codeobj = self._memobj.anicode.code
            _code = "".join([DTMFCHARS[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 5, _code, False)
            val.set_charset(DTMFCHARS)
            rs = RadioSetting("anicode.code", "ANI Code", val)

            def apply_code(setting, obj):
                code = []
                for j in range(0, 5):
                    try:
                        code.append(DTMFCHARS.index(str(setting.value)[j]))
                    except IndexError:
                        code.append(0xFF)
                obj.code = code

            rs.set_apply_callback(apply_code, anicode)

            dtmf.append(rs)

            try:
                current_group = DTMFCHARS[int(anicode.groupcode)]
            except IndexError:
                LOG.warning('ANI group code index %i out of range',
                            anicode.groupcode)
                current_group = DTMFCHARS[0]
            dtmf.append(
                RadioSetting(
                    "anicode.groupcode", "Group Code",
                    RadioSettingValueList(list(DTMFCHARS),
                                          current_group)))

        else:
            dtmf.append(
                RadioSetting(
                    'anicode.code', 'ANI Code',
                    RadioSettingValueString(0, 5, cur,
                                            autopad=False,
                                            charset=DTMFCHARS)))
            dtmf.append(
                RadioSetting(
                    'anicode.groupcode', 'Group Code',
                    RadioSettingValueList(
                        list(DTMFCHARS),
                        DTMFCHARS[int(anicode.groupcode)])))
            dtmf.append(
                RadioSetting(
                    'anicode.releasetosend', 'Release To Send',
                    RadioSettingValueBoolean(
                        int(anicode.releasetosend))))
            dtmf.append(
                RadioSetting(
                    'anicode.presstosend', 'Press To Send',
                    RadioSettingValueBoolean(
                        int(anicode.presstosend))))

        cur = int(anicode.dtmfspeedon) * 10 + 80
        dtmf.append(
            RadioSetting(
                'anicode.dtmfspeedon', 'DTMF Speed (on time in ms)',
                RadioSettingValueInteger(60, 2000, cur, 10)))
        cur = int(anicode.dtmfspeedoff) * 10 + 80
        dtmf.append(
            RadioSetting(
                'anicode.dtmfspeedoff', 'DTMF Speed (off time in ms)',
                RadioSettingValueInteger(60, 2000, cur, 10)))

        top = RadioSettings(basic, adv, dtmf)
        return top

    def set_settings(self, settings):
        for element in settings:
            if element.get_name().startswith('anicode.'):
                self._set_anicode(element)
            elif element.get_name().startswith('dtmf.code'):
                self._set_dtmfcode(element)
            elif element.get_name().startswith('skey.'):
                self._set_skey(element)
            elif not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                self._set_setting(element)

    def _set_setting(self, setting):
        key = setting.get_name()
        val = setting.value

        setattr(self._memobj.settings, key, int(val))

    def _set_anicode(self, setting):
        name = setting.get_name().split('.', 1)[1]
        if name == 'code':
            val = [DTMFCHARS.index(c) for c in str(setting.value)]
            for i in range(0, 5):
                try:
                    value = val[i]
                except IndexError:
                    value = 0xFF
                self._memobj.anicode.code[i] = value
        elif name.startswith('dtmfspeed'):
            setattr(self._memobj.anicode, name,
                    (int(setting.value) - 80) // 10)
        else:
            setattr(self._memobj.anicode, name, int(setting.value))

    def _set_dtmfcode(self, setting):
        index = int(setting.get_name().split('@', 1)[1]) - 1
        val = [DTMFCHARS.index(c) for c in str(setting.value)]
        for i in range(0, 5):
            try:
                value = val[i]
            except IndexError:
                value = 0xFF
            self._memobj.dtmfgroup[index].code[i] = value

    def _set_skey(self, setting):
        if setting.has_apply_callback():
            LOG.debug("Using apply callback")
            setting.run_apply_callback()


@directory.register
class RetevisRA685Radio(RadioddityGA510Radio):
    VENDOR = 'Retevis'
    MODEL = 'RA685'
    POWER_LEVELS = [
        chirp_common.PowerLevel('H', watts=5),
        chirp_common.PowerLevel('L', watts=1),
        chirp_common.PowerLevel('M', watts=3)]

    _magic = b'PROGROMWLTU'

    def get_features(self):
        rf = RadioddityGA510Radio.get_features(self)
        rf.memory_bounds = (1, 128)
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 520000000)]
        return rf

    def _get_mem(self, num):
        return self._memobj.memories[num - 1]

    def _get_nam(self, number):
        return self._memobj.names[number - 1]

    def _set_mem(self, num):
        return self._memobj.memories[num - 1]

    def _set_nam(self, number):
        return self._memobj.names[number - 1]

    vhftx = [144000000, 146000000]
    uhftx = [430000000, 440000000]


@directory.register
class RetevisRA85Radio(RadioddityGA510Radio):
    VENDOR = 'Retevis'
    MODEL = 'RA85'
    POWER_LEVELS = [
        chirp_common.PowerLevel('H', watts=5),
        chirp_common.PowerLevel('L', watts=0.5),
        chirp_common.PowerLevel('M', watts=0.6)]

    _magic = b'PROGROMWLTU'

    def get_features(self):
        rf = RadioddityGA510Radio.get_features(self)
        rf.memory_bounds = (1, 128)
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 520000000)]
        return rf

    def _get_mem(self, num):
        return self._memobj.memories[num - 1]

    def _get_nam(self, number):
        return self._memobj.names[number - 1]

    def _set_mem(self, num):
        return self._memobj.memories[num - 1]

    def _set_nam(self, number):
        return self._memobj.names[number - 1]


@directory.register
class TDH6Radio(RadioddityGA510Radio):
    VENDOR = "TIDRADIO"
    MODEL = "TD-H6"

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = [(136000000, 174000000),
                          (400000000, 520000000)]
        return rf


@directory.register
class Senhaix8800Radio(RadioddityGA510Radio):
    """Senhaix 8800"""
    VENDOR = "SenhaiX"
    MODEL = "8800"

    POWER_LEVELS = [
        chirp_common.PowerLevel('H', watts=5),
        chirp_common.PowerLevel('L', watts=1)]
    _mem_format = MODEL_SHX8800_FORMAT
    _magic = b'PROGROMSHXU'

    def get_features(self):
        rf = super().get_features()
        rf.valid_bands = rf.valid_bands + [AIRBAND]
        rf.valid_modes = rf.valid_modes + ['AM']
        return rf

    def get_memory(self, number):
        m = super().get_memory(number)
        if chirp_common.in_range(m.freq, [AIRBAND]):
            m.mode = 'AM'
        return m

    def validate_memory(self, mem):
        msgs = []
        if chirp_common.in_range(mem.freq, [AIRBAND]):
            if not mem.mode == 'AM':
                msgs.append(chirp_common.ValidationWarning(
                    _('Frequency in this range requires AM mode')))
            if mem.duplex or mem.tmode:
                msgs.append(chirp_common.ValidationError(
                    _('AM mode does not allow duplex or tone')))
        elif not chirp_common.in_range(
                mem.freq, [AIRBAND]) and mem.mode == 'AM':
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range must not be AM mode')))
        return msgs + super().validate_memory(mem)


@directory.register
class RadioddityGS5BRadio(Senhaix8800Radio):
    """Radioddity GS-5B"""
    VENDOR = "Radioddity"
    MODEL = "GS-5B"


# NOTE: This was added as Signus originally in 18295675
@directory.register
class CignusXTR5Radio(Senhaix8800Radio):
    """Cignus XTR-5"""
    VENDOR = "Cignus"
    MODEL = "XTR-5"


@directory.register
class AnysecuAC580Radio(Senhaix8800Radio):
    """Anysecu AC-580"""
    VENDOR = "Anysecu"
    MODEL = "AC-580"


@directory.register
class AbbreeARF5Radio(RadioddityGA510Radio):
    VENDOR = 'Abbree'
    MODEL = 'AR-F5'
    POWER_LEVELS = [
        chirp_common.PowerLevel('H', watts=5),
        chirp_common.PowerLevel('L', watts=1),
        chirp_common.PowerLevel('M', watts=2)]

    _magic = b'PROGROMWLTU'

    def get_features(self):
        rf = RadioddityGA510Radio.get_features(self)
        rf.memory_bounds = (1, 128)
        rf.valid_bands = [(136000000, 174000000),
                          (200000000, 300000000),
                          (300000000, 400000000),
                          (400000000, 520000000)]
        return rf

    def _get_mem(self, num):
        return self._memobj.memories[num - 1]

    def _get_nam(self, number):
        return self._memobj.names[number - 1]

    def _set_mem(self, num):
        return self._memobj.memories[num - 1]

    def _set_nam(self, number):
        return self._memobj.names[number - 1]


@directory.register
@directory.detected_by(RadioddityGA510Radio)
class RadioddityGA510v2(baofeng_uv17.UV17):
    """Baofeng UV-17"""
    VENDOR = "Radioddity"
    MODEL = "GA-510"
    VARIANT = "V2"

    MODES = ["FM", "NFM"]
    BLOCK_ORDER = [2, 4, 6, 16, 24]
    MEM_TOTAL = 0x6000
    WRITE_MEM_TOTAL = 0x6000
    BLOCK_SIZE = 0x40
    BAUD_RATE = 57600

    _magic = b"PSEARCH"
    _magic_response_length = 8
    _magics = [(b"PASSSTA", 3), (b"SYSINFO", 1),
               (b"\x56\x00\x00\x0A\x0D", 13), (b"\x06", 1),
               (b"\x56\x00\x10\x0A\x0D", 13), (b"\x06", 1),
               (b"\x56\x00\x20\x0A\x0D", 13), (b"\x06", 1),
               (b"\x56\x00\x00\x00\x0A", 11), (b"\x06", 1),
               (b"\xFF\xFF\xFF\xFF\x0C\x44\x4d\x52\x31\x37\x30\x32", 1),
               (b"\02", 8), (b"\x06", 1)]
    _magic_memsize = []
    _radio_memsize = 0x10000
    _magics2 = []
    _fingerprint = b"\x06DMR1702"
    _scode_offset = 1

    _tri_band = False
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("Medium", watts=5.00),
                    chirp_common.PowerLevel("High",  watts=10.00)]

    LENGTH_NAME = 8
    SCODE_LIST = ["%s" % x for x in range(1, 16)]
    SQUELCH_LIST = ["Off"] + list("123456789")
    LIST_POWERON_DISPLAY_TYPE = ["Full", "Message", "Voltage"]
    LIST_TIMEOUT = ["Off"] + ["%s sec" % x for x in range(15, 615, 15)]
    LIST_VOICE = ["Chinese", "English"]
    LIST_BACKLIGHT_TIMER = ["Always On"] + ["%s sec" % x for x in range(1, 11)]
    LIST_MODE = ["Name", "Frequency"]
    CHANNELS = 128

    CHANNEL_DEF = """
      struct channel {
      lbcd rxfreq[4];
      lbcd txfreq[4];
      u8 unused1;
      ul16 rxtone;
      ul16 txtone;
      u8 unknown1:1,
         bcl:1,
         pttid:2,
         unknown2:1,
         wide:1,
         lowpower:2;
      u8 scode:4,
         unknown3:3,
         scan:1;
      u8 unknown4;
    };
    """

    MEM_LAYOUT = """
    #seekto 0x1000;
    struct settings settings;

    #seekto 0x2000;
    struct pttid pttid[15];
    struct ani ani;

    #seekto 0x3040;
    struct {
      struct channel mem[128];
    } mem1;

    #seekto 0x400B;
    struct channelname names1[128];
    """
    MEM_FORMAT = CHANNEL_DEF + baofeng_uv17.UV17.MEM_DEFS + MEM_LAYOUT

    _has_workmode_support = False
