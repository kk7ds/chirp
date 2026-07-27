# Copyright 2026
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

"""wx-facing adapter for chirp.memcolors: config persistence + caching.

This is the only module in the color-coding feature that imports wx. It
translates the pure-Python classifier/profile model into wx.Colour
values for chirp.wxui.memedit, and is the single place that knows how
the profile is stored in CHIRP's config.

Storage: a single JSON blob (chirp.memcolors.profile.ColorProfile,
schema-versioned) under config section 'memcolors', key 'profile'. Every
other persisted setting in this fork's memedit uses small delimited
string values (see chirp/wxui/memedit.py's hidden_columns/column_order),
but the color profile is a nested structure -- category color overrides
plus an ordered list of multi-field custom rules -- that doesn't fit
that flat idiom. A single validated JSON value keeps it human-readable
and diffable (e.g. for manual backup/inspection of chirp.config) while
still going through the same get()/set() API as everything else, so it
automatically respects --config-dir and AppImage config isolation.
"""

import logging

import wx

from chirp.memcolors import classifier
from chirp.memcolors import profile as profile_mod
from chirp.wxui import config

CONF_SECTION = 'memcolors'
CONF_KEY = 'profile'

LOG = logging.getLogger(__name__)


class ColorCodingController:
    """Owns the current ColorProfile, its config persistence, and a
    small classification cache shared by every open memory-edit grid."""

    def __init__(self):
        self._conf = config.get(CONF_SECTION)
        self._profile = self._load()
        self._generation = 0
        self._cache = {}
        self._listeners = []

    def _load(self):
        raw = self._conf.get(CONF_KEY)
        if not raw:
            return profile_mod.default_profile()
        try:
            loaded = profile_mod.ColorProfile.from_json(raw)
        except profile_mod.ProfileValidationError as e:
            LOG.warning('Failed to load memory color profile (%s); '
                        'falling back to defaults', e)
            return profile_mod.default_profile()
        if loaded.load_warnings:
            LOG.warning('Memory color profile loaded with %i warning(s): '
                        '%s', len(loaded.load_warnings),
                        '; '.join(loaded.load_warnings))
        return loaded

    @property
    def profile(self):
        return self._profile

    def save(self):
        """Persist the current profile and notify listeners/invalidate
        the classification cache."""
        self._conf.set(CONF_KEY, self._profile.to_json())
        self._bump_generation()

    def replace_profile(self, new_profile):
        """Swap in an entirely new profile (e.g. from Import) and save."""
        self._profile = new_profile
        self.save()

    def discard_changes(self):
        """Reload from persisted config, discarding any in-memory edits
        that were never save()d (Cancel button semantics)."""
        self._profile = self._load()
        self._bump_generation()

    def _bump_generation(self):
        self._generation += 1
        self._cache.clear()
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                LOG.exception('Color coding listener callback failed')

    def add_listener(self, callback):
        """Register a no-arg callback invoked whenever the profile
        changes (Apply/OK/Import/reset). Used by open grids to refresh
        without needing a restart."""
        self._listeners.append(callback)

    def remove_listener(self, callback):
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _cache_key(self, memory, has_validation_error):
        return (memory.number, memory.freq, memory.duplex, memory.offset,
                memory.mode, memory.tmode, memory.skip, memory.empty,
                memory.name, memory.comment, bool(has_validation_error),
                self._generation)

    def classify(self, memory, validation_errors=None):
        if not self._profile.enabled:
            return None
        key = self._cache_key(memory, validation_errors)
        try:
            return self._cache[key]
        except KeyError:
            pass
        result = classifier.classify(
            memory, region=self._profile.region,
            rules=self._profile.custom_rules,
            validation_errors=validation_errors)
        self._cache[key] = result
        return result

    def validation_errors_for(self, radio, memory):
        """Return validate_memory() ValidationErrors for @memory, but
        only when the "flag invalid" option is on AND the memory is
        actually meant to transmit -- a receive-only memory that's
        outside a radio's TX range should not be painted "invalid"
        merely because it can't transmit (see classifier.classify's
        docstring)."""
        if not self._profile.flag_invalid or memory.duplex == 'off':
            return None
        try:
            features = radio.get_features()
            msgs = features.validate_memory(memory)
        except Exception:
            LOG.exception('Failed to validate memory %s for color coding',
                          memory.number)
            return None
        from chirp import chirp_common
        return [m for m in msgs if isinstance(m, chirp_common.ValidationError)]

    def style_for(self, memory, col_name, radio=None):
        """Return (wx.Colour bg, wx.Colour fg, bold) for @memory's
        @col_name cell, or None if no color coding should be applied
        (feature disabled, column mode excludes this column, or the
        resolved category is disabled by the user)."""
        if not self._profile.enabled:
            return None
        if (self._profile.apply_mode == profile_mod.APPLY_COLUMNS and
                col_name not in self._profile.selected_columns):
            return None

        validation_errors = (self.validation_errors_for(radio, memory)
                             if radio is not None else None)
        result = self.classify(memory, validation_errors=validation_errors)
        if result is None:
            return None

        if result.is_rule_override:
            bg, fg, bold = result.rule.bg, result.rule.fg, result.rule.bold
        else:
            state = self._profile.category_state(result.category_id)
            if not state.enabled:
                return None
            bg, fg, bold = state.bg, state.fg, state.bold

        return wx.Colour(bg), wx.Colour(fg), bold


_CONTROLLER = None


def get_controller():
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = ColorCodingController()
    return _CONTROLLER
