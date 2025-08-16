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

from chirp import util, memmap, chirp_common, bitwise, directory, errors
from chirp import bitwise, errors, util
from chirp.settings import RadioSetting, RadioSettingGroup,RadioSettingSubGroup, \
    RadioSettingValueList, RadioSettingValueString, RadioSettings, \
    RadioSettingValueInteger, RadioSettingValueBoolean,RadioSettingValueFloat
    
LOG = logging.getLogger(__name__)

crc16_tab = [
    0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241, 0xC601, 0x06C0, 0x0780, 0xC741,
0x0500, 0xC5C1, 0xC481, 0x0440, 0xCC01, 0x0CC0, 0x0D80, 0xCD41, 0x0F00, 0xCFC1, 0xCE81, 0x0E40, 0x0A00, 0xCAC1, 0xCB81, 0x0B40,
0xC901, 0x09C0, 0x0880, 0xC841, 0xD801, 0x18C0, 0x1980, 0xD941, 0x1B00, 0xDBC1, 0xDA81, 0x1A40, 0x1E00, 0xDEC1, 0xDF81, 0x1F40,
0xDD01, 0x1DC0, 0x1C80, 0xDC41, 0x1400, 0xD4C1, 0xD581, 0x1540, 0xD701, 0x17C0, 0x1680, 0xD641, 0xD201, 0x12C0, 0x1380, 0xD341,
0x1100, 0xD1C1, 0xD081, 0x1040, 0xF001, 0x30C0, 0x3180, 0xF141, 0x3300, 0xF3C1, 0xF281, 0x3240, 0x3600, 0xF6C1, 0xF781, 0x3740,
0xF501, 0x35C0, 0x3480, 0xF441, 0x3C00, 0xFCC1, 0xFD81, 0x3D40, 0xFF01, 0x3FC0, 0x3E80, 0xFE41, 0xFA01, 0x3AC0, 0x3B80, 0xFB41,
0x3900, 0xF9C1, 0xF881, 0x3840, 0x2800, 0xE8C1, 0xE981, 0x2940, 0xEB01, 0x2BC0, 0x2A80, 0xEA41, 0xEE01, 0x2EC0, 0x2F80, 0xEF41,
0x2D00, 0xEDC1, 0xEC81, 0x2C40, 0xE401, 0x24C0, 0x2580, 0xE541, 0x2700, 0xE7C1, 0xE681, 0x2640, 0x2200, 0xE2C1, 0xE381, 0x2340,
0xE101, 0x21C0, 0x2080, 0xE041, 0xA001, 0x60C0, 0x6180, 0xA141, 0x6300, 0xA3C1, 0xA281, 0x6240, 0x6600, 0xA6C1, 0xA781, 0x6740,
0xA501, 0x65C0, 0x6480, 0xA441, 0x6C00, 0xACC1, 0xAD81, 0x6D40, 0xAF01, 0x6FC0, 0x6E80, 0xAE41, 0xAA01, 0x6AC0, 0x6B80, 0xAB41,
0x6900, 0xA9C1, 0xA881, 0x6840, 0x7800, 0xB8C1, 0xB981, 0x7940, 0xBB01, 0x7BC0, 0x7A80, 0xBA41, 0xBE01, 0x7EC0, 0x7F80, 0xBF41,
0x7D00, 0xBDC1, 0xBC81, 0x7C40, 0xB401, 0x74C0, 0x7580, 0xB541, 0x7700, 0xB7C1, 0xB681, 0x7640, 0x7200, 0xB2C1, 0xB381, 0x7340,
0xB101, 0x71C0, 0x7080, 0xB041, 0x5000, 0x90C1, 0x9181, 0x5140, 0x9301, 0x53C0, 0x5280, 0x9241, 0x9601, 0x56C0, 0x5780, 0x9741,
0x5500, 0x95C1, 0x9481, 0x5440, 0x9C01, 0x5CC0, 0x5D80, 0x9D41, 0x5F00, 0x9FC1, 0x9E81, 0x5E40, 0x5A00, 0x9AC1, 0x9B81, 0x5B40,
0x9901, 0x59C0, 0x5880, 0x9841, 0x8801, 0x48C0, 0x4980, 0x8941, 0x4B00, 0x8BC1, 0x8A81, 0x4A40, 0x4E00, 0x8EC1, 0x8F81, 0x4F40,
0x8D01, 0x4DC0, 0x4C80, 0x8C41, 0x4400, 0x84C1, 0x8581, 0x4540, 0x8701, 0x47C0, 0x4680, 0x8641, 0x8201, 0x42C0, 0x4380, 0x8341,
0x4100, 0x81C1, 0x8081, 0x4040,
]

MEM_FORMAT = """
   
#seekto 0x0E;
struct{
   u8 modelnumber[32];
   u8 hardwareversion[2];
   u8 serialn0[16];
   u8 freqmin[4];
   u8 freqmax[4];
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
  u8 homepoweronzone_1;
  u8 poweron_type_1:4,
     homepoweronzone_1_height:4;
  u16 homepoweronch_1;
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
  u8 homepoweronzone_2;
  u8 poweron_type_2:4,
     homepoweronzone_2_height:4;
  u16 homepoweronch_2;
  u16 homepoweronzone_3;
  u16 homepoweronch_3;
  u16 frestep;
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
    u16 zonenum;
    u16 zoneindex[64]; 
} zonedata; 

#seekto 0x142;
struct {
    char name[14];
    u16 chnum;
    u16 chindex[16];
} zones[64];

#seekto 0x0D42;
struct  {
    u16 chnum;
    u16 chindex[1027];
} channeldata;

#seekto 0x154a;
struct  {
  u8 alias[14];  
  u8 chmode:4,
     chpro:4;
  u8 fixedpower:1,
     fixedbandwidth:1,
     TailElimination:2,
     power:2,
     bandwidth:2;
  u8 rxfreq[4];
  u8 txfreq[4];
  u8 rxctcvaluetype:2,
     rxctctypecode:1,
     rev_1:1,  
     rxctchight:4;
  u8 rxctclowvalue;
  u8 rxsqlmode;
  u8 txctcvaluetype:2,
     txctctypecode:1,
     rev_2:1,
     txctchight:4;
  u8 txctclowvalue;
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
  u16 dtmfcllid;
  u8 reserve[3] ;
} channels[1027];

#seekto 0xb5c2;
struct  {
    u16 scannum;
    u16 scanindex[16];   
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
   u16 specifych;
   u16 PriorityCh1;
   u16 PriorityCh2;
   u8 scanmode;
   u16 chindex[100];
} scans[16];

#seekto 0xc3e4;
struct  {
    u16 vfoscannum;
    u16 vfoscanindex[3];
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
   u8 vhffreq_start[4];
   u8 vhffreq_end[4];
   u32 uhffreq_start;
   u32 uhffreq_end;
   u8 rev;
} vfoscans[3];

#seekto 0xc444;
struct  {
    u16 alarmnum;
    u16 alarmindex[8];
} alarmdata;



#seekto 0xc456;
struct {
    char name[14];
    u8 alarmtype:4,
       alarmmode:4;
    u16 jumpch;
    u8 localalarm:1,
       txbackground:1,
       ctcmode:2,
       rev_1:4;
    u8 alarmtime:4,
       alarmcycle:4;
    u8 txinterval:4,
       mictime:4;  
    u8 alarmid[8];
    u8 alarmstatus;
    u8 rev_3[1];         
} alarms[8];

#seekto 0xc848;
struct  {
    u16 dtmfnum;
    u16 dtmfindex[4];
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
        DecodingEnable:1,
        EncodingEnable:1;
     u8 dtmfstatus;
     u8 rev_2[12];
} dtmfs[4]; 

"""

class HandShakeStuts(Enum):
    Normal= 0
    Wrong = 1
    PwdWrong = 3
    RadioWrong = 4

class Clone_TypeEnum(Enum):    
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
        outFactoryData = 17        

class File_AddrEnum(Enum):    
        radioHead = 0
        radioInfo = 0xE
        radioVer = 0x52
        settingData = 0x5c
        zoneData = 0xc0
        channelData = 0xd42
        scanData = 0xb5c2
        vfoScanData = 0xc3e4
        alarmData = 0xc444
        dTMFData = 0xc848
        outFactoryData = 0xccb4           


DTMFCHARSET='0123456789ABCDabcd#*'
NAMECHATSET=chirp_common.CHARSET_ALPHANUMERIC + "-/;,._!? *#@$%&+=/<>~(){}]'"
SPECIAL_MEMORIES={
     "VFOA": -2,
     "VFOB": -1
}
BANDWIDEH_LIST=["NFM","FM"]
POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=0),
    chirp_common.PowerLevel("High", watts=2),
    ]
TIMEOUTTIMER_LIST = [{"name": "%ss" % (x*5), "id": x} for x in range(1, 64, 1)]
TOTPERSMISSION_LIST=["Always","CTCSS/DCS Match","Channel Free","Receive Only"]
SQUELCHLEVEL_LIST=["AlwaysOpen","1","2","3","4","5","6","7","8","9"]
AUTOSCAN_LIST=["OFF","Auto Scan System"]
OFFLINE_REVERSAL_LIST=["OFF","Freq Reversql","Talk Around"]
SIDE_KEY_LIST=[{"name":"OFF","id":0},{"name":"TX Power","id":1},{"name":"Scan","id":2},{"name":"FM Radio","id":3},{"name":"Talkaround/Reversal","id":5},{"name":"Monitor","id":15},{"name":"Zone Plus","id":20},{"name":"Zone Minus","id":21},{"name":"Squelch","id":28},{"name":"Emergency Start","id":29},{"name":"Emergency Stop","id":30},{"name":"Optional DTMF Code","id":32},{"name":"Prog PTT","id":31}]
Fre_Step_List=[{"name":"2.5KHZ","id":2500},{"name":"5KHZ","id":5000},{"name":"6.25KHZ","id":6250},{"name":"8.33KHz","id":8330},{"name":"10KHZ","id":10000},{"name":"12.5KHZ","id":12500},{"name":"25KHZ","id":25000}]
ALARM_LIST=[{"name":"OFF","id":255}]
DTMFSYSTEM_LIST=[{"name":"OFF","id":15}]


class HA1GBank(chirp_common.NamedBank):
    """A HA1G bank"""
    def get_name(self):
        _zone_data=get_zone_index_list(self._model._radio)
        _zone_list=self._model._radio._memobj.zones
        if(self.index in _zone_data):
            zone_name= ''.join(filter(_zone_list[self.index].name,NAMECHATSET,12))
            return zone_name
        else:
            return ""
     
    def set_name(self, name):
        _zone_data=get_zone_index_list(self._model._radio)
        _zone_list=self._model._radio._memobj.zones
        if(self.index in _zone_data):
            _zone=_zone_list[self.index]
            _zone["name"]=filter(name, NAMECHATSET,12,True).ljust(14, '\x00')

class HA1GBankModel(chirp_common.BankModel):
    """A HA1G bank model"""

    def __init__(self, radio, name='Banks'):
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
        if(memory.freq==0):
            raise errors.RadioError("Cannot select a channel with empty frequency")
        else:    
            ch_num=memory.number
            if(len(channels_in_bank)<16):
                if ch_num not in channels_in_bank:
                    channels_in_bank.add(ch_num)
                    zone_ch_list=[x+2 for x in channels_in_bank]  # Adjusting channel numbers to match the radio's format
                    set_zone_ch_list(self._radio,bank.index, sorted(zone_ch_list))
            else:
                raise Exception("Bank is full, cannot add more channels")
        
     
    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._channel_numbers_in_bank(bank)
        ch_num=memory.number
        if(ch_num  in channels_in_bank):
            channels_in_bank.remove(ch_num)
            zone_ch_list=[x+2 for x in channels_in_bank] 
            set_zone_ch_list(self._radio,bank.index, sorted(zone_ch_list))
        else:
            raise Exception("Memory not found in bank, cannot remove")
        
    
    def _channel_numbers_in_bank(self, bank):
        _zone_data=get_zone_index_list(self._radio)
        _zone_list=self._radio._memobj.zones
        if(bank.index in _zone_data):
            _zone=_zone_list[bank.index] 
            _members=[get_ch_index_by_bytes(x) for x in _zone.chindex]
            return set([int(ch)-2 for ch in _members if ch != 0xFFFF])


    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._channel_numbers_in_bank(bank):
                banks.append(bank)
        return banks

def do_download(self):
   serial = self.pipe
   all_bytes=bytearray(self._memsize)
   handShake_Result= Handshake(self,serial)
   if(handShake_Result==HandShakeStuts.Normal):
       all_bytes= ReadItems(self,serial)
      
   elif(handShake_Result==HandShakeStuts.RadioWrong):
      raise errors.RadioError('Radio not match')
   elif(handShake_Result==HandShakeStuts.PwdWrong):
       raise errors.RadioError("download redio password Wrong")  
   else:
       raise errors.RadioError("connect Wrong")     
   exit_programming_mode(self)
   return memmap.MemoryMapBytes(bytes(all_bytes))

def do_upload(self):
    serial = self.pipe
    handShake_Result= Handshake(self,serial)
    if(handShake_Result==HandShakeStuts.Normal):
         write_items(self,serial)       
    elif(handShake_Result==HandShakeStuts.RadioWrong):
       raise errors.RadioError('Radio not match')
    elif(handShake_Result==HandShakeStuts.PwdWrong):
        raise errors.RadioError("download redio password Wrong")  
    else:
        raise errors.RadioError("connect Wrong")     
    exit_programming_mode(self)
    
def Handshake(self,serial):
    databytes=b""
    num=0
    while(num<=5):
       serial.write(Get_HandshakeBytes(self.MODEL+" "))   
       databytes=serial.read(self.page_len)
       flag,databytes=handle_connect_ver(databytes,serial)
       if(flag==True):
         break
       num +=1
    return HandshakeHandleConnectEvent(self,databytes)

def ReadItems(self,serial): 
    all_bytes =  bytearray(self._memsize)
    status = chirp_common.Status()
    status.msg = "Cloning from radio"
    status.cur = 0
    status.max = self._memsize
    for item in Clone_TypeEnum:
        try:
            print(item)
            item_bytes = get_read_current_page_bytes(self,item.value, serial,status)
            if item_bytes:                    
               all_bytes= read_item_handle_connect_event(all_bytes,item_bytes,item)               
        except Exception as e:
            print(f"读取项目 {item.name} 时出错: {e}")
            continue   
    return all_bytes       

def write_items(self, serial):
     print("开始写频")
     status = chirp_common.Status()
     status.msg = "Uploading to radio"
     status.cur = 0
     status.max = self._memsize
     data_bytes=self.get_mmap()
     print("数据")
     for item in Clone_TypeEnum:
         if item==Clone_TypeEnum.radioHead or item==Clone_TypeEnum.radioInfo or item==Clone_TypeEnum.radioVer or item==Clone_TypeEnum.zoneData or item ==Clone_TypeEnum.outFactoryData:
            continue
         item_bytes=get_write_item_bytes(data_bytes, item)
         write_item_current_page_bytes(self,serial,item_bytes,item.value,status)

def HandshakeHandleConnectEvent(self,dataByte:bytes):
    if(dataByte[14:16] == b"\x00\x01"):
            if (dataByte[20] !=1):
                 model_str = self.MODEL.decode('ascii') if isinstance(self.MODEL, bytes) else str(self.MODEL)
                 radioType = radioType = dataByte[20:20 + len(model_str)]
                 if (radioType==f"{model_str}".encode('ascii')):
                     return HandShakeStuts.Normal
                 else:
                      return HandShakeStuts.RadioWrong
            else:
                return HandShakeStuts.PwdWrong     
    else:
        return HandShakeStuts.Wrong
    
def handle_connect_ver(current_page_byte: bytes, serial_conn, max_retries=5, chunk_size=1024)-> tuple[bool, bytes]:
     new_bytes=current_page_byte
     if not new_bytes:  
        return False,new_bytes    
     for _ in range(max_retries):
        if RDTP_PageDataCrc16Ver(new_bytes):  
            return True,new_bytes     
        chunk = serial_conn.read(chunk_size)   
        if not chunk:  
            return False,new_bytes   
        new_bytes += chunk   
     print("校验未通过") 
     print(new_bytes)     
     return False,new_bytes  

def RDTP_PageDataCrc16Ver( current_Page_Byte:bytes):
    byteLen = len(current_Page_Byte)
    # 如果字节长度小于等于13，直接返回 False
    if byteLen <= 13:
        return False

    pageLen = current_Page_Byte[12] - 6 if current_Page_Byte[12] > 6 else 0
    pageLen += current_Page_Byte[13]

    if byteLen - 23 < pageLen:
        return False
    crcBytes = current_Page_Byte[-3:-1]
    dataBytes = current_Page_Byte[:-3]
    crcStr = calculate_crc16(dataBytes, 2)
    return crcBytes == crcStr

def Get_HandshakeBytes(currentModel):
    model_str = currentModel.decode('ascii') if isinstance(currentModel, bytes) else str(currentModel)
    data_part = b"\x00\x00\x00\x00\x01\x00" +f"{model_str}".encode('ascii')+ b"\x00" * (41-len(model_str))

    # 2. 构建握手数据（不含CRC和结束符）
    handshake_data = (
        b"RDTP\x01\x00\x00\x00\x00\x00\x00\x00" +   # 固定头部
        len(data_part).to_bytes(2, 'little') +      # 数据长度（小端序）
        data_part                                   # 实际数据
    )

    # 3. 计算CRC并拼接结束符
    crc = calculate_crc16(handshake_data,2)
    return handshake_data + crc + b"\xFF"

def get_read_current_page_bytes(self,item:int,serial,status): 
    pagecount=1
    pageindex=0
    item_bytes=b""
    while pageindex< pagecount:   
        num=0   
        success =False 
        while(num<=5):
            serial.write(Get_ReadItemBytes(item,pageindex))   
            databytes=serial.read(self.page_len)
            flag,newdatabytes=handle_connect_ver(databytes,serial)
            if(flag==True):           
                if(newdatabytes[14]!=item):
                   num +=1
                   time.sleep(0.05) 
                   print("读取数据错误，重新尝试")
                   print(newdatabytes)
                   continue
                if(pageindex==0):
                   pagecount= newdatabytes[18] | (newdatabytes[19] << 8)
                status.cur +=len(newdatabytes)
                self.status_fn(status)
                num=0    
                pageindex+=1
                item_bytes+=newdatabytes[20:-3]
                success=True
                break
            success=False
            print("读取数据错误，重新尝试")
            num +=1
            time.sleep(0.05) 
        if not success:
            raise errors.RadioError("down Wrong")  

    return item_bytes         

def write_item_current_page_bytes(self,serial,itemBytes:bytes,item:int,status):
    pagecount = math.ceil(len(itemBytes) / self.page_len)
    print(f"写频长度{len(itemBytes)}包数{pagecount}")
    for i in range(0,pagecount):
        num = 0
        print(i)
        while(num <= 5): 
            current_page_bytes=Get_WriteItemBytes(item, i, pagecount, itemBytes[i * self.page_len:(i + 1) * self.page_len])
            serial.write(current_page_bytes)   
            return_bytes=serial.read(self.page_len)
            flag,newdatabytes=handle_connect_ver(return_bytes,serial)
            if(flag==True):
                if(newdatabytes[14]!=item):
                   num +=1
                   time.sleep(0.05) 
                   print("写入数据错误，重新尝试")
                   print(newdatabytes)
                   continue
                status.cur +=len(current_page_bytes)
                
                self.status_fn(status)
                break
            print("写入数据错误，重新尝试")
            num+=1
            time.sleep(0.05) 
                       
def get_write_item_bytes(allbytes:bytearray,item):
    item_bytes=b""
    if(item==Clone_TypeEnum.radioHead):
        item_bytes= allbytes[File_AddrEnum.radioHead.value:File_AddrEnum.radioHead.value+14]  
    elif(item==Clone_TypeEnum.radioInfo):
        item_bytes= allbytes[File_AddrEnum.radioHead.value:File_AddrEnum.radioInfo.value+68]    
    elif(item==Clone_TypeEnum.radioVer):
        item_bytes= allbytes[File_AddrEnum.radioVer.value:File_AddrEnum.radioVer.value+10]         
    elif(item==Clone_TypeEnum.settingData):
        item_bytes= allbytes[File_AddrEnum.settingData.value:File_AddrEnum.settingData.value+100]
    elif(item==Clone_TypeEnum.zoneData):
        item_bytes=  allbytes[File_AddrEnum.zoneData.value:File_AddrEnum.zoneData.value+3202] 
    elif(item==Clone_TypeEnum.channelData):
        item_bytes= allbytes[File_AddrEnum.channelData.value:File_AddrEnum.channelData.value+43136]
    elif(item==Clone_TypeEnum.scanData):
        item_bytes= allbytes[File_AddrEnum.scanData.value:File_AddrEnum.scanData.value+3618]
    elif(item==Clone_TypeEnum.alarmData):
        item_bytes= allbytes[File_AddrEnum.alarmData.value:File_AddrEnum.alarmData.value+258]
    elif(item==Clone_TypeEnum.dTMFData):
        item_bytes= allbytes[File_AddrEnum.dTMFData.value:File_AddrEnum.dTMFData.value+842] 
    elif(item==Clone_TypeEnum.outFactoryData):
        item_bytes= allbytes[File_AddrEnum.outFactoryData.value:File_AddrEnum.outFactoryData.value+2688]
    elif(item==Clone_TypeEnum.vfoScanData):
        item_bytes= allbytes[File_AddrEnum.vfoScanData.value:File_AddrEnum.vfoScanData.value+68] 
    return item_bytes

def read_item_handle_connect_event(allbytes:bytearray,itemBytes:bytes,item):
    if(item==Clone_TypeEnum.radioHead):
        itemlen=min(len(itemBytes),14)
        allbytes[File_AddrEnum.radioHead.value:File_AddrEnum.radioHead.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.radioInfo):
        itemlen=min(len(itemBytes),68)
        allbytes[File_AddrEnum.radioInfo.value:File_AddrEnum.radioInfo.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.radioVer):
        itemlen=min(len(itemBytes),10)
        allbytes[File_AddrEnum.radioVer.value:File_AddrEnum.radioVer.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.settingData):
        itemlen=min(len(itemBytes),100)
        allbytes[File_AddrEnum.settingData.value:File_AddrEnum.settingData.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.zoneData):
        itemlen=min(len(itemBytes),3202)
        allbytes[File_AddrEnum.zoneData.value:File_AddrEnum.zoneData.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.channelData):
        itemlen=min(len(itemBytes),43136)
        allbytes[File_AddrEnum.channelData.value:File_AddrEnum.channelData.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.scanData):
        itemlen=min(len(itemBytes),3618)
        allbytes[File_AddrEnum.scanData.value:File_AddrEnum.scanData.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.alarmData):
        itemlen=min(len(itemBytes),258)
        allbytes[File_AddrEnum.alarmData.value:File_AddrEnum.alarmData.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.dTMFData):
        itemlen=min(len(itemBytes),842)
        allbytes[File_AddrEnum.dTMFData.value:File_AddrEnum.dTMFData.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.outFactoryData):
        itemlen=min(len(itemBytes),2688)
        allbytes[File_AddrEnum.outFactoryData.value:File_AddrEnum.outFactoryData.value+itemlen] = itemBytes[:itemlen]
    elif(item==Clone_TypeEnum.vfoScanData):
        itemlen=min(len(itemBytes),68)
        allbytes[File_AddrEnum.vfoScanData.value:File_AddrEnum.vfoScanData.value+itemlen] = itemBytes[:itemlen]
    return allbytes

def exit_programming_mode(self):
    serial = self.pipe
    try:
        serial.write(Get_ReadItemBytes(111,0,0))
    except:
        raise errors.RadioError("Radio refused to exit programming mode")

def Get_ReadItemBytes( dataType:int,  pageIndex:int,  dataCode:int= 2):
    data_part=b"RDTP\x01\x00\x00\x00\x00\x00\x00\x00\x08\x00"+dataType.to_bytes(1, 'little')+dataCode.to_bytes(1, 'little')+b"\x00\x00\x01\x00"+pageIndex.to_bytes(2, 'little')
    crc=calculate_crc16(data_part,2)
    return data_part+crc+b"\xFF"

def Get_WriteItemBytes(dataType:int, pageIndex:int, pageCount:int, dataBuffer:bytes):
    data_part=b"RDTP\x01\x00\x00\x00\x00\x00\x00\x00"+(len(dataBuffer)+6).to_bytes(2, 'little')+dataType.to_bytes(1, 'little')+b"\x00"+pageIndex.to_bytes(2, 'little')+pageCount.to_bytes(2, 'little')+dataBuffer
    return data_part+calculate_crc16(data_part,2)+b"\xFF"

def get_crc_bytes(buf, start, length):
    cksum = 0x0000
    for i in range(start, start + length):
        value1 = (cksum >> 8)
        value2 = (cksum ^ buf[i]) & 0xFF
        value3 = crc16_tab[value2]
        cksum = value1 ^ value3
    return cksum

def calculate_crc16(byte_array,  result_length)-> int:
    checksum = 0xFFFF
    checksum = get_crc_bytes(byte_array, 0, len(byte_array))

    # tem = checksum % 256
    # result = ((checksum // 256) + tem * 256)&0xFFFF
    crc_bytes = struct.pack("<H", checksum)  # "<H" 表示小端格式的 2 字节整数
    return crc_bytes

def is_int_in_u16_bytes(data: bytes, target: int) -> bool:
    if not 0 < target < 0xFFFF:
        return False
    # 使用 memoryview 避免切片复制，提高效率
    mv = memoryview(data)
    # 每次取 2 字节，并转换为小端 U16
    return any(
        int.from_bytes(mv[i], 'little', signed=False) == target
        for i in range(0, len(data))
        if i <= len(data)  # 防止越界
    )

def _get_memory(self,mem, _mem,ch_index):
    ch_index_dict=get_ch_index(self)
    mem.extra = RadioSettingGroup("Extra", "extra")
    mem.extra.append(RadioSetting("tottime", "TOT[S]", RadioSettingValueList(get_namedict_by_items(TIMEOUTTIMER_LIST), current_index=(_mem.tottime-1))))
    mem.extra.append(RadioSetting("totPermissions", "TX Permissions", RadioSettingValueList(TOTPERSMISSION_LIST, current_index=_mem.totPermissions)))
    mem.extra.append(RadioSetting("rxsqlmode", "Squelch Level", RadioSettingValueList(SQUELCHLEVEL_LIST, current_index=_mem.rxsqlmode)))
    mem.extra.append(RadioSetting("autoscan", "Auto Scan System", RadioSettingValueList(AUTOSCAN_LIST, current_index=_mem.autoscan)))
    mem.extra.append(RadioSetting("alarmlist", "Alarm Sytem", RadioSettingValueList(get_namedict_by_items(ALARM_LIST), current_index=get_item_by_id(ALARM_LIST,_mem.alarmlist))))
    mem.extra.append(RadioSetting("dtmfsignalinglist", "DTMF System", RadioSettingValueList(get_namedict_by_items(DTMFSYSTEM_LIST), current_index=get_item_by_id(DTMFSYSTEM_LIST,_mem.dtmfsignalinglist))))
    mem.extra.append(RadioSetting("offlineorreversal","Talkaround & Reversal",RadioSettingValueList(OFFLINE_REVERSAL_LIST, current_index=_mem.offlineorreversal)))
    mem.extra.append(RadioSetting("vox", "vox", RadioSettingValueBoolean(_mem.vox)))
    mem.extra.append(RadioSetting("companding", "compander", RadioSettingValueBoolean(_mem.companding)))
    mem.extra.append(RadioSetting("scramble", "scramble", RadioSettingValueBoolean(_mem.scramble)))
    
    if ch_index not in ch_index_dict:
        mem.freq=0
        mem.empty = True
        return mem
    mem.freq = int.from_bytes(_mem.rxfreq, byteorder='little') 
    mem.name=bytes(_mem.alias).decode('utf-8').replace("\x00","")
    tx_freq= int.from_bytes(_mem.txfreq, byteorder='little')         
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
        mem.duplex = "off"
    else:
        mem.duplex = mem.freq > tx_freq and "-" or "+"
        mem.offset = abs(mem.freq  - tx_freq)
    mem.mode =BANDWIDEH_LIST[(1 if _mem.bandwidth>=3 else 0)]
    rxtone = txtone = None
    if(_mem.rxctcvaluetype==1):
        tone_value=(_mem.rxctchight<<8|_mem.rxctclowvalue)/10.0
        if tone_value in chirp_common.TONES:  
            rxtone=tone_value
    elif(_mem.rxctcvaluetype==2 or _mem.rxctcvaluetype==3):  
        rxtone=int("%03o" % ((_mem.rxctchight & 0x0F) <<8|_mem.rxctclowvalue& 0xFF))
        # oct_value=int(oct((_mem.rxctchight & 0x0F) <<8|_mem.rxctclowvalue& 0xFF)[2:])  
        # if oct_value in chirp_common.DTCS_CODES:
        #    print("rxtone")  
        #    rxtone=oct_value  
    if(_mem.txctcvaluetype==1):     
        tone_value=(_mem.txctchight<<8|_mem.txctclowvalue)/10.0
        if tone_value in chirp_common.TONES: 
            txtone=tone_value
    elif(_mem.txctcvaluetype==2 or _mem.txctcvaluetype==3):
         txtone=int("%03o" % ((_mem.txctchight & 0x0F) <<8|_mem.txctclowvalue& 0xFF))
        # oct_value=int(oct((_mem.txctchight & 0x0F) <<8|_mem.txctclowvalue& 0xFF)[2:])  
        # if oct_value in chirp_common.DTCS_CODES:
        #     print("txtone")  
        #     txtone=oct_value         
    rx_tone=("" if _mem.rxctcvaluetype==0 else "Tone" if _mem.rxctcvaluetype==1 else "DTCS", rxtone,(_mem.rxctcvaluetype == 0x3) and "R" or "N"  )  
    tx_tone=(("" if _mem.txctcvaluetype==0 else "Tone" if _mem.txctcvaluetype==1 else "DTCS"), txtone, (_mem.txctcvaluetype == 0x3) and "R" or "N")
    print(rx_tone)
    print(tx_tone)
    chirp_common.split_tone_decode(mem, tx_tone, rx_tone)
    
    mem.power =POWER_LEVELS[(1 if _mem.power ==2  else 0)]  

    return mem

def get_model_info(self,model_info):
    # _model_info=self._memobj.radioinfo
    rs_value=RadioSettingValueString(0,20,self.current_model)
    rs_value.set_mutable(False)
    rs=RadioSetting(
            "modelinfo.Machinecode", "Machine Code",
            rs_value)
    model_info.append(rs)
    rs_value=RadioSettingValueString(0,100,"136.00000-174.00000, 400.00000-480.00000")
    rs_value.set_mutable(False)
    rs=RadioSetting(
            "modelinfo.freqrange", "Frequency Range[MHZ]",
            rs_value)
    model_info.append(rs)
    # rs_value=RadioSettingValueString(0,100,"")
    # rs_value.set_mutable(False)
    # rs=RadioSetting(
    #         "modelinfo.HardwareVersion", "Hardware Version",
    #         rs_value)
    # model_info.append(rs)

def get_common_setting(self,common):
    print("获取公共设置")
    _settings = self._memobj.settings
    _zonedata=self._memobj.zonedata
    _zones=self._memobj.zones
    _radioinfo= self._memobj.radioinfo
    opts=["Low","Normal","Strengthen"]
    common.append(
        RadioSetting(
            "settings.micmain", "Mic Main",
            RadioSettingValueList(opts, current_index=_settings.micmain)))
    opts=["Stun WakeUp","Stun TX","Stun TX/RX"]
    common.append(
        RadioSetting(
            "settings.stunmode", "Stun Type",
            RadioSettingValueList(opts, current_index=_settings.stunmode)))
    opts_dict=[{"name": "%s" % (x+1), "id": x} for x in range(0, 10, 1)]
    common.append(get_radiosetting_by_key(self,_settings,"calltone","Call Tone",_settings.calltone,opts_dict))
    common.append(get_radiosetting_by_key(self,_settings,"frestep","Frequency Step",int.from_bytes(struct.pack('<H', _settings.frestep)),Fre_Step_List,set_item_twobytes_callback))
    opts=["OFF","1:1","1:2","1:4"]
    common.append(
        RadioSetting(
            "settings.powersavingmode", "Battery Mode",
            RadioSettingValueList(opts, current_index=_settings.powersavingmode)))
    opts_dict=[{"name": "%ss" % ((x+1)*5), "id": x} for x in range(0, 16, 1)]
    common.append(get_radiosetting_by_key(self,_settings,"powersavingdelaytime","Battery Delay Time",_settings.powersavingdelaytime,opts_dict))
    opts_dict=[{"name": "%s" % x, "id": x}  for x in range(1, 16, 1)]
    common.append(get_radiosetting_by_key(self,_settings,"backlightbrightness","Backlight Brightness",_settings.backlightbrightness,opts_dict))
    
    opts=["Always","5s","10s","15s","20s","25s","30s","1min","2min","3min","4min","5min","15min","30min","45min","1h"]
    common.append(
        RadioSetting(
            "settings.backlighttime", "Backlight Time",
            RadioSettingValueList(opts, current_index=_settings.backlighttime)))
    opts_dict=[{"name": "%s" % x, "id": x} for x in range(1, 16, 1)]
    common.append(get_radiosetting_by_key(self,_settings,"voxthreshold","Vox Level",_settings.voxthreshold,opts_dict))
    opts_dict=[{"name": "%sms" % ((x)*500), "id": x}  for x in range(1, 5, 1)]
    common.append(get_radiosetting_by_key(self,_settings,"voxdelaytime","Vox Delay Time",_settings.voxdelaytime,opts_dict))
    opts_dict = [ {"name": "OFF", "id": 0}  ] + [  {"name": "%ss" % x, "id": x}   for x in range(5, 256, 5)]

    common.append(get_radiosetting_by_key(self,_settings,"menuouttime","Menu Timeout Setting",_settings.menuouttime,opts_dict))
    opts=["Manual","Auto"]
    common.append(
        RadioSetting(
            "settings.autoormanuallock", "KeyLock Mode",
            RadioSettingValueList(opts, current_index=_settings.autoormanuallock)))
    opts=["Frequency","Name","Channel"]
    common.append(
        RadioSetting(
            "settings.chdisplay", "Display Mode",
            RadioSettingValueList(opts, current_index=_settings.chdisplay)))
    opts=["Band A","Band B","Band A & Band B","Band B & Band A"]
    rs=RadioSetting(
            "settings.homeselect", "Band Selection",
            RadioSettingValueList(opts, current_index=get_band_selection(_settings.homeselect,_settings.homeindex)))
    rs.set_apply_callback(set_band_selection,self,_settings,opts,"homeselect","homeindex")
    common.append(rs)
    opts=["Channel","VFO Frequency"]
    common.append(
        RadioSetting(
            "settings.homechtype_1", "Channel Type A",
            RadioSettingValueList(opts, current_index=_settings.homechtype_1)))
    common.append(
        RadioSetting(
            "settings.homechtype_2", "Channel Type B",
            RadioSettingValueList(opts, current_index=_settings.homechtype_2)))
    opts=["Last Active Channel","Designated Channel"] 
    common.append(RadioSetting(
            "settings.poweron_type_1", "Power On A",
            RadioSettingValueList(opts, current_index=_settings.poweron_type_1)))
    common.append(RadioSetting(
            "settings.poweron_type_2", "Power On B",
            RadioSettingValueList(opts, current_index=_settings.poweron_type_2)))
    home_poweron_zone_1=(_settings.homepoweronzone_1_height<<8)|_settings.homepoweronzone_1
    home_poweron_zone_2=(_settings.homepoweronzone_2_height<<8)|_settings.homepoweronzone_2
    ch_dict=get_ch_items(self)
    # zone_dict=[{"name":"All Channel","id":0x0FFF,"chs":ch_dict}]
    # zone_num=int.from_bytes(struct.pack('<H', _zonedata.zonenum))
    # if(zone_num>0):
    #     for i in range(0, zone_num):
    #         zone_index=int.from_bytes(struct.pack('<H', _zonedata.zoneindex[i]))
    #         if(zone_index<64):
    #              zone_item=_zones[zone_index]
    #              zonename=''.join(filter(zone_item.name,NAMECHATSET,12))
    #              zone_dict.append({"name":zonename,"id":zone_index,"chs":[get_ch_index_by_bytes(x) for x in zone_item.chindex]})                 
    # common.append(get_zoneitem_by_key(self,_settings,"homepoweronzone_1","Specify Zone A",home_poweron_zone_1,zone_dict))
    # common.append(get_zoneitem_by_key(self,_settings,"homepoweronzone_2","Specify Zone B",home_poweron_zone_2,zone_dict))
    # ch_dict_1=ch_dict_2=[{"name": item["name"], "id": i} for i, item in enumerate(ch_dict)]
    # if home_poweron_zone_1 != 0x0FFF:
    #     zone_item = next((zone for zone in zone_dict if zone["id"] == home_poweron_zone_1), None)
    #     if zone_item is not None:
    #         ch_dict_1=get_ch_items_by_index(ch_dict,zone_item["chs"]) 
    # if home_poweron_zone_2 != 0x0FFF:
    #   zone_item = next((zone for zone in zone_dict if zone["id"] == home_poweron_zone_1), None)
    #   if zone_item is not None:
    #       print(zone_item)
    #       ch_dict_2=get_ch_items_by_index(ch_dict,zone_item["chs"])      
    # ch_value_1=int.from_bytes(struct.pack('<H',_settings.homepoweronch_1))             
    # common.append(get_radiosetting_by_key(self,_settings,"homepoweronch_1","Specify Channel A",ch_value_1,ch_dict_1,set_item_twobytes_callback))
    # ch_value_2=int.from_bytes(struct.pack('<H',_settings.homepoweronch_2))     
    # common.append(get_radiosetting_by_key(self,_settings,"homepoweronch_2","Specify Channel B",ch_value_2,ch_dict_2,set_item_twobytes_callback))
    
    opts_dict=get_scan_item_list(self)
    common.append(get_radiosetting_by_key(self,_settings,"scanlist","Enable Scan List",_settings.scanlist,opts_dict))
    short_dict=SIDE_KEY_LIST[:12]
    common.append(get_radiosetting_by_key(self,_settings,"tk1_short","TK Short Press",_settings.tk1_short,short_dict))
    common.append(get_radiosetting_by_key(self,_settings,"tk1_long","TK Long Press",_settings.tk1_long,short_dict))
    common.append(get_radiosetting_by_key(self,_settings,"sk1_short","Short Press SK1",_settings.sk1_short,short_dict))
    common.append(get_radiosetting_by_key(self,_settings,"sk1_long","Long Press SK1",_settings.sk1_long,SIDE_KEY_LIST))
    common.append(get_radiosetting_by_key(self,_settings,"sk2_short","Short Press SK2",_settings.sk2_short,short_dict))
    common.append(get_radiosetting_by_key(self,_settings,"sk2_long","Long Press SK2",_settings.sk2_long,SIDE_KEY_LIST))
    opts=["55HZ","120°","180°","240°"]
    common.append(
        RadioSetting(
            "settings.tailsoundeliminationsfre", "CTC Tail Elimination",
            RadioSettingValueList(opts, current_index=_settings.tailsoundeliminationsfre)))
    print("settings.salezone:%d"% _settings.salezone)
    if(_settings.salezone!=2):
        opts=["NOAA-%s" % x for x in range(1, 13, 1)]
        common.append(
            RadioSetting(
                "settings.wxch", "NOAA Channel",
                RadioSettingValueList(opts, current_index=_settings.wxch)))
    opts=["1000HZ","1450HZ","1750HZ","2100HZ"]
    common.append(
        RadioSetting(
            "settings.singletone", "Single Tone",
            RadioSettingValueList(opts, current_index=_settings.singletone)))
    common.append(
        RadioSetting(
            "settings.tailsoundeliminationswitch", "Tail Elimination Switch",
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

def get_dtmf_setting(self,dtmf):
    _dtmf_comm=self._memobj.dtmfcomm   
    opts=["OFF"]+["%ss" % x for x in range(1, 16, 1)]
    dtmf.append(
        RadioSetting(
            "dtmfsetting.autoresettime", "Auto Reset Time",
            RadioSettingValueList(opts, current_index=_dtmf_comm.autoresettime)))
    opts=[{"name":"Stun Tx","id":1},{"name":"Stun TX/RX","id":2}]
    dtmf.append(get_radiosetting_by_key(self,_dtmf_comm,"stunmode","Stun Type",_dtmf_comm.stunmode-1,opts) )
    # RadioSetting(
    #         "dtmfsetting.stunmode", "Stun Type",
    #         RadioSettingValueList(opts, current_index=_dtmf_comm.stunmode-1))
    opts=["300ms","550ms","800ms","1050ms"]
    dtmf.append(
        RadioSetting(
            "dtmfsetting.codedelaytime", "Digit Delay",
            RadioSettingValueList(opts, current_index=_dtmf_comm.codedelaytime)))
    opts=["OFF","BOT","EOT","Both"]
    dtmf.append(
        RadioSetting(
            "dtmfsetting.pttidtype", "PTT ID Type",
            RadioSettingValueList(opts, current_index=_dtmf_comm.pttidtype)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.showani", "Show ANI",
            RadioSettingValueBoolean(_dtmf_comm.showani)))
    dtmf.append(
        RadioSetting(
            "dtmfsetting.sidetone", "Side Tone",
            RadioSettingValueBoolean(_dtmf_comm.sidetone)))
    dtmf.append(RadioSetting("dtmfsetting.callid", "Call Id", RadioSettingValueString(0, 10, ''.join(filter(_dtmf_comm.callid,DTMFCHARSET,10,True)),False,DTMFCHARSET) ))
    dtmf.append(RadioSetting("dtmfsetting.stunid", "Stun Id", RadioSettingValueString(0, 10, ''.join(filter(_dtmf_comm.stunid,DTMFCHARSET,10,True)),False,DTMFCHARSET) ))
    dtmf.append(RadioSetting("dtmfsetting.revive", "Revive Id", RadioSettingValueString(0, 10, ''.join(filter(_dtmf_comm.revive,DTMFCHARSET,10,True)),False,DTMFCHARSET) ))
    dtmf.append(RadioSetting("dtmfsetting.bot", "Bot", RadioSettingValueString(0, 16, ''.join(filter(_dtmf_comm.bot,DTMFCHARSET,16,True)),False,DTMFCHARSET) ))
    dtmf.append(RadioSetting("dtmfsetting.eot", "Eot", RadioSettingValueString(0, 16, ''.join(filter(_dtmf_comm.eot,DTMFCHARSET,16,True)),False,DTMFCHARSET) ))

def get_dtmf_list(self,dtmf_list):
    _dtmf_data=self._memobj.dtmfdata
    _dtmf_list=self._memobj.dtmfs
    dtmf_count=int.from_bytes(struct.pack('<H', _dtmf_data.dtmfnum))
    dtmf_count=4 if dtmf_count>4 else dtmf_count
    print("_dtmf_data.dtmfnum : %d"  % dtmf_count)
    if(dtmf_count<=0):
        return  
    dtmf_list.set_shortname("dtmf list")
    for i in range(0,dtmf_count):
        index=i+1
        dtmf_item =_dtmf_list[i]
        rsg = RadioSettingSubGroup('dtmf_list-%i' % i, 'dtmf_list %i' % (i + 1))
        # rs=RadioSetting(
        #     "dtmfstatus_%s" % index, "Enable",
        #     RadioSettingValueBoolean(1 if dtmf_item.dtmfstatus==1 else 0))
        # rs.set_apply_callback(set_dtmf_list_callback,self,i,"dtmfstatus")
        # rsg.append(rs)
        rs= RadioSetting("dtmflist.name_%s" % index, "DTMF Name", RadioSettingValueString(0, 12, ''.join(filter(dtmf_item.name,NAMECHATSET,12)),False,NAMECHATSET))
        rs.set_apply_callback(set_dtmf_list_callback,self,i,"name")
        rsg.append(rs)
        opts=["%sms" % x for x in range(50, 210, 10)]
        rs=RadioSetting(
            "codelen_%s"% index , "DTMF Code Length" ,
            RadioSettingValueList(opts, current_index=dtmf_item.codelen))
        rs.set_apply_callback(set_dtmf_list_callback,self,i,"codelen")
        rsg.append(rs)
        opts=["None","A","B","C","D","*","#"]
        rs=RadioSetting(
            "groupcode_%s" % index, "Group Code" ,
            RadioSettingValueList(opts, current_index=dtmf_item.groupcode))
        rs.set_apply_callback(set_dtmf_list_callback,self,i,"groupcode")
        rsg.append(rs)
        rs=RadioSetting(
            "EncodingEnable_%s" % index, "IsEncodingEnable" ,
            RadioSettingValueBoolean(dtmf_item.EncodingEnable))
        rs.set_apply_callback(set_dtmf_list_callback,self,i,"EncodingEnable")
        rsg.append(rs)
        rs= RadioSetting(
            "DecodingEnable_%s" % index, "IsDecodingEnable" ,
            RadioSettingValueBoolean(dtmf_item.DecodingEnable))
        rs.set_apply_callback(set_dtmf_list_callback,self,i,"DecodingEnable")
        rsg.append(rs)
        for j in range(1,11):
            rs=RadioSetting("dtmfsetting.fastcall_%d_%s" % (index,j), "FastCall_%s" % j, RadioSettingValueString(0, 16, ''.join(filter(dtmf_item["fastcall%d" % j],DTMFCHARSET,16)),False,DTMFCHARSET) )
            rs.set_apply_callback(set_dtmf_list_callback,self,i,"fastcall%s" % j) 
            rsg.append(rs)
        dtmf_list.append(rsg)    

def get_scan_list(self,scan_list):
    _scan_list=self._memobj.scans
    _scan_data=self._memobj.scandata
    scan_count=int.from_bytes(struct.pack('<H', _scan_data.scannum))
    scan_count= 16 if scan_count>16 else scan_count
    print("_scan_data.scannum : %d"  % scan_count)
    if(scan_count<=0):
        return
    for i in range(0,scan_count):
        index=i+1
        rsg = RadioSettingSubGroup('scan_list-%i' % i, 'scan_list %i' % index)
        _scan_item=_scan_list[i]
        rs=RadioSetting(
            "scanlist.status_%s" % index, "Enable" ,
            RadioSettingValueBoolean(_scan_item.scanstatus))
        rs.set_apply_callback(set_scan_list_callback,self,i,"scanstatus")
        rsg.append(rs)
        rs= RadioSetting("scanlist.name_%s" % index, "Scan Name", RadioSettingValueString(0, 12, ''.join(filter(_scan_item.name,NAMECHATSET,12)),False,NAMECHATSET))
        rs.set_apply_callback(set_scan_list_callback,self,i,"name")
        rsg.append(rs)
        opts=["Carrier","Time","Search"]
        rs=RadioSetting(
            "scanlist.scanmode_%s" % index, "Scan Mode",
            RadioSettingValueList(opts, current_index=_scan_item.scanmode))
        rs.set_apply_callback(set_scan_list_callback,self,i,"scanmode")
        rsg.append(rs)
        opts=["Carrier","CTC/DCS"]
        rs=RadioSetting(
            "scanlist.scancondition_%s" % index, "Scan Condition" ,
            RadioSettingValueList(opts, current_index=_scan_item.scancondition))
        rs.set_apply_callback(set_scan_list_callback,self,i,"scancondition")
        rsg.append(rs)
        opts=["Selected","Last Active Channel","Designated Channel"]
        rs=RadioSetting(
            "scanlist.scantxch_%s" % index, "Designated Transmission Channel",
            RadioSettingValueList(opts, current_index=_scan_item.scantxch))
        rs.set_apply_callback(set_scan_list_callback,self,i,"scantxch")
        rsg.append(rs)
        # filtered_ch_list = get_ch_items(self)
        # rs=RadioSetting(
        #     "scanlist.specifych_%s" % index, "Transmit Channel",
        #     RadioSettingValueList(get_namedict_by_items(filtered_ch_list), current_index=get_ch_index_by_bytes(_scan_item.specifych)-3))
        # rs.set_apply_callback(set_scan_list_callback,self,i,"specifych",filtered_ch_list)
        # rsg.append(rs)
        # priority_ch_list = [{"name":"None","id":0xFFFF}]+filtered_ch_list
        # PriorityCh1_value=_scan_item.PriorityCh1
        # if(PriorityCh1_value==0xFFFF):
        #     PriorityCh1_value=0
        # rs=RadioSetting(
        #     "scanlist.PriorityCh1_%s" % index, "Priority Channel1",
        #     RadioSettingValueList(get_namedict_by_items(priority_ch_list), current_index=get_ch_index_by_bytes(PriorityCh1_value)-2))
        # rs.set_apply_callback(set_scan_list_callback,self,i,"PriorityCh1",priority_ch_list)
        # rsg.append(rs)
        # PriorityCh2_value=_scan_item.PriorityCh2
        # if(PriorityCh2_value==0xFFFF):
        #     PriorityCh2_value=0
        # rs=RadioSetting(
        #     "scanlist.PriorityCh2_%s" % index, "Priority Channel2",
        #     RadioSettingValueList(get_namedict_by_items(priority_ch_list), current_index=get_ch_index_by_bytes(PriorityCh2_value)-2))
        # rs.set_apply_callback(set_scan_list_callback,self,i,"PriorityCh2",priority_ch_list)
        # rsg.append(rs)
        
        opts=["%ss" % (x+1) for x in range(0, 16, 1)]
        rs=RadioSetting(
            "scanlist.hangtime_%s" % index, "Scan Hang Time" ,
            RadioSettingValueList(opts, current_index=_scan_item.hangtime))
        rs.set_apply_callback(set_scan_list_callback,self,i,"hangtime")
        rsg.append(rs)
        rs=RadioSetting(
            "scanlist.talkback_%s" % index, "TalkBackEnable" ,
            RadioSettingValueBoolean(_scan_item.talkback))
        rs.set_apply_callback(set_scan_list_callback,self,i,"talkback")
        rsg.append(rs)
        scan_list.append(rsg)
    
def get_vfo_scan(self,vfoscan):
    _vfo_scan=self._memobj.vfoscans[0]
    
    opts=["Carrier","Time","Search"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.scanmode", "Scan Mode",
            RadioSettingValueList(opts, current_index=_vfo_scan.scanmode)))
    opts=["Carrier","CTC/DCS"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.scancondition", "Scan Conditions",
            RadioSettingValueList(opts, current_index=_vfo_scan.scancondition)))
    
    opts=["%s" % x for x in range(1, 16, 1)]
    vfoscan.append(
        RadioSetting(
            "vfoscan.hangtime", "Scan Hang Time[s]",
            RadioSettingValueList(opts, current_index=_vfo_scan.hangtime)))
    vfoscan.append(
        RadioSetting(
            "vfoscan.talkback", "Talk Back Enable",
            RadioSettingValueBoolean(_vfo_scan.talkback)))
    opts=["Current Frequency","Starting Frequency"]
    vfoscan.append(
        RadioSetting(
            "vfoscan.startcondition", "Start Condition",
            RadioSettingValueList(opts, current_index=_vfo_scan.startcondition)))
    
    freq_start=int.from_bytes(_vfo_scan.vhffreq_start, byteorder='little') /1000000
    vfoscan.append(
        RadioSetting(
            "vfoscan.vhffreq_start", "Start Frequency",
            RadioSettingValueFloat(136,480, freq_start,0.00001,5)))
    
    freq_end=int.from_bytes(_vfo_scan.vhffreq_end, byteorder='little') /1000000
    vfoscan.append(
        RadioSetting(
            "vfoscan.vhffreq_end", "End Frequency",
            RadioSettingValueFloat(136,480, freq_end,0.00001,5)))

def get_alarm_list(self,alarm_list):
    _alarm_list=self._memobj.alarms
    _alarm_data=self._memobj.alarmdata
    alarm_count=int.from_bytes(struct.pack('<H', _alarm_data.alarmnum))
    alarm_count= 8 if alarm_count>8 else alarm_count
    print("_alarm_data.alarmnum : %d"  % alarm_count)
    if(alarm_count<=0):
        return
    for i in range(0,alarm_count):
        index=i+1
        rsg = RadioSettingSubGroup('alarm_list-%i' % i, 'alarm_list %i' % index)
        _alarm_item=_alarm_list[i]
        # rs=RadioSetting(
        #     "alarmlist.status_%s" % index, "Enable",
        #     RadioSettingValueBoolean(_alarm_item.alarmstatus))
        # rs.set_apply_callback(set_alarm_list_callback,self,i,"alarmstatus")
        # rsg.append(rs)
        rs= RadioSetting("alarmlist.name_%s" % index, "Alarm Name", RadioSettingValueString(0, 12, ''.join(filter(_alarm_item.name,NAMECHATSET,12)),False,NAMECHATSET))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"name")
        rsg.append(rs)
        opts=["Siren","Regular","Silent","Silent & w/Voice"]
        rs= RadioSetting("alarmlist.alarmtype_%s" % index, "Alarm Type", RadioSettingValueList(opts, current_index=_alarm_item.alarmtype))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"alarmtype")
        rsg.append(rs)
        opts=["Alarm","w/Call","Alarm & w/Call"]
        rs= RadioSetting("alarmlist.alarmmode_%s" % index, "Alarm Mode", RadioSettingValueList(opts, current_index=_alarm_item.alarmmode))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"alarmmode")
        rsg.append(rs)
        # filtered_ch_list =[{"name":"None","id":0xFFFF}]+ get_ch_items(self)
        # jumpch_value=_alarm_item.jumpch
        # if(jumpch_value==0xFFFF):
        #     jumpch_value=0
        # rs=RadioSetting(
        #     "scanlist.jumpch_%s" % index, "Alarm Revert Channel",
        #     RadioSettingValueList(get_namedict_by_items(filtered_ch_list), current_index=get_ch_index_by_bytes(jumpch_value)-2))
        # rs.set_apply_callback(set_alarm_list_callback,self,i,"jumpch",filtered_ch_list)
        # rsg.append(rs)
        rs=RadioSetting(
            "scanlist.localalarm_%s" % index, "Local Alarm Tone" ,
            RadioSettingValueBoolean(_alarm_item.localalarm))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"localalarm")
        rsg.append(rs)
        opts=["Carrier Wave","CTCSS/DCS"]
        rs= RadioSetting("alarmlist.ctcmode_%s" % index, "Alarm Tone Mode", RadioSettingValueList(opts, current_index=_alarm_item.ctcmode))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"ctcmode")
        rsg.append(rs)
        
        opts=["Infinite"]+["%ss" % x for x in range(5,70 , 5)]
        rs=RadioSetting(
            "alarmlist.alarmcycle_%s" % index, "Alarm Cycle",
            RadioSettingValueList(opts, current_index=_alarm_item.alarmcycle))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"alarmcycle")
        rsg.append(rs)
        opts=["%ss" % x for x in range(10, 170, 10)]
        rs=RadioSetting(
            "alarmlist.alarmtime_%s" % index, "Alarm Duration",
            RadioSettingValueList(opts, current_index=_alarm_item.alarmtime))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"alarmtime")
        rsg.append(rs)
        rs=RadioSetting(
            "alarmlist.txinterval_%s" % index, "Alarm Interval",
            RadioSettingValueList(opts, current_index=_alarm_item.txinterval))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"txinterval")
        rsg.append(rs)
        rs=RadioSetting(
            "alarmlist.mictime_%s" % index, "Alarm Mic Time",
            RadioSettingValueList(opts, current_index=_alarm_item.mictime))
        rs.set_apply_callback(set_alarm_list_callback,self,i,"mictime")
        rsg.append(rs)
        alarm_list.append(rsg)

def get_zone_list(self,zone_list):
    _zone_list=self._memobj.zones
    for i in range(0,64):
        index=i+1
        rsg = RadioSettingSubGroup('zone_list-%i' % i, 'zone_list %i' % index)
        _zone_item=_zone_list[i]
        zone_index_dict = get_zone_index_list(self)
        zone_status=  i in zone_index_dict
        rs=RadioSetting(
            "zonelist.status_%s" % index, "Enable",
            RadioSettingValueBoolean(zone_status))
        rs.set_apply_callback(set_zone_list_callback,self,i,"zonestatus")
        rsg.append(rs)
        rs= RadioSetting("zonelist.name_%s" % index, "Zone Name", RadioSettingValueString(0, 12, ''.join(filter(_zone_item.name,NAMECHATSET,12)),False,NAMECHATSET))
        rs.set_apply_callback(set_zone_list_callback,self,i,"name")
        rsg.append(rs)
        zone_list.append(rsg)

def _set_memory(self, mem, _mem,ch_index):
    print("当前信道信息")
    ch_index_dict=get_ch_index(self)
    rx_freq=get_ch_rxfreq(mem.freq)
    if ch_index not in ch_index_dict and (rx_freq!=0 and rx_freq!=0xFFFFFFFF):
        ch_index_dict.append(ch_index)
        set_ch_index(self,ch_index_dict)
    elif ch_index in ch_index_dict and rx_freq<=0:
        ch_index_dict.remove(ch_index)
        set_ch_index(self,ch_index_dict) 
    _mem.rxfreq=rx_freq.to_bytes(4, byteorder='little', signed=False)
    if(not mem.name.strip()):
        mem.name="CH-%d" % mem.number
    alias_bytes=mem.name.encode('utf-8')[:12].ljust(14, b'\x00')
    setattr(_mem, 'alias', alias_bytes)
    txfrq = rx_freq - mem.offset if mem.duplex=="-" and mem.offset>0 else  rx_freq + mem.offset  if  mem.duplex=="+" and mem.offset>0 else  rx_freq 
    _mem.txfreq=get_ch_txfreq(rx_freq,txfrq).to_bytes(4, byteorder='little', signed=False)
    _mem.bandwidth =(3 if mem.mode=="FM" else 1) 
    if(mem.power in POWER_LEVELS):
        _mem.power=POWER_LEVELS.index(mem.power)   
    else:
        _mem.power=0
    ((txmode, txtone, txpol),
     (rxmode, rxtone, rxpol)) = chirp_common.split_tone_encode(mem)
    if(rxmode=="Tone"):
        _mem.rxctcvaluetype=1
        rxtone_value=int(rxtone*10)
        _mem.rxctchight =(rxtone_value>>8)&0x0F
        _mem.rxctclowvalue =rxtone_value&0xFF
    elif(rxmode=="DTCS"):
        _mem.rxctcvaluetype= (rxpol=="R" and 3 or 2)
        oct_value=int(str(rxtone),8)  
        _mem.rxctchight =(oct_value>>8)&0x0F
        _mem.rxctclowvalue =oct_value&0xFF
    else:
        _mem.rxctcvaluetype=0  
    if(txmode=="Tone"):
        _mem.txctcvaluetype=1
        txtone_value=int(txtone*10)
        _mem.txctchight =(txtone_value>>8)&0x0F
        _mem.txctclowvalue =txtone_value&0xFF
    elif(txmode=="DTCS"):
        _mem.txctcvaluetype=(txpol=="R" and 3 or 2)
        oct_value=int(str(txtone),8)  
        _mem.txctchight =(oct_value>>8)&0x0F
        _mem.txctclowvalue =oct_value&0xFF
    else:
        _mem.txctcvaluetype=0  
    for setting in mem.extra:
        if setting.get_name()=="tottime":
            _mem.tottime =get_item_by_name(TIMEOUTTIMER_LIST,str(setting.value)) 
        elif setting.get_name()=="alarmlist":
            _mem.alarmlist= get_item_by_name(ALARM_LIST,setting.value)
        elif setting.get_name()=="dtmfsignalinglist":
            _mem.dtmfsignalinglist= get_item_by_name(DTMFSYSTEM_LIST,setting.value)
        else:
            setattr(_mem, setting.get_name(), setting.value)
    return _mem

def get_radiosetting_by_key(self,_setting,item_key,item_display_name,item_value,opts_dict,callback=None):
    opts=get_namedict_by_items(opts_dict)
    item=RadioSetting(
           item_key,item_display_name,
            RadioSettingValueList(opts, current_index=get_item_by_id(opts_dict,item_value)))
    item.set_apply_callback(set_item_callback if callback is None else callback,_setting,item_key,opts_dict,self)
    return item

def get_zoneitem_by_key(self,_setting,item_key,item_display_name,item_value,opts_dict,callback=None):
    opts=get_namedict_by_items(opts_dict)
    item=RadioSetting(
           item_key,item_display_name,
            RadioSettingValueList(opts, current_index=get_item_by_id(opts_dict,item_value)))
    item.set_volatile(True)
    item.set_doc('Requires reload of file after changing!')
    item.set_apply_callback(set_poweron_zone_callback if callback is None else callback,self,_setting,item_key,opts_dict)
    return item

def get_namedict_by_items(items):
    return [x["name"] for x in items]

def get_item_by_id(items,value):
    return next(
        (i for i, item in enumerate(items) if item["id"] == value),
        0 
    )

def get_item_name_by_id(items,value):
    return next((item["name"] for item in items if item["id"] == value),"")

def set_poweron_zone_callback(set_item,self,obj,name,items):
    item_value=get_item_by_name(items,set_item.value)
    self._memobj.settings[name]=(item_value&0xFF)
    self._memobj.settings[("%s_height" % name)]=(item_value>>8)&0xF
    # setattr(obj, name, item_value)
        
def set_item_twobytes_callback(setting,obj,item_key,opts,self):  
    item_value=get_item_by_name(opts,setting.value)
    setattr(obj, item_key, (((item_value & 0xFF) << 8) | ((item_value >> 8) & 0xFF))) 
    
def set_item_callback(set_item,obj,name,items,self):
        item_value= get_item_by_name(items,set_item.value)
        setattr(obj, name, item_value)
        
def get_item_by_name(items,name):
    return next(
        (item["id"] for item in items if item["name"] == name),
        items[0]["id"] if items else 0  # 默认值处理
    )

def get_band_selection(band_value,band_index):
    return (3 if band_value>=3  else 1) if band_index >= 1 else (2 if band_value >= 3 else 0) 
  
def get_ch_items(self):
    ch_dict=[]
    _chdata=self._memobj.channeldata
    _chs=self._memobj.channels
    ch_num=int.from_bytes(struct.pack('<H', _chdata.chnum))
    if(ch_num>3):
         for i in range(3, ch_num):
            ch_index=int.from_bytes(struct.pack('<H', _chdata.chindex[i]))
            if(ch_index<259):
                 chname=bytes(_chs[ch_index].alias).decode('utf-8').replace("\x00","")
                 ch_dict.append({"name":chname,"id":ch_index})
    return ch_dict

def get_ch_items_by_index(ch_items,ch_index_dict):
    items=[]
    for i, ch_index in enumerate(ch_index_dict):
        ch_item= next((item for item in ch_items if item["id"] == ch_index), None)
        if(ch_item is not None):
            items.append({"name": ch_item["name"], "id": i})
    print(items)
    return items

def get_ch_index(self):
    ch_dict=[]
    ch_data = self._memobj.channeldata
    ch_num =int.from_bytes(struct.pack('<H', ch_data.chnum))
    for i in range(0, ch_num):
        ch_dict.append(int.from_bytes(struct.pack('<H', ch_data.chindex[i])))  
    return ch_dict

def set_ch_index(self,ch_index):
    if not isinstance(ch_index, list):
        raise TypeError("ch_index must be a list")
    _ch_data=self._memobj.channeldata
    ch_num=len(ch_index)
    if len(_ch_data.chindex) < ch_num:
        raise ValueError("Not enough space in chindex array")
    _ch_data.chnum= ((ch_num & 0xFF) << 8)| ((ch_num >> 8) & 0xFF)
    ch_index.sort()
    for i in range(0, 1027):
        if(i< ch_num):
            _ch_data.chindex[i]= (((ch_index[i] & 0xFF) << 8) | ((ch_index[i] >> 8) & 0xFF))    
        else:
            _ch_data.chindex[i]=0xFFFF 
   
def get_ch_index_by_bytes(ch_bytes):
    return int.from_bytes(struct.pack('<H', ch_bytes))

def get_ch_rxfreq(freq):
    ch_freq=(freq // 10) *10
    if(freq==0):
        return freq
    elif(freq<134000000):
        ch_freq= 134000000
    elif(freq>174000000 and freq<400000000):
        ch_freq= 174000000
    elif(freq>480000000):
        ch_freq= 480000000     
    return  ch_freq

def get_ch_txfreq(rx_freq,tx_freq):
    return rx_freq if(tx_freq<134 or (tx_freq>174 and tx_freq<400) or tx_freq>480) else tx_freq

def get_alarm_item_list(self):
    _alarmdata=self._memobj.alarmdata
    _alarms=self._memobj.alarms
    ALARM_LIST.clear()
    ALARM_LIST.append({"name":"OFF","id":255})
    alarm_num=int.from_bytes(struct.pack('<H', _alarmdata.alarmnum))
    if(alarm_num>0):
        for i in range(0, alarm_num):
            alarm_index=int.from_bytes(struct.pack('<H', _alarmdata.alarmindex[i]))
            if(alarm_index<8):
                 alarm_item=_alarms[alarm_index]
                 alarm_item.alarmstatus=1
                 alarmname=''.join(filter(alarm_item.name,NAMECHATSET,12))
                 ALARM_LIST.append({"name":alarmname,"id":alarm_index}) 

def get_dtmf_item_list(self):
    print("get_dtmf_item_list")
    _dtmfdata=self._memobj.dtmfdata
    _dtmfs=self._memobj.dtmfs
    DTMFSYSTEM_LIST.clear()
    DTMFSYSTEM_LIST.append({"name":"OFF","id":15})
    print("DTMF:")
    print(_dtmfdata.dtmfnum)
    dtmf_num=int.from_bytes(struct.pack('<H', _dtmfdata.dtmfnum))
    if(dtmf_num>0):
        for i in range(0, dtmf_num):
            dtmf_index=int.from_bytes(struct.pack('<H', _dtmfdata.dtmfindex[i]))
            if(dtmf_index<8):
                 dtmf_item=_dtmfs[dtmf_index]
                 dtmf_item.dtmfstatus=1
                 dtmfname=''.join(filter(dtmf_item.name,NAMECHATSET,12))
                 DTMFSYSTEM_LIST.append({"name":dtmfname,"id":dtmf_index}) 
    print(DTMFSYSTEM_LIST)

def get_scan_item_list(self):
    _scandata=self._memobj.scandata
    _scans=self._memobj.scans
    scan_dict=[]
    scan_num=int.from_bytes(struct.pack('<H', _scandata.scannum))
    if(scan_num>0):
        for i in range(0, scan_num):
            scan_index=int.from_bytes(struct.pack('<H', _scandata.scanindex[i]))
            if(scan_index<16):
                 scan_item=_scans[scan_index]
                 scanname=''.join(filter(scan_item.name,NAMECHATSET,12))
                 scan_dict.append({"name":scanname,"id":scan_index})
    return scan_dict

def get_alarm_index_list(self):
    _alarmdata=self._memobj.alarmdata
    alarm_index_dict=[]
    alarm_num=int.from_bytes(struct.pack('<H', _alarmdata.alarmnum))
    if(alarm_num>0):
        for i in range(0, alarm_num):
            alarm_index=int.from_bytes(struct.pack('<H', _alarmdata.alarmindex[i]))
            if(alarm_index<8):
                 alarm_index_dict.append(alarm_index)
    return alarm_index_dict

def get_dtmf_index_list(self):
    _dtmfdata=self._memobj.dtmfdata
    dtmf_index_dict=[]
    dtmf_num=int.from_bytes(struct.pack('<H', _dtmfdata.dtmfnum))
    if(dtmf_num>0):
        for i in range(0, dtmf_num):
            dtmf_index=int.from_bytes(struct.pack('<H', _dtmfdata.dtmfindex[i]))
            if(dtmf_index<4):
                 dtmf_index_dict.append(dtmf_index)
    return dtmf_index_dict

def get_scan_index_list(self):
    _scandata=self._memobj.scandata
    scan_index_dict=[]
    scan_num=int.from_bytes(struct.pack('<H', _scandata.scannum))
    if(scan_num>0):
        for i in range(0, scan_num):
            scan_index=int.from_bytes(struct.pack('<H', _scandata.scanindex[i]))
            if(scan_index<16):
                 scan_index_dict.append(scan_index)
    return scan_index_dict

def get_zone_index_list(self):
    _zonedata=self._memobj.zonedata
    zone_index_dict=[]
    zone_num=int.from_bytes(struct.pack('<H', _zonedata.zonenum))
    if(zone_num>0):
        for i in range(0, zone_num):
            zone_index=int.from_bytes(struct.pack('<H', _zonedata.zoneindex[i]))
            if(zone_index<64):
                 zone_index_dict.append(zone_index)
    return zone_index_dict

def set_alarm_index_list(self,alarm_index_dict):
    _alarmdata=self._memobj.alarmdata
    alarm_count=len(alarm_index_dict)
    _alarmdata.alarmnum= ((alarm_count & 0xFF) << 8) | ((alarm_count >> 8) & 0xFF)
    if(alarm_count>0):
        for i in range(0, 8):
            if(i<alarm_count):
                _alarmdata.alarmindex[i]=(((alarm_index_dict[i] & 0xFF) << 8) | ((alarm_index_dict[i] >> 8) & 0xFF))
            else:
                _alarmdata.alarmindex[i]=0xFFFF
    get_alarm_item_list(self)  # 更新 ALARM_LIST

def set_zone_index_list (self,zone_index_dict):
    _zonedata=self._memobj.zonedata
    zone_count=len(zone_index_dict)
    _zonedata.zonenum= ((zone_count & 0xFF) << 8) | ((zone_count >> 8) & 0xFF)
    if(zone_count>0):
        for i in range(0, 64):
            if(i<zone_count):
                _zonedata.zoneindex[i]=(((zone_index_dict[i] & 0xFF) << 8) | ((zone_index_dict[i] >> 8) & 0xFF))
            else:
                _zonedata.zoneindex[i]=0xFFFF

def set_zone_ch_list(self,zone_index,zone_ch_dict):
    _zone_list= self._memobj.zones
    if(zone_index>=len(_zone_list)):
        raise Exception("Zone index out of range")
    zone_item=_zone_list[zone_index]
    zone_ch_count=len(zone_ch_dict)
    zone_item.chnum= ((zone_ch_count & 0xFF) << 8) | ((zone_ch_count >> 8) & 0xFF)
    if(zone_ch_count>0):
        for i in range(0, 16):
            if(i<zone_ch_count):
                zone_item.chindex[i]=(((zone_ch_dict[i] & 0xFF) << 8) | ((zone_ch_dict[i] >> 8) & 0xFF))
            else:
                zone_item.chindex[i]=0xFFFF                   

def set_dtmf_index_list(self,dtmf_index_dict):
    print("DTMF index list")
    _dtmfdata=self._memobj.dtmfdata
    dtmf_count=len(dtmf_index_dict)
    _dtmfdata.dtmfnum=((dtmf_count & 0xFF) << 8) | ((dtmf_count >> 8) & 0xFF)
    if(dtmf_count>0):
        for i in range(0, dtmf_count):
            if(i<4):
                _dtmfdata.dtmfindex[i]=(((dtmf_index_dict[i] & 0xFF) << 8) | ((dtmf_index_dict[i] >> 8) & 0xFF))
            else:
                raise ValueError("Not enough space in alarmindex array")
    get_dtmf_item_list(self)  # 更新 DTMFSYSTEM_LIST

def set_scan_index_list(self,scan_index_dict):
    _scandata=self._memobj.scandata
    scan_count=len(scan_index_dict)
    scan_num= ((scan_count & 0xFF) << 8) | ((scan_count >> 8) & 0xFF)
    if(scan_count>0):
        for i in range(0, scan_count):
            if(i<16):
                _scandata.scanindex[i]=(((scan_index_dict[i] & 0xFF) << 8) | ((scan_index_dict[i] >> 8) & 0xFF))
            else:
                raise ValueError("Not enough space in scanindex array")

def set_dtmf_list_callback(set_item,self,index,name):
    print(set_item)
    print(index)
    print(name)
    _dtmf_list=self._memobj.dtmfs
    print(_dtmf_list[index][name])
    value=set_item.value
    if(index<len(_dtmf_list)): 
        if(name=="dtmfstatus"):
            dtmf_index_dict=get_dtmf_index_list(self)
            if(value==1 and index not in dtmf_index_dict):
                dtmf_index_dict.append(index)
            elif(value==0 and index in dtmf_index_dict):
                dtmf_index_dict.remove(index)
            set_dtmf_index_list(self,dtmf_index_dict)               
        elif(name=="name"):
           value = filter(value, NAMECHATSET,12,True)
           value=value.ljust(14, '\x00')
        elif(name.startswith("fastcall")):
           value = filter(value, DTMFCHARSET,16,True)
           value=value.ljust(16, '\x00')
        setattr(_dtmf_list[index], name, value)

def set_scan_list_callback(set_item,self,index,name,items=None):
    print(set_item)
    _scan_list=self._memobj.scans
    value=set_item.value
    if(index<len(_scan_list)):
        if(name=="scanstatus"):
            scan_index_dict=get_scan_index_list(self)
            if(value==1 and index not in scan_index_dict):
                scan_index_dict.append(index)
            elif(value==0 and index in scan_index_dict):
                scan_index_dict.remove(index)
            set_scan_index_list(self,scan_index_dict)
        elif(name=="name"):
           value = filter(value, NAMECHATSET,12,True)
           value=value.ljust(14, '\x00')
        elif(name=="specifych" or name=="PriorityCh1" or name=="PriorityCh2") and items is not None: 
            ch_value=get_item_by_name(items,value)
            value=((ch_value&0xFF)<<8)|((ch_value>>8)&0xFF)     
        setattr(_scan_list[index], name, value)               

def set_alarm_list_callback(set_item,self,index,name,items=None):
    print(set_item)
    _alarm_list=self._memobj.alarms
    value=set_item.value
    if(index<len(_alarm_list)):
        if(name=="alarmstatus"):
            alarm_index_dict=get_alarm_index_list(self)
            if(value==1 and index not in alarm_index_dict):
                alarm_index_dict.append(index)
            elif(value==0 and index in alarm_index_dict):
                alarm_index_dict.remove(index)
            set_alarm_index_list(self,alarm_index_dict)
        elif(name=="name"):
           value = filter(value, NAMECHATSET,12,True)
           value=value.ljust(14, '\x00')
        elif(name=="jumpch" ) and items is not None: 
            ch_value=get_item_by_name(items,value)
            value=((ch_value&0xFF)<<8)|((ch_value>>8)&0xFF)     
        setattr(_alarm_list[index], name, value)              

def set_zone_list_callback(set_item,self,index,name,items=None):
    print(set_item)
    _zone_list=self._memobj.zones
    value=set_item.value
    if(index<len(_zone_list)):
        if(name=="zonestatus"):
            zone_index_dict=get_zone_index_list(self)
            if(value==1 and index not in zone_index_dict):
                zone_index_dict.append(index)
            elif(value==0 and index in zone_index_dict):
                zone_index_dict.remove(index)
            set_zone_index_list(self,zone_index_dict)
        elif(name=="name"):
           value = filter(value, NAMECHATSET,12,True)
           value=value.ljust(14, '\x00')
           setattr(_zone_list[index], name, value)

def set_band_selection(set_item,self,obj,opts,home_select_field_name,home_index_field_name):
     value=opts.index(set_item.value)
     if(value==3):
         setattr(obj,home_index_field_name,1)
         setattr(obj,home_select_field_name,3)
     elif(value==2):
         setattr(obj,home_index_field_name,0)
         setattr(obj,home_select_field_name,3)
     elif(value==1):
         setattr(obj,home_index_field_name,1)
         setattr(obj,home_select_field_name,2)
     else:
         setattr(obj,home_index_field_name,0)
         setattr(obj,home_select_field_name,1)

def filter(s,char_set,max_length=10,is_upper=False):
            s_ = ""
            input_len=len(s)
            for i in range(0, min(max_length, input_len)):
                c = str(s[i])
                if is_upper:
                    c=c.upper()
                s_ += (c if c in char_set else "")
            return s_
        
@directory.register
class HA1G(chirp_common.CloneModeRadio):
    """Retevis HA1G"""
    VENDOR = "Retevis"
    MODEL = "HA1G"
    BAUD_RATE = 115200      # 串口波特率（根据电台手册）
    _memsize=0xd868
    page_len=1024
    current_model="HA1G"
    handshakeBytes=Get_HandshakeBytes(MODEL)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.valid_special_chans = sorted(SPECIAL_MEMORIES.keys())
        rf.memory_bounds = (1, 256)  # 频道范围
        rf.has_ctone = True          # 支持 CTCSS
        rf.has_rx_dtcs = True
        rf.has_dtcs = True
        rf.has_cross = True
        rf.has_bank = False          # 不支持频道组
        rf.valid_bands = [(134000000, 174000000),(400000000,480000000)]
        rf.has_tuning_step=False
        rf.has_nostep_tuning=True
        rf.valid_name_length = 12
        rf.valid_tuning_steps = [2.5, 5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0,
                                 50.0, 100.0]
        rf.valid_characters = chirp_common.CHARSET_UPPER_NUMERIC + "".join(c for c in "-/;,._!? *#@$%&+=/<>~(){}]'" if c not in chirp_common.CHARSET_UPPER_NUMERIC) 
        rf.has_settings=True
        rf.valid_modes=BANDWIDEH_LIST
        rf.valid_power_levels=POWER_LEVELS
        rf.has_comment=True
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        return rf
   
    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
        get_dtmf_item_list(self)
        get_alarm_item_list(self)
    
    def sync_in(self):
        print("sync_in")
        try:
            self._mmap = do_download(self)   
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)

    def sync_out(self):
        """Upload to radio"""
        try:
            logging.debug("come in sync_out")
            do_upload(self)
            
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_memory(self, number): 
        print("get_memory：% s" % number)
        mem = chirp_common.Memory()
        ch_index= 0
        if isinstance(number, str) :
            mem.extd_number =number
            ch_index=0 if number=="VFOA" else 1
            mem.number =len(self._memobj.channels) +ch_index+1
        elif  number>len(self._memobj.channels):
            ch_index=0 if number=="VFOA" else 1
        else:
            ch_index=number+2    
            mem.number = number 
        _mem = self._memobj.channels[ch_index] 
        mem= _get_memory(self,mem,_mem,ch_index)
        if(ch_index>2 and ch_index<33):
            mem.immutable=["freq","duplex","offset"]
        if(ch_index>=10 and ch_index<17):
            mem.immutable += ["mode","power"]
        return mem
    
    def set_memory(self, mem):
        print("set_memory")
        ch_index=0
        if mem.number>len(self._memobj.channels):
            ch_index= 0 if mem.extd_number=="VFOA" else 1  
        else:
            ch_index=mem.number+2
        _mem = self._memobj.channels[ch_index]
        _set_memory(self,mem, _mem,ch_index)          
        LOG.debug("Setting %i(%s)" % (mem.number, mem.extd_number))
    
    def get_raw_memory(self, number):
        print(number)
        if isinstance(number, str):
            ch_index=0 if number=="VFOA" else 1
        else:
            ch_index=number+2    
        
        _mem = self._memobj.channels[ch_index]
        return repr(_mem)
    
    def validate_memory(self, mem):
        print("validate_memory")
        print(mem.number)
        ch_number= (0 if mem.extd_number=="VFOA" else 1 ) if mem.number>len(self._memobj.channels)  else mem.number+2
        msgs=super().validate_memory(mem)
        if(self.current_model=="HA1G"):
            _mem = self._memobj.channels[ch_number]
            rx_freq=int.from_bytes(_mem.rxfreq, byteorder='little')
            if(mem.number<=30 and mem.freq !=rx_freq ):
                msgs.append(chirp_common.ValidationWarning('GMRS channels 1-30 freq cannot be modified'))
            if(mem.number<=30 and( mem.offset !=0  or mem.duplex != "")):
                msgs.append(chirp_common.ValidationWarning('GMRS channels 1-30 freq cannot be modified'))
            if((mem.number>=7 and mem.number<14) and mem.mode !="NFM"):
                msgs.append(chirp_common.ValidationWarning('GMRS channels 8-14 Mode cannot be modified'))
            if((mem.number>=7 and mem.number<14) and mem.power !=POWER_LEVELS[0]):
                msgs.append(chirp_common.ValidationWarning('GMRS channels 8-14 power cannot be modified'))    
        return msgs
                   
    def get_settings(self):
        
        ModelInfo = RadioSettingGroup("info", "Model Information")
        common = RadioSettingGroup("basic", "Common Settings")
        scan = RadioSettingGroup("scan", "Scan List")
        dtmf = RadioSettingGroup("dtmfe", "DTMF Settings")
        vfoscan = RadioSettingGroup("vfoscan", "VFO  Scan")
        alarm = RadioSettingGroup("alarm", "Alarm List")
        # zone=RadioSettingGroup("zone", "Zone List")
        setmode = RadioSettings(ModelInfo,common,  dtmf,scan,vfoscan,alarm)
        try:
            get_model_info(self,ModelInfo)
            get_common_setting(self,common)
            get_dtmf_setting(self,dtmf)
            get_dtmf_list(self,dtmf)
            get_scan_list(self,scan)
            get_vfo_scan(self,vfoscan)
            get_alarm_list(self,alarm)
            # get_zone_list(self,zone)
        except Exception as e:
            LOG.exception("Error getting settings: %s", e)
               
        return setmode
        
    def set_settings(self, uisettings):
        print("setting 赋值")
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
                    if(name.startswith("settings.")):
                        name = name[9:]
                        _settings = self._memobj.settings
                        setattr(_settings, name, value)
                    elif(name.startswith("dtmfsetting.")):
                        name = name[12:]
                        _dtmfcomm = self._memobj.dtmfcomm
                        if(name=="callid" or name=="stunid" or name=="revive"):
                            value = filter(value, DTMFCHARSET,10,True)
                            value=value.ljust(10, '\x00')
                        elif(name=="bot" or name=="eot"):
                            value = filter(value, DTMFCHARSET,16,True)
                            value=value.ljust(16, '\x00')
                        setattr(_dtmfcomm, name, value)  
                    elif(name.startswith("vfoscan.")):
                        name = name[8:]
                        _vfo_scan=self._memobj.vfoscans[0]
                        if(name=="vhffreq_start" or name=="vhffreq_end"):
                            value=int(value*1000000).to_bytes(4, byteorder='little', signed=True)  
                        setattr(_vfo_scan, name, value)  
                    LOG.debug("Setting %s: %s", name, value)
            except Exception:
                print("报错")
                LOG.debug(element.get_name())
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
    current_model="HA1UV"

    def validate_memory(self, mem):
       return super().validate_memory(mem)
   
    def get_memory(self, number): 
        mem = chirp_common.Memory()
        ch_index= 0
        if isinstance(number, str) :
            mem.extd_number =number
            ch_index=0 if number=="VFOA" else 1
            mem.number =len(self._memobj.channels) +ch_index+1
        elif  number>len(self._memobj.channels):
            ch_index=0 if number=="VFOA" else 1
        else:
            ch_index=number+2    
            mem.number = number 
        _mem = self._memobj.channels[ch_index]
        return _get_memory(self,mem,_mem,ch_index)
    

