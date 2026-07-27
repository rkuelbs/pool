"""
Tests for the Waveshare analog input mode CLI helper.

These tests keep the bringup tool's command-line behavior and register writes
stable for configuring the analog module.
"""

from __future__ import annotations

import pytest

from poolctl.tools import modbus_analog_mode


def test_parse_channel_updates_accepts_multiple_entries() -> None:
    parser = modbus_analog_mode.build_parser()

    updates = modbus_analog_mode.parse_channel_updates(
        ["1=0", "4=2", "8=4"],
        parser=parser,
    )

    assert updates == {1: 0, 4: 2, 8: 4}


def test_parse_channel_updates_rejects_invalid_channel() -> None:
    parser = modbus_analog_mode.build_parser()

    with pytest.raises(SystemExit):
        modbus_analog_mode.parse_channel_updates(["9=0"], parser=parser)


def test_format_modes_lists_all_channels() -> None:
    text = modbus_analog_mode.format_modes((0, 0, 2, 2, 4, 4, 1, 3))

    assert "CH1: mode 0 = 0-5V / 0-10V" in text
    assert "CH8: mode 3 = 4-20mA" in text
