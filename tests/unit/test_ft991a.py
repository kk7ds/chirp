from unittest import mock

from tests.unit import base
from chirp import chirp_common, errors
from chirp.drivers import ft991a


class FakeFT991A:
    """Simulates the CAT behavior observed on a real FT-991A"""

    # As read from a real radio
    MENUS = (
        "0300 0700 3000 0 1 0 1 15 3 005 050 3 0 30 000 0 0001 0 0 0 0 0 1 "
        "1 05 027 +0000 0 0 0 3 1 1 0 +05 10 1 1 +00 0 00 0 00 0 0 050 0 0 "
        "050 04 1 11 1 050 0 0 0200 2 1 2 0 1 0 +1500 +1500 00 1 00 1 0 1 0 "
        "050 0 050 0 0 050 0 0100 0500 0600 07600 1 1 0 G0NR9 0 1 0 1 05 1 "
        "47 1 0 0 0 050 0 1 01 0 47 0 0 050 0 0 3 1 -15 10 1 1 04 0 7 00 "
        "+05 10 00 +05 10 00 +05 10 02 +00 02 02 +00 01 07 +00 01 100 100 "
        "050 050 1 1 010 0100 050 050 0100 000 0 0 14537500 0 000").split()

    def __init__(self, baudrate=38400):
        self.radio_baudrate = baudrate
        self.baudrate = 38400
        self.timeout = 0.1
        self.out = b""
        self.commands = []
        self.menus = {"%03i" % (i + 1): x for i, x in enumerate(self.MENUS)}
        # Channel -> [fields from frequency to mode, tone mode, shift, name,
        #             CTCSS tone number, DCS code number]
        self.channels = {
            1: ["439000000+0000004", "2", "2", "RPT UHF     ", 3, 0],
            3: ["145762500+0000004", "1", "2", "RPT VHF     ", 20, 0],
            5: ["014200000+0000002", "0", "0", "20M         ", 0, 0],
            6: ["433500000+0000004", "3", "0", "DCS         ", 0, 47],
            7: ["433525000+0000004", "4", "0", "DCS ENC     ", 0, 5],
            8: ["007040000-0150108", "0", "0", "DATA LSB    ", 0, 0],
            36: ["145775000+0000004", "2", "2", "CURRENT     ", 12, 0],
            100: ["144000000+0000002", "0", "0", "            ", 0, 0],
        }
        # Channels of which the bit is cleared in each of the two tables
        self.cleared = {0x3229: set(), 0x3239: set()}
        self.vfo = ["439087500+0000004", "2", "2", "", 3, 0]
        self.channel = 36
        self.memory_mode = False
        # Selecting a channel does not load it, as seen on a real radio
        # after its memory was written by other software
        self.recall_broken = False
        # Sent in front of the next answer, as seen once on a real radio
        self.stray = b""

    @property
    def state(self):
        return self.channel, self.memory_mode

    @property
    def current(self):
        if self.memory_mode and not self.recall_broken:
            return self.channels[self.channel]
        return self.vfo

    @property
    def writes(self):
        return [x for x in self.commands
                if x[:3] == "SPW" or
                x[:2] in ("MT", "CN", "EX") and len(x) > 5]

    def reset_input_buffer(self):
        self.out = b""

    def read(self, count):
        data, self.out = self.out[:count], self.out[count:]
        return data

    def read_until(self, expected):
        end = self.out.find(expected)
        if end < 0:
            data, self.out = self.out, b""
            return data
        return self.read(end + len(expected))

    def _memory(self, data):
        """Direct access to the tables of channels in use and the tones"""
        assert sum(data[:-2]) & 0xFF == data[-2] and data[-1:] == b";"
        addr = (data[3] << 8) | data[4]
        if addr >= 0x3249:
            assert data[:3] == b"SPR"
            number, offset = divmod(addr - 0x3249, 0x60)
            assert offset == 0x46
            reply = data[:5] + bytes(self.channels[number + 1][4:])
            return reply + bytes([sum(reply) & 0xFF]) + b";"
        table = max(x for x in self.cleared if x <= addr)
        first = (addr - table) * 8 + 1
        if data[:3] == b"SPR":
            used = [x in self.channels and x not in self.cleared[table]
                    for x in range(first, first + 16)]
            value = sum(1 << i for i, x in enumerate(used) if x)
            reply = data[:5] + bytes([value & 0xFF, value >> 8])
            return reply + bytes([sum(reply) & 0xFF]) + b";"
        value = data[5] | (data[6] << 8)
        for i in range(16):
            if first + i in self.channels and not value & (1 << i):
                self.cleared[table].add(first + i)
        for number in set.intersection(*self.cleared.values()):
            self.channels.pop(number, None)
        return b"A;"

    def write(self, data):
        if self.baudrate != self.radio_baudrate:
            self.out += b"\xfe\xce"
            return
        if data[:3] in (b"SPR", b"SPW"):
            self.commands.append(data[:3].decode() + data[3:-2].hex())
            self.out += self._memory(data)
            return
        for cmd in data.decode().split(";")[:-1]:
            self.commands.append(cmd)
            self.out += self.stray + self._command(cmd).encode()
            self.stray = b""

    def _info(self, prefix, channel):
        cur = channel[0], int(self.memory_mode), channel[1], channel[2]
        return "%s%03i%s%i%s00%s" % ((prefix, self.channel) + cur)

    def _command(self, cmd):
        op, args = cmd[:2], cmd[2:]
        if op == "ID" and not args:
            return "ID0670;"
        elif op == "IF" and not args:
            return self._info("IF", self.current) + ";"
        elif op == "MT" and len(args) == 3:
            try:
                channel = self.channels[int(args)]
            except KeyError:
                return "?;"
            return self._info("MT", channel) + "0" + channel[3] + ";"
        elif op == "MT" and len(args) == 38:
            number = int(args[:3])
            if not 1 <= number <= 117 or args[22:24] != "00":
                return "?;"
            # The tones are inherited from what the radio is on
            self.channels[number] = [args[3:20], args[21], args[24],
                                     args[26:]] + self.current[4:]
            self.channel = number
            self.memory_mode = True
            return ""
        elif op == "MC" and len(args) == 3:
            if int(args) not in self.channels:
                return "?;"
            self.channel = int(args)
            self.memory_mode = True
            return ""
        elif op == "VM" and not args:
            self.memory_mode = not self.memory_mode
            return ""
        elif op == "CN" and args in ("00", "01"):
            return "CN%s%03i;" % (args, self.current[4 + int(args[1])])
        elif op == "CN" and len(args) == 5:
            self.current[4 + int(args[1])] = int(args[2:])
            return ""
        elif op == "EX" and args in self.menus:
            return "EX%s%s;" % (args, self.menus[args])
        elif op == "EX" and args[:3] in self.menus:
            if (args[:3] == "087" or
                    len(args[3:]) != len(self.menus[args[:3]])):
                return "?;"
            self.menus[args[:3]] = args[3:]
            return ""
        return "?;"


class TestFT991A(base.BaseTest):
    def setUp(self):
        super().setUp()
        patch = mock.patch("time.sleep")
        patch.start()
        self.addCleanup(patch.stop)
        self.pipe = FakeFT991A()
        self.initial_state = self.pipe.state
        self.radio = ft991a.FT991ARadio(self.pipe)
        self.pipe.commands.clear()

    def test_without_pipe(self):
        radio = ft991a.FT991ARadio(None)
        self.assertEqual((1, 99), radio.get_features().memory_bounds)

    def test_pipe_set_later(self):
        radio = ft991a.FT991ARadio(None)
        radio.pipe = FakeFT991A()
        self.assertEqual("RPT UHF", radio.get_memory(1).name)

    def test_timeout(self):
        self.assertEqual(1, self.pipe.timeout)

    def test_wrong_baud(self):
        self.assertRaises(errors.RadioNoResponse,
                          ft991a.FT991ARadio, FakeFT991A(9600))

    def test_features(self):
        rf = self.radio.get_features()
        self.assertEqual((1, 99), rf.memory_bounds)
        self.assertEqual(18, len(rf.valid_special_chans))
        self.assertEqual(50, len(rf.valid_tones))
        for mode in rf.valid_modes:
            self.assertIn(mode, chirp_common.MODES)

    def test_reading_does_not_change_radio(self):
        for number in range(1, 100):
            self.radio.get_memory(number)
        for name in self.radio.get_features().valid_special_chans:
            self.radio.get_memory(name)
        self.radio.get_settings()
        self.assertEqual([], self.pipe.writes)
        self.assertEqual([], [x for x in self.pipe.commands
                              if x[:2] in ("MC", "VM")])
        self.assertEqual(self.initial_state, self.pipe.state)

    def test_radio_read_once(self):
        self.radio.get_memory(1)
        self.radio.get_memory(1)
        self.radio.get_settings()
        self.radio.get_settings()
        self.assertEqual(1, self.pipe.commands.count("MT001"))
        self.assertEqual(1, self.pipe.commands.count("EX001"))

    def test_broken_recall(self):
        self.pipe.recall_broken = True
        self.pipe.memory_mode = True
        self.assertEqual(131.8, self.radio.get_memory(3).ctone)
        self.assertEqual(265, self.radio.get_memory(6).dtcs)

        mem = self.radio.get_memory(3)
        mem.ctone = 88.5
        self.radio.set_memory(mem)
        self.assertEqual(8, self.pipe.channels[3][4])
        # The other channels must keep their own tone
        self.assertEqual(3, self.pipe.channels[1][4])
        self.assertEqual(12, self.pipe.channels[36][4])

    def test_get_memory_tone(self):
        mem = self.radio.get_memory(1)
        self.assertEqual(1, mem.number)
        self.assertEqual(439000000, mem.freq)
        self.assertEqual("FM", mem.mode)
        self.assertEqual("Tone", mem.tmode)
        self.assertEqual(74.4, mem.rtone)
        self.assertEqual("-", mem.duplex)
        self.assertEqual(7600000, mem.offset)
        self.assertEqual("RPT UHF", mem.name)

    def test_get_memory_tsql(self):
        mem = self.radio.get_memory(3)
        self.assertEqual("TSQL", mem.tmode)
        self.assertEqual(131.8, mem.ctone)
        self.assertEqual(600000, mem.offset)

    def test_get_memory_dtcs(self):
        mem = self.radio.get_memory(6)
        self.assertEqual("DTCS", mem.tmode)
        self.assertEqual(265, mem.dtcs)
        mem = self.radio.get_memory(7)
        self.assertEqual("Cross", mem.tmode)
        self.assertEqual("DTCS->", mem.cross_mode)
        self.assertEqual(36, mem.dtcs)

    def test_get_memory_no_tone(self):
        mem = self.radio.get_memory(5)
        self.assertEqual(14200000, mem.freq)
        self.assertEqual("USB", mem.mode)
        self.assertEqual("", mem.tmode)
        self.assertEqual("", mem.duplex)

    def test_get_memory_empty(self):
        mem = self.radio.get_memory(2)
        self.assertTrue(mem.empty)
        self.assertEqual(2, mem.number)

    def test_get_memory_special(self):
        mem = self.radio.get_memory("P-1L")
        self.assertEqual("P-1L", mem.extd_number)
        self.assertEqual(144000000, mem.freq)
        self.assertTrue(self.radio.get_memory("P-9U").empty)
        self.assertRaises(errors.InvalidMemoryLocation,
                          self.radio.get_memory, "P-0L")
        self.assertRaises(errors.InvalidMemoryLocation,
                          self.radio.get_memory, 118)

    def test_set_memory_unchanged(self):
        self.radio.set_memory(self.radio.get_memory(1))
        self.radio.set_memory(self.radio.get_memory(8))
        self.assertEqual([], self.pipe.writes)
        self.assertEqual(self.initial_state, self.pipe.state)

    def test_set_memory_new(self):
        mem = chirp_common.Memory()
        mem.number = 99
        mem.freq = 145500000
        mem.mode = "NFM"
        mem.tmode = "Tone"
        mem.rtone = 123.0
        mem.duplex = "+"
        mem.name = "Test;99"
        self.radio.set_memory(mem)
        # The tone is set on the VFO first, and put back afterwards
        self.assertEqual(["CN00018",
                          "MT099145500000+000000B020010Test99      ",
                          "CN00003", "CN01000"], self.pipe.writes)
        self.assertEqual(18, self.pipe.channels[99][4])
        self.assertEqual([3, 0], self.pipe.vfo[4:])
        self.assertEqual(self.initial_state, self.pipe.state)

        radio = ft991a.FT991ARadio(self.pipe)
        mem = radio.get_memory(99)
        self.assertEqual(145500000, mem.freq)
        self.assertEqual("NFM", mem.mode)
        self.assertEqual("Tone", mem.tmode)
        self.assertEqual(123.0, mem.rtone)
        self.assertEqual("+", mem.duplex)
        self.assertEqual("Test99", mem.name)

    def test_set_memory_changes(self):
        mem = self.radio.get_memory(3)
        mem.ctone = 88.5
        self.radio.set_memory(mem)
        mem = self.radio.get_memory(6)
        mem.dtcs = 754
        self.radio.set_memory(mem)
        mem = self.radio.get_memory(1)
        mem.tmode = ""
        self.radio.set_memory(mem)
        self.assertEqual(["CN00008",
                          "MT003145762500+0000004010020RPT VHF     ",
                          "CN00003", "CN01000",
                          "CN01103",
                          "MT006433500000+0000004030000DCS         ",
                          "CN00003", "CN01000",
                          "MT001439000000+0000004000020RPT UHF     ",
                          "CN00003", "CN01000"], self.pipe.writes)
        self.assertEqual(8, self.pipe.channels[3][4])
        self.assertEqual(103, self.pipe.channels[6][5])
        self.assertEqual(self.initial_state, self.pipe.state)
        self.assertEqual(88.5, self.radio.get_memory(3).ctone)

        self.pipe.memory_mode = True
        mem = self.radio.get_memory(3)
        mem.ctone = 100.0
        self.radio.set_memory(mem)
        self.assertEqual(12, self.pipe.channels[3][4])
        # Back in memory mode, and its channel still has its own tone
        self.assertEqual((36, True), self.pipe.state)
        self.assertEqual(12, self.pipe.channels[36][4])

    def test_set_memory_failure(self):
        mem = self.radio.get_memory(1)
        mem.name = "Changed"
        with mock.patch.object(self.radio, "_write_channel",
                               side_effect=errors.RadioError("Refused")):
            self.assertRaises(errors.RadioError, self.radio.set_memory, mem)
        # What the radio has is read again
        self.pipe.commands.clear()
        self.assertEqual("RPT UHF", self.radio.get_memory(1).name)
        self.assertIn("MT001", self.pipe.commands)
        self.assertEqual(self.initial_state, self.pipe.state)

    def test_set_memory_keeps_clarifier_and_data_lsb(self):
        mem = self.radio.get_memory(8)
        self.assertEqual("DIG", mem.mode)
        mem.freq = 7041000
        self.radio.set_memory(mem)
        self.assertEqual("007041000-0150108", self.pipe.channels[8][0])

        mem.mode = "USB"
        self.radio.set_memory(mem)
        mem.mode = "DIG"
        self.radio.set_memory(mem)
        self.assertEqual("007041000-015010C", self.pipe.channels[8][0])

    def test_set_memory_special(self):
        mem = self.radio.get_memory("P-1L")
        mem.freq = 144300000
        self.radio.set_memory(mem)
        self.assertEqual("144300000+0000002", self.pipe.channels[100][0])

    def test_erase_memory(self):
        self.radio.erase_memory(5)
        self.assertNotIn(5, self.pipe.channels)
        # Channel 5 is bit 4 of the first byte of each table, and the
        # other channels of the bytes that are written must be kept
        self.assertEqual(["SPW3229e500", "SPW3239e500"], self.pipe.writes)
        self.assertTrue(self.radio.get_memory(5).empty)

        self.radio.erase_memory("P-1L")
        self.assertNotIn(100, self.pipe.channels)
        self.assertEqual([1, 3, 6, 7, 8, 36], sorted(self.pipe.channels))
        self.assertEqual(self.initial_state, self.pipe.state)
        self.assertTrue(
            ft991a.FT991ARadio(self.pipe).get_memory(5).empty)

    def test_erase_with_stray_bytes(self):
        self.radio.get_memory(36)
        self.pipe.memory_mode = True
        # Left over from before, then in front of the answer to IF
        self.pipe.out = b"F;"
        self.pipe.stray = b"\x00"
        self.radio.erase_memory(36)
        self.assertNotIn(36, self.pipe.channels)
        self.assertFalse(self.pipe.memory_mode)

    def test_erase_empty_memory(self):
        self.radio.erase_memory(2)
        self.assertEqual([], self.pipe.writes)

    def test_set_empty_memory(self):
        mem = self.radio.get_memory(5)
        mem.empty = True
        self.radio.set_memory(mem)
        self.assertNotIn(5, self.pipe.channels)

    def test_erase_current_channel(self):
        self.pipe.memory_mode = True
        self.radio.erase_memory(36)
        self.assertNotIn(36, self.pipe.channels)
        self.assertFalse(self.pipe.memory_mode)

    def test_validate_offset(self):
        self.assertEqual(
            [], self.radio.validate_memory(self.radio.get_memory(3)))

        mem = chirp_common.Memory()
        mem.number = 10
        mem.freq = 145600000
        mem.duplex = "-"
        mem.offset = 600000
        self.pipe.commands.clear()
        self.assertEqual([], self.radio.validate_memory(mem))
        mem.offset = 1600000
        msgs = self.radio.validate_memory(mem)
        self.assertEqual(1, len(msgs))
        self.assertIsInstance(msgs[0], chirp_common.ValidationWarning)
        # This is known from the start
        self.assertEqual([], self.pipe.commands)

    def _setting(self, settings, number):
        for group in settings:
            for setting in group:
                if setting.get_name() == "menu_%03i" % number:
                    return setting

    def test_get_settings(self):
        settings = self.radio.get_settings()
        self.assertEqual(153, sum(len(group) for group in settings))
        self.assertEqual("001 AGC FAST DELAY (msec)",
                         self._setting(settings, 1).get_shortname())
        self.assertEqual(300, int(self._setting(settings, 1).value))
        self.assertEqual("BLUE", str(self._setting(settings, 6).value))
        self.assertEqual("UTC+00:00", str(self._setting(settings, 27).value))
        self.assertEqual(-15, int(self._setting(settings, 112).value))
        self.assertEqual("100 kHz", str(self._setting(settings, 116).value))
        self.assertEqual("153 WIRES DG-ID",
                         self._setting(settings, 153).get_shortname())
        self.assertEqual("AUTO", str(self._setting(settings, 153).value))
        for number in range(1, 154):
            mutable = self._setting(settings, number).value.get_mutable()
            self.assertEqual(number not in (31, 33, 87), mutable, number)

    def test_get_settings_unexpected_value(self):
        self.pipe.menus["028"] = "9"
        self.pipe.menus["001"] = "9999"
        settings = self.radio.get_settings()
        for number, value in ((28, "9"), (1, "9999")):
            setting = self._setting(settings, number)
            self.assertEqual(value, str(setting.value))
            self.assertFalse(setting.value.get_mutable())
        self.radio.set_settings(settings)
        self.assertEqual([], self.pipe.writes)

    def test_set_settings(self):
        settings = self.radio.get_settings()
        self._setting(settings, 6).value = "RED"
        self._setting(settings, 27).value = "UTC-03:30"
        self._setting(settings, 57).value = 30
        self._setting(settings, 82).value = 1600
        self._setting(settings, 112).value = 5
        self._setting(settings, 116).value = "1000 kHz"
        self._setting(settings, 153).value = "DG-ID 42"
        self.radio.set_settings(settings)
        self.assertEqual(["EX0065", "EX027-0330", "EX0570030", "EX0821600",
                          "EX112+05", "EX11607", "EX153042"],
                         self.pipe.writes)
        # The offset of the memories follows the menu
        self.assertEqual(1600000, self.radio.get_memory(3).offset)

        settings = ft991a.FT991ARadio(self.pipe).get_settings()
        self.assertEqual("RED", str(self._setting(settings, 6).value))
        self.assertEqual(5, int(self._setting(settings, 112).value))
        self.assertEqual("DG-ID 42", str(self._setting(settings, 153).value))
