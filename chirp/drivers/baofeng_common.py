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
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList

LOG = logging.getLogger(__name__)

STIMEOUT = 1.5


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

    if len(data) != amount:
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
    """Pack the info in the headder format"""
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


def _get_radio_firmware_version(radio):
    msg = struct.pack(">BHB", ord("S"), radio._fw_ver_start,
                      radio._recv_block_size)
    radio.pipe.write(msg)
    block = _recv(radio, radio._fw_ver_start, radio._recv_block_size)
    _rawsend(radio, "\x06")
    time.sleep(0.05)
    version = block[0:16]
    return version


def _image_ident_from_data(data, start, stop):
    return data[start:stop]


def _get_image_firmware_version(radio):
    return _image_ident_from_data(radio.get_mmap(), radio._fw_ver_start,
                                  radio._fw_ver_start + 0x10)


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
    if ack != "\x06":
        if ack:
            LOG.debug(repr(ack))
        raise errors.RadioError("Radio did not respond")

    _rawsend(radio, "\x02")

    # Ok, get the response
    ident = _rawrecv(radio, radio._magic_response_length)

    # check if response is OK
    if not ident.startswith("\xaa") or not ident.endswith("\xdd"):
        # bad response
        msg = "Unexpected response, got this:"
        msg +=  util.hexprint(ident)
        LOG.debug(msg)
        raise errors.RadioError("Unexpected response from radio.")

    # DEBUG
    LOG.info("Valid response, got this:")
    LOG.debug(util.hexprint(ident))

    _rawsend(radio, "\x06")
    ack = _rawrecv(radio, 1)
    if ack != "\x06":
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
        except errors.RadioError, e:
            print e
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
    radio_ident = _get_radio_firmware_version(radio)
    LOG.info("Radio firmware version:")
    LOG.debug(util.hexprint(radio_ident))

    if radio_ident == "\xFF" * 16:
        ident += radio.MODEL.ljust(8)
    elif radio.MODEL in ("GMRS-V1", "MURS-V1"):
        # check if radio_ident is OK
        if not radio_ident[:7] in radio._fileid:
            msg = "Incorrect model ID, got this:\n\n"
            msg += util.hexprint(radio_ident)
            LOG.debug(msg)
            raise errors.RadioError("Incorrect 'Model' selected.")

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._mem_size / radio._recv_block_size
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = ""
    for addr in range(0, radio._mem_size, radio._recv_block_size):
        frame = _make_frame("S", addr, radio._recv_block_size)
        # DEBUG
        LOG.info("Request sent:")
        LOG.debug(util.hexprint(frame))

        # sending the read request
        _rawsend(radio, frame)

        if radio._ack_block:
            ack = _rawrecv(radio, 1)
            if ack != "\x06":
                raise errors.RadioError(
                    "Radio refused to send block 0x%04x" % addr)

        # now we read
        d = _recv(radio, addr, radio._recv_block_size)

        _rawsend(radio, "\x06")
        time.sleep(0.05)

        # aggregate the data
        data += d

        # UI Update
        status.cur = addr / radio._recv_block_size
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    data += ident

    return data


def _upload(radio):
    """Upload procedure"""
    # put radio in program mode
    _ident_radio(radio)

    # identify radio
    radio_ident = _get_radio_firmware_version(radio)
    LOG.info("Radio firmware version:")
    LOG.debug(util.hexprint(radio_ident))
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

    if radio_ident != "0xFF" * 16 and image_ident == radio_ident:
        _ranges = radio._ranges
    else:
        _ranges = [(0x0000, 0x0DF0),
                   (0x0E00, 0x1800)]

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = radio._mem_size / radio._send_block_size
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
            if ack != "\x06":
                msg = "Bad ack writing block 0x%04x" % addr
                raise errors.RadioError(msg)

            # UI Update
            status.cur = addr / radio._send_block_size
            status.msg = "Cloning to radio..."
            radio.status_fn(status)


def _split(rf, f1, f2):
    """Returns False if the two freqs are in the same band (no split)
    or True otherwise"""

    # determine if the two freqs are in the same band
    for low, high in rf.valid_bands:
        if f1 >= low and f1 <= high and \
                f2 >= low and f2 <= high:
            # if the two freqs are on the same Band this is not a split
            return False

    # if you get here is because the freq pairs are split
    return True

class BaofengCommonHT(chirp_common.CloneModeRadio,
                      chirp_common.ExperimentalRadio):
    """Baofeng HT Sytle Radios"""
    VENDOR = "Baofeng"
    MODEL = ""
    IDENT = ""

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
        self._mmap = memmap.MemoryMap(data)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
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
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.txfreq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number]
        _nam = self._memobj.names[number]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw()[0] == "\xff":
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
                if _split(self.get_features(), mem.freq, int(_mem.txfreq) * 10):
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
                                                self.PTTID_LIST[_mem.pttid]))
        mem.extra.append(rs)

        rs = RadioSetting("scode", "S-CODE",
                          RadioSettingValueList(self.SCODE_LIST,
                                                self.SCODE_LIST[_mem.scode]))
        mem.extra.append(rs)

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
                except Exception, e:
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
            except Exception, e:
                LOG.debug(element.get_name())
                raise
