import struct
import logging
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.drivers import th_uv88

LOG = logging.getLogger(__name__)

MEM_SIZE = 0x2F00
BLOCK_SIZE = 0x200
STIMEOUT = 1
BAUDRATE = 57600

MEM_FORMAT = """
#seekto 0x10BC;
struct chns chan_vfo_mem[4]; // CHAN_NUM

#seekto 0x1F00;
struct {
  u8 bitmap[26];    // one bit for each channel marked in use
} chan_avail;

#seekto 0x1F20;
struct {
  u8 bitmap[26];    // one bit for each channel skipped
} chan_skip;

 #seekto 0x1140;
struct chname chan_name[200]; // CHAN_NAME

#seekto 0x2010;
struct {
  ul32 scan_v_start_freq;
  ul32 scan_v_end_freq;
  ul32 scan_u_start_freq;
  ul32 scan_u_end_freq;
} scanfreq;

#seekto 0x2020;
struct {
  u8 sideKey2:4,          // side key 2
     sideKey1:4;          //        side key 1
  u8 sideKey2_long:4,     //  side key 2 Long
     sideKey1_long:4;     //        side key 1 Long
  u8 aliasPreTime:4,      //        Alias Display Preamble Time
     unk21:1,
     ledtype:1,
     rxledmode:2;
  u8 menuexittime;
  u8 scantxch;
  u8 nknownbytes2[2];
  u8 btsuspendtime;       //  Bluetooth Suspend Time
  u8 btmiclevel:4,
     btvolumelevel:4;
  u8 unk17:1,
     btappmodeswitch:1,
     localspkswitch:1,
     unk18:4,
     btswitch:1;
  u8 unk20:5,
     miclevel:3;
  u8 unk19;
  u8 unk1:4,
     sqlLevel : 4;
  u8 beep : 1,
     callKind : 2,
     introScreen: 2,
     unk2:2,
     txChSelect : 1;
  u8 tot;
  u8 roger:2,
     language:1,
     endToneElim:3,
     unk5:2;
  u8 scanpausetype: 2,
     disMode : 2,
     ledMode: 4;
  u8 unk7;
  u8 unk8;
  u8 dtmf:4,
     tone2:4;
  u8 swAudio : 1,
     radioMoni : 1,
     keylock : 1,
     dualWait : 1,
     light : 4;
  u8 voxSw : 1,
     voxDelay: 4,
     voxLevel : 3;
  u8 unk9:1,
     remote_local_alarm:1,
     scantxchtype:2,
     saveMode : 2,
     keyMode : 2;
  u8 wxch:4,
     unk22:1,
     sendidforalias:1,
     aliasdisplay:1,
     wxmode:1;
  u8 unk13[8];
} basicsettings;

 #seekto 0x1F70;
struct {
  char name1[16];         // Intro Screen Line 1 (16 alpha text characters)
  char name2[16];         // Intro Screen Line 2 (16 alpha text characters)
}  openradioname;

 #seekto 0x2580;
struct {
  u8  fmset[4];
} fmmap;

 #seekto 0x2500;
struct {
  ul32 rxfreq;
} fm_stations[32];

#seekto 0x2584;
struct  {
  ul32 fmcur;
} fmfrqs;

"""

SPECIAL_MEMORIES = {"VFOA": -2, "VFOB": -1}


def _make_read_frame(addr, length):
    frame = b"\xFE\xFE\xEE\xEF\xEB"
    """Pack the info in the header format"""
    frame += _encode_data(
        struct.pack(">ihB", addr,
                    length, (addr+length) >> 8))
    frame += b"\xFD"
    # Return the data
    return frame


def _make_write_frame(addr, length, data=""):
    frame = b"\xFE\xFE\xEE\xEF\xE4"
    """Pack the info in the header format"""
    output = struct.pack(">ih", addr, length)
    # Add the data if set
    if len(data) != 0:
        output += data
    frame += _encode_data(output + lrc_cal(0, output))
    frame += b"\xFD"
    # Return the data
    return frame


def _do_start(radio, send_data):
    th_uv88._rawsend(radio, send_data)
    ack = th_uv88._rawrecv(radio, 8)
    if ack != b"\xFE\xFE\xEF\xEE\xE6\x80\x80\xFD":
        th_uv88._exit_program_mode(radio)
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond to enter read mode")


def _download(radio):
    """Get the memory map"""
    # Put radio in program mode and identify it
    th_uv88._do_ident(radio)
    # Enter read mode
    magic = b"\xFE\xFE\xEE\xEF\xE2\x80\x80\x80\x80\x80\x80\xAF\x00\x2F\xFD"
    _do_start(radio, magic)
    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE // BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)
    data = b""
    for addr in range(0, MEM_SIZE, BLOCK_SIZE):
        return_data_len = min(BLOCK_SIZE, MEM_SIZE - addr)
        frame = _make_read_frame(addr, return_data_len)

        # DEBUG
        LOG.debug("Frame=" + util.hexprint(frame))

        # Sending the read request
        th_uv88._rawsend(radio, frame)

        # Now we read data
        """
         Regular packet size is 1037 bytes.
         Combined with encryption algorithm and port transmission monitoring,
         packet length is not fixed.
         Packet length is calculated as 512*2+13 to prevent data field loss.
        """
        d = th_uv88._rawrecv(radio, BLOCK_SIZE*2 + 13)

        LOG.debug("Response Data= " + util.hexprint(d))

        if not d.startswith(b"\xFE\xFE\xEF\xEE\xE4"):
            LOG.warning("Incorrect start")
        if not d.endswith(b"\xFD"):
            LOG.warning("Incorrect end")
        # Aggregate the data
        decoded_data = _decode_data(d[11:-1])
        data += decoded_data[0:-1]
        # UI Update
        status.cur = addr // BLOCK_SIZE
        status.msg = "Cloning from radio..."
        radio.status_fn(status)
    th_uv88._exit_program_mode(radio)
    return data


def _upload(radio):
    """Upload procedure"""
    # Put radio in program mode and identify it
    th_uv88._do_ident(radio)

    magic = b"\xFE\xFE\xEE\xEF\xE3\x80\x80\x80\x80\x80\x80\xAF\x00\x2F\xFD"
    _do_start(radio, magic)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = 0x2600
    status.msg = "Cloning to radio..."
    radio.status_fn(status)
    write_data = radio.get_mmap()
    # The fun starts here
    for addr in range(0, 0x2600, BLOCK_SIZE):
        # Sending the data
        data = write_data[addr:addr + BLOCK_SIZE]

        frame = _make_write_frame(addr, BLOCK_SIZE, data)
        LOG.warning("Frame:%s:" % util.hexprint(frame))
        th_uv88._rawsend(radio, frame)

        ack = th_uv88._rawrecv(radio, 8)
        LOG.debug("Response Data= " + util.hexprint(ack))

        if not ack.startswith(b"\xFE\xFE\xEF\xEE\xE6\x80\x80\xFD"):
            LOG.warning("Unexpected response")
            th_uv88._exit_program_mode(radio)
            msg = "Bad ack writing block 0x%04x" % addr
            raise errors.RadioError(msg)

        # UI Update
        status.cur = addr
        status.msg = "Cloning to radio..."
        radio.status_fn(status)
    th_uv88._exit_program_mode(radio)


def _encode_data(byte_data_backup):
    byte_data = []
    for item in byte_data_backup:
        data_temp = (item + 0x80) & 0xFF
        if data_temp > 0xF9:
            byte_data.extend([0xFF, data_temp & 0x0F])
        else:
            byte_data.append(data_temp)
    return bytes(byte_data)


def _decode_data(byte_data):
    decoded_data = []
    index = 0
    data_len = len(byte_data)
    while index < data_len:
        if byte_data[index] != 0xFF:
            val = (byte_data[index] + 0x80) & 0xFF
            decoded_data.append(val)
            index += 1
        else:
            if index + 1 < data_len:
                val = (0xF0 + byte_data[index + 1] + 0x80) & 0xFF
                decoded_data.append(val)
                index += 2
            else:
                decoded_data.append(byte_data[index])
                index += 1
    return bytes(decoded_data)


def lrc_cal(lrc_init_value: int, auch_msg: bytes) -> bytes:
    lrc_value = (lrc_init_value - sum(auch_msg)) % 256
    return struct.pack('B', lrc_value)


@directory.register
class RA89R(th_uv88.THUV88Radio):
    VENDOR = "Retevis"
    MODEL = "RA89R"
    MODES = ['WFM', 'FM', 'NFM', "AM"]
    _hasSideKeys = True
    _fingerprint = b"\xFE\xFE\xEF\xEE\xE1" + _encode_data(b"RA89")
    _magic0 = b"\xFE\xFE\xEE\xEF\xE0"+_encode_data(b"RA89")+b"\x84\xFD"
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5" + _encode_data(b"RA89") + b"\x84\xFD"
    handshake_return_len = 37
    _airband = (108000000, 135999999)
    _vhf = (136000000, 174000010)
    _uhf = (400000000, 480000010)
    VALID_BANDS = [_airband, _vhf, _uhf]

    def get_features(self):
        rf = super().get_features()
        rf.valid_special_chans = sorted(SPECIAL_MEMORIES.keys())
        return rf

    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
            # with open('output.bin', 'wb') as f:
            #  f.write(data)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = memmap.MemoryMapBytes(data)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""

        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_memory(self, number):
        # radio first channel is 1, mem map is base 0
        mem = chirp_common.Memory()

        if isinstance(number, str):
            mem.extd_number = number
            ch_index = 0 if number == "VFOA" else 3
            mem.number = -2 if number == "VFOA" else -1
            _mem = self._memobj.chan_vfo_mem[ch_index]
            return self._get_memory(mem, _mem, number, False)
        else:
            mem.number = number
            _mem = self._memobj.chan_mem[number - 1]
            _name = self._memobj.chan_name[number - 1]
            # Determine if channel is empty
            if th_uv88._do_map(number, 2, self._memobj.chan_avail.bitmap) == 0:
                mem.empty = True
                return mem

            if th_uv88._do_map(number, 2, self._memobj.chan_skip.bitmap) > 0:
                mem.skip = ""
            else:
                mem.skip = "S"
            return self._get_memory(mem, _mem, _name)

    def set_memory(self, memory):
        """A value in a UI column for chan 'number' has been modified."""
        # update all raw channel memory values (_mem) from UI (mem)
        if memory.number < 0:
            index = 0 if memory.extd_number == "VFOA" else 3
            _mem = self._memobj.chan_vfo_mem[index]
            _name = memory.extd_number
        else:
            _mem = self._memobj.chan_mem[memory.number - 1]
            _name = self._memobj.chan_name[memory.number - 1]

            if memory.empty:
                th_uv88._do_map(memory.number, 0,
                                self._memobj.chan_avail.bitmap)
                return

            th_uv88._do_map(memory.number, 1,
                            self._memobj.chan_avail.bitmap)

            if memory.skip == "":
                th_uv88._do_map(memory.number, 1,
                                self._memobj.chan_skip.bitmap)
            else:
                th_uv88._do_map(memory.number, 0,
                                self._memobj.chan_skip.bitmap)
        return self._set_memory(memory, _mem, _name, memory.number > 0)

    def process_mmap(self):
        """Process the mem map into the mem object"""
        mem_format = th_uv88.MEM_FORMAT + MEM_FORMAT
        self._memobj = bitwise.parse(mem_format, self._mmap)

    def validate_memory(self, mem):
        msgs = []
        if (chirp_common.in_range(mem.freq, [self._airband])
                and mem.mode != 'AM'):
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range requires AM mode')))
        if (not chirp_common.in_range(mem.freq, [self._airband])
                and mem.mode == 'AM'):
            msgs.append(chirp_common.ValidationWarning(
                _('Frequency in this range must not be AM mode')))
        return msgs + super().validate_memory(mem)


@directory.register
class RA89G(RA89R):
    VENDOR = "Retevis"
    MODEL = "RA89G"
