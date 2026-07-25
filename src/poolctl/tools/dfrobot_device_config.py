from __future__ import annotations

import argparse
import asyncio
from typing import Sequence

from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusConfig, SharedModbusRtuBus

ADDRESS_REGISTER = 0x07D0
BAUD_REGISTER = 0x07D1

BAUD_TO_CODE: dict[int, int] = {
    2400: 0,
    4800: 1,
    9600: 2,
    19200: 3,
    38400: 4,
    57600: 5,
    115200: 6,
    1200: 7,
}
CODE_TO_BAUD = {value: key for key, value in BAUD_TO_CODE.items()}


def _int_auto(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure DFRobot SEN0708/SEN0709 RS485 sensor address and baud.",
    )
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--current-id", type=_int_auto, required=True)
    parser.add_argument("--current-baudrate", type=int, default=4800)
    parser.add_argument("--timeout-s", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-backoff-s", type=float, default=0.05)
    parser.add_argument("--new-id", type=_int_auto, default=None)
    parser.add_argument("--new-baudrate", type=int, default=None)
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-write verification readback.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.current_id < 1 or args.current_id > 254:
        parser.error("--current-id must be 1..254")
    if args.new_id is not None and (args.new_id < 1 or args.new_id > 254):
        parser.error("--new-id must be 1..254")
    if args.current_baudrate not in BAUD_TO_CODE:
        parser.error(
            "--current-baudrate must be one of: "
            + ", ".join(str(item) for item in sorted(BAUD_TO_CODE))
        )
    if args.new_baudrate is not None and args.new_baudrate not in BAUD_TO_CODE:
        parser.error(
            "--new-baudrate must be one of: "
            + ", ".join(str(item) for item in sorted(BAUD_TO_CODE))
        )
    if args.new_id is None and args.new_baudrate is None:
        parser.error("set at least one of --new-id or --new-baudrate")

    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    print(
        f"Connecting on {args.port} with current DFRobot settings: "
        f"id=0x{args.current_id:02X}, baud={args.current_baudrate}"
    )
    print("Important: only one default-address DFRobot sensor should be on the bus while configuring.")

    current_bus = _bus_for(
        port=args.port,
        baudrate=args.current_baudrate,
        timeout_s=args.timeout_s,
        retries=args.retries,
        retry_backoff_s=args.retry_backoff_s,
    )
    try:
        initial_addr = await _read_address(current_bus, args.current_id)
        initial_baud = await _read_baudrate(current_bus, args.current_id)
        print(f"Current readback: address=0x{initial_addr:02X}, baud={initial_baud}")

        target_id = args.current_id
        if args.new_id is not None:
            await current_bus.write_holding_register(
                slave_id=args.current_id,
                register_address=ADDRESS_REGISTER,
                value=args.new_id,
            )
            print(f"Wrote new address: 0x{args.new_id:02X}")
            target_id = args.new_id

        if args.new_baudrate is not None:
            await current_bus.write_holding_register(
                slave_id=target_id,
                register_address=BAUD_REGISTER,
                value=BAUD_TO_CODE[args.new_baudrate],
            )
            print(f"Wrote new baudrate: {args.new_baudrate}")
    finally:
        await current_bus.close()

    if args.skip_verify:
        return 0

    verify_id = args.new_id if args.new_id is not None else args.current_id
    verify_baud = args.new_baudrate if args.new_baudrate is not None else args.current_baudrate
    verify_bus = _bus_for(
        port=args.port,
        baudrate=verify_baud,
        timeout_s=args.timeout_s,
        retries=args.retries,
        retry_backoff_s=args.retry_backoff_s,
    )
    try:
        read_addr = await _read_address(verify_bus, verify_id)
        read_baud = await _read_baudrate(verify_bus, verify_id)
    except Exception as error:
        print(
            "Verification failed: could not read back with new settings. "
            f"Try a bus scan at baud={verify_baud}. Error: {error}"
        )
        return 1
    finally:
        await verify_bus.close()

    print(f"Verified: address=0x{read_addr:02X}, baud={read_baud}")
    return 0


def _bus_for(
    *,
    port: str,
    baudrate: int,
    timeout_s: float,
    retries: int,
    retry_backoff_s: float,
) -> SharedModbusRtuBus:
    return SharedModbusRtuBus(
        ModbusRtuBusConfig(
            port=port,
            baudrate=baudrate,
            timeout_s=timeout_s,
            retries=retries,
            retry_backoff_s=retry_backoff_s,
        )
    )


async def _read_address(bus: SharedModbusRtuBus, slave_id: int) -> int:
    value = await bus.read_holding_registers(
        slave_id=slave_id,
        start_address=ADDRESS_REGISTER,
        count=1,
    )
    address = value[0] & 0xFFFF
    if address < 1 or address > 254:
        raise RuntimeError(f"unexpected DFRobot address register value: {address}")
    return address


async def _read_baudrate(bus: SharedModbusRtuBus, slave_id: int) -> int:
    value = await bus.read_holding_registers(
        slave_id=slave_id,
        start_address=BAUD_REGISTER,
        count=1,
    )
    raw = value[0] & 0xFFFF
    baudrate = CODE_TO_BAUD.get(raw)
    if baudrate is None:
        raise RuntimeError(f"unexpected DFRobot baud register value: 0x{raw:04X}")
    return baudrate


if __name__ == "__main__":
    raise SystemExit(main())
