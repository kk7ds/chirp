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

import time
import os
import logging

from chirp.drivers import yaesu_clone
from chirp import chirp_common, memmap, bitwise, directory, errors
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettingValueFloat, RadioSettings
from textwrap import dedent

LOG = logging.getLogger(__name__)

ACK = "\x06"


def _send(pipe, data):
    pipe.write(data)
    echo = pipe.read(len(data))
    if echo != data:
        raise errors.RadioError("Error reading echo (Bad cable?)")


def _download(radio):
    data = ""
    for i in range(0, 10):
        chunk = radio.pipe.read(8)
        if len(chunk) == 8:
            data += chunk
            break
        elif chunk:
            raise Exception("Received invalid response from radio")
        time.sleep(1)
        LOG.info("Trying again...")

    if not data:
        raise Exception("Radio is not responding")

    _send(radio.pipe, ACK)

    for i in range(0, 448):
        chunk = radio.pipe.read(64)
        data += chunk
        _send(radio.pipe, ACK)
        if len(chunk) == 1 and i == 447:
            break
        elif len(chunk) != 64:
            raise Exception("Reading block %i was short (%i)" %
                            (i, len(chunk)))
        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = i * 64
            status.max = radio.get_memsize()
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    return memmap.MemoryMap(data)


def _upload(radio):
    _send(radio.pipe, radio.get_mmap()[0:8])

    ack = radio.pipe.read(1)
    if ack != ACK:
        raise Exception("Radio did not respond")

    for i in range(0, 448):
        offset = 8 + (i * 64)
        _send(radio.pipe, radio.get_mmap()[offset:offset + 64])
        ack = radio.pipe.read(1)
        if ack != ACK:
            raise Exception(_("Radio did not ack block %i") % i)

        if radio.status_fn:
            status = chirp_common.Status()
            status.cur = offset + 64
            status.max = radio.get_memsize()
            status.msg = "Cloning to radio"
            radio.status_fn(status)


def _decode_freq(freqraw):
    freq = int(freqraw) * 10000
    if freq > 8000000000:
        freq = (freq - 8000000000) + 5000

    if freq > 4000000000:
        freq -= 4000000000
        for i in range(0, 3):
            freq += 2500
            if chirp_common.required_step(freq) == 12.5:
                break

    return freq


def _encode_freq(freq):
    freqraw = freq / 10000
    flags = 0x00
    if ((freq / 1000) % 10) >= 5:
        flags += 0x80
    if chirp_common.is_fractional_step(freq):
        flags += 0x40
    return freqraw, flags


def _decode_name(mem):
    name = ""
    for i in mem:
        if i == 0xFF:
            break
        try:
            name += CHARSET[i]
        except IndexError:
            LOG.error("Unknown char index: %i " % (i))
    return name


def _encode_name(mem):
    name = [None] * 6
    for i in range(0, 6):
        try:
            name[i] = CHARSET.index(mem[i])
        except IndexError:
            name[i] = CHARSET.index(" ")

    return name


MEM_FORMAT = """
#seekto 0x0024;
struct {
  u8 apo;
  u8 x25:3,
     tot:5;
  u8 x26;
  u8 x27;
  u8 x28:4,
     rf_sql:4;
  u8 x29:4,
     int_cd:4;
  u8 x2A:4,
     int_mr:4;
  u8 x2B:5,
     lock:3;
  u8 x2C:5,
     dt_dly:3;
  u8 x2D:7,
     dt_spd:1;
  u8 ar_bep;
  u8 x2F:6,
     lamp:2;
  u8 x30:5,
     bell:3;
  u8 x31:5,
     rxsave:3;
  u8 x32;
  u8 x33;
  u8 x34;
  u8 x35;
  u8 x36;
  u8 x37;
  u8 wx_alt:1,
     x38_1:3,
     ar_int:1,
     x38_5:3;
  u8 x39:3,
     ars:1,
     vfo_bnd:1,
     dcs_nr:2,
     ssrch:1;
  u8 pri_rvt:1,
     x3A_1:1,
     beep_sc:1,
     edg_bep:1,
     beep_key:1,
     inet:2,
     x3A_7:1;
  u8 x3B_0:5,
     scn_md:1,
     x3B_6:2;
  u8 x3C_0:2,
     rev_hm:1,
     mt_cl:1
     resume:2,
     txsave:1,
     pag_abk:1;
  u8 x3D_0:1,
     scn_lmp:1,
     x3D_2:1,
     bsy_led:1,
     x3D_4:1,
     tx_led:1,
     x3D_6:2;
  u8 x3E_0:2,
     bclo:1,
     x3E_3:5;
} settings;

#seekto 0x09E;
ul16 mbs;

#seekto 0x0C8;
struct {
  u8 memory[16];
} dtmf[9];

struct mem {
  u8 used:1,
     unknown1:1,
     isnarrow:1,
     isam:1,
     duplex:4;
  bbcd freq[3];
  u8 unknown2:1,
     step:3,
     unknown2_1:1,
     tmode:3;
  bbcd tx_freq[3];
  u8 power:2,
     tone:6;
  u8 unknown4:1,
     dtcs:7;
  u8 unknown5;
  u16 unknown5_1:1
      offset:15;
  u8 unknown6[3];
};

#seekto 0x0248;
struct mem memory[1000];

#seekto 0x40c8;
struct mem pms[100];

#seekto 0x6EC8;
// skips:2 for Memory M in [1, 1000] is in flags[(M-1)/4].skip((M-1)%4).
// Interpret with SKIPS[].
// PMS memories L0 - U50 aka memory 1001 - 1100 don't have skip flags.
struct {
  u8 skip3:2,
     skip2:2,
     skip1:2,
     skip0:2;
} flags[250];

#seekto 0x4708;
struct {
  u8 name[6];
  u8 use_name:1,
     unknown1:7;
  u8 valid:1,
     unknown2:7;
} names[1000];

#seekto 0x69C8;
struct {
  bbcd memory[128];
} banks[10];

#seekto 0x6FC8;
u8 checksum;
"""

DUPLEX = ["", "", "-", "+", "split", "off"]
TMODES = ["", "Tone", "TSQL", "TSQL-R", "DTCS"]
POWER_LEVELS = [chirp_common.PowerLevel("High", watts=5.0),
                chirp_common.PowerLevel("Mid", watts=2.0),
                chirp_common.PowerLevel("Low", watts=0.5)]
STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
SKIPS = ["", "S", "P"]
DTMF_CHARS = list("0123456789ABCD*#")
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ !`o$%&'()*+,-./|;/=>?@[u]^_"
SPECIALS = ["%s%d" % (c, i + 1) for i in range(0, 50) for c in ('L', 'U')]


class FT60BankModel(chirp_common.BankModel):

    def get_num_mappings(self):
        return 10

    def get_mappings(self):
        banks = []
        for i in range(0, self.get_num_mappings()):
            bank = chirp_common.Bank(self, "%i" % (i + 1), "Bank %i" % (i + 1))
            bank.index = i
            banks.append(bank)
        return banks

    def add_memory_to_mapping(self, memory, bank):
        number = (memory.number - 1) / 8
        mask = 1 << ((memory.number - 1) & 7)
        self._radio._memobj.banks[bank.index].memory[number].set_bits(mask)

    def remove_memory_from_mapping(self, memory, bank):
        number = (memory.number - 1) / 8
        mask = 1 << ((memory.number - 1) & 7)
        m = self._radio._memobj.banks[bank.index].memory[number]
        if m.get_bits(mask) != mask:
            raise Exception("Memory %i is not in bank %s." %
                            (memory.number, bank))
        self._radio._memobj.banks[bank.index].memory[number].clr_bits(mask)

    def get_mapping_memories(self, bank):
        memories = []
        for i in range(*self._radio.get_features().memory_bounds):
            number = (i - 1) / 8
            mask = 1 << ((i - 1) & 7)
            m = self._radio._memobj.banks[bank.index].memory[number]
            if m.get_bits(mask) == mask:
                memories.append(self._radio.get_memory(i))
        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            number = (memory.number - 1) / 8
            mask = 1 << ((memory.number - 1) & 7)
            m = self._radio._memobj.banks[bank.index].memory[number]
            if m.get_bits(mask) == mask:
                banks.append(bank)
        return banks


@directory.register
class FT60Radio(yaesu_clone.YaesuCloneModeRadio):

    """Yaesu FT-60"""
    BAUD_RATE = 9600
    VENDOR = "Yaesu"
    MODEL = "FT-60"
    _model = "AH017"

    _memsize = 28617

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(dedent("""\
1. Turn radio off.
2. Connect cable to MIC/SP jack.
3. Press and hold in the [MONI] switch while turning the
     radio on.
4. Rotate the DIAL job to select "F8 CLONE".
5. Press the [F/W] key momentarily.
6. <b>After clicking OK</b>, hold the [PTT] switch
     for one second to send image."""))
        rp.pre_upload = _(dedent("""\
1. Turn radio off.
2. Connect cable to MIC/SP jack.
3. Press and hold in the [MONI] switch while turning the
     radio on.
4. Rotate the DIAL job to select "F8 CLONE".
5. Press the [F/W] key momentarily.
6. Press the [MONI] switch ("--RX--" will appear on the LCD)."""))
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (1, 1000)
        rf.valid_duplexes = DUPLEX[1:]
        rf.valid_tmodes = TMODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tuning_steps = STEPS
        rf.valid_skips = SKIPS
        rf.valid_special_chans = SPECIALS
        rf.valid_characters = CHARSET
        rf.valid_name_length = 6
        rf.valid_modes = ["FM", "NFM", "AM"]
        rf.valid_bands = [(108000000, 520000000), (700000000, 999990000)]
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_bank = True
        rf.has_settings = True
        rf.has_dtcs_polarity = False

        return rf

    def get_bank_model(self):
        return FT60BankModel(self)

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, 0x6FC7)]

    def sync_in(self):
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()
        self.check_checksums()

    def sync_out(self):
        self.update_checksums()
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception, e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_settings(self):
        _settings = self._memobj.settings

        repeater = RadioSettingGroup("repeater", "Repeater Settings")
        ctcss = RadioSettingGroup("ctcss", "CTCSS/DCS/DTMF Settings")
        arts = RadioSettingGroup("arts", "ARTS Settings")
        scan = RadioSettingGroup("scan", "Scan Settings")
        power = RadioSettingGroup("power", "Power Saver Settings")
        wires = RadioSettingGroup("wires", "WiRES(tm) Settings")
        eai = RadioSettingGroup("eai", "EAI/EPCS Settings")
        switch = RadioSettingGroup("switch", "Switch/Knob Settings")
        misc = RadioSettingGroup("misc", "Miscellaneous Settings")
        mbls = RadioSettingGroup("banks", "Memory Bank Link Scan")

        setmode = RadioSettings(repeater, ctcss, arts, scan, power,
                                wires, eai, switch, misc, mbls)

        # APO
        opts = ["OFF"] + ["%0.1f" % (x * 0.5) for x in range(1, 24 + 1)]
        misc.append(
            RadioSetting(
                "apo", "Automatic Power Off",
                RadioSettingValueList(opts, opts[_settings.apo])))

        # AR.BEP
        opts = ["OFF", "INRANG", "ALWAYS"]
        arts.append(
            RadioSetting(
                "ar_bep", "ARTS Beep",
                RadioSettingValueList(opts, opts[_settings.ar_bep])))

        # AR.INT
        opts = ["25 SEC", "15 SEC"]
        arts.append(
            RadioSetting(
                "ar_int", "ARTS Polling Interval",
                RadioSettingValueList(opts, opts[_settings.ar_int])))

        # ARS
        opts = ["OFF", "ON"]
        repeater.append(
            RadioSetting(
                "ars", "Automatic Repeater Shift",
                RadioSettingValueList(opts, opts[_settings.ars])))

        # BCLO
        opts = ["OFF", "ON"]
        misc.append(RadioSetting(
            "bclo", "Busy Channel Lock-Out",
            RadioSettingValueList(opts, opts[_settings.bclo])))

        # BEEP
        opts = ["OFF", "KEY", "KEY+SC"]
        rs = RadioSetting(
            "beep_key", "Enable the Beeper",
            RadioSettingValueList(
                opts, opts[_settings.beep_key + _settings.beep_sc]))

        def apply_beep(s, obj):
            setattr(obj, "beep_key",
                    (int(s.value) & 1) or ((int(s.value) >> 1) & 1))
            setattr(obj, "beep_sc", (int(s.value) >> 1) & 1)
        rs.set_apply_callback(apply_beep, self._memobj.settings)
        switch.append(rs)

        # BELL
        opts = ["OFF", "1T", "3T", "5T", "8T", "CONT"]
        ctcss.append(RadioSetting("bell", "Bell Repetitions",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.bell])))

        # BSY.LED
        opts = ["ON", "OFF"]
        misc.append(RadioSetting("bsy_led", "Busy LED",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.bsy_led])))

        # DCS.NR
        opts = ["TR/X N", "RX R", "TX R", "T/RX R"]
        ctcss.append(RadioSetting("dcs_nr", "\"Inverted\" DCS Code Decoding",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.dcs_nr])))

        # DT.DLY
        opts = ["50 MS", "100 MS", "250 MS", "450 MS", "750 MS", "1000 MS"]
        ctcss.append(RadioSetting("dt_dly", "DTMF Autodialer Delay Time",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.dt_dly])))

        # DT.SPD
        opts = ["50 MS", "100 MS"]
        ctcss.append(RadioSetting("dt_spd", "DTMF Autodialer Sending Speed",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.dt_spd])))

        # DT.WRT
        for i in range(0, 9):
            dtmf = self._memobj.dtmf[i]
            str = ""
            for c in dtmf.memory:
                if c == 0xFF:
                    break
                if c < len(DTMF_CHARS):
                    str += DTMF_CHARS[c]
            val = RadioSettingValueString(0, 16, str, False)
            val.set_charset(DTMF_CHARS + list("abcd"))
            rs = RadioSetting("dtmf_%i" % i,
                              "DTMF Autodialer Memory %i" % (i + 1), val)

            def apply_dtmf(s, obj):
                str = s.value.get_value().upper().rstrip()
                val = [DTMF_CHARS.index(x) for x in str]
                for x in range(len(val), 16):
                    val.append(0xFF)
                obj.memory = val
            rs.set_apply_callback(apply_dtmf, dtmf)
            ctcss.append(rs)

        # EDG.BEP
        opts = ["OFF", "ON"]
        misc.append(RadioSetting("edg_bep", "Band Edge Beeper",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.edg_bep])))

        # I.NET
        opts = ["OFF", "COD", "MEM"]
        rs = RadioSetting("inet", "Internet Link Connection",
                          RadioSettingValueList(
                              opts, opts[_settings.inet - 1]))

        def apply_inet(s, obj):
            setattr(obj, s.get_name(), int(s.value) + 1)
        rs.set_apply_callback(apply_inet, self._memobj.settings)
        wires.append(rs)

        # INT.CD
        opts = ["CODE 0", "CODE 1", "CODE 2", "CODE 3", "CODE 4",
                "CODE 5", "CODE 6", "CODE 7", "CODE 8", "CODE 9",
                "CODE A", "CODE B", "CODE C", "CODE D", "CODE E", "CODE F"]
        wires.append(RadioSetting("int_cd", "Access Number for WiRES(TM)",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.int_cd])))

        # INT.MR
        opts = ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "d9"]
        wires.append(RadioSetting(
            "int_mr", "Access Number (DTMF) for Non-WiRES(TM)",
                     RadioSettingValueList(opts, opts[_settings.int_mr])))

        # LAMP
        opts = ["KEY", "5SEC", "TOGGLE"]
        switch.append(RadioSetting("lamp", "Lamp Mode",
                                   RadioSettingValueList(opts, opts[
                                                         _settings.lamp])))

        # LOCK
        opts = ["LK KEY", "LKDIAL", "LK K+D", "LK PTT",
                "LP P+K", "LK P+D", "LK ALL"]
        rs = RadioSetting("lock", "Control Locking",
                          RadioSettingValueList(
                              opts, opts[_settings.lock - 1]))

        def apply_lock(s, obj):
            setattr(obj, s.get_name(), int(s.value) + 1)
        rs.set_apply_callback(apply_lock, self._memobj.settings)
        switch.append(rs)

        # M/T-CL
        opts = ["MONI", "T-CALL"]
        switch.append(RadioSetting("mt_cl", "MONI Switch Function",
                                   RadioSettingValueList(opts, opts[
                                                         _settings.mt_cl])))

        # PAG.ABK
        opts = ["OFF", "ON"]
        eai.append(RadioSetting("pag_abk", "Paging Answer Back",
                                RadioSettingValueList(opts, opts[
                                                      _settings.pag_abk])))

        # RESUME
        opts = ["TIME", "HOLD", "BUSY"]
        scan.append(RadioSetting("resume", "Scan Resume Mode",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.resume])))

        # REV/HM
        opts = ["REV", "HOME"]
        switch.append(RadioSetting("rev_hm", "HM/RV Key Function",
                                   RadioSettingValueList(opts, opts[
                                                         _settings.rev_hm])))

        # RF.SQL
        opts = ["OFF", "S-1", "S-2", "S-3", "S-4", "S-5", "S-6",
                "S-7", "S-8", "S-FULL"]
        misc.append(RadioSetting("rf_sql", "RF Squelch Threshold",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.rf_sql])))

        # PRI.RVT
        opts = ["OFF", "ON"]
        scan.append(RadioSetting("pri_rvt", "Priority Revert",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.pri_rvt])))

        # RXSAVE
        opts = ["OFF", "200 MS", "300 MS", "500 MS", "1 S", "2 S"]
        power.append(RadioSetting(
            "rxsave", "Receive Mode Batery Savery Interval",
                     RadioSettingValueList(opts, opts[_settings.rxsave])))

        # S.SRCH
        opts = ["SINGLE", "CONT"]
        misc.append(RadioSetting("ssrch", "Smart Search Sweep Mode",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.ssrch])))

        # SCN.MD
        opts = ["MEM", "ONLY"]
        scan.append(RadioSetting(
                    "scn_md", "Memory Scan Channel Selection Mode",
                    RadioSettingValueList(opts, opts[_settings.scn_md])))

        # SCN.LMP
        opts = ["OFF", "ON"]
        scan.append(RadioSetting("scn_lmp", "Scan Lamp",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.scn_lmp])))

        # TOT
        opts = ["OFF"] + ["%dMIN" % (x) for x in range(1, 30 + 1)]
        misc.append(RadioSetting("tot", "Timeout Timer",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.tot])))

        # TX.LED
        opts = ["ON", "OFF"]
        misc.append(RadioSetting("tx_led", "TX LED",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.tx_led])))

        # TXSAVE
        opts = ["OFF", "ON"]
        power.append(RadioSetting("txsave", "Transmitter Battery Saver",
                                  RadioSettingValueList(opts, opts[
                                                        _settings.txsave])))

        # VFO.BND
        opts = ["BAND", "ALL"]
        misc.append(RadioSetting("vfo_bnd", "VFO Band Edge Limiting",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.vfo_bnd])))

        # WX.ALT
        opts = ["OFF", "ON"]
        scan.append(RadioSetting("wx_alt", "Weather Alert Scan",
                                 RadioSettingValueList(opts, opts[
                                                       _settings.wx_alt])))

        # MBS
        for i in range(0, 10):
            opts = ["OFF", "ON"]
            mbs = (self._memobj.mbs >> i) & 1
            rs = RadioSetting("mbs%i" % i, "Bank %s Scan" % (i + 1),
                              RadioSettingValueList(opts, opts[mbs]))

            def apply_mbs(s, index):
                if int(s.value):
                    self._memobj.mbs |= (1 << index)
                else:
                    self._memobj.mbs &= ~(1 << index)
            rs.set_apply_callback(apply_mbs, i)
            mbls.append(rs)

        return setmode

    def set_settings(self, uisettings):
        _settings = self._memobj.settings
        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue

            try:
                name = element.get_name()
                value = element.value

                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    element.run_apply_callback()
                else:
                    obj = getattr(_settings, name)
                    setattr(_settings, name, value)

                LOG.debug("Setting %s: %s" % (name, value))
            except Exception, e:
                LOG.debug(element.get_name())
                raise

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1]) + \
            repr(self._memobj.flags[(number - 1) / 4]) + \
            repr(self._memobj.names[number - 1])

    def get_memory(self, number):

        mem = chirp_common.Memory()

        if isinstance(number, str):
            # pms channel
            mem.number = 1001 + SPECIALS.index(number)
            mem.extd_number = number
            mem.immutable = ["number", "extd_number", "name", "skip"]
            _mem = self._memobj.pms[mem.number - 1001]
            _nam = _skp = None
        elif number > 1000:
            # pms channel
            mem.number = number
            mem.extd_number = SPECIALS[number - 1001]
            mem.immutable = ["number", "extd_number", "name", "skip"]
            _mem = self._memobj.pms[mem.number - 1001]
            _nam = _skp = None
        else:
            mem.number = number
            _mem = self._memobj.memory[mem.number - 1]
            _nam = self._memobj.names[mem.number - 1]
            _skp = self._memobj.flags[(mem.number - 1) / 4]

        if not _mem.used:
            mem.empty = True
            return mem

        mem.freq = _decode_freq(_mem.freq)
        mem.offset = int(_mem.offset) * 50000
        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            if int(_mem.tx_freq) == 0:
                mem.duplex = "off"
            else:
                mem.offset = _decode_freq(_mem.tx_freq)
        mem.tmode = TMODES[_mem.tmode]
        mem.rtone = chirp_common.TONES[_mem.tone]
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs]
        mem.power = POWER_LEVELS[_mem.power]
        mem.mode = _mem.isam and "AM" or _mem.isnarrow and "NFM" or "FM"
        mem.tuning_step = STEPS[_mem.step]

        if _skp is not None:
            skip = _skp["skip%i" % ((mem.number - 1) % 4)]
            mem.skip = SKIPS[skip]

        if _nam is not None:
            if _nam.use_name and _nam.valid:
                mem.name = _decode_name(_nam.name).rstrip()

        return mem

    def set_memory(self, mem):

        if mem.number > 1000:
            # pms channel
            _mem = self._memobj.pms[mem.number - 1001]
            _nam = _skp = None
        else:
            _mem = self._memobj.memory[mem.number - 1]
            _nam = self._memobj.names[mem.number - 1]
            _skp = self._memobj.flags[(mem.number - 1) / 4]

        assert(_mem)
        if mem.empty:
            _mem.used = False
            return

        if not _mem.used:
            _mem.set_raw("\x00" * 16)
            _mem.used = 1

        _mem.freq, flags = _encode_freq(mem.freq)
        _mem.freq[0].set_bits(flags)
        if mem.duplex == "split":
            _mem.tx_freq, flags = _encode_freq(mem.offset)
            _mem.tx_freq[0].set_bits(flags)
            _mem.offset = 0
        elif mem.duplex == "off":
            _mem.tx_freq = 0
            _mem.offset = 0
        else:
            _mem.tx_freq = 0
            _mem.offset = mem.offset / 50000
        _mem.duplex = DUPLEX.index(mem.duplex)
        _mem.tmode = TMODES.index(mem.tmode)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.power = mem.power and POWER_LEVELS.index(mem.power) or 0
        _mem.isnarrow = mem.mode == "NFM"
        _mem.isam = mem.mode == "AM"
        _mem.step = STEPS.index(mem.tuning_step)

        if _skp is not None:
            _skp["skip%i" % ((mem.number - 1) % 4)] = SKIPS.index(mem.skip)

        if _nam is not None:
            _nam.name = _encode_name(mem.name)
            _nam.use_name = mem.name.strip() and True or False
            _nam.valid = _nam.use_name
