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
from importlib import resources
import logging
import os
import pickle
import platform
import sys
import time
import typing
import webbrowser


import wx
import wx.adv
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
from chirp.wxui import bugreport
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
CHIRP_TAB_DF = wx.DataFormat('x-chirp/file-tab')
ALL_MAIN_WINDOWS = []
REVEAL_STOCK_DIR = wx.NewId()


def get_stock_configs():
    default_dir = chirp_platform.get_platform().config_file(
                      "stock_configs")
    prefs_dir = CONF.get('stock_configs', 'prefs')
    return prefs_dir or default_dir


class ChirpDropTarget(wx.DropTarget):
    def __init__(self, chirpmain):
        super().__init__()
        self._main = chirpmain
        self.data = wx.DataObjectComposite()
        tab_df = wx.CustomDataObject(CHIRP_TAB_DF)
        self.data.Add(tab_df)
        self.SetDataObject(self.data)
        self.SetDefaultAction(wx.DragMove)

    def move_tab(self, source_window, index, target_index):
        LOG.debug('Moving page %i to %i', index, target_index)
        source = source_window._editors
        eset = source.GetPage(index)
        source.RemovePage(index)
        eset.Reparent(self._main._editors)
        self._main.add_editorset(eset, atindex=(
            target_index if target_index >= 0 else None))

    def handle_tab_data(self, x, y):
        tab_data = self.data.GetObject(CHIRP_TAB_DF)
        src_wid, index = pickle.loads(tab_data.GetData().tobytes())
        source_window = self._main.FindWindowById(src_wid)
        try:
            target_index, flags = self._main._editors.HitTest(wx.Point(x, y))
        except wx._core.wxAssertionError:
            # Apparently AUINotebook has no HitTest implementation on Linux
            LOG.warning('Unable to perform HitTest on target: '
                        'no reordering possible')
            if source_window is self._main:
                # Defeat drag-to-self on this platform entirely since it is
                # meaningless
                return wx.DragNone
            # Default to append since we cannot define an order
            target_index = -1
        if source_window is self._main and index == target_index:
            LOG.debug('Drag to self without reorder')
            return wx.DragNone
        self.move_tab(source_window, index, target_index)
        return wx.DragMove

    def OnData(self, x, y, defResult):
        if self.GetData():
            format = self.data.GetReceivedFormat().GetId()
            if format == CHIRP_TAB_DF.GetId():
                return self.handle_tab_data(x, y)

        return wx.DragNone

    def OnDrop(self, x, y):
        self._main.add_tab_panel.Hide()
        return True

    def OnEnter(self, x, y, defResult):
        self._main.add_tab_panel.SetSize(self._main._editors.GetSize())
        self._main.add_tab_panel.Show()
        return defResult

    def OnLeave(self):
        self._main.add_tab_panel.Hide()
        return super().OnLeave()


class ChirpEditorSet(wx.Panel):
    MEMEDIT_CLS = memedit.ChirpMemEdit
    SETTINGS_CLS = settingsedit.ChirpCloneSettingsEdit
    BANK_CLS: typing.Union[type, None] = bankedit.ChirpBankEditSync

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

        if (developer.developer_mode() and
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

    @common.error_proof()
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

    def cb_paste(self):
        return self.current_editor.cb_paste()

    def cb_delete(self):
        return self.current_editor.cb_delete()

    def cb_find(self, text):
        return self.current_editor.cb_find(text)

    def select_all(self):
        return self.current_editor.select_all()

    def close(self):
        pass

    @common.error_proof(common.ExportFailed)
    def export_to_file(self, filename):
        current = self.current_editor
        if not isinstance(current, memedit.ChirpMemEdit):
            raise Exception(_('Only memory tabs may be exported'))
        LOG.debug('Exporting to %r' % filename)
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
        try:
            self._radio.pipe.close()
        except Exception as e:
            LOG.exception('Failed to close %s: %s', self._radio.pipe, e)
        else:
            LOG.debug('Closed %s', self._radio.pipe)

    @property
    def modified(self):
        return any(t.pending != 0 for t in self._threads)


class ChirpWelcomePanel(wx.Panel):
    """Fake "editorset" that just displays the welcome image."""

    def __init__(self, *a, **k):
        super(ChirpWelcomePanel, self).__init__(*a, **k)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)

        # Search for welcome_screen_en_US, welcome_screen_en, welcome_screen
        locale = wx.App.Get()._lc.GetCanonicalName()
        locale_base_path = resources.files('chirp.share')
        welcome_file = locale_base_path.joinpath(
            'welcome_screen_%s.png' % locale)
        if not os.path.exists(welcome_file):
            welcome_file = locale_base_path.joinpath(
                'welcome_screen_%s.png' % locale[0:2])
        if not os.path.exists(welcome_file):
            welcome_file = locale_base_path.joinpath('welcome_screen.png')

        with resources.as_file(welcome_file) as welcome:
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
        try:
            x = max(0, CONF.get_int('window_x', 'state'))
            y = max(0, CONF.get_int('window_y', 'state'))
            if not ALL_MAIN_WINDOWS:
                # Only restore position for the first window of the session
                self.SetPosition((x, y))
        except TypeError:
            pass

        ALL_MAIN_WINDOWS.append(self)

        if not CONF.get_bool('agreed_to_license', 'state'):
            wx.CallAfter(self._menu_about, None)

        self.set_icon()
        self._drop_target = ChirpDropTarget(self)
        self.SetDropTarget(self._drop_target)

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
                   wx.aui.AUI_NB_SCROLL_BUTTONS |
                   wx.aui.AUI_NB_WINDOWLIST_BUTTON))

        if len(ALL_MAIN_WINDOWS) == 1:
            # Only add the welcome page to the first window opened
            welcome_page = ChirpWelcomePanel(self._editors)
            self._editors.AddPage(welcome_page, _('Welcome'), select=True)

        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CLOSE, self._editor_close)
        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CHANGED,
                  self._editor_page_changed)
        self._editors.Bind(wx.aui.EVT_AUINOTEBOOK_BEGIN_DRAG, self._tab_drag)
        self._editors.Bind(wx.aui.EVT_AUINOTEBOOK_TAB_RIGHT_DOWN,
                           self._tab_rclick)
        self.Bind(wx.EVT_CLOSE, self._window_close)

        self.statusbar = self.CreateStatusBar(2)
        self.statusbar.SetStatusWidths([-1, 200])

        self._update_window_for_editor()

        vbox = wx.BoxSizer()
        self.SetSizer(vbox)
        vbox.Add(self._editors, 1, flag=wx.EXPAND)

        self.add_tab_panel = wx.Panel(self, pos=(0, 0), size=(600, 600))
        self.add_tab_panel.Hide()

        with resources.as_file(
            resources.files('chirp.share').joinpath('plus-icon.png')
        ) as icon:
            self.add_tab_bm = wx.Bitmap(str(icon), wx.BITMAP_TYPE_ANY)

        self.add_tab_panel.Bind(wx.EVT_PAINT, self._paint_add_tab_panel)

    def _paint_add_tab_panel(self, event):
        panel = event.GetEventObject()
        dc = wx.PaintDC(panel)
        dc.SetBackground(wx.Brush("BLACK"))

        img_size = self.add_tab_bm.GetSize()
        my_size = panel.GetSize()
        x = (my_size.width // 2) - (img_size.width // 2)
        y = (my_size.height // 2) - (img_size.width // 2)

        dc.DrawBitmap(self.add_tab_bm, x, y, True)

    def _remove_welcome_page(self):
        def remove():
            for i in range(self._editors.GetPageCount()):
                if isinstance(self._editors.GetPage(i), ChirpWelcomePanel):
                    self._editors.RemovePage(i)
                    break
        wx.CallAfter(remove)

    def _tab_drag(self, event):
        event.Skip()
        d = wx.CustomDataObject(CHIRP_TAB_DF)
        index = self._editors.GetSelection()
        if isinstance(self._editors.GetPage(index), ChirpWelcomePanel):
            # Don't allow moving the welcome panels
            return
        d.SetData(pickle.dumps((self.GetId(), index)))
        data = wx.DataObjectComposite()
        data.Add(d)
        ds = wx.DropSource(self)
        ds.SetData(data)
        result = ds.DoDragDrop(wx.Drag_AllowMove)
        if result == wx.DragMove:
            LOG.debug('Target took our window')
            self._update_window_for_editor()
        else:
            LOG.debug('Target rejected our window')

    def _tab_rclick(self, event):
        selected = event.GetSelection()
        eset = self._editors.GetPage(selected)
        if isinstance(eset, ChirpWelcomePanel):
            return

        def _detach(event):
            new = ChirpMain(None, title='CHIRP')
            self._editors.RemovePage(selected)
            eset.Reparent(new._editors)
            new.add_editorset(eset)
            new.Show()

        menu = wx.Menu()
        detach = wx.MenuItem(menu, wx.ID_ANY, _('Open in new window'))
        self.Bind(wx.EVT_MENU, _detach, detach)
        menu.Append(detach)

        self.PopupMenu(menu)

    def set_icon(self):
        if sys.platform == 'win32':
            icon = 'chirp.ico'
        else:
            icon = 'chirp.png'
        with resources.as_file(
            resources.files('chirp.share').joinpath(icon)
        ) as path:
            self.SetIcon(wx.Icon(str(path)))

    @property
    def current_editorset(self):
        eset = self._editors.GetCurrentPage()
        if isinstance(eset, ChirpEditorSet):
            return eset

    def enable_bugreport(self):
        self.bug_report_item.Enable(True)

    @common.error_proof(errors.ImageDetectFailed, FileNotFoundError)
    def open_file(self, filename, exists=True, select=True, rclass=None):
        self.enable_bugreport()
        CSVRadio = directory.get_radio('Generic_CSV')
        label = _('Driver messages')
        with common.expose_logs(logging.WARNING, 'chirp.drivers', label,
                                parent=self):
            if exists:
                LOG.debug('Doing open from %r' % filename)
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

    def add_editorset(self, editorset, select=True, atindex=None):
        self._remove_welcome_page()
        if atindex is None:
            self._editors.AddPage(editorset,
                                  os.path.basename(editorset.filename),
                                  select=select)
        else:
            self._editors.InsertPage(atindex,
                                     editorset,
                                     os.path.basename(editorset.filename),
                                     select=select)
        self.Bind(EVT_EDITORSET_CHANGED, self._editor_changed, editorset)
        self.Bind(common.EVT_STATUS_MESSAGE, self._editor_status, editorset)
        self._update_editorset_title(editorset)

    def add_stock_menu(self):
        stock = wx.Menu()

        try:
            user_stock_dir = get_stock_configs()
            user_stock_confs = sorted(os.listdir(user_stock_dir))
        except FileNotFoundError:
            user_stock_confs = []
            os.makedirs(user_stock_dir, exist_ok=True)
        dist_stock_confs = sorted(
            [
                (conf.name, hashlib.md5(conf.read_bytes())) for conf
                in resources.files('chirp.stock_configs').iterdir()
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

        if user_stock_confs:
            stock.Append(wx.MenuItem(stock, wx.ID_SEPARATOR))

        if sys.platform in ('darwin', 'linux', 'win32'):
            reveal = stock.Append(REVEAL_STOCK_DIR,
                                  _('Open stock config directory'))
            self.Bind(wx.EVT_MENU, self._menu_open_stock_config, reveal)
            stock.Append(wx.MenuItem(stock, wx.ID_SEPARATOR))

        for fn, hash in dist_stock_confs:
            if os.path.basename(fn) in found:
                # Remove old stock configs that were copied to the user's
                # directory by legacy chirp.
                try:
                    user_fn = os.path.join(get_stock_configs(),
                                           os.path.basename(fn))
                    with open(user_fn, 'rb') as f:
                        user_hash = hashlib.md5(f.read())
                    if hash.digest() == user_hash.digest():
                        LOG.info('Removing stale legacy stock config %s',
                                 os.path.basename(fn))
                        os.remove(user_fn)
                        # Since we already added it to the user area, just
                        # don't add it to system this time. At next startup,
                        # it will move to the system section.
                        continue
                    else:
                        raise FileExistsError('File is changed')
                except Exception as e:
                    LOG.info('Ignoring dist stock conf %s because same name '
                             'found in user dir: %s',
                             os.path.basename(fn), e)
                    continue
            add_stock(fn)

        return stock

    def make_menubar(self):
        self.editor_menu_items = {}
        memedit_items = memedit.ChirpMemEdit.get_menu_items()
        self.editor_menu_items.update(memedit_items)

        file_menu = wx.Menu()

        new_item = file_menu.Append(wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self._menu_new, new_item)

        new_window = file_menu.Append(wx.ID_ANY, _('New Window'))
        self.Bind(wx.EVT_MENU, self._menu_new_window, new_window)
        new_window.SetAccel(
            wx.AcceleratorEntry(
                wx.MOD_CONTROL | wx.ACCEL_SHIFT, ord('N')))

        open_item = file_menu.Append(wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self._menu_open, open_item)

        self.OPEN_STOCK_CONFIG_MENU = self.add_stock_menu()
        file_menu.AppendSubMenu(self.OPEN_STOCK_CONFIG_MENU,
                                _("Open Stock Config"))

        self.OPEN_RECENT_MENU = wx.Menu()
        self.restore_tabs_item = wx.NewId()

        last_files = [
            x for x in (CONF.get('last_open', 'state') or '').split('$')
            if x]
        self.adj_menu_open_recent(None)
        if last_files:
            submenu_item = self.OPEN_RECENT_MENU.Prepend(
                self.restore_tabs_item,
                ngettext('Restore %i tab', 'Restore %i tabs', len(last_files))
                % len(last_files))
            submenu_item.SetAccel(wx.AcceleratorEntry(
                wx.MOD_CONTROL | wx.ACCEL_SHIFT, ord('T')))
            self.Bind(wx.EVT_MENU, self.restore_tabs, submenu_item)

        file_menu.AppendSubMenu(self.OPEN_RECENT_MENU, _('Open Recent'))

        save_item = file_menu.Append(wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self._menu_save, save_item)

        saveas_item = file_menu.Append(wx.ID_SAVEAS)
        saveas_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL | wx.ACCEL_ALT,
                                                 ord('S')))
        self.Bind(wx.EVT_MENU, self._menu_save_as, saveas_item)

        self._import_menu_item = wx.NewId()
        import_item = file_menu.Append(wx.MenuItem(file_menu,
                                                   self._import_menu_item,
                                                   _('Import from file...')))
        self.Bind(wx.EVT_MENU, self._menu_import, import_item)

        self._export_menu_item = wx.NewId()
        export_item = file_menu.Append(wx.MenuItem(file_menu,
                                                   self._export_menu_item,
                                                   _('Export to CSV...')))
        export_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL, ord('E')))
        self.Bind(wx.EVT_MENU, self._menu_export, export_item)

        if developer.developer_mode():
            loadmod_item = file_menu.Append(wx.MenuItem(file_menu, wx.NewId(),
                                                        _('Load Module...')))
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
        delete_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL, wx.WXK_BACK))
        self.Bind(wx.EVT_MENU, self._menu_delete, delete_item)

        edit_menu.Append(wx.MenuItem(edit_menu, wx.ID_SEPARATOR))

        self._last_search_text = ''
        find_item = edit_menu.Append(wx.ID_FIND)
        edit_menu.SetLabel(wx.ID_FIND, _('Find...'))
        find_item.SetAccel(wx.AcceleratorEntry(wx.MOD_CONTROL, ord('F')))
        self.Bind(wx.EVT_MENU, self._menu_find, find_item)

        if platform.system() == 'Windows':
            findnextacc = wx.AcceleratorEntry()
            findnextacc.FromString('F3')
        else:
            findnextacc = wx.AcceleratorEntry(wx.MOD_CONTROL | wx.ACCEL_ALT,
                                              ord('F'))

        self._find_next_item = wx.NewId()
        find_next_item = edit_menu.Append(wx.MenuItem(edit_menu,
                                                      self._find_next_item,
                                                      _('Find Next')))
        find_next_item.SetAccel(findnextacc)
        self.Bind(wx.EVT_MENU, self._menu_find, find_next_item,
                  self._find_next_item)

        edit_menu.Append(wx.MenuItem(edit_menu, wx.ID_SEPARATOR))

        for item in memedit_items[common.EditorMenuItem.MENU_EDIT]:
            edit_menu.Append(item)
            self.Bind(wx.EVT_MENU, self.do_editor_callback, item)
            item.add_menu_callback()

        view_menu = wx.Menu()

        for item in memedit_items[common.EditorMenuItem.MENU_VIEW]:
            view_menu.Append(item)
            self.Bind(wx.EVT_MENU, self.do_editor_callback, item)
            item.add_menu_callback()

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

        restore_tabs = wx.MenuItem(view_menu, wx.NewId(),
                                   _('Restore tabs on start'),
                                   kind=wx.ITEM_CHECK)
        view_menu.Append(restore_tabs)
        self.Bind(wx.EVT_MENU, self._menu_restore_tabs, restore_tabs)
        restore_tabs.Check(CONF.get_bool('restore_tabs', 'prefs', False))

        lang_item = wx.MenuItem(view_menu, wx.NewId(),
                                _('Language') + '...')
        self.Bind(wx.EVT_MENU, self._menu_language, lang_item)
        view_menu.Append(lang_item)

        radio_menu = wx.Menu()

        if sys.platform == 'darwin':
            updownmod = wx.MOD_CONTROL
        else:
            updownmod = wx.ACCEL_ALT

        self._download_menu_item = wx.NewId()
        download_item = wx.MenuItem(
            radio_menu, self._download_menu_item,
            _('Download from radio...'))
        download_item.SetAccel(wx.AcceleratorEntry(updownmod, ord('D')))
        self.Bind(wx.EVT_MENU, self._menu_download, download_item)
        radio_menu.Append(download_item)

        self._upload_menu_item = wx.NewId()
        upload_item = wx.MenuItem(
            radio_menu, self._upload_menu_item,
            _('Upload to radio...'))
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

        query_prznet_item = wx.MenuItem(source_menu, wx.NewId(),
                                        'przemienniki.net')
        self.Bind(wx.EVT_MENU, self._menu_query_prznet, query_prznet_item)
        source_menu.Append(query_prznet_item)

        query_przeu_item = wx.MenuItem(source_menu, wx.NewId(),
                                       'przemienniki.eu')
        self.Bind(wx.EVT_MENU, self._menu_query_przeu, query_przeu_item)
        source_menu.Append(query_przeu_item)

        radio_menu.Append(wx.MenuItem(radio_menu, wx.ID_SEPARATOR))

        auto_edits = wx.MenuItem(radio_menu, wx.NewId(),
                                 _('Enable Automatic Edits'),
                                 kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU, self._menu_auto_edits, auto_edits)
        radio_menu.Append(auto_edits)
        auto_edits.Check(CONF.get_bool('auto_edits', 'state', True))

        select_bandplan = wx.MenuItem(radio_menu, wx.NewId(),
                                      _('Select Bandplan...'))
        self.Bind(wx.EVT_MENU, self._menu_select_bandplan, select_bandplan)
        radio_menu.Append(select_bandplan)

        if developer.developer_mode():
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
        else:
            self._reload_both_item = None
            self._reload_driver_item = None
            self._interact_driver_item = None

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
        developer_menu.Check(developer.developer_mode())

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

        backup_loc_menu = wx.MenuItem(help_menu, wx.NewId(),
                                      _('Show image backup location'))
        self.Bind(wx.EVT_MENU, self._menu_backup_loc, backup_loc_menu)
        help_menu.Append(backup_loc_menu)

        lmfi_menu = wx.MenuItem(help_menu, wx.NewId(),
                                _('Load module from issue...'))
        self.Bind(wx.EVT_MENU, self._menu_load_from_issue, lmfi_menu)
        help_menu.Append(lmfi_menu)

        self.bug_report_item = wx.MenuItem(
            help_menu, wx.NewId(),
            _('Report or update a bug...'))
        self.Bind(wx.EVT_MENU,
                  functools.partial(bugreport.do_bugreport, self),
                  self.bug_report_item)
        help_menu.Append(self.bug_report_item)
        self.bug_report_item.Enable(False)

        menu_bar = wx.MenuBar()
        menu_bar.Append(file_menu, wx.GetStockLabel(wx.ID_FILE))
        menu_bar.Append(edit_menu, wx.GetStockLabel(wx.ID_EDIT))
        menu_bar.Append(view_menu, '&' + _('View'))
        menu_bar.Append(radio_menu, '&' + _('Radio'))
        menu_bar.Append(help_menu, _('Help'))

        return menu_bar

    def do_editor_callback(self, event):
        menu = event.GetEventObject()
        item = menu.FindItemById(event.GetId())
        item.editor_callback(self.current_editorset.current_editor, event)

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
        """Update the "open recent" menu

        If filename is passed, arrange for it to be the most-recent recent
        file. Otherwise just synchronize config and the submenu state.
        """
        if filename:
            # Don't persist template names that have not been saved or do not
            # exist.
            if not os.path.exists(filename):
                LOG.debug('Ignoring recent file %s', filename)
                return
            # Don't add stock config files to the recent files list
            stock_dir = get_stock_configs()
            this_dir = os.path.dirname(filename)
            if (stock_dir and os.path.exists(stock_dir) and
                    this_dir and os.path.samefile(stock_dir, this_dir)):
                return

        # Make a list of recent files in config
        recent = [CONF.get('recent%i' % i, 'state')
                  for i in range(KEEP_RECENT)
                  if CONF.get('recent%i' % i, 'state')]
        while filename in recent:
            # The old algorithm could have dupes, so keep looking and
            # cleaning until they're gone
            LOG.debug('File exists in recent, moving to front')
            recent.remove(filename)
        if filename:
            recent.insert(0, filename)
        recent = recent[:KEEP_RECENT]
        LOG.debug('Recent is now %s' % recent)

        # Update and clean config
        for i in range(KEEP_RECENT):
            try:
                CONF.set('recent%i' % i, recent[i], 'state')
            except IndexError:
                # Clean higher-order entries if they exist
                if CONF.is_defined('recent%i' % i, 'state'):
                    CONF.remove_option('recent%i' % i, 'state')
        config._CONFIG.save()

        # Clear the menu
        while self.OPEN_RECENT_MENU.GetMenuItemCount():
            self.OPEN_RECENT_MENU.Delete(
                self.OPEN_RECENT_MENU.FindItemByPosition(0))

        # Update the menu to match our list
        for i, fn in enumerate(recent):
            mi = self.OPEN_RECENT_MENU.Append(wx.ID_ANY, fn.replace('&', '&&'))
            self.Bind(wx.EVT_MENU, self._menu_open_recent, mi)

    def _editor_page_changed(self, event):
        self._editors.GetPage(event.GetSelection())
        self._update_window_for_editor()

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
        can_edit = False
        is_memedit = False
        is_bank = False
        if eset is not None:
            is_live = isinstance(eset.radio, chirp_common.LiveRadio)
            is_network = isinstance(eset.radio,
                                    base.NetworkResultRadio)
            can_close = True
            can_save = eset.modified and not is_live and not is_network
            can_saveas = not is_live and not is_network
            can_upload = True
            is_memedit = isinstance(eset.current_editor, memedit.ChirpMemEdit)
            is_bank = isinstance(eset.current_editor, bankedit.ChirpBankEdit)
            can_edit = not is_network
            self.SetTitle('CHIRP (%s)' % os.path.basename(eset.filename))
        else:
            self.SetTitle('CHIRP')

        if self.current_editorset:
            radio = self.current_editorset.radio
            radio_name = '%s %s' % (radio.VENDOR, radio.MODEL)
            self.statusbar.SetStatusText(radio_name, i=1)
        else:
            self.statusbar.SetStatusText('', i=1)

        items = [
            (wx.ID_CLOSE, can_close),
            (wx.ID_SAVE, can_save),
            (wx.ID_SAVEAS, can_saveas),
            (self._upload_menu_item, can_upload),
            (self._find_next_item, is_memedit),
            (wx.ID_FIND, is_memedit),
            (wx.ID_PRINT, is_memedit),
            (wx.ID_DELETE, is_memedit and can_edit),
            (wx.ID_CUT, is_memedit and can_edit),
            (wx.ID_COPY, is_memedit),
            (wx.ID_PASTE, is_memedit and can_edit),
            (wx.ID_SELECTALL, is_memedit),
            (self._print_preview_item, is_memedit),
            (self._export_menu_item, can_close),
            (self._fixed_item, is_memedit or is_bank),
            (self._large_item, is_memedit or is_bank),
            (self._reload_driver_item, can_saveas),
            (self._reload_both_item, can_saveas),
            (self._interact_driver_item, can_close),
            (self._import_menu_item, is_memedit and can_edit)
        ]
        for ident, enabled in items:
            if ident is None:
                continue
            menuitem = self.GetMenuBar().FindItemById(ident)
            if menuitem:
                # Some items may not be present on all systems (i.e.
                # print preview on Linux)
                menuitem.Enable(enabled)

        for menu, items in self.editor_menu_items.items():
            for item in items:
                editor_match = (
                    eset and
                    isinstance(eset.current_editor, item.editor_class) or
                    False)
                item.Enable(editor_match)

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

        ALL_MAIN_WINDOWS.remove(self)
        self.Destroy()

    def _update_editorset_title(self, editorset):
        index = self._editors.GetPageIndex(editorset)
        self._editors.SetPageText(index, '%s%s' % (
            os.path.basename(editorset.filename),
            editorset.modified and '*' or ''))

    def _menu_new(self, event):
        self.open_file('Untitled.csv', exists=False)

    def _do_open(self):
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
            return str(filename)

    def _menu_open(self, event):
        filename = self._do_open()
        if filename is not None:
            self.open_file(filename)

    @common.error_proof(FileNotFoundError)
    def _menu_open_stock_config(self, event):
        if event.GetId() == REVEAL_STOCK_DIR:
            common.reveal_location(get_stock_configs())
            return

        fn = self.OPEN_STOCK_CONFIG_MENU.FindItemById(
            event.GetId()).GetItemLabelText()

        user_stock_dir = get_stock_configs()
        user_stock_conf = os.path.join(user_stock_dir, fn)
        with resources.as_file(
            resources.files('chirp.stock_configs').joinpath(fn)
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
            self._update_window_for_editor()
            return True

    def _menu_save(self, event):
        editorset = self.current_editorset
        if not editorset.modified:
            return

        if not os.path.exists(editorset.filename):
            return self._menu_save_as(event)

        editorset.save()
        self._update_editorset_title(self.current_editorset)

    @common.error_proof(errors.ImageDetectFailed, FileNotFoundError)
    def _menu_import(self, event):
        filename = self._do_open()
        if filename is None:
            return
        d = wx.MessageDialog(
            self,
            _('The recommended procedure for importing memories is to open '
              'the source file and copy/paste memories from it into your '
              'target image. If you continue with this import function, CHIRP '
              'will replace all memories in your currently-open file with '
              'those in %(file)s. Would you like to open this file to '
              'copy/paste memories across, or proceed with the import?') % {
                  'file': os.path.basename(filename)},
            _('Import not recommended'),
            wx.ICON_WARNING | wx.YES_NO | wx.CANCEL | wx.NO_DEFAULT)
        d.SetYesNoLabels(_('Import'), _('Open'))
        r = d.ShowModal()
        if r == wx.ID_YES:
            with common.expose_logs(logging.WARNING, 'chirp.drivers',
                                    _('Import messages'), parent=self):
                LOG.debug('Doing import from %r' % filename)
                radio = directory.get_radio_by_image(filename)
                self.current_editorset.current_editor.memedit_import_all(radio)
        elif r == wx.ID_NO:
            self.open_file(filename)
        else:
            return

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

        if isinstance(editorset, ChirpLiveEditorSet):
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
        for w in list(ALL_MAIN_WINDOWS):
            w.Close(True)

    @common.error_proof(RuntimeError, errors.InvalidMemoryLocation)
    def _menu_copy(self, event, cut=False):
        try:
            self.current_editorset.cb_copy(cut=cut)
        except NotImplementedError:
            LOG.warning('Attempt to cut/copy from %s not supported',
                        self.current_editorset.current_editor)

    @common.error_proof()
    def _menu_paste(self, event):
        try:
            self.current_editorset.cb_paste()
        except NotImplementedError:
            LOG.warning('Attempt to paste to %s not supported',
                        self.current_editorset.current_editor)

    def _menu_selall(self, event):
        self.current_editorset.select_all()

    def _menu_delete(self, event):
        self.current_editorset.cb_delete()

    def _menu_new_window(self, event):
        new = ChirpMain(None, title='CHIRP')
        new.Show()

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

    def _menu_restore_tabs(self, event):
        menuitem = event.GetEventObject().FindItemById(event.GetId())
        CONF.set_bool('restore_tabs', menuitem.IsChecked(), 'prefs')

    @common.error_proof()
    def _menu_language(self, event):
        def fmt_lang(lang):
            return '%s - %s' % (lang.DescriptionNative,
                                lang.Description.split(' ')[0])

        trans = wx.Translations.Get()
        langs = {fmt_lang(wx.Locale.FindLanguageInfo(code)): code
                 for code in trans.GetAvailableTranslations('CHIRP')
                 if code != 'messages'}
        # This is stupid, but wx.GetSingleChoice does not honor the width
        # parameter. But, we can pad out the automatic selection to get some
        # extra padding in the dialog since we don't otherwise index it.
        choices = ([_('Automatic from system') + ' ' * 30] +
                   sorted(langs.keys(), key=str.casefold))
        try:
            current = wx.Locale.FindLanguageInfo(
                CONF.get('force_language', 'prefs'))
            initial = choices.index(fmt_lang(current))
        except TypeError:
            # Unset in the config (i.e. None)
            initial = 0
        except IndexError:
            LOG.debug('Unable to find current language selection; '
                      'defaulting to auto')
            initial = 0

        choice = wx.GetSingleChoice(_('Select Language'), _('Language'),
                                    choices, parent=self,
                                    initialSelection=initial)
        if not choice:
            return

        try:
            LOG.debug('User chose override language %r (%r)',
                      choice, langs[choice])
            CONF.set('force_language', langs[choice], 'prefs')
        except KeyError:
            LOG.debug('User chose automatic language')
            CONF.remove_option('force_language', 'prefs')

        if initial != choices.index(choice):
            wx.MessageBox(_('CHIRP must be restarted for the new selection '
                            'to take effect'),
                          _('Restart Required'))

    def _make_backup(self, radio, backup_type):
        if not isinstance(radio, chirp_common.CloneModeRadio):
            LOG.debug('Not backing up %s' % radio)
            return
        backup_dir = chirp_platform.get_platform().config_file('backups')
        now = datetime.datetime.now()
        backup_fn = os.path.join(backup_dir,
                                 '%s_%s_%s' % (directory.radio_class_id(
                                               radio.__class__),
                                               backup_type,
                                               now.strftime(
                                                   '%Y%m%dT%H%M%S.img')))
        try:
            os.makedirs(backup_dir, exist_ok=True)
            radio.save(backup_fn)
            LOG.info('Saved %s backup to %s', backup_type, backup_fn)
        except Exception as e:
            LOG.warning('Failed to backup %s %s: %s', backup_type, radio, e)
            return

        try:
            keep_days = CONF.get_int('keep_backups_days', 'prefs')
        except TypeError:
            keep_days = 365
        try:
            files = os.listdir(backup_dir)
            bydate = [(os.stat(os.path.join(backup_dir, f)).st_mtime, f)
                      for f in files]
            now = time.time()
            for mtime, fn in sorted(bydate):
                age = (now - mtime) // 86400
                if keep_days > 0 and age > keep_days:
                    os.remove(os.path.join(backup_dir, fn))
                    LOG.warning('Pruned backup %s older than %i days',
                                fn, keep_days)
                elif age + 30 > keep_days:
                    LOG.info('Backup %s will be pruned soon', fn)
                else:
                    break
        except Exception as e:
            LOG.exception('Failed to prune: %s' % e)

        return backup_fn

    def _menu_download(self, event):
        self.enable_bugreport()
        with clone.ChirpDownloadDialog(self) as d:
            d.Centre()
            if d.ShowModal() == wx.ID_OK:
                radio = d._radio
                self._make_backup(radio, 'download')
                report.report_model(radio, 'download')
                if isinstance(radio, chirp_common.LiveRadio):
                    editorset = ChirpLiveEditorSet(radio, None, self._editors)
                else:
                    editorset = ChirpEditorSet(radio, None, self._editors)
                self.add_editorset(editorset)

    def _menu_upload(self, event):
        radio = self.current_editorset.radio
        fn = self._make_backup(radio, 'upload')
        report.report_model(radio, 'upload')
        CSVRadio = directory.get_radio('Generic_CSV')

        if isinstance(radio, chirp_common.LiveRadio):
            msg = _('This is a live-mode radio, which means changes are '
                    'sent to the radio in real-time as you make them. Upload '
                    'is not necessary!')
            d = wx.MessageDialog(self, msg, _('Live Radio'),
                                 wx.ICON_INFORMATION)
        elif isinstance(radio, (CSVRadio, base.NetworkResultRadio)):
            msg = _('This is a radio-independent file and cannot be uploaded '
                    'directly to a radio. Open a radio image (or download one '
                    'from a radio) and then copy/paste items from this tab '
                    'into that one in order to upload')
            d = wx.MessageDialog(self, msg, _('Unable to upload this file'),
                                 wx.ICON_INFORMATION)
        else:
            d = clone.ChirpUploadDialog(radio, self)

        d.Centre()
        r = d.ShowModal()
        if r != wx.ID_OK:
            LOG.info('Removing un-uploaded backup %s', fn)
            try:
                os.remove(fn)
            except Exception:
                pass

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
        if hasattr(module, '_was_loaded'):
            LOG.warning('Reloading loaded module %s' % module)
            self.load_module(module.__file__)
        else:
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
        radio = self.current_editorset.current_editor.radio
        import code
        locals = {'main': self,
                  'radio': radio}
        if self.current_editorset.radio != radio:
            locals['parent_radio'] = self.current_editorset.radio
        code.interact(banner='Locals are: %s' % (', '.join(locals.keys())),
                      local=locals)

    @common.error_proof()
    def load_module(self, filename):
        # We're in development mode, so we need to tell the directory to
        # allow a loaded module to override an existing driver, against
        # its normal better judgement
        directory.enable_reregistrations()
        self.SetTitle('CHIRP **%s**' % _('Module Loaded'))

        self.SetBackgroundColour((0xEA, 0x62, 0x62, 0xFF))

        with open(filename, 'rb') as module:
            code = module.read()
        sha = hashlib.sha256()
        sha.update(code)
        LOG.info('Loading module %s SHA256 %s' % (filename, sha.hexdigest()))

        import importlib.util
        import sys
        modname = 'chirp.loaded.%s' % os.path.splitext(
            os.path.basename(filename))[0]

        spec = importlib.util.spec_from_file_location(modname, filename)
        module = importlib.util.module_from_spec(spec)
        module._was_loaded = True
        sys.modules[modname] = module
        try:
            spec.loader.exec_module(module)
            return True
        except Exception as e:
            LOG.error('Failed to load module: %s' % e)
            raise Exception(_('Invalid or unsupported module file'))

    def _menu_load_module(self, event):
        formats = ['Python %s (*.py)|*.py' % _('Files'),
                   '%s %s (*.mod)|*.mod' % (_('Module'), _('Files'))]

        r = wx.MessageDialog(self,
                             _('Loading modules can be extremely dangerous, '
                               'leading to damage to your computer, radio, '
                               'or both. NEVER load a module from a source '
                               'you do not trust, and especially not from '
                               'anywhere other than the main CHIRP website '
                               '(chirpmyradio.com). Loading a module from '
                               'another source is akin to giving them direct '
                               'access to your computer and everything on '
                               'it! Proceed despite this risk?'),
                             'Warning',
                             wx.ICON_WARNING | wx.YES_NO)
        if r.ShowModal() != wx.ID_YES:
            return

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
        d = wx.Dialog(self, title=_('About CHIRP'))
        d.SetSize((500, 400))
        vbox = wx.BoxSizer(wx.VERTICAL)
        d.SetSizer(vbox)

        label = wx.StaticText(d, label='CHIRP %s' % CHIRP_VERSION)
        label.SetFont(label.GetFont().Scale(2))
        vbox.Add(label, 0,
                 border=10,
                 flag=wx.ALIGN_CENTER | wx.ALL)

        details = ('Python %s.%s.%s' % (pyver.major, pyver.minor, pyver.micro),
                   'wxPython %s' % wx.version())
        for detail in details:
            label = wx.StaticText(d, label=detail)
            vbox.Add(label, 0,
                     border=10,
                     flag=wx.ALIGN_CENTER)

        license_link = wx.adv.HyperlinkCtrl(
            d, label=_('Click here for full license text'),
            url=('https://www.chirpmyradio.com/projects/chirp/repository/'
                 'github/revisions/master/entry/COPYING'))
        vbox.Add(license_link, border=10, flag=wx.ALL | wx.ALIGN_CENTER)

        licheader = """
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details."""

        lic = wx.TextCtrl(
            d, value=licheader.strip(),
            style=wx.TE_WORDWRAP | wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(lic, border=10, flag=wx.ALL | wx.EXPAND, proportion=1)

        license_approved = CONF.get_bool('agreed_to_license', 'state')

        if not license_approved:
            buttons = wx.OK | wx.CANCEL
        else:
            buttons = wx.OK
        bs = d.CreateButtonSizer(buttons)
        vbox.Add(bs, border=10, flag=wx.ALL)
        if not license_approved:
            d.FindWindowById(wx.ID_OK).SetLabel(_('Agree'))
            d.FindWindowById(wx.ID_CANCEL).SetLabel(_('Close'))
        d.Center()
        r = d.ShowModal()
        if r == wx.ID_OK:
            LOG.debug('User approved license')
            CONF.set_bool('agreed_to_license', True, 'state')
        else:
            LOG.debug('User did not approve license - exiting')
            self.Close()

    def _menu_developer(self, menuitem, event):
        developer.developer_mode(menuitem.IsChecked())
        state = menuitem.IsChecked() and _('enabled') or _('disabled')
        if menuitem.IsChecked():
            msg = _(
                'Please note that developer mode is intended for use '
                'by developers of the CHIRP project, or under the '
                'direction of a developer. It enables behaviors and '
                'functions that can damage your computer and your '
                'radio if not used with EXTREME care. You have been '
                'warned! Proceed anyway?')
            d = wx.MessageDialog(self, msg, _('Danger Ahead'),
                                 style=wx.ICON_WARNING | wx.YES_NO)
            if d.ShowModal() != wx.ID_YES:
                menuitem.Check(False)
                return

        wx.MessageBox(_('Developer state is now %s. '
                        'CHIRP must be restarted to take effect') % state,
                      _('Restart Required'), wx.OK)
        LOG.info('User set developer mode to %s', menuitem.IsChecked())

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
        dst = common.temporary_debug_log()
        wx.LaunchDefaultApplication(dst)

    @common.error_proof()
    def _menu_debug_loc(self, event):
        dst = common.temporary_debug_log()
        common.reveal_location(dst)

    @common.error_proof()
    def _menu_backup_loc(self, event):
        backup_dir = chirp_platform.get_platform().config_file('backups')

        # Backup directory may not exist if no backup has been made
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except Exception as e:
            LOG.warning('Failed to create backup directory %s: %s' %
                        (backup_dir, e))
            return

        common.reveal_location(backup_dir)

    @common.error_proof()
    def _menu_load_from_issue(self, event):
        if self.current_editorset:
            r = wx.MessageBox(
                _('Loading a module will not affect open tabs. '
                  'It is recommended (unless instructed '
                  'otherwise) to close all tabs before loading '
                  'a module.'),
                _('Warning'),
                wx.ICON_WARNING | wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT)
            if r == wx.CANCEL:
                return
        module = developer.IssueModuleLoader(self).run()
        if module:
            if self.load_module(module):
                wx.MessageBox(_('Module loaded successfully'),
                              _('Success'),
                              wx.ICON_INFORMATION)

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
        self.enable_bugreport()
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

    def _menu_query_prznet(self, event):
        self._do_network_query(query_sources.PrzemiennikiNetQueryDialog)

    def _menu_query_przeu(self, event):
        self._do_network_query(query_sources.PrzemiennikiEuQueryDialog)


def display_update_notice(version):
    LOG.info('Server reports %s is latest' % version)

    if version == CHIRP_VERSION:
        return

    if CONF.get_bool("skip_update_check", "state"):
        return

    if CHIRP_VERSION.endswith('dev'):
        return

    # Report new updates occasionally
    intv = 3600 * 24 * 7

    if CONF.is_defined("last_update_check", "state") and \
       (time.time() - CONF.get_int("last_update_check", "state")) < intv:
        return

    CONF.set_int("last_update_check", int(time.time()), "state")

    url = 'https://chirpmyradio.com'
    msg = _('A new CHIRP version is available. Please visit the '
            'website as soon as possible to download it!')
    d = wx.MessageDialog(None, msg, _('New version available'),
                         style=wx.OK | wx.CANCEL | wx.ICON_INFORMATION)
    visit = d.ShowModal()
    if visit == wx.ID_OK:
        wx.MessageBox(_('Please be sure to quit CHIRP before installing '
                        'the new version!'))
        webbrowser.open(url)
