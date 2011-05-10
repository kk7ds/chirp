#!/usr/bin/python
#
# Copyright 2011 Dan Smith <dsmith@danplanet.com>
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

from chirp import chirp_common, errors

class ImportError(Exception):
    pass

class DestNotCompatible(ImportError):
    pass

def ensure_has_calls(radio, memory):
    ulist_changed = rlist_changed = False

    ulist = radio.get_urcall_list()
    rlist = radio.get_repeater_call_list()

    if memory.dv_urcall and memory.dv_urcall not in ulist:
        for i in range(0, len(ulist)):
            if not ulist[i].strip():
                ulist[i] = memory.dv_urcall
                ulist_changed = True
                break
        if not ulist_changed:
            raise ImportError("No room to add callsign %s" % memory.dv_urcall)

    rlist_add = []
    if memory.dv_rpt1call and memory.dv_rpt1call not in rlist:
        rlist_add.append(memory.dv_rpt1call)
    if memory.dv_rpt2call and memory.dv_rpt2call not in rlist:
        rlist_add.append(memory.dv_rpt2call)

    while rlist_add:
        call = rlist_add.pop()
        for i in range(0, len(rlist)):
            if not rlist[i].strip():
                rlist[i] = call
                call = None
                rlist_changed = True
                break
        if call:
            raise errors.RadioError("No room to add callsign %s" % call)

    if ulist_changed:
        radio.set_urcall_list(ulist)
    if rlist_changed:
        radio.set_repeater_cal_list(rlist)

# Filter the name according to the destination's rules
def _import_name(dst_radio, mem):
    mem.name = dst_radio.filter_name(mem.name)

# If the bank is out of range for the destination, revert to "no bank"
def _import_bank(dst_radio, mem):
    nbanks = len(dst_radio.get_banks())
    if mem.bank >= nbanks:
        mem.bank = None

def _import_power(dst_radio, mem):
    levels = dst_radio.get_features().valid_power_levels
    if not levels:
        mem.power = None
        return
    elif mem.power is None:
        # Source radio did not support power levels, so choose the
        # first (highest) level from the destination radio.
        mem.power = levels[0]
        return 

    # If both radios support power levels, we need to decide how to
    # convert the source power level to a valid one for the destination
    # radio.  To do that, find the absolute level of the source value
    # and calculate the different between it and all the levels of the
    # destination, choosing the one that matches most closely.

    deltas = [abs(mem.power - power) for power in levels]
    mem.power = levels[deltas.index(min(deltas))]

def import_mem(dst_radio, src_mem, overrides={}):
    dst_rf = dst_radio.get_features()

    if isinstance(src_mem, chirp_common.DVMemory):
        if not isinstance(dst_radio, chirp_common.IcomDstarSupport):
            raise DestNotCompatible("Destination radio does not support D-STAR")
        if dst_rf.requires_call_lists:
            ensure_has_calls(dst_radio, src_mem)

    dst_mem = src_mem.dupe()

    helpers = [_import_name,
               _import_bank,
               _import_power,
               ]

    for helper in helpers:
        helper(dst_radio, dst_mem)

    for k, v in overrides.items():
        dst_mem.__dict__[k] = v

    msgs = dst_radio.validate_memory(dst_mem)
    errors = [x for x in msgs if isinstance(x, chirp_common.ValidationError)]
    if errors:
        raise DestNotCompatible("Unable to create import memory: %s" %\
                                    ", ".join(errors))

    return dst_mem
        
