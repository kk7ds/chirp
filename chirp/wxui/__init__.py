import argparse
import gettext
import locale
import logging
import os
import sys

if sys.version_info < (3, 10):
    import importlib_resources
else:
    import importlib.resources as importlib_resources

from chirp import directory
from chirp import logger

LOG = logging.getLogger(__name__)


def chirpmain():
    try:
        # This looks strange, but:
        # files('chirp') returns a Path which we can use
        # files('chirp.locale') returns a MultiplexedPath, which we cannot
        # So, get the path to the module/bundle and then construct the
        # path to localedir, as gettext needs a path and not to iterate
        # files or anything.
        localedir = str(os.path.join(importlib_resources.files('chirp'),
                                     'locale'))
        lang = locale.getdefaultlocale()[0]
        gettext.translation('CHIRP', localedir, languages=[lang]).install()
        translation_error = None
    except Exception as e:
        # Logging is not setup yet, so stash and log later
        translation_error = e
        lang = None
        # Need to do some install to make _() work elsewhere
        gettext.install('CHIRP', localedir)

    import wx
    from chirp.ui import config
    from chirp.wxui import main
    from chirp.wxui import report

    actions = ['upload', 'download', 'query_rrca', 'query_rrus',
               'query_rb', 'query_dm', 'new']

    parser = argparse.ArgumentParser()
    parser.add_argument("files", metavar="file", nargs='*',
                        help="File to open")
    parser.add_argument("--module", metavar="module",
                        help="Load module on startup")
    logger.add_version_argument(parser)
    parser.add_argument("--profile", action="store_true",
                        help="Enable profiling")
    parser.add_argument("--onlydriver", nargs="+",
                        help="Include this driver while loading")
    parser.add_argument("--inspect", action="store_true",
                        help="Show wxPython inspector")
    parser.add_argument('--page', default=None,
                        help='Select this page of the default editor at start')
    parser.add_argument('--action', default=None, choices=actions,
                        help='Start UI action immediately')
    if sys.platform == 'linux':
        parser.add_argument('--no-linux-gdk-backend', action='store_true',
                            help='Do not force GDK_BACKEND=x11')
    logger.add_arguments(parser)
    args = parser.parse_args()

    logger.handle_options(args)
    logging.getLogger('main').info(report.get_environment())

    if not os.path.isdir(localedir):
        LOG.warning('Did not find localedir: %s' % localedir)
    LOG.debug('Got system locale %s' % lang)
    if translation_error:
        LOG.debug('Failed to set up translations: %s',
                  translation_error)

    directory.import_drivers(limit=args.onlydriver)

    CONF = config.get()
    if CONF.get('developer', 'state'):
        from chirp.drivers import fake
        fake.register_fakes()

    # wxGTK on Wayland seems to have problems. Override GDK_BACKEND to
    # use X11, unless we were asked not to
    if sys.platform == 'linux' and not args.no_linux_gdk_backend:
        os.putenv('GDK_BACKEND', 'x11')

    app = wx.App()
    app.SetAppName('CHIRP')
    app._locale = wx.Locale(wx.Locale.GetSystemLanguage())
    mainwindow = main.ChirpMain(None, title='CHIRP')
    mainwindow.Show()

    if args.module:
        mainwindow.load_module(args.module)

    for fn in args.files:
        mainwindow.open_file(fn, select=False)

    if args.page:
        mainwindow.current_editorset.select_editor(name=args.page)

    if args.inspect:
        from wx.lib import inspection
        inspection.InspectionTool().Show()

    if args.action:
        wx.CallAfter(getattr(mainwindow, '_menu_%s' % args.action), None)

    report.check_for_updates(
        lambda ver: wx.CallAfter(main.display_update_notice, ver))

    app.MainLoop()
