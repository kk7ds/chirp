# Copyright 2026
#
# Driver for WLN KD-C1S and compatible radios (SMP558 architecture).
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

import struct
import time
import logging

from chirp import chirp_common, directory, errors, memmap
from chirp.drivers import radtel_t18 as t18

LOG = logging.getLogger(__name__)


class KDC1PlusAlias(chirp_common.Alias):
    VENDOR = "WLN"
    MODEL = "KD-C1 Plus"


class KDC1NewAlias(chirp_common.Alias):
    VENDOR = "WLN"
    MODEL = "KD-C1 (SMP558)"


@directory.register
class WLNKDC1SRadio(t18.T18Radio):
    """WLN KD-C1S"""

    VENDOR = "WLN"
    MODEL = "KD-C1S"
    ALIASES = [KDC1PlusAlias, KDC1NewAlias]

    BLOCK_SIZE = 0x40
    CMD_EXIT = b"b"
    ACK_BLOCK = True

    _magic = b"PROGRAM"
    _fingerprint = [b"S\x02", b"\x53\x02", b"SMP558"]

    _upper = 16
    _mem_params = _upper
    _frs = _frs16 = _murs = _pmr = _gmrs = False
    _echo = False
    _reserved = False

    _ranges = [
        (0x0000, 0x0400),
    ]
    _memsize = 0x0400

    VALID_BANDS = [(400000000, 470000000)]

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=2.00),
                    chirp_common.PowerLevel("Low",  watts=0.50)]

    def _do_handshake(self, pipe):
        try:
            pipe.dtr = True
            pipe.rts = True
            time.sleep(0.15)
            pipe.reset_input_buffer()
            pipe.reset_output_buffer()

            # Step 1: Send PROGRAM handshake command
            pipe.write(b"\x02PROGRAM")
            pipe.read(1)
            pipe.read(pipe.in_waiting or 0)

            # Step 2: Request Ident
            pipe.write(b"\x02")
            ident = pipe.read(8)
            if not ident:
                raise errors.RadioNoResponse("No response from radio")

            for fp in self._fingerprint:
                if ident.startswith(fp):
                    break
            else:
                raise errors.RadioError("Radio identification failed")

            pipe.write(t18.CMD_ACK)
            pipe.read(1)

            # Step 3: Auth step
            pipe.write(b"\x05")
            pipe.read(6)
            pipe.write(t18.CMD_ACK)
            pipe.read(1)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(f"Error communicating with radio: {e}")

    def sync_in(self):
        pipe = self.pipe
        old_timeout = getattr(pipe, "timeout", 0.25)
        pipe.timeout = 1.0

        try:
            self._do_handshake(pipe)

            status = chirp_common.Status()
            status.msg = "Cloning from radio"
            status.cur = 0
            status.max = self._memsize

            full_mem = bytearray(self._memsize)
            for addr in range(0x0000, self._memsize, self.BLOCK_SIZE):
                status.cur = addr + self.BLOCK_SIZE
                self.status_fn(status)

                cmd = struct.pack(">cHb", b'R', addr, self.BLOCK_SIZE)
                try:
                    pipe.write(cmd)
                    resp = pipe.read(4 + self.BLOCK_SIZE)
                except Exception as e:
                    raise errors.RadioError(f"Failed reading block: {e}")

                if len(resp) == (4 + self.BLOCK_SIZE) and resp[:1] == b'W':
                    full_mem[addr:addr + self.BLOCK_SIZE] = resp[4:]
                else:
                    raise errors.RadioError(
                        f"Failed reading block at 0x{addr:04X}")

                try:
                    pipe.write(t18.CMD_ACK)
                except Exception as e:
                    raise errors.RadioError(f"Failed sending ACK: {e}")
                time.sleep(0.02)

            try:
                pipe.write(self.CMD_EXIT)
            except Exception:
                pass
            self._mmap = memmap.MemoryMapBytes(bytes(full_mem))
            self.process_mmap()
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(f"Clone failed: {e}")
        finally:
            pipe.timeout = old_timeout

    def sync_out(self):
        pipe = self.pipe
        old_timeout = getattr(pipe, "timeout", 0.25)
        pipe.timeout = 1.0

        try:
            self._do_handshake(pipe)

            mem = self.get_mmap()
            status = chirp_common.Status()
            status.msg = "Uploading to radio"
            status.cur = 0
            status.max = 0x03F0

            for addr in range(0x0000, 0x03F0, 8):
                status.cur = addr + 8
                self.status_fn(status)

                chunk = mem[addr:addr + 8]
                cmd = struct.pack(">cHb", b'W', addr, 8) + chunk
                try:
                    pipe.write(cmd)
                    ack = pipe.read(1)
                except Exception as e:
                    raise errors.RadioError(f"Failed writing block: {e}")

                if ack != t18.CMD_ACK:
                    raise errors.RadioError(
                        f"Failed writing block at 0x{addr:04X}")

            try:
                pipe.write(self.CMD_EXIT)
            except Exception:
                pass
            time.sleep(0.3)
        except errors.RadioError:
            raise
        except Exception as e:
            raise errors.RadioError(f"Upload failed: {e}")
        finally:
            pipe.timeout = old_timeout
