# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import struct
import re
import time
import logging

from chirp import chirp_common, errors, util, memmap
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueBoolean, RadioSettings

LOG = logging.getLogger(__name__)

CMD_CLONE_OUT = 0xE2
CMD_CLONE_IN = 0xE3
CMD_CLONE_DAT = 0xE4
CMD_CLONE_END = 0xE5

SAVE_PIPE = None


class IcfFrame:
    """A single ICF communication frame"""
    src = 0
    dst = 0
    cmd = 0

    payload = ""

    def __str__(self):
        addrs = {0xEE: "PC",
                 0xEF: "Radio"}
        cmds = {0xE0: "ID",
                0xE1: "Model",
                0xE2: "Clone out",
                0xE3: "Clone in",
                0xE4: "Clone data",
                0xE5: "Clone end",
                0xE6: "Clone result"}

        return "%s -> %s [%s]:\n%s" % (addrs[self.src], addrs[self.dst],
                                       cmds[self.cmd],
                                       util.hexprint(self.payload))

    def __init__(self):
        pass


def parse_frame_generic(data):
    """Parse an ICF frame of unknown type from the beginning of @data"""
    frame = IcfFrame()

    frame.src = ord(data[2])
    frame.dst = ord(data[3])
    frame.cmd = ord(data[4])

    try:
        end = data.index("\xFD")
    except ValueError:
        return None, data

    frame.payload = data[5:end]

    return frame, data[end+1:]


class RadioStream:
    """A class to make reading a stream of IcfFrames easier"""
    def __init__(self, pipe):
        self.pipe = pipe
        self.data = ""

    def _process_frames(self):
        if not self.data.startswith("\xFE\xFE"):
            LOG.error("Out of sync with radio:\n%s" % util.hexprint(self.data))
            raise errors.InvalidDataError("Out of sync with radio")
        elif len(self.data) < 5:
            return []  # Not enough data for a full frame

        frames = []

        while self.data:
            try:
                cmd = ord(self.data[4])
            except IndexError:
                break  # Out of data

            try:
                frame, rest = parse_frame_generic(self.data)
                if not frame:
                    break
                elif frame.src == 0xEE and frame.dst == 0xEF:
                    # PC echo, ignore
                    pass
                else:
                    frames.append(frame)

                self.data = rest
            except errors.InvalidDataError, e:
                LOG.error("Failed to parse frame (cmd=%i): %s" % (cmd, e))
                return []

        return frames

    def get_frames(self, nolimit=False):
        """Read any pending frames from the stream"""
        while True:
            _data = self.pipe.read(64)
            if not _data:
                break
            else:
                self.data += _data

            if not nolimit and len(self.data) > 128 and "\xFD" in self.data:
                break  # Give us a chance to do some status
            if len(self.data) > 1024:
                break  # Avoid an endless loop of chewing garbage

        if not self.data:
            return []

        return self._process_frames()


def get_model_data(radio, mdata="\x00\x00\x00\x00"):
    """Query the @radio for its model data"""
    send_clone_frame(radio, 0xe0, mdata, raw=True)

    stream = RadioStream(radio.pipe)
    frames = stream.get_frames()

    if len(frames) != 1:
        raise errors.RadioError("Unexpected response from radio")

    return frames[0].payload


def get_clone_resp(pipe, length=None, max_count=None):
    """Read the response to a clone frame"""
    def exit_criteria(buf, length, cnt, max_count):
        """Stop reading a clone response if we have enough data or encounter
        the end of a frame"""
        if max_count is not None:
            if cnt >= max_count:
                return True
        if length is None:
            return buf.endswith("\xfd")
        else:
            return len(buf) == length

    resp = ""
    cnt = 0
    while not exit_criteria(resp, length, cnt, max_count):
        resp += pipe.read(1)
        cnt += 1
    return resp


def send_clone_frame(radio, cmd, data, raw=False, checksum=False):
    """Send a clone frame with @cmd and @data to the @radio"""
    payload = radio.get_payload(data, raw, checksum)

    frame = "\xfe\xfe\xee\xef%s%s\xfd" % (chr(cmd), payload)

    if SAVE_PIPE:
        LOG.debug("Saving data...")
        SAVE_PIPE.write(frame)

    # LOG.debug("Sending:\n%s" % util.hexprint(frame))
    # LOG.debug("Sending:\n%s" % util.hexprint(hed[6:]))
    if cmd == 0xe4:
        # Uncomment to avoid cloning to the radio
        # return frame
        pass

    radio.pipe.write(frame)
    if radio.MUNCH_CLONE_RESP:
        # Do max 2*len(frame) read(1) calls
        get_clone_resp(radio.pipe, max_count=2*len(frame))

    return frame


def process_data_frame(radio, frame, _mmap):
    """Process a data frame, adding the payload to @_mmap"""
    _data = radio.process_frame_payload(frame.payload)
    # Checksum logic added by Rick DeWitt, 9/2019, issue # 7075
    if len(_mmap) >= 0x10000:   # This map size not tested for checksum
        saddr, = struct.unpack(">I", _data[0:4])
        length, = struct.unpack("B", _data[4])
        data = _data[5:5+length]
        sumc, = struct.unpack("B", _data[5+length])
        addr1, = struct.unpack("B", _data[0])
        addr2, = struct.unpack("B", _data[1])
        addr3, = struct.unpack("B", _data[2])
        addr4, = struct.unpack("B", _data[3])
    else:   # But this one has been tested for raw mode radio (IC-2730)
        saddr, = struct.unpack(">H", _data[0:2])
        length, = struct.unpack("B", _data[2])
        data = _data[3:3+length]
        sumc, = struct.unpack("B", _data[3+length])
        addr1, = struct.unpack("B", _data[0])
        addr2, = struct.unpack("B", _data[1])
        addr3 = 0
        addr4 = 0

    cs = addr1 + addr2 + addr3 + addr4 + length
    for byte in data:
        cs += ord(byte)
    vx = ((cs ^ 0xFFFF) + 1) & 0xFF
    if sumc != vx:
        LOG.error("Bad checksum in address %04X frame: %02x "
                  "calculated, %02x sent!" % (saddr, vx, sumc))
        raise errors.InvalidDataError(
            "Checksum error in download! "
            "Try disabling High Speed Clone option in Settings.")
    try:
        _mmap[saddr] = data
    except IndexError:
        LOG.error("Error trying to set %i bytes at %05x (max %05x)" %
                  (bytes, saddr, len(_mmap)))
    return saddr, saddr + length


def start_hispeed_clone(radio, cmd):
    """Send the magic incantation to the radio to go fast"""
    buf = ("\xFE" * 20) + \
        "\xEE\xEF\xE8" + \
        radio.get_model() + \
        "\x00\x00\x02\x01\xFD"
    LOG.debug("Starting HiSpeed:\n%s" % util.hexprint(buf))
    radio.pipe.write(buf)
    radio.pipe.flush()
    resp = radio.pipe.read(128)
    LOG.debug("Response:\n%s" % util.hexprint(resp))

    LOG.info("Switching to 38400 baud")
    radio.pipe.baudrate = 38400

    buf = ("\xFE" * 14) + \
        "\xEE\xEF" + \
        chr(cmd) + \
        radio.get_model()[:3] + \
        "\x00\xFD"
    LOG.debug("Starting HiSpeed Clone:\n%s" % util.hexprint(buf))
    radio.pipe.write(buf)
    radio.pipe.flush()


def _clone_from_radio(radio):
    md = get_model_data(radio)

    if md[0:4] != radio.get_model():
        LOG.info("This model: %s" % util.hexprint(md[0:4]))
        LOG.info("Supp model: %s" % util.hexprint(radio.get_model()))
        raise errors.RadioError("I can't talk to this model")

    if radio.is_hispeed():
        start_hispeed_clone(radio, CMD_CLONE_OUT)
    else:
        send_clone_frame(radio, CMD_CLONE_OUT, radio.get_model(), raw=True)

    LOG.debug("Sent clone frame")

    stream = RadioStream(radio.pipe)

    addr = 0
    _mmap = memmap.MemoryMap(chr(0x00) * radio.get_memsize())
    last_size = 0
    while True:
        frames = stream.get_frames()
        if not frames:
            break

        for frame in frames:
            if frame.cmd == CMD_CLONE_DAT:
                src, dst = process_data_frame(radio, frame, _mmap)
                if last_size != (dst - src):
                    LOG.debug("ICF Size change from %i to %i at %04x" %
                              (last_size, dst - src, src))
                    last_size = dst - src
                if addr != src:
                    LOG.debug("ICF GAP %04x - %04x" % (addr, src))
                addr = dst
            elif frame.cmd == CMD_CLONE_END:
                LOG.debug("End frame (%i):\n%s" %
                          (len(frame.payload), util.hexprint(frame.payload)))
                LOG.debug("Last addr: %04x" % addr)

        if radio.status_fn:
            status = chirp_common.Status()
            status.msg = "Cloning from radio"
            status.max = radio.get_memsize()
            status.cur = addr
            radio.status_fn(status)

    return _mmap


def clone_from_radio(radio):
    """Do a full clone out of the radio's memory"""
    try:
        return _clone_from_radio(radio)
    except Exception, e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


def send_mem_chunk(radio, start, stop, bs=32):
    """Send a single chunk of the radio's memory from @start-@stop"""
    _mmap = radio.get_mmap()

    status = chirp_common.Status()
    status.msg = "Cloning to radio"
    status.max = radio.get_memsize()

    for i in range(start, stop, bs):
        if i + bs < stop:
            size = bs
        else:
            size = stop - i

        if radio.get_memsize() >= 0x10000:
            chunk = struct.pack(">IB", i, size)
        else:
            chunk = struct.pack(">HB", i, size)
        chunk += _mmap[i:i+size]

        send_clone_frame(radio,
                         CMD_CLONE_DAT,
                         chunk,
                         raw=False,
                         checksum=True)

        if radio.status_fn:
            status.cur = i+bs
            radio.status_fn(status)

    return True


def _clone_to_radio(radio):
    global SAVE_PIPE

    # Uncomment to save out a capture of what we actually write to the radio
    # SAVE_PIPE = file("pipe_capture.log", "w", 0)

    md = get_model_data(radio)

    if md[0:4] != radio.get_model():
        raise errors.RadioError("I can't talk to this model")

    # This mimics what the Icom software does, but isn't required and just
    # takes longer
    # md = get_model_data(radio, mdata=md[0:2]+"\x00\x00")
    # md = get_model_data(radio, mdata=md[0:2]+"\x00\x00")

    stream = RadioStream(radio.pipe)

    if radio.is_hispeed():
        start_hispeed_clone(radio, CMD_CLONE_IN)
    else:
        send_clone_frame(radio, CMD_CLONE_IN, radio.get_model(), raw=True)

    frames = []

    for start, stop, bs in radio.get_ranges():
        if not send_mem_chunk(radio, start, stop, bs):
            break
        frames += stream.get_frames()

    send_clone_frame(radio, CMD_CLONE_END, radio.get_endframe(), raw=True)

    if SAVE_PIPE:
        SAVE_PIPE.close()
        SAVE_PIPE = None

    for i in range(0, 10):
        try:
            frames += stream.get_frames(True)
            result = frames[-1]
        except IndexError:
            LOG.debug("Waiting for clone result...")
            time.sleep(0.5)

    if len(frames) == 0:
        raise errors.RadioError("Did not get clone result from radio")

    return result.payload[0] == '\x00'


def clone_to_radio(radio):
    """Initiate a full memory clone out to @radio"""
    try:
        return _clone_to_radio(radio)
    except Exception, e:
        logging.exception("Failed to communicate with the radio")
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


def convert_model(mod_str):
    """Convert an ICF-style model string into what we get from the radio"""
    data = ""
    for i in range(0, len(mod_str), 2):
        hexval = mod_str[i:i+2]
        intval = int(hexval, 16)
        data += chr(intval)

    return data


def convert_data_line(line):
    """Convert an ICF data line to raw memory format"""
    if line.startswith("#"):
        return ""

    line = line.strip()

    # Detection of the prefix length. The code assumes that the data line
    # length (without the prefix) is multiply of 8 characters (i.e. multiply
    # of 4 bytes), so the rest (remainder of division by 8) has to be the
    # prefix (prefix = address + length) - for small memory the address is
    # 2 bytes long and the length indicator is 1 byte long which means 3 bytes
    # in total which is 6 characters in total for the prefix on the ICF line.
    if len(line) % 8 == 6:
        # Small memory (< 0x10000)
        size = int(line[4:6], 16)
        data = line[6:]
    else:
        # Large memory (>= 0x10000)
        size = int(line[8:10], 16)
        data = line[10:]

    _mmap = ""
    i = 0
    while i < (size * 2):
        try:
            val = int("%s%s" % (data[i], data[i+1]), 16)
            i += 2
            _mmap += struct.pack("B", val)
        except ValueError, e:
            LOG.debug("Failed to parse byte: %s" % e)
            break

    return _mmap


def read_file(filename):
    """Read an ICF file and return the model string and memory data"""
    f = file(filename)

    mod_str = f.readline()
    dat = f.readlines()

    model = convert_model(mod_str.strip())

    _mmap = ""
    for line in dat:
        if not line.startswith("#"):
            _mmap += convert_data_line(line)

    return model, memmap.MemoryMap(_mmap)


def is_9x_icf(filename):
    """Returns True if @filename is an IC9x ICF file"""
    f = file(filename)
    mdata = f.read(8)
    f.close()

    return mdata in ["30660000", "28880000"]


def is_icf_file(filename):
    """Returns True if @filename is an ICF file"""
    f = file(filename)
    data = f.readline()
    data += f.readline()
    f.close()

    data = data.replace("\n", "").replace("\r", "")

    return bool(re.match("^[0-9]{8}#", data))


class IcomBank(chirp_common.Bank):
    """A bank that works for all Icom radios"""
    # Integral index of the bank (not to be confused with per-memory
    # bank indexes
    index = 0


class IcomNamedBank(IcomBank):
    """A bank with an adjustable name"""
    def set_name(self, name):
        """Set the name of the bank"""
        pass


class IcomBankModel(chirp_common.BankModel):
    """Icom radios all have pretty much the same simple bank model. This
    central implementation can, with a few icom-specific radio interfaces
    serve most/all of them"""

    def get_num_mappings(self):
        return self._radio._num_banks

    def get_mappings(self):
        banks = []

        for i in range(0, self._radio._num_banks):
            index = chr(ord("A") + i)
            bank = self._radio._bank_class(self, index, "BANK-%s" % index)
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_mapping(self, memory, bank):
        self._radio._set_bank(memory.number, bank.index)

    def remove_memory_from_mapping(self, memory, bank):
        if self._radio._get_bank(memory.number) != bank.index:
            raise Exception("Memory %i not in bank %s. Cannot remove." %
                            (memory.number, bank))

        self._radio._set_bank(memory.number, None)

    def get_mapping_memories(self, bank):
        memories = []
        for i in range(*self._radio.get_features().memory_bounds):
            if self._radio._get_bank(i) == bank.index:
                memories.append(self._radio.get_memory(i))
        return memories

    def get_memory_mappings(self, memory):
        index = self._radio._get_bank(memory.number)
        if index is None:
            return []
        else:
            return [self.get_mappings()[index]]


class IcomIndexedBankModel(IcomBankModel,
                           chirp_common.MappingModelIndexInterface):
    """Generic bank model for Icom radios with indexed banks"""
    def get_index_bounds(self):
        return self._radio._bank_index_bounds

    def get_memory_index(self, memory, bank):
        return self._radio._get_bank_index(memory.number)

    def set_memory_index(self, memory, bank, index):
        if bank not in self.get_memory_mappings(memory):
            raise Exception("Memory %i is not in bank %s" % (memory.number,
                                                             bank))

        if index not in range(*self._radio._bank_index_bounds):
            raise Exception("Invalid index")
        self._radio._set_bank_index(memory.number, index)

    def get_next_mapping_index(self, bank):
        indexes = []
        for i in range(*self._radio.get_features().memory_bounds):
            if self._radio._get_bank(i) == bank.index:
                indexes.append(self._radio._get_bank_index(i))

        for i in range(0, 256):
            if i not in indexes:
                return i

        raise errors.RadioError("Out of slots in this bank")


def compute_checksum(data):
    cs = 0
    for byte in data:
        cs += ord(byte)
    return ((cs ^ 0xFFFF) + 1) & 0xFF


class IcomCloneModeRadio(chirp_common.CloneModeRadio):
    """Base class for Icom clone-mode radios"""
    VENDOR = "Icom"
    BAUDRATE = 9600
    # Ideally, the driver should read clone response after each clone frame
    # is sent, but for some reason it hasn't behaved this way for years.
    # So not to break the existing tested drivers the MUNCH_CLONE_RESP flag
    # was added. It's False by default which brings the old behavior,
    # i.e. clone response is not read. The expectation is that new Icom
    # drivers will use MUNCH_CLONE_RESP = True and old drivers will be
    # gradually migrated to this. Once all Icom drivers will use
    # MUNCH_CLONE_RESP = True, this flag will be removed.
    MUNCH_CLONE_RESP = False

    _model = "\x00\x00\x00\x00"  # 4-byte model string
    _endframe = ""               # Model-unique ending frame
    _ranges = []                 # Ranges of the mmap to send to the radio
    _num_banks = 10              # Most simple Icoms have 10 banks, A-J
    _bank_index_bounds = (0, 99)
    _bank_class = IcomBank
    _can_hispeed = False

    @classmethod
    def is_hispeed(cls):
        """Returns True if the radio supports hispeed cloning"""
        return cls._can_hispeed

    @classmethod
    def get_model(cls):
        """Returns the Icom model data for this radio"""
        return cls._model

    @classmethod
    def get_endframe(cls):
        """Returns the magic clone end frame for this radio"""
        return cls._endframe

    @classmethod
    def get_ranges(cls):
        """Returns the ranges this radio likes to have in a clone"""
        return cls._ranges

    def process_frame_payload(self, payload):
        """Convert BCD-encoded data to raw"""
        bcddata = payload
        data = ""
        i = 0
        while i+1 < len(bcddata):
            try:
                val = int("%s%s" % (bcddata[i], bcddata[i+1]), 16)
                i += 2
                data += struct.pack("B", val)
            except ValueError, e:
                LOG.error("Failed to parse byte: %s" % e)
                break

        return data

    def get_payload(self, data, raw, checksum):
        """Returns the data with optional checksum BCD-encoded for the radio"""
        if raw:
            return data
        payload = ""
        for byte in data:
            payload += "%02X" % ord(byte)
        if checksum:
            payload += "%02X" % compute_checksum(data)
        return payload

    def sync_in(self):
        self._mmap = clone_from_radio(self)
        self.process_mmap()

    def sync_out(self):
        clone_to_radio(self)

    def get_bank_model(self):
        rf = self.get_features()
        if rf.has_bank:
            if rf.has_bank_index:
                return IcomIndexedBankModel(self)
            else:
                return IcomBankModel(self)
        else:
            return None

    # Icom-specific bank routines
    def _get_bank(self, loc):
        """Get the integral bank index of memory @loc, or None"""
        raise Exception("Not implemented")

    def _set_bank(self, loc, index):
        """Set the integral bank index of memory @loc to @index, or
        no bank if None"""
        raise Exception("Not implemented")

    def get_settings(self):
        return make_speed_switch_setting(self)

    def set_settings(self, settings):
        return honor_speed_switch_setting(self, settings)


def flip_high_order_bit(data):
    return [chr(ord(d) ^ 0x80) for d in list(data)]


def escape_raw_byte(byte):
    """Escapes a raw byte for sending to the radio"""
    # Certain bytes are used as control characters to the radio, so if one of
    # these bytes is present in the stream to the radio, it gets escaped as
    # 0xff followed by (byte & 0x0f)
    if ord(byte) > 0xf9:
        return "\xff%s" % (chr(ord(byte) & 0xf))
    return byte


def unescape_raw_bytes(escaped_data):
    """Unescapes raw bytes from the radio."""
    data = ""
    i = 0
    while i < len(escaped_data):
        byte = escaped_data[i]
        if byte == '\xff':
            if i + 1 >= len(escaped_data):
                raise errors.InvalidDataError(
                    "Unexpected escape character at end of data")
            i += 1
            byte = chr(0xf0 | ord(escaped_data[i]))
        data += byte
        i += 1
    return data


class IcomRawCloneModeRadio(IcomCloneModeRadio):
    """Subclass for Icom clone-mode radios using the raw data protocol."""

    def process_frame_payload(self, payload):
        """Payloads from a raw-clone-mode radio are already in raw format."""
        return unescape_raw_bytes(payload)

    def get_payload(self, data, raw, checksum):
        """Returns the data with optional checksum in raw format."""
        if checksum:
            cs = chr(compute_checksum(data))
        else:
            cs = ""
        payload = "%s%s" % (data, cs)
        # Escape control characters.
        escaped_payload = [escape_raw_byte(b) for b in payload]
        return "".join(escaped_payload)

    def sync_in(self):
        # The radio returns all the bytes with the high-order bit flipped.
        _mmap = clone_from_radio(self)
        _mmap = flip_high_order_bit(_mmap.get_packed())
        self._mmap = memmap.MemoryMap(_mmap)
        self.process_mmap()

    def get_mmap(self):
        _data = flip_high_order_bit(self._mmap.get_packed())
        return memmap.MemoryMap(_data)


class IcomLiveRadio(chirp_common.LiveRadio):
    """Base class for an Icom Live-mode radio"""
    VENDOR = "Icom"
    BAUD_RATE = 38400

    _num_banks = 26              # Most live Icoms have 26 banks, A-Z
    _bank_index_bounds = (0, 99)
    _bank_class = IcomBank

    def get_bank_model(self):
        rf = self.get_features()
        if rf.has_bank:
            if rf.has_bank_index:
                return IcomIndexedBankModel(self)
            else:
                return IcomBankModel(self)
        else:
            return None


def make_speed_switch_setting(radio):
    if not radio.__class__._can_hispeed:
        return {}
    drvopts = RadioSettingGroup("drvopts", "Driver Options")
    top = RadioSettings(drvopts)
    rs = RadioSetting("drv_clone_speed", "Use Hi-Speed Clone",
                      RadioSettingValueBoolean(radio._can_hispeed))
    drvopts.append(rs)
    return top


def honor_speed_switch_setting(radio, settings):
    for element in settings:
        if element.get_name() == "drvopts":
            return honor_speed_switch_setting(radio, element)
        if element.get_name() == "drv_clone_speed":
            radio.__class__._can_hispeed = element.value.get_value()
            return
