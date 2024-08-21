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

import binascii
import hashlib
import os
import struct
import re
import time
import logging

from chirp import chirp_common, errors, util, memmap
from chirp import directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)

CMD_CLONE_ID = 0xE0
CMD_CLONE_MODEL = 0xE1
CMD_CLONE_OUT = 0xE2
CMD_CLONE_IN = 0xE3
CMD_CLONE_DAT = 0xE4
CMD_CLONE_END = 0xE5
CMD_CLONE_OK = 0xE6
CMD_CLONE_HISPEED = 0xE8

ADDR_PC = 0xEE
ADDR_RADIO = 0xEF

SAVE_PIPE = None
TRACE_ICF = 'CHIRP_DEBUG_ICF' in os.environ


class IcfFrame:
    """A single ICF communication frame"""

    def __str__(self):
        addrs = {ADDR_PC: "PC",
                 ADDR_RADIO: "Radio"}
        cmds = {CMD_CLONE_ID: "ID",
                CMD_CLONE_MODEL: "Model",
                CMD_CLONE_OUT: "Clone out",
                CMD_CLONE_IN: "Clone in",
                CMD_CLONE_DAT: "Clone data",
                CMD_CLONE_END: "Clone end",
                CMD_CLONE_OK: "Clone OK",
                CMD_CLONE_HISPEED: "Clone hispeed"}

        return "%s -> %s [%s]:\n%s" % (addrs.get(self.src, '??'),
                                       addrs.get(self.dst, '??'),
                                       cmds.get(self.cmd, '??'),
                                       util.hexprint(self.payload))

    def __init__(self, src=0, dst=0, cmd=0):
        self.src = src
        self.dst = dst
        self.cmd = cmd
        self.payload = b''

    @classmethod
    def parse(cls, data):
        """Parse an ICF frame of unknown type from the beginning of @data"""
        frame = cls(util.byte_to_int(data[2]),
                    util.byte_to_int(data[3]),
                    util.byte_to_int(data[4]))

        try:
            end = data.index(b"\xFD")
        except ValueError:
            LOG.warning('Frame parsed with no end')
            return None

        assert isinstance(data, bytes), (
            'parse_frame_generic() expected bytes, '
            'but got %s' % data.__class__)

        if data[end + 1:]:
            LOG.warning('Frame parsed with trailing data')

        frame.payload = data[5:end]

        return frame

    def pack(self):
        return (b'\xfe\xfe' +
                struct.pack('BBB', self.src, self.dst, self.cmd) +
                self.payload + b'\xfd')


class RadioStream:
    """A class to make reading a stream of IcfFrames easier"""
    def __init__(self, pipe):
        self.pipe = pipe
        self.data = bytes()
        self.iecho = None

    def _process_frames(self):
        if not self.data.startswith(b"\xFE\xFE"):
            LOG.error("Out of sync with radio:\n%s" % util.hexprint(self.data))
            raise errors.InvalidDataError("Out of sync with radio")
        elif len(self.data) < 5:
            return []  # Not enough data for a full frame

        frames = []

        while self.data:
            # Hispeed clone frames start with a pad of \xFE, so strip those
            # away until we have the two we expect
            while self.data.startswith(b'\xfe\xfe\xfe'):
                self.data = self.data[1:]

            try:
                cmd = self.data[4]
            except IndexError:
                break  # Out of data

            try:
                end = self.data.index(b'\xFD')
                frame = IcfFrame.parse(self.data[:end + 1])
                self.data = self.data[end + 1:]
                if frame.src == 0xEE and frame.dst == 0xEF:
                    # PC echo, ignore
                    if self.iecho is None:
                        LOG.info('Detected an echoing cable')
                        self.iecho = True
                else:
                    if TRACE_ICF:
                        LOG.debug('Received frame:\n%s' % frame)
                    frames.append(frame)
            except ValueError:
                # no data
                break
            except errors.InvalidDataError as e:
                LOG.error("Failed to parse frame (cmd=%i): %s" % (cmd, e))
                return []

        if frames and self.iecho is None:
            LOG.info('Non-echoing cable detected')
            self.iecho = False
        return frames

    def get_frames(self, nolimit=False, limit=None):
        """Read any pending frames from the stream"""
        while True:
            _data = self.pipe.read(1)
            if not _data:
                if limit:
                    LOG.warning('Hit timeout before one frame')
                break
            else:
                self.data += _data

            if limit and 0xFD in self.data:
                break
            if not nolimit and len(self.data) > 128 and 0xFD in self.data:
                break  # Give us a chance to do some status
            if len(self.data) > 1024:
                break  # Avoid an endless loop of chewing garbage

        if not self.data:
            return []

        return self._process_frames()

    def munch_echo(self):
        if self.iecho is not False:
            f = self.get_frames(limit=1)
            if len(f) != 0:
                LOG.warning('Expected to read one echo frame, found %i',
                            len(f))
            if f and f[0].src == 0xEF:
                LOG.warning('Expected PC echo but found radio frame!')


def decode_model(data):
    if len(data) != 49:
        LOG.info('Unable to decode %i-byte model data' % len(data))
        return None
    rev = util.byte_to_int(data[5])
    LOG.info('Radio revision is %i' % rev)
    comment = data[6:6 + 16]
    LOG.info('Radio comment is %r' % comment)
    serial = binascii.unhexlify(data[35:35 + 14])
    model, b1, b2, u1, s3 = struct.unpack('>HBBBH', serial)
    serial_num = '%04i%02i%02i%04i' % (model, b1, b2, s3)
    LOG.info('Radio serial is %r' % serial_num)
    return rev


def get_model_data(radio, mdata=b"\x00\x00\x00\x00", stream=None):
    """Query the @radio for its model data"""
    send_clone_frame(radio, 0xe0, mdata, raw=True)

    if stream is None:
        stream = RadioStream(radio.pipe)
    frames = stream.get_frames()

    if len(frames) != 1:
        raise errors.RadioError("Unexpected response from radio")

    LOG.debug('Model query result:\n%s' % frames[0])

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

    frame = IcfFrame(ADDR_PC, ADDR_RADIO, cmd)
    frame.payload = radio.get_payload(data, raw, checksum)

    if SAVE_PIPE:
        LOG.debug("Saving data...")
        SAVE_PIPE.write(frame.pack())

    if TRACE_ICF:
        LOG.debug('Sending:\n%s' % frame)

    if cmd == 0xe4:
        # Uncomment to avoid cloning to the radio
        # return frame
        pass

    radio.pipe.write(frame.pack())

    return frame


def process_data_frame(radio, frame, _mmap):
    """Process a data frame, adding the payload to @_mmap"""
    _data = radio.process_frame_payload(frame.payload)

    # NOTE: On the _data[N:N+1] below. Because:
    #  - on py2 bytes[N] is a bytes
    #  - on py3 bytes[N] is an int
    #  - on both bytes[N:M] is a bytes
    # So we do a slice so we get consistent behavior
    # Checksum logic added by Rick DeWitt, 9/2019, issue # 7075
    if len(_mmap) >= 0x10000:   # This map size not tested for checksum
        saddr, = struct.unpack(">I", _data[0:4])
        length, = struct.unpack("B", _data[4:5])
        data = _data[5:5+length]
        sumc, = struct.unpack("B", _data[5+length:])
        addr1, = struct.unpack("B", _data[0:1])
        addr2, = struct.unpack("B", _data[1:2])
        addr3, = struct.unpack("B", _data[2:3])
        addr4, = struct.unpack("B", _data[3:4])
    else:   # But this one has been tested for raw mode radio (IC-2730)
        saddr, = struct.unpack(">H", _data[0:2])
        length, = struct.unpack("B", _data[2:3])
        data = _data[3:3+length]
        sumc, = struct.unpack("B", _data[3+length:])
        addr1, = struct.unpack("B", _data[0:1])
        addr2, = struct.unpack("B", _data[1:2])
        addr3 = 0
        addr4 = 0

    cs = addr1 + addr2 + addr3 + addr4 + length
    for byte in data:
        cs += byte
    vx = ((cs ^ 0xFFFF) + 1) & 0xFF
    if sumc != vx:
        LOG.error("Bad checksum in address %04X frame: %02x "
                  "calculated, %02x sent!" % (saddr, vx, sumc))
        raise errors.InvalidDataError(
            "Checksum error in download!")
    try:
        _mmap[saddr] = data
    except IndexError:
        LOG.error("Error trying to set %i bytes at %05x (max %05x)" %
                  (length, saddr, len(_mmap)))
    return saddr, saddr + length


def start_hispeed_clone(radio, cmd):
    """Send the magic incantation to the radio to go fast"""
    frame = IcfFrame(ADDR_PC, ADDR_RADIO, CMD_CLONE_HISPEED)
    frame.payload = radio.get_model() + b'\x00\x00\x02\x01\xFD'

    LOG.debug("Starting HiSpeed:\n%s" % frame)
    radio.pipe.write(b'\xFE' * 20 + frame.pack())
    radio.pipe.flush()
    resp = radio.pipe.read(128)
    LOG.debug("Response:\n%s" % util.hexprint(resp))

    LOG.info("Switching to 38400 baud")
    radio.pipe.baudrate = 38400

    frame = IcfFrame(ADDR_PC, ADDR_RADIO, cmd)
    frame.payload = radio.get_model()[:3] + b'\x00'

    LOG.debug("Starting HiSpeed Clone:\n%s" % frame)
    radio.pipe.write(b'\xFE' * 14 + frame.pack())
    radio.pipe.flush()


def _clone_from_radio(radio):
    md = get_model_data(radio)

    try:
        radio_rev = decode_model(md)
    except Exception:
        LOG.error('Failed to decode model data')
        radio_rev = None

    if md[0:4] != radio.get_model():
        LOG.info("This model: %s" % util.hexprint(md[0:4]))
        LOG.info("Supp model: %s" % util.hexprint(radio.get_model()))
        raise errors.RadioError("I can't talk to this model")

    if radio.is_hispeed():
        start_hispeed_clone(radio, CMD_CLONE_OUT)
    else:
        send_clone_frame(radio, CMD_CLONE_OUT,
                         radio.get_model(),
                         raw=True)

    LOG.debug("Sent clone frame")

    stream = RadioStream(radio.pipe)

    addr = 0
    _mmap = memmap.MemoryMapBytes(bytes(b'\x00') * radio.get_memsize())
    last_size = 0
    got_end = False
    last_frame = time.time()
    timeout = 10
    while not got_end:
        frames = stream.get_frames()
        if not frames and (time.time() - last_frame) > timeout:
            break

        for frame in frames:
            last_frame = time.time()
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
                # For variable-length radios, make sure we don't
                # return a longer map than we got from the radio.
                _mmap.truncate(addr)
                got_end = True

        if radio.status_fn:
            status = chirp_common.Status()
            status.msg = "Cloning from radio"
            status.max = radio.get_memsize()
            status.cur = addr
            radio.status_fn(status)

    if not got_end:
        LOG.error('clone_from_radio ending at address %06X before '
                  'CLONE_END; stream buffer is:\n%s',
                  addr, util.hexprint(stream.data))
        raise errors.RadioError('Data stream stopped before end-of-clone '
                                'received')

    return _mmap


def clone_from_radio(radio):
    """Do a full clone out of the radio's memory"""
    try:
        return _clone_from_radio(radio)
    except Exception as e:
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


def send_mem_chunk(radio, stream, start, stop, bs=32):
    """Send a single chunk of the radio's memory from @start-@stop"""
    _mmap = radio.get_mmap().get_byte_compatible()

    status = chirp_common.Status()
    status.msg = "Cloning to radio"
    status.max = radio.get_memsize()

    LOG.debug('Sending memory range %06x - %06x @ %i bytes' % (
        start, stop, bs))
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

        stream.munch_echo()

        if radio.status_fn:
            status.cur = i+bs
            radio.status_fn(status)

    return True


def _clone_to_radio(radio):
    global SAVE_PIPE

    # Uncomment to save out a capture of what we actually write to the radio
    # SAVE_PIPE = file("pipe_capture.log", "w", 0)

    stream = RadioStream(radio.pipe)
    md = get_model_data(radio, stream=stream)
    if radio._double_ident:
        md = get_model_data(radio, stream=stream)

    if md[0:4] != radio.get_model():
        raise errors.RadioError("I can't talk to this model")

    try:
        radio_rev = decode_model(md)
    except Exception:
        LOG.error('Failed to decode model data')
        radio_rev = None

    image_rev = radio._icf_data.get('MapRev', 1)
    if radio_rev is not None and radio_rev != image_rev:
        raise errors.RadioError('Radio revision %i does not match image %i' % (
            radio_rev, image_rev))

    # This mimics what the Icom software does, but isn't required and just
    # takes longer
    # md = get_model_data(radio, mdata=md[0:2]+"\x00\x00")
    # md = get_model_data(radio, mdata=md[0:2]+"\x00\x00")

    if radio.is_hispeed():
        start_hispeed_clone(radio, CMD_CLONE_IN)
    else:
        send_clone_frame(radio, CMD_CLONE_IN,
                         radio.get_model(),
                         raw=True)

    frames = []

    for start, stop, bs in radio.get_ranges():
        if not send_mem_chunk(radio, stream, start, stop, bs):
            break

    send_clone_frame(radio, CMD_CLONE_END,
                     radio.get_endframe(),
                     raw=True)

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
    elif result.cmd != CMD_CLONE_OK:
        LOG.error('Clone failed result frame:\n%s' % result)
        raise errors.RadioError('Radio rejected clone')
    else:
        LOG.debug('Clone result frame:\n%s' % result)

    return result.payload[0] == bytes(b'\x00')


def clone_to_radio(radio):
    """Initiate a full memory clone out to @radio"""
    try:
        return _clone_to_radio(radio)
    except Exception as e:
        logging.exception("Failed to communicate with the radio")
        raise errors.RadioError("Failed to communicate with the radio: %s" % e)


def convert_model(mod_str):
    """Convert an ICF-style model string into what we get from the radio"""
    data = b""
    for i in range(0, len(mod_str), 2):
        hexval = mod_str[i:i+2]
        intval = int(hexval, 16)
        data += bytes([intval])

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

    _mmap = b""
    i = 0
    while i < (size * 2):
        try:
            val = int("%s%s" % (data[i], data[i+1]), 16)
            i += 2
            _mmap += struct.pack("B", val)
        except ValueError as e:
            LOG.debug("Failed to parse byte: %s" % e)
            break

    return _mmap


def read_file(filename):
    """Read an ICF file and return the model string and memory data"""
    f = open(filename)

    mod_str = f.readline()
    dat = f.readlines()

    icfdata = {
        'model': convert_model(mod_str.strip())
    }

    _mmap = b""
    for line in dat:
        if line.startswith("#"):
            try:
                key, value = line.strip().split('=', 1)
                if key == '#EtcData':
                    value = int(value, 16)
                elif value.isdigit():
                    value = int(value)
                icfdata[key[1:]] = value
            except ValueError:
                # Some old files have lines with just #
                pass
        else:
            line_data = convert_data_line(line)
            _mmap += line_data
            if 'recordsize' not in icfdata:
                icfdata['recordsize'] = len(line_data)

    return icfdata, memmap.MemoryMapBytes(_mmap)


def _encode_model_for_icf(model):
    """ Encode the model magically for the ICF file hash.

    If model is: AB CD 00 00
    Then the magic is AA BB CC DD AB CD
    """
    a = (util.byte_to_int(model[0]) & 0xF0) >> 4
    b = util.byte_to_int(model[0]) & 0x0F
    c = (util.byte_to_int(model[1]) & 0xF0) >> 4
    d = util.byte_to_int(model[1]) & 0x0F

    sequence = [(a << 4) | a,
                (b << 4) | b,
                (c << 4) | c,
                (d << 4) | d,
                (a << 4) | b,
                (c << 4) | d]
    return b''.join(util.int_to_byte(x) for x in sequence)


def write_file(radio, filename):
    """Write an ICF file"""
    f = open(filename, 'w', newline='\r\n')

    model = radio._model
    mdata = '%02x%02x%02x%02x' % (ord(model[0]),
                                  ord(model[1]),
                                  ord(model[2]),
                                  ord(model[3]))
    data = radio._mmap.get_packed()

    f.write('%s\n' % mdata)
    f.write('#Comment=%s\n' % radio._icf_data.get('Comment', ''))
    f.write('#MapRev=%i\n' % radio._icf_data.get('MapRev', 1))
    f.write('#EtcData=%06x\n' % radio._icf_data.get('EtcData', 0))

    binicf = _encode_model_for_icf(model)

    # ICF files for newer models (probably everything with an SD card
    # slot) store a hash on the last line of the ICF file, as
    # #CD=$hexdigest. This is an MD5 sum of a sequence that starts
    # with the specially-encoded model from _encode_model_for_icf(),
    # followed by the unencoded lines of the ICF file (including
    # address and length values). So for an ID31 the value we hash
    # looks like this (in hex, line breaks for the humans and pep8):
    #
    # 333322223322
    # 0000000020
    #     dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    # 0000002020
    #     dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    # ... and so on

    LOG.debug('ICF hash header: %r' % binascii.hexlify(binicf))
    blksize = radio._icf_data.get('recordsize', 32)
    for addr in range(0, len(data), blksize):
        block = binascii.hexlify(data[addr:addr + blksize]).decode().upper()
        if blksize == 32:
            line = '%08X%02X%s' % (addr, blksize, block)
            binicf += binascii.unhexlify(line)
        else:
            line = '%04X%02X%s' % (addr, blksize, block)
        f.write(line + '\n')

    if blksize == 32:
        hash = hashlib.md5(binicf)
        digest = hash.hexdigest().upper()
        LOG.debug('ICF hash digest: %s' % digest)
        f.write('#CD=%s\n' % digest)
    f.close()


def is_9x_icf(filename):
    """Returns True if @filename is an IC9x ICF file"""
    try:
        with open(filename) as f:
            mdata = f.read(8)
    except UnicodeDecodeError:
        # ICF files are ASCII, so any unicode failure means no.
        return False

    return mdata in ["30660000", "28880000"]


def is_icf_file(filename):
    """Returns True if @filename is an ICF file"""
    try:
        with open(filename) as f:
            data = f.readline()
            data += f.readline()
    except UnicodeDecodeError:
        # ICF files are ASCII, so any unicode failure means no.
        return False

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

        if index not in list(range(*self._radio._bank_index_bounds)):
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
        cs += byte
    return ((cs ^ 0xFFFF) + 1) & 0xFF


class IcomCloneModeRadio(chirp_common.CloneModeRadio):
    """Base class for Icom clone-mode radios"""
    VENDOR = "Icom"
    BAUDRATE = 9600
    FORMATS = [directory.register_format('Icom ICF', '*.icf')]

    _model = "\x00\x00\x00\x00"  # 4-byte model string
    _endframe = ""               # Model-unique ending frame
    _ranges = []                 # Ranges of the mmap to send to the radio
    _num_banks = 10              # Most simple Icoms have 10 banks, A-J
    _bank_index_bounds = (0, 99)
    _bank_class = IcomBank
    _can_hispeed = False
    _double_ident = False  # A couple radios require double ident before upload

    # Newer radios (ID51Plus2, ID5100, IC2730) use a slightly
    # different CLONE_DAT format
    _raw_frames = False
    _highbit_flip = False

    # Attributes that get put into ICF files when we export. The meaning
    # of these are unknown at this time, but differ per model (at least).
    # Saving ICF files will not be offered unless _icf_data has attributes.
    _icf_data = {
        'recordsize': 16,
    }

    @classmethod
    def is_hispeed(cls):
        """Returns True if the radio supports hispeed cloning"""
        return cls._can_hispeed

    @classmethod
    def get_model(cls):
        """Returns the Icom model data for this radio"""
        return bytes([util.byte_to_int(x) for x in cls._model])

    def get_endframe(self):
        """Returns the magic clone end frame for this radio"""
        return bytes([util.byte_to_int(x) for x in self._endframe])

    def get_ranges(self):
        """Returns the ranges this radio likes to have in a clone"""
        return self._ranges

    def process_frame_payload(self, payload):
        if self._raw_frames:
            return unescape_raw_bytes(payload)

        # Legacy frame format: convert BCD-encoded data to raw"""
        bcddata = payload
        data = b""
        i = 0
        while i+1 < len(bcddata):
            try:
                val = int(b"%s%s" % (util.int_to_byte(bcddata[i]),
                                     util.int_to_byte(bcddata[i+1])), 16)
                i += 2
                data += struct.pack("B", val)
            except (ValueError, TypeError) as e:
                LOG.error("Failed to parse byte %i (%r): %s" % (i,
                                                                bcddata[i:i+2],
                                                                e))
                break

        return data

    def get_payload(self, data, raw, checksum):
        """Returns the data with optional checksum BCD-encoded for the radio"""
        if checksum:
            data += util.int_to_byte(compute_checksum(data))
        if self._raw_frames:
            # Always raw format, no need to check raw
            return b''.join(escape_raw_byte(b) for b in data)
        if raw:
            return data
        payload = b''
        for byte in data:
            payload += b"%02X" % util.byte_to_int(byte)
        return payload

    def sync_in(self):
        _mmap = clone_from_radio(self)
        if self._highbit_flip:
            LOG.debug('Flipping high bits of received image')
            map_cls = _mmap.__class__
            _mmap = flip_high_order_bit(_mmap.get_packed())
            self._mmap = map_cls(_mmap)
        else:
            self._mmap = _mmap
        self.process_mmap()

    def get_mmap(self):
        if self._highbit_flip:
            map_cls = self._mmap.__class__
            LOG.debug('Flipping high bits of image')
            return map_cls(flip_high_order_bit(self._mmap.get_packed()))
        else:
            return self._mmap

    def sync_out(self):
        # We always start at 9600 baud. The UI may have handed us the same
        # rate we ended with last time (for radios which have variable but
        # unchanging speeds) but we always have to start in low-speed mode.
        self.pipe.baudrate = 9600
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

    def _make_call_list_setting_group(self, listname):
        current = getattr(self, 'get_%s_list' % listname)()
        nice_name = listname.split('_', 1)[0].upper()
        group = RadioSettingGroup('%s_list' % listname,
                                  '%s List' % nice_name)
        for i, cs in enumerate(current):
            group.append(RadioSetting('%03i' % i, '%i' % i,
                                      RadioSettingValueString(0, 8, cs)))
        return group

    def get_settings(self):
        if isinstance(self, chirp_common.IcomDstarSupport):
            dstar = RadioSettingGroup('dstar', 'D-STAR')
            dstar.append(self._make_call_list_setting_group('urcall'))
            dstar.append(self._make_call_list_setting_group('repeater_call'))
            dstar.append(self._make_call_list_setting_group('mycall'))
            return RadioSettings(dstar)
        return []

    def _apply_call_list_setting(self, dstar, listname):
        listgroup = dstar['%s_list' % listname]
        calls = [str(listgroup[i].value)
                 for i in sorted(listgroup.keys())]
        getattr(self, 'set_%s_list' % listname)(calls)

    def set_settings(self, settings):
        for group in settings:
            if group.get_name() == 'dstar':
                self._apply_call_list_setting(group, 'mycall')
                self._apply_call_list_setting(group, 'urcall')
                self._apply_call_list_setting(group, 'repeater_call')

    def load_mmap(self, filename):
        if filename.lower().endswith('.icf'):
            self._icf_data, self._mmap = read_file(filename)
            LOG.debug('Loaded ICF file %s with data: %s' % (filename,
                                                            self._icf_data))
            self.process_mmap()
        else:
            chirp_common.CloneModeRadio.load_mmap(self, filename)

    def save_mmap(self, filename):
        if filename.lower().endswith('.icf'):
            write_file(self, filename)
        else:
            chirp_common.CloneModeRadio.save_mmap(self, filename)

    @classmethod
    def match_model(cls, filedata, filename):
        if (filedata[:4] == binascii.hexlify(cls.get_model())[:4] and
                filename.lower().endswith('.icf')):
            return True
        else:
            return super(IcomCloneModeRadio, cls).match_model(filedata,
                                                              filename)


def flip_high_order_bit(data):
    return bytes([d ^ 0x80 for d in list(data)])


def escape_raw_byte(byte):
    """Escapes a raw byte for sending to the radio"""
    # Certain bytes are used as control characters to the radio, so if one of
    # these bytes is present in the stream to the radio, it gets escaped as
    # 0xff followed by (byte & 0x0f)
    if byte > 0xf9:
        return bytes([0xff, byte & 0xf])
    return bytes([byte])


def unescape_raw_bytes(escaped_data):
    """Unescapes raw bytes from the radio."""
    data = b""
    i = 0
    while i < len(escaped_data):
        byte = escaped_data[i]
        if byte == 0xff:
            if i + 1 >= len(escaped_data):
                raise errors.InvalidDataError(
                    "Unexpected escape character at end of data")
            i += 1
            byte = 0xf0 | escaped_data[i]
        data += bytes([byte])
        i += 1
    return data


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


def warp_byte_size(inbytes, obw=8, ibw=8, iskip=0, opad=0):
    """Convert between "byte sizes".

    This will pack N-bit characters into a sequence of 8-bit bytes,
    and perform the opposite.

    ibw (input bit width) is the width of the storage
    obw (output bit width) is the width of the characters to extract
    iskip is the number of input padding bits to skip
    opad is the number of output zero padding bits to add

    ibw=8,obw=7 will pull seven-bit characters from a sequence of bytes
    ibw=7,obw=8 will pack seven-bit characters into a sequence of bytes
    """
    if isinstance(inbytes, str):
        inbytes = [ord(x) for x in inbytes]
    outbit = opad
    tmp = 0
    stripmask = 1 << (ibw - 1)
    for byte in inbytes:
        inbit = 0
        while iskip:
            byte = (byte << 1) & 0xFF
            inbit += 1
            iskip -= 1
        for i in range(0, max(obw, ibw - inbit)):
            if inbit == ibw:
                # Move to next char
                inbit = 0
                break
            tmp = (tmp << 1) | ((byte & stripmask) and 1 or 0)
            byte = (byte << 1) & 0xFF
            inbit += 1
            outbit += 1
            if outbit == obw:
                yield tmp
                tmp = 0
                outbit = 0
