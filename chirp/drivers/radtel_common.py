from logging import Logger
import struct
from typing import Literal, Tuple, Protocol, Any, Callable

from chirp import chirp_common, errors, util

COMMAND_ACCEPT = b"\x06"
CHARSET_HEX = "0123456789ABCDEFabcdef"
BLOCK_SIZE = 0x10  # 16 bytes


class RadtelLikeRadio(Protocol):
    _fingerprint: bytes
    _magic: bytes
    _upper: int
    pipe: Any
    status_fn: Callable[[chirp_common.Status], None]

    MEM_ROWS: int

    def get_mmap(self) -> bytearray: ...


def rt_clean_buffer(radio: RadtelLikeRadio, LOG: Logger):
    radio.pipe.timeout = 0.005
    junk = radio.pipe.read(256)
    radio.pipe.timeout = 5  # 5000ms

    if junk:
        LOG.debug("Got %i bytes of junk before starting" % len(junk))


def _get_memory_address(channel_id: int) -> Tuple[int, int]:
    """Calculates the memory address for a given channel_id"""
    block = (channel_id - 1) // 16           # Determines high byte
    offset = ((channel_id - 1) % 16) * 0x10  # Determines low byte

    return (block, offset)


def _calculate_checksum(data: bytes) -> int:
    """
    Calculate the checksum for a 32-byte data block.

    (The checksum is computed as the sum of two 16-byte blocks modulo 256.)
    """
    if len(data) != 32:
        raise ValueError("Data must be exactly 32 bytes long.")

    first_block_sum = sum(data[:16]) % 256
    second_block_sum = sum(data[16:]) % 256

    return (first_block_sum + second_block_sum) % 256


def _verify_checksum(data: bytes) -> bool:
    """
    Verify data integrity by checking the checksum and length.
    """
    if len(data) != 32 + 1:
        raise ValueError("Data must be exactly 32 bytes long.")

    # Replace last byte with 0 for calculation
    calculated_checksum = _calculate_checksum(data[:-1])
    return calculated_checksum == data[-1]


def rt_read_block(
        radio: RadtelLikeRadio, channel_id: int, LOG: Logger,
        with_chksum: bool = False, send_acpt: bool = False) -> bytes:
    """Reads two memory channels from the radio starting at channel_id
    + one extra byte"""

    address = bytes(_get_memory_address(channel_id))
    # 52=read | 20 = hex(32 bytes) = length of 2 channels
    # + settings without header
    cmd = struct.pack(">BBBB", 0x52, address[0], address[1], 0x20)

    radio.pipe.write(cmd)
    hdr = radio.pipe.read(4)  # Read 4 byte header
    if not hdr:
        raise errors.RadioNoContactLikelyK1()
    data = radio.pipe.read(32)  # Read the data (0x20)
    if not data:
        raise errors.RadioNoContactLikelyK1()
    if with_chksum:
        checksum = radio.pipe.read(1)  # Read the checksum
        if not checksum:
            raise errors.RadioNoContactLikelyK1()

        # Verify checksum
        if checksum[0] != _calculate_checksum(data):
            LOG.error("Checksum mismatch for block 0x%04s:" %
                      util.hexprint(address))
            raise errors.RadioError("Checksum mismatch")

    mode, a, resp_length = struct.unpack(">BHB", hdr)
    if a != int.from_bytes(address, byteorder="big") \
            or resp_length != 32 or mode != ord("W"):
        LOG.error("Invalid answer for block 0x%04s:" % util.hexprint(address))
        LOG.debug("CMD: %s  ADDR: %04x  SIZE: %02x" % (mode, a, resp_length))
        raise errors.RadioError("Unknown response from the radio")

    if send_acpt:
        # Sending an accept after reading the first line will crash
        # the communication. The accept is sent when entering programming
        # mdoe, so before reading the first block
        if address != b"\x00\x00":
            radio.pipe.write(COMMAND_ACCEPT)
            response = radio.pipe.read(1)
            if not response:
                raise errors.RadioNoContactLikelyK1()
            elif response != COMMAND_ACCEPT:
                raise errors.RadioError("Radio refused to read block at %04s"
                                        % util.hexprint(address))

    return data


def rt_write_blocks(
    radio: RadtelLikeRadio, channel_id: int, data: bytes,
        block_count: int, LOG: Logger, with_chksum: bool = False):
    """Writes blocks of data to the radio starting at channel_id"""
    assert block_count > 0, "Block count must be greater than 0"
    assert len(data) == BLOCK_SIZE * \
        block_count, f"Data must be {BLOCK_SIZE * block_count} bytes long"

    address = bytes(_get_memory_address(channel_id))
    cmd = struct.pack(
        ">BBBB", 0x57, address[0],
        address[1],
        BLOCK_SIZE * block_count) + data

    if with_chksum:
        # Calculate checksum
        checksum = _calculate_checksum(data)
        cmd += struct.pack(">B", checksum)

    radio.pipe.write(cmd)
    response = radio.pipe.read(1)
    if not response:
        raise errors.RadioNoContactLikelyK1()
    elif response != COMMAND_ACCEPT:
        raise errors.RadioError("Radio refused to write block at %04s"
                                % util.hexprint(address))


def rt_enter_programming_mode(
        radio: RadtelLikeRadio, LOG: Logger, first_ack_length: Literal
        [1, 2] = 2) -> bytes:
    rt_clean_buffer(radio, LOG)

    radio.pipe.write(radio._magic)
    LOG.debug("Sent magic sequence")
    ack = radio.pipe.read(first_ack_length)
    if not ack:
        raise errors.RadioNoContactLikelyK1()
    LOG.debug("Received magic sequence response")
    if len(ack) != first_ack_length or (
            ack[1: 2] if first_ack_length > 1 else ack) != COMMAND_ACCEPT:
        if ack:
            LOG.error("Received: Len=%i Data=%s"
                      % (len(ack), util.hexprint(ack)))
        raise errors.RadioError("Radio refused to enter programming mode")

    radio.pipe.write(b"\x02")
    ident = radio.pipe.read(8)
    if not ident:
        raise errors.RadioNoContactLikelyK1()
    elif not ident.startswith(radio._fingerprint):
        raise errors.RadioError(
            "Radio returned unknown identification string")

    LOG.info("Radio entered programming mode")
    LOG.debug("Radio identification: %s" % util.hexprint(ident))

    radio.pipe.write(COMMAND_ACCEPT)
    ack = radio.pipe.read(1)
    if not ack:
        raise errors.RadioNoContactLikelyK1()
    elif ack != COMMAND_ACCEPT:
        if ack:
            LOG.error("Got %s" % util.hexprint(ack))
        raise errors.RadioError("Radio refused to enter programming mode")

    return ident


def rt_exit_programming_mode(
        radio: RadtelLikeRadio, LOG: Logger, with_ack: bool = False):
    try:
        radio.pipe.write(b"\x45")
        if with_ack:
            ack = radio.pipe.read(1)
            if not ack:
                LOG.debug("No response to exit programming mode")
            radio.pipe.write(b"\x02")  # Probably reboot signal
    except Exception:
        raise errors.RadioError("Radio refused to exit programming mode")


def rt_do_download(
        radio: RadtelLikeRadio,
        LOG: Logger,
        first_ack_length: Literal[1, 2],
        with_chksum=False,
        send_acpt=False) -> bytes:
    """Expects caller to exit programming mode"""

    LOG.debug("Downloading data from radio")

    status = chirp_common.Status()
    status.msg = "Downloading from radio"

    status.cur = 0
    status.max = radio._upper
    radio.status_fn(status)

    data = bytearray()

    rt_enter_programming_mode(radio, LOG, first_ack_length=first_ack_length)
    for i in range(1, radio.MEM_ROWS, 2):
        status.cur = i
        radio.status_fn(status)

        result = rt_read_block(
            radio, i, LOG, with_chksum=with_chksum, send_acpt=send_acpt)
        data.extend(result)

        LOG.debug("Downloaded memory channel %i" % i)

    LOG.debug("Downloaded %i bytes of data" % len(data))

    return bytes(data)


def rt_do_upload(
        radio: RadtelLikeRadio, LOG: Logger, chunk_size: int,
        first_ack_length: Literal[1, 2],
        with_chksum=False):
    """Expects caller to exit programming mode"""

    LOG.debug("Uploading data to radio")
    rt_enter_programming_mode(radio, LOG, first_ack_length=first_ack_length)

    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    status.cur = 0
    status.max = radio._upper
    radio.status_fn(status)

    radio_mem = radio.get_mmap()
    for i in range(1, radio.MEM_ROWS, chunk_size):
        status.cur = i
        radio.status_fn(status)

        block_offset = (i - 1) * BLOCK_SIZE
        blocks = radio_mem[block_offset:block_offset +
                           (BLOCK_SIZE * chunk_size)]
        rt_write_blocks(radio, i, blocks, chunk_size,
                        LOG, with_chksum=with_chksum)

        LOG.debug("Uploaded %i memory channels from Nr. %i" % (chunk_size, i))
