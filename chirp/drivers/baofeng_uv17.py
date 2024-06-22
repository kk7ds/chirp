# Copyright 2023:
# * Sander van der Wel, <svdwel@icloud.com>
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

import logging

from chirp import chirp_common, directory
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettings, RadioSettingValueString
import struct
from chirp.drivers import baofeng_common, baofeng_uv17Pro
from chirp import errors, util

LOG = logging.getLogger(__name__)
LIST_DTMFST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SCANMODE = ["Time", "Carrier", "Search"]


# Radios seem to have different memory sizes
def _get_memory_size(radio):
    response = baofeng_uv17Pro._sendmagic(radio, radio._magic_memsize[0][0],
                                          radio._magic_memsize[0][1])
    mem_size = struct.unpack("<I", response[7:])[0]
    for magic, resplen in radio._magics2:
        baofeng_uv17Pro._sendmagic(radio, magic, resplen)
    return mem_size


# Locations of memory may differ each time, so a mapping has to be made first
def _get_memory_map(radio):
    # Get memory map
    memory_map = []
    if radio._magic_memsize:
        mem_size = _get_memory_size(radio)
    else:
        mem_size = radio._radio_memsize
    if mem_size != radio._radio_memsize:
        raise errors.RadioError("Incorrect radio model or model not supported "
                                "(memory size doesn't match)")
    for addr in range(0x1FFF, mem_size + 0x1000, 0x1000):
        frame = radio._make_frame(b"R", addr, 1)
        baofeng_common._rawsend(radio, frame)
        blocknr = ord(baofeng_common._rawrecv(radio, 6)[5:])
        blocknr = (blocknr >> 4 & 0xf) * 10 + (blocknr & 0xf)
        memory_map += [blocknr]
        baofeng_uv17Pro._sendmagic(radio, b"\x06", 1)
    return memory_map


def _download(radio):
    """Get the memory map"""
    if not radio._DETECTED_BY:
        # The GA510v2 (at least) is detected, and thus has already done ident
        baofeng_uv17Pro._do_ident(radio)
    data = b""
    memory_map = _get_memory_map(radio)

    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    for block_number in radio.BLOCK_ORDER:
        if block_number not in memory_map:
            # Memory block not found.
            LOG.error('Block %i (0x%x) not in memory map: %s',
                      block_number, block_number, memory_map)
            raise errors.RadioError('Radio memory is corrupted. ' +
                                    'Fix this by uploading a backup image ' +
                                    'to the radio.')
        block_index = memory_map.index(block_number) + 1
        start_addr = block_index * 0x1000
        for addr in range(start_addr, start_addr + 0x1000,
                          radio.BLOCK_SIZE):
            frame = radio._make_read_frame(addr, radio.BLOCK_SIZE)
            # DEBUG
            LOG.debug("Frame=" + util.hexprint(frame))

            baofeng_common._rawsend(radio, frame)

            d = baofeng_common._rawrecv(radio, radio.BLOCK_SIZE + 5)

            LOG.debug("Response Data= " + util.hexprint(d))

            data += d[5:]

            status.cur = len(data) // radio.BLOCK_SIZE
            status.msg = "Cloning from radio..."
            radio.status_fn(status)

            baofeng_uv17Pro._sendmagic(radio, b"\x06", 1)
    return data


def _upload(radio):
    """Upload procedure"""
    baofeng_uv17Pro._do_ident(radio)
    memory_map = _get_memory_map(radio)

    status = chirp_common.Status()
    status.cur = 0
    status.max = radio.WRITE_MEM_TOTAL // radio.BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    for block_number in radio.BLOCK_ORDER:
        # Choose a block number if memory map is corrupt
        # This can happen when the upload process was interrupted
        if block_number not in memory_map:
            memory_map[memory_map.index(165)] = block_number
        block_index = memory_map.index(block_number) + 1
        start_addr = block_index * 0x1000
        data_start_addr = radio.BLOCK_ORDER.index(block_number) * 0x1000
        for addr in range(start_addr, start_addr + 0x1000,
                          radio.BLOCK_SIZE):

            # sending the data
            data_addr = data_start_addr + addr - start_addr
            data = radio.get_mmap()[data_addr:data_addr + radio.BLOCK_SIZE]
            frame = radio._make_frame(b"W", addr, radio.BLOCK_SIZE, data)
            baofeng_common._rawsend(radio, frame)

            # receiving the response
            ack = baofeng_common._rawrecv(radio, 1)
            if ack != b"\x06":
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            # UI Update
            status.cur = (data_addr) // radio.BLOCK_SIZE
            status.msg = "Cloning to radio..."
            radio.status_fn(status)


@directory.register
class UV17(baofeng_uv17Pro.UV17Pro):
    """Baofeng UV-17"""
    VENDOR = "Baofeng"
    MODEL = "UV-17"

    download_function = _download
    upload_function = _upload

    MODES = ["FM", "NFM"]
    BLOCK_ORDER = [16, 17, 18, 19,  24, 25, 26, 4, 6]
    MEM_TOTAL = 0x9000
    WRITE_MEM_TOTAL = 0x9000
    BLOCK_SIZE = 0x40
    BAUD_RATE = 57600
    _magic = b"PSEARCH"
    _magics = [(b"PASSSTA", 3),
               (b"SYSINFO", 1),
               (b"\x56\x00\x00\x0A\x0D", 13),
               (b"\x06", 1),
               (b"\x56\x00\x10\x0A\x0D", 13),
               (b"\x06", 1),
               (b"\x56\x00\x20\x0A\x0D", 13),
               (b"\x06", 1)]
    _magic_memsize = [(b"\x56\x00\x00\x00\x0A", 11)]
    _radio_memsize = 0xffff
    _magics2 = [(b"\x06", 1),
                (b"\xFF\xFF\xFF\xFF\x0C\x55\x56\x31\x35\x39\x39\x39", 1),
                (b"\02", 8),
                (b"\x06", 1)]
    _fingerprint = b"\x06" + b"UV15999"
    _scode_offset = 1
    _mem_positions = ()

    _tri_band = False
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("High",  watts=5.00)]

    LENGTH_NAME = 11
    VALID_BANDS = [baofeng_uv17Pro.UV17Pro._vhf_range,
                   baofeng_uv17Pro.UV17Pro._uhf_range]
    SCODE_LIST = ["%s" % x for x in range(1, 16)]
    SQUELCH_LIST = ["Off"] + list("123456789")
    LIST_POWERON_DISPLAY_TYPE = ["Full", "Message", "Voltage"]
    LIST_TIMEOUT = ["Off"] + ["%s sec" % x for x in range(15, 615, 15)]
    LIST_VOICE = ["Chinese", "English"]
    LIST_BACKLIGHT_TIMER = ["Always On"] + ["%s sec" % x for x in range(1, 11)]
    LIST_MODE = ["Name", "Frequency"]
    CHANNELS = 999

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
         lowpower:1,
         unknown:1;
      u8 scode:4,
         unknown3:3,
         scan:1;
      u8 unknown4;
    };
    """
    MEM_DEFS = """
    struct channelname {
      char name[11];
    };
    struct settings {
      u8 powerondistype;
      u8 unknown0[15];
      char boottext1[10];
      u8 unknown1[6];
      char boottext2[10];
      u8 unknown2[22];
      u8 tot;
      u8 squelch;
      u8 vox;
      u8 powersave: 4,
         unknown3:2,
         voice: 1,
         voicesw: 1;
      u8 backlight;
      u8 beep:1,
         autolock:1,
         unknown4:1,
         tail:1,
         scanmode:2,
         dtmfst:2;
      u8 unknown5:1,
         dualstandby:1,
         roger:1,
         unknown6:3,
         fmenable:1,
         unknown7:1;
      u8 unknown8[9];
      u8 unknown9:6,
         chbdistype:1,
         chadistype:1;
    };
    struct ani {
      u8 unknown[5];
      u8 code[5];
    };
    struct pttid {
      u8 code[5];
    };
    """

    MEM_LAYOUT = """
    #seekto 0x0030;
    struct {
      struct channel mem[252];
    } mem1;

    #seek 0x10;
    struct {
      struct channel mem[255];
    } mem2;

    #seek 0x10;
    struct {
      struct channel mem[255];
    } mem3;

    #seek 0x10;
    struct {
      struct channel mem[237];
    } mem4;

    #seekto 0x7000;
    struct settings settings;

    struct vfo {
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
         lowpower:1,
         unknown:1;
      u8 scode:4,
         unknown3:3,
         scan:1;
      u8 unknown4;
    };

    #seekto 0x0010;
    struct {
      struct vfo a;
      struct vfo b;
    } vfo;

    #seekto 0x4000;
    struct channelname names1[372];
    #seek 0x4;
    struct channelname names2[372];
    #seek 0x4;
    struct channelname names3[255];

    #seekto 0x8000;
    struct pttid pttid[15];

    struct ani ani;
    """
    MEM_FORMAT = CHANNEL_DEF + MEM_DEFS + MEM_LAYOUT

    def _make_frame(self, cmd, addr, length, data=""):
        """Pack the info in the header format"""
        frame = struct.pack("<cI", cmd, addr)[:-1] + struct.pack(">B", length)
        # add the data if set
        if len(data) != 0:
            frame += data
        # return the data
        return frame

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        _mem = self._memobj
        basic = RadioSettingGroup("basic", "Basic Settings")
        dtmfe = RadioSettingGroup("dtmfe", "DTMF Encode Settings")
        top = RadioSettings(basic, dtmfe)

        self.get_settings_common_basic(basic, _mem)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        rs = RadioSetting("settings.boottext1", "Power-On Message 1",
                          RadioSettingValueString(
                              0, 10, _filter(self._memobj.settings.boottext1)))
        basic.append(rs)

        rs = RadioSetting("settings.boottext2", "Power-On Message 2",
                          RadioSettingValueString(
                              0, 10, _filter(self._memobj.settings.boottext2)))
        basic.append(rs)

        if _mem.settings.powersave > 0x04:
            val = 0x00
        else:
            val = _mem.settings.powersave
        rs = RadioSetting("settings.powersave", "Battery Saver",
                          RadioSettingValueList(
                              LIST_SAVE, current_index=val))
        basic.append(rs)

        rs = RadioSetting("settings.scanmode", "Scan Mode",
                          RadioSettingValueList(
                              LIST_SCANMODE,
                              current_index=_mem.settings.scanmode))
        basic.append(rs)

        rs = RadioSetting(
            "settings.dtmfst", "DTMF Sidetone",
            RadioSettingValueList(
                LIST_DTMFST, current_index=_mem.settings.dtmfst))
        basic.append(rs)

        rs = RadioSetting("settings.fmenable", "Enable FM radio",
                          RadioSettingValueBoolean(_mem.settings.fmenable))
        basic.append(rs)

        self.get_settings_common_dtmf(dtmfe, _mem)

        return top

    def decode_tone(self, val):
        pol = "N"
        mode = ""
        if val in [0, 0xFFFF]:
            xval = 0
        elif (val & 0x8000) > 0:
            mode = "DTCS"
            xval = (val & 0x0f) + (val >> 4 & 0xf)\
                * 10 + (val >> 8 & 0xf) * 100
            if (val & 0xC000) == 0xC000:
                pol = "R"
        else:
            mode = "Tone"
            xval = int((val & 0x0f) + (val >> 4 & 0xf) * 10 +
                       (val >> 8 & 0xf) * 100 + (val >> 12 & 0xf)
                       * 1000) / 10.0

        return mode, xval, pol

    def _get_raw_memory(self, number):
        # The flash memory contains page_numbers
        # This is probably to do wear leveling on the memory
        # These numbers are needed, but make the channel memory
        # not continuous.
        number = number - 1
        if number >= 762:
            _mem = self._memobj.mem4.mem[number - 762]
            return _mem
        if number >= 507:
            _mem = self._memobj.mem3.mem[number - 507]
            return _mem
        if number >= 252:
            _mem = self._memobj.mem2.mem[number - 252]
            return _mem
        _mem = self._memobj.mem1.mem[number]
        return _mem

    def get_raw_memory(self, number):
        return repr(self._get_raw_memory(number))

    def get_channel_name(self, number):
        number = number - 1
        if number >= 744:
            _name = self._memobj.names3[number - 744]
            return _name
        if number >= 372:
            _name = self._memobj.names2[number - 372]
            return _name
        _name = self._memobj.names1[number]
        return _name

    def get_memory(self, number):
        _mem = self._get_raw_memory(number)
        _nam = self.get_channel_name(number)

        mem = chirp_common.Memory()
        mem.number = number

        self.get_memory_common(_mem, _nam.name, mem)

        return mem

    def encode_tone(self, memtone, mode, tone, pol):
        if mode == "Tone":
            xtone = '%04i' % (tone * 10)
            memtone.set_value((int(xtone[0]) << 12) + (int(xtone[1]) << 8) +
                              (int(xtone[2]) << 4) + int(xtone[3]))
        elif mode == "TSQL":
            xtone = '%04i' % (tone * 10)
            memtone.set_value((int(tone[0]) << 12) + (int(xtone[1]) << 8) +
                              (int(xtone[2]) << 4) + int(xtone[3]))
        elif mode == "DTCS":
            xtone = str(int(tone)).rjust(4, '0')
            memtone.set_value((0x8000 + (int(xtone[0]) << 12) +
                               (int(xtone[1]) << 8) + (int(xtone[2]) << 4) +
                               int(xtone[3])))
        else:
            memtone.set_value(0)

        if mode == "DTCS" and pol == "R":
            memtone.set_value(memtone + 0x4000)

    def set_memory(self, mem):
        _mem = self._get_raw_memory(mem.number)
        _nam = self.get_channel_name(mem.number)

        if mem.empty:
            _mem.set_raw(b"\xff" * 16)
            return

        _mem.set_raw(b"\x00" * 16)

        _namelength = self.get_features().valid_name_length
        _nam.name = mem.name[:_namelength].ljust(11, '\x00')

        self.set_memory_common(mem, _mem)


@directory.register
class UV13Pro(UV17):
    VENDOR = "Baofeng"
    MODEL = "UV-13Pro"

    _radio_memsize = 0x31fff
