import os
from pathlib import Path
import sys
from unittest import mock

sys.modules['wx'] = wx = mock.MagicMock()
sys.modules['wx.adv'] = mock.MagicMock()
sys.modules['wx.aui'] = mock.MagicMock()
sys.modules['wx.lib'] = mock.MagicMock()
sys.modules['wx.lib.newevent'] = mock.MagicMock()
sys.modules['wx.richtext'] = mock.MagicMock()
wx.lib.newevent.NewCommandEvent.return_value = None, None
wx.GetTranslation = lambda s: s
sys.modules['chirp.wxui.developer'] = mock.MagicMock()

# Real, OR-able wx constants (a plain MagicMock attribute can't be
# combined with `|`, which the module under test relies on).
wx.YES_NO = 1 << 0
wx.YES = 1 << 1
wx.NO = 1 << 2
wx.OK = 1 << 3
wx.CANCEL = 1 << 4
wx.ICON_INFORMATION = 1 << 5
wx.ICON_WARNING = 1 << 6
wx.ICON_ERROR = 1 << 7
wx.ID_OK = 1 << 8
wx.ID_CANCEL = 1 << 9

# These need to be imported after the wx mock is installed so that we
# don't require wx to be present for these tests.
from tests.unit import base  # noqa
import chirp  # noqa
from chirp import linux_desktop  # noqa
from chirp.wxui import linux_launcher  # noqa


class DoInstallLinuxLauncherTest(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.parent = mock.MagicMock()
        wx.reset_mock()

    def test_noop_on_unsupported_platform(self):
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=False), \
                mock.patch.object(linux_desktop,
                                  'get_appimage_status') as status:
            linux_launcher.do_install_linux_launcher(self.parent, None)
        status.assert_not_called()
        wx.MessageBox.assert_not_called()

    def test_not_an_appimage_shows_info_and_does_nothing(self):
        not_appimage = linux_desktop.AppImageStatus(path=None)
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=True), \
                mock.patch.object(linux_desktop, 'get_appimage_status',
                                  return_value=not_appimage), \
                mock.patch.object(linux_desktop,
                                  'install_launchers') as install:
            linux_launcher.do_install_linux_launcher(self.parent, None)
        install.assert_not_called()
        wx.MessageBox.assert_called_once()

    def test_missing_appimage_file_shows_error(self):
        status = linux_desktop.AppImageStatus(
            path=Path('/opt/gone.AppImage'), exists=False)
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=True), \
                mock.patch.object(linux_desktop, 'get_appimage_status',
                                  return_value=status), \
                mock.patch.object(linux_desktop,
                                  'install_launchers') as install:
            linux_launcher.do_install_linux_launcher(self.parent, None)
        install.assert_not_called()
        wx.MessageBox.assert_called_once()

    def test_not_executable_declined_repair_does_nothing(self):
        status = linux_desktop.AppImageStatus(
            path=Path('/opt/c.AppImage'), exists=True, is_file=True,
            is_executable=False)
        wx.MessageBox.return_value = wx.NO
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=True), \
                mock.patch.object(linux_desktop, 'get_appimage_status',
                                  return_value=status), \
                mock.patch.object(
                    linux_desktop, 'grant_execute_permission') as grant, \
                mock.patch.object(linux_desktop,
                                  'install_launchers') as install:
            linux_launcher.do_install_linux_launcher(self.parent, None)
        grant.assert_not_called()
        install.assert_not_called()

    def test_not_executable_approved_repair_then_dialog_cancelled(self):
        status = linux_desktop.AppImageStatus(
            path=Path('/opt/c.AppImage'), exists=True, is_file=True,
            is_executable=False)
        fixed_status = linux_desktop.AppImageStatus(
            path=status.path, exists=True, is_file=True, is_executable=True)
        wx.MessageBox.return_value = wx.YES
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=True), \
                mock.patch.object(linux_desktop, 'get_appimage_status',
                                  return_value=status), \
                mock.patch.object(linux_desktop, 'grant_execute_permission',
                                  return_value=fixed_status) as grant, \
                mock.patch.object(linux_launcher, 'LinuxLauncherDialog') \
                as dialog_cls, \
                mock.patch.object(linux_desktop,
                                  'install_launchers') as install:
            dialog = dialog_cls.return_value
            dialog.ShowModal.return_value = wx.ID_CANCEL
            linux_launcher.do_install_linux_launcher(self.parent, None)
        grant.assert_called_once_with(status.path)
        dialog.Destroy.assert_called_once()
        # Cancel means: no files created, no launchers installed.
        install.assert_not_called()

    def test_repair_failure_aborts_before_dialog(self):
        status = linux_desktop.AppImageStatus(
            path=Path('/opt/c.AppImage'), exists=True, is_file=True,
            is_executable=False)
        wx.MessageBox.return_value = wx.YES
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=True), \
                mock.patch.object(linux_desktop, 'get_appimage_status',
                                  return_value=status), \
                mock.patch.object(
                    linux_desktop, 'grant_execute_permission',
                    side_effect=linux_desktop.LinuxDesktopError('nope')), \
                mock.patch.object(linux_launcher, 'LinuxLauncherDialog') \
                as dialog_cls, \
                mock.patch.object(linux_desktop,
                                  'install_launchers') as install:
            linux_launcher.do_install_linux_launcher(self.parent, None)
        dialog_cls.assert_not_called()
        install.assert_not_called()

    def test_confirmed_dialog_invokes_install_with_selected_targets(self):
        status = linux_desktop.AppImageStatus(
            path=Path('/opt/c.AppImage'), exists=True, is_file=True,
            is_executable=True)
        outcome = linux_desktop.LauncherInstallOutcome(
            menu=(Path('/x/chirp-appimage.desktop'), 'installed'))
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=True), \
                mock.patch.object(linux_desktop, 'get_appimage_status',
                                  return_value=status), \
                mock.patch.object(linux_launcher, 'LinuxLauncherDialog') \
                as dialog_cls, \
                mock.patch.object(linux_desktop, 'install_launchers',
                                  return_value=outcome) as install:
            dialog = dialog_cls.return_value
            dialog.ShowModal.return_value = wx.ID_OK
            dialog.install_menu = True
            dialog.install_desktop_icon = False
            linux_launcher.do_install_linux_launcher(self.parent, None)
        install.assert_called_once_with(
            status.path, install_menu=True, install_desktop_icon=False)
        dialog.Destroy.assert_called_once()

    def test_confirmed_dialog_with_neither_checkbox_skips_install(self):
        status = linux_desktop.AppImageStatus(
            path=Path('/opt/c.AppImage'), exists=True, is_file=True,
            is_executable=True)
        with mock.patch.object(linux_desktop, 'is_supported_platform',
                               return_value=True), \
                mock.patch.object(linux_desktop, 'get_appimage_status',
                                  return_value=status), \
                mock.patch.object(linux_launcher, 'LinuxLauncherDialog') \
                as dialog_cls, \
                mock.patch.object(linux_desktop,
                                  'install_launchers') as install:
            dialog = dialog_cls.return_value
            dialog.ShowModal.return_value = wx.ID_OK
            dialog.install_menu = False
            dialog.install_desktop_icon = False
            linux_launcher.do_install_linux_launcher(self.parent, None)
        install.assert_not_called()


class ReportOutcomeTest(base.BaseTest):
    def setUp(self):
        super().setUp()
        wx.reset_mock()

    def _style_flags(self):
        args, kwargs = wx.MessageBox.call_args
        return args[2]

    def test_success_shows_information(self):
        outcome = linux_desktop.LauncherInstallOutcome(
            menu=(Path('/x/chirp-appimage.desktop'), 'installed'))
        linux_launcher._report_outcome(mock.MagicMock(), outcome)
        self.assertTrue(self._style_flags() & wx.ICON_INFORMATION)

    def test_errors_show_error_dialog(self):
        outcome = linux_desktop.LauncherInstallOutcome(
            errors=['could not write file'])
        linux_launcher._report_outcome(mock.MagicMock(), outcome)
        self.assertTrue(self._style_flags() & wx.ICON_ERROR)

    def test_validation_warning_shows_warning_dialog(self):
        outcome = linux_desktop.LauncherInstallOutcome(
            menu=(Path('/x/chirp-appimage.desktop'), 'installed'),
            validation_warning='hint: missing MimeType')
        linux_launcher._report_outcome(mock.MagicMock(), outcome)
        self.assertTrue(self._style_flags() & wx.ICON_WARNING)


class MenuWiringSourceTest(base.BaseTest):
    """Verifies the Help-menu item is gated to Linux and correctly
    bound, by inspecting the actual make_menubar() source.

    ChirpMain.make_menubar() has too many GUI/radio-driver
    dependencies to practically instantiate in a unit test, so this
    checks the real source of the method that runs in production
    rather than a reimplementation of it.
    """

    def _make_menubar_source(self):
        # Read main.py's source directly rather than importing it: the
        # module pulls in the full wxui dependency chain (bankedit,
        # clone, memedit, ...), which isn't practical to mock out just
        # to inspect one method's text.
        main_path = os.path.join(
            os.path.dirname(chirp.__file__), 'wxui', 'main.py')
        with open(main_path, encoding='utf-8') as f:
            content = f.read()
        start = content.index('def make_menubar(self):')
        end = content.index('\n    def ', start + 1)
        return content[start:end]

    def test_menu_item_gated_to_linux(self):
        source = self._make_menubar_source()
        self.assertIn("sys.platform == 'linux'", source)
        # The Linux-only block containing our item must be the one that
        # binds it, not just present anywhere else in the method.
        idx = source.index("_('Install Linux Launcher...')")
        gate_idx = source.rindex("if sys.platform == 'linux':", 0, idx)
        bind_idx = source.index('do_install_linux_launcher', idx)
        self.assertLess(gate_idx, idx)
        self.assertLess(idx, bind_idx)

    def test_menu_item_bound_to_handler(self):
        source = self._make_menubar_source()
        self.assertIn(
            'linux_launcher.do_install_linux_launcher', source)
        self.assertIn('help_menu.Append(linux_launcher_menu)', source)
