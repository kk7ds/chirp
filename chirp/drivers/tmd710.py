# Copyright 2011 Dan Smith <dsmith@danplanet.com>
# --        2019 Rick DeWitt <aa0rd@yahoo.com>
# -- Implementing Kenwood TM-D710G as MCP Clone Mode for Python 2.7
# -- Thanks to Herm Halbach, W7HRM, for the 710 model testing.
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

import time
import struct
import logging
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettingValueInteger, \
    RadioSettingValueFloat, RadioSettings
from chirp.drivers import kenwood_live

LOG = logging.getLogger(__name__)

BAUD = 0
STIMEOUT = 0.2
TERM = b'\x0d'         # Cmd write terminator (CR)
ACK = b'\x06'           # Data write acknowledge char
W8S = 0.001      # short wait, secs
W8L = 0.1       # long wait
TMD710_DUPLEX = ["", "+", "-", "", "split"]
TMD710_SKIP = ["", "S"]
TMD710_MODES = ["FM", "NFM", "AM"]
TMD710_BANDS = [(118000000, 135995000),
                (136000000, 199995000),
                (200000000, 299995000),
                (300000000, 399995000),
                (400000000, 523995000),
                (800000000, 1299995000)]
TMD710_STEPS = [5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0,
                30.0, 50.0, 100.0]
# Need string list of those steps for mem.extra value list
STEPS_STR = []
for val in TMD710_STEPS:
    STEPS_STR.append("%3.2f" % val)
TMD710_TONE_MODES = ["", "Tone", "TSQL", "DTCS", "Cross"]
TMD710_CROSS = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone"]
TMD710_DTSC = list(chirp_common.DTCS_CODES)
TMD710_TONES = list(chirp_common.TONES)
TMD710_TONES.remove(159.8)
TMD710_TONES.remove(165.5)
TMD710_TONES.remove(171.3)
TMD710_TONES.remove(177.3)
TMD710_TONES.remove(183.5)
TMD710_TONES.remove(189.9)
TMD710_TONES.remove(196.6)
TMD710_TONES.remove(199.5)
TMD710_CHARS = chirp_common.CHARSET_ASCII
TMD710_CHARS += chr(34)     # "


def _command(ser, cmd, rsplen, w8t=0.01):
    """Send cmd to radio via ser port
    cmd is output string with possible terminator
    rsplen is expected response char count, NOT incl prefix and term
    If rsplen = 0 then do not0 read after write """
    ser.write(cmd)
    time.sleep(w8t)
    result = b""
    if rsplen > 0:  # read response
        result = ser.read(rsplen)
    return result


def _connect_radio(radio):
    """Determine baud rate and verify radio on-line"""
    global BAUD
    xid = "D710" + radio.SHORT
    resp = kenwood_live.KenwoodLiveRadio(None).get_id(radio.pipe)
    BAUD = radio.pipe.baudrate      # As detected by kenwood_live
    LOG.debug("Got [%s] at %i Baud." % (resp, BAUD))
    resp = resp[3:]     # Strip "ID " prefix
    if len(resp) > 2:   # Got something from "ID"
        if resp == xid:     # Good comms
            return
        else:
            stx = "Radio responded as %s, not %s." % (resp, xid)
            raise errors.RadioError(stx)
    raise errors.RadioError("No response from radio")


def _update_status(self, status, step=1):
    """ Increment status bar """
    status.cur += step
    self.status_fn(status)
    return


def _val_list(setting, opts, obj, atrb, fix=0, ndx=-1):
    """Callback:from ValueList. Set the integer index.
    This function is here to be available to get_mem and get_set
    fix is optional additive offset to the list index
    ndx is optional obj[ndx] array index """
    value = opts.index(str(setting.value))
    value += fix
    if ndx >= 0:    # indexed obj
        setattr(obj[ndx], atrb, value)
    else:
        setattr(obj, atrb, value)
    return


class KenwoodTMx710Radio(chirp_common.CloneModeRadio):
    """ Base class for TMD-710 """
    VENDOR = "Kenwood"
    MODEL = "TM-x710"
    SHORT = "X"       # Short model ID code

    _upper = 999         # Number of normal chans

    # Put Special memory channels after normal ones
    SPECIAL_MEMORIES = {"Scan-0Lo": 1000, "Scan-0Hi": 1001,
                        "Scan-1Lo": 1002, "Scan-1Hi": 1003,
                        "Scan-2Lo": 1004, "Scan-2Hi": 1005,
                        "Scan-3Lo": 1006, "Scan-3Hi": 1007,
                        "Scan-4Lo": 1008, "Scan-4Hi": 1009,
                        "Scan-5Lo": 1010, "Scan-5Hi": 1011,
                        "Scan-6Lo": 1012, "Scan-6Hi": 1013,
                        "Scan-7Lo": 1014, "Scan-7Hi": 1015,
                        "Scan-8Lo": 1016, "Scan-8Hi": 1017,
                        "Scan-9Lo": 1018, "Scan-9Hi": 1019,
                        "WX-1": 1020, "WX-2": 1021,
                        "WX-3": 1022, "WX-4": 1023,
                        "WX-5": 1024, "WX-6": 1025,
                        "WX-7": 1026, "WX-8": 1027,
                        "WX-9": 1028, "WX-10": 1029,
                        "Call C0": 1030, "Call C1": 1031
                        }
    # _REV dict is used to retrieve name given number
    SPECIAL_MEMORIES_REV = dict(zip(SPECIAL_MEMORIES.values(),
                                    SPECIAL_MEMORIES.keys()))

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.can_odd_split = True
        rf.has_dtcs = True
        rf.has_dtcs_polarity = False
        if self.SHORT == "G":             # NOT for D710
            rf.has_rx_dtcs = True       # Enable DTCS Rx Code column
            rf.has_cross = True
            rf.valid_cross_modes = TMD710_CROSS
        rf.has_bank = False
        rf.has_settings = True
        rf.has_ctone = True
        rf.has_mode = True
        rf.has_comment = False
        rf.valid_tmodes = TMD710_TONE_MODES
        rf.valid_modes = TMD710_MODES
        rf.valid_duplexes = TMD710_DUPLEX
        rf.valid_tuning_steps = TMD710_STEPS
        rf.valid_tones = TMD710_TONES
        rf.valid_dtcs_codes = TMD710_DTSC
        # Supports upper and lower case text
        rf.valid_characters = TMD710_CHARS
        rf.valid_name_length = 8
        rf.valid_skips = TMD710_SKIP
        rf.valid_bands = TMD710_BANDS
        rf.memory_bounds = (0, 999)        # including special chans 1000-1029
        rf.valid_special_chans = sorted(self.SPECIAL_MEMORIES.keys())
        return rf

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "Connect your interface cable to the PC Port on the\n"
            "back of the 'TX/RX' unit. NOT the Com Port on the head.\n")
        rp.pre_upload = _(
            "Connect your interface cable to the PC Port on the\n"
            "back of the 'TX/RX' unit. NOT the Com Port on the head.\n")
        return rp

    def sync_in(self):
        """Download from radio"""
        try:
            _connect_radio(self)
            data = bytes(self._read_mem())
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
            _connect_radio(self)
            self._write_mem()
        except Exception:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        """Convert raw channel data (_mem) into UI columns (mem)"""
        mem = chirp_common.Memory()
        if self.SHORT == "G":
            mem.extra = RadioSettingGroup("extra", "Extra")
        # If called from 'Properties', spcl chans number is integer
        propflg = False
        if isinstance(number, int):
            if number > 999:
                propflg = True
        if isinstance(number, str) or propflg:
            if propflg:
                mem.number = number
                mem.name = self.SPECIAL_MEMORIES_REV[number]
                mem.extd_number = mem.name
            else:
                mem.name = number   # Spcl chns 1st var
                mem.number = self.SPECIAL_MEMORIES[number]
                mem.extd_number = number    # Uses name as LOC
                mem.immutable = ["name"]
            if mem.number < 1030:       # Scan edges, WX
                _mem = self._memobj.ch_mem[mem.number]
                _map = self._memobj.chmap[mem.number]
            else:                       # Call chans
                _mem = self._memobj.call[mem.number - 1030]
        else:       # Normal mem chans
            _mem = self._memobj.ch_mem[number]
            _nam = self._memobj.ch_nam[number]
            _map = self._memobj.chmap[number]
            mem.number = number
            mnx = ""
            for char in _nam.name:
                if int(char) < 127:
                    mnx += chr(int(char))
            mem.name = mnx.rstrip()
        if _mem.rxfreq == 0x0ffffffff or _mem.rxfreq == 0:
            mem.empty = True
            return mem
        mem.empty = False
        if mem.number < 1030 and _map.skip != 0x0ff:      # empty
            mem.skip = TMD710_SKIP[_map.skip]
        mem.freq = int(_mem.rxfreq)
        mem.duplex = TMD710_DUPLEX[_mem.duplex]
        mem.offset = int(_mem.offset)
        # Duplex = 4 (split); offset contains the TX freq
        mem.mode = TMD710_MODES[_mem.mode]
        # _mem.tmode is 4-bit pattern, not number
        mx = 0      # No tone
        mem.cross_mode = TMD710_CROSS[0]
        mem.rx_dtcs = TMD710_DTSC[_mem.dtcs]
        mem.dtcs = TMD710_DTSC[_mem.dtcs]
        if self.SHORT == "G":
            if _mem.tmode & 8:     # Tone
                mx = 1
            if _mem.tmode & 4:     # Tsql
                mx = 2
            if _mem.tmode & 2:     # Dtcs
                mx = 3
            if _mem.tmode & 1:     # Cross
                mx = 4
                if _mem.cross == 1:     # Tone->DTCS
                    mem.cross_mode = TMD710_CROSS[1]
                if _mem.cross == 2:     # DTCS->Tone
                    mem.cross_mode = TMD710_CROSS[2]
        else:           # D710; may have bit 8 set
            if _mem.tmode & 4:     # Tone
                mx = 1
            if _mem.tmode & 2:     # Tsql
                mx = 2
            if _mem.tmode & 1:     # Dtcs
                mx = 3
                mem.dtcs = TMD710_DTSC[_mem.dtcs]
        mem.tmode = TMD710_TONE_MODES[mx]
        mem.ctone = TMD710_TONES[_mem.ctone]
        mem.rtone = TMD710_TONES[_mem.rtone]
        mem.tuning_step = TMD710_STEPS[_mem.tstep]

        if self.SHORT == "G":         # Only the 710G
            rx = RadioSettingValueList(STEPS_STR, current_index=_mem.splitstep)
            sx = "Split TX step (kHz)"
            rset = RadioSetting("splitstep", sx, rx)
            mem.extra.append(rset)

        return mem

    def set_memory(self, mem):
        """Convert UI column data (mem) into MEM_FORMAT memory (_mem)"""
        if mem.number > 999:      # Special chans
            if mem.number < 1030:        # Scan, Wx
                _mem = self._memobj.ch_mem[mem.number]
                _map = self._memobj.chmap[mem.number]
            else:                        # Call chans
                _mem = self._memobj.call[mem.number - 1030]
            _nam = None
        else:
            _mem = self._memobj.ch_mem[mem.number]
            _nam = self._memobj.ch_nam[mem.number]
            _map = self._memobj.chmap[mem.number]
            nx = len(mem.name)
            for ix in range(8):
                if ix < nx:
                    _nam.name[ix] = mem.name[ix]
                else:
                    _nam.name[ix] = chr(0x0ff)    # needs 8 chrs
        if mem.empty:
            _mem.rxfreq = 0x0ffffffff
            _mem.offset = 0x0ffffff
            _mem.duplex = 0x0f
            _mem.tstep = 0x0ff
            _mem.tmode = 0x0f
            _mem.mode = 0x0ff
            _mem.rtone = 0x0ff
            _mem.ctone = 0x0ff
            _mem.dtcs = 0x0ff
            _map.skip = 0x0ff
            _map.band = 0x0ff
            if _nam:
                for ix in range(8):
                    _nam.name[ix] = chr(0x0ff)
            return
        if _mem.rxfreq == 0x0ffffffff:    # New Channel needs defaults
            _mem.rxfreq = 144000000
            _map.band = 5
            _map.skip = 0
            _mem.mode = 0
            _mem.duplex = 0
            _mem.offset = 0
            _mem.rtone = 8
            _mem.ctone = 8
            _mem.dtcs = 0
            _mem.tstep = 0
            _mem.splitstep = 0
        # Now use the UI values entered so far
        _mem.rxfreq = mem.freq
        _mem.mode = TMD710_MODES.index(mem.mode)
        try:
            _tone = mem.rtone
            _mem.rtone = TMD710_TONES.index(mem.rtone)
            _tone = mem.ctone
            _mem.ctone = TMD710_TONES.index(mem.ctone)
        except ValueError:
            raise errors.UnsupportedToneError("This radio does not support " +
                                              "tone %.1fHz" % _tone)
        _mem.dtcs = TMD710_DTSC.index(mem.dtcs)
        _mem.tmode = 0      # None
        _mem.cross = 0
        if self.SHORT == "G":
            if mem.tmode == "Tone":
                _mem.tmode = 8
            if mem.tmode == "TSQL":
                _mem.tmode = 4
            if mem.tmode == "DTCS":
                _mem.tmode = 2
            if mem.tmode == "Cross":
                _mem.tmode = 1
                mx = TMD710_CROSS.index(mem.cross_mode)
                _mem.cross = 3          # t -t
                if mx == 1:
                    _mem.cross = 1      # t-d
                    _mem.dtcs = TMD710_DTSC.index(mem.rx_dtcs)
                if mx == 2:
                    _mem.cross = 2      # d-t
                    _mem.dtcs = TMD710_DTSC.index(mem.dtcs)
        else:
            _mem.tmode = 0x80       # None
            if mem.tmode == "Tone":
                _mem.tmode = 0x0c
            if mem.tmode == "TSQL":
                _mem.tmode = 0x0a
            if mem.tmode == "DTCS":
                _mem.tmode = 0x09
        if mem.duplex == "n/a":     # Not valid
            mem.duplex = ""
        _mem.duplex = TMD710_DUPLEX.index(mem.duplex)
        _mem.offset = mem.offset
        _mem.tstep = TMD710_STEPS.index(mem.tuning_step)
        # Set _map.band for this bank. Not Calls!
        if mem.number < 1030:
            _map.band = 5
            val = mem.freq
            for mx in range(6):     # Band codes are 0, 5, 6, 7, 8, 9
                if val >= TMD710_BANDS[mx][0] and \
                        val <= TMD710_BANDS[mx][1]:
                    _map.band = mx
                    if mx > 0:
                        _map.band = mx + 4
            _map.skip = TMD710_SKIP.index(mem.skip)
        # Only 1 mem.extra entry now
        for ext in mem.extra:
            if ext.get_name() == "splitstep":
                val = STEPS_STR.index(str(ext.value))
                setattr(_mem, "splitstep", val)
            else:
                setattr(_mem, ext.get_name(), ext.value)
        return

    def get_settings(self):
        """Translate the MEM_FORMAT structs into settings in the UI"""
        # Define mem struct write-back shortcuts
        if self.SHORT == "G":
            _bmp = self._memobj.bitmap
        _blk1 = self._memobj.block1
        _blk1a = self._memobj.block1a
        _pmg = self._memobj.pmg     # array[6] of settings
        _dtmc = self._memobj.dtmc
        _dtmn = self._memobj.dtmn
        _com = self._memobj.mcpcom
        _skyc = self._memobj.skycmd
        basic = RadioSettingGroup("basic", "Basic")
        disp = RadioSettingGroup("disp", "PM0: Display")    # PM[0] settings
        aud = RadioSettingGroup("aud", "PM0: Audio")
        aux = RadioSettingGroup("aux", "PM0: Aux")
        txrx = RadioSettingGroup("txrc", "PM0: Transmit/Receive")
        memz = RadioSettingGroup("memz", "PM0: Memory")
        pfk = RadioSettingGroup("pfk", "PM0: PF Keys")
        pvfo = RadioSettingGroup("pvfo", "PM0: Programmable VFO")
        bmsk = RadioSettingGroup("bmsk", "PM0: Band Masks")    # end PM[0]
        rptr = RadioSettingGroup("rptr", "Repeater")
        dtmf = RadioSettingGroup("dtmf", "DTMF")
        skyk = RadioSettingGroup("skyk", "Sky Command")
        pmm = RadioSettingGroup("pmm", "PM Groups 1-5(Partial)")
        group = RadioSettings(basic, disp, aud, aux, txrx, memz, pvfo, pfk,
                              bmsk, rptr, dtmf, skyk, pmm)

        mhz1 = 1000000.   # Raw freq is stored with 0.1 Hz resolution

        def _adjraw(setting, obj, atrb, fix=0, ndx=-1):
            """Callback for Integer add or subtract fix from value."""
            vx = int(str(setting.value))
            value = vx + int(fix)
            if value < 0:
                value = 0
            if ndx < 0:
                setattr(obj, atrb, value)
            else:
                setattr(obj[ndx], atrb, value)
            return

        def _mhz_val(setting, obj, atrb, ndx=-1, ndy=-1):
            """ Callback to set freq back to Hz """
            vx = float(str(setting.value))
            vx = int(vx * mhz1)
            if ndx < 0:
                setattr(obj, atrb, vx)
            else:
                if atrb[0:7] == "progvfo":      # 2-deep
                    stx = atrb.split(".")
                    setattr(obj[ndx].progvfo[ndy], stx[1], vx)
                else:
                    setattr(obj[ndx], atrb, vx)
            return

        def _char_to_str(chrx):
            """ Remove ff pads from char array """
            #  chrx is char array
            str1 = ""
            for sx in chrx:
                if int(sx) > 31 and int(sx) < 127:
                    str1 += chr(int(sx))
            return str1

        def _pswd_vfy(setting, obj, atrb):
            """ Verify password is 1-6 chars, numbers 1-5 """
            str1 = str(setting.value).strip()   # initial
            str2 = ''.join(filter(lambda c: c in '12345', str1))  # valid chars
            if str1 != str2:
                # Two lines due to python 73 char limit
                sx = "Bad characters in Password"
                raise errors.RadioError(sx)
            str2 = str1.ljust(6, chr(255))      # pad to 6 with ff's
            setattr(obj, atrb, str2)
            return

        def _pad_str(setting, lenstr, padchr, obj, atrb, ndx=-1):
            """ pad string to lenstr with padchr  """
            str1 = str(setting.value).strip()      # initial string
            str2 = str1.ljust(lenstr, padchr)
            if ndx < 0:
                setattr(obj, atrb, str2)
            else:
                setattr(obj[ndx], atrb, str2)
            return

        # ===== BASIC GROUP =====
        sx = _char_to_str(_com.comnt)
        rx = RadioSettingValueString(0, 32, sx)
        sx = "Comment"
        rset = RadioSetting("mcpcom.comnt", sx, rx)
        basic.append(rset)

        rx = RadioSettingValueInteger(0, 5, _blk1.pmrecall)
        sx = "Current PM Select"
        rset = RadioSetting("block1.pmrecall", sx, rx)
        basic.append(rset)

        rx = RadioSettingValueBoolean(bool(_blk1.pwdon))
        sx = "Password"
        rset = RadioSetting("block1.pwdon", sx, rx)
        basic.append(rset)

        sx = _char_to_str(_blk1.pswd).strip()
        rx = RadioSettingValueString(0, 6, sx)
        # rx.set_charset("12345")   # Keeps finding `'
        sx = "-   Password (numerals 1-5)"
        rset = RadioSetting("block1.pswd", sx, rx)
        rset.set_apply_callback(_pswd_vfy, _blk1, "pswd")
        basic.append(rset)

        # ===== PM0 (off) DISPLAY GROUP =====
        rx = RadioSettingValueString(0, 8, _char_to_str(_pmg[0].pwron))
        sx = "Power-On message"
        rset = RadioSetting("pmg/0.pwron", sx, rx)
        disp.append(rset)

        if self.SHORT == "G":         # TMD-710G
            rx = RadioSettingValueBoolean(bool(_bmp.bmpon))
            sx = "PM0: Custom display bitmap"
            rset = RadioSetting("bitmap.bmpon", sx, rx)
            disp.append(rset)

            rx = RadioSettingValueString(0, 64, _char_to_str(_bmp.bmpfyl))
            rx.set_mutable(False)
            sx = "-   Custom bitmap filename"
            rset = RadioSetting("bitmap.bmpfyl", sx, rx)
            rset.set_doc("Read-only: To modify, use MCP-6 s/w")
            disp.append(rset)

        opts = ["VFO", "Mem Recall"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].a_mr)
        sx = "A: Left Side VFO/MR"
        rset = RadioSetting("pmg/0.a_mr", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "a_mr")
        disp.append(rset)

        rx = RadioSettingValueInteger(0, 999, _pmg[0].a_chn)
        sx = "A: Left Side MR Channel"
        rset = RadioSetting("pmg/0.a_chn", sx, rx)
        disp.append(rset)

        rx = RadioSettingValueList(opts, current_index=_pmg[0].b_mr)
        sx = "B: Right Side VFO/MR"
        rset = RadioSetting("pmg/0.b_mr", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "b_mr")
        disp.append(rset)

        rx = RadioSettingValueInteger(0, 999, _pmg[0].b_chn)
        sx = "B: Right Side MR Channel"
        rset = RadioSetting("pmg/0.b_chn", sx, rx)
        disp.append(rset)

        rx = RadioSettingValueInteger(0, 8, _pmg[0].bright)
        sx = "Brightness level"
        rset = RadioSetting("pmg/0.bright", sx, rx)
        disp.append(rset)

        opts = ["Amber", "Green"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].bkltclr)
        sx = "Backlight color"
        rset = RadioSetting("pmg/0.bkltclr", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "bkltclr")
        disp.append(rset)

        val = _pmg[0].bkltcont + 1
        rx = RadioSettingValueInteger(1, 16, val)
        sx = "Contrast level"
        rset = RadioSetting("pmg/0.bkltcont", sx, rx)
        rset.set_apply_callback(_adjraw, _pmg[0], "bkltcont", -1)
        disp.append(rset)

        opts = ["Positive", "Negative"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].dsprev)
        sx = "Color mode"
        rset = RadioSetting("pmg/0.dsprev", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "dsprev")
        disp.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].autobri))
        sx = "Auto brightness"
        rset = RadioSetting("pmg/0.autobri", sx, rx)
        disp.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].dispbar))
        sx = "Display partition bar"
        rset = RadioSetting("pmg/0.dispbar", sx, rx)
        disp.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].single))
        sx = "Single band display"
        rset = RadioSetting("pmg/0.single", sx, rx)
        disp.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].autopm))
        sx = "Auto PM Store"
        rset = RadioSetting("pmg/0.autopm", sx, rx)
        disp.append(rset)

        # ===== AUDIO GROUP =====
        rx = RadioSettingValueBoolean(bool(_pmg[0].beepon))
        sx = "Beep On"
        rset = RadioSetting("pmg/0.beepon", sx, rx)
        aud.append(rset)

        val = _pmg[0].beepvol + 1     # 1-7 downloads as 0-6
        rx = RadioSettingValueInteger(1, 7, val)
        sx = "Beep volume (1 - 7)"
        rset = RadioSetting("pmg/0.beepvol", sx, rx)
        rset.set_apply_callback(_adjraw, _pmg[0], "beepvol", -1)
        aud.append(rset)

        opts = ["Mode1", "Mode2"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].extspkr)
        sx = "External Speaker"
        rset = RadioSetting("pmg/0.extspkr", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "extspkr")
        aud.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].pbkrpt))
        sx = "VGS Plugin: Playback repeat"
        rset = RadioSetting("pmg/0.pbkrpt", sx, rx)
        aud.append(rset)

        rx = RadioSettingValueInteger(0, 60, _pmg[0].pbkint)
        sx = "     Playback repeat interval (0 - 60 secs)"
        rset = RadioSetting("pmg/0.pbkint", sx, rx)
        aud.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].cntrec))
        sx = "     Continuous recording"
        rset = RadioSetting("pmg/0.cntrec", sx, rx)
        aud.append(rset)

        opts = ["Off", "Auto", "Manual"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].ance)
        sx = "     Announce mode"
        rset = RadioSetting("pmg/0.ance", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "ance")
        aud.append(rset)

        opts = ["English", "Japanese"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].lang)
        sx = "     Announce language"
        rset = RadioSetting("pmg/0.lang", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "lang")
        aud.append(rset)

        rx = RadioSettingValueInteger(1, 7, _pmg[0].vcvol + 1)
        sx = "     Voice volume (1 - 7)"
        rset = RadioSetting("pmg/0.vcvol", sx, rx)
        rset.set_apply_callback(_adjraw, _pmg[0], "vcvol", -1)
        aud.append(rset)

        rx = RadioSettingValueInteger(0, 4, _pmg[0].vcspd)
        sx = "     Voice speed (0 - 4)"
        rset = RadioSetting("pmg/0.vcspd", sx, rx)
        aud.append(rset)

        # ===== AUX GROUP =====
        opts = ["9600", "19200", "38400", "57600"]
        rx = RadioSettingValueList(opts, current_index=_blk1.pcbaud)
        sx = "PC port baud rate"
        rset = RadioSetting("block1.pcbaud", sx, rx)
        rset.set_apply_callback(_val_list, opts, _blk1, "pcbaud")
        aux.append(rset)

        opts = ["A-Band", "B-Band", "TX-A / RX-B", "RX-A / TX-B"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].intband)
        sx = "Internal TNC band"
        rset = RadioSetting("pmg/0.intband", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "intband")
        aux.append(rset)

        opts = ["A-Band", "B-Band", "TX-A / RX-B", "RX-A / TX-B"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].extband)
        sx = "External TNC band"
        rset = RadioSetting("pmg/0.extband", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "extband")
        aux.append(rset)

        opts = ["1200", "9600"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].extbaud)
        sx = "External TNC baud"
        rset = RadioSetting("pmg/0.extbaud", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "extbaud")
        aux.append(rset)

        opts = ["Off", "BUSY", "SQL", "TX", "BUSY/TX", "SQL/TX"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].sqcsrc)
        sx = "SQC output source"
        rset = RadioSetting("pmg/0.sqcsrc", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "sqcsrc")
        aux.append(rset)

        opts = ["Low", "High"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].sqclogic)
        sx = "SQC logic"
        rset = RadioSetting("pmg/0.sqclogic", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "sqclogic")
        aux.append(rset)

        opts = ["Off", "30", "60", "90", "120", "180"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].apo)
        sx = "APO: Auto Power Off (Mins)"
        rset = RadioSetting("pmg/0.apo", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "apo")
        aux.append(rset)

        opts = ["Time Operate (TO)", "Carrier Operate (CO)", "Seek"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].scnrsm)
        sx = "Scan resume mode"
        rset = RadioSetting("pmg/0.scnrsm", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "scnrsm")
        aux.append(rset)

        rx = RadioSettingValueInteger(1, 10, _pmg[0].scntot + 1)
        sx = "   Scan TO delay (Secs)"
        rset = RadioSetting("pmg/0.scntot", sx, rx)
        rset.set_apply_callback(_adjraw, _pmg[0], "scntot", -1)
        aux.append(rset)

        rx = RadioSettingValueInteger(1, 10, _pmg[0].scncot + 1)
        sx = "   Scan CO delay (Secs)"
        rset = RadioSetting("pmg/0.scncot", sx, rx)
        rset.set_apply_callback(_adjraw, _pmg[0], "scncot", -1)
        aux.append(rset)

        opts = ["Mode 1: 1ch", "Mode 2: 61ch", "Mode 3: 91ch",
                "Mode 4: 181ch"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].vsmode)
        sx = "Visual scan"
        rset = RadioSetting("pmg/0.vsmode", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "vsmode")
        aux.append(rset)

        rx = RadioSettingValueBoolean(bool(_blk1.m10mz))
        sx = "10 MHz mode"
        rset = RadioSetting("block1.m10mz", sx, rx)
        aux.append(rset)

        rx = RadioSettingValueBoolean(bool(_blk1.ansbck))
        sx = "Remote control answerback"
        rset = RadioSetting("block1.ansbck", sx, rx)
        aux.append(rset)

        # ===== TX / RX Group =========
        opts = ["A: Left", "B: Right"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].txband)
        sx = "TX Side (PTT)"
        rset = RadioSetting("pmg/0.txband", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "txband")
        txrx.append(rset)

        opts = ["High (50W)", "Medium (10W)", "Low (5W)"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].a_pwr)
        sx = "A-Band transmit power"
        rset = RadioSetting("pmg/0.a_pwr", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "a_pwr")
        txrx.append(rset)

        rx = RadioSettingValueList(opts, current_index=_pmg[0].b_pwr)
        sx = "B-Band transmit power"
        rset = RadioSetting("pmg/0.b_pwr", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "b_pwr")
        txrx.append(rset)

        opts = ["Off", "125", "250", "500", "750", "1000"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].mutehu)
        sx = "Rx Mute hangup time (ms)"
        rset = RadioSetting("pmg/0.mutehu", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "mutehu")
        txrx.append(rset)

        opts = ["Off", "125", "250", "500"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].ssqlhu)
        sx = "S-meter SQL hangup time (ms)"
        rset = RadioSetting("pmg/0.ssqlhu", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "ssqlhu")
        txrx.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].beatshft))
        sx = "Beat shift"
        rset = RadioSetting("pmg/0.beatshft", sx, rx)
        txrx.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].asmsql))
        sx = "A-Band S-meter SQL"
        rset = RadioSetting("pmg/0.asmsql", sx, rx)
        txrx.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].bsmsql))
        sx = "B-Band S-meter SQL"
        rset = RadioSetting("pmg/0.bsmsql", sx, rx)
        txrx.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].vhfaip))
        sx = "VHF band AIP"
        rset = RadioSetting("pmg/0.vhfaip", sx, rx)
        txrx.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].uhfaip))
        sx = "UHF band AIP"
        rset = RadioSetting("pmg/0.uhfaip", sx, rx)
        txrx.append(rset)

        opts = ["High", "Medium", "Low"]
        rx = RadioSettingValueList(opts, current_index=_blk1.micsens)
        sx = "Microphone sensitivity (gain)"
        rset = RadioSetting("block1.micsens", sx, rx)
        txrx.append(rset)

        opts = ["3", "5", "10"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].tot)
        sx = "Time-Out timer (Mins)"
        rset = RadioSetting("pmg/0.tot", sx, rx)
        #  rset.set_apply_callback(_val_list, opts, _pmg[0], "tot")
        txrx.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].wxalerta))
        sx = "WX Alert A-band"
        rset = RadioSetting("pmg/0.wxalerta", sx, rx)
        txrx.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].wxalertb))
        sx = "WX Alert B-band"
        rset = RadioSetting("pmg/0.wxalertb", sx, rx)
        txrx.append(rset)

        opts = ["Off", "15", "30", "60"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].wxscntm)
        sx = "WX alert scan memory time (Mins)"
        rset = RadioSetting("pmg/0.wxscntm", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "wxscntm")
        txrx.append(rset)

        # ===== DTMF GROUP =====
        rx = RadioSettingValueBoolean(bool(_pmg[0].dtmfhld))
        sx = "DTMF hold"
        rset = RadioSetting("pmg/0.dtmfhld", sx, rx)
        dtmf.append(rset)

        opts = ["100", "250", "500", "750", "1000", "1500", "2000"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].dtmfpau)
        sx = "DTMF pause duration (mS)"
        rset = RadioSetting("pmg/0.dtmfpau", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "dtmfpau")
        dtmf.append(rset)

        opts = ["Fast", "Slow"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].dtmfspd)
        sx = "DTMF speed"
        rset = RadioSetting("pmg/0.dtmfspd", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "dtmfspd")
        dtmf.append(rset)

        for mx in range(0, 10):
            csx = _char_to_str(_dtmn[mx].id).strip()
            rx = RadioSettingValueString(0, 8, csx)
            sx = "DTMF %i Name (8 chars)" % mx
            rset = RadioSetting("dtmn.id/%d" % mx, sx, rx)
            rset.set_apply_callback(_pad_str, 8, chr(255), _dtmn, "id", mx)
            dtmf.append(rset)

            csx = _char_to_str(_dtmc[mx].code).strip()
            rx = RadioSettingValueString(0, 16, csx)
            sx = "    Code %i (16 chars)" % mx
            rset = RadioSetting("dtmc.code/%d" % mx, sx, rx)
            rset.set_apply_callback(_pad_str, 16, chr(255), _dtmc, "code", mx)
            dtmf.append(rset)

        # ===== MEMORY GROUP =====
        opts = ["All Bands", "Current Band"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].recall)
        sx = "Memory recall method"
        rset = RadioSetting("pmg/0.recall", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "recall")
        memz.append(rset)

        rx = RadioSettingValueString(0, 10, _char_to_str(_pmg[0].memgrplk))
        sx = "Group link"
        rset = RadioSetting("pmg/0.memgrplk", sx, rx)
        memz.append(rset)

        opts = ["Fast", "Slow"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].eclnkspd)
        sx = "Echolink speed"
        rset = RadioSetting("pmg/0.eclnkspd", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "eclnkspd")
        memz.append(rset)

        rx = RadioSettingValueBoolean(bool(_blk1.dspmemch))
        sx = "Display memory channel number"
        rset = RadioSetting("block1.dspmemch", sx, rx)
        memz.append(rset)

        # ===== REPEATER GROUP =====
        rx = RadioSettingValueBoolean(bool(_pmg[0].rptr1750))
        sx = "1750 Hz transmit hold"
        rset = RadioSetting("pmg/0.rptr1750", sx, rx)
        rptr.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].rptrofst))
        sx = "Auto repeater offset"
        rset = RadioSetting("pmg/0.rptrofst", sx, rx)
        rptr.append(rset)

        opts = ["Cross Band", "TX:A-Band / RX:B-Band", "RX:A-Band / TX:B-Band"]
        rx = RadioSettingValueList(opts, current_index=_blk1.rptrmode)
        sx = "Repeater Mode"
        rset = RadioSetting("block1.rptrmode", sx, rx)
        rset.set_apply_callback(_val_list, opts, _blk1, "rptrmode")
        rptr.append(rset)

        opts = ["Off", "Morse", "Voice"]
        rx = RadioSettingValueList(opts, current_index=_blk1.rptridx)
        sx = "Repeater ID transmit"
        rset = RadioSetting("block1.rptridx", sx, rx)
        rset.set_apply_callback(_val_list, opts, _blk1, "rptridx")
        rptr.append(rset)

        rx = RadioSettingValueString(0, 12, _char_to_str(_blk1a.rptrid))
        sx = "Repeater ID"
        rset = RadioSetting("block1a.rptrid", sx, rx)
        rptr.append(rset)

        rx = RadioSettingValueBoolean(bool(_blk1.rptrhold))
        sx = "Repeater transmit hold"
        rset = RadioSetting("block1.rptrhold", sx, rx)
        rptr.append(rset)

        # ===== Prog VFO Group =============
        for mx in range(0, 10):
            # Raw freq is 0.1 MHz resolution
            vfx = int(_pmg[0].progvfo[mx].blow) / mhz1
            if vfx == 0:
                vfx = 118
            rx = RadioSettingValueFloat(118.0, 1299.9, vfx, 0.005, 3)
            sx = "VFO-%i Low Limit (MHz)" % mx
            rset = RadioSetting("pmg/0.progvfo/%d.blow" % mx, sx, rx)
            rset.set_apply_callback(_mhz_val, _pmg, "progvfo.blow", 0, mx)
            pvfo.append(rset)

            vfx = int(_pmg[0].progvfo[mx].bhigh) / mhz1
            if vfx == 0:
                vfx = 118
            rx = RadioSettingValueFloat(118.0, 1300.0, vfx, 0.005, 3)
            sx = "   VFO-%i High Limit (MHz)" % mx
            rset = RadioSetting("pmg/0.progvfo/%d.bhigh" % mx, sx, rx)
            rset.set_apply_callback(_mhz_val, _pmg, "progvfo.bhigh", 0, mx)
            pvfo.append(rset)

        # ===== PFK GROUP =====
        opts = ["WX CH", "FRQ.BAND", "CTRL", "MONITOR", "VGS", "VOICE",
                "GROUP UP", "MENU", "MUTE", "SHIFT", "DUAL", "M>V",
                "1750 Tone"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].pf1key)
        sx = "Front panel PF1 key"
        rset = RadioSetting("pmg/0.pf1key", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "pf1key")
        pfk.append(rset)

        rx = RadioSettingValueList(opts, current_index=_pmg[0].pf2key)
        sx = "Front panel PF2 key"
        rset = RadioSetting("pmg/0.pf2key", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "pf2key")
        pfk.append(rset)

        opts = ["WX CH", "FRQ.BAND", "CTRL", "MONITOR", "VGS", "VOICE",
                "GROUP UP", "MENU", "MUTE", "SHIFT", "DUAL", "M>V",
                "VFO", "MR", "CALL", "MHz", "TONE", "REV", "LOW",
                "LOCK", "A/B", "ENTER", "1750 Tone", "M.LIST",
                "S.LIST", "MSG.NEW", "REPLY", "POS", "P.MONI",
                "BEACON", "DX", "WX"]
        rx = RadioSettingValueList(opts, current_index=_pmg[0].micpf1)
        sx = "Microphone PF1 key"
        rset = RadioSetting("pmg/0.micpf1", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "micpf1")
        pfk.append(rset)

        rx = RadioSettingValueList(opts, current_index=_pmg[0].micpf2)
        sx = "Microphone PF2 key"
        rset = RadioSetting("pmg/0.micpf2", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "micpf2")
        pfk.append(rset)

        rx = RadioSettingValueList(opts, current_index=_pmg[0].micpf3)
        sx = "Microphone PF3 key"
        rset = RadioSetting("pmg/0.micpf3", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "micpf3")
        pfk.append(rset)

        rx = RadioSettingValueList(opts, current_index=_pmg[0].micpf4)
        sx = "Microphone PF4 key"
        rset = RadioSetting("pmg/0.micpf4", sx, rx)
        rset.set_apply_callback(_val_list, opts, _pmg[0], "micpf4")
        pfk.append(rset)

        # ===== BMSK GROUP =====
        rx = RadioSettingValueBoolean(bool(_pmg[0].abnd118))
        sx = "A/Left: 118 MHz Band"
        rset = RadioSetting("pmg/0.abnd118", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].abnd144))
        sx = "A/Left: 144 MHz Band"
        rset = RadioSetting("pmg/0.abnd144", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].abnd220))
        sx = "A/Left: 220 MHz Band"
        rset = RadioSetting("pmg/0.abnd220", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].abnd300))
        sx = "A/Left: 300 MHz Band"
        rset = RadioSetting("pmg/0.abnd300", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].abnd430))
        sx = "A/Left: 430 MHz Band"
        rset = RadioSetting("pmg/0.abnd430", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].bbnd144))
        sx = "B/Right: 144 MHz Band"
        rset = RadioSetting("pmg/0.bbnd144", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].bbnd220))
        sx = "B/Right: 220 MHz Band"
        rset = RadioSetting("pmg/0.bbnd220", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].bbnd300))
        sx = "B/Right: 300 MHz Band"
        rset = RadioSetting("pmg/0.bbnd300", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].bbnd430))
        sx = "B/Right: 430 MHz Band"
        rset = RadioSetting("pmg/0.bbnd430", sx, rx)
        bmsk.append(rset)

        rx = RadioSettingValueBoolean(bool(_pmg[0].bbnd800))
        sx = "B/Right: 800 MHz Band"
        rset = RadioSetting("pmg/0.bbnd800", sx, rx)
        bmsk.append(rset)

        # ===== Sky command Group =============
        rx = RadioSettingValueString(0, 10, _char_to_str(_skyc.cmdr))
        sx = "Commandr call sign"
        rset = RadioSetting("skycmd.cmdr", sx, rx)
        rset.set_apply_callback(_pad_str, 10, chr(0), _skyc, "cmdr")
        skyk.append(rset)

        rx = RadioSettingValueString(0, 10, _char_to_str(_skyc.tptr))
        sx = "Transporter call sign"
        rset = RadioSetting("skycmd.tptr", sx, rx)
        rset.set_apply_callback(_pad_str, 10, chr(0), _skyc, "tptr")
        skyk.append(rset)

        opts = []
        for val in TMD710_TONES:
            opts.append(str(val))
        rx = RadioSettingValueList(opts, current_index=_skyc.skytone)
        sx = "Tone frequency"
        rset = RadioSetting("skycmd.skytone", sx, rx)
        rset.set_apply_callback(_val_list, opts, _skyc, "skytone")
        skyk.append(rset)

        # ===== PM MEMORY GROUP =====
        """ These 5 blocks of 512 bytes are repeats of the major settings """
        # Only showing limited settings for now...
        _pmn = self._memobj.pm_name
        for ix in range(1, 6):
            nx = ix - 1          # Names are [0-4]
            rx = RadioSettingValueString(0, 16, _char_to_str(_pmn[nx].pmname))
            sx = "PM Group %i Name" % ix
            rset = RadioSetting("pm_name/%i.pmname" % nx, sx, rx)
            rset.set_apply_callback(_pad_str, 16, chr(0xff), _pmn,
                                    "pmname", nx)
            pmm.append(rset)

            rx = RadioSettingValueString(0, 8, _char_to_str(_pmg[ix].pwron))
            sx = "-   Power-On Message"
            rset = RadioSetting("pmg/%i.pwron" % ix, sx, rx)
            rset.set_apply_callback(_pad_str, 8, chr(0xff), _pmg, "pwron", ix)
            pmm.append(rset)

            opts = ["VFO", "Mem Recall"]
            rx = RadioSettingValueList(opts, current_index=_pmg[ix].a_mr)
            sx = "-   A: Left Side VFO/MR"
            rset = RadioSetting("pmg/%i.a_mr" % ix, sx, rx)
            rset.set_apply_callback(_val_list, opts, _pmg[ix], "a_mr")
            pmm.append(rset)

            rx = RadioSettingValueInteger(0, 999, _pmg[ix].a_chn)
            sx = "-   A: Left Side MR Channel"
            rset = RadioSetting("pmg/%i.a_chn" % ix, sx, rx)
            pmm.append(rset)

            rx = RadioSettingValueList(opts, current_index=_pmg[ix].b_mr)
            sx = "-   B: Right Side VFO/MR"
            rset = RadioSetting("pmg/%i.b_mr" % ix, sx, rx)
            rset.set_apply_callback(_val_list, opts, _pmg[ix], "b_mr")
            pmm.append(rset)

            rx = RadioSettingValueInteger(0, 999, _pmg[ix].b_chn)
            sx = "-   B: Right Side MR Channel"
            rset = RadioSetting("pmg/%i.b_chn" % ix, sx, rx)
            pmm.append(rset)

            rx = RadioSettingValueInteger(0, 8, _pmg[ix].bright)
            sx = "-   Brightness level"
            rset = RadioSetting("pmg/%i.bright" % ix, sx, rx)
            pmm.append(rset)

            opts = ["Amber", "Green"]
            rx = RadioSettingValueList(opts, current_index=_pmg[ix].bkltclr)
            sx = "-   Backlight color"
            rset = RadioSetting("pmg/%i.bkltclr" % ix, sx, rx)
            rset.set_apply_callback(_val_list, opts, _pmg[ix], "bkltclr")
            pmm.append(rset)

            val = _pmg[ix].bkltcont + 1
            rx = RadioSettingValueInteger(1, 16, val)
            sx = "-   Contrast level"
            rset = RadioSetting("pmg/%i.bkltcont" % ix, sx, rx)
            rset.set_apply_callback(_adjraw, _pmg[ix], "bkltcont", -1)
            pmm.append(rset)

            opts = ["Positive", "Negative"]
            rx = RadioSettingValueList(opts, current_index=_pmg[ix].dsprev)
            sx = "-   Color mode"
            rset = RadioSetting("pmg/%i.dsprev" % ix, sx, rx)
            rset.set_apply_callback(_val_list, opts, _pmg[ix], "dsprev")
            pmm.append(rset)

            rx = RadioSettingValueBoolean(bool(_pmg[ix].beepon))
            sx = "-   Beep On"
            rset = RadioSetting("pmg/%i.beepon" % ix, sx, rx)
            pmm.append(rset)

            val = _pmg[ix].beepvol + 1     # 1-7 downloads as 0-6
            rx = RadioSettingValueInteger(1, 7, val)
            sx = "-   Beep volume (1 - 7)"
            rset = RadioSetting("pmg/%i.beepvol" % ix, sx, rx)
            rset.set_apply_callback(_adjraw, _pmg[ix], "beepvol", -1)
            pmm.append(rset)

            rx = RadioSettingValueBoolean(bool(_pmg[ix].autopm))
            sx = "-   Auto PM Store"
            rset = RadioSetting("pmg/%i.autopm" % ix, sx, rx)
            pmm.append(rset)

            opts = ["A: Left", "B: Right"]
            rx = RadioSettingValueList(opts, current_index=_pmg[ix].txband)
            sx = "-   X Side (PTT)"
            rset = RadioSetting("pmg/%i.txband" % ix, sx, rx)
            rset.set_apply_callback(_val_list, opts, _pmg[ix], "txband")
            pmm.append(rset)

            opts = ["High (50W)", "Medium (10W)", "Low (5W)"]
            rx = RadioSettingValueList(opts, current_index=_pmg[ix].a_pwr)
            sx = "-   A-Band transmit power"
            rset = RadioSetting("pmg/%i.a_pwr" % ix, sx, rx)
            rset.set_apply_callback(_val_list, opts, _pmg[ix], "a_pwr")
            pmm.append(rset)

            rx = RadioSettingValueList(opts, current_index=_pmg[ix].b_pwr)
            sx = "-   B-Band transmit power"
            rset = RadioSetting("pmg/%i.b_pwr" % ix, sx, rx)
            rset.set_apply_callback(_val_list, opts, _pmg[ix], "b_pwr")
            pmm.append(rset)

        return group       # END get_settings()

    def set_settings(self, settings):
        """ Convert UI modified changes into mem_format values """
        blks = (self._memobj.block1, self._memobj.block1a,
                self._memobj.pmg, self._memobj.pm_name)
        for _settings in blks:
            for element in settings:
                if not isinstance(element, RadioSetting):
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
                            LOG.debug("Setting %s = %s"
                                      % (setting, element.value))
                            setattr(obj, setting, element.value)
                    except Exception:
                        LOG.debug(element.get_name())
                        raise
        return

    @classmethod
    def match_model(cls, fdata, fyle):
        """ Included to prevent 'File > New' error """
        return False


@directory.register
class KenwoodTMD710Radio(KenwoodTMx710Radio):
    """ Kenwood TM-D710 VHF/UHF/APRS Radio model. """
    VENDOR = "Kenwood"
    MODEL = "TM-D710_CloneMode"
    SHORT = ""       # Quick model code

    _num_blocks = 3
    _num_packets = [0x9c, 1, 1]

    MEM_FORMAT = """
    struct chns {            // 16 bytes channel structure
    ul32  rxfreq;
    u8   tstep;
    u8   mode;
    u8   tmode:4,
        duplex:4;         // 4 = split
    u8   rtone;
    u8   ctone;
    u8   dtcs;
    ul32 offset;          // or Split mode TX freq
    u8   splitstep;
    u8   cross;           // not used
    };

    struct pm_grp {         // 512 bytes per group
    u8   unk0200;
    u8   a_mr;
    u8   unk0202;
    u8   unk0203;
    u8   unk0204;
    u8   unk0205;
    u8   unk0206;
    u8   a_pwr;
    u8   wxalerta;
    u8   asmsql;
    u8   a_chn;
    u8   unk020b;
    u8   unk020c;
    u8   b_mr;
    u8   unk020e;
    u8   unk020f;
    u8   unk0210;
    u8   unk0211;
    u8   unk0212;
    u8   b_pwr;
    u8   wxalertb;
    u8   bsmsql;
    u8   b_chn;
    u8   unk0217;
    u8   unk0218;
    u8   unk0219;
    u8   unk021a;
    u8   unk021b;
    u8   unk021c;
    u8   unk021d;
    u8   unk021e;
    u8   unk021f;
    u8   unk0220;
    u8   unk0221;
    u8   unk0222;
    u8   unk0223;
    u8   unk0224;
    u8   unk0225;
    u8   unk0226;
    u8   unk0227;
    u8   unk0228;
    u8   unk0229;
    u8   unk022a;
    u8   unk022b;
    u8   unk022c;
    u8   unk022d;
    u8   unk022e;
    u8   unk022f;
    u8   unk0230;
    u8   unk0231;
    u8   sqclogic;
    u8   txband;
    u8   single;
    u8   unk0235;
    u8   mute;
    u8   unk0237;
    u8   unk0238;
    u8   unk0239;
    u8   unk0237a;
    u8   unk023b;
    u8   unk023c;
    u8   unk023d;
    u8   unk023e;
    u8   unk023f;
    struct chns vfo[10];         // 0x0240 - 0x02df
    char pwron[8];
    u8   unk02e8;
    u8   unk02e9;
    u8   unk02ea;
    u8   unk02eb;
    u8   unk02ec;
    u8   unk02ed;
    u8   unk02ee;
    u8   unk02ef;
    char memgrplk[10];
    u8   unk02fa;
    u8   unk02fb;
    u8   unk02fc;
    u8   unk02fd;
    u8   unk02fe;
    u8   unk02ff;
    struct {
        ul32 blow;
        ul32 bhigh;
    } progvfo[10];
    u8   beepon;
    u8   beepvol;
    u8   extspkr;
    u8   ance;
    u8   lang;
    u8   vcvol;
    u8   vcspd;
    u8   pbkrpt;
    u8   pbkint;
    u8   cntrec;
    u8   vhfaip;
    u8   uhfaip;
    u8   ssqlhu;
    u8   mutehu;
    u8   beatshft;
    u8   tot;
    u8   recall;
    u8   eclnkspd;
    u8   dtmfhld;
    u8   dtmfspd;
    u8   dtmfpau;
    u8   dtmflck;
    u8   rptrofst;
    u8   rptr1750;
    u8   bright;
    u8   autobri;
    u8   bkltclr;
    u8   pf1key;
    u8   pf2key;
    u8   micpf1;
    u8   micpf2;
    u8   micpf3;
    u8   micpf4;
    u8   miclck;
    u8   unk0372;
    u8   scnrsm;
    u8   apo;
    u8   extband;
    u8   extbaud;
    u8   sqcsrc;
    u8   autopm;
    u8   dispbar;
    u8   unk037a;
    u8   bkltcont;
    u8   dsprev;
    u8   vsmode;
    u8   intband;
    u8   wxscntm;
    u8   scntot;
    u8   scncot;
    u8   unk0382;
    u8   unk0383;
    u8   unk0384;
    u8   unk0385;
    u8   unk0386;
    u8   unk0387;
    u8   unk0388;
    u8   unk0389;
    u8   unk038a;
    u8   unk038b;
    u8   unk038c;
    u8   unk038d;
    u8   unk038e;
    u8   unk038f;
    u8   abnd118;
    u8   abnd144;
    u8   abnd220;
    u8   abnd300;
    u8   abnd430;
    u8   bbnd144;
    u8   bbnd220;
    u8   bbnd300;
    u8   bbnd430;
    u8   bbnd800;
    u8   unk039a;
    u8   unk039b;
    u8   unk039c;
    u8   unk039d;
    u8   unk039e;
    u8   unk039f;
    u8   unk03a0[96];       // to 0x03ff
    };                        // end of struct pm

    #seekto 0x0000;         // block1: x000 - x023f
    struct {
    u8   unk000[16];
    u8   unk010;
    u8   unk011;
    char unk012[3];
    u8   ansbck;
    u8   pmrecall;            // 0x0016
    u8   pnlklk;
    u8   dspmemch;
    u8   m10mz;
    u8   micsens;
    u8   opband;
    u8   unk01c;
    u8   rptrmode;
    u8   rptrhold;
    u8   rptridx;
    u8   unk020;
    u8   pcbaud;
    u8   unk022;
    u8   pwdon;               //  0x0023
    u8   unk024;
    u8   unk025;
    u8   unk026;
    u8   unk027;
    u8   unk028;
    u8   unk029;
    char pswd[6];             // 0x023a - 23f
    } block1;

    #seekto 0x0030;
    struct {
    char code[16];            // @ 0x0030
    } dtmc[10];

    struct {
    char id[8];               // 0x00d0 - 0x011f
    } dtmn[10];

    struct {                    // block1a: 0x0120 - 0x023f
    u8   unk0120;
    u8   unk0121;
    u8   unk0122[78];
    char rptrid[12];          // 0x0170 - 017b
    u8   unk017c;
    u8   unk017d;
    u8   unk017e;
    u8   unk017f;
    u8   unk0180[128];        // 0x0180 - 0x01ff
    } block1a;

    struct pm_grp pmg[6];       // 0x0200 - 0x0dff

    #seekto 0x0e00;
    struct {
    u8   band;
    u8   skip;
    } chmap[1030];              // to 0x0160b

    #seekto 0x01700;            // 0x01700 - 0x0575f
    struct chns ch_mem[1030];   // 0-999 MR and 1000 -1029 Specials

    #seekto 0x05760;
    struct chns call[2];

    #seekto 0x05800;
    struct {
    char name[8];
    } ch_nam[1020];         // ends @ 0x07e0

    #seekto 0x077e0;        // 0x077e0 - 0x07830
    struct {
    char name[8];
    } wxnam[10];

    #seekto 0x07da0;
    struct {
    char pmname[16];
    } pm_name[5];

    #seekto 0x07df0;
    struct {
    char comnt[32];
    } mcpcom;

    #seekto 0x08660;
    struct {
    char cmdr[10];
    char tptr[10];
    u8  skytone;          // 0x08674
    } skycmd;
                        // data stops at 0x09b98
    """

    def _read_mem(radio):
        """ Load the memory map """
        global BAUD
        status = chirp_common.Status()
        status.cur = 0
        val = 0
        for mx in range(0, radio._num_blocks):
            val += radio._num_packets[mx]
        status.max = val
        status.msg = "Reading %i packets" % val
        radio.status_fn(status)

        data = ""

        radio.pipe.baudrate = BAUD
        cmc = b"0M PROGRAM" + TERM
        resp0 = _command(radio.pipe, cmc, 3, W8S)
        junk = radio.pipe.read(16)       # flushit
        for bkx in range(0, 0x09c):
            if bkx != 0x07f:            # Skip block 7f !!??
                cmc = struct.pack('>cHB', b'R', bkx << 8, 0)
                resp0 = _command(radio.pipe, cmc, 260, W8S)
                junk = _command(radio.pipe, ACK, 1, W8S)
                if len(resp0) < 260:
                    junk = _command(radio.pipe, b"E", 2, W8S)
                    sx = "Block 0x%x read error: " % bkx
                    sx += "Got %i bytes, expected 260." % len(resp0)
                    LOG.error(sx)
                    sx = "Block read error! Check debug.log"
                    raise errors.RadioError(sx)
                if bkx == 0:   # 1st packet of 1st block
                    mht = resp0[4:7]   # [57 00 00 00] 03 4b 01 ff ff ...
                    data = resp0[5:6]  # 2nd byte (4b) replaces 1st
                    data += resp0[5:]  # then bytes 2 on (4b 4b 01 ff ...)
                else:
                    data += resp0[4:]       # skip cmd echo
                _update_status(radio, status)        # UI Update
        cmc = struct.pack('>cHB', b'R', 0xFEF0, 0x10)
        resp0 = _command(radio.pipe, cmc, 0x014, W8S)
        data += resp0[4:]
        junk = _command(radio.pipe, ACK, 1, W8S)
        _update_status(radio, status)
        cmc = struct.pack('>cHB', b'R', 0xFF00, 0x90)
        resp0 = _command(radio.pipe, cmc, 0x094, W8S)
        data += resp0[4:]
        junk = _command(radio.pipe, ACK, 1, W8S)
        _update_status(radio, status)
        # Exit Prog mode, no TERM
        resp = _command(radio.pipe, b"E", 2, W8S)     # Rtns 06 0d
        radio.pipe.baudrate = BAUD
        return data

    def _write_mem(radio):
        """ PROG MCP Blocks Send """
        global BAUD
        # UI progress
        status = chirp_common.Status()
        status.cur = 0
        val = 0
        for mx in range(0, radio._num_blocks):
            val += radio._num_packets[mx]
        status.max = val
        status.msg = "Writing %i packets" % val
        radio.status_fn(status)

        imgadr = 0
        radio.pipe.baudrate = BAUD
        resp0 = _command(radio.pipe, b"0M PROGRAM" + TERM, 3, W8S)
        # Read block 0 magic header thingy, save it
        cmc = b"R" + bytes([0, 0, 4])
        resp0 = _command(radio.pipe, cmc, 8, W8S)
        mht0 = resp0[4:]    # Expecting [57 00 00 04] 03 4b 01 ff
        junk = _command(radio.pipe, ACK, 1, W8S)
        cmc = b"W" + bytes([0, 0, 1, 0xff])
        junk = _command(radio.pipe, cmc, 1, W8S)     # responds ACK
        cmc = b"R" + bytes([0x80, 0, 3])
        resp = _command(radio.pipe, cmc, 7, W8S)   # [57 80 00 03] 00 33 00
        mht1 = resp[4:]
        junk = _command(radio.pipe, ACK, 1, W8S)
        cmc = b"W" + bytes([0x80, 0, 1, 0xff])
        junk = _command(radio.pipe, cmc, 1, W8S)
        imgadr = 4      # After 03 4b 01 ff
        for bkx in range(0, radio._num_packets[0]):
            cmc = b"W" + bytes([bkx, 0, 0])
            imgstep = 256
            if bkx == 0:
                imgstep = 0x0fc
                cmc = b"W" + bytes([0, 4, imgstep])
                cmc += radio.get_mmap()[imgadr:imgadr + imgstep]
            else:       # after first packet
                cmc += radio.get_mmap()[imgadr:imgadr + imgstep]
            if bkx != 0x07f:        # don't send 7f !
                resp0 = _command(radio.pipe, cmc, 1, W8S)
                if resp0 != ACK:
                    LOG.error("Packet 0x%x Write error, no ACK." % bkx)
                    sx = "Radio failed to acknowledge upload packet!"
                    raise errors.RadioError(sx)
                imgadr += imgstep
            _update_status(radio, status)        # UI Update
        # write fe and ff blocks
        cmc = b"W" + bytes([0xfe, 0xf0, 16])
        cmc += radio.get_mmap()[imgadr:imgadr + 16]
        resp0 = _command(radio.pipe, cmc, 1, W8S)
        if resp0 != ACK:
            LOG.error("Packet 0xfe Write error, no ACK.")
            sx = "Radio failed to acknowledge upload packet!"
            raise errors.RadioError(sx)
        imgadr += 16
        cmc = b"W" + bytes([0xff, 0, 0x90])
        cmc += radio.get_mmap()[imgadr:imgadr + 0x090]
        resp0 = _command(radio.pipe, cmc, 1, W8S)
        if resp0 != ACK:
            LOG.error("Packet 0xff Write error, no ACK.")
            sx = "Radio failed to acknowledge upload packet!"
            raise errors.RadioError(sx)
        # Write mht1
        cmc = b"W" + bytes([0x80, 0, 3]) + mht1
        resp0 = _command(radio.pipe, cmc, 1, W8S)
        if resp0 != ACK:
            LOG.error("Mht1 Write error at 0x080 00 03 , no ACK.")
            sx = "Radio failed to acknowledge upload packet!"
            raise errors.RadioError(sx)
        # and mht0
        cmc = b"W" + bytes([0, 0, 4]) + mht0
        resp0 = _command(radio.pipe, cmc, 1, W8S)
        if resp0 != ACK:
            LOG.error("Mht0 Write error at 00 00 04 , no ACK.")
            sx = "Radio failed to acknowledge upload packet!"
            raise errors.RadioError(sx)
        # Write E to Exit PROG mode
        resp = _command(radio.pipe, b"E", 2, W8S)
        return


@directory.register
class KenwoodTMD710GRadio(KenwoodTMx710Radio):
    """ Kenwood TM-D710G VHF/UHF/GPS/APRS Radio model. """
    VENDOR = "Kenwood"
    MODEL = "TM-D710G_CloneMode"
    SHORT = "G"       # Quick model code 1 for G

    _num_blocks = 2                # Only reading first 2, not GPS logs
    _packet_size = [261, 261, 261]
    _block_addr = [0, 0x100, 0x200]       # starting addr, each block
    _num_packets = [0x7f, 0x0fe, 0x200]   # num packets per block, 0-based

    MEM_FORMAT = """
    struct chns {            // 16 bytes channel structure
    ul32  rxfreq;
    u8   tstep;
    u8   mode;
    u8   tmode:4,
        duplex:4;         // 4 = split
    u8   rtone;
    u8   ctone;
    u8   dtcs;
    u8   cross;
    ul32 offset;          // or Split mode TX freq
    u8   splitstep;
    };

    struct pm_grp {         // 512 bytes per group
    u8   unk0200;
    u8   a_mr;
    u8   unk0202;
    u8   unk0203;
    u8   unk0204;
    u8   unk0205;
    u8   unk0206;
    u8   a_pwr;
    u8   wxalerta;
    u8   asmsql;
    u8   a_chn;
    u8   unk020b;
    u8   unk020c;
    u8   b_mr;
    u8   unk020e;
    u8   unk020f;
    u8   unk0210;
    u8   unk0211;
    u8   unk0212;
    u8   b_pwr;
    u8   wxalertb;
    u8   bsmsql;
    u8   b_chn;
    u8   unk0217;
    u8   unk0218;
    u8   unk0219;
    u8   unk021a;
    u8   unk021b;
    u8   unk021c;
    u8   unk021d;
    u8   unk021e;
    u8   unk021f;
    u8   unk0220;
    u8   unk0221;
    u8   unk0222;
    u8   unk0223;
    u8   unk0224;
    u8   unk0225;
    u8   unk0226;
    u8   unk0227;
    u8   unk0228;
    u8   unk0229;
    u8   unk022a;
    u8   unk022b;
    u8   unk022c;
    u8   unk022d;
    u8   unk022e;
    u8   unk022f;
    u8   unk0230;
    u8   unk0231;
    u8   sqclogic;
    u8   txband;
    u8   single;
    u8   unk0235;
    u8   mute;
    u8   unk0237;
    u8   unk0238;
    u8   unk0239;
    u8   unk0237a;
    u8   unk023b;
    u8   unk023c;
    u8   unk023d;
    u8   unk023e;
    u8   unk023f;
    struct chns vfo[10];         // 0x0240 - 0x02df
    char pwron[8];
    u8   unk02e8;
    u8   unk02e9;
    u8   unk02ea;
    u8   unk02eb;
    u8   unk02ec;
    u8   unk02ed;
    u8   unk02ee;
    u8   unk02ef;
    char memgrplk[10];
    u8   unk02fa;
    u8   unk02fb;
    u8   unk02fc;
    u8   unk02fd;
    u8   unk02fe;
    u8   unk02ff;
    struct {
        ul32 blow;
        ul32 bhigh;
    } progvfo[10];
    u8   beepon;
    u8   beepvol;
    u8   extspkr;
    u8   ance;
    u8   lang;
    u8   vcvol;
    u8   vcspd;
    u8   pbkrpt;
    u8   pbkint;
    u8   cntrec;
    u8   vhfaip;
    u8   uhfaip;
    u8   ssqlhu;
    u8   mutehu;
    u8   beatshft;
    u8   tot;
    u8   recall;
    u8   eclnkspd;
    u8   dtmfhld;
    u8   dtmfspd;
    u8   dtmfpau;
    u8   dtmflck;
    u8   rptrofst;
    u8   rptr1750;
    u8   bright;
    u8   autobri;
    u8   bkltclr;
    u8   pf1key;
    u8   pf2key;
    u8   micpf1;
    u8   micpf2;
    u8   micpf3;
    u8   micpf4;
    u8   miclck;
    u8   unk0372;
    u8   scnrsm;
    u8   apo;
    u8   extband;
    u8   extbaud;
    u8   sqcsrc;
    u8   autopm;
    u8   dispbar;
    u8   unk037a;
    u8   bkltcont;
    u8   dsprev;
    u8   vsmode;
    u8   intband;
    u8   wxscntm;
    u8   scntot;
    u8   scncot;
    u8   unk0382;
    u8   unk0383;
    u8   unk0384;
    u8   unk0385;
    u8   unk0386;
    u8   unk0387;
    u8   unk0388;
    u8   unk0389;
    u8   unk038a;
    u8   unk038b;
    u8   unk038c;
    u8   unk038d;
    u8   unk038e;
    u8   unk038f;
    u8   abnd118;
    u8   abnd144;
    u8   abnd220;
    u8   abnd300;
    u8   abnd430;
    u8   bbnd144;
    u8   bbnd220;
    u8   bbnd300;
    u8   bbnd430;
    u8   bbnd800;
    u8   unk039a;
    u8   unk039b;
    u8   unk039c;
    u8   unk039d;
    u8   unk039e;
    u8   unk039f;
    u8   unk03a0[96];       // to 0x03ff
    };                        // end of struct pm

    #seekto 0x0000;         // block1: x000 - x023f
    struct {
    u8   unk000[16];
    u8   unk010;
    u8   unk011;
    char unk012[3];
    u8   ansbck;
    u8   pmrecall;            // 0x0016
    u8   pnlklk;
    u8   dspmemch;
    u8   m10mz;
    u8   micsens;
    u8   opband;
    u8   unk01c;
    u8   rptrmode;
    u8   rptrhold;
    u8   rptridx;
    u8   unk020;
    u8   pcbaud;
    u8   unk022;
    u8   pwdon;               //  0x0023
    u8   unk024;
    u8   unk025;
    u8   unk026;
    u8   unk027;
    u8   unk028;
    u8   unk029;
    char pswd[6];             // 0x023a - 23f
    } block1;

    #seekto 0x0030;
    struct {
    char code[16];            // @ 0x0030
    } dtmc[10];

    struct {
    char id[8];               // 0x00d0 - 0x011f
    } dtmn[10];

    struct {                    // block1a: 0x0120 - 0x023f
    u8   unk0120;
    u8   unk0121;
    u8   unk0122[78];
    char rptrid[12];          // 0x0170 - 017b
    u8   unk017c;
    u8   unk017d;
    u8   unk017e;
    u8   unk017f;
    u8   unk0180[128];        // 0x0180 - 0x01ff
    } block1a;

    struct pm_grp pmg[6];       // 0x0200 - 0x0dff

    #seekto 0x0e00;
    struct {
    u8   band;
    u8   skip;
    } chmap[1030];              // to 0x0160b

    #seekto 0x01700;            // 0x01700 - 0x0575f
    struct chns ch_mem[1030];   // 0-999 MR and 1000 -1029 Specials

    #seekto 0x058a0;
    struct chns call[2];

    #seekto 0x05900;
    struct {
    char name[8];
    } ch_nam[1020];         // ends @ 0x07840

    #seekto 0x078e0;        // 0x078e0 - 0x0792f
    struct {
    char name[8];
    } wxnam[10];

    #seekto 0x07da0;
    struct {
    char pmname[16];
    } pm_name[5];

    #seekto 0x07df0;
    struct {
    char comnt[32];
    } mcpcom;
                        // Block 1 ends @ 0x07eff
                        // Block 2 starts @ 0x07f00
    #seekto 0x08660;
    struct {
    char cmdr[10];
    char tptr[10];
    u8  skytone;          // 0x08674
    } skycmd;

    #seekto 0x10ef0;
    struct {
    u8   bmp[1896];
    u8   unk11658[8];     // 0x11658
    char bmpfyl[64];      // 0x11660
    u8   unk116a0[95];
    u8   bmpon;           // 0x116ff
    } bitmap;

                    // 2nd block ends @ 0x017cff
    """

    def _make_command(self, cmd, addr, length, data=b''):
        cmc = struct.pack('>IB', addr, length)
        return cmd + cmc[1:] + data

    def _read_mem(radio):
        """ Load the memory map """
        global BAUD
        status = chirp_common.Status()
        status.cur = 0
        val = 0
        for mx in range(0, radio._num_blocks):
            val += radio._num_packets[mx]
        status.max = val
        status.msg = "Reading %i packets" % val
        radio.status_fn(status)

        data = b""

        radio.pipe.baudrate = BAUD
        resp0 = radio.pipe.read(16)     # flush
        cmc = b"0M PROGRAM" + TERM
        resp0 = _command(radio.pipe, cmc, 3, W8S)
        if resp0[:1] == "?":        # try once more
            resp0 = _command(radio.pipe, cmc, 3, W8S)
        radio.pipe.baudrate = 57600     # PROG mode is always 57.6
        LOG.debug("Switching to 57600 baud download.")
        junk = radio.pipe.read(1)       # trailing byte
        for blkn in range(0, radio._num_blocks):
            for bkx in range(0, radio._num_packets[blkn]):
                addr = (radio._block_addr[blkn] << 8) | (bkx << 8)
                resp0 = _command(radio.pipe,
                                 radio._make_command(b'R', addr, 0),
                                 radio._packet_size[blkn], W8S)
                if len(resp0) < radio._packet_size[blkn]:
                    junk = _command(radio.pipe, b"E", 0, W8S)
                    lb = len(resp0)
                    xb = radio._packet_size[blkn]
                    sx = "Block 0x%x, 0x%x read error: " % (blkn, bkx)
                    sx += "Got %i bytes, expected %i." % (lb, xb)
                    LOG.error(sx)
                    sx = "Block read error! Check debug.log"
                    raise errors.RadioError(sx)
                if blkn == 0 and bkx == 0:   # 1st packet of 1st block
                    mht = resp0[5:9]   # Magic Header Thingy after cmd echo
                    data += mht[0:1]
                    data += b'\xff\xff\xff'
                    data += resp0[9:]
                else:
                    data += resp0[5:]       # skip cmd echo
                _update_status(radio, status)        # UI Update
        # Exit Prog mode, no TERM
        resp = _command(radio.pipe, b"E", 0, W8S)
        radio.pipe.baudrate = BAUD
        return data

    def _write_mem(radio):
        """ PROG MCP Blocks Send """
        global BAUD
        # UI progress
        status = chirp_common.Status()
        status.cur = 0
        val = 0
        for mx in range(0, radio._num_blocks):
            val += radio._num_packets[mx]
        status.max = val
        status.msg = "Writing %i packets" % val
        radio.status_fn(status)

        imgadr = 0
        radio.pipe.baudrate = BAUD
        resp0 = _command(radio.pipe, b"0M PROGRAM" + TERM, 3, W8S)
        radio.pipe.baudrate = 57600
        LOG.debug("Switching to 57600 baud upload.")
        junk = radio.pipe.read(1)
        # Read block 0 magic header thingy, save it
        addr = radio._block_addr[0] << 8
        resp0 = _command(radio.pipe,
                         radio._make_command(b'R', addr, 4),
                         16, W8S)
        mht0 = resp0[5:]
        # Now get block 1 mht
        addr = radio._block_addr[1] << 8
        resp0 = _command(radio.pipe,
                         radio._make_command(b'R', addr, 5),
                         16, W8S)
        mht1 = resp0[5:]
        for blkn in range(0, radio._num_blocks):
            for bkx in range(0, radio._num_packets[blkn]):
                addr = (radio._block_addr[blkn] << 8) | (bkx << 8)

                if bkx == 0:    # First packet of the block includes mht
                    if blkn == 0:
                        data = (b'\xff\x4b\x01\x32' +
                                radio.get_mmap()[4:imgadr + 256])
                    elif blkn == 1:
                        data = mht1 + radio.get_mmap()[imgadr + 5:imgadr +
                                                       256]
                else:       # after first packet
                    data = radio.get_mmap()[imgadr:imgadr + 256]
                cmc = radio._make_command(b'W', addr, 0, data)

                resp0 = _command(radio.pipe, cmc, 6, W8S)
                if bkx > 0 and resp0 != ACK:
                    LOG.error("Packet 0x%x Write error, no ACK!" % bkx)
                    sx = "Radio failed to acknowledge upload. "
                    sx += "See debug.log"
                    raise errors.RadioError(sx)
                imgadr += 256
                _update_status(radio, status)        # UI Update
        # Re-write magic headers
        cmc = radio._make_command(b'W', (radio._block_addr[0] << 8) | 1, 3,
                                  mht0[1:3] + b'\x32')
        resp0 = _command(radio.pipe, cmc, 1, W8S)
        cmc = radio._make_command(b'W', radio._block_addr[1] << 8, 5, mht1)
        resp0 = _command(radio.pipe, cmc, 1, W8S)
        cmc = radio._make_command(b'Z', radio._block_addr[0], 1, mht0[0:1])
        resp0 = _command(radio.pipe, cmc, 16, W8S)
        # Write E to Exit PROG mode
        resp = _command(radio.pipe, b"E", 0, W8S)
        radio.pipe.baudrate = BAUD
        return
