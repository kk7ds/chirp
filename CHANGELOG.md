# Changelog

Releases of this fork's AppImage builds are tagged `appimage-vX.Y.Z` and
follow [Semantic Versioning](https://semver.org/):

- **X** (major) — breaking changes (e.g. dropped platform support, an
  incompatible config format change)
- **Y** (minor) — new features, added in a backwards-compatible way
- **Z** (patch) — bug fixes, with no new functionality

Every release is published as a [GitHub Release](../../releases) with a
downloadable `CHIRP-*-x86_64.AppImage` asset, built automatically by
[`.github/workflows/appimage.yml`](.github/workflows/appimage.yml).

## [Unreleased]

## [1.6.0] - 2026-07-27

### Changed

- Adopted semantic versioning for releases (this file, going forward).
  Earlier releases (`appimage-v1` through `appimage-v6`) used a plain
  incrementing counter with no distinction between features, fixes, or
  docs-only changes; see below for what each of those actually shipped.

## Pre-semver releases

These used a plain incrementing `appimage-vN` counter, kept here for
reference.

### appimage-v6 - 2026-07-26

- **Added**: Right-click "Insert Rows Above..." now prompts for how many
  rows to insert, instead of always inserting exactly one. The whole batch
  is one undo step.
- **Fixed**: an intermediate version of the above silently dropped memories
  when inserting more than one row, due to a stale-cache bug; caught and
  fixed before release.

### appimage-v5 - 2026-07-26

- **Fixed**: the AppImage no longer inherits settings (notably Help >
  Developer Mode, and the "Browser"/"Info" tabs it unlocks) from another
  CHIRP install's shared `~/.chirp` config directory. It now defaults to
  its own isolated `~/.chirp-appimage`, overridable with `--config-dir`.

### appimage-v4 - 2026-07-26

- **Fixed** (unconfirmed): attempted fix for a reported row-label/grid
  misalignment in the memory list on some Linux hosts, by forcing a
  repaint after populating rows. Could not be reproduced in testing, so
  this fix's effectiveness is unverified.

### appimage-v3 - 2026-07-26

- **Fixed**: crash (`'PropertyGrid' object has no attribute
  'EnableScrolling'`) opening the Radio Info tab (developer mode only),
  caused by an older wxWidgets version than the code assumed.

### appimage-v2 - 2026-07-26

- **Changed**: documented the AppImage packaging effort in the README. No
  functional changes.

### appimage-v1 - 2026-07-26

- Initial AppImage build. Deleted as a test release once appimage-v2
  superseded it.
