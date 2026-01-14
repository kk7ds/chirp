import argparse
import builtins
from importlib import resources
import logging
import os
import sys

from chirp import CHIRP_VERSION
from chirp import directory
from chirp import logger

LOG = logging.getLogger(__name__)
CONF = None
logging.captureWarnings(True)


def developer_mode(enabled=None):
    if not CONF:
        return False

    if enabled is True:
        CONF.set('developer_mode', CHIRP_VERSION, 'state')
    elif enabled is False:
        CONF.remove_option('developer_mode', 'state')

    return CONF.get('developer_mode', 'state') == CHIRP_VERSION


def maybe_install_desktop(args, parent):
    local = os.path.join(os.path.expanduser('~'), '.local')
    desktop_path = os.path.join(local, 'share',
                                'applications', 'chirp.desktop')
    with resources.as_file(
            resources.files('chirp.share').joinpath('chirp.desktop')
    ) as desktop_src:
        with open(desktop_src) as f:
            desktop_content = f.readlines()
    with resources.as_file(
            resources.files('chirp.share').joinpath('chirp.ico')) as p:
        icon_path = str(p)

    # If asked not to do this, always bail
    if args.no_install_desktop_app:
        return

    # Already exists, don't prompt user
    if os.path.exists(desktop_path):
        LOG.debug('Desktop file exists')
        return

    # If already asked and not explicitly opted-in, stop nagging
    if (CONF.get_bool('offered_desktop', 'state') and not
            args.install_desktop_app):
        LOG.debug('Desktop file missing but user previously offered')
        return

    import wx
    r = wx.MessageBox(
        _('Would you like CHIRP to install a desktop icon for you?'),
        _('Install desktop icon?'), parent=parent, style=wx.YES_NO)
    if r != wx.YES:
        CONF.set_bool('offered_desktop', True, 'state')
        return

    os.makedirs(os.path.dirname(desktop_path), exist_ok=True)

    # Try to run chirp by name from ~/.local/bin
    exec_path = os.path.join(local, 'bin', 'chirp')
    if not os.path.exists(exec_path):
        # If that doesn't work, then just run it with our python via
        # module, which should always work
        exec_path = '%s -mchirp.wxui' % sys.executable
    with open(desktop_path, 'w') as f:
        for line in desktop_content:
            if line.startswith('Exec'):
                f.write('Exec=%s\n' % exec_path)
            elif line.startswith('Icon'):
                f.write('Icon=%s\n' % icon_path)
            else:
                f.write(line)
        LOG.debug('Wrote %s with exec=%r icon=%r' % (
            f.name, exec_path, icon_path))


def chirpmain():
    global CONF

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
    parser.add_argument('--force-language', default=None,
                        help='Force locale to this ISO language code')
    parser.add_argument('--config-dir',
                        help=('Use this alternate directory for config and '
                              'other profile data'))
    if sys.platform == 'linux':
        desktop = parser.add_mutually_exclusive_group()
        parser.add_argument('--no-linux-gdk-backend', action='store_true',
                            help='Do not force GDK_BACKEND=x11')
        desktop.add_argument('--install-desktop-app', action='store_true',
                             default=False,
                             help=('Install a desktop icon even if it was '
                                   'previously refused'))
        desktop.add_argument('--no-install-desktop-app', action='store_true',
                             default=False,
                             help='Do not prompt to install a desktop icon')
    logger.add_arguments(parser)
    args = parser.parse_args()
    logger.handle_options(args)
    from chirp.wxui import config

    if args.config_dir:
        try:
            os.mkdir(args.config_dir)
        except Exception:
            pass
        assert os.path.isdir(args.config_dir), \
            '--config must specify directory'
        config._CONFIG = config.ChirpConfig(args.config_dir)
    CONF = config.get()

    # wxGTK on Wayland seems to have problems. Override GDK_BACKEND to
    # use X11, unless we were asked not to.
    # NOTE this needs to happen before we import wx to be effective!
    if sys.platform == 'linux' and not args.no_linux_gdk_backend:
        os.putenv('GDK_BACKEND', 'x11')

    import wx
    # This must be imported before wx.App() to squelch warnings on startup
    # about duplicate "Windows bitmap file" handlers
    import wx.richtext
    app = wx.App()
    if args.force_language:
        force_lang = wx.Locale.FindLanguageInfo(args.force_language)
        if force_lang is None:
            print('Failed to find language %r' % args.force_language)
            return 1
        LOG.info('Forcing locale to %r (%s)' % (
            args.force_language, force_lang.Description))
        lang = force_lang.Language
    elif CONF.is_defined('force_language', 'prefs'):
        prefs_lang = CONF.get('force_language', 'prefs')
        force_lang = wx.Locale.FindLanguageInfo(prefs_lang)
        if force_lang is None:
            LOG.warning('Config prefs.force_language specifies unknown '
                        'language %r', prefs_lang)
            lang = wx.Locale.GetSystemLanguage()
        else:
            LOG.info('Forcing locale to %r (%s) via config', prefs_lang,
                     force_lang.Description)
            lang = force_lang.Language
    else:
        lang = wx.Locale.GetSystemLanguage()

    localedir = str(os.path.join(resources.files('chirp'), 'locale'))
    app._lc = wx.Locale()
    if localedir and os.path.isdir(localedir):
        wx.Locale.AddCatalogLookupPathPrefix(localedir)
    else:
        LOG.warning('Did not find localedir: %s' % localedir)

    if lang != wx.LANGUAGE_UNKNOWN:
        app._lc.Init(lang)
    else:
        LOG.warning('Initializing locale without known language')
        app._lc.Init()
    app._lc.AddCatalog('CHIRP')
    builtins._ = wx.GetTranslation
    builtins.ngettext = wx.GetTranslation
    LOG.debug('Using locale: %s (%i)',
              app._lc.GetCanonicalName(),
              lang)
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

    from chirp.wxui import main
    from chirp.wxui import report

    logging.getLogger('main').info(report.get_environment())

    directory.import_drivers(limit=args.onlydriver)

    if developer_mode():
        LOG.warning('Developer mode is enabled')
        from chirp.drivers import fake
        fake.register_fakes()

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

    if sys.platform == 'linux':
        try:
            maybe_install_desktop(args, mainwindow)
        except Exception as e:
            LOG.exception('Failed to run linux desktop installer: %s', e)

    app.MainLoop()
