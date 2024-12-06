import sys
from unittest import mock

from chirp import chirp_common
import lark
from tests.unit import base

sys.modules['wx'] = wx = mock.MagicMock()
sys.modules['wx.adv'] = wx = mock.MagicMock()

from chirp.wxui import memquery  # noqa


class TestMemquery(base.BaseTest):
    def _get_sample_memories(self):
        mems = []
        freqs = (118, 145, 146, 440, 800)
        for i, freq in enumerate(freqs):
            mem = chirp_common.Memory(1 + i, name="mem%s" % freq)
            mem.freq = freq * 1000000
            mem.mode = "FM"
            mems.append(mem)
        return mems

    def test_query_parse(self):
        query = ('name="foo" OR name IN ["mem800", "baz"] OR '
                 '(mode="FM" AND freq<144,147.1>) OR '
                 'name~"7$"')
        parser = lark.Lark(memquery.LANG)
        transformer = memquery.Interpreter(self._get_sample_memories())
        filtered = transformer.transform(parser.parse(query)).children[0]
        self.assertEqual(3, len(filtered), filtered)
        self.assertEqual([145, 146, 800],
                         sorted([x.freq // 1000000 for x in filtered]))
