import datetime
import functools
import logging
import os
import sys

import wx
import wx.aui
import wx.lib.newevent

from chirp import bandplan
from chirp import chirp_common
from chirp import directory
from chirp.drivers import icf
from chirp import platform
from chirp.ui import config
from chirp.wxui import common
from chirp.wxui import clone
from chirp.wxui import developer
from chirp.wxui import memedit
from chirp.wxui import query_sources
from chirp.wxui import radiothread
from chirp.wxui import settingsedit
from chirp import CHIRP_VERSION

from fnmatch import fnmatch

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

    @property
    def tab_name(self):
        return '%s.%s' % (self.default_filename,
                          self._radio.FILE_EXTENSION)

    def add_editor(self, editor, title):
        self._editors.AddPage(editor, title)
        self.Bind(common.EVT_STATUS_MESSAGE, self._editor_status, editor)

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

        self._editors = wx.Notebook(self, style=wx.NB_TOP)

        self._editors.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGING,
                           self._editor_selected)

        sizer = wx.BoxSizer()
        sizer.Add(self._editors, 1, wx.EXPAND)
        self.SetSizer(sizer)

        features = radio.get_features()

        parent_radio = radio
        if features.has_sub_devices:
            radios = radio.get_sub_devices()
            format = 'Memories (%(variant)s)'
        else:
            radios = [radio]
            format = 'Memories'

        for radio in radios:
            edit = self.MEMEDIT_CLS(radio, self._editors)
            self.add_editor(edit, format % {'variant': radio.VARIANT})
            edit.refresh()
            self.Bind(common.EVT_EDITOR_CHANGED, self._editor_changed)

        if features.has_settings:
            settings = self.SETTINGS_CLS(parent_radio, self._editors)
            self.add_editor(settings, 'Settings')

        if (CONF.get_bool('developer', 'state') and
                not isinstance(radio, chirp_common.LiveRadio)):
            browser = developer.ChirpRadioBrowser(parent_radio, self._editors)
            self.add_editor(browser, 'Browser')

    def _editor_changed(self, event):
        self._modified = True
        wx.PostEvent(self, EditorSetChanged(self.GetId(), editorset=self))

    def _editor_selected(self, event):
        page_index = event.GetSelection()
        page = self._editors.GetPage(page_index)
        page.selected()

    def save(self, filename=None):
        if filename is None:
            filename = self.filename
        LOG.debug('Saving to %s' % filename)
        self._radio.save(filename)
        self._filename = filename
        self._modified = False
        # FIXME
        self._editors.GetPage(1).saved()

    @property
    def filename(self):
        return self._filename

    @property
    def modified(self):
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

    def select_editor(self, index):
        self._editors.SetSelection(index)

    def cb_copy(self, cut=False):
        return self.current_editor.cb_copy(cut=cut)

    def cb_paste(self, data):
        return self.current_editor.cb_paste(data)

    def select_all(self):
        return self.current_editor.select_all()

    def close(self):
        pass


class ChirpLiveEditorSet(ChirpEditorSet):
    MEMEDIT_CLS = memedit.ChirpLiveMemEdit
    SETTINGS_CLS = settingsedit.ChirpLiveSettingsEdit

    @property
    def tab_name(self):
        return '%s %s@LIVE' % (self._radio.VENDOR,
                               self._radio.MODEL)

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


class ChirpMain(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(ChirpMain, self).__init__(*args, **kwargs)

        self.SetSize(int(CONF.get('window_w', 'state') or 1024),
                     int(CONF.get('window_h', 'state') or 768))

        d = CONF.get('last_dir', 'state')
        if d and os.path.isdir(d):
            platform.get_platform().set_last_dir(d)

        self.SetMenuBar(self.make_menubar())

        # Stock items look good on linux, terrible on others,
        # so punt on this for the moment.
        # self.make_toolbar()

        self._editors = wx.aui.AuiNotebook(
            self,
            style=wx.aui.AUI_NB_CLOSE_ON_ALL_TABS | wx.aui.AUI_NB_TAB_MOVE)
        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CLOSE, self._editor_close)
        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CHANGED,
                  self._editor_page_changed)
        self.Bind(wx.EVT_CLOSE, self._window_close)

        self.statusbar = self.CreateStatusBar(2)
        self.statusbar.SetStatusWidths([-1, 200])

        self._update_window_for_editor()

    @property
    def current_editorset(self):
        return self._editors.GetCurrentPage()

    def open_file(self, filename, exists=True, select=True):

        if exists:
            radio = directory.get_radio_by_image(filename)
        else:
            CSVRadio = directory.get_radio('Generic_CSV')
            radio = CSVRadio(None)

        self.adj_menu_open_recent(filename)
        editorset = ChirpEditorSet(radio, filename, self._editors)
        self.add_editorset(editorset, select=select)

    def add_editorset(self, editorset, select=True):
        self._editors.AddPage(editorset,
                              os.path.basename(editorset.filename),
                              select=select)
        self.Bind(EVT_EDITORSET_CHANGED, self._editor_changed, editorset)
        self.Bind(common.EVT_STATUS_MESSAGE, self._editor_status, editorset)
        self._update_editorset_title(editorset)

    def make_menubar(self):
        file_menu = wx.Menu()

        new_item = file_menu.Append(wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self._menu_new, new_item)

        open_item = file_menu.Append(wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self._menu_open, open_item)

        stock_dir = platform.get_platform().config_file("stock_configs")
        sconfigs = []
        if os.path.isdir(stock_dir):
            for fn in os.listdir(stock_dir):
                if fnmatch(fn, "*.csv"):
                    config, ext = os.path.splitext(fn)
                    sconfigs.append(config)
            sconfigs.sort()
            if len(sconfigs):
                self.OPEN_STOCK_CONFIG_MENU = wx.Menu()
                for fn in sconfigs:
                    submenu_item = self.OPEN_STOCK_CONFIG_MENU.Append(
                                       wx.ID_ANY, fn)
                    self.Bind(wx.EVT_MENU,
                              self._menu_open_stock_config, submenu_item)
                file_menu.AppendSubMenu(self.OPEN_STOCK_CONFIG_MENU,
                                        "Open Stock Config")

        self.OPEN_RECENT_MENU = wx.Menu()
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
        file_menu.AppendSubMenu(self.OPEN_RECENT_MENU, 'Open Recent')

        save_item = file_menu.Append(wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self._menu_save, save_item)

        save_item = file_menu.Append(wx.ID_SAVEAS)
        self.Bind(wx.EVT_MENU, self._menu_save_as, save_item)

        file_menu.Append(wx.MenuItem(file_menu, wx.ID_SEPARATOR))

        close_item = file_menu.Append(wx.ID_CLOSE)
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

        radio_menu = wx.Menu()

        self._download_menu_item = wx.NewId()
        download_item = wx.MenuItem(radio_menu, self._download_menu_item,
                                    'Download')
        download_item.SetAccel(wx.AcceleratorEntry(wx.ACCEL_ALT, ord('D')))
        self.Bind(wx.EVT_MENU, self._menu_download, download_item)
        radio_menu.Append(download_item)

        self._upload_menu_item = wx.NewId()
        upload_item = wx.MenuItem(radio_menu, self._upload_menu_item, 'Upload')
        upload_item.SetAccel(wx.AcceleratorEntry(wx.ACCEL_ALT, ord('U')))
        self.Bind(wx.EVT_MENU, self._menu_upload, upload_item)
        radio_menu.Append(upload_item)

        source_menu = wx.Menu()
        radio_menu.AppendSubMenu(source_menu, 'Query Source')

        query_rb_item = wx.MenuItem(source_menu, wx.NewId(), 'RepeaterBook')
        self.Bind(wx.EVT_MENU, self._menu_query_rb, query_rb_item)
        source_menu.Append(query_rb_item)

        radio_menu.Append(wx.MenuItem(radio_menu, wx.ID_SEPARATOR))

        auto_edits = wx.MenuItem(radio_menu, wx.NewId(),
                                 'Enable Automatic Edits',
                                 kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU, self._menu_auto_edits, auto_edits)
        radio_menu.Append(auto_edits)
        auto_edits.Check(CONF.get_bool('auto_edits', 'state', True))

        select_bandplan = wx.MenuItem(radio_menu, wx.NewId(),
                                      'Select Bandplan')
        self.Bind(wx.EVT_MENU, self._menu_select_bandplan, select_bandplan)
        radio_menu.Append(select_bandplan)

        if CONF.get_bool('developer', 'state'):
            radio_menu.Append(wx.MenuItem(file_menu, wx.ID_SEPARATOR))

            self._reload_driver_item = wx.NewId()
            reload_drv_item = wx.MenuItem(radio_menu,
                                          self._reload_driver_item,
                                          'Reload Driver')
            reload_drv_item.SetAccel(
                wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_CTRL,
                                    ord('R')))
            self.Bind(wx.EVT_MENU, self._menu_reload_driver, reload_drv_item)
            radio_menu.Append(reload_drv_item)

            self._reload_both_item = wx.NewId()
            reload_both_item = wx.MenuItem(radio_menu,
                                           self._reload_both_item,
                                           'Reload Driver and File')
            reload_both_item.SetAccel(
                wx.AcceleratorEntry(
                    wx.ACCEL_ALT | wx.ACCEL_CTRL | wx.ACCEL_SHIFT,
                    ord('R')))
            self.Bind(
                wx.EVT_MENU,
                functools.partial(self._menu_reload_driver, andfile=True),
                reload_both_item)
            radio_menu.Append(reload_both_item)

            self._interact_driver_item = wx.NewId()
            interact_drv_item = wx.MenuItem(radio_menu,
                                            self._interact_driver_item,
                                            'Interact with driver')
            self.Bind(wx.EVT_MENU, self._menu_interact_driver,
                      interact_drv_item)
            radio_menu.Append(interact_drv_item)

        help_menu = wx.Menu()

        about_item = wx.MenuItem(help_menu, wx.NewId(), 'About')
        self.Bind(wx.EVT_MENU, self._menu_about, about_item)
        help_menu.Append(about_item)

        developer_menu = wx.MenuItem(help_menu, wx.NewId(), 'Developer Mode',
                                     kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU,
                  functools.partial(self._menu_developer, developer_menu),
                  developer_menu)
        help_menu.Append(developer_menu)
        developer_menu.Check(CONF.get_bool('developer', 'state'))

        menu_bar = wx.MenuBar()
        menu_bar.Append(file_menu, '&File')
        menu_bar.Append(edit_menu, '&Edit')
        menu_bar.Append(radio_menu, '&Radio')
        menu_bar.Append(help_menu, '&Help')

        return menu_bar

    def make_toolbar(self):
        tb = self.CreateToolBar()

        def bm(stock):
            return wx.ArtProvider.GetBitmap(stock,
                                            wx.ART_TOOLBAR, (32, 32))

        tbopen = tb.AddTool(wx.NewId(), 'Open', bm(wx.ART_FILE_OPEN),
                            'Open a file')
        tb.AddTool(wx.NewId(), 'Save', bm(wx.ART_FILE_SAVE),
                   'Save file')
        tb.AddTool(wx.NewId(), 'Close', bm(wx.ART_CLOSE),
                   'Close file')
        tb.AddTool(wx.NewId(), 'Download', bm(wx.ART_GO_DOWN),
                   'Download from radio')
        tb.AddTool(wx.NewId(), 'Upload', bm(wx.ART_GO_UP),
                   'Upload to radio')

        self.Bind(wx.EVT_MENU, self._menu_open, tbopen)
        tb.Realize()

    def adj_menu_open_recent(self, filename):
        # Don't add stock config files to the recent files list
        stock_dir = platform.get_platform().config_file("stock_configs")
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
        if eset.modified:
            if wx.MessageBox(
                    '%s has not been saved. Close anyway?' % eset.filename,
                    'Close without saving?',
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING) != wx.YES:
                event.Veto()

        eset.close()

        wx.CallAfter(self._update_window_for_editor)

    def _update_window_for_editor(self):
        eset = self.current_editorset
        can_close = False
        can_save = False
        can_saveas = False
        can_upload = False
        CSVRadio = directory.get_radio('Generic_CSV')
        if eset is not None:
            is_live = isinstance(eset.radio, chirp_common.LiveRadio)
            can_close = True
            can_save = eset.modified and not is_live
            can_saveas = not is_live
            can_upload = (not isinstance(eset.radio, CSVRadio) and
                          not isinstance(eset.radio, common.LiveAdapter) and
                          not is_live)

        items = [
            (wx.ID_CLOSE, can_close),
            (wx.ID_SAVE, can_save),
            (wx.ID_SAVEAS, can_saveas),
            (self._upload_menu_item, can_upload),
        ]
        for ident, enabled in items:
            menuitem = self.GetMenuBar().FindItemById(ident)
            menuitem.Enable(enabled)

    def _window_close(self, event):
        if any([self._editors.GetPage(i).modified
                for i in range(self._editors.GetPageCount())]):
            if wx.MessageBox(
                    'Some files have not been saved. Exit anyway?',
                    'Exit without saving?',
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING) != wx.YES:
                if event.CanVeto():
                    event.Veto()
                return

        size = self.GetSize()
        CONF.set_int('window_w', size.GetWidth(), 'state')
        CONF.set_int('window_h', size.GetHeight(), 'state')
        config._CONFIG.save()

        # Make sure we call close on each editor, so it can end
        # threads and do other cleanup
        for i in range(self._editors.GetPageCount()):
            e = self._editors.GetPage(i)
            e.close()

        self.Destroy()

    def _update_editorset_title(self, editorset):
        index = self._editors.GetPageIndex(editorset)
        self._editors.SetPageText(index, '%s%s' % (
            os.path.basename(editorset.filename),
            editorset.modified and '*' or ''))

    def _menu_new(self, event):
        self.open_file('Untitled.csv', exists=False)

    def _menu_open(self, event):
        wildcard = '|'.join(['Chirp Image Files (*.img)|*.img',
                             'CSV Files (*.csv)|*.csv',
                             'ICF Files (*.icf)|*.icf',
                             'All Files (*.*)|*.*'])
        with wx.FileDialog(self, 'Open a file',
                           platform.get_platform().get_last_dir(),
                           wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            filename = fd.GetPath()
            d = fd.GetDirectory()
            platform.get_platform().set_last_dir(d)
            CONF.set('last_dir', d, 'state')
            config._CONFIG.save()
            self.open_file(str(filename))

    def _menu_open_stock_config(self, event):
        stock_dir = platform.get_platform().config_file("stock_configs")
        fn = self.OPEN_STOCK_CONFIG_MENU.FindItemById(
            event.GetId()).GetItemLabelText()
        fn += ".csv"
        filename = os.path.join(stock_dir, fn)
        self.open_file(filename)

    def _menu_open_recent(self, event):
        filename = self.OPEN_RECENT_MENU.FindItemById(
            event.GetId()).GetItemLabelText()
        self.open_file(filename)

    def _menu_save_as(self, event):
        eset = self.current_editorset
        wildcard = 'CHIRP %(vendor)s %(model)s Files (*.%(ext)s)|*.%(ext)s' % {
            'vendor': eset._radio.VENDOR,
            'model': eset._radio.MODEL,
            'ext': eset._radio.FILE_EXTENSION}

        if isinstance(eset.radio, icf.IcomCloneModeRadio):
            wildcard += '|ICF Files (*.icf)|*.icf'

        style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT | wx.FD_CHANGE_DIR
        with wx.FileDialog(self, "Save file", defaultFile=eset.filename,
                           wildcard=wildcard,
                           style=style) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            filename = fd.GetPath()
            eset.save(filename)
            self.adj_menu_open_recent(filename)
            self._update_editorset_title(eset)

    def _menu_save(self, event):
        editorset = self.current_editorset
        if not editorset.modified:
            return

        if not os.path.exists(editorset.filename):
            return self._menu_save_as(event)

        editorset.save()
        self._update_editorset_title(self.current_editorset)

    def _menu_close(self, event):
        self._editors.DeletePage(self._editors.GetSelection())
        self._update_window_for_editor()

    def _menu_exit(self, event):
        self.Close(True)

    def _menu_copy(self, event, cut=False):
        data = self.current_editorset.cb_copy(cut=cut)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(data)
            wx.TheClipboard.Close()

    def _menu_paste(self, event):
        memdata = wx.CustomDataObject(common.CHIRP_DATA_MEMORY)
        textdata = wx.TextDataObject()
        if wx.TheClipboard.Open():
            gotchirpmem = wx.TheClipboard.GetData(memdata)
            got = wx.TheClipboard.GetData(textdata)
            wx.TheClipboard.Close()
        if gotchirpmem:
            self.current_editorset.cb_paste(memdata)
        if got:
            self.current_editorset.cb_paste(textdata)

    def _menu_selall(self, event):
        self.current_editorset.select_all()

    def _menu_download(self, event):
        with clone.ChirpDownloadDialog(self) as d:
            d.Centre()
            if d.ShowModal() == wx.ID_OK:
                radio = d._radio
                if isinstance(radio, chirp_common.LiveRadio):
                    editorset = ChirpLiveEditorSet(radio, None, self._editors)
                else:
                    editorset = ChirpEditorSet(radio, None, self._editors)
                self.add_editorset(editorset)

    def _menu_upload(self, event):
        radio = self.current_editorset.radio
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

        # Kill the current editorset now that we know the radio loaded
        # successfully
        last_editor = self.current_editorset.current_editor_index
        self._menu_close(event)

        # Mimic the File->Open process to get a new editorset based
        # on our franken-radio
        editorset = ChirpEditorSet(new_radio, filename, self._editors)
        self.add_editorset(editorset, select=True)
        editorset.select_editor(last_editor)

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

    def _menu_about(self, event):
        pyver = sys.version_info
        aboutinfo = 'CHIRP %s on Python %s wxPython %s' % (
            CHIRP_VERSION,
            '%s.%s.%s' % (pyver.major, pyver.minor, pyver.micro),
            wx.version())
        wx.MessageBox(aboutinfo, 'About CHIRP',
                      wx.OK | wx.ICON_INFORMATION)

    def _menu_developer(self, menuitem, event):
        CONF.set_bool('developer', menuitem.IsChecked(), 'state')
        state = menuitem.IsChecked() and 'enabled' or 'disabled'
        wx.MessageBox(('Developer state is now %s. '
                       'CHIRP must be restarted to take effect') % state,
                      'Restart Required', wx.OK)

    def _menu_auto_edits(self, event):
        CONF.set_bool('auto_edits', event.IsChecked(), 'state')
        LOG.debug('Set auto_edits=%s' % event.IsChecked())

    def _menu_select_bandplan(self, event):
        bandplans = bandplan.BandPlans(CONF)
        plans = sorted([(shortname, details[0])
                        for shortname, details in bandplans.plans.items()],
                       key=lambda x: x[1])
        d = wx.SingleChoiceDialog(self, 'Select a bandplan',
                                  'Bandplan',
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

    def _menu_query_rb(self, event):
        d = query_sources.RepeaterBookQueryDialog(self,
                                                  title='Query Repeaterbook')
        r = d.ShowModal()
        if r == wx.ID_OK:
            LOG.debug('Result file: %s' % d.result_file)
            self.open_file(d.result_file)
