"""
Radio driver for the Boblov X3 Plus Motorcycle Helmet Radio
"""
# Copyright 2018 Robert C Jennings <rcj4747@gmail.com>
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

import logging
import struct
import time

from datetime import datetime
from textwrap import dedent

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
)

LOG = logging.getLogger(__name__)


@directory.register
class BoblovX3Plus(chirp_common.CloneModeRadio,
                   chirp_common.ExperimentalRadio):
    """Boblov X3 Plus motorcycle/cycling helmet radio"""

    VENDOR = 'Boblov'
    MODEL = 'X3Plus'
    BAUD_RATE = 9600
    CHANNELS = 16

    MEM_FORMAT = """
    #seekto 0x0010;
    struct {
        lbcd rxfreq[4];
        lbcd txfreq[4];
        lbcd rxtone[2];
        lbcd txtone[2];
        u8 unknown1:1,
           compander:1,
           scramble:1,
           skip:1,
           highpower:1,
           narrow:1,
           unknown2:1,
           bcl:1;
        u8 unknown3[3];
    } memory[16];
    #seekto 0x03C0;
    struct {
        u8 unknown1:4,
           voiceprompt:2,
           batterysaver:1,
           beep:1;
        u8 squelchlevel;
        u8 unknown2;
        u8 timeouttimer;
        u8 voxlevel;
        u8 unknown3;
        u8 unknown4;
        u8 voxdelay;
    } settings;
    """

    # Radio command data
    CMD_ACK = '\x06'
    CMD_IDENTIFY = '\x02'
    CMD_PROGRAM_ENTER = '.VKOGRAM'
    CMD_PROGRAM_EXIT = '\x62'  # 'b'
    CMD_READ = 'R'
    CMD_WRITE = 'W'

    BLOCK_SIZE = 0x08

    VOICE_LIST = ['Off', 'Chinese', 'English']
    TIMEOUTTIMER_LIST = ['Off', '30 seconds', '60 seconds', '90 seconds',
                         '120 seconds', '150 seconds', '180 seconds',
                         '210 seconds', '240 seconds', '270 seconds',
                         '300 seconds']
    VOXLEVEL_LIST = ['Off', '1', '2', '3', '4', '5', '6', '7', '8', '9']
    VOXDELAY_LIST = ['1 seconds', '2 seconds',
                     '3 seconds', '4 seconds', '5 seconds']
    X3P_POWER_LEVELS = [chirp_common.PowerLevel('Low', watts=0.5),
                        chirp_common.PowerLevel('High', watts=2.00)]

    _memsize = 0x03F0
    _ranges = [
        (0x0000, 0x03F0),
    ]

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = _(dedent("""\
            The X3Plus driver is currently experimental.

            There are no known issues but you should proceed with caution.

            Please save an unedited copy of your first successful
            download to a CHIRP Radio Images (*.img) file.
            """))
        return rp

    @classmethod
    def match_model(cls, filedata, filename):
        """Given contents of a stored file (@filedata), return True if
          this radio driver handles the represented model"""

        if len(filedata) != cls._memsize:
            LOG.debug('Boblov_x3plus: match_model: size mismatch')
            return False

        LOG.debug('Boblov_x3plus: match_model: size matches')

        if 'P310' in filedata[0x03D0:0x03D8]:
            LOG.debug('Boblov_x3plus: match_model: radio ID matches')
            return True

        LOG.debug('Boblov_x3plus: match_model: no radio ID match')
        return False

    def get_features(self):
        """Return a RadioFeatures object for this radio"""

        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.valid_modes = ['NFM', 'FM']  # 12.5 KHz, 25 kHz.
        rf.valid_power_levels = self.X3P_POWER_LEVELS
        rf.valid_skips = ['', 'S']
        rf.valid_tmodes = ['', 'Tone', 'TSQL', 'DTCS', 'Cross']
        rf.valid_duplexes = ['', '-', '+', 'split', 'off']
        rf.can_odd_split = True
        rf.has_rx_dtcs = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_cross_modes = [
            'Tone->Tone',
            'DTCS->',
            '->DTCS',
            'Tone->DTCS',
            'DTCS->Tone',
            '->Tone',
            'DTCS->DTCS']
        rf.has_tuning_step = False
        rf.has_bank = False
        rf.has_name = False
        rf.memory_bounds = (1, self.CHANNELS)
        rf.valid_bands = [(400000000, 470000000)]
        return rf

    def process_mmap(self):
        """Process a newly-loaded or downloaded memory map"""
        self._memobj = bitwise.parse(self.MEM_FORMAT, self._mmap)

    def sync_in(self):
        "Initiate a radio-to-PC clone operation"

        LOG.debug('Cloning from radio')
        status = chirp_common.Status()
        status.msg = 'Cloning from radio'
        status.cur = 0
        status.max = self._memsize
        self.status_fn(status)

        self._enter_programming_mode()

        data = ''
        for addr in range(0, self._memsize, self.BLOCK_SIZE):
            status.cur = addr + self.BLOCK_SIZE
            self.status_fn(status)

            block = self._read_block(addr, self.BLOCK_SIZE)
            data += block

            LOG.debug('Address: %04x', addr)
            LOG.debug(util.hexprint(block))

        self._exit_programming_mode()

        self._mmap = memmap.MemoryMap(data)
        self.process_mmap()

    def sync_out(self):
        "Initiate a PC-to-radio clone operation"

        LOG.debug('Upload to radio')
        status = chirp_common.Status()
        status.msg = 'Uploading to radio'
        status.cur = 0
        status.max = self._memsize
        self.status_fn(status)

        self._enter_programming_mode()

        for start_addr, end_addr in self._ranges:
            for addr in range(start_addr, end_addr, self.BLOCK_SIZE):
                status.cur = addr + self.BLOCK_SIZE
                self.status_fn(status)

                self._write_block(addr, self.BLOCK_SIZE)

        self._exit_programming_mode()

    def get_raw_memory(self, number):
        """Return a raw string describing the memory at @number"""
        return repr(self._memobj.memory[number - 1])

    @staticmethod
    def _decode_tone(val):
        val = int(val)
        if val == 16665:
            return '', None, None
        elif val >= 12000:
            return 'DTCS', val - 12000, 'R'
        elif val >= 8000:
            return 'DTCS', val - 8000, 'N'

        return 'Tone', val / 10.0, None

    @staticmethod
    def _encode_tone(memval, mode, value, pol):
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
            raise Exception('Internal error: invalid mode `%s`' % mode)

    def get_memory(self, number):
        """Return a Memory object for the memory at location @number"""
        try:
            rmem = self._memobj.memory[number - 1]
        except KeyError:
            raise errors.InvalidMemoryLocation('Unknown channel %s' % number)

        if number < 1 or number > self.CHANNELS:
            raise errors.InvalidMemoryLocation(
                'Channel number must be 1 and %s' % self.CHANNELS)

        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = int(rmem.rxfreq) * 10

        # A blank (0MHz) or 0xFFFFFFFF frequency is considered empty
        if mem.freq == 0 or rmem.rxfreq.get_raw() == '\xFF\xFF\xFF\xFF':
            LOG.debug('empty channel %d', number)
            mem.freq = 0
            mem.empty = True
            return mem

        if rmem.txfreq.get_raw() == '\xFF\xFF\xFF\xFF':
            mem.duplex = 'off'
            mem.offset = 0
        elif int(rmem.rxfreq) == int(rmem.txfreq):
            mem.duplex = ''
            mem.offset = 0
        else:
            mem.duplex = '-' if int(rmem.rxfreq) > int(rmem.txfreq) else '+'
            mem.offset = abs(int(rmem.rxfreq) - int(rmem.txfreq)) * 10

        mem.mode = 'NFM' if rmem.narrow else 'FM'
        mem.skip = 'S' if rmem.skip else ''
        mem.power = self.X3P_POWER_LEVELS[rmem.highpower]

        txtone = self._decode_tone(rmem.txtone)
        rxtone = self._decode_tone(rmem.rxtone)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

        mem.extra = RadioSettingGroup('Extra', 'extra')
        mem.extra.append(RadioSetting('bcl', 'Busy Channel Lockout',
                                      RadioSettingValueBoolean(
                                          current=(not rmem.bcl))))
        mem.extra.append(RadioSetting('scramble', 'Scramble',
                                      RadioSettingValueBoolean(
                                          current=(not rmem.scramble))))
        mem.extra.append(RadioSetting('compander', 'Compander',
                                      RadioSettingValueBoolean(
                                          current=(not rmem.compander))))

        return mem

    def set_memory(self, memory):
        """Set the memory object @memory"""
        rmem = self._memobj.memory[memory.number - 1]

        if memory.empty:
            rmem.set_raw('\xFF' * (rmem.size() / 8))
            return

        rmem.rxfreq = memory.freq / 10

        set_txtone = True
        if memory.duplex == 'off':
            for i in range(0, 4):
                rmem.txfreq[i].set_raw('\xFF')
                # If recieve only then txtone value should be none
                self._encode_tone(rmem.txtone, mode='', value=None, pol=None)
                set_txtone = False
        elif memory.duplex == 'split':
            rmem.txfreq = memory.offset / 10
        elif memory.duplex == '+':
            rmem.txfreq = (memory.freq + memory.offset) / 10
        elif memory.duplex == '-':
            rmem.txfreq = (memory.freq - memory.offset) / 10
        else:
            rmem.txfreq = memory.freq / 10

        txtone, rxtone = chirp_common.split_tone_encode(memory)
        if set_txtone:
            self._encode_tone(rmem.txtone, *txtone)
        self._encode_tone(rmem.rxtone, *rxtone)

        rmem.narrow = 'N' in memory.mode
        rmem.skip = memory.skip == 'S'

        for setting in memory.extra:
            # NOTE: Only three settings right now, all are inverted
            setattr(rmem, setting.get_name(), not int(setting.value))

    def get_settings(self):
        """
        Return a RadioSettings list containing one or more RadioSettingGroup
        or RadioSetting objects.  These represent general settings that can
        be adjusted on the radio.
        """
        cur = self._memobj.settings
        basic = RadioSettingGroup('basic', 'Basic Settings')
        rs = RadioSetting('squelchlevel', 'Squelch level',
                          RadioSettingValueInteger(
                              minval=0, maxval=9,
                              current=cur.squelchlevel))
        basic.append(rs)
        rs = RadioSetting('timeouttimer', 'Timeout timer',
                          RadioSettingValueList(
                            options=self.TIMEOUTTIMER_LIST,
                            current=self.TIMEOUTTIMER_LIST[cur.timeouttimer]))
        basic.append(rs)
        rs = RadioSetting('voiceprompt', 'Voice prompt',
                          RadioSettingValueList(
                              options=self.VOICE_LIST,
                              current=self.VOICE_LIST[cur.voiceprompt]))
        basic.append(rs)
        rs = RadioSetting('voxlevel', 'Vox level',
                          RadioSettingValueList(
                              options=self.VOXLEVEL_LIST,
                              current=self.VOXLEVEL_LIST[cur.voxlevel]))
        basic.append(rs)
        rs = RadioSetting('voxdelay', 'VOX delay',
                          RadioSettingValueList(
                              options=self.VOXDELAY_LIST,
                              current=self.VOXDELAY_LIST[cur.voxdelay]))
        basic.append(rs)
        basic.append(RadioSetting('batterysaver', 'Battery saver',
                                  RadioSettingValueBoolean(
                                      current=cur.batterysaver)))
        basic.append(RadioSetting('beep', 'Beep',
                                  RadioSettingValueBoolean(
                                      current=cur.beep)))
        return RadioSettings(basic)

    def set_settings(self, settings):
        """
        Accepts the top-level RadioSettingGroup returned from
        get_settings() and adjusts the values in the radio accordingly.
        This function expects the entire RadioSettingGroup hierarchy
        returned from get_settings().
        """
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if '.' in element.get_name():
                        bits = element.get_name().split('.')
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug('Using apply callback')
                        element.run_apply_callback()
                    else:
                        LOG.debug('Setting %s = %s', setting, element.value)
                        setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    def _write(self, data, timeout=3):
        """
        Write data to the serial port and consume the echoed response

        The radio echos the data it is sent before replying.  Send the
        data to the radio, consume the reply, and ensure that the reply
        is the same as the data sent.
        """

        serial = self.pipe
        expected = len(data)
        resp = b''
        start = datetime.now()

        # LOG.debug('WRITE(%02d): %s', expected, util.hexprint(data).rstrip())
        serial.write(data)
        while True:
            if not expected:
                break
            rbytes = serial.read(expected)
            resp += rbytes
            expected -= len(rbytes)
            if (datetime.now() - start).seconds > timeout:
                raise errors.RadioError('Timeout while reading from radio')
        if resp != data:
            raise errors.RadioError('Echoed response did not match sent data')

    def _read(self, length, timeout=3):
        """Read data from the serial port"""

        resp = b''
        serial = self.pipe
        remaining = length
        start = datetime.now()

        if not remaining:
            return resp

        while True:
            rbytes = serial.read(remaining)
            resp += rbytes
            remaining -= len(rbytes)
            if not remaining:
                break
            if (datetime.now() - start).seconds > timeout:
                raise errors.RadioError('Timeout while reading from radio')
            time.sleep(0.1)

        # LOG.debug('READ(%02d):  %s', length, util.hexprint(resp).rstrip())
        return resp

    def _read_block(self, block_addr, block_size):

        LOG.debug('Reading block %04x...', block_addr)
        cmd = struct.pack('>cHb', self.CMD_READ, block_addr,
                          block_size)
        resp_prefix = self.CMD_WRITE + cmd[1:]

        try:
            msg = ('Failed to write command to radio for block '
                   'read at %04x' % block_addr)
            self._write(cmd)

            msg = ('Failed to read response from radio for block '
                   'read at %04x' % block_addr)
            response = self._read(len(cmd) + block_size)

            if response[:len(cmd)] != resp_prefix:
                raise errors.RadioError('Error reading block %04x, '
                                        'Command not returned.' % (block_addr))

            msg = ('Failed to write ACK to radio after block read at '
                   '%04x' % block_addr)
            self._write(self.CMD_ACK)

            msg = ('Failed to read ACK from radio after block read at '
                   '%04x' % block_addr)
            ack = self._read(1)
        except Exception:
            LOG.debug(msg, exc_info=True)
            raise errors.RadioError(msg)

        if ack != self.CMD_ACK:
            raise errors.RadioError('No ACK reading block '
                                    '%04x.' % (block_addr))

        return response[len(cmd):]

    def _write_block(self, block_addr, block_size):

        cmd = struct.pack('>cHb', self.CMD_WRITE, block_addr, block_size)
        data = self.get_mmap()[block_addr:block_addr + 8]

        LOG.debug('Writing Data:\n%s%s',
                  util.hexprint(cmd), util.hexprint(data))

        try:
            self._write(cmd + data)
            if self._read(1) != self.CMD_ACK:
                raise Exception('No ACK')
        except Exception:
            msg = 'Failed to send block to radio at %04x' % block_addr
            LOG.debug(msg, exc_info=True)
            raise errors.RadioError(msg)

    def _enter_programming_mode(self):

        LOG.debug('Entering programming mode')
        try:
            msg = 'Error communicating with radio entering programming mode.'
            self._write(self.CMD_PROGRAM_ENTER)
            time.sleep(0.5)
            ack = self._read(1)

            if not ack:
                raise errors.RadioError('No response from radio')
            elif ack != self.CMD_ACK:
                raise errors.RadioError('Radio refused to enter '
                                        'programming mode')

            msg = 'Error communicating with radio during identification'
            self._write(self.CMD_IDENTIFY)
            ident = self._read(8)

            if not ident.startswith('SMP558'):
                LOG.debug(util.hexprint(ident))
                raise errors.RadioError('Radio returned unknown ID string')

            msg = ('Error communicating with radio while querying '
                   'model identifier')
            self._write(self.CMD_ACK)

            msg = 'Error communicating with radio on final handshake'
            ack = self._read(1)

            if ack != self.CMD_ACK:
                raise errors.RadioError('Radio refused to enter programming '
                                        'mode failed on final handshake.')
        except Exception:
            LOG.debug(msg, exc_info=True)
            raise errors.RadioError(msg)

    def _exit_programming_mode(self):
        try:
            self._write(self.CMD_PROGRAM_EXIT)
        except Exception:
            msg = 'Radio refused to exit programming mode'
            LOG.debug(msg, exc_info=True)
            raise errors.RadioError(msg)
        LOG.debug('Exited programming mode')
