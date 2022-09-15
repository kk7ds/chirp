import base64
import glob
import json
import os
import tempfile

from tests.unit import base
from chirp import chirp_common
from chirp import directory


class TestDirectory(base.BaseTest):
    def setUp(self):
        super(TestDirectory, self).setUp()

        directory.enable_reregistrations()

        class FakeAlias(chirp_common.Alias):
            VENDOR = 'Taylor'
            MODEL = 'Barmaster 2000'
            VARIANT = 'A'

        @directory.register
        class FakeRadio(chirp_common.FileBackedRadio):
            VENDOR = 'Dan'
            MODEL = 'Foomaster 9000'
            VARIANT = 'R'
            ALIASES = [FakeAlias]

            @classmethod
            def match_model(cls, file_data, image_file):
                return file_data == b'thisisrawdata'

        self.test_class = FakeRadio

    def _test_detect_finds_our_class(self, tempfn):
        radio = directory.get_radio_by_image(tempfn)
        self.assertTrue(isinstance(radio, self.test_class))
        return radio

    def test_detect_with_no_metadata(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'thisisrawdata')
            f.flush()
            self._test_detect_finds_our_class(f.name)

    def test_detect_with_metadata_base_class(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'thisisrawdata')
            f.write(self.test_class.MAGIC + b'-')
            f.write(self.test_class._make_metadata())
            f.flush()
            self._test_detect_finds_our_class(f.name)

    def test_detect_with_metadata_alias_class(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'thisisrawdata')
            f.write(self.test_class.MAGIC + b'-')
            FakeAlias = self.test_class.ALIASES[0]
            fake_metadata = base64.b64encode(json.dumps(
                {'vendor': FakeAlias.VENDOR,
                 'model': FakeAlias.MODEL,
                 'variant': FakeAlias.VARIANT,
                }).encode())
            f.write(fake_metadata)
            f.flush()
            radio = self._test_detect_finds_our_class(f.name)
            self.assertEqual('Taylor', radio.VENDOR)
            self.assertEqual('Barmaster 2000', radio.MODEL)
            self.assertEqual('A', radio.VARIANT)


class TestDetectBruteForce(base.BaseTest):
    def test_detect_all(self):
        # Attempt a brute-force detection of all test images.
        #
        # This confirms that no test image is detected by more than one
        # radio class. If it is, fail and report those classes.

        path = os.path.dirname(__file__)
        path = os.path.join(path, '..', 'images', '*.img')
        test_images = glob.glob(path)
        self.assertNotEqual(0, len(test_images))
        for image in test_images:
            detections = []
            filedata = open(image, 'rb').read()
            for cls in directory.RADIO_TO_DRV:
                if not hasattr(cls, 'match_model'):
                    continue
                if cls.match_model(filedata, image):
                    detections.append(cls)
            if len(detections) > 1:
                raise Exception('Detection of %s failed: %s' % (image,
                                                                detections))
