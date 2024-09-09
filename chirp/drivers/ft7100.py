# Copyright 2011 Dan Smith <dsmith@danplanet.com>
#
# FT-2900-specific modifications by Richard Cochran, <ag6qr@sonic.net>
# Initial work on settings by Chris Fosnight, <chris.fosnight@gmail.com>
# FT-7100-specific modifications by Bruno Maire, <bruno@e48.ch>
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
import logging

from chirp import util, memmap, chirp_common, bitwise, directory, errors
from chirp.drivers.yaesu_clone import YaesuCloneModeRadio
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueList, RadioSettingValueString, RadioSettings, \
    RadioSettingValueInteger, RadioSettingValueBoolean


LOG = logging.getLogger(__name__)

ACK = b"\x06"
NB_OF_BLOCKS = 248
BLOCK_LEN = 32


def _send(pipe, data):
    time.sleep(0.035)   # Same delay as "FT7100 Programmer" from RT Systems
    # pipe.write(data) --> It seems, that the single bytes are sent too fast
    # so send character per character with a delay
    for ch in data:
        pipe.write(bytes([ch]))
        time.sleep(0.0012)  # 0.0011 is to short. No ACK after a few packets
    echo = pipe.read(len(data))
    if data == b"":
        raise Exception("Failed to read echo."
                        " Maybe serial hardware not connected."
                        " Maybe radio not powered or not in receiving mode.")
    if data != echo:
        LOG.debug("expecting echo\n%s\n", util.hexprint(data))
        LOG.debug("got echo\n%s\n", util.hexprint(echo))
        raise Exception("Got false echo. Expected: %r, got: %r.",
                        data, echo)


def _send_ack(pipe):
    time.sleep(0.01)  # Wait for radio input buffer ready
    # time.sleep(0.0003) is the absolute working minimum.
    # This delay is not critical for the transfer as there are not many ACKs.
    _send(pipe, ACK)


def _wait_for_ack(pipe):
    echo = pipe.read(1)
    if echo == b"":
        raise Exception("Failed to read ACK. No response from radio.")
    if echo != ACK:
        raise Exception("Failed to read ACK.  Expected: %r, got: %r.",
                        ACK, echo)


def _download(radio):
    LOG.debug("in _download\n")
    data = b""
    for _i in range(0, 60):
        chunk = radio.pipe.read(BLOCK_LEN)
        data += chunk
        LOG.debug("Header:\n%s", util.hexprint(data))
        if data == radio.IDBLOCK:
            break
        if len(data) > len(radio.IDBLOCK):
            break
    if data == b"":
        raise Exception("Got no data from radio.")
    if data != radio.IDBLOCK:
        raise Exception("Got false header. Expected: %r, got: %r." % (
                          radio.IDBLOCK, data))
    _send_ack(radio.pipe)

    # read 16 Byte block
    # and ignore it because it is constant. This might be a bug.
    # It was built in at the very beginning and discovered very late that the
    # data might be necessary later to write to the radio.
    # Now the data is hardcoded in _upload(radio)
    data = radio.pipe.read(16)
    _send_ack(radio.pipe)
    LOG.debug('Magic 16-byte chunk:\n%s' % util.hexprint(data))

    # initialize data, the big var that holds all memory
    data = b""
    for block_nr in range(NB_OF_BLOCKS):
        chunk = radio.pipe.read(BLOCK_LEN)
        if len(chunk) != BLOCK_LEN:
            LOG.debug("Block %i ", block_nr)
            LOG.debug("Got: %i:\n%s", len(chunk), util.hexprint(chunk))
            LOG.debug("len chunk is %i\n", len(chunk))
            raise Exception("Failed to get full data block")
        else:
            data += chunk
        _send_ack(radio.pipe)

        if radio.status_fn:
            status = chirp_common.Status()
            status.max = NB_OF_BLOCKS * BLOCK_LEN
            status.cur = len(data)
            status.msg = "Cloning from radio"
            radio.status_fn(status)

    LOG.debug("Total: %i", len(data))
    _send_ack(radio.pipe)

    # for debugging purposes, dump the channels, in hex.
    for _i in range(0, (NB_OF_BLOCKS * BLOCK_LEN) // 26):
        _start_data = 4 + 26 * _i
        chunk = data[_start_data:_start_data + 26]
        LOG.debug("channel %i:\n%s", _i-21, util.hexprint(chunk))

    return memmap.MemoryMapBytes(data)


def _upload(radio):
    data = radio.pipe.read(256)  # Clear buffer
    _send(radio.pipe, radio.IDBLOCK)
    _wait_for_ack(radio.pipe)

    # write 16 Byte block
    # If there should be a problem, see remarks in _download(radio)
    _send(radio.pipe, b"\xEE\x77\x01\x00\x0E\x07\x0E\x07"
                      b"\x00\x00\x00\x00\x00\x02\x00\x00")
    _wait_for_ack(radio.pipe)

    for block_nr in range(NB_OF_BLOCKS):
        data = radio.get_mmap()[block_nr * BLOCK_LEN:
                                (block_nr + 1) * BLOCK_LEN]
        LOG.debug("Writing block_nr %i:\n%s", block_nr, util.hexprint(data))
        _send(radio.pipe, data)
        _wait_for_ack(radio.pipe)

        if radio.status_fn:
            status = chirp_common.Status()
            status.max = NB_OF_BLOCKS * BLOCK_LEN
            status.cur = block_nr * BLOCK_LEN
            status.msg = "Cloning to radio"
            radio.status_fn(status)
        block_nr += 1


MEM_FORMAT = """
struct mem {
  u8   is_used:1,
       is_masked:1,
       is_skip:1,
       unknown11:3,
       show_name:1,
       is_split:1;
  u8   unknown2;
  ul32 freq_rx_Hz;
  ul32 freq_tx_Hz;
  ul16 offset_10khz;
  u8   unknown_dependent_of_band_144_b0000_430_b0101:4,
       tuning_step_index_1_2:4;
  u8   unknown51:2,
       is_offset_minus:1,
       is_offset_plus:1,
       unknown52:1,
       tone_mode_index:3;
  u8   tone_index;
  u8   dtcs_index;
  u8   is_mode_am:1,
       unknown71:2,
       is_packet96:1,
       unknown72:2,
       power_index:2;
  u8   unknown81:2,
       tuning_step_index_2_2:4,
       unknown82:2;
  char name[6];
  u8   unknown9;
  u8   unknownA;
};

// Settings are often present multiple times.
// The memories which is written to are mapped here
struct
{
#seekto 0x41;
  u8        current_band;
#seekto 0xa1;
  u8        apo;
#seekto 0xa2;
  u8        ars_vhf;
#seekto 0xe2;
  u8        ars_uhf;
#seekto 0xa3;
  u8        arts_vhf;
#seekto 0xa3;
  u8        arts_uhf;
#seekto 0xa4;
  u8        beep;
#seekto 0xa5;
  u8        cwid;
#seekto 0x80;
  char        cwidw[6];
#seekto 0xa7;
  u8        dim;
#seekto 0xaa;
  u8        dcsnr_vhf;
#seekto 0xea;
  u8        dcsnr_uhf;
#seekto 0xab;
  u8        disp;
#seekto 0xac;
  u8        dtmfd;
#seekto 0xad;
  u8        dtmfs;
#seekto 0xae;
  u8        dtmfw;
#seekto 0xb0;
  u8        lockt;
#seekto 0xb1;
  u8        mic;
#seekto 0xb2;
  u8        mute;
#seekto 0xb4;
  u8        button[4];
#seekto 0xb8;
  u8        rf_sql_vhf;
#seekto 0xf8;
  u8        rf_sql_uhf;
#seekto 0xb9;
  u8        scan_vhf;
#seekto 0xf9;
  u8        scan_uhf;
#seekto 0xbc;
  u8        speaker_cnt;
#seekto 0xff;
  u8        tot;
#seekto 0xc0;
  u8        txnar_vhf;
#seekto 0x100;
  u8        txnar_uhf;
#seekto 0xc1;
  u8        vfotr;
#seekto 0xc2;
  u8        am;
} overlay;

// All known memories
#seekto 0x20;
  u8        nb_mem_used_vhf;
#seekto 0x22;
  u8        nb_mem_used_vhf_and_limits;
#seekto 0x24;
  u8        nb_mem_used_uhf;
#seekto 0x26;
  u8        nb_mem_used_uhf_and_limits;

#seekto 0x41;
  u8        current_band;

#seekto 0x42;
  u8        current_nb_mem_used_vhf_maybe_not;

#seekto 0x4c;
  u8        priority_channel_maybe_1;   // not_implemented
  u8        priority_channel_maybe_2;   // not_implemented
  u8        priority_channel;           // not_implemented

#seekto 0x87;
  u8        opt_01_apo_1_4;
#seekto 0xa1;
  u8        opt_01_apo_2_4;
#seekto 0xc5;
  u8        opt_01_apo_3_4;
#seekto 0xe1;
  u8        opt_01_apo_4_4;

#seekto 0x88;
  u8        opt_02_ars_vhf_1_2;
#seekto 0xa2;
  u8        opt_02_ars_vhf_2_2;
#seekto 0xc6;
  u8        opt_02_ars_uhf_1_2;
#seekto 0xe2;
  u8        opt_02_ars_uhf_2_2;

#seekto 0x89;
  u8        opt_03_arts_mode_vhf_1_2;
#seekto 0xa3;
  u8        opt_03_arts_mode_vhf_2_2;
#seekto 0xc7;
  u8        opt_03_arts_mode_uhf_1_2;
#seekto 0xa3;
  u8        opt_03_arts_mode_uhf_2_2;

#seekto 0x8a;
  u8        opt_04_beep_1_2;
#seekto 0xa4;
  u8        opt_04_beep_2_2;

#seekto 0x8b;
  u8        opt_05_cwid_on_1_4;
#seekto 0xa5;
  u8        opt_05_cwid_on_2_4;
#seekto 0xc9;
  u8        opt_05_cwid_on_3_4;
#seekto 0xe5;
  u8        opt_05_cwid_on_4_4;

#seekto 0x80;
  char        opt_06_cwidw[6];

#seekto 0x8d;
  u8        opt_07_dim_1_4;
#seekto 0xa7;
  u8        opt_07_dim_2_4;
#seekto 0xcb;
  u8        opt_07_dim_3_4;
#seekto 0xe7;
  u8        opt_07_dim_4_4;

#seekto 0x90;
  u8        opt_10_dcsnr_vhf_1_2;
#seekto 0xaa;
  u8        opt_10_dcsnr_vhf_2_2;
#seekto 0xce;
  u8        opt_10_dcsnr_uhf_1_2;
#seekto 0xea;
  u8        opt_10_dcsnr_uhf_2_2;

#seekto 0x91;
  u8        opt_11_disp_1_4;
#seekto 0xab;
  u8        opt_11_disp_2_4;
#seekto 0xcf;
  u8        opt_11_disp_3_4;
#seekto 0xeb;
  u8        opt_11_disp_4_4;

#seekto 0x92;
  u8        opt_12_dtmf_delay_1_4;
#seekto 0xac;
  u8        opt_12_dtmf_delay_2_4;
#seekto 0xd0;
  u8        opt_12_dtmf_delay_3_4;
#seekto 0xec;
  u8        opt_12_dtmf_delay_4_4;

#seekto 0x93;
  u8        opt_13_dtmf_speed_1_4;
#seekto 0xad;
  u8        opt_13_dtmf_speed_2_4;
#seekto 0xd1;
  u8        opt_13_dtmf_speed_3_4;
#seekto 0xed;
  u8        opt_13_dtmf_speed_4_4;

#seekto 0x94;
  u8        opt_14_dtmfw_index_1_4;
#seekto 0xae;
  u8        opt_14_dtmfw_index_2_4;
#seekto 0xd2;
  u8        opt_14_dtmfw_index_3_4;
#seekto 0xee;
  u8        opt_14_dtmfw_index_4_4;

#seekto 0x96;
  u8        opt_16_lockt_1_4;
#seekto 0xb0;
  u8        opt_16_lockt_2_4;
#seekto 0xd4;
  u8        opt_16_lockt_3_4;
#seekto 0xf0;
  u8        opt_16_lockt_4_4;

#seekto 0x97;
  u8        opt_17_mic_MH48_1_4;
#seekto 0xb1;
  u8        opt_17_mic_MH48_2_4;
#seekto 0xd5;
  u8        opt_17_mic_MH48_3_4;
#seekto 0xf1;
  u8        opt_17_mic_MH48_4_4;

#seekto 0x98;
  u8        opt_18_mute_1_4;
#seekto 0xb2;
  u8        opt_18_mute_2_4;
#seekto 0xd6;
  u8        opt_18_mute_3_4;
#seekto 0xf2;
  u8        opt_18_mute_4_4;

#seekto 0x9a;
  u8        opt_20_pg_p_1_4[4];
#seekto 0xb4;
  u8        opt_20_pg_p_2_4[4];
#seekto 0xd8;
  u8        opt_20_pg_p_3_4[4];
#seekto 0xf4;
  u8        opt_20_pg_p_4_4[4];

#seekto 0x9e;
  u8        opt_24_rf_sql_vhf_1_2;
#seekto 0xb8;
  u8        opt_24_rf_sql_vhf_2_2;
#seekto 0xdc;
  u8        opt_24_rf_sql_uhf_1_2;
#seekto 0xf8;
  u8        opt_24_rf_sql_uhf_2_2;

#seekto 0x9f;
  u8        opt_25_scan_resume_vhf_1_2;
#seekto 0xb9;
  u8        opt_25_scan_resume_vhf_2_2;
#seekto 0xdd;
  u8        opt_25_scan_resume_uhf_1_2;
#seekto 0xf9;
  u8        opt_25_scan_resume_uhf_2_2;

#seekto 0xbc;
  u8        opt_28_speaker_cnt_1_2;
#seekto 0xfc;
  u8        opt_28_speaker_cnt_2_2;

#seekto 0xbf;
  u8        opt_31_tot_1_2;
#seekto 0xff;
  u8        opt_31_tot_2_2;

#seekto 0xc0;
  u8        opt_32_tx_nar_vhf;
#seekto 0x100;
  u8        opt_32_tx_nar_uhf;

#seekto 0xc1;
  u8        opt_33_vfo_tr;

#seekto 0xc2;
  u8        opt_34_am_1_2;
#seekto 0x102;
  u8        opt_34_am_2_2;

#seekto 260;
struct {
  struct mem mem_struct;
  char        fill_ff[2];
} unknown00;

struct {
  struct mem mem_struct;
  char        fill_00[6];
} current_vfo_vhf_uhf[2];

struct {
  struct mem mem_struct;
  char        fill_ff[6];
} current_mem_vhf_uhf[2];

struct {
  struct mem mem_struct;
  char        fill_ff[6];
} home_vhf_uhf[2];

struct {
  struct mem mem_struct;
  char        fill_010003000000[6];
} vhome;

struct {
  struct mem mem_struct;
  char        fill_010001000000[6];
} unknown01;

struct {
  char name[32];
} Vertex_Standard_AH003M_Backup_DT;

struct mem
  memory[260];

struct {
  char name[24];
} Vertex_Standard_AH003M;

struct {
  u8 dtmf[16];
} dtmf_mem[16];
"""

MODES_VHF = ["FM", "AM"]
MODES_UHF = ["FM"]      # AM can be set but is ignored by the radio
DUPLEX = ["", "-", "+", "split"]
TONE_MODES_RADIO = ["", "Tone", "TSQL", "CTCSS Bell", "DTCS"]
TONE_MODES = ["", "Tone", "TSQL", "DTCS"]
POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=5),
    chirp_common.PowerLevel("Low2", watts=10),
    chirp_common.PowerLevel("Low3", watts=20),
    chirp_common.PowerLevel("High", watts=35),
    ]
TUNING_STEPS = [5.0, 10.0, 12.5, 15.0, 20.0, 25.0, 50.0]
SKIP_VALUES = ["", "S"]
CHARSET = r"!\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\]^ _"
DTMF_CHARSET = "0123456789*# "
SPECIAL_CHANS = ['VFO-VHF', 'VFO-UHF', 'Home-VHF', 'Home-UHF', 'VFO', 'Home']
SCAN_LIMITS = ["L1", "U1", "L2", "U2", "L3", "U3", "L4", "U4", "L5", "U5"]


def do_download(radio):
    """This is your download function"""
    return _download(radio)


@directory.register
class FT7100Radio(YaesuCloneModeRadio):

    """Yaesu FT-7100M"""
    MODEL = "FT-7100M"
    VARIANT = ""
    IDBLOCK = b"Vartex Standard AH003M M-Map V04"
    BAUD_RATE = 9600

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        LOG.debug("get_features")
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False

        rf.memory_bounds = (0, 240)
        # This radio supports 120 + 10 + 120 + 10 = 260 memories
        # These are zero based for chirpc
        rf.valid_bands = [
            (108000000, 180000000),  # Supports 2-meters tx
            (320000000, 999990000),  # Supports 70-centimeters tx
            ]
        rf.can_odd_split = True
        rf.has_ctone = True
        rf.has_rx_dtcs = True
        rf.has_cross = False
        rf.has_dtcs_polarity = False
        rf.has_bank = False
        rf.has_bank_names = False
        rf.has_settings = True
        rf.has_sub_devices = True
        rf.valid_tuning_steps = TUNING_STEPS
        rf.valid_modes = MODES_VHF
        rf.valid_tmodes = TONE_MODES
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_duplexes = DUPLEX
        rf.valid_skips = SKIP_VALUES
        rf.valid_name_length = 6
        rf.valid_characters = CHARSET
        rf.valid_special_chans = SPECIAL_CHANS
        return rf

    def sync_in(self):
        start = time.time()
        try:
            self._mmap = _download(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Downloaded in %.2f sec", (time.time() - start))
        self.process_mmap()

    def sync_out(self):
        self.pipe.timeout = 1
        start = time.time()
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError("Failed to communicate with radio: %s" % e)
        LOG.info("Uploaded in %.2f sec", (time.time() - start))

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def get_memory(self, number):
        LOG.debug("get_memory Number: %r", number)

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        # Get a low-level memory object mapped to the image
        if isinstance(number, int) and number < 0:
            number = SPECIAL_CHANS[number + 10]
        if isinstance(number, str):
            mem.number = -10 + SPECIAL_CHANS.index(number)
            mem.extd_number = number
            band = 0
            if self._memobj.overlay.current_band != 0:
                band = 1
            if number == 'VFO-VHF':
                _mem = self._memobj.current_vfo_vhf_uhf[0].mem_struct
            elif number == 'VFO-UHF':
                _mem = self._memobj.current_vfo_vhf_uhf[1].mem_struct
            elif number == 'Home-VHF':
                _mem = self._memobj.home_vhf_uhf[0].mem_struct
            elif number == 'Home-UHF':
                _mem = self._memobj.home_vhf_uhf[1].mem_struct
            elif number == 'VFO':
                _mem = self._memobj.current_vfo_vhf_uhf[band].mem_struct
            elif number == 'Home':
                _mem = self._memobj.home_vhf_uhf[band].mem_struct
            _mem.is_used = True
        else:
            mem.number = number                 # Set the memory number
            _mem = self._memobj.memory[number]
            upper_channel = self._memobj.nb_mem_used_vhf
            upper_limit = self._memobj.nb_mem_used_vhf_and_limits
            if number >= upper_channel and number < upper_limit:
                i = number - upper_channel
                mem.extd_number = SCAN_LIMITS[i]
            if number >= 260-10:
                i = number - (260-10)
                mem.extd_number = SCAN_LIMITS[i]

        # Convert your low-level frequency to Hertz
        mem.freq = int(_mem.freq_rx_Hz)
        mem.name = str(_mem.name).rstrip()  # Set the alpha tag

        mem.rtone = chirp_common.TONES[_mem.tone_index]
        mem.ctone = chirp_common.TONES[_mem.tone_index]

        mem.dtcs = chirp_common.DTCS_CODES[_mem.dtcs_index]
        mem.rx_dtcs = chirp_common.DTCS_CODES[_mem.dtcs_index]

        tmode_radio = TONE_MODES_RADIO[_mem.tone_mode_index]
        # CTCSS Bell is TSQL plus a flag in the extra setting
        is_ctcss_bell = tmode_radio == "CTCSS Bell"
        if is_ctcss_bell:
            mem.tmode = "TSQL"
        else:
            mem.tmode = tmode_radio

        mem.duplex = ""
        if _mem.is_offset_plus:
            mem.duplex = "+"
        elif _mem.is_offset_minus:
            mem.duplex = "-"
        elif _mem.is_split:
            mem.duplex = "split"

        if _mem.is_split:
            mem.offset = int(_mem.freq_tx_Hz)
        else:
            mem.offset = int(_mem.offset_10khz)*10000   # 10 kHz to Hz

        if _mem.is_mode_am:
            mem.mode = "AM"
        else:
            mem.mode = "FM"

        mem.power = POWER_LEVELS[_mem.power_index]

        mem.tuning_step = TUNING_STEPS[_mem.tuning_step_index_1_2]

        if _mem.is_skip:
            mem.skip = "S"
        else:
            mem.skip = ""

        # mem.comment = ""

        mem.empty = not _mem.is_used

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("show_name", "Show Name",
                          RadioSettingValueBoolean(_mem.show_name))
        mem.extra.append(rs)
        rs = RadioSetting("is_masked", "Is Masked",
                          RadioSettingValueBoolean(_mem.is_masked))
        mem.extra.append(rs)
        rs = RadioSetting("is_packet96", "Packet 9600",
                          RadioSettingValueBoolean(_mem.is_packet96))
        mem.extra.append(rs)
        rs = RadioSetting("is_ctcss_bell", "CTCSS Bell",
                          RadioSettingValueBoolean(is_ctcss_bell))
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):
        LOG.debug("set_memory Number: %r", mem.number)
        if mem.number < 0:
            number = SPECIAL_CHANS[mem.number+10]
            if number == 'VFO-VHF':
                _mem = self._memobj.current_vfo_vhf_uhf[0].mem_struct
            elif number == 'VFO-UHF':
                _mem = self._memobj.current_vfo_vhf_uhf[1].mem_struct
            elif number == 'Home-VHF':
                _mem = self._memobj.home_vhf_uhf[0].mem_struct
            elif number == 'Home-UHF':
                _mem = self._memobj.home_vhf_uhf[1].mem_struct
            else:
                raise errors.RadioError("Unexpected Memory Number: %r",
                                        mem.number)
        else:
            _mem = self._memobj.memory[mem.number]

        _mem.name = mem.name.ljust(6)

        _mem.tone_index = chirp_common.TONES.index(mem.rtone)
        _mem.dtcs_index = chirp_common.DTCS_CODES.index(mem.dtcs)
        if mem.tmode == "TSQL":
            _mem.tone_index = chirp_common.TONES.index(mem.ctone)
        if mem.tmode == "DTSC-R":
            _mem.dtcs_index = chirp_common.DTCS_CODES.index(mem.rx_dtcs)

        _mem.is_offset_plus = 0
        _mem.is_offset_minus = 0
        _mem.is_split = 0
        _mem.freq_rx_Hz = mem.freq
        _mem.freq_tx_Hz = mem.freq
        if mem.duplex == "+":
            _mem.is_offset_plus = 1
            _mem.freq_tx_Hz = mem.freq + mem.offset
            _mem.offset_10khz = int(mem.offset/10000)
        elif mem.duplex == "-":
            _mem.is_offset_minus = 1
            _mem.freq_tx_Hz = mem.freq - mem.offset
            _mem.offset_10khz = int(mem.offset/10000)
        elif mem.duplex == "split":
            _mem.is_split = 1
            _mem.freq_tx_Hz = mem.offset
            # No change to _mem.offset_10khz

        _mem.is_mode_am = mem.mode == "AM"

        if mem.power:
            _mem.power_index = POWER_LEVELS.index(mem.power)

        _mem.tuning_step_index_1_2 = TUNING_STEPS.index(mem.tuning_step)

        _mem.is_skip = mem.skip == "S"

        _mem.is_used = not mem.empty

        # if name not empty: show name
        _mem.show_name = mem.name.strip() != ""

        # In testmode there is no setting in mem.extra
        # This is why the following line is not located in the else part of
        # the if structure below
        _mem.tone_mode_index = TONE_MODES_RADIO.index(mem.tmode)

        for setting in mem.extra:
            if setting.get_name() == "is_ctcss_bell":
                if mem.tmode == "TSQL" and setting.value:
                    _mem.tone_mode_index = TONE_MODES_RADIO.index("CTCSS Bell")
            else:
                setattr(_mem, setting.get_name(), setting.value)

        LOG.debug("encoded mem\n%s\n",
                  (util.hexprint(_mem.get_raw(asbytes=False)[0:25])))
        LOG.debug(repr(_mem))

    def get_settings(self):
        common = RadioSettingGroup("common", "Common Settings")
        band = RadioSettingGroup("band", "Band dependent Settings")
        arts = RadioSettingGroup("arts",
                                 "Auto Range Transponder System (ARTS)")
        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        mic_button = RadioSettingGroup("mic_button", "Microphone Buttons")
        setmode = RadioSettings(common, band, arts, dtmf, mic_button)

        _overlay = self._memobj.overlay

        # numbers and names of settings refer to the way they're
        # presented in the set menu, as well as the list starting on
        # page 49 of the manual

        # 1 Automatic Power Off
        opts = [
            "Off", "30 Min",
            "1 Hour", "1.5 Hours",
            "2 Hours", "2.5 Hours",
            "3 Hours", "3.5 Hours",
            "4 Hours", "4.5 Hours",
            "5 Hours", "5.5 Hours",
            "6 Hours", "6.5 Hours",
            "7 Hours", "7.5 Hours",
            "8 Hours", "8.5 Hours",
            "9 Hours", "9.5 Hours",
            "10 Hours", "10.5 Hours",
            "11 Hours", "11.5 Hours",
            "12 Hours",
            ]
        common.append(
            RadioSetting(
                "apo", "Automatic Power Off",
                RadioSettingValueList(opts, current_index=_overlay.apo)))

        # 2 Automatic Repeater Shift function
        opts = ["Off", "On"]
        band.append(
            RadioSetting(
                "ars_vhf", "Automatic Repeater Shift VHF",
                RadioSettingValueList(opts, current_index=_overlay.ars_vhf)))
        band.append(
            RadioSetting(
                "ars_uhf", "Automatic Repeater Shift UHF",
                RadioSettingValueList(opts, current_index=_overlay.ars_uhf)))

        # 3  Selects the ARTS mode.
        # -> Only useful to set it on the radio directly

        # 4 Enables/disables the key/button beeper.
        opts = ["Off", "On"]
        common.append(
            RadioSetting(
                "beep", "Key/Button Beep",
                RadioSettingValueList(opts, current_index=_overlay.beep)))

        # 5 Enables/disables the CW IDer during ARTS operation.
        opts = ["Off", "On"]
        arts.append(
            RadioSetting(
                "cwid", "Enables/Disables the CW ID",
                RadioSettingValueList(opts, current_index=_overlay.cwid)))

        # 6  Callsign during ARTS operation.
        cwidw = _overlay.cwidw.get_raw(asbytes=False)
        cwidw = cwidw.rstrip('\x00')
        val = RadioSettingValueString(0, 6, cwidw)
        val.set_charset(CHARSET)
        rs = RadioSetting("cwidw", "CW Identifier Callsign", val)

        def apply_cwid(setting):
            value_string = setting.value.get_value()
            _overlay.cwidw.set_value(value_string)
        rs.set_apply_callback(apply_cwid)
        arts.append(rs)

        # 7 Front panel display's illumination level.
        opts = ["0: Off", "1: Max", "2", "3", "4", "5", "6", "7: Min"]
        common.append(
            RadioSetting(
                "dim", "Display Illumination",
                RadioSettingValueList(opts, current_index=_overlay.dim)))

        # 8 Setting the DCS code number.
        #   Note: This Menu item can be set independently for each band,
        #         and independently in each memory.

        # 9 Activates the DCS Code Search
        # -> Only useful if set on radio itself

        # 10 Selects 'Normal' or 'Inverted' DCS coding.
        opts = ["TRX Normal", "RX Reversed", "TX Reversed", "TRX Reversed"]
        band.append(
            RadioSetting(
                "dcsnr_vhf", "DCS coding VHF",
                RadioSettingValueList(opts, current_index=_overlay.dcsnr_vhf)))
        band.append(
            RadioSetting(
                "dcsnr_uhf", "DCS coding UHF",
                RadioSettingValueList(opts, current_index=_overlay.dcsnr_uhf)))

        # 11 Selects the 'sub' band display format
        opts = ["Frequency", "Off / Sub Band disabled",
                "DC Input Voltage", "CW ID"]
        common.append(
            RadioSetting(
                "disp", "Sub Band Display Format",
                RadioSettingValueList(opts, current_index=_overlay.disp)))

        # 12 Setting the DTMF Autodialer delay time
        opts = ["50 ms", "250 ms", "450 ms", "750 ms", "1 s"]
        dtmf.append(
            RadioSetting(
                "dtmfd", "Autodialer delay time",
                RadioSettingValueList(opts, current_index=_overlay.dtmfd)))

        # 13 Setting the DTMF Autodialer sending speed
        opts = ["50 ms", "75 ms", "100 ms"]
        dtmf.append(
            RadioSetting(
                "dtmfs", "Autodialer sending speed",
                RadioSettingValueList(opts, current_index=_overlay.dtmfs)))

        # 14 Current DTMF Autodialer memory
        rs = RadioSetting("dtmfw", "Current Autodialer memory",
                          RadioSettingValueInteger(1, 16, _overlay.dtmfw + 1))

        def apply_dtmfw(setting):
            _overlay.dtmfw = setting.value.get_value() - 1
        rs.set_apply_callback(apply_dtmfw)
        dtmf.append(rs)

        # DTMF Memory
        for i in range(16):
            dtmf_string = ""
            for j in range(16):
                dtmf_char = ''
                dtmf_int = int(self._memobj.dtmf_mem[i].dtmf[j])
                if dtmf_int < 10:
                    dtmf_char = str(dtmf_int)
                elif dtmf_int == 14:
                    dtmf_char = '*'
                elif dtmf_int == 15:
                    dtmf_char = '#'
                elif dtmf_int == 255:
                    break
                dtmf_string += dtmf_char
            radio_setting_value_string = RadioSettingValueString(0, 16,
                                                                 dtmf_string)
            radio_setting_value_string.set_charset(DTMF_CHARSET)
            rs = RadioSetting("dtmf_%02i" % i,
                              "DTMF Mem " + str(i+1),
                              radio_setting_value_string)

            def apply_dtmf(setting, index):
                radio_setting_value_string = setting.value.get_value().rstrip()
                j = 0
                for dtmf_char in radio_setting_value_string:
                    dtmf_int = 255
                    if dtmf_char in "0123456789":
                        dtmf_int = int(dtmf_char)
                    elif dtmf_char == '*':
                        dtmf_int = 14
                    elif dtmf_char == '#':
                        dtmf_int = 15
                    if dtmf_int < 255:
                        self._memobj.dtmf_mem[index].dtmf[j] = dtmf_int
                        j += 1
                if j < 16:
                    self._memobj.dtmf_mem[index].dtmf[j] = 255
            rs.set_apply_callback(apply_dtmf, i)
            dtmf.append(rs)

        # 16 Enables/disables the PTT switch lock
        opts = ["Off", "Band A", "Band B", "Both"]
        common.append(
            RadioSetting(
                "lockt", "PTT switch lock",
                RadioSettingValueList(opts, current_index=_overlay.lockt)))

        # 17 Selects the Microphone type to be used
        opts = ["MH-42", "MH-48"]
        common.append(
            RadioSetting(
                "mic", "Microphone type",
                RadioSettingValueList(opts, current_index=_overlay.mic)))

        # 18 Reduces the audio level on the sub receiver when the
        #    main receiver is active
        opts = ["Off", "On"]
        common.append(
            RadioSetting(
                "mute", "Mute Sub Receiver",
                RadioSettingValueList(opts, current_index=_overlay.mute)))

        # 20 - 23 Programming the microphones button assignment
        buttons = [
            "ACC / P1",
            "P / P2",
            "P1 / P3",
            "P2 / P4",
            ]
        opts_button = ["Low", "Tone", "MHz", "Rev", "Home", "Band",
                       "VFO / Memory", "Sql Off", "1750 Hz Tone Call",
                       "Repeater", "Priority"]
        for i, button in enumerate(buttons):
            rs = RadioSetting(
                "button" + str(i), button,
                RadioSettingValueList(opts_button,
                                      current_index=_overlay.button[i]))

            def apply_button(setting, index):
                value_string = setting.value.get_value()
                value_int = opts_button.index(value_string)
                _overlay.button[index] = value_int
            rs.set_apply_callback(apply_button, i)
            mic_button.append(rs)

        # 24 Adjusts the RF SQL threshold level
        opts = ["Off", "S-1", "S-5", "S-9", "S-FULL"]
        band.append(
            RadioSetting(
                "rf_sql_vhf", "RF Sql VHF",
                RadioSettingValueList(
                    opts, current_index=_overlay.rf_sql_vhf)))
        band.append(
            RadioSetting(
                "rf_sql_uhf", "RF Sql UHF",
                RadioSettingValueList(
                    opts, current_index=_overlay.rf_sql_uhf)))

        # 25 Selects the Scan-Resume mode
        opts = ["Busy", "Time"]
        band.append(
            RadioSetting(
                "scan_vhf", "Scan-Resume VHF",
                RadioSettingValueList(opts, current_index=_overlay.scan_vhf)))
        band.append(
            RadioSetting(
                "scan_uhf", "Scan-Resume UHF",
                RadioSettingValueList(opts, current_index=_overlay.scan_uhf)))

        # 28 Defining the audio path to the external speaker
        opts = ["Off", "Band A", "Band B", "Both"]
        common.append(
            RadioSetting(
                "speaker_cnt", "External Speaker",
                RadioSettingValueList(
                    opts, current_index=_overlay.speaker_cnt)))

        # 31 Sets the Time-Out Timer
        opts = ["Off", "Band A", "Band B", "Both"]
        common.append(
            RadioSetting(
                "tot", "TX Time-Out [Min.] (0 = Off)",
                RadioSettingValueInteger(0, 30, _overlay.tot)))

        # 32 Reducing the MIC Gain (and Deviation)
        opts = ["Off", "On"]
        band.append(
            RadioSetting(
                "txnar_vhf", "TX Narrowband VHF",
                RadioSettingValueList(opts, current_index=_overlay.txnar_vhf)))
        band.append(
            RadioSetting(
                "txnar_uhf", "TX Narrowband UHF",
                RadioSettingValueList(opts, current_index=_overlay.txnar_uhf)))

        # 33 Enables/disables the VFO Tracking feature
        opts = ["Off", "On"]
        common.append(
            RadioSetting(
                "vfotr", "VFO Tracking",
                RadioSettingValueList(opts, current_index=_overlay.vfotr)))

        # 34 Selects the receiving mode on the VHF band
        opts = ["Inhibit (only FM)", "AM", "Auto"]
        common.append(
            RadioSetting(
                "am", "AM Mode",
                RadioSettingValueList(opts, current_index=_overlay.am)))

        # Current Band
        opts = ["VHF", "UHF"]
        common.append(
            RadioSetting(
                "current_band", "Current Band",
                RadioSettingValueList(
                    opts, current_index=_overlay.current_band)))

        # Show number of VHF and UHF channels
        val = RadioSettingValueString(0, 7,
                                      str(int(self._memobj.nb_mem_used_vhf)))
        val.set_mutable(False)
        rs = RadioSetting("num_chan_vhf", "Number of VHF channels", val)
        common.append(rs)
        val = RadioSettingValueString(0, 7,
                                      str(int(self._memobj.nb_mem_used_uhf)))
        val.set_mutable(False)
        rs = RadioSetting("num_chan_uhf", "Number of UHF channels", val)
        common.append(rs)

        return setmode

    def set_settings(self, uisettings):
        _overlay = self._memobj.overlay
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
                    setattr(_overlay, name, value)

                LOG.debug("Setting %s: %s", name, value)
            except Exception:
                LOG.debug(element.get_name())
                raise

    def _get_upper_vhf_limit(self):
        if self._memobj is None:
            # test with tox has no _memobj
            upper_vhf_limit = 120
        else:
            upper_vhf_limit = int(self._memobj.nb_mem_used_vhf)
        return upper_vhf_limit

    def _get_upper_uhf_limit(self):
        if self._memobj is None:
            # test with tox has no _memobj
            upper_uhf_limit = 120
        else:
            upper_uhf_limit = int(self._memobj.nb_mem_used_uhf)
        return upper_uhf_limit

    @classmethod
    def match_model(cls, filedata, filename):
        return filedata[0x1ec0:0x1ec0+len(cls.IDBLOCK)] == cls.IDBLOCK

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.pre_download = _(
            "1. Turn Radio off.\n"
            "2. Connect data cable.\n"
            "3. While holding \"TONE\" and \"REV\" buttons, turn radio on.\n"
            "4. <b>After clicking OK</b>, press \"TONE\" to send image.\n")
        rp.pre_upload = _(
            "1. Turn Radio off.\n"
            "2. Connect data cable.\n"
            "3. While holding \"TONE\" and \"REV\" buttons, turn radio on.\n"
            "4. Press \"REV\" to receive image.\n"
            "5. Make sure display says \"CLONE RX\" and green led is"
            " blinking\n"
            "6. Click OK to start transfer.\n")
        return rp

    def get_sub_devices(self):
        if not self.VARIANT:
            return [FT7100RadioVHF(self._mmap),
                    FT7100RadioUHF(self._mmap)]
        else:
            return []


class FT7100RadioVHF(FT7100Radio):
    VARIANT = "VHF Band"

    def get_features(self):
        LOG.debug("VHF get_features")
        upper_vhf_limit = self._get_upper_vhf_limit()
        rf = FT7100Radio.get_features(self)
        rf.memory_bounds = (1, upper_vhf_limit)
        # Normally this band supports 120 + 10 memories. 1 based for chirpw
        rf.valid_bands = [(108000000, 180000000)]  # Supports 2-meters tx
        rf.valid_modes = MODES_VHF
        rf.valid_special_chans = ['VFO', 'Home']
        rf.has_sub_devices = False
        return rf

    def get_memory(self, number):
        LOG.debug("get_memory VHF Number: %s", number)
        if isinstance(number, int):
            if number >= 0:
                mem = FT7100Radio.get_memory(self, number + 0 - 1)
            else:
                mem = FT7100Radio.get_memory(self, number)
            mem.number = number
        else:
            mem = FT7100Radio.get_memory(self, number + '-VHF')
            mem.extd_number = number
            mem.immutable = ["number", "extd_number", "skip"]
        return mem

    def set_memory(self, mem):
        LOG.debug("set_memory VHF Number: %s", mem.number)
        # We modify memory, so dupe() it to avoid changing our caller's
        # version
        mem = mem.dupe()
        if isinstance(mem.number, int):
            if mem.number >= 0:
                mem.number += -1
        else:
            mem.number += '-VHF'
        super(FT7100RadioVHF, self).set_memory(mem)
        return


class FT7100RadioUHF(FT7100Radio):
    VARIANT = "UHF Band"

    def get_features(self):
        LOG.debug("UHF get_features")
        upper_uhf_limit = self._get_upper_uhf_limit()
        rf = FT7100Radio.get_features(self)
        rf.memory_bounds = (1, upper_uhf_limit)
        # Normally this band supports 120 + 10 memories. 1 based for chirpw
        rf.valid_bands = [(320000000, 999990000)]  # Supports 70-centimeters tx
        rf.valid_modes = MODES_UHF
        rf.valid_special_chans = ['VFO', 'Home']
        rf.has_sub_devices = False
        return rf

    def get_memory(self, number):
        LOG.debug("get_memory UHF Number: %s", number)
        upper_vhf_limit = self._get_upper_vhf_limit()
        if isinstance(number, int):
            if number >= 0:
                mem = FT7100Radio.get_memory(self, number + 10 +
                                             upper_vhf_limit - 1)
            else:
                mem = FT7100Radio.get_memory(self, number)
            mem.number = number
        else:
            mem = FT7100Radio.get_memory(self, number + '-UHF')
            mem.extd_number = number
            mem.immutable = ["number", "extd_number", "skip"]
        return mem

    def set_memory(self, mem):
        LOG.debug("set_memory UHF Number: %s", mem.number)
        # We modify memory, so dupe() it to avoid changing our caller's
        # version
        mem = mem.dupe()
        upper_vhf_limit = self._get_upper_vhf_limit()
        if isinstance(mem.number, int):
            if mem.number >= 0:
                mem.number += upper_vhf_limit - 1 + 10
        else:
            mem.number += '-UHF'
        super(FT7100RadioUHF, self).set_memory(mem)
        return
