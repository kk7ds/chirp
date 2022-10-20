import sys
import time
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
        mem = mock.MagicMock()
        job1id = thread.submit(editor, 'get_memory', 12)
        job2id = thread.submit(editor, 'set_memory', mem)
        job3id = thread.submit(editor, 'get_features')
        # We have to start the thread after we submit the main jobs so
        # the order is stable for comparison.
        thread.start()

        # Wait for the main jobs to be processed before we signal exit
        while thread.pending:
            time.sleep(0.1)

        thread.end()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        radio.get_memory.assert_called_once_with(12)
        radio.set_memory.assert_called_once_with(mem)
        radio.get_features.assert_called_once_with()
        self.assertEqual(3, wx.PostEvent.call_count)

        expected_order = [job2id, job3id, job1id]
        for i, (jobid, call) in enumerate(zip(expected_order,
                                              wx.PostEvent.call_args_list)):
            job = event_cls.call_args_list[i][1]['job']
            self.assertEqual(jobid, job.id)

    def test_thread_abort_priority(self):
        radio = mock.MagicMock()
        radio.get_features.side_effect = ValueError('some error')
        editor = mock.MagicMock()
        thread = radiothread.RadioThread(radio)
        mem = mock.MagicMock()
        job1id = thread.submit(editor, 'get_memory', 12)
        job2id = thread.submit(editor, 'set_memory', mem)
        job3id = thread.submit(editor, 'get_features')
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
