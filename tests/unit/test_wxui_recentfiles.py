import sys
import tempfile
from unittest import mock

# Stash/restore rather than leaving our mock in sys.modules['wx']: some
# modules (chirp.wxui's own maybe_install_desktop) do `import wx` inside
# a function body rather than at module scope, so they re-resolve
# sys.modules['wx'] on every call. If our mock were still installed as
# the *last* one written to sys.modules once test collection finishes,
# it would silently become the one those functions see everywhere, not
# just in this file's own tests -- e.g. breaking
# tests/unit/test_wxui_radiothread.py, which relies on its own mock
# still being current at that point.
_real_wx = sys.modules.get('wx')
sys.modules['wx'] = wx = mock.MagicMock()

from tests.unit import base  # noqa
from chirp.wxui import config  # noqa
from chirp.wxui import recentfiles  # noqa

if _real_wx is not None:
    sys.modules['wx'] = _real_wx
else:
    sys.modules.pop('wx', None)


class RecentFilesConfigTest(base.BaseTest):
    def setUp(self):
        super().setUp()
        tmpdir = tempfile.mkdtemp()
        config._CONFIG = config.ChirpConfig(tmpdir)
        self.conf = config.get()

    def test_load_empty(self):
        self.assertEqual([], recentfiles.load(self.conf))

    def test_add_single(self):
        recent = recentfiles.add(self.conf, '/a/one.img')
        self.assertEqual(['/a/one.img'], recent)
        self.assertEqual(['/a/one.img'], recentfiles.load(self.conf))

    def test_add_multiple_most_recent_first(self):
        recentfiles.add(self.conf, '/a/one.img')
        recentfiles.add(self.conf, '/a/two.img')
        recentfiles.add(self.conf, '/a/three.img')
        self.assertEqual(
            ['/a/three.img', '/a/two.img', '/a/one.img'],
            recentfiles.load(self.conf))

    def test_add_dedup_moves_existing_to_front(self):
        recentfiles.add(self.conf, '/a/one.img')
        recentfiles.add(self.conf, '/a/two.img')
        recent = recentfiles.add(self.conf, '/a/one.img')
        self.assertEqual(['/a/one.img', '/a/two.img'], recent)

    def test_add_respects_keep_limit(self):
        for i in range(5):
            recentfiles.add(self.conf, '/a/%i.img' % i, keep=3)
        recent = recentfiles.load(self.conf, keep=3)
        self.assertEqual(['/a/4.img', '/a/3.img', '/a/2.img'], recent)

    def test_add_prunes_config_entries_beyond_keep(self):
        for i in range(5):
            recentfiles.add(self.conf, '/a/%i.img' % i, keep=3)
        for i in range(3, 8):
            self.assertFalse(
                self.conf.is_defined('recent%i' % i, 'state'),
                'recent%i should have been pruned' % i)

    def test_remove_single(self):
        recentfiles.add(self.conf, '/a/one.img')
        recentfiles.add(self.conf, '/a/two.img')
        recent = recentfiles.remove(self.conf, ['/a/one.img'])
        self.assertEqual(['/a/two.img'], recent)
        self.assertEqual(['/a/two.img'], recentfiles.load(self.conf))

    def test_remove_multiple(self):
        recentfiles.add(self.conf, '/a/one.img')
        recentfiles.add(self.conf, '/a/two.img')
        recentfiles.add(self.conf, '/a/three.img')
        recent = recentfiles.remove(
            self.conf, ['/a/one.img', '/a/three.img'])
        self.assertEqual(['/a/two.img'], recent)

    def test_remove_nonexistent_is_noop(self):
        recentfiles.add(self.conf, '/a/one.img')
        recent = recentfiles.remove(self.conf, ['/a/missing.img'])
        self.assertEqual(['/a/one.img'], recent)

    def test_remove_prunes_config_entries(self):
        recentfiles.add(self.conf, '/a/one.img')
        recentfiles.add(self.conf, '/a/two.img')
        recentfiles.remove(self.conf, ['/a/one.img', '/a/two.img'])
        self.assertEqual([], recentfiles.load(self.conf))
        self.assertFalse(self.conf.is_defined('recent0', 'state'))

    def test_clear(self):
        recentfiles.add(self.conf, '/a/one.img')
        recentfiles.add(self.conf, '/a/two.img')
        recent = recentfiles.clear(self.conf)
        self.assertEqual([], recent)
        self.assertEqual([], recentfiles.load(self.conf))
        self.assertFalse(self.conf.is_defined('recent0', 'state'))

    def test_clear_empty_is_safe(self):
        self.assertEqual([], recentfiles.clear(self.conf))


class MenuWiringSourceTest(base.BaseTest):
    """Verifies the Remove/Clear Recent Files items are wired up, by
    inspecting main.py's actual source.

    ChirpMain has too many GUI/radio-driver dependencies to practically
    instantiate in a unit test, so this checks the real source of
    adj_menu_open_recent() that runs in production rather than a
    reimplementation of it.
    """

    def _adj_menu_open_recent_source(self):
        import os

        import chirp
        main_path = os.path.join(
            os.path.dirname(chirp.__file__), 'wxui', 'main.py')
        with open(main_path, encoding='utf-8') as f:
            content = f.read()
        start = content.index('def adj_menu_open_recent(self, filename):')
        end = content.index('\n    def ', start + 1)
        return content[start:end]

    def test_remove_item_bound_to_handler(self):
        source = self._adj_menu_open_recent_source()
        self.assertIn("_('Remove from Recent Files...')", source)
        self.assertIn('_menu_open_recent_remove', source)

    def test_clear_item_bound_to_handler(self):
        source = self._adj_menu_open_recent_source()
        self.assertIn("_('Clear Recent Files')", source)
        self.assertIn('_menu_open_recent_clear', source)

    def test_items_only_added_when_recent_nonempty(self):
        source = self._adj_menu_open_recent_source()
        # Both new items must be inside the `if recent:` guard, not
        # unconditionally appended every rebuild.
        guard_idx = source.index('if recent:')
        remove_idx = source.index("_('Remove from Recent Files...')")
        clear_idx = source.index("_('Clear Recent Files')")
        self.assertLess(guard_idx, remove_idx)
        self.assertLess(guard_idx, clear_idx)
