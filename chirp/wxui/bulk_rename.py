# Copyright 2026 Tony Gies <tgies@tgies.net>
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
import re

import wx

LOG = logging.getLogger(__name__)

# Token buttons: (label, tooltip).
_DISPLAY_TOKENS = [
    ('{num}', 'Channel number'),
    ('{seq}', 'Sequential counter (1, 2, 3...)'),
    ('{freq}', 'Frequency in MHz (e.g. 462.5625)'),
    ('{freq_khz}', 'Frequency in kHz (e.g. 462562)'),
    ('{name}', 'Current channel name'),
    ('{mode}', 'Modulation (FM, NFM, AM)'),
    ('{duplex}', 'Duplex direction (+, -, off)'),
]

_SYNTAX_HELP = (
    'Format specs\n'
    '{freq:.1f} - 1 decimal (462.6)\n'
    '{seq:03d} - zero-padded (001)\n'
    '\n'
    'Counter options\n'
    '{seq+10} - start at 10\n'
    '{seq+10/2} - start 10, step 2\n'
    '\n'
    'Arithmetic (+ - * % //)\n'
    '{freq_khz%1000} - last 3 digits\n'
    '{freq_khz%1000:03d} - zero-padded\n'
    '\n'
    'Conditionals\n'
    '{duplex?+=RPTR|SPLX}\n'
    '  if + then RPTR, else SPLX\n'
    '{mode?FM=F|NFM=N|?}\n'
    '  map values, ? is fallback\n'
    '{duplex?!+=NOT PLUS|PLUS}\n'
    '  ! negates the match'
)


class CaseInsensitiveDict(dict):
    """Dict subclass that normalizes key lookups to lowercase."""

    def __init__(self, data):
        super().__init__({k.lower(): v for k, v in data.items()})

    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def __contains__(self, key):
        return super().__contains__(key.lower())


# Regex to match {seq}, {seq+N}, {seq+N/S}, {SEQ+N:fmt}, etc.
# Groups: 1=sign(+/-), 2=start, 3=step, 4=format_spec
_SEQ_RE = re.compile(
    r'\{[Ss][Ee][Qq]'       # opening {seq (case-insensitive)
    r'(?:([+-])(\d+))?'     # optional +N or -N
    r'(?:/(\d+))?'          # optional /step
    r'(:[^}]+)?'            # optional :format_spec
    r'\}',                  # closing }
)


def _extract_seq_params(m):
    """Extract (start, step) from a _SEQ_RE match."""
    sign = m.group(1)
    start_str = m.group(2)
    step_str = m.group(3)
    start = 1
    if start_str is not None:
        start = int(start_str)
        if sign == '-':
            start = -start
    step = int(step_str) if step_str else 1
    return start, step


def parse_seq_token(template):
    """Parse {seq} extended syntax out of a template string.

    Returns (normalized_template, start, step) where all {seq...}
    tokens have been replaced with plain {seq} or {seq:fmt}.
    Start and step are extracted from the first match.
    Raises ValueError if multiple seq tokens have conflicting
    start/step values.
    """
    matches = list(_SEQ_RE.finditer(template))
    if not matches:
        return template, 1, 1

    # Extract and validate start/step across all matches
    start, step = _extract_seq_params(matches[0])
    for m in matches[1:]:
        s, st = _extract_seq_params(m)
        if s != start or st != step:
            raise ValueError(
                'conflicting {seq} modifiers: '
                '%s vs %s' % (matches[0].group(),
                              m.group()))

    # Replace all matches, preserving each one's format spec
    def _replace(m):
        fmt = m.group(4) or ''
        return '{seq%s}' % fmt

    normalized = _SEQ_RE.sub(_replace, template)
    return normalized, start, step


# Memory attributes to skip
_SKIP_ATTRS = frozenset((
    'empty', 'immutable', 'extra', 'vfo', 'extd_number',
))

# Attributes needing conversion from raw storage
_CONVERSIONS = {
    'freq': lambda v: v / 1_000_000,
    'offset': lambda v: v / 1_000_000,
    'power': lambda v: str(v) if v else '',
}


def build_format_dict(mem, seq_value):
    """Build the format dict from a Memory object.

    Dynamically exposes all Memory attributes plus extras.
    Frequency and offset are converted from Hz to MHz.
    """
    d = {}

    # Pull all public attributes from Memory
    for attr in dir(mem):
        if attr.startswith('_') or attr in _SKIP_ATTRS:
            continue
        val = getattr(mem, attr, None)
        if callable(val):
            continue
        if attr in _CONVERSIONS:
            val = _CONVERSIONS[attr](val)
        d[attr] = val

    # Aliases and derived tokens
    d['num'] = mem.number
    d['freq_khz'] = mem.freq // 1000
    d['seq'] = seq_value

    # Flatten mem.extra settings into the dict
    if mem.extra:
        for setting in mem.extra:
            name = setting.get_name()
            if name not in d:
                d[name] = str(setting.value)

    return CaseInsensitiveDict(d)


# Regex to match {field+N}, {field//N}, {field%N}, etc.
# Groups: 1=field, 2=operator, 3=operand, 4=format_spec
_ARITH_RE = re.compile(
    r'\{(\w+)(//|[+\-*%])(\d+)(:[^}]+)?\}'
)

_ARITH_OPS = {
    '+': lambda a, b: a + b,
    '-': lambda a, b: a - b,
    '*': lambda a, b: a * b,
    '%': lambda a, b: a % b,
    '//': lambda a, b: a // b,
}


def resolve_arithmetic(template, fmt_dict):
    """Resolve {field<op>N} arithmetic expressions.

    Supported operators: + - * % //
    Result is injected into fmt_dict under a synthetic key.
    """
    counter = [0]

    def _resolve(m):
        field = m.group(1).lower()
        op = m.group(2)
        operand = int(m.group(3))
        fmt = m.group(4) or ''

        if field not in fmt_dict:
            raise KeyError(field)
        val = fmt_dict[field]
        if not isinstance(val, (int, float)):
            raise ValueError(
                'cannot do arithmetic on %s' % field)
        if operand == 0 and op in ('%', '//'):
            raise ValueError('division by zero')

        result = _ARITH_OPS[op](val, operand)
        if isinstance(result, float) and result == int(result):
            result = int(result)

        key = '_arith_%i' % counter[0]
        counter[0] += 1
        fmt_dict[key] = result
        return '{%s%s}' % (key, fmt)

    return _ARITH_RE.sub(_resolve, template)


# Regex to match {field?val=repl|val2=repl2|fallback}
# The expression part allows nested {token} references
# inside replacement values.
_COND_RE = re.compile(
    r'\{(\w+)\?((?:[^{}]|\{[^}]*\})+)\}'
)


def resolve_conditionals(template, fmt_dict):
    """Resolve {field?value=replacement|...} conditional tokens.

    Syntax:
        {field?val=repl|val2=repl2|fallback}

    Entries with = are match cases (if field equals val, emit
    repl). The last entry without = is the default. If no match
    and no default, the original field value passes through.
    Field lookup is case-insensitive.
    """
    def _resolve(m):
        field = m.group(1).lower()
        expr = m.group(2)
        if field not in fmt_dict:
            raise KeyError(field)
        field_val = str(fmt_dict[field])
        entries = expr.split('|')
        fallback = None
        for entry in entries:
            if '=' in entry:
                negate = entry.startswith('!')
                if negate:
                    entry = entry[1:]
                match_val, repl = entry.split('=', 1)
                matched = (match_val == field_val)
                if negate:
                    matched = not matched
                if matched:
                    return repl
            else:
                fallback = entry
        if fallback is not None:
            return fallback
        return field_val

    return _COND_RE.sub(_resolve, template)


class TemplateResult:
    """Result of applying a template: either a name or an error."""

    def __init__(self, value, error=None):
        self.value = value
        self.error = error

    @property
    def ok(self):
        return self.error is None


def apply_template(template, mem, row_index):
    """Apply a name template to a Memory object.

    Args:
        template: Format string with {token} placeholders.
        mem: chirp_common.Memory object.
        row_index: Zero-based index of this memory in the selection
                   (used for {seq} counter).

    Returns:
        TemplateResult with .value (formatted string) and
        .error (None on success, error message on failure).
    """
    try:
        normalized, start, step = parse_seq_token(template)
        seq_value = start + (row_index * step)
        fmt_dict = build_format_dict(mem, seq_value)
        normalized = resolve_arithmetic(
            normalized, fmt_dict)
        normalized = resolve_conditionals(
            normalized, fmt_dict)
        return TemplateResult(
            normalized.format_map(fmt_dict))
    except KeyError as e:
        return TemplateResult(
            '', 'unknown: %s' % str(e).strip("'"))
    except (ValueError, IndexError) as e:
        return TemplateResult('', str(e))


class BulkRenameDialog(wx.Dialog):
    """Dialog for renaming multiple channels using a template."""

    def __init__(self, parent, radio, memories):
        super().__init__(parent, title=_('Bulk Rename Channels'),
                         style=wx.DEFAULT_DIALOG_STYLE
                         | wx.RESIZE_BORDER)
        self._radio = radio
        self._memories = memories
        self._features = radio.get_features()

        self._build_ui()
        self._update_preview()

        self.SetSize(wx.Size(680, 520))
        self.CenterOnParent()

    def _build_ui(self):
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        # Left column: controls
        left = wx.BoxSizer(wx.VERTICAL)

        # Template input
        lbl = wx.StaticText(self, label=_('Template:'))
        left.Add(lbl, 0, wx.ALL, 5)

        self._template = wx.TextCtrl(self)
        self._template.Bind(wx.EVT_TEXT,
                            self._on_template_changed)
        left.Add(self._template, 0,
                 wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Token buttons
        token_lbl = wx.StaticText(
            self, label=_('Common tokens:'))
        left.Add(token_lbl, 0, wx.ALL, 5)

        token_sizer = wx.WrapSizer()
        for token, tip in _DISPLAY_TOKENS:
            btn = wx.Button(self, label=token,
                            style=wx.BU_EXACTFIT)
            btn.SetToolTip(_(tip))
            btn.Bind(
                wx.EVT_BUTTON,
                lambda e, t=token:
                    self._insert_token(t))
            token_sizer.Add(btn, 0, wx.ALL, 2)

        # "More..." button with popup of all tokens
        more_btn = wx.Button(self, label=_('More...'),
                             style=wx.BU_EXACTFIT)
        more_btn.Bind(wx.EVT_BUTTON,
                      self._on_more_tokens)
        token_sizer.Add(more_btn, 0, wx.ALL, 2)

        left.Add(token_sizer, 0,
                 wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Preview list
        preview_lbl = wx.StaticText(
            self, label=_('Preview:'))
        left.Add(preview_lbl, 0, wx.ALL, 5)

        self._preview = wx.ListCtrl(
            self, style=wx.LC_REPORT)
        self._preview.AppendColumn(_('Ch'), width=50)
        self._preview.AppendColumn(
            _('Current Name'), width=120)
        self._preview.AppendColumn(
            _('New Name'), width=200)
        left.Add(self._preview, 1,
                 wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # Radio constraints info
        info = _('Max name length: %i') % (
            self._features.valid_name_length)
        info_lbl = wx.StaticText(self, label=info)
        info_lbl.SetFont(
            info_lbl.GetFont().MakeSmaller())
        left.Add(info_lbl, 0, wx.ALL, 5)

        # Buttons
        btn_sizer = self.CreateStdDialogButtonSizer(
            wx.OK | wx.CANCEL)
        self._ok_btn = self.FindWindowById(wx.ID_OK)
        self._ok_btn.SetLabel(_('Apply'))
        self._ok_btn.Enable(False)
        left.Add(btn_sizer, 0,
                 wx.EXPAND | wx.ALL, 5)

        hbox.Add(left, 1, wx.EXPAND)

        # Right column: syntax help
        right = wx.BoxSizer(wx.VERTICAL)
        help_lbl = wx.StaticText(
            self, label=_('Syntax Reference'))
        help_lbl.SetFont(
            help_lbl.GetFont().MakeBold())
        right.Add(help_lbl, 0, wx.ALL, 5)

        help_text = wx.StaticText(
            self, label=_(_SYNTAX_HELP))
        right.Add(help_text, 0, wx.ALL, 5)

        hbox.Add(right, 0, wx.EXPAND | wx.RIGHT, 5)

        self.SetSizer(hbox)

    def _insert_token(self, token):
        """Insert a token string at the cursor position."""
        pos = self._template.GetInsertionPoint()
        self._template.Replace(pos, pos, token)
        self._template.SetInsertionPoint(
            pos + len(token))
        self._template.SetFocus()

    def _on_more_tokens(self, event):
        """Show popup menu with all available tokens."""
        # Build token list from first memory
        fmt_dict = build_format_dict(
            self._memories[0], 1)
        common = {t for t, _ in _DISPLAY_TOKENS}
        menu = wx.Menu()
        for key in sorted(fmt_dict.keys()):
            if key.startswith('_'):
                continue
            label = '{%s}' % key
            if label in common:
                continue
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(
                wx.EVT_MENU,
                lambda e, t=label:
                    self._insert_token(t),
                item)
        btn = event.GetEventObject()
        btn.PopupMenu(menu)
        menu.Destroy()

    def _on_template_changed(self, event):
        self._update_preview()

    def _update_preview(self):
        """Re-render the preview list from the template."""
        self._preview.DeleteAllItems()
        template = self._template.GetValue()
        has_error = False

        if not template:
            self._ok_btn.Enable(False)
            return

        for i, mem in enumerate(self._memories):
            r = apply_template(template, mem, i)
            if r.ok:
                new_name = self._radio.filter_name(
                    r.value)
            else:
                has_error = True
                new_name = r.error

            idx = self._preview.InsertItem(
                self._preview.GetItemCount(),
                str(mem.number))
            self._preview.SetItem(idx, 1, mem.name)
            self._preview.SetItem(idx, 2, new_name)

            if not r.ok:
                self._preview.SetItemTextColour(
                    idx, wx.Colour(200, 0, 0))

        self._ok_btn.Enable(not has_error)

    @property
    def new_names(self):
        """Return list of (memory, new_name) tuples."""
        template = self._template.GetValue()
        result = []
        for i, mem in enumerate(self._memories):
            r = apply_template(template, mem, i)
            name = self._radio.filter_name(r.value)
            result.append((mem, name))
        return result
