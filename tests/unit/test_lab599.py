import itertools
import unittest
from unittest import mock

from chirp import chirp_common, errors
from chirp.drivers import lab599
from chirp.drivers.lab599 import LAB599_MODES, SETTING_GROUPS, SPECS_BY_NAME, \
    BoolSpec, ChoiceSpec, CommandGate, CommandRefused, IntSpec, Lab599Cat, \
    MemoryRecord, StatusSpec
from chirp.settings import RadioSetting, RadioSettingSubGroup, \
    RadioSettingValueInteger
from tests.unit import base

# Captured from a TX-500MP
# MR<0><0><channel><frequency in Hz><mode><RF path><fixed fields>;
REAL_EMPTY_01 = 'MR000100000000000200000000000000000000000        ;'
REAL_USB_PREAMP_97 = 'MR009700014250000210000000000000000000000        ;'
REAL_CW_ATT_98 = 'MR009800010120000320000000000000000000000        ;'
REAL_IF = 'IF00001580000     +000000000010000540;'
REAL_SETTINGS = {
    'AC;': 'AC000;', 'AG0;': 'AG0175;', 'AL;': 'AL0;', 'BY;': 'BY10;',
    'CG;': 'CG010;', 'CN;': 'CN54;', 'CT;': 'CT0;', 'FA;': 'FA00001580000;',
    'FL;': 'FL00;', 'FR;': 'FR0;', 'FT;': 'FT0;', 'GT;': 'GT003;',
    'IF;': REAL_IF, 'IS;': 'IS0;', 'KS;': 'KS100;', 'LK;': 'LK00;',
    'MA;': 'MA020;', 'MC;': 'MC000;', 'MD;': 'MD1;', 'MG;': 'MG021;',
    'ML;': 'ML120;', 'MO;': 'MO1;', 'NB;': 'NB0;', 'NL;': 'NL050;',
    'NR;': 'NR0;', 'NT;': 'NT0;', 'PA;': 'PA00;', 'PC;': 'PC097;',
    'PL;': 'PL005;', 'PR;': 'PR1;', 'PS;': 'PS1;', 'RA;': 'RA0000;',
    'RG;': 'RG092;', 'RL;': 'RL050;', 'RM;': 'RM00000;', 'SM0;': 'SM00000;',
    'SQ0;': 'SQ0000;', 'TO;': 'TO0;', 'TP;': 'TP010;', 'VD;': 'VD1000;',
    'VG;': 'VG050;', 'VL;': 'VL12.0 ;', 'VX;': 'VX0;', 'TM;': 'TM02:35:12;',
}
# The radio adds these to the end when it answers, e.g. PA1; reads back as
# PA10;
SET_ANSWER_SUFFIX = {'PA': '0', 'RA': '00', 'RM': '0000'}
# Measured on a TX-500MP: the index is the RF gain written, the value is what
# the radio then reports
REAL_RF_GAIN_MAP = [
    0, 0, 0, 0, 0, 0, 2, 4, 4, 6,
    6, 8, 9, 9, 11, 11, 13, 15, 15, 17,
    17, 18, 18, 20, 22, 22, 24, 24, 25, 27,
    27, 29, 29, 31, 33, 33, 34, 34, 36, 36,
    38, 40, 40, 42, 42, 43, 45, 45, 47, 47,
    49, 50, 50, 52, 52, 54, 54, 56, 58, 58,
    59, 59, 61, 63, 63, 65, 65, 67, 68, 68,
    70, 70, 72, 72, 74, 75, 75, 77, 77, 79,
    81, 81, 83, 83, 84, 86, 86, 88, 88, 90,
    90, 92, 93, 93, 95, 95, 97, 99, 99, 100,
    100,
]
# Modes on one line share a stored value
REAL_SHARED = {
    'RG;': ('LSB USB', 'CW CWR', 'FM', 'AM', 'DIG'),
    'GT;': ('LSB USB', 'CW CWR', 'FM DIG', 'AM'),
    'SQ0;': ('LSB USB CW AM DIG CWR', 'FM'),
    'VG;': ('LSB USB FM AM', 'CW CWR', 'DIG'),
    'VD;': ('LSB USB FM AM', 'CW CWR', 'DIG'),
    'VX;': ('LSB USB FM AM', 'CW CWR', 'DIG'),
}
REAL_MODE_VALUES = {
    ('GT;', 'CW'): 'GT005;', ('GT;', 'FM'): 'GT010;',
    ('VG;', 'CW'): 'VG100;',
    ('VD;', 'CW'): 'VD0300;', ('VD;', 'DIG'): 'VD0100;',
}
REAL_FIXED = {('GT;', 'FM'), ('GT;', 'DIG'), ('VG;', 'CW'), ('VG;', 'CWR')}


def record(number, freq, mode, rf_path=0, command='MR'):
    return '%s00%02i%011i%i%i%s%s;' % (command, number, freq, mode, rf_path,
                                       '0' * 22, ' ' * 8)


class FakeTX500:
    def __init__(self, radio_id='505'):
        self.radio_id = radio_id
        self.ptt = 0
        self.records = {n: record(n, 0, 2) for n in range(100)}
        self.sent = []
        self.rx = bytearray()
        self.reject_writes = False
        self.corrupt_writes = False
        self.deaf = 0
        self.state = dict(REAL_SETTINGS)
        self.ignore_sets = False
        self.refuse_vox_on = False
        self.bare_sq = False
        self.stored = {}
        for read, groups in REAL_SHARED.items():
            for index, modes in enumerate(groups):
                self.stored[read, index] = REAL_MODE_VALUES.get(
                    (read, modes.split()[0]), self.state[read])

    @property
    def mode(self):
        return LAB599_MODES[int(self.state['MD;'][2])]

    @staticmethod
    def _store_index(read, mode):
        return next(index for index, modes in enumerate(REAL_SHARED[read])
                    if mode in modes.split())

    def saved(self, read, mode):
        index = self._store_index(read, mode)
        if index == self._store_index(read, self.mode):
            return self.state[read]
        return self.stored[read, index]

    def save(self, read, mode, reply):
        index = self._store_index(read, mode)
        self.stored[read, index] = reply
        if index == self._store_index(read, self.mode):
            self.state[read] = reply

    def _change_mode(self, frame):
        for read in REAL_SHARED:
            self.stored[read, self._store_index(read, self.mode)] = (
                self.state[read])
        self.state['MD;'] = frame
        for read in REAL_SHARED:
            self.state[read] = self.stored[
                read, self._store_index(read, self.mode)]

    def write(self, data):
        for frame in data.decode().split(';')[:-1]:
            frame += ';'
            self.sent.append(frame)
            self._handle(frame)

    def _handle(self, frame):
        if self.deaf and not frame.startswith('MW'):
            self.deaf -= 1
        elif frame == 'ID;':
            self.rx += b'ID%s;' % self.radio_id.encode()
        elif frame == 'PT;':
            self.rx += b'PT%i;' % self.ptt
        elif frame.startswith('MR'):
            self.rx += self.records[int(frame[4:6])].encode()
        elif frame.startswith('MW'):
            number, freq = int(frame[4:6]), int(frame[6:17])
            if self.reject_writes:
                self.rx += b'?;'
            elif self.corrupt_writes:
                pass
            elif freq and not 500000 <= freq <= 55990000:
                # Real radio clears the channel instead of refusing
                self.records[number] = record(number, 0, 2)
            else:
                self.records[number] = 'MR' + frame[2:]
        elif self.bare_sq and frame == 'SQ0;':
            self.rx += b';'
        elif self.bare_sq and frame == 'SQ;':
            self.rx += self.state['SQ0;'].encode()
        elif frame in self.state:
            self.rx += self.state[frame].encode()
        elif not self._apply_set(frame):
            self.rx += b'?;'

    def _apply_set(self, frame):
        code = frame[:2]
        read = {'AG': 'AG0;', 'SQ': 'SQ0;'}.get(code, code + ';')
        if read not in self.state or len(frame) <= 3:
            return False
        if code == 'MD':
            self._change_mode(frame)
            return True
        if (read, self.mode) in REAL_FIXED:
            return True
        if frame == 'VX1;' and self.refuse_vox_on:
            return True
        if code == 'TP':
            self.state['CG;'] = 'CG%s' % frame[2:]
        if code == 'RG' and not self.ignore_sets:
            self.state[read] = 'RG%03i;' % REAL_RF_GAIN_MAP[int(frame[2:5])]
        elif not self.ignore_sets:
            self.state[read] = '%s%s;' % (frame[:-1],
                                          SET_ANSWER_SUFFIX.get(code, ''))
        return True

    def read(self, count=1):
        data = bytes(self.rx[:count])
        del self.rx[:count]
        return data

    def read_until(self, expected):
        data = b''
        while not data.endswith(expected):
            byte = self.read(1)
            if not byte:
                break
            data += byte
        return data

    def reset_input_buffer(self):
        self.rx.clear()


class TestCommandGate(unittest.TestCase):
    def setUp(self):
        self.gate = CommandGate()

    def test_reads_allowed(self):
        for frame in ('ID;', 'PT;', 'MR0000;', 'MR0099;'):
            self.gate.check_read(frame)

    def test_dangerous_reads_refused(self):
        for frame in ('TX;', 'RX;', 'BD;', 'BU;', 'VV;', 'AI0;', 'AC011;',
                      'PS0;', 'FA00007000000;', 'MR1000;', 'MR00100;',
                      'MR00' + chr(0x661) + chr(0x662) + ';',
                      'ID;TX;', 'ID;\n', record(1, 7100000, 1)):
            with self.assertRaises(CommandRefused, msg=frame):
                self.gate.check_read(frame)

    def test_write_shape(self):
        self.gate.check_write(record(5, 7100000, 1, 2, 'MW'))
        self.gate.check_write(record(5, 0, 2, 0, 'MW'))

    def test_bad_writes_refused(self):
        good = record(5, 7100000, 1, 0, 'MW')
        bad = [
            good[:-2] + ';',                # short
            good[:-1] + ' ;',               # long
            good.replace('MW', 'MR', 1),
            good[:2] + '1' + good[3:],      # P1
            good[:17] + '8' + good[18:],    # mode
            good[:17] + '0' + good[18:],    # mode none
            good[:18] + '3' + good[19:],    # RF path
            good[:19] + '1' + good[20:],    # fixed field
            good[:41] + 'NAME    ;',        # P16
            'TX;',
        ]
        for frame in bad:
            with self.assertRaises(CommandRefused, msg=frame):
                self.gate.check_write(frame)


class TestLab599Cat(unittest.TestCase):
    def setUp(self):
        self.pipe = FakeTX500()
        self.cat = Lab599Cat(self.pipe)
        patcher = mock.patch.object(lab599, 'WRITE_SETTLE', 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_refused_frames_never_reach_the_pipe(self):
        with self.assertRaises(CommandRefused):
            self.cat.query('TX;')
        with self.assertRaises(CommandRefused):
            self.cat.write_memory('TX;')
        with self.assertRaises(CommandRefused):
            self.cat.query(record(1, 7100000, 1, 0, 'MW'))
        self.assertEqual([], self.pipe.sent)

    def test_timeout_is_set_on_the_pipe(self):
        self.assertEqual(lab599.REPLY_TIMEOUT, self.pipe.timeout)

    def test_error_replies_raise(self):
        for reply in (b'?;', b'E;', b'O;'):
            self.pipe.read = mock.Mock(side_effect=[bytes([c]) for c in reply])
            with self.assertRaises(errors.RadioError):
                self.cat.query('PT;')

    def test_wrong_reply_raises(self):
        self.pipe.read = mock.Mock(
            side_effect=itertools.cycle([b'I', b'D', b';']))
        with self.assertRaises(errors.RadioError):
            self.cat.query('PT;')

    def test_query_survives_write_stall(self):
        self.pipe.deaf = 3
        self.assertEqual('PT0;', self.cat.query('PT;'))
        self.assertEqual(['PT;'] * 4, self.pipe.sent)

    def test_probe_returns_bare_answers(self):
        self.pipe.bare_sq = True
        self.assertEqual(';', self.cat.probe('SQ0;'))

    def test_protocol_version_is_told_apart_by_its_answers(self):
        cases = (
            (True, 'TM02:35:12;', lab599.Lab599Protocol),
            (False, 'TM02:35:12;', lab599.Lab599ProtocolV130),
            (False, 'TM;', lab599.Lab599ProtocolV128),
            (False, None, lab599.Lab599ProtocolV128),
        )
        for bare_sq, clock, expected in cases:
            with self.subTest(expected=expected.__name__, clock=clock):
                pipe = FakeTX500()
                pipe.bare_sq = bare_sq
                if clock:
                    pipe.state['TM;'] = clock
                else:
                    del pipe.state['TM;']
                found = lab599.detect_protocol(Lab599Cat(pipe))
                self.assertIs(expected, type(found))

    def test_newest_protocol_reads_squelch_with_sq(self):
        self.pipe.bare_sq = True
        squelch = lab599.SETTING_COMMANDS['SQ']
        protocol = lab599.Lab599Protocol(self.cat)
        self.assertEqual('SQ0000;', protocol.read(squelch))
        self.assertEqual(['SQ;'], self.pipe.sent)

    def test_older_protocol_reads_squelch_with_sq0(self):
        squelch = lab599.SETTING_COMMANDS['SQ']
        protocol = lab599.Lab599ProtocolV130(self.cat)
        self.assertEqual('SQ0000;', protocol.read(squelch))
        self.assertEqual(['SQ0;'], self.pipe.sent)

    def test_oldest_protocol_has_no_clock(self):
        clock = lab599.SETTING_COMMANDS['TM']
        protocol = lab599.Lab599ProtocolV128(self.cat)
        self.assertIsNone(protocol.read(clock))
        self.assertEqual([], self.pipe.sent)

    def test_stale_reply_is_not_accepted(self):
        self.pipe.records[4] = record(5, 7100000, 1)
        with self.assertRaises(errors.RadioError):
            self.cat.query('MR0004;')

    def test_no_reply_raises(self):
        self.pipe.read = mock.Mock(return_value=b'')
        with self.assertRaises(errors.RadioNoResponse):
            self.cat.query('ID;')

    def test_ts2000_mode_explained(self):
        cat = Lab599Cat(FakeTX500('019'))
        with self.assertRaisesRegex(errors.RadioError, 'LAB599'):
            cat.require_id('505')

    def test_wrong_id_refused(self):
        cat = Lab599Cat(FakeTX500('999'))
        with self.assertRaises(errors.RadioError):
            cat.require_id('505')


class TestMemoryRecord(unittest.TestCase):
    def test_real_empty_record(self):
        parsed = MemoryRecord.from_spec(REAL_EMPTY_01)
        self.assertEqual(1, parsed.number)
        self.assertTrue(parsed.is_empty)
        mem = parsed.to_memory()
        self.assertTrue(mem.empty)
        self.assertEqual(1, mem.number)

    def test_real_populated_records(self):
        for spec, number, freq, mode, path in (
                (REAL_USB_PREAMP_97, 97, 14250000, 'USB', 'Preamp'),
                (REAL_CW_ATT_98, 98, 10120000, 'CW', 'ATT')):
            mem = MemoryRecord.from_spec(spec).to_memory()
            self.assertEqual((number, freq, mode, path),
                             (mem.number, mem.freq, mem.mode,
                              str(mem.extra['rf_path'].value)))
            self.assertEqual(spec[6:-1],
                             MemoryRecord.from_memory(mem).to_spec())

    def test_every_mode_and_rf_path(self):
        for code, mode in enumerate(LAB599_MODES[1:], 1):
            for path_code, path in enumerate(('Off', 'Preamp', 'ATT')):
                spec = record(42, 29600000, code, path_code)
                mem = MemoryRecord.from_spec(spec).to_memory()
                self.assertEqual((29600000, mode, path),
                                 (mem.freq, mem.mode,
                                  str(mem.extra['rf_path'].value)))
                self.assertEqual(spec[6:-1],
                                 MemoryRecord.from_memory(mem).to_spec())

    def test_malformed(self):
        for spec in ('', '?;', REAL_EMPTY_01[:-1], REAL_EMPTY_01[:-1] + ':',
                     'XX' + REAL_EMPTY_01[2:],
                     REAL_EMPTY_01[:6] + 'x' + REAL_EMPTY_01[7:]):
            with self.assertRaises(errors.RadioError, msg=spec):
                MemoryRecord.from_spec(spec)

    def test_unknown_mode(self):
        for code in (0, 8, 9):
            with self.assertRaises(errors.RadioError):
                MemoryRecord.from_spec(record(1, 7100000, code)).to_memory()

    def test_unknown_rf_path(self):
        with self.assertRaises(errors.RadioError):
            MemoryRecord.from_spec(record(1, 7100000, 1, 3)).to_memory()

    def test_empty_matches_regardless_of_mode(self):
        self.assertTrue(MemoryRecord.empty(3).matches(
            MemoryRecord.from_spec(record(3, 0, 1))))


class TestTX500MPRadio(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.pipe = FakeTX500()
        self.radio = lab599.TX500MPRadio(self.pipe)
        self.use(mock.patch.object(lab599, 'WRITE_SETTLE', 0))

    def _mem(self, number=10, freq=14250000, mode='USB'):
        mem = chirp_common.Memory()
        mem.number = number
        mem.freq = freq
        mem.mode = mode
        return mem

    def test_control_lines_stay_low(self):
        self.assertFalse(lab599.TX500MPRadio.WANTS_DTR)
        self.assertFalse(lab599.TX500MPRadio.WANTS_RTS)
        self.assertFalse(lab599.TX500MPRadio.HARDWARE_FLOW)

    def test_construct_without_pipe(self):
        rf = lab599.TX500MPRadio(None).get_features()
        self.assertEqual((0, 99), rf.memory_bounds)
        self.assertFalse(rf.has_name)

    def test_wrong_radio_refused(self):
        with self.assertRaises(errors.RadioError):
            lab599.TX500MPRadio(FakeTX500('500'))

    def test_tx500_uses_its_own_id(self):
        radio = lab599.TX500Radio(FakeTX500('500'))
        self.assertEqual('TX-500', radio.MODEL)
        self.assertTrue(radio.get_memory(0).empty)
        with self.assertRaises(errors.RadioError):
            lab599.TX500Radio(FakeTX500('505'))

    def test_read_all_sends_only_reads(self):
        for number in range(100):
            self.assertTrue(self.radio.get_memory(number).empty)
        expected = ['ID;'] + ['MR00%02i;' % n for n in range(100)]
        self.assertEqual(expected, self.pipe.sent)

    def test_read_is_cached_and_isolated(self):
        self.pipe.records[3] = record(3, 7100000, 1)
        first = self.radio.get_memory(3)
        first.freq = 1
        count = len(self.pipe.sent)
        self.assertEqual(7100000, self.radio.get_memory(3).freq)
        self.assertEqual(count, len(self.pipe.sent))

    def test_wrong_channel_reply_refused(self):
        self.pipe.records[3] = record(4, 7100000, 1)
        with self.assertRaises(errors.RadioError):
            self.radio.get_memory(3)

    def test_out_of_range(self):
        for number in (-1, 100):
            with self.assertRaises(errors.InvalidMemoryLocation):
                self.radio.get_memory(number)
            with self.assertRaises(errors.InvalidMemoryLocation):
                self.radio.erase_memory(number)

    def test_pipe_swap_reidentifies_and_drops_cache(self):
        self.radio.get_memory(3)
        new_pipe = FakeTX500()
        new_pipe.records[3] = record(3, 7100000, 1)
        self.radio.pipe = new_pipe
        self.assertEqual(7100000, self.radio.get_memory(3).freq)
        self.assertEqual(['ID;', 'MR0003;'], new_pipe.sent)

    def test_pipe_swap_to_wrong_radio_refused(self):
        self.radio.pipe = FakeTX500('019')
        with self.assertRaises(errors.RadioError):
            self.radio.get_memory(3)

    def test_set_memory(self):
        self.radio.set_memory(self._mem())
        self.assertEqual(['ID;', 'PT;', 'MR0010;',
                          record(10, 14250000, 2, 0, 'MW'), 'MR0010;'],
                         self.pipe.sent)
        self.assertEqual(14250000, self.radio.get_memory(10).freq)

    def test_set_memory_keeps_rf_path(self):
        self.pipe.records[10] = record(10, 7100000, 1, 2)
        mem = self.radio.get_memory(10)
        mem.freq = 7200000
        self.radio.set_memory(mem)
        self.assertEqual(record(10, 7200000, 1, 2), self.pipe.records[10])

    def test_refuses_while_transmitting(self):
        self.pipe.ptt = 1
        with self.assertRaisesRegex(errors.RadioError, 'transmitting'):
            self.radio.set_memory(self._mem())
        with self.assertRaisesRegex(errors.RadioError, 'transmitting'):
            self.radio.erase_memory(10)
        self.assertFalse([f for f in self.pipe.sent if f.startswith('MW')])

    def test_rejected_write_raises(self):
        self.pipe.reject_writes = True
        with self.assertRaises(errors.RadioError):
            self.radio.set_memory(self._mem())

    def test_mismatch_raises_and_drops_cache(self):
        self.radio.get_memory(10)
        self.pipe.corrupt_writes = True
        with self.assertRaisesRegex(errors.RadioError, 'did not store'):
            self.radio.set_memory(self._mem())
        self.assertNotIn(10, self.radio._memcache)

    def test_out_of_band_refused_before_send(self):
        self.pipe.records[10] = record(10, 7100000, 1, 2)
        for freq in (499999, 55990001, 60000000):
            with self.assertRaisesRegex(errors.RadioError, 'outside'):
                self.radio.set_memory(self._mem(freq=freq))
        self.assertFalse([f for f in self.pipe.sent if f.startswith('MW')])
        self.assertEqual(record(10, 7100000, 1, 2), self.pipe.records[10])

    def test_wiped_channel_is_restored(self):
        self.pipe.records[10] = record(10, 7100000, 1, 2)
        self.radio._valid_bands = [(0, 10 ** 9)]
        with self.assertRaisesRegex(errors.RadioError, 'restored'):
            self.radio.set_memory(self._mem(freq=60000000))
        self.assertEqual(record(10, 7100000, 1, 2), self.pipe.records[10])
        self.assertEqual(7100000, self.radio.get_memory(10).freq)

    def test_write_survives_stall(self):
        real_write = self.pipe.write

        def stall_after_mw(data):
            real_write(data)
            if data.startswith(b'MW'):
                self.pipe.deaf = 2
        self.pipe.write = stall_after_mw
        self.radio.set_memory(self._mem())
        self.assertEqual(14250000, self.radio.get_memory(10).freq)

    def test_erase(self):
        self.pipe.records[10] = record(10, 7100000, 1, 1)
        self.radio.get_memory(10)
        self.radio.erase_memory(10)
        self.assertEqual(record(10, 0, 2), self.pipe.records[10])
        self.assertTrue(self.radio.get_memory(10).empty)

    def test_setting_empty_memory_erases(self):
        self.pipe.records[10] = record(10, 7100000, 1)
        mem = chirp_common.Memory()
        mem.number = 10
        mem.empty = True
        self.radio.set_memory(mem)
        self.assertEqual(record(10, 0, 2), self.pipe.records[10])

    def test_unsupported_mode_refused_before_send(self):
        with self.assertRaises(errors.RadioError):
            self.radio.set_memory(self._mem(mode='WFM'))
        self.assertEqual(['ID;'], self.pipe.sent)

    def test_band_edges_validate(self):
        rf = self.radio.get_features()
        self.assertFalse(rf.validate_memory(self._mem(freq=500000)))
        self.assertFalse(rf.validate_memory(self._mem(freq=55990000)))
        self.assertTrue(rf.validate_memory(self._mem(freq=55990001)))

    def test_fields_the_radio_cannot_store_have_no_columns(self):
        rf = self.radio.get_features()
        for field in (rf.valid_tmodes, rf.valid_tones, rf.valid_duplexes,
                      rf.valid_skips):
            self.assertEqual([], field)

    def test_fields_the_radio_cannot_store_are_still_refused(self):
        self.assertFalse(self.radio.validate_memory(self._mem()))
        for field, value in (('tmode', 'Tone'), ('duplex', '+'),
                             ('skip', 'S')):
            mem = self._mem()
            setattr(mem, field, value)
            self.assertTrue(self.radio.validate_memory(mem), field)


class TestProtocolTable(unittest.TestCase):
    def setUp(self):
        self.gate = CommandGate()

    def _action_frames(self):
        for command in lab599.ACTION_COMMANDS.values():
            if command.params:
                for value in (0, 1):
                    yield command.template.format(
                        *[value] * len(command.params))
                yield command.template.format(
                    *['%0*i' % (param.width, param.hi)
                      for param in command.params])
            else:
                yield command.template

    def test_every_documented_command_is_listed(self):
        documented = {
            'AC', 'AG', 'AL', 'BY', 'BD', 'BU', 'CG', 'CN', 'CT', 'FA', 'FB',
            'FL', 'FR', 'FT', 'GT', 'ID', 'IF', 'IS', 'KS', 'LK', 'MC', 'MD',
            'MA', 'MG', 'MR', 'ML', 'MO', 'MW', 'NB', 'NL', 'NR', 'NT', 'PA',
            'PC', 'PL', 'PR', 'PS', 'PT', 'RA', 'RG', 'RM', 'RT', 'RX', 'RL',
            'SM', 'SP', 'SQ', 'TO', 'TP', 'TX', 'VD', 'VG', 'VV', 'VL', 'VX',
            'XT', 'NF', 'TM',
        }
        listed = {'MR', 'MW', *lab599.SETTING_COMMANDS,
                  *lab599.STATUS_COMMANDS, *lab599.ACTION_COMMANDS,
                  *lab599.UNSUPPORTED_COMMANDS}
        self.assertEqual(set(), documented - listed)

    def test_action_frames_cannot_pass_the_gate(self):
        frames = list(self._action_frames())
        self.assertIn('TX;', frames)
        self.assertIn('AC011;', frames)
        self.assertIn('PT1;', frames)
        for frame in frames:
            for check in (self.gate.check_read, self.gate.check_set,
                          self.gate.check_write):
                with self.assertRaises(CommandRefused, msg=frame):
                    check(frame)

    def test_action_commands_cannot_build_frames(self):
        for command in lab599.ACTION_COMMANDS.values():
            with self.assertRaises(errors.RadioError):
                command.set_frame(*[1] * len(command.params))

    def test_unsupported_commands_cannot_be_sent(self):
        for command in lab599.UNSUPPORTED_COMMANDS.values():
            with self.assertRaises(CommandRefused):
                self.gate.check_read(command.read)

    def test_setting_limits_are_enforced(self):
        for command in lab599.SETTING_COMMANDS.values():
            low = [param.lo for param in command.params]
            high = [param.hi for param in command.params]
            self.gate.check_set(command.set_frame(*low))
            self.gate.check_set(command.set_frame(*high))
            for index, param in enumerate(command.params):
                over = list(high)
                over[index] = param.hi + param.step
                with self.assertRaises(errors.RadioError, msg=command.code):
                    command.set_frame(*over)

    def test_tuning_cannot_start_through_the_tuner_setting(self):
        command = lab599.SETTING_COMMANDS['AC']
        self.assertEqual('AC010;', command.set_frame(1))
        self.assertFalse(command.accepts('AC011;'))
        self.assertFalse(command.accepts('AC001;'))

    def test_ctcss_table(self):
        self.assertEqual(42, len(lab599.CTCSS_TONES))
        self.assertEqual(67.0, lab599.CTCSS_TONES[0])
        self.assertEqual(100.0, lab599.CTCSS_TONES[12])
        self.assertEqual(254.1, lab599.CTCSS_TONES[41])


class TestRadioSettings(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.pipe = FakeTX500()
        self.radio = lab599.TX500MPRadio(self.pipe)
        self.use(mock.patch.object(lab599, 'WRITE_SETTLE', 0))
        self.use(mock.patch.object(lab599, 'MODE_SETTLE', 0))

    @classmethod
    def _find(cls, top, name):
        for element in top:
            if isinstance(element, RadioSetting):
                continue
            if name in element.keys():
                return element[name]
            try:
                return cls._find(element, name)
            except KeyError:
                pass
        raise KeyError(name)

    def _sets_sent(self):
        return [f for f in self.pipe.sent
                if f not in lab599.READ_FRAMES and
                not f.startswith(('MR', 'MD'))]

    def _modes_sent(self):
        return [f for f in self.pipe.sent
                if f.startswith('MD') and f != 'MD;']

    def _change(self, name, value):
        top = self.radio.get_settings()
        self._find(top, name).value = value
        self.radio.set_settings(top)

    def test_groups(self):
        top = self.radio.get_settings()
        self.assertEqual(
            ['Operating', 'Receiver', 'Noise', 'Transmit', 'Audio',
             'CW & VOX', 'Tones', 'Status'],
            [group.get_shortname() for group in top])

    def test_per_mode_settings_have_a_section_per_mode(self):
        top = self.radio.get_settings()

        def pages(group):
            return {element.get_shortname(): list(element.keys())
                    for element in group
                    if isinstance(element, RadioSettingSubGroup)}

        self.assertEqual({
            'SSB': ['rf_gain_ssb', 'agc_ssb'],
            'CW': ['rf_gain_cw', 'agc_cw'],
            'DIG': ['rf_gain_dig'],
            'AM': ['rf_gain_am', 'agc_am'],
            'FM': ['rf_gain_fm', 'squelch_fm'],
        }, pages(top['receiver']))
        self.assertEqual({
            'CW': ['vox_cw', 'vox_delay_cw'],
            'MIC': ['vox_mic', 'vox_gain_mic', 'vox_delay_mic'],
            'DIG': ['vox_dig', 'vox_gain_dig', 'vox_delay_dig'],
        }, pages(top['cw_vox']))
        self.assertIn('squelch_ssb_am', top['receiver'].keys())

    def test_change_in_a_section_is_applied(self):
        self._change('agc_cw', 7)
        self.assertEqual('GT007;', self.pipe.saved('GT;', 'CW'))
        self.assertEqual('GT003;', self.pipe.saved('GT;', 'LSB'))

    def test_real_values(self):
        top = self.radio.get_settings()
        for name, expected in (('vfo_a', 1580000), ('af_gain', 175),
                               ('power', 97), ('agc_ssb', 3),
                               ('keyer_speed', 100), ('vox_delay_mic', 1000),
                               ('memory_channel', 0)):
            self.assertEqual(expected, int(self._find(top, name).value), name)
        self.assertEqual('LSB', str(self._find(top, 'mode').value))
        self.assertEqual('Radio value 54',
                         str(self._find(top, 'ctcss_tone').value))
        self.assertFalse(bool(self._find(top, 'vox_mic').value))
        self.assertTrue(bool(self._find(top, 'compressor').value))
        self.assertEqual('12.0 V', str(self._find(top, 'voltage').value))
        self.assertEqual('Yes', str(self._find(top, 'busy').value))
        self.assertEqual('Receive', str(self._find(top, 'ptt').value))

    def test_reading_only_changes_mode_and_returns(self):
        for number in range(1, 8):
            self.pipe.state['MD;'] = 'MD1;'
            self.pipe._change_mode('MD%i;' % number)
            before = dict(self.pipe.state)
            self.pipe.sent.clear()
            self.radio.get_settings()
            self.assertEqual([], self._sets_sent(), number)
            self.assertEqual('MD%i;' % number, self._modes_sent()[-1])
            self.assertEqual(before, self.pipe.state, number)

    def test_saving_unchanged_settings_sends_nothing(self):
        top = self.radio.get_settings()
        self.pipe.sent.clear()
        self.radio.set_settings(top)
        self.assertEqual([], self._sets_sent())
        self.assertEqual([], self._modes_sent())

    def test_every_group_shows_its_own_value(self):
        top = self.radio.get_settings()
        for name, expected in (('agc_ssb', 3), ('agc_cw', 5), ('agc_am', 3),
                               ('vox_gain_mic', 50), ('vox_gain_dig', 50),
                               ('vox_delay_mic', 1000), ('vox_delay_cw', 300),
                               ('vox_delay_dig', 100), ('squelch_ssb_am', 0),
                               ('squelch_fm', 0)):
            self.assertEqual(expected, int(self._find(top, name).value), name)
        for group in ('ssb', 'cw', 'dig', 'am', 'fm'):
            setting = self._find(top, 'rf_gain_' + group)
            self.assertEqual('0', str(setting.value))
        for group in ('cw', 'mic', 'dig'):
            self.assertFalse(bool(self._find(top, 'vox_' + group).value))

    def test_values_the_radio_fixes_are_not_offered(self):
        for name in ('agc_fm', 'agc_dig', 'vox_gain_cw'):
            self.assertNotIn(name, SPECS_BY_NAME)

    def test_groups_match_the_measured_radio(self):
        for code, groups in lab599.MODE_GROUPS.items():
            read = lab599.SETTING_COMMANDS[code].read
            for modes in groups.values():
                indexes = {FakeTX500._store_index(read, mode)
                           for mode in modes}
                self.assertEqual(1, len(indexes), (code, modes))
            for first, second in itertools.combinations(groups.values(), 2):
                self.assertNotEqual(
                    FakeTX500._store_index(read, first[0]),
                    FakeTX500._store_index(read, second[0]), code)

    def test_change_in_another_mode_reaches_only_that_group(self):
        self._change('rf_gain_fm', '-50')
        self.assertEqual('RG002;', self.pipe.saved('RG;', 'FM'))
        for mode in ('LSB', 'CW', 'DIG', 'AM'):
            self.assertEqual('RG092;', self.pipe.saved('RG;', mode), mode)
        self.assertEqual('MD1;', self.pipe.state['MD;'])

    def test_later_edit_does_not_revisit_earlier_modes(self):
        top = self.radio.get_settings()
        self._find(top, 'agc_cw').value = 7
        self.radio.set_settings(top)
        self.pipe.sent.clear()
        self._find(top, 'squelch_fm').value = 10
        self.radio.set_settings(top)
        self.assertEqual(['MD4;', 'MD1;'], self._modes_sent())
        self.assertEqual(['SQ0010;'], self._sets_sent())

    def test_earlier_edit_can_be_changed_back(self):
        top = self.radio.get_settings()
        self._find(top, 'agc_cw').value = 7
        self.radio.set_settings(top)
        self._find(top, 'agc_cw').value = 5
        self.radio.set_settings(top)
        self.assertEqual('GT005;', self.pipe.saved('GT;', 'CW'))

    def test_earlier_edit_does_not_undo_a_change_on_the_radio(self):
        top = self.radio.get_settings()
        self._find(top, 'mode').value = 'CW'
        self.radio.set_settings(top)
        self.pipe._change_mode('MD2;')
        self.pipe.sent.clear()
        self._find(top, 'af_gain').value = 100
        self.radio.set_settings(top)
        self.assertEqual([], self._modes_sent())
        self.assertEqual('MD2;', self.pipe.state['MD;'])
        self.assertEqual('AG0100;', self.pipe.state['AG0;'])

    def test_failed_edit_is_tried_again(self):
        top = self.radio.get_settings()
        self._find(top, 'agc_cw').value = 7
        self.pipe.ignore_sets = True
        with self.assertRaises(errors.RadioError):
            self.radio.set_settings(top)
        self.pipe.ignore_sets = False
        self.radio.set_settings(top)
        self.assertEqual('GT007;', self.pipe.saved('GT;', 'CW'))

    def test_change_in_current_mode_does_not_switch(self):
        top = self.radio.get_settings()
        self._find(top, 'agc_ssb').value = 7
        self.pipe.sent.clear()
        self.radio.set_settings(top)
        self.assertEqual([], self._modes_sent())
        self.assertEqual('GT007;', self.pipe.state['GT;'])

    def test_failed_change_in_another_mode_still_returns(self):
        top = self.radio.get_settings()
        self._find(top, 'agc_cw').value = 7
        self.pipe.ignore_sets = True
        with self.assertRaisesRegex(errors.RadioError, 'did not accept'):
            self.radio.set_settings(top)
        self.assertEqual('MD1;', self.pipe.state['MD;'])

    def test_mode_with_vox_on_is_read_with_vox_off(self):
        self.pipe.save('VX;', 'CW', 'VX1;')
        top = self.radio.get_settings()
        sent = self.pipe.sent
        off = sent.index('VX0;')
        self.assertLess(sent.index('MD3;'), off)
        self.assertLess(off, sent.index('RG;', off))
        self.assertLess(sent.index('RG;', off), sent.index('VX1;'))
        self.assertEqual('VX1;', self.pipe.saved('VX;', 'CW'))
        self.assertEqual('MD1;', self.pipe.state['MD;'])
        vox = self._find(top, 'vox_cw')
        self.assertTrue(bool(vox.value))
        self.assertTrue(vox.value.get_mutable())
        self.assertEqual('0', str(self._find(top, 'rf_gain_cw').value))

    def test_shared_vox_is_held_off_across_modes(self):
        self.pipe._change_mode('MD3;')
        self.pipe.save('VX;', 'LSB', 'VX1;')
        top = self.radio.get_settings()
        self.assertEqual(1, self.pipe.sent.count('VX0;'))
        self.assertEqual(1, self.pipe.sent.count('VX1;'))
        self.assertEqual('VX1;', self.pipe.saved('VX;', 'LSB'))
        self.assertEqual('MD3;', self.pipe.state['MD;'])
        self.assertTrue(bool(self._find(top, 'vox_mic').value))
        for name in ('rf_gain_ssb', 'rf_gain_am', 'rf_gain_fm'):
            self.assertEqual('0', str(self._find(top, name).value), name)

    def test_current_mode_with_vox_on_stays_editable(self):
        self.pipe.state['VX;'] = 'VX1;'
        top = self.radio.get_settings()
        self.assertTrue(self._find(top, 'vox_mic').value.get_mutable())

    def test_change_in_a_mode_with_vox_on(self):
        self.pipe.save('VX;', 'CW', 'VX1;')
        self._change('agc_cw', 7)
        self.assertEqual('GT007;', self.pipe.saved('GT;', 'CW'))
        self.assertEqual('VX1;', self.pipe.saved('VX;', 'CW'))
        self.assertEqual('MD1;', self.pipe.state['MD;'])

    def test_vox_can_be_turned_off_in_another_mode(self):
        self.pipe.save('VX;', 'CW', 'VX1;')
        top = self.radio.get_settings()
        self._find(top, 'vox_cw').value = False
        self.pipe.sent.clear()
        self.radio.set_settings(top)
        self.assertEqual('VX0;', self.pipe.saved('VX;', 'CW'))
        self.assertNotIn('VX1;', self.pipe.sent)
        self.assertEqual('MD1;', self.pipe.state['MD;'])

    def test_vox_that_stays_on_stops_the_visit(self):
        self.pipe.save('VX;', 'CW', 'VX1;')
        self.pipe.ignore_sets = True
        with self.assertRaisesRegex(errors.RadioError, 'VOX'):
            self.radio.get_settings()
        self.assertEqual('MD1;', self.pipe.state['MD;'])

    def test_vox_that_cannot_return_is_reported(self):
        self.pipe.save('VX;', 'CW', 'VX1;')
        self.pipe.refuse_vox_on = True
        with self.assertRaisesRegex(errors.RadioError,
                                    'VOX was left off for CW'):
            self.radio.get_settings()
        self.assertEqual('VX0;', self.pipe.saved('VX;', 'CW'))
        self.assertEqual('MD1;', self.pipe.state['MD;'])

    def test_vox_is_restored_when_its_off_reply_is_lost(self):
        self.pipe.save('VX;', 'CW', 'VX1;')
        real_write = self.pipe.write

        def lose_reply_after_vox_off(data):
            real_write(data)
            if data == b'VX0;':
                self.pipe.deaf = lab599.REPLY_ATTEMPTS
        self.pipe.write = lose_reply_after_vox_off
        with self.assertRaises(errors.RadioNoResponse):
            self.radio.get_settings()
        self.assertEqual('VX1;', self.pipe.saved('VX;', 'CW'))
        self.assertEqual('MD1;', self.pipe.state['MD;'])

    def test_memory_channel_blocks_mode_switching(self):
        self.pipe.state['FR;'] = 'FR2;'
        top = self.radio.get_settings()
        self.assertEqual([], self._modes_sent())
        self.assertEqual('0', str(self._find(top, 'rf_gain_ssb').value))
        self.assertIn('memory', str(self._find(top, 'rf_gain_fm').value))

    def test_transmitting_blocks_mode_switching(self):
        self.pipe.ptt = 1
        top = self.radio.get_settings()
        self.assertEqual([], self._modes_sent())
        self.assertIn('transmitting',
                      str(self._find(top, 'rf_gain_fm').value))

    def test_status_is_read_only(self):
        top = self.radio.get_settings()
        for _name, _label, specs in SETTING_GROUPS:
            for spec in specs:
                if isinstance(spec, StatusSpec):
                    value = self._find(top, spec.name).value
                    self.assertFalse(value.get_mutable())

    def test_every_setting_can_change(self):
        for spec in SPECS_BY_NAME.values():
            if isinstance(spec, StatusSpec):
                continue
            self.pipe = FakeTX500()
            self.radio = lab599.TX500MPRadio(self.pipe)
            top = self.radio.get_settings()
            setting = self._find(top, spec.name)
            if isinstance(spec, BoolSpec):
                new = not bool(setting.value)
            elif isinstance(spec, ChoiceSpec):
                new = next(option for option in spec.options
                           if option != str(setting.value))
            else:
                self.assertIsInstance(spec, IntSpec)
                limits = spec.limits
                now = int(setting.value)
                new = now + limits.step if now < limits.hi else limits.lo
            setting.value = new
            self.pipe.sent.clear()
            self.radio.set_settings(top)
            sets = (self._modes_sent() if spec.code == 'MD'
                    else self._sets_sent())
            self.assertEqual(1, len(sets), spec.name)
            self.assertTrue(spec.command.accepts(sets[0]), spec.name)
            fresh = self._find(self.radio.get_settings(), spec.name)
            self.assertEqual(str(new), str(fresh.value), spec.name)

    def test_filters_share_one_command(self):
        self._change('tx_filter', 'Filter 2')
        self.assertEqual('FL01;', self.pipe.state['FL;'])
        self._change('rx_filter', 'Filter 4')
        self.assertEqual('FL31;', self.pipe.state['FL;'])

    def test_answer_shapes(self):
        self._change('preamp', True)
        self.assertEqual('PA10;', self.pipe.state['PA;'])
        self._change('attenuator', True)
        self.assertEqual('RA0100;', self.pipe.state['RA;'])
        self._change('meter', 'ALC')
        self.assertEqual('RM30000;', self.pipe.state['RM;'])
        self._change('lock', True)
        self.assertEqual('LK10;', self.pipe.state['LK;'])

    def test_tuner_change_never_starts_tuning(self):
        self._change('atu', True)
        self.assertEqual(['AC010;'], self._sets_sent())

    def test_unknown_tone_can_be_replaced(self):
        self._change('ctcss_tone', '100.0 Hz')
        self.assertEqual('CN12;', self.pipe.state['CN;'])

    def test_refuses_while_transmitting(self):
        top = self.radio.get_settings()
        self._find(top, 'power').value = 50
        self.pipe.ptt = 1
        with self.assertRaisesRegex(errors.RadioError, 'transmitting'):
            self.radio.set_settings(top)
        self.assertEqual([], self._sets_sent())

    def test_rejected_setting_is_tried_once_and_raises(self):
        self.pipe.ignore_sets = True
        with self.assertRaisesRegex(errors.RadioError, 'did not accept'):
            self._change('power', 50)
        self.assertEqual(['PC050;', 'PC097;'], self._sets_sent())
        self.assertEqual('PC097;', self.pipe.state['PC;'])

    def test_carrier_is_read_only_and_follows_tune_power(self):
        setting = self._find(self.radio.get_settings(), 'carrier')
        self.assertFalse(setting.value.get_mutable())
        self.assertEqual('10', str(setting.value))
        for frame in ('CG000;', 'CG010;', 'CG011;', 'CG100;'):
            with self.assertRaises(CommandRefused):
                CommandGate().check_set(frame)
        self._change('tune_power', 20)
        fresh = self._find(self.radio.get_settings(), 'carrier')
        self.assertEqual('20', str(fresh.value))

    def test_rf_gain_table_matches_measured_map(self):
        levels = lab599.RF_GAIN_LEVELS
        self.assertEqual(57, len(levels))
        self.assertEqual(set(REAL_RF_GAIN_MAP), set(levels))
        for level, code in levels.items():
            self.assertEqual(level, REAL_RF_GAIN_MAP[code])

    def test_rf_gain_offers_front_panel_labels(self):
        labels = lab599.RF_GAIN_LABELS
        self.assertEqual(list(lab599.RF_GAIN_LEVELS), list(labels))
        self.assertEqual(('-51', '-50', '0', '+5'),
                         (labels[0], labels[2], labels[92], labels[100]))
        setting = self._find(self.radio.get_settings(), 'rf_gain_ssb')
        self.assertEqual(list(labels.values()), setting.value.get_options())
        self.assertEqual('0', str(setting.value))

    def test_every_rf_gain_level_can_be_selected(self):
        for level, code in lab599.RF_GAIN_LEVELS.items():
            if level == 92:
                continue
            self.pipe.state['RG;'] = 'RG092;'
            self.pipe.sent.clear()
            self._change('rf_gain_ssb', lab599.RF_GAIN_LABELS[level])
            self.assertEqual('RG%03i;' % level, self.pipe.state['RG;'])
            self.assertEqual(['RG%03i;' % code], self._sets_sent())

    def test_failed_rf_gain_change_restores_previous_level(self):
        with mock.patch.dict(lab599.RF_GAIN_LEVELS, {18: 20}):
            with self.assertRaisesRegex(errors.RadioError, 'did not accept'):
                self._change('rf_gain_ssb', lab599.RF_GAIN_LABELS[18])
        self.assertEqual('RG092;', self.pipe.state['RG;'])
        self.assertEqual(['RG020;', 'RG091;'], self._sets_sent())

    def test_unknown_rf_gain_is_shown_and_replaceable(self):
        self.pipe.state['RG;'] = 'RG091;'
        setting = self._find(self.radio.get_settings(), 'rf_gain_ssb')
        self.assertEqual('Radio value 91', str(setting.value))
        self._change('rf_gain_ssb', lab599.RF_GAIN_LABELS[50])
        self.assertEqual('RG050;', self.pipe.state['RG;'])

    def test_noise_reduction_level_stops_at_99(self):
        command = lab599.SETTING_COMMANDS['RL']
        self.assertTrue(command.accepts('RL099;'))
        self.assertFalse(command.accepts('RL100;'))

    def test_out_of_range_radio_value_is_locked(self):
        self.pipe.state['PC;'] = 'PC005;'
        value = self._find(self.radio.get_settings(), 'power').value
        self.assertIsInstance(value, RadioSettingValueInteger)
        self.assertFalse(value.get_mutable())

    def test_vox_warns_only_when_enabling(self):
        top = self.radio.get_settings()
        for name in ('vox_cw', 'vox_mic', 'vox_dig'):
            setting = self._find(top, name)
            self.assertIn('dummy load', setting.get_warning(True))
            self.assertIsNone(setting.get_warning(False))

    def test_clock_is_shown_under_its_own_header(self):
        top = self.radio.get_settings()
        self.assertEqual(['clock_hour', 'clock_minute'],
                         list(top['operating']['operating_clock'].keys()))
        self.assertEqual(2, int(self._find(top, 'clock_hour').value))
        self.assertEqual(35, int(self._find(top, 'clock_minute').value))

    def test_clock_change_restarts_seconds(self):
        self._change('clock_minute', 40)
        self.assertEqual(['TM02:40:00;'], self._sets_sent())
        self.assertEqual('TM02:40:00;', self.pipe.state['TM;'])

    def test_running_clock_counts_as_stored(self):
        real_write = self.pipe.write

        def tick_after_set(data):
            real_write(data)
            if data == b'TM02:40:00;':
                self.pipe.state['TM;'] = 'TM02:40:01;'
        self.pipe.write = tick_after_set
        self._change('clock_minute', 40)
        self.assertEqual(['TM02:40:00;'], self._sets_sent())

    def test_clock_is_skipped_on_older_firmware(self):
        for reply in (None, 'TM;'):
            if reply:
                self.pipe.state['TM;'] = reply
            else:
                del self.pipe.state['TM;']
            top = self.radio.get_settings()
            for name in ('clock_hour', 'clock_minute'):
                value = self._find(top, name).value
                self.assertFalse(value.get_mutable(), name)
                self.assertIn('v1.29.01', str(value), name)

    def test_other_rejected_settings_still_fail(self):
        del self.pipe.state['PC;']
        with self.assertRaises(errors.RadioError):
            self.radio.get_settings()

    def test_features_report_settings(self):
        self.assertTrue(self.radio.get_features().has_settings)
