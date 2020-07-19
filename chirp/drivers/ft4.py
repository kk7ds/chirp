# Copyright 2019 Dan Clemmensen <DanClemmensen@Gmail.com>
#    Derives loosely from two sources released under GPLv2:
#      ./template.py, Copyright 2012 Dan Smith <dsmith@danplanet.com>
#      ./ft60.py, Copyright 2011 Dan Smith <dsmith@danplanet.com>
#    Edited 2020 Bernhard Hailer AE6YN <ham73tux@gmail.com>
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

"""
CHIRP driver for Yaesu radios that use the SCU-35 cable. This includes at
least the FT-4X, FT-4V, FT-65, and FT-25. This driver will not work with older
Yaesu models.
"""
import logging
import struct
import copy
from chirp import chirp_common, directory, memmap, bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList, RadioSettingValueString, RadioSettings

LOG = logging.getLogger(__name__)


# Layout of Radio memory image.
# This module and the serial protocol treat the FT-4 memory as 16-byte blocks.
# There in nothing magic about 16-byte blocks, but it simplifies the
# description. There are 17 groups of blocks, each with a different purpose
# and format. Five groups consist of channel memories, or "mems" in CHIRP.
# A "mem" describes a radio channel, and all "mems" have the same internal
# format. Three of the groups consist of bitmaps, which all have the same
# internal mapping. also groups for Name, misc, DTMF digits, and prog,
# plus some unused groups. The MEM_FORMAT describes the radio image memory.
# MEM_FORMAT is parsed in module ../bitwise.py. Syntax is similar but not
# identical to C data and structure definitions.

# Define the structures for each type of group here, but do not associate them
# with actual memory addresses yet
MEM_FORMAT = """
struct slot {
 u8 tx_pwr;     //0, 1, 2 == lo, medium, high
 bbcd freq[4];  // Hz/10   but must end in 00
 u8 tx_ctcss;   //see ctcss table, but radio code = CHIRP code+1. 0==off
 u8 rx_ctcss;   //see ctcss table, but radio code = CHIRP code+1. 0==off
 u8 tx_dcs;     //see dcs table, but radio code = CHIRP code+1. 0==off
 u8 rx_dcs;     //see dcs table, but radio code = CHIRP code+1. 0==off
 u8 duplex;     //(auto,offset). (0,2,4,5)= (+,-,0, auto)
 ul16 offset;   //little-endian binary * scaler, +- per duplex
                   //scaler is 25 kHz for FT-4, 50 kHz for FT-65.
 u8 tx_width;   //0=wide, 1=narrow
 u8 step;       //STEPS (0-9)=(auto,5,6.25,10,12.5,15,20,25,50,100) kHz
 u8 sql_type;   //(0-6)==(off,r-tone,t-tone,tsql,rev tn,dcs,pager)
 u8 unused;
};
// one bit per channel. 220 bits (200 mem+ 2*10 PMS) padded to fill
//exactly 2 blocks
struct bitmap {
u8 b8[28];
u8 unused[4];
};
//name struct occupies half a block (8 bytes)
//the code restricts the actual len to 6 for an FT-4
struct name {
  u8 chrs[8];    //[0-9,A-z,a-z, -] padded with spaces
};
//txfreq struct occupies 4 bytes (1/4 slot)
struct txfreq {
 bbcd freq[4];
};

//miscellaneous params. One 4-block group.
//"SMI": "Set Mode Index" of the FT-4 radio keypad function to set parameter.
//"SMI numbers on the FT-65 are different but the names in mem are the same.
struct misc {
  u8  apo;        //SMI 01. 0==off, (1-24) is the number of half-hours.
  u8  arts_beep;  //SMI 02. 0==off, 1==inrange, 2==always
  u8  arts_intv;  //SMI 03. 0==25 seconds, 1==15 seconds
  u8  battsave;   //SMI 32. 0==off, (1-5)==(200,300,500,1000,2000) ms
  u8  bclo;       //SMI 04. 0==off, 1==on
  u8  beep;       //SMI 05. (0-2)==(key+scan,key, off)
  u8  bell;       //SMI 06. (0-5)==(0,1,3,5,8,continuous) bells
  u8  cw_id[6];   //SMI 08. callsign (A_Z,0-9) (pad with space if <6)
  u8  unknown1[3];
  // addr= 2010
  u8  dtmf_mode;  //SMI 12. 0==manual, 1==auto
  u8  dtmf_delay; //SMI 11. (0-4)==(50,250,450,750,1000) ms
  u8  dtmf_speed; //SMI 13. (0,1)=(50,100) ms
  u8  edg_beep;   //SMI 14. 0==off, 1==on
  u8  key_lock;   //SMI 18. (0-2)==(key,ptt,key+ptt)
  u8  lamp;       //SMI 15. (0-4)==(5,10,30,continuous,off) secKEY
  u8  tx_led;     //SMI 17. 0==off, 1==on
  u8  bsy_led;    //SMI 16. 0==off, 1==on
  u8  moni_tcall; //SMI 19. (0-4)==(mon,1750,2100,1000,1450) tcall Hz.
  u8  pri_rvt;    //SMI 23. 0==off, 1==on
  u8  scan_resume; //SMI 34. (0-2)==(busy,hold,time)
  u8  rf_squelch;  //SMI 28. 0==off, 8==full, (1-7)==(S1-S7)
  u8  scan_lamp;  //SMI 33  0==off,1==on
  u8  unknown2;
  u8  use_cwid;   //SMI 7. 0==no, 1==yes
  u8  compander;  // compander on FT_65
  // addr 2020
  u8  unknown3;
  u8  tx_save;    //SMI 41. 0==off, 1==on (addr==2021)
  u8  vfo_spl;    //SMI 42. 0==off, 1==on
  u8  vox;        //SMI 43. 0==off, 1==on
  u8  wfm_rcv;    //SMI 44. 0==off, 1==on
  u8  unknown4;
  u8  wx_alert;   //SMI 46. 0==off, 1==0n
  u8  tot;        //SMI 39. 0-off, (1-30)== (1-30) minutes
  u8  pager_tx1;  //SMI 21. (0-49)=(1-50) epcs code (i.e., value is code-1)
  u8  pager_tx2;  //SMI 21   same
  u8  pager_rx1;  //SMI 23   same
  u8  pager_rx2;  //SMI 23   same
  u8  pager_ack;  //SMI 22   same
  u8  unknown5[3];  //possibly sql_setting and pgm_vfo_scan on FT-65?
  // addr 2030
  u8  use_passwd; //SMI 26 0==no, 1==yes
  u8  passwd[4];  //SMI 27 ASCII (0-9)
  u8  unused2[11]; //  pad out to a block boundary
};

struct dtmfset {
 u8 digit[16];    //ASCII (*,#,-,0-9,A-D). (dash-filled)
};

// area to be filled with 0xff, or just ignored
struct notused {
  u8 unused[16];
};
// areas we are still analyzing
struct unknown {
  u8 notknown[16];
};

struct progc {
  u8 usage;          //P key is (0-2) == unused, use P channel, use parm
  u8 submode:2,      //if parm!=0 submode 0-3 of mode
     parm:6;         //if usage == 2: if 0, use m-channel, else  mode
};
"""
# Actual memory layout. 0x215 blocks, in 20 groups.
MEM_FORMAT += """
#seekto 0x0000;
struct unknown radiotype;     //0000 probably a radio type ID but not sure
struct slot    memory[200];   //0010 channel memory array
struct slot    pms[20];       //0c90 10 PMS (L,U) slot pairs
struct slot    vfo[5];        //0dd0 VFO (A UHF, A VHF, B FM, B  UHF, B VHF)
struct slot    home[3];       //0e20 Home (FM, VHF, UHF)
struct bitmap  enable;        //0e50
struct bitmap  scan;          //0e70
struct notused notused0;      //0e90
struct bitmap  bankmask[10];  //0ea0
struct notused notused1[2];   //0fe0
struct name  names[220];      //1000 220 names in 110 blocks
struct notused notused2[2];   //16e0
struct txfreq  txfreqs[220];  //1700 220 freqs in 55 blocks
struct notused notused3[89];  //1a20
struct misc  settings;        //2000  4-block collection of misc params
struct notused notused4[2];   //2040
struct dtmfset dtmf[9];       //2060  sets 1-9
struct notused notused5;      //20f0
//struct progs progkeys;      //2100  not a struct. bitwise.py refuses
struct progc  progctl[4];        //2100 8 bytes. 1 2-byte struct per P key
u8 pmemndx[4];                   //2108 4 bytes, 1 per P key
u8 notused6[4];                  //210c fill out the block
struct slot  prog[4];         //2110  P key "channel" array
//---------------- end of FT-4 mem?
"""
# The remaining mem is (apparently) not available on the FT4 but is
# reported to be available on the FT-65. Not implemented here yet.
# Possibly, memory-mapped control registers that  allow for "live-mode"
# operation instead of "clone-mode" operation.
# 2150 27ff                   (unused?)
# 2800 285f       6           MRU operation?
# 2860 2fff                   (unused?)
# 3000 310f       17          (version info, etc?)
# ----------END of memory map


# Begin Serial transfer utilities for the SCU-35 cable.

# The serial transfer protocol was implemented here after snooping the wire.
# After it was implemented, we noticed that it is identical to the protocol
# implemented in th9000.py. A non-echo version is implemented in anytone_ht.py.
#
# The pipe.read and pipe.write functions use bytes, not strings. The serial
# transfer utilities operate only to move data between the memory object and
# the serial port. The code runs on either Python 2 or Python3, so some
# constructs could be better optimized for one or the other, but not both.


def get_mmap_data(radio):
    """
    horrible kludge needed until we convert entirely to Python 3 OR we add a
    slightly less horrible kludge to the Py2 or Py3 versions of memmap.py.
    The minimal change have Py3 code return a bytestring instead of a string.
    This is the only function in this module that must explicitly test for the
    data string type. It is used only in the do_upload function.
    returns the memobj data as a byte-like object.
    """
    data = radio.get_mmap().get_packed()
    if isinstance(data, bytes):
        return data
    return bytearray(radio.get_mmap()._data)


def checkSum8(data):
    """
    Calculate the 8 bit checksum of buffer
    Input: buffer   - bytes
    returns: integer
    """
    return sum(x for x in bytearray(data)) & 0xFF


def variable_len_resp(pipe):
    """
    when length of expected reply is not known, read byte at a time
    until the ack character is found.
    """
    response = b""
    i = 0
    toolong = 256        # arbitrary
    while True:
        b = pipe.read(1)
        if b == b'\x06':
            break
        else:
            response += b
            i += 1
            if i > toolong:
                LOG.debug("Response too long. got" + util.hexprint(response))
                raise errors.RadioError("Response from radio too long.")
    return(response)


def sendcmd(pipe, cmd, response_len):
    """
    send a command bytelist to radio,receive and return the resulting bytelist.
    Input: pipe         - serial port object to use
           cmd          - bytes to send
           response_len - number of bytes of expected response,
                          not including the ACK. (if None, read until ack)
    This cable is "two-wire": The TxD and RxD are "or'ed" so we receive
    whatever we send and then whatever response the radio sends. We check the
    echo and strip it, returning only the radio's response.
    We also check and strip the ACK character at the end of the response.
    """
    pipe.write(cmd)
    echo = pipe.read(len(cmd))
    if echo != cmd:
        msg = "Bad echo. Sent:" + util.hexprint(cmd) + ", "
        msg += "Received:" + util.hexprint(echo)
        LOG.debug(msg)
        raise errors.RadioError(
            "Incorrect echo on serial port. Radio off? Bad cable?")
    if response_len is None:
        return variable_len_resp(pipe)
    if response_len > 0:
        response = pipe.read(response_len)
    else:
        response = b""
    ack = pipe.read(1)
    if ack != b'\x06':
        LOG.debug("missing ack: expected 0x06, got" + util.hexprint(ack))
        raise errors.RadioError("Incorrect ACK on serial port.")
    return response


def enter_clonemode(radio):
    """
    Send the PROGRAM command and check the response. Retry if
    needed. After 3 tries, send an "END" and try some more if
    it is acknowledged.
    """
    for use_end in range(0, 3):
        for i in range(0, 3):
            try:
                if b"QX" == sendcmd(radio.pipe, b"PROGRAM", 2):
                    return
            except:
                continue
        sendcmd(radio.pipe, b"END", 0)
    raise errors.RadioError("expected QX from radio.")


def startcomms(radio, way):
    """
    For either upload or download, put the radio into PROGRAM mode
    and check the radio's ID. In this preliminary version of the driver,
    the exact nature of the ID has been inferred from a single test case.
        set up the progress bar
        send "PROGRAM" to command the radio into clone mode
        read the initial string (version?)
    """
    progressbar = chirp_common.Status()
    progressbar.msg = "Cloning " + way + " radio"
    progressbar.max = radio.numblocks
    enter_clonemode(radio)
    id_response = sendcmd(radio.pipe, b'\x02', None)
    if id_response != radio.id_str:
        substr0 = radio.id_str[:radio.id_str.find('\x00')]
        if id_response[:id_response.find('\x00')] != substr0:
            msg = "ID mismatch. Expected" + util.hexprint(radio.id_str)
            msg += ", Received:" + util.hexprint(id_response)
            LOG.warning(msg)
            raise errors.RadioError("Incorrect ID read from radio.")
        else:
            msg = "ID suspect. Expected" + util.hexprint(radio.id_str)
            msg += ", Received:" + util.hexprint(id_response)
            LOG.warning(msg)
    return progressbar


def getblock(pipe, addr, image):
    """
    read a single 16-byte block from the radio.
    send the command and check the response
    places the response into the correct offset in the supplied bytearray
    returns True if successful, False if error.
    """
    cmd = struct.pack(">cHb", b"R", addr, 16)
    response = sendcmd(pipe, cmd, 21)
    if (response[0] != b"W"[0]) or (response[1:4] != cmd[1:4]):
        msg = "Bad response. Sent:" + util.hexprint(cmd) + ", "
        msg += b"Received:" + util.hexprint(response)
        LOG.debug(msg)
        return False
    if checkSum8(response[1:20]) != bytearray(response)[20]:
        LOG.debug(b"Bad checksum: " + util.hexprint(response))
        return False
    image[addr:addr+16] = response[4:20]
    return True


def do_download(radio):
    """
    Read memory from the radio.
      call startcomms to go into program mode and check version
      create an mmap
      read the memory blocks and place the data into the mmap
      send "END"
    """
    image = bytearray(radio.get_memsize())
    pipe = radio.pipe  # Get the serial port connection
    progressbar = startcomms(radio, "from")
    for blocknum in range(radio.numblocks):
        for i in range(0, 3):
            if getblock(pipe, 16 * blocknum, image):
                break
            if i == 2:
                raise errors.RadioError(
                   "read block from radio failed 3 times")
        progressbar.cur = blocknum
        radio.status_fn(progressbar)
    sendcmd(pipe, b"END", 0)
    return memmap.MemoryMap(bytes(image))


def putblock(pipe, addr, data):
    """
    write a single 16-byte block to the radio
    send the command and check the response
    """
    chkstr = struct.pack(">Hb",  addr, 16) + data
    msg = b'W' + chkstr + struct.pack('B', checkSum8(chkstr)) + b'\x06'
    sendcmd(pipe, msg, 0)


def do_upload(radio):
    """
    Write memory image to radio
      call startcomms to go into program mode and check version
      write the memory blocks. Skip the first block
      send "END"
    """
    pipe = radio.pipe  # Get the serial port connection
    progressbar = startcomms(radio, "to")
    data = get_mmap_data(radio)
    for _i in range(1, radio.numblocks):
        putblock(pipe, 16*_i, data[16*_i:16*(_i+1)])
        progressbar.cur = _i
        radio.status_fn(progressbar)
    sendcmd(pipe, b"END", 0)
    return
# End serial transfer utilities


def bit_loc(bitnum):
    """
    return the ndx and mask for a bit location
    """
    return (bitnum // 8, 1 << (bitnum & 7))


def store_bit(bankmem, bitnum, val):
    """
    store a bit in a bankmem. Store 0 or 1 for False or True
    """
    ndx, mask = bit_loc(bitnum)
    if val:
        bankmem.b8[ndx] |= mask
    else:
        bankmem.b8[ndx] &= ~mask
    return


def retrieve_bit(bankmem, bitnum):
    """
    return True or False for a bit in a bankmem
    """
    ndx, mask = bit_loc(bitnum)
    return (bankmem.b8[ndx] & mask) != 0


# A bank is a bitmap of 220 bits. 200 mem slots and 2*10 PMS slots.
# There are 10 banks.
class YaesuSC35GenericBankModel(chirp_common.BankModel):

    def get_num_mappings(self):
        return 10

    def get_mappings(self):
        banks = []
        for i in range(1, 1 + self.get_num_mappings()):
            bank = chirp_common.Bank(self, "%i" % i, "Bank %i" % i)
            bank.index = i - 1
            banks.append(bank)
        return banks

    def add_memory_to_mapping(self, memory, bank):
        bankmem = self._radio._memobj.bankmask[bank.index]
        store_bit(bankmem, memory.number-1, True)

    def remove_memory_from_mapping(self, memory, bank):
        bankmem = self._radio._memobj.bankmask[bank.index]
        if not retrieve_bit(bankmem, memory.number-1):
            raise Exception("Memory %i is not in bank %s." %
                            (memory.number, bank))
        store_bit(bankmem, memory.number-1, False)

    # return a list of slots in a bank
    def get_mapping_memories(self, bank):
        memories = []
        for i in range(*self._radio.get_features().memory_bounds):
            if retrieve_bit(self._radio._memobj.bankmask[bank.index], i - 1):
                memories.append(self._radio.get_memory(i))
        return memories

    # return a list of banks a slot is a member of
    def get_memory_mappings(self, memory):
        memndx = memory.number - 1
        banks = []
        for bank in self.get_mappings():
            if retrieve_bit(self._radio._memobj.bankmask[bank.index], memndx):
                banks.append(bank)
        return banks

# the values in these lists must also be in the canonical UI list
# we can re-arrange the order, and we don't need to have all
# the values, but we cannot add our own values here.

DUPLEX = ["+", "", "-", "", "off", "", "split"]  # (0,2,4,5) = (+, -, 0, auto)
# The radio implements duplex "auto" as 5. We map to "". It is a convenience
# function in the radio that affects the offset, which sets the duplex value
# according to the frequency in use. Yaesu doesn't entirely adhere to the band
# plans; but worse, they save the value 'auto' instead of + or -. Why Yaesu
# is doing such a thing is beyond me. [AE6YN]
DUPLEX_AUTO_US = [
    [145100000, 145495000, 2],
    [146000000, 146395000, 0],
    [146600000, 146995000, 2],
    [147000000, 147395000, 0],
    [147600000, 147995000, 2]]
# (There are no automatic duplex values in IARU-2 70CM.)
DUPLEX_AUTO_EU = [
    [145600000, 145800000, 2],
    [438200000, 439425000, 2]]

SKIPS = ["S", ""]

POWER_LEVELS = [
    chirp_common.PowerLevel("High", watts=5.0),  # high must be first (0)
    chirp_common.PowerLevel("Mid", watts=2.5),
    chirp_common.PowerLevel("Low", watts=0.5)]

# these steps encode to 0-9 on all radios, but encoding #2 is disallowed
# on the US versions (FT-4XR)
STEP_CODE = [0, 5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0]
US_LEGAL_STEPS = list(STEP_CODE)  # copy to pass to UI on US radios
US_LEGAL_STEPS.remove(6.25)       # euro radios just use STEP_CODE

# Map the radio image sql_type (0-6) to the CHIRP mem values.
# Yaesu "TSQL" and "DCS" each map to different CHIRP values depending on the
# radio values of the tx and rx tone codes. The table is a list of rows, one
# per Yaesu sql_type (0-5). The code does not use this table when the sql_type
# is 6 (PAGER). Each row is a tuple. Its first member is a list of
# [tmode,cross] or [tmode, cross, suppress]. "Suppress" is used only when
# encoding UI-->radio. When decoding radio-->UI, two of the sql_types each
# result in 5 possibible UI decodings depending on the tx and rx codes, and the
# list in each of these rows has five members. These two row tuples each have
# two additional members to specify which of the radio fields to examine.
# The map from CHIRP UI to radio image types is also built from this table.
RADIO_TMODES = [
        ([["", None], ], ),            # sql_type= 0. off
        ([["Cross", "->Tone"], ], ),   # sql_type= 1. R-TONE
        ([["Tone", None], ], ),        # sql_type= 2. T-TONE
        ([                             # sql_type= 3. TSQL:
          ["", None],                       # tx==0, rx==0 : invalid
          ["TSQL", None],                   # tx==0
          ["Tone", None],                   # rx==0
          ["Cross", "Tone->Tone"],          # tx!=rx
          ["TSQL", None]                    # tx==rx
         ], "tx_ctcss", "rx_ctcss"),     # tx and rx fields to check
        ([["TSQL-R", None], ], ),      # sql_type= 4. REV TN
        ([                             # sql_type= 5.DCS:
          ["", None],                       # tx==0, rx==0 : invalid
          ["Cross", "->DTCS", "tx_dcs"],    # tx==0. suppress tx
          ["Cross", "DTCS->", "rx_dcs"],    # rx==0. suppress rx
          ["Cross", "DTCS->DTCS"],          # tx!=rx
          ["DTCS", None]                    # tx==rx
         ], "tx_dcs", "rx_dcs"),         # tx and rx fields to check
        #                              # sql_type= 6. PAGER is a CHIRP "extra"
        ]

# Find all legal values for the tmode and cross fields for the UI.
# We build two dictionaries to do the lookups when encoding.
# The reversed range is a kludge: by happenstance, earlier duplicates
# in the above table are the preferred mapping, they override the
# later ones when we process the table backwards.
TONE_DICT = {}          # encode sql_type.
CROSS_DICT = {}         # encode sql_type.

for sql_type in reversed(range(0, len(RADIO_TMODES))):
    sql_type_row = RADIO_TMODES[sql_type]
    for decode_row in sql_type_row[0]:
        suppress = None
        if len(decode_row) == 3:
            suppress = decode_row[2]
        TONE_DICT[decode_row[0]] = (sql_type, suppress)
        if decode_row[1]:
            CROSS_DICT[decode_row[1]] = (sql_type, suppress)

# The keys are added to the "VALID" lists using code that puts those lists
# in the same order as the UI's default order instead of the random dict
# order or the arbitrary build order.
VALID_TONE_MODES = []   # list for UI.
VALID_CROSS_MODES = []  # list for UI.
for name in chirp_common.TONE_MODES:
    if name in TONE_DICT:
        VALID_TONE_MODES += [name]
for name in chirp_common.CROSS_MODES:
    if name in CROSS_DICT:
        VALID_CROSS_MODES += [name]


DTMF_CHARS = "0123456789ABCD*#- "
CW_ID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ "
PASSWD_CHARS = "0123456789"
CHARSET = CW_ID_CHARS + "abcdefghijklmnopqrstuvwxyz*+-/@"
PMSNAMES = ["%s%02d" % (c, i) for i in range(1, 11) for c in ('L', 'U')]

# Four separate arrays of special channel mems.
# Each special has unique constrants: band, name yes/no, and pms L/U
# The FT-65 class replaces the "prog" entry in this list.
# The name field must be the name of a slot array in MEM_FORMAT
SPECIALS_FT4 = [
    ("pms", PMSNAMES),
    ("vfo", ["VFO A UHF", "VFO A VHF", "VFO B FM", "VFO B VHF", "VFO B UHF"]),
    ("home", ["HOME FM", "HOME VHF", "HOME UHF"]),
    ("prog", ["P1", "P2"])
    ]
SPECIALS_FT65 = SPECIALS_FT4
FT65_PROGS = ("prog", ["P1", "P2", "P3", "P4"])
SPECIALS_FT65[-1] = FT65_PROGS    # replace the last entry (P key names)


VALID_BANDS_DUAL = [
    (65000000, 108000000),     # broadcast FM, receive only
    (136000000, 174000000),    # VHF
    (400000000, 480000000)     # UHF
    ]

VALID_BANDS_VHF = [
    (65000000, 108000000),     # broadcast FM, receive only
    (136000000, 174000000),    # VHF
    ]

# bands for the five VFO and three home channel memories
BAND_ASSIGNMENTS_DUALBAND = [2, 1, 0, 1, 2, 0, 1, 2]  # all locations used
BAND_ASSIGNMENTS_MONO_VHF = [1, 1, 0, 1, 1, 0, 1, 1]  # UHF locations unused


# None, and 50 Tones. Use this explicit array because the
# one in chirp_common could change and no longer describe our radio
TONE_MAP = [
    None, 67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5,
    85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5,
    107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
    131.8, 136.5, 141.3, 146.2, 151.4, 156.7,
    159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
    177.3, 179.9, 183.5, 186.2, 189.9, 192.8,
    196.6, 199.5, 203.5, 206.5, 210.7, 218.1,
    225.7, 229.1, 233.6, 241.8, 250.3, 254.1
    ]

# None, and 104 DTCS Codes. Use this explicit array because the
# one in chirp_common could change and no longer describe our radio
DTCS_MAP = [
    None, 23,  25,  26,  31,  32,  36,  43,  47,  51,  53,  54,
    65,  71,  72,  73,  74,  114, 115, 116, 122, 125, 131,
    132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174,
    205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252,
    255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325,
    331, 332, 343, 346, 351, 356, 364, 365, 371, 411, 412,
    413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464,
    465, 466, 503, 506, 516, 523, 526, 532, 546, 565, 606,
    612, 624, 627, 631, 632, 654, 662, 664, 703, 712, 723,
    731, 732, 734, 743, 754
    ]

# The legal PAGER codes are the same as the CTCSS codes, but we
# pass them to the UI as a list of strings
EPCS_CODES = [format(flt) for flt in [0] + TONE_MAP[1:]]


# allow a child class to add a param to its class
# description list. used when a specific radio class has
# a param that is not in the generic list.
def add_paramdesc(desc_list, group, param):
    for description in desc_list:
        groupname, title, parms = description
        if group == groupname:
            description[2].append(param)
            return


class YaesuSC35GenericRadio(chirp_common.CloneModeRadio,
                            chirp_common.ExperimentalRadio):
    """
    Base class for all Yaesu radios using the SCU-35 programming cable
    and its protocol. Classes for sub families extend this class and
    are found towards the end of this file.
    """
    VENDOR = "Yaesu"
    MODEL = "SCU-35Generic"  # No radio directly uses the base class
    BAUD_RATE = 9600
    MAX_MEM_SLOT = 200
    NEEDS_COMPAT_SERIAL = False

    # These settings are common to all radios in this family.
    _valid_chars = chirp_common.CHARSET_ASCII
    numblocks = 0x215           # number of 16-byte blocks in the radio
    _memsize = 16 * numblocks   # used by CHIRP file loader to guess radio type
    MAX_MEM_SLOT = 200

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = (
            'Tested only by the developer and only on a single radio.\n'
            'Proceed at your own risk!'
            )

        rp.pre_download = "".join([
            "1. Connect programming cable to MIC jack.\n",
            "2. Press OK."
            ]
            )
        rp.pre_upload = rp.pre_download
        return rp

    # identify the features that can be manipulated on this radio.
    # mentioned here only when different from defaults in chirp_common.py
    def get_features(self):

        rf = chirp_common.RadioFeatures()
        specials = [name for s in self.class_specials for name in s[1]]
        rf.valid_special_chans = specials
        rf.memory_bounds = (1, self.MAX_MEM_SLOT)
        rf.valid_duplexes = DUPLEX
        rf.valid_tmodes = VALID_TONE_MODES
        rf.valid_cross_modes = VALID_CROSS_MODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tuning_steps = self.legal_steps
        rf.valid_skips = SKIPS
        rf.valid_characters = CHARSET
        rf.valid_name_length = self.namelen
        rf.valid_modes = ["FM", "NFM"]
        rf.valid_bands = self.valid_bands
        rf.can_odd_split = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = False    # REV TN reverses the tone, not the dcs
        rf.has_cross = True
        rf.has_settings = True

        return rf

    def get_bank_model(self):
        return YaesuSC35GenericBankModel(self)

    # read and parse the radio memory
    def sync_in(self):
        try:
            self._mmap = do_download(self)
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        self.process_mmap()

    # write the memory image to the radio
    def sync_out(self):
        try:
            do_upload(self)
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    # There are about 40 settings and most are handled generically in
    # get_settings. get_settings invokes these handlers for the few
    # that are more complicated.

    # callback for setting  byte arrays: DTMF[0-9], passwd, and CW_ID
    def apply_str_to_bytearray(self, element, obj):
        lng = len(obj)
        strng = (element.value.get_value() + "                ")[:lng]
        bytes = bytearray(strng, "ascii")
        for x in range(0, lng):    # memobj cannot iterate, so byte-by-byte
            obj[x] = bytes[x]
        return

    # add a string value to the RadioSettings
    def get_string_setting(self, obj, valid_chars, desc1, desc2, group):
        content = ''
        maxlen = len(obj)
        for x in range(0, maxlen):
            content += chr(obj[x])
        val = RadioSettingValueString(0, maxlen, content, True, valid_chars)
        rs = RadioSetting(desc1, desc2, val)
        rs.set_apply_callback(self.apply_str_to_bytearray, obj)
        group.append(rs)

    # called when found in the group_descriptions table to handle string value
    def get_strset(self, group, parm):
        #   parm =(paramname, paramtitle,(handler,[handler params])).
        objname, title, fparms = parm
        myparms = fparms[1]
        obj = getattr(self._memobj.settings,  objname)
        self.get_string_setting(obj, myparms[0], objname, title, group)

    # called when found in the group_descriptions table for DTMF strings
    def get_dtmfs(self, group, parm):
        objname, title, fparms = parm
        for i in range(1, 10):
            dtmf_digits = self._memobj.dtmf[i - 1].digit
            self.get_string_setting(
                dtmf_digits, DTMF_CHARS,
                "dtmf_%i" % i, "DTMF Autodialer Memory %i" % i, group)

    def apply_P(self, element, pnum, memobj):
        memobj.progctl[pnum].usage = element.value

    def apply_Pmode(self, element, pnum, memobj):
        memobj.progctl[pnum].parm = element.value

    def apply_Psubmode(self, element, pnum, memobj):
        memobj.progctl[pnum].submode = element.value

    def apply_Pmem(self, element, pnum, memobj):
        memobj.pmemndx[pnum] = element.value

    MEMLIST = ["%d" % i for i in range(1, MAX_MEM_SLOT + 1)] + PMSNAMES
    USAGE_LIST = ["unused", "P channel", "mode or M channel"]

    # called when found in the group_descriptions table
    # returns the settings for the programmable keys (P1-P4)
    def get_progs(self, group, parm):
        _progctl = self._memobj.progctl
        _progndx = self._memobj.pmemndx

        def get_prog(i, val_list, valndx, sname, longname, f_apply):
            k = str(i + 1)
            val = val_list[valndx]
            valuelist = RadioSettingValueList(val_list, val)
            rs = RadioSetting(sname + k, longname + k, valuelist)
            rs.set_apply_callback(f_apply, i, self._memobj)
            group.append(rs)
        for i in range(0, self.Pkeys):
            get_prog(i, self.USAGE_LIST,  _progctl[i].usage,
                     "P", "Programmable key ",  self.apply_P)
            get_prog(i, self.SETMODES, _progctl[i].parm, "modeP",
                     "mode for Programmable key ",  self.apply_Pmode)
            get_prog(i, ["0", "1", "2", "3"], _progctl[i].submode, "submodeP",
                     "submode for Programmable key ",  self.apply_Psubmode)
            get_prog(i, self.MEMLIST, _progndx[i], "memP",
                     "mem for Programmable key ",  self.apply_Pmem)
    # ------------ End of special settings handlers.

    # list of group description tuples: [groupame,group title, [param list]].
    # A param is a tuple:
    #  for a simple param: (paramname, paramtitle,[valuename list])
    #  for a handler param: (paramname, paramtitle,( handler,[handler params]))
    # This is a class variable. subclasses msut create a variable named
    # class_group_descs. The FT-4 classes simply equate this, but the
    # FT-65 classes must copy and modify this.
    group_descriptions = [
        ("misc", "Miscellaneous Settings", [    # misc
         ("apo", "Automatic Power Off",
          ["OFF"] + ["%0.1f" % (x * 0.5) for x in range(1, 24 + 1)]),
         ("bclo", "Busy Channel Lock-Out", ["OFF", "ON"]),
         ("beep", "Enable the Beeper", ["OFF", "KEY", "KEY+SC"]),
         ("bsy_led", "Busy LED", ["ON", "OFF"]),
         ("edg_beep", "Band Edge Beeper", ["OFF", "ON"]),
         ("vox", "VOX", ["OFF", "ON"]),
         ("rf_squelch", "RF Squelch Threshold",
          ["OFF", "S-1", "S-2", "S-3", "S-4", "S-5", "S-6", "S-7", "S-FULL"]),
         ("tot", "Timeout Timer",
          ["OFF"] + ["%dMIN" % (x) for x in range(1, 30 + 1)]),
         ("tx_led", "TX LED", ["OFF", "ON"]),
         ("use_cwid", "use CW ID", ["NO", "YES"]),
         ("cw_id",  "CW ID Callsign",  (get_strset, [CW_ID_CHARS])),  # handler
         ("vfo_spl", "VFO Split", ["OFF", "ON"]),
         ("wfm_rcv", "Enable Broadband FM", ["OFF", "ON"]),
         ("passwd", "Password",  (get_strset, [PASSWD_CHARS]))  # handler
         ]),
        ("arts", "ARTS Settings", [  # arts
         ("arts_beep", "ARTS BEEP", ["OFF", "INRANG", "ALWAYS"]),
         ("arts_intv", "ARTS Polling Interval", ["25 SEC", "15 SEC"])
         ]),
        ("ctcss", "CTCSS/DCS/DTMF Settings", [  # ctcss
         ("bell", "Bell Repetitions", ["OFF", "1T", "3T", "5T", "8T", "CONT"]),
         ("dtmf_mode", "DTMF Mode", ["Manual", "Auto"]),
         ("dtmf_delay", "DTMF Autodialer Delay Time",
          ["50 MS", "100 MS", "250 MS", "450 MS", "750 MS", "1000 MS"]),
         ("dtmf_speed", "DTMF Autodialer Sending Speed", ["50 MS", "100 MS"]),
         ("dtmf", "DTMF Autodialer Memory ",  (get_dtmfs, []))  # handler
         ]),
        ("switch", "Switch/Knob Settings", [  # switch
         ("lamp", "Lamp Mode", ["5SEC", "10SEC", "30SEC", "KEY", "OFF"]),
         ("moni_tcall", "MONI Switch Function",
          ["MONI", "1750", "2100", "1000", "1450"]),
         ("key_lock", "Lock Function", ["KEY", "PTT", "KEY+PTT"]),
         ("Pkeys", "Pkey fields", (get_progs, []))
         ]),
        ("scan", "Scan Settings", [   # scan
         ("scan_resume", "Scan Resume Mode", ["BUSY", "HOLD", "TIME"]),
         ("pri_rvt", "Priority Revert", ["OFF", "ON"]),
         ("scan_lamp", "Scan Lamp", ["OFF", "ON"]),
         ("wx_alert", "Weather Alert Scan", ["OFF", "ON"])
         ]),
        ("power", "Power Saver Settings", [  # power
         ("battsave", "Receive Mode Battery Save Interval",
          ["OFF", "200 MS", "300 MS", "500 MS", "1 S", "2 S"]),
         ("tx_save", "Transmitter Battery Saver", ["OFF", "ON"])
         ]),
        ("eai", "EAI/EPCS Settings", [  # eai
         ("pager_tx1", "TX pager frequency 1", EPCS_CODES),
         ("pager_tx2", "TX pager frequency 2", EPCS_CODES),
         ("pager_rx1", "RX pager frequency 1", EPCS_CODES),
         ("pager_rx2", "RX pager frequency 2", EPCS_CODES),
         ("pager_ack", "Pager answerback", ["NO", "YES"])
         ])
        ]
    # ----------------end of group_descriptions

    # returns the current values of all the settings in the radio memory image,
    # in the form of a RadioSettings list. Uses the class_group_descs
    # list to create the groups and params. Valuelist scalars are handled
    # inline. More complex params are built by calling the special handlers.
    def get_settings(self):
        _settings = self._memobj.settings
        groups = RadioSettings()
        for description in self.class_group_descs:
            groupname, title, parms = description
            group = RadioSettingGroup(groupname, title)
            groups.append(group)
            for parm in parms:
                param, title, opts = parm
                try:
                    if isinstance(opts, list):
                        # setting is a single value from the list
                        objval = getattr(_settings, param)
                        value = opts[objval]
                        valuelist = RadioSettingValueList(opts, value)
                        group.append(RadioSetting(param, title, valuelist))
                    else:
                        # setting  needs special handling. opts[0] is a
                        # function name
                        opts[0](self,  group, parm)
                except Exception as e:
                    LOG.debug(
                        "%s: cannot set %s to %s" % (e, param, repr(objval))
                        )
        return groups
        # end of get_settings

    # modify settings values in the radio memory image
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
                    setattr(_settings, name, value)

                LOG.debug("Setting %s: %s" % (name, value))
            except:
                LOG.debug(element.get_name())
                raise

    # maps a boolean pair (tx==0,rx==0) to the numbers 0-3
    LOOKUP = [[True, True], [True, False], [False, True], [False, False]]

    def decode_sql(self, mem, chan):
        """
        examine the radio channel fields and determine the correct
        CHIRP CSV values for tmode, cross_mode, and sql_override
        """
        mem.extra = RadioSettingGroup("Extra", "extra")
        extra_modes = ["(None)", "PAGER"]
        value = extra_modes[chan.sql_type == 6]
        valuelist = RadioSettingValueList(extra_modes, value)
        rs = RadioSetting("sql_override", "Squelch override", valuelist)
        mem.extra.append(rs)
        if chan.sql_type == 6:
            return
        sql_map = RADIO_TMODES[chan.sql_type]
        ndx = 0
        if len(sql_map[0]) > 1:
            # the sql_type is TSQL or DCS, so there are multiple UI mappings
            x = getattr(chan, sql_map[1])
            r = getattr(chan, sql_map[2])
            ndx = self.LOOKUP.index([x == 0, r == 0])
            if ndx == 3 and x == r:
                ndx = 4
        mem.tmode = sql_map[0][ndx][0]
        cross = sql_map[0][ndx][1]
        if cross:
            mem.cross_mode = cross
        if chan.rx_ctcss:
            mem.ctone = TONE_MAP[chan.rx_ctcss]
        if chan.tx_ctcss:
            mem.rtone = TONE_MAP[chan.tx_ctcss]
        if chan.tx_dcs:
            mem.dtcs = DTCS_MAP[chan.tx_dcs]
        if chan.rx_dcs:
            mem.rx_dtcs = DTCS_MAP[chan.rx_dcs]

    def encode_sql(self, mem, chan):
        """
        examine CHIRP's mem.tmode and mem.cross_mode and set the values
        for the radio sql_type, dcs codes, and ctcss codes. We set all four
        codes, and then zero out a code if needed when Tone or DCS is one-way
        """
        chan.tx_ctcss = TONE_MAP.index(mem.rtone)
        chan.tx_dcs = DTCS_MAP.index(mem.dtcs)
        chan.rx_ctcss = TONE_MAP.index(mem.ctone)
        chan.rx_dcs = DTCS_MAP.index(mem.rx_dtcs)
        if mem.tmode == "TSQL":
            chan.tx_ctcss = chan.rx_ctcss  # CHIRP uses ctone for TSQL
        if mem.tmode == "DTCS":
            chan.tx_dcs = chan.rx_dcs     # CHIRP uses rx_dtcs for DTCS
        # select the correct internal dictionary and key
        mode_dict, key = [
            (TONE_DICT, mem.tmode),
            (CROSS_DICT, mem.cross_mode)
            ][mem.tmode == "Cross"]
        # now look up that key in that dictionary.
        chan.sql_type, suppress = mode_dict[key]
        if suppress:
            setattr(chan, suppress, 0)
        for setting in mem.extra:
            if (setting.get_name() == 'sql_override'):
                value = str(setting.value)
                if value == "PAGER":
                    chan.sql_type = 6
        return

    # given a CHIRP memory ref, get the radio memobj for it.
    # A memref is either a number or the name of a special
    # CHIRP will sometimes use numbers (>MAX_SLOTS) for specials
    # returns the obj and several attributes
    def slotloc(self, memref):
        array = None
        num = memref
        sname = memref
        if isinstance(memref, str):   # named special?
            num = self.MAX_MEM_SLOT + 1
            for x in self.class_specials:
                try:
                    ndx = x[1].index(memref)
                    array = x[0]
                    break
                except:
                    num += len(x[1])
            if array is None:
                LOG.debug("unknown Special %s", memref)
                raise
            num += ndx
        elif memref > self.MAX_MEM_SLOT:    # numbered special?
            ndx = memref - (self.MAX_MEM_SLOT + 1)
            for x in self.class_specials:
                if ndx < len(x[1]):
                    array = x[0]
                    sname = x[1][ndx]
                    break
                ndx -= len(x[1])
            if array is None:
                LOG.debug("memref number %d out of range", memref)
                raise
        else:                    # regular memory slot
            array = "memory"
            ndx = memref - 1
        memloc = getattr(self._memobj, array)[ndx]
        return (memloc, ndx, num, array, sname)
        # end of slotloc

    # return the raw info for a memory channel
    def get_raw_memory(self, memref):
        memloc, ndx, num, regtype, sname = self.slotloc(memref)
        if regtype == "memory":
            return repr(memloc)
        else:
            return repr(memloc) + repr(self._memobj.names[ndx])

    # return the info for a memory channel In CHIRP canonical form
    def get_memory(self, memref):

        def clean_name(obj):     # helper func to tidy up the name
            name = ''
            for x in range(0, self.namelen):
                y = obj[x]
                if y == 0:
                    break
                if y == 0x7F:    # when programmed from VFO
                    y = 0x20
                name += chr(y)
            return name.rstrip()

        def get_duplex(freq):    # auto duplex to real duplex
            """
            Select the duplex direction if duplex == 'auto'.
            0 is +, 2 is -, and 4 is none.
            """
            return_value = 4     # off, if not in auto range
            for x in self.DUPLEX_AUTO:
                if freq in range(x[0], x[1]):
                    return_value = x[2]
            return return_value

        mem = chirp_common.Memory()
        _mem, ndx, num, regtype, sname = self.slotloc(memref)
        mem.number = num

        # First, we need to know whether a channel is enabled,
        # then we can process any channel parameters.
        # It was found (at least on an FT-25) that channels might be
        # uninitialized and memory is just completely filled with 0xFF.

        if regtype == "pms":
            mem.extd_number = sname
        if regtype in ["memory", "pms"]:
            ndx = num - 1
            mem.name = clean_name(self._memobj.names[ndx].chrs)
            mem.empty = not retrieve_bit(self._memobj.enable, ndx)
            mem.skip = SKIPS[retrieve_bit(self._memobj.scan, ndx)]
        else:
            mem.empty = False
            mem.extd_number = sname
            mem.immutable = ["number", "extd_number", "name", "skip"]

        # So, now if channel is not empty, we can do the evaluation of
        # all parameters. Otherwise we set them to defaults.

        if mem.empty:
            mem.freq = 0
            mem.offset = 0
            mem.duplex = "off"
            mem.power = POWER_LEVELS[0]  # "High"
            mem.mode = "FM"
            mem.tuning_step = 0
        else:
            mem.freq = int(_mem.freq) * 10
            txfreq = int(self._memobj.txfreqs[ndx].freq) * 10
            if _mem.duplex == 5:  # auto offset
                mem.duplex = DUPLEX[get_duplex(mem.freq)]
            else:
                mem.duplex = DUPLEX[_mem.duplex]
            if _mem.duplex == 6:  # split: offset is tx frequency
                mem.offset = txfreq
            else:
                mem.offset = int(_mem.offset) * self.freq_offset_scale
            self.decode_sql(mem, _mem)
            mem.power = POWER_LEVELS[2 - _mem.tx_pwr]
            mem.mode = ["FM", "NFM"][_mem.tx_width]
            mem.tuning_step = STEP_CODE[_mem.step]
        return mem

    def enforce_band(self, memloc, freq, mem_num, sname):
        """
        vfo and home channels are each restricted to a particular band.
        If the frequency is not in the band, use the lower bound
        Raise an exception to cause UI to pop up an error message
        """
        first_vfo_num = self.MAX_MEM_SLOT + len(PMSNAMES) + 1
        band = BAND_ASSIGNMENTS[mem_num - first_vfo_num]
        frange = self.valid_bands[band]
        if freq >= frange[0] and freq <= frange[1]:
            memloc.freq = freq / 10
            return freq
        memloc.freq = frange[0] / 10
        raise Exception("freq out of range for %s" % sname)

    # modify a radio channel in memobj based on info in CHIRP canonical form
    def set_memory(self, mem):
        _mem, ndx, num, regtype, sname = self.slotloc(mem.number)
        assert(_mem)
        if mem.empty:
            if regtype in ["memory", "pms"]:
                store_bit(self._memobj.enable, ndx, False)
                return

        txfreq = mem.freq / 10     # really. RX freq is used for TX base
        _mem.freq = txfreq
        self.encode_sql(mem, _mem)
        if mem.power:
            _mem.tx_pwr = 2 - POWER_LEVELS.index(mem.power)
        else:
            _mem.tx_pwr = 0  # set to "High" if CHIRP canonical value is None
        _mem.tx_width = mem.mode == "NFM"
        _mem.step = STEP_CODE.index(mem.tuning_step)

        _mem.offset = mem.offset / self.freq_offset_scale
        duplex = mem.duplex
        if regtype in ["memory", "pms"]:
            ndx = num - 1
            store_bit(self._memobj.enable, ndx, True)
            store_bit(self._memobj.scan, ndx, SKIPS.index(mem.skip))
            nametrim = (mem.name + "        ")[:8]
            self._memobj.names[ndx].chrs = bytearray(nametrim, "ascii")
            if mem.duplex == "split":
                txfreq = mem.offset / 10
            self._memobj.txfreqs[num-1].freq = txfreq
        _mem.duplex = DUPLEX.index(duplex)
        if regtype in ["vfo", "home"]:
            self.enforce_band(_mem, mem.freq, num, sname)

        return


class YaesuFT4GenericRadio(YaesuSC35GenericRadio):
    """
    FT-4 sub family class. Classes for individual radios extend
    these classes and are found at the end of this file.
    """
    class_specials = SPECIALS_FT4
    Pkeys = 2     # number of programmable keys
    namelen = 6   # length of the mem name display on the front-panel
    freq_offset_scale = 25000
    class_group_descs = YaesuSC35GenericRadio.group_descriptions
    # names for the setmode function for the programmable keys. Mode zero means
    # that the key is programmed for a memory not a setmode.
    SETMODES = [
        "mem", "apo", "ar bep", "ar int", "beclo",              # 00-04
        "beep", "bell", "cw id", "cw wrt", "dc vlt",            # 05-09
        "dcs cod", "dt dly", "dt set", "dtc spd", "edg.bep",    # 10-14
        "lamp", "led.bsy", "led.tx", "lock", "m/t-cl",          # 15-19
        "mem.del", "mem.tag", "pag.abk", "pag.cdr", "pag.cdt",  # 20-24
        "pri.rvt", "pswd", "pswdwt", "rf sql", "rpt.ars",       # 25-29
        "rpt.frq", "rpt.sft", "rxsave", "scn.lmp", "scn.rsm",   # 30-34
        "skip", "sql.typ", "step", "tn frq", "tot",             # 35-39
        "tx pwr", "tx save", "vfo.spl", "vox", "wfm.rcv",       # 40-44
        "w/n.dev", "wx.alert"                                   # 45-46
        ]


class YaesuFT65GenericRadio(YaesuSC35GenericRadio):
    """
    FT-65 sub family class. Classes for individual radios extend
    these classes and are found at the end of this file.
    """
    class_specials = SPECIALS_FT65
    Pkeys = 4     # number of programmable keys
    namelen = 8   # length of the mem name display on the front-panel
    freq_offset_scale = 50000
    # we need a deep copy here because we are adding deeper than the top level.
    class_group_descs = copy.deepcopy(YaesuSC35GenericRadio.group_descriptions)
    add_paramdesc(
        class_group_descs, "misc", ("compander", "Compander", ["OFF", "ON"]))
    # names for the setmode function for the programmable keys. Mode zero means
    # that the key is programmed for a memory not a setmode.
    SETMODES = [
        "mem", "apo", "arts", "battsave", "b-ch.l/o",              # 00-04
        "beep", "bell", "compander", "ctcss", "cw id",             # 05-09
        "dc volt", "dcs code", "dtmf set", "dtmf wrt", "edg bep",  # 10-14
        "key lock", "lamp", "ledbsy", "mem del", "mon/t-cl",       # 15-19
        "name tag", "pager", "password", "pri.rvt", "repeater",    # 20-24
        "resume", "rf.sql", "scn.lamp", "skip", "sql type",        # 25-29
        "step", "tot", "tx pwr", "tx save", "vfo.spl",             # 30-34
        "vox", "wfm.rcv", "wide/nar", "wx alert", "scramble"       # 35-39
        ]


# Classes for each individual radio.


@directory.register
class YaesuFT4XRRadio(YaesuFT4GenericRadio):
    """
    FT-4X dual band, US version
    """
    MODEL = "FT-4XR"
    id_str = b'IFT-35R\x00\x00V100\x00\x00'
    valid_bands = VALID_BANDS_DUAL
    DUPLEX_AUTO = DUPLEX_AUTO_US
    legal_steps = US_LEGAL_STEPS
    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_DUALBAND


@directory.register
class YaesuFT4XERadio(YaesuFT4GenericRadio):
    """
    FT-4X dual band, EU version
    """
    MODEL = "FT-4XE"
    id_str = b'IFT-35R\x00\x00V100\x00\x00'
    valid_bands = VALID_BANDS_DUAL
    DUPLEX_AUTO = DUPLEX_AUTO_EU
    legal_steps = STEP_CODE
    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_DUALBAND


@directory.register
class YaesuFT4VRRadio(YaesuFT4GenericRadio):
    """
    FT-4V VHF, US version
    """
    MODEL = "FT-4VR"
    id_str = b'IFT-15R\x00\x00V100\x00\x00'
    valid_bands = VALID_BANDS_VHF
    DUPLEX_AUTO = DUPLEX_AUTO_US
    legal_steps = US_LEGAL_STEPS
    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_MONO_VHF


# No image available yet
# @directory.register
# class YaesuFT4VERadio(YaesuFT4GenericRadio):
#    """
#    FT-4V VHF, EU version
#    """
#    MODEL = "FT-4VE"
#    id_str = b'IFT-15R\x00\x00V100\x00\x00'
#    valid_bands = VALID_BANDS_VHF
#    DUPLEX_AUTO = DUPLEX_AUTO_EU
#    legal_steps = STEP_CODE
#    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_MONO_VHF


@directory.register
class YaesuFT65RRadio(YaesuFT65GenericRadio):
    """
    FT-65 dual band, US version
    """
    MODEL = "FT-65R"
    id_str = b'IH-420\x00\x00\x00V100\x00\x00'
    valid_bands = VALID_BANDS_DUAL
    DUPLEX_AUTO = DUPLEX_AUTO_US
    legal_steps = US_LEGAL_STEPS
    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_DUALBAND


@directory.register
class YaesuFT65ERadio(YaesuFT65GenericRadio):
    """
    FT-65 dual band, EU version
    """
    MODEL = "FT-65E"
    id_str = b'IH-420\x00\x00\x00V100\x00\x00'
    valid_bands = VALID_BANDS_DUAL
    DUPLEX_AUTO = DUPLEX_AUTO_EU
    legal_steps = STEP_CODE
    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_DUALBAND


@directory.register
class YaesuFT25RRadio(YaesuFT65GenericRadio):
    """
    FT-25 VHF, US version
    """
    MODEL = "FT-25R"
    id_str = b'IFT-25R\x00\x00V100\x00\x00'
    valid_bands = VALID_BANDS_VHF
    DUPLEX_AUTO = DUPLEX_AUTO_US
    legal_steps = US_LEGAL_STEPS
    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_MONO_VHF


# No image available yet
# @directory.register
# class YaesuFT25ERadio(YaesuFT65GenericRadio):
#    """
#    FT-25 VHF, EU version
#    """
#    MODEL = "FT-25E"
#    id_str = b'IFT-25R\x00\x00V100\x00\x00'
#    valid_bands = VALID_BANDS_VHF
#    DUPLEX_AUTO = DUPLEX_AUTO_EU
#    legal_steps = STEP_CODE
#    BAND_ASSIGNMENTS = BAND_ASSIGNMENTS_MONO_VHF
