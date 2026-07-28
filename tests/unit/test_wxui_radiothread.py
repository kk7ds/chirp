import os
import sys
import time
from unittest import mock

import ddt

# Snapshot sys.modules before mocking, so it can be restored exactly,
# immediately below, once this file's own collection-time imports
# (clone.py, radiothread.py) are done with it. See the restore block
# after the imports, and TestStartup.setUp() further down, for why
# this needs to be a two-part fix rather than a single restore.
_PRE_MOCK_SYS_MODULES = dict(sys.modules)


def _evict_chirp_wxui_modules():
    """Remove every already-imported chirp.wxui.* submodule (and the
    parent package's attribute reference to it) so that whatever
    imports chirp.wxui submodules next gets a fresh import rather than
    reusing a module cached from however wx looked the last time it
    was genuinely imported. See test_wxui_linux_launcher.py, which
    has the identical helper (and the identical underlying problem)
    with a more detailed explanation of why both the sys.modules
    removal and the parent-attribute cleanup are needed."""
    for name in list(sys.modules):
        if name != 'chirp.wxui' and not name.startswith('chirp.wxui.'):
            continue
        if name == 'chirp.wxui':
            continue
        del sys.modules[name]
        parent_name, _, attr = name.rpartition('.')
        parent = sys.modules.get(parent_name)
        if parent is not None:
            vars(parent).pop(attr, None)


_evict_chirp_wxui_modules()

sys.modules['wx'] = wx = mock.MagicMock()
sys.modules['wx.lib'] = mock.MagicMock()
sys.modules['wx.lib.scrolledpanel'] = mock.MagicMock()
sys.modules['wx.lib.sized_controls'] = mock.MagicMock()
sys.modules['wx.richtext'] = mock.MagicMock()
wx.lib.newevent.NewCommandEvent.return_value = None, None
sys.modules['chirp.wxui.developer'] = mock.MagicMock()

# These need to be imported after the above mock so that we don't require
# wx to be present for these tests
from tests.unit import base  # noqa
from chirp import chirp_common  # noqa
from chirp import directory  # noqa
from chirp.wxui import clone  # noqa
from chirp.wxui import config  # noqa
from chirp.wxui import radiothread  # noqa

# Restore sys.modules immediately -- synchronously, still as part of
# this file's own collection -- for the same reason and via the same
# mechanism as test_wxui_linux_launcher.py: pytest fully collects
# every test file before executing any test, so restoring only once
# this file's own tests finish executing (e.g. via a pytest fixture)
# is too late to stop a later-collected real-wx test file (like
# test_wxui_programming_assistant.py) from seeing this mock during
# *its* collection.
#
# clone.py and radiothread.py (the modules under test for
# TestRadioThread/TestClone below) both only `import wx` at module
# scope, captured once at this file's own import time, so restoring
# immediately is safe for those two classes' own tests. TestStartup is
# the exception -- see its setUp() below, which re-installs a scoped
# copy of this same mock for exactly that class's own tests, instead
# of relying on it staying installed globally for the rest of the
# session the way this file used to leave it.
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


class TestRadioThread(base.BaseTest):
    def setUp(self):
        super().setUp()

    def test_radiojob(self):
        radio = mock.MagicMock()
        editor = mock.MagicMock()
        job = radiothread.RadioJob(editor, 'get_memory', [12], {})
        self.assertIsNone(job.dispatch(radio))
        radio.get_memory.assert_called_once_with(12)
        self.assertEqual(job.result, radio.get_memory.return_value)

    def test_radiojob_exception(self):
        radio = mock.MagicMock()
        radio.get_memory.side_effect = ValueError('some error')
        editor = mock.MagicMock()
        job = radiothread.RadioJob(editor, 'get_memory', [12], {})
        self.assertIsNone(job.dispatch(radio))
        radio.get_memory.assert_called_once_with(12)
        self.assertIsInstance(job.result, ValueError)

    def test_thread(self):
        radio = mock.MagicMock()
        radio.get_features.side_effect = ValueError('some error')
        editor = mock.MagicMock()
        # Simulate an edit conflict with the first event by returning
        # False for "delivered" to force us to queue an event.
        editor.radio_thread_event.side_effect = [False, True, True, True]
        thread = radiothread.RadioThread(radio)
        mem = mock.MagicMock()
        job1id = thread.submit(editor, 'get_memory', 12)
        job2id = thread.submit(editor, 'set_memory', mem)
        job3id = thread.submit(editor, 'get_features')
        # We have to start the thread after we submit the main jobs so
        # the order is stable for comparison.
        thread.start()

        # Wait for the main jobs to be processed before we signal exit
        while not all([radio.get_memory.called,
                       radio.set_memory.called,
                       radio.get_features.called]):
            time.sleep(0.1)

        thread.end()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        radio.get_memory.assert_called_once_with(12)
        radio.set_memory.assert_called_once_with(mem)
        radio.get_features.assert_called_once_with()
        self.assertEqual(4, editor.radio_thread_event.call_count)

        # We expect the jobs to be delivered in order of
        # priority. Since we return False for the first call to
        # radio_thread_event(), job2 should be queued and then
        # delivered first on the next cycle.
        expected_order = [job2id, job2id, job3id, job1id]
        for i, (jobid, call) in enumerate(
                zip(expected_order,
                    editor.radio_thread_event.call_args_list)):
            job = call[0][0]
            self.assertEqual(jobid, job.id)

        # We should call non-blocking for every call except the last
        # one, when the queue is empty
        editor.radio_thread_event.assert_has_calls([
            mock.call(mock.ANY, block=False),
            mock.call(mock.ANY, block=False),
            mock.call(mock.ANY, block=False),
            mock.call(mock.ANY, block=True),
        ])

    def test_thread_abort_priority(self):
        radio = mock.MagicMock()
        radio.get_features.side_effect = ValueError('some error')
        editor = mock.MagicMock()
        thread = radiothread.RadioThread(radio)
        mem = mock.MagicMock()
        thread.submit(editor, 'get_memory', 12)
        thread.submit(editor, 'set_memory', mem)
        thread.submit(editor, 'get_features')
        thread.end()
        # We have to start the thread after we submit the main jobs so
        # the order is stable for comparison.
        thread.start()

        thread.join(5)
        self.assertFalse(thread.is_alive())

        # Our end sentinel should have gone to the head of the queue
        # so that exiting the application does not leave a thread
        # running in the background fetching hundreds of memories.
        radio.get_memory.assert_not_called()
        radio.set_memory.assert_not_called()
        radio.get_features.assert_not_called()
        wx.PostEvent.assert_not_called()


class TestClone(base.BaseTest):
    @mock.patch('platform.system', return_value='Linux')
    def test_sort_ports_unix(self, system):
        ports = [
            mock.MagicMock(device='/dev/cu.zed',
                           description='My Zed'),
            mock.MagicMock(device='/dev/cu.abc',
                           description='Some device'),
            mock.MagicMock(device='/dev/cu.serial',
                           description='')
            ]
        self.assertEqual(
            ['Some device (cu.abc)',
             'cu.serial',
             'My Zed (cu.zed)'],
            [clone.port_label(p)
                for p in sorted(ports, key=clone.port_sort_key)])

    @mock.patch('platform.system', return_value='Windows')
    def test_sort_ports_windows(self, system):
        ports = [
            mock.MagicMock(device='COM7',
                           description='Some serial device'),
            mock.MagicMock(device='COM17',
                           description='Some other device'),
            mock.MagicMock(device='CNC0',
                           description='Some weird device'),
            mock.MagicMock(device='COM4',
                           description=''),
            ]
        self.assertEqual(
            ['CNC0: Some weird device',
             'COM4',
             'COM7: Some serial device',
             'COM17: Some other device'],
            [clone.port_label(p)
                for p in sorted(ports, key=clone.port_sort_key)])

    def test_detected_model_labels(self):
        # Make sure all our detected model labels will be reasonable
        # (and nonzero) in length. If the full label is too long, it will not
        # be visible in the model box.
        for rclass in [x for x in directory.DRV_TO_RADIO.values()
                       if issubclass(x, chirp_common.DetectableInterface)]:
            label = clone.get_model_label(rclass)
            self.assertLessEqual(len(label), 32,
                                 'Label %r is too long' % label)


class TestException(Exception):
    pass


@ddt.ddt
class TestStartup(base.BaseTest):
    def setUp(self):
        super().setUp()
        # maybe_install_desktop() (chirp/wxui/__init__.py) does a
        # lazy `import wx` inside its own function body, resolved
        # fresh every call -- unlike this file's own collection-time
        # imports (clone.py etc.), which only ever needed the
        # module-level mock during collection, and have already been
        # restored by the module-level cleanup above. Re-install the
        # *same* wx mock object this file's own module-level `wx`
        # variable refers to (so the wx.MessageBox.assert_*() calls
        # below, which check that same object, keep working), scoped
        # to just this test -- not left mocked globally for the rest
        # of the session the way this file used to.
        #
        # Deliberately not mock.patch.dict(sys.modules, {'wx': wx}):
        # confirmed by direct reproduction that using it here, even
        # though it is a no-op in terms of the *value* sys.modules['wx']
        # ends up holding, makes some later test in this class trip
        # pytest's own assertion-rewrite import hook into calling
        # os.path.normcase() on a real path while os.path is
        # separately mocked below, raising
        # "TypeError: expected string or bytes-like object, got
        # 'MagicMock'" resolving importlib.resources.files('chirp.
        # share') -- a mock.patch.dict-specific interaction with
        # pytest/importlib's own caching, unrelated to wx isolation.
        # Plain manual save/restore does not trigger it.
        self._prior_wx = sys.modules.get('wx')
        sys.modules['wx'] = wx
        self.addCleanup(self._restore_wx_module)
        self.use(mock.patch('os.path'))
        self.use(mock.patch('os.makedirs'))
        self.use(mock.patch('chirp.wxui.CONF'))
        self.args = mock.MagicMock()
        self.args.install_desktop_app = False
        self.args.no_install_desktop_app = False
        from chirp.wxui import maybe_install_desktop, CONF
        self.maybe_install_desktop = maybe_install_desktop
        self.conf = CONF

    def _restore_wx_module(self):
        if self._prior_wx is not None:
            sys.modules['wx'] = self._prior_wx
        else:
            sys.modules.pop('wx', None)

    @ddt.data(
        # No arguments, no file, no previous, answer no
        [False, False, False, False, False],
        # No arguments, no file, no previous, answer yes
        [False, False, False, False, True],
        # No arguments, no file, previous yes, no prompt
        [False, False, False, True, None],
        # No arguments, exists, previous no, no prompt
        [False, False, True, False, None],
        # Opt out, no file, no prompt
        [False, True, False, None, None],
        # Opt in, no file, previous yes, still prompt
        [True, False, False, True, True],
        # Opt in, exists, previous no, no prompt'),
        [True, False, True, False, None],
    )
    @ddt.unpack
    def test_linux_desktop_file(self, optin, optout, exists, last, answ):
        self.args.install_desktop_app = optin
        self.args.no_install_desktop_app = optout
        os.path.exists.return_value = exists
        self.conf.get_bool.return_value = last
        wx.MessageBox.return_value = wx.YES if answ else wx.NO
        os.makedirs.side_effect = TestException
        wx.MessageBox.reset_mock()

        if answ is True:
            # If we made it through all the checks, and thus prompted the user,
            # make sure we get to the makedirs part if expected
            self.assertRaises(TestException,
                              self.maybe_install_desktop, self.args, None)
        elif answ is False:
            # If we were supposed to make it to the prompt but answer no,
            # make sure we did
            self.maybe_install_desktop(self.args, None)
            self.assertFalse(os.makedirs.called)
            self.assertTrue(wx.MessageBox.called)
        else:
            # If we were not supposed to make it to the prompt, make sure we
            # didn't, nor did we do any create actions
            self.maybe_install_desktop(self.args, None)
            self.assertFalse(os.makedirs.called)
            self.assertFalse(wx.MessageBox.called)

    def test_linux_desktop_file_exists(self):
        os.path.exists.return_value = True
        self.maybe_install_desktop(self.args, None)
        self.assertFalse(os.makedirs.called)
