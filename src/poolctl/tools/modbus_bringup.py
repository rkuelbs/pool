from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Sequence

from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusConfig, SharedModbusRtuBus


@dataclass(frozen=True)
class BringupResult:
    ok: bool
    message: str


def _int_auto(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bringup helper for RS485 Modbus relay and analog modules on Raspberry Pi.",
    )
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout-s", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-backoff-s", type=float, default=0.05)

    parser.add_argument("--relay-slave-id", type=_int_auto, default=None)
    parser.add_argument("--relay-count", type=int, default=8)
    parser.add_argument(
        "--toggle-relay",
        type=int,
        default=None,
        help="One-based relay number to pulse and restore.",
    )
    parser.add_argument(
        "--toggle-seconds",
        type=float,
        default=2.0,
        help="Pulse duration when --toggle-relay is used.",
    )

    parser.add_argument("--analog-slave-id", type=_int_auto, default=None)
    parser.add_argument("--analog-channel-count", type=int, default=8)
    parser.add_argument("--raw-to-volts-scale", type=float, default=0.001)
    parser.add_argument("--raw-to-volts-offset", type=float, default=0.0)

    parser.add_argument(
        "--scan",
        action="store_true",
        help="Probe a slave-id range before device-specific checks.",
    )
    parser.add_argument("--scan-min-id", type=_int_auto, default=1)
    parser.add_argument("--scan-max-id", type=_int_auto, default=16)
    parser.add_argument(
        "--scan-probe",
        choices=("coils", "input", "both"),
        default="both",
        help="Probe function(s) to use while scanning.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.scan and args.relay_slave_id is None and args.analog_slave_id is None:
        parser.error("select at least one action: --scan, --relay-slave-id, or --analog-slave-id")

    if args.relay_count < 1:
        parser.error("--relay-count must be at least 1")
    if args.analog_channel_count < 1:
        parser.error("--analog-channel-count must be at least 1")
    if args.scan_min_id < 1 or args.scan_max_id < args.scan_min_id:
        parser.error("--scan-min-id/--scan-max-id must define a valid positive range")
    if args.toggle_relay is not None and not (1 <= args.toggle_relay <= args.relay_count):
        parser.error("--toggle-relay must be within 1..relay-count")
    if args.toggle_seconds <= 0:
        parser.error("--toggle-seconds must be greater than zero")

    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    bus = SharedModbusRtuBus(
        ModbusRtuBusConfig(
            port=args.port,
            baudrate=args.baudrate,
            timeout_s=args.timeout_s,
            retries=args.retries,
            retry_backoff_s=args.retry_backoff_s,
        )
    )
    any_failure = False

    print(
        f"Using RS485 bus port={args.port} baudrate={args.baudrate} timeout_s={args.timeout_s} "
        f"retries={args.retries}"
    )

    try:
        if args.scan:
            print(
                f"\n[scan] Probing slave IDs {args.scan_min_id}..{args.scan_max_id} "
                f"with probe={args.scan_probe}"
            )
            scan_result = await _scan_slaves(
                bus=bus,
                min_id=args.scan_min_id,
                max_id=args.scan_max_id,
                probe=args.scan_probe,
            )
            if scan_result:
                print("[scan] Responding slave IDs:", ", ".join(str(item) for item in scan_result))
            else:
                print("[scan] No responding slave IDs found")

        if args.relay_slave_id is not None:
            relay_result = await _relay_check(
                bus=bus,
                slave_id=args.relay_slave_id,
                relay_count=args.relay_count,
                toggle_relay=args.toggle_relay,
                toggle_seconds=args.toggle_seconds,
            )
            print(f"[relay] {relay_result.message}")
            any_failure = any_failure or not relay_result.ok

        if args.analog_slave_id is not None:
            analog_result = await _analog_check(
                bus=bus,
                slave_id=args.analog_slave_id,
                channel_count=args.analog_channel_count,
                raw_to_volts_scale=args.raw_to_volts_scale,
                raw_to_volts_offset=args.raw_to_volts_offset,
            )
            print(f"[analog] {analog_result.message}")
            any_failure = any_failure or not analog_result.ok
    finally:
        await bus.close()

    return 1 if any_failure else 0


async def _scan_slaves(
    *,
    bus: SharedModbusRtuBus,
    min_id: int,
    max_id: int,
    probe: str,
) -> list[int]:
    found: list[int] = []
    for slave_id in range(min_id, max_id + 1):
        methods: list[str] = []
        if probe in {"coils", "both"}:
            try:
                await bus.read_coils(slave_id=slave_id, start_address=0, count=1)
                methods.append("coils")
            except Exception:
                pass
        if probe in {"input", "both"}:
            try:
                await bus.read_input_registers(slave_id=slave_id, start_address=0, count=1)
                methods.append("input")
            except Exception:
                pass

        if methods:
            found.append(slave_id)
            print(f"[scan] slave {slave_id}: response on {', '.join(methods)}")

    return found


async def _relay_check(
    *,
    bus: SharedModbusRtuBus,
    slave_id: int,
    relay_count: int,
    toggle_relay: int | None,
    toggle_seconds: float,
) -> BringupResult:
    try:
        states = await bus.read_coils(slave_id=slave_id, start_address=0, count=relay_count)
    except Exception as error:
        return BringupResult(False, f"failed to read relay states for slave {slave_id}: {error}")

    print(
        f"[relay] slave {slave_id} states: "
        + ", ".join(
            f"R{index + 1}={'ON' if state else 'OFF'}"
            for index, state in enumerate(states)
        )
    )

    if toggle_relay is None:
        return BringupResult(True, "read relay states successfully")

    coil_address = toggle_relay - 1
    initial_state = states[coil_address]
    pulse_state = not initial_state

    try:
        print(
            f"[relay] pulsing relay {toggle_relay}: "
            f"{'ON' if pulse_state else 'OFF'} for {toggle_seconds:.2f}s then restore"
        )
        await bus.write_coil(slave_id=slave_id, coil_address=coil_address, value=pulse_state)
        await asyncio.sleep(toggle_seconds)
        await bus.write_coil(slave_id=slave_id, coil_address=coil_address, value=initial_state)
        verify = await bus.read_coils(slave_id=slave_id, start_address=coil_address, count=1)
    except Exception as error:
        return BringupResult(False, f"relay pulse failed for relay {toggle_relay}: {error}")

    if not verify:
        return BringupResult(False, f"relay {toggle_relay} verify read returned no data")
    if verify[0] != initial_state:
        return BringupResult(
            False,
            f"relay {toggle_relay} did not restore to initial state "
            f"({'ON' if initial_state else 'OFF'})",
        )

    return BringupResult(
        True,
        f"relay {toggle_relay} pulse and restore succeeded (restored to {'ON' if initial_state else 'OFF'})",
    )


async def _analog_check(
    *,
    bus: SharedModbusRtuBus,
    slave_id: int,
    channel_count: int,
    raw_to_volts_scale: float,
    raw_to_volts_offset: float,
) -> BringupResult:
    try:
        registers = await bus.read_input_registers(
            slave_id=slave_id,
            start_address=0,
            count=channel_count,
        )
    except Exception as error:
        return BringupResult(False, f"failed to read analog channels for slave {slave_id}: {error}")

    for index, raw in enumerate(registers, start=1):
        volts = raw * raw_to_volts_scale + raw_to_volts_offset
        print(f"[analog] slave {slave_id} CH{index}: raw={raw:5d} volts={volts:7.4f} V")

    return BringupResult(True, f"read {len(registers)} analog channels successfully")


if __name__ == "__main__":
    raise SystemExit(main())
