# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import functools
import logging
import requests
import threading
import uuid
import platform

try:
    import wx
except ImportError:
    wx = None

from chirp import CHIRP_VERSION
from chirp.wxui import config

CONF = config.get()
LOG = logging.getLogger(__name__)
logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)
SESSION = None
DISABLED = False
SEM = threading.Semaphore(2)
BASE = 'http://chirpmyradio.com/report'


def get_environment():
    if wx:
        wx_ver = wx.version()
    else:
        wx_ver = 'None'
    return ' // '.join(['Python/%s' % platform.python_version(),
                        '%s/%s' % (platform.system(),
                                   platform.platform()),
                        'CHIRP/%s' % CHIRP_VERSION,
                        'wx/%s' % wx_ver])


class ReportThread(threading.Thread):
    def __init__(self, fn):
        self.__fn = fn
        super(ReportThread, self).__init__()

    def run(self):
        global DISABLED

        try:
            self.__fn()
        except Exception as e:
            LOG.info('Disabling reporting because %s' % e)
            DISABLED = True
        finally:
            SEM.release()


def ensure_session():
    global SESSION
    if SESSION is None:
        SESSION = requests.Session()
        SESSION.headers = {
            'User-Agent': 'CHIRP/%s' % CHIRP_VERSION,
            'X-CHIRP-UUID': CONF.get('seat', 'state'),
            'X-CHIRP-Environment': get_environment(),
        }


def with_session(fn):

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global DISABLED

        if DISABLED:
            return

        if not SEM.acquire(False):
            return

        if not CONF.is_defined('seat', 'state'):
            CONF.set('seat', str(uuid.uuid4()), 'state')

        ensure_session()

        t = ReportThread(functools.partial(fn, SESSION, *args, **kwargs))
        t.start()

    return wrapper


@with_session
def check_for_updates(session, callback):
    r = session.get('%s/latest' % BASE)
    callback(r.json()['latest'])


@with_session
def report_model(session, rclass, op):
    if CONF.get_bool('no_report', 'global', False):
        return

    session.post('%s/usage' % BASE,
                 json={'vendor': rclass.VENDOR,
                       'model': rclass.MODEL,
                       'variant': rclass.VARIANT,
                       'op': op})
