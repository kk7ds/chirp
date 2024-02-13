# Copyright 2015  Zachary T Welch  <zach@mandolincreekfarm.com>
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


r"""
The chirp.logger module provides the core logging facilities for CHIRP.
It sets up the console and (optionally) a log file.  For early debugging,
it checks the CHIRP_DEBUG, CHIRP_LOG, and CHIRP_LOG_LEVEL environment
variables.
"""

import contextlib
import os
import sys
import logging
import argparse
from . import platform
from chirp import CHIRP_VERSION


def version_string():
    args = (CHIRP_VERSION,
            platform.get_platform().os_version_string(),
            sys.version.split()[0])
    return "CHIRP %s on %s (Python %s)" % args


class VersionAction(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        print(version_string())
        sys.exit(1)


def add_version_argument(parser):
    parser.add_argument("--version", action=VersionAction, nargs=0,
                        help="Print version and exit")


#: Map human-readable logging levels to their internal values.
log_level_names = {"critical": logging.CRITICAL,
                   "error":    logging.ERROR,
                   "warn":     logging.WARNING,
                   "info":     logging.INFO,
                   "debug":    logging.DEBUG,
                   }


class Logger(object):

    log_format = '[%(asctime)s] %(name)s - %(levelname)s: %(message)s'

    def __init__(self):
        # create root logger
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.DEBUG)

        self.LOG = logging.getLogger(__name__)

        # Set CHIRP_DEBUG in environment for early console debugging.
        # It can be a number or a name; otherwise, level is set to 'debug'
        # in order to maintain backward compatibility.
        CHIRP_DEBUG = os.getenv("CHIRP_DEBUG")
        self.early_level = logging.WARNING
        if CHIRP_DEBUG:
            try:
                self.early_level = int(CHIRP_DEBUG)
            except ValueError:
                try:
                    self.early_level = log_level_names[CHIRP_DEBUG]
                except KeyError:
                    self.early_level = logging.DEBUG

        # If we're on Win32 or MacOS, we don't use the console; instead,
        # we create 'debug.log', redirect all output there, and set the
        # console logging handler level to DEBUG.  To test this on Linux,
        # set CHIRP_DEBUG_LOG in the environment.
        console_stream = None
        console_format = '%(levelname)s: %(message)s'
        if 'CHIRP_TESTENV' not in os.environ and (
                hasattr(sys, "frozen") or not os.isatty(0) or
                os.getenv("CHIRP_DEBUG_LOG")):
            p = platform.get_platform()
            log = open(p.config_file("debug.log"), "w")
            sys.stdout = log
            sys.stderr = log
            console_stream = log
            console_format = self.log_format
            self.early_level = logging.DEBUG
            self.has_debug_log_file = True
        else:
            self.has_debug_log_file = False

        self.console = logging.StreamHandler(console_stream)
        self.console_level = self.early_level
        self.console.setLevel(self.early_level)
        self.console.setFormatter(logging.Formatter(console_format))
        self.logger.addHandler(self.console)

        # Set CHIRP_LOG in environment to the name of log file.
        logname = os.getenv("CHIRP_LOG")
        self.logfile = None
        if logname is not None:
            self.create_log_file(logname)
            level = os.getenv("CHIRP_LOG_LEVEL")
            if level is not None:
                self.set_log_verbosity(level)
            else:
                self.set_log_level(logging.DEBUG)

        if self.early_level <= logging.DEBUG:
            self.LOG.debug(version_string())

    def create_log_file(self, name):
        if self.logfile is None:
            self.logname = name
            # always truncate the log file
            with open(name, "w"):
                pass
            self.logfile = logging.FileHandler(name)
            format_str = self.log_format
            self.logfile.setFormatter(logging.Formatter(format_str))
            self.logger.addHandler(self.logfile)
        else:
            self.logger.error("already logging to " + self.logname)

    def set_verbosity(self, level):
        self.LOG.debug("verbosity=%d", level)
        if level > logging.CRITICAL:
            level = logging.CRITICAL
        self.console_level = level
        self.console.setLevel(level)

    def set_log_level(self, level):
        self.LOG.debug("log level=%d", level)
        if level > logging.CRITICAL:
            level = logging.CRITICAL
        self.logfile.setLevel(level)

    def set_log_level_by_name(self, level):
        self.set_log_level(log_level_names[level])

    instance: object


Logger.instance = Logger()


def is_visible(level):
    """Returns True if a message at level will be shown on the console"""
    return level >= Logger.instance.console_level


def add_arguments(parser):
    parser.add_argument("-q", "--quiet", action="count", default=0,
                        help="Decrease verbosity")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity")
    parser.add_argument("--log", dest="log_file", action="store", default=0,
                        help="Log messages to a file")
    parser.add_argument("--log-level", action="store", default="debug",
                        help="Log file verbosity (critical, error, warn, " +
                        "info, debug).  Defaults to 'debug'.")


def handle_options(options):
    logger = Logger.instance

    if options.verbose or options.quiet:
        logger.set_verbosity(30 + 10 * (options.quiet - options.verbose))

    if options.log_file:
        logger.create_log_file(options.log_file)
        try:
            level = int(options.log_level)
            logger.set_log_level(level)
        except ValueError:
            logger.set_log_level_by_name(options.log_level)

    if logger.early_level > logging.DEBUG:
        logger.LOG.debug(version_string())


class LookbackHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self._history = []

    def emit(self, record):
        self._history.append(record)

    def get_history(self):
        return self._history


@contextlib.contextmanager
def log_history(level, root=None):
    root = logging.getLogger(root)
    handler = LookbackHandler()
    handler.setLevel(level)
    try:
        root.addHandler(handler)
        yield handler
    finally:
        root.removeHandler(handler)
