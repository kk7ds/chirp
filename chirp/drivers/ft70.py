# Copyright 2010 Dan Smith <dsmith@danplanet.com>
# Copyright 2017 Nicolas Pike <nick@zbm2.com>
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

import logging

from chirp.drivers import yaesu_clone
from chirp import chirp_common, directory, bitwise
from chirp.settings import RadioSettingGroup, RadioSetting, RadioSettings, \
    RadioSettingValueInteger, RadioSettingValueString, \
    RadioSettingValueList, RadioSettingValueBoolean, \
    InvalidValueError
from textwrap import dedent
import string
LOG = logging.getLogger(__name__)

# Testing

# 37    PAG.ABK     Turn the pager answer back Function ON/OFF
# 38    PAG.CDR     Specify a personal code (receive)
# 39    PAG.CDT     Specify a personal code (transmit)
# 47    RX.MOD      Select the receive mode. Auto FM AM

MEM_SETTINGS_FORMAT = """

// FT-70DE New Model #5329
//
// Communications Mode ? AMS,FM DN,DW   TX vs RX? 
// Mode not currently correctly stored in memories ? - ALL show as FM in memories 
// SKIP test/where stored
// Check storage of steps
// Pager settings ?
// Triple check/ understand _memsize and _block_lengths
// Bank name label name size display 6 store 16? padded with 0xFF same for MYCALL and message 
// CHIRP mode DIG not supported - is there a CHIRP Fusion mode? Auto?
// Check character set
// Supported Modes ?  
// Supported Bands ?
// rf.has_dtcs_polarity = False - think radio supports DTCS polarity
// rf.memory_bounds = (1, 900) - should this be 0? as zero displays as blank
// RPT offsets (stored per band) not included.
// 59 Display radio firmware version info and Radio ID?
// Front Panel settings power etc?
// Banks and VFO?

// Features Required
// Default AMS and Memory name (in mem extras) to enabled. 

// Bugs
// MYCALL and Opening Message errors if not 10 characters
// Values greater than one sometimes stored as whole bytes, these need to be refactored into bit fields
// to prevent accidental overwriting of adjacent values  
// Bank Name length not checked on gui input - but first 6 characters are saved correctly. 
// Extended characters entered as bank names on radio are corrupted in Chirp

// Missing
// 50 SCV.WTH Set the VFO scan frequency range. BAND / ALL - NOT FOUND
// 49 SCM.WTH Set the memory scan frequency range. ALL / BAND - NOT FOUND

// Radio Questions
// Temp unit C/F not saved by radio, always goes back to C ?
// 44 RF SQL Adjusts the RF Squelch threshold level. OFF / S1 - S9? Default is OFF - Based on RF strength - for AM? How 
// is this different from F, Monitor, Dial Squelch?
// Password setting on radio allows letters (DTMF), but letters cannot be entered at the radio's password prompt?  
// 49 SCM.WTH Set the memory scan frequency range. ALL / BAND Defaults to ALL Not Band as stated in the manual. 
    
   #seekto 0x049a;
    struct { 
    u8 unknown0:4,
    squelch:4;              // Squelch F, Monitor, Dial Adjust the Squelch level
    } squelch_settings; 
        
    #seekto 0x04ba;
    struct { 
    u8 unknown:3,
    scan_resume:5;          // 52 SCN.RSM   Configure the scan stop mode settings. 2.0 S - 5.0 S - 10.0 S / BUSY / HOLD
    u8 unknown1:3, 
    dw_resume_interval:5;   // 22 DW RSM    Configure the scan stop mode settings for Dual Receive. 2.0S-10.0S/BUSY/HOLD
    u8 unknown2;          
    u8 unknown3:3,
    apo:5;                  // 02 APO       Set the length of time until the transceiver turns off automatically.
    u8 unknown4:6, 
    gm_ring:2;              // 24 GM RNG    Select the beep option while receiving digital GM info. OFF/IN RNG/ALWAYS 
    u8 temp_cf;             // Placeholder as not found                        
    u8 unknown5;
    } first_settings;   
   
    #seekto 0x04ed;
    struct {   
    u8 unknown1:1,
    unknown2:1,           
    unknown3:1,
    unknown4:1,            
    unknown5:1,          
    unknown6:1, 
    unknown7:1,          
    unknown8:1;          
    } test_bit_field;    
    
    #seekto 0x04c0;
    struct {
    u8 unknown1:5,
    beep_level:3;           // 05 BEP.LVL   Beep volume setting LEVEL1 - LEVEL4 - LEVEL7
    u8 unknown2:6,
    beep_select:2;          // 04 BEEP      Sets the beep sound function OFF / KEY+SC / KEY
    } beep_settings;        
    
    #seekto 0x04ce;                     
    struct {
    u8 lcd_dimmer;                      // 14 DIMMER    LCD Dimmer
    u8 dtmf_delay;                      // 18 DT DLY    DTMF delay    
    u8 unknown0[3];             
    u8 unknown1:4,
    unknown1:4;      
    u8 lamp;                            // 28 LAMP      Set the duration time of the backlight and keys to be lit
    u8 lock;                            // 30 LOCK      Configure the lock mode setting. KEY/DIAL/K+D/PTT/K+P/D+P/ALL
    u8 unknown2_1;
    u8 mic_gain;                        // 31 MCGAIN    Adjust the microphone gain level
    u8 unknown2_3;
    u8 dw_interval;                     // 21 DW INT Set the priority memory ch mon int during Dual RX 0.1S-5.0S-10.0S
    u8 ptt_delay;                       // 42 PTT.DLY   Set the PTT delay time. OFF / 20 MS / 50 MS / 100 MS / 200 MS
    u8 rx_save;                         // 48 RX.SAVE   Set the battery save time. OFF / 0.2 S - 60.0 S    
    u8 scan_restart;                    // 53 SCN.STR   Set the scanning restart time.  0.1 S - 2.0 S - 10.0 S
    u8 unknown2_5;                      
    u8 unknown2_6;          
    u8 unknown4[5];
    u8 tot;                             // 56 TOT       Set the transmission timeout timer 
    u8 unknown5[3];          // 26                                                
    u8 vfo_mode:1,                      // 60 VFO.MOD   Set freq setting range in the VFO mode by DIAL knob. ALL / BAND
    unknown7:1,
    scan_lamp:1,                        // 51 SCN.LMP   Set the scan lamp ON or OFF when scanning stops On/Off
    unknown8:1,
    ars:1,                              // 45 RPT.ARS   Turn the ARS function on/off.
    dtmf_speed:1,                       // 20 DT SPD    Set DTMF speed
    unknown8:1,                        
    dtmf_mode:1;                        // DTMF Mode set from front panel
    u8 busy_led:1,                      // Not Supported ?  
    unknown8_2:1,
    unknown8_3:1,
    bclo:1,                             // 03 BCLO      Turns the busy channel lockout function on/off.
    beep_edge:1,                        // 06 BEP.Edg   Sets the beep sound ON or OFF when a band edge is encountered.    
    unknown8_6:1, 
    unknown8_7:1,
    unknown8_8:1;            // 28
    u8 unknown9_1:1,                   
    unknown9_2:1,
    unknown9_3:1,
    unknown9_4:1,         
    unknown9_5:1,             
    password:1,                         // Placeholder location
    home_rev:1,                         // 26 HOME/REV   Select the function of the [HOME/REV] key.
    moni:1;                             // 32 Mon/T-Call Select the function of the [MONI/T-CALL] switch.
    u8 gm_interval:4,       // 30       // 25 GM INT Set tx interval of digital GM information. OFF / NORMAL / LONG 
    unknown10:4;
    u8 unknown11;          
    u8 unknown12:1,
    unknown12_2:1,
    unknown12_3:1,
    unknown12_4:1,                
    home_vfo:1,                         // 27 HOME->VFO  Turn transfer VFO to the Home channel ON or OFF.
    unknown12_6:1, 
    unknown12_7:1,
    dw_rt:1;                // 32       // 23 DW RVT Turn "Priority Channel Revert" feature ON or OFF during Dual Rx.
    u8 unknown33;
    u8 unknown34;
    u8 unknown35;
    u8 unknown36;
    u8 unknown37;
    u8 unknown38; 
    u8 unknown39;
    u8 unknown40;
    u8 unknown41;
    u8 unknown42;
    u8 unknown43;
    u8 unknown44;
    u8 unknown45;
    u8 prog_key1;           // P1 Set Mode Items to the Programmable Key
    u8 prog_key2;           // P2 Set Mode Items to the Programmable Key
    u8 unknown48;
    u8 unknown49;
    u8 unknown50;                      
    } scan_settings;    
    
    #seekto 0x064b;  
    struct {
    u8 unknown1:1,
    unknown2:1,
    unknown3:1,
    unknown4:1,
    vfo_scan_width:1,       // Placeholder as not found - 50 SCV.WTH Set the VFO scan frequency range. BAND / ALL 
    memory_scan_width:1,    // Placeholder as not found - 49 SCM.WTH Set the memory scan frequency range. ALL / BAND 
    unknown7:1,
    unknown8:1;
    } scan_settings_1;
    
    #seekto 0x06B6;  
    struct {
    u8 unknown1:3,
    volume:5;               // # VOL and Dial  Adjust the volume level
    } scan_settings_2;       
        
    #seekto 0x0690;         // Memory or VFO Settings Map?
    struct {
    u8 unknown[48];         // Array cannot be 64 elements!
    u8 unknown1[16];        // Exception: Not implemented for chirp.bitwise.structDataElement       
    } vfo_info_1;
    
    #seekto 0x0710;         // Backup Memory or VFO Settings Map?
    struct {
    u8 unknown[48];
    u8 unknown1[16];
    } vfo_backup_info_1;      
   
    #seekto 0x047e;
    struct {
    u8 unknown1;
    u8 flag;
    u16 unknown2;
    struct {
    char padded_string[6];              // 36 OPN.MSG   Select MSG then key vm to edit it
    } message;
    } opening_message;                  // 36 OPN.MSG   Select the Opening Message when transceiver is ON. OFF/MSG/DC    
 
    #seekto 0x094a;                     // DTMF Memories
    struct {
    u8 memory[16];
    } dtmf[10];    
    
    #seekto 0x154a;                     
    struct {
    u16 channel[100];
    } bank_members[24];
    
    #seekto 0x54a;
    struct {
    u16 in_use;
    } bank_used[24];
    
    #seekto 0x0EFE;
    struct {
    u8 unknown[2];
    u8 name[6];
    u8 unknown1[10];
    } bank_info[24];
        
    #seekto 0xCF30;
    struct {
    u8 unknown0;
    u8 unknown1;
    u8 unknown2;
    u8 unknown3;
    u8 unknown4;
    u8 unknown5;
    u8 unknown6;
    u8 digital_popup;                   // 15 DIG.POP   Call sign display pop up time                
    } digital_settings_more;
   
    #seekto 0xCF7C;
    struct {
    u8 unknown0:6,
    ams_tx_mode:2;                      // AMS TX Mode  Short Press AMS button AMS TX Mode
    u8 unknown1;
    u8 unknown2:7,
    standby_beep:1;                     // 07 BEP.STB   Standby Beep in the digital C4FM mode. On/Off
    u8 unknown3; 
    u8 unknown4:6,
    gm_ring:2;                          // 24 GM RNG Select beep option while rx digital GM info. OFF/IN RNG/ALWAYS
    u8 unknown5;
    u8 rx_dg_id;                        // RX DG-ID     Long Press Mode Key, Mode Key to select, Dial
    u8 tx_dg_id;                        // TX DG-ID     Long Press Mode Key, Dial                  
    u8 unknown6:7,
    vw_mode:1;                          // 16 DIG VW    Turn the VW mode selection ON or OFF
    u8 unknown7;
    } digital_settings;
    
    // ^^^ All above referenced U8's have been refactored to minimum number of bits.
    
    """

MEM_FORMAT = """
    #seekto 0x2D4A;
    struct {                            // 32 Bytes per memory entry
    u8 display_tag:1,                   // 0 Display Freq, 1 Display Name
    unknown0:1,                         // Mode if AMS not selected???????? 
    deviation:1,                        // 0 Full deviation (Wide), 1 Half deviation (Narrow)
    clock_shift:1,                      // 0 None, 1 CPU clock shifted
    unknown1:4;                                                                         // 1
    u8 mode:2,                          // FM,AM,WFM only? - check
    duplex:2,                           // Works
    tune_step:4;                        // Works - check all steps? 7 = Auto            // 1
    bbcd freq[3];                       // Works                                        // 3
    u8 power:2,                         // Works
    unknown2:1,                         // 0 FM, 1 Digital - If AMS off     
    ams:1,                              // 0 AMS off, 1 AMS on ?        
    tone_mode:4;                        // Works                                        // 1
    u8 charsetbits[2];                                                                  // 2    
    char label[6];                      // Works - Can only input 6 on screen           // 6
    char unknown7[10];                  // Rest of label ???                            // 10    
    bbcd offset[3];                     // Works                                        // 3
    u8 unknown5:2,
    tone:6;                             // Works                                       // 1
    u8 unknown6:1,
    dcs:7;                              // Works                                        // 1
    u8 unknown9;
    u8 ams_on_dn_vw_fm:2,               // AMS DN, AMS VW, AMS FM  
    unknown8_3:1,
    unknown8_4:1,
    unknown8_5:1,
    unknown8_6:1,
    unknown8_7:1,
    unknown8_8:1;                   
    u8 unknown10;                                                             
    } memory[%d];                        // DN, VW, FM, AM 
                                        // AMS DN, AMS VW, AMS FM  
    
    #seekto 0x280A;
    struct {
    u8 nosubvfo:1,
    unknown:3,
    pskip:1,                            // PSkip (Select?)
    skip:1,                             // Skip memory during scan
    used:1,                             // Memory used 
    valid:1;                            // Aways 1?
    } flag[%d];
    """

MEM_CALLSIGN_FORMAT = """
#seekto 0x0ced0;
    struct {
    char callsign[10];              // 63 MYCALL    Set the call sign. (up to 10 characters)
    u16 charset;                    // character set ID
    } my_call;
    """

MEM_CHECKSUM_FORMAT = """
    #seekto 0xFECA;
    u8 checksum;
    """

TMODES = ["", "Tone", "TSQL", "DTCS"]
DUPLEX = ["", "-", "+", "split"]

MODES = ["FM", "AM"]

STEPS = [0, 5, 6.25, 10, 12.5, 15, 20, 25, 50, 100]  # 0 = auto
RFSQUELCH = ["OFF", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]

SKIPS = ["", "S", "P"]
FT70_DTMF_CHARS = list("0123456789ABCDEF-")

CHARSET = ["%i" % int(x) for x in range(0, 10)] + \
          [chr(x) for x in range(ord("A"), ord("Z") + 1)] + \
          [" ", ] + \
          [chr(x) for x in range(ord("a"), ord("z") + 1)] + \
          list(".,:;*#_-/&()@!?^ ") + list("\x00" * 100)

POWER_LEVELS = [chirp_common.PowerLevel("Hi", watts=5.00),
                chirp_common.PowerLevel("Mid", watts=2.00),
                chirp_common.PowerLevel("Low", watts=.50)]


class FT70Bank(chirp_common.NamedBank):
    """A FT70 bank"""

    def get_name(self):
        _bank = self._model._radio._memobj.bank_info[self.index]
        name = ""
        for i in _bank.name:
            if i == 0xff:
                break
            name += chr(i & 0xFF)
        return name.rstrip()

    def set_name(self, name):
        _bank = self._model._radio._memobj.bank_info[self.index]
        _bank.name = [ord(x) for x in name.ljust(6, chr(0xFF))[:6]]


class FT70BankModel(chirp_common.BankModel):
    """A FT70 bank model"""

    def __init__(self, radio, name='Banks'):
        super(FT70BankModel, self).__init__(radio, name)

        _banks = self._radio._memobj.bank_info
        self._bank_mappings = []
        for index, _bank in enumerate(_banks):
            bank = FT70Bank(self, "%i" % index, "BANK-%i" % index)
            bank.index = index
            self._bank_mappings.append(bank)

    def get_num_mappings(self):
        return len(self._bank_mappings)

    def get_mappings(self):
        return self._bank_mappings

    def _channel_numbers_in_bank(self, bank):
        _bank_used = self._radio._memobj.bank_used[bank.index]
        if _bank_used.in_use == 0xFFFF:
            return set()

        _members = self._radio._memobj.bank_members[bank.index]
        return set([int(ch) + 1 for ch in _members.channel if ch != 0xFFFF])

    def _update_bank_with_channel_numbers(self, bank, channels_in_bank):
        _members = self._radio._memobj.bank_members[bank.index]
        if len(channels_in_bank) > len(_members.channel):
            raise Exception("Too many entries in bank %d" % bank.index)

        empty = 0
        for index, channel_number in enumerate(sorted(channels_in_bank)):
            _members.channel[index] = channel_number - 1
            empty = index + 1
        for index in range(empty, len(_members.channel)):
            _members.channel[index] = 0xFFFF

    def add_memory_to_mapping(self, memory, bank):
        channels_in_bank = self._channel_numbers_in_bank(bank)
        channels_in_bank.add(memory.number)
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        _bank_used = self._radio._memobj.bank_used[bank.index]
        _bank_used.in_use = 0x06

    def remove_memory_from_mapping(self, memory, bank):
        channels_in_bank = self._channel_numbers_in_bank(bank)
        try:
            channels_in_bank.remove(memory.number)
        except KeyError:
            raise Exception("Memory %i is not in bank %s. Cannot remove" %
                            (memory.number, bank))
        self._update_bank_with_channel_numbers(bank, channels_in_bank)

        if not channels_in_bank:
            _bank_used = self._radio._memobj.bank_used[bank.index]
            _bank_used.in_use = 0xFFFF

    def get_mapping_memories(self, bank):
        memories = []
        for channel in self._channel_numbers_in_bank(bank):
            memories.append(self._radio.get_memory(channel))

        return memories

    def get_memory_mappings(self, memory):
        banks = []
        for bank in self.get_mappings():
            if memory.number in self._channel_numbers_in_bank(bank):
                banks.append(bank)

        return banks


@directory.register
class FT70Radio(yaesu_clone.YaesuCloneModeRadio):
    """Yaesu FT-70DE"""
    BAUD_RATE = 38400
    VENDOR = "Yaesu"
    MODEL = "FT-70D"

    _model = "AH51G"

    _memsize = 65227  # 65227 read from dump
    _block_lengths = [10, 65217]
    _block_size = 32
    _mem_params = (900,  # size of memories array
                   900,  # size of flags array
                   )

    _has_vibrate = False
    _has_af_dual = True

    _BEEP_SELECT = ("Off", "Key+Scan", "Key")
    _OPENING_MESSAGE = ("Off", "DC", "Message")
    _MIC_GAIN = ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5", "Level 6", "Level 7", "Level 8", "Level 9")
    _AMS_TX_MODE = ("TX Auto", "TX DIGITAL", "TX FM")
    _VW_MODE = ("On", "Off")
    _DIG_POP_UP = ("Off", "2sec", "4sec", "6sec", "8sec", "10sec", "20sec", "30sec", "60sec", "Continuous")
    _STANDBY_BEEP = ("On", "Off")
    _SCAN_RESUME = ["%.1fs" % (0.5 * x) for x in range(4, 21)] + \
                   ["Busy", "Hold"]
    _SCAN_RESTART = ["%.1fs" % (0.1 * x) for x in range(1, 10)] + \
                    ["%.1fs" % (0.5 * x) for x in range(2, 21)]
    _LAMP_KEY = ["Key %d sec" % x
                 for x in range(2, 11)] + ["Continuous", "OFF"]
    _LCD_DIMMER = ["Level %d" % x for x in range(1, 7)]
    _TOT_TIME = ["Off"] + ["%.1f min" % (0.5 * x) for x in range(1, 21)]
    _OFF_ON = ("Off", "On")
    _ON_OFF = ("On", "Off")
    _DTMF_MODE = ("Manual", "Auto")
    _DTMF_SPEED = ("50ms", "100ms")
    _DTMF_DELAY = ("50ms", "250ms", "450ms", "750ms", "1000ms")
    _TEMP_CF = ("Centigrade", "Fahrenheit")
    _APO_SELECT = ("Off", "0.5H", "1.0H", "1.5H", "2.0H", "2.5H", "3.0H", "3.5H", "4.0H", "4.5H", "5.0H",
                   "5.5H", "6.0H", "6.5H", "7.0H", "7.5H", "8.0H", "8.5H", "9.0H", "9.5H", "10.0H", "10.5H",
                   "11.0H", "11.5H", "12.0H")
    _MONI_TCALL = ("Monitor", "Tone-CALL")
    _HOME_REV = ("Home", "Reverse")
    _LOCK = ("KEY", "DIAL", "Key+Dial", "PTT", "Key+PTT", "Dial+PTT", "ALL")
    _PTT_DELAY = ("Off", "20 MS", "50 MS", "100 MS", "200 MS")
    _BEEP_LEVEL = ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5", "Level 6", "Level 7")
    _SET_MODE = ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5", "Level 6", "Level 7")
    _RX_SAVE = ("OFF", "0.2s", ".3s", ".4s", ".5s", ".6s", ".7s", ".8s", ".9s", "1.0s", "1.5s",
                "2.0s", "2.5s", "3.0s", "3.5s", "4.0s", "4.5s", "5.0s", "5.5s", "6.0s", "6.5s", "7.0s",
                "7.5s", "8.0s", "8.5s", "9.0s", "10.0s", "15s", "20s", "25s", "30s", "35s", "40s", "45s", "50s", "55s",
                "60s")
    _VFO_MODE = ("ALL", "BAND")
    _VFO_SCAN_MODE = ("BAND", "ALL")
    _MEMORY_SCAN_MODE = ("BAND", "ALL")

    _VOLUME = ["Level %d" % x for x in range(0, 32)]
    _SQUELCH = ["Level %d" % x for x in range(0, 16)]

    _DG_ID = ["%d" % x for x in range(0, 100)]
    _GM_RING = ("OFF", "IN RING", "AlWAYS")
    _GM_INTERVAL = ("LONG", "NORMAL", "OFF")

    _MYCALL_CHR_SET = list(string.ascii_uppercase) + list(string.digits) + ['-','/' ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()

        rp.pre_download = _(dedent("""\
            1. Turn radio on.
            2. Connect cable to DATA terminal.
            3. Unclip battery.
            4. Press and hold in the [AMS] key and power key while clipping the battery back in 
            ("ADMS" will appear on the display).
            5. <b>After clicking OK</b>, press the [BAND] key."""
                                   ))
        rp.pre_upload = _(dedent("""\
            1. Turn radio on.
            2. Connect cable to DATA terminal.
            3. Unclip battery.
            4. Press and hold in the [AMS] key and power key while clipping the battery back in 
            ("ADMS" will appear on the display).
            5. Press the [MODE] key ("-WAIT-" will appear on the LCD). <b>Then click OK</b>"""))
        return rp

    def process_mmap(self):

        mem_format = MEM_SETTINGS_FORMAT + MEM_FORMAT + MEM_CALLSIGN_FORMAT + MEM_CHECKSUM_FORMAT

        self._memobj = bitwise.parse(mem_format % self._mem_params, self._mmap)

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_dtcs_polarity = False
        rf.valid_modes = list(MODES)
        rf.valid_tmodes = list(TMODES)
        rf.valid_duplexes = list(DUPLEX)
        rf.valid_tuning_steps = list(STEPS)
        rf.valid_bands = [(500000, 999900000)]
        rf.valid_skips = SKIPS
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_characters = "".join(CHARSET)
        rf.valid_name_length = 6
        rf.memory_bounds = (1, 900)
        rf.can_odd_split = True
        rf.has_ctone = False
        rf.has_bank_names = True
        rf.has_settings = True
        return rf

    def get_raw_memory(self, number):
        return "\n".join([repr(self._memobj.memory[number - 1]),
                          repr(self._memobj.flag[number - 1])])

    def _checksums(self):
        return [yaesu_clone.YaesuChecksum(0x0000, 0xFEC9)]  # The whole file -2 bytes

    @staticmethod
    def _add_ff_pad(val, length):
        return val.ljust(length, "\xFF")[:length]

    @classmethod
    def _strip_ff_pads(cls, messages):
        result = []
        for msg_text in messages:
            result.append(str(msg_text).rstrip("\xFF"))
        return result

    def get_memory(self, number):
        flag = self._memobj.flag[number - 1]
        _mem = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number
        if not flag.used:
            mem.empty = True
        if not flag.valid:
            mem.empty = True
            return mem
        mem.freq = chirp_common.fix_rounded_step(int(_mem.freq) * 1000)
        mem.offset = int(_mem.offset) * 1000
        mem.rtone = mem.ctone = chirp_common.TONES[_mem.tone]
        self._get_tmode(mem, _mem)
        mem.duplex = DUPLEX[_mem.duplex]
        if mem.duplex == "split":
            mem.offset = chirp_common.fix_rounded_step(mem.offset)
        mem.mode = self._decode_mode(_mem)
        mem.dtcs = chirp_common.DTCS_CODES[_mem.dcs]
        mem.tuning_step = STEPS[_mem.tune_step]
        mem.power = self._decode_power_level(_mem)
        mem.skip = flag.pskip and "P" or flag.skip and "S" or ""
        mem.name = self._decode_label(_mem)

        return mem

    def _decode_label(self, mem):
        return str(mem.label).rstrip("\xFF")

    def _encode_label(self, mem):
        return self._add_ff_pad(mem.name.rstrip(), 6)

    def _encode_charsetbits(self, mem):
        # We only speak english here in chirpville
        return [0x00, 0x00]

    def _decode_power_level(self, mem):  # 3 High 2 Mid 1 Low
        return POWER_LEVELS[3 - mem.power]

    def _encode_power_level(self, mem):
        return 3 - POWER_LEVELS.index(mem.power)

    def _decode_mode(self, mem):
        return MODES[mem.mode]

    def _encode_mode(self, mem):
        return MODES.index(mem.mode)

    def _get_tmode(self, mem, _mem):
        mem.tmode = TMODES[_mem.tone_mode]

    def _set_tmode(self, _mem, mem):
        _mem.tone_mode = TMODES.index(mem.tmode)

    def _set_mode(self, _mem, mem):
        _mem.mode = self._encode_mode(mem)

    def _debank(self, mem):
        bm = self.get_bank_model()
        for bank in bm.get_memory_mappings(mem):
            bm.remove_memory_from_mapping(mem, bank)

    def set_memory(self, mem):
        _mem = self._memobj.memory[mem.number - 1]
        flag = self._memobj.flag[mem.number - 1]

        self._debank(mem)

        if not mem.empty and not flag.valid:
            self._wipe_memory(_mem)

        if mem.empty and flag.valid and not flag.used:
            flag.valid = False
            return
        flag.used = not mem.empty
        flag.valid = flag.used

        if mem.empty:
            return

        if mem.freq < 30000000 or \
                (mem.freq > 88000000 and mem.freq < 108000000) or \
                mem.freq > 580000000:
            flag.nosubvfo = True  # Masked from VFO B
        else:
            flag.nosubvfo = False  # Available in both VFOs

        _mem.freq = int(mem.freq / 1000)
        _mem.offset = int(mem.offset / 1000)
        _mem.tone = chirp_common.TONES.index(mem.rtone)
        self._set_tmode(_mem, mem)
        _mem.duplex = DUPLEX.index(mem.duplex)
        self._set_mode(_mem, mem)
        _mem.dcs = chirp_common.DTCS_CODES.index(mem.dtcs)
        _mem.tune_step = STEPS.index(mem.tuning_step)

        if mem.power:
            _mem.power = self._encode_power_level(mem)
        else:
            _mem.power = 3  # Set 3 - High power as the default

        _mem.label = self._encode_label(mem)
        charsetbits = self._encode_charsetbits(mem)
        _mem.charsetbits[0], _mem.charsetbits[1] = charsetbits

        flag.skip = mem.skip == "S"
        flag.pskip = mem.skip == "P"

        _mem.display_tag = 1    # Always Display Memory Name (For the moment..)

    @classmethod
    def _wipe_memory(cls, mem):
        mem.set_raw("\x00" * (mem.size() / 8))
        mem.unknown1 = 0x05

    def get_bank_model(self):
        return FT70BankModel(self)

    def _get_dtmf_settings(self):
        menu = RadioSettingGroup("dtmf_settings", "DTMF")
        dtmf = self._memobj.scan_settings

        val = RadioSettingValueList(
            self._DTMF_MODE,
            self._DTMF_MODE[dtmf.dtmf_mode])
        rs = RadioSetting("scan_settings.dtmf_mode", "DTMF Mode", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._DTMF_DELAY,
            self._DTMF_DELAY[dtmf.dtmf_delay])
        rs = RadioSetting(
            "scan_settings.dtmf_delay", "DTMF Delay", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._DTMF_SPEED,
            self._DTMF_SPEED[dtmf.dtmf_speed])
        rs = RadioSetting(
            "scan_settings.dtmf_speed", "DTMF Speed", val)
        menu.append(rs)

        for i in range(10):

            name = "dtmf_%02d" % (i + 1)
            if i == 9:
                name = "dtmf_%02d" % 0

            dtmfsetting = self._memobj.dtmf[i]
            dtmfstr = ""
            for c in dtmfsetting.memory:
                if c == 0xFF:
                    break
                if c < len(FT70_DTMF_CHARS):
                    dtmfstr += FT70_DTMF_CHARS[c]
            dtmfentry = RadioSettingValueString(0, 16, dtmfstr)
            dtmfentry.set_charset(
                FT70_DTMF_CHARS + list("abcdef "))  # Allow input in lowercase, space ? validation fails otherwise
            rs = RadioSetting(name, name.upper(), dtmfentry)
            rs.set_apply_callback(self.apply_dtmf, i)
            menu.append(rs)

        return menu

    def _get_display_settings(self):
        menu = RadioSettingGroup("display_settings", "Display")
        scan_settings = self._memobj.scan_settings

        val = RadioSettingValueList(
            self._LAMP_KEY,
            self._LAMP_KEY[scan_settings.lamp])
        rs = RadioSetting("scan_settings.lamp", "Lamp", val)
        menu.append(rs)

        val = RadioSettingValueList(
            self._LCD_DIMMER,
            self._LCD_DIMMER[scan_settings.lcd_dimmer])
        rs = RadioSetting("scan_settings.lcd_dimmer", "LCD Dimmer", val)
        menu.append(rs)

        opening_message = self._memobj.opening_message
        val = RadioSettingValueList(
            self._OPENING_MESSAGE,
            self._OPENING_MESSAGE[opening_message.flag])
        rs = RadioSetting("opening_message.flag", "Opening Msg Mode", val)
        menu.append(rs)

        return menu

    def _get_config_settings(self):
        menu = RadioSettingGroup("config_settings", "Config")
        scan_settings = self._memobj.scan_settings

        # 02 APO    Set the length of time until the transceiver turns off automatically.

        first_settings = self._memobj.first_settings
        val = RadioSettingValueList(
            self._APO_SELECT,
            self._APO_SELECT[first_settings.apo])
        rs = RadioSetting("first_settings.apo", "APO", val)
        menu.append(rs)

        # 03 BCLO   Turns the busy channel lockout function on/off.

        val = RadioSettingValueList(
            self._OFF_ON,
            self._OFF_ON[scan_settings.bclo])
        rs = RadioSetting("scan_settings.bclo", "Busy Channel Lockout", val)
        menu.append(rs)

        # 04 BEEP   Sets the beep sound function.

        beep_settings = self._memobj.beep_settings
        val = RadioSettingValueList(
            self._BEEP_SELECT,
            self._BEEP_SELECT[beep_settings.beep_select])
        rs = RadioSetting("beep_settings.beep_select", "Beep", val)
        menu.append(rs)

        # 05 BEP.LVL    Beep volume setting LEVEL1 - LEVEL4 - LEVEL7

        val = RadioSettingValueList(
            self._BEEP_LEVEL,
            self._BEEP_LEVEL[beep_settings.beep_level])
        rs = RadioSetting("beep_settings", "Beep Level", val)
        menu.append(rs)

        # 06 BEP.Edg    Sets the beep sound ON or OFF when a band edge is encountered.

        val = RadioSettingValueList(
            self._OFF_ON,
            self._OFF_ON[scan_settings.beep_edge])
        rs = RadioSetting("scan_settings.beep_edge", "Beep Band Edge", val)
        menu.append(rs)

        # 10 Bsy.LED    Turn the MODE/STATUS Indicator ON or OFF while receiving signals.

        val = RadioSettingValueList(
            self._ON_OFF,
            self._ON_OFF[scan_settings.busy_led])
        rs = RadioSetting("scan_settings.busy_led", "Busy LED", val)
        menu.append(rs)

        # 26 HOME/REV   Select the function of the [HOME/REV] key.

        val = RadioSettingValueList(
            self._HOME_REV,
            self._HOME_REV[scan_settings.home_rev])
        rs = RadioSetting("scan_settings.home_rev", "HOME/REV", val)
        menu.append(rs)

        # 27 HOME->VFO  Turn transfer VFO to the Home channel ON or OFF.

        val = RadioSettingValueList(
            self._OFF_ON,
            self._OFF_ON[scan_settings.home_vfo])
        rs = RadioSetting("scan_settings.home_vfo", "Home->VFO", val)
        menu.append(rs)

        # 30 LOCK       Configure the lock mode setting. KEY / DIAL / K+D / PTT / K+P / D+P / ALL

        val = RadioSettingValueList(
            self._LOCK,
            self._LOCK[scan_settings.lock])
        rs = RadioSetting("scan_settings.lock", "Lock Mode", val)
        menu.append(rs)

        # 32 Mon/T-Call Select the function of the [MONI/T-CALL] switch.

        val = RadioSettingValueList(
            self._MONI_TCALL,
            self._MONI_TCALL[scan_settings.moni])
        rs = RadioSetting("scan_settings.moni", "MONI/T-CALL", val)
        menu.append(rs)

        # 42 PTT.DLY    Set the PTT delay time. OFF / 20 MS / 50 MS / 100 MS / 200 MS

        val = RadioSettingValueList(
            self._PTT_DELAY,
            self._PTT_DELAY[scan_settings.ptt_delay])
        rs = RadioSetting("scan_settings.ptt_delay", "PTT Delay", val)
        menu.append(rs)

        # 45 RPT.ARS    Turn the ARS function on/off.

        val = RadioSettingValueList(
            self._OFF_ON,
            self._OFF_ON[scan_settings.ars])
        rs = RadioSetting("scan_settings.ars", "ARS", val)
        menu.append(rs)

        # 48 RX.SAVE    Set the battery save time. OFF / 0.2 S - 60.0 S

        val = RadioSettingValueList(
            self._RX_SAVE,
            self._RX_SAVE[scan_settings.rx_save])
        rs = RadioSetting("scan_settings.rx_save", "RX SAVE", val)
        menu.append(rs)

        # 60 VFO.MOD    Set the frequency setting range in the VFO mode by DIAL knob. ALL / BAND

        val = RadioSettingValueList(
            self._VFO_MODE,
            self._VFO_MODE[scan_settings.vfo_mode])
        rs = RadioSetting("scan_settings.vfo_mode", "VFO MODE", val)
        menu.append(rs)

        # 56 TOT        Set the timeout timer.

        val = RadioSettingValueList(
            self._TOT_TIME,
            self._TOT_TIME[scan_settings.tot])
        rs = RadioSetting("scan_settings.tot", "Transmit Timeout (TOT)", val)
        menu.append(rs)

        # 31 MCGAIN     Adjust the microphone gain level

        val = RadioSettingValueList(
            self._MIC_GAIN,
            self._MIC_GAIN[scan_settings.mic_gain])
        rs = RadioSetting("scan_settings.mic_gain", "Mic Gain", val)
        menu.append(rs)

        # VOLUME       Adjust the volume level

        scan_settings_2 = self._memobj.scan_settings_2
        val = RadioSettingValueList(
            self._VOLUME,
            self._VOLUME[scan_settings_2.volume])
        rs = RadioSetting("scan_settings_2.volume", "Volume", val)
        menu.append(rs)

        # Squelch       F key, Hold Monitor, Dial to adjust squelch level

        squelch_settings = self._memobj.squelch_settings
        val = RadioSettingValueList(
            self._SQUELCH,
            self._SQUELCH[squelch_settings.squelch])
        rs = RadioSetting("squelch_settings.squelch", "Squelch", val)
        menu.append(rs)

        return menu

    def _get_digital_settings(self):
        menu = RadioSettingGroup("digital_settings", "Digital")

        # MYCALL
        mycall = self._memobj.my_call
        mycallstr = str(mycall.callsign).rstrip("\xFF")
    
        mycallentry = RadioSettingValueString(0, 10, mycallstr, False, charset=self._MYCALL_CHR_SET)
        rs = RadioSetting('mycall.callsign', 'MYCALL', mycallentry)
        rs.set_apply_callback(self.apply_mycall, mycall)
        menu.append(rs)
        
        # Short Press AMS button AMS TX Mode

        digital_settings = self._memobj.digital_settings
        val = RadioSettingValueList(
            self._AMS_TX_MODE,
            self._AMS_TX_MODE[digital_settings.ams_tx_mode])
        rs = RadioSetting("digital_settings.ams_tx_mode", "AMS TX Mode", val)
        menu.append(rs)

        # 16 DIG VW  Turn the VW mode selection ON or OFF.

        val = RadioSettingValueList(
            self._VW_MODE,
            self._VW_MODE[digital_settings.vw_mode])
        rs = RadioSetting("digital_settings.vw_mode", "VW Mode", val)
        menu.append(rs)

        # TX DG-ID Long Press Mode Key, Dial

        val = RadioSettingValueList(
            self._DG_ID,
            self._DG_ID[digital_settings.tx_dg_id])
        rs = RadioSetting("digital_settings.tx_dg_id", "TX DG-ID", val)
        menu.append(rs)

        # RX DG-ID Long Press Mode Key, Mode Key to select, Dial

        val = RadioSettingValueList(
            self._DG_ID,
            self._DG_ID[digital_settings.rx_dg_id])
        rs = RadioSetting("digital_settings.rx_dg_id", "RX DG-ID", val)
        menu.append(rs)

        # 15 DIG.POP    Call sign display pop up time

        # 00 OFF     00
        # 0A 2s      10
        # 0B 4s      11
        # 0C 6s      12
        # 0D 8s      13
        # 0E 10s     14
        # 0F 20s     15
        # 10 30s     16
        # 11 60s     17
        # 12 CONT    18

        digital_settings_more = self._memobj.digital_settings_more

        val = RadioSettingValueList(
            self._DIG_POP_UP,
            self._DIG_POP_UP[
                0 if digital_settings_more.digital_popup == 0 else digital_settings_more.digital_popup - 9])

        rs = RadioSetting("digital_settings_more.digital_popup", "Digital Popup", val)
        rs.set_apply_callback(self.apply_digital_popup, digital_settings_more)
        menu.append(rs)

        # 07  BEP.STB    Standby Beep in the digital C4FM mode. On/Off

        val = RadioSettingValueList(
            self._STANDBY_BEEP,
            self._STANDBY_BEEP[digital_settings.standby_beep])
        rs = RadioSetting("digital_settings.standby_beep", "Standby Beep", val)
        menu.append(rs)

        return menu

    def _get_gm_settings(self):
        menu = RadioSettingGroup("first_settings", "Group Monitor")

        # 24 GM RNG Select the beep option while receiving digital GM information. OFF / IN RNG /ALWAYS

        first_settings = self._memobj.first_settings
        val = RadioSettingValueList(
            self._GM_RING,
            self._GM_RING[first_settings.gm_ring])
        rs = RadioSetting("first_settings.gm_ring", "GM Ring", val)
        menu.append(rs)

        # 25 GM INT Set the transmission interval of digital GM information. OFF / NORMAL / LONG

        scan_settings = self._memobj.scan_settings
        val = RadioSettingValueList(
            self._GM_INTERVAL,
            self._GM_INTERVAL[scan_settings.gm_interval])
        rs = RadioSetting("scan_settings.gm_interval", "GM Interval", val)
        menu.append(rs)

        return menu

    def _get_scan_settings(self):
        menu = RadioSettingGroup("scan_settings", "Scan")
        scan_settings = self._memobj.scan_settings

        # 23 DW RVT     Turn the "Priority Channel Revert" feature ON or OFF during Dual Receive.

        val = RadioSettingValueList(
            self._OFF_ON,
            self._OFF_ON[scan_settings.dw_rt])
        rs = RadioSetting("scan_settings.dw_rt", "Dual Watch Priority Channel Revert", val)
        menu.append(rs)

        # 21 DW INT Set the priority memory channel monitoring interval during Dual Receive. 0.1S - 5.0S - 10.0S

        val = RadioSettingValueList(
            self._SCAN_RESTART,
            self._SCAN_RESTART[scan_settings.dw_interval])
        rs = RadioSetting("scan_settings.dw_interval", "Dual Watch Interval", val)
        menu.append(rs)

        # 22 DW RSM Configure the scan stop mode settings for Dual Receive. 2.0S - 10.0 S / BUSY / HOLD

        first_settings = self._memobj.first_settings
        val = RadioSettingValueList(
            self._SCAN_RESUME,
            self._SCAN_RESUME[first_settings.dw_resume_interval])
        rs = RadioSetting("first_settings.dw_resume_interval", "Dual Watch Resume Interval", val)
        menu.append(rs)

        # 51 SCN.LMP   Set the scan lamp ON or OFF when scanning stops. OFF / ON

        val = RadioSettingValueList(
            self._OFF_ON,
            self._OFF_ON[scan_settings.scan_lamp])
        rs = RadioSetting("scan_settings.scan_lamp", "Scan Lamp", val)
        menu.append(rs)

        # 53 SCN.STR   Set the scanning restart time.  0.1 S - 2.0 S - 10.0 S

        val = RadioSettingValueList(
            self._SCAN_RESTART,
            self._SCAN_RESTART[scan_settings.scan_restart])
        rs = RadioSetting("scan_settings.scan_restart", "Scan Restart", val)
        menu.append(rs)

        # Scan Width Section

        # 50 SCV.WTH Set the VFO scan frequency range. BAND / ALL  - NOT FOUND!

        # Scan Resume Section

        # 52 SCN.RSM    Configure the scan stop mode settings. 2.0 S - 5.0 S - 10.0 S / BUSY / HOLD

        first_settings = self._memobj.first_settings
        val = RadioSettingValueList(
            self._SCAN_RESUME,
            self._SCAN_RESUME[first_settings.scan_resume])
        rs = RadioSetting("first_settings.scan_resume", "Scan Resume", val)
        menu.append(rs)

        return menu

    def _get_settings(self):
        top = RadioSettings(
            self._get_config_settings(),
            self._get_digital_settings(),
            self._get_display_settings(),
            self._get_dtmf_settings(),
            self._get_gm_settings(),
            self._get_scan_settings()
        )
        return top

    def get_settings(self):
        try:
            return self._get_settings()
        except:
            import traceback
            LOG.error("Failed to parse settings: %s", traceback.format_exc())
            return None

    @classmethod
    def apply_ff_padded_string(cls, setting, obj):
        setattr(obj, "padded_string", cls._add_ff_pad(setting.value.get_value().rstrip(), 6))

    def set_settings(self, settings):
        _mem = self._memobj
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            if not element.changed():
                continue
            try:
                if element.has_apply_callback():
                    LOG.debug("Using apply callback")
                    try:
                        element.run_apply_callback()
                    except NotImplementedError as e:
                        LOG.error(e)
                    continue

                # Find the object containing setting.
                obj = _mem
                bits = element.get_name().split(".")
                setting = bits[-1]
                for name in bits[:-1]:
                    if name.endswith("]"):
                        name, index = name.split("[")
                        index = int(index[:-1])
                        obj = getattr(obj, name)[index]
                    else:
                        obj = getattr(obj, name)

                try:
                    old_val = getattr(obj, setting)
                    LOG.debug("Setting %s(%r) <= %s" % (
                        element.get_name(), old_val, element.value))
                    setattr(obj, setting, element.value)
                except AttributeError as e:
                    LOG.error("Setting %s is not in the memory map: %s" %
                              (element.get_name(), e))
            except Exception as e:
                LOG.debug(element.get_name())
                raise

    def apply_volume(cls, setting, vfo):
        val = setting.value.get_value()
        cls._memobj.vfo_info[(vfo * 2)].volume = val
        cls._memobj.vfo_info[(vfo * 2) + 1].volume = val

    def apply_dtmf(cls, setting, i):
        rawval = setting.value.get_value().upper().rstrip()
        val = [FT70_DTMF_CHARS.index(x) for x in rawval]
        for x in range(len(val), 16):
            val.append(0xFF)
        cls._memobj.dtmf[i].memory = val

    def apply_digital_popup(cls, setting, obj):
        rawval = setting.value.get_value()
        val = 0 if cls._DIG_POP_UP.index(rawval) == 0 else cls._DIG_POP_UP.index(rawval) + 9
        obj.digital_popup = val

    def apply_mycall(cls, setting, obj):
        cs = setting.value.get_value()
        if cs[0] in ('-', '/'):
            raise InvalidValueError("First character of call sign can't be - or /:  {0:s}".format(cs))
        else:
            obj.callsign = cls._add_ff_pad(cs.rstrip(), 10)
