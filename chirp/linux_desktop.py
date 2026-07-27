# Copyright 2026 CHIRP Development Team
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

"""Linux desktop-integration helpers for running as an AppImage.

This module contains platform-detection, permission, and file-generation
logic used to install a freedesktop application-menu entry and/or desktop
icon that points back at the currently-running CHIRP AppImage. It has no
dependency on wx and is safe to import (though most of it is a no-op or
unused) on any platform, so it must never be imported at module scope by
code that also needs to run on Windows or macOS.
"""

import dataclasses
import filecmp
from importlib import resources
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import typing

if typing.TYPE_CHECKING:
    # `_` is installed into builtins at wx-app startup (see
    # chirp.wxui.builtins._ = wx.GetTranslation); declare its type here
    # only for the type checker's benefit -- this has no effect at
    # runtime.
    _: typing.Callable[[str], str]

LOG = logging.getLogger(__name__)

#: Filename used for both the application-menu and desktop-icon copies
#: of the generated launcher. Kept stable so re-running installation
#: always finds (and can safely update) the same file.
DESKTOP_FILE_NAME = 'chirp-appimage.desktop'

#: freedesktop icon name we install into the user's hicolor icon theme
#: and reference from the generated .desktop file's Icon= key.
ICON_NAME = 'chirp'

#: Size (in pixels, square) of the bundled chirp.png source icon.
ICON_SOURCE_SIZE = 256

# Custom (X-prefixed) keys written into generated .desktop files so we
# can recognize our own launchers on a later run, and know which
# AppImage they currently point at, without having to parse the
# (deliberately quoted/escaped) Exec= value back apart.
_MANAGED_KEY = 'X-CHIRP-Managed'
_APPIMAGE_PATH_KEY = 'X-CHIRP-AppImagePath'

_USER_DIRS_LINE_RE = re.compile(r'^\s*([A-Z_]+)\s*=\s*"(.*)"\s*$')

# Characters that require an Exec= argument to be quoted, per the
# Desktop Entry Specification's "Exec variables" quoting rules.
_EXEC_RESERVED_CHARS = set(' \t\n"\'\\`$><|;&()#*?[]!{}^~')
# Of those, only these four need backslash-escaping once inside quotes.
_EXEC_ESCAPE_CHARS = set('"`$\\')


class LinuxDesktopError(Exception):
    """Raised when a desktop-integration operation cannot be completed."""


def is_supported_platform() -> bool:
    """Return whether this feature is applicable on the current OS."""
    return sys.platform == 'linux'


def detect_appimage_path() -> typing.Optional[Path]:
    """Return the resolved path to the running AppImage, if any.

    Relies on the ``APPIMAGE`` environment variable that the AppImage
    runtime sets for every process it launches, rather than guessing
    from the executable name. Returns None if it is not set, i.e. CHIRP
    is not currently running from an AppImage.
    """
    raw = os.environ.get('APPIMAGE')
    if not raw:
        return None
    try:
        # Resolve through any symlinks so every later check (existence,
        # file-type, permission) and the Exec= line we generate all
        # agree on the same real, canonical file.
        return Path(raw).resolve(strict=False)
    except (OSError, RuntimeError) as e:
        LOG.warning('Failed to resolve AppImage path %r: %s', raw, e)
        return None


@dataclasses.dataclass
class AppImageStatus:
    """A point-in-time snapshot of the detected AppImage's state."""

    path: typing.Optional[Path]
    exists: bool = False
    is_file: bool = False
    is_executable: bool = False

    @property
    def usable(self) -> bool:
        """Whether a launcher can be built for this AppImage right now."""
        return self.path is not None and self.exists and self.is_file


def get_appimage_status() -> AppImageStatus:
    """Detect the running AppImage and inspect its file state."""
    path = detect_appimage_path()
    if path is None:
        return AppImageStatus(path=None)
    return inspect_appimage(path)


def inspect_appimage(path: Path) -> AppImageStatus:
    """Inspect an already-detected AppImage @path."""
    try:
        st = path.stat()
    except OSError:
        return AppImageStatus(path=path, exists=False)

    is_file = stat.S_ISREG(st.st_mode)
    is_executable = is_file and os.access(path, os.X_OK)
    return AppImageStatus(path=path, exists=True, is_file=is_file,
                          is_executable=is_executable)


def grant_execute_permission(path: Path) -> AppImageStatus:
    """Add the owner-execute bit to @path, preserving all other bits.

    Never touches group/other write bits, never widens permissions
    beyond adding S_IXUSR, and never shells out to chmod(1) or sudo.
    """
    try:
        st = path.stat()
    except OSError as e:
        raise LinuxDesktopError(
            _('Unable to read %(path)s: %(error)s') % {
                'path': path, 'error': e}) from e

    if not stat.S_ISREG(st.st_mode):
        raise LinuxDesktopError(
            _('%s is not a regular file') % path)

    try:
        os.chmod(path, st.st_mode | stat.S_IXUSR)
    except OSError as e:
        raise LinuxDesktopError(
            _('Failed to set execute permission on %(path)s: '
              '%(error)s') % {'path': path, 'error': e}) from e

    return inspect_appimage(path)


def _xdg_data_home() -> Path:
    value = os.environ.get('XDG_DATA_HOME')
    if value:
        return Path(value)
    return Path.home() / '.local' / 'share'


def applications_dir() -> Path:
    """Return the per-user freedesktop application-menu directory."""
    return _xdg_data_home() / 'applications'


def icon_theme_dir(size: int = ICON_SOURCE_SIZE) -> Path:
    """Return the per-user hicolor icon theme directory for @size."""
    return (_xdg_data_home() / 'icons' / 'hicolor' /
            ('%dx%d' % (size, size)) / 'apps')


def _read_user_dirs_value(user_dirs_file: Path,
                          key: str) -> typing.Optional[str]:
    try:
        content = user_dirs_file.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None

    for line in content.splitlines():
        m = _USER_DIRS_LINE_RE.match(line)
        if not m or m.group(1) != key:
            continue
        home = str(Path.home())
        return m.group(2).replace('$HOME', home).replace('${HOME}', home)
    return None


def desktop_dir() -> typing.Optional[Path]:
    """Return the user's Desktop directory, or None if undeterminable.

    Prefers ``XDG_DESKTOP_DIR`` (the environment variable, then the
    ``user-dirs.dirs`` config file it's normally set from), and only
    falls back to a plain ``~/Desktop`` if that directory already
    exists -- this function never invents a new desktop directory that
    isn't already configured or present.
    """
    xdg_desktop = os.environ.get('XDG_DESKTOP_DIR')
    if xdg_desktop:
        home = str(Path.home())
        xdg_desktop = xdg_desktop.replace('$HOME', home).replace(
            '${HOME}', home)
        return Path(xdg_desktop).expanduser()

    config_home = os.environ.get('XDG_CONFIG_HOME')
    if config_home:
        user_dirs_file = Path(config_home) / 'user-dirs.dirs'
    else:
        user_dirs_file = Path.home() / '.config' / 'user-dirs.dirs'

    value = _read_user_dirs_value(user_dirs_file, 'XDG_DESKTOP_DIR')
    if value:
        return Path(value).expanduser()

    fallback = Path.home() / 'Desktop'
    if fallback.is_dir():
        return fallback

    return None


def _quote_exec_argument(value: str) -> str:
    """Quote/escape a single Exec= argument per the Desktop Entry Spec.

    Field codes (e.g. %f, %U) are never generated here, so any literal
    percent sign is always escaped to %% first. The result is a value
    that desktop environments parse directly into an argv list -- no
    shell is ever invoked, so this cannot enable command injection.
    """
    value = value.replace('%', '%%')
    if not any(c in _EXEC_RESERVED_CHARS for c in value):
        return value
    escaped = ''.join(
        ('\\' + c) if c in _EXEC_ESCAPE_CHARS else c for c in value)
    return '"%s"' % escaped


def _check_no_newlines(value: str, what: str) -> None:
    if '\n' in value or '\r' in value:
        raise LinuxDesktopError(
            _('%s must not contain line breaks') % what)


def build_desktop_entry(appimage_path: Path,
                        icon_name: str = ICON_NAME) -> str:
    """Build the contents of a .desktop file that launches @appimage_path."""
    raw_path = str(appimage_path)
    _check_no_newlines(raw_path, _('AppImage path'))
    _check_no_newlines(icon_name, _('Icon name'))

    lines = [
        '[Desktop Entry]',
        'Type=Application',
        'Version=1.0',
        'Name=CHIRP',
        'GenericName=Radio Programming Tool',
        'Comment=Program amateur radios',
        'Exec=%s' % _quote_exec_argument(raw_path),
        'Icon=%s' % icon_name,
        'Terminal=false',
        'Categories=Utility;HamRadio;',
        'StartupNotify=true',
        '%s=true' % _MANAGED_KEY,
        '%s=%s' % (_APPIMAGE_PATH_KEY, raw_path),
    ]
    return '\n'.join(lines) + '\n'


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix='.%s.' % path.name, suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _is_chirp_managed(path: Path) -> bool:
    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    marker = '%s=true' % _MANAGED_KEY
    return any(line.strip() == marker for line in content.splitlines())


def _write_managed_desktop_file(target: Path, content: str,
                                mode: int) -> str:
    """Write @content to @target, refusing to clobber unrelated files.

    Returns 'installed', 'updated', or 'unchanged'. Raises
    LinuxDesktopError (never a bare OSError) on any failure.
    """
    if target.exists():
        if not _is_chirp_managed(target):
            raise LinuxDesktopError(
                _('%s already exists and was not created by CHIRP; '
                  'refusing to overwrite it') % target)
        try:
            existing = target.read_text(encoding='utf-8')
        except OSError:
            existing = None
        if existing == content:
            return 'unchanged'
        status = 'updated'
    else:
        status = 'installed'

    try:
        _atomic_write(target, content, mode)
    except OSError as e:
        raise LinuxDesktopError(
            _('Failed to write %(path)s: %(error)s') % {
                'path': target, 'error': e}) from e

    return status


def install_icon(size: int = ICON_SOURCE_SIZE) -> Path:
    """Copy CHIRP's bundled icon into the per-user hicolor theme.

    Idempotent: if the destination already matches the bundled source
    byte-for-byte, no write is performed.
    """
    dest = icon_theme_dir(size) / ('%s.png' % ICON_NAME)

    with resources.as_file(
            resources.files('chirp.share').joinpath('chirp.png')) as src:
        if dest.exists():
            try:
                if filecmp.cmp(str(src), str(dest), shallow=False):
                    return dest
            except OSError:
                pass

        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix='.%s.' % dest.name, suffix='.tmp', dir=str(dest.parent))
        try:
            with os.fdopen(fd, 'wb') as out_f, open(src, 'rb') as in_f:
                shutil.copyfileobj(in_f, out_f)
                out_f.flush()
                os.fsync(out_f.fileno())
            os.chmod(tmp_name, 0o644)
            os.replace(tmp_name, dest)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    return dest


def install_application_menu_launcher(
        appimage_path: Path,
        icon_name: str = ICON_NAME) -> typing.Tuple[Path, str]:
    """Install/update CHIRP's launcher in the per-user application menu.

    Returns (path, status) where status is 'installed', 'updated', or
    'unchanged'. Raises LinuxDesktopError if the target path exists and
    was not created by CHIRP.
    """
    target = applications_dir() / DESKTOP_FILE_NAME
    content = build_desktop_entry(appimage_path, icon_name)
    status = _write_managed_desktop_file(target, content, 0o644)
    return target, status


def install_desktop_launcher(
        appimage_path: Path,
        icon_name: str = ICON_NAME
        ) -> typing.Tuple[typing.Optional[Path], str]:
    """Install/update a desktop-icon launcher for CHIRP.

    Returns (path, status) where status is 'installed', 'updated',
    'unchanged', or 'unsupported' (path is None) if no Desktop
    directory could be safely determined. Raises LinuxDesktopError if
    the target path exists and was not created by CHIRP.
    """
    ddir = desktop_dir()
    if ddir is None or not ddir.is_dir():
        return None, 'unsupported'

    target = ddir / DESKTOP_FILE_NAME
    content = build_desktop_entry(appimage_path, icon_name)
    # Desktop-icon launchers additionally need the executable bit set
    # for most desktop environments (GNOME, Xfce, Cinnamon...) to be
    # willing to run them via double-click at all; some (notably
    # GNOME/Nautilus) additionally require the user to mark the file as
    # trusted, which is out of scope here -- see the caller for the
    # associated user-facing explanation.
    status = _write_managed_desktop_file(target, content, 0o755)
    return target, status


def validate_desktop_file(path: Path) -> typing.Optional[str]:
    """Run desktop-file-validate on @path if it's installed.

    Returns None if the tool is unavailable or reports no problems, or
    its combined output if it reports problems. Never fatal.
    """
    tool = shutil.which('desktop-file-validate')
    if not tool:
        return None
    try:
        proc = subprocess.run(
            [tool, str(path)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        LOG.warning('Failed to run desktop-file-validate: %s', e)
        return None
    if proc.returncode == 0:
        return None
    return (proc.stdout + proc.stderr).strip() or None


def refresh_desktop_database(applications_directory: Path) -> None:
    """Run update-desktop-database on @applications_directory if present.

    A best-effort convenience only; failure or absence is never fatal
    and the feature never depends on this having run.
    """
    tool = shutil.which('update-desktop-database')
    if not tool:
        return
    try:
        subprocess.run([tool, str(applications_directory)],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        LOG.warning('update-desktop-database failed (nonfatal): %s', e)


@dataclasses.dataclass
class LauncherInstallOutcome:
    """Structured result of an install_launchers() call."""

    icon_path: typing.Optional[Path] = None
    menu: typing.Optional[typing.Tuple[Path, str]] = None
    desktop: typing.Optional[typing.Tuple[typing.Optional[Path], str]] = None
    validation_warning: typing.Optional[str] = None
    errors: typing.List[str] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def install_launchers(appimage_path: Path, *, install_menu: bool,
                      install_desktop_icon: bool) -> LauncherInstallOutcome:
    """Install the requested launcher(s) for @appimage_path.

    Pure orchestration over the functions above; installs the icon
    once, then each requested launcher target independently so that,
    e.g., an unsupported desktop-icon environment doesn't prevent the
    application-menu install from succeeding.
    """
    outcome = LauncherInstallOutcome()

    icon_name = ICON_NAME
    try:
        outcome.icon_path = install_icon()
    except OSError as e:
        LOG.warning('Failed to install icon, falling back to icon name '
                    'lookup: %s', e)

    if install_menu:
        try:
            outcome.menu = install_application_menu_launcher(
                appimage_path, icon_name)
        except LinuxDesktopError as e:
            outcome.errors.append(str(e))

    if install_desktop_icon:
        try:
            outcome.desktop = install_desktop_launcher(
                appimage_path, icon_name)
        except LinuxDesktopError as e:
            outcome.errors.append(str(e))

    validated_path = None
    if outcome.menu and outcome.menu[1] != 'unchanged':
        validated_path = outcome.menu[0]
    elif (outcome.desktop and outcome.desktop[0] and
          outcome.desktop[1] != 'unchanged'):
        validated_path = outcome.desktop[0]

    if validated_path:
        outcome.validation_warning = validate_desktop_file(validated_path)
        refresh_desktop_database(applications_dir())

    return outcome
