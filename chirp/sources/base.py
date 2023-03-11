import logging
import sys

from chirp import CHIRP_VERSION
from chirp import chirp_common
from chirp import errors

LOG = logging.getLogger(__name__)
HEADERS = {
    'User-Agent': 'chirp/%s Python %i.%i.%i %s' % (
        CHIRP_VERSION,
        sys.version_info.major, sys.version_info.minor, sys.version_info.micro,
        sys.platform),
}


class QueryStatus:
    def send_status(self, status, percent):
        LOG.info('QueryStatus[%i%%]: %s' % (percent, status))

    def send_end(self):
        LOG.info('QueryStatus: END')

    def send_fail(self, reason):
        LOG.error('QueryStatus Failed: %s' % reason)


class NetworkResultRadio(chirp_common.NetworkSourceRadio):
    VENDOR = 'Query'
    MODEL = 'Result'

    def __init__(self):
        self._memories = []

    def do_fetch(self, status, params):
        pass

    def get_label(self):
        return 'QueryResult'

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, len(self._memories) - 1)
        rf.has_rx_dtcs = True
        rf.has_cross = True
        rf.has_bank = False
        rf.has_settings = False
        rf.has_comment = True
        rf.valid_skips = []
        rf.valid_cross_modes = chirp_common.CROSS_MODES
        rf.valid_tmodes = chirp_common.TONE_MODES
        return rf

    def get_memory(self, number):
        return self._memories[number]

    def set_memory(self, memory):
        raise errors.RadioError('Network source is immutable')

    def validate_memory(self, memory):
        return ['Network source is immutable']
