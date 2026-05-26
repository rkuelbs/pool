from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Sequence

from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusConfig, SharedModbusRtuBus

UART_REGISTER = 0x2000
ADDRESS_REGISTER = 0x4000

BAUD_TO_CODE: dict[int, int] = {
    4800: 0x00,
    9600: 0x01,
    19200: 0x02,
    38400: 0x03,
    57600: 0x04,
    115200: 0x05,
    128000: 0x06,
    256000: 0x07,
}
CODE_TO_BAUD = {value: key for key, value in BAUD_TO_CODE.items()}
PARITY_TO_CODE: dict[str, int] = {
    "N": 0x00,
    "E": 0x01,
    "O": 0x02,
}
CODE_TO_PARITY = {value: key for key, value in PARITY_TO_CODE.items()}


@dataclass(frozen=True)
class DeviceUart:
    parity: str
    baudrate: int


def _int_auto(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure Waveshare Modbus RTU module address/baud/parity (relay or analog input).",
    )
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--current-id", type=_int_auto, required=True)
    parser.add_argument("--current-baudrate", type=int, default=9600)
    parser.add_argument(
        "--current-parity",
        choices=("N", "E", "O"),
        default="N",
    )
    parser.add_argument("--timeout-s", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-backoff-s", type=float, default=0.05)

    parser.add_argument("--new-id", type=_int_auto, default=None)
    parser.add_argument("--new-baudrate", type=int, default=None)
    parser.add_argument(
        "--new-parity",
        choices=("N", "E", "O"),
        default=None,
    )

    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-write verification readback.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.current_id < 0 or args.current_id > 0xFF:
        parser.error("--current-id must be 0..255 (0 means broadcast)")
    if args.new_id is not None and (args.new_id < 1 or args.new_id > 0xFF):
        parser.error("--new-id must be 1..255")
    if args.current_baudrate not in BAUD_TO_CODE:
        parser.error("--current-baudrate must be one of: " + ", ".join(str(item) for item in BAUD_TO_CODE))
    if args.new_baudrate is not None and args.new_baudrate not in BAUD_TO_CODE:
        parser.error("--new-baudrate must be one of: " + ", ".join(str(item) for item in BAUD_TO_CODE))
    if args.new_id is None and args.new_baudrate is None and args.new_parity is None:
        parser.error("set at least one of --new-id, --new-baudrate, --new-parity")
    if args.new_parity is not None and args.new_baudrate is None:
        parser.error("--new-parity requires --new-baudrate (UART register write)")

    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    print(
        f"Connecting on {args.port} with current device settings: id=0x{args.current_id:02X}, "
        f"baud={args.current_baudrate}, parity={args.current_parity}"
    )
    print("Important: only one default-address module should be on the bus while configuring.")

    current_bus = _bus_for(
        port=args.port,
        baudrate=args.current_baudrate,
        timeout_s=args.timeout_s,
        retries=args.retries,
        retry_backoff_s=args.retry_backoff_s,
    )
    try:
        # Read baseline address/UART when directly addressed. Broadcast (id=0) cannot be read.
        if args.current_id != 0:
            initial_addr = await _read_address(current_bus, args.current_id)
            initial_uart = await _read_uart(current_bus, args.current_id)
            print(
                f"Current readback: address=0x{initial_addr:02X}, "
                f"uart=parity={initial_uart.parity}, baud={initial_uart.baudrate}"
            )

        target_id = args.current_id
        if args.new_id is not None:
            await current_bus.write_holding_register(
                slave_id=args.current_id,
                register_address=ADDRESS_REGISTER,
                value=args.new_id,
            )
            print(f"Wrote new address: 0x{args.new_id:02X}")
            target_id = args.new_id

        target_baud = args.current_baudrate
        target_parity = args.current_parity
        if args.new_baudrate is not None:
            target_baud = args.new_baudrate
            target_parity = args.new_parity or args.current_parity
            uart_value = (PARITY_TO_CODE[target_parity] << 8) | BAUD_TO_CODE[target_baud]
            await current_bus.write_holding_register(
                slave_id=target_id,
                register_address=UART_REGISTER,
                value=uart_value,
            )
            print(f"Wrote new UART settings: parity={target_parity}, baud={target_baud}")
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
        read_uart = await _read_uart(verify_bus, verify_id)
    except Exception as error:
        print(
            "Verification failed: could not read back with new settings. "
            f"Try a bus scan at baud={verify_baud}. Error: {error}"
        )
        return 1
    finally:
        await verify_bus.close()

    print(
        f"Verified: address=0x{read_addr:02X}, parity={read_uart.parity}, baud={read_uart.baudrate}"
    )
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
    return value[0] & 0xFF


async def _read_uart(bus: SharedModbusRtuBus, slave_id: int) -> DeviceUart:
    value = await bus.read_holding_registers(
        slave_id=slave_id,
        start_address=UART_REGISTER,
        count=1,
    )
    raw = value[0] & 0xFFFF
    parity_code = (raw >> 8) & 0xFF
    baud_code = raw & 0xFF

    parity = CODE_TO_PARITY.get(parity_code)
    baudrate = CODE_TO_BAUD.get(baud_code)
    if parity is None or baudrate is None:
        raise RuntimeError(
            f"unexpected UART register value 0x{raw:04X} (parity_code={parity_code}, baud_code={baud_code})"
        )

    return DeviceUart(parity=parity, baudrate=baudrate)


if __name__ == "__main__":
    raise SystemExit(main())

