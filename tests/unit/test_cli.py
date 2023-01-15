import os
import unittest
from unittest import mock

from chirp.cli import main


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.stdout_lines = []
        self.patches = []
        self.patches.append(mock.patch('sys.exit'))
        self.patches.append(mock.patch.object(main, 'print',
                                              new=self.fake_print))
        for patch in self.patches:
            patch.start()

        # A path to an image file we can pass to the CLI for testing
        self.testfile = os.path.join(
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), '..', 'images',
                    'Icom_IC-2820H.img')))

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def fake_print(self, *a):
        for i in a:
            self.stdout_lines.append(str(i))

    @property
    def stdout(self):
        return '\n'.join(self.stdout_lines)

    def test_cli_simple(self):
        # Super simple, just print the first memory and make sure it
        # works
        args = ['--mmap', self.testfile, '--get-mem', 0]
        main.main(args=args)
        self.assertIn('147.56', self.stdout)
