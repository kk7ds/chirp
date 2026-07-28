"""Regression coverage for the wx sys.modules isolation defect fixed
in test_wxui_linux_launcher.py and test_wxui_radiothread.py.

Both of those files mock sys.modules['wx'] (and related entries) at
module import time, to let their own tests run without a real wx
installation. The defect: importing either of them also transitively
imports chirp.wxui.common, which subclasses real wx types --
producing classes built against whichever wx (real or fake) happened
to be in sys.modules at that moment, cached under chirp.wxui.common's
own sys.modules entry (and as an attribute of the chirp.wxui package
object) for the rest of the process. Any test file collected
afterward that triggers a fresh `from chirp.wxui import memedit`
(chirp/wxui/memedit.py:1021 defines `class ChirpMemEdit(common.
ChirpEditor, common.ChirpSyncEditor)`) inherited whatever was cached,
including a fake one -- raising "TypeError: metaclass conflict" if
chirp.wxui.common was left built against a MagicMock.

This can only be verified across process/collection boundaries -- the
underlying bug is entirely about what state a *separate* test file's
module-level code leaves in sys.modules for whichever file pytest
collects next, which isn't observable from calls made within a single
already-running test. Each test here launches a fresh, isolated
pytest subprocess with a specific combination and ordering of test
files (mirroring the exact CI invocation: `pytest tests/unit -k "not
network"`, scoped down to just the files relevant to this defect) and
asserts it exits 0 with no collection errors.
"""

import os
import subprocess
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class WxModuleIsolationRegressionTest(unittest.TestCase):
    def _run_pytest(self, *relative_test_paths):
        env = dict(os.environ)
        env['CHIRP_TESTENV'] = '1'
        env['PYTHONPATH'] = _REPO_ROOT
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', *relative_test_paths],
            cwd=_REPO_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=120)
        return result

    def _assert_clean_pass(self, result, context):
        self.assertEqual(
            0, result.returncode,
            '%s: expected a clean pytest run (exit 0), got %i:\n%s' % (
                context, result.returncode, result.stdout))
        self.assertNotIn('metaclass conflict', result.stdout, context)
        self.assertNotIn('ERROR collecting', result.stdout, context)

    def test_linux_launcher_individually(self):
        result = self._run_pytest('tests/unit/test_wxui_linux_launcher.py')
        self._assert_clean_pass(result, 'linux_launcher alone')

    def test_radiothread_individually(self):
        result = self._run_pytest('tests/unit/test_wxui_radiothread.py')
        self._assert_clean_pass(result, 'radiothread alone')

    def test_linux_launcher_then_real_memedit_import_succeeds(self):
        # A stand-in for "a real-wx test file collected after
        # linux_launcher.py, that imports chirp.wxui.memedit" --
        # chirp.wxui.memedit is production code, present regardless of
        # whether any particular feature's own test file exists on
        # this branch, so this doesn't depend on one.
        result = self._run_pytest(
            'tests/unit/test_wxui_linux_launcher.py', '-p', 'no:cacheprovider',
            '--co')
        self._assert_clean_pass(result, 'linux_launcher collect-only')
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys\n'
             'import tests.unit.test_wxui_linux_launcher\n'
             'from chirp.wxui import memedit\n'
             'assert "MagicMock" not in repr(type(memedit.common.'
             'ChirpEditor)), memedit.common.ChirpEditor\n'
             'sys.stdout.write("OK\\n")'],
            cwd=_REPO_ROOT,
            env=dict(os.environ, CHIRP_TESTENV='1', PYTHONPATH=_REPO_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=60)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn('OK', result.stdout)

    def test_real_memedit_import_then_linux_launcher_succeeds(self):
        # The reverse order: a real-wx module imported first, then
        # linux_launcher.py collected afterward -- confirmed to be a
        # distinct failure mode from the forward order (linux_launcher.
        # py's own tests broke, exercising the real wx.MessageDialog,
        # if chirp.wxui.common was already cached for real).
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys\n'
             'from chirp.wxui import memedit\n'
             'import tests.unit.test_wxui_linux_launcher\n'
             'sys.stdout.write("OK\\n")'],
            cwd=_REPO_ROOT,
            env=dict(os.environ, CHIRP_TESTENV='1', PYTHONPATH=_REPO_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=60)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn('OK', result.stdout)

        result = self._run_pytest('tests/unit/test_wxui_linux_launcher.py')
        self._assert_clean_pass(
            result, 'linux_launcher after a real chirp.wxui.memedit import')

    def test_radiothread_then_linux_launcher_then_real_memedit_import(self):
        # The exact three-file combination and order from the original
        # report: test_wxui_radiothread.py (the older, previously-
        # accepted pre-existing pollution source) collected first,
        # then test_wxui_linux_launcher.py, then a real-wx import.
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys\n'
             'import tests.unit.test_wxui_radiothread\n'
             'import tests.unit.test_wxui_linux_launcher\n'
             'from chirp.wxui import memedit\n'
             'assert "MagicMock" not in repr(type(memedit.common.'
             'ChirpEditor)), memedit.common.ChirpEditor\n'
             'sys.stdout.write("OK\\n")'],
            cwd=_REPO_ROOT,
            env=dict(os.environ, CHIRP_TESTENV='1', PYTHONPATH=_REPO_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=60)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn('OK', result.stdout)

        result = self._run_pytest(
            'tests/unit/test_wxui_radiothread.py',
            'tests/unit/test_wxui_linux_launcher.py')
        self._assert_clean_pass(result, 'radiothread + linux_launcher, run')

    def test_radiothread_and_linux_launcher_together_both_orders(self):
        result = self._run_pytest(
            'tests/unit/test_wxui_radiothread.py',
            'tests/unit/test_wxui_linux_launcher.py')
        self._assert_clean_pass(result, 'radiothread, then linux_launcher')

        result = self._run_pytest(
            'tests/unit/test_wxui_linux_launcher.py',
            'tests/unit/test_wxui_radiothread.py')
        self._assert_clean_pass(result, 'linux_launcher, then radiothread')

    def test_relevant_files_pass_together_with_full_directory_deselection(
            self):
        # A lighter-weight proxy for "passes as part of the full
        # `pytest tests/unit -k not network` collection": collecting
        # the whole tests/unit directory (so every other file's own
        # module-level imports run too, in their normal relative
        # order) but only *running* the files relevant to this
        # defect, via -k, keeps this fast while still exercising the
        # real, full collection order the CI job uses.
        result = self._run_pytest(
            'tests/unit', '-k',
            'TestStartup or DoInstallLinuxLauncherTest or '
            'ReportOutcomeTest or MenuWiringSourceTest')
        self._assert_clean_pass(result, 'full tests/unit collection order')
