#!/usr/bin/env python3
#
# Developer helper for Iradio DM-UV4R optional OEM utility writers.
#
# This is intentionally not wired into normal chirpc upload flow. The 0x9A
# power-on image writer and 0xA4 global contact writer are separate OEM utility
# paths and should be exercised explicitly, with dry-run output first.

import argparse
import hashlib
import json
import os
import shlex
import sys
import tempfile
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import serial  # noqa: E402

from chirp import errors  # noqa: E402
from chirp.drivers.iradio_dmuv4r import (  # noqa: E402
    GLOBAL_CONTACT_MAX_PAYLOAD,
    IradioDMUV4RRadio,
    MATCH_MODEL_SIZES,
    SEGMENTS,
    STARTUP_IMAGE_PAYLOAD_SIZE,
)


STARTUP_TEST_PATTERNS = ("blank", "checkerboard", "border")
GLOBAL_CONTACT_TEST_SETS = ("minimal",)
AFTER_WRITE_BACKUP_RETRY_DELAYS = (2.0, 5.0, 10.0)
SCRIPT_VALUE_OPTIONS = {
    "--image", "--operation", "--port", "--timeout", "--expect-manifest",
    "--backup-dir", "--report", "--startup-payload", "--startup-bitmap",
    "--startup-scale-width", "--startup-scale-height", "--startup-crop-x",
    "--startup-crop-y", "--startup-test-pattern", "--csv",
    "--global-contacts-test-set",
}
SCRIPT_FLAG_OPTIONS = {
    "--execute", "--strict-validation", "--fail-on-backup-diff",
}


def _die(message):
    raise SystemExit(message)


def _read_startup_payload(path):
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise errors.RadioError("Startup payload does not exist: %s" % path)
    if not os.path.isfile(path):
        raise errors.RadioError("Startup payload is not a file: %s" % path)
    try:
        with open(path, "rb") as payload_file:
            payload = payload_file.read()
    except OSError as exc:
        raise errors.RadioError(
            "Startup payload cannot be read: %s" % exc) from exc
    valid_lengths = (1024, STARTUP_IMAGE_PAYLOAD_SIZE)
    if len(payload) not in valid_lengths:
        raise errors.RadioError(
            "Startup payload must be 1024 or %d bytes, got %d" %
            (STARTUP_IMAGE_PAYLOAD_SIZE, len(payload)))
    return payload


def _startup_payload_from_bitmap(
        path,
        scale_width,
        scale_height,
        crop_x,
        crop_y):
    try:
        from PIL import Image
    except ImportError as exc:
        raise errors.RadioError(
            "Pillow is required for --startup-bitmap") from exc

    if scale_width < 128 or scale_height < 64:
        raise errors.RadioError(
            "Scaled startup bitmap must be at least 128x64")
    if crop_x < 0 or crop_y < 0:
        raise errors.RadioError(
            "Startup bitmap crop offsets must be non-negative")
    if crop_x + 128 > scale_width or crop_y + 64 > scale_height:
        raise errors.RadioError(
            "Startup bitmap crop exceeds scaled image bounds")

    source = Image.open(os.path.expanduser(path)).convert("RGB")
    resampling = getattr(getattr(Image, "Resampling", Image), "BICUBIC")
    scaled = source.resize((scale_width, scale_height), resampling)
    cropped = scaled.crop((crop_x, crop_y, crop_x + 128, crop_y + 64))

    payload = bytearray(b"\x00" * STARTUP_IMAGE_PAYLOAD_SIZE)
    for row_group in range(8):
        for x_pos in range(128):
            byte_index = 1023 - (row_group * 128 + (127 - x_pos))
            for bit_row in range(8):
                r_val, g_val, b_val = cropped.getpixel(
                    (x_pos, row_group * 8 + bit_row))
                payload[byte_index] >>= 1
                if not (r_val > 128 and g_val > 128 and b_val > 128):
                    payload[byte_index] |= 0x80
    payload[896] = 0x00
    return bytes(payload)


def _startup_test_payload(pattern):
    if pattern == "blank":
        return b"\x00" * STARTUP_IMAGE_PAYLOAD_SIZE
    if pattern == "checkerboard":
        block = bytearray(1024)
        for index in range(len(block)):
            block[index] = 0xAA if index % 2 else 0x55
        return bytes(block) + (b"\x00" * (STARTUP_IMAGE_PAYLOAD_SIZE - 1024))
    if pattern == "border":
        block = bytearray(b"\x00" * 1024)
        for x_pos in range(128):
            block[x_pos] = 0xFF
            block[896 + x_pos] = 0xFF
        for row in range(8):
            block[row * 128] = 0xFF
            block[row * 128 + 127] = 0xFF
        return bytes(block) + (b"\x00" * (STARTUP_IMAGE_PAYLOAD_SIZE - 1024))
    raise errors.RadioError("Unknown startup test pattern: %s" % pattern)


def _global_contacts_test_csv(test_set):
    if test_set == "minimal":
        return (
            "No,Radio ID,Callsign,Name,City,State,Country\n"
            "1,1234567,N0CALL,TEST,Prague,CZ,Czech\n")
    raise errors.RadioError("Unknown global contacts test set: %s" % test_set)


def _write_global_contacts_test_csv(test_set):
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False,
                prefix="iradio_dmuv4r_global_contacts_",
                suffix=".csv") as csv_file:
            csv_file.write(_global_contacts_test_csv(test_set))
            return csv_file.name
    except OSError as exc:
        raise errors.RadioError(
            "Global contacts test CSV cannot be created: %s" % exc) from exc


def _enable_startup_payload(radio, payload):
    data = bytearray(b"\x00" * (1 + STARTUP_IMAGE_PAYLOAD_SIZE))
    data[0] = 0x01
    data[1:1 + len(payload)] = payload
    radio._set_segment("startup_image", data)


def _enable_global_contacts(radio, csv_path):
    data = radio._get_segment("global_contacts")
    data[0] = 0x01
    radio._set_segment("global_contacts", data)
    radio._set_global_contacts_path(csv_path)


def _build_blocks(radio, operation):
    if operation == "startup-image":
        return 0x9A, radio._build_startup_image_upload()
    if operation == "global-contacts":
        return 0xA4, radio._build_global_contacts_upload()
    raise AssertionError("unknown operation %s" % operation)


def _payload_source(radio, operation, args):
    if operation == "startup-image":
        if args.startup_test_pattern:
            return "startup-test-pattern:%s" % args.startup_test_pattern
        if args.startup_bitmap:
            return os.path.expanduser(args.startup_bitmap)
        if args.startup_payload:
            return os.path.expanduser(args.startup_payload)
        return "image settings"
    if args.global_contacts_test_set:
        return "global-contacts-test-set:%s" % args.global_contacts_test_set
    if args.csv:
        return os.path.expanduser(args.csv)
    return radio._global_contacts_path() or "image settings"


def _payload_sha256(blocks):
    digest = hashlib.sha256()
    for block in blocks:
        digest.update(bytes(block))
    return digest.hexdigest()


def _normalize_sha256(value):
    if not value:
        return None
    text = str(value).strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise errors.RadioError(
            "Expected payload SHA-256 must be 64 hex characters")
    return text


def _check_expected_payload_sha256(blocks, expected):
    expected = _normalize_sha256(expected)
    if not expected:
        return None
    actual = _payload_sha256(blocks)
    if actual != expected:
        raise errors.RadioError(
            "Payload SHA-256 mismatch: expected %s, got %s" %
            (expected, actual))
    return actual


def _read_manifest(path):
    manifest_path = os.path.expanduser(path)
    if not os.path.exists(manifest_path):
        raise errors.RadioError("Manifest does not exist: %s" % manifest_path)
    if not os.path.isfile(manifest_path):
        raise errors.RadioError("Manifest is not a file: %s" % manifest_path)
    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except (OSError, ValueError) as exc:
        raise errors.RadioError("Manifest cannot be read: %s" % exc) from exc
    if not isinstance(manifest, dict):
        raise errors.RadioError("Manifest must be a JSON object")
    return manifest


def _read_execute_report(path):
    report_path = os.path.expanduser(path)
    if not os.path.exists(report_path):
        raise errors.RadioError(
            "Execute report does not exist: %s" % report_path)
    if not os.path.isfile(report_path):
        raise errors.RadioError(
            "Execute report is not a file: %s" % report_path)
    try:
        with open(report_path, "r", encoding="utf-8") as report_file:
            report = json.load(report_file)
    except (OSError, ValueError) as exc:
        raise errors.RadioError("Execute report cannot be read: %s" %
                                exc) from exc
    if not isinstance(report, dict):
        raise errors.RadioError("Execute report must be a JSON object")
    return report


def _check_expected_manifest(actual, path):
    if not path:
        return None
    expected = _read_manifest(path)
    checks = (
        "schema", "vendor", "model", "operation", "opcode", "blocks",
        "payload_bytes", "wire_bytes", "payload_sha256",
        "first_frame_checksum", "last_frame_checksum",
        "declared_database_bytes", "maximum_oem_payload_bytes",
    )
    for key in checks:
        if expected.get(key) != actual.get(key):
            raise errors.RadioError(
                "Manifest mismatch for %s: expected %r, got %r" %
                (key, expected.get(key), actual.get(key)))
    return actual["payload_sha256"]


def _frame_checksum(opcode, block, payload):
    frame = bytes([opcode, (block >> 8) & 0xFF, block & 0xFF])
    return (sum(frame) + sum(payload)) & 0xFF


def _payload_manifest(radio, operation, opcode, blocks, args):
    manifest = {
        "schema": "iradio-dmuv4r-optional-writer-v1",
        "vendor": radio.VENDOR,
        "model": radio.MODEL,
        "operation": operation,
        "opcode": "0x%02X" % opcode,
        "source": _payload_source(radio, operation, args),
        "blocks": len(blocks),
        "payload_bytes": len(blocks) * 1024,
        "wire_bytes": len(blocks) * 1028,
        "payload_sha256": _payload_sha256(blocks),
        "first_frame_checksum": "0x%02X" %
        _frame_checksum(opcode, 0, blocks[0]),
        "last_frame_checksum": "0x%02X" %
        _frame_checksum(opcode, len(blocks) - 1, blocks[-1]),
    }
    if operation == "global-contacts":
        manifest["declared_database_bytes"] = (
            (blocks[0][0] << 24) |
            (blocks[0][1] << 16) |
            (blocks[0][2] << 8) |
            blocks[0][3]
        )
        manifest["maximum_oem_payload_bytes"] = GLOBAL_CONTACT_MAX_PAYLOAD
    return manifest


def _build_payload_from_args(args):
    radio = _load_radio_image(args.image)

    if args.startup_payload:
        _enable_startup_payload(
            radio, _read_startup_payload(args.startup_payload))
    if args.startup_bitmap:
        _enable_startup_payload(
            radio,
            _startup_payload_from_bitmap(
                args.startup_bitmap,
                args.startup_scale_width,
                args.startup_scale_height,
                args.startup_crop_x,
                args.startup_crop_y))
    if args.startup_test_pattern:
        _enable_startup_payload(
            radio, _startup_test_payload(args.startup_test_pattern))
    global_contacts_test_csv = None
    if args.global_contacts_test_set:
        global_contacts_test_csv = _write_global_contacts_test_csv(
            args.global_contacts_test_set)
        _enable_global_contacts(radio, global_contacts_test_csv)
    if args.csv:
        _enable_global_contacts(radio, args.csv)

    try:
        opcode, blocks = _build_blocks(radio, args.operation)
    finally:
        if global_contacts_test_csv:
            try:
                os.unlink(global_contacts_test_csv)
            except OSError:
                pass
    if not blocks:
        raise errors.RadioError(
            "No payload configured for %s" % args.operation.replace("-", " "))
    return radio, opcode, blocks, _payload_manifest(
        radio, args.operation, opcode, blocks, args)


def _print_dry_run(radio, operation, opcode, blocks, args):
    if not blocks:
        raise errors.RadioError(
            "No payload configured for %s" % operation.replace("-", " "))

    manifest = _payload_manifest(radio, operation, opcode, blocks, args)
    print("DRY RUN: no serial port opened and no radio writes performed")
    print("radio: %s %s" % (manifest["vendor"], manifest["model"]))
    print("operation: %s" % manifest["operation"])
    print("opcode: %s" % manifest["opcode"])
    print("source: %s" % manifest["source"])
    print("blocks: %d" % manifest["blocks"])
    print("payload bytes: %d" % manifest["payload_bytes"])
    print("wire bytes: %d" % manifest["wire_bytes"])
    print("payload sha256: %s" % manifest["payload_sha256"])
    print("first frame checksum: %s" % manifest["first_frame_checksum"])
    print("last frame checksum: %s" % manifest["last_frame_checksum"])
    if operation == "global-contacts":
        print("declared database bytes: %d" %
              manifest["declared_database_bytes"])
        print("maximum OEM payload bytes: %d" %
              manifest["maximum_oem_payload_bytes"])
    return manifest


COMPARE_SEGMENTS = (
    "cfg", "vfo", "all", "zone", "contact", "group", "encrypt", "sms", "fm")


def _read_image_payload(path):
    with open(os.path.expanduser(path), "rb") as image_file:
        data = image_file.read()
    for size in MATCH_MODEL_SIZES:
        if len(data) == size:
            return data
        if data[size:size + len(IradioDMUV4RRadio.MAGIC)
                ] == IradioDMUV4RRadio.MAGIC:
            return data[:size]
    return data


def _compare_backup_images(before_path, after_path, fail_on_diff=False):
    before = _read_image_payload(before_path)
    after = _read_image_payload(after_path)
    differences = []
    for name in COMPARE_SEGMENTS:
        offset, size = SEGMENTS[name]
        before_segment = before[offset:offset + size]
        after_segment = after[offset:offset + size]
        if before_segment != after_segment:
            changed = sum(
                1 for old, new in zip(before_segment, after_segment)
                if old != new)
            changed += abs(len(before_segment) - len(after_segment))
            differences.append((name, changed))

    if not differences:
        print("Backup comparison: normal codeplug sections unchanged")
        return differences

    print("Backup comparison: normal codeplug differences found")
    for name, changed in differences:
        print("  %s: %d bytes differ" % (name, changed))
    if fail_on_diff:
        raise errors.RadioError(
            "Backup comparison found codeplug differences: %s" %
            ", ".join(name for name, _changed in differences))
    return differences


def _status(status):
    print("%s: %d/%d" % (status.msg, status.cur, status.max))


def _open_serial(port, timeout, baudrate):
    return serial.Serial(
        port=os.path.expanduser(port),
        baudrate=baudrate,
        timeout=timeout)


def _check_backup_path(path, overwrite=False):
    backup_path = os.path.expanduser(path)
    parent = os.path.dirname(os.path.abspath(backup_path))
    if not os.path.isdir(parent):
        raise errors.RadioError(
            "Backup directory does not exist: %s" % parent)
    if os.path.isdir(backup_path):
        raise errors.RadioError("Backup path is a directory: %s" % backup_path)
    if os.path.exists(backup_path) and not overwrite:
        raise errors.RadioError(
            "Backup path already exists: %s; use --overwrite-backup "
            "to replace it" % backup_path)
    return backup_path


def _check_output_path(path, label, overwrite=False):
    output_path = os.path.expanduser(path)
    parent = os.path.dirname(os.path.abspath(output_path))
    if not os.path.isdir(parent):
        raise errors.RadioError("%s directory does not exist: %s" %
                                (label, parent))
    if os.path.isdir(output_path):
        raise errors.RadioError("%s path is a directory: %s" %
                                (label, output_path))
    if os.path.exists(output_path) and not overwrite:
        raise errors.RadioError(
            "%s path already exists: %s; use --overwrite-manifest "
            "to replace it" % (label, output_path))
    return output_path


def _check_image_path(path):
    image_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(image_path):
        raise errors.RadioError("Image does not exist: %s" % image_path)
    if not os.path.isfile(image_path):
        raise errors.RadioError("Image is not a file: %s" % image_path)
    return image_path


def _load_radio_image(path):
    image_path = _check_image_path(path)
    try:
        return IradioDMUV4RRadio(image_path)
    except OSError as exc:
        raise errors.RadioError("Image cannot be read: %s" % exc) from exc


def _single_bundle_path(bundle_dir, suffix, label):
    matches = [
        os.path.join(bundle_dir, name)
        for name in os.listdir(bundle_dir)
        if name.endswith(suffix)
    ]
    if len(matches) != 1:
        raise errors.RadioError(
            "Validation bundle must contain exactly one %s file" % label)
    return matches[0]


def _read_command_script(path):
    try:
        with open(path, "r", encoding="utf-8") as command_file:
            lines = command_file.read().splitlines()
    except OSError as exc:
        raise errors.RadioError(
            "Command script cannot be read: %s" % exc) from exc
    if not lines or lines[0].strip() != "#!/bin/sh":
        raise errors.RadioError("Command script must start with '#!/bin/sh'")
    meaningful = [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(meaningful) < 2 or meaningful[0] != "set -eu":
        raise errors.RadioError("Command script must enable 'set -eu'")
    try:
        return shlex.split(meaningful[-1])
    except ValueError as exc:
        raise errors.RadioError(
            "Command script cannot be parsed: %s" % exc) from exc


def _parse_command_options(parts):
    if len(parts) < 3:
        raise errors.RadioError(
            "Command script does not contain utility command")
    if os.path.basename(parts[1]) != "iradio_dmuv4r_utility.py":
        raise errors.RadioError("Command script does not call this utility")
    options = {}
    flags = set()
    index = 2
    while index < len(parts):
        token = parts[index]
        if token in SCRIPT_VALUE_OPTIONS:
            if index + 1 >= len(parts):
                raise errors.RadioError(
                    "Command option missing value: %s" % token)
            options[token] = parts[index + 1]
            index += 2
        elif token in SCRIPT_FLAG_OPTIONS:
            flags.add(token)
            index += 1
        else:
            raise errors.RadioError("Unexpected command option: %s" % token)
    return options, flags


def _require_option(options, option):
    if option not in options or not options[option]:
        raise errors.RadioError("Command script missing %s" % option)
    return options[option]


def _abs_path(path):
    return os.path.abspath(os.path.expanduser(path))


def _require_absolute_option(options, option):
    value = _require_option(options, option)
    if not os.path.isabs(os.path.expanduser(value)):
        raise errors.RadioError("Command script %s must be absolute" % option)
    return value


def _require_absolute_optional_path(options, option):
    value = options.get(option)
    if value and not os.path.isabs(os.path.expanduser(value)):
        raise errors.RadioError("Command script %s must be absolute" % option)
    return value


def _args_from_command_options(options):
    def int_option(name, default):
        value = options.get(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError as exc:
            raise errors.RadioError("Command option %s must be an integer" %
                                    name) from exc

    return argparse.Namespace(
        image=_require_option(options, "--image"),
        operation=_require_option(options, "--operation"),
        startup_payload=options.get("--startup-payload"),
        startup_bitmap=options.get("--startup-bitmap"),
        startup_test_pattern=options.get("--startup-test-pattern"),
        startup_scale_width=int_option("--startup-scale-width", 360),
        startup_scale_height=int_option("--startup-scale-height", 180),
        startup_crop_x=int_option("--startup-crop-x", 0),
        startup_crop_y=int_option("--startup-crop-y", 0),
        csv=options.get("--csv"),
        global_contacts_test_set=options.get("--global-contacts-test-set"),
    )


def _verify_validation_bundle(path):
    bundle_dir = _abs_path(path)
    if not os.path.isdir(bundle_dir):
        raise errors.RadioError(
            "Validation bundle is not a directory: %s" % bundle_dir)

    manifest_path = _single_bundle_path(
        bundle_dir, "_manifest.json", "manifest")
    manifest = _read_manifest(manifest_path)
    operation = manifest.get("operation")
    if operation not in ("startup-image", "global-contacts"):
        raise errors.RadioError(
            "Validation bundle manifest has invalid operation")
    stem = _operation_stem(operation)
    command_path = os.path.join(bundle_dir, "%s_execute_command.sh" % stem)
    backup_dir = os.path.join(bundle_dir, "%s_backups" % stem)
    report_path = os.path.join(bundle_dir, "%s_execute_report.json" % stem)
    readme_path = os.path.join(bundle_dir, "%s_README.txt" % stem)

    for required_path, label in (
            (command_path, "command script"),
            (readme_path, "README"),
            (backup_dir, "backup directory")):
        if label == "backup directory":
            if not os.path.isdir(required_path):
                raise errors.RadioError(
                    "Validation bundle missing %s: %s" %
                    (label, required_path))
        elif not os.path.isfile(required_path):
            raise errors.RadioError(
                "Validation bundle missing %s: %s" % (label, required_path))
    if not os.access(command_path, os.X_OK):
        raise errors.RadioError(
            "Validation bundle command script is not executable: %s" %
            command_path)
    if os.path.exists(report_path):
        raise errors.RadioError(
            "Validation bundle execute report already exists: %s" %
            report_path)

    parts = _read_command_script(command_path)
    options, flags = _parse_command_options(parts)
    for flag in ("--execute", "--strict-validation", "--fail-on-backup-diff"):
        if flag not in flags:
            raise errors.RadioError("Command script missing %s" % flag)
    if _require_option(options, "--operation") != operation:
        raise errors.RadioError("Command operation does not match manifest")
    image_path = _require_absolute_option(options, "--image")
    if _abs_path(image_path) != image_path:
        raise errors.RadioError("Command image path is not normalized")
    if _abs_path(
        _require_absolute_option(
            options,
            "--expect-manifest")) != manifest_path:
        raise errors.RadioError("Command manifest path does not match bundle")
    if _abs_path(
        _require_absolute_option(
            options,
            "--backup-dir")) != backup_dir:
        raise errors.RadioError("Command backup dir does not match bundle")
    if _abs_path(_require_absolute_option(options, "--report")) != report_path:
        raise errors.RadioError("Command report path does not match bundle")
    for option in ("--startup-payload", "--startup-bitmap", "--csv"):
        _require_absolute_optional_path(options, option)
    _require_option(options, "--port")

    args = _args_from_command_options(options)
    _radio, _opcode, _blocks, actual_manifest = _build_payload_from_args(args)
    verified_sha = _check_expected_manifest(actual_manifest, manifest_path)

    print("Validation bundle verified: %s" % bundle_dir)
    print("operation: %s" % operation)
    print("manifest: %s" % manifest_path)
    print("command: %s" % command_path)
    print("backup dir: %s" % backup_dir)
    print("report: %s" % report_path)
    print("payload sha256: %s" % verified_sha)
    return {
        "bundle_dir": bundle_dir,
        "operation": operation,
        "manifest": manifest_path,
        "command": command_path,
        "backup_dir": backup_dir,
        "report": report_path,
        "payload_sha256": verified_sha,
    }


def _verify_execute_report(path):
    report_path = _abs_path(path)
    report = _read_execute_report(report_path)
    if report.get("schema") != "iradio-dmuv4r-optional-execute-report-v1":
        raise errors.RadioError("Execute report has invalid schema")
    if report.get("status") != "success":
        raise errors.RadioError("Execute report status is not success")

    operation = report.get("operation")
    if operation not in ("startup-image", "global-contacts"):
        raise errors.RadioError("Execute report has invalid operation")
    manifest = report.get("payload_manifest")
    if not isinstance(manifest, dict):
        raise errors.RadioError("Execute report missing payload manifest")
    if manifest.get("operation") != operation:
        raise errors.RadioError(
            "Execute report operation does not match payload manifest")
    expected_opcode = "0x9A" if operation == "startup-image" else "0xA4"
    if manifest.get("opcode") != expected_opcode:
        raise errors.RadioError("Execute report payload opcode mismatch")

    payload_sha = manifest.get("payload_sha256")
    if not payload_sha:
        raise errors.RadioError("Execute report missing payload SHA-256")
    expected_manifest = report.get("expected_manifest")
    if expected_manifest:
        verified_sha = _check_expected_manifest(manifest, expected_manifest)
        if report.get("verified_manifest_sha256") != verified_sha:
            raise errors.RadioError(
                "Execute report verified manifest SHA-256 mismatch")
    else:
        verified_sha = report.get("verified_payload_sha256")
        if verified_sha != payload_sha:
            raise errors.RadioError(
                "Execute report verified payload SHA-256 mismatch")

    if report.get("compare_backups") is not True:
        raise errors.RadioError("Execute report did not compare backups")
    if report.get("normal_codeplug_unchanged") is not True:
        raise errors.RadioError(
            "Execute report says normal codeplug changed or was not checked")
    if report.get("backup_differences") != []:
        raise errors.RadioError("Execute report contains backup differences")
    before = report.get("backup_before")
    after = report.get("backup_after")
    if not before or not after:
        raise errors.RadioError("Execute report missing backup paths")
    # Recheck current backup artifacts so the report is not the only evidence.
    _compare_backup_images(before, after, fail_on_diff=True)

    print("Execute report verified: %s" % report_path)
    print("operation: %s" % operation)
    print("payload sha256: %s" % payload_sha)
    print("expected manifest: %s" % (expected_manifest or "none"))
    print("backup before: %s" % before)
    print("backup after: %s" % after)
    return {
        "report": report_path,
        "operation": operation,
        "payload_sha256": payload_sha,
        "expected_manifest": expected_manifest,
        "backup_before": before,
        "backup_after": after,
    }


def _write_manifest(path, manifest, overwrite=False):
    manifest_path = _check_output_path(path, "Manifest", overwrite=overwrite)
    try:
        with open(manifest_path, "w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, indent=2, sort_keys=True)
            manifest_file.write("\n")
    except OSError as exc:
        raise errors.RadioError(
            "Manifest cannot be written: %s" % exc) from exc
    print("manifest: %s" % manifest_path)
    return manifest_path


def _write_report(path, report, overwrite=False):
    report_path = _check_output_path(path, "Report", overwrite=overwrite)
    try:
        with open(report_path, "w", encoding="utf-8") as report_file:
            json.dump(report, report_file, indent=2, sort_keys=True)
            report_file.write("\n")
    except OSError as exc:
        raise errors.RadioError("Report cannot be written: %s" % exc) from exc
    print("report: %s" % report_path)
    return report_path


def _write_text_file(path, text, label, overwrite=False, executable=False):
    output_path = _check_output_path(path, label, overwrite=overwrite)
    try:
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write(text)
    except OSError as exc:
        raise errors.RadioError("%s cannot be written: %s" %
                                (label, exc)) from exc
    if executable:
        os.chmod(output_path, 0o755)
    print("%s: %s" % (label.lower(), output_path))
    return output_path


def _utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _execute_report(args, manifest, checked_sha256, checked_manifest_sha256,
                    started_at, finished_at, backup_differences):
    differences = None
    normal_codeplug_unchanged = None
    if backup_differences is not None:
        differences = [
            {"segment": name, "changed_bytes": changed}
            for name, changed in backup_differences
        ]
        normal_codeplug_unchanged = not backup_differences
    return {
        "schema": "iradio-dmuv4r-optional-execute-report-v1",
        "status": "success",
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "operation": args.operation,
        "port": args.port,
        "timeout_seconds": args.timeout,
        "payload_manifest": manifest,
        "verified_payload_sha256": checked_sha256,
        "verified_manifest_sha256": checked_manifest_sha256,
        "expected_manifest": (
            os.path.expanduser(args.expect_manifest)
            if args.expect_manifest else None),
        "backup_before": (
            os.path.expanduser(args.backup_before)
            if args.backup_before else None),
        "backup_after": (
            os.path.expanduser(args.backup_after)
            if args.backup_after else None),
        "compare_backups": bool(args.compare_backups),
        "normal_codeplug_unchanged": normal_codeplug_unchanged,
        "backup_differences": differences,
    }


def _backup_paths_from_dir(path, operation):
    backup_dir = os.path.expanduser(path)
    if not os.path.isdir(backup_dir):
        raise errors.RadioError(
            "Backup directory does not exist: %s" % backup_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = "iradio_dmuv4r_%s_%s" % (operation.replace("-", "_"), stamp)
    before = os.path.join(backup_dir, stem + "_before.img")
    after = os.path.join(backup_dir, stem + "_after.img")
    return before, after


def _operation_stem(operation):
    return operation.replace("-", "_")


def _prepare_validation_bundle_dir(path):
    bundle_dir = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(os.path.abspath(bundle_dir))
    if not os.path.isdir(parent):
        raise errors.RadioError(
            "Validation bundle directory parent does not exist: %s" % parent)
    if os.path.exists(bundle_dir) and not os.path.isdir(bundle_dir):
        raise errors.RadioError(
            "Validation bundle path is not a directory: %s" % bundle_dir)
    if not os.path.exists(bundle_dir):
        try:
            os.makedirs(bundle_dir)
        except OSError as exc:
            raise errors.RadioError(
                "Validation bundle directory cannot be created: %s" %
                exc) from exc
    return bundle_dir


def _validation_payload_args(args):
    payload_args = []
    if args.startup_payload:
        payload_args.extend([
            "--startup-payload", _abs_path(args.startup_payload)])
    if args.startup_bitmap:
        payload_args.extend([
            "--startup-bitmap", _abs_path(args.startup_bitmap),
            "--startup-scale-width", str(args.startup_scale_width),
            "--startup-scale-height", str(args.startup_scale_height),
            "--startup-crop-x", str(args.startup_crop_x),
            "--startup-crop-y", str(args.startup_crop_y),
        ])
    if args.startup_test_pattern:
        payload_args.extend([
            "--startup-test-pattern", args.startup_test_pattern])
    if args.global_contacts_test_set:
        payload_args.extend([
            "--global-contacts-test-set", args.global_contacts_test_set])
    if args.csv:
        payload_args.extend(["--csv", _abs_path(args.csv)])
    return payload_args


def _validation_command(args, manifest_path, backup_dir, report_path):
    port = args.port or "/dev/ttyUSB0"
    command = [
        "python3", os.path.abspath(__file__),
        "--image", _check_image_path(args.image),
        "--operation", args.operation,
        "--execute",
        "--strict-validation",
        "--port", port,
        "--expect-manifest", manifest_path,
        "--backup-dir", backup_dir,
        "--fail-on-backup-diff",
        "--report", report_path,
    ]
    command.extend(_validation_payload_args(args))
    return " ".join(shlex.quote(part) for part in command)


def _write_validation_bundle(args, manifest):
    bundle_dir = _prepare_validation_bundle_dir(args.validation_bundle)
    stem = _operation_stem(args.operation)
    manifest_path = os.path.join(bundle_dir, "%s_manifest.json" % stem)
    backup_dir = os.path.join(bundle_dir, "%s_backups" % stem)
    report_path = os.path.join(bundle_dir, "%s_execute_report.json" % stem)
    command_path = os.path.join(bundle_dir, "%s_execute_command.sh" % stem)
    readme_path = os.path.join(bundle_dir, "%s_README.txt" % stem)
    try:
        os.makedirs(backup_dir, exist_ok=True)
    except OSError as exc:
        raise errors.RadioError(
            "Validation backup directory cannot be created: %s" % exc) from exc

    _write_manifest(
        manifest_path, manifest, overwrite=args.overwrite_validation_bundle)

    command = _validation_command(args, manifest_path, backup_dir, report_path)
    script = "#!/bin/sh\nset -eu\n%s\n" % command
    _write_text_file(
        command_path, script, "Command",
        overwrite=args.overwrite_validation_bundle, executable=True)

    readme = (
        "Iradio DM-UV4R optional writer validation bundle\n"
        "\n"
        "This bundle was generated in dry-run mode. No radio write was "
        "performed while creating it.\n"
        "\n"
        "Operation: %s\n"
        "Manifest: %s\n"
        "Backup directory: %s\n"
        "Execute report: %s\n"
        "\n"
        "Before running the command script:\n"
        "1. Inspect the manifest and payload source.\n"
        "2. Confirm the radio is connected and ready on the command port.\n"
        "3. Confirm you explicitly want to perform this optional writer.\n"
        "\n"
        "Offline verification command:\n"
        "python3 %s --verify-validation-bundle %s\n"
        "\n"
        "Post-run report verification command:\n"
        "python3 %s --verify-execute-report %s\n"
        "\n"
        "Command:\n%s\n" %
        (args.operation, manifest_path, backup_dir, report_path,
         os.path.abspath(__file__), bundle_dir, os.path.abspath(__file__),
         report_path, command))
    _write_text_file(
        readme_path, readme, "README",
        overwrite=args.overwrite_validation_bundle)
    print("validation bundle: %s" % bundle_dir)
    return {
        "bundle_dir": bundle_dir,
        "manifest": manifest_path,
        "backup_dir": backup_dir,
        "report": report_path,
        "command": command_path,
        "readme": readme_path,
    }


def _backup_radio(port, timeout, path, overwrite=False):
    backup_path = _check_backup_path(path, overwrite=overwrite)
    pipe = _open_serial(port, timeout, IradioDMUV4RRadio.BAUD_RATE)
    try:
        radio = IradioDMUV4RRadio(pipe)
        radio.status_fn = _status
        radio.sync_in()
        radio.save_mmap(backup_path)
        print("Backup saved: %s" % backup_path)
    finally:
        pipe.close()


def _backup_before_execute(port, timeout, path, overwrite=False):
    _backup_radio(port, timeout, path, overwrite=overwrite)


def _backup_after_execute(port, timeout, path, overwrite=False):
    for attempt, delay in enumerate(AFTER_WRITE_BACKUP_RETRY_DELAYS, start=1):
        try:
            _backup_radio(port, timeout, path, overwrite=overwrite)
            return
        except errors.RadioNoResponse:
            print(
                "Radio not ready for after-backup; retrying in %.0fs "
                "(attempt %d/%d)" %
                (delay, attempt + 1,
                 len(AFTER_WRITE_BACKUP_RETRY_DELAYS) + 1))
            time.sleep(delay)
    _backup_radio(port, timeout, path, overwrite=overwrite)


def _execute(radio, operation, port, timeout, blocks=None):
    pipe = _open_serial(port, timeout, radio.BAUD_RATE)
    try:
        radio.pipe = pipe
        radio.status_fn = _status
        if blocks is not None:
            if operation == "startup-image":
                radio._sync_out_utility_blocks(
                    0x9A, blocks, "Uploading power-on image")
            else:
                radio._sync_out_utility_blocks(
                    0xA4, blocks, "Uploading global contacts")
            return
        if operation == "startup-image":
            radio.sync_out_startup_image()
        else:
            radio.sync_out_global_contacts()
    finally:
        pipe.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Iradio DM-UV4R optional OEM utility uploader. Defaults to "
            "dry-run; serial writes require --execute. Use only after a "
            "current backup."))
    parser.add_argument(
        "--image",
        help="Existing CHIRP/DM-UV4R image to load")
    parser.add_argument(
        "--operation",
        choices=("startup-image", "global-contacts"),
        help="OEM utility writer to prepare or execute")
    parser.add_argument(
        "--port",
        help="Serial port, required with --execute or --backup-only")
    parser.add_argument(
        "--timeout", type=float, default=2.0,
        help="Serial read timeout in seconds for serial operations")
    parser.add_argument(
        "--backup-only",
        help="Read-only clone backup to this image path; performs no write")
    parser.add_argument(
        "--verify-validation-bundle",
        help=(
            "Offline verify a generated validation bundle without opening "
            "the serial port"))
    parser.add_argument(
        "--verify-execute-report",
        help=(
            "Offline verify a live execute report and its before/after "
            "backup artifacts"))
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually write to the radio; omit for dry-run")
    parser.add_argument(
        "--strict-validation", action="store_true",
        help=(
            "Require the full live validation gate set: --execute, "
            "--expect-manifest, before/after backups, --compare-backups, "
            "--fail-on-backup-diff, and --report"))
    parser.add_argument(
        "--i-have-current-backup", action="store_true",
        help="With --execute, confirm a fresh radio backup already exists")
    parser.add_argument(
        "--backup-before",
        help="With --execute, save a fresh radio backup before writing")
    parser.add_argument(
        "--backup-after",
        help="With --execute, save a fresh radio backup after writing")
    parser.add_argument(
        "--backup-dir",
        help=(
            "With --execute, create before/after backup files in this "
            "directory and compare normal codeplug sections afterward"))
    parser.add_argument(
        "--overwrite-backup", action="store_true",
        help="Allow backup files to replace existing paths")
    parser.add_argument(
        "--compare-backups", action="store_true",
        help="Compare normal codeplug sections after --backup-after")
    parser.add_argument(
        "--fail-on-backup-diff", action="store_true",
        help="Fail if --compare-backups finds normal codeplug differences")
    parser.add_argument(
        "--expect-payload-sha256",
        help=(
            "Require the generated optional payload blocks to match this "
            "SHA-256 before any execute-time serial session starts"))
    parser.add_argument(
        "--expect-manifest",
        help=(
            "Require generated optional payload metadata to match this "
            "dry-run manifest before any execute-time serial session starts"))
    parser.add_argument(
        "--manifest",
        help="Dry-run only: write optional payload metadata to this JSON file")
    parser.add_argument(
        "--overwrite-manifest", action="store_true",
        help="Allow --manifest to replace an existing file")
    parser.add_argument(
        "--validation-bundle",
        help=(
            "Dry-run only: create manifest plus strict live validation "
            "command files in this directory"))
    parser.add_argument(
        "--overwrite-validation-bundle", action="store_true",
        help="Allow validation bundle manifest/command files to be replaced")
    parser.add_argument(
        "--report",
        help="Execute only: write live optional-writer result report as JSON")
    parser.add_argument(
        "--overwrite-report", action="store_true",
        help="Allow --report to replace an existing file")
    parser.add_argument(
        "--startup-payload",
        help="Raw 1024- or 4096-byte power-on image payload")
    parser.add_argument(
        "--startup-bitmap",
        help=(
            "Bitmap/image file to convert using the OEM 128x64 startup "
            "format"))
    parser.add_argument(
        "--startup-test-pattern",
        choices=STARTUP_TEST_PATTERNS,
        help=(
            "Built-in deterministic startup image payload for validation "
            "without an external binary file"))
    parser.add_argument(
        "--startup-scale-width", type=int, default=360,
        help="Startup bitmap scaled width before crop, default 360")
    parser.add_argument(
        "--startup-scale-height", type=int, default=180,
        help="Startup bitmap scaled height before crop, default 180")
    parser.add_argument(
        "--startup-crop-x", type=int, default=0,
        help="Startup bitmap crop X after scaling, default 0")
    parser.add_argument(
        "--startup-crop-y", type=int, default=0,
        help="Startup bitmap crop Y after scaling, default 0")
    parser.add_argument(
        "--csv",
        help="Global contacts CSV source for the 0xA4 writer")
    parser.add_argument(
        "--global-contacts-test-set",
        choices=GLOBAL_CONTACT_TEST_SETS,
        help=(
            "Built-in deterministic global contacts CSV for validation "
            "without an external CSV file"))

    args = parser.parse_args(argv)
    if args.verify_execute_report:
        verify_conflicts = (
            args.image,
            args.operation,
            args.port,
            args.backup_only,
            args.verify_validation_bundle,
            args.execute,
            args.strict_validation,
            args.i_have_current_backup,
            args.backup_before,
            args.backup_after,
            args.backup_dir,
            args.overwrite_backup,
            args.compare_backups,
            args.fail_on_backup_diff,
            args.expect_payload_sha256,
            args.expect_manifest,
            args.manifest,
            args.overwrite_manifest,
            args.validation_bundle,
            args.overwrite_validation_bundle,
            args.report,
            args.overwrite_report,
            args.startup_payload,
            args.startup_bitmap,
            args.startup_test_pattern,
            args.csv,
            args.global_contacts_test_set,
        )
        if any(verify_conflicts):
            parser.error(
                "--verify-execute-report cannot be combined with other "
                "options")
        _verify_execute_report(args.verify_execute_report)
        return

    if args.verify_validation_bundle:
        verify_conflicts = (
            args.image, args.operation, args.port, args.backup_only,
            args.execute, args.strict_validation, args.i_have_current_backup,
            args.backup_before, args.backup_after, args.backup_dir,
            args.overwrite_backup, args.compare_backups,
            args.fail_on_backup_diff, args.expect_payload_sha256,
            args.expect_manifest, args.manifest, args.overwrite_manifest,
            args.validation_bundle, args.overwrite_validation_bundle,
            args.report, args.overwrite_report, args.startup_payload,
            args.startup_bitmap, args.startup_test_pattern, args.csv,
            args.global_contacts_test_set,
        )
        if any(verify_conflicts):
            parser.error(
                "--verify-validation-bundle cannot be combined with other "
                "options")
        _verify_validation_bundle(args.verify_validation_bundle)
        return

    if args.backup_only:
        if not args.port:
            parser.error("--backup-only requires --port")
        if args.execute:
            parser.error("--backup-only cannot be combined with --execute")
        backup_only_conflicts = (
            args.image, args.operation, args.i_have_current_backup,
            args.backup_before, args.backup_after, args.backup_dir,
            args.compare_backups, args.fail_on_backup_diff,
            args.expect_payload_sha256, args.expect_manifest, args.manifest,
            args.overwrite_manifest, args.report, args.overwrite_report,
            args.validation_bundle, args.overwrite_validation_bundle,
            args.strict_validation, args.startup_payload, args.startup_bitmap,
            args.startup_test_pattern, args.csv, args.global_contacts_test_set,
        )
        if any(backup_only_conflicts):
            parser.error(
                "--backup-only cannot be combined with writer, manifest, or "
                "comparison options")
        _backup_radio(
            args.port, args.timeout, args.backup_only,
            overwrite=args.overwrite_backup)
        return

    if not args.image:
        parser.error("--image is required unless --backup-only")
    if not args.operation:
        parser.error("--operation is required unless --backup-only")
    if args.execute and not args.port:
        parser.error("--execute requires --port")
    if args.strict_validation and not args.execute:
        parser.error("--strict-validation requires --execute")
    if args.backup_before and not args.execute:
        parser.error("--backup-before requires --execute")
    if args.backup_after and not args.execute:
        parser.error("--backup-after requires --execute")
    if args.backup_dir and not args.execute:
        parser.error("--backup-dir requires --execute")
    if args.backup_dir and (args.backup_before or args.backup_after):
        parser.error(
            "--backup-dir cannot be combined with explicit backup paths")
    if args.backup_dir:
        args.backup_before, args.backup_after = _backup_paths_from_dir(
            args.backup_dir, args.operation)
        args.compare_backups = True
    if args.overwrite_backup and not (
            args.backup_before or args.backup_after or args.backup_dir):
        parser.error(
            "--overwrite-backup requires --backup-before, --backup-after, "
            "or --backup-dir")
    if args.backup_before and args.backup_after:
        before = os.path.abspath(os.path.expanduser(args.backup_before))
        after = os.path.abspath(os.path.expanduser(args.backup_after))
        if before == after:
            parser.error("--backup-before and --backup-after must differ")
    if args.compare_backups and not (args.backup_before and args.backup_after):
        parser.error(
            "--compare-backups requires --backup-before and --backup-after")
    if args.fail_on_backup_diff and not args.compare_backups:
        parser.error("--fail-on-backup-diff requires --compare-backups")
    if args.manifest and args.execute:
        parser.error("--manifest is only valid without --execute")
    if args.overwrite_manifest and not args.manifest:
        parser.error("--overwrite-manifest requires --manifest")
    if args.validation_bundle and args.execute:
        parser.error("--validation-bundle is only valid without --execute")
    if args.overwrite_validation_bundle and not args.validation_bundle:
        parser.error(
            "--overwrite-validation-bundle requires --validation-bundle")
    if args.report and not args.execute:
        parser.error("--report requires --execute")
    if args.overwrite_report and not args.report:
        parser.error("--overwrite-report requires --report")
    if args.strict_validation:
        if not args.expect_manifest:
            parser.error("--strict-validation requires --expect-manifest")
        if not (args.backup_before and args.backup_after):
            parser.error(
                "--strict-validation requires before and after backups")
        if not args.compare_backups:
            parser.error("--strict-validation requires --compare-backups")
        if not args.fail_on_backup_diff:
            parser.error("--strict-validation requires --fail-on-backup-diff")
        if not args.report:
            parser.error("--strict-validation requires --report")
    if (args.execute and not args.i_have_current_backup and
            not args.backup_before):
        parser.error(
            "--execute requires --i-have-current-backup or --backup-before")
    if args.operation != "startup-image" and args.startup_payload:
        parser.error("--startup-payload is only valid with startup-image")
    if args.operation != "startup-image" and args.startup_bitmap:
        parser.error("--startup-bitmap is only valid with startup-image")
    if args.operation != "startup-image" and args.startup_test_pattern:
        parser.error("--startup-test-pattern is only valid with startup-image")
    startup_sources = [
        bool(args.startup_payload),
        bool(args.startup_bitmap),
        bool(args.startup_test_pattern),
    ]
    if sum(1 for enabled in startup_sources if enabled) > 1:
        parser.error(
            "--startup-payload, --startup-bitmap, and "
            "--startup-test-pattern are mutually exclusive")
    if args.operation != "global-contacts" and args.csv:
        parser.error("--csv is only valid with global-contacts")
    if args.operation != "global-contacts" and args.global_contacts_test_set:
        parser.error(
            "--global-contacts-test-set is only valid with global-contacts")
    if args.csv and args.global_contacts_test_set:
        parser.error(
            "--csv and --global-contacts-test-set are mutually exclusive")
    if args.backup_before:
        _check_backup_path(args.backup_before, overwrite=args.overwrite_backup)
    if args.backup_after:
        _check_backup_path(args.backup_after, overwrite=args.overwrite_backup)
    if args.manifest:
        _check_output_path(
            args.manifest, "Manifest", overwrite=args.overwrite_manifest)
    if args.report:
        _check_output_path(
            args.report, "Report", overwrite=args.overwrite_report)
    if args.execute and not (
            args.expect_payload_sha256 or args.expect_manifest):
        parser.error(
            "--execute requires --expect-manifest or --expect-payload-sha256")

    radio, opcode, blocks, manifest = _build_payload_from_args(args)
    checked_sha256 = _check_expected_payload_sha256(
        blocks, args.expect_payload_sha256)
    checked_manifest_sha256 = _check_expected_manifest(
        manifest, args.expect_manifest)
    if args.execute:
        started_at = _utc_timestamp()
        if checked_sha256:
            print("Payload SHA-256 verified: %s" % checked_sha256)
        if checked_manifest_sha256:
            print("Manifest payload verified: %s" % checked_manifest_sha256)
        if args.backup_before:
            _backup_before_execute(
                args.port, args.timeout, args.backup_before,
                overwrite=args.overwrite_backup)
        _execute(radio, args.operation, args.port, args.timeout, blocks)
        if args.backup_after:
            _backup_after_execute(
                args.port, args.timeout, args.backup_after,
                overwrite=args.overwrite_backup)
        backup_differences = None
        if args.compare_backups:
            backup_differences = _compare_backup_images(
                args.backup_before, args.backup_after,
                fail_on_diff=args.fail_on_backup_diff)
        finished_at = _utc_timestamp()
        if args.report:
            _write_report(
                args.report,
                _execute_report(
                    args, manifest, checked_sha256, checked_manifest_sha256,
                    started_at, finished_at, backup_differences),
                overwrite=args.overwrite_report)
    else:
        _print_dry_run(radio, args.operation, opcode, blocks, args)
        if checked_sha256:
            print("expected payload sha256: matched")
        if checked_manifest_sha256:
            print("expected manifest: matched")
        if args.manifest:
            _write_manifest(
                args.manifest, manifest, overwrite=args.overwrite_manifest)
        if args.validation_bundle:
            _write_validation_bundle(args, manifest)


if __name__ == "__main__":
    try:
        main()
    except errors.RadioError as exc:
        _die("ERROR: %s" % exc)
