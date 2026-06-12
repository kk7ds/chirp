import contextlib
from collections import Counter
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from chirp import checksum, chirp_common, drivers, memmap
from chirp import directory
from chirp.drivers import iradio_dmuv4r


def load_utility_module():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "tools", "iradio_dmuv4r_utility.py")
    spec = importlib.util.spec_from_file_location(
        "iradio_dmuv4r_utility", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_radio():
    radio = iradio_dmuv4r.IradioDMUV4RRadio(
        memmap.MemoryMapBytes(b"\xFF" * iradio_dmuv4r.MEM_SIZE)
    )
    radio.process_mmap()
    return radio


class AckPipe:
    def __init__(self):
        self.timeout = 1
        self.writes = []
        self.read_sizes = []

    def write(self, data):
        self.writes.append(bytes(data))

    def read(self, size):
        self.read_sizes.append(size)
        return iradio_dmuv4r.ACK


class UploadPipe(AckPipe):
    def read(self, size):
        self.read_sizes.append(size)
        if size == 1:
            return iradio_dmuv4r.ACK
        if size != iradio_dmuv4r.BLOCK_SIZE + 4:
            raise AssertionError("unexpected read size %d" % size)

        command = self.writes[-1]
        if len(command) != 4 or command[0] != 0x52:
            raise AssertionError("last write is not a read command")
        addr = (command[1] << 8) | command[2]
        payload = b"\x00" * iradio_dmuv4r.BLOCK_SIZE
        if addr == 0x0008:
            payload = b"\xFF" * iradio_dmuv4r.BLOCK_SIZE
        elif addr != 0x0000:
            raise AssertionError("unexpected read address 0x%04X" % addr)

        reply = command[:3] + payload
        return reply + bytes([checksum.checksum_8bit(reply)])


def expand_ranges(*ranges):
    offsets = set()
    for start, end in ranges:
        offsets.update(range(start, end + 1))
    return offsets


OEM_CFG_SAVEALLDATA_OFFSETS = expand_ranges(
    (12, 13), (16, 16), (19, 20), (23, 93), (95, 101),
    (103, 109), (126, 127), (142, 161), (163, 166),
    (169, 169), (233, 234), (256, 258), (261, 262),
    (267, 268), (272, 273), (275, 277), (384, 392),
    (397, 404), (406, 408), (512, 520), (522, 852),
)

OEM_CFG2_SAVEALLDATA_OFFSETS = expand_ranges(
    (0, 5), (8, 16), (18, 30), (31, 46),
)
ONE_ROW_GLOBAL_CONTACTS_SHA256 = (
    "3f1315a8ff087b76d483dad73e7550c2a639898036d934a2fde8e82f555e199f")
LIVE_VENDOR_CHANNEL_RECORDS = {
    1: (
        "48104801406871070168710701000000000000000001000000000000000000"
        "56484631FFFFFFFFFFFFFFFFFFFFFFFFFF"),
    2: (
        "4810080140B48E0701B48E0701000000000000000000010000000000000000"
        "56484632FFFFFFFFFFFFFFFFFFFFFFFFFF"),
    61: (
        "006048014098AB730298AB7302000000000100010000000100000000000000"
        "494E4E4552FFFFFFFFFFFFFFFFFFFFFFFF"),
    200: (
        "50100E01505895BC005895BC00000000000000000000000100000000000000"
        "4149522D506C617379FFFFFFFFFFFFFFFF"),
    41: (
        "50104801406857AC026857AC024C204C20000000000001000000000000000000"
        "454D475F6368616E67FFFFFFFFFFFFFF"),
    42: (
        "4010080140A876AC02A876AC0223202320000000000001000000000000000000"
        "55545F6368616E67FFFFFFFFFFFFFFFF"),
    43: (
        "4010488140C8C4AC02C8C4AC0223202320000000000001000000000000000000"
        "5A415A454D495F6368616EFFFFFFFFFF"),
    44: (
        "001048014060BEA20260BEA20223202320000000000001000000000000000000"
        "50524F4752414D5F64696769FFFFFFFF"),
    45: (
        "0010480140E8D1A202E8D1A20223202320000000010001000000000000000000"
        "494E464F5F656E6372FFFFFFFFFFFFFF"),
    46: (
        "00F0480140ACDBA202ACDBA20223202320000000000001000000000000000000"
        "53554243414D505F636F6C6F723135FF"),
    47: (
        "02104801408DD1A8028DD1A80275137513000000000001000000000000000000"
        "464F544F5F747332FFFFFFFFFFFFFFFF"),
    48: (
        "04104801406FD6A8026FD6A80223202320000000000001000000000000000000"
        "52455A455256315F647332FFFFFFFFFF"),
    49: (
        "001048214005BEA80205BEA80223202320000000000001000000000000000000"
        "50524F47325F636866FFFFFFFFFFFFFF"),
    50: (
        "001048C140ABCCA802ABCCA80223202320000000000001000000000000000000"
        "52455A455256325F6368666369FFFFFF"),
    51: (
        "0110480140C9C7A802C9C7A80200000000000000000001000000000000000000"
        "52455A455256335F70726F6DFFFFFFFF"),
    52: (
        "60104801404886AC024886AC0223202320000000000001000000000000000000"
        "55542D52455A5F74786F6E6C79FFFFFF"),
    53: (
        "5010480140085BAE02085BAE0223202320000000000001000000000000000000"
        "72785F6F6E6C79FFFFFFFFFFFFFFFFFF"),
}

LIVE_VENDOR_CONTACT_RECORDS = {
    2: (
        "0043434300496E646976696475616C5F63616C6CFF"),
}


def cfg_setting_offsets():
    offsets = {12, 13}
    offsets.update(range(23, 27))
    offsets.update(range(28, 44))
    offsets.update(range(44, 76))
    offsets.update(range(76, 92))
    offsets.update(range(522, 842))
    offsets.update(iradio_dmuv4r.LIST_BOOL_FIELDS)
    offsets.update(iradio_dmuv4r.CONFIG_LIST_FIELDS)
    for offset, _label, _minimum, _maximum, kind in (
            iradio_dmuv4r.CONFIG_INT_FIELDS.values()):
        size = {"u8": 1, "u16": 2, "u32": 4, "bcd32": 4}[kind]
        offsets.update(range(offset, offset + size))
    for offset, _label, _minimum, _maximum, _default in (
            iradio_dmuv4r.CONFIG_FLOAT_FIELDS.values()):
        offsets.update(range(offset, offset + 4))
    return offsets


def cfg2_setting_offsets():
    offsets = set(iradio_dmuv4r.CFG2_LIST_FIELDS)
    offsets.update(iradio_dmuv4r.CFG2_KEY_FIELDS)
    offsets.update(range(8, 17))
    offsets.add(18)
    offsets.update(range(24, 30))
    return offsets


class TestIradioDMUV4R(unittest.TestCase):
    def test_match_model_accepts_supported_image_sizes(self):
        for size in iradio_dmuv4r.MATCH_MODEL_SIZES:
            self.assertTrue(
                iradio_dmuv4r.IradioDMUV4RRadio.match_model(
                    b"\xFF" * size, "Iradio_DM-UV4R.img"),
                "size %i should match" % size)

        self.assertFalse(
            iradio_dmuv4r.IradioDMUV4RRadio.match_model(
                b"\xFF" * 1234, "wrong.img"))

    def test_driver_is_available_through_chirp_directory(self):
        self.assertIn("iradio_dmuv4r", drivers.__all__)
        self.assertEqual(
            "Iradio_DM-UV4R",
            directory.radio_class_id(iradio_dmuv4r.IradioDMUV4RRadio))
        self.assertIs(
            iradio_dmuv4r.IradioDMUV4RRadio,
            directory.get_radio("Iradio_DM-UV4R"))

    def test_match_model_strips_chirp_metadata(self):
        radio = make_radio()
        raw = b"\xFF" * iradio_dmuv4r.LEGACY_COMPACT_MEM_SIZE
        filedata = raw + radio.MAGIC + radio._make_metadata()

        self.assertTrue(
            iradio_dmuv4r.IradioDMUV4RRadio.match_model(
                filedata, "Iradio_DM-UV4R.img"))

    def test_image_metadata_strip_ignores_embedded_magic(self):
        radio = make_radio()
        raw = bytearray(b"\xFF" * iradio_dmuv4r.MEM_SIZE)
        raw[100:100 + len(radio.MAGIC)] = radio.MAGIC
        raw[200] = 0x42
        filedata = bytes(raw) + radio.MAGIC + radio._make_metadata()

        self.assertTrue(
            iradio_dmuv4r.IradioDMUV4RRadio.match_model(
                filedata, "Iradio_DM-UV4R.img"))

        with tempfile.NamedTemporaryFile(suffix=".img") as img:
            img.write(filedata)
            img.flush()

            loaded = iradio_dmuv4r.IradioDMUV4RRadio(img.name)

        self.assertEqual(iradio_dmuv4r.MEM_SIZE, len(loaded._mmap))
        self.assertEqual(radio.MAGIC, bytes(
            loaded._mmap[100:100 + len(radio.MAGIC)]))
        self.assertEqual(b"\x42", loaded._mmap[200])

    def test_directory_detects_legacy_raw_image(self):
        with tempfile.NamedTemporaryFile(suffix=".img") as img:
            img.write(b"\xFF" * iradio_dmuv4r.LEGACY_COMPACT_MEM_SIZE)
            img.flush()

            radio = directory.get_radio_by_image(img.name)

        self.assertIsInstance(radio, iradio_dmuv4r.IradioDMUV4RRadio)

    def test_process_mmap_pads_compact_images(self):
        for size in (iradio_dmuv4r.LEGACY_COMPACT_MEM_SIZE,
                     iradio_dmuv4r.COMPACT_MEM_SIZE):
            radio = iradio_dmuv4r.IradioDMUV4RRadio(
                memmap.MemoryMapBytes(b"\x00" * size))
            radio.process_mmap()

            self.assertEqual(iradio_dmuv4r.MEM_SIZE, len(radio._mmap))
            self.assertEqual(
                b"\xFF" * (iradio_dmuv4r.MEM_SIZE - size),
                radio._mmap.get(size, iradio_dmuv4r.MEM_SIZE - size))

    def test_oem_cfg_savealldata_offsets_are_covered(self):
        missing = OEM_CFG_SAVEALLDATA_OFFSETS - cfg_setting_offsets()

        self.assertEqual(set(), missing)

    def test_oem_cfg2_savealldata_offsets_are_covered(self):
        missing = OEM_CFG2_SAVEALLDATA_OFFSETS - cfg2_setting_offsets()

        self.assertEqual(set(), missing)

    def test_non_cfg_table_sizes_match_oem_layout(self):
        self.assertEqual(48, iradio_dmuv4r.CHANNEL_RECORD_SIZE)
        self.assertEqual(1024 * 48, iradio_dmuv4r.SEGMENTS["all"][1])
        self.assertEqual(128 * 1024, iradio_dmuv4r.SEGMENTS["zone"][1])
        self.assertLessEqual(250 * 520, iradio_dmuv4r.SEGMENTS["zone"][1])
        self.assertEqual(208 * 1024, iradio_dmuv4r.SEGMENTS["contact"][1])
        self.assertLessEqual(10000 * 21, iradio_dmuv4r.SEGMENTS["contact"][1])
        self.assertEqual(20 * 1024, iradio_dmuv4r.SEGMENTS["group"][1])
        self.assertLessEqual(250 * 80, iradio_dmuv4r.SEGMENTS["group"][1])
        self.assertEqual(12 * 1024, iradio_dmuv4r.SEGMENTS["encrypt"][1])
        self.assertEqual(256 * 48, iradio_dmuv4r.SEGMENTS["encrypt"][1])
        self.assertEqual(100 * 1024, iradio_dmuv4r.SEGMENTS["sms"][1])
        self.assertEqual(4 * 1024, iradio_dmuv4r.SEGMENTS["fm"][1])
        self.assertEqual(16 * 256, iradio_dmuv4r.SMS_PRESET_COUNT *
                         iradio_dmuv4r.SMS_RECORD_SIZE)
        self.assertEqual(80 * 48, iradio_dmuv4r.FM_COUNT *
                         iradio_dmuv4r.FM_RECORD_SIZE)
        self.assertLessEqual(80 * 48, iradio_dmuv4r.SEGMENTS["fm"][1])

    def test_optional_utility_constants_match_newer_oem(self):
        self.assertEqual(bytes([52, 82, 5, 16, 155]), iradio_dmuv4r.READ_MAGIC)
        self.assertEqual(bytes([52, 82, 5, 238, 121]), iradio_dmuv4r.END_MAGIC)
        self.assertEqual(4096, iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE)
        self.assertEqual(29360124, iradio_dmuv4r.GLOBAL_CONTACT_MAX_PAYLOAD)

        radio = make_radio()
        startup_image = radio._get_segment("startup_image")
        startup_image[0] = 0x01
        startup_image[1:1 + iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE] = (
            b"\x55" * iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE)
        radio._set_segment("startup_image", startup_image)

        self.assertEqual(4, len(radio._build_startup_image_upload()))
        self.assertEqual(1, len(radio._build_startup_image_follow_upload()))

    def test_upload_plan_matches_firmware_flash_map(self):
        self.assertEqual((
            (0x90, 0x002, "cfg", 1),
            (0x91, 0x004, "all", 48),
            (0x92, 0x01C, "vfo", 1),
            (0x93, 0x01E, "zone", 128),
            (0x94, 0x05E, "contact", 208),
            (0x95, 0x0C6, "group", 20),
            (0x96, 0x0D0, "encrypt", 12),
            (0x97, 0x0D6, "sms", 4),
            (0x98, 0x0F0, "fm", 4),
        ), iradio_dmuv4r.UPLOAD_PLAN)

    def test_utility_startup_dry_run_does_not_open_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", payload,
                    ])

        output = stdout.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("opcode: 0x9A", output)
        self.assertIn("blocks: 4", output)
        self.assertIn("payload bytes: 4096", output)
        self.assertIn("wire bytes: 4112", output)
        self.assertIn(
            "payload sha256: "
            "ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7",
            output)
        self.assertIn("first frame checksum: 0x9A", output)
        self.assertIn("last frame checksum: 0x9D", output)

    def test_utility_startup_test_pattern_dry_run(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            make_radio().save_mmap(image)

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-test-pattern", "blank",
                    ])

        output = stdout.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("source: startup-test-pattern:blank", output)
        self.assertIn("opcode: 0x9A", output)
        self.assertIn("blocks: 4", output)
        self.assertIn(
            "payload sha256: "
            "ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7",
            output)

    def test_startup_test_patterns_are_deterministic(self):
        utility = load_utility_module()

        blank = utility._startup_test_payload("blank")
        checkerboard = utility._startup_test_payload("checkerboard")
        border = utility._startup_test_payload("border")

        self.assertEqual(iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE, len(blank))
        self.assertEqual(iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE,
                         len(checkerboard))
        self.assertEqual(iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE, len(border))
        self.assertEqual(b"\x00" * len(blank), blank)
        self.assertEqual(bytes([0x55, 0xAA, 0x55, 0xAA]),
                         checkerboard[:4])
        self.assertEqual(b"\xFF", border[:1])
        self.assertEqual(b"\x00" * 3072, checkerboard[1024:])
        self.assertEqual(b"\x00" * 3072, border[1024:])

    def test_utility_global_contacts_dry_run_does_not_open_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--csv", csv_path,
                    ])

        output = stdout.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("opcode: 0xA4", output)
        self.assertIn("blocks: 1", output)
        self.assertIn("payload bytes: 1024", output)
        self.assertIn("wire bytes: 1028", output)
        self.assertIn("declared database bytes: 36", output)
        self.assertIn("payload sha256: " + ONE_ROW_GLOBAL_CONTACTS_SHA256,
                      output)
        self.assertIn("first frame checksum: 0x4A", output)
        self.assertIn("last frame checksum: 0x4A", output)

    def test_utility_global_contacts_test_set_dry_run(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            make_radio().save_mmap(image)

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--global-contacts-test-set", "minimal",
                    ])

        output = stdout.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("source: global-contacts-test-set:minimal", output)
        self.assertIn("opcode: 0xA4", output)
        self.assertIn("blocks: 1", output)
        self.assertIn("declared database bytes: 36", output)
        self.assertIn("payload sha256: " + ONE_ROW_GLOBAL_CONTACTS_SHA256,
                      output)

    def test_utility_dry_run_accepts_expected_payload_sha256(self):
        utility = load_utility_module()
        expected_sha = (
            "ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7")
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", payload,
                        "--expect-payload-sha256", expected_sha.upper(),
                    ])

        self.assertIn("expected payload sha256: matched", stdout.getvalue())

    def test_utility_dry_run_writes_manifest(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            manifest = os.path.join(tmpdir, "startup-manifest.json")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", payload,
                        "--manifest", manifest,
                    ])

            with open(manifest, "r", encoding="utf-8") as manifest_file:
                data = json.load(manifest_file)

        self.assertIn("manifest: ", stdout.getvalue())
        self.assertEqual("iradio-dmuv4r-optional-writer-v1", data["schema"])
        self.assertEqual("startup-image", data["operation"])
        self.assertEqual("0x9A", data["opcode"])
        self.assertEqual(4, data["blocks"])
        self.assertEqual(4096, data["payload_bytes"])
        self.assertEqual(4112, data["wire_bytes"])
        self.assertEqual(
            "ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7",
            data["payload_sha256"])
        self.assertEqual("0x9A", data["first_frame_checksum"])
        self.assertEqual("0x9D", data["last_frame_checksum"])

    def test_utility_manifest_refuses_existing_file_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            manifest = os.path.join(tmpdir, "startup-manifest.json")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)
            with open(manifest, "w", encoding="utf-8") as manifest_file:
                manifest_file.write("{}\n")

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Manifest path already exists"):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", payload,
                        "--manifest", manifest,
                    ])

        open_serial.assert_not_called()

    def test_utility_validation_bundle_writes_strict_command(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)

            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                utility.main([
                    "--image", image,
                    "--operation", "startup-image",
                    "--startup-test-pattern", "blank",
                    "--port", "/dev/ttyUSB0",
                    "--validation-bundle", bundle,
                ])

            manifest_path = os.path.join(bundle, "startup_image_manifest.json")
            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            readme_path = os.path.join(bundle, "startup_image_README.txt")
            backup_dir = os.path.join(bundle, "startup_image_backups")
            report_path = os.path.join(
                bundle, "startup_image_execute_report.json")
            with open(manifest_path, "r", encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            with open(readme_path, "r", encoding="utf-8") as readme_file:
                readme = readme_file.read()
            backup_dir_exists = os.path.isdir(backup_dir)
            command_executable = os.access(command_path, os.X_OK)

        self.assertEqual("startup-image", manifest["operation"])
        self.assertEqual("0x9A", manifest["opcode"])
        self.assertTrue(backup_dir_exists)
        self.assertTrue(command_executable)
        self.assertIn("--strict-validation", command)
        self.assertIn("--expect-manifest", command)
        self.assertIn(manifest_path, command)
        self.assertIn("--backup-dir", command)
        self.assertIn(backup_dir, command)
        self.assertIn("--fail-on-backup-diff", command)
        self.assertIn("--report", command)
        self.assertIn(report_path, command)
        self.assertIn("--startup-test-pattern", command)
        self.assertIn("blank", command)
        self.assertIn("No radio write was performed", readme)
        self.assertIn("--verify-validation-bundle", readme)
        self.assertIn("--verify-execute-report", readme)
        self.assertIn(bundle, readme)

    def test_utility_validation_bundle_writes_global_contacts_test_command(
            self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)

            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                utility.main([
                    "--image", image,
                    "--operation", "global-contacts",
                    "--global-contacts-test-set", "minimal",
                    "--port", "/dev/ttyUSB0",
                    "--validation-bundle", bundle,
                ])

            manifest_path = os.path.join(
                bundle, "global_contacts_manifest.json")
            command_path = os.path.join(
                bundle, "global_contacts_execute_command.sh")
            with open(manifest_path, "r", encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()

        self.assertEqual("global-contacts", manifest["operation"])
        self.assertEqual("0xA4", manifest["opcode"])
        self.assertEqual(
            "global-contacts-test-set:minimal", manifest["source"])
        self.assertEqual(
            ONE_ROW_GLOBAL_CONTACTS_SHA256, manifest["payload_sha256"])
        self.assertIn("--global-contacts-test-set", command)
        self.assertIn("minimal", command)

    def test_utility_validation_bundle_command_uses_absolute_paths(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                make_radio().save_mmap("radio.img")
                with mock.patch.object(
                        utility.serial, "Serial",
                        side_effect=AssertionError("serial opened")):
                    utility.main([
                        "--image", "radio.img",
                        "--operation", "startup-image",
                        "--startup-test-pattern", "blank",
                        "--port", "/dev/ttyUSB0",
                        "--validation-bundle", "bundle",
                    ])
            finally:
                os.chdir(old_cwd)

            bundle = os.path.join(tmpdir, "bundle")
            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            readme_path = os.path.join(bundle, "startup_image_README.txt")
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            with open(readme_path, "r", encoding="utf-8") as readme_file:
                readme = readme_file.read()

        self.assertIn(os.path.join(tmpdir, "radio.img"), command)
        self.assertIn(bundle, command)
        self.assertIn(bundle, readme)
        self.assertNotIn("--image radio.img", command)

    def test_utility_missing_image_is_radio_error_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, "missing.img")
            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Image does not exist"):
                    utility.main([
                        "--image", missing,
                        "--operation", "startup-image",
                        "--startup-test-pattern", "blank",
                    ])

        open_serial.assert_not_called()

    def test_utility_verify_validation_bundle_rejects_relative_image(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            utility.main([
                "--image", image,
                "--operation", "startup-image",
                "--startup-test-pattern", "blank",
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            command = command.replace(image, "radio.img")
            with open(command_path, "w", encoding="utf-8") as command_file:
                command_file.write(command)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "--image must be absolute"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_rejects_relative_bundle_paths(
            self):
        utility = load_utility_module()
        for option, filename in (
                ("--expect-manifest", "startup_image_manifest.json"),
                ("--backup-dir", "startup_image_backups"),
                ("--report", "startup_image_execute_report.json")):
            with self.subTest(option=option):
                with tempfile.TemporaryDirectory() as tmpdir:
                    image = os.path.join(tmpdir, "radio.img")
                    bundle = os.path.join(tmpdir, "bundle")
                    make_radio().save_mmap(image)
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-test-pattern", "blank",
                        "--port", "/dev/ttyUSB0",
                        "--validation-bundle", bundle,
                    ])

                    command_path = os.path.join(
                        bundle, "startup_image_execute_command.sh")
                    absolute = os.path.join(bundle, filename)
                    with open(command_path, "r",
                              encoding="utf-8") as command_file:
                        command = command_file.read()
                    command = command.replace(absolute, filename)
                    with open(command_path, "w",
                              encoding="utf-8") as command_file:
                        command_file.write(command)

                    with self.assertRaisesRegex(
                            utility.errors.RadioError,
                            "%s must be absolute" % option):
                        utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_rejects_relative_payload_source(
            self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)
            utility.main([
                "--image", image,
                "--operation", "startup-image",
                "--startup-payload", payload,
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            command = command.replace(payload, "startup.bin")
            with open(command_path, "w", encoding="utf-8") as command_file:
                command_file.write(command)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "--startup-payload must be absolute"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_rejects_relative_bitmap_source(
            self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bitmap = os.path.join(tmpdir, "startup.png")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            Image.new("RGB", (360, 180), "white").save(bitmap)
            utility.main([
                "--image", image,
                "--operation", "startup-image",
                "--startup-bitmap", bitmap,
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            command = command.replace(bitmap, "startup.png")
            with open(command_path, "w", encoding="utf-8") as command_file:
                command_file.write(command)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "--startup-bitmap must be absolute"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_rejects_relative_csv_source(
            self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write("id,callsign,name,city,state,country,extra\n")
                csv_file.write("123,OK1ABC,Jose,Prague,CZ,Czechia,ignored\n")
            utility.main([
                "--image", image,
                "--operation", "global-contacts",
                "--csv", csv_path,
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            command_path = os.path.join(
                bundle, "global_contacts_execute_command.sh")
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            command = command.replace(csv_path, "contacts.csv")
            with open(command_path, "w", encoding="utf-8") as command_file:
                command_file.write(command)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "--csv must be absolute"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_accepts_startup_bundle(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)

            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                utility.main([
                    "--image", image,
                    "--operation", "startup-image",
                    "--startup-test-pattern", "blank",
                    "--port", "/dev/ttyUSB0",
                    "--validation-bundle", bundle,
                ])
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    utility.main(["--verify-validation-bundle", bundle])

        output = stdout.getvalue()
        self.assertIn("Validation bundle verified", output)
        self.assertIn("operation: startup-image", output)
        self.assertIn(
            "payload sha256: "
            "ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7",
            output)

    def test_utility_verify_validation_bundle_accepts_global_contacts_bundle(
            self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)

            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                utility.main([
                    "--image", image,
                    "--operation", "global-contacts",
                    "--global-contacts-test-set", "minimal",
                    "--port", "/dev/ttyUSB0",
                    "--validation-bundle", bundle,
                ])
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    utility.main(["--verify-validation-bundle", bundle])

        output = stdout.getvalue()
        self.assertIn("Validation bundle verified", output)
        self.assertIn("operation: global-contacts", output)
        self.assertIn(
            "payload sha256: " + ONE_ROW_GLOBAL_CONTACTS_SHA256, output)

    def test_utility_verify_validation_bundle_rejects_edited_command(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            utility.main([
                "--image", image,
                "--operation", "startup-image",
                "--startup-test-pattern", "blank",
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            command = command.replace(" --strict-validation", "")
            with open(command_path, "w", encoding="utf-8") as command_file:
                command_file.write(command)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "missing --strict-validation"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_rejects_bad_shebang(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            utility.main([
                "--image", image,
                "--operation", "startup-image",
                "--startup-test-pattern", "blank",
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            with open(command_path, "r", encoding="utf-8") as command_file:
                command = command_file.read()
            command = command.replace("#!/bin/sh", "#!/bin/bash", 1)
            with open(command_path, "w", encoding="utf-8") as command_file:
                command_file.write(command)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "must start with '#!/bin/sh'"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_rejects_non_executable_command(
            self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            utility.main([
                "--image", image,
                "--operation", "startup-image",
                "--startup-test-pattern", "blank",
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            command_path = os.path.join(
                bundle, "startup_image_execute_command.sh")
            os.chmod(command_path, 0o644)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "command script is not executable"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_verify_validation_bundle_rejects_existing_report(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bundle = os.path.join(tmpdir, "bundle")
            make_radio().save_mmap(image)
            utility.main([
                "--image", image,
                "--operation", "startup-image",
                "--startup-test-pattern", "blank",
                "--port", "/dev/ttyUSB0",
                "--validation-bundle", bundle,
            ])

            report_path = os.path.join(
                bundle, "startup_image_execute_report.json")
            with open(report_path, "w", encoding="utf-8") as report_file:
                report_file.write("{}\n")

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "execute report already exists"):
                utility.main(["--verify-validation-bundle", bundle])

    def test_utility_validation_bundle_refuses_existing_outputs(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            bundle = os.path.join(tmpdir, "bundle")
            os.mkdir(bundle)
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)
            with open(os.path.join(bundle, "startup_image_manifest.json"),
                      "w", encoding="utf-8") as manifest_file:
                manifest_file.write("{}\n")

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Manifest path already exists"):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", payload,
                        "--validation-bundle", bundle,
                    ])

        open_serial.assert_not_called()

    def test_utility_startup_sources_are_mutually_exclusive(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "startup-image",
                    "--startup-payload", "startup.bin",
                    "--startup-test-pattern", "blank",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--startup-payload, --startup-bitmap, and --startup-test-pattern",
            stderr.getvalue())

    def test_utility_global_contacts_sources_are_mutually_exclusive(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--csv", "contacts.csv",
                    "--global-contacts-test-set", "minimal",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("mutually exclusive", stderr.getvalue())

    def test_utility_validation_bundle_is_dry_run_only(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "startup-image",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--i-have-current-backup",
                    "--expect-payload-sha256", "0" * 64,
                    "--validation-bundle", "bundle",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--validation-bundle is only valid without --execute",
                      stderr.getvalue())

    def test_utility_dry_run_accepts_expected_manifest(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            manifest = os.path.join(tmpdir, "startup-manifest.json")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)

            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                utility.main([
                    "--image", image,
                    "--operation", "startup-image",
                    "--startup-payload", payload,
                    "--manifest", manifest,
                ])
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", payload,
                        "--expect-manifest", manifest,
                    ])

        self.assertIn("expected manifest: matched", stdout.getvalue())

    def test_utility_execute_refuses_manifest_mismatch_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            manifest = os.path.join(tmpdir, "startup-manifest.json")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                utility.main([
                    "--image", image,
                    "--operation", "startup-image",
                    "--startup-payload", payload,
                    "--manifest", manifest,
                ])

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Manifest mismatch for operation"):
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--i-have-current-backup",
                        "--csv", csv_path,
                        "--expect-manifest", manifest,
                    ])

        open_serial.assert_not_called()

    def test_utility_execute_refuses_missing_manifest_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            manifest = os.path.join(tmpdir, "missing-manifest.json")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Manifest does not exist"):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--i-have-current-backup",
                        "--startup-payload", payload,
                        "--expect-manifest", manifest,
                    ])

        open_serial.assert_not_called()

    def test_utility_manifest_is_dry_run_only(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--i-have-current-backup",
                    "--manifest", "manifest.json",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--manifest is only valid without --execute",
                      stderr.getvalue())

    def test_utility_execute_refuses_payload_sha256_mismatch_before_serial(
            self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Payload SHA-256 mismatch"):
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--i-have-current-backup",
                        "--csv", csv_path,
                        "--expect-payload-sha256", "0" * 64,
                    ])

        open_serial.assert_not_called()

    def test_utility_rejects_invalid_expected_payload_sha256(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            payload = os.path.join(tmpdir, "startup.bin")
            make_radio().save_mmap(image)
            with open(payload, "wb") as payload_file:
                payload_file.write(b"\x00" * 1024)

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "64 hex characters"):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", payload,
                        "--expect-payload-sha256", "not-a-sha",
                    ])

        open_serial.assert_not_called()

    def test_utility_startup_payload_refuses_directory_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            make_radio().save_mmap(image)

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Startup payload is not a file"):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-payload", tmpdir,
                    ])

        open_serial.assert_not_called()

    def test_utility_global_contacts_refuses_directory_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            make_radio().save_mmap(image)

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Global contacts CSV is not a file"):
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--csv", tmpdir,
                    ])

        open_serial.assert_not_called()

    def test_utility_execute_requires_port(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--execute requires --port", stderr.getvalue())

    def test_utility_execute_requires_backup_confirmation(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--execute requires --i-have-current-backup or --backup-before",
            stderr.getvalue())

    def test_utility_execute_requires_payload_expectation(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            stderr = io.StringIO()
            with mock.patch.object(utility, "_open_serial") as open_serial:
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as err:
                        utility.main([
                            "--image", image,
                            "--operation", "global-contacts",
                            "--execute",
                            "--port", "/dev/ttyUSB0",
                            "--i-have-current-backup",
                            "--csv", csv_path,
                        ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--execute requires --expect-manifest or --expect-payload-sha256",
            stderr.getvalue())
        open_serial.assert_not_called()

    def test_utility_backup_only_reads_without_writer_inputs(self):
        utility = load_utility_module()
        with mock.patch.object(utility, "_backup_radio") as backup_radio:
            utility.main([
                "--backup-only", "backup.img",
                "--port", "/dev/ttyUSB0",
            ])

        backup_radio.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, "backup.img", overwrite=False)

    def test_utility_backup_only_allows_overwrite(self):
        utility = load_utility_module()
        with mock.patch.object(utility, "_backup_radio") as backup_radio:
            utility.main([
                "--backup-only", "backup.img",
                "--port", "/dev/ttyUSB0",
                "--overwrite-backup",
            ])

        backup_radio.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, "backup.img", overwrite=True)

    def test_utility_backup_only_requires_port(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--backup-only", "backup.img",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--backup-only requires --port", stderr.getvalue())

    def test_utility_backup_only_refuses_writer_options(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with mock.patch.object(utility, "_backup_radio") as backup_radio:
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as err:
                    utility.main([
                        "--backup-only", "backup.img",
                        "--port", "/dev/ttyUSB0",
                        "--image", "radio.img",
                    ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--backup-only cannot be combined with writer",
            stderr.getvalue())
        backup_radio.assert_not_called()

    def test_utility_backup_before_satisfies_execute_guard(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            backup = os.path.join(tmpdir, "backup.img")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            order = []
            with mock.patch.object(
                    utility, "_backup_before_execute",
                    side_effect=lambda *args, **kwargs: order.append(
                        "backup")) as backup_fn:
                with mock.patch.object(
                        utility, "_execute",
                        side_effect=lambda *args: order.append(
                            "execute")) as exec_fn:
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--backup-before", backup,
                        "--csv", csv_path,
                        "--expect-payload-sha256",
                        ONE_ROW_GLOBAL_CONTACTS_SHA256,
                    ])

        self.assertEqual(["backup", "execute"], order)
        backup_fn.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, backup, overwrite=False)
        self.assertEqual("/dev/ttyUSB0", exec_fn.call_args[0][2])

    def test_utility_execute_passes_prebuilt_global_contacts_test_blocks(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            make_radio().save_mmap(image)

            captured = {}

            def execute(_radio, operation, port, timeout, blocks):
                captured["operation"] = operation
                captured["port"] = port
                captured["timeout"] = timeout
                captured["blocks"] = blocks

            with mock.patch.object(utility, "_execute", side_effect=execute):
                utility.main([
                    "--image", image,
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--i-have-current-backup",
                    "--global-contacts-test-set", "minimal",
                    "--expect-payload-sha256",
                    ONE_ROW_GLOBAL_CONTACTS_SHA256,
                ])

        self.assertEqual("global-contacts", captured["operation"])
        self.assertEqual("/dev/ttyUSB0", captured["port"])
        self.assertEqual(2.0, captured["timeout"])
        self.assertEqual(1, len(captured["blocks"]))
        self.assertEqual(b"\x00\x00\x00\x24", captured["blocks"][0][:4])

    def test_utility_execute_with_blocks_does_not_rebuild_payload(self):
        utility = load_utility_module()
        radio = make_radio()
        blocks = [b"\xFF" * iradio_dmuv4r.BLOCK_SIZE]
        pipe = mock.Mock()
        radio._build_global_contacts_upload = mock.Mock(
            side_effect=AssertionError("payload rebuilt"))

        with mock.patch.object(
                utility, "_open_serial", return_value=pipe) as open_serial:
            with mock.patch.object(
                    radio, "_sync_out_utility_blocks") as sync_blocks:
                utility._execute(
                    radio, "global-contacts", "/dev/ttyUSB0", 2.0, blocks)

        open_serial.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, radio.BAUD_RATE)
        sync_blocks.assert_called_once_with(
            0xA4, blocks, "Uploading global contacts")
        pipe.close.assert_called_once_with()

    def test_utility_backup_after_runs_after_execute(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            order = []
            with mock.patch.object(
                    utility, "_backup_before_execute",
                    side_effect=lambda *args, **kwargs: order.append(
                        "before")) as before_fn:
                with mock.patch.object(
                        utility, "_execute",
                        side_effect=lambda *args: order.append("execute")):
                    with mock.patch.object(
                            utility, "_backup_after_execute",
                            side_effect=lambda *args, **kwargs: order.append(
                                "after")) as after_fn:
                        with mock.patch.object(
                                utility, "_compare_backup_images",
                                side_effect=lambda *args, **kwargs:
                                order.append("compare")) as compare_fn:
                            utility.main([
                                "--image", image,
                                "--operation", "global-contacts",
                                "--execute",
                                "--port", "/dev/ttyUSB0",
                                "--backup-before", before,
                                "--backup-after", after,
                                "--compare-backups",
                                "--csv", csv_path,
                                "--expect-payload-sha256",
                                ONE_ROW_GLOBAL_CONTACTS_SHA256,
                            ])

        self.assertEqual(["before", "execute", "after", "compare"], order)
        before_fn.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, before, overwrite=False)
        after_fn.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, after, overwrite=False)
        compare_fn.assert_called_once_with(
            before, after, fail_on_diff=False)

    def test_utility_backup_dir_generates_validation_backups(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            backup_dir = os.path.join(tmpdir, "backups")
            os.mkdir(backup_dir)
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            before = os.path.join(
                backup_dir,
                "iradio_dmuv4r_global_contacts_20260530-120000_before.img")
            after = os.path.join(
                backup_dir,
                "iradio_dmuv4r_global_contacts_20260530-120000_after.img")
            order = []
            with mock.patch.object(
                    utility.time, "strftime",
                    return_value="20260530-120000"):
                with mock.patch.object(
                        utility, "_backup_before_execute",
                        side_effect=lambda *args, **kwargs: order.append(
                            "before")) as before_fn:
                    with mock.patch.object(
                            utility, "_execute",
                            side_effect=lambda *args: order.append("execute")):
                        with mock.patch.object(
                                utility, "_backup_after_execute",
                                side_effect=lambda *args, **kwargs:
                                order.append("after")) as after_fn:
                            with mock.patch.object(
                                    utility, "_compare_backup_images",
                                    side_effect=lambda *args, **kwargs:
                                    order.append("compare")) as compare_fn:
                                utility.main([
                                    "--image", image,
                                    "--operation", "global-contacts",
                                    "--execute",
                                    "--port", "/dev/ttyUSB0",
                                    "--backup-dir", backup_dir,
                                    "--csv", csv_path,
                                    "--expect-payload-sha256",
                                    ONE_ROW_GLOBAL_CONTACTS_SHA256,
                                ])

        self.assertEqual(["before", "execute", "after", "compare"], order)
        before_fn.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, before, overwrite=False)
        after_fn.assert_called_once_with(
            "/dev/ttyUSB0", 2.0, after, overwrite=False)
        compare_fn.assert_called_once_with(
            before, after, fail_on_diff=False)

    def test_utility_after_backup_retries_when_radio_is_not_ready(self):
        utility = load_utility_module()
        with mock.patch.object(
                utility, "_backup_radio",
                side_effect=[utility.errors.RadioNoResponse(), None]
        ) as backup_fn:
            with mock.patch.object(utility.time, "sleep") as sleep_fn:
                utility._backup_after_execute(
                    "/dev/ttyUSB0", 2.0, "/tmp/after.img")

        self.assertEqual(2, backup_fn.call_count)
        backup_fn.assert_has_calls([
            mock.call("/dev/ttyUSB0", 2.0, "/tmp/after.img",
                      overwrite=False),
            mock.call("/dev/ttyUSB0", 2.0, "/tmp/after.img",
                      overwrite=False),
        ])
        sleep_fn.assert_called_once_with(2.0)

    def test_utility_execute_writes_success_report(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            report = os.path.join(tmpdir, "report.json")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")
            manifest = os.path.join(tmpdir, "manifest.json")
            utility.main([
                "--image", image,
                "--operation", "global-contacts",
                "--csv", csv_path,
                "--manifest", manifest,
            ])

            order = []

            def compare(*args, **kwargs):
                order.append("compare")
                return []

            with mock.patch.object(
                    utility, "_backup_before_execute",
                    side_effect=lambda *args, **kwargs: order.append(
                        "before")):
                with mock.patch.object(
                        utility, "_execute",
                        side_effect=lambda *args: order.append("execute")):
                    with mock.patch.object(
                            utility, "_backup_after_execute",
                            side_effect=lambda *args, **kwargs:
                            order.append("after")):
                        with mock.patch.object(
                                utility, "_compare_backup_images",
                                side_effect=compare):
                            with mock.patch.object(
                                    utility, "_utc_timestamp",
                                    side_effect=[
                                        "2026-05-30T03:10:00Z",
                                        "2026-05-30T03:10:01Z"]):
                                utility.main([
                                    "--image", image,
                                    "--operation", "global-contacts",
                                    "--execute",
                                    "--port", "/dev/ttyUSB0",
                                    "--strict-validation",
                                    "--backup-before", before,
                                    "--backup-after", after,
                                    "--compare-backups",
                                    "--fail-on-backup-diff",
                                    "--csv", csv_path,
                                    "--expect-manifest", manifest,
                                    "--report", report,
                                ])

            with open(report, "r", encoding="utf-8") as report_file:
                data = json.load(report_file)

        self.assertEqual(["before", "execute", "after", "compare"], order)
        self.assertEqual(
            "iradio-dmuv4r-optional-execute-report-v1", data["schema"])
        self.assertEqual("success", data["status"])
        self.assertEqual("global-contacts", data["operation"])
        self.assertEqual("/dev/ttyUSB0", data["port"])
        self.assertEqual("2026-05-30T03:10:00Z", data["started_at_utc"])
        self.assertEqual("2026-05-30T03:10:01Z", data["finished_at_utc"])
        self.assertEqual(before, data["backup_before"])
        self.assertEqual(after, data["backup_after"])
        self.assertTrue(data["compare_backups"])
        self.assertTrue(data["normal_codeplug_unchanged"])
        self.assertEqual([], data["backup_differences"])
        self.assertIsNone(data["verified_payload_sha256"])
        self.assertEqual(
            ONE_ROW_GLOBAL_CONTACTS_SHA256,
            data["verified_manifest_sha256"])
        self.assertEqual(manifest, data["expected_manifest"])
        self.assertEqual(
            ONE_ROW_GLOBAL_CONTACTS_SHA256,
            data["payload_manifest"]["payload_sha256"])
        self.assertEqual("0xA4", data["payload_manifest"]["opcode"])

    def test_utility_verify_execute_report_accepts_success_report(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            manifest = os.path.join(tmpdir, "manifest.json")
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            report = os.path.join(tmpdir, "report.json")
            make_radio().save_mmap(image)
            make_radio().save_mmap(before)
            make_radio().save_mmap(after)
            utility.main([
                "--image", image,
                "--operation", "global-contacts",
                "--global-contacts-test-set", "minimal",
                "--manifest", manifest,
            ])
            with open(manifest, "r", encoding="utf-8") as manifest_file:
                payload_manifest = json.load(manifest_file)
            with open(report, "w", encoding="utf-8") as report_file:
                json.dump({
                    "schema": "iradio-dmuv4r-optional-execute-report-v1",
                    "status": "success",
                    "started_at_utc": "2026-05-30T03:10:00Z",
                    "finished_at_utc": "2026-05-30T03:10:01Z",
                    "operation": "global-contacts",
                    "port": "/dev/ttyUSB0",
                    "timeout_seconds": 2.0,
                    "payload_manifest": payload_manifest,
                    "verified_payload_sha256": None,
                    "verified_manifest_sha256": ONE_ROW_GLOBAL_CONTACTS_SHA256,
                    "expected_manifest": manifest,
                    "backup_before": before,
                    "backup_after": after,
                    "compare_backups": True,
                    "normal_codeplug_unchanged": True,
                    "backup_differences": [],
                }, report_file)

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main(["--verify-execute-report", report])

        output = stdout.getvalue()
        self.assertIn("Execute report verified", output)
        self.assertIn("operation: global-contacts", output)
        self.assertIn("Backup comparison: normal codeplug sections unchanged",
                      output)

    def test_utility_verify_execute_report_rejects_backup_difference(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            manifest = os.path.join(tmpdir, "manifest.json")
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            report = os.path.join(tmpdir, "report.json")
            make_radio().save_mmap(image)
            make_radio().save_mmap(before)
            changed = make_radio()
            cfg = changed._get_segment("cfg")
            cfg[0] = 0x00
            changed._set_segment("cfg", cfg)
            changed.save_mmap(after)
            utility.main([
                "--image", image,
                "--operation", "global-contacts",
                "--global-contacts-test-set", "minimal",
                "--manifest", manifest,
            ])
            with open(manifest, "r", encoding="utf-8") as manifest_file:
                payload_manifest = json.load(manifest_file)
            with open(report, "w", encoding="utf-8") as report_file:
                json.dump({
                    "schema": "iradio-dmuv4r-optional-execute-report-v1",
                    "status": "success",
                    "operation": "global-contacts",
                    "payload_manifest": payload_manifest,
                    "verified_manifest_sha256": ONE_ROW_GLOBAL_CONTACTS_SHA256,
                    "expected_manifest": manifest,
                    "backup_before": before,
                    "backup_after": after,
                    "compare_backups": True,
                    "normal_codeplug_unchanged": True,
                    "backup_differences": [],
                }, report_file)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "Backup comparison found codeplug differences"):
                utility.main(["--verify-execute-report", report])

    def test_utility_verify_execute_report_rejects_manifest_mismatch(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            manifest = os.path.join(tmpdir, "manifest.json")
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            report = os.path.join(tmpdir, "report.json")
            make_radio().save_mmap(image)
            make_radio().save_mmap(before)
            make_radio().save_mmap(after)
            utility.main([
                "--image", image,
                "--operation", "global-contacts",
                "--global-contacts-test-set", "minimal",
                "--manifest", manifest,
            ])
            with open(manifest, "r", encoding="utf-8") as manifest_file:
                payload_manifest = json.load(manifest_file)
            payload_manifest["payload_sha256"] = "0" * 64
            with open(report, "w", encoding="utf-8") as report_file:
                json.dump({
                    "schema": "iradio-dmuv4r-optional-execute-report-v1",
                    "status": "success",
                    "operation": "global-contacts",
                    "payload_manifest": payload_manifest,
                    "verified_manifest_sha256": "0" * 64,
                    "expected_manifest": manifest,
                    "backup_before": before,
                    "backup_after": after,
                    "compare_backups": True,
                    "normal_codeplug_unchanged": True,
                    "backup_differences": [],
                }, report_file)

            with self.assertRaisesRegex(
                    utility.errors.RadioError,
                    "Manifest mismatch"):
                utility.main(["--verify-execute-report", report])

    def test_utility_strict_validation_requires_full_gate_set(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            report = os.path.join(tmpdir, "report.json")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            stderr = io.StringIO()
            with mock.patch.object(utility, "_open_serial") as open_serial:
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as err:
                        utility.main([
                            "--image", image,
                            "--operation", "global-contacts",
                            "--execute",
                            "--port", "/dev/ttyUSB0",
                            "--strict-validation",
                            "--backup-before", os.path.join(
                                tmpdir, "before.img"),
                            "--backup-after", os.path.join(tmpdir,
                                                           "after.img"),
                            "--compare-backups",
                            "--fail-on-backup-diff",
                            "--csv", csv_path,
                            "--expect-payload-sha256",
                            ONE_ROW_GLOBAL_CONTACTS_SHA256,
                            "--report", report,
                        ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--strict-validation requires --expect-manifest",
            stderr.getvalue())
        open_serial.assert_not_called()

    def test_utility_strict_validation_accepts_backup_dir(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            backup_dir = os.path.join(tmpdir, "backups")
            manifest = os.path.join(tmpdir, "manifest.json")
            report = os.path.join(tmpdir, "report.json")
            os.mkdir(backup_dir)
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")
            utility.main([
                "--image", image,
                "--operation", "global-contacts",
                "--csv", csv_path,
                "--manifest", manifest,
            ])

            order = []
            with mock.patch.object(
                    utility.time, "strftime",
                    return_value="20260530-120000"):
                with mock.patch.object(
                        utility, "_backup_before_execute",
                        side_effect=lambda *args, **kwargs: order.append(
                            "before")):
                    with mock.patch.object(
                            utility, "_execute",
                            side_effect=lambda *args: order.append("execute")):
                        with mock.patch.object(
                                utility, "_backup_after_execute",
                                side_effect=lambda *args, **kwargs:
                                order.append("after")):
                            with mock.patch.object(
                                    utility, "_compare_backup_images",
                                    side_effect=lambda *args, **kwargs: []):
                                utility.main([
                                    "--image", image,
                                    "--operation", "global-contacts",
                                    "--execute",
                                    "--port", "/dev/ttyUSB0",
                                    "--strict-validation",
                                    "--backup-dir", backup_dir,
                                    "--csv", csv_path,
                                    "--expect-manifest", manifest,
                                    "--fail-on-backup-diff",
                                    "--report", report,
                                ])

            self.assertEqual(["before", "execute", "after"], order)
            self.assertTrue(os.path.exists(report))

    def test_utility_report_refuses_existing_file_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            report = os.path.join(tmpdir, "report.json")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")
            with open(report, "w", encoding="utf-8") as report_file:
                report_file.write("{}\n")

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Report path already exists"):
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--i-have-current-backup",
                        "--csv", csv_path,
                        "--expect-payload-sha256",
                        ONE_ROW_GLOBAL_CONTACTS_SHA256,
                        "--report", report,
                    ])

        open_serial.assert_not_called()

    def test_utility_report_requires_execute(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--report", "report.json",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--report requires --execute", stderr.getvalue())

    def test_utility_overwrite_report_requires_report(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--overwrite-report",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--overwrite-report requires --report",
                      stderr.getvalue())

    def test_utility_backup_before_requires_execute(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--backup-before", "backup.img",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--backup-before requires --execute", stderr.getvalue())

    def test_utility_backup_after_requires_execute(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--backup-after", "backup.img",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--backup-after requires --execute", stderr.getvalue())

    def test_utility_backup_dir_requires_execute(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--backup-dir", "backups",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn("--backup-dir requires --execute", stderr.getvalue())

    def test_utility_backup_dir_conflicts_with_explicit_backup(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--backup-dir", "backups",
                    "--backup-before", "before.img",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--backup-dir cannot be combined with explicit backup paths",
            stderr.getvalue())

    def test_utility_overwrite_backup_requires_backup_before(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--i-have-current-backup",
                    "--overwrite-backup",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--overwrite-backup requires --backup-before, --backup-after, "
            "or --backup-dir",
            stderr.getvalue())

    def test_utility_before_and_after_backups_must_differ(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--backup-before", "same.img",
                    "--backup-after", "same.img",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--backup-before and --backup-after must differ",
            stderr.getvalue())

    def test_utility_compare_backups_requires_before_and_after(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--backup-before", "before.img",
                    "--compare-backups",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--compare-backups requires --backup-before and --backup-after",
            stderr.getvalue())

    def test_utility_fail_on_backup_diff_requires_compare(self):
        utility = load_utility_module()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as err:
                utility.main([
                    "--image", "unused.img",
                    "--operation", "global-contacts",
                    "--execute",
                    "--port", "/dev/ttyUSB0",
                    "--backup-before", "before.img",
                    "--backup-after", "after.img",
                    "--fail-on-backup-diff",
                ])

        self.assertEqual(2, err.exception.code)
        self.assertIn(
            "--fail-on-backup-diff requires --compare-backups",
            stderr.getvalue())

    def test_utility_backup_before_refuses_existing_file_before_serial(self):
        utility = load_utility_module()
        with tempfile.NamedTemporaryFile() as backup:
            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Backup path already exists"):
                    utility._backup_before_execute(
                        "/dev/ttyUSB0", 2.0, backup.name)

        open_serial.assert_not_called()

    def test_utility_backup_after_refuses_existing_file_before_serial(self):
        utility = load_utility_module()
        with tempfile.NamedTemporaryFile() as backup:
            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Backup path already exists"):
                    utility.main([
                        "--image", "unused.img",
                        "--operation", "global-contacts",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--i-have-current-backup",
                        "--backup-after", backup.name,
                    ])

        open_serial.assert_not_called()

    def test_utility_backup_before_refuses_missing_directory_before_serial(
            self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            backup = os.path.join(tmpdir, "missing", "backup.img")
            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Backup directory does not exist"):
                    utility._backup_before_execute(
                        "/dev/ttyUSB0", 2.0, backup)

        open_serial.assert_not_called()

    def test_utility_backup_dir_refuses_missing_directory_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            csv_path = os.path.join(tmpdir, "contacts.csv")
            backup_dir = os.path.join(tmpdir, "missing")
            make_radio().save_mmap(image)
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write(
                    "No,Radio ID,Callsign,Name,City,State,Country\n")
                csv_file.write(
                    "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")

            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Backup directory does not exist"):
                    utility.main([
                        "--image", image,
                        "--operation", "global-contacts",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--backup-dir", backup_dir,
                        "--csv", csv_path,
                    ])

        open_serial.assert_not_called()

    def test_utility_backup_after_refuses_directory_before_serial(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as backup:
            with mock.patch.object(utility, "_open_serial") as open_serial:
                with self.assertRaisesRegex(
                        utility.errors.RadioError,
                        "Backup path is a directory"):
                    utility.main([
                        "--image", "unused.img",
                        "--operation", "global-contacts",
                        "--execute",
                        "--port", "/dev/ttyUSB0",
                        "--i-have-current-backup",
                        "--overwrite-backup",
                        "--backup-after", backup,
                    ])

        open_serial.assert_not_called()

    def test_utility_compare_backups_reports_unchanged_codeplug(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            radio = make_radio()
            radio.save_mmap(before)
            radio.save_mmap(after)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                differences = utility._compare_backup_images(before, after)

        self.assertEqual([], differences)
        self.assertIn("unchanged", stdout.getvalue())

    def test_utility_compare_backups_reports_codeplug_differences(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            make_radio().save_mmap(before)
            radio = make_radio()
            cfg = radio._get_segment("cfg")
            cfg[100] = 0x12
            radio._set_segment("cfg", cfg)
            radio.save_mmap(after)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                differences = utility._compare_backup_images(before, after)

            with self.assertRaisesRegex(
                    utility.errors.RadioError, "codeplug differences"):
                utility._compare_backup_images(
                    before, after, fail_on_diff=True)

        self.assertEqual([("cfg", 1)], differences)
        self.assertIn("cfg: 1 bytes differ", stdout.getvalue())

    def test_utility_compare_backups_ignores_embedded_magic(self):
        utility = load_utility_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            before = os.path.join(tmpdir, "before.img")
            after = os.path.join(tmpdir, "after.img")
            radio = make_radio()
            raw = bytearray(radio._mmap.get_packed())
            raw[100:100 + len(radio.MAGIC)] = radio.MAGIC

            with open(before, "wb") as before_file:
                before_file.write(raw)
                before_file.write(radio.MAGIC)
                before_file.write(radio._make_metadata())

            raw[200] = 0x12
            with open(after, "wb") as after_file:
                after_file.write(raw)
                after_file.write(radio.MAGIC)
                after_file.write(radio._make_metadata())

            differences = utility._compare_backup_images(before, after)

        self.assertEqual([("cfg", 1)], differences)

    def test_startup_bitmap_conversion_matches_oem_layout(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        utility = load_utility_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            bitmap = os.path.join(tmpdir, "startup.png")
            image = Image.new("RGB", (360, 180), "black")
            image.putpixel((1, 0), (255, 255, 255))
            image.save(bitmap)

            payload = utility._startup_payload_from_bitmap(
                bitmap, 360, 180, 0, 0)

        self.assertEqual(
            iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE, len(payload))
        self.assertEqual(0x00, payload[896])
        self.assertEqual(0xFE, payload[897])
        self.assertEqual(0xFF, payload[898])
        self.assertEqual(b"\x00" * 3072, payload[1024:])

    def test_utility_startup_bitmap_dry_run_does_not_open_serial(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        utility = load_utility_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            image = os.path.join(tmpdir, "radio.img")
            bitmap = os.path.join(tmpdir, "startup.png")
            make_radio().save_mmap(image)
            Image.new("RGB", (360, 180), "white").save(bitmap)

            stdout = io.StringIO()
            with mock.patch.object(
                    utility.serial, "Serial",
                    side_effect=AssertionError("serial opened")):
                with contextlib.redirect_stdout(stdout):
                    utility.main([
                        "--image", image,
                        "--operation", "startup-image",
                        "--startup-bitmap", bitmap,
                    ])

        output = stdout.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("opcode: 0x9A", output)
        self.assertIn("blocks: 4", output)

    def test_tone_codec(self):
        raw = iradio_dmuv4r._encode_tone("Tone", 123.0, "N")
        self.assertEqual(("Tone", 123.0, "N"),
                         iradio_dmuv4r._decode_tone(raw))

        raw = iradio_dmuv4r._encode_tone("DTCS", 245, "R")
        self.assertEqual(("DTCS", 245, "R"),
                         iradio_dmuv4r._decode_tone(raw))

    def test_live_vendor_channel_records_roundtrip_without_edits(self):
        radio = make_radio()

        for number, raw_hex in LIVE_VENDOR_CHANNEL_RECORDS.items():
            with self.subTest(number=number):
                raw = bytes.fromhex(raw_hex)
                radio._write_channel(number, raw)
                radio.set_memory(radio.get_memory(number))

                self.assertEqual(raw, bytes(radio._channel_data(number)))

    def test_live_vendor_changed_channel_definitions_decode(self):
        radio = make_radio()

        for number in (41, 42, 43, 44, 45, 46):
            radio._write_channel(
                number, bytes.fromhex(LIVE_VENDOR_CHANNEL_RECORDS[number]))

        def extras(memory):
            return {item.get_name(): item.value for item in memory.extra}

        ch41 = radio.get_memory(41)
        self.assertEqual("EMG_chang", ch41.name)
        self.assertEqual("Only RX", str(extras(ch41)["rx_tx"]))

        ch42 = radio.get_memory(42)
        self.assertEqual("UT_chang", ch42.name)
        self.assertEqual(radio.get_features().valid_power_levels[0],
                         ch42.power)

        ch43 = radio.get_memory(43)
        self.assertEqual("ZAZEMI_chan", ch43.name)
        self.assertEqual("", ch43.skip)

        ch44 = radio.get_memory(44)
        self.assertEqual("PROGRAM_digi", ch44.name)
        self.assertEqual("DMR", ch44.mode)

        ch45 = radio.get_memory(45)
        self.assertEqual("INFO_encr", ch45.name)
        self.assertEqual(1, int(extras(ch45)["encryption_index"]))

        ch46 = radio.get_memory(46)
        self.assertEqual("SUBCAMP_color15", ch46.name)
        self.assertEqual(15, int(extras(ch46)["color_code"]))

    def test_live_vendor_feature_channel_definitions_decode(self):
        radio = make_radio()

        for number in (47, 48, 49, 50, 51, 52, 53):
            radio._write_channel(
                number, bytes.fromhex(LIVE_VENDOR_CHANNEL_RECORDS[number]))

        def extras(memory):
            return {item.get_name(): item.value for item in memory.extra}

        ch47 = radio.get_memory(47)
        self.assertEqual("FOTO_ts2", ch47.name)
        self.assertEqual("DMR", ch47.mode)
        self.assertEqual("2", str(extras(ch47)["time_slot"]))

        ch48 = radio.get_memory(48)
        self.assertEqual("REZERV1_ds2", ch48.name)
        self.assertEqual("DMR", ch48.mode)
        self.assertEqual("Dual Slot On", str(extras(ch48)["dmr_mode"]))

        ch49 = radio.get_memory(49)
        self.assertEqual("PROG2_chf", ch49.name)
        self.assertEqual("DMR", ch49.mode)
        self.assertEqual("Channel Free", str(extras(ch49)["call_priority"]))

        ch50 = radio.get_memory(50)
        self.assertEqual("REZERV2_chfci", ch50.name)
        self.assertEqual("DMR", ch50.mode)
        self.assertEqual("", ch50.skip)
        self.assertEqual("Color Code Idle",
                         str(extras(ch50)["call_priority"]))

        ch51 = radio.get_memory(51)
        self.assertEqual("REZERV3_prom", ch51.name)
        self.assertEqual("DMR", ch51.mode)
        self.assertTrue(bool(extras(ch51)["digital_monitor"]))

        ch52 = radio.get_memory(52)
        self.assertEqual("UT-REZ_txonly", ch52.name)
        self.assertEqual("Only TX", str(extras(ch52)["rx_tx"]))

        ch53 = radio.get_memory(53)
        self.assertEqual("rx_only", ch53.name)
        self.assertEqual("Only RX", str(extras(ch53)["rx_tx"]))

    def test_live_vendor_contact_record_decode(self):
        radio = make_radio()
        contact = bytearray(b"\xFF" * iradio_dmuv4r.SEGMENTS["contact"][1])
        for slot, raw_hex in LIVE_VENDOR_CONTACT_RECORDS.items():
            base = slot * iradio_dmuv4r.CONTACT_RECORD_SIZE
            contact[base:base + iradio_dmuv4r.CONTACT_RECORD_SIZE] = (
                bytes.fromhex(raw_hex))
        radio._set_segment("contact", contact)

        contact = radio.get_settings()["dmr_contacts"]["contact_00002"]

        self.assertEqual("Private", str(contact["contact_00002_type"].value))
        self.assertEqual(434343, int(contact["contact_00002_id"].value))
        self.assertEqual("Individual_call",
                         str(contact["contact_00002_name"].value))

    def test_low_power_memory_encodes_low_power_bit(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 1
        mem.freq = 145500000
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "NFM"
        mem.tmode = ""
        mem.name = "LOWPWR"
        mem.power = radio.get_features().valid_power_levels[0]
        mem.skip = ""
        mem.extra = radio.get_memory(1).extra

        radio.set_memory(mem)

        self.assertEqual(0x00, radio._channel_data(1)[2] & 0x40)

    def test_analog_memory_roundtrip(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 1
        mem.freq = 145500000
        mem.duplex = "+"
        mem.offset = 600000
        mem.mode = "NFM"
        mem.tmode = "Cross"
        mem.cross_mode = "Tone->DTCS"
        mem.rtone = 88.5
        mem.rx_dtcs = 245
        mem.dtcs_polarity = "NR"
        mem.name = "ANALOG1"
        mem.power = radio.get_features().valid_power_levels[1]
        mem.skip = ""
        mem.extra = radio.get_memory(1).extra
        for item in mem.extra:
            if item.get_name() == "raw_mode":
                item.value = "Analog"
            elif item.get_name() == "analog_scramble":
                item.value = "3"
            elif item.get_name() == "tot_index":
                item.value = 7

        radio.set_memory(mem)
        raw = radio._channel_data(1)
        self.assertEqual(0x40, raw[0] & 0xC0)
        self.assertEqual(0x40, raw[2] & 0xC0)
        self.assertEqual(0x80, raw[3] & 0x80)
        self.assertEqual(7, raw[2] & 0x3F)
        self.assertEqual(3, raw[1] & 0x0F)
        self.assertEqual(1, (raw[4] >> 6) & 0x03)
        result = radio.get_memory(1)
        self.assertEqual(mem.freq, result.freq)
        self.assertEqual(mem.duplex, result.duplex)
        self.assertEqual(mem.offset, result.offset)
        self.assertEqual(mem.mode, result.mode)
        self.assertEqual(mem.tmode, result.tmode)
        self.assertEqual(mem.cross_mode, result.cross_mode)
        self.assertEqual(mem.rtone, result.rtone)
        self.assertEqual(mem.rx_dtcs, result.rx_dtcs)

    def test_pm446_6_25khz_grid_validates(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 54
        mem.freq = 446143750
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "NFM"
        mem.tmode = ""
        mem.tuning_step = 6.25
        mem.name = "PMR12"
        mem.power = radio.get_features().valid_power_levels[0]
        mem.skip = ""

        self.assertFalse([
            msg for msg in radio.validate_memory(mem)
            if isinstance(msg, chirp_common.ValidationError)
        ])

    def test_sub_10hz_frequency_grid_is_rejected(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 54
        mem.freq = 446143751
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "NFM"
        mem.tmode = ""
        mem.tuning_step = 0.01
        mem.name = "BADSTEP"
        mem.power = radio.get_features().valid_power_levels[0]
        mem.skip = ""

        self.assertIn(
            "Unable to find a supported tuning step",
            "; ".join(str(msg) for msg in radio.validate_memory(mem)))

    def test_dmr_memory_roundtrip(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 2
        mem.freq = 438500000
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "DMR"
        mem.name = "DMRTEST"
        mem.power = radio.get_features().valid_power_levels[0]
        mem.skip = "S"
        mem.extra = radio.get_memory(2).extra
        for item in mem.extra:
            if item.get_name() == "raw_mode":
                item.value = "DMR"
            elif item.get_name() == "time_slot":
                item.value = "2"
            elif item.get_name() == "color_code":
                item.value = 7
            elif item.get_name() == "contact_index":
                item.value = 123
            elif item.get_name() == "rx_group_index":
                item.value = 4
            elif item.get_name() == "encryption_index":
                item.value = 9
            elif item.get_name() == "channel_id":
                item.value = 310123

        radio.set_memory(mem)
        raw = radio._channel_data(2)
        self.assertEqual(0, (raw[0] >> 6) & 0x03)
        self.assertEqual(1, (raw[0] >> 1) & 0x01)
        self.assertEqual(7, (raw[1] >> 4) & 0x0F)
        self.assertEqual(123, iradio_dmuv4r._u16le(raw, 17))
        self.assertEqual(4, raw[19])
        self.assertEqual(9, iradio_dmuv4r._u16le(raw, 20))
        self.assertEqual(0, raw[4])
        self.assertEqual(310123,
                         iradio_dmuv4r._bcd_to_int(
                             iradio_dmuv4r._u32le(raw, 22)))
        result = radio.get_memory(2)
        self.assertEqual("DMR", result.mode)
        extras = {item.get_name(): item.value for item in result.extra}
        self.assertEqual("2", str(extras["time_slot"]))
        self.assertEqual(7, int(extras["color_code"]))
        self.assertEqual(123, int(extras["contact_index"]))
        self.assertEqual(4, int(extras["rx_group_index"]))
        self.assertEqual(9, int(extras["encryption_index"]))
        self.assertEqual(310123, int(extras["channel_id"]))

    def test_contact_selector_is_labeled_as_oem_selector(self):
        radio = make_radio()

        contact_setting = None
        for item in radio.get_memory(1).extra:
            if item.get_name() == "contact_index":
                contact_setting = item
                break

        self.assertIsNotNone(contact_setting)
        self.assertEqual("Contact Selector Index",
                         contact_setting.get_shortname())
        self.assertIn("OEM combo-box indexes",
                      radio.get_settings()["dmr_contacts"].__doc__)

    def test_dmr_memory_allows_last_encryption_selector(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 4
        mem.freq = 438500000
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "DMR"
        mem.name = "DMRENC"
        mem.power = radio.get_features().valid_power_levels[0]
        mem.skip = ""
        mem.extra = radio.get_memory(4).extra
        for item in mem.extra:
            if item.get_name() == "raw_mode":
                item.value = "DMR"
            elif item.get_name() == "encryption_index":
                item.value = iradio_dmuv4r.ENCRYPTION_COUNT

        radio.set_memory(mem)

        raw = radio._channel_data(4)
        self.assertEqual(iradio_dmuv4r.ENCRYPTION_COUNT,
                         iradio_dmuv4r._u16le(raw, 20))
        extras = {
            item.get_name(): item.value for item in radio.get_memory(4).extra}
        self.assertEqual(iradio_dmuv4r.ENCRYPTION_COUNT,
                         int(extras["encryption_index"]))

    def test_signaling_id_matches_oem_24bit_write(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 5
        mem.freq = 438500000
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "DMR"
        mem.name = "SIGID"
        mem.power = radio.get_features().valid_power_levels[0]
        mem.skip = ""
        mem.extra = radio.get_memory(5).extra
        for item in mem.extra:
            if item.get_name() == "raw_mode":
                item.value = "DMR"
            elif item.get_name() == "signaling_id_hex":
                item.value = "12345678"

        radio.set_memory(mem)

        raw = radio._channel_data(5)
        self.assertEqual(0x00345678, iradio_dmuv4r._u32le(raw, 26))

        iradio_dmuv4r._set_u32le(raw, 26, 0x12345678)
        radio._write_channel(5, raw)
        extras = {
            item.get_name(): item.value for item in radio.get_memory(5).extra}
        self.assertEqual("00345678", str(extras["signaling_id_hex"]))

    def test_power_levels_match_oem_low_high_labels(self):
        radio = make_radio()
        levels = radio.get_features().valid_power_levels

        self.assertEqual(["Low", "High"], [str(level) for level in levels])
        self.assertEqual([0.0, 0.0], [float(level) for level in levels])

    def test_dmr_memory_preserves_power_bits(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 3
        mem.freq = 438500000
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "DMR"
        mem.name = "DMRPWR"
        mem.power = radio.get_features().valid_power_levels[1]
        mem.skip = ""
        mem.extra = radio.get_memory(3).extra

        radio.set_memory(mem)
        raw = radio._channel_data(3)
        self.assertEqual(0x40, raw[2] & 0xC0)
        self.assertEqual(radio.get_features().valid_power_levels[1],
                         radio.get_memory(3).power)

    def test_vfo_special_memory_roundtrip(self):
        radio = make_radio()
        mem = radio.get_memory("VFO-A")
        self.assertEqual("VFO-A", mem.extd_number)
        self.assertEqual(-2, mem.number)
        mem.empty = False
        mem.freq = 145600000
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "FM"
        mem.name = "VFOA"
        mem.power = radio.get_features().valid_power_levels[1]
        mem.skip = ""
        for item in mem.extra:
            if item.get_name() == "raw_mode":
                item.value = "Analog"
            elif item.get_name() == "tot_index":
                item.value = 3

        radio.set_memory(mem)

        vfo = radio._get_segment("vfo")
        self.assertEqual(0x40, vfo[0] & 0xC0)
        self.assertEqual(14560000, iradio_dmuv4r._u32le(vfo, 5))
        self.assertEqual(14560000, iradio_dmuv4r._u32le(vfo, 9))
        self.assertEqual("VFOA",
                         iradio_dmuv4r._decode_string(bytes(vfo[32:48])))
        result = radio.get_memory("VFO-A")
        self.assertEqual(145600000, result.freq)
        self.assertEqual("VFOA", result.name)

    def test_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()
        for group in settings:
            for item in group:
                if item.get_name() == "program_password_hex":
                    item.value = "00112233445566778899AABB"
                elif item.get_name() == "startup_password":
                    item.value = "HELLO"
                elif item.get_name() == "clock_seconds":
                    item.value = 42
                elif item.get_name() == "fm_alias_00":
                    item.value = "FMONE"
                elif item.get_name() == "fm_freq_00":
                    item.value = "99.5"
                elif item.get_name() == "sms_preset_00":
                    item.value = "TEST SMS"
        radio.set_settings(settings)
        reread = radio.get_settings()
        flat = {}
        for item in reread.walk():
            flat[item.get_name()] = str(item.value).strip()
        self.assertEqual("00112233445566778899AABB",
                         flat["program_password_hex"])
        self.assertEqual("HELLO", flat["startup_password"])
        self.assertEqual("42", flat["clock_seconds"])
        self.assertEqual("FMONE", flat["fm_alias_00"])
        self.assertEqual("99.5", flat["fm_freq_00"])
        self.assertEqual("TEST SMS", flat["sms_preset_00"])

    def test_sms_upload_requires_preset_marker(self):
        radio = make_radio()
        sms = radio._get_segment("sms")
        sms[0] = 0x01
        sms[56:56 + iradio_dmuv4r.SMS_TEXT_LEN] = (
            iradio_dmuv4r._encode_string("STALE", iradio_dmuv4r.SMS_TEXT_LEN))
        base = iradio_dmuv4r.SMS_RECORD_SIZE
        sms[base] = 0x00
        sms[base + 56:base + 56 + iradio_dmuv4r.SMS_TEXT_LEN] = (
            iradio_dmuv4r._encode_string("VALID", iradio_dmuv4r.SMS_TEXT_LEN))
        radio._set_segment("sms", sms)

        upload = radio._build_sms_upload()

        self.assertEqual(b"\xFF" * iradio_dmuv4r.SMS_RECORD_SIZE,
                         bytes(upload[:iradio_dmuv4r.SMS_RECORD_SIZE]))
        self.assertEqual(0x00, upload[base])
        self.assertEqual("VALID", iradio_dmuv4r._decode_string(
            bytes(upload[base + 56:base + 56 + iradio_dmuv4r.SMS_TEXT_LEN])))

    def test_cfg0_upload_preserves_radio_tail(self):
        radio = make_radio()
        cfg = radio._get_segment("cfg")
        cfg[:12] = bytes.fromhex("00112233445566778899AABB")
        radio._set_segment("cfg", cfg)
        radio_cfg0 = bytearray(b"\x00" * iradio_dmuv4r.BLOCK_SIZE)
        radio_cfg0[960:1024] = b"\x55" * 64
        payload = radio._build_upload_cfg0(radio_cfg0)
        self.assertEqual(b"\x55" * 64, payload[960:1024])
        self.assertEqual(bytes.fromhex(
            "00112233445566778899AABB"), payload[:12])
        self.assertEqual(b"\xCD\xAB", payload[12:14])
        self.assertEqual(b"\xFF\xFF", payload[14:16])

    def test_dmr_codeplug_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()

        contact = settings["dmr_contacts"]["contact_00001"]
        contact["contact_00001_type"].value = "Group"
        contact["contact_00001_id"].value = 310123
        contact["contact_00001_name"].value = "OPS"

        tglist = settings["dmr_tg_lists"]["tg_000"]
        tglist["tg_000_name"].value = "RXGRP"
        tglist["tg_000_members"].value = "1,2"

        encrypt = settings["dmr_encryption"]["encrypt_000"]
        encrypt["encrypt_000_enabled"].value = True
        encrypt["encrypt_000_type"].value = "AES-128"
        encrypt["encrypt_000_name"].value = "KEY1"
        encrypt["encrypt_000_key_hex"].value = (
            "00112233445566778899AABBCCDDEEFF")

        radio.set_settings(settings)

        contact_data = radio._get_segment("contact")
        base = iradio_dmuv4r.CONTACT_RECORD_SIZE
        self.assertEqual(1, contact_data[base])
        self.assertEqual(310123,
                         iradio_dmuv4r._bcd_to_int(
                             iradio_dmuv4r._u32le(contact_data, base + 1)))
        self.assertEqual("OPS",
                         iradio_dmuv4r._decode_string(
                             bytes(contact_data[base + 5:base + 21])))

        group_data = radio._get_segment("group")
        self.assertEqual("RXGRP",
                         iradio_dmuv4r._decode_string(bytes(group_data[:16])))
        self.assertEqual(1, iradio_dmuv4r._u16le(group_data, 16))
        self.assertEqual(2, iradio_dmuv4r._u16le(group_data, 18))

        encrypt_data = radio._get_segment("encrypt")
        self.assertEqual(1, encrypt_data[0])
        self.assertEqual(1, encrypt_data[1])
        self.assertEqual("KEY1", iradio_dmuv4r._decode_string(
            bytes(encrypt_data[2:16])))
        self.assertEqual(bytes.fromhex("00112233445566778899AABBCCDDEEFF"),
                         bytes(encrypt_data[16:32]))

    def test_ctdcs_select_label_matches_newer_oem(self):
        self.assertEqual(
            ["RX+TX", "Only RX", "Only TX"],
            iradio_dmuv4r.CHANNEL_RXTX_CHOICES)
        self.assertEqual(
            ["Allow TX", "Channel Free", "Color Code Idle"],
            iradio_dmuv4r.CHANNEL_CALL_PRIORITY_CHOICES)
        self.assertEqual(
            ["Allow TX", "Channel Free", "CTC/DCS Idle"],
            iradio_dmuv4r.CHANNEL_TX_PRIORITY_CHOICES)
        self.assertEqual(
            ["Standard", "Encrypt 1", "Encrypt 2", "Encrypt 3", "Mute Code"],
            iradio_dmuv4r.CHANNEL_CTDCS_SELECT_CHOICES)

    def test_local_contacts_csv_replace_can_program_high_slots(self):
        radio = make_radio()
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "contacts.csv")
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write("No.,Call Type,Contact Alias,Call ID\n")
                csv_file.write("1,All Call,All Call,16777215\n")
                csv_file.write("2,Individual Call,LOW,12345\n")
                csv_file.write("10000,Group Call,HIGH,12345678\n")

            settings = radio.get_settings()
            contacts = settings["dmr_contacts"]
            contacts["local_contacts_csv_import_mode"].value = "Replace"
            contacts["local_contacts_csv_import_path"].value = csv_path
            radio.set_settings(settings)

        contact = radio._get_segment("contact")
        self.assertEqual(2, contact[0])
        self.assertEqual(b"\xAA\xAA\xAA\xAA", bytes(contact[1:5]))
        self.assertEqual("All Call",
                         iradio_dmuv4r._decode_string(bytes(contact[5:21])))

        base = iradio_dmuv4r.CONTACT_RECORD_SIZE
        self.assertEqual(0, contact[base])
        self.assertEqual(12345,
                         iradio_dmuv4r._bcd_to_int(
                             iradio_dmuv4r._u32le(contact, base + 1)))
        self.assertEqual("LOW",
                         iradio_dmuv4r._decode_string(
                             bytes(contact[base + 5:base + 21])))

        base = (iradio_dmuv4r.CONTACT_COUNT - 1) * (
            iradio_dmuv4r.CONTACT_RECORD_SIZE)
        self.assertEqual(1, contact[base])
        self.assertEqual(12345678,
                         iradio_dmuv4r._bcd_to_int(
                             iradio_dmuv4r._u32le(contact, base + 1)))
        self.assertEqual("HIGH",
                         iradio_dmuv4r._decode_string(
                             bytes(contact[base + 5:base + 21])))

        shown_slots = [group.get_name() for group in
                       radio.get_settings()["dmr_contacts"]
                       if group.get_name().startswith("contact_")]
        self.assertIn("contact_09999", shown_slots)

    def test_local_contacts_csv_append_uses_first_blank_slot(self):
        radio = make_radio()
        settings = radio.get_settings()
        contact = settings["dmr_contacts"]["contact_00001"]
        contact["contact_00001_type"].value = "Group"
        contact["contact_00001_id"].value = 111
        contact["contact_00001_name"].value = "EXISTING"
        radio.set_settings(settings)

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "contacts.csv")
            with open(csv_path, "w", encoding="utf-8") as csv_file:
                csv_file.write("No.,Call Type,Contact Alias,Call ID\n")
                csv_file.write("1,All Call,All Call,16777215\n")
                csv_file.write("2,Group Call,APPEND1,222\n")
                csv_file.write("3,Private,APPEND2,333\n")

            settings = radio.get_settings()
            contacts = settings["dmr_contacts"]
            contacts["local_contacts_csv_import_mode"].value = "Append"
            contacts["local_contacts_csv_import_path"].value = csv_path
            radio.set_settings(settings)

        contact_data = radio._get_segment("contact")
        base = iradio_dmuv4r.CONTACT_RECORD_SIZE
        self.assertEqual("EXISTING",
                         iradio_dmuv4r._decode_string(
                             bytes(contact_data[base + 5:base + 21])))
        base = 2 * iradio_dmuv4r.CONTACT_RECORD_SIZE
        self.assertEqual(1, contact_data[base])
        self.assertEqual("APPEND1",
                         iradio_dmuv4r._decode_string(
                             bytes(contact_data[base + 5:base + 21])))
        base = 3 * iradio_dmuv4r.CONTACT_RECORD_SIZE
        self.assertEqual(0, contact_data[base])
        self.assertEqual("APPEND2",
                         iradio_dmuv4r._decode_string(
                             bytes(contact_data[base + 5:base + 21])))

    def test_local_contacts_csv_refuses_directory(self):
        radio = make_radio()
        settings = radio.get_settings()
        contacts = settings["dmr_contacts"]
        contacts["local_contacts_csv_import_mode"].value = "Replace"
        contacts["local_contacts_csv_import_path"].value = (
            tempfile.gettempdir())

        with self.assertRaisesRegex(
                iradio_dmuv4r.errors.RadioError,
                "DMR contacts CSV is not a file"):
            radio.set_settings(settings)

    def test_encryption_keys_are_limited_by_type(self):
        radio = make_radio()
        settings = radio.get_settings()
        encrypt = settings["dmr_encryption"]["encrypt_000"]
        encrypt["encrypt_000_enabled"].value = True
        encrypt["encrypt_000_type"].value = "ARC"
        encrypt["encrypt_000_name"].value = "ARC"
        encrypt["encrypt_000_key_hex"].value = (
            "00112233445566778899AABBCCDDEEFF00112233445566778899")

        radio.set_settings(settings)

        encrypt_data = radio._get_segment("encrypt")
        self.assertEqual(bytes.fromhex("0011223344"),
                         bytes(encrypt_data[16:21]))
        self.assertEqual(b"\xFF" * 27, bytes(encrypt_data[21:48]))

        upload = radio._build_encrypt_upload()
        self.assertEqual(bytes(encrypt_data[:48]), bytes(upload[:48]))

    def test_cfg2_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()
        cfg2 = settings["cfg2"]
        screen = settings["screen_display"]
        scan = settings["scan_receive"]
        fm_settings = settings["fm"]
        ptt_mic = settings["ptt_mic"]
        keys = settings["programmable_keys"]

        cfg2["cfg2_key_lock"].value = "Lock"
        cfg2["cfg2_main_range"].value = "B"
        cfg2["cfg2_dual_watch"].value = "On"
        screen["cfg2_dual_display"].value = "Single"
        scan["cfg2_scan_direction"].value = "Down"
        cfg2["cfg2_step"].value = "12.5K"
        cfg2["cfg2_special_freq"].value = 440.125
        cfg2["cfg2_special_step"].value = 0.0125
        cfg2["cfg2_special_rssi"].value = 80
        fm_settings["cfg2_fm_channel"].value = 5
        cfg2["cfg2_fm_standby"].value = "On"
        cfg2["cfg2_work_mode_a"].value = "Zone Mode"
        cfg2["cfg2_work_mode_b"].value = "CH Mode"
        screen["cfg2_display_mode_a"].value = "Freq"
        screen["cfg2_display_mode_b"].value = "Alias"
        cfg2["cfg2_zone_a"].value = 3
        cfg2["cfg2_zone_b"].value = 4
        cfg2["cfg2_channel_a"].value = 76
        cfg2["cfg2_channel_b"].value = 77
        ptt_mic["cfg2_second_ptt"].value = "On"
        keys["cfg2_fs1_short"].value = "Scanning"
        keys["cfg2_key_0"].value = "FM Radio"

        radio.set_settings(settings)

        vfo = radio._get_segment("vfo")
        base = iradio_dmuv4r.CFG2_OFFSET
        self.assertEqual(1, vfo[base])
        self.assertEqual(1, vfo[base + 1])
        self.assertEqual(1, vfo[base + 2])
        self.assertEqual(1, vfo[base + 3])
        self.assertEqual(1, vfo[base + 4])
        self.assertEqual(13, vfo[base + 5])
        self.assertEqual(44012500, iradio_dmuv4r._u32le(vfo, base + 8))
        self.assertEqual(1250, iradio_dmuv4r._u32le(vfo, base + 12))
        self.assertEqual(80, vfo[base + 16])
        self.assertEqual(4, vfo[base + 18])
        self.assertEqual(1, vfo[base + 19])
        self.assertEqual(2, vfo[base + 20])
        self.assertEqual(1, vfo[base + 21])
        self.assertEqual(1, vfo[base + 22])
        self.assertEqual(2, vfo[base + 23])
        self.assertEqual(2, vfo[base + 24])
        self.assertEqual(3, vfo[base + 25])
        self.assertEqual(75, iradio_dmuv4r._u16le(vfo, base + 26))
        self.assertEqual(76, iradio_dmuv4r._u16le(vfo, base + 28))
        self.assertEqual(1, vfo[base + 30])
        self.assertEqual(5, vfo[base + 31])
        self.assertEqual(8, vfo[base + 37])

    def test_oem_global_cfg_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()

        settings["radio_identity"]["startup_text"].value = "HELLO RADIO"
        settings["radio_identity"]["radio_name"].value = "DMUV4R"
        settings["power_management"]["save_start"].value = 12
        settings["power_management"]["auto_power_off"].value = True
        settings["power_management"]["clock_seconds"].value = 3661
        settings["frequency_range_limits"]["lock_type_1"].value = "RX Only"
        settings["frequency_range_limits"]["lock_range_1_start"].value = 136
        settings["frequency_range_limits"]["lock_range_1_end"].value = 174
        settings["screen_display"]["lcd_contrast"].value = 7
        settings["general"]["single_tone_hz"].value = 1750
        settings["scan_receive"]["squelch_level"].value = 4
        settings["general"]["analog_vox"].value = "On"
        settings["general"]["analog_vox_threshold"].value = 25
        settings["general"]["analog_vox_delay"].value = 3
        settings["general"]["short_tail"].value = "On"
        settings["scan_receive"]["scan_start_mhz"].value = 400.125
        settings["scan_receive"]["scan_end_mhz"].value = 439.975
        settings["screen_display"]["carrier_led"].value = "On"
        settings["radio_identity"]["dmr_radio_id"].value = 12345678
        settings["digital"]["dmr_remote"].value = "On"
        settings["screen_display"]["dmr_group_display"].value = (
            "Show Called Info")
        settings["digital"]["dmr_send_dtmf"].value = "On"
        settings["digital"]["sms_format"].value = "Motorola"
        settings["dtmf"]["dtmf_send_delay"].value = "500ms"
        settings["dtmf"]["dtmf_send_duration"].value = "70ms"
        settings["dtmf"]["dtmf_send_interval"].value = "80ms"
        settings["dtmf"]["dtmf_send_mode"].value = "TX End"
        settings["dtmf"]["dtmf_send_select"].value = "DTMF-03"
        settings["screen_display"]["dtmf_decode_display"].value = "On"
        settings["dtmf"]["dtmf_gain"].value = 33
        settings["dtmf"]["dtmf_decode_threshold"].value = 17
        settings["dtmf"]["dtmf_remote"].value = "On"
        settings["dtmf"]["dtmf_code_00"].value = "123A#"

        radio.set_settings(settings)

        cfg = radio._get_segment("cfg")
        self.assertEqual("HELLO RADIO",
                         iradio_dmuv4r._decode_string(bytes(cfg[44:76])))
        self.assertEqual("DMUV4R",
                         iradio_dmuv4r._decode_string(bytes(cfg[76:92])))
        self.assertEqual(12, cfg[100])
        self.assertEqual(3661, iradio_dmuv4r._u32le(cfg, 106))
        self.assertEqual(1, cfg[142])
        self.assertEqual(136, iradio_dmuv4r._u16le(cfg, 143))
        self.assertEqual(174, iradio_dmuv4r._u16le(cfg, 145))
        self.assertEqual(7, cfg[233])
        self.assertEqual(1750, iradio_dmuv4r._u16le(cfg, 256))
        self.assertEqual(4, cfg[258])
        self.assertEqual(1, cfg[269])
        self.assertEqual(25, cfg[270])
        self.assertEqual(3, cfg[271])
        self.assertEqual(1, cfg[278])
        self.assertEqual(40012500, iradio_dmuv4r._u32le(cfg, 844))
        self.assertEqual(43997500, iradio_dmuv4r._u32le(cfg, 848))
        self.assertEqual(1, cfg[852])
        self.assertEqual(12345678,
                         iradio_dmuv4r._bcd_to_int(
                             iradio_dmuv4r._u32le(cfg, 384)))
        self.assertEqual(1, cfg[388])
        self.assertEqual(1, cfg[404])
        self.assertEqual(1, cfg[405])
        self.assertEqual(1, cfg[406])
        self.assertEqual(5, cfg[512])
        self.assertEqual(4, cfg[513])
        self.assertEqual(5, cfg[514])
        self.assertEqual(2, cfg[515])
        self.assertEqual(2, cfg[516])
        self.assertEqual(1, cfg[517])
        self.assertEqual(33, cfg[518])
        self.assertEqual(17, cfg[519])
        self.assertEqual(1, cfg[520])
        self.assertEqual(b"123A#", bytes(cfg[522:527]))
        self.assertEqual(5, cfg[537])

    def test_fm_full_record_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()
        fm_settings = settings["fm"]

        fm_settings["fm_range_00"].value = "2-30 MHz"
        fm_settings["fm_freq_00"].value = "99.5"
        fm_settings["fm_alias_00"].value = "BCAST"
        fm_settings["fm_sw_demod_00"].value = "USB"
        fm_settings["fm_sw_freq_00"].value = "7.150"
        fm_settings["fm_sw_step_00"].value = "5K"
        fm_settings["fm_sw_bw_00"].value = "2.2 K"
        fm_settings["fm_sw_agc_00"].value = "-10"
        fm_settings["fm_sw_bfo_00"].value = -123
        fm_settings["fm_mw_demod_00"].value = "LSB"
        fm_settings["fm_mw_freq_00"].value = "1000"
        fm_settings["fm_mw_step_00"].value = "9K"
        fm_settings["fm_mw_bw_00"].value = "1.2 K"
        fm_settings["fm_mw_agc_00"].value = "-5"
        fm_settings["fm_mw_bfo_00"].value = 321
        fm_settings["fm_lw_demod_00"].value = "CW"
        fm_settings["fm_lw_freq_00"].value = "279"
        fm_settings["fm_lw_step_00"].value = "10K"
        fm_settings["fm_lw_bw_00"].value = "4.0 K"
        fm_settings["fm_lw_agc_00"].value = "0"
        fm_settings["fm_lw_bfo_00"].value = -1
        fm_settings["fm_freq_01"].value = "88.1"
        fm_settings["fm_alias_01"].value = "REC2"
        fm_settings["fm_sw_agc_01"].value = "-20"
        fm_settings["fm_sw_bfo_01"].value = -222

        radio.set_settings(settings)

        fm = radio._get_segment("fm")
        self.assertEqual(1, fm[0])
        self.assertEqual(995, iradio_dmuv4r._u16le(fm, 1))
        self.assertEqual(2, fm[3])
        self.assertEqual(1, fm[4])
        self.assertEqual(3, fm[5])
        self.assertEqual(11, fm[6])
        self.assertEqual(32645, iradio_dmuv4r._u16le(fm, 7))
        self.assertEqual(7150, iradio_dmuv4r._u16le(fm, 9))
        self.assertEqual(1, fm[12])
        self.assertEqual(2, fm[13])
        self.assertEqual(2, fm[14])
        self.assertEqual(6, fm[15])
        self.assertEqual(33089, iradio_dmuv4r._u16le(fm, 16))
        self.assertEqual(1000, iradio_dmuv4r._u16le(fm, 18))
        self.assertEqual(3, fm[21])
        self.assertEqual(3, fm[22])
        self.assertEqual(5, fm[23])
        self.assertEqual(1, fm[24])
        self.assertEqual(32767, iradio_dmuv4r._u16le(fm, 25))
        self.assertEqual(279, iradio_dmuv4r._u16le(fm, 27))
        self.assertEqual(
            "BCAST", iradio_dmuv4r._decode_string(bytes(fm[30:46])))
        base = iradio_dmuv4r.FM_RECORD_SIZE
        self.assertEqual(881, iradio_dmuv4r._u16le(fm, base + 1))
        self.assertEqual(21, fm[base + 6])
        self.assertEqual(32546, iradio_dmuv4r._u16le(fm, base + 7))
        self.assertEqual("REC2", iradio_dmuv4r._decode_string(
            bytes(fm[base + 30:base + 46])))
        self.assertEqual(b"\xFF\xFF", bytes(fm[39:41]))

    def test_poweron_image_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()
        poweron = settings["poweron_image"]

        poweron["startup_image_upload"].value = True
        poweron["startup_image_payload_hex"].value = "AA" * 1024

        radio.set_settings(settings)

        data = radio._get_segment("startup_image")
        self.assertEqual(0x01, data[0])
        self.assertEqual(b"\xAA" * 1024, bytes(data[1:1025]))
        self.assertEqual(b"\x00" * 3072, bytes(data[1025:]))

        reread = radio.get_settings()["poweron_image"]
        self.assertTrue(bool(reread["startup_image_upload"].value))
        self.assertEqual("AA" * 1024,
                         str(reread["startup_image_payload_hex"].value))

    def test_global_contacts_settings_roundtrip(self):
        radio = make_radio()
        settings = radio.get_settings()
        global_contacts = settings["global_contacts"]

        global_contacts["global_contacts_upload"].value = True
        global_contacts["global_contacts_csv_path"].value = "/tmp/dmrids.csv"

        radio.set_settings(settings)

        data = radio._get_segment("global_contacts")
        self.assertEqual(0x01, data[0])
        self.assertEqual("/tmp/dmrids.csv",
                         str(radio.get_settings()["global_contacts"]
                             ["global_contacts_csv_path"].value))

    def test_global_contacts_payload_from_csv(self):
        radio = make_radio()
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", delete=False) as csv_file:
                path = csv_file.name
                csv_file.write("id,callsign,name,city,state,country,extra\n")
                csv_file.write("123,OK1ABC,Jose,Prague,CZ,Czechia,ignored\n")
                csv_file.write("456,OK2XYZ,Alice,Brno,CZ,Czechia,ignored\n")

            blocks = radio._global_contacts_payload_from_csv(path)
        finally:
            if path:
                os.unlink(path)

        payload = b"123,OK1ABC,Jose,Prague,CZ,Czechia\n"
        payload += b"456,OK2XYZ,Alice,Brno,CZ,Czechia\n"
        expected_len = len(payload) + 4
        self.assertEqual(bytes([
            (expected_len >> 24) & 0xFF,
            (expected_len >> 16) & 0xFF,
            (expected_len >> 8) & 0xFF,
            expected_len & 0xFF,
        ]), blocks[0][:4])
        self.assertEqual(payload, blocks[0][4:4 + len(payload)])
        self.assertEqual(b"\xFF" * (iradio_dmuv4r.BLOCK_SIZE -
                         4 - len(payload)), blocks[0][4 + len(payload):])

    def test_global_contacts_payload_requires_oem_sixth_comma(self):
        radio = make_radio()
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", delete=False) as csv_file:
                path = csv_file.name
                csv_file.write("id,callsign,name,city,state,country\n")
                csv_file.write("123,OK1ABC,Jose,Prague,CZ,Czechia\n")

            blocks = radio._global_contacts_payload_from_csv(path)
        finally:
            if path:
                os.unlink(path)

        self.assertEqual(b"\x00\x00\x00\x04", blocks[0][:4])
        self.assertEqual(b"\xFF" * (iradio_dmuv4r.BLOCK_SIZE - 4),
                         blocks[0][4:])

    def test_global_contacts_payload_refuses_directory(self):
        radio = make_radio()
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(iradio_dmuv4r.errors.RadioError,
                                        "CSV is not a file"):
                radio._global_contacts_payload_from_csv(tmpdir)

    def test_enabled_global_contacts_requires_csv_path(self):
        radio = make_radio()
        global_contacts = radio._get_segment("global_contacts")
        global_contacts[0] = 0x01
        global_contacts[1:] = b"\xFF" * (len(global_contacts) - 1)
        radio._set_segment("global_contacts", global_contacts)

        with self.assertRaisesRegex(iradio_dmuv4r.errors.RadioError,
                                    "no CSV path"):
            radio._build_global_contacts_upload()

    def test_sync_out_preflights_global_contacts_before_entering(self):
        radio = make_radio()
        global_contacts = radio._get_segment("global_contacts")
        global_contacts[0] = 0x01
        global_contacts[1:] = b"\xFF" * (len(global_contacts) - 1)
        radio._set_segment("global_contacts", global_contacts)
        radio._enter = mock.Mock()
        radio._exit = mock.Mock()

        with self.assertRaisesRegex(iradio_dmuv4r.errors.RadioError,
                                    "no CSV path"):
            radio.sync_out()

        radio._enter.assert_not_called()
        radio._exit.assert_not_called()

    def test_sync_out_preflights_global_contacts_directory_before_entering(
            self):
        radio = make_radio()
        with tempfile.TemporaryDirectory() as tmpdir:
            global_contacts = radio._get_segment("global_contacts")
            global_contacts[0] = 0x01
            global_contacts[1:1 + len(tmpdir)] = tmpdir.encode("ascii")
            radio._set_segment("global_contacts", global_contacts)
            radio._enter = mock.Mock()
            radio._exit = mock.Mock()

            with self.assertRaisesRegex(iradio_dmuv4r.errors.RadioError,
                                        "CSV is not a file"):
                radio.sync_out()

        radio._enter.assert_not_called()
        radio._exit.assert_not_called()

    def test_obsolete_active_channel_cfg_settings_are_hidden(self):
        names = {item.get_name()
                 for item in make_radio().get_settings().walk()}
        self.assertNotIn("zone_a", names)
        self.assertNotIn("channel_a", names)
        self.assertNotIn("zone_b", names)
        self.assertNotIn("channel_b", names)
        self.assertNotIn("key_lock", names)
        self.assertNotIn("dual_watch", names)
        self.assertNotIn("step_index", names)
        self.assertNotIn("key_0", names)
        self.assertNotIn("tone_protect", names)
        self.assertNotIn("bluetooth_enabled", names)
        self.assertNotIn("gps_record_count", names)
        self.assertFalse(any(name.startswith("alarm_clock_")
                         for name in names))

    def test_newer_oem_cfg_settings_are_exposed(self):
        settings = make_radio().get_settings()
        names = {item.get_name() for item in settings.walk()}
        expected = {
            "program_password_hex",
            "startup_password",
            "startup_text",
            "radio_name",
            "startup_line",
            "startup_column",
        }
        expected.update(iradio_dmuv4r.LIST_BOOL_FIELDS.values())
        expected.update(name for name, _choices
                        in iradio_dmuv4r.CONFIG_LIST_FIELDS.values())
        expected.update(iradio_dmuv4r.CONFIG_INT_FIELDS)
        expected.update(iradio_dmuv4r.CONFIG_FLOAT_FIELDS)
        expected.update("dtmf_code_%02d" % index for index in range(20))

        self.assertEqual(set(), expected - names)
        self.assertEqual(
            iradio_dmuv4r.LIST_ON_OFF,
            settings["general"]["voice_prompt"].value.get_options())
        self.assertEqual("DMR / SMS", settings["digital"].get_shortname())

    def test_firmware_menu_settings_and_bounds_are_used(self):
        settings = make_radio().get_settings()

        self.assertIn("analog_vox", settings["general"].keys())
        self.assertIn("analog_vox_threshold", settings["general"].keys())
        self.assertIn("analog_vox_delay", settings["general"].keys())
        self.assertIn("short_tail", settings["general"].keys())
        self.assertIn("dmr_send_dtmf", settings["digital"].keys())

        clock = settings["power_management"]["clock_seconds"].value
        self.assertEqual(iradio_dmuv4r.APO_SECONDS_MIN, clock.get_min())
        self.assertEqual(iradio_dmuv4r.APO_SECONDS_MAX, clock.get_max())
        self.assertEqual(iradio_dmuv4r.APO_SECONDS_MIN, int(clock))

        contrast = settings["screen_display"]["lcd_contrast"].value
        self.assertEqual(0, contrast.get_min())
        self.assertEqual(10, contrast.get_max())
        self.assertEqual(5, int(contrast))

        self.assertEqual(
            16, settings["digital"]["dmr_squelch_level"].value.get_max())
        self.assertEqual(
            60, settings["screen_display"]["dmr_called_keep"].value.get_max())
        self.assertEqual(
            245, settings["general"]["analog_vox_threshold"].value.get_max())
        self.assertEqual(
            5, settings["general"]["analog_vox_delay"].value.get_max())

    def test_firmware_menu_choice_labels_are_used(self):
        self.assertIn("560-620MHz", iradio_dmuv4r.DETECT_RANGE_CHOICES)
        self.assertNotIn("560-640MHz", iradio_dmuv4r.DETECT_RANGE_CHOICES)
        self.assertEqual(
            ["Show Caller Info", "Show Called Info"],
            iradio_dmuv4r.GROUP_DISPLAY_CHOICES)
        self.assertIn("Promiscuous Mode", iradio_dmuv4r.CFG2_KEY_FUNCTIONS)
        self.assertNotIn("Promiscuos Mode", iradio_dmuv4r.CFG2_KEY_FUNCTIONS)

    def test_radio_identity_settings_are_first(self):
        settings = make_radio().get_settings()

        self.assertEqual("radio_identity", settings[0].get_name())
        self.assertEqual("Radio Identity", settings[0].get_shortname())
        self.assertEqual([
            "radio_name",
            "dmr_radio_id",
            "startup_text",
        ], settings["radio_identity"].keys())

    def test_password_settings_are_last(self):
        settings = make_radio().get_settings()

        self.assertEqual("passwords", settings[-1].get_name())
        self.assertEqual("Passwords", settings[-1].get_shortname())
        self.assertEqual([
            "program_password_hex",
            "startup_password_enabled",
            "startup_password",
        ], settings["passwords"].keys())

    def test_power_management_settings_are_grouped(self):
        settings = make_radio().get_settings()

        self.assertEqual("Power Management",
                         settings["power_management"].get_shortname())
        self.assertEqual([
            "auto_power_off",
            "clock_seconds",
            "save_mode",
            "save_start",
        ], settings["power_management"].keys())
        for name in settings["power_management"].keys():
            self.assertNotIn(name, settings["general"].keys())

    def test_screen_display_settings_are_grouped(self):
        settings = make_radio().get_settings()

        self.assertEqual("Screen & Display",
                         settings["screen_display"].get_shortname())
        self.assertEqual([
            "led_enabled",
            "lcd_brightness",
            "led_timer",
            "lcd_contrast",
            "carrier_led",
            "cfg2_dual_display",
            "cfg2_display_mode_a",
            "cfg2_display_mode_b",
            "dmr_group_display",
            "dmr_called_keep",
            "dtmf_decode_display",
        ], settings["screen_display"].keys())
        for name in (
                "led_enabled",
                "lcd_brightness",
                "led_timer",
                "lcd_contrast",
                "carrier_led"):
            self.assertNotIn(name, settings["general"].keys())
        for name in (
                "cfg2_dual_display",
                "cfg2_display_mode_a",
                "cfg2_display_mode_b"):
            self.assertNotIn(name, settings["cfg2"].keys())
        for name in ("dmr_group_display", "dmr_called_keep"):
            self.assertNotIn(name, settings["digital"].keys())
        self.assertNotIn("dtmf_decode_display", settings["dtmf"].keys())

    def test_scan_receive_settings_are_grouped(self):
        settings = make_radio().get_settings()

        self.assertEqual("Scan & Receive",
                         settings["scan_receive"].get_shortname())
        self.assertEqual([
            "scan_mode",
            "scan_return",
            "scan_dwell",
            "scan_interval",
            "refresh_delay",
            "detect_range",
            "glitch_filter",
            "scan_start_mhz",
            "scan_end_mhz",
            "noaa_1050_alarm",
            "squelch_level",
            "cfg2_scan_direction",
        ], settings["scan_receive"].keys())
        for name in (
                "scan_mode",
                "scan_return",
                "scan_dwell",
                "scan_interval",
                "refresh_delay",
                "detect_range",
                "glitch_filter",
                "scan_start_mhz",
                "scan_end_mhz",
                "noaa_1050_alarm",
                "squelch_level"):
            self.assertNotIn(name, settings["general"].keys())
        self.assertNotIn("cfg2_scan_direction", settings["cfg2"].keys())

    def test_newer_oem_cfg2_settings_are_exposed(self):
        names = {item.get_name()
                 for item in make_radio().get_settings().walk()}
        expected = {
            "cfg2_special_freq",
            "cfg2_special_step",
            "cfg2_special_rssi",
            "cfg2_fm_channel",
            "cfg2_zone_a",
            "cfg2_zone_b",
            "cfg2_channel_a",
            "cfg2_channel_b",
        }
        expected.update(name for name, _label, _choices
                        in iradio_dmuv4r.CFG2_LIST_FIELDS.values())
        expected.update(name for name, _label
                        in iradio_dmuv4r.CFG2_KEY_FIELDS.values())

        self.assertEqual(set(), expected - names)

    def test_programmable_key_settings_are_grouped(self):
        settings = make_radio().get_settings()

        self.assertEqual("Programmable Keys",
                         settings["programmable_keys"].get_shortname())
        expected = [
            name for _offset, (name, _label)
            in sorted(iradio_dmuv4r.CFG2_KEY_FIELDS.items())
        ]
        self.assertEqual(expected, settings["programmable_keys"].keys())
        for name in expected:
            self.assertNotIn(name, settings["cfg2"].keys())

    def test_fm_radio_channel_setting_is_in_fm_broadcast(self):
        settings = make_radio().get_settings()

        self.assertNotIn("cfg2_fm_channel", settings["cfg2"].keys())
        self.assertEqual(
            "FM Radio Channel",
            settings["fm"]["cfg2_fm_channel"].get_shortname())

    def test_ptt_mic_settings_are_grouped(self):
        settings = make_radio().get_settings()

        self.assertEqual("PTT & Mic Setting",
                         settings["ptt_mic"].get_shortname())
        self.assertEqual([
            "main_ptt",
            "cfg2_second_ptt",
            "tx_priority",
            "tx_mic_gain",
            "dmr_call_mic_gain",
            "dmr_tx_denoise",
            "tx_start_beep",
            "roger_beep",
            "call_start_beep",
            "call_end_beep",
        ], settings["ptt_mic"].keys())
        for name in (
                "main_ptt",
                "tx_priority",
                "tx_mic_gain",
                "tx_start_beep",
                "roger_beep",
                "call_start_beep",
                "call_end_beep"):
            self.assertNotIn(name, settings["general"].keys())
        for name in ("dmr_call_mic_gain", "dmr_tx_denoise"):
            self.assertNotIn(name, settings["digital"].keys())
        self.assertNotIn("cfg2_second_ptt", settings["cfg2"].keys())

    def test_dtmf_settings_are_grouped(self):
        settings = make_radio().get_settings()

        self.assertEqual("DTMF", settings["dtmf"].get_shortname())
        self.assertEqual([
            "dtmf_send_delay",
            "dtmf_send_duration",
            "dtmf_send_interval",
            "dtmf_send_mode",
            "dtmf_send_select",
            "dtmf_gain",
            "dtmf_decode_threshold",
            "dtmf_remote",
        ] + ["dtmf_code_%02d" % index for index in range(20)],
            settings["dtmf"].keys())
        for name in settings["dtmf"].keys():
            self.assertNotIn(name, settings["digital"].keys())

    def test_newer_oem_nearby_ui_labels_are_used(self):
        settings = make_radio().get_settings()

        expected_labels = [
            (settings["radio_identity"]["radio_name"],
             "Radio Name (max 16 chars)"),
            (settings["radio_identity"]["dmr_radio_id"], "Personal ID"),
            (settings["radio_identity"]["startup_text"],
             "Welcome Message (max 32 chars)"),
            (settings["passwords"]["program_password_hex"],
             "Program Password (hex, 6 chars max)"),
            (settings["passwords"]["startup_password_enabled"],
             "Startup Password Enabled"),
            (settings["passwords"]["startup_password"],
             "Startup Password (max 16 chars)"),
            (settings["startup"]["startup_picture"], "Startup Logo"),
            (settings["startup"]["startup_label"], "Startup Text"),
            (settings["power_management"]["auto_power_off"],
             "APO Enabled"),
            (settings["power_management"]["clock_seconds"],
             "APO Time (seconds)"),
            (settings["power_management"]["save_mode"],
             "Power Save Mode"),
            (settings["power_management"]["save_start"],
             "Power Save Start Time (s)"),
            (settings["screen_display"]["led_enabled"], "Backlight"),
            (settings["screen_display"]["led_timer"], "Timed Screen Off"),
            (settings["general"]["display_id_digits"],
             "Frequency Input Digits"),
            (settings["scan_receive"]["refresh_delay"], "RSSI Refresh Time"),
            (settings["scan_receive"]["glitch_filter"],
             "Adjacent-Channel Threshold"),
            (settings["scan_receive"]["noaa_1050_alarm"],
             "NOAA 1050 Alarm"),
            (settings["frequency_range_limits"]["lock_type_1"],
             "Lock Range 1 Status"),
            (settings["screen_display"]["dmr_group_display"],
             "Called Info Display"),
            (settings["screen_display"]["dmr_called_keep"],
             "Called Screen Keep Time (s)"),
            (settings["dtmf"]["dtmf_send_delay"], "DTMF Send Delay"),
            (settings["dtmf"]["dtmf_send_duration"], "DTMF Send Duration"),
            (settings["dtmf"]["dtmf_send_interval"], "DTMF Send Interval"),
            (settings["dtmf"]["dtmf_send_mode"], "DTMF Send Mode"),
            (settings["dtmf"]["dtmf_send_select"],
             "DTMF Send Selection"),
            (settings["screen_display"]["dtmf_decode_display"],
             "DTMF Decode Display"),
            (settings["dtmf"]["dtmf_remote"], "DTMF Remote Control"),
            (settings["dtmf"]["dtmf_gain"], "DTMF Send Gain"),
            (settings["ptt_mic"]["main_ptt"], "Main PTT TX Band"),
            (settings["ptt_mic"]["cfg2_second_ptt"], "Sub PTT Active"),
            (settings["ptt_mic"]["tx_priority"], "Priority TX"),
            (settings["ptt_mic"]["tx_mic_gain"], "Analog MIC Gain"),
            (settings["ptt_mic"]["dmr_call_mic_gain"], "DMR MIC Gain"),
            (settings["ptt_mic"]["dmr_tx_denoise"], "DMR TX Denoise"),
            (settings["ptt_mic"]["tx_start_beep"], "Tx Start Beep"),
            (settings["ptt_mic"]["roger_beep"], "End TX Beep"),
            (settings["ptt_mic"]["call_start_beep"], "Call Start Beep"),
            (settings["ptt_mic"]["call_end_beep"], "Call End Beep"),
            (settings["cfg2"]["cfg2_special_freq"],
             "Spectrum Center Frequency MHz"),
            (settings["cfg2"]["cfg2_special_step"], "Spectrum Step MHz"),
            (settings["cfg2"]["cfg2_special_rssi"],
             "Spectrum RSSI Threshold"),
            (settings["scan_receive"]["cfg2_scan_direction"],
             "Scan Direction"),
            (settings["programmable_keys"]["cfg2_fs1_short"],
             "FS1 Short Key"),
            (settings["programmable_keys"]["cfg2_key_0"], "Key 0"),
            (settings["fm"]["cfg2_fm_channel"], "FM Radio Channel"),
        ]
        for setting, label in expected_labels:
            self.assertEqual(label, setting.get_shortname())

        self.assertEqual(
            7, settings["startup"]["startup_line"].value.get_max())
        self.assertEqual(
            127, settings["startup"]["startup_column"].value.get_max())
        self.assertEqual(
            18, settings["frequency_range_limits"][
                "lock_range_1_start"].value.get_min())
        self.assertEqual(
            1, settings["radio_identity"]["dmr_radio_id"].value.get_min())
        self.assertEqual(
            16776415,
            settings["radio_identity"]["dmr_radio_id"].value.get_max())
        self.assertEqual(
            32,
            settings["radio_identity"]["startup_text"].value.maxlength)
        self.assertEqual(
            16,
            settings["passwords"]["startup_password"].value.maxlength)

    def test_frequency_range_limit_settings_are_grouped_by_range(self):
        settings = make_radio().get_settings()

        self.assertEqual([
            "lock_type_1",
            "lock_range_1_start",
            "lock_range_1_end",
            "lock_type_2",
            "lock_range_2_start",
            "lock_range_2_end",
            "lock_type_3",
            "lock_range_3_start",
            "lock_range_3_end",
            "lock_type_4",
            "lock_range_4_start",
            "lock_range_4_end",
        ], settings["frequency_range_limits"].keys())

    def test_newer_oem_repeated_tables_are_exposed(self):
        names = {item.get_name()
                 for item in make_radio().get_settings().walk()}
        expected = {
            "contact_00000_type",
            "contact_00000_id",
            "contact_00000_name",
            "tg_000_name",
            "tg_000_members",
            "tg_249_name",
            "tg_249_members",
            "encrypt_000_enabled",
            "encrypt_000_type",
            "encrypt_000_name",
            "encrypt_000_key_hex",
            "encrypt_255_enabled",
            "encrypt_255_type",
            "encrypt_255_name",
            "encrypt_255_key_hex",
            "sms_preset_00",
            "sms_preset_15",
            "fm_range_00",
            "fm_freq_00",
            "fm_alias_00",
            "fm_sw_demod_00",
            "fm_sw_freq_00",
            "fm_sw_step_00",
            "fm_sw_bw_00",
            "fm_sw_agc_00",
            "fm_sw_bfo_00",
            "fm_mw_demod_00",
            "fm_mw_freq_00",
            "fm_mw_step_00",
            "fm_mw_bw_00",
            "fm_mw_agc_00",
            "fm_mw_bfo_00",
            "fm_lw_demod_00",
            "fm_lw_freq_00",
            "fm_lw_step_00",
            "fm_lw_bw_00",
            "fm_lw_agc_00",
            "fm_lw_bfo_00",
            "fm_range_79",
            "fm_freq_79",
            "fm_alias_79",
            "startup_image_upload",
            "startup_image_payload_hex",
            "global_contacts_upload",
            "global_contacts_csv_path",
        }

        self.assertEqual(set(), expected - names)
        self.assertNotIn("zone_default_a_249", names)
        self.assertNotIn("zone_default_b_249", names)

    def test_settings_pages_have_unique_property_names(self):
        for group in make_radio().get_settings():
            names = [item.get_name() for item in group.walk()]
            duplicates = [
                name for name, count in Counter(names).items() if count > 1
            ]
            self.assertEqual([], duplicates, group.get_name())

    def test_zone_parser_uses_dmuv4r_520_byte_table(self):
        radio = make_radio()
        zone = radio._get_segment("zone")
        base = iradio_dmuv4r.ZONE_TABLE_OFFSET
        zone[base:base + iradio_dmuv4r.ZONE_RECORD_SIZE] = b"\xFF" * \
            iradio_dmuv4r.ZONE_RECORD_SIZE
        zone[base:base + 4] = b"\x3C\x00\x49\x00"
        zone[base + 4:base + 20] = iradio_dmuv4r._encode_string("IC2026", 16)
        for index, channel in enumerate((59, 60, 61)):
            iradio_dmuv4r._set_u16le(zone, base + 20 + (index * 2), channel)
        next_base = base + iradio_dmuv4r.ZONE_RECORD_SIZE
        zone[next_base:next_base + iradio_dmuv4r.ZONE_RECORD_SIZE] = (
            b"\xFF" * iradio_dmuv4r.ZONE_RECORD_SIZE)
        zone[next_base + 4:next_base +
             20] = iradio_dmuv4r._encode_string("Zone-002", 16)
        radio._set_segment("zone", zone)

        zones = radio._parse_zones()
        self.assertEqual("IC2026", zones[0]["name"])
        self.assertEqual(60, zones[0]["channel_a"])
        self.assertEqual(73, zones[0]["channel_b"])
        self.assertEqual([59, 60, 61], zones[0]["members"])
        self.assertEqual("Zone-002", zones[1]["name"])
        self.assertEqual(base, radio._zone_offset(0))
        self.assertEqual(next_base, radio._zone_offset(1))

    def test_zone_parser_accepts_legacy_prefixed_readback(self):
        radio = make_radio()
        zone = radio._get_segment("zone")
        base = iradio_dmuv4r.LEGACY_ZONE_TABLE_OFFSET
        zone[base:base + iradio_dmuv4r.ZONE_RECORD_SIZE] = (
            b"\xFF" * iradio_dmuv4r.ZONE_RECORD_SIZE)
        zone[base + 4:base + 20] = iradio_dmuv4r._encode_string("LEGACY", 16)
        iradio_dmuv4r._set_u16le(zone, base + 20, 11)
        radio._set_segment("zone", zone)

        zones = radio._parse_zones()
        self.assertEqual("LEGACY", zones[0]["name"])
        self.assertEqual([11], zones[0]["members"])
        self.assertEqual(base, radio._zone_offset(0))

    def test_zone_upload_normalizes_legacy_prefixed_readback(self):
        radio = make_radio()
        zone = radio._get_segment("zone")
        base = iradio_dmuv4r.LEGACY_ZONE_TABLE_OFFSET
        zone[base:base + 32] = bytes(range(32))
        zone[base + 4:base + 20] = iradio_dmuv4r._encode_string("LEGACY", 16)
        iradio_dmuv4r._set_u16le(zone, base + 20, 11)
        radio._set_segment("zone", zone)

        upload = radio._build_zone_upload()
        self.assertEqual(zone[base:base + 32], upload[:32])
        self.assertEqual(b"\xFF" * 32, bytes(upload[base:base + 32]))

    def test_zone_upload_is_in_safe_live_plan(self):
        self.assertTrue(iradio_dmuv4r.ZONE_WRITES_ENABLED)
        self.assertIn("zone",
                      [segment for _op, _base, segment, _blocks
                       in iradio_dmuv4r.SAFE_UPLOAD_PLAN])

    def test_zone_bank_model_renaming_visible_zone_persists(self):
        radio = make_radio()
        mappings = radio.get_bank_model().get_mappings()

        mappings[0].set_name("OPSZONE")

        self.assertEqual("OPSZONE", radio._parse_zones()[0]["name"])
        rebuilt = radio.get_bank_model().get_mappings()
        self.assertEqual("OPSZONE", rebuilt[0].get_name())
        self.assertEqual(0, rebuilt[0].get_index())

    def test_zone_bank_model_edits_zones(self):
        radio = make_radio()
        for number, name in ((60, "CRISIS"), (61, "INNER"), (62, "OPS")):
            mem = chirp_common.Memory()
            mem.number = number
            mem.freq = 157800000 + number
            mem.duplex = ""
            mem.offset = 0
            mem.mode = "FM"
            mem.name = name
            mem.skip = ""
            radio.set_memory(mem)

        zone = radio._get_segment("zone")
        base = iradio_dmuv4r.ZONE_TABLE_OFFSET
        zone[base:base + iradio_dmuv4r.ZONE_RECORD_SIZE] = (
            b"\xFF" * iradio_dmuv4r.ZONE_RECORD_SIZE)
        zone[base + 4:base + 20] = iradio_dmuv4r._encode_string("IC2026", 16)
        iradio_dmuv4r._set_u16le(zone, base + 20, 59)
        iradio_dmuv4r._set_u16le(zone, base + 22, 60)
        radio._set_segment("zone", zone)

        banks = radio.get_bank_model()
        mappings = banks.get_mappings()
        self.assertEqual(radio._zone_record_count(), len(mappings))
        self.assertEqual("IC2026", mappings[0].get_name())
        self.assertEqual("Zone-002", mappings[1].get_name())
        self.assertEqual(
            [60, 61],
            [mem.number for mem in banks.get_mapping_memories(mappings[0])])
        self.assertEqual(
            [mappings[0]], banks.get_memory_mappings(radio.get_memory(60)))
        banks.add_memory_to_mapping(radio.get_memory(62), mappings[0])
        self.assertEqual([59, 60, 61], radio._zone_members(0))
        self.assertEqual(
            [mappings[0]], banks.get_memory_mappings(radio.get_memory(62)))
        banks.remove_memory_from_mapping(radio.get_memory(60), mappings[0])
        self.assertEqual([60, 61], radio._zone_members(0))
        self.assertEqual([], banks.get_memory_mappings(radio.get_memory(60)))
        mappings[0].set_name("OPSZONE")
        self.assertEqual("OPSZONE", radio._parse_zones()[0]["name"])

    def test_zone_bank_model_caches_zone_membership(self):
        radio = make_radio()
        zone = radio._get_segment("zone")
        base = iradio_dmuv4r.ZONE_TABLE_OFFSET
        zone[base:base + iradio_dmuv4r.ZONE_RECORD_SIZE] = (
            b"\xFF" * iradio_dmuv4r.ZONE_RECORD_SIZE)
        iradio_dmuv4r._set_u16le(zone, base + 20, 59)
        radio._set_segment("zone", zone)

        with mock.patch.object(radio, "_parse_zones",
                               wraps=radio._parse_zones) as parse_zones:
            banks = radio.get_bank_model()
            parse_zones.assert_called_once()
            for _index in range(5):
                self.assertEqual(
                    [banks.get_mappings()[0]],
                    banks.get_memory_mappings(radio.get_memory(60)))
            parse_zones.assert_called_once()

    def test_zone_bank_model_initializes_default_channels(self):
        radio = make_radio()
        mem = chirp_common.Memory()
        mem.number = 60
        mem.freq = 157800000
        mem.duplex = ""
        mem.offset = 0
        mem.mode = "FM"
        mem.name = "ZONECH"
        mem.skip = ""
        radio.set_memory(mem)

        banks = radio.get_bank_model()
        mapping = banks.get_mappings()[0]
        banks.add_memory_to_mapping(radio.get_memory(60), mapping)

        raw = radio._zone_record(0)
        self.assertEqual(59, iradio_dmuv4r._u16le(raw, 0))
        self.assertEqual(59, iradio_dmuv4r._u16le(raw, 2))

    def test_zone_default_channel_settings_roundtrip(self):
        radio = make_radio()
        zone = radio._get_segment("zone")
        base = iradio_dmuv4r.ZONE_TABLE_OFFSET
        zone[base:base + iradio_dmuv4r.ZONE_RECORD_SIZE] = (
            b"\xFF" * iradio_dmuv4r.ZONE_RECORD_SIZE)
        iradio_dmuv4r._set_u16le(zone, base, 59)
        iradio_dmuv4r._set_u16le(zone, base + 2, 60)
        zone[base + 4:base + 20] = iradio_dmuv4r._encode_string("IC2026", 16)
        radio._set_segment("zone", zone)

        settings = radio.get_settings()
        zone_defaults = settings["zone_defaults"]
        self.assertEqual(60, int(zone_defaults["zone_default_a_000"].value))
        self.assertEqual(61, int(zone_defaults["zone_default_b_000"].value))

        zone_defaults["zone_default_a_000"].value = 62
        zone_defaults["zone_default_b_000"].value = 63
        radio.set_settings(settings)

        raw = radio._zone_record(0)
        self.assertEqual(61, iradio_dmuv4r._u16le(raw, 0))
        self.assertEqual(62, iradio_dmuv4r._u16le(raw, 2))

    def test_zone_defaults_skip_oem_placeholder_names(self):
        radio = make_radio()
        zone = radio._get_segment("zone")
        base = iradio_dmuv4r.ZONE_TABLE_OFFSET
        zone[base:base + iradio_dmuv4r.ZONE_RECORD_SIZE] = (
            b"\xFF" * iradio_dmuv4r.ZONE_RECORD_SIZE)
        iradio_dmuv4r._set_u16le(zone, base, 59)
        iradio_dmuv4r._set_u16le(zone, base + 2, 60)
        zone[base + 4:base + 20] = iradio_dmuv4r._encode_string("IC2026", 16)

        next_base = base + iradio_dmuv4r.ZONE_RECORD_SIZE
        zone[next_base:next_base + iradio_dmuv4r.ZONE_RECORD_SIZE] = (
            b"\xFF" * iradio_dmuv4r.ZONE_RECORD_SIZE)
        iradio_dmuv4r._set_u16le(zone, next_base, 0)
        iradio_dmuv4r._set_u16le(zone, next_base + 2, 0)
        zone[next_base + 4:next_base + 20] = (
            iradio_dmuv4r._encode_string("Zone-002", 16))
        radio._set_segment("zone", zone)

        names = radio.get_settings()["zone_defaults"].keys()

        self.assertIn("zone_default_a_000", names)
        self.assertNotIn("zone_default_a_001", names)
        self.assertNotIn("zone_default_b_001", names)

    def test_zone_bank_names_are_advertised_editable(self):
        features = make_radio().get_features()
        self.assertTrue(features.has_bank)
        self.assertTrue(features.has_bank_names)

    def test_contact_upload_synthesizes_all_call_when_empty(self):
        radio = make_radio()
        upload = radio._build_contact_upload()
        self.assertEqual(2, upload[0])
        self.assertEqual(b"\xAA\xAA\xAA\xAA", bytes(upload[1:5]))
        self.assertEqual("All Call",
                         iradio_dmuv4r._decode_string(bytes(upload[5:21])))
        empty = 9999 * iradio_dmuv4r.CONTACT_RECORD_SIZE
        self.assertEqual(0xFF, upload[empty])
        self.assertEqual(b"\xFF" * 20, bytes(upload[empty + 1:empty + 21]))

    def test_contact_upload_preserves_valid_contact(self):
        radio = make_radio()
        contact = radio._get_segment("contact")
        base = iradio_dmuv4r.CONTACT_RECORD_SIZE
        contact[base] = 1
        iradio_dmuv4r._set_u32le(contact, base + 1,
                                 iradio_dmuv4r._int_to_bcd(310123))
        contact[base + 5:base + 21] = iradio_dmuv4r._encode_string("OPS", 16)
        radio._set_segment("contact", contact)

        upload = radio._build_contact_upload()
        self.assertEqual(1, upload[base])
        self.assertEqual(
            310123, iradio_dmuv4r._bcd_to_int(
                iradio_dmuv4r._u32le(
                    upload, base + 1)))
        self.assertEqual("OPS", iradio_dmuv4r._decode_string(
            bytes(upload[base + 5:base + 21])))

    def test_sync_out_uses_section_relative_upload_addresses(self):
        radio = make_radio()
        radio.pipe = mock.Mock()
        radio._enter = mock.Mock()
        radio._exit = mock.Mock()
        radio._read_frame = mock.Mock(side_effect=[
            bytes([0] * iradio_dmuv4r.BLOCK_SIZE),
            bytes([0xFF] * iradio_dmuv4r.BLOCK_SIZE),
        ])
        radio._write_frame = mock.Mock()
        radio.status_fn = lambda status: None

        radio.sync_out()

        calls = radio._write_frame.call_args_list
        self.assertEqual(1, radio._enter.call_count)
        self.assertEqual(1, radio._exit.call_count)
        self.assertEqual((0x90, 0, mock.ANY), calls[0][0])
        self.assertEqual((0x91, 0, mock.ANY), calls[1][0])
        self.assertEqual((0x91, 47, mock.ANY), calls[48][0])
        self.assertEqual((0x92, 0, mock.ANY), calls[49][0])
        self.assertEqual((0x93, 0, mock.ANY), calls[50][0])
        self.assertEqual((0x93, 127, mock.ANY), calls[177][0])
        self.assertEqual((0x94, 0, mock.ANY), calls[178][0])
        self.assertEqual((0x94, 207, mock.ANY), calls[385][0])
        self.assertEqual((0x95, 0, mock.ANY), calls[386][0])
        self.assertEqual((0x96, 0, mock.ANY), calls[406][0])
        self.assertEqual((0x97, 0, mock.ANY), calls[418][0])
        self.assertEqual((0x98, 3, mock.ANY), calls[-1][0])
        self.assertEqual(426, len(calls))

    def test_sync_out_full_upload_wire_frames(self):
        radio = make_radio()
        pipe = UploadPipe()
        statuses = []
        radio.pipe = pipe
        radio.status_fn = lambda status: statuses.append(
            (status.msg, status.cur, status.max))

        radio.sync_out()

        self.assertEqual(iradio_dmuv4r.READ_MAGIC, pipe.writes[0])
        self.assertEqual(iradio_dmuv4r.END_MAGIC, pipe.writes[-1])
        self.assertEqual(bytes([0x52, 0x00, 0x00,
                                checksum.checksum_8bit(b"\x52\x00\x00")]),
                         pipe.writes[1])
        self.assertEqual(bytes([0x52, 0x00, 0x08,
                                checksum.checksum_8bit(b"\x52\x00\x08")]),
                         pipe.writes[2])

        frames = pipe.writes[3:-1]
        self.assertEqual(426, len(frames))
        expected = []
        for opcode, _base, _segment, blocks in iradio_dmuv4r.SAFE_UPLOAD_PLAN:
            expected.extend((opcode, block) for block in range(blocks))
        actual = [(frame[0], (frame[1] << 8) | frame[2]) for frame in frames]
        self.assertEqual(expected, actual)
        for frame in frames:
            self.assertEqual(iradio_dmuv4r.BLOCK_SIZE + 4, len(frame))
            self.assertEqual(checksum.checksum_8bit(frame[:-1]), frame[-1])
        self.assertEqual((0x90, 0), actual[0])
        self.assertEqual((0x93, 0), actual[50])
        self.assertEqual((0x93, 127), actual[177])
        self.assertEqual((0x98, 3), actual[-1])
        self.assertEqual([1, iradio_dmuv4r.BLOCK_SIZE + 4,
                          iradio_dmuv4r.BLOCK_SIZE + 4] +
                         ([1] * 426),
                         pipe.read_sizes)
        self.assertEqual(1, pipe.timeout)
        self.assertEqual(("Uploading to radio", 426, 426), statuses[-1])

    def test_sync_out_appends_enabled_poweron_image(self):
        radio = make_radio()
        startup_image = radio._get_segment("startup_image")
        startup_image[0] = 0x01
        startup_image[1:1 + iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE] = (
            bytes(range(256)) * 16)
        radio._set_segment("startup_image", startup_image)

        radio.pipe = mock.Mock()
        radio._enter = mock.Mock()
        radio._exit = mock.Mock()
        radio._read_frame = mock.Mock(side_effect=[
            bytes([0] * iradio_dmuv4r.BLOCK_SIZE),
            bytes([0xFF] * iradio_dmuv4r.BLOCK_SIZE),
        ])
        radio._write_frame = mock.Mock()
        radio.status_fn = lambda status: None

        radio.sync_out()

        calls = radio._write_frame.call_args_list
        self.assertEqual(427, len(calls))
        self.assertEqual((0x9A, 0, mock.ANY), calls[-1][0])
        self.assertEqual(bytes(range(256)) * 4, calls[-1][0][2])

    def test_sync_out_startup_image_only(self):
        radio = make_radio()
        startup_image = radio._get_segment("startup_image")
        startup_image[0] = 0x01
        startup_image[1:1 + iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE] = (
            b"\x55" * iradio_dmuv4r.STARTUP_IMAGE_PAYLOAD_SIZE)
        radio._set_segment("startup_image", startup_image)

        radio._enter = mock.Mock()
        radio._exit = mock.Mock()
        radio._write_frame = mock.Mock()
        radio.status_fn = lambda status: None

        radio.sync_out_startup_image()

        calls = radio._write_frame.call_args_list
        self.assertEqual(4, len(calls))
        self.assertEqual((0x9A, 0, mock.ANY), calls[0][0])
        self.assertEqual((0x9A, 3, mock.ANY), calls[-1][0])

    def test_sync_out_appends_enabled_global_contacts(self):
        radio = make_radio()
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", delete=False) as csv_file:
                path = csv_file.name
                csv_file.write("id,callsign,name,city,state,country,extra\n")
                csv_file.write("123,OK1ABC,Jose,Prague,CZ,Czechia,ignored\n")

            global_contacts = radio._get_segment("global_contacts")
            global_contacts[0] = 0x01
            global_contacts[1:1 + len(path)] = path.encode("ascii")
            radio._set_segment("global_contacts", global_contacts)

            radio.pipe = mock.Mock()
            radio._enter = mock.Mock()
            radio._exit = mock.Mock()
            radio._read_frame = mock.Mock(side_effect=[
                bytes([0] * iradio_dmuv4r.BLOCK_SIZE),
                bytes([0xFF] * iradio_dmuv4r.BLOCK_SIZE),
            ])
            radio._write_frame = mock.Mock()
            radio.status_fn = lambda status: None

            radio.sync_out()
        finally:
            if path:
                os.unlink(path)

        calls = radio._write_frame.call_args_list
        self.assertEqual(2, radio._enter.call_count)
        self.assertEqual(2, radio._exit.call_count)
        self.assertEqual(427, len(calls))
        self.assertEqual((0xA4, 0, mock.ANY), calls[-1][0])
        expected = b"123,OK1ABC,Jose,Prague,CZ,Czechia\n"
        self.assertEqual(expected, calls[-1][0][2][4:4 + len(expected)])

    def test_sync_out_global_contacts_only(self):
        radio = make_radio()
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", delete=False) as csv_file:
                path = csv_file.name
                csv_file.write("id,callsign,name,city,state,country,extra\n")
                csv_file.write("123,OK1ABC,Jose,Prague,CZ,Czechia,ignored\n")

            global_contacts = radio._get_segment("global_contacts")
            global_contacts[0] = 0x01
            global_contacts[1:1 + len(path)] = path.encode("ascii")
            radio._set_segment("global_contacts", global_contacts)

            radio._enter = mock.Mock()
            radio._exit = mock.Mock()
            radio._write_frame = mock.Mock()
            radio.status_fn = lambda status: None

            radio.sync_out_global_contacts()
        finally:
            if path:
                os.unlink(path)

        calls = radio._write_frame.call_args_list
        self.assertEqual(1, len(calls))
        self.assertEqual((0xA4, 0, mock.ANY), calls[0][0])

    def test_startup_image_utility_writer_frames(self):
        radio = make_radio()
        payload = bytes(range(256)) * 16
        startup_image = radio._get_segment("startup_image")
        startup_image[0] = 0x01
        startup_image[1:1 + len(payload)] = payload
        radio._set_segment("startup_image", startup_image)

        pipe = AckPipe()
        statuses = []
        radio.pipe = pipe
        radio.status_fn = lambda status: statuses.append(
            (status.msg, status.cur, status.max))

        radio.sync_out_startup_image()

        self.assertEqual(iradio_dmuv4r.READ_MAGIC, pipe.writes[0])
        self.assertEqual(iradio_dmuv4r.END_MAGIC, pipe.writes[-1])
        frames = pipe.writes[1:-1]
        self.assertEqual(4, len(frames))
        for index, frame in enumerate(frames):
            self.assertEqual(0x9A, frame[0])
            self.assertEqual(bytes([0, index]), frame[1:3])
            self.assertEqual(iradio_dmuv4r.BLOCK_SIZE + 4, len(frame))
            self.assertEqual(payload[index * iradio_dmuv4r.BLOCK_SIZE:
                                     (index + 1) * iradio_dmuv4r.BLOCK_SIZE],
                             frame[3:-1])
            self.assertEqual(checksum.checksum_8bit(frame[:-1]), frame[-1])
        self.assertEqual([1, 1, 1, 1, 1], pipe.read_sizes)
        self.assertEqual(1, pipe.timeout)
        self.assertEqual(("Uploading power-on image", 4, 4), statuses[-1])

    def test_global_contacts_utility_writer_frames(self):
        radio = make_radio()
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", delete=False) as csv_file:
                path = csv_file.name
                csv_file.write("id,callsign,name,city,state,country,extra\n")
                csv_file.write("123,OK1ABC,Jose,Prague,CZ,Czechia,ignored\n")

            global_contacts = radio._get_segment("global_contacts")
            global_contacts[0] = 0x01
            global_contacts[1:1 + len(path)] = path.encode("ascii")
            radio._set_segment("global_contacts", global_contacts)

            pipe = AckPipe()
            statuses = []
            radio.pipe = pipe
            radio.status_fn = lambda status: statuses.append(
                (status.msg, status.cur, status.max))

            radio.sync_out_global_contacts()
        finally:
            if path:
                os.unlink(path)

        self.assertEqual(iradio_dmuv4r.READ_MAGIC, pipe.writes[0])
        self.assertEqual(iradio_dmuv4r.END_MAGIC, pipe.writes[-1])
        self.assertEqual(3, len(pipe.writes))
        frame = pipe.writes[1]
        self.assertEqual(0xA4, frame[0])
        self.assertEqual(b"\x00\x00", frame[1:3])
        self.assertEqual(iradio_dmuv4r.BLOCK_SIZE + 4, len(frame))
        expected = b"123,OK1ABC,Jose,Prague,CZ,Czechia\n"
        self.assertEqual(expected, frame[7:7 + len(expected)])
        declared = (
            (frame[3] << 24) | (frame[4] << 16) |
            (frame[5] << 8) | frame[6])
        self.assertEqual(len(expected) + 4, declared)
        self.assertEqual(checksum.checksum_8bit(frame[:-1]), frame[-1])
        self.assertEqual([1, 1], pipe.read_sizes)
        self.assertEqual(1, pipe.timeout)
        self.assertEqual(("Uploading global contacts", 1, 1), statuses[-1])

    def test_utility_upload_does_not_exit_when_enter_fails(self):
        radio = make_radio()
        radio._enter = mock.Mock(
            side_effect=iradio_dmuv4r.errors.RadioNoResponse())
        radio._exit = mock.Mock()

        with self.assertRaises(iradio_dmuv4r.errors.RadioNoResponse):
            radio._sync_out_utility_blocks(
                0x9A, [bytes([0] * iradio_dmuv4r.BLOCK_SIZE)],
                "Uploading power-on image")

        radio._exit.assert_not_called()

    def test_global_contacts_error_replies_are_specific(self):
        radio = make_radio()
        radio.pipe = mock.Mock()
        radio.pipe.timeout = 1

        radio.pipe.read.return_value = b"\xA4"
        with self.assertRaisesRegex(iradio_dmuv4r.errors.RadioError,
                                    "flash IC mismatch"):
            radio._write_frame(0xA4, 0, bytes([0] * iradio_dmuv4r.BLOCK_SIZE))

        radio.pipe.read.return_value = b"\x4A"
        with self.assertRaisesRegex(iradio_dmuv4r.errors.RadioError,
                                    "flash capacity"):
            radio._write_frame(0xA4, 1, bytes([0] * iradio_dmuv4r.BLOCK_SIZE))

    def test_read_plan_matches_newer_oem_zone_map(self):
        self.assertIn((0x0070, "vfo", 1), iradio_dmuv4r.READ_PLAN)
        self.assertIn((0x0078, "zone", 128), iradio_dmuv4r.READ_PLAN)
        self.assertIn((0x0178, "contact", 208), iradio_dmuv4r.READ_PLAN)
        self.assertIn((0x0318, "group", 20), iradio_dmuv4r.READ_PLAN)
        self.assertIn((0x0340, "encrypt", 12), iradio_dmuv4r.READ_PLAN)
        self.assertIn((0x0358, "sms", 100), iradio_dmuv4r.READ_PLAN)
        self.assertIn((0x03C0, "fm", 4), iradio_dmuv4r.READ_PLAN)

    def test_vfo_special_channels_are_advertised(self):
        self.assertEqual(["VFO-A", "VFO-B"],
                         make_radio().get_features().valid_special_chans)
