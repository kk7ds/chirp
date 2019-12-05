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

from builtins import bytes

import struct
import time
import os
import logging

from chirp import chirp_common, errors, util, directory, memmap
from chirp import bitwise
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, InvalidValueError, RadioSettings
from textwrap import dedent

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0008;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:3,
     isuhf:1,
     scode:4;
  u8 unknown1:7,
     txtoneicon:1;
  u8 mailicon:3,
     unknown2:3,
     lowpower:2;
  u8 unknown3:1,
     wide:1,
     unknown4:2,
     bcl:1,
     scan:1,
     pttid:2;
} memory[128];

#seekto 0x0B08;
struct {
  u8 code[5];
  u8 unused[11];
} pttid[15];

#seekto 0x0C88;
struct {
  u8 code222[3];
  u8 unused222[2];
  u8 code333[3];
  u8 unused333[2];
  u8 alarmcode[3];
  u8 unused119[2];
  u8 unknown1;
  u8 code555[3];
  u8 unused555[2];
  u8 code666[3];
  u8 unused666[2];
  u8 code777[3];
  u8 unused777[2];
  u8 unknown2;
  u8 code60606[5];
  u8 code70707[5];
  u8 code[5];
  u8 unused1:6,
     aniid:2;
  u8 unknown[2];
  u8 dtmfon;
  u8 dtmfoff;
} ani;

#seekto 0x0E28;
struct {
  u8 squelch;
  u8 step;
  u8 unknown1;
  u8 save;
  u8 vox;
  u8 unknown2;
  u8 abr;
  u8 tdr;
  u8 beep;
  u8 timeout;
  u8 unknown3[4];
  u8 voice;
  u8 unknown4;
  u8 dtmfst;
  u8 unknown5;
  u8 unknown12:6,
     screv:2;
  u8 pttid;
  u8 pttlt;
  u8 mdfa;
  u8 mdfb;
  u8 bcl;
  u8 autolk; // NOTE: The UV-6 calls this byte voxenable, but the UV-5R
             // calls it autolk. Since this is a minor difference, it will
             // be referred to by the wrong name for the UV-6.
  u8 sftd;
  u8 unknown6[3];
  u8 wtled;
  u8 rxled;
  u8 txled;
  u8 almod;
  u8 band;
  u8 tdrab;
  u8 ste;
  u8 rpste;
  u8 rptrl;
  u8 ponmsg;
  u8 roger;
  u8 rogerrx;
  u8 tdrch; // NOTE: The UV-82HP calls this byte rtone, but the UV-6
            // calls it tdrch. Since this is a minor difference, it will
            // be referred to by the wrong name for the UV-82HP.
  u8 displayab:1,
     unknown1:2,
     fmradio:1,
     alarm:1,
     unknown2:1,
     reset:1,
     menu:1;
  u8 unknown1:6,
     singleptt:1,
     vfomrlock:1;
  u8 workmode;
  u8 keylock;
} settings;

#seekto 0x0E7E;
struct {
  u8 unused1:1,
     mrcha:7;
  u8 unused2:1,
     mrchb:7;
} wmchannel;

#seekto 0x0F10;
struct {
  u8 freq[8];
  u8 unknown1;
  u8 offset[4];
  u8 unknown2;
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:7,
     band:1;
  u8 unknown3;
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown4;
  u8 unused3:1
     step:3,
     unused4:4;
  u8 txpower:1,
     widenarr:1,
     unknown5:4,
     txpower3:2;
} vfoa;

#seekto 0x0F30;
struct {
  u8 freq[8];
  u8 unknown1;
  u8 offset[4];
  u8 unknown2;
  ul16 rxtone;
  ul16 txtone;
  u8 unused1:7,
     band:1;
  u8 unknown3;
  u8 unused2:2,
     sftd:2,
     scode:4;
  u8 unknown4;
  u8 unused3:1
     step:3,
     unused4:4;
  u8 txpower:1,
     widenarr:1,
     unknown5:4,
     txpower3:2;
} vfob;

#seekto 0x0F56;
u16 fm_presets;

#seekto 0x1008;
struct {
  char name[7];
  u8 unknown2[9];
} names[128];

#seekto 0x1818;
struct {
  char line1[7];
  char line2[7];
} sixpoweron_msg;

#seekto 0x%04X;
struct {
  char line1[7];
  char line2[7];
} poweron_msg;

#seekto 0x1838;
struct {
  char line1[7];
  char line2[7];
} firmware_msg;

struct limit {
  u8 enable;
  bbcd lower[2];
  bbcd upper[2];
};

#seekto 0x1908;
struct {
  struct limit vhf;
  struct limit uhf;
} limits_new;

#seekto 0x1910;
struct {
  u8 unknown1[2];
  struct limit vhf;
  u8 unknown2;
  u8 unknown3[8];
  u8 unknown4[2];
  struct limit uhf;
} limits_old;

struct squelch {
  u8 sql0;
  u8 sql1;
  u8 sql2;
  u8 sql3;
  u8 sql4;
  u8 sql5;
  u8 sql6;
  u8 sql7;
  u8 sql8;
  u8 sql9;
};

#seekto 0x18A8;
struct {
  struct squelch vhf;
  u8 unknown1[6];
  u8 unknown2[16];
  struct squelch uhf;
} squelch_new;

#seekto 0x18E8;
struct {
  struct squelch vhf;
  u8 unknown[6];
  struct squelch uhf;
} squelch_old;

"""

# 0x1EC0 - 0x2000

vhf_220_radio = bytes(b"\x02")

BASETYPE_UV5R = [b"BFS", b"BFB", b"N5R-2", b"N5R2", b"N5RV", b"BTS", b"D5R2",
                 b"B5R2"]
BASETYPE_F11 = [b"USA"]
BASETYPE_UV82 = [b"US2S2", b"B82S", b"BF82", b"N82-2", b"N822"]
BASETYPE_BJ55 = [b"BJ55"]  # needed for for the Baojie UV-55 in bjuv55.py
BASETYPE_UV6 = [b"BF1", b"UV6"]
BASETYPE_KT980HP = [b"BFP3V3 B"]
BASETYPE_F8HP = [b"BFP3V3 F", b"N5R-3", b"N5R3", b"F5R3", b"BFT"]
BASETYPE_UV82HP = [b"N82-3", b"N823", b"N5R2"]
BASETYPE_UV82X3 = [b"HN5RV01"]
BASETYPE_LIST = BASETYPE_UV5R + BASETYPE_F11 + BASETYPE_UV82 + \
    BASETYPE_BJ55 + BASETYPE_UV6 + BASETYPE_KT980HP + \
    BASETYPE_F8HP + BASETYPE_UV82HP + BASETYPE_UV82X3

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
RTONE_LIST = ["1000 Hz", "1450 Hz", "1750 Hz", "2100Hz"]
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
TIMEOUT_LIST = ["%s sec" % x for x in range(15, 615, 15)]
TXPOWER_LIST = ["High", "Low"]
TXPOWER3_LIST = ["High", "Mid", "Low"]
VOICE_LIST = ["Off", "English", "Chinese"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 11)]
WORKMODE_LIST = ["Frequency", "Channel"]

SETTING_LISTS = {
    "almod": ALMOD_LIST,
    "aniid": PTTID_LIST,
    "displayab": AB_LIST,
    "dtmfst": DTMFST_LIST,
    "dtmfspeed": DTMFSPEED_LIST,
    "mdfa": MODE_LIST,
    "mdfb": MODE_LIST,
    "ponmsg": PONMSG_LIST,
    "pttid": PTTID_LIST,
    "rtone": RTONE_LIST,
    "rogerrx": ROGERRX_LIST,
    "rpste": RPSTE_LIST,
    "rxled": COLOR_LIST,
    "save": SAVE_LIST,
    "scode": PTTIDCODE_LIST,
    "screv": RESUME_LIST,
    "sftd": SHIFTD_LIST,
    "stedelay": STEDELAY_LIST,
    "step": STEP_LIST,
    "step291": STEP291_LIST,
    "tdrab": TDRAB_LIST,
    "tdrch": TDRCH_LIST,
    "timeout": TIMEOUT_LIST,
    "txled": COLOR_LIST,
    "txpower": TXPOWER_LIST,
    "txpower3": TXPOWER3_LIST,
    "voice": VOICE_LIST,
    "vox": VOX_LIST,
    "widenarr": BANDWIDTH_LIST,
    "workmode": WORKMODE_LIST,
    "wtled": COLOR_LIST
}


def _do_status(radio, block):
    status = chirp_common.Status()
    status.msg = "Cloning"
    status.cur = block
    status.max = radio.get_memsize()
    radio.status_fn(status)

UV5R_MODEL_ORIG = bytes(b"\x50\xBB\xFF\x01\x25\x98\x4D")
UV5R_MODEL_291 = bytes(b"\x50\xBB\xFF\x20\x12\x07\x25")
UV5R_MODEL_F11 = bytes(b"\x50\xBB\xFF\x13\xA1\x11\xDD")
UV5R_MODEL_UV82 = bytes(b"\x50\xBB\xFF\x20\x13\x01\x05")
UV5R_MODEL_UV6 = bytes(b"\x50\xBB\xFF\x20\x12\x08\x23")
UV5R_MODEL_UV6_ORIG = bytes(b"\x50\xBB\xFF\x12\x03\x98\x4D")
UV5R_MODEL_A58 = bytes(b"\x50\xBB\xFF\x20\x14\x04\x13")


def _upper_band_from_data(data):
    return data[0x03:0x04]


def _upper_band_from_image(radio):
    return _upper_band_from_data(radio.get_mmap())


def _firmware_version_from_data(data, version_start, version_stop):
    version_tag = data[version_start:version_stop]
    return version_tag


def _firmware_version_from_image(radio):
    version = _firmware_version_from_data(
        radio.get_mmap().get_byte_compatible(),
        radio._fw_ver_file_start,
        radio._fw_ver_file_stop)
    LOG.debug("_firmware_version_from_image: " + util.hexprint(version))
    return version


def _do_ident(radio, magic, secondack=True):
    serial = radio.pipe
    serial.timeout = 1

    LOG.info("Sending Magic: %s" % util.hexprint(magic))
    for byte in magic:
        serial.write(bytes([byte]))
        time.sleep(0.01)
    ack = serial.read(1)

    if ack != b"\x06":
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")

    serial.write(bytes(b"\x02"))

    # Until recently, the "ident" returned by the radios supported by this
    # driver have always been 8 bytes long. The image sturcture is the 8 byte
    # "ident" followed by the downloaded memory data. So all of the settings
    # structures are offset by 8 bytes. The ident returned from a UV-6 radio
    # can be 8 bytes (original model) or now 12 bytes.
    #
    # To accomodate this, the "ident" is now read one byte at a time until the
    # last byte ("\xdd") is encountered. The bytes containing the value "\x01"
    # are discarded to shrink the "ident" length down to 8 bytes to keep the
    # image data aligned with the existing settings structures.

    # Ok, get the response
    response = bytes(b"")
    for i in range(1, 13):
        byte = serial.read(1)
        response += byte
        # stop reading once the last byte ("\xdd") is encountered
        if byte == b"\xDD":
            break

    # check if response is OK
    if len(response) in [8, 12]:
        # DEBUG
        LOG.info("Valid response, got this:")
        LOG.debug(util.hexprint(response))
        if len(response) == 12:
            ident = (bytes([response[0], response[3], response[5]]) +
                     response[7:])
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


def _read_block(radio, start, size, first_command=False):
    msg = struct.pack(">BHB", ord("S"), start, size)
    radio.pipe.write(msg)

    if first_command is False:
        ack = radio.pipe.read(1)
        if ack != b"\x06":
            raise errors.RadioError(
                "Radio refused to send second block 0x%04x" % start)

    answer = radio.pipe.read(4)
    if len(answer) != 4:
        raise errors.RadioError("Radio refused to send block 0x%04x" % start)

    cmd, addr, length = struct.unpack(">BHB", answer)
    if cmd != ord("X") or addr != start or length != size:
        LOG.error("Invalid answer for block 0x%04x:" % start)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (cmd, addr, length))
        raise errors.RadioError("Unknown response from radio")

    chunk = radio.pipe.read(0x40)
    if not chunk:
        raise errors.RadioError("Radio did not send block 0x%04x" % start)
    elif len(chunk) != size:
        LOG.error("Chunk length was 0x%04i" % len(chunk))
        raise errors.RadioError("Radio sent incomplete block 0x%04x" % start)

    radio.pipe.write(b"\x06")
    time.sleep(0.05)

    return chunk


def _get_radio_firmware_version(radio):
    if radio.MODEL == "BJ-UV55":
        block = _read_block(radio, 0x1FF0, 0x40, True)
        version = block[0:6]
    else:
        block1 = _read_block(radio, 0x1EC0, 0x40, True)
        block2 = _read_block(radio, 0x1F00, 0x40, False)
        block = block1 + block2
        version = block[48:62]
    return version


IDENT_BLACKLIST = {
    b"\x50\x0D\x0C\x20\x16\x03\x28": "Radio identifies as BTECH UV-5X3",
}


def _ident_radio(radio):
    for magic in radio._idents:
        error = None
        try:
            data = _do_ident(radio, magic)
            return data
        except errors.RadioError as e:
            LOG.error("uv5r._ident_radio: %s", e)
            error = e
            time.sleep(2)

    for magic, reason in list(IDENT_BLACKLIST.items()):
        try:
            _do_ident(radio, magic, secondack=False)
        except errors.RadioError as e:
            # No match, try the next one
            continue

        # If we got here, it means we identified the radio as
        # something other than one of our valid idents. Warn
        # the user so they can do the right thing.
        LOG.warning(('Identified radio as a blacklisted model '
                     '(details: %s)') % reason)
        raise errors.RadioError(('%s. Please choose the proper vendor/'
                                 'model and try again.') % reason)

    if error:
        raise error
    raise errors.RadioError("Radio did not respond")


def _do_download(radio):
    data = _ident_radio(radio)

    radio_version = _get_radio_firmware_version(radio)
    LOG.info("Radio Version is %s" % repr(radio_version))

    if b"HN5RV" in radio_version:
        # A radio with HN5RV firmware has been detected. It could be a
        # UV-5R style radio with HIGH/LOW power levels or it could be a
        # BF-F8HP style radio with HIGH/MID/LOW power levels.
        # We are going to count on the user to make the right choice and
        # then append that model type to the end of the image so it can
        # be properly detected when loaded.
        append_model = True
    elif b"\xFF" * 7 in radio_version:
        # A radio UV-5R style radio that reports no firmware version has
        # been detected.
        # We are going to count on the user to make the right choice and
        # then append that model type to the end of the image so it can
        # be properly detected when loaded.
        append_model = True
    elif not any(type in radio_version for type in radio._basetype):
        # This radio can't be properly detected by parsing its firmware
        # version.
        raise errors.RadioError("Incorrect 'Model' selected.")
    else:
        # This radio can be properly detected by parsing its firmware version.
        # There is no need to append its model type to the end of the image.
        append_model = False

    # Main block
    LOG.debug("downloading main block...")
    for i in range(0, 0x1800, 0x40):
        data += _read_block(radio, i, 0x40, False)
        _do_status(radio, i)
    _do_status(radio, radio.get_memsize())
    LOG.debug("done.")
    LOG.debug("downloading aux block...")
    # Auxiliary block starts at 0x1ECO (?)
    for i in range(0x1EC0, 0x2000, 0x40):
        data += _read_block(radio, i, 0x40, False)

    if append_model:
        data += radio.MODEL.ljust(8)

    LOG.debug("done.")
    return memmap.MemoryMapBytes(data)


def _send_block(radio, addr, data):
    msg = struct.pack(">BHB", ord("X"), addr, len(data))
    radio.pipe.write(msg + data)
    time.sleep(0.05)

    ack = radio.pipe.read(1)
    if ack != b"\x06":
        raise errors.RadioError("Radio refused to accept block 0x%04x" % addr)


def _do_upload(radio):
    ident = _ident_radio(radio)
    radio_upper_band = ident[3:4]
    image_upper_band = _upper_band_from_image(radio)

    if image_upper_band == vhf_220_radio or radio_upper_band == vhf_220_radio:
        if image_upper_band != radio_upper_band:
            raise errors.RadioError("Image not supported by radio")

    image_version = _firmware_version_from_image(radio)
    radio_version = _get_radio_firmware_version(radio)
    LOG.info("Image Version is %s" % repr(image_version))
    LOG.info("Radio Version is %s" % repr(radio_version))

    # default ranges
    _ranges_main_default = [
        (0x0008, 0x0CF8),
        (0x0D08, 0x0DF8),
        (0x0E08, 0x1808)
        ]
    _ranges_aux_default = [
        (0x1EC0, 0x1EF0),
        ]

    # extra aux ranges
    _ranges_aux_extra = [
        (0x1F60, 0x1F70),
        (0x1F80, 0x1F90),
        (0x1FC0, 0x1FD0)
        ]

    if image_version == radio_version:
        image_matched_radio = True
        if image_version.startswith(b"HN5RV"):
            ranges_main = _ranges_main_default
            ranges_aux = _ranges_aux_default + _ranges_aux_extra
        elif image_version == 0xFF * 7:
            ranges_main = _ranges_main_default
            ranges_aux = _ranges_aux_default + _ranges_aux_extra
        else:
            ranges_main = radio._ranges_main
            ranges_aux = radio._ranges_aux
    elif any(type in radio_version for type in radio._basetype):
        image_matched_radio = False
        ranges_main = _ranges_main_default
        ranges_aux = _ranges_aux_default
    else:
        msg = ("The upload was stopped because the firmware "
               "version of the image (%s) does not match that "
               "of the radio (%s).")
        raise errors.RadioError(msg % (image_version, radio_version))

    # Main block
    mmap = radio.get_mmap().get_byte_compatible()
    for start_addr, end_addr in ranges_main:
        for i in range(start_addr, end_addr, 0x10):
            _send_block(radio, i - 0x08, mmap[i:i + 0x10])
            _do_status(radio, i)
        _do_status(radio, radio.get_memsize())

    if len(mmap.get_packed()) == 0x1808:
        LOG.info("Old image, not writing aux block")
        return  # Old image, no aux block

    # Auxiliary block at radio address 0x1EC0, our offset 0x1808
    for start_addr, end_addr in ranges_aux:
        for i in range(start_addr, end_addr, 0x10):
            addr = 0x1808 + (i - 0x1EC0)
            _send_block(radio, i, mmap[addr:addr + 0x10])

    if not image_matched_radio:
        msg = ("Upload finished, but the 'Other Settings' "
               "could not be sent because the firmware "
               "version of the image (%s) does not match "
               "that of the radio (%s).")
        raise errors.RadioError(msg % (image_version, radio_version))

UV5R_POWER_LEVELS = [chirp_common.PowerLevel("High", watts=4.00),
                     chirp_common.PowerLevel("Low",  watts=1.00)]

UV5R_POWER_LEVELS3 = [chirp_common.PowerLevel("High", watts=8.00),
                      chirp_common.PowerLevel("Med",  watts=4.00),
                      chirp_common.PowerLevel("Low",  watts=1.00)]

UV5R_DTCS = sorted(chirp_common.DTCS_CODES + [645])

UV5R_CHARSET = chirp_common.CHARSET_UPPER_NUMERIC + \
    "!@#$%^&*()+-=[]:\";'<>?,./"


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""

    if len(data) == 0x1950:
        rid = data[0x1948:0x1950]
        return rid.startswith(cls.MODEL)
    elif len(data) == 0x1948:
        rid = data[cls._fw_ver_file_start:cls._fw_ver_file_stop]
        if any(type in rid for type in cls._basetype):
            return True
    else:
        return False


class BaofengUV5R(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):

    """Baofeng UV-5R"""
    VENDOR = "Baofeng"
    MODEL = "UV-5R"
    BAUD_RATE = 9600
    NEEDS_COMPAT_SERIAL = False

    _memsize = 0x1808
    _basetype = BASETYPE_UV5R
    _idents = [UV5R_MODEL_291,
               UV5R_MODEL_ORIG
               ]
    _vhf_range = (136000000, 174000000)
    _220_range = (220000000, 260000000)
    _uhf_range = (400000000, 520000000)
    _mem_params = (0x1828  # poweron_msg offset
                   )
    # offset of fw version in image file
    _fw_ver_file_start = 0x1838
    _fw_ver_file_stop = 0x1846

    _ranges_main = [
                    (0x0008, 0x1808),
                   ]
    _ranges_aux = [
                   (0x1EC0, 0x2000),
                  ]
    _valid_chars = UV5R_CHARSET

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('Due to the fact that the manufacturer continues to '
             'release new versions of the firmware with obscure and '
             'hard-to-track changes, this driver may not work with '
             'your device. Thus far and to the best knowledge of the '
             'author, no UV-5R radios have been harmed by using CHIRP. '
             'However, proceed at your own risk!')
        rp.pre_download = _(dedent("""\
            1. Turn radio off.
            2. Connect cable to mic/spkr connector.
            3. Make sure connector is firmly connected.
            4. Turn radio on (volume may need to be set at 100%).
            5. Ensure that the radio is tuned to channel with no activity.
            6. Click OK to download image from device."""))
        rp.pre_upload = _(dedent("""\
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
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.valid_name_length = 7
        rf.valid_characters = self._valid_chars
        rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = UV5R_POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_tuning_steps = STEPS

        normal_bands = [self._vhf_range, self._uhf_range]
        rax_bands = [self._vhf_range, self._220_range]

        if self._mmap is None:
            rf.valid_bands = [normal_bands[0], rax_bands[1], normal_bands[1]]
        elif not self._is_orig() and self._my_upper_band() == vhf_220_radio:
            rf.valid_bands = rax_bands
        else:
            rf.valid_bands = normal_bands
        rf.memory_bounds = (0, 127)
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False
        if len(filedata) in [0x1808, 0x1948, 0x1950]:
            match_size = True
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT % self._mem_params, self._mmap)

    def sync_in(self):
        try:
            self._mmap = _do_download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    def sync_out(self):
        try:
            _do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def _get_mem(self, number):
        return self._memobj.memory[number]

    def _get_nam(self, number):
        return self._memobj.names[number]

    def get_memory(self, number):
        _mem = self._get_mem(number)
        _nam = self._get_nam(number)

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        elif abs(int(_mem.rxfreq) * 10 - int(_mem.txfreq) * 10) > 70000000:
            mem.duplex = "split"
            mem.offset = int(_mem.txfreq) * 10
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "  # The UV-5R software may have 0xFF mid-name
            mem.name += str(char)
        mem.name = mem.name.rstrip()

        dtcs_pol = ["N", "N"]

        if _mem.txtone in [0, 0xFFFF]:
            txmode = ""
        elif _mem.txtone >= 0x0258:
            txmode = "Tone"
            mem.rtone = int(_mem.txtone) / 10.0
        elif _mem.txtone <= 0x0258:
            txmode = "DTCS"
            if _mem.txtone > 0x69:
                index = _mem.txtone - 0x6A
                dtcs_pol[0] = "R"
            else:
                index = _mem.txtone - 1
            mem.dtcs = UV5R_DTCS[index]
        else:
            LOG.warn("Bug: txtone is %04x" % _mem.txtone)

        if _mem.rxtone in [0, 0xFFFF]:
            rxmode = ""
        elif _mem.rxtone >= 0x0258:
            rxmode = "Tone"
            mem.ctone = int(_mem.rxtone) / 10.0
        elif _mem.rxtone <= 0x0258:
            rxmode = "DTCS"
            if _mem.rxtone >= 0x6A:
                index = _mem.rxtone - 0x6A
                dtcs_pol[1] = "R"
            else:
                index = _mem.rxtone - 1
            mem.rx_dtcs = UV5R_DTCS[index]
        else:
            LOG.warn("Bug: rxtone is %04x" % _mem.rxtone)

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        mem.dtcs_polarity = "".join(dtcs_pol)

        if not _mem.scan:
            mem.skip = "S"

        if self.MODEL in ("KT-980HP", "BF-F8HP", "UV-82HP"):
            levels = UV5R_POWER_LEVELS3
        else:
            levels = UV5R_POWER_LEVELS
        try:
            mem.power = levels[_mem.lowpower]
        except IndexError:
            LOG.error("Radio reported invalid power level %s (in %s)" %
                      (_mem.lowpower, levels))
            mem.power = levels[0]

        mem.mode = _mem.wide and "FM" or "NFM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[_mem.pttid]))
        mem.extra.append(rs)

        rs = RadioSetting("scode", "PTT ID Code",
                          RadioSettingValueList(PTTIDCODE_LIST,
                                                PTTIDCODE_LIST[_mem.scode]))
        mem.extra.append(rs)

        return mem

    def _set_mem(self, number):
        return self._memobj.memory[number]

    def _set_nam(self, number):
        return self._memobj.names[number]

    def set_memory(self, mem):
        _mem = self._get_mem(mem.number)
        _nam = self._get_nam(mem.number)

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

        was_empty = False
        # same method as used in get_memory to find
        # out whether a raw memory is empty
        if _mem.get_raw()[0] == "\xff":
            was_empty = True
            LOG.debug("UV5R: this mem was empty")
        else:
            # memorize old extra-values before erasing the whole memory
            # used to solve issue 4121
            LOG.debug("mem was not empty, memorize extra-settings")
            prev_bcl = _mem.bcl.get_value()
            prev_scode = _mem.scode.get_value()
            prev_pttid = _mem.pttid.get_value()

        _mem.set_raw("\x00" * 16)

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _namelength = self.get_features().valid_name_length
        for i in range(_namelength):
            try:
                _nam.name[i] = mem.name[i]
            except IndexError:
                _nam.name[i] = "\xFF"

        rxmode = txmode = ""
        if mem.tmode == "Tone":
            _mem.txtone = int(mem.rtone * 10)
            _mem.rxtone = 0
        elif mem.tmode == "TSQL":
            _mem.txtone = int(mem.ctone * 10)
            _mem.rxtone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            rxmode = txmode = "DTCS"
            _mem.txtone = UV5R_DTCS.index(mem.dtcs) + 1
            _mem.rxtone = UV5R_DTCS.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = UV5R_DTCS.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = UV5R_DTCS.index(mem.rx_dtcs) + 1
            else:
                _mem.rxtone = 0
        else:
            _mem.rxtone = 0
            _mem.txtone = 0

        if txmode == "DTCS" and mem.dtcs_polarity[0] == "R":
            _mem.txtone += 0x69
        if rxmode == "DTCS" and mem.dtcs_polarity[1] == "R":
            _mem.rxtone += 0x69

        _mem.scan = mem.skip != "S"
        _mem.wide = mem.mode == "FM"

        if mem.power:
            if self.MODEL in ("KT-980HP", "BF-F8HP", "UV-82HP"):
                levels = [str(l) for l in UV5R_POWER_LEVELS3]
                _mem.lowpower = levels.index(str(mem.power))
            else:
                _mem.lowpower = UV5R_POWER_LEVELS.index(mem.power)
        else:
            _mem.lowpower = 0

        if not was_empty:
            # restoring old extra-settings (issue 4121
            _mem.bcl.set_value(prev_bcl)
            _mem.scode.set_value(prev_scode)
            _mem.pttid.set_value(prev_pttid)

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def _is_orig(self):
        version_tag = _firmware_version_from_image(self)
        LOG.debug("@_is_orig, version_tag: %s", util.hexprint(version_tag))
        try:
            if b'BFB' in version_tag:
                idx = version_tag.index(b"BFB") + 3
                version = int(version_tag[idx:idx + 3])
                return version < 291
            return False
        except:
            pass
        raise errors.RadioError("Unable to parse version string %s" %
                                version_tag)

    def _my_version(self):
        version_tag = _firmware_version_from_image(self)
        if b'BFB' in version_tag:
            idx = version_tag.index(b"BFB") + 3
            return int(version_tag[idx:idx + 3])

        raise Exception("Unrecognized firmware version string")

    def _my_upper_band(self):
        band_tag = _upper_band_from_image(self)
        return band_tag

    def _get_settings(self):
        _ani = self._memobj.ani
        _fm_presets = self._memobj.fm_presets
        _settings = self._memobj.settings
        _squelch = self._memobj.squelch_new
        _vfoa = self._memobj.vfoa
        _vfob = self._memobj.vfob
        _wmchannel = self._memobj.wmchannel
        basic = RadioSettingGroup("basic", "Basic Settings")
        advanced = RadioSettingGroup("advanced", "Advanced Settings")

        group = RadioSettings(basic, advanced)

        rs = RadioSetting("squelch", "Carrier Squelch Level",
                          RadioSettingValueInteger(0, 9, _settings.squelch))
        basic.append(rs)

        rs = RadioSetting("save", "Battery Saver",
                          RadioSettingValueList(
                              SAVE_LIST, SAVE_LIST[_settings.save]))
        basic.append(rs)

        rs = RadioSetting("vox", "VOX Sensitivity",
                          RadioSettingValueList(
                              VOX_LIST, VOX_LIST[_settings.vox]))
        advanced.append(rs)

        if self.MODEL == "UV-6":
            # NOTE: The UV-6 calls this byte voxenable, but the UV-5R calls it
            # autolk. Since this is a minor difference, it will be referred to
            # by the wrong name for the UV-6.
            rs = RadioSetting("autolk", "Vox",
                              RadioSettingValueBoolean(_settings.autolk))
            advanced.append(rs)

        if self.MODEL != "UV-6":
            rs = RadioSetting("abr", "Backlight Timeout",
                              RadioSettingValueInteger(0, 24, _settings.abr))
            basic.append(rs)

        rs = RadioSetting("tdr", "Dual Watch",
                          RadioSettingValueBoolean(_settings.tdr))
        advanced.append(rs)

        if self.MODEL == "UV-6":
            rs = RadioSetting("tdrch", "Dual Watch Channel",
                              RadioSettingValueList(
                                  TDRCH_LIST, TDRCH_LIST[_settings.tdrch]))
            advanced.append(rs)

            rs = RadioSetting("tdrab", "Dual Watch TX Priority",
                              RadioSettingValueBoolean(_settings.tdrab))
            advanced.append(rs)
        else:
            rs = RadioSetting("tdrab", "Dual Watch TX Priority",
                              RadioSettingValueList(
                                  TDRAB_LIST, TDRAB_LIST[_settings.tdrab]))
            advanced.append(rs)

        if self.MODEL == "UV-6":
            rs = RadioSetting("alarm", "Alarm Sound",
                              RadioSettingValueBoolean(_settings.alarm))
            advanced.append(rs)

        if _settings.almod > 0x02:
            val = 0x01
        else:
            val = _settings.almod
        rs = RadioSetting("almod", "Alarm Mode",
                          RadioSettingValueList(
                              ALMOD_LIST, ALMOD_LIST[val]))
        advanced.append(rs)

        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(_settings.beep))
        basic.append(rs)

        rs = RadioSetting("timeout", "Timeout Timer",
                          RadioSettingValueList(
                              TIMEOUT_LIST, TIMEOUT_LIST[_settings.timeout]))
        basic.append(rs)

        if self._is_orig() and self._my_version() < 251:
            rs = RadioSetting("voice", "Voice",
                              RadioSettingValueBoolean(_settings.voice))
            advanced.append(rs)
        else:
            rs = RadioSetting("voice", "Voice",
                              RadioSettingValueList(
                                  VOICE_LIST, VOICE_LIST[_settings.voice]))
            advanced.append(rs)

        rs = RadioSetting("screv", "Scan Resume",
                          RadioSettingValueList(
                              RESUME_LIST, RESUME_LIST[_settings.screv]))
        advanced.append(rs)

        if self.MODEL != "UV-6":
            rs = RadioSetting("mdfa", "Display Mode (A)",
                              RadioSettingValueList(
                                  MODE_LIST, MODE_LIST[_settings.mdfa]))
            basic.append(rs)

            rs = RadioSetting("mdfb", "Display Mode (B)",
                              RadioSettingValueList(
                                  MODE_LIST, MODE_LIST[_settings.mdfb]))
            basic.append(rs)

        rs = RadioSetting("bcl", "Busy Channel Lockout",
                          RadioSettingValueBoolean(_settings.bcl))
        advanced.append(rs)

        if self.MODEL != "UV-6":
            rs = RadioSetting("autolk", "Automatic Key Lock",
                              RadioSettingValueBoolean(_settings.autolk))
            advanced.append(rs)

        rs = RadioSetting("fmradio", "Broadcast FM Radio",
                          RadioSettingValueBoolean(_settings.fmradio))
        advanced.append(rs)

        if self.MODEL != "UV-6":
            rs = RadioSetting("wtled", "Standby LED Color",
                              RadioSettingValueList(
                                  COLOR_LIST, COLOR_LIST[_settings.wtled]))
            basic.append(rs)

            rs = RadioSetting("rxled", "RX LED Color",
                              RadioSettingValueList(
                                  COLOR_LIST, COLOR_LIST[_settings.rxled]))
            basic.append(rs)

            rs = RadioSetting("txled", "TX LED Color",
                              RadioSettingValueList(
                                  COLOR_LIST, COLOR_LIST[_settings.txled]))
            basic.append(rs)

        if isinstance(self, BaofengUV82Radio):
            rs = RadioSetting("roger", "Roger Beep (TX)",
                              RadioSettingValueBoolean(_settings.roger))
            basic.append(rs)
            rs = RadioSetting("rogerrx", "Roger Beep (RX)",
                              RadioSettingValueList(
                                  ROGERRX_LIST,
                                  ROGERRX_LIST[_settings.rogerrx]))
            basic.append(rs)
        else:
            rs = RadioSetting("roger", "Roger Beep",
                              RadioSettingValueBoolean(_settings.roger))
            basic.append(rs)

        rs = RadioSetting("ste", "Squelch Tail Eliminate (HT to HT)",
                          RadioSettingValueBoolean(_settings.ste))
        advanced.append(rs)

        rs = RadioSetting("rpste", "Squelch Tail Eliminate (repeater)",
                          RadioSettingValueList(
                              RPSTE_LIST, RPSTE_LIST[_settings.rpste]))
        advanced.append(rs)

        rs = RadioSetting("rptrl", "STE Repeater Delay",
                          RadioSettingValueList(
                              STEDELAY_LIST, STEDELAY_LIST[_settings.rptrl]))
        advanced.append(rs)

        if self.MODEL != "UV-6":
            rs = RadioSetting("reset", "RESET Menu",
                              RadioSettingValueBoolean(_settings.reset))
            advanced.append(rs)

            rs = RadioSetting("menu", "All Menus",
                              RadioSettingValueBoolean(_settings.menu))
            advanced.append(rs)

        if self.MODEL == "F-11":
            # this is an F-11 only feature
            rs = RadioSetting("vfomrlock", "VFO/MR Button",
                              RadioSettingValueBoolean(_settings.vfomrlock))
            advanced.append(rs)

        if isinstance(self, BaofengUV82Radio):
            # this is a UV-82C only feature
            rs = RadioSetting("vfomrlock", "VFO/MR Switching (UV-82C only)",
                              RadioSettingValueBoolean(_settings.vfomrlock))
            advanced.append(rs)

        if self.MODEL == "UV-82HP":
            # this is a UV-82HP only feature
            rs = RadioSetting(
                "vfomrlock", "VFO/MR Switching (BTech UV-82HP only)",
                RadioSettingValueBoolean(_settings.vfomrlock))
            advanced.append(rs)

        if isinstance(self, BaofengUV82Radio):
            # this is an UV-82C only feature
            rs = RadioSetting("singleptt", "Single PTT (UV-82C only)",
                              RadioSettingValueBoolean(_settings.singleptt))
            advanced.append(rs)

        if self.MODEL == "UV-82HP":
            # this is an UV-82HP only feature
            rs = RadioSetting("singleptt", "Single PTT (BTech UV-82HP only)",
                              RadioSettingValueBoolean(_settings.singleptt))
            advanced.append(rs)

        if self.MODEL == "UV-82HP":
            # this is an UV-82HP only feature
            rs = RadioSetting(
                "tdrch", "Tone Burst Frequency (BTech UV-82HP only)",
                RadioSettingValueList(RTONE_LIST, RTONE_LIST[_settings.tdrch]))
            advanced.append(rs)

        if len(self._mmap.get_packed()) == 0x1808:
            # Old image, without aux block
            return group

        other = RadioSettingGroup("other", "Other Settings")
        group.append(other)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        _msg = self._memobj.firmware_msg
        val = RadioSettingValueString(0, 7, _filter(_msg.line1))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line1", "Firmware Message 1", val)
        other.append(rs)

        val = RadioSettingValueString(0, 7, _filter(_msg.line2))
        val.set_mutable(False)
        rs = RadioSetting("firmware_msg.line2", "Firmware Message 2", val)
        other.append(rs)

        if self.MODEL != "UV-6":
            _msg = self._memobj.sixpoweron_msg
            rs = RadioSetting("sixpoweron_msg.line1", "6+Power-On Message 1",
                              RadioSettingValueString(
                                  0, 7, _filter(_msg.line1)))
            other.append(rs)
            rs = RadioSetting("sixpoweron_msg.line2", "6+Power-On Message 2",
                              RadioSettingValueString(
                                  0, 7, _filter(_msg.line2)))
            other.append(rs)

            _msg = self._memobj.poweron_msg
            rs = RadioSetting("poweron_msg.line1", "Power-On Message 1",
                              RadioSettingValueString(
                                  0, 7, _filter(_msg.line1)))
            other.append(rs)
            rs = RadioSetting("poweron_msg.line2", "Power-On Message 2",
                              RadioSettingValueString(
                                  0, 7, _filter(_msg.line2)))
            other.append(rs)

            rs = RadioSetting("ponmsg", "Power-On Message",
                              RadioSettingValueList(
                                  PONMSG_LIST, PONMSG_LIST[_settings.ponmsg]))
            other.append(rs)

            if self._is_orig():
                limit = "limits_old"
            else:
                limit = "limits_new"

            vhf_limit = getattr(self._memobj, limit).vhf
            rs = RadioSetting("%s.vhf.lower" % limit, "VHF Lower Limit (MHz)",
                              RadioSettingValueInteger(1, 1000,
                                                       vhf_limit.lower))
            other.append(rs)

            rs = RadioSetting("%s.vhf.upper" % limit, "VHF Upper Limit (MHz)",
                              RadioSettingValueInteger(1, 1000,
                                                       vhf_limit.upper))
            other.append(rs)

            rs = RadioSetting("%s.vhf.enable" % limit, "VHF TX Enabled",
                              RadioSettingValueBoolean(vhf_limit.enable))
            other.append(rs)

            uhf_limit = getattr(self._memobj, limit).uhf
            rs = RadioSetting("%s.uhf.lower" % limit, "UHF Lower Limit (MHz)",
                              RadioSettingValueInteger(1, 1000,
                                                       uhf_limit.lower))
            other.append(rs)
            rs = RadioSetting("%s.uhf.upper" % limit, "UHF Upper Limit (MHz)",
                              RadioSettingValueInteger(1, 1000,
                                                       uhf_limit.upper))
            other.append(rs)
            rs = RadioSetting("%s.uhf.enable" % limit, "UHF TX Enabled",
                              RadioSettingValueBoolean(uhf_limit.enable))
            other.append(rs)

        if self.MODEL != "UV-6":
            workmode = RadioSettingGroup("workmode", "Work Mode Settings")
            group.append(workmode)

            rs = RadioSetting("displayab", "Display",
                              RadioSettingValueList(
                                  AB_LIST, AB_LIST[_settings.displayab]))
            workmode.append(rs)

            rs = RadioSetting("workmode", "VFO/MR Mode",
                              RadioSettingValueList(
                                  WORKMODE_LIST,
                                  WORKMODE_LIST[_settings.workmode]))
            workmode.append(rs)

            rs = RadioSetting("keylock", "Keypad Lock",
                              RadioSettingValueBoolean(_settings.keylock))
            workmode.append(rs)

            rs = RadioSetting("wmchannel.mrcha", "MR A Channel",
                              RadioSettingValueInteger(0, 127,
                                                       _wmchannel.mrcha))
            workmode.append(rs)

            rs = RadioSetting("wmchannel.mrchb", "MR B Channel",
                              RadioSettingValueInteger(0, 127,
                                                       _wmchannel.mrchb))
            workmode.append(rs)

            def convert_bytes_to_freq(bytes):
                real_freq = 0
                for byte in bytes:
                    real_freq = (real_freq * 10) + byte
                return chirp_common.format_freq(real_freq * 10)

            def my_validate(value):
                value = chirp_common.parse_freq(value)
                if 17400000 <= value and value < 40000000:
                    msg = ("Can't be between 174.00000-400.00000")
                    raise InvalidValueError(msg)
                return chirp_common.format_freq(value)

            def apply_freq(setting, obj):
                value = chirp_common.parse_freq(str(setting.value)) / 10
                obj.band = value >= 40000000
                for i in range(7, -1, -1):
                    obj.freq[i] = value % 10
                    value /= 10

            val1a = RadioSettingValueString(0, 10,
                                            convert_bytes_to_freq(_vfoa.freq))
            val1a.set_validate_callback(my_validate)
            rs = RadioSetting("vfoa.freq", "VFO A Frequency", val1a)
            rs.set_apply_callback(apply_freq, _vfoa)
            workmode.append(rs)

            val1b = RadioSettingValueString(0, 10,
                                            convert_bytes_to_freq(_vfob.freq))
            val1b.set_validate_callback(my_validate)
            rs = RadioSetting("vfob.freq", "VFO B Frequency", val1b)
            rs.set_apply_callback(apply_freq, _vfob)
            workmode.append(rs)

            rs = RadioSetting("vfoa.sftd", "VFO A Shift",
                              RadioSettingValueList(
                                  SHIFTD_LIST, SHIFTD_LIST[_vfoa.sftd]))
            workmode.append(rs)

            rs = RadioSetting("vfob.sftd", "VFO B Shift",
                              RadioSettingValueList(
                                  SHIFTD_LIST, SHIFTD_LIST[_vfob.sftd]))
            workmode.append(rs)

            def convert_bytes_to_offset(bytes):
                real_offset = 0
                for byte in bytes:
                    real_offset = (real_offset * 10) + byte
                return chirp_common.format_freq(real_offset * 10000)

            def apply_offset(setting, obj):
                value = chirp_common.parse_freq(str(setting.value)) / 10000
                for i in range(3, -1, -1):
                    obj.offset[i] = value % 10
                    value /= 10

            val1a = RadioSettingValueString(
                0, 10, convert_bytes_to_offset(_vfoa.offset))
            rs = RadioSetting("vfoa.offset",
                              "VFO A Offset (0.00-69.95)", val1a)
            rs.set_apply_callback(apply_offset, _vfoa)
            workmode.append(rs)

            val1b = RadioSettingValueString(
                0, 10, convert_bytes_to_offset(_vfob.offset))
            rs = RadioSetting("vfob.offset",
                              "VFO B Offset (0.00-69.95)", val1b)
            rs.set_apply_callback(apply_offset, _vfob)
            workmode.append(rs)

            if self.MODEL in ("KT-980HP", "BF-F8HP", "UV-82HP"):
                rs = RadioSetting("vfoa.txpower3", "VFO A Power",
                                  RadioSettingValueList(
                                      TXPOWER3_LIST,
                                      TXPOWER3_LIST[_vfoa.txpower3]))
                workmode.append(rs)

                rs = RadioSetting("vfob.txpower3", "VFO B Power",
                                  RadioSettingValueList(
                                      TXPOWER3_LIST,
                                      TXPOWER3_LIST[_vfob.txpower3]))
                workmode.append(rs)
            else:
                rs = RadioSetting("vfoa.txpower", "VFO A Power",
                                  RadioSettingValueList(
                                      TXPOWER_LIST,
                                      TXPOWER_LIST[_vfoa.txpower]))
                workmode.append(rs)

                rs = RadioSetting("vfob.txpower", "VFO B Power",
                                  RadioSettingValueList(
                                      TXPOWER_LIST,
                                      TXPOWER_LIST[_vfob.txpower]))
                workmode.append(rs)

            rs = RadioSetting("vfoa.widenarr", "VFO A Bandwidth",
                              RadioSettingValueList(
                                  BANDWIDTH_LIST,
                                  BANDWIDTH_LIST[_vfoa.widenarr]))
            workmode.append(rs)

            rs = RadioSetting("vfob.widenarr", "VFO B Bandwidth",
                              RadioSettingValueList(
                                  BANDWIDTH_LIST,
                                  BANDWIDTH_LIST[_vfob.widenarr]))
            workmode.append(rs)

            rs = RadioSetting("vfoa.scode", "VFO A PTT-ID",
                              RadioSettingValueList(
                                  PTTIDCODE_LIST, PTTIDCODE_LIST[_vfoa.scode]))
            workmode.append(rs)

            rs = RadioSetting("vfob.scode", "VFO B PTT-ID",
                              RadioSettingValueList(
                                  PTTIDCODE_LIST, PTTIDCODE_LIST[_vfob.scode]))
            workmode.append(rs)

            if not self._is_orig():
                rs = RadioSetting("vfoa.step", "VFO A Tuning Step",
                                  RadioSettingValueList(
                                      STEP291_LIST, STEP291_LIST[_vfoa.step]))
                workmode.append(rs)
                rs = RadioSetting("vfob.step", "VFO B Tuning Step",
                                  RadioSettingValueList(
                                      STEP291_LIST, STEP291_LIST[_vfob.step]))
                workmode.append(rs)
            else:
                rs = RadioSetting("vfoa.step", "VFO A Tuning Step",
                                  RadioSettingValueList(
                                      STEP_LIST, STEP_LIST[_vfoa.step]))
                workmode.append(rs)
                rs = RadioSetting("vfob.step", "VFO B Tuning Step",
                                  RadioSettingValueList(
                                      STEP_LIST, STEP_LIST[_vfob.step]))
                workmode.append(rs)

        fm_preset = RadioSettingGroup("fm_preset", "FM Radio Preset")
        group.append(fm_preset)

        if _fm_presets <= 108.0 * 10 - 650:
            preset = _fm_presets / 10.0 + 65
        elif _fm_presets >= 65.0 * 10 and _fm_presets <= 108.0 * 10:
            preset = _fm_presets / 10.0
        else:
            preset = 76.0
        rs = RadioSetting("fm_presets", "FM Preset(MHz)",
                          RadioSettingValueFloat(65, 108.0, preset, 0.1, 1))
        fm_preset.append(rs)

        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        group.append(dtmf)
        dtmfchars = "0123456789 *#ABCD"

        for i in range(0, 15):
            _codeobj = self._memobj.pttid[i].code
            _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
            val = RadioSettingValueString(0, 5, _code, False)
            val.set_charset(dtmfchars)
            rs = RadioSetting("pttid/%i.code" % i,
                              "PTT ID Code %i" % (i + 1), val)

            def apply_code(setting, obj):
                code = []
                for j in range(0, 5):
                    try:
                        code.append(dtmfchars.index(str(setting.value)[j]))
                    except IndexError:
                        code.append(0xFF)
                obj.code = code
            rs.set_apply_callback(apply_code, self._memobj.pttid[i])
            dtmf.append(rs)

        _codeobj = self._memobj.ani.code
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 5, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("ani.code", "ANI Code", val)

        def apply_code(setting, obj):
            code = []
            for j in range(0, 5):
                try:
                    code.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    code.append(0xFF)
            obj.code = code
        rs.set_apply_callback(apply_code, _ani)
        dtmf.append(rs)

        rs = RadioSetting("ani.aniid", "ANI ID",
                          RadioSettingValueList(PTTID_LIST,
                                                PTTID_LIST[_ani.aniid]))
        dtmf.append(rs)

        _codeobj = self._memobj.ani.alarmcode
        _code = "".join([dtmfchars[x] for x in _codeobj if int(x) < 0x1F])
        val = RadioSettingValueString(0, 3, _code, False)
        val.set_charset(dtmfchars)
        rs = RadioSetting("ani.alarmcode", "Alarm Code", val)

        def apply_code(setting, obj):
            alarmcode = []
            for j in range(0, 3):
                try:
                    alarmcode.append(dtmfchars.index(str(setting.value)[j]))
                except IndexError:
                    alarmcode.append(0xFF)
            obj.alarmcode = alarmcode
        rs.set_apply_callback(apply_code, _ani)
        dtmf.append(rs)

        rs = RadioSetting("dtmfst", "DTMF Sidetone",
                          RadioSettingValueList(DTMFST_LIST,
                                                DTMFST_LIST[_settings.dtmfst]))
        dtmf.append(rs)

        if _ani.dtmfon > 0xC3:
            val = 0x00
        else:
            val = _ani.dtmfon
        rs = RadioSetting("ani.dtmfon", "DTMF Speed (on)",
                          RadioSettingValueList(DTMFSPEED_LIST,
                                                DTMFSPEED_LIST[val]))
        dtmf.append(rs)

        if _ani.dtmfoff > 0xC3:
            val = 0x00
        else:
            val = _ani.dtmfoff
        rs = RadioSetting("ani.dtmfoff", "DTMF Speed (off)",
                          RadioSettingValueList(DTMFSPEED_LIST,
                                                DTMFSPEED_LIST[val]))
        dtmf.append(rs)

        rs = RadioSetting("pttlt", "PTT ID Delay",
                          RadioSettingValueInteger(0, 50, _settings.pttlt))
        dtmf.append(rs)

        if not self._is_orig():
            service = RadioSettingGroup("service", "Service Settings")
            group.append(service)

            for band in ["vhf", "uhf"]:
                for index in range(0, 10):
                    key = "squelch_new.%s.sql%i" % (band, index)
                    if band == "vhf":
                        _obj = self._memobj.squelch_new.vhf
                    elif band == "uhf":
                        _obj = self._memobj.squelch_new.uhf
                    name = "%s Squelch %i" % (band.upper(), index)
                    rs = RadioSetting(key, name,
                                      RadioSettingValueInteger(
                                          0, 123,
                                          getattr(_obj, "sql%i" % (index))))
                    service.append(rs)

        return group

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    def set_settings(self, settings):
        _settings = self._memobj.settings
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
                    else:
                        obj = _settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
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
            except Exception as e:
                LOG.debug(element.get_name())
                raise


class UV5XAlias(chirp_common.Alias):
    VENDOR = "Baofeng"
    MODEL = "UV-5X"


class RT5RAlias(chirp_common.Alias):
    VENDOR = "Retevis"
    MODEL = "RT-5R"


class RT5RVAlias(chirp_common.Alias):
    VENDOR = "Retevis"
    MODEL = "RT-5RV"


class RT5Alias(chirp_common.Alias):
    VENDOR = "Retevis"
    MODEL = "RT5"


class RT5_TPAlias(chirp_common.Alias):
    VENDOR = "Retevis"
    MODEL = "RT5(tri-power)"


class RH5RAlias(chirp_common.Alias):
    VENDOR = "Rugged"
    MODEL = "RH5R"


class ROUV5REXAlias(chirp_common.Alias):
    VENDOR = "Radioddity"
    MODEL = "UV-5R EX"


class A5RAlias(chirp_common.Alias):
    VENDOR = "Ansoko"
    MODEL = "A-5R"


class TenwayUV5RPro(chirp_common.Alias):
    VENDOR = 'Tenway'
    MODEL = 'UV-5R Pro'


@directory.register
class BaofengUV5RGeneric(BaofengUV5R):
    ALIASES = [UV5XAlias, RT5RAlias, RT5RVAlias, RT5Alias, RH5RAlias,
               ROUV5REXAlias, A5RAlias, TenwayUV5RPro]


@directory.register
class BaofengF11Radio(BaofengUV5R):
    VENDOR = "Baofeng"
    MODEL = "F-11"
    _basetype = BASETYPE_F11
    _idents = [UV5R_MODEL_F11]

    def _is_orig(self):
        # Override this for F11 to always return False
        return False


@directory.register
class BaofengUV82Radio(BaofengUV5R):
    MODEL = "UV-82"
    _basetype = BASETYPE_UV82
    _idents = [UV5R_MODEL_UV82]
    _vhf_range = (130000000, 176000000)
    _uhf_range = (400000000, 521000000)
    _valid_chars = chirp_common.CHARSET_ASCII

    def _is_orig(self):
        # Override this for UV82 to always return False
        return False


@directory.register
class Radioddity82X3Radio(BaofengUV82Radio):
    VENDOR = "Radioddity"
    MODEL = "UV-82X3"
    _basetype = BASETYPE_UV82X3

    def get_features(self):
        rf = BaofengUV5R.get_features(self)
        rf.valid_bands = [self._vhf_range,
                          (200000000, 260000000),
                          self._uhf_range]
        return rf


@directory.register
class BaofengUV6Radio(BaofengUV5R):

    """Baofeng UV-6/UV-7"""
    VENDOR = "Baofeng"
    MODEL = "UV-6"
    _basetype = BASETYPE_UV6
    _idents = [UV5R_MODEL_UV6,
               UV5R_MODEL_UV6_ORIG
               ]

    def get_features(self):
        rf = BaofengUV5R.get_features(self)
        rf.memory_bounds = (1, 128)
        return rf

    def _get_mem(self, number):
        return self._memobj.memory[number - 1]

    def _get_nam(self, number):
        return self._memobj.names[number - 1]

    def _set_mem(self, number):
        return self._memobj.memory[number - 1]

    def _set_nam(self, number):
        return self._memobj.names[number - 1]

    def _is_orig(self):
        # Override this for UV6 to always return False
        return False


@directory.register
class IntekKT980Radio(BaofengUV5R):
    VENDOR = "Intek"
    MODEL = "KT-980HP"
    _basetype = BASETYPE_KT980HP
    _idents = [UV5R_MODEL_291]
    _vhf_range = (130000000, 180000000)
    _uhf_range = (400000000, 521000000)

    def get_features(self):
        rf = BaofengUV5R.get_features(self)
        rf.valid_power_levels = UV5R_POWER_LEVELS3
        return rf

    def _is_orig(self):
        # Override this for KT980HP to always return False
        return False


class ROGA5SAlias(chirp_common.Alias):
    VENDOR = "Radioddity"
    MODEL = "GA-5S"


@directory.register
class BaofengBFF8HPRadio(BaofengUV5R):
    VENDOR = "Baofeng"
    MODEL = "BF-F8HP"
    ALIASES = [RT5_TPAlias, ROGA5SAlias]
    _basetype = BASETYPE_F8HP
    _idents = [UV5R_MODEL_291,
               UV5R_MODEL_A58
               ]
    _vhf_range = (130000000, 180000000)
    _uhf_range = (400000000, 521000000)

    def get_features(self):
        rf = BaofengUV5R.get_features(self)
        rf.valid_power_levels = UV5R_POWER_LEVELS3
        return rf

    def _is_orig(self):
        # Override this for BFF8HP to always return False
        return False


@directory.register
class BaofengUV82HPRadio(BaofengUV5R):
    VENDOR = "Baofeng"
    MODEL = "UV-82HP"
    _basetype = BASETYPE_UV82HP
    _idents = [UV5R_MODEL_UV82]
    _vhf_range = (136000000, 175000000)
    _uhf_range = (400000000, 521000000)

    def get_features(self):
        rf = BaofengUV5R.get_features(self)
        rf.valid_power_levels = UV5R_POWER_LEVELS3
        return rf

    def _is_orig(self):
        # Override this for UV82HP to always return False
        return False


@directory.register
class RadioddityUV5RX3Radio(BaofengUV5R):
    VENDOR = "Radioddity"
    MODEL = "UV-5RX3"

    def get_features(self):
        rf = BaofengUV5R.get_features(self)
        rf.valid_bands = [self._vhf_range,
                          (200000000, 260000000),
                          self._uhf_range]
        return rf

    @classmethod
    def match_model(cls, filename, filedata):
        return False
