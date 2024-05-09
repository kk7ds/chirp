#!/bin/env python3

import argparse
import contextlib
import logging
import random
import serial
import time
import sys

from chirp import bitwise
from chirp.drivers import icomciv
from chirp import memmap

LOG = logging.getLogger()

# Note these are only the frequencies from the chart that fit into the
# US band edges.
BANDS = {
    160: [i for i in range(1805, 2005, 20)],
    80: [i for i in range(3510, 4010, 10)],
    40: [i for i in range(7013, 7313, 25)],
    30: [10125],
    20: [i for i in range(14025, 14325, 50)],
    17: [18075, 18125, 18165],
    15: [i for i in range(21025, 21475, 50)],
    12: [24891, 24963],
    10: [i for i in range(28050, 29750, 100)],
    6: [i for i in range(50125, 54125, 250)],
}


class BitwiseFrame(icomciv.Frame):
    _fmt = ''
    _datalen = 0
    _querycmd: int | None = None

    def __init__(self):
        super().__init__()
        self._data = memmap.MemoryMapBytes(b'\x00' * self._datalen)
        self.parse()

    def parse(self):
        self._obj = bitwise.parse(self._fmt, self._data)

    @classmethod
    def get(cls, radio):
        f = icomciv.Frame()
        f.set_command(cls._querycmd or cls._cmd, cls._sub)
        radio._send_frame(f)
        r = radio._recv_frame(frame=cls())
        # If we used a different command to query, reset the received frame
        # to the one we'd use for the setting
        r._cmd = cls._cmd
        return r


class SetFreqFrame(BitwiseFrame):
    _datalen = 5
    _cmd = 0x05
    _querycmd = 0x03
    _sub = None
    _fmt = 'lbcd freq[5];'

    @property
    def freq(self):
        return self._obj.freq // 1000

    @freq.setter
    def freq(self, khz):
        self._obj.freq = khz * 1000


class SetModeFrame(BitwiseFrame):
    _datalen = 2
    _cmd = 0x06
    _querycmd = 0x04
    _sub = None
    _fmt = 'u8 mode; u8 filter;'
    _modes = [
        ('LSB', 0),
        ('USB', 1),
        ('AM', 2),
        ('CW', 3),
        ('RTTY', 4),
        ('FM', 5),
        ('CW-R', 7),
        ('RTTY-R', 8),
        ('PSK', 12),
        ('PSK-R', 17),
    ]

    @property
    def mode(self):
        for mode, index in self._modes:
            if index == self._obj.mode:
                return mode
        raise RuntimeError('Unsupported mode %i' % self._obj.mode)

    @mode.setter
    def mode(self, mode):
        self._obj.filter = 1
        for m, index in self._modes:
            if mode == m:
                self._obj.mode = index
                return
        raise RuntimeError('Unsupported mode %s' % mode)

    @property
    def filter(self):
        return int(self._obj.filter)


class BKINFrame(BitwiseFrame):
    _datalen = 1
    _cmd = 0x16
    _sub = 0x47
    _fmt = 'u8 mode;'
    _modes = ('off', 'semi', 'full')

    @property
    def mode(self):
        return self._modes[self._obj.mode]

    @mode.setter
    def mode(self, mode):
        self._obj.mode = self._modes.index(mode)


class CWSpeedFrame(BitwiseFrame):
    _datalen = 2
    _cmd = 0x14
    _sub = 0x0C
    _fmt = 'bbcd speed[2];'

    @property
    def speed(self):
        return 48 * self._obj.speed // 255

    @speed.setter
    def speed(self, wpm):
        self._obj.speed = int((wpm / 48) * 255)


class PowerFrame(BitwiseFrame):
    _datalen = 2
    _cmd = 0x15
    _sub = 0x11
    _fmt = 'bbcd power[2];'

    @classmethod
    def get(cls, radio):
        f = icomciv.Frame()
        f.set_command(cls._cmd, cls._sub)
        radio._send_frame(f)
        f = radio._recv_frame(frame=cls())
        f.parse()
        return f

    @property
    def power(self):
        return int(100 * int(self._obj.power) / 212)

    @power.setter
    def power(self, power):
        self._obj.power = 212 * (power / 100)


class Demo:
    def __init__(self, s=None):
        self._last_command = 0

    def _send_frame(self, f):
        self._last_command = f._cmd

    def _recv_frame(self, frame=None):
        if frame is None:
            frame = PowerFrame()
        if self._last_command == 0x15:
            frame.power = random.randint(0, 10) * 10
        else:
            frame.set_command(0xFB, None)
        return frame


def setup(port, rcls):
    LOG.debug('Connecting to %s' % port)
    s = serial.Serial(port, timeout=1)
    LOG.debug('Starting radio')
    radio = rcls(s)
    LOG.debug('Detecting baudrate')
    radio._detect_baudrate()
    LOG.debug('Connected')
    return radio


def set_freq(radio, khz, mode):
    f = SetFreqFrame()
    f.freq = khz
    radio._send_frame(f)
    r = radio._recv_frame()
    assert r._cmd == 0xFB
    LOG.debug('Set frequency to %i kHz', khz)

    f = SetModeFrame()
    f.mode = mode
    radio._send_frame(f)
    r = radio._recv_frame()
    assert r._cmd == 0xFB
    LOG.debug('Set mode to %s', mode)


def interactive_next(current):
    print()
    print('Options:')
    print('r: Retry this frequency')
    print('x: Exit immediately')
    print('[enter]: Continue to the next frequency')
    i = input('> ').lower()
    if i == '':
        return True
    elif i == 'r':
        return False
    elif i == 'x':
        raise RuntimeError('Abort')


def auto_next(current):
    print()
    return True


def send_id(radio, call):
    f = SetModeFrame()
    f.mode = 'CW'
    radio._send_frame(f)
    r = radio._recv_frame()
    assert r._cmd == 0xFB
    LOG.debug('Set mode to CW')

    f = BKINFrame()
    f.mode = 'full'
    radio._send_frame(f)
    r = radio._recv_frame()
    assert r._cmd == 0xFB
    LOG.debug('Set BK-IN to full')

    f = CWSpeedFrame()
    f.speed = 22
    radio._send_frame(f)
    r = radio._recv_frame()
    assert r._cmd == 0xFB
    LOG.debug('Set key speed to 22WPM')

    f = icomciv.Frame()
    f.set_command(0x17, 0x40)
    f.set_data(b'DE %s' % call.upper().encode())
    radio._send_frame(f)
    r = radio._recv_frame()
    if r._cmd != 0xFB:
        print('Radio does not support CWID - ID manually now')
    else:
        print('Sending id %s' % call)
    time.sleep(len(call) + 2)
    LOG.debug('Sent ID')


def wait_for_power(radio, fn):
    po = None
    maxl = 0
    while po is None or not fn(po):
        po = PowerFrame.get(radio).power
        line = sys.stdout.write('Po: |%-10s| %3iW\r' % ('=' * (po // 10), po))
        maxl = max(maxl, line)
        time.sleep(0.5)
    sys.stdout.write('%s\r' % (' ' * maxl))


def wait_for_tune(radio):
    print('Transmit to tune now (waiting for key)')
    wait_for_power(radio, lambda po: po > 0)
    print('Keyed, waiting for completion')
    wait_for_power(radio, lambda po: po == 0)
    print('Done')


@contextlib.contextmanager
def restore_settings(radio):
    if not isinstance(radio, Demo):
        settings = [
            SetModeFrame.get(radio),
            SetFreqFrame.get(radio),
            BKINFrame.get(radio),
            CWSpeedFrame.get(radio),
        ]
    else:
        settings = []
    try:
        yield
    finally:
        LOG.debug('Restoring previous settings')
        for f in settings:
            radio._send_frame(f)
            radio._recv_frame()


def tune_loop(radio, bands, call, next_fn):
    for band in bands:
        for freq in BANDS[band]:
            done = False
            while not done:
                print('Changing to %i kHz' % freq)
                set_freq(radio, freq, 'RTTY')
                time.sleep(1)

                wait_for_tune(radio)
                time.sleep(2)
                if call:
                    send_id(radio, call)

                try:
                    done = next_fn(freq)
                except RuntimeError:
                    return 0


def main():
    # More of these may work, but these are known to work
    radios = {
        '7200': icomciv.Icom7200Radio,
        '7300': icomciv.Icom7300Radio,
        '7610': icomciv.Icom7610Radio,
        'Demo': Demo,
    }

    p = argparse.ArgumentParser(description=(
        'A simple tool to automate running through the required frequencies '
        'to tune an SPE Expert linear.'))
    p.add_argument('radio', choices=radios,
                   help='Radio model')
    p.add_argument('port', help='Serial port for CAT control')
    p.add_argument('--bands', help=('Comma-separated list of bands '
                                    'to tune (160, 80, etc)'))
    p.add_argument('--call', help='Callsign for CW ID after each step')
    p.add_argument('--next',
                   choices=['interactive', 'auto'],
                   default='interactive',
                   help='Next step strategy')
    p.add_argument('--debug', action='store_true',
                   help='Enable verbose debugging')
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    next_fn = globals()['%s_next' % args.next]

    try:
        bands = [int(i) for i in args.bands.split(',')]
        for band in bands:
            assert band in BANDS
    except (ValueError, AssertionError):
        print('Invalid band input. Must be one or more of %s' % (
            ','.join(str(i) for i in BANDS.keys())))
        return 1

    if args.radio == 'Demo':
        radio = Demo()
    else:
        radio = setup(args.port, radios[args.radio])

    with restore_settings(radio):
        tune_loop(radio, bands, args.call, next_fn)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
