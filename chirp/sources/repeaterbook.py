import logging
import os
import tempfile

import requests

from chirp.drivers import generic_csv
from chirp.sources import base

LOG = logging.getLogger(__name__)


class RepeaterBook(base.NetworkResultRadio):
    def do_fetch(self, status, params):
        status.send_status('Querying', 10)

        r = requests.get('http://chirp.danplanet.com/%s' % params.pop('_url'),
                         params=params,
                         headers=base.HEADERS,
                         stream=True)
        if r.status_code != 200:
            status.send_fail('Got error code %i from server' % (
                r.status_code))
            return

        status.send_status('Downloading', 20)

        size = 0
        chunks = 0

        result_file = tempfile.NamedTemporaryFile(
            prefix='repeaterbook-',
            suffix='.csv').name

        LOG.debug('Writing to %s' % result_file)
        with open(result_file, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                size += len(chunk)
                chunks += 1
                status.send_status('Read %iKiB' % (size // 1024),
                                 20 + max(chunks * 10, 80))
                f.write(chunk)

        if size <= 105:
            status.send_fail('No results!')
            return

        radio = generic_csv.CSVRadio(None)
        radio.load(result_file)
        f = radio.get_features()
        self._memories = [radio.get_memory(i)
                          for i in range(0, f.memory_bounds[1])]
        try:
            os.remove(result_file)
        except OSError:
            pass

        status.send_end()