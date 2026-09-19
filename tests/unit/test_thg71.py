from tests.unit import base
from chirp import chirp_common, errors
from chirp.drivers import kenwood_live


class TestTHG71(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.radio = kenwood_live.THG71Radio(None)

    def test_features(self):
        rf = self.radio.get_features()
        self.assertEqual(rf.memory_bounds, (0, 199))
        self.assertEqual(rf.valid_modes, ["FM"])
        self.assertEqual(rf.valid_tmodes, ["", "Tone", "TSQL"])
        self.assertEqual(rf.valid_duplexes, ["", "+", "-", "split"])
        self.assertEqual(rf.valid_skips, ["", "S"])
        self.assertEqual(rf.valid_name_length, 6)
        self.assertTrue(rf.has_tuning_step)
        self.assertTrue(rf.can_odd_split)
        self.assertTrue(rf.has_settings)
        self.assertFalse(rf.has_sub_devices)
        self.assertFalse(rf.has_dtcs)
        self.assertFalse(rf.has_bank)

        # Tone checks
        self.assertEqual(len(rf.valid_tones), 38)
        self.assertNotIn(69.3, rf.valid_tones)
        self.assertIn(67.0, rf.valid_tones)
        self.assertIn(71.9, rf.valid_tones)
        self.assertIn(250.3, rf.valid_tones)

        # Steps check
        self.assertEqual(len(rf.valid_tuning_steps), 10)
        self.assertEqual(rf.valid_tuning_steps[0], 5.0)
        self.assertEqual(rf.valid_tuning_steps[9], 100.0)

        # Special channels check
        self.assertIn("CALL-V", rf.valid_special_chans)
        self.assertIn("CALL-U", rf.valid_special_chans)
        self.assertIn("Pr", rf.valid_special_chans)
        self.assertIn("L0", rf.valid_special_chans)
        self.assertIn("U0", rf.valid_special_chans)
        self.assertIn("L9", rf.valid_special_chans)
        self.assertIn("U9", rf.valid_special_chans)

        # Bands check
        self.assertEqual(len(rf.valid_bands), 3)
        self.assertEqual(rf.valid_bands[0], (118000000, 174000000))
        self.assertEqual(rf.valid_bands[1], (320000000, 470000000))
        self.assertEqual(rf.valid_bands[2], (800000000, 949000000))

    def test_tone_codes(self):
        # Test code to tone conversion
        self.assertEqual(kenwood_live._thg71_code_to_tone("01"), 67.0)
        self.assertEqual(kenwood_live._thg71_code_to_tone("03"), 71.9)
        self.assertEqual(kenwood_live._thg71_code_to_tone("09"), 88.5)
        self.assertEqual(kenwood_live._thg71_code_to_tone("27"), 162.2)
        self.assertEqual(kenwood_live._thg71_code_to_tone("39"), 250.3)
        # Invalid code 02 should fall back
        self.assertEqual(kenwood_live._thg71_code_to_tone("02"), 88.5)

        # Test tone to code conversion
        self.assertEqual(kenwood_live._thg71_tone_to_code(67.0), "01")
        self.assertEqual(kenwood_live._thg71_tone_to_code(71.9), "03")
        self.assertEqual(kenwood_live._thg71_tone_to_code(88.5), "09")
        self.assertEqual(kenwood_live._thg71_tone_to_code(162.2), "27")
        self.assertEqual(kenwood_live._thg71_tone_to_code(250.3), "39")
        self.assertEqual(kenwood_live._thg71_tone_to_code(69.3), "09")

    def test_parse_mr_spec(self):
        # MR 0,0,000,00146980000,0,2,0,1,0,,27,,09,000600000,0
        spec = ["0", "0", "000", "00146980000", "0", "2", "0", "1", "0", "",
                "27", "", "09", "000600000", "0"]
        mem = self.radio._parse_mem_spec(spec)
        self.assertEqual(mem.number, 0)
        self.assertEqual(mem.freq, 146980000)
        self.assertEqual(mem.tuning_step, 5.0)
        self.assertEqual(mem.duplex, "-")
        self.assertEqual(mem.tmode, "Tone")
        self.assertEqual(mem.rtone, 162.2)
        self.assertEqual(mem.ctone, 88.5)
        self.assertEqual(mem.offset, 600000)
        self.assertEqual(mem.skip, "")

    def test_parse_mr_spec_with_skip(self):
        # MR 0,0,005,00146520000,0,0,0,0,0,,09,,09,000000000,1
        spec = ["0", "0", "005", "00146520000", "0", "0", "0", "0", "0", "",
                "09", "", "09", "000000000", "1"]
        mem = self.radio._parse_mem_spec(spec)
        self.assertEqual(mem.number, 5)
        self.assertEqual(mem.freq, 146520000)
        self.assertEqual(mem.duplex, "")
        self.assertEqual(mem.skip, "S")

    def test_parse_call_spec(self):
        # CR 1,0,00446000000,6,0,0,0,0,,09,,09,005000000
        spec = ["1", "0", "00446000000", "6", "0", "0", "0", "0", "",
                "09", "", "09", "005000000"]
        mem = self.radio._parse_call_spec(1, spec)
        self.assertEqual(mem.extd_number, "CALL-U")
        self.assertEqual(mem.freq, 446000000)
        self.assertEqual(mem.tuning_step, 25.0)
        self.assertEqual(mem.duplex, "")
        self.assertEqual(mem.offset, 5000000)

    def test_make_mr_spec(self):
        mem = chirp_common.Memory()
        mem.number = 0
        mem.freq = 146980000
        mem.tuning_step = 5.0
        mem.duplex = "-"
        mem.tmode = "Tone"
        mem.rtone = 162.2
        mem.ctone = 88.5
        mem.offset = 600000
        mem.skip = ""

        spec = self.radio._make_mem_spec(mem)
        spec_str = ",".join(spec)
        self.assertEqual(
            spec_str,
            "00146980000,0,2,0,1,0,,27,,09,000600000,0"
        )

    def test_make_split_spec(self):
        mem = chirp_common.Memory()
        mem.number = 0
        mem.freq = 146400000
        mem.tuning_step = 25.0
        mem.duplex = "split"
        mem.offset = 445000000

        split_spec = self.radio._make_split_spec(mem)
        self.assertEqual(split_spec, ("00445000000", "6"))

    def test_unsupported_tone(self):
        mem = chirp_common.Memory()
        mem.number = 1
        mem.freq = 146520000
        mem.tmode = "Tone"
        mem.rtone = 69.3
        with self.assertRaises(errors.UnsupportedToneError):
            self.radio.set_memory(mem)

        mem.tmode = "TSQL"
        mem.rtone = 88.5
        mem.ctone = 69.3
        with self.assertRaises(errors.UnsupportedToneError):
            self.radio.set_memory(mem)

    def test_mock_get_memory_regular_and_split(self):
        def fake_command(ser, cmd, *args):
            if cmd == "MR" and args[0] == "0,0,000":
                # Split RX
                return "MR 0,0,000,00146400000,0,0,0,0,0,,27,,09,,0"
            elif cmd == "MR" and args[0] == "0,1,000":
                # Split TX
                return "MR 0,1,000,00445000000,6"
            elif cmd == "MNA" and args[0] == "0,000":
                return "MNA 0,000,SPLIT1"
            elif cmd == "MR" and args[0] == "0,0,001":
                return "MR 0,0,001,00146980000,0,2,0,1,0,,27,,09,000600000,0"
            elif cmd == "MR" and args[0] == "0,1,001":
                return "N"
            elif cmd == "MNA" and args[0] == "0,001":
                return "MNA 0,001,RPT1"
            elif cmd == "MR" and args[0] == "0,0,002":
                return "N"
            return "?"

        self.radio.command = fake_command

        # Test split channel 0
        mem0 = self.radio.get_memory(0)
        self.assertEqual(mem0.number, 0)
        self.assertEqual(mem0.freq, 146400000)
        self.assertEqual(mem0.duplex, "split")
        self.assertEqual(mem0.offset, 445000000)
        self.assertEqual(mem0.name, "SPLIT1")

        # Test regular channel 1
        mem1 = self.radio.get_memory(1)
        self.assertEqual(mem1.number, 1)
        self.assertEqual(mem1.freq, 146980000)
        self.assertEqual(mem1.duplex, "-")
        self.assertEqual(mem1.offset, 600000)
        self.assertEqual(mem1.tmode, "Tone")
        self.assertEqual(mem1.rtone, 162.2)
        self.assertEqual(mem1.name, "RPT1")

        # Test empty channel 2
        mem2 = self.radio.get_memory(2)
        self.assertTrue(mem2.empty)

    def test_mock_get_and_set_call_channel(self):
        sent_commands = []

        def fake_command(ser, cmd, *args):
            sent_commands.append((cmd, args))
            if cmd == "CR" and args[0] == "0,0":
                return "CR 0,0,00147405000,0,0,0,0,0,,27,,09,000600000"
            elif cmd == "CR" and args[0] == "0,1":
                return "N"
            elif cmd == "CW":
                return "CW"
            return "N"

        self.radio.command = fake_command

        mem = self.radio.get_memory("CALL-V")
        self.assertEqual(mem.extd_number, "CALL-V")
        self.assertEqual(mem.freq, 147405000)
        self.assertEqual(mem.offset, 600000)

        mem.freq = 146520000
        mem.offset = 0
        self.radio.set_memory(mem)
        self.assertIn(("CW", ("0,0,00146520000,0,0,0,0,0,,27,,09,000000000",)),
                      sent_commands)

    def test_mock_get_and_set_settings(self):
        sent_commands = []

        def fake_command(ser, cmd, *args):
            sent_commands.append((cmd, args))
            if cmd == "PC" and args[0] == "0":
                return "PC 0,2"  # Low power VHF
            elif cmd == "PC" and args[0] == "1":
                return "PC 1,0"  # High power UHF
            elif cmd == "SQ" and args[0] == "0":
                return "SQ 0,03"
            elif cmd == "DM" and args[0] == "00":
                return "DM 00,E5558881234"  # *5558881234
            elif cmd == "DM":
                return "DM %s" % args[0]
            return cmd

        self.radio.command = fake_command

        settings = self.radio.get_settings()
        self.assertEqual(str(settings["basic"]["pc_vhf"].value), "Low")
        self.assertEqual(str(settings["basic"]["pc_uhf"].value), "High")
        self.assertEqual(int(settings["basic"]["squelch"].value), 3)
        self.assertEqual(str(settings["dtmf"]["dm_00"].value), "*5558881234")

        # Change settings and apply
        settings["basic"]["pc_vhf"].value = "Economic Low"
        settings["basic"]["squelch"].value = 5
        settings["dtmf"]["dm_00"].value = "*123#456"
        self.radio.set_settings(settings)

        self.assertIn(("PC", ("0,3",)), sent_commands)
        self.assertIn(("SQ", ("0,05",)), sent_commands)
        self.assertIn(("DM", ("00,E123F456",)), sent_commands)
