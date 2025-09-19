# Copyright 2016:
# * Jim Unroe KC9HI, <rock.unroe@gmail.com>
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

"""common functions for Baofeng (or similar) handheld radios"""

import time
import struct
import logging
from chirp import chirp_common, memmap
from chirp import errors, util
from chirp import bandplan_na
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, InternalError, \
    RadioSettingValueList

LOG = logging.getLogger(__name__)

STIMEOUT = 1.5
TXPOWER_HIGH = 0x00
TXPOWER_LOW = 0x02


def _clean_buffer(radio):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = STIMEOUT
    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
    except:
        msg = "Generic error reading data from radio; check your cable."
        raise errors.RadioError(msg)

    if not data:
        LOG.debug('No response from radio')
        raise errors.RadioNoContactLikelyK1()
    elif len(data) != amount:
        LOG.debug('Wanted %i, got %i: %s',
                  amount, len(data), util.hexprint(data))
        msg = "Error reading data from radio: not the amount of data we want."
        raise errors.RadioError(msg)

    return data


def _rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        radio.pipe.write(data)
    except:
        raise errors.RadioError("Error sending data to radio")


def _make_frame(cmd, addr, length, data=""):
    """Pack the info in the header format"""
    frame = struct.pack(">BHB", ord(cmd), addr, length)
    # add the data if set
    if len(data) != 0:
        frame += data
    # return the data
    return frame


def _recv(radio, addr, length):
    """Get data from the radio """
    # read 4 bytes of header
    hdr = _rawrecv(radio, 4)

    # read data
    data = _rawrecv(radio, length)

    # DEBUG
    LOG.info("Response:")
    LOG.debug(util.hexprint(hdr + data))

    c, a, l = struct.unpack(">BHB", hdr)
    if a != addr or l != length or c != ord("X"):
        LOG.error("Invalid answer for block 0x%04x:" % addr)
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (c, a, l))
        raise errors.RadioError("Unknown response from the radio")

    return data


def _read_from_data(data, data_start, data_stop):
    data = data[data_start:data_stop]
    return data


def _get_data_from_image(radio, _data_start, _data_stop):
    image_data = _read_from_data(
        radio.get_mmap().get_byte_compatible(),
        _data_start,
        _data_stop)
    return image_data


def _read_block(radio, start, size, first_command=False):
    msg = struct.pack(">BHB", ord("S"), start, size)
    radio.pipe.write(msg)

    if radio._ack_block and first_command is False:
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

    chunk = radio.pipe.read(size)
    if not chunk:
        raise errors.RadioError("Radio did not send block 0x%04x" % start)
    elif len(chunk) != size:
        LOG.error("Chunk length was 0x%04i" % len(chunk))
        raise errors.RadioError("Radio sent incomplete block 0x%04x" % start)

    radio.pipe.write(b"\x06")
    time.sleep(0.05)

    return chunk


def _get_aux_data_from_radio(radio):
    block0 = _read_block(radio, 0x1E80, 0x40, True)
    block1 = _read_block(radio, 0x1EC0, 0x40, False)
    block2 = _read_block(radio, 0x1F00, 0x40, False)
    block3 = _read_block(radio, 0x1F40, 0x40, False)
    block4 = _read_block(radio, 0x1F80, 0x40, False)
    block5 = _read_block(radio, 0x1FC0, 0x40, False)
    version = block1[48:62]
    area1 = block2 + block3[0:32]
    area2 = block3[48:64]
    area3 = block4[16:64]
    # check for dropped byte
    dropped_byte = block5[15:16] == b"\xFF"  # True/False
    return version, area1, area2, area3, dropped_byte


def _get_radio_firmware_version(radio):
    # New radios will reply with 'alternative' (aka: bad) data if the Aux
    # memory area is read without first reading a block from another area
    # of memory. Reading any block that is outside of the Aux memory area
    # (which starts at 0x1EC0) prior to reading blocks in the Aux mem area
    # turns out to be a workaround for this problem.

    # read and disregard block0
    block0 = _read_block(radio, 0x1E80, 0x40, True)
    block1 = _read_block(radio, 0x1EC0, 0x40, False)
    block2 = _read_block(radio, 0x1FC0, 0x40, False)

    # get firmware version
    version = block1[48:62]  # firmware version

    # Some new radios will drop the byte at 0x1FCF when read in 0x40 byte
    # blocks. This results in the next 0x30 bytes being moved forward one
    # position (putting 0xFF in position 0x1FCF and pads the now missing byte
    # at the end, 0x1FFF, with 0x80).

    # detect dropped byte
    dropped_byte = (block2[15:16] == b"\xFF")  # dropped byte?

    return version, dropped_byte


def _image_ident_from_data(data, start, stop):
    return data[start:stop]


def _get_image_firmware_version(radio):
    return _image_ident_from_data(radio.get_mmap(), radio._fw_ver_start,
                                  radio._fw_ver_start + 0x0E)


def _do_ident(radio, magic):
    """Put the radio in PROGRAM mode"""
    #  set the serial discipline
    radio.pipe.baudrate = 9600
    radio.pipe.parity = "N"
    radio.pipe.timeout = STIMEOUT

    # flush input buffer
    _clean_buffer(radio)

    # send request to enter program mode
    _rawsend(radio, magic)

    ack = _rawrecv(radio, 1)
    if ack != b"\x06":
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")

    _rawsend(radio, b"\x02")

    # Ok, get the response
    ident = _rawrecv(radio, radio._magic_response_length)

    # check if response is OK
    if not ident.startswith(b"\xaa") or not ident.endswith(b"\xdd"):
        # bad response
        msg = "Unexpected response, got this:"
        msg += util.hexprint(ident)
        LOG.debug(msg)
        raise errors.RadioError("Unexpected response from radio.")

    # DEBUG
    LOG.info("Valid response, got this:")
    LOG.debug(util.hexprint(ident))

    _rawsend(radio, b"\x06")
    ack = _rawrecv(radio, 1)
    if ack != b"\x06":
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio refused clone")

    return ident


def _ident_radio(radio):
    for magic in radio._magic:
        error = None
        try:
            data = _do_ident(radio, magic)
            return data
        except errors.RadioError as e:
            print(e)
            error = e
            time.sleep(2)
    if error:
        raise error
    raise errors.RadioError("Radio did not respond")


def _download(radio):
    """Get the memory map"""
    # put radio in program mode
    ident = _ident_radio(radio)

    # identify radio
    radio_ident, has_dropped_byte = _get_radio_firmware_version(radio)
    LOG.info("Radio firmware version:")
    LOG.debug(util.hexprint(radio_ident))
    LOG.info("Radio has dropped byte issue: %s" % repr(has_dropped_byte))

    if radio_ident == "\xFF" * 16:
        ident += radio.MODEL.ljust(8)
    elif radio.MODEL in ("GMRS-V1", "GMRS-V2", "MURS-V1", "MURS-V2"):
        # check if radio_ident is OK
        if not radio_ident[:7] in radio._fileid:
            msg = "Incorrect model ID, got this:\n\n"
            msg += util.hexprint(radio_ident)
            LOG.debug(msg)
            raise errors.RadioError("Incorrect 'Model' selected.")

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._mem_size // radio._recv_block_size
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    start = 0
    end = radio._mem_size
    blocksize = radio._recv_block_size
    passes = 1
    if has_dropped_byte:
        passes = 2
        end = radio._mem_size - radio._recv_block_size

    data = b""
    for i in range(0, passes):
        if i == 1:
            start = radio._mem_size - radio._recv_block_size
            end = radio._mem_size
            blocksize = 0x10

        for addr in range(start, end, blocksize):
            frame = _make_frame("S", addr, blocksize)
            # DEBUG
            LOG.info("Request sent:")
            LOG.debug(util.hexprint(frame))

            # sending the read request
            _rawsend(radio, frame)

            if radio._ack_block:
                ack = _rawrecv(radio, 1)
                if ack != b"\x06":
                    raise errors.RadioError(
                        "Radio refused to send block 0x%04x" % addr)

            # now we read
            d = _recv(radio, addr, blocksize)

            _rawsend(radio, b"\x06")
            time.sleep(0.05)

            # aggregate the data
            data += d

            # UI Update
            status.cur = addr // blocksize
            status.msg = "Cloning from radio..."
            radio.status_fn(status)

    data += ident

    return data


def _upload(radio):
    """Upload procedure"""
    # put radio in program mode
    _ident_radio(radio)

    # identify radio
    radio_ident, aux_r1, aux_r2, aux_r3, \
        has_dropped_byte = _get_aux_data_from_radio(radio)
    LOG.info("Radio firmware version:")
    LOG.debug(util.hexprint(radio_ident))
    LOG.info("Radio has dropped byte issue: %s" % repr(has_dropped_byte))
    # identify image
    image_ident = _get_image_firmware_version(radio)
    LOG.info("Image firmware version:")
    LOG.debug(util.hexprint(image_ident))

    if radio.MODEL in ("GMRS-V1", "MURS-V1"):
        # check if radio_ident is OK
        if radio_ident != image_ident:
            msg = "Incorrect model ID, got this:\n\n"
            msg += util.hexprint(radio_ident)
            LOG.debug(msg)
            raise errors.RadioError("Image not supported by radio")

    aux_i1 = _get_data_from_image(radio, 0x1F00, 0x1F60)
    aux_i2 = _get_data_from_image(radio, 0x1F70, 0x1F80)
    aux_i3 = _get_data_from_image(radio, 0x1F90, 0x1FC0)

    # check if Aux memory of image matches Aux memory of radio
    aux_matched = False
    if aux_i1 != aux_r1:
        # Area 1 does not match
        # The safest thing to do is to skip uploading Aux mem area.
        LOG.info("Aux memory mismatch")
        LOG.info("Aux area 1 from image is %s" % repr(aux_i1))
        LOG.info("Aux area 1 from radio is %s" % repr(aux_r1))
    elif aux_i2 != aux_r2:
        # Area 2 does not match
        # The safest thing to do is to skip uploading Aux mem area.
        LOG.info("Aux memory mismatch")
        LOG.info("Aux area 2 from image is %s" % repr(aux_i2))
        LOG.info("Aux area 2 from radio is %s" % repr(aux_r2))
    elif aux_i3 != aux_r3:
        # Area 3 does not match
        # The safest thing to do is to skip uploading Aux mem area.
        LOG.info("Aux memory mismatch")
        LOG.info("Aux area 3 from image is %s" % repr(aux_i3))
        LOG.info("Aux area 3 from radio is %s" % repr(aux_r3))
    else:
        # All areas matched
        # Uploading full Aux mem area is permitted
        aux_matched = True

    if has_dropped_byte and not aux_matched:
        msg = ("Image not supported by radio. You must...\n"
               "1. Download from radio.\n"
               "2. Make changes.\n"
               "3. Upload back to same radio.")
        raise errors.RadioError(msg)

    if has_dropped_byte or (aux_matched and radio.VENDOR != "BTECH"):
        _ranges = [(0x0000, 0x0DF0),
                   (0x0E00, 0x1800),
                   (0x1E80, 0x2000),
                   ]
    else:
        _ranges = radio._ranges

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._mem_size // radio._send_block_size
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    # the fun start here
    for start, end in _ranges:
        for addr in range(start, end, radio._send_block_size):
            # sending the data
            data = radio.get_mmap()[addr:addr + radio._send_block_size]

            frame = _make_frame("X", addr, radio._send_block_size, data)

            _rawsend(radio, frame)
            time.sleep(0.05)

            # receiving the response
            ack = _rawrecv(radio, 1)
            if ack != b"\x06":
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            # UI Update
            status.cur = addr // radio._send_block_size
            status.msg = "Cloning to radio..."
            radio.status_fn(status)


def bcd_decode_freq(bytes):
    real_freq = 0
    for byte in bytes:
        if byte > 9:
            msg = ("Found Invalid BCD Encoding")
            raise InternalError(msg)
        real_freq = (real_freq * 10) + byte
    return chirp_common.format_freq(real_freq * 10)


class BaofengCommonHT(chirp_common.CloneModeRadio,
                      chirp_common.ExperimentalRadio):
    """Baofeng HT Style Radios"""
    VENDOR = "Baofeng"
    MODEL = ""
    IDENT = ""

    _gmrs = False
    _bw_shift = False
    _tri_band = False

    def sync_in(self):
        """Download from radio"""
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
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

    def get_features(self):
        """Get the radio's features"""

        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = True
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = self.MODES
        rf.valid_characters = self.VALID_CHARS
        rf.valid_name_length = self.LENGTH_NAME
        if self._gmrs:
            rf.valid_duplexes = ["", "+", "off"]
        else:
            rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_skips = self.SKIP_VALUES
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.memory_bounds = (0, 127)
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = self.VALID_BANDS
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 20.0, 25.0, 50.0]

        return rf

    def _is_txinh(self, _mem):
        raw_tx = b""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == b"\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[:1] == b"\xff":
            mem.empty = True
            return mem

        mem.freq = int(_mem.rxfreq) * 10

        if self._is_txinh(_mem):
            # TX freq not set
            mem.duplex = "off"
            mem.offset = 0
        else:
            # TX freq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset != 0:
                if chirp_common.is_split(self.get_features().valid_bands,
                                         mem.freq, int(_mem.txfreq) * 10):
                    mem.duplex = "split"
                    mem.offset = int(_mem.txfreq) * 10
                elif offset < 0:
                    mem.offset = abs(offset)
                    mem.duplex = "-"
                elif offset > 0:
                    mem.offset = offset
                    mem.duplex = "+"
            else:
                mem.offset = 0

        for char in _nam.name:
            if str(char) == "\xFF":
                char = " "  # The OEM software may have 0xFF mid-name
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
            mem.dtcs = self.DTCS_CODES[index]
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
            mem.rx_dtcs = self.DTCS_CODES[index]
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

        levels = self.POWER_LEVELS
        if self._tri_band:
            if _mem.lowpower == TXPOWER_HIGH:
                mem.power = levels[0]
            elif _mem.lowpower == TXPOWER_LOW:
                mem.power = levels[1]
            else:
                LOG.error("Radio reported invalid power level %s (in %s)" %
                          (_mem.power, levels))
                mem.power = levels[0]
        else:
            try:
                mem.power = levels[_mem.lowpower]
            except IndexError:
                LOG.error("Radio reported invalid power level %s (in %s)" %
                          (_mem.power, levels))
                mem.power = levels[0]

        mem.mode = _mem.wide and "FM" or "NFM"

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(_mem.bcl))
        mem.extra.append(rs)

        rs = RadioSetting("pttid", "PTT ID",
                          RadioSettingValueList(self.PTTID_LIST,
                                                current_index=_mem.pttid))
        mem.extra.append(rs)

        rs = RadioSetting("scode", "S-CODE",
                          RadioSettingValueList(self.SCODE_LIST,
                                                current_index=_mem.scode))
        mem.extra.append(rs)

        immutable = []

        if self._gmrs:
            if self.MODEL == "UV-9G":
                if mem.number >= 1 and mem.number <= 30:
                    # 30 GMRS fixed channels
                    GMRS_30_FIXED_FREQS = \
                        bandplan_na.ALL_GMRS_FREQS + \
                        bandplan_na.GMRS_HIRPT
                    GMRS_FREQ = GMRS_30_FIXED_FREQS[mem.number - 1]
                    mem.freq = GMRS_FREQ
                    immutable = ["empty", "freq"]
                    if mem.number <= 22:
                        # GMRS simplex only channels
                        mem.duplex = ''
                        mem.offset = 0
                        immutable += ["duplex", "offset"]
                        if mem.number >= 8 and mem.number <= 14:
                            # GMRS 467 MHz interstitial channels
                            # must be narrow FM and low power
                            mem.mode = "NFM"
                            mem.power = self.POWER_LEVELS[2]
                            immutable += ["mode", "power"]
                    if mem.number > 22:
                        # GMRS repeater only channels
                        mem.duplex = '+'
                        mem.offset = 5000000
                        immutable += ["duplex", "offset"]
                elif mem.freq in bandplan_na.ALL_GMRS_FREQS:
                    # 98 GMRS customizable channels
                    if mem.freq in bandplan_na.GMRS_LOW:
                        # GMRS 462 MHz interstitial frequencies
                        mem.duplex = ''
                        mem.offset = 0
                        immutable = ["duplex", "offset"]
                    if mem.freq in bandplan_na.GMRS_HHONLY:
                        # GMRS 467 MHz interstitial frequencies
                        mem.duplex = ''
                        mem.offset = 0
                        mem.mode = "NFM"
                        mem.power = self.POWER_LEVELS[2]
                        immutable = ["duplex", "offset", "mode", "power"]
                    if mem.freq in bandplan_na.GMRS_HIRPT:
                        # GMRS 462 MHz main frequencies
                        # GMRS 467 MHz main frequencies (repeater input)
                        if mem.duplex == '':
                            mem.offset = 0
                        if mem.duplex == '+':
                            mem.offset = 5000000
                else:
                    # Not a GMRS frequency - disable TX
                    mem.duplex = 'off'
                    mem.offset = 0
                    immutable = ["duplex", "offset"]

        mem.immutable = immutable

        return mem

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number]
        _nam = self._memobj.names[mem.number]

        if mem.empty:
            _mem.set_raw("\xff" * 16)
            _nam.set_raw("\xff" * 16)
            return

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
            _mem.txtone = self.DTCS_CODES.index(mem.dtcs) + 1
            _mem.rxtone = self.DTCS_CODES.index(mem.dtcs) + 1
        elif mem.tmode == "Cross":
            txmode, rxmode = mem.cross_mode.split("->", 1)
            if txmode == "Tone":
                _mem.txtone = int(mem.rtone * 10)
            elif txmode == "DTCS":
                _mem.txtone = self.DTCS_CODES.index(mem.dtcs) + 1
            else:
                _mem.txtone = 0
            if rxmode == "Tone":
                _mem.rxtone = int(mem.ctone * 10)
            elif rxmode == "DTCS":
                _mem.rxtone = self.DTCS_CODES.index(mem.rx_dtcs) + 1
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

        if self._tri_band:
            levels = self.POWER_LEVELS
            if mem.power is None:
                _mem.lowpower = TXPOWER_HIGH
            elif mem.power == levels[0]:
                _mem.lowpower = TXPOWER_HIGH
            elif mem.power == levels[1]:
                _mem.lowpower = TXPOWER_LOW
            else:
                _mem.lowpower = TXPOWER_HIGH
        else:
            if mem.power:
                _mem.lowpower = self.POWER_LEVELS.index(mem.power)
            else:
                _mem.lowpower = 0

        # extra settings
        if len(mem.extra) > 0:
            # there are setting, parse
            for setting in mem.extra:
                setattr(_mem, setting.get_name(), setting.value)
        else:
            # there are no extra settings, load defaults
            _mem.bcl = 0
            _mem.pttid = 0
            _mem.scode = 0

    def set_settings(self, settings):
        _settings = self._memobj.settings
        _mem = self._memobj
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
                if self._bw_shift:
                    value = ((value & 0x00FF) << 8) | ((value & 0xFF00) >> 8)
                self._memobj.fm_presets = value
            except Exception:
                LOG.debug(element.get_name())
                raise
