from builtins import bytes
import unittest
import io

from chirp import errors
import chirp.drivers.anytone_clone as ac

MODEL_VERSION = b"Ianytone" + b"\x00" * (16 - 8)
SIXTEEN_BYTES = (
    b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x10\x11\x12\x13\x14\x15"
)
THIRTYTWO_BYTES = (
    b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x10\x11\x12\x13\x14\x15"
    b"\x16\x17\x18\x19\x20\x21\x22\x23\x24\x25\x26\x27\x28\x29\x30\x31"
)
CHECKSUM_16_BYTES = b"\x9C"
CHECKSUM_32_BYTES = b"\xE8"


class FakeProtocol(ac.RadioCommunicationProtocol):
    def __init__(
        self, pipe=None, block_size: int = 16, file_ident=b"faker"
    ) -> None:
        super().__init__(pipe, block_size, file_ident, echos_write=False)
        if not pipe:
            pipe = io.BytesIO(b"fake data")

    def start_session(self):
        pass

    def end_session(self):
        pass

    def inquire_model_number(self) -> bytes:
        return b"faker"


class TestRadioCommunicationProtocol(unittest.TestCase):
    """Tests the communications protocol base class (radio-agnostic)."""

    def test_verify_radio_ident_single(self):
        proto = FakeProtocol()
        proto._verify_radio_ident()

    def test_verify_radio_ident_double(self):
        proto = FakeProtocol(file_ident=[b"faker", b"faker1"])
        proto._verify_radio_ident()

    def test_verify_radio_ident_no_such(self):
        proto = FakeProtocol(file_ident=[b"faker1", b"faker2"])
        with self.assertRaises(
            errors.RadioError, msg="Unsupported model for this driver: faker2"
        ):
            proto._verify_radio_ident()

    def test_read_bytes(self):
        with FakeProtocol(pipe=io.BytesIO(THIRTYTWO_BYTES)) as proto:
            self.assertEquals(b"\x00\x01\x02\x03", proto.read_bytes(4))
            self.assertEquals(b"\x04\x05", proto.read_bytes(2))

    def test_read_bytes_short(self):
        with FakeProtocol(pipe=io.BytesIO(THIRTYTWO_BYTES)) as proto:
            with self.assertRaises(
                errors.RadioError, msg="Short read from radio"
            ):
                proto.read_bytes(33)

    def test_write_bytes(self):
        proto = FakeProtocol(pipe=io.BytesIO(THIRTYTWO_BYTES))
        self.assertEquals(b"\x00\x01\x02\x03", proto.read_bytes(4))

        # overwrites the 5th and 6th bytes and advances the cursor
        proto.write_bytes(b"\xFF\xFF")

        self.assertEquals(b"\x06", proto.read_bytes(1))


class TestAnytoneProtocol(unittest.TestCase):
    """Tests the non-radio-specific aspects of the communications protocol
    base class."""

    def test_checksum(self):
        self.assertEquals(156, ac.AnytoneProtocol.checksum(SIXTEEN_BYTES))
        self.assertEquals(200, ac.AnytoneProtocol.checksum(THIRTYTWO_BYTES))

    def test_read_one_frame(self):
        CHECKSUM_BLOCK_1 = bytes(
            (ac.AnytoneProtocol.checksum(b"\x00\x00\x10" + SIXTEEN_BYTES),)
        )

        SESSION = (
            # space to write the start command
            ac.AnytoneProtocol.CMD_BEGIN_PROGRAMMING_SESSION
            +
            # read the ack
            ac.AnytoneProtocol.ACK_CLEAN_START
            +
            # space to write the inquire command
            ac.AnytoneProtocol.CMD_INQUIRE_MODEL
            +
            # read the model number response
            MODEL_VERSION
            +
            # space to write the read-frame command
            b"R\x00\x00\x10"
            +
            # read the frame: header, data, checksum, ack
            b"R\x00\x00\x10"
            + SIXTEEN_BYTES
            + CHECKSUM_BLOCK_1
            + ac.AnytoneProtocol.ACK
            +
            # space to write the end command
            ac.AnytoneProtocol.CMD_END_SESSION
            +
            # read the ack
            ac.AnytoneProtocol.ACK
        )

        with ac.AnytoneProtocol(
            pipe=io.BytesIO(SESSION),
            block_size=16,
            file_ident=b"anytone",
            echos_write=False,
        ) as proto:
            result = proto.read_block(0)
            self.assertEquals(SIXTEEN_BYTES, result)
