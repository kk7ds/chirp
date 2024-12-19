# Copyright 2024 Marcos Del Sol Vives <marcos@orca.pet>
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

from collections import namedtuple
import logging
import struct
import time
from chirp import chirp_common, directory, errors, memmap
from chirp import bitwise
from chirp.drivers import baofeng_common
from chirp.settings import (RadioSetting, RadioSettingGroup,
                            RadioSettingValueBoolean,
                            RadioSettingValueList)


LOG = logging.getLogger(__name__)

CMD_ACK = b'\x06'
CMD_READ = b'R'
CMD_WRITE = b'W'
CMD_EXIT = b'E'

MemoryChunk = namedtuple('MemoryChunk', ['start', 'end', 'read_only'])

ProtoVersion = namedtuple('ProtoVersion',
                          ['chan_count', 'serial_magic', 'mem_chunks'])

PROTO_A = ProtoVersion(
    chan_count=16,
    serial_magic=b'\x80\x82',
    mem_chunks=[
        MemoryChunk(start=0x000, end=0x10F, read_only=False),
        MemoryChunk(start=0x2B0, end=0x2BF, read_only=False),
        MemoryChunk(start=0x330, end=0x33F, read_only=True),
        MemoryChunk(start=0x380, end=0x3DF, read_only=False),
    ],
)
PROTO_B = ProtoVersion(
    chan_count=16,
    serial_magic=b'\x80\x82',
    mem_chunks=PROTO_A.mem_chunks,
)
PROTO_C = ProtoVersion(
    chan_count=16,
    serial_magic=b'\x20\x22',
    mem_chunks=PROTO_A.mem_chunks,
)
PROTO_D = ProtoVersion(
    chan_count=30,
    serial_magic=b'\x80\x82',
    mem_chunks=[
        MemoryChunk(start=0x000, end=0x1EF, read_only=False),
        MemoryChunk(start=0x2B0, end=0x2BF, read_only=False),
        MemoryChunk(start=0x330, end=0x33F, read_only=True),
        MemoryChunk(start=0x380, end=0x3DF, read_only=False),
    ],
)


class BaofengDigital(chirp_common.CloneModeRadio,
                     chirp_common.ExperimentalRadio):
    """Base for all digital radios from Fujian Baofeng Electronics Co. Ltd."""
    VENDOR = "Baofeng"
    BAUD_RATE = 9600

    MEM_FORMAT = """
        #seekto 0x0010;
        struct {{
            lbcd rx_freq[4];
            lbcd tx_freq[4];
            lbcd rx_tone[2];
            lbcd tx_tone[2];
            u8 hopping:1,
               unused1:2,
               scan:1,
               high_power:1,
               narrow:1,
               digital:1,
               bcl_disabled:1;
            u8 unused2:3,
               encryption_key:5;
            u16 unused3;
        }} memory[{chan_count}];
    """

    _PREAMBLE_CMDS = [
        (b'\x02', b'P3107\xf7\x00\x00'),
        (CMD_ACK, CMD_ACK),
        (b'R\x01\x30\x08', b'W\x01\x30\x08\xff\xff\xff\xff\xff\xff\xff\xff'),
        (CMD_ACK, CMD_ACK),
    ]

    _WRITE_PREAMBLE_CMDS = [
        (b'E', b'F'),
        (b'\x02\x80\x82OGRAM', CMD_ACK),
        (b'\x02', b'P3107\xf7\x00\x00'),
        (CMD_ACK, CMD_ACK),
    ]

    _VOICES_PER_REGION = {
        0x00: ('English', 'Chinese'),
        0x01: ('Chinese', 'Russian'),
        0x02: ('Russian', 'English'),
        0x03: ('Arabic', 'English'),
        0x04: ('Arabic', 'Chinese'),
        0x05: ('Arabic', 'Russian'),
        0x06: ('Chinese', 'Portuguese'),
        0x07: ('English', 'Portuguese'),
        0x08: ('Chinese', 'Spanish'),
        0x09: ('English', 'Spanish'),
        0x0A: ('Chinese', 'German'),
        0x0B: ('English', 'German'),
        0x0C: ('Chinese', 'French'),
        0x0D: ('English', 'French'),
    }

    _ENC_OPTS = ['None (analog)'] + [str(x) for x in range(32)]

    @property
    def _memsize(self):
        return self._proto.mem_chunks[-1].end + 1

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_rx_dtcs = True
        rf.has_bank = False
        rf.has_name = False
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_cross = True
        rf.memory_bounds = (1, self._proto.chan_count)
        rf.valid_bands = self.VALID_BANDS
        rf.valid_duplexes = ["", "+", "-", "split"]
        rf.valid_modes = ['FM', 'NFM']
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_tuning_steps = [2.5, 6.25, 5.0]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->Tone",
            "Tone->DTCS",
            "DTCS->Tone",
            "DTCS->",
            "->Tone",
            "->DTCS",
            "DTCS->DTCS",
        ]
        return rf

    def _get_radio_id(self):
        for attempt in range(5):
            try:
                baofeng_common._clean_buffer(self)

                self.pipe.write(b'\x02prOGRAM')
                resp = self.pipe.read(4)
                if len(resp) != 4:
                    raise errors.RadioError(
                        'Radio did not send identification')
                return resp
            except errors.RadioError:
                # Don't wait if already last attempt
                if attempt == 4:
                    raise
                self._exit_programming()
                time.sleep(1)

    def _enter_programming(self, write):
        radio_id = self._get_radio_id()
        if radio_id[1] != self._serial_id:
            raise errors.RadioError('Detected a different radio model')

        self._metadata['fw_region'] = radio_id[0]
        self._metadata['fw_version'] = radio_id[2] * 0x100 + radio_id[3]

        # Issue protocol-specific command
        self.pipe.write(b'\x02' + self._proto.serial_magic + b'OGRAM')
        if self.pipe.read(1) != CMD_ACK:
            raise errors.RadioError('No ACK on protocol-specific command')

        # Issue fixed commands and check their values
        if write:
            preamble = self._PREAMBLE_CMDS + self._WRITE_PREAMBLE_CMDS
        else:
            preamble = self._PREAMBLE_CMDS
        for step, cmd in enumerate(preamble, 1):
            self.pipe.write(cmd[0])
            if self.pipe.read(len(cmd[1])) != cmd[1]:
                raise errors.RadioError(
                    f'Radio replied incorrectly to preamble step {step}')

    def _clean_buffer(self):
        self.pipe.timeout = 0.001
        self.pipe.read(256)
        self.pipe.timeout = 0.1

    def _exit_programming(self):
        try:
            self.pipe.write(CMD_EXIT)
        except Exception:
            pass

    def sync_in(self):
        try:
            self._enter_programming(False)

            memory = memmap.MemoryMapBytes(b"\xFF" * self._memsize)
            for chunk in self._proto.mem_chunks:
                for addr in range(chunk.start, chunk.end, 8):
                    self.pipe.write(struct.pack('>cHB', CMD_READ, addr, 8))
                    reply = self.pipe.read(12)
                    if len(reply) != 12:
                        raise errors.RadioError(
                            f'Failed to read block at 0x{addr:03x}')

                    self.pipe.write(CMD_ACK)
                    if self.pipe.read(1) != CMD_ACK:
                        raise errors.RadioError(
                            f'No ACK after reading from 0x{addr:03x}')

                    memory.set(addr, reply[4:])
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                f'Failed to communicate with the radio: {e}')
        finally:
            self._exit_programming()

        self._mmap = memory
        self.process_mmap()

    def sync_out(self):
        try:
            self._enter_programming(True)

            for chunk in self._proto.mem_chunks:
                if chunk.read_only:
                    continue

                for addr in range(chunk.start, chunk.end, 8):
                    frame = (
                        struct.pack('>cHB', CMD_WRITE, addr, 8) +
                        self._mmap.get(addr, 8)
                    )
                    self.pipe.write(frame)

                    if self.pipe.read(1) != CMD_ACK:
                        raise errors.RadioError(
                            f'Not ACK after writing to 0x{addr:03x}')
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(
                f'Failed to communicate with the radio: {e}')
        finally:
            self._exit_programming()

    def process_mmap(self):
        mem_fmt = self.MEM_FORMAT.format(chan_count=self._proto.chan_count)
        self._memobj = bitwise.parse(mem_fmt, self._mmap)

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number])

    def _get_squelch(self, elem):
        # Get raw and check if unset
        if elem.get_raw() in (b'\x00\x00', b'\xFF\xFF'):
            return ('', None, 'N')

        # Get flags, unset them so we can parse as BCD, then restore them
        flags = elem[1].get_bits(0xC0)
        elem[1].clr_bits(0xC0)
        value = int(elem)
        elem[1].set_bits(flags)

        # DTCS if bit 15 is set
        if flags & 0x80:
            return ('DTCS', value, flags & 0x40 and 'R' or 'N')
        else:
            # Parse as CTCSS frequency * 10
            return ('Tone', value / 10.0, 'N')

    def get_memory(self, number):
        raw = self._memobj.memory[number - 1]

        mem = chirp_common.Memory()
        mem.number = number
        mem.empty = raw.rx_freq.get_raw() in (
            b'\x00\x00\x00\x00', b'\xFF\xFF\xFF\xFF'
        )

        bcl = hopping = False
        enc_idx = 0
        if not mem.empty:
            rx_freq = int(raw.rx_freq) * 10
            tx_freq = int(raw.tx_freq) * 10

            mem.freq = rx_freq
            offset = tx_freq - rx_freq
            if offset == 0:
                mem.duplex = ''
                mem.offset = 0
            elif abs(offset) < 10000000:
                mem.duplex = '-' if offset < 0 else '+'
                mem.offset = abs(offset)
            else:
                mem.duplex = 'split'
                mem.offset = tx_freq

            mem.mode = raw.narrow and 'NFM' or 'FM'
            if raw.digital:
                mem.tmode = ''
                mem.dtcs_polarity = 'NN'
                enc_idx = raw.encryption_key + 1
            else:
                hopping = raw.hopping

                tx_tmode, tx_tvalue, tx_tpol = self._get_squelch(raw.tx_tone)
                if tx_tmode == 'Tone':
                    mem.rtone = tx_tvalue
                elif tx_tmode == 'DTCS':
                    mem.dtcs = tx_tvalue

                rx_tmode, rx_tvalue, rx_tpol = self._get_squelch(raw.rx_tone)
                if rx_tmode == 'Tone':
                    mem.ctone = rx_tvalue
                elif rx_tmode == 'DTCS':
                    mem.rx_dtcs = rx_tvalue

                if tx_tmode == 'Tone' and rx_tmode == '':
                    mem.tmode = 'Tone'
                elif tx_tmode and tx_tmode == rx_tmode and \
                        tx_tvalue == rx_tvalue:
                    mem.tmode = tx_tmode == 'Tone' and 'TSQL' or 'DTCS'
                elif tx_tmode or rx_tmode:
                    mem.tmode = 'Cross'
                    mem.cross_mode = f'{tx_tmode}->{rx_tmode}'

                mem.dtcs_polarity = tx_tpol + rx_tpol

            mem.power = self.POWER_LEVELS[raw.high_power]
            mem.skip = '' if raw.scan else 'S'
            bcl = not raw.bcl_disabled

        mem.extra = RadioSettingGroup("Extra", "extra")

        rs = RadioSetting("bcl", "BCL",
                          RadioSettingValueBoolean(bcl))
        rs.set_doc('Busy channel lockout.')
        mem.extra.append(rs)

        rs = RadioSetting("encryption_key", "Encryption key",
                          RadioSettingValueList(self._ENC_OPTS,
                                                current_index=enc_idx))
        rs.set_doc('Encryption key for the digital mode. ' +
                   'If none is selected, analog audio will be used.')
        mem.extra.append(rs)

        rs = RadioSetting("hopping", "Hopping",
                          RadioSettingValueBoolean(hopping))
        rs.set_doc('Frequency hopping. Only supported on analog modes.')
        mem.extra.append(rs)

        return mem

    def _set_no_tone(self, elem):
        elem.set_raw(b'\xFF\xFF')

    def _set_ctcss(self, freq, elem):
        elem.set_value(int(freq * 10))

    def _set_dtcs(self, code, polarity, elem):
        elem.set_value(code)
        elem[1].set_bits(0x80)
        if polarity == 'R':
            elem[1].set_bits(0x40)

    def _set_squelch(self, mode, ctcss_freq, dtcs_code, dtcs_polarity, elem):
        if mode == 'Tone':
            self._set_ctcss(ctcss_freq, elem)
        elif mode == 'DTCS':
            self._set_dtcs(dtcs_code, dtcs_polarity, elem)
        else:
            self._set_no_tone(elem)

    def set_memory(self, mem):
        raw = self._memobj.memory[mem.number - 1]
        if mem.empty:
            raw.fill_raw(b'\xFF')
            return

        raw.fill_raw(b'\x00')

        raw.rx_freq = mem.freq // 10
        if mem.duplex == '':
            raw.tx_freq = mem.freq // 10
        elif mem.duplex == 'split':
            raw.tx_freq = mem.offset // 10
        elif mem.duplex == '-':
            raw.tx_freq = (mem.freq - mem.offset) // 10
        elif mem.duplex == '+':
            raw.tx_freq = (mem.freq + mem.offset) // 10
        else:
            raise errors.RadioError('Unsupported duplex mode %r' % mem.duplex)

        raw.narrow = mem.mode == 'NFM'
        try:
            raw.high_power = self.POWER_LEVELS.index(mem.power)
        except ValueError:
            raw.high_power = 1
        raw.scan = mem.skip != 'S'

        raw.bcl_disabled = 1
        raw.digital = 0
        for item in mem.extra:
            if item.get_name() == 'bcl':
                raw.bcl_disabled = not item.value
            elif item.get_name() == 'encryption_key':
                idx = self._ENC_OPTS.index(item.value)
                if idx == 0:
                    raw.digital = 0
                else:
                    raw.digital = 1
                    raw.encryption_key = idx - 1
            elif item.get_name() == 'hopping' and not raw.digital:
                raw.hopping = item.value

        if raw.digital:
            self._set_no_tone(raw.tx_tone)
            self._set_no_tone(raw.rx_tone)
        elif mem.tmode == 'Tone':
            self._set_ctcss(mem.rtone, raw.tx_tone)
            self._set_no_tone(raw.rx_tone)
        elif mem.tmode == 'TSQL':
            self._set_ctcss(mem.ctone, raw.tx_tone)
            self._set_ctcss(mem.ctone, raw.rx_tone)
        elif mem.tmode == 'DTCS':
            # According to the documentation we should use ".rx_dtcs" because
            # "has_rx_dtcs" is set. However, the code does not match the docs,
            # and we have to use ".dtcs".
            self._set_dtcs(mem.dtcs, mem.dtcs_polarity[0], raw.tx_tone)
            self._set_dtcs(mem.dtcs, mem.dtcs_polarity[1], raw.rx_tone)
        elif mem.tmode == 'Cross':
            tx_tmode, rx_tmode = mem.cross_mode.split('->', 2)
            self._set_squelch(tx_tmode, mem.rtone, mem.dtcs,
                              mem.dtcs_polarity[0], raw.tx_tone)
            self._set_squelch(rx_tmode, mem.ctone, mem.rx_dtcs,
                              mem.dtcs_polarity[1], raw.rx_tone)


@directory.register
class BaofengW31D(BaofengDigital):
    """Baofeng W31D"""
    MODEL = 'W31D'
    VALID_BANDS = [(400000000, 480000000)]
    POWER_LEVELS = [
        chirp_common.PowerLevel("Low", watts=0.5),
        chirp_common.PowerLevel("High", watts=2.00),
    ]
    _serial_id = 0x04
    _proto = PROTO_D
