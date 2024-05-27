import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import pytest

from chirp import chirp_common
from chirp.sources import repeaterbook


class TestRepeaterbook(unittest.TestCase):
    def fake_config(self, fn):
        return os.path.join(self.tempdir, fn)

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.patches = []
        self.patches.append(mock.patch('chirp.platform.Platform.config_file',
                            self.fake_config))
        for p in self.patches:
            p.start()

        self.testfile = os.path.join(os.path.dirname(__file__),
                                     'rb-united_states-oregon.json')

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tempdir)

    @pytest.mark.network
    def test_get_oregon(self):
        rb = repeaterbook.RepeaterBook()
        self.assertRaises(IndexError, rb.get_memory, 0)
        rb.do_fetch(mock.MagicMock(), {
            'country': 'United States',
            'state': 'Oregon',
            'lat': 45,
            'lon': -122,
            'dist': 100,
            'openonly': False,
        })
        m = rb.get_memory(0)
        self.assertIsInstance(m, chirp_common.Memory)
        f = rb.get_features()
        self.assertGreater(sum(f.memory_bounds), 20)

        for i in range(*f.memory_bounds):
            m = rb.get_memory(i)
            if m.mode == 'DV':
                self.assertIsInstance(m, chirp_common.DVMemory)
                self.assertEqual('CQCQCQ  ', m.dv_urcall)
                self.assertEqual(8, len(m.dv_rpt1call))
                self.assertEqual(8, len(m.dv_rpt2call))
                self.assertEqual(m.dv_rpt1call, m.dv_rpt2call)
                self.assertNotEqual('', m.dv_rpt1call)
                break
        else:
            raise Exception('Did not find any DV results')

    @pytest.mark.network
    def test_get_wyoming(self):
        rb = repeaterbook.RepeaterBook()
        self.assertRaises(IndexError, rb.get_memory, 0)
        rb.do_fetch(mock.MagicMock(), {
            'country': 'United States',
            'state': 'Wyoming',
            'lat': 45,
            'lon': -122,
            'dist': 0,
            'openonly': False,
        })
        m = rb.get_memory(0)
        self.assertIsInstance(m, chirp_common.Memory)
        f = rb.get_features()
        self.assertGreater(sum(f.memory_bounds), 20)

    @pytest.mark.network
    def test_get_oregon_gmrs(self):
        rb = repeaterbook.RepeaterBook()
        self.assertRaises(IndexError, rb.get_memory, 0)
        rb.do_fetch(mock.MagicMock(), {
            'country': 'United States',
            'state': 'Oregon',
            'lat': 45,
            'lon': -122,
            'dist': 100,
            'service': 'gmrs',
            'openonly': False,
        })
        m = rb.get_memory(0)
        self.assertIsInstance(m, chirp_common.Memory)
        f = rb.get_features()
        self.assertGreater(sum(f.memory_bounds), 1)

    @pytest.mark.network
    def test_get_australia(self):
        rb = repeaterbook.RepeaterBook()
        self.assertRaises(IndexError, rb.get_memory, 0)
        rb.do_fetch(mock.MagicMock(), {
            'country': 'Australia',
            'state': 'ALL',
            'lat': -26,
            'lon': 133,
            'dist': 20000,
            'openonly': False,
        })
        m = rb.get_memory(0)
        self.assertIsInstance(m, chirp_common.Memory)
        f = rb.get_features()
        self.assertGreater(sum(f.memory_bounds), 20)

    def _test_with_mocked(self, params):
        rb = repeaterbook.RepeaterBook()
        with mock.patch.object(rb, 'get_data') as gd:
            gd.return_value = self.testfile
            rb.do_fetch(mock.MagicMock(), params)
        return rb

    def test_filter(self):
        params = {'country': 'United States',
                  'state': 'Oregon',
                  'lat': 45,
                  'lon': -122,
                  'dist': 0,
                  'openonly': False,
                  'filter': 'tower'}
        rb = self._test_with_mocked(params)
        self.assertGreater(sum(rb.get_features().memory_bounds), 5)

    def test_distance(self):
        params = {'country': 'United States',
                  'state': 'Oregon',
                  'lat': 45,
                  'lon': -122,
                  'dist': 0,
                  'openonly': False,
                  'filter': 'tower'}
        rb1 = self._test_with_mocked(dict(params))
        self.assertGreater(sum(rb1.get_features().memory_bounds), 5)

        # Make sure we got fewer than everything in Oregon
        params['dist'] = 100
        rb2 = self._test_with_mocked(dict(params))
        self.assertLess(sum(rb2.get_features().memory_bounds),
                        sum(rb1.get_features().memory_bounds))

        # There is nothing 1km away from this spot in the ocean
        params['dist'] = 1
        params['lat'] = 45
        params['lon'] = -140
        rb3 = self._test_with_mocked(dict(params))
        self.assertEqual(sum(rb3.get_features().memory_bounds), -1)

    def test_get_data_500(self):
        rb = repeaterbook.RepeaterBook()
        with mock.patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 500
            status = mock.MagicMock()
            r = rb.get_data(status, 'US', 'OR', '')
            self.assertIsNone(r)
            status.send_fail.assert_called()
            # Make sure we wrote no files
            self.assertEqual([], os.listdir(os.path.join(self.tempdir,
                                                         'repeaterbook')))

    def test_get_data_json_fail(self):
        rb = repeaterbook.RepeaterBook()
        with mock.patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.iter_content.return_value = [b'foo']
            status = mock.MagicMock()
            r = rb.get_data(status, 'US', 'OR', '')
            self.assertIsNone(r)
            files = os.listdir(os.path.join(self.tempdir,
                                            'repeaterbook'))
            # Make sure we only wrote one file and that it is a tempfile
            # not one we will find as a data file later
            self.assertEqual(1, len(files))
            self.assertTrue(files[0].endswith('tmp'))
            status.send_fail.assert_called()

    def test_get_data_no_results(self):
        rb = repeaterbook.RepeaterBook()
        with mock.patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.iter_content.return_value = [json.dumps(
                {'count': 0}).encode()]
            status = mock.MagicMock()
            r = rb.get_data(status, 'US', 'OR', '')
            self.assertIsNone(r)
            files = os.listdir(os.path.join(self.tempdir,
                                            'repeaterbook'))
            # Make sure we cleaned up and signaled failure
            self.assertEqual(0, len(files))
            status.send_fail.assert_called()

    def test_get_data_got_results(self):
        files = os.listdir(self.tempdir)
        # Make sure we started with no data files
        self.assertEqual(0, len(files))
        rb = repeaterbook.RepeaterBook()
        with mock.patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.iter_content.return_value = [json.dumps(
                {'count': 1}).encode()]
            status = mock.MagicMock()
            r = rb.get_data(status, 'US', 'OR', '')
            self.assertIsNotNone(r)
            files = os.listdir(os.path.join(self.tempdir,
                                            'repeaterbook'))
            # Make sure we left only a data file and did not signal failure
            self.assertEqual(1, len(files))
            self.assertFalse(files[0].endswith('tmp'))
            self.assertEqual(os.path.basename(r), files[0])
            status.send_fail.assert_not_called()

    def test_get_data_honors_cache_rules(self):
        os.mkdir(os.path.join(self.tempdir, 'repeaterbook'))
        cache_file = os.path.join(self.tempdir,
                                  'repeaterbook',
                                  os.path.basename(self.testfile))
        with open(cache_file, 'w') as f:
            f.write('foo')
        rb = repeaterbook.RepeaterBook()
        with mock.patch('requests.get') as mock_get:
            r = rb.get_data(mock.MagicMock(), 'United States', 'Oregon', '')
            self.assertEqual(cache_file, r)
            # Make sure we returned the cached file
            mock_get.assert_not_called()

            real_timedelta = datetime.timedelta
            real_datetime = datetime.datetime

            future = datetime.datetime.now() + datetime.timedelta(days=4)
            with mock.patch.object(repeaterbook, 'datetime') as mock_dt:
                mock_dt.datetime.fromtimestamp = real_datetime.fromtimestamp
                mock_dt.timedelta = real_timedelta
                mock_dt.datetime.now.return_value = future
                r = rb.get_data(mock.MagicMock(),
                                'United States', 'Oregon', '')
                # Cache file is 4 days old, we should use it
                mock_get.assert_not_called()

            future = datetime.datetime.now() + datetime.timedelta(days=45)
            with mock.patch.object(repeaterbook, 'datetime') as mock_dt:
                mock_dt.datetime.fromtimestamp = real_datetime.fromtimestamp
                mock_dt.timedelta = real_timedelta
                mock_dt.datetime.now.return_value = future
                r = rb.get_data(mock.MagicMock(),
                                'United States', 'Oregon', '')
                # Cache file is 45 days old, we should re-fetch
                mock_get.assert_called()
