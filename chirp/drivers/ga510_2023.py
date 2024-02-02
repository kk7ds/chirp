# Copyright 2024:
# * bsilvereagle, <bsilvereagle@gmail.com>
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
from chirp.drivers import baofeng_common, baofeng_uv17, baofeng_uv17Pro
from chirp import errors, util

LOG = logging.getLogger(__name__)
LIST_DTMFST = ["Off", "DT-ST", "ANI-ST", "DT+ANI"]
LIST_SAVE = ["Off", "1:1", "1:2", "1:3", "1:4"]
LIST_SCANMODE = ["Time", "Carrier", "Search"]


_mem_format = """

    #seekto 0x1000;
    struct {
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
    } settings;

    #seekto 0x2000;
    struct {
      u8 code[5];
    } pttid[15];

    struct {
      u8 unknown[5];
      u8 code[5];
    } ani;

    struct vfo {
      u8 freq[8];
      u8 unused1;
      ul16 rxtone;
      ul16 txtone;
      u8 unknown1:1,
         busy:1,
         pttid:2,
         unknown2:1,
         wide:1,
         lowpower:2;
      u8 scode:4,
         unknown6:2,
         freq_hop:1,
         scan:1;
      u8 unknown4;
    };

    #seekto 0x4010;
    struct {
      struct vfo a;
      struct vfo b;
    } vfo;

    #seekto 0x4020;
    struct {
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
         unknown6:2,
         freq_hop:1,
         scan:1;
      u8 unknown4;
    } memories[129];

    #seekto 0x5000;
    struct {
      char name[11];
    } names[129];
"""


@directory.register
class RadioddityGA5102023(baofeng_uv17.UV17):
    """Baofeng UV-17"""
    VENDOR = "Radioddity"
    MODEL = "GA-510 (2023)"
    NEEDS_COMPAT_SERIAL = False

    MODES = ["FM", "NFM"]
    MEM_TOTAL = 0x6000
    WRITE_MEM_TOTAL = 0x6000
    BLOCK_SIZE = 0x40
    BAUD_RATE = 57600

    _magic = b"PSEARCH"
    _magic_response_length = 8
    _magics = [[b"PASSSTA", 3], [b"SYSINFO", 1],
               [b"\x56\x00\x00\x0A\x0D", 13], [b"\x06", 1],
               [b"\x56\x00\x10\x0A\x0D", 13], [b"\x06", 1],
               [b"\x56\x00\x20\x0A\x0D", 13], [b"\x06", 1],
               [b"\x56\x00\x00\x00\x0A", 11], [b"\x06", 1],
               [b"\xFF\xFF\xFF\xFF\x0C\x44\x4d\x52\x31\x37\x30\x32", 1],
               [b"\02", 8], [b"\x06", 1]]

    _fingerprint = b"\x06" + b"DMR1702"
    _scode_offset = 1

    _tri_band = False
    _has_workmode_support = False

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("Medium", watts=5.00),
                    chirp_common.PowerLevel("High",  watts=10.00)]

    LENGTH_NAME = 11
    SCODE_LIST = ["%s" % x for x in range(1, 16)]
    SQUELCH_LIST = ["Off"] + list("123456789")
    LIST_POWERON_DISPLAY_TYPE = ["Full", "Message", "Voltage"]
    LIST_TIMEOUT = ["Off"] + ["%s sec" % x for x in range(15, 615, 15)]
    LIST_VOICE = ["Chinese", "English"]
    LIST_BACKLIGHT_TIMER = ["Always On"] + ["%s sec" % x for x in range(1, 11)]
    LIST_MODE = ["Name", "Frequency"]
    CHANNELS = 128

    MEM_FORMAT = _mem_format

    def _get_memory_map(self):
        """
        Get the mapping for where various blocks are stored in the radio memory.

        Presumably for wear leveling the vendor CPS saves various settings in different
        locations on every write. 0xXFFF contains a value explaining what the last 0x1000
        block of memory contains. 

        0x02 - Unknown
        0x04 - Settings
        0x06 - DTMF
        0x10 - Channel Settings
        0x16 - Channel Names
        0x24 - Unknown but similar to channel names

        We will read each 0xXFFF value and store it in a dictionary which will then be read
        *inorder* via download. So the memory addresses in the memory map are the order in the dict
        multiplied by 0x1000. 
        """
        memory_map = {
            0x02: None,
            0x04: None,
            0x06: None,
            0x10: None,
            0x16: None,
            0x24: None
        }

        for addr in range(0x0000, 0x10000, 0x1000):
            frame = self._make_frame(b"R", addr + 0xFFF, 1)
            baofeng_common._rawsend(self, frame)
            blocknr = ord(baofeng_common._rawrecv(self, 6)[5:])
            LOG.debug(f"Block{blocknr}\t{hex(blocknr)}")
            if blocknr in memory_map:
                LOG.debug("Known Memory Map: %x, %x" % (addr, blocknr))
                memory_map[blocknr] = addr
            else:
                LOG.debug("Unknown Memory Map: %x, %x" % (addr, blocknr))
            self._sendmagic(b"\x06", 1)
        LOG.debug(memory_map)
        return memory_map

    def _sendmagic(self, magic, response_len):
        baofeng_common._rawsend(self, magic)
        baofeng_common._rawrecv(self, response_len)

    def _start_communication(self, magics):
        for magic in magics:
            self._sendmagic(magic[0], magic[1])

    def download_all(self):
        """Download the entire memory."""
        baofeng_uv17Pro._do_ident(self)

        data = b""

        status = chirp_common.Status()
        status.cur = 0
        status.max = 0xF*0x1000 // self.BLOCK_SIZE
        status.msg = "Cloning from radio..."
        self.status_fn(status)

        for addr in range(0x0000, 0x10000, self.BLOCK_SIZE):
            frame = self._make_read_frame(addr, self.BLOCK_SIZE)
            # DEBUG
            # LOG.debug("Frame=" + util.hexprint(frame))

            baofeng_common._rawsend(self, frame)

            d = baofeng_common._rawrecv(self, self.BLOCK_SIZE + 5)

            # LOG.debug("Response Data= " + util.hexprint(d))

            data += d[5:]

            status.cur = len(data) // self.BLOCK_SIZE
            status.msg = "Cloning from radio..."
            self.status_fn(status)

            self._sendmagic(b"\x06", 1)
        data += bytes(self.MODEL, 'ascii')
        return data

    def download_map(self):
        """Download only data marked as good."""
        baofeng_uv17Pro._do_ident(self)

        data = b""

        memory_map = self._get_memory_map()

        status = chirp_common.Status()
        status.cur = 0
        status.max = self.MEM_TOTAL // self.BLOCK_SIZE
        status.msg = "Cloning from radio..."
        self.status_fn(status)

        # Iterate through the memory map reading 0x1000 bytes at a time
        # The dict is in a fixed order so the memory_map maps directly to
        # MEM_FORMAT
        LOG.debug(memory_map)
        for key, start_addr in memory_map.items():
            if not start_addr:
                LOG.debug(f"Error processing {key}:{start_addr}")
                continue
            for addr in range(start_addr, start_addr + 0x1000,
                              self.BLOCK_SIZE):
                frame = self._make_read_frame(addr, self.BLOCK_SIZE)
                # LOG.debug("Frame=" + util.hexprint(frame))

                baofeng_common._rawsend(self, frame)

                d = baofeng_common._rawrecv(self, self.BLOCK_SIZE + 5)

                data += d[5:]

                status.cur = len(data) // self.BLOCK_SIZE
                status.msg = "Cloning from radio..."
                self.status_fn(status)

                self._sendmagic(b"\x06", 1)
        data += bytes(self.MODEL, 'ascii')
        return data

    def download_function(self):
        return self.download_map()

    def upload_function(self):
        """Upload procedure"""
        radio = self
        baofeng_uv17Pro._do_ident(radio)

        memory_map = self._get_memory_map()

        LOG.debug(memory_map)

        status = chirp_common.Status()
        status.cur = 0
        status.max = radio.WRITE_MEM_TOTAL // radio.BLOCK_SIZE
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

        for addr in range(0x0000, 0x10000, 0x1000):
            # Zero out all of the information fields
            frame = self._make_frame(b"W", addr + 0xFFF, 0x01, b"\xFF")
            baofeng_common._rawsend(radio, frame)
            # receiving the response
            ack = baofeng_common._rawrecv(radio, 1)
            if ack != b"\x06":
                LOG.debug(frame)
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

        i = 0
        for key, start_addr in memory_map.items():
            # Iterate through the memory map writing 0x1000 bytes at a time
            if not start_addr:
                LOG.debug(f"Error processing {key}:{start_addr}")
                continue
            for addr in range(0x000, 0x0FFF, radio.BLOCK_SIZE):
                # Find the offset data in the CHIRP memory map
                data_addr = 0x1000*i + addr
                data = radio.get_mmap()[
                    data_addr:data_addr + radio.BLOCK_SIZE]
                frame = radio._make_frame(
                    b"W", start_addr+addr, radio.BLOCK_SIZE, data)
                # LOG.debug(
                #    f"addr: {addr}\tdata: {data_addr}\tradio: {start_addr+addr}")
                baofeng_common._rawsend(radio, frame)

                # receiving the response
                ack = baofeng_common._rawrecv(radio, 1)
                if ack != b"\x06":
                    LOG.debug(frame)
                    msg = "Bad ack writing block 0x%04x" % addr
                    raise errors.RadioError(msg)

                # UI Update
                status.cur = (data_addr) // radio.BLOCK_SIZE
                status.msg = "Cloning to radio..."
                radio.status_fn(status)
            # Write the key describing the data into 0x0FFF
            frame = radio._make_frame(
                b"W", start_addr+0x0FFF, 0x01, key.to_bytes(1))
            baofeng_common._rawsend(radio, frame)
            # receiving the response
            ack = baofeng_common._rawrecv(radio, 1)
            if ack != b"\x06":
                LOG.debug(frame)
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            i = i+1

    def get_raw_memory(self, num):
        mem = self._memobj.memories[num]
        # LOG.debug("RAW %i: %s" % (num, mem))
        # breakpoint()
        return mem

    def set_memory(self, mem):
        _mem = self.get_raw_memory(mem.number)
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            _mem.set_raw(b"\xff" * 16)
            return

        _mem.set_raw(b"\x00" * 16)

        _namelength = self.get_features().valid_name_length
        _nam.name = mem.name.ljust(_namelength, '\x00')

        self.set_memory_common(mem, _mem)

    def get_settings(self):
        settings = super().get_settings()

        # The UV17Pro has very similar VFO settings but not quite
        # similar enough for this to "just work".
        # super().get_settings_common_workmode(settings, self._memobj)

        return settings
