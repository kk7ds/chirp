# Copyright 2015 David Fannin KK6DF  <kk6df@arrl.org>
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

import os
import struct
import time
import logging

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import memmap
from chirp import util
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings, \
    RadioSettingValueList, RadioSettingValueString, RadioSettingValueBoolean, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettingValueFloat, InvalidValueError

LOG = logging.getLogger(__name__)

#
#  Chirp Driver for TYT TH-9000D (models: 2M (144 Mhz), 1.25M (220 Mhz)  and 70cm (440 Mhz)  radios)
#
#  Version 1.0 
#
#         - Skip channels
#
# Global Parameters 
#
MMAPSIZE = 16384
TONES = [62.5] + list(chirp_common.TONES)
TMODES =  ['','Tone','DTCS',''] 
DUPLEXES = ['','err','-','+'] # index 2 not used
MODES = ['WFM','FM','NFM']  #  25k, 20k,15k bw 
TUNING_STEPS=[ 5.0, 6.25, 8.33, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0 ] # index 0-9
POWER_LEVELS=[chirp_common.PowerLevel("High", watts=65),
              chirp_common.PowerLevel("Mid", watts=25),
              chirp_common.PowerLevel("Low", watts=10)]

CROSS_MODES = chirp_common.CROSS_MODES

APO_LIST = [ "Off","30 min","1 hr","2 hrs" ] 
BGCOLOR_LIST = ["Blue","Orange","Purple"]
BGBRIGHT_LIST = ["%s" % x for x in range(1,32)]
SQUELCH_LIST = ["Off"] + ["Level %s" % x for x in range(1,20)] 
TIMEOUT_LIST = ["Off"] + ["%s min" % x for x in range(1,30)]
TXPWR_LIST = ["60W","25W"]  # maximum power for Hi setting
TBSTFREQ_LIST = ["1750Hz","2100Hz","1000Hz","1450Hz"]
BEEP_LIST = ["Off","On"]

SETTING_LISTS = {
        "auto_power_off": APO_LIST,
        "bg_color"      : BGCOLOR_LIST,
        "bg_brightness" : BGBRIGHT_LIST,
        "squelch"       : SQUELCH_LIST,
        "timeout_timer" : TIMEOUT_LIST,
        "choose_tx_power": TXPWR_LIST,
        "tbst_freq"     : TBSTFREQ_LIST,
        "voice_prompt"  : BEEP_LIST
}

MEM_FORMAT = """
#seekto 0x0000;
struct {
   u8 unknown0000[16];
   char idhdr[16];
   u8 unknown0001[16];
} fidhdr;
"""
#Overall Memory Map:
#
#    Memory Map (Range 0x0100-3FF0, step 0x10):
#
#        Field                   Start  End  Size   
#                                (hex)  (hex) (hex)  
#        
#        1 Channel Set Flag        0100  011F   20 
#        2 Channel Skip Flag       0120  013F   20 
#        3 Blank/Unknown           0140  01EF   B0 
#        4 Unknown                 01F0  01FF   10
#        5 TX/RX Range             0200  020F   10    
#        6 Bootup Passwd           0210  021F   10 
#        7 Options, Radio          0220  023F   20
#        8 Unknown                 0240  019F   
#            8B Startup Label      03E0  03E7   07
#        9 Channel Bank            2000  38FF 1900  
#             Channel 000          2000  201F   20  
#             Channel 001          2020  202F   20  
#             ... 
#             Channel 199          38E0  38FF   20 
#        10 Blank/Unknown          3900  3FFF  6FF  14592  16383    1792   
#            Total Map Size           16128 (2^8 = 16384)
#
#  TH9000/220  memory map 
#  section: 1 and 2:  Channel Set/Skip Flags
# 
#    Channel Set (starts 0x100) : Channel Set  bit is value 0 if a memory location in the channel bank is active.
#    Channel Skip (starts 0x120): Channel Skip bit is value 0 if a memory location in the channel bank is active.
#
#    Both flag maps are a total 24 bytes in length, aligned on 32 byte records.
#    bit = 0 channel set/no skip,  1 is channel not set/skip
#
#    to index a channel:
#        cbyte = channel / 8 ;
#        cbit  = channel % 8 ;
#        setflag  = csetflag[cbyte].c[cbit] ;
#        skipflag = cskipflag[cbyte].c[cbit] ;
#
#    channel range is 0-199, range is 32 bytes (last 7 unknown)
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x0100;
struct {
   bit c[8];
} csetflag[32];

struct {
   u8 unknown0100[7];
} ropt0100;

#seekto 0x0120;
struct {
   bit c[8];
} cskipflag[32];

struct {
   u8 unknown0120[7];
} ropt0120;
"""
#  TH9000  memory map 
#  section: 5  TX/RX Range
#     used to set the TX/RX range of the radio (e.g.  222-228Mhz for 220 meter)
#     possible to set range for tx/rx 
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x0200;
struct {
    bbcd txrangelow[4];
    bbcd txrangehi[4];
    bbcd rxrangelow[4];
    bbcd rxrangehi[4];
} freqrange;
"""
# TH9000  memory map 
# section: 6  bootup_passwd
#    used to set bootup passwd (see boot_passwd checkbox option)
#
#  options - bootup password
#
#  bytes:bit   type                 description
#  ---------------------------------------------------------------------------
#  6         u8 bootup_passwd[6]     bootup passwd, 6 chars, numberic chars 30-39 , see boot_passwd checkbox to set
#  10        u8 unknown;  
#

MEM_FORMAT = MEM_FORMAT + """
#seekto 0x0210;
struct {
   u8 bootup_passwd[6];
   u8 unknown2010[10];
} ropt0210;
"""
#  TH9000/220  memory map 
#  section: 7  Radio Options  
#        used to set a number of radio options 
#
#  bytes:bit   type                 description
#  ---------------------------------------------------------------------------
#  1         u8 display_mode     display mode, range 0-2, 0=freq,1=channel,2=name (selecting name affects vfo_mr)
#  1         u8 vfo_mr;          vfo_mr , 0=vfo, mr=1 
#  1         u8 unknown;  
#  1         u8 squelch;         squelch level, range 0-19, hex for menu
#  1         u8 unknown[2]; 
#  1         u8 channel_lock;    if display_mode[channel] selected, then lock=1,no lock =0
#  1         u8 unknown; 
#  1         u8 bg_brightness ;  background brightness, range 0-21, hex, menu index 
#  1         u8 unknown;     
#  1         u8 bg_color ;       bg color, menu index,  blue 0 , orange 1, purple 2
#  1         u8 tbst_freq ;      tbst freq , menu 0 = 1750Hz, 1=2100 , 2=1000 , 3=1450hz 
#  1         u8 timeout_timer;   timeout timer, hex, value = minutes, 0= no timeout
#  1         u8 unknown; 
#  1         u8 auto_power_off;   auto power off, range 0-3, off,30min, 1hr, 2hr, hex menu index
#  1         u8 voice_prompt;     voice prompt, value 0,1 , Beep ON = 1, Beep Off = 2
#
# description of function setup options, starting at 0x0230
#
#  bytes:bit   type                 description
#  ---------------------------------------------------------------------------
#  1         u8  // 0
#   :4       unknown:6
#   :1       elim_sql_tail:1   eliminate squelsh tail when no ctcss checkbox (1=checked)
#   :1       sql_key_function  "squelch off" 1 , "squelch momentary off" 0 , menu index
#  2         u8 unknown[2] /1-2  
#  1         u8 // 3
#   :4       unknown:4
#   :1       inhibit_init_ops:1 //bit 5
#   :1       unknownD:1
#   :1       inhibit_setup_bg_chk:1 //bit 7
#   :1       unknown:1
#  1         u8 tail_elim_type    menu , (off=0,120=1,180=2),  // 4
#  1         u8 choose_tx_power    menu , (60w=0,25w=1) // 5
#  2         u8 unknown[2]; // 6-7 
#  1         u8 bootup_passwd_flag  checkbox 1=on, 0=off // 8
#  7         u8 unknown[7]; // 9-F 
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x0220;
struct {
   u8 display_mode; 
   u8 vfo_mr; 
   u8 unknown0220A; 
   u8 squelch; 
   u8 unknown0220B[2]; 
   u8 channel_lock; 
   u8 unknown0220C; 
   u8 bg_brightness; 
   u8 unknown0220D; 
   u8 bg_color;
   u8 tbst_freq;
   u8 timeout_timer;
   u8 unknown0220E;
   u8 auto_power_off;
   u8 voice_prompt; 
   u8 unknown0230A:6,
      elim_sql_tail:1,
      sql_key_function:1;
   u8 unknown0230B[2];
   u8 unknown0230C:4, 
      inhibit_init_ops:1,
      unknown0230D:1,
      inhibit_setup_bg_chk:1,
      unknown0230E:1;
   u8 tail_elim_type;
   u8 choose_tx_power;
   u8 unknown0230F[2];
   u8 bootup_passwd_flag;
   u8 unknown0230G[7];
} settings;
"""
#  TH9000  memory map 
#  section: 8B  Startup Label  
#
#  bytes:bit   type                 description
#  ---------------------------------------------------------------------------
#  7     char start_label[7]    label displayed at startup (usually your call sign)
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x03E0;
struct {
    char startname[7];
} slabel;
"""
#  TH9000/220  memory map 
#  section: 9  Channel Bank
#         description of channel bank (200 channels , range 0-199)
#         Each 32 Byte (0x20 hex)  record:
#  bytes:bit   type                 description
#  ---------------------------------------------------------------------------
#  4         bbcd freq[4]        receive frequency in packed binary coded decimal  
#  4         bbcd offset[4]      transmit offset in packed binary coded decimal (note: plus/minus direction set by 'duplex' field)
#  1         u8
#   :4       unknown:4
#   :4       tuning_step:4         tuning step, menu index value from 0-9
#            5,6.25,8.33,10,12.5,15,20,25,30,50
#  1         u8
#   :4       unknown:4          not yet decoded, used for DCS coding?
#   :2       channel_width:2     channel spacing, menu index value from 0-3
#            25,20,12.5
#   :1       reverse:1           reverse flag, 0=off, 1=on (reverses tx and rx freqs)
#   :1       txoff:1             transmitt off flag, 0=transmit , 1=do not transmit 
#  1         u8
#   :1       talkaround:1        talkaround flag, 0=off, 1=on (bypasses repeater) 
#   :1       compander:1         compander flag, 0=off, 1=on (turns on/off voice compander option)  
#   :2       unknown:2          
#   :2       power:2             tx power setting, value range 0-2, 0=hi,1=med,2=lo 
#   :2       duplex:2            duplex settings, 0=simplex,2= minus(-) offset, 3= plus (+) offset (see offset field) 
#            
#  1         u8 
#   :4       unknown:4
#   :2       rxtmode:2           rx tone mode, value range 0-2, 0=none, 1=CTCSS, 2=DCS  (ctcss tone in field rxtone)
#   :2       txtmode:2           tx tone mode, value range 0-2, 0=none, 1=CTCSS, 3=DCS  (ctcss tone in field txtone)
#  1         u8 
#   :2       unknown:2
#   :6       txtone:6            tx ctcss tone, menu index
#  1         u8 
#   :2       unknown:2 
#   :6       rxtone:6            rx ctcss tone, menu index
#  1         u8 txcode           ?, not used for ctcss
#  1         u8 rxcode           ?, not used for ctcss
#  3         u8 unknown[3]
#  7         char name[7]        7 byte char string for channel name
#  1         u8 
#   :6       unknown:6,
#   :2       busychannellockout:2 busy channel lockout option , 0=off, 1=repeater, 2=busy  (lock out tx if channel busy)
#  4         u8 unknownI[4];
#  1         u8 
#   :7       unknown:7 
#   :1       scrambler:1         scrambler flag, 0=off, 1=on (turns on tyt scrambler option)
#
MEM_FORMAT = MEM_FORMAT + """
#seekto 0x2000;
struct {
  bbcd freq[4];
  bbcd offset[4];
  u8 unknown2000A:4,
     tuning_step:4;
  u8 rxdcsextra:1,
     txdcsextra:1,
     rxinv:1,
     txinv:1,
     channel_width:2,
     reverse:1,
     txoff:1;
  u8 talkaround:1,
     compander:1,
     unknown2000C:2,
     power:2,
     duplex:2;
  u8 unknown2000D:4,
     rxtmode:2,
     txtmode:2;
  u8 unknown2000E:2,
     txtone:6;
  u8 unknown2000F:2,
     rxtone:6;
  u8 txcode;
  u8 rxcode;
  u8 unknown2000G[3];
  char name[7];
  u8 unknown2000H:6,
     busychannellockout:2;
  u8 unknown2000I[4];
  u8 unknown2000J:7,
     scrambler:1; 
} memory[200] ;
"""

def _echo_write(radio, data):
    try:
        radio.pipe.write(data)
        radio.pipe.read(len(data))
    except Exception as e:
        LOG.error("Error writing to radio: %s" % e)
        raise errors.RadioError("Unable to write to radio")


def _checksum(data):
    cs = 0
    for byte in data:
        cs += ord(byte)
    return cs % 256

def _read(radio, length):
    try:
        data = radio.pipe.read(length)
    except Exception as e:
        LOG.error( "Error reading from radio: %s" % e)
        raise errors.RadioError("Unable to read from radio")

    if len(data) != length:
        LOG.error( "Short read from radio (%i, expected %i)" % (len(data),
                                                           length))
        LOG.debug(util.hexprint(data))
        raise errors.RadioError("Short read from radio")
    return data



def _ident(radio):
    radio.pipe.timeout = 1
    _echo_write(radio,"PROGRAM")
    response = radio.pipe.read(3)
    if response != "QX\06":
        LOG.debug( "Response was :\n%s" % util.hexprint(response))
        raise errors.RadioError("Unsupported model")
    _echo_write(radio, "\x02")
    response = radio.pipe.read(16)
    LOG.debug(util.hexprint(response))
    if response[1:8] != "TH-9000":
        LOG.error( "Looking  for:\n%s" % util.hexprint("TH-9000"))
        LOG.error( "Response was:\n%s" % util.hexprint(response))
        raise errors.RadioError("Unsupported model")

def _send(radio, cmd, addr, length, data=None):
    frame = struct.pack(">cHb", cmd, addr, length)
    if data:
        frame += data
        frame += chr(_checksum(frame[1:]))
        frame += "\x06"
    _echo_write(radio, frame)
    LOG.debug("Sent:\n%s" % util.hexprint(frame))
    if data:
        result = radio.pipe.read(1)
        if result != "\x06":
            LOG.debug( "Ack was: %s" % repr(result))
            raise errors.RadioError("Radio did not accept block at %04x" % addr)
        return
    result = _read(radio, length + 6)
    LOG.debug("Got:\n%s" % util.hexprint(result))
    header = result[0:4]
    data = result[4:-2]
    ack = result[-1]
    if ack != "\x06":
        LOG.debug("Ack was: %s" % repr(ack))
        raise errors.RadioError("Radio NAK'd block at %04x" % addr)
    _cmd, _addr, _length = struct.unpack(">cHb", header)
    if _addr != addr or _length != _length:
        LOG.debug( "Expected/Received:")
        LOG.debug(" Length: %02x/%02x" % (length, _length))
        LOG.debug( " Addr: %04x/%04x" % (addr, _addr))
        raise errors.RadioError("Radio send unexpected block")
    cs = _checksum(result[1:-2])
    if cs != ord(result[-2]):
        LOG.debug( "Calculated: %02x" % cs)
        LOG.debug( "Actual:     %02x" % ord(result[-2]))
        raise errors.RadioError("Block at 0x%04x failed checksum" % addr)
    return data


def _finish(radio):
    endframe = "\x45\x4E\x44"
    _echo_write(radio, endframe)
    result = radio.pipe.read(1)
    # TYT radios acknowledge the "endframe" command, Luiton radios do not.
    if result != "" and result != "\x06":  
        LOG.error( "Got:\n%s" % util.hexprint(result))
        raise errors.RadioError("Radio did not finish cleanly")

def do_download(radio):

    _ident(radio)

    _memobj = None
    data = ""

    for start,end in radio._ranges: 
        for addr in range(start,end,0x10):
            block = _send(radio,'R',addr,0x10) 
            data += block
            status = chirp_common.Status()
            status.cur = len(data)
            status.max = end
            status.msg = "Downloading from radio"
            radio.status_fn(status)

    _finish(radio)

    return memmap.MemoryMap(data)

def do_upload(radio):

    _ident(radio)

    for start,end in radio._ranges:
        for addr in range(start,end,0x10):
            if addr < 0x0100:
                continue
            block = radio._mmap[addr:addr+0x10]
            _send(radio,'W',addr,len(block),block)
            status = chirp_common.Status()
            status.cur = addr
            status.max = end
            status.msg = "Uploading to Radio"
            radio.status_fn(status)

    _finish(radio)
            


#
# The base class, extended for use with other models
#
class Th9000Radio(chirp_common.CloneModeRadio,
                  chirp_common.ExperimentalRadio):
    """TYT TH-9000"""
    VENDOR = "TYT"    
    MODEL = "TH9000 Base" 
    BAUD_RATE = 9600 
    valid_freq = [(900000000, 999000000)]
    

    _memsize = MMAPSIZE
    _ranges = [(0x0000,0x4000)]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = ("The TYT TH-9000 driver is an beta version."
                           "Proceed with Caution and backup your data")
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_cross = True
        rf.has_tuning_step = False
        rf.has_rx_dtcs = True
        rf.valid_skips = ["","S"]
        rf.memory_bounds = (0, 199) 
        rf.valid_name_length = 7
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "-"
        rf.valid_modes = MODES
        rf.valid_tmodes = ['','Tone','TSQL','DTCS','Cross']
        rf.valid_cross_modes = ['Tone->DTCS','DTCS->Tone',
                               '->Tone','->DTCS','Tone->Tone']
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_dtcs_codes = chirp_common.ALL_DTCS_CODES
        rf.valid_bands = self.valid_freq
        return rf

    # Do a download of the radio from the serial port
    def sync_in(self):
        self._mmap = do_download(self)
        self.process_mmap()

    # Do an upload of the radio to the serial port
    def sync_out(self):
        do_upload(self)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)


    # Return a raw representation of the memory object, which 
    # is very helpful for development
    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    # not working yet
    def _get_dcs_index(self, _mem,which):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        return (int(extra) << 8) | int(base)

    def _set_dcs_index(self, _mem, which, index):
        base = getattr(_mem, '%scode' % which)
        extra = getattr(_mem, '%sdcsextra' % which)
        base.set_value(index & 0xFF)
        extra.set_value(index >> 8)


    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number):
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[number]

        # get flag info
        cbyte = number / 8 ;
        cbit =  7 - (number % 8) ;
        setflag = self._memobj.csetflag[cbyte].c[cbit]; 
        skipflag = self._memobj.cskipflag[cbyte].c[cbit]; 

        mem = chirp_common.Memory()

        mem.number = number  # Set the memory number

        if setflag == 1:
            mem.empty = True
            return mem

        mem.freq = int(_mem.freq) * 100    
        mem.offset = int(_mem.offset) * 100
        mem.name = str(_mem.name).rstrip() # Set the alpha tag
        mem.duplex = DUPLEXES[_mem.duplex]
        mem.mode = MODES[_mem.channel_width]
        mem.power = POWER_LEVELS[_mem.power]

        rxtone = txtone = None


        rxmode = TMODES[_mem.rxtmode]
        txmode = TMODES[_mem.txtmode]



        # doesn't work
        if rxmode == "Tone":
            rxtone = TONES[_mem.rxtone]
        elif rxmode == "DTCS":
            rxtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,'rx')]

        if txmode == "Tone":
            txtone = TONES[_mem.txtone]
        elif txmode == "DTCS":
            txtone = chirp_common.ALL_DTCS_CODES[self._get_dcs_index(_mem,'tx')]

        rxpol = _mem.rxinv and "R" or "N"
        txpol = _mem.txinv and "R" or "N"

        chirp_common.split_tone_decode(mem,
                                       (txmode, txtone, txpol),
                                       (rxmode, rxtone, rxpol))

        mem.skip = "S" if skipflag == 1 else ""


        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True

        return mem

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        # Get a low-level memory object mapped to the image

        _mem = self._memobj.memory[mem.number]

        cbyte = mem.number / 8 
        cbit =  7 - (mem.number % 8) 

        if mem.empty:
            self._memobj.csetflag[cbyte].c[cbit] = 1
            self._memobj.cskipflag[cbyte].c[cbit] = 1
            return

        self._memobj.csetflag[cbyte].c[cbit] =  0 
        self._memobj.cskipflag[cbyte].c[cbit]  =  1 if (mem.skip == "S") else 0

        _mem.set_raw("\x00" * 32)

        _mem.freq = mem.freq / 100         # Convert to low-level frequency
        _mem.offset = mem.offset / 100         # Convert to low-level frequency

        _mem.name = mem.name.ljust(7)[:7]  # Store the alpha tag
        _mem.duplex = DUPLEXES.index(mem.duplex)


        try:
            _mem.channel_width = MODES.index(mem.mode)
        except ValueError:
            _mem.channel_width = 0

        ((txmode, txtone, txpol),
         (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)

        _mem.txtmode = TMODES.index(txmode)

        _mem.rxtmode = TMODES.index(rxmode)

        if txmode == "Tone":
            _mem.txtone = TONES.index(txtone)
        elif txmode == "DTCS":
            self._set_dcs_index(_mem,'tx',chirp_common.ALL_DTCS_CODES.index(txtone))

        if rxmode == "Tone":
            _mem.rxtone = TONES.index(rxtone)
        elif rxmode == "DTCS":
            self._set_dcs_index(_mem, 'rx', chirp_common.ALL_DTCS_CODES.index(rxtone))

        _mem.txinv = txpol == "R"
        _mem.rxinv = rxpol == "R"

       
        if mem.power:
            _mem.power = POWER_LEVELS.index(mem.power)
        else:
            _mem.power = 0

    def _get_settings(self):
        _settings = self._memobj.settings
        _freqrange = self._memobj.freqrange
        _slabel = self._memobj.slabel

        basic = RadioSettingGroup("basic","Global Settings")
        freqrange = RadioSettingGroup("freqrange","Frequency Ranges")
        top = RadioSettingGroup("top","All Settings",basic,freqrange)
        settings = RadioSettings(top)

        def _filter(name):
            filtered = ""
            for char in str(name):
                if char in chirp_common.CHARSET_ASCII:
                    filtered += char
                else:
                    filtered += ""
            return filtered
                   
        val = RadioSettingValueString(0,7,_filter(_slabel.startname))
        rs = RadioSetting("startname","Startup Label",val)
        basic.append(rs)

        rs = RadioSetting("bg_color","LCD Color",
                           RadioSettingValueList(BGCOLOR_LIST, BGCOLOR_LIST[_settings.bg_color]))
        basic.append(rs)

        rs = RadioSetting("bg_brightness","LCD Brightness",
                           RadioSettingValueList(BGBRIGHT_LIST, BGBRIGHT_LIST[_settings.bg_brightness]))
        basic.append(rs)

        rs = RadioSetting("squelch","Squelch Level",
                           RadioSettingValueList(SQUELCH_LIST, SQUELCH_LIST[_settings.squelch]))
        basic.append(rs)

        rs = RadioSetting("timeout_timer","Timeout Timer (TOT)",
                           RadioSettingValueList(TIMEOUT_LIST, TIMEOUT_LIST[_settings.timeout_timer]))
        basic.append(rs)

        rs = RadioSetting("auto_power_off","Auto Power Off (APO)",
                           RadioSettingValueList(APO_LIST, APO_LIST[_settings.auto_power_off]))
        basic.append(rs)

        rs = RadioSetting("voice_prompt","Beep Prompt",
                           RadioSettingValueList(BEEP_LIST, BEEP_LIST[_settings.voice_prompt]))
        basic.append(rs)

        rs = RadioSetting("tbst_freq","Tone Burst Frequency",
                           RadioSettingValueList(TBSTFREQ_LIST, TBSTFREQ_LIST[_settings.tbst_freq]))
        basic.append(rs)

        rs = RadioSetting("choose_tx_power","Max Level of TX Power",
                           RadioSettingValueList(TXPWR_LIST, TXPWR_LIST[_settings.choose_tx_power]))
        basic.append(rs)

        (flow,fhigh)  = self.valid_freq[0]
        flow  /= 1000
        fhigh /= 1000
        fmidrange = (fhigh- flow)/2

        rs = RadioSetting("txrangelow","TX Freq, Lower Limit (khz)", RadioSettingValueInteger(flow,
            flow + fmidrange,
            int(_freqrange.txrangelow)/10))
        freqrange.append(rs)

        rs = RadioSetting("txrangehi","TX Freq, Upper Limit (khz)", RadioSettingValueInteger(fhigh-fmidrange,
            fhigh,
            int(_freqrange.txrangehi)/10))
        freqrange.append(rs)

        rs = RadioSetting("rxrangelow","RX Freq, Lower Limit (khz)", RadioSettingValueInteger(flow,
            flow+fmidrange,
            int(_freqrange.rxrangelow)/10))
        freqrange.append(rs)

        rs = RadioSetting("rxrangehi","RX Freq, Upper Limit (khz)", RadioSettingValueInteger(fhigh-fmidrange,
            fhigh,
            int(_freqrange.rxrangehi)/10))
        freqrange.append(rs)

        return settings

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error( "failed to parse settings")
            traceback.print_exc()
            return None

    def set_settings(self,settings):
        _settings = self._memobj.settings
        for element in settings:
            if not isinstance(element,RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    name = element.get_name()

                    if  name in ["txrangelow","txrangehi","rxrangelow","rxrangehi"]:
                        LOG.debug( "setting %s = %s" % (name,int(element.value)*10))
                        setattr(self._memobj.freqrange,name,int(element.value)*10)
                        continue

                    if name in ["startname"]:
                        LOG.debug( "setting %s = %s" % (name, element.value))
                        setattr(self._memobj.slabel,name,element.value)
                        continue

                    obj = _settings
                    setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug( "using apply callback")
                        element.run_apply_callback()
                    else:
                        LOG.debug( "Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception as e:
                    LOG.debug( element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        if  MMAPSIZE == len(filedata):
           (flow,fhigh)  = cls.valid_freq[0]
           flow  /= 1000000
           fhigh /= 1000000

           txmin=ord(filedata[0x200])*100 + (ord(filedata[0x201])>>4)*10 + ord(filedata[0x201])%16
           txmax=ord(filedata[0x204])*100 + (ord(filedata[0x205])>>4)*10 + ord(filedata[0x205])%16
           rxmin=ord(filedata[0x208])*100 + (ord(filedata[0x209])>>4)*10 + ord(filedata[0x209])%16
           rxmax=ord(filedata[0x20C])*100 + (ord(filedata[0x20D])>>4)*10 + ord(filedata[0x20D])%16

           if ( rxmin >= flow and rxmax <= fhigh and txmin >= flow and txmax <= fhigh ):
                return True

        return False

# Declaring Aliases (Clones of the real radios)
class LT580VHF(chirp_common.Alias):
    VENDOR = "LUITON"
    MODEL = "LT-580_VHF"


class LT580UHF(chirp_common.Alias):
    VENDOR = "LUITON"
    MODEL = "LT-580_UHF"


@directory.register
class Th9000220Radio(Th9000Radio):
    """TYT TH-9000 220"""
    VENDOR = "TYT"    
    MODEL = "TH9000_220" 
    BAUD_RATE = 9600 
    valid_freq = [(220000000, 260000000)]

@directory.register
class Th9000144Radio(Th9000220Radio):
    """TYT TH-9000 144"""
    VENDOR = "TYT"    
    MODEL = "TH9000_144" 
    BAUD_RATE = 9600 
    valid_freq = [(136000000, 174000000)]
    ALIASES = [LT580VHF, ]

@directory.register
class Th9000440Radio(Th9000220Radio):
    """TYT TH-9000 440"""
    VENDOR = "TYT"    
    MODEL = "TH9000_440" 
    BAUD_RATE = 9600 
    valid_freq = [(400000000, 490000000)]
    ALIASES = [LT580UHF, ]
