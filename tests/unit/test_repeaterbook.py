import tempfile
import unittest
from unittest import mock
import requests

from chirp import chirp_common
from chirp.sources import repeaterbook


class TestRepeaterBook(unittest.TestCase):
    def _fetch_and_load(self, query):
        fn = tempfile.mktemp('.csv')
        try:
            r = requests.get(query, timeout=5)
        except requests.Timeout:
            raise unittest.SkipTest('RepeaterBook timeout')
        with open(fn, 'wb') as f:
            f.write(r.content)
        radio = repeaterbook.RBRadio(fn)
        return fn, radio

    def test_political(self):
        r = repeaterbook.RepeaterBook()
        r.do_fetch(mock.MagicMock(), {
            '_url': 'query/rb/1.0/chirp',
            'func': 'default', 'state_id': '41', 'band': '%%',
        })

    def test_proximity(self):
        r = repeaterbook.RepeaterBook()
        r.do_fetch(mock.MagicMock(), {
            '_url': 'query/rb/1.0/app_direct',
            'loc': '97124', 'band': '%%', 'dist': '20',
        })
