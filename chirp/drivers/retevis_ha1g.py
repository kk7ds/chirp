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
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettingSubGroup,
    RadioSettingValueList,
    RadioSettingValueString,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueFloat)


LOG = logging.getLogger(__name__)

MEM_FORMAT = """

#seekto 0x0E;
struct{
    u8 modelnumber[32];
    u8 hardwareversion[2];
    u8 serialn0[16];
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
  u8 wcscan:1,
     agc:1,
     rtcreport:1,
     displaybatterylevel:1,
     batterlevelreport:1,
     lowbattery:1,
     stunmode:2;
  u8 voiceprompts:1,
     touchtone:1,
     txenstone:1,
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
  ul16 frestep;
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
     TailElimination:2,
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
  u8 totPermissions:2,
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
  ul16 dtmfcllid;
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
NAMECHATSET = chirp_common.CHARSET_ALPHANUMERIC + "-/;,._!? *#@$%&+=/<>~(){}]'"
SPECIAL_MEMORIES = {"VFOA": -2, "VFOB": -1}
BANDWIDEH_LIST = ["NFM", "FM"]
POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=0),
    chirp_common.PowerLevel("High", watts=2)]
TIMEOUTTIMER_LIST = [{"name": "%ss" % (x * 5), "id": x}
                     for x in range(1, 64, 1)]
TOTPERSMISSION_LIST = ["Always", "CTCSS/DCS Match",
                       "Channel Free", "Receive Only"]
SQUELCHLEVEL_LIST = ["AlwaysOpen", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
AUTOSCAN_LIST = ["OFF", "Auto Scan System"]
OFFLINE_REVERSAL_LIST = ["OFF", "Freq Reversql", "Talk Around"]
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

Fre_Step_List = [
    {"name": "2.5KHZ", "id": 2500},
    {"name": "5KHZ", "id": 5000},
    {"name": "6.25KHZ", "id": 6250},
    {"name": "8.33KHz", "id": 8330},
    {"name": "10KHZ", "id": 10000},
    {"name": "12.5KHZ", "id": 12500},
    {"name": "25KHZ", "id": 25000}]

ALARM_LIST = [{"name": "OFF", "id": 255}]
DTMFSYSTEM_LIST = [{"name": "OFF", "id": 15}]


class HA1GBank(chirp_common.NamedBank):
    """A HA1G bank"""

    def get_name(self):
        _zone_data = get_zone_index_list(self._model._radio)
        _zone_list = self._model._radio._memobj.zones
        if self.index in _zone_data:
            zone_name = "".join(filter(_zone_list[self.index].name,
                                       NAMECHATSET, 12))
            return zone_name
        else:
            return ""

    def set_name(self, name):
        _zone_data = get_zone_index_list(self._model._radio)
        _zone_list = self._model._radio._memobj.zones
        if self.index in _zone_data:
            _zone = _zone_list[self.index]
            _zone["name"] = (filter(name,
                                    NAMECHATSET, 12, True).ljust(14, "\x00"))


class HA1GBankModel(chirp_common.BankModel):
    """A HA1G bank model"""

    def __init__(self, radio, name="Banks"):
        super(HA1GBankModel, self).__init__(radio, name)
        _banks = get_zone_index_list(self._radio)
        self._bank_mappings = []
        for index, _bank in enumerate(_banks):
            bank = HA1GBank(self, "%i" % index, "BANK-%i" % index)
            bank.index = index
            self._bank_mappings.append(bank)

    def get_num_mappings(self):
        return len(self._bank_mappings)

    def get_mappings(self):
        return self._bank_mappings

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._channel_numbers_in_bank(bank)
        if memory.freq == 0:
            raise errors.RadioError(
                "Cannot select a channel with empty frequency")
        else:
            ch_num = memory.number
            if len(channels_in_bank) < 16:
                if ch_num not in channels_in_bank:
                    channels_in_bank.add(ch_num)
                    zone_ch_list = [x + 2 for x in channels_in_bank]
                    # Adjusting channel numbers
                    # to match the radio's format
                    set_zone_ch_list(self._radio, bank.index,
                                     sorted(zone_ch_list))
            else:
                raise Exception("Bank is full, cannot add more channels")

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._channel_numbers_in_bank(bank)
        ch_num = memory.number
        if ch_num in channels_in_bank:
            channels_in_bank.remove(ch_num)
            zone_ch_list = [x + 2 for x in channels_in_bank]
            set_zone_ch_list(self._radio, bank.index, sorted(zone_ch_list))
        else:
            raise Exception("Memory not found in bank, cannot remove")

    def _channel_numbers_in_bank(self, bank):
        _zone_data = get_zone_index_list(self._radio)
        _zone_list = self._radio._memobj.zones
        if bank.index in _zone_data:
            _zone = _zone_list[bank.index]
            _members = [x for x in _zone.chindex]
            return set([int(ch) - 2 for ch in _members if ch != 0xFFFF])

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._channel_numbers_in_bank(bank):
                banks.append(bank)
        return banks


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
    for num in range(15):
        flag, databytes = exchange_block_with_radio(
            get_handshake_bytes(self.MODEL + " "),
            serial, self.read_packet_len)
        time.sleep(0.05)
        if flag:
            break
    return handshake_handle_connect_event(self, databytes)


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
            if item_bytes:
                read_item_handle_connect_event(
                    all_bytes, item_bytes, item)
        except Exception as e:
            LOG.error(
                f"read item_data error: {item.name} error_msg: {e}")
            continue
    return all_bytes


def write_items(self, serial):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"
    status.cur = 0
    status.max = self._memsize
    data_bytes = self.get_mmap()
    for item in MemoryRegions:
        if (item in [MemoryRegions.radioHead, MemoryRegions.radioInfo,
                     MemoryRegions.radioVer, MemoryRegions.zoneData]):
            continue
        item_bytes = get_write_item_bytes(data_bytes, item)
        write_item_current_page_bytes(
            self, serial, item_bytes, item.value, status)


def handshake_handle_connect_event(self, dataByte: bytes):
    if dataByte[14:16] == b"\x00\x01":
        if dataByte[20] != 1:
            model_str = self.MODEL
            radioType = dataByte[20: 20 + len(model_str)]
            if radioType == model_str.encode("ascii"):
                return HandshakeStatuses.Normal
            else:
                return HandshakeStatuses.RadioWrong
        else:
            return HandshakeStatuses.PwdWrong
    else:
        return HandshakeStatuses.Wrong


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
    """
    Fully optimized version using struct.pack for all components.
    """
    model_bytes = currentModel.encode("ascii")
    magic = b"RDTP\x01\x00\x00\x00\x00\x00\x00\x00"
    prefix = b"\x00\x00\x00\x00\x01\x00"
    padding_len = 41 - len(model_bytes)
    padding = b"\x00" * padding_len
    data_len = len(prefix) + len(model_bytes) + padding_len
    packet = struct.pack(
        f"<12sH6s{len(model_bytes)}s{padding_len}s",
        magic,
        data_len,
        prefix,
        model_bytes,
        padding)
    # Calculate CRC and append footer
    crc = calculate_crc16(packet)
    return packet + crc + b"\xff"


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
                                      packet_index.to_bytes(2, "little")),
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


def read_item_handle_connect_event(all_bytes: bytearray,
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


def calculate_crc16(buf):
    crc = 0x0000
    for b in buf:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack("<H", crc)


def _get_memory(self, mem, _mem, ch_index):
    ch_index_dict = get_ch_index(self)
    if ch_index not in ch_index_dict:
        mem.freq = 0
        mem.empty = True
    mem.extra = RadioSettingGroup("Extra", "extra")
    mem.extra.append(
        RadioSetting(
            "tottime",
            "TOT[S]",
            RadioSettingValueList(
                get_namedict_by_items(TIMEOUTTIMER_LIST),
                current_index=(_mem.tottime - 1))))
    mem.extra.append(
        RadioSetting(
            "totPermissions",
            "TX Permissions",
            RadioSettingValueList(TOTPERSMISSION_LIST,
                                  current_index=_mem.totPermissions)))
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
            "Alarm Sytem",
            RadioSettingValueList(
                get_namedict_by_items(ALARM_LIST),
                current_index=get_item_by_id(ALARM_LIST,
                                             _mem.alarmlist))))
    mem.extra.append(
        RadioSetting(
            "dtmfsignalinglist",
            "DTMF System",
            RadioSettingValueList(
                get_namedict_by_items(DTMFSYSTEM_LIST),
                current_index=get_item_by_id(DTMFSYSTEM_LIST,
                                             _mem.dtmfsignalinglist))))
    mem.extra.append(
        RadioSetting(
            "offlineorreversal",
            "Talkaround & Reversal",
            RadioSettingValueList(OFFLINE_REVERSAL_LIST,
                                  current_index=_mem.offlineorreversal)))
    mem.extra.append(
        RadioSetting(
            "vox", "vox",
            RadioSettingValueBoolean(_mem.vox)))
    mem.extra.append(
        RadioSetting(
            "companding", "compander",
            RadioSettingValueBoolean(_mem.companding)))
    mem.extra.append(
        RadioSetting("scramble", "scramble",
                     RadioSettingValueBoolean(_mem.scramble)))
    if mem.empty:
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
    rs = RadioSetting("modelinfo.freqrange", "Frequency Range[MHZ]", rs_value)
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
            self, _settings, "frestep", "Frequency Step",
            _settings.frestep, Fre_Step_List))
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
            self, _settings, "voxthreshold", "Vox Level",
            _settings.voxthreshold, opts_dict))
    opts_dict = [
        {"name": "%sms" % ((x) * 500), "id": x} for x in range(1, 5, 1)]
    common.append(
        get_radiosetting_by_key(
            self, _settings, "voxdelaytime", "Vox Delay Time",
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
            "settings.autoormanuallock", "KeyLock Mode",
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
    print(_settings)
    print(_settings.poweron_type_1)
    common.append(
        RadioSetting(
            "settings.poweron_type_1",
            "Power On A",
            RadioSettingValueList(opts,
                                  current_index=_settings.poweron_type_1)))
    print(_settings.poweron_type_2)
    common.append(
        RadioSetting(
            "settings.poweron_type_2",
            "Power On B",
            RadioSettingValueList(opts,
                                  current_index=_settings.poweron_type_2)))
    opts_dict = get_scan_item_list(self)
    common.append(
        get_radiosetting_by_key(
            self, _settings, "scanlist", "Enable Scan List",
            _settings.scanlist, opts_dict))
    short_dict = SIDE_KEY_LIST[:12]
    common.append(
        get_radiosetting_by_key(
            self, _settings, "tk1_short", "TK Short Press",
            _settings.tk1_short, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "tk1_long", "TK Long Press",
            _settings.tk1_long, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk1_short", "Short Press SK1",
            _settings.sk1_short, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk1_long", "Long Press SK1",
            _settings.sk1_long, SIDE_KEY_LIST))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk2_short", "Short Press SK2",
            _settings.sk2_short, short_dict))
    common.append(
        get_radiosetting_by_key(
            self, _settings, "sk2_long", "Long Press SK2",
            _settings.sk2_long, SIDE_KEY_LIST))
    opts = ["55HZ", "120°", "180°", "240°"]
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
    opts = ["1000HZ", "1450HZ", "1750HZ", "2100HZ"]
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
            "settings.rogerbeep", "RogerBeep",
            RadioSettingValueBoolean(_settings.rogerbeep)))
    common.append(
        RadioSetting(
            "settings.touchtone", "Key Beep",
            RadioSettingValueBoolean(_settings.touchtone)))
    common.append(
        RadioSetting(
            "settings.txenstone", "TX Permit Tone",
            RadioSettingValueBoolean(_settings.txenstone)))
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
    opts = [{"name": "Stun Tx", "id": 1}, {"name": "Stun TX/RX", "id": 2}]
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
            "dtmfsetting.callid", "Call Id",
            RadioSettingValueString(
                0, 10,
                "".join(filter(_dtmf_comm.callid, DTMFCHARSET, 10, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.stunid", "Stun Id",
            RadioSettingValueString(
                0, 10,
                "".join(filter(_dtmf_comm.stunid, DTMFCHARSET, 10, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.revive", "Revive Id",
            RadioSettingValueString(
                0, 10,
                "".join(filter(_dtmf_comm.revive, DTMFCHARSET, 10, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.bot", "Bot",
            RadioSettingValueString(
                0, 16,
                "".join(filter(_dtmf_comm.bot, DTMFCHARSET, 16, True)),
                False, DTMFCHARSET)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.eot", "Eot",
            RadioSettingValueString(
                0, 16,
                "".join(filter(_dtmf_comm.eot, DTMFCHARSET, 16, True)),
                False, DTMFCHARSET)))


def get_dtmf_list(self, dtmf_list):
    _dtmf_data = self._memobj.dtmfdata
    _dtmf_list = self._memobj.dtmfs
    dtmf_count = _dtmf_data.dtmfnum
    dtmf_count = 4 if dtmf_count > 4 else dtmf_count
    if dtmf_count <= 0:
        return
    dtmf_list.set_shortname("dtmf list")
    for i in range(0, dtmf_count):
        index = i + 1
        dtmf_item = _dtmf_list[i]
        rsg = RadioSettingSubGroup("dtmf_list-%i" % i,
                                   "dtmf_list %i" % (i + 1))
        rs = RadioSetting(
            "dtmflist.name_%s" % index, "DTMF Name",
            RadioSettingValueString(
                0, 12,
                "".join(filter(dtmf_item.name, NAMECHATSET, 12)),
                False, NAMECHATSET))
        rs.set_apply_callback(set_dtmf_list_callback, self, i, "name")
        rsg.append(rs)
        opts = ["%sms" % x for x in range(50, 210, 10)]
        rs = RadioSetting(
            "codelen_%s" % index, "DTMF Code Length",
            RadioSettingValueList(opts, current_index=dtmf_item.codelen))
        rs.set_apply_callback(set_dtmf_list_callback, self, i, "codelen")
        rsg.append(rs)
        opts = ["None", "A", "B", "C", "D", "*", "#"]
        rs = RadioSetting(
            "groupcode_%s" % index, "Group Code",
            RadioSettingValueList(opts, current_index=dtmf_item.groupcode))
        rs.set_apply_callback(set_dtmf_list_callback, self, i, "groupcode")
        rsg.append(rs)
        rs = RadioSetting(
            "EncodingEnable_%s" % index, "IsEncodingEnable",
            RadioSettingValueBoolean(dtmf_item.EncodingEnable))
        rs.set_apply_callback(set_dtmf_list_callback,
                              self, i, "EncodingEnable")
        rsg.append(rs)
        rs = RadioSetting(
            "DecodingEnable_%s" % index, "IsDecodingEnable",
            RadioSettingValueBoolean(dtmf_item.DecodingEnable))
        rs.set_apply_callback(set_dtmf_list_callback,
                              self, i, "DecodingEnable")
        rsg.append(rs)
        for j in range(1, 11):
            rs = RadioSetting(
                "dtmfsetting.fastcall_%d_%s" % (index, j),
                "FastCall_%s" % j,
                RadioSettingValueString(
                    0, 16,
                    "".join(filter(dtmf_item["fastcall%d" % j],
                                   DTMFCHARSET, 16)),
                    False, DTMFCHARSET))
            rs.set_apply_callback(set_dtmf_list_callback,
                                  self, i, "fastcall%s" % j)
            rsg.append(rs)
        dtmf_list.append(rsg)


def get_scan_list(self, scan_list):
    _scan_list = self._memobj.scans
    _scan_data = self._memobj.scandata
    scan_count = _scan_data.scannum
    scan_count = 16 if scan_count > 16 else scan_count
    if scan_count <= 0:
        return
    for i in range(0, scan_count):
        index = i + 1
        rsg = RadioSettingSubGroup("scan_list-%i" % i,
                                   "scan_list %i" % index)
        _scan_item = _scan_list[i]
        rs = RadioSetting(
            "scanlist.name_%s" % index,
            "Scan Name",
            RadioSettingValueString(
                0, 12,
                "".join(filter(_scan_item.name, NAMECHATSET, 12)),
                False, NAMECHATSET))
        rs.set_apply_callback(set_scan_list_callback,
                              self, i, "name")
        rsg.append(rs)
        opts = ["Carrier", "Time", "Search"]
        rs = RadioSetting(
            "scanlist.scanmode_%s" % index, "Scan Mode",
            RadioSettingValueList(opts, current_index=_scan_item.scanmode))
        rs.set_apply_callback(set_scan_list_callback, self, i, "scanmode")
        rsg.append(rs)
        opts = ["Carrier", "CTC/DCS"]
        rs = RadioSetting(
            "scanlist.scancondition_%s" % index, "Scan Condition",
            RadioSettingValueList(opts,
                                  current_index=_scan_item.scancondition))
        rs.set_apply_callback(set_scan_list_callback,
                              self, i, "scancondition")
        rsg.append(rs)
        opts = ["Selected", "Last Active Channel", "Designated Channel"]
        rs = RadioSetting(
            "scanlist.scantxch_%s" % index,
            "Designated Transmission Channel",
            RadioSettingValueList(opts, current_index=_scan_item.scantxch))
        rs.set_apply_callback(set_scan_list_callback,
                              self, i, "scantxch")
        rsg.append(rs)
        opts = ["%ss" % (x + 1) for x in range(0, 17, 1)]
        rs = RadioSetting(
            "scanlist.hangtime_%s" % index,
            "Scan Hang Time",
            RadioSettingValueList(opts, current_index=_scan_item.hangtime))
        rs.set_apply_callback(set_scan_list_callback, self, i, "hangtime")
        rsg.append(rs)
        rs = RadioSetting(
            "scanlist.talkback_%s" % index,
            "TalkBackEnable",
            RadioSettingValueBoolean(_scan_item.talkback))
        rs.set_apply_callback(set_scan_list_callback, self, i, "talkback")
        rsg.append(rs)
        scan_list.append(rsg)


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
            "vfoscan.scancondition", "Scan Conditions",
            RadioSettingValueList(opts,
                                  current_index=_vfo_scan.scancondition)))

    opts = ["%s" % x for x in range(1, 16, 1)]
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


def get_alarm_list(self, alarm_list):
    _alarm_list = self._memobj.alarms
    _alarm_data = self._memobj.alarmdata
    alarm_count = _alarm_data.alarmnum
    alarm_count = 8 if alarm_count > 8 else alarm_count
    if alarm_count <= 0:
        return
    for i in range(0, alarm_count):
        index = i + 1
        rsg = RadioSettingSubGroup("alarm_list-%i" % i,
                                   "alarm_list %i" % index)
        _alarm_item = _alarm_list[i]
        rs = RadioSetting(
            "alarmlist.name_%s" % index, "Alarm Name",
            RadioSettingValueString(
                0, 12,
                "".join(filter(_alarm_item.name, NAMECHATSET, 12)),
                False, NAMECHATSET))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "name")
        rsg.append(rs)
        opts = ["Siren", "Regular", "Silent", "Silent & w/Voice"]
        rs = RadioSetting(
            "alarmlist.alarmtype_%s" % index, "Alarm Type",
            RadioSettingValueList(opts, current_index=_alarm_item.alarmtype))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "alarmtype")
        rsg.append(rs)
        opts = ["Alarm", "w/Call", "Alarm & w/Call"]
        rs = RadioSetting(
            "alarmlist.alarmmode_%s" % index, "Alarm Mode",
            RadioSettingValueList(opts, current_index=_alarm_item.alarmmode))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "alarmmode")
        rsg.append(rs)
        rs = RadioSetting(
            "scanlist.localalarm_%s" % index, "Local Alarm Tone",
            RadioSettingValueBoolean(_alarm_item.localalarm))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "localalarm")
        rsg.append(rs)
        opts = ["Carrier Wave", "CTCSS/DCS"]
        rs = RadioSetting(
            "alarmlist.ctcmode_%s" % index, "Alarm Tone Mode",
            RadioSettingValueList(opts, current_index=_alarm_item.ctcmode))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "ctcmode")
        rsg.append(rs)

        opts = ["Infinite"] + ["%ss" % x for x in range(5, 70, 5)]
        rs = RadioSetting(
            "alarmlist.alarmcycle_%s" % index, "Alarm Cycle",
            RadioSettingValueList(opts, current_index=_alarm_item.alarmcycle))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "alarmcycle")
        rsg.append(rs)
        opts = ["%ss" % x for x in range(10, 170, 10)]
        rs = RadioSetting(
            "alarmlist.alarmtime_%s" % index, "Alarm Duration",
            RadioSettingValueList(opts, current_index=_alarm_item.alarmtime))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "alarmtime")
        rsg.append(rs)
        rs = RadioSetting(
            "alarmlist.txinterval_%s" % index, "Alarm Interval",
            RadioSettingValueList(opts, current_index=_alarm_item.txinterval))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "txinterval")
        rsg.append(rs)
        rs = RadioSetting(
            "alarmlist.mictime_%s" % index, "Alarm Mic Time",
            RadioSettingValueList(opts, current_index=_alarm_item.mictime))
        rs.set_apply_callback(set_alarm_list_callback, self, i, "mictime")
        rsg.append(rs)
        alarm_list.append(rsg)


def get_zone_list(self, zone_list):
    _zone_list = self._memobj.zones
    for i in range(0, 64):
        index = i + 1
        rsg = RadioSettingSubGroup("zone_list-%i" % i, "zone_list %i" % index)
        _zone_item = _zone_list[i]
        zone_index_dict = get_zone_index_list(self)
        zone_status = i in zone_index_dict
        rs = RadioSetting(
            "zonelist.status_%s" % index, "Enable",
            RadioSettingValueBoolean(zone_status))
        rs.set_apply_callback(set_zone_list_callback, self, i, "zonestatus")
        rsg.append(rs)
        rs = RadioSetting(
            "zonelist.name_%s" % index, "Zone Name",
            RadioSettingValueString(
                0, 12,
                "".join(filter(_zone_item.name, NAMECHATSET, 12)),
                False, NAMECHATSET))
        rs.set_apply_callback(set_zone_list_callback, self, i, "name")
        rsg.append(rs)
        zone_list.append(rsg)


def _set_memory(self, mem, _mem, ch_index):
    ch_index_dict = get_ch_index(self)
    rx_freq = get_ch_rxfreq(mem)
    flag = ch_index not in ch_index_dict and rx_freq != 0
    if rx_freq != 0xFFFFFFFF and flag:
        ch_index_dict.append(ch_index)
        set_ch_index(self, ch_index_dict)
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
                ALARM_LIST, setting.value)
        elif setting.get_name() == "dtmfsignalinglist":
            _mem.dtmfsignalinglist = get_item_by_name(
                DTMFSYSTEM_LIST, setting.value)
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


def get_zoneitem_by_key(self, _setting, item_key,
                        item_display_name, item_value,
                        opts_dict, callback=None):
    opts = get_namedict_by_items(opts_dict)
    item = RadioSetting(
        item_key,
        item_display_name,
        RadioSettingValueList(
            opts, current_index=get_item_by_id(opts_dict, item_value)))
    item.set_volatile(True)
    item.set_doc("Requires reload of file after changing!")
    item.set_apply_callback(
        set_poweron_zone_callback if callback is None else callback,
        self, _setting, item_key, opts_dict)
    return item


def get_namedict_by_items(items):
    return [x["name"] for x in items]


def get_item_by_id(items, value):
    return next((i for i, item in enumerate(items) if item["id"] == value), 0)


def get_item_name_by_id(items, value):
    return next((item["name"] for item in items if item["id"] == value), "")


def set_poweron_zone_callback(set_item, self, obj, name, items):
    item_value = get_item_by_name(items, set_item.value)
    self._memobj.settings[name] = item_value & 0xFF
    self._memobj.settings[("%s_height" % name)] = (item_value >> 8) & 0xF


def set_item_twobytes_callback(setting, obj, item_key, opts, self):
    item_value, = swap_high_low_bytes_16bit_int(
        get_item_by_name(opts, setting.value))
    setattr(obj, item_key, item_value)


def swap_high_low_bytes_16bit_int(value: int) -> int:
    swapped, = struct.unpack(">H", struct.pack("<H", value))
    return swapped


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


def get_ch_items(self):
    ch_dict = []
    _chdata = self._memobj.channeldata
    _chs = self._memobj.channels
    ch_num = _chdata.chnum
    if ch_num > 3:
        for i in range(3, ch_num):
            ch_index = _chdata.chindex[i]
            if ch_index < 259:
                chname = "".join(filter(_chs[ch_index].alias, NAMECHATSET, 12))
                ch_dict.append({"name": chname, "id": ch_index})
    return ch_dict


def get_ch_items_by_index(ch_items, ch_index_dict):
    items = []
    for i, ch_index in enumerate(ch_index_dict):
        ch_item = next(
            (item for item in ch_items
             if item["id"] == ch_index), None)
        if ch_item is not None:
            items.append({"name": ch_item["name"], "id": i})
    return items


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
    elif mem.freq < 134000000:
        ch_freq = 134000000
    elif mem.freq > 174000000 and mem.freq < 400000000:
        ch_freq = 174000000
    elif mem.freq > 480000000:
        ch_freq = 480000000
    return ch_freq


def get_ch_txfreq(rx_freq, tx_freq):
    return (rx_freq
            if (tx_freq < 134
                or (tx_freq > 174 and tx_freq < 400)
                or tx_freq > 480)
            else tx_freq)


def get_alarm_item_list(self):
    _alarmdata = self._memobj.alarmdata
    _alarms = self._memobj.alarms
    ALARM_LIST.clear()
    ALARM_LIST.append({"name": "OFF", "id": 255})
    alarm_num = _alarmdata.alarmnum
    if alarm_num > 0:
        for i in range(0, alarm_num):
            alarm_index = _alarmdata.alarmindex[i]
            if alarm_index < 8:
                alarm_item = _alarms[alarm_index]
                alarm_item.alarmstatus = 1
                alarmname = "".join(filter(alarm_item.name, NAMECHATSET, 12))
                ALARM_LIST.append({"name": alarmname, "id": alarm_index})


def get_dtmf_item_list(self):
    _dtmfdata = self._memobj.dtmfdata
    _dtmfs = self._memobj.dtmfs
    DTMFSYSTEM_LIST.clear()
    DTMFSYSTEM_LIST.append({"name": "OFF", "id": 15})
    dtmf_num = _dtmfdata.dtmfnum
    if dtmf_num > 0:
        for i in range(0, dtmf_num):
            dtmf_index = _dtmfdata.dtmfindex[i]
            if dtmf_index < 8:
                dtmf_item = _dtmfs[dtmf_index]
                dtmf_item.dtmfstatus = 1
                dtmfname = "".join(filter(dtmf_item.name, NAMECHATSET, 12))
                DTMFSYSTEM_LIST.append({"name": dtmfname, "id": dtmf_index})


def get_scan_item_list(self):
    _scandata = self._memobj.scandata
    _scans = self._memobj.scans
    scan_dict = []
    scan_num = _scandata.scannum
    if scan_num > 0:
        for i in range(0, scan_num):
            scan_index = _scandata.scanindex[i]
            if scan_index < 16:
                scan_item = _scans[scan_index]
                scanname = "".join(filter(scan_item.name, NAMECHATSET, 12))
                scan_dict.append({"name": scanname, "id": scan_index})
    return scan_dict


def get_alarm_index_list(self):
    _alarmdata = self._memobj.alarmdata
    alarm_index_dict = []
    alarm_num = _alarmdata.alarmnum
    if alarm_num > 0:
        for i in range(0, alarm_num):
            alarm_index = _alarmdata.alarmindex[i]
            if alarm_index < 8:
                alarm_index_dict.append(alarm_index)
    return alarm_index_dict


def get_dtmf_index_list(self):
    _dtmfdata = self._memobj.dtmfdata
    dtmf_index_dict = []
    dtmf_num = _dtmfdata.dtmfnum
    if dtmf_num > 0:
        for i in range(0, dtmf_num):
            dtmf_index = _dtmfdata.dtmfindex[i]
            if dtmf_index < 4:
                dtmf_index_dict.append(dtmf_index)
    return dtmf_index_dict


def get_scan_index_list(self):
    _scandata = self._memobj.scandata
    scan_index_dict = []
    scan_num = _scandata.scannum
    if scan_num > 0:
        for i in range(0, scan_num):
            scan_index = _scandata.scanindex[i]
            if scan_index < 16:
                scan_index_dict.append(scan_index)
    return scan_index_dict


def get_zone_index_list(self):
    _zonedata = self._memobj.zonedata
    zone_index_dict = []
    zone_num = _zonedata.zonenum
    if zone_num > 0:
        for i in range(0, zone_num):
            zone_index = _zonedata.zoneindex[i]
            if zone_index < 64:
                zone_index_dict.append(zone_index)
    return zone_index_dict


def set_alarm_index_list(self, alarm_index_dict):
    _alarmdata = self._memobj.alarmdata
    alarm_count, = len(alarm_index_dict)
    _alarmdata.alarmnum = alarm_count
    if alarm_count > 0:
        for i in range(0, 8):
            if i < alarm_count:
                _alarmdata.alarmindex[i] = alarm_index_dict[i]
            else:
                _alarmdata.alarmindex[i] = 0xFFFF
    get_alarm_item_list(self)  # update ALARM_LIST


def set_zone_index_list(self, zone_index_dict):
    _zonedata = self._memobj.zonedata
    zone_count = len(zone_index_dict)
    _zonedata.zonenum = zone_count
    if zone_count > 0:
        for i in range(0, 64):
            if i < zone_count:
                _zonedata.zoneindex[i] = zone_index_dict
            else:
                _zonedata.zoneindex[i] = 0xFFFF


def set_zone_ch_list(self, zone_index, zone_ch_dict):
    _zone_list = self._memobj.zones
    if zone_index >= len(_zone_list):
        raise Exception("Zone index out of range")
    zone_item = _zone_list[zone_index]
    zone_ch_count = len(zone_ch_dict)
    zone_item.chnum = zone_ch_count
    if zone_ch_count > 0:
        for i in range(0, 16):
            if i < zone_ch_count:
                zone_item.chindex[i] = zone_ch_dict[i]
            else:
                zone_item.chindex[i] = 0xFFFF


def set_dtmf_index_list(self, dtmf_index_dict):
    _dtmfdata = self._memobj.dtmfdata
    dtmf_count = len(dtmf_index_dict)
    _dtmfdata.dtmfnum = dtmf_count
    if dtmf_count > 0:
        for i in range(0, dtmf_count):
            if i < 4:
                _dtmfdata.dtmfindex[i] = dtmf_index_dict[i]
            else:
                raise ValueError("Not enough space in alarmindex array")
    get_dtmf_item_list(self)  # update DTMFSYSTEM_LIST


def set_scan_index_list(self, scan_index_dict):
    _scandata = self._memobj.scandata
    scan_count = len(scan_index_dict)
    if scan_count > 0:
        for i in range(0, scan_count):
            if i < 16:
                _scandata.scanindex[i] = scan_index_dict
            else:
                raise ValueError("Not enough space in scanindex array")


def set_dtmf_list_callback(set_item, self, index, name):
    _dtmf_list = self._memobj.dtmfs
    value = set_item.value
    if index < len(_dtmf_list):
        if name == "dtmfstatus":
            dtmf_index_dict = get_dtmf_index_list(self)
            if value == 1 and index not in dtmf_index_dict:
                dtmf_index_dict.append(index)
            elif value == 0 and index in dtmf_index_dict:
                dtmf_index_dict.remove(index)
            set_dtmf_index_list(self, dtmf_index_dict)
        elif name == "name":
            value = filter(value, NAMECHATSET, 12, True)
            value = value.ljust(14, "\x00")
        elif name.startswith("fastcall"):
            value = filter(value, DTMFCHARSET, 16, True)
            value = value.ljust(16, "\x00")
        setattr(_dtmf_list[index], name, value)


def set_scan_list_callback(set_item, self, index, name, items=None):
    _scan_list = self._memobj.scans
    value = set_item.value
    if index < len(_scan_list):
        if name == "scanstatus":
            scan_index_dict = get_scan_index_list(self)
            if value == 1 and index not in scan_index_dict:
                scan_index_dict.append(index)
            elif value == 0 and index in scan_index_dict:
                scan_index_dict.remove(index)
            set_scan_index_list(self, scan_index_dict)
        elif name == "name":
            value = filter(value, NAMECHATSET, 12, True)
            value = value.ljust(14, "\x00")
        elif (name in ["specifych", "PriorityCh1", "PriorityCh2"]
              and items is not None):
            ch_value = get_item_by_name(items, value)
            value = ch_value
        setattr(_scan_list[index], name, value)


def set_alarm_list_callback(set_item, self,
                            index, name, items=None):
    _alarm_list = self._memobj.alarms
    value = set_item.value
    if index < len(_alarm_list):
        if name == "alarmstatus":
            alarm_index_dict = get_alarm_index_list(self)
            if value == 1 and index not in alarm_index_dict:
                alarm_index_dict.append(index)
            elif value == 0 and index in alarm_index_dict:
                alarm_index_dict.remove(index)
            set_alarm_index_list(self, alarm_index_dict)
        elif name == "name":
            value = filter(value, NAMECHATSET, 12, True)
            value = value.ljust(14, "\x00")
        elif (name == "jumpch") and items is not None:
            ch_value = get_item_by_name(items, value)
            value = ch_value
        setattr(_alarm_list[index], name, value)


def set_zone_list_callback(set_item, self, index, name):
    _zone_list = self._memobj.zones
    value = set_item.value
    if index < len(_zone_list):
        if name == "zonestatus":
            zone_index_dict = get_zone_index_list(self)
            if value == 1 and index not in zone_index_dict:
                zone_index_dict.append(index)
            elif value == 0 and index in zone_index_dict:
                zone_index_dict.remove(index)
            set_zone_index_list(self, zone_index_dict)
        elif name == "name":
            value = filter(value, NAMECHATSET, 12, True)
            value = value.ljust(14, "\x00")
            setattr(_zone_list[index], name, value)


def set_band_selection(set_item, obj,
                       opts, home_select_field_name,
                       home_index_field_name):
    value = opts.index(set_item.value)
    if value == 3:
        setattr(obj, home_index_field_name, 1)
        setattr(obj, home_select_field_name, 3)
    elif value == 2:
        setattr(obj, home_index_field_name, 0)
        setattr(obj, home_select_field_name, 3)
    elif value == 1:
        setattr(obj, home_index_field_name, 1)
        setattr(obj, home_select_field_name, 2)
    else:
        setattr(obj, home_index_field_name, 0)
        setattr(obj, home_select_field_name, 1)


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
    hand_shake_bytes = get_handshake_bytes(MODEL)
    _ch_cache = None

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_special_chans = sorted(SPECIAL_MEMORIES.keys())
        rf.memory_bounds = (1, 256)  # Channel range
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_dtcs = True
        rf.has_cross = True
        rf.has_bank = False
        rf.valid_bands = [(134000000, 174000010), (400000000, 480000010)]
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
        get_dtmf_item_list(self)
        get_alarm_item_list(self)

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
        scan = RadioSettingGroup("scan", "Scan List")
        dtmf = RadioSettingGroup("dtmfe", "DTMF Settings")
        vfoscan = RadioSettingGroup("vfoscan", "VFO  Scan")
        alarm = RadioSettingGroup("alarm", "Alarm List")
        setmode = RadioSettings(ModelInfo, common, dtmf, scan, vfoscan, alarm)
        try:
            get_model_info(self, ModelInfo)
            get_common_setting(self, common)
            get_dtmf_setting(self, dtmf)
            get_dtmf_list(self, dtmf)
            get_scan_list(self, scan)
            get_vfo_scan(self, vfoscan)
            get_alarm_list(self, alarm)
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

    def _debank(self, mem):
        bm = self.get_bank_model()
        for bank in bm.get_memory_mappings(mem):
            bm.remove_memory_from_mapping(mem, bank)

    def get_bank_model(self):
        return HA1GBankModel(self)


@directory.register
class HA1UV(HA1G):
    """Retevis HA1UV"""

    MODEL = "HA1UV"
    current_model = "HA1UV"

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
    _set_memory(self, mem, _mem, ch_index)
    LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
