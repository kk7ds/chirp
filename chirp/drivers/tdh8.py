# Copyright 2012 Dan Smith <dsmith@danplanet.com>
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
import time
import logging


from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import InvalidValueError, RadioSetting, \
    RadioSettingGroup, RadioSettingValueFloat, \
    RadioSettingValueList, RadioSettingValueBoolean, \
    RadioSettingValueString, RadioSettings
from textwrap import dedent
from chirp import bandplan_na

LOG = logging.getLogger(__name__)


MEM_FORMAT = """
#seekto 0x0008;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  lbcd rxtone[2];
  lbcd txtone[2];
  u8 unused1;
  u8 pttid:2,
     freqhop:1,
     unused3:1,
     unused4:1,
     bcl:1,
     unused5:1,
     unused2:1;
  u8 unused6:1,
     unused7:1,
     lowpower:2,
     wide:1,
     unused8:1,
     offset:2;
  u8 unused10;
} memory[200];

#seekto 0x0D38;
struct {
  char name[8];
  u8 unknown2[8];
} names[200];

#seekto 0x0CA8;
struct {
  u8 txled:1,
     rxled:1,
     unused11:1,
     ham:1,
     gmrs:1,
     unused14:1,
     unused15:1,
     pritx:1;
  u8 scanmode:2,
     unused16:1,
     keyautolock:1,
     unused17:1,
     btnvoice:1,
     unknown18:1,
     voiceprompt:1;
  u8 fmworkmode:1,
     sync:1,
     tonevoice:2,
     fmrec:1,
     mdfa:1,
     aworkmode:2;
  u8 openmes:2,
     unused19:1,
     mdfb:1,
     unused20:1,
     dbrx:1,
     bworkmode:2;
  u8 ablock;
  u8 bblock;
  u8 fmroad;
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
     unused:6,
     alarm:1;
} settings;

#seekto 0x0CB8;
struct {
    u8 ofseta[4];
    u8 ununsed26[12];
} aoffset;

#seekto 0x0CBC;
struct {
    u8 ofsetb[4];
    u8 ununsed27[12];
} boffset;

#seekto 0x0CD8;
struct{
    u8 fmblock[4];
}fmmode[25];

#seekto 0x1A08;
struct{
    u8 block8:1,
       block7:1,
       block6:1,
       block5:1,
       block4:1,
       block3:1,
       block2:1,
       block1:1;
} usedflags[25];

#seekto 0x1a28;
struct{
  u8 scan8:1,
     scan7:1,
     scan6:1,
     scan5:1,
     scan4:1,
     scan3:1,
     scan2:1,
     scan1:1;
} scanadd[25];

#seekto 0x1B38;
struct{
    u8 vfo[4];
}fmvfo;

#seekto 0x1B58;
struct {
  lbcd rxfreqa[4];
  lbcd txfreq[4];
  u8 rxtone[2];
  u8 txtone[2];
  u8 unused1;
  u8 pttid:2,
     specialqta:1,
     unused3:1,
     unused4:1,
     bcl:1,
     unused5:1,
     unused2:1;
  u8 unused6:1,
     unused7:1,
     lowpower:2,
     wide:1,
     unused8:1,
     offset:2;
  u8 unused10;
} vfoa;

#seekto 0x1B68;
struct {
  lbcd rxfreqb[4];
  lbcd txfreq[4];
  u8 rxtoneb[2];
  u8 txtone[2];
  u8 unused1;
  u8 pttid:2,
     specialqtb:1,
     unused3:1,
     unused4:1,
     bclb:1,
     unused5:1,
     unused2:1;
  u8 unused6:1,
     unused7:1,
     lowpowerb:2,
     wideb:1,
     unused8:1,
     offsetb:2;
  u8 unused10;
} vfob;

#seekto 0x1B78;
struct{
   u8  block8:1,
       block7:1,
       block6:1,
       block5:1,
       block4:1,
       block3:1,
       block2:1,
       block1:1;
} fmusedflags[4];

#seekto 0x1CC8;
struct{
  u8 stopkey1;
  u8 ssidekey1;
  u8 ssidekey2;
  u8 ltopkey2;
  u8 lsidekey3;
  u8 lsidekey4;
  u8 unused25[10];
} press;

#seekto 0x1E28;
struct{
    u8 idcode[3];
}icode;

#seekto 0x1E31;
struct{
    u8 gcode;
}groupcode;

#seekto 0x1E38;
struct{
    u8 group1[7];
}group1;

#seekto 0x1E48;
struct{
    u8 group2[7];
}group2;

#seekto 0x1E58;
struct{
    u8 group3[7];
}group3;

#seekto 0x1E68;
struct{
    u8 group4[7];
}group4;

#seekto 0x1E78;
struct{
    u8 group5[7];
}group5;

#seekto 0x1E88;
struct{
    u8 group6[7];
}group6;

#seekto 0x1E98;
struct{
    u8 group7[7];
}group7;

#seekto 0x1EA8;
struct{
    u8 group8[7];
}group8;

#seekto 0x1EC8;
struct{
    u8 scode[7];
}startcode;

#seekto 0x1ED8;
struct{
    u8 ecode[7];
}endcode;

"""

# basic settings
SQUELCH = ['%s' % x for x in range(0, 10)]
LIGHT_LIST = ["CONT", "5s", "10s", "15s", "30s"]
VOICE_PRMPT_LIST = ["OFF", "ON"]
AUTOLOCK_LIST = ["OFF", "ON"]
TIME_OUT_LIST = ["OFF", "60s", "120s", "180s"]
MDFA_LIST = ["Frequency", "Name"]
MDFB_LIST = ["Frequency", "Name"]
SYNC_LIST = ["ON", "OFF"]
LANG_LIST = ["Chinese", "English"]
BTV_SAVER_LIST = ["OFF", "1:1", "1:2", "1:3", "1:4"]
DBRX_LIST = ["OFF", "ON"]
ASTEP_LIST = ["2.50K", "5.00K", "6.25K",
              "10.00K", "12.00K", "25.00K", "50.00K"]
BSTEP_LIST = ["2.50K", "5.00K", "6.25K",
              "10.00K", "12.00K", "25.00K", "50.00K"]
SCAN_MODE_LIST = ["TO", "CO", "SE"]
PRIO_LIST = ["Edit", "Busy"]
SHORT_KEY_LIST = ["None", "FM Radio", "Lamp", "Monitor",
                  "TONE", "Alarm", "Weather"]
LONG_KEY_LIST = ["None", "FM Radio", "Lamp",
                 "Monitor", "TONE", "Alarm", "Weather"]
BUSYLOCK_LIST = ["Off", "On"]
PRESS_NAME = ["stopkey1", "ssidekey1", "ssidekey2",
              "ltopkey2", "lsidekey3", "lsidekey4"]

VFOA_NAME = ["rxfreqa",
             "txfreq",
             "rxtone",
             "txtone",
             "pttid",
             "specialqta",
             "bcl",
             "lowpower",
             "wide",
             "offset"]

VFOB_NAME = ["rxfreqb",
             "txfreq",
             "rxtoneb",
             "txtone",
             "pttid",
             "specialqtb",
             "bclb",
             "lowpowerb",
             "wideb",
             "offsetb"]

# KEY
VOX_GAIN = ["OFF", "1", "2", "3", "4", "5"]
VOX_DELAY = ["1.05s", "2.0s", "3.0s"]
PTTID_VALUES = ["Off", "BOT", "EOT", "BOTH"]
BCLOCK_VALUES = ["Off", "On"]
FREQHOP_VALUES = ["Off", "On"]
SCAN_VALUES = ["Del", "Add"]

# AB CHANNEL
A_OFFSET = ["Off", "-", "+"]
A_TX_POWER = ["Low", "Mid", "High"]
A_BAND = ["Wide", "Narrow"]
A_BUSYLOCK = ["Off", "On"]
A_SPEC_QTDQT = ["Off", "On"]
A_WORKMODE = ["VFO", "VFO+CH", "CH Mode"]

B_OFFSET = ["Off", "-", "+"]
B_TX_POWER = ["Low", "Mid", "High"]
B_BAND = ["Wide", "Narrow"]
B_BUSYLOCK = ["Off", "On"]
B_SPEC_QTDQT = ["Off", "On"]
B_WORKMODE = ["VFO", "VFO+CH", "CH Mode"]

# FM
FM_WORKMODE = ["CH", "VFO"]
FM_CHANNEL = ['%s' % x for x in range(0, 26)]

# DTMF
GROUPCODE = ["", "Off", "*", "#", "A", "B", "C", "D"]

AB_LIST = ["A", "B"]
ALMOD_LIST = ["Site", "Tone", "Code"]
BANDWIDTH_LIST = ["Wide", "Narrow"]
COLOR_LIST = ["Off", "Blue", "Orange", "Purple"]
DTMFSPEED_LIST = ["%s ms" % x for x in range(50, 2010, 10)]
DTMFST_LIST = ["OFF", "DT-ST", "ANI-ST", "DT+ANI"]
MODE_LIST = ["Channel", "Name", "Frequency"]
PONMSG_LIST = ["Full", "Message"]
PTTID_LIST = ["Off", "BOT", "EOT", "Both"]
PTTIDCODE_LIST = ["%s" % x for x in range(1, 16)]
RTONE_LIST = ["1000 Hz", "1450 Hz", "1750 Hz", "2100 Hz"]
RESUME_LIST = ["TO", "CO", "SE"]
ROGERRX_LIST = ["Off"] + AB_LIST
RPSTE_LIST = ["OFF"] + ["%s" % x for x in range(1, 11)]
SAVE_LIST = ["Off", "1:1", "1:2", "1:3", "1:4"]
SCODE_LIST = ["%s" % x for x in range(1, 16)]
SHIFTD_LIST = ["Off", "+", "-"]
STEDELAY_LIST = ["OFF"] + ["%s ms" % x for x in range(100, 1100, 100)]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
STEP_LIST = [str(x) for x in STEPS]
STEPS = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]
STEP291_LIST = [str(x) for x in STEPS]
TDRAB_LIST = ["Off"] + AB_LIST
TDRCH_LIST = ["CH%s" % x for x in range(1, 129)]
TIMEOUT_LIST = ["%s sec" % x for x in range(15, 615, 15)] + \
    ["Off (if supported by radio)"]
TXPOWER_LIST = ["High", "Low"]
TXPOWER3_LIST = ["High", "Mid", "Low"]
VOICE_LIST = ["Off", "English", "Chinese"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 11)]
WORKMODE_LIST = ["Frequency", "Channel"]

GMRS_FREQS = bandplan_na.GMRS_HIRPT

NOAA_FREQS = [162550000, 162400000, 162475000, 162425000, 162450000,
              162500000, 162525000, 161650000, 161775000, 161750000,
              162000000]

HAM_GMRS_NAME = ["NOAA 1", "NOAA 2", "NOAA 3", "NOAA 4", "NOAA 5", "NOAA 6",
                 "NOAA 7", "NOAA 8", "NOAA 9", "NOAA 10", "NOAA 11"]

ALL_MODEL = ["TD-H8", "TD-H8-HAM", "TD-H8-GMRS"]

TD_H8 = b"\x50\x56\x4F\x4A\x48\x1C\x14"


def _do_status(radio, block):
    status = chirp_common.Status()
    status.msg = "Cloning"
    status.cur = block
    status.max = radio._memsize
    radio.status_fn(status)


def _upper_band_from_data(data):
    return data[0x03:0x04]


def _upper_band_from_image(radio):
    return _upper_band_from_data(radio.get_mmap())


def _firmware_version_from_data(data, version_start, version_stop):
    version_tag = data[version_start:version_stop]
    return version_tag


def _firmware_version_from_image(radio):
    version = _firmware_version_from_data(radio.get_mmap(),
                                          radio._fw_ver_file_start,
                                          radio._fw_ver_file_stop)
    # LOG.debug("_firmware_version_from_image: " + util.hexprint(version))
    return version


def _do_ident(radio, magic, secondack=True):
    serial = radio.pipe
    serial.timeout = 1

    LOG.info("Sending Magic: %s" % util.hexprint(magic))
    serial.write(magic)
    ack = serial.read(1)

    if ack != b"\x06":
        if ack:
            # LOG.debug(repr(ack))
            pass
        raise errors.RadioError("Radio did not respond")

    serial.write(b"\x02")

    response = b""
    for i in range(1, 9):
        byte = serial.read(1)
        response += byte
        if byte == b"\xDD":
            break

    if len(response) in [8, 12]:
        # DEBUG
        LOG.info("Valid response, got this:")
        LOG.info(util.hexprint(response))
        if len(response) == 12:
            ident = response[0] + response[3] + response[5] + response[7:]
        else:
            ident = response
    else:
        # bad response
        msg = "Unexpected response, got this:"
        msg += util.hexprint(response)
        LOG.debug(msg)
        raise errors.RadioError("Unexpected response from radio.")

    if secondack:
        serial.write(b"\x06")
        ack = serial.read(1)
        if ack != b"\x06":
            raise errors.RadioError("Radio refused clone")

    return ident


def response_mode(mode):
    data = mode
    return data


def _read_block(radio, start, size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", b'R', start, size)
    expectedresponse = b"W" + cmd[1:]

    try:
        serial.write(cmd)
        response = serial.read(5 + size)
        if response[:4] != expectedresponse:
            raise errors.RadioError("Error reading block %04x." % (start))
        block_data = response[4:-1]

    except Exception:
        raise errors.RadioError("Failed to read block at %04x" % start)

    return block_data


def _get_radio_firmware_version(radio):
    if radio.MODEL in ALL_MODEL:
        block = _read_block(radio, 0x1B40, 0x20)
        version = block[0:6]
    return version


IDENT_BLACKLIST = {
    b"\x50\x56\x4F\x4A\x48\x1C\x14": "Radio identifies as TIDRADIO TD-H8",
}


def _ident_radio(radio):
    for magic in radio._idents:
        error = None
        try:
            data = _do_ident(radio, magic)
            return data
        except errors.RadioError as e:
            error = e
            time.sleep(2)

    if error:
        raise error
    raise errors.RadioError("Radio did not respond")


def _do_download(radio):
    data = _ident_radio(radio)
    append_model = False
    # HAM OR GMRS
    # Determine the walkie-talkie mode
    # TDH8 have three mode:ham, gmrs and normal

    LOG.info("Radio mode is " + str(data)[2:8])
    LOG.info("Chirp choose mode is " + str(data)[2:8])
    # The Ham and GMRS modes are subclasses of this model TDH8.
    # We compare the radio identification to the value of that class to
    # make sure the user chose the model that matches
    # the radio we're talking to right now. If they do not match,
    # we refuse to talk to the radio until the user selects the correct model.

    if radio.ident_mode == data:
        LOG.info("Successful match.")
    else:
        msg = ("Model mismatch!")
        raise errors.RadioError(msg)

    # Main block
    LOG.info("Downloading...")

    for i in range(0, radio._memsize, 0x20):
        block = _read_block(radio, i, 0x20)
        data += block
        _do_status(radio, i)
    _do_status(radio, radio._memsize)
    LOG.info("done.")

    if append_model:
        data += radio.MODEL.ljust(8)

    return memmap.MemoryMapBytes(data)


def _exit_write_block(radio):
    serial = radio.pipe
    try:
        serial.write(b"E")

    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def _write_block(radio, addr, data):
    serial = radio.pipe
    cmd = struct.pack(">cHb", b'W', addr, 0x20)
    data = radio.get_mmap()[addr + 8: addr + 40]
    # The checksum needs to be in the last
    check_sum = bytes([sum(data) & 0xFF])
    data += check_sum
    used_data = cmd + data
    serial.write(used_data)

    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise errors.RadioError("Radio refused to accept block 0x%04x" % addr)


def _do_upload(radio):
    data = _ident_radio(radio)
    radio_version = _get_radio_firmware_version(radio)
    LOG.info("Radio Version is %s" % repr(radio_version))

    if radio.ident_mode == data:
        LOG.info("Successful match.")
    else:
        msg = ("Model mismatch!")
        raise errors.RadioError(msg)

    # Main block
    LOG.debug("Uploading...")

    for start_addr, end_addr in radio._ranges_main:
        for addr in range(start_addr, end_addr, 0x20):
            _write_block(radio, addr, 0x20)
            _do_status(radio, addr)
    _exit_write_block(radio)
    LOG.debug("Upload all done.")


TX_POWER = [chirp_common.PowerLevel("Low",  watts=1.00),
            chirp_common.PowerLevel("Mid",  watts=4.00),
            chirp_common.PowerLevel("High", watts=8.00)]

TDH8_CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + \
    "!@#$%^&*()+-=[]:\";'<>?,./"


@directory.register
class TDH8(chirp_common.CloneModeRadio):
    """TIDRADIO TD-H8"""
    VENDOR = "TIDRADIO"
    MODEL = "TD-H8"
    ident_mode = b'P31183\xff\xff'
    BAUD_RATE = 38400
    NEEDS_COMPAT_SERIAL = False
    _memsize = 0x1eef
    _ranges_main = [(0x0000, 0x1eef)]
    _idents = [TD_H8]
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 521000000)
    _aux_block = True
    _tri_power = True
    _gmrs = False
    _ham = False
    _mem_params = (0x1F2F)

    # offset of fw version in image file
    _fw_ver_file_start = 0x1838
    _fw_ver_file_stop = 0x1846
    _valid_chars = TDH8_CHARSET

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
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
        rf.valid_name_length = 8
        rf.valid_characters = self._valid_chars
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_power_levels = TX_POWER
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tuning_steps = STEPS

        normal_bands = [self._vhf_range, self._uhf_range]

        if self._mmap is None:
            rf.valid_bands = [normal_bands[0], normal_bands[1]]
        else:
            rf.valid_bands = normal_bands
        rf.memory_bounds = (1, 199)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            self._mmap = _do_download(self)
            self.process_mmap()
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def sync_out(self):
        try:
            _do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    # Encoding processing
    def _decode_tone(self, val):
        if val == 16665 or val == 0:
            return '', None, None
        elif val >= 12000:
            return 'DTCS', val - 12000, 'R'
        elif val >= 8000:
            return 'DTCS', val - 8000, 'N'
        else:
            return 'Tone', val / 10.0, None

    # Decoding processing
    def _encode_tone(self, memval, mode, value, pol):
        if mode == "":
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))

        elif mode == 'DTCS':
            flag = 0x80 if pol == 'N' else 0xC0
            memval.set_value(value)
            memval[1].set_bits(flag)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def _get_mem(self, number):
        return self._memobj.memory[number]

    def _get_nam(self, number):
        return self._memobj.names[number]

    def _get_fm(self, number):
        return self._memobj.fmmode[number]

    def _get_get_scanvfo(self, number):
        return self._memobj.fmvfo[number]

    def _get_scan(self, number):
        return self._memobj.scanadd[number]

    def _get_block_data(self, number):
        return self._memobj.usedflags[number]

    def _get_fmblock_data(self, number):
        return self._memobj.fmusedflags[number]

    def get_memory(self, number):
        _mem = self._get_mem(number)
        _nam = self._get_nam(number)
        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw(asbytes=False)[0] == "\xff":
            mem.empty = True
            return mem

        # receiving frequency
        mem.freq = int(_mem.rxfreq) * 10

        # narrow and wide
        mem.mode = _mem.wide and "NFM" or "FM"

        # power
        try:
            mem.power = TX_POWER[_mem.lowpower]
        except IndexError:
            LOG.error("Radio reported invalid power level %s (in %s)" %
                      (_mem.lowpower, TX_POWER))
            mem.power = TX_POWER[0]

        # Channel name
        for char in _nam.name:
            if "\x00" in str(char) or "\xFF" in str(char):
                char = ""
            mem.name += str(char)

        mem.name = mem.name.rstrip()
        if self.ident_mode != b'P31183\xff\xff' and \
                (mem.number >= 189 and mem.number <= 199):
            mem.name = HAM_GMRS_NAME[mem.number - 200]

        # tmode
        lin2 = int(_mem.rxtone)
        rxtone = self._decode_tone(lin2)

        lin = int(_mem.txtone)
        txtone = self._decode_tone(lin)

        if txtone[0] == "Tone" and not rxtone[0]:
            mem.tmode = "Tone"
        elif txtone[0] == rxtone[0] and txtone[0] == "Tone" \
                and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txtone[0] == rxtone[0] and txtone[0] == "DTCS" \
                and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxtone[0] or txtone[0]:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txtone[0], rxtone[0])

        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # skip/scanadd
        scan_val_list = []
        for x in range(25):
            a = self._get_scan(x)
            for i in range(0, 8):
                scan_val = (getattr(a, 'scan%i' % (i+1)))
                # print(str(scan_val)[3])
                used_scan_val = str(scan_val)[3]
                scan_val_list.append(used_scan_val)

        if int(scan_val_list[number - 1]) == 0:
            mem.skip = 'S'
        elif int(scan_val_list[number - 1]) == 1:
            mem.skip = ''

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif int(_mem.txfreq) == 66666665 and int(_mem.rxfreq) != 66666665:
            mem.offset = 0
            mem.duplex = 'off'
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        if self._gmrs:
            # mem.duplex = ""
            # mem.offset = 0
            if mem.number >= 1 and mem.number <= 30:
                mem.immutable.append('freq')
                if mem.number >= 8 and mem.number <= 14:
                    mem.mode = 'NFM'
                    mem.power = TX_POWER[0]
                    mem.immutable = ['freq', 'mode', 'power',
                                     'duplex', 'offset']
            elif mem.number >= 31 and mem.number <= 54:
                # mem.immutable = ['duplex', 'offset']
                mem.duplex = '+'
                mem.offset = 5000000
            elif mem.number >= 189 and mem.number <= 199:
                ham_freqs = NOAA_FREQS[mem.number - 189]
                mem.freq = ham_freqs
                mem.immutable = ['name', 'power', 'duplex', 'freq',
                                 'rx_dtcs', 'vfo', 'tmode', 'empty',
                                 'offset', 'rtone', 'ctone', 'dtcs',
                                 'dtcs_polarity', 'cross_mode']
        elif self._ham:
            if mem.number >= 189 and mem.number <= 199:
                ham_freqs = NOAA_FREQS[mem.number - 189]
                mem.freq = ham_freqs
                mem.immutable = ['name', 'power', 'freq', 'rx_dtcs', 'vfo',
                                 'tmode', 'empty', 'offset', 'rtone', 'ctone',
                                 'dtcs', 'dtcs_polarity', 'cross_mode']

        # other function
        # pttid
        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(PTTID_VALUES,
                                                PTTID_VALUES[_mem.pttid]))
        mem.extra.append(rs)

        # Busylock
        rs = RadioSetting("bcl", "Busy Lock",
                          RadioSettingValueList(BCLOCK_VALUES,
                                                BCLOCK_VALUES[_mem.bcl]))
        mem.extra.append(rs)

        rs = RadioSetting(
            "freqhop", "Frequency Hop", RadioSettingValueList(
                FREQHOP_VALUES, FREQHOP_VALUES[_mem.freqhop]))
        mem.extra.append(rs)

        return mem

    def _set_mem(self, number):
        return self._memobj.memory[number]

    def _set_nam(self, number):
        return self._memobj.names[number]

    def _get_scan_list(self, scan_data):
        # scan_val_list - Get all scans Add data 1-200 digits
        scan_val_list = []
        for x in range(25):
            a = self._get_scan(x)
            for i in range(0, 8):
                scan_val = (getattr(a, 'scan%i' % (i+1)))
                used_scan_val = str(scan_val)[3]
                scan_val_list.append(used_scan_val)

        # used_scan_list - 25 structures, split the scan added
        # data into 25 groups of 8 bits each
        used_scan_list = []
        count_num = 1
        for i in range(0, len(scan_val_list), 8):
            used_scan_list.append(scan_val_list[i:i + 8])
            count_num += 1
        # Determine whether it is a standard number that can be divisible
        # Which group is the scan addition located in the modified channel
        if scan_data % 8 != 0:
            x_list = scan_data / 8
            y_list = scan_data % 8

        else:
            x_list = (scan_data / 8) - 1
            y_list = 8

        return ([x_list, y_list])

    def get_block_xy(self, number):
        if number % 8 != 0:
            x_list = number / 8
            y_list = number % 8

        else:
            x_list = (number / 8) - 1
            y_list = 8

        return ([x_list, y_list])

    def set_memory(self, mem):
        _mem = self._get_mem(mem.number)
        _nam = self._get_nam(mem.number)

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

        _mem.set_raw("\x00" * 16)

        # When the channel is empty, you need to set "usedflags" to 0,
        # which means it is empty.When the channel has a value,
        # you need to set "usedflags" to 0,
        # indicating that it contains a value.
        # The method "get_block_xy" is due to
        # the particularity of the structure,
        # x represents a certain structure group,
        # and y represents a certain byte of the structure group.
        if not mem.empty:
            block_xy = self.get_block_xy(mem.number)
            _usedflags = self._get_block_data(block_xy[0])
            if block_xy[1] == 1:
                _usedflags.block1 = 1
            elif block_xy[1] == 2:
                _usedflags.block2 = 1
            elif block_xy[1] == 3:
                _usedflags.block3 = 1
            elif block_xy[1] == 4:
                _usedflags.block4 = 1
            elif block_xy[1] == 5:
                _usedflags.block5 = 1
            elif block_xy[1] == 6:
                _usedflags.block6 = 1
            elif block_xy[1] == 7:
                _usedflags.block7 = 1
            elif block_xy[1] == 8:
                _usedflags.block8 = 1
        else:
            block_xy = self.get_block_xy(mem.number)
            _usedflags = self._get_block_data(block_xy[0])
            if block_xy[1] == 1:
                _usedflags.block1 = 0
            elif block_xy[1] == 2:
                _usedflags.block2 = 0
            elif block_xy[1] == 3:
                _usedflags.block3 = 0
            elif block_xy[1] == 4:
                _usedflags.block4 = 0
            elif block_xy[1] == 5:
                _usedflags.block5 = 0
            elif block_xy[1] == 6:
                _usedflags.block6 = 0
            elif block_xy[1] == 7:
                _usedflags.block7 = 0
            elif block_xy[1] == 8:
                _usedflags.block8 = 0

        if mem.duplex == "":
            _mem.rxfreq = _mem.txfreq = mem.freq / 10
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == 'off':
            _mem.txfreq = 166666665
        else:
            _mem.txfreq = mem.freq / 10

        _mem.rxfreq = mem.freq / 10
        _namelength = self.get_features().valid_name_length

        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        txtone, rxtone = chirp_common.split_tone_encode(mem)

        self._encode_tone(_mem.txtone, *txtone)
        self._encode_tone(_mem.rxtone, *rxtone)

        if mem.mode == "FM":
            _mem.wide = 0
        else:
            _mem.wide = 1

        if str(mem.power) == "Low":
            _mem.lowpower = 0
        elif str(mem.power) == "Mid":
            _mem.lowpower = 1
        elif str(mem.power) == "High":
            _mem.lowpower = 10
        else:
            _mem.lowpower = 0

        # Skip/Scanadd Setting
        scanlist = self._get_scan_list(mem.number)
        _scan = self._get_scan(scanlist[0])

        if scanlist[1] == 1:
            _scan.scan1 = mem.skip != "S"
        elif scanlist[1] == 2:
            _scan.scan2 = mem.skip != "S"
        elif scanlist[1] == 3:
            _scan.scan3 = mem.skip != "S"
        elif scanlist[1] == 4:
            _scan.scan4 = mem.skip != "S"
        elif scanlist[1] == 5:
            _scan.scan5 = mem.skip != "S"
        elif scanlist[1] == 6:
            _scan.scan6 = mem.skip != "S"
        elif scanlist[1] == 7:
            _scan.scan7 = mem.skip != "S"
        elif scanlist[1] == 8:
            _scan.scan8 = mem.skip != "S"

        for setting in mem.extra:
            if (self.ident_mode == b'P31185\xff\xff' or
                self.ident_mode == b'P31184\xff\xff') and \
                    mem.number >= 189 and mem.number <= 199:
                if setting.get_name() == 'pttid':
                    setting.value = 'Off'
                    setattr(_mem, setting.get_name(), setting.value)
                elif setting.get_name() == 'bcl':
                    setting.value = 'Off'
                    setattr(_mem, setting.get_name(), setting.value)
                elif setting.get_name() == 'freqhop':
                    setting.value = 'Off'
                    setattr(_mem, setting.get_name(), setting.value)
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def _is_orig(self):
        version_tag = _firmware_version_from_image(self)
        try:
            if b'BFB' in version_tag:
                idx = version_tag.index(b"BFB") + 3
                version = int(version_tag[idx:idx + 3])
                return version < 291
            return False
        except Exception:
            pass
        raise errors.RadioError("Unable to parse version string %s" %
                                version_tag)

    def _my_upper_band(self):
        band_tag = _upper_band_from_image(self)
        return band_tag

    def _get_settings(self):
        _settings = self._memobj.settings
        _press = self._memobj.press
        _aoffset = self._memobj.aoffset
        _boffset = self._memobj.boffset
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _gcode = self._memobj.groupcode

        basic = RadioSettingGroup("basic", "Basic Settings")
        abblock = RadioSettingGroup("abblock", "A/B Channel")
        fmmode = RadioSettingGroup("fmmode", "FM")
        dtmf = RadioSettingGroup("dtmf", "DTMF")

        # group = RadioSettings(fmmode, dtmf)
        group = RadioSettings(basic, abblock, fmmode, dtmf)

        rs = RadioSetting("squelch", "Squelch Level",
                          RadioSettingValueList(
                              SQUELCH, SQUELCH[_settings.squelch]))
        basic.append(rs)

        rs = RadioSetting("ligcon", "Light Control",
                          RadioSettingValueList(
                              LIGHT_LIST, LIGHT_LIST[_settings.ligcon]))
        basic.append(rs)

        rs = RadioSetting("voiceprompt", "Voice Prompt",
                          RadioSettingValueList(
                              VOICE_PRMPT_LIST, VOICE_PRMPT_LIST[
                                  _settings.voiceprompt]))
        basic.append(rs)

        rs = RadioSetting("keyautolock", "Auto Lock",
                          RadioSettingValueList(
                              AUTOLOCK_LIST, AUTOLOCK_LIST[
                                  _settings.keyautolock]))
        basic.append(rs)

        rs = RadioSetting("mdfa", "MDF-A",
                          RadioSettingValueList(
                              MDFA_LIST, MDFA_LIST[_settings.mdfa]))
        basic.append(rs)

        rs = RadioSetting("mdfb", "MDF-B",
                          RadioSettingValueList(
                              MDFB_LIST, MDFB_LIST[_settings.mdfb]))
        basic.append(rs)

        rs = RadioSetting("sync", "SYNC",
                          RadioSettingValueList(
                              SYNC_LIST, SYNC_LIST[_settings.sync]))
        basic.append(rs)

        if _settings.lang in (2, 3):
            langs = 1
        else:
            langs = 0
        rs = RadioSetting("lang", "Language",
                          RadioSettingValueList(
                              LANG_LIST, LANG_LIST[langs]))
        basic.append(rs)

        rs = RadioSetting("save", "Battery Save",
                          RadioSettingValueList(
                              BTV_SAVER_LIST, BTV_SAVER_LIST[_settings.save]))
        basic.append(rs)

        rs = RadioSetting("dbrx", "Double Rx",
                          RadioSettingValueList(
                              DBRX_LIST, DBRX_LIST[_settings.dbrx]))
        basic.append(rs)

        rs = RadioSetting("astep", "A Step",
                          RadioSettingValueList(
                              ASTEP_LIST, ASTEP_LIST[_settings.astep]))
        basic.append(rs)

        rs = RadioSetting("bstep", "B Step",
                          RadioSettingValueList(
                              BSTEP_LIST, BSTEP_LIST[_settings.bstep]))
        basic.append(rs)

        rs = RadioSetting("scanmode", "Scan Mode",
                          RadioSettingValueList(
                              SCAN_MODE_LIST, SCAN_MODE_LIST[
                                  _settings.scanmode]))
        basic.append(rs)

        rs = RadioSetting("pritx", "Priority TX",
                          RadioSettingValueList(
                              PRIO_LIST, PRIO_LIST[_settings.pritx]))
        basic.append(rs)

        rs = RadioSetting("btnvoice", "Beep",
                          RadioSettingValueBoolean(_settings.btnvoice))
        basic.append(rs)

        rs = RadioSetting("rogerprompt", "Roger",
                          RadioSettingValueBoolean(_settings.rogerprompt))
        basic.append(rs)

        rs = RadioSetting("txled", "Disp Lcd(TX)",

                          RadioSettingValueBoolean(_settings.txled))
        basic.append(rs)

        rs = RadioSetting("rxled", "Disp Lcd(RX)",
                          RadioSettingValueBoolean(_settings.rxled))
        basic.append(rs)

        rs = RadioSetting("onlychmode", "Only CH Mode",
                          RadioSettingValueBoolean(_settings.onlychmode))
        basic.append(rs)

        rs = RadioSetting("stopkey1", "SHORT_KEY_TOP",
                          RadioSettingValueList(
                              SHORT_KEY_LIST, SHORT_KEY_LIST[0]))
        basic.append(rs)

        rs = RadioSetting("ssidekey1", "SHORT_KEY_PF1",
                          RadioSettingValueList(
                              SHORT_KEY_LIST, SHORT_KEY_LIST[
                                  _press.ssidekey1]))
        basic.append(rs)

        rs = RadioSetting("ssidekey2", "SHORT_KEY_PF2",
                          RadioSettingValueList(
                              SHORT_KEY_LIST, SHORT_KEY_LIST[
                                  _press.ssidekey2]))
        basic.append(rs)

        rs = RadioSetting("ltopkey2", "LONG_KEY_TOP",
                          RadioSettingValueList(
                              LONG_KEY_LIST, LONG_KEY_LIST[_press.ltopkey2]))
        basic.append(rs)

        rs = RadioSetting("lsidekey3", "LONG_KEY_PF1",
                          RadioSettingValueList(
                              LONG_KEY_LIST, LONG_KEY_LIST[_press.lsidekey3]))
        basic.append(rs)

        rs = RadioSetting("lsidekey4", "LONG_KEY_PF2",
                          RadioSettingValueList(
                              LONG_KEY_LIST, LONG_KEY_LIST[_press.lsidekey4]))
        basic.append(rs)

        rs = RadioSetting("voxgain", "VOX Gain",
                          RadioSettingValueList(
                              VOX_GAIN, VOX_GAIN[_settings.voxgain]))
        basic.append(rs)

        rs = RadioSetting("voxdelay", "VOX Delay",
                          RadioSettingValueList(
                              VOX_DELAY, VOX_DELAY[_settings.voxdelay]))
        basic.append(rs)

        # A channel
        a_freq = int(_vfoa.rxfreqa)
        freqa = "%i.%05i" % (a_freq / 100000, a_freq % 100000)
        if freqa == "0.00000":
            val1a = RadioSettingValueString(0, 7, '0.00000')
        else:
            val1a = RadioSettingValueFloat(
                136, 520, float(freqa), 0.00001, 5)
        rs = RadioSetting("rxfreqa", "A Channel - Frequency", val1a)
        abblock.append(rs)

        # Offset
        # If the offset is 12.345
        # Then the data obtained is [0x45, 0x23, 0x01, 0x00]
        a_set_val = _aoffset.ofseta
        a_set_list = len(_aoffset.ofseta) - 1
        real_val = ''
        for i in range(a_set_list, -1, -1):
            real_val += str(a_set_val[i])[2:]
        if real_val == "FFFFFFFF":
            rs = RadioSetting("ofseta", "A Offset Frequency",
                              RadioSettingValueString(0, 7, ""))

        else:
            real_val = int(real_val)
            real_val = "%i.%05i" % (real_val / 100000, real_val % 100000)
            rs = RadioSetting("ofseta", "A Offset Frequency",
                              RadioSettingValueFloat(
                                  0.00000, 59.99750, real_val, 0.00001, 5))
        abblock.append(rs)

        rs = RadioSetting("offset", "A Offset",
                          RadioSettingValueList(
                              A_OFFSET, A_OFFSET[_vfoa.offset]))
        abblock.append(rs)

        rs = RadioSetting("lowpower", "A TX Power",
                          RadioSettingValueList(
                              A_TX_POWER, A_TX_POWER[_vfoa.lowpower]))
        abblock.append(rs)

        rs = RadioSetting("wide", "A Band",
                          RadioSettingValueList(
                              A_BAND, A_BAND[_vfoa.wide]))
        abblock.append(rs)

        rs = RadioSetting("bcl", "A Busy Lock",
                          RadioSettingValueList(
                              A_BUSYLOCK, A_BUSYLOCK[_vfoa.bcl]))
        abblock.append(rs)

        rs = RadioSetting("specialqta", "A Special QT/DQT",
                          RadioSettingValueList(
                              A_SPEC_QTDQT, A_SPEC_QTDQT[_vfoa.specialqta]))
        abblock.append(rs)

        rs = RadioSetting("aworkmode", "A Work Mode",
                          RadioSettingValueList(
                              A_WORKMODE, A_WORKMODE[_settings.aworkmode]))
        abblock.append(rs)

        # B channel
        b_freq = int(str(int(_vfob.rxfreqb)).ljust(8, '0'))
        freqb = "%i.%05i" % (b_freq / 100000, b_freq % 100000)
        if freqb == "0.00000":
            val1a = RadioSettingValueString(0, 7, '0.00000')
        else:
            val1a = RadioSettingValueFloat(
                136, 520, float(freqb), 0.00001, 5)
        rs = RadioSetting("rxfreqb", "B Channel - Frequency", val1a)
        abblock.append(rs)

        # Offset frequency
        # If the offset is 12.345
        # Then the data obtained is [0x45, 0x23, 0x01, 0x00]
        # Need to use the following anonymous function to process data
        b_set_val = _boffset.ofsetb
        b_set_list = len(_boffset.ofsetb) - 1
        real_val = ''
        for i in range(b_set_list, -1, -1):
            real_val += str(b_set_val[i])[2:]
        if real_val == "FFFFFFFF":
            rs = RadioSetting("ofsetb", "B Offset Frequency",
                              RadioSettingValueString(0, 7, " "))
        else:
            real_val = int(real_val)
            real_val = "%i.%05i" % (real_val / 100000, real_val % 100000)
            rs = RadioSetting("ofsetb", "B Offset Frequency",
                              RadioSettingValueFloat(
                                  0.00000, 59.99750, real_val, 0.00001, 5))
        abblock.append(rs)

        rs = RadioSetting("offsetb", "B Offset",
                          RadioSettingValueList(
                              B_OFFSET, B_OFFSET[_vfob.offsetb]))
        abblock.append(rs)

        rs = RadioSetting("lowpowerb", "B TX Power",
                          RadioSettingValueList(
                              B_TX_POWER, B_TX_POWER[_vfob.lowpowerb]))
        abblock.append(rs)

        rs = RadioSetting("wideb", "B Band",
                          RadioSettingValueList(
                              B_BAND, B_BAND[_vfob.wideb]))
        abblock.append(rs)

        rs = RadioSetting("bclb", "B Busy Lock",
                          RadioSettingValueList(
                              B_BUSYLOCK, B_BUSYLOCK[_vfob.bclb]))
        abblock.append(rs)

        rs = RadioSetting("specialqtb", "B Special QT/DQT",
                          RadioSettingValueList(
                              B_SPEC_QTDQT, B_SPEC_QTDQT[_vfob.specialqtb]))
        abblock.append(rs)

        rs = RadioSetting("bworkmode", "B Work Mode",
                          RadioSettingValueList(
                              B_WORKMODE, B_WORKMODE[_settings.bworkmode]))
        abblock.append(rs)

        rs = RadioSetting("fmworkmode", "Work Mode",
                          RadioSettingValueList(
                              FM_WORKMODE, FM_WORKMODE[_settings.fmworkmode]))
        fmmode.append(rs)

        rs = RadioSetting("fmroad", "Channel",
                          RadioSettingValueList(
                              FM_CHANNEL, FM_CHANNEL[_settings.fmroad]))
        fmmode.append(rs)

        rs = RadioSetting("fmrec", "Forbid Receive",
                          RadioSettingValueBoolean(_settings.fmrec))
        fmmode.append(rs)

        # FM
        for i in range(25):
            _fm = self._get_fm(i).fmblock
            _fm_len = len(_fm) - 1
            _fm_temp = ''
            for x in range(_fm_len, -1, -1):
                _fm_temp += str(_fm[x])[2:]
            if _fm_temp == "00000000" or _fm_temp == 'FFFFFFFF':
                rs = RadioSetting('block' + str(i), "Channel" + " " + str(i+1),
                                  RadioSettingValueString(0, 5, ""))
            else:
                _fm_block = int(_fm_temp)
                _fm_block = '%i.%i' % (_fm_block / 10, _fm_block % 10)
                rs = RadioSetting('block' + str(i), "Channel" + " " + str(i+1),
                                  RadioSettingValueString(0, 5, _fm_block))
            fmmode.append(rs)

        _fmv = self._memobj.fmvfo.vfo
        _fmv_len = len(_fmv) - 1
        _fmv_temp = ''
        for x in range(_fmv_len, -1, -1):
            _fmv_temp += str(_fmv[x])[2:]
        _fmv_block = int(_fmv_temp)
        _fmv_block = '%i.%i' % (_fmv_block / 10, _fmv_block % 10)
        rs = RadioSetting(
            "fmvfo", "VFO", RadioSettingValueFloat(
                76.0, 108.0, _fmv_block, 0.1, 1))
        fmmode.append(rs)

        # DTMF
        gcode_val = str(_gcode.gcode)[2:]
        if gcode_val == "FF":
            gcode_val = "Off"
        elif gcode_val == "0F":
            gcode_val = "#"
        elif gcode_val == "0E":
            gcode_val = "*"
        elif gcode_val == '00':
            gcode_val = ""
        else:
            gcode_val = gcode_val[1]
        rs = RadioSetting("gcode", "Group Code",
                          RadioSettingValueList(GROUPCODE,
                                                gcode_val))
        dtmf.append(rs)

        icode_list = self._memobj.icode.idcode
        used_icode = ''
        for i in icode_list:
            if i == 0xFF:
                continue
            used_icode += str(i)[3]
        dtmfcharsani = "0123456789ABCD "
        i_val = RadioSettingValueString(0, 3, used_icode)
        rs = RadioSetting("icode", "ID Code", i_val)
        i_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_1 = self._memobj.group1.group1
        used_group1 = ''
        for i in gcode_list_1:
            if i == 0xFF:
                continue
            used_group1 += str(i)[3]
        group1_val = RadioSettingValueString(0, 7, used_group1)
        rs = RadioSetting("group1", "1", group1_val)
        group1_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_2 = self._memobj.group2.group2
        used_group2 = ''
        for i in gcode_list_2:
            if i == 0xFF:
                continue
            used_group2 += str(i)[3]
        group2_val = RadioSettingValueString(0, 7, used_group2)
        rs = RadioSetting("group2", "2", group2_val)
        group2_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_3 = self._memobj.group3.group3
        used_group3 = ''
        for i in gcode_list_3:
            if i == 0xFF:
                continue
            used_group3 += str(i)[3]
        group3_val = RadioSettingValueString(0, 7, used_group3)
        rs = RadioSetting("group3", "3", group3_val)
        group3_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_4 = self._memobj.group4.group4
        used_group4 = ''
        for i in gcode_list_4:
            if i == 0xFF:
                continue
            used_group4 += str(i)[3]
        group4_val = RadioSettingValueString(0, 7, used_group4)
        rs = RadioSetting("group4", "4", group4_val)
        group4_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_5 = self._memobj.group5.group5
        used_group5 = ''
        for i in gcode_list_5:
            if i == 0xFF:
                continue
            used_group5 += str(i)[3]
        group5_val = RadioSettingValueString(0, 7, used_group5)
        rs = RadioSetting("group5", "5", group5_val)
        group5_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_6 = self._memobj.group6.group6
        used_group6 = ''
        for i in gcode_list_6:
            if i == 0xFF:
                continue
            used_group6 += str(i)[3]
        group6_val = RadioSettingValueString(0, 7, used_group6)
        rs = RadioSetting("group6", "6", group6_val)
        group6_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_7 = self._memobj.group7.group7
        used_group7 = ''
        for i in gcode_list_7:
            if i == 0xFF:
                continue
            used_group7 += str(i)[3]
        group7_val = RadioSettingValueString(0, 7, used_group7)
        rs = RadioSetting("group7", "7", group7_val)
        group7_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        gcode_list_8 = self._memobj.group8.group8
        used_group8 = ''
        for i in gcode_list_8:
            if i == 0xFF:
                continue
            used_group8 += str(i)[3]
        group8_val = RadioSettingValueString(0, 7, used_group8)
        rs = RadioSetting("group8", "8", group7_val)
        group8_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        scode_list = self._memobj.startcode.scode
        used_scode = ''
        for i in scode_list:
            if i == 0xFF:
                continue
            used_scode += str(i)[3]
        scode_val = RadioSettingValueString(0, 7, used_scode)
        rs = RadioSetting("scode", "PTT ID Starting(BOT)", scode_val)
        scode_val.set_charset(dtmfcharsani)
        dtmf.append(rs)

        ecode_list = self._memobj.endcode.ecode
        used_ecode = ''
        for i in ecode_list:
            if i == 0xFF:
                continue
            used_ecode += str(i)[3]
        ecode_val = RadioSettingValueString(0, 7, used_ecode)
        rs = RadioSetting("ecode", "PTT ID Ending(BOT)", ecode_val)
        dtmf.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except Exception:
            raise InvalidValueError("Setting Failed!")

    def set_settings(self, settings):

        def fm_validate(value):
            if 760 > value or value > 1080:
                msg = ("FM Channel muse be between 76.0-108.0")
                raise InvalidValueError(msg)

        _settings = self._memobj.settings
        _press = self._memobj.press
        _aoffset = self._memobj.aoffset
        _boffset = self._memobj.boffset
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _fmmode = self._memobj.fmmode
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() == "fm_preset":
                    self._set_fm_preset(element)
                else:
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
                    elif name in PRESS_NAME:
                        obj = _press
                        setting = element.get_name()

                    elif name in VFOA_NAME:
                        obj = _vfoa
                        setting = element.get_name()
                    elif name == "ofseta":
                        obj = _aoffset
                        setting = element.get_name()
                    elif name in VFOB_NAME:
                        obj = _vfob
                        setting = element.get_name()
                    elif name == "ofsetb":
                        obj = _boffset
                        setting = element.get_name()
                    elif "block" in name:
                        obj = _fmmode
                        setting = element.get_name()
                    elif "fmvfo" in name:
                        obj = self._memobj.fmvfo.vfo
                        setting = element.get_name()
                    elif "gcode" in name:
                        obj = self._memobj.groupcode.gcode
                        setting = element.get_name()
                    elif "idcode" in name:
                        obj = self._memobj.icode.idcode
                        setting = element.get_name()
                    elif "scode" in name:
                        obj = self._memobj.startcode.scode
                        setting = element.get_name()
                    elif "ecode" in name:
                        obj = self._memobj.endcode.ecode
                        setting = element.get_name()
                    elif "group1" in name:
                        obj = self._memobj.group1.group1
                        setting = element.get_name()
                    elif "group2" in name:
                        obj = self._memobj.group2.group2
                        setting = element.get_name()
                    elif "group3" in name:
                        obj = self._memobj.group3.group3
                        setting = element.get_name()
                    elif "group4" in name:
                        obj = self._memobj.group4.group4
                        setting = element.get_name()
                    elif "group5" in name:
                        obj = self._memobj.group5.group5
                        setting = element.get_name()
                    elif "group6" in name:
                        obj = self._memobj.group6.group6
                        setting = element.get_name()
                    elif "group7" in name:
                        obj = self._memobj.group7.group7
                        setting = element.get_name()
                    elif "group8" in name:
                        obj = self._memobj.group8.group8
                        setting = element.get_name()

                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()

                    # Channel A
                    elif setting == "rxfreqa" and element.value.get_mutable():
                        val = int(str(element.value).replace(
                            '.', '').ljust(8, '0'))
                        if (val >= 13600000 and val <= 17400000) or \
                                (val >= 40000000 and val <= 52000000):
                            setattr(obj, setting, val)
                        else:
                            msg = (
                                "Frequency must be between "
                                "136.00000-174.00000 or 400.00000-520.00000")
                            raise InvalidValueError(msg)

                    elif setting == "ofseta" and element.value.get_mutable():
                        if '.' in str(element.value):
                            val = str(element.value).replace(' ', '')
                            if len(
                                val[val.index(".") + 1:]
                                ) >= 1 and int(val[val.index(".") + 1:]
                                               ) != 0:
                                val = '00' + val.replace('.', '')
                            else:
                                val = '0' + val.replace('.', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        else:
                            val = '0' + str(element.value).replace(' ', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        if (int(val) >= 0 and int(val) <= 5999750):
                            if int(val) == 0:
                                _aoffset.ofseta = [0xFF, 0xFF, 0xFF, 0xFF]
                            else:
                                while lenth_val < (len(val)):
                                    list_val.insert(
                                        0, val[lenth_val:lenth_val + 2])
                                    lenth_val += 2
                                for i in range(len(list_val)):
                                    list_val[i] = int(list_val[i], 16)
                                _aoffset.ofseta = list_val
                        else:
                            msg = ("Offset must be between 0.00000-59.99750")
                            raise InvalidValueError(msg)

                    # B channel
                    elif setting == "rxfreqb" and element.value.get_mutable():
                        val = 0
                        val = int(str(element.value).replace(
                            '.', '').ljust(8, '0'))
                        if (val >= 13600000 and val <= 17400000) or \
                                (val >= 40000000 and val <= 52000000):
                            setattr(obj, setting, val)
                        else:
                            msg = (
                                "Frequency must be between "
                                "136.00000-174.00000 or 400.00000-520.00000")
                            raise InvalidValueError(msg)
                        # setattr(obj, setting, val)

                    elif setting == "ofsetb" and element.value.get_mutable():
                        if '.' in str(element.value):
                            val = str(element.value).replace(' ', '')
                            if len(val[val.index(".") + 1:]
                                   ) >= 1 and int(val[val.index(".") + 1:]
                                                  ) != 0:
                                val = '00' + \
                                    str(element.value).replace('.', '')
                            else:
                                val = '0' + str(element.value).replace('.', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        else:
                            val = '0' + str(element.value).replace(' ', '')
                            val = val.ljust(8, '0')
                            lenth_val = 0
                            list_val = []
                        if (int(val) >= 0 and int(val) <= 5999750):
                            if int(val) == 0:
                                _boffset.ofsetb = [0xFF, 0xFF, 0xFF, 0xFF]
                            else:
                                while lenth_val < (len(val)):
                                    list_val.insert(
                                        0, val[lenth_val:lenth_val + 2])
                                    lenth_val += 2
                                for i in range(len(list_val)):
                                    list_val[i] = int(list_val[i], 16)
                                _boffset.ofsetb = list_val
                        else:
                            msg = ("Offset must be between 0.00000-59.99750")
                            raise InvalidValueError(msg)

                    # FM
                    elif "block" in name:

                        val = str(element.value).replace('.', '').zfill(8)
                        num = int(element.get_name().replace('block', '')) + 1
                        lenth_val = 0
                        list_val = []
                        if str(element.value)[0] == ' ':
                            list_val = [0, 0, 0, 0]
                        else:
                            val = val.replace(' ', '').zfill(8)
                            fm_validate(int(val))
                            while lenth_val < (len(val)):
                                list_val.insert(
                                    0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        self._memobj.fmmode[num - 1].fmblock = list_val

                        if val != '00000   ':
                            fmblock_xy = self.get_block_xy(num)
                            _fmusedflags = self._get_fmblock_data(
                                fmblock_xy[0])
                            if fmblock_xy[1] == 1:
                                _fmusedflags.block1 = 1
                            elif fmblock_xy[1] == 2:
                                _fmusedflags.block2 = 1
                            elif fmblock_xy[1] == 3:
                                _fmusedflags.block3 = 1
                            elif fmblock_xy[1] == 4:
                                _fmusedflags.block4 = 1
                            elif fmblock_xy[1] == 5:
                                _fmusedflags.block5 = 1
                            elif fmblock_xy[1] == 6:
                                _fmusedflags.block6 = 1
                            elif fmblock_xy[1] == 7:
                                _fmusedflags.block7 = 1
                            elif fmblock_xy[1] == 8:
                                _fmusedflags.block8 = 1
                        else:
                            fmblock_xy = self.get_block_xy(num)
                            _fmusedflags = self._get_fmblock_data(
                                fmblock_xy[0])
                            if fmblock_xy[1] == 1:
                                _fmusedflags.block1 = 0
                            elif fmblock_xy[1] == 2:
                                _fmusedflags.block2 = 0
                            elif fmblock_xy[1] == 3:
                                _fmusedflags.block3 = 0
                            elif fmblock_xy[1] == 4:
                                _fmusedflags.block4 = 0
                            elif fmblock_xy[1] == 5:
                                _fmusedflags.block5 = 0
                            elif fmblock_xy[1] == 6:
                                _fmusedflags.block6 = 0
                            elif fmblock_xy[1] == 7:
                                _fmusedflags.block7 = 0
                            elif fmblock_xy[1] == 8:
                                _fmusedflags.block8 = 0

                    elif setting == 'fmvfo' and element.value.get_mutable():
                        val = str(element.value).replace('.', '').zfill(8)
                        lenth_val = 0
                        list_val = []
                        if " " in val:
                            list_val = [0, 0, 0, 0]
                        else:
                            while lenth_val < (len(val)):
                                list_val.insert(
                                    0, int(val[lenth_val:lenth_val + 2], 16))
                                lenth_val += 2
                        self._memobj.fmvfo.vfo = list_val

                    elif setting == 'gcode' and element.value.get_mutable():
                        val = str(element.value)
                        if val == 'Off':
                            gcode_used = 0xFF
                        elif val == 'A':
                            gcode_used = 0x0A
                        elif val == 'B':
                            gcode_used = 0x0B
                        elif val == 'C':
                            gcode_used = 0x0C
                        elif val == 'D':
                            gcode_used = 0x0D
                        elif val == '#':
                            gcode_used = 0x0F
                        elif val == '*':
                            gcode_used = 0x0E
                        elif val == '':
                            gcode_used = 0x00
                        self._memobj.groupcode.gcode = gcode_used

                    elif setting == 'icode' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.icode.idcode = list_val

                    elif setting == 'scode' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.startcode.scode = list_val

                    elif setting == 'ecode' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.endcode.ecode = list_val

                    elif setting == 'group1' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group1.group1 = list_val

                    elif setting == 'group2' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group2.group2 = list_val

                    elif setting == 'group3' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group3.group3 = list_val

                    elif setting == 'group4' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group4.group4 = list_val

                    elif setting == 'group5' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group5.group5 = list_val

                    elif setting == 'group6' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group6.group6 = list_val

                    elif setting == 'group7' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group7.group7 = list_val

                    elif setting == 'group8' and element.value.get_mutable():
                        val = str(element.value)
                        list_val = []
                        lenth_val = 0
                        while lenth_val < (len(val)):
                            if val[lenth_val] != ' ':
                                list_val.append(int(val[lenth_val], 16))
                                lenth_val += 1
                            else:
                                list_val.append(0xFF)
                                lenth_val += 1
                        self._memobj.group8.group8 = list_val
                    elif setting == 'lang':
                        self._memobj.settings.lang = (
                                str(element.value) == 'English' and 2 or 1)
                    elif element.value.get_mutable():
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _set_fm_preset(self, settings):
        for element in settings:
            try:
                val = element.value
                if self._memobj.fm_presets <= 108.0 * 10 - 650:
                    value = int(val.get_value() * 10 - 650)
                else:
                    value = int(val.get_value() * 10)
                LOG.debug("Setting fm_presets = %s" % (value))
                self._memobj.fm_presets = value
            except Exception:
                LOG.debug(element.get_name())
                raise


@directory.register
class TDH8_HAM(TDH8):
    VENDOR = "TIDRADIO"
    MODEL = "TD-H8-HAM"
    ident_mode = b'P31185\xff\xff'
    _ham = True
    _vhf_range = (144000000, 149000000)
    _uhf_range = (420000000, 451000000)


@directory.register
class TDH8_GMRS(TDH8):
    VENDOR = "TIDRADIO"
    MODEL = "TD-H8-GMRS"
    ident_mode = b'P31184\xff\xff'
    _gmrs = True
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 521000000)

    def validate_memory(self, mem):
        msgs = super().validate_memory(mem)
        if 31 <= mem.number <= 54 and mem.freq not in GMRS_FREQS:
            msgs.append(chirp_common.ValidationError(
                "The frequency in channels 31-54 must be between"
                "462.55000-462.72500 in 0.025 increments."))
        return msgs


@directory.register
class UV68(TDH8):
    VENDOR = "TID"
    MODEL = "TD-UV68"
