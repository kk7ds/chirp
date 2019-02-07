#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
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

import gtk
import gobject
import threading
import logging

from chirp import errors, chirp_common

LOG = logging.getLogger(__name__)


class ShiftDialog(gtk.Dialog):
    def __init__(self, rthread, parent=None):
        gtk.Dialog.__init__(self,
                            title=_("Shift"),
                            buttons=(gtk.STOCK_CLOSE, gtk.RESPONSE_OK))

        self.set_position(gtk.WIN_POS_CENTER_ALWAYS)

        self.rthread = rthread

        self.__prog = gtk.ProgressBar()
        self.__prog.show()

        self.__labl = gtk.Label("")
        self.__labl.show()

        self.vbox.pack_start(self.__prog, 1, 1, 1)
        self.vbox.pack_start(self.__labl, 0, 0, 0)

        self.quiet = False

        self.thread = None

    def _status(self, msg, prog):
        self.__labl.set_text(msg)
        self.__prog.set_fraction(prog)

    def status(self, msg, prog):
        gobject.idle_add(self._status, msg, prog)

    def _shift_memories(self, delta, memories):
        count = 0.0
        for i in memories:
            src = i.number
            dst = src + delta

            LOG.info("Moving %i to %i" % (src, dst))
            self.status(_("Moving {src} to {dst}").format(src=src,
                                                          dst=dst),
                        count / len(memories))

            i.number = dst
            if i.empty:
                self.rthread.radio.erase_memory(i.number)
            else:
                self.rthread.radio.set_memory(i)
            count += 1.0

        return int(count)

    def _get_mems_until_hole(self, start, endokay=False, all=False):
        mems = []

        llimit, ulimit = self.rthread.radio.get_features().memory_bounds

        pos = start
        while pos <= ulimit:
            self.status(_("Looking for a free spot ({number})").format(
                        number=pos), 0)
            try:
                mem = self.rthread.radio.get_memory(pos)
                if mem.empty and not all:
                    break
            except errors.InvalidMemoryLocation:
                break

            mems.append(mem)
            pos += 1

        if pos > ulimit and not endokay:
            raise errors.InvalidMemoryLocation(_("No space to insert a row"))

        LOG.debug("Found a hole: %i" % pos)

        return mems

    def _insert_hole(self, start):
        mems = self._get_mems_until_hole(start)
        mems.reverse()
        if mems:
            ret = self._shift_memories(1, mems)
            if ret:
                # Clear the hole we made
                self.rthread.radio.erase_memory(start)
            return ret
        else:
            LOG.warn("No memory list?")
            return 0

    def _delete_hole(self, start, all=False):
        mems = self._get_mems_until_hole(start+1, endokay=True, all=all)
        if mems:
            count = self._shift_memories(-1, mems)
            self.rthread.radio.erase_memory(count+start)
            return count
        else:
            LOG.warn("No memory list?")
            return 0

    def finished(self):
        if self.quiet:
            gobject.idle_add(self.response, gtk.RESPONSE_OK)
        else:
            gobject.idle_add(self.set_response_sensitive,
                             gtk.RESPONSE_OK, True)

    def threadfn(self, newhole, func, *args):
        self.status("Waiting for radio to become available", 0)
        self.rthread.lock()

        try:
            count = func(newhole, *args)
        except errors.InvalidMemoryLocation as e:
            self.status(str(e), 0)
            self.finished()
            return

        self.rthread.unlock()
        self.status(_("Moved {count} memories").format(count=count), 1)

        self.finished()

    def insert(self, newhole, quiet=False):
        self.quiet = quiet
        self.thread = threading.Thread(target=self.threadfn,
                                       args=(newhole, self._insert_hole))
        self.thread.start()
        gtk.Dialog.run(self)

    def delete(self, newhole, quiet=False, all=False):
        self.quiet = quiet
        self.thread = threading.Thread(target=self.threadfn,
                                       args=(newhole, self._delete_hole, all))
        self.thread.start()
        gtk.Dialog.run(self)
