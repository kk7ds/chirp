# Copyright 2024 Tommy <tommy83033@gmail.com>
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


import struct
import logging
import math
import time
from enum import Enum

from chirp import memmap, chirp_common, bitwise, directory, errors
from chirp import crc
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettingValueList,
    RadioSettingValueString,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueFloat)


LOG = logging.getLogger(__name__)

# This is the minimum required firmare version supported by this driver
REQUIRED_VER = (1, 1, 11, 6)

MEM_FORMAT = """

#seekto 0x0E;
struct{
    u8 modelnumber[32];
    u8 hardwareversion[2];
    u8 serialno[16];
    ul32 freqmin;
    ul32 freqmax;
    u8 rev_1;
    u8 saleterr;
    u8 radiomode;
    u8 rev[7];
} radioinfo;

#seekto 0x52;
struct{
    u8 dataver[2];
    u8 softver[4];
    u8 rev[4];
    }dataver;

#seekto 0x5C;
struct {
  u8 readpwd[8];
  u8 writepwd[8];
  u8 poweronpwd[8];
  u8 squelch:4,
     rev_1:4;
  u8 powersavingdelaytime:4,
     powersavingmode:4;
  u8 tk1_short;
  u8 tk1_long;
  u8 sk1_short;
  u8 sk1_long;
  u8 sk2_short;
  u8 sk2_long;
  u8 longtime;
  u8 chknoblock:1,
     sidekeylock:1,
     panellock:1,
     rev_2:3,
     autoormanuallock:1,
     keylockswitch:1;
  u8 wxscan:1,
     agc:1,
     rtcreport:1,
     displaybatterylevel:1,
     batterlevelreport:1,
     lowbattery:1,
     stunmode:2;
  u8 voiceprompts:1,
     touchtone:1,
     txpermittone:1,
     channelmode:1,
     screenlight:1,
     rogerbeep:1,
     rev_3:2;
  ul16 poweron_type_1:4,
       homepoweronzone_1:12;
  ul16 homepoweronch_1;
  u8 relaytaildelay;
  u8 radioid[10];
  u8 radioname[16];
  u8 micmain;
  u8 agcmain:4,
     agcthreshold:4;
  u8 scenemode;
  u8 autooff;
  u8 menuouttime;
  u8 voxthreshold:4,
     voxdelaytime:4;
  u8 rev_4:1,
     homeselect:3,
     homeindex:2,
     chdisplay:2;
  ul16 poweron_type_2:4,
     homepoweronzone_2:12;
  ul16 homepoweronch_2;
  ul16 homepoweronzone_3;
  ul16 homepoweronch_3;
  ul16 freqstep;
  u8 language;
  u8 backlightbrightness:4,
     backlighttime:4;
  u8 wxch;
  u8 calltone;
  u8 rev_5:5,
     homechtype_3:1,
     homechtype_2:1,
     homechtype_1:1;
  u8 spreadspectrummode;
  u8 salezone;
  u8 tailsoundeliminationsfre:7,
     tailsoundeliminationswitch:1;
  u8 singletone;
  u8 scanlist;
  u8 rev_6[6];
} settings;

#seekto 0xc0;
struct  {
    ul16 zonenum;
    ul16 zoneindex[64];
} zonedata;

#seekto 0x142;
struct {
    char name[14];
    ul16 chnum;
    ul16 chindex[16];
} zones[64];

#seekto 0x0D42;
struct  {
    ul16 chnum;
    ul16 chindex[1027];
} channeldata;

#seekto 0x154a;
struct  {
  char alias[14];
  u8 chmode:4,
     chpro:4;
  u8 fixedpower:1,
     fixedbandwidth:1,
     tailelimination:2,
     power:2,
     bandwidth:2;
  ul32 rxfreq;
  ul32 txfreq;
  u16 rxctcvaluetype:2,
      rxctctypecode:1,
      rev_1:1,
      rxctc:12;
  u8 rxsqlmode;
  u16 txctcvaluetype:2,
      txctctypecode:1,
      rev_2:1,
      txctc:12;
  u8 totpermissions:2,
     tottime:6;
  u8 vox:1,
     companding:1,
     scramble:1,
     offlineorreversal:2,
     rev_3:3;
  u8 voxthreshold:4,
     voxdelaytime:4;
  u8 autoscan:1,
     scanlist:7;
  u8 alarmlist;
  u8 dtmfsignalinglist:4,
     pttidtype:2,
     rev_4:2;
  ul16 dtmfcallid;
  u8 reserve[3];
} channels[1027];

#seekto 0xb5c2;
struct  {
    ul16 scannum;
    ul16 scanindex[16];
} scandata;

#seekto 0xb5e4;
struct {
   char name[14];
   u8 scantxch:4,
      scancondition:4;
   u8 hangtime:4,
      talkback:1,
      scanstatus:3;
   u8 chnum;
   ul16 specifych;
   ul16 PriorityCh1;
   ul16 PriorityCh2;
   u8 scanmode;
   ul16 chindex[100];
} scans[16];

#seekto 0xc3e4;
struct  {
    ul16 vfoscannum;
    ul16 vfoscanindex[3];
} vfoscandata;

#seekto 0xc3ec;
struct {
   u8 scantxch:4,
      scancondition:4;
   u8 hangtime:4,
      talkback:1,
      startcondition:1,
      rev_1:2;
   u8 scanmode;
   ul32 vhffreq_start;
   ul32 vhffreq_end;
   ul32 uhffreq_start;
   ul32 uhffreq_end;
   u8 rev;
} vfoscans[3];

#seekto 0xc444;
struct  {
    ul16 alarmnum;
    ul16 alarmindex[8];
} alarmdata;

#seekto 0xc456;
struct {
    char name[14];
    u8 alarmtype:4,
       alarmmode:4;
    ul16 jumpch;
    u8 localalarm:1,
       txbackground:1,
       ctcmode:2,
       rev_1:4;
    u8 alarmtime:4,
       alarmcycle:4;
    u8 mictime:4,
       txinterval:4;
    u8 alarmid[8];
    u8 alarmstatus;
    u8 rev_3[1];
    } alarms[8];

#seekto 0xc848;
struct  {
    ul16 dtmfnum;
    ul16 dtmfindex[4];
} dtmfdata;

#seekto 0xc852;
struct {
    u8 autoresettime:4,
       codedelaytime:4;
    u8 stunmode:2,
       showani:1,
       sidetone:1,
       pttidtype:2,
       rev_1:2;
    char callid[10];
    char stunid[10];
    char revive[10];
    char bot[16];
    char eot[16];
    char rev_2[8];
} dtmfcomm;

#seekto 0xc89a;
struct {
     char name[14];
     u8 codelen:4,
        signaling:4;
     u8 groupcode:4,
        intermediatecode:4;
     char fastcall1[16];
     char fastcall2[16];
     char fastcall3[16];
     char fastcall4[16];
     char fastcall5[16];
     char fastcall6[16];
     char fastcall7[16];
     char fastcall8[16];
     char fastcall9[16];
     char fastcall10[16];
     u8 rev_1:6,
        EncodingEnable:1,
        DecodingEnable:1;
     u8 dtmfstatus;
     u8 rev_2[12];
} dtmfs[4];
"""


class HandshakeStatuses(Enum):
    Normal = 0
    Wrong = 1
    PwdWrong = 3
    RadioWrong = 4


class MemoryRegions(Enum):
    """
    Defines the logical memory regions for this radio model.
    """
    radioHead = 2
    radioInfo = 3
    radioVer = 4
    settingData = 6
    zoneData = 7
    channelData = 8
    scanData = 11
    vfoScanData = 12
    alarmData = 13
    dTMFData = 15


MEMORY_REGIONS_RANGES = {
    MemoryRegions.radioHead: (0, 14),   # (Start addr, len)
    MemoryRegions.radioInfo: (14, 68),
    MemoryRegions.radioVer: (82, 10),
    MemoryRegions.settingData: (92, 100),
    MemoryRegions.zoneData: (192, 3202),
    MemoryRegions.channelData: (3394, 43136),
    MemoryRegions.scanData: (46530, 3618),
    MemoryRegions.vfoScanData: (50148, 68),
    MemoryRegions.alarmData: (50244, 258),
    MemoryRegions.dTMFData: (51272, 842)}

DTMFCHARSET = "0123456789ABCDabcd#*"
NAMECHARSET = chirp_common.CHARSET_ALPHANUMERIC + "-/;,._!? *#@$%&+=/<>~(){}]'"
SPECIAL_MEMORIES = {"VFOA": -2, "VFOB": -1}
BANDWIDEH_LIST = ["NFM", "FM"]
POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=5),
    chirp_common.PowerLevel("High", watts=50)]
TIMEOUTTIMER_LIST = [{"name": "%ss" % (x * 5), "id": x}
                     for x in range(1, 64, 1)]
TOTPERMISSIONS_LIST = ["Always", "CTCSS/DCS Match",
                       "Channel Free", "Receive Only"]
SQUELCHLEVEL_LIST = ["AlwaysOpen", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
AUTOSCAN_LIST = ["OFF", "Auto Scan System"]
OFFLINE_REVERSAL_LIST = ["OFF", "Freq Reversal", "Talk Around"]
SIDE_KEY_LIST = [
    {"name": "OFF", "id": 0},
    {"name": "TX Power", "id": 1},
    {"name": "Scan", "id": 2},
    {"name": "FM Radio", "id": 3},
    {"name": "Talkaround/Reversal", "id": 5},
    {"name": "Monitor", "id": 15},
    {"name": "Zone Plus", "id": 20},
    {"name": "Zone Minus", "id": 21},
    {"name": "Squelch", "id": 28},
    {"name": "Emergency Start", "id": 29},
    {"name": "Emergency Stop", "id": 30},
    {"name": "Optional DTMF Code", "id": 32},
    {"name": "Prog PTT", "id": 31}]
FREQ_STEP_List = [
    {"name": "2.5kHz", "id": 2500},
    {"name": "5kHz", "id": 5000},
    {"name": "6.25kHz", "id": 6250},
    {"name": "8.33kHz", "id": 8330},
    {"name": "10kHz", "id": 10000},
    {"name": "12.5kHz", "id": 12500},
    {"name": "25kHz", "id": 25000}]


def do_download(self):
    error_map = {
        HandshakeStatuses.RadioWrong: "Radio model mismatch",
        HandshakeStatuses.PwdWrong: "Radio is password protected"}
    try:
        handshake_result = handshake(self, self.pipe)
        if handshake_result == HandshakeStatuses.Normal:
            all_bytes = read_items(self, self.pipe)
            return memmap.MemoryMapBytes(bytes(all_bytes))
        raise errors.RadioError(error_map.get(
            handshake_result, "Unknown error communicating with radio"))
    except errors.RadioError:
        raise
    except Exception as e:
        LOG.error(f"download error: {e}")
        raise errors.RadioError("Unknown error communicating with radio")
    finally:
        exit_programming_mode(self)


def do_upload(self):
    error_map = {
        HandshakeStatuses.RadioWrong: "Radio model mismatch",
        HandshakeStatuses.PwdWrong: "Radio is password protected"}
    try:
        handshake_result = handshake(self, self.pipe)
        if handshake_result == HandshakeStatuses.Normal:
            write_items(self, self.pipe)
        else:
            raise errors.RadioError(error_map.get(
                handshake_result, "Unknown error communicating with radio"))
    except errors.RadioError:
        raise
    except Exception as e:
        LOG.error(f"upload error: {e}")
        raise errors.RadioError("Unknown error communicating with radio")
    finally:
        exit_programming_mode(self)


def handshake(self, serial):
    databytes = b""
    max_retries = 15
    retry_delay = 0.05
    for num in range(max_retries):
        flag, databytes = exchange_block_with_radio(
            get_handshake_bytes(self.MODEL + " "),
            serial, self.read_packet_len)
        time.sleep(retry_delay)
        if flag:
            break
    return validate_connection_handshake(self, databytes)


def read_items(self, serial):
    all_bytes = bytearray(self._memsize)
    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.cur = 0
    status.max = self._memsize
    for item in MemoryRegions:
        try:
            item_bytes = get_read_current_packet_bytes(
                self, item.value, serial, status)
            if item == MemoryRegions.radioVer and item_bytes:
                fmver_validate(item_bytes[2:6])
            if item_bytes:
                write_memory_region(all_bytes, item_bytes, item)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.error(
                f"read item_data error: {item.name} error_msg: {e}")
            continue
    return all_bytes


def write_items(self, serial):
    status = chirp_common.Status()
    status.max = self._memsize
    status.msg = "Uploading to radio"
    status.cur = 0
    data_bytes = self.get_mmap()
    item_bytes = get_read_current_packet_bytes(
                self, MemoryRegions.radioVer.value, serial, status)
    if item_bytes:
        fmver_validate(item_bytes[2:6])
    EXCLUDED_REGIONS = {MemoryRegions.radioHead,
                        MemoryRegions.radioInfo,
                        MemoryRegions.radioVer,
                        MemoryRegions.zoneData,
                        MemoryRegions.scanData,
                        MemoryRegions.alarmData}
    for item in MemoryRegions:
        if item in EXCLUDED_REGIONS:
            continue
        item_bytes = get_write_item_bytes(data_bytes, item)
        write_item_current_page_bytes(
            self, serial, item_bytes, item.value, status)


def validate_connection_handshake(self, dataByte: bytes):
    success_status = b"\x00\x01"
    pwd_faild_flag = 1
    if dataByte[14:16] != success_status:
        return HandshakeStatuses.Wrong
    if dataByte[20] == pwd_faild_flag:
        return HandshakeStatuses.PwdWrong
    radioType = dataByte[20: 20 + len(self.MODEL)]
    model_bytes = self.MODEL.encode("ascii")
    if radioType == model_bytes:
        return HandshakeStatuses.Normal
    else:
        return HandshakeStatuses.RadioWrong


def exchange_block_with_radio(
    send_byte: bytes, serial_conn, chunk_size=1050
) -> tuple[bool, bytes]:
    serial_conn.write(send_byte)
    new_bytes = serial_conn.read(chunk_size)
    if validate_packet(new_bytes):
        return True, new_bytes
    return False, new_bytes


def validate_packet(current_packet_Byte: bytes, chunk_size=1024):
    byteLen = len(current_packet_Byte)
    if byteLen <= 13:
        LOG.debug(f"Packet too short: {byteLen} bytes")
        return False
    """
    I noticed Retevis has another model
    that sends 250 bytes per packet,
    and the total packet count calculation is different.
    So I added this piece of code to handle
    that case and make it reusable later.
    """
    packet_count = 256 if chunk_size > 255 else chunk_size+1
    """
     I noticed that bytes [12:13] always equal len(current_page_byte) - 17.
     By adding this length check, we can filter out garbage data
     before it even gets to the CRC calculation - should give us a nice
     performance boost!
    """
    data_len = (current_packet_Byte[12] - 6
                if current_packet_Byte[12] > 6 else 0)
    data_len += current_packet_Byte[13] * packet_count
    if byteLen - 17 < data_len:
        LOG.debug(f"Packet too short: {byteLen} bytes")
        return False
    crcBytes = current_packet_Byte[-3:-1]
    crcStr = calculate_crc16(current_packet_Byte[:-3])
    return crcBytes == crcStr


def get_handshake_bytes(currentModel):
    handshake_flag = 0
    send_packet_index = 0
    send_packet_count = 1
    data_code = 0   # 0-write
    return get_send_packet_bytes(
        handshake_flag, send_packet_index, data_code, send_packet_count,
        currentModel.encode("ascii").ljust(41, b'\x00'))


def get_read_current_packet_bytes(self, item: int, serial, status):
    packet_count = 1
    packet_index = 0
    item_bytes = b""
    send_packet_index = 0
    send_packet_count = 1
    data_code = 2   # 0-write 2-read
    while packet_index < packet_count:
        flag, new_data_bytes = exchange_block_with_radio(
                get_send_packet_bytes(item, send_packet_index,
                                      data_code, send_packet_count,
                                      struct.pack("<H", packet_index)),
                serial, self.read_packet_len)
        if (not flag
           or (len(new_data_bytes) > 14 and new_data_bytes[14] != item)):
            raise errors.RadioError("radio reported failure")
        if packet_index == 0:
            packet_count, = struct.unpack("<H", new_data_bytes[18:20])
        status.cur += len(new_data_bytes)
        self.status_fn(status)
        item_bytes += new_data_bytes[20:-3]
        packet_index += 1
    return item_bytes


def write_item_current_page_bytes(self, serial, item_Bytes: bytes,
                                  item: int, status):
    if not item_Bytes:
        raise ValueError("item_bytes cannot be empty")
    packet_len = self.write_page_len
    packet_count = math.ceil(len(item_Bytes) / packet_len)
    data_code = 0   # 0-write 2-read
    if packet_count == 0:
        return True
    for i in range(0, packet_count):
        current_packet_bytes = get_send_packet_bytes(
                item, i, data_code, packet_count,
                item_Bytes[i * packet_len: (i + 1) * packet_len])
        flag, new_data_bytes = exchange_block_with_radio(
            current_packet_bytes,
            serial, self.read_packet_len)
        if (not flag
           or (len(new_data_bytes) > 14 and new_data_bytes[14] != item)):
            raise errors.RadioError("radio reported failure")
        status.cur += len(current_packet_bytes)
        self.status_fn(status)


def get_write_item_bytes(all_bytes: bytearray, item):
    """
       Get the bytes for a specific memory region
       - Uses MEMORY_REGIONS_RANGES to find start and length
    """
    if item not in MEMORY_REGIONS_RANGES:
        LOG.debug(f"Unknown memory Range:{item}")
        return b""
    start, length = MEMORY_REGIONS_RANGES[item]
    return all_bytes[start:start+length]


def write_memory_region(all_bytes: bytearray,
                        item_bytes: bytes, item):
    """
    Put the given region bytes into the main memory array
    - Uses MEMORY_REGIONS_RANGES to find start and length
    """
    if item not in MEMORY_REGIONS_RANGES:
        LOG.debug(f"Unknown memory Range:{item}")
        return
    start, length = MEMORY_REGIONS_RANGES[item]
    item_len = min(len(item_bytes), length)
    all_bytes[start:start + item_len] = item_bytes[:item_len]


def exit_programming_mode(self):
    serial = self.pipe
    """
    exiting read/write mode and reboot radio
    """
    reboot_sign = 111
    packet_index = 0
    data_code = 0   # 0-write 2-read
    packet_count = 1
    data_buffer = b'\x00'
    try:
        serial.write(get_send_packet_bytes(reboot_sign,
                                           packet_index, data_code,
                                           packet_count, data_buffer))
    except Exception as e:
        LOG.debug(
            f"Radio refused to exit programming mode:{e}")
        raise errors.RadioError(
            "Radio refused to exit programming mode")


def get_send_packet_bytes(data_type: int, packet_index: int,
                          data_code: int, packet_count: int,
                          data_buffer: bytes):
    data_len = len(data_buffer)
    data_part = struct.pack(f'<12sHBBHH{data_len}s',
                            b"RDTP\x01\x00\x00\x00\x00\x00\x00\x00",
                            data_len + 6,
                            data_type & 0xFF,
                            data_code & 0xFF,  # 0-write 2-read
                            packet_index & 0xFFFF,
                            packet_count & 0xFFFF,
                            data_buffer)
    return data_part + calculate_crc16(data_part) + b"\xff"


def format_version(ver):
    return 'v%02i.%02i.%02i.%03i' % ver


def fmver_validate(raw_bytes):
    current_ver = struct.unpack("BBBB", raw_bytes)
    if REQUIRED_VER > current_ver:
        raise errors.RadioError(
            ("Firmware is %s; You must update to %s or higher "
             "to be compatible with CHIRP") % (format_version(current_ver),
                                               format_version(REQUIRED_VER)))


def calculate_crc16(data):
    return struct.pack('<H', crc.crc16_ibm_rev(data))


def _get_memory(self, mem, _mem, ch_index):
    mem.extra = RadioSettingGroup("Extra", "extra")
    mem.extra.append(
        RadioSetting(
            "tottime",
            "TOT",
            RadioSettingValueList(
                get_namedict_by_items(TIMEOUTTIMER_LIST),
                current_index=(_mem.tottime - 1))))
    mem.extra.append(
        RadioSetting(
            "totpermissions",
            "TX Permissions",
            RadioSettingValueList(TOTPERMISSIONS_LIST,
                                  current_index=_mem.totpermissions)))
    mem.extra.append(
        RadioSetting(
            "rxsqlmode",
            "Squelch Level",
            RadioSettingValueList(SQUELCHLEVEL_LIST,
                                  current_index=_mem.rxsqlmode)))
    mem.extra.append(
        RadioSetting(
            "autoscan",
            "Auto Scan System",
            RadioSettingValueList(AUTOSCAN_LIST,
                                  current_index=_mem.autoscan)))
    mem.extra.append(
        RadioSetting(
            "alarmlist",
            "Alarm System",
            RadioSettingValueList(
                get_namedict_by_items(self._alarm_list),
                current_index=get_item_by_id(self._alarm_list,
                                             _mem.alarmlist))))
    mem.extra.append(
        RadioSetting(
            "dtmfsignalinglist",
            "DTMF System",
            RadioSettingValueList(
                get_namedict_by_items(self._dtmf_list),
                current_index=get_item_by_id(self._dtmf_list,
                                             _mem.dtmfsignalinglist))))
    mem.extra.append(
        RadioSetting(
            "offlineorreversal",
            "Talkaround & Reversal",
            RadioSettingValueList(OFFLINE_REVERSAL_LIST,
                                  current_index=_mem.offlineorreversal)))
    mem.extra.append(
        RadioSetting(
            "vox", "VOX",
            RadioSettingValueBoolean(_mem.vox)))
    mem.extra.append(
        RadioSetting(
            "companding", "Compander",
            RadioSettingValueBoolean(_mem.companding)))
    mem.extra.append(
        RadioSetting("scramble", "Scramble",
                     RadioSettingValueBoolean(_mem.scramble)))
    ch_index_dict = get_ch_index(self)
    if ch_index not in ch_index_dict:
        mem.freq = 0
        mem.empty = True
        return mem
    mem.freq = _mem.rxfreq
    mem.name = self.filter_name(str(_mem.alias).rstrip())
    tx_freq = _mem.txfreq
    if mem.freq == 0:
        mem.empty = True
        return mem
    if mem.freq == 0xFFFFFFFF:
        mem.freq = 0
        mem.empty = True
        return mem
    if mem.freq == tx_freq:
        mem.duplex = ""
        mem.offset = 0
    elif tx_freq == 0xFFFFFFFF:
        mem.duplex = ""
        mem.offset = 0
    else:
        mem.duplex = mem.freq > tx_freq and "-" or "+"
        mem.offset = abs(mem.freq - tx_freq)
    mem.mode = BANDWIDEH_LIST[(1 if _mem.bandwidth >= 3 else 0)]
    rxtone = txtone = None
    if _mem.rxctcvaluetype == 1:
        tone_value = _mem.rxctc / 10.0
        if tone_value in chirp_common.TONES:
            rxtone = tone_value
    elif _mem.rxctcvaluetype in [2, 3]:
        rxtone = int("%03o" % _mem.rxctc)
    if _mem.txctcvaluetype == 1:
        tone_value = _mem.txctc / 10.0
        if tone_value in chirp_common.TONES:
            txtone = tone_value
    elif _mem.txctcvaluetype in [2, 3]:
        txtone = int("%03o" % _mem.txctc)
    rx_tone = (("" if _mem.rxctcvaluetype == 0
                else "Tone" if _mem.rxctcvaluetype == 1 else "DTCS"),
               rxtone, (_mem.rxctcvaluetype == 0x3) and "R" or "N")
    tx_tone = (("" if _mem.txctcvaluetype == 0
                else "Tone" if _mem.txctcvaluetype == 1 else "DTCS"),
               txtone, (_mem.txctcvaluetype == 0x3) and "R" or "N")
    chirp_common.split_tone_decode(mem, tx_tone, rx_tone)
    mem.power = POWER_LEVELS[(1 if _mem.power == 2 else 0)]
    if ch_index < 2:
        mem.immutable += ["name"]
    return mem


def get_model_info(self, model_info):
    rs_value = RadioSettingValueString(0, 20, self.current_model)
    rs_value.set_mutable(False)
    rs = RadioSetting("modelinfo.Machinecode", "Machine Code", rs_value)
    model_info.append(rs)
    rs_value = RadioSettingValueString(
        0, 100,
        "136.00000-174.00000, 400.00000-480.00000")
    rs_value.set_mutable(False)
    rs = RadioSetting("modelinfo.freqrange", "Frequency Range[MHz]", rs_value)
    model_info.append(rs)


def get_common_setting(self, common):
    _settings = self._memobj.settings
    opts = ["Low", "Normal", "Strengthen"]
    common.append(RadioSetting(
        "settings.micmain", "Mic Main",
        RadioSettingValueList(opts, current_index=_settings.micmain)))
    opts = ["Stun WakeUp", "Stun TX", "Stun TX/RX"]
    common.append(
        RadioSetting("settings.stunmode", "Stun Type",
                     RadioSettingValueList(opts,
                                           current_index=_settings.stunmode)))
    opts_dict = [{"name": "%s" % (x + 1), "id": x} for x in range(0, 10, 1)]
    common.append(get_radiosetting_by_key(self, _settings,
                                          "calltone", "Call Tone",
                                          _settings.calltone, opts_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "freqstep", "Frequency Step",
            _settings.freqstep, FREQ_STEP_List))
    opts = ["OFF", "1:1", "1:2", "1:4"]
    common.append(
        RadioSetting(
            "settings.powersavingmode", "Battery Mode",
            RadioSettingValueList(
                opts, current_index=_settings.powersavingmode)))
    opts_dict = [
        {"name": "%ss" % ((x + 1) * 5), "id": x} for x in range(0, 16, 1)]
    common.append(
        get_radiosetting_by_key(
            self, _settings, "powersavingdelaytime", "Battery Delay Time",
            _settings.powersavingdelaytime, opts_dict))
    opts_dict = [{"name": "%s" % x, "id": x} for x in range(1, 16, 1)]
    common.append(
        get_radiosetting_by_key(
            self, _settings, "backlightbrightness", "Backlight Brightness",
            _settings.backlightbrightness, opts_dict))

    opts = [
        "Always", "5s", "10s", "15s", "20s", "25s", "30s",
        "1min", "2min", "3min", "4min", "5min", "15min", "30min",
        "45min", "1h"]
    common.append(
        RadioSetting("settings.backlighttime", "Backlight Time",
                     RadioSettingValueList(
                         opts, current_index=_settings.backlighttime)))
    opts_dict = [{"name": "%s" % x, "id": x} for x in range(1, 16, 1)]
    common.append(
        get_radiosetting_by_key(
            self, _settings, "voxthreshold", "VOX Level",
            _settings.voxthreshold, opts_dict))
    opts_dict = [
        {"name": "%sms" % ((x) * 500), "id": x} for x in range(1, 5, 1)]
    common.append(
        get_radiosetting_by_key(
            self, _settings, "voxdelaytime", "VOX Delay Time",
            _settings.voxdelaytime, opts_dict))
    opts_dict = [{"name": "OFF", "id": 0}] + [
        {"name": "%ss" % x, "id": x} for x in range(5, 256, 5)]

    common.append(
        get_radiosetting_by_key(
            self, _settings, "menuouttime", "Menu Timeout Setting",
            _settings.menuouttime, opts_dict))
    opts = ["Manual", "Auto"]
    common.append(
        RadioSetting(
            "settings.autoormanuallock", "Key Lock Mode",
            RadioSettingValueList(opts,
                                  current_index=_settings.autoormanuallock)))
    opts = ["Frequency", "Name", "Channel"]
    common.append(
        RadioSetting(
            "settings.chdisplay", "Display Mode",
            RadioSettingValueList(opts, current_index=_settings.chdisplay)))
    opts = ["Band A", "Band B", "Band A & Band B", "Band B & Band A"]
    rs = RadioSetting(
        "settings.homeselect",
        "Band Selection",
        RadioSettingValueList(
            opts,
            current_index=get_band_selection(
                _settings.homeselect, _settings.homeindex)))
    rs.set_apply_callback(
        set_band_selection, _settings, opts, "homeselect", "homeindex")
    common.append(rs)
    opts = ["Channel", "VFO Frequency"]
    common.append(
        RadioSetting(
            "settings.homechtype_1",
            "Channel Type A",
            RadioSettingValueList(opts, current_index=_settings.homechtype_1)))
    common.append(
        RadioSetting(
            "settings.homechtype_2",
            "Channel Type B",
            RadioSettingValueList(opts, current_index=_settings.homechtype_2)))
    opts = ["Last Active Channel", "Designated Channel"]
    common.append(
        RadioSetting(
            "settings.poweron_type_1",
            "Power On A",
            RadioSettingValueList(opts,
                                  current_index=_settings.poweron_type_1)))
    common.append(
        RadioSetting(
            "settings.poweron_type_2",
            "Power On B",
            RadioSettingValueList(opts,
                                  current_index=_settings.poweron_type_2)))
    opts_dict = self.get_scan_item_list()
    common.append(
        get_radiosetting_by_key(
            self, _settings, "scanlist", "Enable Scan List",
            _settings.scanlist, opts_dict))
    short_dict = SIDE_KEY_LIST[:12]
    common.append(
        get_radiosetting_by_key(
            self, _settings, "tk1_short", "Top Key Short Press",
            _settings.tk1_short, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "tk1_long", "Top Key Long Press",
            _settings.tk1_long, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk1_short", "Short Press Side Key 1",
            _settings.sk1_short, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk1_long", "Long Press Side Key 1",
            _settings.sk1_long, SIDE_KEY_LIST))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk2_short", "Short Press Side Key 2",
            _settings.sk2_short, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk2_long", "Long Press Side Key 2",
            _settings.sk2_long, SIDE_KEY_LIST))
    opts = ["55Hz", "120°", "180°", "240°"]
    common.append(
        RadioSetting(
            "settings.tailsoundeliminationsfre", "CTC Tail Elimination",
            RadioSettingValueList(
                opts, current_index=_settings.tailsoundeliminationsfre)))
    if _settings.salezone != 2:
        opts = ["NOAA-%s" % x for x in range(1, 13, 1)]
        common.append(
            RadioSetting(
                "settings.wxch", "NOAA Channel",
                RadioSettingValueList(opts, current_index=_settings.wxch)))
    opts = ["1000Hz", "1450Hz", "1750Hz", "2100Hz"]
    common.append(
        RadioSetting(
            "settings.singletone", "Single Tone",
            RadioSettingValueList(opts, current_index=_settings.singletone)))
    common.append(
        RadioSetting(
            "settings.tailsoundeliminationswitch",
            "Tail Elimination Switch",
            RadioSettingValueBoolean(_settings.tailsoundeliminationswitch)))
    common.append(
        RadioSetting(
            "settings.rogerbeep", "Roger Beep",
            RadioSettingValueBoolean(_settings.rogerbeep)))
    common.append(
        RadioSetting(
            "settings.touchtone", "Key Beep",
            RadioSettingValueBoolean(_settings.touchtone)))
    common.append(
        RadioSetting(
            "settings.txpermittone", "TX Permit Tone",
            RadioSettingValueBoolean(_settings.txpermittone)))
    common.append(
        RadioSetting(
            "settings.voiceprompts", "Voice Broadcast",
            RadioSettingValueBoolean(_settings.voiceprompts)))
    common.append(
        RadioSetting(
            "settings.chknoblock", "Channel Knob Lock",
            RadioSettingValueBoolean(_settings.chknoblock)))
    common.append(
        RadioSetting(
            "settings.panellock", "Keyboard Lock",
            RadioSettingValueBoolean(_settings.panellock)))

    common.append(
        RadioSetting(
            "settings.sidekeylock", "Side Key Lock",
            RadioSettingValueBoolean(_settings.sidekeylock)))


def get_dtmf_setting(self, dtmf):
    _dtmf_comm = self._memobj.dtmfcomm
    opts = ["OFF"] + ["%ss" % x for x in range(1, 16, 1)]
    dtmf.append(
        RadioSetting(
            "dtmfsetting.autoresettime",
            "Auto Reset Time",
            RadioSettingValueList(opts,
                                  current_index=_dtmf_comm.autoresettime)))
    opts = [{"name": "Stun TX", "id": 1}, {"name": "Stun TX/RX", "id": 2}]
    dtmf.append(
        get_radiosetting_by_key(
            self, _dtmf_comm, "stunmode",
            "Stun Type", _dtmf_comm.stunmode, opts))
    opts = ["300ms", "550ms", "800ms", "1050ms"]
    dtmf.append(
        RadioSetting(
            "dtmfsetting.codedelaytime", "Digit Delay",
            RadioSettingValueList(opts,
                                  current_index=_dtmf_comm.codedelaytime)))
    opts = ["OFF", "BOT", "EOT", "Both"]
    dtmf.append(
        RadioSetting(
            "dtmfsetting.pttidtype", "PTT ID Type",
            RadioSettingValueList(opts,
                                  current_index=_dtmf_comm.pttidtype)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.showani", "Show ANI",
            RadioSettingValueBoolean(_dtmf_comm.showani)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.sidetone", "Side Tone",
            RadioSettingValueBoolean(_dtmf_comm.sidetone)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.callid", "Call ID",
            RadioSettingValueString(
                0, 10,
                "".join(filter(_dtmf_comm.callid, DTMFCHARSET, 10, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.stunid", "Stun ID",
            RadioSettingValueString(
                0, 10,
                "".join(filter(_dtmf_comm.stunid, DTMFCHARSET, 10, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.revive", "Revive ID",
            RadioSettingValueString(
                0, 10,
                "".join(filter(_dtmf_comm.revive, DTMFCHARSET, 10, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.bot", "BOT",
            RadioSettingValueString(
                0, 16,
                "".join(filter(_dtmf_comm.bot, DTMFCHARSET, 16, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.eot", "EOT",
            RadioSettingValueString(
                0, 16,
                "".join(filter(_dtmf_comm.eot, DTMFCHARSET, 16, True)),
                False, DTMFCHARSET)))


def get_vfo_scan(self, vfoscan):
    _vfo_scan = self._memobj.vfoscans[0]
    opts = ["Carrier", "Time", "Search"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.scanmode", "Scan Mode",
            RadioSettingValueList(opts, current_index=_vfo_scan.scanmode)))
    opts = ["Carrier", "CTC/DCS"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.scancondition", "Scan Condition",
            RadioSettingValueList(opts,
                                  current_index=_vfo_scan.scancondition)))

    opts = ["%s" % (x + 1) for x in range(0, 16, 1)]
    vfoscan.append(
        RadioSetting(
            "vfoscan.hangtime", "Scan Hang Time[s]",
            RadioSettingValueList(opts, current_index=_vfo_scan.hangtime)))
    vfoscan.append(
        RadioSetting(
            "vfoscan.talkback", "Talk Back Enable",
            RadioSettingValueBoolean(_vfo_scan.talkback)))
    opts = ["Current Frequency", "Starting Frequency"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.startcondition", "Start Condition",
            RadioSettingValueList(opts,
                                  current_index=_vfo_scan.startcondition)))

    freq_start = _vfo_scan.vhffreq_start / 1000000
    vfoscan.append(
        RadioSetting(
            "vfoscan.vhffreq_start", "Start Frequency",
            RadioSettingValueFloat(136, 480, freq_start, 0.00001, 5)))

    freq_end = _vfo_scan.vhffreq_end / 1000000
    vfoscan.append(
        RadioSetting(
            "vfoscan.vhffreq_end", "End Frequency",
            RadioSettingValueFloat(136, 480, freq_end, 0.00001, 5)))


def _set_memory(self, mem, _mem, ch_index):
    ch_index_dict = get_ch_index(self)
    rx_freq = get_ch_rxfreq(mem)
    flag = ch_index not in ch_index_dict and rx_freq != 0
    if rx_freq != 0xFFFFFFFF and flag:
        ch_index_dict.append(ch_index)
    elif ch_index in ch_index_dict and rx_freq <= 0:
        ch_index_dict.remove(ch_index)
    set_ch_index(self, ch_index_dict)
    _mem.set_raw(b"\x00" * 40)
    if mem.empty:
        return
    _mem.rxfreq = rx_freq
    _mem.alias = mem.name.ljust(14)
    txfrq = (int(rx_freq - mem.offset)
             if mem.duplex == "-" and mem.offset > 0
             else (int(rx_freq + mem.offset)
                   if mem.duplex == "+" and mem.offset > 0
                   else rx_freq))
    _mem.txfreq = txfrq
    _mem.bandwidth = 3 if mem.mode == "FM" else 1
    if mem.power in POWER_LEVELS:
        _mem.power = 2 if POWER_LEVELS.index(mem.power) == 1 else 0
    else:
        _mem.power = 0
    ((txmode, txtone, txpol),
     (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(
        mem)
    if rxmode == "Tone":
        _mem.rxctcvaluetype = 1
        rxtone_value = int(rxtone * 10)
        _mem.rxctc = rxtone_value
    elif rxmode == "DTCS":
        _mem.rxctcvaluetype = rxpol == "R" and 3 or 2
        oct_value = int(str(rxtone), 8)
        _mem.rxctc = oct_value
    else:
        _mem.rxctcvaluetype = 0
    if txmode == "Tone":
        _mem.txctcvaluetype = 1
        txtone_value = int(txtone * 10)
        _mem.txctc = txtone_value
    elif txmode == "DTCS":
        _mem.txctcvaluetype = txpol == "R" and 3 or 2
        oct_value = int(str(txtone), 8)
        _mem.txctc = oct_value
    else:
        _mem.txctcvaluetype = 0
    for setting in mem.extra:
        if setting.get_name() == "tottime":
            _mem.tottime = get_item_by_name(
                TIMEOUTTIMER_LIST, str(setting.value))
        elif setting.get_name() == "alarmlist":
            _mem.alarmlist = get_item_by_name(
                self._alarm_list, setting.value)
        elif setting.get_name() == "dtmfsignalinglist":
            _mem.dtmfsignalinglist = get_item_by_name(
                self._dtmf_list, setting.value)
        else:
            setattr(_mem, setting.get_name(), setting.value)
    return _mem


def get_radiosetting_by_key(self, _setting, item_key,
                            item_display_name, item_value,
                            opts_dict, callback=None):
    opts = get_namedict_by_items(opts_dict)
    item = RadioSetting(
        item_key, item_display_name,
        RadioSettingValueList(
            opts, current_index=get_item_by_id(opts_dict, item_value)))
    item.set_apply_callback(
        set_item_callback if callback is None else callback,
        _setting, item_key, opts_dict, self)
    return item


def get_namedict_by_items(items):
    return [x["name"] for x in items]


def get_item_by_id(items, value):
    return next((i for i, item in enumerate(items) if item["id"] == value), 0)


def set_item_callback(set_item, obj, name, items, self):
    item_value = get_item_by_name(items, set_item.value)
    setattr(obj, name, item_value)


def get_item_by_name(items, name):
    return next(
        (item["id"] for item in items if item["name"] == name),
        items[0]["id"] if items else 0)


def get_band_selection(band_value, band_index):
    return (
        (3 if band_value >= 3 else 1)
        if band_index >= 1
        else (2 if band_value >= 3 else 0))


def get_ch_index(self):
    if self._ch_cache is None:
        ch_data = self._memobj.channeldata
        self._ch_cache = []
        seen = set()
        for i in range(ch_data.chnum):
            ch_index = int(ch_data.chindex[i])
            if ch_index != 0xFFFF and ch_index not in seen:
                seen.add(ch_index)
                self._ch_cache.append(ch_index)
    return self._ch_cache


def set_ch_index(self, ch_index_list):
    if not isinstance(ch_index_list, list):
        raise TypeError("ch_index must be a list")
    ch_index_list = sorted(int(x) for x in ch_index_list)
    _ch_data = self._memobj.channeldata
    ch_num = len(ch_index_list)
    if len(_ch_data.chindex) < ch_num:
        raise ValueError("Not enough space in chindex array")
    _ch_data.chnum = ch_num
    for i in range(1027):
        _ch_data.chindex[i] = (
            ch_index_list[i] if i < ch_num else 0xFFFF)
    self._ch_cache = ch_index_list.copy()


def get_ch_rxfreq(mem):
    if mem.empty:
        return 0
    ch_freq = (mem.freq // 10) * 10
    if mem.freq == 0:
        return mem.freq
    elif mem.freq < 136000000:
        ch_freq = 136000000
    elif mem.freq > 174000000 and mem.freq < 400000000:
        ch_freq = 174000000
    elif mem.freq > 480000000:
        ch_freq = 480000000
    return ch_freq


def set_band_selection(set_item, obj,
                       opts, home_select_field_name,
                       home_index_field_name):
    value = opts.index(set_item.value)
    value_mapping = {3: (1, 3), 2: (0, 3), 1: (1, 2), 0: (0, 1)}
    home_index, home_select = value_mapping.get(value, (0, 1))
    setattr(obj, home_index_field_name, home_index)
    setattr(obj, home_select_field_name, home_select)


def filter(s, char_set, max_length=10, is_upper=False):
    s_ = ""
    input_len = len(s)
    for i in range(0, min(max_length, input_len)):
        c = str(s[i])
        if is_upper:
            c = c.upper()
        s_ += c if c in char_set else ""
    return s_


@directory.register
class HA1G(chirp_common.CloneModeRadio):
    """Retevis HA1G"""

    VENDOR = "Retevis"
    MODEL = "HA1G"
    BAUD_RATE = 115200
    _memsize = 0xD868
    read_packet_len = 1047
    write_page_len = 1024
    current_model = "HA1G"
    _ch_cache = None
    _dtmf_list = [{"name": "OFF", "id": 15}]
    _alarm_list = [{"name": "OFF", "id": 255}]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_special_chans = sorted(SPECIAL_MEMORIES.keys())
        rf.memory_bounds = (1, 256)  # Channel range
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_dtcs = True
        rf.has_cross = True
        rf.has_bank = False
        rf.valid_bands = [(136000000, 174000010), (400000000, 480000010)]
        rf.has_tuning_step = False
        rf.has_nostep_tuning = True
        rf.valid_name_length = 12
        rf.valid_skips = []
        rf.valid_tuning_steps = []
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "".join(
            c for c in "-/;,._!? *#@$%&+=/<>~(){}]'"
            if c not in chirp_common.CHARSET_UPPER_NUMERIC)
        rf.has_settings = True
        rf.valid_modes = BANDWIDEH_LIST
        rf.valid_power_levels = POWER_LEVELS
        rf.has_comment = True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "->DTCS",
            "DTCS->",
            "DTCS->DTCS"]
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        self._dtmf_list = self.get_dtmf_item_list()
        self._alarm_list = self.get_alarm_item_list()

    def sync_in(self):
        try:
            self._mmap = do_download(self)
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                "Failed to communicate with radio: %s" % e)

    def sync_out(self):
        """Upload to radio"""
        try:
            logging.debug("come in sync_out")
            do_upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            LOG.exception(
                "Unexpected error during upload: %s" % e)
            raise errors.RadioError(
                "Unexpected error communicating with the radio")

    def get_memory(self, number):
        mem = chirp_common.Memory()
        ch_index = 0
        if isinstance(number, str):
            mem.extd_number = number
            ch_index = 0 if number == "VFOA" else 1
            mem.number = len(self._memobj.channels) + ch_index + 1
        elif number > len(self._memobj.channels):
            mem.extd_number = (
                number - len(self._memobj.channels) == 1 and "VFOA" or "VFOB")
            number = mem.extd_number
            ch_index = 0 if number == "VFOA" else 1
        else:
            ch_index = number + 2
            mem.number = number
        _mem = self._memobj.channels[ch_index]
        mem = _get_memory(self, mem, _mem, ch_index)
        if ch_index > 2 and ch_index < 33:
            mem.immutable = ["empty", "freq", "duplex", "offset"]
        if ch_index >= 10 and ch_index < 17:
            mem.immutable += ["mode", "power"]
        return mem

    def set_memory(self, mem):
        ch_index = 0
        if mem.number > len(self._memobj.channels):
            ch_index = 0 if mem.extd_number == "VFOA" else 1
        else:
            ch_index = mem.number + 2
        _mem = self._memobj.channels[ch_index]
        if ch_index < 33 and mem.freq == 0:
            return
        _set_memory(self, mem, _mem, ch_index)

    def get_raw_memory(self, number):
        if isinstance(number, str):
            ch_index = 0 if number == "VFOA" else 1
        else:
            ch_index = number + 2
        _mem = self._memobj.channels[ch_index]
        return repr(_mem)

    def get_settings(self):
        ModelInfo = RadioSettingGroup("info", "Model Information")
        common = RadioSettingGroup("basic", "Common Settings")
        dtmf = RadioSettingGroup("dtmfe", "DTMF Settings")
        vfoscan = RadioSettingGroup("vfoscan", "VFO  Scan")
        setmode = RadioSettings(ModelInfo, common, dtmf, vfoscan)
        try:
            get_model_info(self, ModelInfo)
            get_common_setting(self, common)
            get_dtmf_setting(self, dtmf)
            get_vfo_scan(self, vfoscan)
        except Exception as e:
            LOG.exception("Error getting settings: %s", e)
        return setmode

    def set_settings(self, uisettings):
        for element in uisettings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    element.run_apply_callback()
                else:
                    name = element.get_name()
                    value = element.value
                    if name.startswith("settings."):
                        name = name[9:]
                        _settings = self._memobj.settings
                        setattr(_settings, name, value)
                    elif name.startswith("dtmfsetting."):
                        name = name[12:]
                        _dtmfcomm = self._memobj.dtmfcomm
                        if (name in ["callid", "stunid", "revive"]):
                            value = filter(value, DTMFCHARSET, 10, True)
                            value = value.ljust(10, "\x00")
                        elif name in ["bot", "eot"]:
                            value = filter(value, DTMFCHARSET, 16, True)
                            value = value.ljust(16, "\x00")
                        setattr(_dtmfcomm, name, value)
                    elif name.startswith("vfoscan."):
                        name = name[8:]
                        _vfo_scan = self._memobj.vfoscans[0]
                        if name in ["vhffreq_start", "vhffreq_end"]:
                            value = int(value * 1000000)
                        setattr(_vfo_scan, name, value)
                    LOG.debug("Setting %s: %s", name, value)
            except Exception:
                LOG.exception(element.get_name())
                raise

    def get_alarm_item_list(self):
        _alarmdata = self._memobj.alarmdata
        _alarms = self._memobj.alarms
        alarm_list = [{"name": "OFF", "id": 255}]
        max_count = 8
        alarm_num = min(_alarmdata.alarmnum, max_count)
        if alarm_num > 0:
            for i in range(alarm_num):
                alarm_index = min(_alarmdata.alarmindex[i], max_count - 1)
                alarm_item = _alarms[alarm_index]
                alarm_item.alarmstatus = 1
                alarmname = "".join(filter(alarm_item.name, NAMECHARSET, 12))
                alarm_list.append({"name": alarmname, "id": alarm_index})
        return alarm_list

    def get_dtmf_item_list(self):
        _dtmfdata = self._memobj.dtmfdata
        _dtmfs = self._memobj.dtmfs
        dtmf_list = [{"name": "OFF", "id": 15}]
        max_count = 4
        dtmf_num = min(_dtmfdata.dtmfnum, max_count)
        if dtmf_num > 0:
            for i in range(dtmf_num):
                dtmf_index = min(_dtmfdata.dtmfindex[i], max_count - 1)
                dtmf_item = _dtmfs[dtmf_index]
                dtmf_item.dtmfstatus = 1
                dtmfname = "".join(filter(dtmf_item.name, NAMECHARSET, 12))
                dtmf_list.append({"name": dtmfname, "id": dtmf_index})
        return dtmf_list

    def get_scan_item_list(self):
        _scandata = self._memobj.scandata
        _scans = self._memobj.scans
        scan_dict = []
        max_count = 16
        scan_num = min(_scandata.scannum, max_count)
        if scan_num > 0:
            for i in range(0, scan_num):
                scan_index = min(_scandata.scanindex[i], max_count)
                scan_item = _scans[scan_index]
                scanname = "".join(filter(scan_item.name, NAMECHARSET, 12))
                scan_dict.append({"name": scanname, "id": scan_index})
        return scan_dict


@directory.register
class HA1UV(HA1G):
    """Retevis HA1UV"""

    MODEL = "HA1UV"
    current_model = "HA1UV"

    def get_features(self):
        rf = super().get_features()
        rf.memory_bounds = (1, 1024)  # Channel range
        return rf

    def validate_memory(self, mem):
        return super().validate_memory(mem)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        ch_index = 0
        if isinstance(number, str):
            mem.extd_number = number
            ch_index = 0 if number == "VFOA" else 1
            mem.number = len(self._memobj.channels) + ch_index + 1
        elif number > len(self._memobj.channels):
            mem.extd_number = (
                number - len(self._memobj.channels) == 1 and "VFOA" or "VFOB")
            number = mem.extd_number
            ch_index = 0 if number == "VFOA" else 1
        else:
            ch_index = number + 2
            mem.number = number
        _mem = self._memobj.channels[ch_index]
        return _get_memory(self, mem, _mem, ch_index)

    def set_memory(self, mem):
        ch_index = 0
        if mem.number > len(self._memobj.channels):
            ch_index = 0 if mem.extd_number == "VFOA" else 1
        else:
            ch_index = mem.number + 2
        _mem = self._memobj.channels[ch_index]
        if ch_index < 2 and mem.freq == 0:
            return
        _set_memory(self, mem, _mem, ch_index)
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
