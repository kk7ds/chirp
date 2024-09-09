# Copyright 2016 Dan Smith <dsmith@danplanet.com>
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

import logging
import time

from chirp import chirp_common, directory, errors
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings


LOG = logging.getLogger(__name__)
BAUDS = [1200, 4800, 9600, 19200, 38400, 57600]
POWER_LEVELS = [chirp_common.PowerLevel('Low', dBm=10),
                chirp_common.PowerLevel('High', dBm=24)]
TONE_MODES = ['', 'Tone', 'TSQL', '']


def detect_baudrate(radio):
    bauds = list(BAUDS)
    bauds.remove(radio.pipe.baudrate)
    bauds.insert(0, radio.pipe.baudrate)
    for baud in bauds:
        radio.pipe.baudrate = baud
        radio.pipe.timeout = 0.5
        radio.pipe.write(b'\rFW?\r')
        resp = radio.pipe.read(2)
        if resp.strip().startswith(b'FW'):
            resp += radio.pipe.read(16)
            LOG.info('HobbyPCB %r at baud rate %i' % (resp.strip(), baud))
            return baud


@directory.register
class HobbyPCBRSUV3Radio(chirp_common.LiveRadio):
    """HobbyPCB RS-UV3"""
    VENDOR = "HobbyPCB"
    MODEL = "RS-UV3"
    BAUD_RATE = 19200

    def __init__(self, *args, **kwargs):
        super(HobbyPCBRSUV3Radio, self).__init__(*args, **kwargs)
        if self.pipe:
            baud = detect_baudrate(self)
            if not baud:
                raise errors.RadioError('Radio did not respond')

    def _cmd(self, command, rsize=None):
        command = command.encode()
        LOG.debug('> %s' % command)
        self.pipe.write(b'%s\r' % command)
        resp = b''

        if rsize is None:
            complete = lambda: time.sleep(0.1) is None
        elif rsize == 0:
            rsize = 1
            complete = lambda: resp.endswith(b'\r')
        else:
            complete = lambda: len(resp) >= rsize

        while not complete():
            chunk = self.pipe.read(rsize)
            if not chunk:
                break
            resp += chunk
        LOG.debug('< %r [%i]' % (resp, len(resp)))
        return resp.decode().strip()

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.has_name = False
        rf.has_cross = False
        rf.has_dtcs = False
        rf.has_rx_dtcs = False
        rf.has_dtcs_polarity = False
        rf.has_tuning_step = False
        rf.has_mode = False
        rf.has_settings = True
        rf.memory_bounds = (1, 9)  # This radio supports memories 0-9
        rf.valid_bands = [(144000000, 148000000),
                          (220000000, 222000000),
                          (440000000, 450000000),
                          ]
        rf.valid_tmodes = TONE_MODES
        rf.valid_power_levels = POWER_LEVELS
        return rf

    def get_memory(self, number):
        _mem = self._cmd('CP%i' % number, 33).split('\r')
        LOG.debug('Memory elements: %r' % _mem)
        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = int(_mem[0]) * 1000
        txfreq = int(_mem[1]) * 1000
        mem.offset = abs(txfreq - mem.freq)
        if mem.freq < txfreq:
            mem.duplex = '+'
        elif mem.freq > txfreq:
            mem.duplex = '-'
        else:
            mem.duplex = ''
        mem.ctone = int(_mem[2]) / 100.0
        mem.rtone = mem.ctone
        mem.tmode = TONE_MODES[int(_mem[3])]
        mem.power = POWER_LEVELS[int(_mem[5])]
        return mem

    def set_memory(self, mem):
        if mem.tmode in ['', 'Tone']:
            tone = mem.rtone * 100
        else:
            tone = mem.ctone * 100
        if mem.duplex == '+':
            self._cmd('FT%06i' % ((mem.freq + mem.offset) / 1000))
            self._cmd('FR%06i' % (mem.freq / 1000))
        elif mem.duplex == '-':
            self._cmd('FT%06i' % ((mem.freq - mem.offset) / 1000))
            self._cmd('FR%06i' % (mem.freq / 1000))
        else:
            self._cmd('FS%06i' % (mem.freq / 1000))
        self._cmd('TM%i' % TONE_MODES.index(mem.tmode))
        self._cmd('TF%05i' % tone)
        self._cmd('PW%i' % POWER_LEVELS.index(mem.power))
        self._cmd('ST%i' % mem.number)

    def get_settings(self):
        def _get(cmd):
            return self._cmd('%s?' % cmd, 0).split(':')[1].strip()

        cw = RadioSettingGroup('beacon', 'Beacon Settings')
        cl = RadioSetting('CL%15s', 'CW Callsign',
                          RadioSettingValueString(0, 15,
                                                  _get('CL')))
        cw.append(cl)

        cf = RadioSetting('CF%4i', 'CW Audio Frequency',
                          RadioSettingValueInteger(400, 1300,
                                                   int(_get('CF'))))
        cw.append(cf)

        cs = RadioSetting('CS%02i', 'CW Speed',
                          RadioSettingValueInteger(5, 25,
                                                   int(_get('CS'))))
        cw.append(cs)

        bc = RadioSetting('BC%03i', 'CW Beacon Timer',
                          RadioSettingValueInteger(0, 600,
                                                   int(_get('BC'))))
        cw.append(bc)

        bm = RadioSetting('BM%15s', 'Beacon Message',
                          RadioSettingValueString(0, 15,
                                                  _get('BM')))
        cw.append(bm)

        bt = RadioSetting('BT%03i', 'Beacon Timer',
                          RadioSettingValueInteger(0, 600,
                                                   int(_get('BT'))))
        cw.append(bt)

        it = RadioSetting('IT%03i', 'CW ID Timer',
                          RadioSettingValueInteger(0, 500,
                                                   int(_get('IT'))))
        cw.append(it)

        tg = RadioSetting('TG%7s', 'CW Timeout Message',
                          RadioSettingValueString(0, 7,
                                                  _get('TG')))
        cw.append(tg)

        io = RadioSettingGroup('io', 'IO')

        af = RadioSetting('AF%i', 'Arduino LPF',
                          RadioSettingValueBoolean(_get('AF') == 'ON'))
        io.append(af)

        input_pin = ['OFF', 'SQ OPEN', 'PTT']
        ai = RadioSetting('AI%i', 'Arduino Input Pin',
                          RadioSettingValueList(
                              input_pin,
                              current_index=int(_get('AI'))))
        io.append(ai)

        output_pin = ['LOW', 'SQ OPEN', 'DTMF DETECT', 'TX ON', 'CTCSS DET',
                      'HIGH']
        ao = RadioSetting('AO%i', 'Arduino Output Pin',
                          RadioSettingValueList(
                              output_pin,
                              current_index=int(_get('AO'))))
        io.append(ao)

        bauds = [str(x) for x in BAUDS]
        b1 = RadioSetting('B1%i', 'Arduino Baudrate',
                          RadioSettingValueList(
                              bauds,
                              current_index=int(_get('B1'))))
        io.append(b1)

        b2 = RadioSetting('B2%i', 'Main Baudrate',
                          RadioSettingValueList(
                              bauds,
                              current_index=int(_get('B2'))))
        io.append(b2)

        dtmf = RadioSettingGroup('dtmf', 'DTMF Settings')

        dd = RadioSetting('DD%04i', 'DTMF Tone Duration',
                          RadioSettingValueInteger(50, 2000,
                                                   int(_get('DD'))))
        dtmf.append(dd)

        dr = RadioSetting('DR%i', 'DTMF Tone Detector',
                          RadioSettingValueBoolean(_get('DR') == 'ON'))
        dtmf.append(dr)

        gt = RadioSetting('GT%02i', 'DTMF/CW Tone Gain',
                          RadioSettingValueInteger(0, 15,
                                                   int(_get('GT'))))
        dtmf.append(gt)

        sd = RadioSetting('SD%i', 'DTMF/CW Side Tone',
                          RadioSettingValueBoolean(_get('SD') == 'ON'))
        dtmf.append(sd)

        general = RadioSettingGroup('general', 'General')

        dp = RadioSetting('DP%i', 'Pre-Emphasis',
                          RadioSettingValueBoolean(_get('DP') == 'ON'))
        general.append(dp)

        fw = RadioSetting('_fw', 'Firmware Version',
                          RadioSettingValueString(0, 20,
                                                  _get('FW')))
        general.append(fw)

        gm = RadioSetting('GM%02i', 'Mic Gain',
                          RadioSettingValueInteger(0, 15,
                                                   int(_get('GM'))))
        general.append(gm)

        hp = RadioSetting('HP%i', 'Audio High-Pass Filter',
                          RadioSettingValueBoolean(_get('HP') == 'ON'))
        general.append(hp)

        ht = RadioSetting('HT%04i', 'Hang Time',
                          RadioSettingValueInteger(0, 5000,
                                                   int(_get('HT'))))
        general.append(ht)

        ledmode = ['OFF', 'ON', 'SQ OPEN', 'BATT CHG STAT']
        ld = RadioSetting('LD%i', 'LED Mode',
                          RadioSettingValueList(
                              ledmode,
                              current_index=int(_get('LD'))))
        general.append(ld)

        sq = RadioSetting('SQ%i', 'Squelch Level',
                          RadioSettingValueInteger(0, 9,
                                                   int(_get('SQ'))))
        general.append(sq)

        to = RadioSetting('TO%03i', 'Timeout Timer',
                          RadioSettingValueInteger(0, 600,
                                                   int(_get('TO'))))
        general.append(to)

        vu = RadioSetting('VU%02i', 'Receiver Audio Volume',
                          RadioSettingValueInteger(0, 39,
                                                   int(_get('VU'))))
        general.append(vu)

        rc = RadioSetting('RC%i', 'Current Channel',
                          RadioSettingValueInteger(0, 9, 0))
        rc.set_doc('Choosing one of these values causes the radio '
                   'to change to the selected channel. The radio '
                   'cannot tell CHIRP what channel is selected.')
        general.append(rc)

        return RadioSettings(general, cw, io, dtmf)

    def set_settings(self, settings):
        def _set(thing):
            # Try to only set something if it's new
            query = '%s?' % thing[:2]
            cur = self._cmd(query, 0)
            if cur.strip():
                cur = cur.split()[1].strip()
            new = thing[2:].strip()
            if cur in ['ON', 'OFF']:
                cur = int(cur == 'ON')
                new = int(new)
            elif cur.isdigit():
                cur = int(cur)
                new = int(new)
            if new != cur:
                LOG.info('Setting %s (%r != %r)' % (thing, cur, new))
                self._cmd(thing)
                time.sleep(1)

        for group in settings:
            for setting in group:
                if setting.get_name().startswith('_'):
                    LOG.debug('Skipping %s' % setting)
                    continue
                cmd = setting.get_name()
                value = setting.value.get_value()
                if hasattr(setting.value, '_options'):
                    value = setting.value._options.index(value)
                fullcmd = (cmd % value).strip()
                _set(fullcmd)
