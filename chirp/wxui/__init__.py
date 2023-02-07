import argparse
import builtins
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
    import wx

    app = wx.App()
    localedir = str(os.path.join(importlib_resources.files('chirp'),
                                 'locale'))
    syslang = wx.Locale.GetSystemLanguage()
    app._lc = wx.Locale()
    if localedir and os.path.isdir(localedir):
        wx.Locale.AddCatalogLookupPathPrefix(localedir)
    if syslang != wx.LANGUAGE_UNKNOWN:
        app._lc.Init(syslang)
    else:
        app._lc.Init()
    app._lc.AddCatalog('CHIRP')
    builtins._ = wx.GetTranslation

    from chirp.wxui import config
    from chirp.wxui import main
    from chirp.wxui import report

    actions = ['upload', 'download', 'query_rr', 'query_mg',
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
    parser.add_argument('--restore', default=None, action='store_true',
                        help="Restore previous tabs")
    if sys.platform == 'linux':
        parser.add_argument('--no-linux-gdk-backend', action='store_true',
                            help='Do not force GDK_BACKEND=x11')
    logger.add_arguments(parser)
    args = parser.parse_args()

    logger.handle_options(args)
    logging.getLogger('main').info(report.get_environment())

    if not localedir or not os.path.isdir(localedir):
        LOG.warning('Did not find localedir: %s' % localedir)
    LOG.debug('System locale: %s (%i)',
              app._lc.GetCanonicalName(),
              syslang)
    LOG.debug('Translation loaded=%s for CHIRP: %s (%s) from %s',
              app._lc.IsLoaded('CHIRP'),
              wx.Translations.Get().GetBestTranslation('CHIRP'),
              ','.join(
                  wx.Translations.Get().GetAvailableTranslations('CHIRP')),
              localedir)
    LOG.debug('Translation loaded=%s for wxstd: %s (%s)',
              app._lc.IsLoaded('wxstd'),
              wx.Translations.Get().GetBestTranslation('wxstd'),
              ','.join(
                  wx.Translations.Get().GetAvailableTranslations('wxstd')))

    directory.import_drivers(limit=args.onlydriver)

    CONF = config.get()
    if CONF.get('developer', 'state'):
        from chirp.drivers import fake
        fake.register_fakes()

    # wxGTK on Wayland seems to have problems. Override GDK_BACKEND to
    # use X11, unless we were asked not to
    if sys.platform == 'linux' and not args.no_linux_gdk_backend:
        os.putenv('GDK_BACKEND', 'x11')

    app.SetAppName('CHIRP')
    mainwindow = main.ChirpMain(None, title='CHIRP')
    mainwindow.Show()

    if args.module:
        mainwindow.load_module(args.module)

    if args.restore or CONF.get_bool('restore_tabs', 'prefs'):
        restored = mainwindow.restore_tabs(None)
    else:
        restored = []

    for fn in args.files:
        if os.path.abspath(fn) in restored:
            LOG.info('File %s on the command line is already being restored',
                     fn)
            continue
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
