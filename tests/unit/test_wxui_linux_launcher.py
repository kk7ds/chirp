import os
from pathlib import Path
import sys
from unittest import mock

# Snapshot sys.modules before mocking so it can be restored exactly,
# immediately below, once this file's own imports are done with it --
# see the restore block after the imports for why both the snapshot
# and the immediate (not fixture-based) timing are needed.
_PRE_MOCK_SYS_MODULES = dict(sys.modules)


def _evict_chirp_wxui_modules():
    """Remove every already-imported chirp.wxui.* submodule (and the
    parent package's attribute reference to it -- see the restore
    block below for why that second part matters) so that whatever
    imports chirp.wxui submodules next -- our own mock installation
    below, or a real one after it -- gets a fresh import rather than
    reusing a module cached from however wx looked the last time it
    was genuinely imported.

    This runs twice: once here, before our own mocking, in case an
    earlier-collected test file already imported chirp.wxui.common
    (etc.) for real, which would otherwise make this file's own tests
    exercise the real wx.MessageDialog instead of our mock; and once
    after our own imports, to avoid leaving *our* fake-wx-built
    modules cached for a later-collected file that needs the real
    thing (e.g. tests/unit/test_wxui_programming_assistant.py).
    Confirmed by direct reproduction that both directions are
    necessary: running this file before a real-wx test file fails
    without the after-case, and running it after one fails without
    this before-case.
    """
    for name in list(sys.modules):
        if name != 'chirp.wxui' and not name.startswith('chirp.wxui.'):
            continue
        if name == 'chirp.wxui':
            # Never evict the bare package itself -- see the restore
            # block below for why.
            continue
        del sys.modules[name]
        parent_name, _, attr = name.rpartition('.')
        parent = sys.modules.get(parent_name)
        if parent is not None:
            vars(parent).pop(attr, None)


_evict_chirp_wxui_modules()

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

# Restore sys.modules immediately -- synchronously, still as part of
# this file's own collection -- rather than via a pytest fixture.
# pytest fully COLLECTS (imports) every test file before it EXECUTES
# any test; a fixture's teardown only runs during that later execution
# phase, which is already too late to help another test file whose
# own top-level import (e.g. `from chirp.wxui import memedit`) runs
# during ITS collection, potentially before this module's tests ever
# execute. This mirrors test_wxui_recentfiles.py's stash/restore
# pattern, extended to cover every sys.modules entry this file's
# mocking and imports touch, not just 'wx' itself:
#
# Restoring sys.modules['wx'] alone is not enough. Importing
# chirp.wxui.linux_launcher above also transitively imports
# chirp.wxui.common, and chirp.wxui.common defines classes
# (ChirpEditor, ChirpSyncEditor) that subclass real wx types. Since
# that import happens while sys.modules['wx'] is still our MagicMock,
# those classes get built against the *fake* wx and stay cached in
# sys.modules that way -- putting the real 'wx' back afterward does
# not retroactively fix a class object that already exists. Any test
# file collected later in the same pytest session that triggers a
# fresh `from chirp.wxui import memedit` (which also subclasses
# common.ChirpEditor/ChirpSyncEditor) hits "TypeError: metaclass
# conflict" as a result, since chirp.wxui.common never gets
# re-imported with the real wx once it's cached this way. Confirmed by
# direct reproduction that restoring only sys.modules['wx'] still
# reproduces that conflict, and that this broader restore does not.
#
# This evicts every 'wx'/'wx.*' and 'chirp.wxui.*' (submodules only --
# not the bare 'chirp.wxui' package itself, see below) entry that is
# new since this file started, restoring the ones that already existed
# to their prior value, so the next real import of any of them
# re-executes from scratch against the real wx.
#
# The bare 'chirp.wxui' package (chirp/wxui/__init__.py) is
# deliberately excluded: unlike its submodules, it defines no wx-based
# classes at import time -- maybe_install_desktop() does `import wx`
# lazily, inside the function body, so it always resolves
# sys.modules['wx'] fresh at call time regardless of caching. Evicting
# it anyway was tried and confirmed harmful: it forces a second,
# later, non-idempotent import of chirp/wxui/__init__.py, which raises
# wx._core.PyNoAppError deep inside test_wxui_radiothread.py's
# TestStartup tests (no real wx.App exists in this headless test
# environment).
#
# Safe for this file's own tests: chirp.wxui.linux_launcher and
# chirp.linux_desktop both only `import wx` at module scope (captured
# once, at this file's own import time) -- never lazily inside a
# function body -- so nothing in this file's own tests re-resolves
# sys.modules['wx'] later, after this restore has already run.
#
# Removing a submodule from sys.modules is not sufficient on its own:
# `from chirp.wxui import common` first checks whether the chirp.wxui
# *package* object already has a `common` attribute, and uses that
# directly without consulting sys.modules at all if so -- Python sets
# that attribute automatically as a side effect of the first import,
# the same way `import chirp.wxui.common` also makes `common`
# accessible as `chirp.wxui.common`. Since chirp.wxui itself is
# deliberately kept (not evicted, per above), it keeps that stale
# attribute pointing at the fake-wx-built submodule even after the
# submodule's own sys.modules entry is removed, which reproduces the
# exact same metaclass conflict one level further down the import
# chain (chirp/wxui/developer.py, imported by memedit.py, doing its
# own `from chirp.wxui import common`). Confirmed by direct
# reproduction. So each evicted chirp.wxui.* submodule's attribute
# must also be cleared from its parent package object -- and likewise
# fixed up (not just left as whatever this file's own imports left
# behind) on the restore path.
#
# The set of names to consider is the *union* of what's in
# _PRE_MOCK_SYS_MODULES and what's in sys.modules now, not just
# whichever of the two is convenient to iterate: something present
# before but evicted by _evict_chirp_wxui_modules() above and never
# reimported by this file's own `from chirp.wxui import
# linux_launcher` chain (e.g. chirp.wxui.programming_assistant, when
# this file runs after a real-wx test module that imported it) would
# otherwise never be considered at all, silently staying evicted
# forever instead of being restored. Confirmed by direct reproduction
# that iterating only `sys.modules` misses exactly this case.
_affected = {n for n in set(_PRE_MOCK_SYS_MODULES) | set(sys.modules)
             if n == 'wx' or n.startswith('wx.') or
             n.startswith('chirp.wxui.')}
for _name in _affected:
    _parent_name, _, _attr = _name.rpartition('.')
    _parent = sys.modules.get(_parent_name)
    if _name in _PRE_MOCK_SYS_MODULES:
        sys.modules[_name] = _PRE_MOCK_SYS_MODULES[_name]
        if _parent is not None:
            setattr(_parent, _attr, _PRE_MOCK_SYS_MODULES[_name])
    else:
        sys.modules.pop(_name, None)
        if _parent is not None:
            vars(_parent).pop(_attr, None)


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
