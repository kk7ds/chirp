# Copyright 2016 Pavel Milanes CO7WT, <co7wt@frcuba.co.cu> <pavelmc@gmail.com>
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

import time
import struct
import logging

LOG = logging.getLogger(__name__)

from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors, util
from chirp.settings import RadioSettingGroup, RadioSetting, \
    RadioSettingValueBoolean, RadioSettingValueList, \
    RadioSettingValueString, RadioSettings

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];
  lbcd txfreq[4];
  lbcd rx_tone[2];
  lbcd tx_tone[2];
  u8 unknown41:1,
     unknown42:1,
     power:1,           // high power set (1=off)
     shift:1,           // Shift (1=off)
     busy:1,            // Busy lock (1=off)
     unknown46:1,
     unknown47:1,
     unknown48:1;
  u8 rxen;              // xff if off, x00 if enabled (if chan sel = 00)
  u8 txen;              // xff if off, x00 if enabled
  u8 unknown7;
} memory[32];

#seekto 0x0338;
u8 scan[4];             //  4 bytes / bit LSBF for the channel

#seekto 0x033C;
u8 active[4];           //  4 bytes / bit LSBF for the active cha
                        // active = 0

#seekto 0x0340;
struct {
  u8 kMoni;             // monitor key function
  u8 kScan;             // scan key function
  u8 kDial;             // dial key function
  u8 kTa;               // ta key function
  u8 kLo;               // low key function
  u8 unknown40[7];
  // 0x034c
  u8 tot;               // TOT val * 30 steps (x00-0xa)
  u8 tot_alert;         // TOT pre-alert val * 10 steps, (x00-x19)
  u8 tot_rekey;         // TOT rekey val, 0-60, (x00-x3c)
  u8 tot_reset;         // TOT reset val, 0-15, (x00-x0f)
  // 0x0350
  u8 sql;               // SQL level val, 0-9 (default 6)
  u8 unknown50[12];
  u8 unknown30:1,
     unknown31:1,
     dealer:1,          // dealer & test mode (1=on)
     add:1,             // add/del from the scan (1=on)
     unknown34:1,
     batt_save:1,       // Battery save (1=on)
     unknown36:1,
     beep:1;            // beep on tone (1=on)
  u8 unknown51[2];
} settings;

#seekto 0x03f0;
struct {
  u8 batt_level;        // inverted (ff-val)
  u8 sq_tight;          // sq tight (ff-val)
  u8 sq_open;           // sq open (ff-val)
  u8 high_power;        // High power
  u8 qt_dev;            // QT deviation
  u8 dqt_dev;           // DQT deviation
  u8 low_power;         // low power
} tune;

"""

MEM_SIZE = 0x400
BLOCK_SIZE = 8
MEM_BLOCKS = list(range(0, (MEM_SIZE // BLOCK_SIZE)))
ACK_CMD = "\x06"
TIMEOUT = 0.05  # from 0.03 up it' s safe, we set in 0.05 for a margin

POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1),
                chirp_common.PowerLevel("High", watts=5)]
SKIP_VALUES = ["", "S"]
TONES = chirp_common.TONES
# TONES.remove(254.1)
DTCS_CODES = chirp_common.DTCS_CODES

# some vars for the UI
off = ["off"]
TOT = off + ["%s" % x for x in range(30, 330, 30)]
TOT_A = off + ["%s" % x for x in range(10, 260, 10)]
TOT_RK = off + ["%s" % x for x in range(1, 61)]
TOT_RS = off + ["%s" % x for x in range(1, 16)]
SQL = off + ["%s" % x for x in range(1, 10)]

# keys
MONI = off + ["Monitor momentary", "Monitor lock", "SQ off momentary"]
SCAN = off + ["Carrier operated (COS)", "Time operated (TOS)"]
YESNO = ["Enabled", "Disabled"]
TA = off + ["Turn around", "Reverse"]


def rawrecv(radio, amount):
    """Raw read from the radio device"""
    data = ""
    try:
        data = radio.pipe.read(amount)
        # print("<= %02i: %s" % (len(data), util.hexprint(data)))
    except:
        raise errors.RadioError("Error reading data from radio")

    return data


def rawsend(radio, data):
    """Raw send to the radio device"""
    try:
        radio.pipe.write(data)
        # print("=> %02i: %s" % (len(data), util.hexprint(data)))
    except:
        raise errors.RadioError("Error sending data from radio")


def send(radio, frame):
    """Generic send data to the radio"""
    rawsend(radio, frame)


def make_frame(cmd, addr, data=""):
    """Pack the info in the format it likes"""
    ts = struct.pack(">BHB", ord(cmd), addr, 8)
    if data == "":
        return ts
    else:
        if len(data) == 8:
            return ts + data
        else:
            raise errors.InvalidValueError("Data of unexpected length to send")


def handshake(radio, msg="", full=False):
    """Make a full handshake, if not full just hals"""
    # send ACK if commandes
    if full is True:
        rawsend(radio, ACK_CMD)
    # receive ACK
    ack = rawrecv(radio, 1)
    # check ACK
    if ack != ACK_CMD:
        # close_radio(radio)
        mesg = "Handshake failed: " + msg
        raise Exception(mesg)


def recv(radio):
    """Receive data from the radio, 12 bytes, 4 in the header, 8 as data"""
    rxdata = rawrecv(radio, 12)

    if len(rxdata) != 12:
        raise errors.RadioError(
            "Received a length of data that is not possible")

    cmd, addr, length = struct.unpack(">BHB", rxdata[0:4])
    data = ""
    if length == 8:
        data = rxdata[4:]

    return data


def open_radio(radio):
    """Open the radio into program mode and check if it's the correct model"""
    # Set serial discipline
    try:
        radio.pipe.parity = "N"
        radio.pipe.timeout = TIMEOUT
        radio.pipe.flush()
    except:
        msg = "Serial error: Can't set serial line discipline"
        raise errors.RadioError(msg)

    # we will try to open the radio 5 times, this is an improved mechanism
    magic = "PROGRAM"
    exito = False
    for i in range(0, 5):
        for i in range(0, len(magic)):
            ack = rawrecv(radio, 1)
            time.sleep(0.05)
            send(radio, magic[i])

        try:
            handshake(radio, "Radio not entering Program mode")
            exito = True
            break
        except:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    rawsend(radio, "\x02")
    ident = rawrecv(radio, 8)
    handshake(radio, "Comm error after ident", True)

    if not (radio.TYPE in ident):
        LOG.debug("Incorrect model ID, got %s" % util.hexprint(ident))
        msg = "Incorrect model ID, got %s, it not contains %s" % \
            (ident[0:5], radio.TYPE)
        raise errors.RadioError(msg)


def do_download(radio):
    """This is your download function"""
    open_radio(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    data = ""
    for addr in MEM_BLOCKS:
        send(radio, make_frame("R", addr * BLOCK_SIZE))
        data += recv(radio)
        handshake(radio, "Rx error in block %03i" % addr, True)
        # DEBUG
        # print("Block: %04x, Pos: %06x" % (addr, addr * BLOCK_SIZE))

        # UI Update
        status.cur = addr
        status.msg = "Cloning from radio..."
        radio.status_fn(status)

    return memmap.MemoryMap(data)


def do_upload(radio):
    """Upload info to radio"""
    open_radio(radio)

    # UI progress
    status = chirp_common.Status()
    status.cur = 0
    status.max = MEM_SIZE / BLOCK_SIZE
    status.msg = "Cloning to radio..."
    radio.status_fn(status)
    count = 0

    for addr in MEM_BLOCKS:
        # UI Update
        status.cur = addr
        status.msg = "Cloning to radio..."
        radio.status_fn(status)

        block = addr * BLOCK_SIZE
        # Beyond 0x03d0 the data is not writable
        if block > 0x3d0:
            continue

        data = radio.get_mmap()[block:block + BLOCK_SIZE]
        send(radio, make_frame("W", block, data))

        time.sleep(0.02)
        handshake(radio, "Rx error in block %03i" % addr)


def get_radio_id(data):
    """Extract the radio identification from the firmware"""
    # Reverse the radio id string. MemoryMap does not support the step/stride
    # slice argument, so it is first sliced to a str then reversed.
    return data[0x03d0:0x03d8][::-1]


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = get_radio_id(data)

    # DEBUG
    # print("Full ident string is %s" % util.hexprint(rid))

    if (rid in cls.VARIANTS):
        # correct model
        return True
    else:
        return False


class Kenwood_P60_Radio(chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio):
    """Kenwood Mobile Family 60 Radios"""
    VENDOR = "Kenwood"
    _range = [350000000, 512000000]  # don't mind, it will be overited
    _upper = 32
    VARIANT = ""
    MODEL = ""
    _kind = ""
    NEEDS_COMPAT_SERIAL = True

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = \
            ('This driver is experimental; not all features have been '
             'implemented, but it has those features most used by hams.\n'
             '\n'
             'This radios are able to work slightly outside the OEM '
             'frequency limits. After testing, the limit in Chirp has '
             'been set 4% outside the OEM limit. This allows you to use '
             'some models on the ham bands.\n'
             '\n'
             'Nevertheless, each radio has its own hardware limits and '
             'your mileage may vary.\n'
             )
        rp.pre_download = _(
            "Follow this instructions to read your radio:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the download of your radio data\n")
        rp.pre_upload = _(
            "Follow this instructions to write your radio:\n"
            "1 - Turn off your radio\n"
            "2 - Connect your interface cable\n"
            "3 - Turn on your radio\n"
            "4 - Do the upload of your radio data\n")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = False
        rf.has_offset = True
        rf.has_mode = False
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_modes = ["FM"]
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_cross_modes = [
            "Tone->Tone",
            "DTCS->",
            "->DTCS",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "DTCS->DTCS"]
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_skips = SKIP_VALUES
        rf.valid_dtcs_codes = DTCS_CODES
        rf.valid_bands = [self._range]
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 25.0]
        return rf

    def sync_in(self):
        """Download from radio"""
        self._mmap = do_download(self)
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        # Get the data ready for upload
        try:
            self._prep_data()
        except:
            raise errors.RadioError("Error processing the radio data")

        # do the upload
        try:
            do_upload(self)
        except:
            raise errors.RadioError("Error uploading data to radio")

    def set_variant(self):
        """Select and set the correct variables for the class according
        to the correct variant of the radio"""
        rid = get_radio_id(self._mmap)

        # identify the radio variant and set the environment to its values
        try:
            self._upper, low, high, self._kind = self.VARIANTS[rid]

            # Frequency ranges: some model/variants are able to work the near
            # ham bands, even if they are outside the OEM ranges.
            # By experimentation we found that a +/- 4% at the edges is in most
            # cases safe and will cover the near ham band in full
            self._range = [low * 1000000 * 0.96, high * 1000000 * 1.04]

            # put the VARIANT in the class, clean the model / CHs / Type
            # in the same layout as the KPG program
            self._VARIANT = self.MODEL + " [" + str(self._upper) + "CH]: "
            # In the OEM string we show the real OEM ranges
            self._VARIANT += self._kind + ", %d - %d MHz" % (low, high)

            # DEBUG
            # print self._VARIANT

        except KeyError:
            LOG.debug("Wrong Kenwood radio, ID or unknown variant")
            LOG.debug(util.hexprint(rid))
            raise errors.RadioError(
                "Wrong Kenwood radio, ID or unknown variant, see LOG output.")

    def _prep_data(self):
        """Prepare the areas in the memmap to do a consistent write
        it has to make an update on the x280 flag data"""
        achs = 0

        for i in range(0, self._upper):
            if self.get_active(i) is True:
                achs += 1

        # The x0280 area has the settings for the DTMF/2-Tone per channel,
        # as we don't support this feature yet,
        # we disabled by cleaning the data
        # fldata = "\x00\xf0\xff\xff\xff" * achs + \
            # "\xff" * (5 * (self._upper - achs))

        fldata = "\xFF" * 5 * self._upper
        self._fill(0x0280, fldata)

    def _fill(self, offset, data):
        """Fill an specified area of the memmap with the passed data"""
        for addr in range(0, len(data)):
            self._mmap[offset + addr] = data[addr]

    def process_mmap(self):
        """Process the mem map into the mem object"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        # to set the vars on the class to the correct ones
        self.set_variant()

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_active(self, chan):
        """Get the channel active status from the 4 bytes array on the eeprom"""
        byte = int(chan/8)
        bit = chan % 8
        res = self._memobj.active[byte] & (pow(2, bit))
        res = not bool(res)

        return res

    def set_active(self, chan, value=True):
        """Set the channel active status from UI to the mem_map"""
        byte = int(chan/8)
        bit = chan % 8

        # DEBUG
        # print("SET Chan %s, Byte %s, Bit % s" % (chan, byte, bit))

        # get the actual value to see if I need to change anything
        actual = self.get_active(chan)
        if actual != bool(value):
            # DEBUG
            # print "VALUE %s flipping" % int(not value)

            # I have to flip the value
            rbyte = self._memobj.active[byte]
            rbyte = rbyte ^ pow(2, bit)
            self._memobj.active[byte] = rbyte

    def decode_tone(self, val):
        """Parse the tone data to decode from mem, it returns:
        Mode (''|DTCS|Tone), Value (None|###), Polarity (None,N,R)"""
        if val.get_raw(asbytes=False) == "\xFF\xFF":
            return '', None, None

        val = int(val)
        if val >= 12000:
            a = val - 12000
            return 'DTCS', a, 'R'
        elif val >= 8000:
            a = val - 8000
            return 'DTCS', a, 'N'
        else:
            a = val / 10.0
            return 'Tone', a, None

    def encode_tone(self, memval, mode, value, pol):
        """Parse the tone data to encode from UI to mem"""
        if mode == '':
            memval[0].set_raw(0xFF)
            memval[1].set_raw(0xFF)
        elif mode == 'Tone':
            memval.set_value(int(value * 10))
        elif mode == 'DTCS':
            flag = 0x80 if pol == 'N' else 0xC0
            memval.set_value(value)
            memval[1].set_bits(flag)
        else:
            raise Exception("Internal error: invalid mode `%s'" % mode)

    def get_scan(self, chan):
        """Get the channel scan status from the 4 bytes array on the eeprom
        then from the bits on the byte, return '' or 'S' as needed"""
        result = "S"
        byte = int(chan/8)
        bit = chan % 8
        res = self._memobj.scan[byte] & (pow(2, bit))
        if res > 0:
            result = ""

        return result

    def set_scan(self, chan, value):
        """Set the channel scan status from UI to the mem_map"""
        byte = int(chan/8)
        bit = chan % 8

        # get the actual value to see if I need to change anything
        actual = self.get_scan(chan)
        if actual != value:
            # I have to flip the value
            rbyte = self._memobj.scan[byte]
            rbyte = rbyte ^ pow(2, bit)
            self._memobj.scan[byte] = rbyte

    def get_memory(self, number):
        """Get the mem representation from the radio image"""
        _mem = self._memobj.memory[number - 1]

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Memory number
        mem.number = number

        if _mem.get_raw(asbytes=False)[0] == "\xFF":
            mem.empty = True
            # but is not enough, you have to clear the memory in the mmap
            # to get it ready for the sync_out process, just in case
            _mem.set_raw("\xFF" * 16)
            # set the channel to inactive state
            self.set_active(number - 1, False)
            return mem

        # Freq and offset
        mem.freq = int(_mem.rxfreq) * 10
        # tx freq can be blank
        if _mem.get_raw(asbytes=False)[4] == "\xFF" or int(_mem.txen) == 255:
            # TX freq not set
            mem.offset = 0
            mem.duplex = "off"
        else:
            # TX feq set
            offset = (int(_mem.txfreq) * 10) - mem.freq
            if offset < 0:
                mem.offset = abs(offset)
                mem.duplex = "-"
            elif offset > 0:
                mem.offset = offset
                mem.duplex = "+"
            else:
                mem.offset = 0

        # power
        mem.power = POWER_LEVELS[int(_mem.power)]

        # skip
        mem.skip = self.get_scan(number - 1)

        # tone data
        rxtone = txtone = None
        txtone = self.decode_tone(_mem.tx_tone)
        rxtone = self.decode_tone(_mem.rx_tone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        # Extra
        # bank and number in the channel
        mem.extra = RadioSettingGroup("extra", "Extra")

        bl = RadioSetting("busy", "Busy Channel lock",
                          RadioSettingValueBoolean(
                              not bool(_mem.busy)))
        mem.extra.append(bl)

        sf = RadioSetting("shift", "Beat Shift",
                          RadioSettingValueBoolean(
                              not bool(_mem.shift)))
        mem.extra.append(sf)

        return mem

    def set_memory(self, mem):
        """Set the memory data in the eeprom img from the UI
        not ready yet, so it will return as is"""

        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[mem.number - 1]

        # Empty memory
        if mem.empty:
            _mem.set_raw("\xFF" * 16)
            self.set_active(mem.number - 1, False)
            return

        # freq rx
        _mem.rxfreq = mem.freq / 10

        # rx enabled if valid channel,
        # set tx to on, we decide if off after duplex = off
        _mem.rxen = 0
        _mem.txen = 0

        # freq tx
        if mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        elif mem.duplex == "off":
            # set tx freq on the memap to xff
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
            # erase the txen flag
            _mem.txen = 255
        else:
            _mem.txfreq = mem.freq / 10

        # tone data
        ((txmode, txtone, txpol), (rxmode, rxtone, rxpol)) = \
            chirp_common.split_tone_encode(mem)
        self.encode_tone(_mem.tx_tone, txmode, txtone, txpol)
        self.encode_tone(_mem.rx_tone, rxmode, rxtone, rxpol)

        # power, default power is high, as the low is configurable via a key
        if mem.power is None:
            mem.power = POWER_LEVELS[1]

        _mem.power = POWER_LEVELS.index(mem.power)

        # skip
        self.set_scan(mem.number - 1, mem.skip)

        # set as active
        self.set_active(mem.number - 1, True)

        # extra settings
        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

        return mem

    @classmethod
    def match_model(cls, filedata, filename):
        match_size = False
        match_model = False

        # testing the file data size
        if len(filedata) == MEM_SIZE:
            match_size = True

        # testing the firmware model fingerprint
        match_model = model_match(cls, filedata)

        if match_size and match_model:
            return True
        else:
            return False

    def get_settings(self):
        """Translate the bit in the mem_struct into settings in the UI"""
        sett = self._memobj.settings

        # basic features of the radio
        basic = RadioSettingGroup("basic", "Basic Settings")
        # keys
        fkeys = RadioSettingGroup("keys", "Function keys")

        top = RadioSettings(basic, fkeys)

        # Basic
        val = RadioSettingValueString(0, 35, self._VARIANT)
        val.set_mutable(False)
        mod = RadioSetting("not.mod", "Radio version", val)
        basic.append(mod)

        beep = RadioSetting("settings.beep", "Beep tone",
                            RadioSettingValueBoolean(
                                 bool(sett.beep)))
        basic.append(beep)

        bsave = RadioSetting("settings.batt_save", "Battery save",
                             RadioSettingValueBoolean(
                                 bool(sett.batt_save)))
        basic.append(bsave)

        deal = RadioSetting("settings.dealer", "Dealer & Test",
                            RadioSettingValueBoolean(
                                 bool(sett.dealer)))
        basic.append(deal)

        add = RadioSetting("settings.add", "Del / Add feature",
                           RadioSettingValueBoolean(
                                 bool(sett.add)))
        basic.append(add)

        # In some cases the values that follows can be 0xFF (HARD RESET)
        # so we need to take and validate that
        if int(sett.tot) == 0xff:
            # 120 sec
            sett.tot = 4
        if int(sett.tot_alert) == 0xff:
            # 10 secs
            sett.tot_alert = 1
        if int(sett.tot_rekey) == 0xff:
            # off
            sett.tot_rekey = 0
        if int(sett.tot_reset) == 0xff:
            # off
            sett.tot_reset = 0
        if int(sett.sql) == 0xff:
            # a comfortable level ~6
            sett.sql = 6

        tot = RadioSetting("settings.tot", "Time Out Timer (TOT)",
                           RadioSettingValueList(TOT, current_index=int(sett.tot)))
        basic.append(tot)

        tota = RadioSetting("settings.tot_alert", "TOT pre-plert",
                            RadioSettingValueList(TOT_A, current_index=int(sett.tot_alert)))
        basic.append(tota)

        totrk = RadioSetting("settings.tot_rekey", "TOT rekey time",
                             RadioSettingValueList(TOT_RK, current_index=int(sett.tot_rekey)))
        basic.append(totrk)

        totrs = RadioSetting("settings.tot_reset", "TOT reset time",
                             RadioSettingValueList(TOT_RS, current_index=int(sett.tot_reset)))
        basic.append(totrs)

        sql = RadioSetting("settings.sql", "Squelch level",
                           RadioSettingValueList(SQL, current_index=int(sett.sql)))
        basic.append(sql)

        # front keys
        m = int(sett.kMoni)
        if m > 3:
            m = 1
        mon = RadioSetting("settings.kMoni", "Monitor",
                           RadioSettingValueList(MONI, current_index=m))
        fkeys.append(mon)

        s = int(sett.kScan)
        if s > 3:
            s = 1
        scn = RadioSetting("settings.kScan", "Scan",
                           RadioSettingValueList(SCAN, current_index=s))
        fkeys.append(scn)

        d = int(sett.kDial)
        if d > 1:
            d = 0
        dial = RadioSetting("settings.kDial", "Dial",
                            RadioSettingValueList(YESNO, current_index=d))
        fkeys.append(dial)

        t = int(sett.kTa)
        if t > 2:
            t = 2
        ta = RadioSetting("settings.kTa", "Ta",
                          RadioSettingValueList(TA, current_index=t))
        fkeys.append(ta)

        l = int(sett.kLo)
        if l > 1:
            l = 0
        low = RadioSetting("settings.kLo", "Low",
                           RadioSettingValueList(YESNO, current_index=l))
        fkeys.append(low)

        return top

    def set_settings(self, settings):
        """Translate the settings in the UI into bit in the mem_struct
        I don't understand well the method used in many drivers
        so, I used mine, ugly but works ok"""

        mobj = self._memobj

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            # Let's roll the ball
            if "." in element.get_name():
                inter, setting = element.get_name().split(".")
                # you must ignore the settings with "not"
                # this are READ ONLY attributes
                if inter == "not":
                    continue

                obj = getattr(mobj, inter)
                value = element.value

                # integers case + special case
                if setting in ["tot", "tot_alert", "tot_rekey",
                               "tot_reset", "sql", "kMoni", "kScan",
                               "kDial", "kTa", "kLo"]:
                    # catching the "off" values as zero
                    try:
                        value = int(value)
                    except:
                        value = 0

                # Bool types + inverted
                if setting in ["beep", "batt_save", "dealer", "add"]:
                    value = bool(value)

            # Apply al configs done
            # DEBUG
            # print("%s: %s" % (setting, value))
            setattr(obj, setting, value)


# This are the oldest family 60 models just portables support here
# Info striped from a hexdump inside the preogram and hack over a
# tk-270

@directory.register
class TK260_Radio(Kenwood_P60_Radio):
    """Kenwood TK-260 Radios"""
    MODEL = "TK-260"
    TYPE = "P0260"
    VARIANTS = {
        b"P0260\x20\x00\x00": (4, 136, 150, "F2"),
        b"P0260\x21\x00\x00": (4, 150, 174, "F1"),
        }


@directory.register
class TK270_Radio(Kenwood_P60_Radio):
    """Kenwood TK-270 Radios"""
    MODEL = "TK-270"
    TYPE = "P0270"
    VARIANTS = {
        b"P0270\x10\x00\x00": (32, 136, 150, "F2"),
        b"P0270\x11\x00\x00": (32, 150, 174, "F1"),
        }


@directory.register
class TK272_Radio(Kenwood_P60_Radio):
    """Kenwood TK-272 Radios"""
    MODEL = "TK-272"
    TYPE = "P0272"
    VARIANTS = {
        b"P0272\x10\x00\x00": (10, 136, 150, "F2"),
        b"P0272\x11\x00\x00": (10, 150, 174, "F1"),
        }


@directory.register
class TK278_Radio(Kenwood_P60_Radio):
    """Kenwood TK-278 Radios"""
    MODEL = "TK-278"
    TYPE = "P0278"
    VARIANTS = {
        b"P0278\x00\x00\x00": (32, 136, 150, "F2"),
        b"P0278\x01\x00\x00": (32, 150, 174, "F1"),
        }


@directory.register
class TK360_Radio(Kenwood_P60_Radio):
    """Kenwood TK-360 Radios"""
    MODEL = "TK-360"
    TYPE = "P0360"
    VARIANTS = {
        b"P0360\x24\x00\x00": (4, 450, 470, "F1"),
        b"P0360\x25\x00\x00": (4, 470, 490, "F2"),
        b"P0360\x26\x00\x00": (4, 490, 512, "F3"),
        b"P0360\x23\x00\x00": (4, 406, 430, "F4"),
        }


@directory.register
class TK370_Radio(Kenwood_P60_Radio):
    """Kenwood TK-370 Radios"""
    MODEL = "TK-370"
    TYPE = "P0370"
    VARIANTS = {
        b"P0370\x14\x00\x00": (32, 450, 470, "F1"),
        b"P0370\x15\x00\x00": (32, 470, 490, "F2"),
        b"P0370\x16\x00\x00": (32, 490, 512, "F3"),
        b"P0370\x13\x00\x00": (32, 406, 430, "F4"),
        }


@directory.register
class TK372_Radio(Kenwood_P60_Radio):
    """Kenwood TK-372 Radios"""
    MODEL = "TK-372"
    TYPE = "P0372"
    VARIANTS = {
        b"P0372\x14\x00\x00": (10, 450, 470, "F1"),
        b"P0372\x15\x00\x00": (10, 470, 490, "F2"),
        }


@directory.register
class TK378_Radio(Kenwood_P60_Radio):
    """Kenwood TK-378 Radios"""
    MODEL = "TK-378"
    TYPE = "P0378"
    VARIANTS = {
        b"P0378\x04\x00\x00": (32, 370, 470, "SP1"),
        b"P0378\x02\x00\x00": (32, 350, 427, "SP2"),
        }
