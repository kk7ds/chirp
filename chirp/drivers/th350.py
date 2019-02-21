# Copyright 2019 Zhaofeng Li <hello@zhaofeng.li>
# Copyright 2013 Dan Smith <dsmith@danplanet.com>
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

import struct
import logging
from math import floor
from chirp import chirp_common, directory, bitwise, memmap, errors, util
from uvb5 import BaofengUVB5

LOG = logging.getLogger(__name__)

mem_format = """
struct memory {
  lbcd freq[4];
  lbcd offset[4];
  u8 unknown1:2,
     txpol:1,
     rxpol:1,
     compander:1,
     scrambler:1,
     unknown2:2;
  u8 rxtoneb;
  u8 rxtonea;
  u8 txtoneb;
  u8 txtonea;
  u8 pttid:1,
     scanadd:1,
     isnarrow:1,
     bcl:1,
     highpower:1,
     revfreq:1,
     duplex:2;
  u8 unknown[2];
};

#seekto 0x0000;
char ident[32];
u8 blank[16];
struct memory vfo1;
struct memory channels[128];
#seekto 0x0840;
struct memory vfo3;
struct memory vfo2;

#seekto 0x09D0;
u16 fm_presets[16];

#seekto 0x0A30;
struct {
  u8 name[5];
} names[128];

#seekto 0x0D30;
struct {
  u8 squelch;
  u8 freqmode_ab:1,
     save_funct:1,
     backlight:1,
     beep_tone_disabled:1,
     roger:1,
     tdr:1,
     scantype:2;
  u8 language:1,
     workmode_b:1,
     workmode_a:1,
     workmode_fm:1,
     voice_prompt:1,
     fm:1,
     pttid:2;
  u8 unknown_0:5,
     timeout:3;
  u8 mdf_b:2,
     mdf_a:2,
     unknown_1:2,
     txtdr:2;
  u8 unknown_2:4,
     ste_disabled:1,
     unknown_3:2,
     sidetone:1;
  u8 vox;
  u8 unk1;
  u8 mem_chan_a;
  u16 fm_vfo;
  u8 unk4;
  u8 unk5;
  u8 mem_chan_b;
  u8 unk6;
  u8 last_menu; // number of last menu item accessed
} settings;

#seekto 0x0D50;
struct {
  u8 code[6];
} pttid;

#seekto 0x0F30;
struct {
  lbcd lower_vhf[2];
  lbcd upper_vhf[2];
  lbcd lower_uhf[2];
  lbcd upper_uhf[2];
} limits;

#seekto 0x0FF0;
struct {
  u8 vhfsquelch0;
  u8 vhfsquelch1;
  u8 vhfsquelch2;
  u8 vhfsquelch3;
  u8 vhfsquelch4;
  u8 vhfsquelch5;
  u8 vhfsquelch6;
  u8 vhfsquelch7;
  u8 vhfsquelch8;
  u8 vhfsquelch9;
  u8 unknown1[6];
  u8 uhfsquelch0;
  u8 uhfsquelch1;
  u8 uhfsquelch2;
  u8 uhfsquelch3;
  u8 uhfsquelch4;
  u8 uhfsquelch5;
  u8 uhfsquelch6;
  u8 uhfsquelch7;
  u8 uhfsquelch8;
  u8 uhfsquelch9;
  u8 unknown2[6];
  u8 vhfhipwr0;
  u8 vhfhipwr1;
  u8 vhfhipwr2;
  u8 vhfhipwr3;
  u8 vhfhipwr4;
  u8 vhfhipwr5;
  u8 vhfhipwr6;
  u8 vhfhipwr7;
  u8 vhflopwr0;
  u8 vhflopwr1;
  u8 vhflopwr2;
  u8 vhflopwr3;
  u8 vhflopwr4;
  u8 vhflopwr5;
  u8 vhflopwr6;
  u8 vhflopwr7;
  u8 uhfhipwr0;
  u8 uhfhipwr1;
  u8 uhfhipwr2;
  u8 uhfhipwr3;
  u8 uhfhipwr4;
  u8 uhfhipwr5;
  u8 uhfhipwr6;
  u8 uhfhipwr7;
  u8 uhflopwr0;
  u8 uhflopwr1;
  u8 uhflopwr2;
  u8 uhflopwr3;
  u8 uhflopwr4;
  u8 uhflopwr5;
  u8 uhflopwr6;
  u8 uhflopwr7;
} test;
"""


def do_ident(radio):
    radio.pipe.timeout = 3
    radio.pipe.write("\x05TROGRAM")
    for x in xrange(10):
        ack = radio.pipe.read(1)
        if ack == '\x06':
            break
    else:
        raise errors.RadioError("Radio did not ack programming mode")
    radio.pipe.write("\x02")
    ident = radio.pipe.read(8)
    LOG.debug(util.hexprint(ident))
    if not ident.startswith('HKT511'):
        raise errors.RadioError("Unsupported model")
    radio.pipe.write("\x06")
    ack = radio.pipe.read(1)
    if ack != "\x06":
        raise errors.RadioError("Radio did not ack ident")


def do_status(radio, direction, addr):
    status = chirp_common.Status()
    status.msg = "Cloning %s radio" % direction
    status.cur = addr
    status.max = 0x1000
    radio.status_fn(status)


def do_download(radio):
    do_ident(radio)
    data = "TH350 Radio Program data v1.08\x00\x00"
    data += ("\x00" * 16)
    firstack = None
    for i in range(0, 0x1000, 16):
        frame = struct.pack(">cHB", "R", i, 16)
        radio.pipe.write(frame)
        result = radio.pipe.read(20)
        if frame[1:4] != result[1:4]:
            LOG.debug(util.hexprint(result))
            raise errors.RadioError("Invalid response for address 0x%04x" % i)
        data += result[4:]
        do_status(radio, "from", i)

    return memmap.MemoryMap(data)


def do_upload(radio):
    do_ident(radio)
    data = radio._mmap[0x0030:]

    for i in range(0, 0x1000, 16):
        frame = struct.pack(">cHB", "W", i, 16)
        frame += data[i:i + 16]
        radio.pipe.write(frame)
        ack = radio.pipe.read(1)
        if ack != "\x06":
            # UV-B5/UV-B6 radios with 27 menus do not support service settings
            # and will stop ACKing when the upload reaches 0x0F10
            if i == 0x0F10:
                # must be a radio with 27 menus detected - stop upload
                break
            else:
                LOG.debug("Radio NAK'd block at address 0x%04x" % i)
                raise errors.RadioError(
                    "Radio NAK'd block at address 0x%04x" % i)
        LOG.debug("Radio ACK'd block at address 0x%04x" % i)
        do_status(radio, "to", i)


DUPLEX = ["", "-", "+"]
CHARSET = "0123456789- ABCDEFGHIJKLMNOPQRSTUVWXYZ/_+*"
POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                chirp_common.PowerLevel("High", watts=5)]


@directory.register
class Th350Radio(BaofengUVB5):
    """TYT TH-350"""
    VENDOR = "TYT"
    MODEL = "TH-350"
    BAUD_RATE = 9600
    SPECIALS = {
        "VFO1": -3,
        "VFO2": -2,
        "VFO3": -1,
    }

    _memsize = 0x1000

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ("This TYT TH-350 driver is an alpha version. "
             "Proceed with Caution and backup your data. "
             "Always confirm the correctness of your settings with the "
             "official programmer.")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_duplexes = DUPLEX + ["split"]
        rf.can_odd_split = True
        rf.valid_skips = ["", "S"]
        rf.valid_characters = CHARSET
        rf.valid_name_length = 5
        rf.valid_bands = [(130000000, 175000000),
                          (220000000, 269000000),
                          (400000000, 520000000)]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_special_chans = self.SPECIALS.keys()
        rf.valid_power_levels = POWER_LEVELS
        rf.has_ctone = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.memory_bounds = (1, 128)
        return rf

    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def _decode_tone(self, _mem, which):
        def _get(field):
            return getattr(_mem, "%s%s" % (which, field))

        tonea, toneb = _get('tonea'), _get('toneb')

        if tonea == 0xff:
            mode = val = pol = None
        elif tonea >= 0x80:
            # DTCS
            # D754N -> 0x87 0x54
            # D754I -> 0xc7 0x54
            # Yes. Decimal digits as hex. You're seeing that right.
            # No idea why TYT engineers would do something like that.
            pold = tonea / 16
            if pold not in [0x8, 0xc]:
                LOG.warn("Bug: tone is %04x %04x" % (tonea, toneb))
                mode = val = pol = None
            else:
                mode = 'DTCS'
                val = (tonea % 16) * 100 + \
                    toneb / 16 * 10 + \
                    (toneb % 16)
                pol = 'N' if pold == 8 else 'R'
        else:
            # Tone
            # 107.2 -> 0x10 0x72. Seriously.
            mode = 'Tone'
            val = tonea / 16 * 100 + \
                (tonea % 16) * 10 + \
                toneb / 16 + \
                float(toneb % 16) / 10
            pol = None

        return mode, val, pol

    def _encode_tone(self, _mem, which, mode, val, pol):
        def _set(field, value):
            setattr(_mem, "%s%s" % (which, field), value)

        if mode == "Tone":
            tonea = int(
                        floor(val / 100) * 16 +
                        floor(val / 10) % 10
                    )
            toneb = int(
                        floor(val % 10) * 16 +
                        floor(val * 10) % 10
                    )
        elif mode == "DTCS":
            tonea = (0x80 if pol == 'N' else 0xc0) + \
                val / 100
            toneb = (val / 10) % 10 * 16 + \
                val % 10
        else:
            tonea = toneb = 0xff

        _set('tonea', tonea)
        _set('toneb', toneb)

    def _get_memobjs(self, number):
        if isinstance(number, str):
            return (getattr(self._memobj, number.lower()), None)
        elif number < 0:
            for k, v in self.SPECIALS.items():
                if number == v:
                    return (getattr(self._memobj, k.lower()), None)
        else:
            return (self._memobj.channels[number - 1],
                    self._memobj.names[number - 1].name)

    @classmethod
    def match_model(cls, filedata, filename):
        return (filedata.startswith("TH350 Radio Program data") and
                len(filedata) == (cls._memsize + 0x30))
