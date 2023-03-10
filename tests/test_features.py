from unittest import mock

from tests import base


class TestCaseFeatures(base.DriverTest):
    def test_prompts(self):
        self.use_patch(mock.patch('builtins._', create=True,
                                  side_effect=lambda s: s))
        prompts = self.radio.get_prompts()
        for p in ('info', 'experimental', 'pre_download', 'pre_upload'):
            prompt = getattr(prompts, p)
            if prompt is not None:
                self.assertIsInstance(prompt, str)
