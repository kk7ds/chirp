import sys
from unittest import mock

from tests.unit import base

sys.modules['wx'] = wx = mock.MagicMock()

event_cls = mock.MagicMock()
event_type = mock.sentinel.radio_thread_result
wx.lib.newevent.NewCommandEvent.return_value = (event_cls, event_type)

from chirp.wxui import radiothread


class TestRadioThread(base.BaseTest):
    def setUp(self):
        super().setUp()
        wx.PostEvent.reset_mock()
        event_cls.reset_mock()

    def test_radiojob(self):
        radio = mock.MagicMock()
        editor = mock.MagicMock()
        job = radiothread.RadioJob(editor, 'get_memory', [12], {})
        self.assertIsNone(job.dispatch(radio))
        radio.get_memory.assert_called_once_with(12)
        wx.PostEvent.assert_called_once_with(editor, event_cls.return_value)
        event_cls.assert_called_once_with(editor.GetId.return_value,
                                          job=job)
        self.assertEqual(job.result, radio.get_memory.return_value)

    def test_radiojob_exception(self):
        radio = mock.MagicMock()
        radio.get_memory.side_effect = ValueError('some error')
        editor = mock.MagicMock()
        job = radiothread.RadioJob(editor, 'get_memory', [12], {})
        self.assertIsNone(job.dispatch(radio))
        radio.get_memory.assert_called_once_with(12)
        wx.PostEvent.assert_called_once_with(editor, event_cls.return_value)
        event_cls.assert_called_once_with(editor.GetId.return_value,
                                          job=job)
        self.assertIsInstance(job.result, ValueError)

    def test_thread(self):
        radio = mock.MagicMock()
        radio.get_features.side_effect = ValueError('some error')
        editor = mock.MagicMock()
        thread = radiothread.RadioThread(radio)
        thread.start()
        mem = mock.MagicMock()
        job1id = thread.submit(editor, 'get_memory', 12)
        job2id = thread.submit(editor, 'set_memory', mem)
        job3id = thread.submit(editor, 'get_features')
        thread.end()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        radio.get_memory.assert_called_once_with(12)
        radio.set_memory.assert_called_once_with(mem)
        radio.get_features.assert_called_once_with()
        self.assertEqual(3, wx.PostEvent.call_count)

        for i, (jobid, call) in enumerate(zip([job1id, job2id, job3id],
                                              wx.PostEvent.call_args_list)):
            job = event_cls.call_args_list[i][1]['job']
            self.assertEqual(jobid, job.id)
