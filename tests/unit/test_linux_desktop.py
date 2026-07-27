import os
import stat
from pathlib import Path
import tempfile
from unittest import mock

from tests.unit import base
from chirp import linux_desktop


def _write(path, content='data', mode=0o644):
    path.write_text(content)
    os.chmod(path, mode)
    return path


class TmpHomeTest(base.BaseTest):
    """Base class that isolates HOME/XDG dirs to a throwaway tempdir.

    No test in this file (or subclasses) may write to the real user's
    home directory, ~/.local/share/applications, ~/Desktop, or
    ~/.local/share/icons.
    """

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / 'home'
        self.home.mkdir()
        self.data_home = self.home / '.local' / 'share'
        self.env_patch = mock.patch.dict(os.environ, {
            'HOME': str(self.home),
            'XDG_DATA_HOME': str(self.data_home),
        }, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)


class AppImageDetectionTest(TmpHomeTest):
    def test_valid_appimage_env(self):
        appimage = _write(self.home / 'CHIRP.AppImage', mode=0o755)
        with mock.patch.dict(os.environ, {'APPIMAGE': str(appimage)}):
            self.assertEqual(appimage, linux_desktop.detect_appimage_path())

    def test_missing_appimage_env(self):
        os.environ.pop('APPIMAGE', None)
        self.assertIsNone(linux_desktop.detect_appimage_path())

    def test_empty_appimage_env(self):
        with mock.patch.dict(os.environ, {'APPIMAGE': ''}):
            self.assertIsNone(linux_desktop.detect_appimage_path())

    def test_nonexistent_appimage_path(self):
        missing = self.home / 'gone.AppImage'
        with mock.patch.dict(os.environ, {'APPIMAGE': str(missing)}):
            status = linux_desktop.get_appimage_status()
        self.assertEqual(missing, status.path)
        self.assertFalse(status.exists)
        self.assertFalse(status.usable)

    def test_non_appimage_linux_execution(self):
        os.environ.pop('APPIMAGE', None)
        status = linux_desktop.get_appimage_status()
        self.assertIsNone(status.path)
        self.assertFalse(status.usable)

    def test_path_with_spaces(self):
        d = self.home / 'has spaces here'
        d.mkdir()
        appimage = _write(d / 'CHIRP App.AppImage', mode=0o755)
        with mock.patch.dict(os.environ, {'APPIMAGE': str(appimage)}):
            status = linux_desktop.get_appimage_status()
        self.assertTrue(status.usable)
        self.assertTrue(status.is_executable)

    def test_unicode_path(self):
        d = self.home / '日本語'
        d.mkdir()
        appimage = _write(d / 'CHIRP-éè.AppImage', mode=0o755)
        with mock.patch.dict(os.environ, {'APPIMAGE': str(appimage)}):
            status = linux_desktop.get_appimage_status()
        self.assertTrue(status.usable)

    def test_symlink_resolves_to_real_target(self):
        real = _write(self.home / 'real.AppImage', mode=0o755)
        link = self.home / 'CHIRP.AppImage'
        link.symlink_to(real)
        with mock.patch.dict(os.environ, {'APPIMAGE': str(link)}):
            detected = linux_desktop.detect_appimage_path()
        self.assertEqual(real.resolve(), detected)


class PermissionsTest(TmpHomeTest):
    def test_already_executable(self):
        appimage = _write(self.home / 'a.AppImage', mode=0o755)
        status = linux_desktop.inspect_appimage(appimage)
        self.assertTrue(status.is_executable)

    def test_not_executable(self):
        appimage = _write(self.home / 'a.AppImage', mode=0o644)
        status = linux_desktop.inspect_appimage(appimage)
        self.assertTrue(status.exists)
        self.assertTrue(status.is_file)
        self.assertFalse(status.is_executable)

    def test_missing_file(self):
        status = linux_desktop.inspect_appimage(self.home / 'nope')
        self.assertFalse(status.exists)
        self.assertFalse(status.is_executable)

    def test_grant_execute_permission_adds_bit_preserves_others(self):
        appimage = _write(self.home / 'a.AppImage', mode=0o640)
        status = linux_desktop.grant_execute_permission(appimage)
        self.assertTrue(status.is_executable)
        mode = appimage.stat().st_mode & 0o777
        self.assertEqual(0o740, mode)

    def test_grant_execute_permission_never_world_writable(self):
        appimage = _write(self.home / 'a.AppImage', mode=0o644)
        linux_desktop.grant_execute_permission(appimage)
        mode = appimage.stat().st_mode & 0o777
        self.assertEqual(0, mode & stat.S_IWOTH)

    def test_grant_execute_permission_missing_file(self):
        self.assertRaises(
            linux_desktop.LinuxDesktopError,
            linux_desktop.grant_execute_permission, self.home / 'nope')

    def test_grant_execute_permission_not_regular_file(self):
        self.assertRaises(
            linux_desktop.LinuxDesktopError,
            linux_desktop.grant_execute_permission, self.home)

    def test_grant_execute_permission_chmod_failure(self):
        appimage = _write(self.home / 'a.AppImage', mode=0o644)
        with mock.patch('os.chmod', side_effect=PermissionError('nope')):
            self.assertRaises(
                linux_desktop.LinuxDesktopError,
                linux_desktop.grant_execute_permission, appimage)
        # Original permissions untouched by the failed attempt.
        self.assertEqual(0o644, appimage.stat().st_mode & 0o777)

    def test_grant_execute_permission_readonly_fs(self):
        appimage = _write(self.home / 'a.AppImage', mode=0o644)
        with mock.patch('os.chmod',
                        side_effect=OSError(30, 'Read-only file system')):
            self.assertRaises(
                linux_desktop.LinuxDesktopError,
                linux_desktop.grant_execute_permission, appimage)

    def test_symlink_permission_policy_targets_real_file(self):
        real = _write(self.home / 'real.AppImage', mode=0o644)
        link = self.home / 'link.AppImage'
        link.symlink_to(real)
        linux_desktop.grant_execute_permission(link)
        self.assertTrue(os.access(real, os.X_OK))


class DesktopEntryGenerationTest(base.BaseTest):
    def test_required_fields(self):
        content = linux_desktop.build_desktop_entry(
            Path('/opt/chirp.AppImage'))
        self.assertIn('[Desktop Entry]', content)
        self.assertIn('Type=Application', content)
        self.assertIn('Name=CHIRP', content)
        self.assertIn('Terminal=false', content)
        self.assertIn('StartupNotify=true', content)

    def test_uses_absolute_path(self):
        p = Path('/opt/radio/chirp.AppImage')
        content = linux_desktop.build_desktop_entry(p)
        self.assertIn('Exec=%s' % p, content)
        self.assertIn('X-CHIRP-AppImagePath=%s' % p, content)

    def test_stable_icon_reference(self):
        content = linux_desktop.build_desktop_entry(Path('/opt/c.AppImage'))
        self.assertIn('Icon=chirp', content)
        # Never an absolute (and thus stale-after-unmount) path.
        self.assertNotIn('Icon=/', content)

    def test_categories(self):
        content = linux_desktop.build_desktop_entry(Path('/opt/c.AppImage'))
        self.assertIn('Categories=Utility;HamRadio;', content)

    def test_managed_marker_present(self):
        content = linux_desktop.build_desktop_entry(Path('/opt/c.AppImage'))
        self.assertIn('X-CHIRP-Managed=true', content)

    def _exec_value(self, content):
        for line in content.splitlines():
            if line.startswith('Exec='):
                return line[len('Exec='):]
        raise AssertionError('No Exec= line found')

    def _unquote_exec(self, value):
        """Mirror the Desktop Entry Spec's unquoting rules for a single
        argument, for round-trip verification in tests."""
        value = value.replace('%%', '%')
        if not (value.startswith('"') and value.endswith('"')):
            return value
        inner = value[1:-1]
        out = []
        i = 0
        while i < len(inner):
            c = inner[i]
            if c == '\\' and i + 1 < len(inner) and \
                    inner[i + 1] in '"`$\\':
                out.append(inner[i + 1])
                i += 2
            else:
                out.append(c)
                i += 1
        return ''.join(out)

    def test_escaping_spaces_round_trips(self):
        p = Path('/opt/My Radio Folder/chirp.AppImage')
        content = linux_desktop.build_desktop_entry(p)
        exec_value = self._exec_value(content)
        self.assertTrue(exec_value.startswith('"'))
        self.assertEqual(str(p), self._unquote_exec(exec_value))

    def test_escaping_quotes_and_backslashes_round_trips(self):
        p = Path('/opt/weird "quote" \\ dir/chirp.AppImage')
        content = linux_desktop.build_desktop_entry(p)
        exec_value = self._exec_value(content)
        self.assertEqual(str(p), self._unquote_exec(exec_value))

    def test_percent_char_escaped(self):
        p = Path('/opt/100%-radio/chirp.AppImage')
        content = linux_desktop.build_desktop_entry(p)
        exec_value = self._exec_value(content)
        self.assertIn('%%', exec_value)
        self.assertEqual(str(p), self._unquote_exec(exec_value))

    def test_unicode_path_round_trips(self):
        p = Path('/opt/日本語/chirpé.AppImage')
        content = linux_desktop.build_desktop_entry(p)
        exec_value = self._exec_value(content)
        self.assertEqual(str(p), self._unquote_exec(exec_value))

    def test_no_newline_injection(self):
        p = Path('/opt/evil\nNewKey=malicious/chirp.AppImage')
        self.assertRaises(
            linux_desktop.LinuxDesktopError,
            linux_desktop.build_desktop_entry, p)

    def test_simple_path_not_quoted(self):
        p = Path('/opt/chirp/chirp.AppImage')
        content = linux_desktop.build_desktop_entry(p)
        exec_value = self._exec_value(content)
        self.assertEqual(str(p), exec_value)


class DesktopDirResolutionTest(TmpHomeTest):
    def test_xdg_desktop_dir_env(self):
        target = self.home / 'MyDesktop'
        target.mkdir()
        with mock.patch.dict(os.environ,
                             {'XDG_DESKTOP_DIR': str(target)}):
            self.assertEqual(target, linux_desktop.desktop_dir())

    def test_user_dirs_dot_dirs_file(self):
        cfg_dir = self.home / '.config'
        cfg_dir.mkdir()
        desktop = self.home / 'Desktop'
        (cfg_dir / 'user-dirs.dirs').write_text(
            'XDG_DESKTOP_DIR="$HOME/Desktop"\n')
        self.assertEqual(desktop, linux_desktop.desktop_dir())

    def test_fallback_to_home_desktop_if_exists(self):
        (self.home / 'Desktop').mkdir()
        self.assertEqual(self.home / 'Desktop', linux_desktop.desktop_dir())

    def test_none_when_undeterminable(self):
        self.assertIsNone(linux_desktop.desktop_dir())


class InstallationTest(TmpHomeTest):
    def setUp(self):
        super().setUp()
        self.appimage = _write(self.home / 'CHIRP.AppImage', mode=0o755)
        self.desktop = self.home / 'Desktop'
        self.desktop.mkdir()
        self.env_patch2 = mock.patch.dict(os.environ, {
            'XDG_DESKTOP_DIR': str(self.desktop),
        })
        self.env_patch2.start()
        self.addCleanup(self.env_patch2.stop)

    def test_creates_application_menu_launcher(self):
        path, status = linux_desktop.install_application_menu_launcher(
            self.appimage)
        self.assertEqual('installed', status)
        self.assertEqual(
            self.data_home / 'applications' / 'chirp-appimage.desktop',
            path)
        self.assertTrue(path.exists())
        self.assertIn(str(self.appimage), path.read_text())

    def test_creates_desktop_launcher(self):
        path, status = linux_desktop.install_desktop_launcher(self.appimage)
        self.assertEqual('installed', status)
        self.assertEqual(self.desktop / 'chirp-appimage.desktop', path)
        self.assertTrue(os.access(path, os.X_OK))

    def test_desktop_launcher_unsupported_without_desktop_dir(self):
        self.env_patch2.stop()
        os.environ.pop('XDG_DESKTOP_DIR', None)
        (self.home / 'Desktop').rmdir()
        path, status = linux_desktop.install_desktop_launcher(self.appimage)
        self.assertIsNone(path)
        self.assertEqual('unsupported', status)

    def test_install_both(self):
        outcome = linux_desktop.install_launchers(
            self.appimage, install_menu=True, install_desktop_icon=True)
        self.assertTrue(outcome.ok)
        self.assertEqual('installed', outcome.menu[1])
        self.assertEqual('installed', outcome.desktop[1])
        self.assertTrue(outcome.icon_path.exists())

    def test_install_only_menu(self):
        outcome = linux_desktop.install_launchers(
            self.appimage, install_menu=True, install_desktop_icon=False)
        self.assertIsNotNone(outcome.menu)
        self.assertIsNone(outcome.desktop)

    def test_install_only_desktop(self):
        outcome = linux_desktop.install_launchers(
            self.appimage, install_menu=False, install_desktop_icon=True)
        self.assertIsNone(outcome.menu)
        self.assertIsNotNone(outcome.desktop)

    def test_existing_managed_launcher_is_updated(self):
        linux_desktop.install_application_menu_launcher(self.appimage)
        moved = self.home / 'moved.AppImage'
        self.appimage.rename(moved)
        os.chmod(moved, 0o755)
        path, status = linux_desktop.install_application_menu_launcher(
            moved)
        self.assertEqual('updated', status)
        self.assertIn(str(moved), path.read_text())

    def test_existing_unrelated_file_not_overwritten(self):
        target = self.data_home / 'applications' / 'chirp-appimage.desktop'
        target.parent.mkdir(parents=True)
        target.write_text('[Desktop Entry]\nName=NotChirp\n')
        self.assertRaises(
            linux_desktop.LinuxDesktopError,
            linux_desktop.install_application_menu_launcher, self.appimage)
        self.assertEqual('[Desktop Entry]\nName=NotChirp\n',
                         target.read_text())

    def test_repeated_installation_is_idempotent(self):
        linux_desktop.install_application_menu_launcher(self.appimage)
        path, status = linux_desktop.install_application_menu_launcher(
            self.appimage)
        self.assertEqual('unchanged', status)
        path2, status2 = linux_desktop.install_application_menu_launcher(
            self.appimage)
        self.assertEqual('unchanged', status2)

    def test_atomic_write_failure_is_handled(self):
        with mock.patch('os.replace', side_effect=OSError('disk full')):
            self.assertRaises(
                linux_desktop.LinuxDesktopError,
                linux_desktop.install_application_menu_launcher,
                self.appimage)
        # No leftover temp files after the failed attempt.
        apps_dir = self.data_home / 'applications'
        leftovers = list(apps_dir.glob('*.tmp')) if apps_dir.exists() else []
        self.assertEqual([], leftovers)

    def test_icon_copy_behavior(self):
        icon_path = linux_desktop.install_icon()
        self.assertTrue(icon_path.exists())
        self.assertEqual(
            self.data_home / 'icons' / 'hicolor' / '256x256' / 'apps' /
            'chirp.png', icon_path)

    def test_icon_copy_is_idempotent(self):
        first = linux_desktop.install_icon()
        first_mtime = first.stat().st_mtime_ns
        second = linux_desktop.install_icon()
        self.assertEqual(first, second)
        self.assertEqual(first_mtime, second.stat().st_mtime_ns)

    def test_missing_optional_validation_tools(self):
        with mock.patch('shutil.which', return_value=None):
            self.assertIsNone(
                linux_desktop.validate_desktop_file(self.appimage))
            # Must not raise even though the tool is unavailable.
            linux_desktop.refresh_desktop_database(self.data_home)

    def test_validate_desktop_file_reports_problems(self):
        fake_proc = mock.Mock(returncode=1, stdout='error: bad key\n',
                              stderr='')
        with mock.patch('shutil.which', return_value='/usr/bin/'
                        'desktop-file-validate'), \
                mock.patch('subprocess.run', return_value=fake_proc):
            result = linux_desktop.validate_desktop_file(self.appimage)
        self.assertIn('bad key', result)


class PlatformGateTest(base.BaseTest):
    def test_is_supported_platform_linux(self):
        with mock.patch('sys.platform', 'linux'):
            self.assertTrue(linux_desktop.is_supported_platform())

    def test_is_supported_platform_windows(self):
        with mock.patch('sys.platform', 'win32'):
            self.assertFalse(linux_desktop.is_supported_platform())

    def test_is_supported_platform_macos(self):
        with mock.patch('sys.platform', 'darwin'):
            self.assertFalse(linux_desktop.is_supported_platform())
