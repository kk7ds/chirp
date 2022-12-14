import tempfile
import unittest
import requests

from chirp import chirp_common
from chirp.drivers import repeaterbook


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
        query = "http://www.repeaterbook.com/repeaters/downloads/chirp.php" + \
            "?func=default&state_id=%s&band=%s&freq=%%&band6=%%&loc=%%" + \
            "&county_id=%s&status_id=%%&features=%%&coverage=%%&use=%%"
        query = query % ('41', '%%', '005')
        self._fetch_and_load(query)

    def test_proximity(self):
        loc = '97124'
        band = '%%'
        dist = '20'
        query = "https://www.repeaterbook.com/repeaters/downloads/CHIRP/" \
                "app_direct.php?loc=%s&band=%s&dist=%s" % (loc, band, dist)
        self._fetch_and_load(query)
