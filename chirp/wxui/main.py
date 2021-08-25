import datetime
import functools
import logging
import os
import sys

import wx
import wx.aui
import wx.lib.newevent

from chirp import directory
from chirp.ui import config
from chirp.wxui import common
from chirp.wxui import clone
from chirp.wxui import developer
from chirp.wxui import memedit
from chirp.wxui import settingsedit
from chirp import CHIRP_VERSION

EditorSetChanged, EVT_EDITORSET_CHANGED = wx.lib.newevent.NewCommandEvent()
CONF = config.get()
LOG = logging.getLogger(__name__)


class ChirpEditorSet(wx.Panel):
    def __init__(self, radio, filename, *a, **k):
        super(ChirpEditorSet, self).__init__(*a, **k)
        self._radio = radio
        if filename is None:
            filename = '%s.%s' % (self.default_filename,
                                  radio.FILE_EXTENSION)
        self._filename = filename
        self._modified = not os.path.exists(filename)

        self._editors = wx.Notebook(self, style=wx.NB_LEFT)

        self._editors.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGING,
                           self._editor_selected)

        sizer = wx.BoxSizer()
        sizer.Add(self._editors, 1, wx.EXPAND)
        self.SetSizer(sizer)

        features = radio.get_features()

        if features.has_sub_devices:
            radios = radio.get_sub_devices()
            format = 'Memories (%(variant)s)'
        else:
            radios = [radio]
            format = 'Memories'

        for radio in radios:
            edit = memedit.ChirpMemEdit(radio, self._editors)
            edit.refresh()
            self.Bind(common.EVT_EDITOR_CHANGED, self._editor_changed)
            self._editors.AddPage(edit, format % {'variant': radio.VARIANT})

        if features.has_settings:
            if isinstance(radio, common.LiveAdapter):
                settings = settingsedit.ChirpLiveSettingsEdit(radio,
                                                              self._editors)
            else:
                settings = settingsedit.ChirpCloneSettingsEdit(radio,
                                                               self._editors)
            self._editors.AddPage(settings, 'Settings')

        if CONF.get_bool('developer', 'state'):
            browser = developer.ChirpRadioBrowser(radio, self._editors)
            self._editors.AddPage(browser, 'Browser')

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


class ChirpMain(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(ChirpMain, self).__init__(*args, **kwargs)

        self.SetSize(int(CONF.get('window_w', 'state') or 1024),
                     int(CONF.get('window_h', 'state') or 768))

        self.SetMenuBar(self.make_menubar())

        # Stock items look good on linux, terrible on others,
        # so punt on this for the moment.
        # self.make_toolbar()

        self._editors = wx.aui.AuiNotebook(
            self, style=wx.aui.AUI_NB_CLOSE_ON_ALL_TABS|wx.aui.AUI_NB_TAB_MOVE)
        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CLOSE, self._editor_close)
        self.Bind(wx.aui.EVT_AUINOTEBOOK_PAGE_CHANGED,
                  self._editor_page_changed)
        self.Bind(wx.EVT_CLOSE, self._window_close)

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

        editorset = ChirpEditorSet(radio, filename, self._editors)
        self.add_editorset(editorset, select=select)

    def add_editorset(self, editorset, select=True):
        self._editors.AddPage(editorset,
                              os.path.basename(editorset.filename),
                              select=select)
        self.Bind(EVT_EDITORSET_CHANGED, self._editor_changed, editorset)
        self._update_editorset_title(editorset)

    def make_menubar(self):
        file_menu = wx.Menu()

        new_item = file_menu.Append(wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self._menu_new, new_item)

        open_item = file_menu.Append(wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self._menu_open, open_item)

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
        tbsave = tb.AddTool(wx.NewId(), 'Save', bm(wx.ART_FILE_SAVE),
                            'Save file')
        tbclose = tb.AddTool(wx.NewId(), 'Close', bm(wx.ART_CLOSE),
                             'Close file')
        tbdl = tb.AddTool(wx.NewId(), 'Download', bm(wx.ART_GO_DOWN),
                   'Download from radio')
        tbl = tb.AddTool(wx.NewId(), 'Upload', bm(wx.ART_GO_UP),
                         'Upload to radio')

        self.Bind(wx.EVT_MENU, self._menu_open, tbopen)
        tb.Realize()

    def _editor_page_changed(self, event):
        self._editors.GetPage(event.GetSelection())
        self._update_window_for_editor()

    def _editor_changed(self, event):
        self._update_editorset_title(event.editorset)
        self._update_window_for_editor()

    def _editor_close(self, event):
        eset = self._editors.GetPage(event.GetSelection())
        if eset.modified:
            if wx.MessageBox(
                    '%s has not been saved. Close anyway?' % eset.filename,
                    'Close without saving?',
                    wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING) != wx.YES:
                event.Veto()

        wx.CallAfter(self._update_window_for_editor)

    def _update_window_for_editor(self):
        eset = self.current_editorset
        can_close = False
        can_save = False
        can_saveas = False
        can_upload = False
        CSVRadio = directory.get_radio('Generic_CSV')
        if eset is not None:
            can_close = True
            can_save = eset.modified
            can_saveas = True
            can_upload = not (isinstance(eset.radio, CSVRadio) and not
                              isinstance(eset.radio, common.LiveAdapter))

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
                    wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING) != wx.YES:
                if event.CanVeto():
                    event.Veto()
                return

        size = self.GetSize()
        CONF.set_int('window_w', size.GetWidth(), 'state')
        CONF.set_int('window_h', size.GetHeight(), 'state')
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
        wildcard = '|'.join(['Chirp Image Files (*.img)|*.img',
                             'CSV Files (*.csv)|*.csv',
                             'All Files (*.*)|*.*'])
        with wx.FileDialog(self, 'Open a file', wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            filename = fd.GetPath()
            self.open_file(str(filename))

    def _menu_save_as(self, event):
        eset = self.current_editorset
        wildcard = 'CHIRP %(vendor)s %(model)s Files (*.%(ext)s)|*.%(ext)s' % {
            'vendor': eset._radio.VENDOR,
            'model': eset._radio.MODEL,
            'ext': eset._radio.FILE_EXTENSION}

        style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT | wx.FD_CHANGE_DIR
        with wx.FileDialog(self, "Save file", defaultFile=eset.filename,
                           wildcard=wildcard,
                           style=style) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            filename = fd.GetPath()
            eset.save(filename)
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

