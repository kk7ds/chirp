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

import logging
from chirp import chirp_common, errors

LOG = logging.getLogger(__name__)


class ImportError(Exception):
    """An import error"""
    pass


class DestNotCompatible(ImportError):
    """Memory is not compatible with the destination radio"""
    pass


def ensure_has_calls(radio, memory):
    """Make sure @radio has the necessary D-STAR callsigns for @memory"""
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
            raise errors.RadioError("No room to add callsign %s" %
                                    memory.dv_urcall)

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
        radio.set_repeater_call_list(rlist)


# Filter the name according to the destination's rules
def _import_name(dst_radio, _srcrf, mem):
    mem.name = dst_radio.filter_name(mem.name)


def _import_power(dst_radio, _srcrf, mem):
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


def _import_tone(dst_radio, srcrf, mem):
    dstrf = dst_radio.get_features()

    # Some radios keep separate tones for Tone and TSQL modes (rtone and
    # ctone). If we're importing to or from radios with differing models,
    # do the conversion here.

    if srcrf.has_ctone and not dstrf.has_ctone:
        # If copying from a radio with separate rtone/ctone to a radio
        # without, and the tmode is TSQL, then use the ctone value
        if mem.tmode == "TSQL":
            mem.rtone = mem.ctone
    elif not srcrf.has_ctone and dstrf.has_ctone:
        # If copying from a radio without separate rtone/ctone to a radio
        # with it, set the dest ctone to the src rtone
        if mem.tmode == "TSQL":
            mem.ctone = mem.rtone


def _import_dtcs(dst_radio, srcrf, mem):
    dstrf = dst_radio.get_features()

    # Some radios keep separate DTCS codes for tx and rx
    # If we're importing to or from radios with differing models,
    # do the conversion here.

    if srcrf.has_rx_dtcs and not dstrf.has_rx_dtcs:
        # If copying from a radio with separate codes to a radio
        # without, and the tmode is DTCS, then use the rx_dtcs value
        if mem.tmode == "DTCS":
            mem.dtcs = mem.rx_dtcs
    elif not srcrf.has_rx_dtcs and dstrf.has_rx_dtcs:
        # If copying from a radio without separate codes to a radio
        # with it, set the dest rx_dtcs to the src dtcs
        if mem.tmode == "DTCS":
            mem.rx_dtcs = mem.dtcs


def _guess_mode_by_frequency(freq):
    ranges = [
        (0, 136000000, "AM"),
        (136000000, 9999000000, "FM"),
        ]

    for lo, hi, mode in ranges:
        if freq > lo and freq <= hi:
            return mode

    # If we don't know, assume FM
    return "FM"


def _import_mode(dst_radio, srcrf, mem):
    dstrf = dst_radio.get_features()

    # Some radios support an "Auto" mode. If we're importing from one
    # that does to one that does not, guess at the proper mode based on the
    # frequency

    if mem.mode == "Auto" and mem.mode not in dstrf.valid_modes:
        mode = _guess_mode_by_frequency(mem.freq)
        if mode not in dstrf.valid_modes:
            raise DestNotCompatible("Destination does not support %s" % mode)
        mem.mode = mode


def _make_offset_with_split(rxfreq, txfreq):
    offset = txfreq - rxfreq

    if offset == 0:
        return "", offset
    elif offset > 0:
        return "+", offset
    elif offset < 0:
        return "-", offset * -1


def _import_duplex(dst_radio, srcrf, mem):
    dstrf = dst_radio.get_features()

    # If a radio does not support odd split, we can use an equivalent offset
    if mem.duplex == "split" and mem.duplex not in dstrf.valid_duplexes:
        mem.duplex, mem.offset = _make_offset_with_split(mem.freq, mem.offset)

        # Enforce maximum offset
        ranges = [(0,          500000000, 15000000),
                  (500000000, 3000000000, 50000000),
                  ]
        for lo, hi, limit in ranges:
            if lo < mem.freq <= hi:
                if abs(mem.offset) > limit:
                    raise DestNotCompatible("Unable to create import memory: "
                                            "offset is abnormally large.")


def import_mem(dst_radio, src_features, src_mem, overrides={}):
    """Perform import logic to create a destination memory from
    src_mem that will be compatible with @dst_radio"""
    dst_rf = dst_radio.get_features()

    if isinstance(src_mem, chirp_common.DVMemory):
        if not isinstance(dst_radio, chirp_common.IcomDstarSupport):
            raise DestNotCompatible(
                "Destination radio does not support D-STAR")
        if dst_rf.requires_call_lists:
            ensure_has_calls(dst_radio, src_mem)

    dst_mem = src_mem.dupe()

    for k, v in overrides.items():
        dst_mem.__dict__[k] = v

    helpers = [_import_name,
               _import_power,
               _import_tone,
               _import_dtcs,
               _import_mode,
               _import_duplex,
               ]

    for helper in helpers:
        helper(dst_radio, src_features, dst_mem)

    msgs = dst_radio.validate_memory(dst_mem)
    errs = [x for x in msgs if isinstance(x, chirp_common.ValidationError)]
    if errs:
        raise DestNotCompatible("Unable to create import memory: %s" %
                                ", ".join(errs))

    return dst_mem


def _get_bank_model(radio):
    for model in radio.get_mapping_models():
        if isinstance(model, chirp_common.BankModel):
            return model
    return None


def import_bank(dst_radio, src_radio, dst_mem, src_mem):
    """Attempt to set the same banks for @mem(by index) in @dst_radio that
    it has in @src_radio"""

    dst_bm = _get_bank_model(dst_radio)
    if not dst_bm:
        return

    dst_banks = dst_bm.get_mappings()

    src_bm = _get_bank_model(src_radio)
    if not src_bm:
        return

    src_banks = src_bm.get_mappings()
    src_mem_banks = src_bm.get_memory_mappings(src_mem)
    src_indexes = [src_banks.index(b) for b in src_mem_banks]

    for bank in dst_bm.get_memory_mappings(dst_mem):
        dst_bm.remove_memory_from_mapping(dst_mem, bank)

    for index in src_indexes:
        try:
            bank = dst_banks[index]
            LOG.debug("Adding memory to bank %s" % bank)
            dst_bm.add_memory_to_mapping(dst_mem, bank)
            if isinstance(dst_bm, chirp_common.MappingModelIndexInterface):
                dst_bm.set_memory_index(dst_mem, bank,
                                        dst_bm.get_next_mapping_index(bank))

        except IndexError:
            pass
