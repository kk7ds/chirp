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

"""The persisted, versioned color-coding profile.

A ColorProfile bundles: whether color coding is on, how it's applied
(whole row vs. selected columns), the built-in category color table
(only entries that differ from the shipped defaults are stored), and
any user-defined rules.

Serialization is plain JSON (see to_dict()/from_dict()) -- no arbitrary
code execution, no pickle. Every loaded value is validated; anything
malformed is dropped (with the built-in default substituted) rather
than raising, so a corrupted or hand-edited config file degrades
gracefully instead of crashing the app. Callers that need to
distinguish "loaded cleanly" from "recovered from a malformed file"
can check ColorProfile.load_warnings.
"""

import dataclasses
import json

from chirp.memcolors import categories
from chirp.memcolors import contrast
from chirp.memcolors import frequency_data
from chirp.memcolors import rules as rules_mod

SCHEMA_VERSION = 1

APPLY_ROW = 'row'
APPLY_COLUMNS = 'columns'

# Logical column identifiers (chirp.wxui.memedit.ChirpMemoryColumn.name
# values), never numeric grid positions -- this fork supports column
# hiding/reordering, so a persisted position would silently point at the
# wrong column (or nothing) the moment the user rearranges columns.
DEFAULT_SELECTED_COLUMNS = (
    'name', 'freq', 'duplex', 'offset', 'mode', 'tmode', 'comment',
)


class ProfileValidationError(ValueError):
    pass


@dataclasses.dataclass
class CategoryState:
    """The fully-resolved (default-merged) display state of one category."""
    bg: str
    fg: str
    enabled: bool
    bold: bool
    priority: int

    def validate(self, category_id):
        if not contrast.is_valid_hex_color(self.bg):
            raise ProfileValidationError(
                'Category %r has invalid bg %r' % (category_id, self.bg))
        if not contrast.is_valid_hex_color(self.fg):
            raise ProfileValidationError(
                'Category %r has invalid fg %r' % (category_id, self.fg))
        if not isinstance(self.enabled, bool):
            raise ProfileValidationError(
                'Category %r enabled must be a bool' % (category_id,))
        if not isinstance(self.priority, int):
            raise ProfileValidationError(
                'Category %r priority must be an int' % (category_id,))

    def to_dict(self):
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, category_id, data):
        try:
            state = cls(bg=data['bg'], fg=data['fg'],
                        enabled=bool(data.get('enabled', True)),
                        bold=bool(data.get('bold', False)),
                        priority=int(data['priority']))
        except (KeyError, TypeError, ValueError) as e:
            raise ProfileValidationError(
                'Malformed category override for %r: %s' % (category_id, e))
        state.validate(category_id)
        return state

    @classmethod
    def from_category(cls, category):
        return cls(bg=category.default_bg, fg=category.default_fg,
                   enabled=True, bold=category.bold,
                   priority=category.priority)


@dataclasses.dataclass
class ColorProfile:
    schema_version: int = SCHEMA_VERSION
    profile_name: str = 'Default'
    region: str = frequency_data.DEFAULT_REGION
    enabled: bool = True
    apply_mode: str = APPLY_ROW
    selected_columns: tuple = DEFAULT_SELECTED_COLUMNS
    show_legend: bool = True
    # Opt-in per classify()'s @validation_errors: off by default since a
    # naive wiring of per-radio validation into the "invalid" category
    # risks flagging things like out-of-band receive-only memories that
    # aren't actually a problem.
    flag_invalid: bool = False
    category_overrides: dict = dataclasses.field(default_factory=dict)
    custom_rules: tuple = ()

    # Populated by from_dict() when recovering from a malformed profile;
    # empty for a cleanly-loaded or freshly-constructed profile.
    load_warnings: tuple = dataclasses.field(default_factory=tuple)

    # --- category access -------------------------------------------------

    def category_state(self, category_id):
        """Return the effective (default-merged) CategoryState."""
        if category_id in self.category_overrides:
            return self.category_overrides[category_id]
        builtin = categories.default_category(category_id)
        if builtin is None:
            raise KeyError(category_id)
        return CategoryState.from_category(builtin)

    def set_category_state(self, category_id, state):
        if categories.default_category(category_id) is None:
            raise KeyError('Unknown category id %r' % (category_id,))
        state.validate(category_id)
        self.category_overrides[category_id] = state

    def reset_category(self, category_id):
        self.category_overrides.pop(category_id, None)

    def reset_all_categories(self):
        """Reset only the built-in color table -- leaves rules, apply
        mode, selected columns, and enable state untouched."""
        self.category_overrides = {}

    def enabled_categories(self):
        """Return [(category_id, CategoryState), ...] for legend display,
        enabled only, sorted by precedence tier then id for stability."""
        result = []
        for cat in categories.DEFAULT_CATEGORIES:
            state = self.category_state(cat.id)
            if state.enabled:
                result.append((cat.id, state))
        return sorted(result, key=lambda x: (x[1].priority, x[0]))

    # --- rules -------------------------------------------------------------

    def add_rule(self, rule):
        rule.validate()
        self.custom_rules = self.custom_rules + (rule,)

    def remove_rule(self, name):
        self.custom_rules = tuple(r for r in self.custom_rules
                                  if r.name != name)

    def move_rule(self, name, delta):
        """Swap the priority of the named rule with its neighbor in
        display order (delta -1 = up/earlier, +1 = down/later)."""
        ordered = sorted(self.custom_rules, key=lambda r: r.priority)
        idx = next((i for i, r in enumerate(ordered) if r.name == name),
                   None)
        if idx is None:
            return
        other = idx + delta
        if not (0 <= other < len(ordered)):
            return
        ordered[idx].priority, ordered[other].priority = (
            ordered[other].priority, ordered[idx].priority)
        self.custom_rules = tuple(ordered)

    # --- serialization -------------------------------------------------

    def to_dict(self):
        return {
            'schema_version': SCHEMA_VERSION,
            'profile_name': self.profile_name,
            'region': self.region,
            'enabled': self.enabled,
            'apply_mode': self.apply_mode,
            'selected_columns': list(self.selected_columns),
            'show_legend': self.show_legend,
            'flag_invalid': self.flag_invalid,
            'category_overrides': {
                cat_id: state.to_dict()
                for cat_id, state in self.category_overrides.items()
            },
            'custom_rules': [r.to_dict() for r in self.custom_rules],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data):
        """Validate and build a ColorProfile from a plain dict.

        Never raises for recoverable problems: unknown/invalid fields are
        dropped and noted in the returned profile's load_warnings, with
        the built-in default substituted. Raises ProfileValidationError
        only if @data isn't even a dict, or the schema_version is one we
        can't read at all.
        """
        if not isinstance(data, dict):
            raise ProfileValidationError('Profile must be a JSON object')

        version = data.get('schema_version')
        if not isinstance(version, int) or version > SCHEMA_VERSION:
            raise ProfileValidationError(
                'Unsupported profile schema_version %r' % (version,))

        warnings = []
        profile = cls()

        if isinstance(data.get('profile_name'), str):
            profile.profile_name = data['profile_name']
        if data.get('region') in frequency_data.REGIONS:
            profile.region = data['region']
        elif 'region' in data:
            warnings.append('Unknown region %r, using default' %
                            (data.get('region'),))
        if isinstance(data.get('enabled'), bool):
            profile.enabled = data['enabled']
        if data.get('apply_mode') in (APPLY_ROW, APPLY_COLUMNS):
            profile.apply_mode = data['apply_mode']
        elif 'apply_mode' in data:
            warnings.append('Invalid apply_mode %r, using default' %
                            (data.get('apply_mode'),))
        if isinstance(data.get('show_legend'), bool):
            profile.show_legend = data['show_legend']
        if isinstance(data.get('flag_invalid'), bool):
            profile.flag_invalid = data['flag_invalid']

        cols = data.get('selected_columns')
        if isinstance(cols, list) and all(isinstance(c, str) for c in cols):
            profile.selected_columns = tuple(cols)
        elif cols is not None:
            warnings.append('Invalid selected_columns, using default')

        overrides = {}
        for cat_id, raw in (data.get('category_overrides') or {}).items():
            if categories.default_category(cat_id) is None:
                # Not an error: could be a category from a newer version
                # of CHIRP we don't know about yet. Skip silently but
                # don't drop the whole profile.
                continue
            try:
                overrides[cat_id] = CategoryState.from_dict(cat_id, raw)
            except ProfileValidationError as e:
                warnings.append(str(e))
        profile.category_overrides = overrides

        parsed_rules = []
        for raw_rule in (data.get('custom_rules') or []):
            try:
                parsed_rules.append(rules_mod.Rule.from_dict(raw_rule))
            except rules_mod.RuleValidationError as e:
                warnings.append('Dropped invalid rule: %s' % e)
        profile.custom_rules = tuple(parsed_rules)

        profile.load_warnings = tuple(warnings)
        return profile

    @classmethod
    def from_json(cls, text):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
            raise ProfileValidationError('Malformed JSON: %s' % e)
        return cls.from_dict(data)


def default_profile():
    """Return a fresh profile using entirely built-in defaults."""
    return ColorProfile()
