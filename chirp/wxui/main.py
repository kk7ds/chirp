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

import datetime
import functools
import hashlib
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
import webbrowser

if sys.version_info < (3, 10):
    import importlib_resources
else:
    import importlib.resources as importlib_resources

import wx
import wx.aui
import wx.lib.newevent

from chirp import bandplan
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import logger
from chirp import platform as chirp_platform
from chirp.sources import base
from chirp.wxui import config
from chirp.wxui import bankedit
from chirp.wxui import common
from chirp.wxui import clone
from chirp.wxui import developer
from chirp.wxui import memedit
from chirp.wxui import printing
from chirp.wxui import query_sources
from chirp.wxui import radioinfo
from chirp.wxui import radiothread
from chirp.wxui import report
from chirp.wxui import settingsedit
from chirp import CHIRP_VERSION

EditorSetChanged, EVT_EDITORSET_CHANGED = wx.lib.newevent.NewCommandEvent()
CONF = config.get()
LOG = logging.getLogger(__name__)

EMPTY_MENU_LABEL = '(none)'
KEEP_RECENT = 8
OPEN_RECENT_MENU = None
OPEN_STOCK_CONFIG_MENU = None


class ChirpEditorSet(wx.Panel):
    MEMEDIT_CLS = memedit.ChirpMemEdit
    SETTINGS_CLS = settingsedit.ChirpCloneSettingsEdit
    BANK_CLS = bankedit.ChirpBankEditSync

    @property
    def tab_name(self):
        if isinstance(self._radio, base.NetworkResultRadio):
            return self._radio.get_label()
        return '%s.%s' % (self.default_filename,
                          self._radio.FILE_EXTENSION)

    def add_editor(self, editor, title):
        self._editors.AddPage(editor, title)
        self.Bind(common.EVT_STATUS_MESSAGE, self._editor_status, editor)
        self._editor_index[title] = editor

    def _editor_status(self, event):
        LOG.info('Editor status: %s' % event.message)
        wx.PostEvent(self, common.StatusMessage(self.GetId(),
                                                message=event.message))

    def __init__(self, radio, filename, *a, **k):
        super(ChirpEditorSet, self).__init__(*a, **k)
        self._radio = radio
        if filename is None:
            filename = self.tab_name

        self._filename = filename
        self._modified = not os.path.exists(filename)

        self._editor_index = {}

        features = radio.get_features()

        parent_radio = radio
        if features.has_sub_devices:
            radios = radio.get_sub_devices()
            format = '%(type)s (%(variant)s)'
            if isinstance(parent_radio, chirp_common.ExternalMemoryProperties):
                parent_radio.link_device_metadata(radios)
        else:
            radios = [radio]
            format = '%(type)s'

        if len(radios) > 2:
            LOG.info('Using TreeBook because radio has %i devices',
                     len(radios))
            self._editors = wx.Treebook(self, style=wx.NB_RIGHT)
            self._editors.Bind(wx.EVT_TREEBOOK_PAGE_CHANGED,
                               self._editor_selected)
        else:
            self._editors = wx.Notebook(self, style=wx.NB_TOP)
            self._editors.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,
                               self._editor_selected)

        sizer = wx.BoxSizer()
        sizer.Add(self._editors, 1, wx.EXPAND)
        self.SetSizer(sizer)

        for radio in radios:
            edit = self.MEMEDIT_CLS(radio, self._editors)
            self.add_editor(edit, format % {'type': _('Memories'),
                                            'variant': radio.VARIANT})
            edit.refresh()
            self.Bind(common.EVT_EDITOR_CHANGED, self._editor_changed)

            sub_features = radio.get_features()
            if sub_features.has_bank and self.BANK_CLS:
                banks = self.BANK_CLS(radio, self._editors)
                self.add_editor(banks, format % {'type': _('Banks'),
                                                 'variant': radio.VARIANT})

        if features.has_settings:
            settings = self.SETTINGS_CLS(parent_radio, self._editors)
            self.add_editor(settings, _('Settings'))

        if (CONF.get_bool('developer', 'state') and
                isinstance(radio, chirp_common.CloneModeRadio)):
            browser = developer.ChirpRadioBrowser(parent_radio, self._editors)
            browser.Bind(common.EVT_EDITOR_CHANGED, self._refresh_all)
            self.add_editor(browser, _('Browser'))
            info = radioinfo.ChirpRadioInfo(parent_radio, self._editors)
            self.add_editor(info, _('Info'))

        # After the GUI is built, set focus to the current editor
        wx.CallAfter(self.current_editor.SetFocus)

    def _refresh_all(self, event):
        LOG.info('Radio browser changed; refreshing all others')
        for i in range(self._editors.GetPageCount()):
            editor = self._editors.GetPage(i)
            if editor.GetId() != event.GetId():
                LOG.debug('refreshing %s' % editor)
                editor.refresh()

    def _editor_changed(self, event):
        self._modified = True
        wx.PostEvent(self, EditorSetChanged(self.GetId(), editorset=self))

    def _editor_selected(self, event):
        page_index = event.GetSelection()
        page = self._editors.GetPage(page_index)
        page.selected()
        wx.PostEvent(self, EditorSetChanged(self.GetId(), editorset=self))

    def save(self, filename=None):
        if filename is None:
            filename = self.filename
        LOG.debug('Saving to %s' % filename)
        self._radio.save(filename)
        self._filename = filename
        self._modified = False
        self.current_editor.saved()

    @property
    def filename(self):
        return self._filename

    @property
    def modified(self):
        if isinstance(self._radio, base.NetworkResultRadio):
            return False
        return self._modified

    @property
    def radio(self):
        return self._radio

    @property
    def default_filename(self):
        defname_format = CONF.get("default_filename", "global") or \
            "{vendor}_{model}_{date}"
        defname = defname_format.format(
            vendor=self._radio.VENDOR,
            model=self._radio.MODEL,
            date=datetime.datetime.now().strftime('%Y%m%d')
        ).replace('/', '_')
        return defname

    @property
    def current_editor(self):
        return self._editors.GetCurrentPage()

    @property
    def current_editor_index(self):
        return self._editors.GetSelection()

    def select_editor(self, index=None, name=None):
        if index is None and name:
            try:
                index = self._editors.FindPage(self._editor_index[name])
            except KeyError:
                LOG.error('No editor %r to select' % name)
                return
        if index is None:
            LOG.error('Unable to find editor to select (%r/%r',
                      index, name)
            return
        self._editors.SetSelection(index)

    def cb_copy(self, cut=False):
        return self.current_editor.cb_copy(cut=cut)

    def cb_paste(self, data):
        return self.current_editor.cb_paste(data)

    def cb_delete(self):
        return self.current_editor.cb_delete()

    def cb_goto(self, number):
        return self.current_editor.cb_goto(number)

    def cb_find(self, text):
        return self.current_editor.cb_find(text)

    def select_all(self):
        return self.current_editor.select_all()

    def close(self):
        pass

    @common.error_proof()
    def export_to_file(self, filename):
        current = self.current_editor
        if not isinstance(current, memedit.ChirpMemEdit):
            raise Exception(_('Only memory tabs may be exported'))
        current.export_to_file(filename)

    def update_font(self):
        for i in range(0, self._editors.PageCount):
            editor = self._editors.GetPage(i)
            editor.update_font()


class ChirpLiveEditorSet(ChirpEditorSet):
    MEMEDIT_CLS = memedit.ChirpLiveMemEdit
    SETTINGS_CLS = settingsedit.ChirpLiveSettingsEdit
    BANK_CLS = None

    @property
    def tab_name(self):
        return '%s %s@%s' % (self._radio.VENDOR,
                             self._radio.MODEL,
                             _('LIVE'))

    def __init__(self, radio, *a, **k):
        self._threads = []
        super().__init__(radio, *a, **k)

    def add_editor(self, editor, title):
        super(ChirpLiveEditorSet, self).add_editor(editor, title)
        thread = radiothread.RadioThread(editor._radio)
        thread.start()
        self._threads.append(thread)
        editor.set_radio_thread(thread)

    def close(self):
        for thread in self._threads:
            thread.end()

    @property
    def modified(self):
        return any(t.pending != 0 for t in self._threads)


class ChirpWelcomePanel(wx.Panel):
    """Fake "editorset" that just displays the welcome image."""
    def __init__(self, *a, **k):
        super(ChirpWelcomePanel, self).__init__(*a, **k)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        with importlib_resources.as_file(
            importlib_resources.files('chirp.share')
            .joinpath('welcome_screen.png')
        ) as welcome:
            bmp = wx.Bitmap(str(welcome))
        width, height = self.GetSize()
        img = wx.StaticBitmap(self, wx.ID_ANY, bmp)
        vbox.Add(img, 1, flag=wx.EXPAND)

    def close(self):
        pass

    @property
    def modified(self):
        return False

    @property
    def filename(self):
        return None


class ChirpMain(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(ChirpMain, self).__init__(*args, **kwargs)

        self.SetSize(int(CONF.get('window_w', 'state') or 1024),
                     int(CONF.get('window_h', 'state') or 768))
        if CONF.is_defined('window_x', 'state'):
            self.SetPosition((CONF.get_int('window_x', 'state'),
                              CONF.get_int('window_y', 'state')))

        self.set_icon()

        d = CONF.get('last_dir', 'state')
        if d and os.path.isdir(d):
            chirp_platform.get_platform().set_last_dir(d)

        self.SetMenuBar(self.make_menubar())

        # Stock items look good on linux, terrible on others,
        # so punt on this for the moment.
        # self.make_toolbar()

        self._editors = wx.aui.AuiNotebook(
            self,
            style=(wx.aui.AUI_NB_CLOSE_ON_ALL_TABS |
                   wx.aui.AUI_NB_TAB_MOVE |
                   wx.aui.AUI_NB_SCROLL_BUTTONS |
                   wx.aui.AUI_NB_WINDOWLIST_BUTTON))

        self._welcome_page = ChirpWelcomePanel(self._editors)
        self._editors.AddPage(self._welcome_page, _('Welcome'), select=True)

        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CLOSE, self._editor_close)
        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CHANGED,
                  self._editor_page_changed)
        self.Bind(wx.EVT_CLOSE, self._window_close)

        self.statusbar = self.CreateStatusBar(2)
        self.statusbar.SetStatusWidths([-1, 200])

        self._update_window_for_editor()

    def set_icon(self):
        if sys.platform == 'win32':
            icon = 'chirp.ico'
        else:
            icon = 'chirp.png'
        with importlib_resources.as_file(
            importlib_resources.files('chirp.share')
            .joinpath(icon)
        ) as path:
            self.SetIcon(wx.Icon(str(path)))

    @property
    def current_editorset(self):
        eset = self._editors.GetCurrentPage()
        if isinstance(eset, ChirpEditorSet):
            return eset

    @common.error_proof(errors.ImageDetectFailed, FileNotFoundError)
    def open_file(self, filename, exists=True, select=True, rclass=None):

        CSVRadio = directory.get_radio('Generic_CSV')
        if exists:
            if not os.path.exists(filename):
                raise FileNotFoundError(
                    _('File does not exist: %s') % filename)
            if rclass is None:
                radio = directory.get_radio_by_image(filename)
            else:
                radio = rclass(filename)
        else:
            radio = CSVRadio(None)

        if (not isinstance(radio, CSVRadio) or
                isinstance(radio, chirp_common.NetworkSourceRadio)):
            report.report_model(radio, 'open')

        self.adj_menu_open_recent(filename)
        editorset = ChirpEditorSet(radio, filename, self._editors)
        self.add_editorset(editorset, select=select)

    def add_editorset(self, editorset, select=True):
        if self._welcome_page:
            self._editors.RemovePage(0)
            self._welcome_page = None
        self._editors.AddPage(editorset,
                              os.path.basename(editorset.filename),
                              select=select)
        self.Bind(EVT_EDITORSET_CHANGED, self._editor_changed, editorset)
        self.Bind(common.EVT_STATUS_MESSAGE, self._editor_status, editorset)
        self._update_editorset_title(editorset)

    def add_stock_menu(self):
        stock = wx.Menu()

        try:
            user_stock_dir = chirp_platform.get_platform().config_file(
                "stock_configs")
            user_stock_confs = sorted(os.listdir(user_stock_dir))
        except FileNotFoundError:
            user_stock_confs = []
        dist_stock_confs = sorted(
            [
                conf.name for conf
                in importlib_resources.files('chirp.stock_configs').iterdir()
                if conf.is_file()
            ]
        )

        def add_stock(fn):
            submenu_item = stock.Append(wx.ID_ANY, fn)
            self.Bind(wx.EVT_MENU,
                      self._menu_open_stock_config, submenu_item)

        found = []
        for fn in user_stock_confs:
            add_stock(fn)
            found.append(os.path.basename(fn))

        stock.Append(wx.MenuItem(stock, wx.ID_SEPARATOR))

        for fn in dist_stock_confs:
            if os.path.basename(fn) not in found:
                add_stock(fn)
            else:
                LOG.info('Ignoring dist stock conf %s because same name found '
                         'in user dir', os.path.basename(fn))

        return stock

    def make_menubar(self):
        file_menu = wx.Menu()

        new_item = file_menu.Append(wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self._menu_new, new_item)

        open_item = file_menu.Append(wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self._menu_open, open_item)

        self.OPEN_STOCK_CONFIG_MENU = self.add_stock_menu()
        file_menu.AppendSubMenu(self.OPEN_STOCK_CONFIG_MENU,
                                _("Open Stock Config"))

        self.OPEN_RECENT_MENU = wx.Menu()
        last_files = [
            x for x in (CONF.get('last_open', 'state') or '').split('$')
            if x]
        self.restore_tabs_item = wx.NewId()
        if last_files:
            submenu_item = self.OPEN_RECENT_MENU.Append(
                self.restore_tabs_item,
                _('Restore %i tabs' % len(last_files)))
            submenu_item.SetAccel(wx.AcceleratorEntry(
                wx.MOD_CONTROL | wx.ACCEL_SHIFT, ord('T')))
            self.Bind(wx.EVT_MENU, self.restore_tabs, submenu_item)

        i = 0
        fn = CONF.get("recent%i" % i, "state")
        while fn:
            submenu_item = self.OPEN_RECENT_MENU.Append(wx.ID_ANY, fn)
            self.Bind(wx.EVT_MENU, self._menu_open_recent, submenu_item)
            i += 1
            if i >= KEEP_RECENT:
                break
            fn = CONF.get("recent%i" % i, "state")
        if self.OPEN_RECENT_MENU.GetMenuItemCount() <= 0:
            submenu_item = self.OPEN_RECENT_MENU.Append(wx.ID_ANY,
                                                        EMPTY_MENU_LABEL)
            submenu_item.Enable(False)
            self.Bind(wx.EVT_MENU, self._menu_open_recent, submenu_item)
        file_menu.AppendSubMenu(self.OPEN_RECENT_MENU, _('Open Recent'))

        save_item = file_menu.Append(wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self._menu_save, save_item)

        saveas_item = file_menu.Append(wx.ID_SAVEAS)
        saveas_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL | wx.ACCEL_ALT,
                                                 ord('S')))
        self.Bind(wx.EVT_MENU, self._menu_save_as, saveas_item)

        self._export_menu_item = wx.NewId()
        export_item = file_menu.Append(wx.MenuItem(file_menu,
                                                   self._export_menu_item,
                                                   _('Export to CSV')))
        export_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL, ord('E')))
        self.Bind(wx.EVT_MENU, self._menu_export, export_item)

        if CONF.get_bool('developer', 'state'):
            loadmod_item = file_menu.Append(wx.MenuItem(file_menu, wx.NewId(),
                                                        _('Load Module')))
            self.Bind(wx.EVT_MENU, self._menu_load_module, loadmod_item)

        file_menu.Append(wx.MenuItem(file_menu, wx.ID_SEPARATOR))

        print_item = file_menu.Append(wx.ID_PRINT)
        self.Bind(wx.EVT_MENU, self._menu_print, print_item)

        self._print_preview_item = wx.NewId()
        print_preview_item = wx.MenuItem(file_menu,
                                         self._print_preview_item,
                                         _('Print Preview'))
        self.Bind(wx.EVT_MENU, self._menu_print, print_preview_item)
        # Linux has integrated preview stuff, and the wx preview dialog
        # does not work well, so skip this on Linux.
        if platform.system() != 'Linux':
            file_menu.Append(print_preview_item)

        close_item = file_menu.Append(wx.ID_CLOSE)
        close_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL, ord('W')))
        self.Bind(wx.EVT_MENU, self._menu_close, close_item)

        exit_item = file_menu.Append(wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._menu_exit, exit_item)

        edit_menu = wx.Menu()

        cut_item = edit_menu.Append(wx.ID_CUT)
        self.Bind(wx.EVT_MENU, functools.partial(self._menu_copy, cut=True),
                  cut_item)

        copy_item = edit_menu.Append(wx.ID_COPY)
        self.Bind(wx.EVT_MENU, self._menu_copy, copy_item)

        paste_item = edit_menu.Append(wx.ID_PASTE)
        self.Bind(wx.EVT_MENU, self._menu_paste, paste_item)

        selall_item = edit_menu.Append(wx.ID_SELECTALL)
        self.Bind(wx.EVT_MENU, self._menu_selall, selall_item)

        delete_item = edit_menu.Append(wx.ID_DELETE)
        self.Bind(wx.EVT_MENU, self._menu_delete, delete_item)

        edit_menu.Append(wx.MenuItem(edit_menu, wx.ID_SEPARATOR))

        self._last_search_text = ''
        find_item = edit_menu.Append(wx.ID_FIND)
        self.Bind(wx.EVT_MENU, self._menu_find, find_item)

        self._find_next_item = wx.NewId()
        find_next_item = edit_menu.Append(wx.MenuItem(edit_menu,
                                                      self._find_next_item,
                                                      _('Find Next')))
        find_next_item.SetAccel(wx.AcceleratorEntry
                                (wx.MOD_CONTROL | wx.ACCEL_ALT, ord('F')))
        self.Bind(wx.EVT_MENU, self._menu_find, find_next_item,
                  self._find_next_item)

        self._goto_item = wx.NewId()
        goto_item = edit_menu.Append(wx.MenuItem(edit_menu, self._goto_item,
                                                 _('Goto')))
        goto_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL, ord('G')))
        self.Bind(wx.EVT_MENU, self._menu_goto, goto_item)

        view_menu = wx.Menu()

        self._fixed_item = wx.NewId()
        fixed_item = wx.MenuItem(view_menu, self._fixed_item,
                                 _('Use fixed-width font'),
                                 kind=wx.ITEM_CHECK)
        view_menu.Append(fixed_item)
        self.Bind(wx.EVT_MENU, self._menu_fixed_font, fixed_item)
        fixed_item.Check(CONF.get_bool('font_fixed', 'state', False))

        self._large_item = wx.NewId()
        large_item = wx.MenuItem(view_menu, self._large_item,
                                 _('Use larger font'),
                                 kind=wx.ITEM_CHECK)
        view_menu.Append(large_item)
        self.Bind(wx.EVT_MENU, self._menu_large_font, large_item)
        large_item.Check(CONF.get_bool('font_large', 'state', False))

        radio_menu = wx.Menu()

        if sys.platform == 'darwin':
            updownmod = wx.MOD_CONTROL
        else:
            updownmod = wx.ACCEL_ALT

        self._download_menu_item = wx.NewId()
        download_item = wx.MenuItem(
            radio_menu, self._download_menu_item,
            _('Download from radio'))
        download_item.SetAccel(wx.AcceleratorEntry(updownmod, ord('D')))
        self.Bind(wx.EVT_MENU, self._menu_download, download_item)
        radio_menu.Append(download_item)

        self._upload_menu_item = wx.NewId()
        upload_item = wx.MenuItem(
            radio_menu, self._upload_menu_item,
            _('Upload to radio'))
        upload_item.SetAccel(wx.AcceleratorEntry(updownmod, ord('U')))
        self.Bind(wx.EVT_MENU, self._menu_upload, upload_item)
        radio_menu.Append(upload_item)

        source_menu = wx.Menu()
        radio_menu.AppendSubMenu(source_menu, _('Query Source'))

        query_rr_item = wx.MenuItem(source_menu,
                                    wx.NewId(), 'RadioReference.com')
        self.Bind(wx.EVT_MENU, self._menu_query_rr, query_rr_item)
        source_menu.Append(query_rr_item)

        query_rb_item = wx.MenuItem(source_menu, wx.NewId(), 'RepeaterBook')
        self.Bind(wx.EVT_MENU, self._menu_query_rb, query_rb_item)
        source_menu.Append(query_rb_item)

        query_dm_item = wx.MenuItem(source_menu, wx.NewId(), 'DMR-MARC')
        self.Bind(wx.EVT_MENU, self._menu_query_dm, query_dm_item)
        source_menu.Append(query_dm_item)

        radio_menu.Append(wx.MenuItem(radio_menu, wx.ID_SEPARATOR))

        auto_edits = wx.MenuItem(radio_menu, wx.NewId(),
                                 _('Enable Automatic Edits'),
                                 kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU, self._menu_auto_edits, auto_edits)
        radio_menu.Append(auto_edits)
        auto_edits.Check(CONF.get_bool('auto_edits', 'state', True))

        select_bandplan = wx.MenuItem(radio_menu, wx.NewId(),
                                      _('Select Bandplan'))
        self.Bind(wx.EVT_MENU, self._menu_select_bandplan, select_bandplan)
        radio_menu.Append(select_bandplan)

        if CONF.get_bool('developer', 'state'):
            radio_menu.Append(wx.MenuItem(file_menu, wx.ID_SEPARATOR))

            self._reload_driver_item = wx.NewId()
            reload_drv_item = wx.MenuItem(radio_menu,
                                          self._reload_driver_item,
                                          _('Reload Driver'))
            reload_drv_item.SetAccel(
                wx.AcceleratorEntry(wx.MOD_CONTROL, ord('R')))
            self.Bind(wx.EVT_MENU, self._menu_reload_driver, reload_drv_item)
            radio_menu.Append(reload_drv_item)

            self._reload_both_item = wx.NewId()
            reload_both_item = wx.MenuItem(radio_menu,
                                           self._reload_both_item,
                                           _('Reload Driver and File'))
            reload_both_item.SetAccel(
                wx.AcceleratorEntry(
                    wx.ACCEL_ALT | wx.MOD_CONTROL,
                    ord('R')))
            self.Bind(
                wx.EVT_MENU,
                functools.partial(self._menu_reload_driver, andfile=True),
                reload_both_item)
            radio_menu.Append(reload_both_item)

            self._interact_driver_item = wx.NewId()
            interact_drv_item = wx.MenuItem(radio_menu,
                                            self._interact_driver_item,
                                            _('Interact with driver'))
            self.Bind(wx.EVT_MENU, self._menu_interact_driver,
                      interact_drv_item)
            radio_menu.Append(interact_drv_item)

        help_menu = wx.Menu()

        about_item = wx.MenuItem(help_menu, wx.NewId(), _('About'))
        self.Bind(wx.EVT_MENU, self._menu_about, about_item)
        help_menu.Append(about_item)

        developer_menu = wx.MenuItem(help_menu, wx.NewId(),
                                     _('Developer Mode'),
                                     kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._menu_developer, developer_menu),
                  developer_menu)
        help_menu.Append(developer_menu)
        developer_menu.Check(CONF.get_bool('developer', 'state'))

        reporting_menu = wx.MenuItem(help_menu, wx.NewId(),
                                     _('Reporting enabled'),
                                     kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._menu_reporting, reporting_menu),
                  reporting_menu)
        help_menu.Append(reporting_menu)
        reporting_menu.Check(not CONF.get_bool('no_report', default=False))

        if logger.Logger.instance.has_debug_log_file:
            # Only expose these debug log menu elements if we are logging to
            # a debug.log file this session.
            debug_log_menu = wx.MenuItem(help_menu, wx.NewId(),
                                         _('Open debug log'))
            self.Bind(wx.EVT_MENU, self._menu_debug_log, debug_log_menu)
            help_menu.Append(debug_log_menu)

            if platform.system() in ('Windows', 'Darwin'):
                debug_loc_menu = wx.MenuItem(help_menu, wx.NewId(),
                                             _('Show debug log location'))
                self.Bind(wx.EVT_MENU, self._menu_debug_loc, debug_loc_menu)
                help_menu.Append(debug_loc_menu)

        menu_bar = wx.MenuBar()
        menu_bar.Append(file_menu, wx.GetStockLabel(wx.ID_FILE))
        menu_bar.Append(edit_menu, wx.GetStockLabel(wx.ID_EDIT))
        menu_bar.Append(view_menu, '&' + _('View'))
        menu_bar.Append(radio_menu, '&' + _('Radio'))
        menu_bar.Append(help_menu, wx.GetStockLabel(wx.ID_HELP))

        return menu_bar

    def _menu_print(self, event):
        p = printing.MemoryPrinter(
            self,
            self.current_editorset.radio,
            self.current_editorset.current_editor)

        mems = self.current_editorset.current_editor.get_selected_memories()
        if event.GetId() == wx.ID_PRINT:
            p.print(mems)
        else:
            p.print_preview(mems)

    def make_toolbar(self):
        tb = self.CreateToolBar()

        def bm(stock):
            return wx.ArtProvider.GetBitmap(stock,
                                            wx.ART_TOOLBAR, (32, 32))

        tbopen = tb.AddTool(wx.NewId(), _('Open'), bm(wx.ART_FILE_OPEN),
                            _('Open a file'))
        tb.AddTool(wx.NewId(), _('Save'), bm(wx.ART_FILE_SAVE),
                   _('Save file'))
        tb.AddTool(wx.NewId(), _('Close'), bm(wx.ART_CLOSE),
                   _('Close file'))
        tb.AddTool(wx.NewId(), _('Download'), bm(wx.ART_GO_DOWN),
                   _('Download from radio'))
        tb.AddTool(wx.NewId(), 'Upload', bm(wx.ART_GO_UP),
                   _('Upload to radio'))

        self.Bind(wx.EVT_MENU, self._menu_open, tbopen)
        tb.Realize()

    def adj_menu_open_recent(self, filename):
        # Don't add stock config files to the recent files list
        stock_dir = chirp_platform.get_platform().config_file("stock_configs")
        this_dir = os.path.dirname(filename)
        if (stock_dir and os.path.exists(stock_dir) and
                this_dir and os.path.samefile(stock_dir, this_dir)):
            return

        # Travel the Open Recent menu looking for filename
        found_mi = None
        empty_mi = None
        for i in range(0, self.OPEN_RECENT_MENU.GetMenuItemCount()):
            menu_item = self.OPEN_RECENT_MENU.FindItemByPosition(i)
            fn = menu_item.GetItemLabelText()
            if fn == filename:
                found_mi = menu_item
            if fn == EMPTY_MENU_LABEL:
                empty_mi = menu_item

        # Move filename to top of menu or add it to top if it wasn't found
        if found_mi:
            self.OPEN_RECENT_MENU.Remove(found_mi)
            self.OPEN_RECENT_MENU.Prepend(found_mi)
        else:
            submenu_item = self.OPEN_RECENT_MENU.Prepend(wx.ID_ANY, filename)
            self.Bind(wx.EVT_MENU, self._menu_open_recent, submenu_item)

        # Get rid of the place holder used in an empty menu
        if empty_mi:
            self.OPEN_RECENT_MENU.Delete(empty_mi)

        # Trim the menu length
        if self.OPEN_RECENT_MENU.GetMenuItemCount() > KEEP_RECENT:
            for i in range(self.OPEN_RECENT_MENU.GetMenuItemCount() - 1,
                           KEEP_RECENT - 1, -1):
                extra_mi = self.OPEN_RECENT_MENU.FindItemByPosition(i)
                self.OPEN_RECENT_MENU.Delete(extra_mi)

        # Travel the Open Recent menu and save file names to config.
        for i in range(0, self.OPEN_RECENT_MENU.GetMenuItemCount()):
            if i >= KEEP_RECENT:
                break
            menu_item = self.OPEN_RECENT_MENU.FindItemByPosition(i)
            if menu_item.GetId() == self.restore_tabs_item:
                continue
            fn = menu_item.GetItemLabelText()
            CONF.set("recent%i" % i, fn, "state")
        config._CONFIG.save()

    def _editor_page_changed(self, event):
        self._editors.GetPage(event.GetSelection())
        self._update_window_for_editor()
        radio = self.current_editorset.radio
        radio_name = '%s %s%s' % (radio.VENDOR, radio.MODEL, radio.VARIANT)
        self.statusbar.SetStatusText(radio_name, i=1)

    def _editor_changed(self, event):
        self._update_editorset_title(event.editorset)
        self._update_window_for_editor()

    def _editor_status(self, event):
        # FIXME: Should probably only do this for the current editorset
        self.statusbar.SetStatusText(event.message)

    def _editor_close(self, event):
        eset = self._editors.GetPage(event.GetSelection())
        if self._prompt_to_close_editor(eset):
            eset.close()
            wx.CallAfter(self._update_window_for_editor)
        else:
            event.Veto()

    def _update_window_for_editor(self):
        eset = self.current_editorset
        can_close = False
        can_save = False
        can_saveas = False
        can_upload = False
        is_memedit = False
        is_bank = False
        CSVRadio = directory.get_radio('Generic_CSV')
        if eset is not None:
            is_live = isinstance(eset.radio, chirp_common.LiveRadio)
            is_network = isinstance(eset.radio,
                                    base.NetworkResultRadio)
            can_close = True
            can_save = eset.modified and not is_live and not is_network
            can_saveas = not is_live and not is_network
            can_upload = (not isinstance(eset.radio, CSVRadio) and
                          not isinstance(eset.radio, common.LiveAdapter) and
                          not is_live and not is_network)
            is_memedit = isinstance(eset.current_editor, memedit.ChirpMemEdit)
            is_bank = isinstance(eset.current_editor, bankedit.ChirpBankEdit)

        items = [
            (wx.ID_CLOSE, can_close),
            (wx.ID_SAVE, can_save),
            (wx.ID_SAVEAS, can_saveas),
            (self._upload_menu_item, can_upload),
            (self._goto_item, is_memedit),
            (self._find_next_item, is_memedit),
            (wx.ID_FIND, is_memedit),
            (wx.ID_PRINT, is_memedit),
            (wx.ID_DELETE, is_memedit),
            (wx.ID_CUT, is_memedit),
            (wx.ID_COPY, is_memedit),
            (wx.ID_PASTE, is_memedit),
            (wx.ID_SELECTALL, is_memedit),
            (self._print_preview_item, is_memedit),
            (self._export_menu_item, can_close),
            (self._fixed_item, is_memedit or is_bank),
            (self._large_item, is_memedit or is_bank),
        ]
        for ident, enabled in items:
            menuitem = self.GetMenuBar().FindItemById(ident)
            if menuitem:
                # Some items may not be present on all systems (i.e.
                # print preview on Linux)
                menuitem.Enable(enabled)

    def _window_close(self, event):
        for i in range(self._editors.GetPageCount()):
            editorset = self._editors.GetPage(i)
            self._editors.ChangeSelection(i)
            if not self._prompt_to_close_editor(editorset):
                if event.CanVeto():
                    event.Veto()
                return

        size = self.GetSize()
        CONF.set_int('window_w', size.GetWidth(), 'state')
        CONF.set_int('window_h', size.GetHeight(), 'state')
        pos = self.GetPosition()
        CONF.set_int('window_x', pos[0], 'state')
        CONF.set_int('window_y', pos[1], 'state')
        CONF.set('last_dir', chirp_platform.get_platform().get_last_dir(),
                 'state')

        # Make sure we call close on each editor, so it can end
        # threads and do other cleanup
        open_files = []
        for i in range(self._editors.GetPageCount()):
            e = self._editors.GetPage(i)
            if e.filename not in open_files:
                open_files.append(e.filename)
            e.close()

        CONF.set('last_open',
                 '$'.join(os.path.abspath(fn)
                          for fn in open_files if fn),
                 'state')
        config._CONFIG.save()

        self.Destroy()

    def _update_editorset_title(self, editorset):
        index = self._editors.GetPageIndex(editorset)
        self._editors.SetPageText(index, '%s%s' % (
            os.path.basename(editorset.filename),
            editorset.modified and '*' or ''))

    def _menu_new(self, event):
        self.open_file('Untitled.csv', exists=False)

    def _menu_open(self, event):
        all_extensions = ['*.img']
        formats = [_('Chirp Image Files') + ' (*.img)|*.img',
                   _('All Files') + ' (*.*)|*.*']
        for name, pattern, readonly in directory.AUX_FORMATS:
            formats.insert(1, '%s %s (%s)|%s' % (
                name, _('Files'), pattern, pattern))
            all_extensions.append(pattern)

        if CONF.get_bool('open_default_all_formats', 'prefs', True):
            i_index = 0
        else:
            i_index = len(formats)
        formats.insert(i_index,
                       (_('All supported formats|') +
                        ';'.join(all_extensions)))
        wildcard = '|'.join(formats)
        with wx.FileDialog(self, _('Open a file'),
                           chirp_platform.get_platform().get_last_dir(),
                           wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            filename = fd.GetPath()
            d = fd.GetDirectory()
            chirp_platform.get_platform().set_last_dir(d)
            CONF.set('last_dir', d, 'state')
            config._CONFIG.save()
            self.open_file(str(filename))

    def _menu_open_stock_config(self, event):
        fn = self.OPEN_STOCK_CONFIG_MENU.FindItemById(
            event.GetId()).GetItemLabelText()

        user_stock_dir = chirp_platform.get_platform().config_file(
            "stock_configs")
        user_stock_conf = os.path.join(user_stock_dir, fn)
        with importlib_resources.as_file(
            importlib_resources.files('chirp.stock_configs')
            .joinpath(fn)
        ) as path:
            dist_stock_conf = str(path)
        if os.path.exists(user_stock_conf):
            filename = user_stock_conf
        elif os.path.exists(dist_stock_conf):
            filename = dist_stock_conf
        else:
            LOG.error('Unable to find %s or %s' % (user_stock_conf,
                                                   dist_stock_conf))
            common.error_proof.show_error(
                _('Unable to find stock config %r') % fn)
            return

        self.open_file(filename)

    def restore_tabs(self, event):
        if self.OPEN_RECENT_MENU.FindItem(self.restore_tabs_item)[0]:
            self.OPEN_RECENT_MENU.Remove(self.restore_tabs_item)
        last_files = (CONF.get('last_open', 'state') or '').split('$')
        for fn in last_files:
            if fn and os.path.exists(fn):
                LOG.debug('Restoring tab for file %r' % fn)
                self.open_file(fn)
            elif fn:
                LOG.debug('Previous file %r no longer exists' % fn)
        return last_files

    def _menu_open_recent(self, event):
        filename = self.OPEN_RECENT_MENU.FindItemById(
            event.GetId()).GetItemLabelText()
        self.open_file(filename)

    def _menu_save_as(self, event):
        eset = self.current_editorset
        wildcard = (
            'CHIRP %(vendor)s %(model)s %(files)s (*.%(ext)s)|*.%(ext)s' % {
                'vendor': eset._radio.VENDOR,
                'model': eset._radio.MODEL,
                'files': _('Files'),
                'ext': eset._radio.FILE_EXTENSION})

        for name, pattern, readonly in directory.AUX_FORMATS:
            if readonly:
                continue
            if pattern in wildcard:
                continue
            if name in eset.radio.FORMATS:
                wildcard += '|%s %s (%s)|%s' % (
                    name, _('Files'), pattern, pattern)

        style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT | wx.FD_CHANGE_DIR
        default_filename = os.path.basename(eset.filename)
        with wx.FileDialog(self, _("Save file"), defaultFile=default_filename,
                           wildcard=wildcard,
                           style=style) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            filename = fd.GetPath()
            chirp_platform.get_platform().set_last_dir(
                fd.GetDirectory())
            eset.save(filename)
            self.adj_menu_open_recent(filename)
            self._update_editorset_title(eset)
            return True

    def _menu_save(self, event):
        editorset = self.current_editorset
        if not editorset.modified:
            return

        if not os.path.exists(editorset.filename):
            return self._menu_save_as(event)

        editorset.save()
        self._update_editorset_title(self.current_editorset)

    def _menu_export(self, event):
        wildcard = 'CSV %s (*.csv)|*.csv' % _('Files')
        defcsv = os.path.splitext(os.path.basename(
                self.current_editorset.filename))[0] + '.csv'
        style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT | wx.FD_CHANGE_DIR
        with wx.FileDialog(self, _('Export to CSV'), defaultFile=defcsv,
                           wildcard=wildcard, style=style) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            self.current_editorset.export_to_file(fd.GetPath())

    def _prompt_to_close_editor(self, editorset):
        """Returns True if it is okay to close the editor, False otherwise"""
        if not editorset.modified:
            return True

        answer = wx.MessageBox(
            _('%s has not been saved. Save before closing?') % (
                editorset.filename),
            _('Save before closing?'),
            wx.YES_NO | wx.YES_DEFAULT | wx.CANCEL | wx.ICON_WARNING)
        if answer == wx.NO:
            # User does not want to save, okay to close
            return True
        elif answer == wx.CANCEL:
            # User wants to cancel, not okay to close
            return False
        else:
            if not os.path.exists(editorset.filename):
                return self._menu_save_as(None)
            else:
                editorset.save()
                return True

    def _menu_close(self, event):
        if self._prompt_to_close_editor(self.current_editorset):
            self.current_editorset.close()
            self._editors.DeletePage(self._editors.GetSelection())
            self._update_window_for_editor()

    def _menu_exit(self, event):
        self.Close(True)

    @common.error_proof(RuntimeError, errors.InvalidMemoryLocation)
    @common.closes_clipboard
    def _menu_copy(self, event, cut=False):
        data = self.current_editorset.cb_copy(cut=cut)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(data)
            wx.TheClipboard.Close()
        else:
            raise RuntimeError(_('Unable to open the clipboard'))

    @common.error_proof()
    @common.closes_clipboard
    def _menu_paste(self, event):
        memdata = wx.CustomDataObject(common.CHIRP_DATA_MEMORY)
        textdata = wx.TextDataObject()
        if wx.TheClipboard.Open():
            gotchirpmem = wx.TheClipboard.GetData(memdata)
            got = wx.TheClipboard.GetData(textdata)
            wx.TheClipboard.Close()
        if gotchirpmem:
            self.current_editorset.cb_paste(memdata)
        elif got:
            self.current_editorset.cb_paste(textdata)

    def _menu_selall(self, event):
        self.current_editorset.select_all()

    def _menu_delete(self, event):
        self.current_editorset.cb_delete()

    def _menu_find(self, event):
        if event.GetId() == wx.ID_FIND:
            search = wx.GetTextFromUser(_('Find') + ':', _('Find'),
                                        self._last_search_text, self)
        elif not self._last_search_text:
            return
        else:
            search = self._last_search_text
        if search:
            self._last_search_text = search
            self.current_editorset.cb_find(search)

    def _update_font(self):
        for i in range(0, self._editors.PageCount):
            eset = self._editors.GetPage(i)
            eset.update_font()

    def _menu_fixed_font(self, event):
        menuitem = event.GetEventObject().FindItemById(event.GetId())
        CONF.set_bool('font_fixed', menuitem.IsChecked(), 'state')
        self._update_font()

    def _menu_large_font(self, event):
        menuitem = event.GetEventObject().FindItemById(event.GetId())
        CONF.set_bool('font_large', menuitem.IsChecked(), 'state')
        self._update_font()

    def _menu_goto(self, event):
        eset = self.current_editorset
        rf = eset.radio.get_features()
        l, u = rf.memory_bounds
        a = wx.GetNumberFromUser(_('Goto Memory:'), _('Number'),
                                 _('Goto Memory'),
                                 1, l, u, self)
        if a >= 0:
            eset.cb_goto(a)

    def _menu_download(self, event):
        with clone.ChirpDownloadDialog(self) as d:
            d.Centre()
            if d.ShowModal() == wx.ID_OK:
                radio = d._radio
                report.report_model(radio, 'download')
                if isinstance(radio, chirp_common.LiveRadio):
                    editorset = ChirpLiveEditorSet(radio, None, self._editors)
                else:
                    editorset = ChirpEditorSet(radio, None, self._editors)
                self.add_editorset(editorset)

    def _menu_upload(self, event):
        radio = self.current_editorset.radio
        report.report_model(radio, 'upload')
        with clone.ChirpUploadDialog(radio, self) as d:
            d.Centre()
            d.ShowModal()

    @common.error_proof()
    def _menu_reload_driver(self, event, andfile=False):
        radio = self.current_editorset.radio
        try:
            # If we were loaded from a dynamic alias in directory,
            # get the pointer to the original
            orig_rclass = radio._orig_rclass
        except AttributeError:
            orig_rclass = radio.__class__

        # Save a reference to the radio's internal mmap. If the radio does
        # anything strange or does not follow the typical convention, this
        # will not work
        mmap = radio._mmap

        # Reload the actual module
        module = sys.modules[orig_rclass.__module__]
        LOG.warning('Going to reload %s' % module)
        directory.enable_reregistrations()
        import importlib
        importlib.reload(module)

        # Grab a new reference to the updated module and pick out the
        # radio class from it.
        module = sys.modules[orig_rclass.__module__]
        rclass = getattr(module, orig_rclass.__name__)

        filename = self.current_editorset.filename
        if andfile:
            # Reload the file while creating the radio
            new_radio = rclass(filename)
        else:
            # Try to reload the driver in place, without
            # re-reading the file; mimic the file loading
            # procedure after jamming the memory back in
            new_radio = rclass(None)
            new_radio._mmap = mmap
            new_radio.process_mmap()

        # Get the currently-selected memedit row so we can re-select it
        editor_pos = self.current_editorset.current_editor.get_scroll_pos()

        # Kill the current editorset now that we know the radio loaded
        # successfully
        last_editor = self.current_editorset.current_editor_index
        self.current_editorset.close()
        self._editors.DeletePage(self._editors.GetSelection())
        self._update_window_for_editor()

        # Mimic the File->Open process to get a new editorset based
        # on our franken-radio
        editorset = ChirpEditorSet(new_radio, filename, self._editors)
        self.add_editorset(editorset, select=True)
        editorset.select_editor(index=last_editor)
        editorset.current_editor.set_scroll_pos(editor_pos)

        LOG.info('Reloaded radio driver%s in place; good luck!' % (
            andfile and ' (and file)' or ''))

    def _menu_interact_driver(self, event):
        LOG.warning('Going to interact with radio at the console')
        radio = self.current_editorset.radio
        import code
        locals = {'main': self,
                  'radio': radio}
        code.interact(banner='Locals are: %s' % (', '.join(locals.keys())),
                      local=locals)

    @common.error_proof()
    def load_module(self, filename):
        # We're in development mode, so we need to tell the directory to
        # allow a loaded module to override an existing driver, against
        # its normal better judgement
        directory.enable_reregistrations()

        self.SetBackgroundColour((0xEA, 0x62, 0x62, 0xFF))

        with open(filename) as module:
            code = module.read()
        sha = hashlib.sha256()
        sha.update(code.encode())
        LOG.info('Loading module %s SHA256 %s' % (filename, sha.hexdigest()))
        pyc = compile(code, filename, 'exec')
        # See this for why:
        # http://stackoverflow.com/questions/2904274/globals-and-locals-in-python-exec
        exec(pyc, globals(), globals())

    def _menu_load_module(self, event):
        formats = ['Python %s (*.py)|*.py' % _('Files'),
                   '%s %s (*.mod)|*.mod' % (_('Module'), _('Files'))]

        wildcard = '|'.join(formats)
        with wx.FileDialog(self, _('Open a module'),
                           chirp_platform.get_platform().get_last_dir(),
                           wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            filename = fd.GetPath()
            self.load_module(filename)

    def _menu_about(self, event):
        pyver = sys.version_info
        aboutinfo = 'CHIRP %s on Python %s wxPython %s' % (
            CHIRP_VERSION,
            '%s.%s.%s' % (pyver.major, pyver.minor, pyver.micro),
            wx.version())
        wx.MessageBox(aboutinfo, _('About CHIRP'),
                      wx.OK | wx.ICON_INFORMATION)

    def _menu_developer(self, menuitem, event):
        CONF.set_bool('developer', menuitem.IsChecked(), 'state')
        state = menuitem.IsChecked() and _('enabled') or _('disabled')
        wx.MessageBox(_('Developer state is now %s. '
                        'CHIRP must be restarted to take effect') % state,
                      _('Restart Required'), wx.OK)

    def _menu_reporting(self, menuitem, event):
        if not menuitem.IsChecked():
            r = wx.MessageBox(
                _('Reporting helps the CHIRP project know which '
                  'radio models and OS platforms to spend our limited '
                  'efforts on. We would really appreciate if you left '
                  'it enabled. Really disable reporting?'),
                _('Disable reporting'),
                wx.YES_NO | wx.ICON_WARNING | wx.NO_DEFAULT)
            if r == wx.NO:
                menuitem.Check(True)
                return

        CONF.set_bool('no_report', not menuitem.IsChecked())

    @common.error_proof()
    def _menu_debug_log(self, event):
        pf = chirp_platform.get_platform()
        src = pf.config_file('debug.log')
        dst = tempfile.NamedTemporaryFile(
            prefix='chirp_debug-',
            suffix='.txt').name
        shutil.copy(src, dst)
        wx.LaunchDefaultApplication(dst)

    @common.error_proof()
    def _menu_debug_loc(self, event):
        pf = chirp_platform.get_platform()
        src = pf.config_file('debug.log')
        dst = tempfile.NamedTemporaryFile(
            prefix='chirp_debug-',
            suffix='.txt').name
        shutil.copy(src, dst)
        system = platform.system()
        if system == 'Windows':
            wx.Execute('explorer /select, %s' % dst)
        elif system == 'Darwin':
            wx.Execute('open -R %s' % dst)
        else:
            raise Exception(_('Unable to reveal %s on this system') % dst)

    def _menu_auto_edits(self, event):
        CONF.set_bool('auto_edits', event.IsChecked(), 'state')
        LOG.debug('Set auto_edits=%s' % event.IsChecked())

    def _menu_select_bandplan(self, event):
        bandplans = bandplan.BandPlans(CONF)
        plans = sorted([(shortname, details[0])
                        for shortname, details in bandplans.plans.items()],
                       key=lambda x: x[1])
        d = wx.SingleChoiceDialog(self, _('Select a bandplan'),
                                  _('Bandplan'),
                                  [x[1] for x in plans])
        for index, (shortname, name) in enumerate(plans):
            if CONF.get_bool(shortname, 'bandplan'):
                d.SetSelection(index)
                break
        r = d.ShowModal()
        if r == wx.ID_OK:
            selected = plans[d.GetSelection()][0]
            LOG.info('Selected bandplan: %s' % selected)
            for shortname, name in plans:
                CONF.set_bool(shortname, shortname == selected, 'bandplan')

    def _do_network_query(self, query_cls):
        d = query_cls(self, title=_('Query %s') % query_cls.NAME)
        r = d.ShowModal()
        if r == wx.ID_OK:
            report.report_model(d.result_radio, 'query')
            editorset = ChirpEditorSet(d.result_radio,
                                       None, self._editors)
            self.add_editorset(editorset)

    def _menu_query_rr(self, event):
        self._do_network_query(query_sources.RRQueryDialog)

    def _menu_query_rb(self, event):
        self._do_network_query(query_sources.RepeaterBookQueryDialog)

    def _menu_query_dm(self, event):
        self._do_network_query(query_sources.DMRMARCQueryDialog)


def display_update_notice(version):
    LOG.info('Server reports %s is latest' % version)

    if version == CHIRP_VERSION:
        return

    if CONF.get_bool("skip_update_check", "state"):
        return

    if CHIRP_VERSION.endswith('dev'):
        return

    # Report new updates every three days
    intv = 3600 * 24 * 3

    if CONF.is_defined("last_update_check", "state") and \
       (time.time() - CONF.get_int("last_update_check", "state")) < intv:
        return

    CONF.set_int("last_update_check", int(time.time()), "state")

    url = 'https://chirp.danplanet.com/projects/chirp/wiki/ChirpNextBuild'
    msg = _('A new CHIRP version is available. Please visit the '
            'website as soon as possible to download it!')
    d = wx.MessageDialog(None, msg, _('New version available'),
                         style=wx.OK | wx.CANCEL | wx.ICON_INFORMATION)
    visit = d.ShowModal()
    if visit == wx.ID_OK:
        wx.MessageBox(_('Please be sure to quit CHIRP before installing '
                        'the new version!'))
        webbrowser.open(url)
