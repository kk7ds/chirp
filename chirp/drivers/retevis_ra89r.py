import struct
import logging
import math
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings
from chirp.drivers import th_uv88

LOG = logging.getLogger(__name__)

MEM_SIZE = 0x2F00
BLOCK_SIZE = 0x200
STIMEOUT = 1
BAUDRATE = 57600

MEM_FORMAT = """
struct chns {
  ul32 rxfreq;
  ul32 txfreq;
  ul16 scramble:4,
       rxtone:12; //decode:12
  ul16 decodeDSCI:1,
       encodeDSCI:1,
       unk1:1,
       unk2:1,
       txtone:12; //encode:12
  u8   power:2,
       wide:2,
       b_lock:2,
       freqreverse:1,
       unk3:1;
  u8   unk4:3,
       signal:2,
       displayName:1,
       talkaround:1,
       unk5:1;
  u8   tone5pttid:2,
       pttid:2,
       unk7:1,
       step:3;               // not required
  u8   name[6];
};

struct chname {
  u8  extra_name[10];
};

#seekto 0x0000;
struct chns chan_mem[200]; // CHAN_NUM

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
     backlightMode: 4;
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
} fmfrqs[32];

#seekto 0x2584;
struct  {
  ul32 rxfreq;
} fm_vfochn;

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


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except Exception:
        th_uv88._exit_program_mode(radio)
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)
    return data


def _do_ident(radio):
    """Put the radio in PROGRAM mode & identify it"""
    radio.pipe.baudrate = BAUDRATE
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT
    handshake_return_len = 37
    # Ident radio
    magic = b"\xFE\xFE\xEE\xEF\xE0"+_encode_data(b"RA89")+b"\x84\xFD"
    th_uv88._rawsend(radio, magic)
    try:
        ack = radio.pipe.read(handshake_return_len)
    except Exception:
        th_uv88._exit_program_mode(radio)
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)
    if not ack:
        th_uv88._exit_program_mode(radio)
        raise errors.RadioNoResponse()
    if len(ack) != handshake_return_len:
        th_uv88._exit_program_mode(radio)
        msg = "Error reading from radio: not the amount of data we want."
        raise errors.RadioError(msg)
    if not ack.startswith(radio._fingerprint) or not ack.endswith(b"\xFD"):
        th_uv88._exit_program_mode(radio)
        LOG.debug(repr(ack))
        raise errors.RadioError("Unexpected response from radio")
    return True


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
    _do_ident(radio)
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
        d = _rawrecv(radio, BLOCK_SIZE*2 + 13)

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
    _do_ident(radio)

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

        ack = _rawrecv(radio, 8)
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
    _magic5 = b"\xFE\xFE\xEE\xEF\xE5" + _encode_data(b"RA89") + b"\x84\xFD"
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
        mem_format = MEM_FORMAT
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

    def get_settings(self):
        """Translate the MEM_FORMAT structs into setstuf in the UI"""
        _settings = self._memobj.basicsettings
        _openradioname = self._memobj.openradioname
        _scanfreq = self._memobj.scanfreq

        basic = RadioSettingGroup("basic", "Basic Settings")
        group = RadioSettings(basic)

        options = ['Frequency', 'Channel #', 'Name']
        rx = RadioSettingValueList(
            options, current_index=_settings.disMode)
        rset = RadioSetting("basicsettings.disMode", "Display Mode", rx)
        basic.append(rset)

        options = ["Off", "On", "5s", "10s", "15s", "20s", "25s",
                   "30s"]
        rx = RadioSettingValueList(
            options, current_index=_settings.backlightMode)
        rset = RadioSetting("basicsettings.backlightMode",
                            "LED Display Mode", rx)
        basic.append(rset)

        options = ["OFF"] + ["%s" % x for x in range(1, 10)]
        rx = RadioSettingValueList(options, current_index=_settings.sqlLevel)
        rset = RadioSetting("basicsettings.sqlLevel", "Squelch Level", rx)
        basic.append(rset)

        options = ["%s" % x for x in range(1, 8)]
        rx = RadioSettingValueList(options, current_index=_settings.light)
        rset = RadioSetting("basicsettings.light",
                            "Background Light Color", rx)
        basic.append(rset)

        options = ["OFF", "END"]
        rx = RadioSettingValueList(options, current_index=_settings.roger)
        rset = RadioSetting("basicsettings.roger", "Roger Beep", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.swAudio)
        rset = RadioSetting("basicsettings.swAudio", "Voice Prompts", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.beep)
        rset = RadioSetting("basicsettings.beep", "Keypad Beep", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.keylock)
        rset = RadioSetting("basicsettings.keylock", "Auto Key Lock", rx)
        basic.append(rset)

        options = ["Off"] + ["%s seconds" % x for x in range(30, 300, 30)]
        rx = RadioSettingValueList(options, current_index=_settings.tot)
        rset = RadioSetting("basicsettings.tot",
                            "Transmission Time-out Timer", rx)
        basic.append(rset)

        options = ["ALL", "PTT", "KEY", "Key & Side Key"]
        rx = RadioSettingValueList(
            options, current_index=_settings.keyMode)
        rset = RadioSetting("basicsettings.keyMode", "Key Lock Mode", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.dualWait)
        rset = RadioSetting("basicsettings.dualWait",
                            "Dual Wait/Standby", rx)
        basic.append(rset)

        options = ["Always On", "Code On", "OFF"]
        rx = RadioSettingValueList(
            options, current_index=(
                0 if _settings.rxledmode > 2 else _settings.rxledmode))
        rset = RadioSetting("basicsettings.rxledmode", "Rx Light", rx)
        basic.append(rset)

        options = ["Off", "1:1", "1:2", "1:4"]
        rx = RadioSettingValueList(options, current_index=_settings.saveMode)
        rset = RadioSetting("basicsettings.saveMode", "Battery Save Mode", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.radioMoni)
        rset = RadioSetting("basicsettings.radioMoni", "Radio Monitor", rx)
        basic.append(rset)

        options = ['OFF', 'Frequency', '120', '180', '240']
        rx = RadioSettingValueList(
            options, current_index=_settings.endToneElim)
        rset = RadioSetting("basicsettings.endToneElim", "End Tone Elim", rx)
        basic.append(rset)

        options = ['Remote Alarm', 'Local Alarm']
        rx = RadioSettingValueList(
            options, current_index=_settings.remote_local_alarm)
        rset = RadioSetting("basicsettings.remote_local_alarm",
                            "Alarm Mode", rx)
        basic.append(rset)

        options = ['OFF', '5s', '10s', '15s', '20s',
                   '30s', '40s', '50s', '60s']
        rx = RadioSettingValueList(
            options, current_index=_settings.menuexittime)
        rset = RadioSetting("basicsettings.menuexittime", "Menu Exit Time", rx)
        basic.append(rset)

        options = ["%s" % x for x in range(1, 8)]
        rx = RadioSettingValueList(
            options, current_index=_settings.miclevel)
        rset = RadioSetting("basicsettings.miclevel", "Mic Gain", rx)
        basic.append(rset)

        options = ["All.Enable", "All.Disable"]
        rx = RadioSettingValueList(
            options, current_index=_settings.ledtype)
        rset = RadioSetting("basicsettings.ledtype", "Led Type", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.aliasdisplay)
        rset = RadioSetting("basicsettings.aliasdisplay", "Alias", rx)
        basic.append(rset)

        options = ["%.1fs" % (x / 10) for x in range(10, 34, 2)]
        rx = RadioSettingValueList(
            options, current_index=(
                0 if _settings.aliasPreTime > 12
                else _settings.aliasPreTime))
        rset = RadioSetting("basicsettings.aliasPreTime", "Pretime", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.sendidforalias)
        rset = RadioSetting("basicsettings.sendidforalias", "Send Own Id", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.wxmode)
        rset = RadioSetting("basicsettings.wxmode", "Weather Sw", rx)
        basic.append(rset)

        options = ["NOAA-%s" % x for x in range(1, 13)]
        rx = RadioSettingValueList(
            options, current_index=_settings.wxch)
        rset = RadioSetting("basicsettings.wxch", "Weather CH", rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(_settings.voxSw)
        rset = RadioSetting("basicsettings.voxSw", "Vox Switch", rx)
        basic.append(rset)

        # Menu 03 - VOX Level
        rx = RadioSettingValueInteger(1, 7, _settings.voxLevel + 1)
        rset = RadioSetting("basicsettings.voxLevel", "Vox Level", rx)
        basic.append(rset)

        options = ['0.5S', '1.0S', '1.5S', '2.0S', '2.5S', '3.0S', '3.5S',
                   '4.0S', '4.5S', '5.0S']
        rx = RadioSettingValueList(options, current_index=_settings.voxDelay)
        rset = RadioSetting("basicsettings.voxDelay", "VOX Delay", rx)
        basic.append(rset)

        advanced = RadioSettingGroup("advanced", "Advanced Settings")
        group.append(advanced)

        options = ["Off", "Voltage", "Character String",
                   "Startup Logo"]
        rx = RadioSettingValueList(
            options, current_index=_settings.introScreen)
        rset = RadioSetting("basicsettings.introScreen",
                            "Intro Screen", rx)
        advanced.append(rset)

        def _name_validate(value):
            return value[:15].ljust(16)

        def _char_to_name(name):
            rname = ""
            for i in range(16):  # 0 - 15
                char = chr(int(name[i]))
                if char == "\x00":
                    char = " "  # Other software may have 0x00 mid-name
                rname += char
            return rname.rstrip()  # remove trailing spaces

        rx = RadioSettingValueString(0, 16,
                                     _char_to_name(_openradioname.name1))
        rx.set_validate_callback(_name_validate)
        rset = RadioSetting("openradioname.name1", "Intro Line 1", rx)
        advanced.append(rset)

        rx = RadioSettingValueString(0, 16,
                                     _char_to_name(_openradioname.name2))
        rx.set_validate_callback(_name_validate)
        rset = RadioSetting("openradioname.name2", "Intro Line 2", rx)
        advanced.append(rset)

        options_short = ["None", "VOX", "Dual Wait",
                         "Scan", "Moni", "1750 Tone",
                         "Power Select", "Alarm", "FM Radio",
                         "Talk Around", "Frequency Reverse"]
        options_long = (
            options_short[:8] + ["Temporarily Moni"] + options_short[8:])

        def _side_key_apply(setting, obj, atrb):
            index = options_long.index(str(setting.value))
            setattr(obj, atrb, index)

        rx = RadioSettingValueList(
            options_short, current_index=(_settings.sideKey1-1
                                          if _settings.sideKey1 > 8
                                          else _settings.sideKey1))
        rset = RadioSetting("basicsettings.sideKey1", "Side Key 1", rx)
        rset.set_apply_callback(_side_key_apply, _settings, "sideKey1")
        advanced.append(rset)

        rx = RadioSettingValueList(options_long,
                                   current_index=_settings.sideKey1_long)
        rset = RadioSetting("basicsettings.sideKey1_long",
                            "Side Key 1 Long", rx)
        advanced.append(rset)

        rx = RadioSettingValueList(options_short,
                                   current_index=(_settings.sideKey2-1
                                                  if _settings.sideKey2 > 8
                                                  else _settings.sideKey2))
        rset = RadioSetting("basicsettings.sideKey2",
                            "Side Key 2", rx)
        rset.set_apply_callback(_side_key_apply, _settings, "sideKey2")
        advanced.append(rset)

        rx = RadioSettingValueList(options_long,
                                   current_index=_settings.sideKey2_long)
        rset = RadioSetting("basicsettings.sideKey2_long",
                            "Side Key 2 Long", rx)
        advanced.append(rset)

        scanb = RadioSettingGroup("scandioc", "Scan Settings")
        group.append(scanb)

        options = ["TO", "CO", "SE"]
        rx = RadioSettingValueList(options,
                                   current_index=_settings.scanpausetype)
        rset = RadioSetting("basicsettings.scanpausetype", "Scan Type", rx)
        scanb.append(rset)

        options = ["Current CH", "Last Active CH", "Select CH"]
        rx = RadioSettingValueList(options,
                                   current_index=_settings.scantxchtype)
        rset = RadioSetting("basicsettings.scantxchtype", "Scan Tx Mode", rx)
        scanb.append(rset)

        def myset_freq(setting, obj, atrb, mult):
            """ Callback to set frequency by applying multiplier"""
            value = int(float(str(setting.value)) * mult)
            setattr(obj, atrb, value)
            return

        rx = RadioSettingValueFloat(108, 174,
                                    _scanfreq.scan_v_start_freq/100000,
                                    0.00001, 5)
        rset = RadioSetting("scanfreq.scan_v_start_freq",
                            "Scan Start Freq(VHF)", rx)
        rset.set_apply_callback(myset_freq, _scanfreq,
                                "scan_v_start_freq", 100000)
        scanb.append(rset)

        rx = RadioSettingValueFloat(108, 174,
                                    _scanfreq.scan_v_end_freq/100000,
                                    0.00001, 5)
        rset = RadioSetting("scanfreq.scan_v_end_freq",
                            "Scan End Freq(VHF)", rx)
        rset.set_apply_callback(myset_freq, _scanfreq,
                                "scan_v_end_freq", 100000)
        scanb.append(rset)

        rx = RadioSettingValueFloat(400, 520,
                                    _scanfreq.scan_u_start_freq/100000,
                                    0.00001, 5)
        rset = RadioSetting("scanfreq.scan_u_start_freq",
                            "Scan Start Freq(UHF)", rx)
        rset.set_apply_callback(myset_freq, _scanfreq,
                                "scan_u_start_freq", 100000)
        scanb.append(rset)

        rx = RadioSettingValueFloat(400, 520,
                                    _scanfreq.scan_u_end_freq/100000,
                                    0.00001, 5)
        rset = RadioSetting("scanfreq.scan_u_end_freq",
                            "Scan End Freq(UHF)", rx)
        rset.set_apply_callback(myset_freq, _scanfreq,
                                "scan_u_end_freq", 100000)
        scanb.append(rset)

        btb = RadioSettingGroup("btdioc", "Bluetooth Settings")
        group.append(btb)

        rx = RadioSettingValueBoolean(_settings.btswitch)
        rset = RadioSetting("basicsettings.btswitch", "Bluetooth Switch", rx)
        btb.append(rset)

        options = ["%ss" % x for x in range(4, 16)] + ["Infinite"]
        rx = RadioSettingValueList(options,
                                   current_index=_settings.btsuspendtime)
        rset = RadioSetting("basicsettings.btsuspendtime", "Hold Time", rx)
        btb.append(rset)

        options = ["%s" % x for x in range(1, 6)]
        rx = RadioSettingValueList(options,
                                   current_index=_settings.btvolumelevel)
        rset = RadioSetting("basicsettings.btvolumelevel", "SpkGain", rx)
        btb.append(rset)

        options = ["%s" % x for x in range(1, 6)]
        rx = RadioSettingValueList(options, current_index=_settings.btmiclevel)
        rset = RadioSetting("basicsettings.btmiclevel", "Mic Gain", rx)
        btb.append(rset)

        rx = RadioSettingValueBoolean(_settings.localspkswitch)
        rset = RadioSetting("basicsettings.localspkswitch", "Speak Switch", rx)
        btb.append(rset)

        fmb = RadioSettingGroup("fmradioc", "FM Radio Settings")
        group.append(fmb)

        def myset_mask(setting, obj, atrb, nx):
            vx = 1 if bool(setting.value) else 0
            th_uv88._do_map(nx + 1, vx, self._memobj.fmmap.fmset)
            return

        def myset_fmfrq(setting, obj, atrb, nx):
            """ Callback to set xx.x FM freq in memory as xx.x * 100000"""
            # in-valid even kHz freqs are allowed; to satisfy run_tests
            vx = int(float(str(setting.value)) * 100000)
            setattr(obj[nx], atrb, vx)
            return

        _fmx = self._memobj.fm_vfochn

        # FM Broadcast Manual Settings
        val = _fmx.rxfreq
        val = val / 100000.0
        if val < 64.0 or val > 108.0:
            val = 100.7
        rx = RadioSettingValueFloat(64.0, 108.0, val, 0.1, 1)
        rset = RadioSetting("fm_vfochn.rxfreq", "Manual FM Freq (MHz)", rx)
        rset.set_apply_callback(myset_freq, _fmx, "rxfreq", 100000)
        fmb.append(rset)

        _fmfrq = self._memobj.fmfrqs
        _fmap = self._memobj.fmmap

        # FM Broadcast Presets Settings
        for j in range(0, 32):
            val = _fmfrq[j].rxfreq
            if val < 6400000 or val > 10800000:
                val = 88.0
                fmset = False
            else:
                val = (float(int(val)) / 100000)
                # get fmmap bit value: 1 = enabled
                ndx = int(math.floor((j) / 8))
                bv = j % 8
                msk = 1 << bv
                vx = _fmap.fmset[ndx]
                fmset = bool(vx & msk)
            rx = RadioSettingValueBoolean(fmset)
            rset = RadioSetting("fmmap.fmset/%d" % j,
                                "FM Preset %02d" % (j + 1), rx)
            rset.set_apply_callback(myset_mask, _fmap, "fmset", j)
            fmb.append(rset)

            rx = RadioSettingValueFloat(64.0, 108.0, val, 0.1, 1)
            rset = RadioSetting("fmfrqs/%d.rxfreq" % j,
                                "    Preset %02d Freq" % (j + 1), rx)
            # This callback uses the array index
            rset.set_apply_callback(myset_fmfrq, _fmfrq, "rxfreq", j)
            fmb.append(rset)

        return group       # END get_settings()


@directory.register
class RA89G(RA89R):
    VENDOR = "Retevis"
    MODEL = "RA89G"
