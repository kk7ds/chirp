import os
import struct
import tempfile
import zlib

from tests.unit import base
from chirp import chirp_common, directory, errors
from chirp.drivers import ftx1

# Channel records as a radio wrote them
DB0BRO = bytes.fromhex(         # 145.575 FM, tone 88.5, minus shift
    "06000001" + "00" * 47 + "080000" + "0008ad4c58"
    "00440042003000420052004f002000200020002000200020" + "000000000000")
DB0HAS = bytes.fromhex(         # 439.975 FM, tone 88.5, TX on 430.575
    "0600c009" + "00" * 47 + "080000" + "001a397c58"
    "004400420030004800410053002000200020002000200020" + "19aa0d980000")
DB0NAI = bytes.fromhex(         # 439.150 FM, automatic repeater shift
    "0600c000" + "00" * 47 + "080000" + "001a2ce5b0"
    "00440042003000" + "4e00410049002000200020002000200020" + "000000000000")

# Channels made from the radio's VFO, which fills in the AGC and filter
# settings of every group of modes
AGC_MID_USB = bytes.fromhex(    # 14.200 USB, AGC mid
    "0180c000000c009600960bb80000040096009601f40000040096009601f4"
    "000004009600960c800000080096009604000000000c00000000d8acc000"
    "4100470043003200200055005300420020002000200020000000000000")
AGC_SLOW_FM = bytes.fromhex(    # 145.500 FM, AGC slow
    "0680c000000c009600960bb80000040096009601f40000040096009601f4"
    "000004009600960c800000080096009610000000000c00000008ac276000"
    "4100470043003300200046004d00200020002000200020000000000000")

CHANNELS = 0x0BD4
USED_COPY = 0x0014
SKIP = 0x00A1
GROUPS = 0x0248
GROUP_SIZE = 141


def make_image(file_type=b"MemList", channels=None):
    """Build a memory list file holding @channels: {number: (record, group)}"""
    plain = bytearray(ftx1.FILE_SIZE - ftx1.HEADER_SIZE)
    plain[:16] = ftx1.FILE_BODY_START
    plain[CHANNELS:CHANNELS + 999 * 89] = b"\xff" * (999 * 89)
    for number, (record, group) in (channels or {}).items():
        assert len(record) == 89
        start = CHANNELS + (number - 1) * 89
        plain[start:start + 89] = record
        byte, mask = (number - 1) // 8, 1 << ((number - 1) % 8)
        for bitmap in (USED_COPY, GROUPS, GROUPS + group * GROUP_SIZE):
            plain[bitmap + byte] |= mask
    blank = b" " * 62 + b"\r\n"
    return (blank * 8 + (file_type + b"  80  00000000").ljust(62) + b"\r\n" +
            ftx1._encode(plain))


DEFAULT_IMAGE = make_image(channels={
    106: (DB0NAI, 5), 109: (DB0BRO, 4), 127: (DB0HAS, 5)})


class TestFTX1(base.RadioTest):
    VENDOR_MODEL = "Yaesu_FTX-1"

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        with open(self._path("in.dat"), "wb") as f:
            f.write(DEFAULT_IMAGE)
        self._replace_radio_image(DEFAULT_IMAGE)

    def _path(self, name):
        return os.path.join(self.tempdir.name, name)

    def _open(self, data, name="in.dat"):
        with open(self._path(name), "wb") as f:
            f.write(data)
        return ftx1.FTX1Radio(self._path(name))

    def _replace_radio_image(self, data):
        """Set file bytes under the cached, already-parsed radio object"""
        self.radio._mmap._data = list(ftx1._image_from_file(data))

    def _save(self, name="out.dat"):
        self.radio.save(self._path(name))
        with open(self._path(name), "rb") as f:
            return f.read()

    def _plain(self):
        return ftx1._decode(self._save()[ftx1.HEADER_SIZE:])

    def _used(self, number, group):
        bitmap = GROUPS + group * GROUP_SIZE if group is not None \
            else USED_COPY
        return bool(self._plain()[bitmap + (number - 1) // 8] &
                    1 << ((number - 1) % 8))

    def _memory(self, number, freq, **kwargs):
        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = freq
        for key, value in kwargs.items():
            setattr(mem, key, value)
        return mem

    def test_get_memory(self):
        mem = self.radio.get_memory(109)
        self.assertEqual(145575000, mem.freq)
        self.assertEqual("FM", mem.mode)
        self.assertEqual("DB0BRO", mem.name)
        self.assertEqual("Tone", mem.tmode)
        self.assertEqual(88.5, mem.rtone)
        self.assertEqual("-", mem.duplex)
        # The file holds no offset amount
        self.assertEqual(0, mem.offset)
        self.assertEqual([], self.radio.validate_memory(mem))
        mem.offset = 600000
        self.assertIn("offset", str(self.radio.validate_memory(mem)[0]))

    def test_get_split_memory(self):
        mem = self.radio.get_memory(127)
        self.assertEqual("split", mem.duplex)
        self.assertEqual(430575000, mem.offset)

    def test_get_empty_memory(self):
        self.assertTrue(self.radio.get_memory(1).empty)

    def test_unknown_mode(self):
        self._replace_radio_image(make_image(channels={
            1: (b"\x0f" + DB0BRO[1:], 4)}))
        self.assertRaises(errors.RadioError, self.radio.get_memory, 1)

    def test_unchanged_file_is_saved_identically(self):
        with open(self._path("in.dat"), "rb") as f:
            original = f.read()
        # make_image() leaves the CRC blank
        saved = self._save()
        self.assertEqual(original[:0x200], saved[:0x200])
        self.assertEqual(original[ftx1.HEADER_SIZE:],
                         saved[ftx1.HEADER_SIZE:])
        self.radio = self._open(saved, "again.dat")
        self.assertEqual(saved, self._save())

    def test_header_crc(self):
        saved = self._save()
        body = saved[ftx1.HEADER_SIZE:]
        crc = zlib.crc32(body + bytes.fromhex("8f93c635"))
        self.assertEqual(
            (b"MemList  80  %08X" % crc).ljust(62) + b"\r\n",
            saved[0x200:0x240])
        self.assertEqual(ftx1.FILE_SIZE, len(saved))

    def test_set_memory_round_trip(self):
        mem = self._memory(5, 438725000, mode="NFM", tmode="TSQL-R",
                           ctone=123.0, duplex="+", name="Relais")
        self.radio.set_memory(mem)
        mem = self._memory(6, 121500000, mode="AM", tmode="DTCS", dtcs=165,
                           duplex="split", offset=121600000, name="Air")
        self.radio.set_memory(mem)

        self.radio = self._open(self._save(), "reloaded.dat")
        read = self.radio.get_memory(5)
        self.assertEqual(
            (438725000, "NFM", "TSQL-R", 123.0, "+", "Relais"),
            (read.freq, read.mode, read.tmode, read.ctone, read.duplex,
             read.name))
        read = self.radio.get_memory(6)
        self.assertEqual(
            (121500000, "AM", "DTCS", 165, "split", 121600000, "Air"),
            (read.freq, read.mode, read.tmode, read.dtcs, read.duplex,
             read.offset, read.name))
        # In use overall and in their band group only
        self.assertEqual([True, True, False, False, True],
                         [self._used(5, g) for g in (None, 0, 3, 4, 5)])
        self.assertEqual([True, True, True, False, False],
                         [self._used(6, g) for g in (None, 0, 3, 4, 5)])

    def test_edit_keeps_what_chirp_cannot_express(self):
        # Automatic repeater shift reads as no shift and must survive
        mem = self.radio.get_memory(106)
        self.assertEqual("", mem.duplex)
        mem.freq = 439175000
        mem.name = "DB0OR"
        self.radio.set_memory(mem)
        start = CHANNELS + 105 * 89
        record = self._plain()[start:start + 89]
        self.assertEqual(DB0NAI[:55], record[:55])
        self.assertEqual(439175000, struct.unpack(">I", record[55:59])[0])

    def test_erase_keeps_the_record(self):
        self.radio.erase_memory(109)
        self.assertTrue(self.radio.get_memory(109).empty)
        self.assertEqual([False] * 3,
                         [self._used(109, g) for g in (None, 0, 4)])
        start = CHANNELS + 108 * 89
        self.assertEqual(DB0BRO, self._plain()[start:start + 89])

    def test_new_channel_does_not_inherit_from_erased_one(self):
        self.radio.erase_memory(127)
        self.radio.set_memory(self._memory(127, 145500000, name="New"))
        mem = self.radio.get_memory(127)
        self.assertEqual(("", "", 0), (mem.tmode, mem.duplex, mem.offset))
        # Moved from the 70 cm group to the 2 m group
        self.assertEqual([True, False],
                         [self._used(127, g) for g in (4, 5)])

    def test_band_groups(self):
        # (frequency, mode, band group) as the radio sorted test channels
        cases = [(500000, "AM", None), (1900000, "LSB", 1),
                 (29600000, "FM", 1), (50150000, "USB", 2),
                 (70200000, "FM", None), (100000000, "WFM", None),
                 (118000000, "AM", 3), (137500000, "FM", 4),
                 (160000000, "FM", 4), (420000000, "FM", 5),
                 (460000000, "FM", 5)]
        for number, (freq, mode, _group) in enumerate(cases, 1):
            self.radio.set_memory(self._memory(number, freq, mode=mode))
        for number, (freq, mode, group) in enumerate(cases, 1):
            self.assertEqual(
                [True, True] + [g == group for g in range(1, 6)],
                [self._used(number, g) for g in (None, 0, 1, 2, 3, 4, 5)],
                freq)

    def test_edit_keeps_the_groups_the_radio_chose(self):
        # A radio listed its channel 1, on 70 cm, under HF as well
        image = bytearray(ftx1._decode(make_image(channels={
            1: (DB0NAI, 5)})[ftx1.HEADER_SIZE:]))
        image[GROUPS + GROUP_SIZE] |= 0x01
        self._replace_radio_image(
            make_image()[:ftx1.HEADER_SIZE] + ftx1._encode(image))
        mem = self.radio.get_memory(1)
        mem.name = "Renamed"
        self.radio.set_memory(mem)
        self.assertEqual([True, True], [self._used(1, g) for g in (1, 5)])
        # Moving it to another band sorts it anew
        mem.freq = 145500000
        self.radio.set_memory(mem)
        self.assertEqual([False, True, False],
                         [self._used(1, g) for g in (1, 4, 5)])

    def test_modes(self):
        modes = self.radio.get_features().valid_modes
        for number, mode in enumerate(modes, 1):
            self.radio.set_memory(self._memory(number, 145500000, mode=mode))
            self.assertEqual(mode, self.radio.get_memory(number).mode)
        # A mode code CHIRP cannot tell apart from another is kept
        self._replace_radio_image(make_image(channels={
            1: (b"\x12" + AGC_SLOW_FM[1:], 4)}))
        mem = self.radio.get_memory(1)
        self.assertEqual("DN", mem.mode)
        mem.name = "C4FM VW"
        self.radio.set_memory(mem)
        self.assertEqual(0x12, self._plain()[CHANNELS])

    def test_data_modes(self):
        # DATA-L, DATA-U, DATA-FM and DATA-FM-N are a mode with data
        cases = {0x08: "LSB", 0x09: "USB", 0x0A: "FM", 0x0B: "NFM"}
        self._replace_radio_image(make_image(channels={
            number: (bytes([code]) + AGC_MID_USB[1:], 1)
            for number, code in enumerate(cases, 1)}))
        for number, mode in enumerate(cases.values(), 1):
            mem = self.radio.get_memory(number)
            self.assertEqual((mode, "On"),
                             (mem.mode, str(mem.extra["data"].value)))
        mem.extra["data"].value = "Off"
        self.radio.set_memory(mem)
        self.assertEqual(0x07, self._plain()[CHANNELS + 3 * 89])
        mem = self.radio.get_memory(4)
        mem.extra["data"].value = "On"
        self.radio.set_memory(mem)
        self.assertEqual(0x0B, self._plain()[CHANNELS + 3 * 89])
        # A mode without a DATA variant drops the flag
        mem.mode = "CW"
        self.radio.set_memory(mem)
        self.assertEqual(0x03, self._plain()[CHANNELS + 3 * 89])
        mem = self.radio.get_memory(4)
        self.assertEqual("Off", str(mem.extra["data"].value))
        self.assertFalse(mem.extra["data"].value.get_mutable())

    def test_frequency_off_the_step_grid(self):
        # PMR446 channels sit on 6.25 kHz
        mem = self._memory(1, 446006250, mode="NFM")
        self.assertEqual([], self.radio.validate_memory(mem))

    def test_skip(self):
        # Channel 1 as the radio saved it after setting it to SKIP
        image = bytearray(ftx1._decode(make_image(channels={
            1: (DB0BRO, 4), 2: (DB0NAI, 5)})[ftx1.HEADER_SIZE:]))
        image[SKIP] = 0x01
        self._replace_radio_image(
            make_image()[:ftx1.HEADER_SIZE] + ftx1._encode(image))
        self.assertEqual(["S", ""],
                         [self.radio.get_memory(n).skip for n in (1, 2)])

        mem = self.radio.get_memory(2)
        mem.skip = "S"
        self.radio.set_memory(mem)
        mem = self.radio.get_memory(1)
        mem.skip = ""
        self.radio.set_memory(mem)
        self.assertEqual(0x02, self._plain()[SKIP])
        # An erased channel does not leave its skip behind
        self.radio.erase_memory(2)
        self.assertEqual(0x00, self._plain()[SKIP])

    def test_sdx(self):
        # Channels on which a radio showed S-DX as switched on and off
        on = DB0BRO[:1] + b"\x80" + DB0BRO[2:]
        self._replace_radio_image(make_image(channels={
            1: (on, 4), 2: (DB0BRO, 4)}))
        self.assertEqual(
            ["On", "Off"],
            [str(self.radio.get_memory(n).extra["sdx"].value)
             for n in (1, 2)])
        for number, value in ((1, "Off"), (2, "On")):
            mem = self.radio.get_memory(number)
            mem.extra["sdx"].value = value
            self.radio.set_memory(mem)
        self.assertEqual(DB0BRO, self._plain()[CHANNELS:CHANNELS + 89])
        self.assertEqual(on, self._plain()[CHANNELS + 89:CHANNELS + 2 * 89])
        # Off on a new channel
        self.radio.set_memory(self._memory(3, 145500000))
        self.assertEqual("Off",
                         str(self.radio.get_memory(3).extra["sdx"].value))

    def test_agc(self):
        self._replace_radio_image(make_image(channels={
            1: (AGC_MID_USB, 1), 2: (AGC_SLOW_FM, 4)}))
        mem = self.radio.get_memory(1)
        self.assertEqual("Mid", str(mem.extra["agc"].value))
        mem = self.radio.get_memory(2)
        self.assertEqual("Slow", str(mem.extra["agc"].value))
        mem.extra["agc"].value = "Fast"
        self.radio.set_memory(mem)
        record = self._plain()[CHANNELS + 89:CHANNELS + 2 * 89]
        # Only the AGC byte of the FM group changed
        self.assertEqual(0x08, record[46])
        self.assertEqual(AGC_SLOW_FM[:46] + AGC_SLOW_FM[47:],
                         record[:46] + record[47:])

    def test_new_channel_gets_the_radio_defaults(self):
        self.radio.set_memory(self._memory(1, 145500000))
        record = self._plain()[CHANNELS:CHANNELS + 89]
        self.assertEqual(ftx1.NEW_MODE_SETTINGS, record[5:50])
        self.assertEqual("Auto",
                         str(self.radio.get_memory(1).extra["agc"].value))

    def test_agc_of_every_mode(self):
        # Each group of modes has its own AGC byte. A file with a
        # different value in each was loaded into a radio, which then
        # reported these over CAT.
        settings = bytearray(ftx1.NEW_MODE_SETTINGS)
        for index, agc in {0: 0, 9: 2, 18: 3, 27: 4, 36: 1, 41: 3}.items():
            settings[index] = settings[index] & ~0x1C | agc << 2
        cases = {0x01: "Off", 0x02: "Fast", 0x03: "Fast", 0x0C: "Mid",
                 0x0D: "Mid", 0x08: "Slow", 0x09: "Slow", 0x0E: "Slow",
                 0x04: "Auto", 0x05: "Auto", 0x06: "Mid", 0x0A: "Mid",
                 0x0B: "Mid"}
        self._replace_radio_image(make_image(channels={
            number: (bytes([code]) + AGC_MID_USB[1:5] + bytes(settings) +
                     AGC_MID_USB[50:], 1)
            for number, code in enumerate(cases, 1)}))
        self.assertEqual(
            list(cases.values()),
            [str(self.radio.get_memory(n).extra["agc"].value)
             for n in range(1, len(cases) + 1)])

    def test_no_agc_in_c4fm_and_wfm(self):
        for mode in ("DN", "WFM"):
            self.radio.set_memory(self._memory(1, 145375000, mode=mode))
            mem = self.radio.get_memory(1)
            self.assertFalse(mem.extra["agc"].value.get_mutable())
            # Saving the channel again leaves its settings alone
            self.radio.set_memory(mem)
            self.assertEqual(ftx1.NEW_MODE_SETTINGS,
                             self._plain()[CHANNELS + 5:CHANNELS + 50])

    def test_file_as_image_and_back(self):
        saved = self._save("copy.img")
        self.assertEqual(ftx1.MEMORY_SIZE,
                         saved.index(chirp_common.CloneModeRadio.MAGIC))
        self.radio = directory.get_radio_by_image(self._path("copy.img"))
        self.assertIsInstance(self.radio, ftx1.FTX1Radio)
        self.assertEqual("DB0BRO", self.radio.get_memory(109).name)
        with open(self._path("in.dat"), "rb") as f:
            original = f.read()
        self.assertEqual(original[ftx1.HEADER_SIZE:],
                         self._save()[ftx1.HEADER_SIZE:])

    def test_tone_is_kept_without_tone_mode(self):
        self.radio.set_memory(self._memory(1, 145500000, rtone=123.0,
                                           dtcs=165))
        mem = self.radio.get_memory(1)
        self.assertEqual(("", 123.0, 165), (mem.tmode, mem.rtone, mem.dtcs))

    def test_unknown_squelch_code_is_kept(self):
        record = DB0BRO[:3] + b"\x06" + DB0BRO[4:]
        self._replace_radio_image(make_image(channels={1: (record, 4)}))
        mem = self.radio.get_memory(1)
        self.assertEqual("", mem.tmode)
        mem.name = "Renamed"
        self.radio.set_memory(mem)
        self.assertEqual(0x06, self._plain()[CHANNELS + 3])

    def test_unknown_tone(self):
        record = DB0BRO[:51] + b"\x40" + DB0BRO[52:]
        self._replace_radio_image(make_image(channels={1: (record, 4)}))
        self.assertRaises(errors.RadioError, self.radio.get_memory, 1)

    def test_preamp_and_name_switch_share_the_mode_byte(self):
        # FM with AMP1 and the name shown
        record = b"\xa6" + DB0BRO[1:]
        self._replace_radio_image(make_image(channels={1: (record, 4)}))
        mem = self.radio.get_memory(1)
        self.assertEqual("FM", mem.mode)
        self.assertEqual("AMP1", str(mem.extra["ipo"].value))
        self.assertEqual("On", str(mem.extra["tag"].value))
        mem.mode = "NFM"
        mem.extra["ipo"].value = "AMP2"
        self.radio.set_memory(mem)
        self.assertEqual(0xc7, self._plain()[CHANNELS])

    def test_c4fm_and_ams_modes(self):
        self._replace_radio_image(make_image(channels={
            number: (bytes([code]) + DB0BRO[1:], 4)
            for number, code in enumerate((0x10, 0x13, 0x1e), 1)}))
        self.assertEqual(
            ["DN", "DN", "Auto"],
            [self.radio.get_memory(number).mode for number in (1, 2, 3)])

    def test_channel_settings(self):
        self.radio.set_memory(self._memory(1, 14200000, mode="USB"))
        mem = self.radio.get_memory(1)
        for name, value in (("att", "On"), ("narrow", "On"), ("nb", "5"),
                            ("dnr", "10"), ("notch", "On"), ("dnf", "On"),
                            ("rx_dgid", "12"), ("tx_dgid", "34")):
            self.assertTrue(mem.extra[name].value.get_mutable(), name)
            mem.extra[name].value = value
        self.radio.set_memory(mem)
        record = self._plain()[CHANNELS:CHANNELS + 89]
        # USB, ATT, DNR next to the shift, narrow SSB, NB
        self.assertEqual(bytes.fromhex("01204a8005"), record[:5])
        # Notch and DNF of the SSB group, next to its AGC
        self.assertEqual(0x85, record[5])
        self.assertEqual(ftx1.NEW_MODE_SETTINGS[1:], record[6:50])
        self.assertEqual(bytes([12, 34]), record[87:])
        mem = self.radio.get_memory(1)
        self.assertEqual(
            ["On", "5", "10", "On", "12"],
            [str(mem.extra[name].value)
             for name in ("narrow", "nb", "dnr", "notch", "rx_dgid")])

    def test_settings_depend_on_the_mode(self):
        # (mode, settings that can be changed)
        cases = [("USB", {"narrow", "notch", "contour", "dnf", "bk_in"}),
                 ("CW", {"narrow", "notch", "contour", "dnf", "apf",
                         "bk_in"}),
                 ("RTTY", {"narrow", "notch", "contour", "dnf"}),
                 ("AM", {"notch", "contour", "dnf", "bk_in"}),
                 ("FM", {"bk_in"}),
                 ("DN", {"narrow"}),
                 ("WFM", set())]
        names = ("narrow", "notch", "contour", "dnf", "apf", "bk_in")
        for number, (mode, mutable) in enumerate(cases, 1):
            self.radio.set_memory(self._memory(number, 145500000, mode=mode))
            extra = self.radio.get_memory(number).extra
            self.assertEqual(
                mutable,
                {name for name in names if extra[name].value.get_mutable()},
                mode)

    def test_mode_change_keeps_the_settings_of_the_new_mode(self):
        self.radio.set_memory(self._memory(1, 145500000, mode="DN"))
        mem = self.radio.get_memory(1)
        # C4FM has no AGC, FM has, and a new channel has it on Auto
        self.assertEqual("Off", str(mem.extra["agc"].value))
        mem.mode = "FM"
        self.radio.set_memory(mem)
        self.assertEqual("Auto",
                         str(self.radio.get_memory(1).extra["agc"].value))

    def test_name_without_characters(self):
        record = DB0BRO[:59] + bytes(24) + DB0BRO[83:]
        self._replace_radio_image(make_image(channels={1: (record, 4)}))
        self.assertEqual("", self.radio.get_memory(1).name)

    def test_setting_of_another_mode_is_left_alone(self):
        self.radio.set_memory(self._memory(1, 145500000, mode="FM"))
        mem = self.radio.get_memory(1)
        # Not a setting of FM, as an import from another radio brings it
        mem.extra["notch"].value.set_mutable(True)
        mem.extra["notch"].value = "On"
        self.radio.set_memory(mem)
        self.assertEqual(ftx1.NEW_MODE_SETTINGS,
                         self._plain()[CHANNELS + 5:CHANNELS + 50])

    def test_unknown_setting_value_is_kept(self):
        # A noise blanker level above the 10 the radio has
        record = DB0BRO[:4] + b"\x0f" + DB0BRO[5:]
        self._replace_radio_image(make_image(channels={1: (record, 4)}))
        mem = self.radio.get_memory(1)
        self.assertEqual("Off", str(mem.extra["nb"].value))
        mem.name = "Renamed"
        self.radio.set_memory(mem)
        self.assertEqual(0x0f, self._plain()[CHANNELS + 4])

    def test_memory_group(self):
        mgrp, mgrp_list = 0x012E, GROUPS + 10 * GROUP_SIZE
        mem = self.radio.get_memory(109)
        self.assertEqual("Off", str(mem.extra["mgrp"].value))
        mem.extra["mgrp"].value = "On"
        self.radio.set_memory(mem)
        byte, mask = 108 // 8, 1 << (108 % 8)
        self.assertEqual([mask, mask], [self._plain()[start + byte]
                                        for start in (mgrp, mgrp_list)])
        self.assertEqual(
            "On", str(self.radio.get_memory(109).extra["mgrp"].value))
        self.radio.erase_memory(109)
        self.assertEqual([0, 0], [self._plain()[start + byte]
                                  for start in (mgrp, mgrp_list)])

    def test_hf_group_is_the_amateur_bands(self):
        self.radio.set_memory(self._memory(1, 14200000, mode="USB"))
        self.radio.set_memory(self._memory(2, 15000000, mode="AM"))
        self.radio.set_memory(self._memory(3, 110000000, mode="AM"))
        self.assertEqual([True, False, False],
                         [self._used(number, 1) for number in (1, 2, 3)])
        self.assertFalse(self._used(3, 3))

    def test_pms_channels(self):
        rf = self.radio.get_features()
        self.assertEqual(100, len(rf.valid_special_chans))
        self.assertEqual(["P-01L", "P-01U", "P-02L"],
                         rf.valid_special_chans[:3])
        self.assertEqual("P-50U", rf.valid_special_chans[-1])
        mem = self.radio.get_memory("P-02U")
        self.assertTrue(mem.empty)
        self.assertEqual((1003, "P-02U"), (mem.number, mem.extd_number))
        self.radio.set_memory(self._memory(1003, 14350000, mode="USB"))
        mem = self.radio.get_memory("P-02U")
        self.assertEqual((14350000, "USB"), (mem.freq, mem.mode))
        record = self._plain()[CHANNELS + 1002 * 89:CHANNELS + 1003 * 89]
        self.assertEqual(14350000, struct.unpack(">I", record[55:59])[0])
        self.assertTrue(self._used(1003, 1))
        self.assertEqual("", self.radio.get_memory(999).extd_number)
        with self.assertRaises(errors.InvalidMemoryLocation) as raised:
            self.radio.get_memory(1100)
        self.assertIn("1099", str(raised.exception))
        self.assertRaises(errors.InvalidMemoryLocation,
                          self.radio.get_memory, "P-51L")


def _shift(data, by):
    return bytes((byte + by) & 0xFF for byte in data)


class FakeRadio:
    """Answers the block commands like the radio does"""
    # Makes ";" show up within the answers
    KEY = 0x3b

    def __init__(self, memory=None, model=b"AH084M"):
        self.memory = bytearray(memory or ftx1.MEMORY_SIZE)
        self.model = model
        self.restarted = False
        self.blocks = []
        self.logged = []
        self.timeout = None
        self._out = b""

    def write(self, data):
        if data == b"PS9;":
            self.restarted = True
            return
        command = data[:-2]
        assert data[-1:] == b";" and data[-2] == sum(command) & 0xFF, data
        if command == b"A1":
            # Three bytes
            payload = struct.pack(">I", len(self.memory))[1:]
        elif command == b"A2":
            payload = self.model + b"\x00\x01"
        else:
            self.blocks.append(command[:3])
            # The driver does not hide what it sends
            assert command[3] == 0, command[:4]
            request = command[4:]
            # The address has three bytes
            address, size = struct.unpack(">IH", b"\x00" + request[:5])
            if command[:3] == b"A0R":
                assert len(request) == 5
                block = self.memory[address:address + size]
                payload = request + bytes(block).ljust(1024, b"\xee")
            else:
                assert command[:3] == b"A0W" and len(request) == 5 + 1024
                self.memory[address:address + size] = request[5:5 + size]
                payload = b"\x06"
        # A block answer repeats the R or W of the command
        name = command[:3] if command[:2] == b"A0" else command
        answer = name + bytes([self.KEY]) + _shift(payload, self.KEY)
        self._out += answer + bytes([sum(answer) & 0xFF]) + b";"

    def read(self, size):
        data, self._out = self._out[:size], self._out[size:]
        return data

    def reset_input_buffer(self):
        self._out = b""

    def log(self, message):
        self.logged.append(message)


class TestFTX1Clone(base.BaseTest):
    # What the driver transfers: info with home, and the channels
    RANGES = [(0x2079, 0x2A7D), (0x70D6, 0x1F7F3)]

    def _radio(self, pipe):
        radio = ftx1.FTX1Radio(pipe)
        radio.status_fn = lambda status: None
        return radio

    @classmethod
    def _programmed(cls):
        """Return the memory of a radio with a memory and a PMS channel"""
        if not hasattr(cls, "_programmed_image"):
            radio = ftx1.FTX1Radio(None)
            memory = bytearray(ftx1.MEMORY_SIZE)
            # A radio has a record in every channel, the weather channels too
            memory[0x70D6 + 1124 * 89:0x70D6 + 1125 * 89] = ftx1.NEW_MEMORY
            radio._mmap = ftx1.memmap.MemoryMapBytes(bytes(memory))
            radio.process_mmap()
            mem = chirp_common.Memory()
            mem.number = 7
            mem.freq = 145500000
            mem.name = "2M CALL"
            radio.set_memory(mem)
            mem.number = 1000
            mem.freq = 144000000
            radio.set_memory(mem)
            cls._programmed_image = radio._mmap.get_packed()
        return cls._programmed_image

    def test_layout(self):
        memory = self._programmed()
        # Channel 7 at its address in the radio, in use and on the VHF list
        record = memory[0x70D6 + 6 * 89:0x70D6 + 7 * 89]
        self.assertEqual(145500000, struct.unpack(">I", record[55:59])[0])
        self.assertEqual("2M CALL     ", record[59:83].decode("utf-16-be"))
        for bitmap in (0x2079 + 4, 0x2079 + 4 + 4 * 141,
                       0x2079 + 4 + 8 * 141):
            self.assertEqual(0x40, memory[bitmap])
        self.assertEqual(0x80, memory[0x2079 + 4 + 124])

    def test_download(self):
        memory = bytearray(b"\x55" * ftx1.MEMORY_SIZE)
        programmed = self._programmed()
        for start, end in self.RANGES:
            memory[start:end] = programmed[start:end]
        pipe = FakeRadio(memory)
        radio = self._radio(pipe)
        radio.sync_in()
        self.assertEqual("2M CALL", radio.get_memory(7).name)
        self.assertEqual(144000000, radio.get_memory("P-01L").freq)
        self.assertTrue(radio.get_memory(8).empty)
        image = radio._mmap.get_packed()
        self.assertEqual(ftx1.MEMORY_SIZE, len(image))
        # Nothing but the channels and what goes with them is read
        self.assertEqual(programmed, image)
        self.assertEqual({b"A0R"}, set(pipe.blocks))
        self.assertFalse(pipe.restarted)
        # The trace names the key of every answer
        self.assertEqual({"Answer is shifted by 0x3B"}, set(pipe.logged))

    def test_upload(self):
        programmed = self._programmed()
        pipe = FakeRadio(b"\x55" * ftx1.MEMORY_SIZE)
        radio = self._radio(pipe)
        radio._mmap = ftx1.memmap.MemoryMapBytes(programmed)
        radio.sync_out()
        expected = bytearray(b"\x55" * ftx1.MEMORY_SIZE)
        for start, end in self.RANGES:
            expected[start:end] = programmed[start:end]
        self.assertEqual(expected, pipe.memory)
        self.assertEqual({b"A0W"}, set(pipe.blocks))
        self.assertTrue(pipe.restarted)

    def test_download_as_file(self):
        radio = self._radio(FakeRadio(self._programmed()))
        radio.sync_in()
        with tempfile.TemporaryDirectory() as tempdir:
            path = os.path.join(tempdir, "MemList.dat")
            radio.save(path)
            self.assertEqual(ftx1.FILE_SIZE, os.path.getsize(path))
            radio = directory.get_radio_by_image(path)
        self.assertEqual("2M CALL", radio.get_memory(7).name)
        self.assertEqual(144000000, radio.get_memory("P-01L").freq)

    def test_upload_of_a_file(self):
        # The file ends within the second 5 MHz channel
        end = 0x70D6 + 1100 * 89 + 88
        programmed = bytearray(self._programmed())
        programmed[end:] = bytes(len(programmed) - end)
        pipe = FakeRadio(b"\x55" * ftx1.MEMORY_SIZE)
        radio = self._radio(pipe)
        radio._mmap = ftx1.memmap.MemoryMapBytes(bytes(programmed))
        radio.sync_out()
        self.assertEqual(programmed[0x70D6:end], pipe.memory[0x70D6:end])
        # What the file does not have stays as it is in the radio
        self.assertEqual(b"\x55" * (ftx1.MEMORY_SIZE - end),
                         pipe.memory[end:])
        self.assertTrue(pipe.restarted)

    def test_other_radio(self):
        for pipe in (FakeRadio(model=b"AH000X"), FakeRadio(bytes(1000))):
            radio = self._radio(pipe)
            self.assertRaises(errors.RadioError, radio.sync_in)
            self.assertEqual([], pipe.blocks)

    def test_damaged_answer(self):
        class Damaging(FakeRadio):
            def read(self, size):
                data = super().read(size)
                # Within the data of a block
                return data[:500] + b"\x00" + data[501:]

        radio = self._radio(Damaging())
        self.assertRaises(errors.RadioError, radio.sync_in)

    def test_input_from_before_the_transfer(self):
        pipe = FakeRadio(self._programmed())
        # Like the radio sends on its own with auto information on
        pipe._out = b"FA014200000;"
        radio = self._radio(pipe)
        radio.sync_in()
        self.assertEqual("2M CALL", radio.get_memory(7).name)

    def test_upload_given_up(self):
        class Failing(FakeRadio):
            def read(self, size):
                return b"" if len(self.blocks) > 3 else super().read(size)

        programmed = self._programmed()
        for pipe, partial in ((Failing(), True),
                              (FakeRadio(model=b"AH000X"), False)):
            radio = self._radio(pipe)
            radio._mmap = ftx1.memmap.MemoryMapBytes(programmed)
            with self.assertRaises(errors.RadioError) as raised:
                radio.sync_out()
            self.assertEqual(partial,
                             "upload again" in str(raised.exception))
            self.assertFalse(pipe.restarted)

    def test_silent_radio(self):
        class Silent(FakeRadio):
            def read(self, size):
                return b""

        radio = self._radio(Silent())
        with self.assertRaises(errors.RadioError) as raised:
            radio.sync_in()
        self.assertIn("38400", str(raised.exception))
