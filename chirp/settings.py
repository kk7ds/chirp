# Copyright 2012 Dan Smith <dsmith@danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from chirp import chirp_common


class InvalidValueError(Exception):

    """An invalid value was specified for a given setting"""
    pass


class InternalError(Exception):

    """A driver provided an invalid settings object structure"""
    pass


class RadioSettingValue:

    """Base class for a single radio setting"""

    def __init__(self):
        self._current = None
        self._has_changed = False
        self._validate_callback = lambda x: x
        self._mutable = True

    def set_mutable(self, mutable):
        self._mutable = mutable

    def get_mutable(self):
        return self._mutable

    def changed(self):
        """Returns True if the setting has been changed since init"""
        return self._has_changed

    def set_validate_callback(self, callback):
        self._validate_callback = callback

    def set_value(self, value):
        """Sets the current value, triggers changed"""
        if not self.get_mutable():
            raise InvalidValueError("This value is not mutable")

        if self._current is not None and value != self._current:
            self._has_changed = True
        self._current = self._validate_callback(value)

    def get_value(self):
        """Gets the current value"""
        return self._current

    def __trunc__(self):
        return int(self.get_value())

    def __str__(self):
        return str(self.get_value())


class RadioSettingValueInteger(RadioSettingValue):

    """An integer setting"""

    def __init__(self, minval, maxval, current, step=1):
        RadioSettingValue.__init__(self)
        self._min = minval
        self._max = maxval
        self._step = step
        self.set_value(current)

    def set_value(self, value):
        try:
            value = int(value)
        except:
            raise InvalidValueError("An integer is required")
        if value > self._max or value < self._min:
            raise InvalidValueError("Value %i not in range %i-%i" %
                                    (value, self._min, self._max))
        RadioSettingValue.set_value(self, value)

    def get_min(self):
        """Returns the minimum allowed value"""
        return self._min

    def get_max(self):
        """Returns the maximum allowed value"""
        return self._max

    def get_step(self):
        """Returns the step increment"""
        return self._step


class RadioSettingValueFloat(RadioSettingValue):

    """A floating-point setting"""

    def __init__(self, minval, maxval, current, resolution=0.001, precision=4):
        RadioSettingValue.__init__(self)
        self._min = minval
        self._max = maxval
        self._res = resolution
        self._pre = precision
        self.set_value(current)

    def format(self, value=None):
        """Formats the value into a string"""
        if value is None:
            value = self._current
        fmt_string = "%%.%if" % self._pre
        return fmt_string % value

    def set_value(self, value):
        try:
            value = float(value)
        except:
            raise InvalidValueError("A floating point value is required")
        if value > self._max or value < self._min:
            raise InvalidValueError("Value %s not in range %s-%s" % (
                self.format(value),
                self.format(self._min), self.format(self._max)))

        # FIXME: honor resolution

        RadioSettingValue.set_value(self, value)

    def get_min(self):
        """Returns the minimum allowed value"""
        return self._min

    def get_max(self):
        """Returns the maximum allowed value"""


class RadioSettingValueBoolean(RadioSettingValue):

    """A boolean setting"""

    def __init__(self, current):
        RadioSettingValue.__init__(self)
        self.set_value(current)

    def set_value(self, value):
        RadioSettingValue.set_value(self, bool(value))

    def __bool__(self):
        return bool(self.get_value())
    __nonzero__ = __bool__

    def __str__(self):
        return str(bool(self.get_value()))


class RadioSettingValueList(RadioSettingValue):

    """A list-of-strings setting"""

    def __init__(self, options, current):
        RadioSettingValue.__init__(self)
        self._options = options
        self.set_value(current)

    def set_value(self, value):
        if value not in self._options:
            raise InvalidValueError("%s is not valid for this setting" % value)
        RadioSettingValue.set_value(self, value)

    def get_options(self):
        """Returns the list of valid option values"""
        return self._options

    def __trunc__(self):
        return self._options.index(self._current)


class RadioSettingValueString(RadioSettingValue):

    """A string setting"""

    def __init__(self, minlength, maxlength, current,
                 autopad=True, charset=chirp_common.CHARSET_ASCII):
        RadioSettingValue.__init__(self)
        self._minlength = minlength
        self._maxlength = maxlength
        self._charset = charset
        self._autopad = autopad
        self.set_value(current)

    def set_charset(self, charset):
        """Sets the set of allowed characters"""
        self._charset = charset

    def set_value(self, value):
        if len(value) < self._minlength or len(value) > self._maxlength:
            raise InvalidValueError("Value must be between %i and %i chars" %
                                    (self._minlength, self._maxlength))
        if self._autopad:
            value = value.ljust(self._maxlength)
        for char in value:
            if char not in self._charset:
                raise InvalidValueError("Value contains invalid " +
                                        "character `%s'" % char)
        RadioSettingValue.set_value(self, value)

    def __str__(self):
        return self._current


class RadioSettingValueMap(RadioSettingValueList):

    """Map User Options to Radio Memory Values

    Provides User Option list for GUI, maintains state, verifies new values,
    and allows {setting,getting} by User Option OR Memory Value.  External
    conversions not needed.

    """

    def __init__(self, map_entries, mem_val=None, user_option=None):
        """Create new map

        Pass in list of 2 member tuples, typically of type (str, int),
        for each Radio Setting.  First member of each tuple is the
        User Option Name, second is the Memory Value that corresponds.
        An example is APO: ("Off", 0), ("0.5", 5), ("1.0", 10).

        """
        # Catch bugs early by testing tuple geometry
        for map_entry in map_entries:
            if not len(map_entry) == 2:
                raise InvalidValueError("map_entries must be 2 el tuples "
                                        "instead of: %s" % str(map_entry))
        user_options = [e[0] for e in map_entries]
        self._mem_vals = [e[1] for e in map_entries]
        RadioSettingValueList.__init__(self, user_options, user_options[0])
        if mem_val is not None:
            self.set_mem_val(mem_val)
        elif user_option is not None:
            self.set_value(user_option)
        self._has_changed = False

    def set_mem_val(self, mem_val):
        """Change setting to User Option that corresponds to 'mem_val'"""
        if mem_val in self._mem_vals:
            index = self._mem_vals.index(mem_val)
            self.set_value(self._options[index])
        else:
            raise InvalidValueError(
                "%s is not valid for this setting" % mem_val)

    def get_mem_val(self):
        """Get the mem val corresponding to the currently selected user
        option"""
        return self._mem_vals[self._options.index(self.get_value())]

    def __trunc__(self):
        """Return memory value that matches current user option"""
        index = self._options.index(self._current)
        value = self._mem_vals[index]
        return value


def zero_indexed_seq_map(user_options):
    """RadioSettingValueMap factory method

    Radio Setting Maps commonly use a list of strings that map to a sequence
    that starts with 0.  Pass in a list of User Options and this function
    returns a list of tuples of form (str, int).

    """
    mem_vals = range(0, len(user_options))
    return zip(user_options, mem_vals)


class RadioSettings(list):

    def __init__(self, *groups):
        list.__init__(self, groups)

    def __str__(self):
        items = [str(self[i]) for i in range(0, len(self))]
        return "\n".join(items)


class RadioSettingGroup(object):

    """A group of settings"""

    def _validate(self, element):
        # RadioSettingGroup can only contain RadioSettingGroup objects
        if not isinstance(element, RadioSettingGroup):
            raise InternalError("Incorrect type %s" % type(element))

    def __init__(self, name, shortname, *elements):
        self._name = name            # Setting identifier
        self._shortname = shortname  # Short human-readable name/description
        self.__doc__ = name          # Longer explanation/documentation
        self._elements = {}
        self._element_order = []

        for element in elements:
            self._validate(element)
            self.append(element)

    def get_name(self):
        """Returns the group name"""
        return self._name

    def get_shortname(self):
        """Returns the short group identifier"""
        return self._shortname

    def set_doc(self, doc):
        """Sets the docstring for the group"""
        self.__doc__ = doc

    def __str__(self):
        string = "group '%s': {\n" % self._name
        for element in sorted(self._elements.values()):
            string += "\t" + str(element) + "\n"
        string += "}"
        return string

    # Kinda list interface

    def append(self, element):
        """Adds an element to the group"""
        self[element.get_name()] = element

    def __iter__(self):
        class RSGIterator:

            """Iterator for a RadioSettingGroup"""

            def __init__(self, rsg):
                self.__rsg = rsg
                self.__i = 0

            def __iter__(self):
                return self

            def next(self):
                """Next Iterator Interface"""
                if self.__i >= len(self.__rsg.keys()):
                    raise StopIteration()
                e = self.__rsg[self.__rsg.keys()[self.__i]]
                self.__i += 1
                return e
        return RSGIterator(self)

    # Dictionary interface

    def __len__(self):
        return len(self._elements)

    def __getitem__(self, name):
        return self._elements[name]

    def __setitem__(self, name, value):
        if name in self._element_order:
            raise KeyError("Duplicate item %s" % name)
        self._elements[name] = value
        self._element_order.append(name)

    def items(self):
        """Returns a key=>value set of elements, like a dict"""
        return [(name, self._elements[name]) for name in self._element_order]

    def keys(self):
        """Returns a list of string element names"""
        return self._element_order

    def values(self):
        """Returns the list of elements"""
        return [self._elements[name] for name in self._element_order]


class RadioSetting(RadioSettingGroup):

    """A single setting, which could be an array of items like a group"""

    def __init__(self, *args):
        super(RadioSetting, self).__init__(*args)
        self._apply_callback = None

    def set_apply_callback(self, callback, *args):
        self._apply_callback = lambda: callback(self, *args)

    def has_apply_callback(self):
        return self._apply_callback is not None

    def run_apply_callback(self):
        return self._apply_callback()

    def _validate(self, value):
        # RadioSetting can only contain RadioSettingValue objects
        if not isinstance(value, RadioSettingValue):
            raise InternalError("Incorrect type")

    def changed(self):
        """Returns True if any of the elements
        in the group have been changed"""
        for element in self._elements.values():
            if element.changed():
                return True
        return False

    def __str__(self):
        return "%s:%s" % (self._name, self.value)

    def __repr__(self):
        return "[RadioSetting %s:%s]" % (self._name, self._value)

    # Magic foo.value attribute
    def __getattr__(self, name):
        if name == "value":
            if len(self) == 1:
                return self._elements[self._element_order[0]]
            else:
                return self._elements.values()
        else:
            return self.__dict__[name]

    def __setattr__(self, name, value):
        if name == "value":
            if len(self) == 1:
                self._elements[self._element_order[0]].set_value(value)
            else:
                raise InternalError("Setting %s is not a scalar" % self._name)
        else:
            self.__dict__[name] = value

    # List interface

    def append(self, value):
        index = len(self._element_order)
        self._elements[index] = value
        self._element_order.append(index)

    def __getitem__(self, name):
        if not isinstance(name, int):
            raise IndexError("Index `%s' is not an integer" % name)
        return self._elements[name]

    def __setitem__(self, name, value):
        if not isinstance(name, int):
            raise IndexError("Index `%s' is not an integer" % name)
        if name in self._elements:
            self._elements[name].set_value(value)
        else:
            self._elements[name] = value
