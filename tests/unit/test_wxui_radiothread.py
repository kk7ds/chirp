import sys
import time
from unittest import mock

sys.modules['wx'] = wx = mock.MagicMock()

from tests.unit import base
from chirp.wxui import radiothread


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
