import base64
import glob
import json
import os
import shutil
import tempfile
from unittest import mock

import yaml

from tests.unit import base
from chirp import chirp_common
from chirp import directory


class TestDirectory(base.BaseTest):
    def cleanUp(self):
        shutil.rmtree(self.tempdir)

    def setUp(self):
        super(TestDirectory, self).setUp()
        self.tempdir = tempfile.mkdtemp()
        directory.enable_reregistrations()

        class FakeAlias(chirp_common.Alias):
            VENDOR = 'Taylor'
            MODEL = 'Barmaster 2000'
            VARIANT = 'A'

        @directory.register
        class FakeRadio(chirp_common.CloneModeRadio):
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
        fn = os.path.join(self.tempdir, 'testfile')
        with open(fn, 'wb') as f:
            f.write(b'thisisrawdata')
            f.flush()
        self._test_detect_finds_our_class(fn)

    def test_detect_with_metadata_base_class(self):
        fn = os.path.join(self.tempdir, 'testfile')
        with open(fn, 'wb') as f:
            f.write(b'thisisrawdata')
            f.write(self.test_class.MAGIC + b'-')
            f.write(self.test_class(None)._make_metadata())
            f.flush()
        self._test_detect_finds_our_class(fn)

    def test_detect_with_metadata_alias_class(self):
        fn = os.path.join(self.tempdir, 'testfile')
        with open(fn, 'wb') as f:
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
        radio = self._test_detect_finds_our_class(fn)
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


class TestAliasMap(base.BaseTest):
    def test_uniqueness(self):
        directory_models = {}
        for rclass in directory.DRV_TO_RADIO.values():
            for cls in [rclass] + rclass.ALIASES:
                # Make sure there are no duplicates
                directory_models.setdefault(cls.VENDOR, set())
                fullmodel = '%s%s' % (cls.MODEL, cls.VARIANT)
                self.assertNotIn(fullmodel,
                                 directory_models[cls.VENDOR])
                directory_models[cls.VENDOR].add(fullmodel)

        aliases = yaml.load(open(os.path.join(os.path.dirname(__file__),
                                              '..', '..', 'chirp', 'share',
                                              'model_alias_map.yaml')).read(),
                            Loader=yaml.FullLoader)
        for vendor, models in sorted(aliases.items()):
            directory_models.setdefault(vendor, set())
            my_aliases = set([x['model'] for x in models])
            vendor = vendor.split('/')[0]
            for model in models:
                # Make sure the thing we tell users to use is in the
                # directory
                try:
                    alt_vendor, alt_model = model['alt'].split(' ', 1)
                except ValueError:
                    alt_vendor = vendor
                    alt_model = model['alt']

                # Aliases may reference other aliases?
                self.assertIn(alt_model,
                              directory_models[alt_vendor] | my_aliases,
                              '%s %s not found for %s %s' % (
                                  alt_vendor, alt_model,
                                  vendor, model['model']))

                # Make sure the alias model is NOT in the directory
                # before we add it to ensure there are no duplicates
                self.assertNotIn(model['model'], directory_models[vendor])
                directory_models[vendor].add(model['model'])


class TestDetectedBy(base.BaseTest):
    @mock.patch('chirp.directory.DRV_TO_RADIO', new={})
    @mock.patch('chirp.directory.RADIO_TO_DRV', new={})
    def test_detected_isolation(self):
        @directory.register
        class BaseRadio(chirp_common.CloneModeRadio):
            VENDOR = 'CHIRP'
            MODEL = 'Base'

        @directory.register
        class SubRadio1(BaseRadio):
            MODEL = 'Sub1'

        @directory.register
        @directory.detected_by(SubRadio1)
        class SubRadio2(SubRadio1):
            MODEL = 'Sub2'

        # BaseRadio should not think it detects the subs
        self.assertEqual([BaseRadio], BaseRadio.detected_models())

        # Sub1 detects both itself and Sub2
        self.assertEqual([SubRadio1, SubRadio2], SubRadio1.detected_models())

        # If include_self=False, Sub1 should not include itself
        self.assertEqual([SubRadio2],
                         SubRadio1.detected_models(include_self=False))

        # Sub2 does not also detect Sub1
        self.assertEqual([SubRadio2], SubRadio2.detected_models())

    @mock.patch('chirp.directory.DRV_TO_RADIO', new={})
    @mock.patch('chirp.directory.RADIO_TO_DRV', new={})
    def test_detected_include_self(self):
        class BaseRadio(chirp_common.CloneModeRadio):
            VENDOR = 'CHIRP'
            MODEL = 'Base'

        @directory.register
        @directory.detected_by(BaseRadio)
        class SubRadio(BaseRadio):
            MODEL = 'Sub'

        # BaseRadio should not include itself since it is not registered
        self.assertEqual([SubRadio], BaseRadio.detected_models())
