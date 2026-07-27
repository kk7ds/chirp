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

"""User-defined color rules: a validated, structured match schema.

Deliberately NOT an expression language -- no eval(), no arbitrary code.
A rule is a name/color plus a list of (field, operator, value) conditions
that are all AND-ed together. This keeps import/export safe: a malformed
or hostile rule file can, at worst, fail validation.
"""

import dataclasses

from chirp.memcolors import contrast

# --- Matchable fields --------------------------------------------------

FIELD_FREQ = 'freq'
FIELD_SERVICE = 'service'
FIELD_DUPLEX = 'duplex'
FIELD_OFFSET_DIRECTION = 'offset_direction'
FIELD_MODE = 'mode'
FIELD_TONE_MODE = 'tone_mode'
FIELD_NAME = 'name'
FIELD_COMMENT = 'comment'
FIELD_SKIP = 'skip'
FIELD_RECEIVE_ONLY = 'receive_only'
FIELD_CLASSIFICATION = 'classification'

ALL_FIELDS = frozenset((
    FIELD_FREQ, FIELD_SERVICE, FIELD_DUPLEX, FIELD_OFFSET_DIRECTION,
    FIELD_MODE, FIELD_TONE_MODE, FIELD_NAME, FIELD_COMMENT, FIELD_SKIP,
    FIELD_RECEIVE_ONLY, FIELD_CLASSIFICATION,
))

# --- Operators -----------------------------------------------------------

OP_EQ = 'eq'
OP_NE = 'ne'
OP_IN = 'in'
OP_RANGE = 'range'
OP_CONTAINS = 'contains'
OP_STARTSWITH = 'startswith'
OP_ENDSWITH = 'endswith'

_TEXT_FIELDS = frozenset((FIELD_NAME, FIELD_COMMENT))
_NUMERIC_FIELDS = frozenset((FIELD_FREQ,))
_BOOL_FIELDS = frozenset((FIELD_RECEIVE_ONLY,))

# Which operators are valid for which fields.
_VALID_OPS = {
    FIELD_FREQ: (OP_EQ, OP_NE, OP_RANGE, OP_IN),
    FIELD_SERVICE: (OP_EQ, OP_NE, OP_IN),
    FIELD_DUPLEX: (OP_EQ, OP_NE, OP_IN),
    FIELD_OFFSET_DIRECTION: (OP_EQ, OP_NE),
    FIELD_MODE: (OP_EQ, OP_NE, OP_IN),
    FIELD_TONE_MODE: (OP_EQ, OP_NE, OP_IN),
    FIELD_NAME: (OP_EQ, OP_NE, OP_CONTAINS, OP_STARTSWITH, OP_ENDSWITH),
    FIELD_COMMENT: (OP_EQ, OP_NE, OP_CONTAINS, OP_STARTSWITH, OP_ENDSWITH),
    FIELD_SKIP: (OP_EQ, OP_NE, OP_IN),
    FIELD_RECEIVE_ONLY: (OP_EQ,),
    FIELD_CLASSIFICATION: (OP_EQ, OP_NE, OP_IN),
}


class RuleValidationError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: object

    def validate(self):
        if self.field not in ALL_FIELDS:
            raise RuleValidationError('Unknown match field %r' % self.field)
        if self.op not in _VALID_OPS.get(self.field, ()):
            raise RuleValidationError(
                'Operator %r is not valid for field %r' % (
                    self.op, self.field))
        if self.field in _NUMERIC_FIELDS:
            if self.op == OP_RANGE:
                if (not isinstance(self.value, (list, tuple)) or
                        len(self.value) != 2 or
                        not all(isinstance(v, int) for v in self.value) or
                        self.value[0] > self.value[1]):
                    raise RuleValidationError(
                        'range value must be a [low, high] pair of ints')
            elif self.op == OP_IN:
                if (not isinstance(self.value, (list, tuple)) or
                        not all(isinstance(v, int) for v in self.value)):
                    raise RuleValidationError(
                        'in value must be a list of ints')
            elif not isinstance(self.value, int):
                raise RuleValidationError(
                    '%s requires an integer value' % self.field)
        elif self.field in _BOOL_FIELDS:
            if not isinstance(self.value, bool):
                raise RuleValidationError(
                    '%s requires a boolean value' % self.field)
        else:
            if self.op == OP_IN:
                if (not isinstance(self.value, (list, tuple)) or
                        not all(isinstance(v, str) for v in self.value)):
                    raise RuleValidationError(
                        'in value must be a list of strings')
            elif not isinstance(self.value, str):
                raise RuleValidationError(
                    '%s requires a string value' % self.field)

    def matches(self, context):
        if self.field not in context:
            return False
        actual = context[self.field]
        if self.op == OP_EQ:
            return actual == self.value
        if self.op == OP_NE:
            return actual != self.value
        if self.op == OP_IN:
            return actual in self.value
        if self.op == OP_RANGE:
            lo, hi = self.value
            return lo <= actual <= hi
        if self.op == OP_CONTAINS:
            return self.value.lower() in (actual or '').lower()
        if self.op == OP_STARTSWITH:
            return (actual or '').lower().startswith(self.value.lower())
        if self.op == OP_ENDSWITH:
            return (actual or '').lower().endswith(self.value.lower())
        return False

    def to_dict(self):
        return {'field': self.field, 'op': self.op, 'value': self.value}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise RuleValidationError('Condition must be an object')
        try:
            cond = cls(field=data['field'], op=data['op'],
                       value=data['value'])
        except KeyError as e:
            raise RuleValidationError('Condition missing field %s' % e)
        cond.validate()
        return cond


@dataclasses.dataclass
class Rule:
    name: str
    enabled: bool
    priority: int
    conditions: tuple
    bg: str
    fg: str
    bold: bool = False
    description: str = ''

    def validate(self):
        if not self.name or not isinstance(self.name, str):
            raise RuleValidationError('Rule must have a non-empty name')
        if not isinstance(self.priority, int):
            raise RuleValidationError('Rule priority must be an integer')
        if not self.conditions:
            raise RuleValidationError(
                'Rule %r must have at least one condition' % self.name)
        for cond in self.conditions:
            cond.validate()
        if not contrast.is_valid_hex_color(self.bg):
            raise RuleValidationError(
                'Rule %r has an invalid background color %r' % (
                    self.name, self.bg))
        if not contrast.is_valid_hex_color(self.fg):
            raise RuleValidationError(
                'Rule %r has an invalid foreground color %r' % (
                    self.name, self.fg))

    def matches(self, context):
        return all(cond.matches(context) for cond in self.conditions)

    def to_dict(self):
        return {
            'name': self.name,
            'enabled': self.enabled,
            'priority': self.priority,
            'conditions': [c.to_dict() for c in self.conditions],
            'bg': self.bg,
            'fg': self.fg,
            'bold': self.bold,
            'description': self.description,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise RuleValidationError('Rule must be an object')
        try:
            conditions = tuple(Condition.from_dict(c)
                               for c in data['conditions'])
            rule = cls(
                name=data['name'],
                enabled=bool(data.get('enabled', True)),
                priority=int(data['priority']),
                conditions=conditions,
                bg=data['bg'],
                fg=data['fg'],
                bold=bool(data.get('bold', False)),
                description=str(data.get('description', '')),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise RuleValidationError('Malformed rule: %s' % e)
        rule.validate()
        return rule


def build_match_context(memory, *, service=None, candidate_category=None):
    """Build the field->value context a Condition.matches() checks against.

    @service is the pre-computed service id (e.g. 'ham', 'gmrs') if any.
    @candidate_category is the built-in category id that would apply
    absent any user rule, so rules can match on FIELD_CLASSIFICATION.
    """
    if memory.duplex in ('+', 'split') and memory.offset:
        offset_direction = 'positive'
    elif memory.duplex == '-' and memory.offset:
        offset_direction = 'negative'
    else:
        offset_direction = 'none'

    return {
        FIELD_FREQ: memory.freq,
        FIELD_SERVICE: service or '',
        FIELD_DUPLEX: memory.duplex,
        FIELD_OFFSET_DIRECTION: offset_direction,
        FIELD_MODE: memory.mode,
        FIELD_TONE_MODE: memory.tmode,
        FIELD_NAME: memory.name,
        FIELD_COMMENT: memory.comment,
        FIELD_SKIP: memory.skip,
        FIELD_RECEIVE_ONLY: memory.duplex == 'off',
        FIELD_CLASSIFICATION: candidate_category or '',
    }


def find_matching_rule(rules, context):
    """Return the highest-priority (lowest number) enabled matching rule."""
    candidates = [r for r in rules if r.enabled and r.matches(context)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: r.priority)[0]
