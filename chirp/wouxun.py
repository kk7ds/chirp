# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

"""Wouxun radios management module"""

import time
import os
from chirp import util, chirp_common, bitwise, memmap, errors, directory
from chirp.settings import RadioSetting, RadioSettingGroup, \
                RadioSettingValueBoolean, RadioSettingValueList, \
                RadioSettingValueInteger, RadioSettingValueString
from chirp.wouxun_common import wipe_memory, do_download, do_upload

FREQ_ENCODE_TABLE = [ 0x7, 0xa, 0x0, 0x9, 0xb, 0x2, 0xe, 0x1, 0x3, 0xf ]
 
def encode_freq(freq):
    """Convert frequency (4 decimal digits) to wouxun format (2 bytes)"""
    enc = 0
    div = 1000
    for i in range(0, 4):
        enc <<= 4
        enc |= FREQ_ENCODE_TABLE[ (freq/div) % 10 ]
        div /= 10
    return enc

def decode_freq(data):
    """Convert from wouxun format (2 bytes) to frequency (4 decimal digits)"""
    freq = 0
    shift = 12
    for i in range(0, 4):
        freq *= 10
        freq += FREQ_ENCODE_TABLE.index( (data>>shift) & 0xf )
        shift -= 4
        # print "data %04x freq %d shift %d" % (data, freq, shift)
    return freq

@directory.register
class KGUVD1PRadio(chirp_common.CloneModeRadio,
        chirp_common.ExperimentalRadio):
    """Wouxun KG-UVD1P,UV2,UV3"""
    VENDOR = "Wouxun"
    MODEL = "KG-UVD1P"
    _model = "KG669V"
    
    _querymodel = "HiWOUXUN\x02"
    
    CHARSET = list("0123456789") + [chr(x + ord("A")) for x in range(0, 26)] + \
        list("?+-")

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]
                    
    valid_freq = [(136000000, 175000000), (216000000, 520000000)]


    _MEM_FORMAT = """
        #seekto 0x0010;
        struct {
          lbcd rx_freq[4];
          lbcd tx_freq[4];
          ul16 rx_tone;
          ul16 tx_tone;
          u8 _3_unknown_1:4,
             bcl:1,
             _3_unknown_2:3;
          u8 splitdup:1,
             skip:1,
             power_high:1,
             iswide:1,
             _2_unknown_2:4;
          u8 unknown[2];
        } memory[199];
        
        #seekto 0x0970;
        struct {
            u16 vhf_rx_start;
            u16 vhf_rx_stop;
            u16 uhf_rx_start;
            u16 uhf_rx_stop;
            u16 vhf_tx_start;
            u16 vhf_tx_stop;
            u16 uhf_tx_start;
            u16 uhf_tx_stop;
        } freq_ranges;

        #seekto 0x0E5C;
        struct {
          u8 unknown_flag1:7,
             menu_available:1;
        } settings;

        #seekto 0x1008;
        struct {
          u8 unknown[8];
          u8 name[6];
          u8 pad[2];
        } names[199];
    """

    @classmethod
    def get_experimental_warning(cls):
        return ('This version of the Wouxun driver allows you to modify the '
                'frequency range settings of your radio. This has been tested '
                'and reports from other users indicate that it is a safe '
                'thing to do. However, modifications to this value may have '
                'unintended consequences, including damage to your device. '
                'You have been warned. Proceed at your own risk!')

    def _identify(self):
        """Do the original wouxun identification dance"""
        for _i in range(0, 5):
            self.pipe.write(self._querymodel)
            resp = self.pipe.read(9)
            if len(resp) != 9:
                print "Got:\n%s" % util.hexprint(resp)
                print "Retrying identification..."
                time.sleep(1)
                continue
            if resp[2:8] != self._model:
                raise Exception("I can't talk to this model (%s)" % 
                    util.hexprint(resp))
            return
        if len(resp) == 0:
            raise Exception("Radio not responding")
        else:
            raise Exception("Unable to identify radio")

    def _start_transfer(self):
        """Tell the radio to go into transfer mode"""
        self.pipe.write("\x02\x06")
        time.sleep(0.05)
        ack = self.pipe.read(1)
        if ack != "\x06":
            raise Exception("Radio refused transfer mode")    
    def _download(self):
        """Talk to an original wouxun and do a download"""
        try:
            self._identify()
            self._start_transfer()
            return do_download(self, 0x0000, 0x2000, 0x0040)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def _upload(self):
        """Talk to an original wouxun and do an upload"""
        try:
            self._identify()
            self._start_transfer()
            return do_upload(self, 0x0000, 0x2000, 0x0010)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)


    def sync_in(self):
        self._mmap = self._download()
        self.process_mmap()

    def sync_out(self):
        self._upload()

    def process_mmap(self):
        if len(self._mmap.get_packed()) != 8192:
            print "NOTE: Fixing old-style Wouxun image"
            # Originally, CHIRP's wouxun image had eight bytes of
            # static data, followed by the first memory at offset
            # 0x0008.  Between 0.1.11 and 0.1.12, this was fixed to 16
            # bytes of (whatever) followed by the first memory at
            # offset 0x0010, like the radio actually stores it.  So,
            # if we find one of those old ones, convert it to the new
            # format, padding 16 bytes of 0xFF in front.
            self._mmap = memmap.MemoryMap(("\xFF" * 16) + \
                                              self._mmap.get_packed()[8:8184])
        self._memobj = bitwise.parse(self._MEM_FORMAT, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
                        "Tone->Tone",
                        "Tone->DTCS",
                        "DTCS->Tone",
                        "DTCS->",
                        "->Tone",
                        "->DTCS",
                        "DTCS->DTCS",
                    ]
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_bands = self.valid_freq
        rf.valid_characters = "".join(self.CHARSET)
        rf.valid_name_length = 6
        rf.valid_duplexes = ["", "+", "-", "split", "off"]
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.has_settings = True
        rf.memory_bounds = (1, 128)
        rf.can_odd_split = True
        return rf

    def get_settings(self):
        freqranges = RadioSettingGroup("freqranges", "Freq ranges")
        top = RadioSettingGroup("top", "All Settings", freqranges)

        rs = RadioSetting("menu_available", "Menu Available",
                          RadioSettingValueBoolean(
                            self._memobj.settings.menu_available))
        top.append(rs)

        rs = RadioSetting("vhf_rx_start", "VHF RX Lower Limit (MHz)",
                          RadioSettingValueInteger(136, 174, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_rx_start)))
        freqranges.append(rs)
        rs = RadioSetting("vhf_rx_stop", "VHF RX Upper Limit (MHz)",
                          RadioSettingValueInteger(136, 174, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_rx_stop)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_rx_start", "UHF RX Lower Limit (MHz)",
                          RadioSettingValueInteger(216, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_rx_start)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_rx_stop", "UHF RX Upper Limit (MHz)",
                          RadioSettingValueInteger(216, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_rx_stop)))
        freqranges.append(rs)
        rs = RadioSetting("vhf_tx_start", "VHF TX Lower Limit (MHz)",
                          RadioSettingValueInteger(136, 174, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_tx_start)))
        freqranges.append(rs)
        rs = RadioSetting("vhf_tx_stop", "VHF TX Upper Limit (MHz)",
                          RadioSettingValueInteger(136, 174, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_tx_stop)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_tx_start", "UHF TX Lower Limit (MHz)",
                          RadioSettingValueInteger(216, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_tx_start)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_tx_stop", "UHF TX Upper Limit (MHz)",
                          RadioSettingValueInteger(216, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_tx_stop)))
        freqranges.append(rs)
        
        # tell the decoded ranges to UI
        self.valid_freq = [
            ( decode_freq(self._memobj.freq_ranges.vhf_rx_start) * 1000000, 
             (decode_freq(self._memobj.freq_ranges.vhf_rx_stop)+1) * 1000000), 
            ( decode_freq(self._memobj.freq_ranges.uhf_rx_start)  * 1000000,
             (decode_freq(self._memobj.freq_ranges.uhf_rx_stop)+1) * 1000000)]

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                if element.get_name() != "freqranges" :
                    self.set_settings(element)
                else:
                    self._set_freq_settings(element)
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()
                    print "Setting %s = %s" % (setting, element.value)
                    setattr(obj, setting, element.value)
                except Exception, e:
                    print element.get_name()
                    raise

    def _set_freq_settings(self, settings):
        for element in settings:
            try:
                setattr(self._memobj.freq_ranges,
                        element.get_name(),
                        encode_freq(int(element.value)))
            except Exception, e:
                print element.get_name()
                raise

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol
            
        if _mem.tx_tone != 0xFFFF and _mem.tx_tone > 0x2800:
            tcode, tpol = _get_dcs(_mem.tx_tone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.tx_tone != 0xFFFF:
            mem.rtone = _mem.tx_tone / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        if _mem.rx_tone != 0xFFFF and _mem.rx_tone > 0x2800:
            rcode, rpol = _get_dcs(_mem.rx_tone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rx_tone != 0xFFFF:
            mem.ctone = _mem.rx_tone / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        if mem.tmode == "DTCS":
            mem.dtcs_polarity = "%s%s" % (tpol, rpol)

        if os.getenv("CHIRP_DEBUG"):
            print "Got TX %s (%i) RX %s (%i)" % (txmode, _mem.tx_tone,
                                                 rxmode, _mem.rx_tone)

    def _is_txinh(self, _mem):
        raw_tx = ""
        for i in range(0, 4):
            raw_tx += _mem.tx_freq[i].get_raw()
        return raw_tx == "\xFF\xFF\xFF\xFF"

    def get_memory(self, number):
        _mem = self._memobj.memory[number - 1]
        _nam = self._memobj.names[number - 1]

        mem = chirp_common.Memory()
        mem.number = number

        if _mem.get_raw() == ("\xff" * 16):
            mem.empty = True
            return mem

        mem.freq = int(_mem.rx_freq) * 10
        if _mem.splitdup:
            mem.duplex = "split"
        elif self._is_txinh(_mem):
            mem.duplex = "off"
        elif int(_mem.rx_freq) < int(_mem.tx_freq):
            mem.duplex = "+"
        elif int(_mem.rx_freq) > int(_mem.tx_freq):
            mem.duplex = "-"

        if mem.duplex == "" or mem.duplex == "off":
            mem.offset = 0
        elif mem.duplex == "split":
            mem.offset = int(_mem.tx_freq) * 10
        else:
            mem.offset = abs(int(_mem.tx_freq) - int(_mem.rx_freq)) * 10

        if not _mem.skip:
            mem.skip = "S"
        if not _mem.iswide:
            mem.mode = "NFM"

        self._get_tone(_mem, mem)

        mem.power = self.POWER_LEVELS[not _mem.power_high]

        for i in _nam.name:
            if i == 0xFF:
                break
            mem.name += self.CHARSET[i]

        mem.extra = RadioSettingGroup("Extra", "extra")
        bcl = RadioSetting("BCL", "bcl",
                           RadioSettingValueBoolean(bool(_mem.bcl)))
        bcl.set_doc("Busy Channel Lockout")
        mem.extra.append(bcl)

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0xA000
            return val

        if mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
        elif mem.tmode == "Tone":
            tx_mode = mem.tmode
            rx_mode = None
        else:
            tx_mode = rx_mode = mem.tmode


        if tx_mode == "DTCS":
            _mem.tx_tone = mem.tmode != "DTCS" and \
                _set_dcs(mem.dtcs, mem.dtcs_polarity[0]) or \
                _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[0])
        elif tx_mode:
            _mem.tx_tone = tx_mode == "Tone" and \
                int(mem.rtone * 10) or int(mem.ctone * 10)
        else:
            _mem.tx_tone = 0xFFFF

        if rx_mode == "DTCS":
            _mem.rx_tone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
        elif rx_mode:
            _mem.rx_tone = int(mem.ctone * 10)
        else:
            _mem.rx_tone = 0xFFFF

        if os.getenv("CHIRP_DEBUG"):
            print "Set TX %s (%i) RX %s (%i)" % (tx_mode, _mem.tx_tone,
                                                 rx_mode, _mem.rx_tone)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        _nam = self._memobj.names[mem.number - 1]

        if mem.empty:
            wipe_memory(_mem, "\xFF")
            return

        if _mem.get_raw() == ("\xFF" * 16):
            wipe_memory(_mem, "\x00")

        _mem.rx_freq = int(mem.freq / 10)
        if mem.duplex == "split":
            _mem.tx_freq = int(mem.offset / 10)
        elif mem.duplex == "off":
            for i in range(0, 4):
                _mem.tx_freq[i].set_raw("\xFF")
        elif mem.duplex == "+":
            _mem.tx_freq = int(mem.freq / 10) + int(mem.offset / 10)
        elif mem.duplex == "-":
            _mem.tx_freq = int(mem.freq / 10) - int(mem.offset / 10)
        else:
            _mem.tx_freq = int(mem.freq / 10)
        _mem.splitdup = mem.duplex == "split"
        _mem.skip = mem.skip != "S"
        _mem.iswide = mem.mode != "NFM"

        self._set_tone(mem, _mem)

        if mem.power:
            _mem.power_high = not self.POWER_LEVELS.index(mem.power)
        else:
            _mem.power_high = True

        _nam.name = [0xFF] * 6
        for i in range(0, len(mem.name)):
            try:
                _nam.name[i] = self.CHARSET.index(mem.name[i])
            except IndexError:
                raise Exception("Character `%s' not supported")

        for setting in mem.extra:
            setattr(_mem, setting.get_shortname(), setting.value)

    @classmethod
    def match_model(cls, filedata, filename):
        # New-style image (CHIRP 0.1.12)
        if len(filedata) == 8192 and \
                filedata[0x60:0x64] != "2009" and \
                filedata[0x1f77:0x1f7d] == "\xff\xff\xff\xff\xff\xff" and \
                filedata[0x0d70:0x0d80] == "\xff\xff\xff\xff\xff\xff\xff\xff" \
                                           "\xff\xff\xff\xff\xff\xff\xff\xff": 
                # those areas are (seems to be) unused
            return True
        # Old-style image (CHIRP 0.1.11)
        if len(filedata) == 8200 and \
                filedata[0:4] == "\x01\x00\x00\x00":
            return True
        return False

@directory.register
class KGUV6DRadio(KGUVD1PRadio):
    """Wouxun KG-UV6 (D and X variants)"""
    MODEL = "KG-UV6"
    
    _querymodel = "HiWXUVD1\x02"
    
    _MEM_FORMAT = """
        #seekto 0x0010;
        struct {
          lbcd rx_freq[4];
          lbcd tx_freq[4];
          ul16 rx_tone;
          ul16 tx_tone;
          u8 _3_unknown_1:4,
             bcl:1,
             _3_unknown_2:3;
          u8 splitdup:1,
             skip:1,
             power_high:1,
             iswide:1,
             _2_unknown_2:4;
          u8 pad[2];
        } memory[199];

        #seekto 0x0F00;
        struct {
          char welcome1[6];
          char welcome2[6];
          char single_band[6];
        } strings;

        #seekto 0x0F20;
        struct {
          u8 unknown_flag_01:6,
             vfo_b_ch_disp:2;
          u8 unknown_flag_02:5,
             vfo_a_fr_step:3;
          u8 unknown_flag_03:4,
             vfo_a_squelch:4;
          u8 unknown_flag_04:7,
             power_save:1;
          u8 unknown_flag_05:5,
             pf2_function:3;
          u8 unknown_flag_06:6,
             roger_beep:2;
          u8 unknown_flag_07:2,
             transmit_time_out:6;
          u8 unknown_flag_08:4,
             vox:4;
          u8 unknown_1[4];
          u8 unknown_flag_09:6,
             voice:2;
          u8 unknown_flag_10:7,
             beep:1;
          u8 unknown_flag_11:7,
             ani_id_enable:1;
          u8 unknown_2[2];
          u8 unknown_flag_12:5,
             vfo_b_fr_step:3;
          u8 unknown_3[1];
          u8 unknown_flag_13:3,
             ani_id_tx_delay:5;
          u8 unknown_4[1];
          u8 unknown_flag_14:6,
             ani_id_sidetone:2;
          u8 unknown_flag_15:4,
             tx_time_out_alert:4;
          u8 unknown_flag_16:6,
             vfo_a_ch_disp:2;
          u8 unknown_flag_15:6,
             scan_mode:2;
          u8 unknown_flag_16:7,
             kbd_lock:1;
          u8 unknown_flag_17:6,
             ponmsg:2;
          u8 unknown_flag_18:5,
             pf1_function:3;
          u8 unknown_5[1];
          u8 unknown_flag_19:7,
             auto_backlight:1;
          u8 unknown_flag_20:7,
             sos_ch:1;
          u8 unknown_6[2];
          u8 unknown_flag_21:7,
             auto_lock_kbd:1;
          u8 unknown_flag_22:4,
             vfo_b_squelch:4;
          u8 unknown_7[1];
          u8 unknown_flag_23:7,
             stopwatch:1;
          u8 vfo_a_cur_chan;
          u8 unknown_flag_24:7,
             dual_band_receive:1;
          u8 current_vfo:1,
             unknown_flag_24:7;
          u8 unknown_8[2];
          u8 mode_password[6];
          u8 reset_password[6];
          u8 ani_id_content[6];
          u8 unknown_flag_25:7,
             menu_available:1;
          u8 unknown_9[1];
          u8 priority_chan;
          u8 vfo_b_cur_chan;
        } settings;

        #seekto 0x0f60;
        struct {
          lbcd rx_freq[4];
          lbcd tx_freq[4];
          ul16 rx_tone;
          ul16 tx_tone;
          u8 _3_unknown_3:4,
             bcl:1,
             _3_unknown_4:3;
          u8 splitdup:1,
             _2_unknown_3:1,
             power_high:1,
             iswide:1,
             _2_unknown_4:4;
          u8 pad[2];
        } vfo_settings[2];
	
        #seekto 0x0f80;
        u16 fm_presets_0[9];

        #seekto 0x0ff0;
        struct {
            u16 vhf_rx_start;
            u16 vhf_rx_stop;
            u16 uhf_rx_start;
            u16 uhf_rx_stop;
            u16 vhf_tx_start;
            u16 vhf_tx_stop;
            u16 uhf_tx_start;
            u16 uhf_tx_stop;
        } freq_ranges;

        #seekto 0x1010;
        struct {
          u8 name[6];
          u8 pad[10];
        } names[199];

        #seekto 0x1f60;
        struct {
            u8 unknown_flag_26:6,
               tx_offset_dir:2;
            u8 tx_offset[6];
            u8 pad[9];
        } vfo_offset[2];

        #seekto 0x1f80;
        u16 fm_presets_1[9];
    """


    def get_features(self):
        rf = KGUVD1PRadio.get_features(self)
        rf.memory_bounds = (1, 199)
        return rf

    def get_settings(self):
        top = KGUVD1PRadio.get_settings(self)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += " "
            return filtered

        # add some radio specific settings
        options = ["Off", "Welcome", "V bat"]
        rs = RadioSetting("ponmsg", "Poweron message",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.ponmsg]))
        top.append(rs)
        rs = RadioSetting("strings.welcome1", "Power-On Message 1",
                          RadioSettingValueString(0, 6, _filter(self._memobj.strings.welcome1)))
        top.append(rs)
        rs = RadioSetting("strings.welcome2", "Power-On Message 2",
                          RadioSettingValueString(0, 6, _filter(self._memobj.strings.welcome2)))
        top.append(rs)
        rs = RadioSetting("strings.single_band", "Single Band Message",
                          RadioSettingValueString(0, 6, _filter(self._memobj.strings.single_band)))
        top.append(rs)
        options = ["Channel", "ch/freq","Name", "VFO"]
        rs = RadioSetting("vfo_a_ch_disp", "VFO A Channel disp mode",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.vfo_a_ch_disp]))
        top.append(rs)
        rs = RadioSetting("vfo_b_ch_disp", "VFO B Channel disp mode",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.vfo_b_ch_disp]))
        top.append(rs)
	# TODO - vfo_a_fr_step
	# TODO -vfo_b_fr_step:3;
        rs = RadioSetting("vfo_a_squelch", "VFO A Squelch",
                          RadioSettingValueInteger(0, 9, self._memobj.settings.vfo_a_squelch))
        top.append(rs)
        rs = RadioSetting("vfo_b_squelch", "VFO B Squelch",
                          RadioSettingValueInteger(0, 9, self._memobj.settings.vfo_b_squelch))
        top.append(rs)
        rs = RadioSetting("vfo_a_cur_chan", "VFO A current channel",
                          RadioSettingValueInteger(1, 199, self._memobj.settings.vfo_a_cur_chan))
        top.append(rs)
        rs = RadioSetting("vfo_b_cur_chan", "VFO B current channel",
                          RadioSettingValueInteger(0, 199, self._memobj.settings.vfo_b_cur_chan))
        top.append(rs)
        rs = RadioSetting("priority_chan", "Priority channel",
                          RadioSettingValueInteger(0, 199, self._memobj.settings.priority_chan))
        top.append(rs)
        rs = RadioSetting("power_save", "Power save",
                          RadioSettingValueBoolean(self._memobj.settings.power_save))
        top.append(rs)
        options = ["Off", "Scan", "Lamp", "SOS", "Radio"]
        rs = RadioSetting("pf1_function", "PF1 Function select",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.pf1_function]))
        top.append(rs)
        options = ["Off", "Radio", "fr/ch", "Rpt", "Stopwatch", "Lamp", "SOS"]
        rs = RadioSetting("pf2_function", "PF2 Function select",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.pf2_function]))
        top.append(rs)
        options = ["Off", "Begin", "End", "Both"]
        rs = RadioSetting("roger_beep", "Roger beep select",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.roger_beep]))
        top.append(rs)
        # TODO - transmit_time_out:6;
        rs = RadioSetting("vox", "Vox",
                          RadioSettingValueInteger(0, 10, self._memobj.settings.vox))
        top.append(rs)
        options = ["Off", "Chinese", "English"]
        rs = RadioSetting("voice", "Voice",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.voice]))
        top.append(rs)
        rs = RadioSetting("beep", "Beep",
                          RadioSettingValueBoolean(self._memobj.settings.beep))
        top.append(rs)
        rs = RadioSetting("ani_id_enable", "ANI id enable",
                          RadioSettingValueBoolean(self._memobj.settings.ani_id_enable))
        top.append(rs)
        rs = RadioSetting("ani_id_tx_delay", "ANI id tx delay",
                          RadioSettingValueInteger(0, 30, self._memobj.settings.ani_id_tx_delay))
        top.append(rs)
        options = ["Off", "Key", "ANI", "Key+ANI"]
        rs = RadioSetting("ani_id_sidetone", "ANI id sidetone",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.ani_id_sidetone]))
        top.append(rs)
        # TODO tx_time_out_alert:4;
        options = ["Time", "Carrier", "Search"]
        rs = RadioSetting("scan_mode", "Scan mode",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.scan_mode]))
        top.append(rs)
        rs = RadioSetting("kbd_lock", "Keyboard lock",
                          RadioSettingValueBoolean(self._memobj.settings.kbd_lock))
        top.append(rs)
        rs = RadioSetting("auto_lock_kbd", "Auto lock keyboard",
                          RadioSettingValueBoolean(self._memobj.settings.auto_lock_kbd))
        top.append(rs)
        rs = RadioSetting("auto_backlight", "Auto backlight",
                          RadioSettingValueBoolean(self._memobj.settings.auto_backlight))
        top.append(rs)
        options = ["CH A", "CH B"]
        rs = RadioSetting("sos_ch", "SOS CH",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.sos_ch]))
        top.append(rs)
        rs = RadioSetting("stopwatch", "Stopwatch",
                          RadioSettingValueBoolean(self._memobj.settings.stopwatch))
        top.append(rs)
        rs = RadioSetting("dual_band_receive", "Dual band receive",
                          RadioSettingValueBoolean(self._memobj.settings.dual_band_receive))
        top.append(rs)
        options = ["VFO A", "VFO B"]
        rs = RadioSetting("current_vfo", "Current VFO",
                          RadioSettingValueList(options,
                                        options[self._memobj.settings.current_vfo]))
        top.append(rs)
        _pwd = self._memobj.settings.mode_password
        rs = RadioSetting("mode_password", "Mode password (000000 disabled)",
                  RadioSettingValueInteger(0, 9, _pwd[0]),
                  RadioSettingValueInteger(0, 9, _pwd[1]),
                  RadioSettingValueInteger(0, 9, _pwd[2]),
                  RadioSettingValueInteger(0, 9, _pwd[3]),
                  RadioSettingValueInteger(0, 9, _pwd[4]),
                  RadioSettingValueInteger(0, 9, _pwd[5]))
        top.append(rs)
        _pwd = self._memobj.settings.reset_password
        rs = RadioSetting("reset_password", "Reset password (000000 disabled)",
                  RadioSettingValueInteger(0, 9, _pwd[0]),
                  RadioSettingValueInteger(0, 9, _pwd[1]),
                  RadioSettingValueInteger(0, 9, _pwd[2]),
                  RadioSettingValueInteger(0, 9, _pwd[3]),
                  RadioSettingValueInteger(0, 9, _pwd[4]),
                  RadioSettingValueInteger(0, 9, _pwd[5]))
        top.append(rs)
        try:
            _ani = self._memobj.settings.ani_id_content
            rs = RadioSetting("ani_id_content", "ANI Code",
                              RadioSettingValueInteger(0, 9, _ani[0]),
                              RadioSettingValueInteger(0, 9, _ani[1]),
                              RadioSettingValueInteger(0, 9, _ani[2]),
                              RadioSettingValueInteger(0, 9, _ani[3]),
                              RadioSettingValueInteger(0, 9, _ani[4]),
                              RadioSettingValueInteger(0, 9, _ani[5]))
            top.append(rs)
        except Exception:
            print ("Your ANI code is not five digits, which is not currently"
                   " supported in CHIRP.")            

        return top

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) == 8192 and \
                filedata[0x1f77:0x1f7d] == "WELCOM":
            return True
        return False

@directory.register
class KG816Radio(KGUVD1PRadio,
        chirp_common.ExperimentalRadio):
    """Wouxun KG816"""
    MODEL = "KG816"

    _MEM_FORMAT = """
        #seekto 0x0010;
        struct {
          lbcd rx_freq[4];
          lbcd tx_freq[4];
          ul16 rx_tone;
          ul16 tx_tone;
          u8 _3_unknown_1:4,
             bcl:1,
             _3_unknown_2:3;
          u8 splitdup:1,
             skip:1,
             power_high:1,
             iswide:1,
             _2_unknown_2:4;
          u8 unknown[2];
        } memory[199];
        
        #seekto 0x0d70;
        struct {
            u16 vhf_rx_start;
            u16 vhf_rx_stop;
            u16 uhf_rx_start;
            u16 uhf_rx_stop;
            u16 vhf_tx_start;
            u16 vhf_tx_stop;
            u16 uhf_tx_start;
            u16 uhf_tx_stop;
        } freq_ranges;

        #seekto 0x1010;
        struct {
		u8 name[6];
		u8 pad[10];
        } names[199];
	
    """

    @classmethod
    def get_experimental_warning(cls):
        return ('We have not that much information on this model '
                'up to now we only know it has the same memory '
                'organization of KGUVD1 but uses 199 memories. '
                'it has been reported to work but '
                'proceed at your own risk!')
    
    def get_features(self):
        rf = KGUVD1PRadio.get_features(self)
        rf.memory_bounds = (1, 199) # this is the only known difference
        return rf

    def get_settings(self):
        freqranges = RadioSettingGroup("freqranges", "Freq ranges (read only)")
        top = RadioSettingGroup("top", "All Settings", freqranges)

        rs = RadioSetting("vhf_rx_start", "vhf rx start",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_rx_start)))
        freqranges.append(rs)
        rs = RadioSetting("vhf_rx_stop", "vhf rx stop",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_rx_stop)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_rx_start", "uhf rx start",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_rx_start)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_rx_stop", "uhf rx stop",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_rx_stop)))
        freqranges.append(rs)
        rs = RadioSetting("vhf_tx_start", "vhf tx start",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_tx_start)))
        freqranges.append(rs)
        rs = RadioSetting("vhf_tx_stop", "vhf tx stop",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.vhf_tx_stop)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_tx_start", "uhf tx start",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_tx_start)))
        freqranges.append(rs)
        rs = RadioSetting("uhf_tx_stop", "uhf tx stop",
                          RadioSettingValueInteger(136, 520, 
                                decode_freq(
                                    self._memobj.freq_ranges.uhf_tx_stop)))
        freqranges.append(rs)
        
        # tell the decoded ranges to UI
        self.valid_freq = [
            ( decode_freq(self._memobj.freq_ranges.vhf_rx_start) * 1000000, 
             (decode_freq(self._memobj.freq_ranges.vhf_rx_stop)+1) * 1000000)]

        return top

    @classmethod
    def match_model(cls, filedata, filename):
        if len(filedata) == 8192 and \
                filedata[0x60:0x64] != "2009" and \
                filedata[0x1f77:0x1f7d] == "\xff\xff\xff\xff\xff\xff" and \
                filedata[0x0d70:0x0d80] != "\xff\xff\xff\xff\xff\xff\xff\xff" \
                                           "\xff\xff\xff\xff\xff\xff\xff\xff": 
            return True
        return False

