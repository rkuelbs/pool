"""
CLI helper for reading or writing Waveshare analog input mode registers.

The pool uses the non-B 0-5 V analog input module. This tool exists so bringup
can verify every channel is in the expected voltage mode before pressure or pH
calibration values are trusted.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusConfig, SharedModbusRtuBus


MODE_REGISTER_BASE = 0x1000
CHANNEL_COUNT = 8
MODE_LABELS = {
    0: "0-5V / 0-10V",
    1: "1-5V / 2-10V",
    2: "0-20mA",
    3: "4-20mA",
    4: "4096-code",
}


def _int_auto(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read or set Waveshare Modbus RTU Analog Input 8CH per-channel input modes.",
    )
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--slave-id", type=_int_auto, required=True)
    parser.add_argument("--baudrate", type=int, default=4800)
    parser.add_argument("--timeout-s", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-backoff-s", type=float, default=0.05)
    parser.add_argument(
        "--set-all",
        type=int,
        choices=tuple(sorted(MODE_LABELS)),
        default=None,
        help="Set all 8 channels to one mode. Use 0 for 0-5V on the non-B board.",
    )
    parser.add_argument(
        "--set-channel",
        action="append",
        default=[],
        metavar="CH=MODE",
        help="Set one channel, e.g. --set-channel 1=0 --set-channel 4=0",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Do not write anything; only read back current channel modes.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.slave_id < 1 or args.slave_id > 0xFF:
        parser.error("--slave-id must be 1..255")
    if args.baudrate <= 0:
        parser.error("--baudrate must be positive")
    if args.set_all is not None and args.verify_only:
        parser.error("--set-all cannot be used with --verify-only")
    if args.set_channel and args.verify_only:
        parser.error("--set-channel cannot be used with --verify-only")

    updates = parse_channel_updates(args.set_channel, parser=parser)
    return asyncio.run(_run(args, updates))


async def _run(args: argparse.Namespace, updates: dict[int, int]) -> int:
    bus = SharedModbusRtuBus(
        ModbusRtuBusConfig(
            port=args.port,
            baudrate=args.baudrate,
            timeout_s=args.timeout_s,
            retries=args.retries,
            retry_backoff_s=args.retry_backoff_s,
        )
    )
    try:
        before = await read_channel_modes(bus, slave_id=args.slave_id)
        print("Current channel modes:")
        print(format_modes(before))

        if args.set_all is not None:
            updates = {channel: args.set_all for channel in range(1, CHANNEL_COUNT + 1)}

        if updates:
            for channel, mode in sorted(updates.items()):
                await write_channel_mode(
                    bus,
                    slave_id=args.slave_id,
                    channel=channel,
                    mode=mode,
                )
            print("Updated channel modes written.")

        after = await read_channel_modes(bus, slave_id=args.slave_id)
        print("Readback channel modes:")
        print(format_modes(after))
    finally:
        await bus.close()

    return 0


def parse_channel_updates(
    entries: Sequence[str],
    *,
    parser: argparse.ArgumentParser,
) -> dict[int, int]:
    updates: dict[int, int] = {}
    for entry in entries:
        if "=" not in entry:
            parser.error(f"invalid --set-channel value {entry!r}; expected CH=MODE")
        raw_channel, raw_mode = entry.split("=", 1)
        try:
            channel = int(raw_channel)
            mode = int(raw_mode)
        except ValueError as error:
            parser.error(f"invalid --set-channel value {entry!r}: {error}")
        if channel < 1 or channel > CHANNEL_COUNT:
            parser.error(f"channel must be 1..{CHANNEL_COUNT}, got {channel}")
        if mode not in MODE_LABELS:
            parser.error(f"mode must be one of {sorted(MODE_LABELS)}, got {mode}")
        updates[channel] = mode
    return updates


async def read_channel_modes(
    bus: SharedModbusRtuBus,
    *,
    slave_id: int,
) -> tuple[int, ...]:
    return await bus.read_holding_registers(
        slave_id=slave_id,
        start_address=MODE_REGISTER_BASE,
        count=CHANNEL_COUNT,
    )


async def write_channel_mode(
    bus: SharedModbusRtuBus,
    *,
    slave_id: int,
    channel: int,
    mode: int,
) -> None:
    await bus.write_holding_register(
        slave_id=slave_id,
        register_address=MODE_REGISTER_BASE + (channel - 1),
        value=mode,
    )


def format_modes(modes: Sequence[int]) -> str:
    lines: list[str] = []
    for index, mode in enumerate(modes, start=1):
        label = MODE_LABELS.get(mode, f"unknown({mode})")
        lines.append(f"  CH{index}: mode {mode} = {label}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
