# Copyright 2024 Dan Smith <chirp@f.danplanet.com>
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

import inspect
import logging
import os
import re

import lark
import wx
import wx.adv
from wx import GetTranslation as _

from chirp import chirp_common

LOG = logging.getLogger(__name__)
LANG = """
start: qexpr
qexpr: qexpr (OPERATOR qexpr)* | "(" qexpr ")" | _expr
QUOTE: /"/
PROPERTY: /[a-z0-9_]+/
TEXT: /[^"]+/
INT: /[0-9]+/
FLOAT: /[0-9]+\\.[0-9]+/
OPERATOR: "AND"i | "OR"i
value: QUOTE TEXT QUOTE | INT | FLOAT
_list: "[" value ("," value)* "]"
_expr: equal | match | contains | range
equal: PROPERTY "=" value
contains: PROPERTY "IN"i _list
match: PROPERTY "~" value
range: PROPERTY "<" value "," value ">"
%ignore " "
"""

MEM_FIELDS_SKIP = ['CSV_FORMAT', 'empty', 'extd_number', 'immutable', 'vfo',
                   'extra']
MEM_FIELDS = [x for x in dir(chirp_common.Memory)
              if not x.startswith('_') and x not in MEM_FIELDS_SKIP and
              not inspect.isfunction(getattr(chirp_common.Memory, x))]


def union(a, b):
    return list({x.number: x for x in a + b}.values())


def intersection(a, b):
    only = {x.number for x in a} & {x.number for x in b}
    return list({x.number: x for x in a + b if x.number in only}.values())


class Interpreter(lark.Transformer):
    def __init__(self, memories, visit_tokens: bool = True) -> None:
        self._memories = memories
        super().__init__(visit_tokens)

    def _val(self, tree):
        if isinstance(tree, lark.Token):
            value = tree
        else:
            value = tree.children[0]
        if value.type == 'TEXT':
            return value.value
        elif value.type == 'INT':
            return int(value.value)
        elif value.type == 'FLOAT':
            return float(value.value)
        else:
            raise RuntimeError('Unsupported value type %r' % value.name)

    def _get(self, mem, key):
        if key == 'freq':
            return mem.freq / 1000000
        return getattr(mem, key)

    def equal(self, items):
        prop = items[0].value
        value = self._val(items[1])
        return [x for x in self._memories if self._get(x, prop) == value]

    def contains(self, items):
        prop = items[0].value
        opts = [self._val(x) for x in items[1:]]
        return [x for x in self._memories if self._get(x, prop) in opts]

    def match(self, items):
        prop = items[0].value
        value = self._val(items[1])
        return [x for x in self._memories
                if re.search(value, self._get(x, prop), re.IGNORECASE)]

    def range(self, items):
        prop = items[0].value
        lo = self._val(items[1])
        hi = self._val(items[2])
        return [x for x in self._memories if lo <= self._get(x, prop) <= hi]

    def value(self, items):
        if len(items) == 1:
            # value
            return items[0]
        else:
            # " value "
            return items[1]

    def OPERATOR(self, item):
        if item == 'OR':
            return union
        else:
            return intersection

    def qexpr(self, items):
        while len(items) > 2:
            left = items.pop(0)
            op = items.pop(0)
            right = items.pop(0)
            result = op(left, right)
            items.insert(0, result)
        return items[0]


class QueryFilterError(SyntaxError):
    pass


class PropertyNameError(QueryFilterError):
    label = _('Property Name')


class OperatorError(QueryFilterError):
    label = _('Operator')


class PropertyValueError(QueryFilterError):
    label = _('Property Value')


class PropertyValueStringError(QueryFilterError):
    label = _('Close String')


class PropertyValueFloatError(QueryFilterError):
    label = _('Finish Float')


class FilteringError(Exception):
    pass


class SearchHelp(wx.PopupTransientWindow):
    def __init__(self, parent):
        super().__init__(parent, flags=wx.SIMPLE_BORDER)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        self._msg = wx.StaticText(self)
        vbox.Add(self._msg, 1, flag=wx.EXPAND | wx.ALL, border=10)
        link = wx.adv.HyperlinkCtrl(
            self, label=_("Query syntax help"),
            url='https://chirpmyradio.com/projects/chirp/wiki/QueryStrings')
        vbox.Add(link, 1, flag=wx.EXPAND | wx.ALL, border=10)
        bgc = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
        self.SetBackgroundColour(bgc)

    def Show(self, show=True):
        parent = self.GetParent()
        psize = parent.GetSize()
        self.Position(parent.ClientToScreen((0, 0)), (10, psize[1]))
        self.SetMinSize((psize[0] - 40, 100))
        self.Fit()
        return super().Show(show)

    def clear(self):
        if self.GetParent().valid:
            self._msg.SetLabel(_('Query syntax OK'))
        else:
            self._msg.SetLabel(_('Type a simple search string or a formatted '
                                 'query and press enter'))
        self.Show(self.IsShown())

    def eat_error(self, exc, orig):
        try:
            expected = set(orig.expected)
        except AttributeError:
            try:
                expected = set(orig.allowed)
            except AttributeError:
                expected = []

        label = []
        if isinstance(exc, PropertyNameError):
            label.append(_('Memory field name (one of %s)') % ','.join(
                sorted(MEM_FIELDS)))
        elif isinstance(exc, PropertyValueError):
            label.append(_('Value to search memory field for'))
        elif isinstance(exc,
                        PropertyValueStringError) or expected == ['QUOTE']:
            label.append(_('Close string value with double-quote (")'))
        elif isinstance(exc, PropertyValueFloatError):
            label.append(_('Finish float value like: 146.52'))
        elif not isinstance(exc, (lark.exceptions.ParseError,
                                  lark.exceptions.UnexpectedCharacters)):
            label.append(str(exc))

        LOG.debug('Query string %r allowed next: %r',
                  self.GetParent().GetValue(), expected)

        exp_map = {
            'QUOTE': '"',
            'LESSTHAN': '<',
            'MORETHAN': '>',
            'LPAR': '(',
            'RPAR': ')',
            'TILDE': '~',
            'EQUAL': '=',
            'LSQB': '[',
            'RSQB': ']',
        }
        expected_filtered = sorted([exp_map.get(e, e) for e in expected])
        if expected:
            label.append('Expected: %s' % (','.join(expected_filtered)))

        for exp in sorted(expected):
            if exp == 'QUOTE':
                label.append(_('Example: "foo"'))
            elif exp == 'INT':
                label.append(_('Example: 123'))
            elif exp == 'FLOAT':
                label.append(_('Example: 146.52'))
            elif exp == 'OPERATOR':
                label.append(_('Example: AND, OR'))
            elif exp in ('LPAR', 'RPAR'):
                label.append(_('Example: ( expression )'))
            elif exp == 'TILDE':
                label.append(_('Example: name~"myrepea"'))
            elif exp == 'EQUAL':
                label.append(_('Example: name="myrepeater'))
            elif exp in ('LESSTHAN', 'MORETHAN'):
                label.append(_('Example: freq<146.0,148.0>'))
            elif exp == 'PROPERTY':
                label.append(_('One of: %s') % ','.join(MEM_FIELDS))
            else:
                LOG.debug(_('No example for %s') % exp)

        self._msg.SetLabel(os.linesep.join(label))
        self.Show()


class SearchBox(wx.TextCtrl):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.Bind(wx.EVT_TEXT, self._typing)
        self.parser = lark.Lark(LANG)
        self.query = None
        self.help = SearchHelp(self)
        self.help.Hide()
        self.help.clear()
        self.Bind(wx.EVT_SIZE, self._resize)
        self.SetHint(_('Filter...'))
        self.Bind(wx.EVT_SET_FOCUS, self._focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._unfocus)

    def _focus(self, event):
        self.help.Show()
        event.Skip()

    def _unfocus(self, event):
        # Without this delay, if the user clicks on the help link it won't
        # activate because we hide it too quickly (apparently)
        wx.CallLater(100, self.help.Hide)
        event.Skip()

    def _resize(self, event):
        self.help.Show(self.help.IsShown())
        event.Skip()

    _errors = {
        PropertyNameError: ['foo'],
        PropertyValueError: ['foo=', 'foo<', 'foo IN', 'foo~'],
        PropertyValueStringError: ['foo="', 'foo~"'],
        PropertyValueFloatError: ['foo=1.'],
        }

    def _typing(self, event):
        query_string = self.GetValue()
        self.help.Show()
        if not query_string.strip():
            self.help.clear()
            return
        if query_string.isalnum():
            # Assume simple search
            self.help.clear()
            return
        try:
            self.query = self.parser.parse(query_string)
            LOG.debug('Query:\n%s', self.query.pretty())
        except lark.UnexpectedInput as e:
            exc_class = e.match_examples(self.parser.parse, self._errors,
                                         use_accepts=True)
            if not exc_class:
                # No specific match
                exc = e
            else:
                exc = exc_class(e.get_context(query_string), e.line, e.column)
            self.help.eat_error(exc, e)
            self.query = None
        except Exception as e:
            LOG.debug('Parse error: %s (%s)', e, e.__class__)
            self.query = None
        else:
            self.help.clear()

    @property
    def valid(self):
        return self.query is not None

    def filter_memories(self, memories):
        if not self.query:
            raise QueryFilterError(_('Query string is invalid'))
        try:
            r = Interpreter(memories).transform(self.query)
        except lark.exceptions.VisitError as e:
            self.help.eat_error(e.orig_exc, e)
            self.help.Show()
            raise FilteringError(_('Error applying filter'))
        else:
            return r.children[0]
