"""USB serial interface to the ESP32-CYD fob.

The fob accepts key=value pairs over serial (newline-terminated, semicolon-separated for multiples).
cmd=lockcams triggers camera locking; cmd=status returns JSON.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import serial  # type: ignore[import-untyped]


@dataclass
class FobStatus:
    kit_id: str = ""
    operator_id: str = ""
    station: str = ""
    cams: int = 0
    ordinal: int = 0
    time_set: bool = False
    ap_ssid: str = ""
    ap_ch: int = 0
    sides: str = ""
    free_heap: int = 0
    min_heap: int = 0
    largest_free_block: int = 0
    log_bytes: int = 0
    raw: dict[str, object] = field(default_factory=dict)

    @property
    def allow_n(self) -> int:
        return len(self.sides.split(",")) if self.sides else 0


def parse_status(raw_json: str) -> FobStatus:
    data = json.loads(raw_json)
    return FobStatus(
        kit_id=data.get("kit_id", ""),
        operator_id=data.get("operator_id", ""),
        station=data.get("station", ""),
        cams=int(data.get("cams", 0)),
        ordinal=int(data.get("ordinal", 0)),
        time_set=bool(data.get("time_set", False)),
        ap_ssid=data.get("ap_ssid", ""),
        ap_ch=int(data.get("ap_ch", 0)),
        sides=data.get("sides", ""),
        free_heap=int(data.get("free_heap", 0)),
        min_heap=int(data.get("min_heap", 0)),
        largest_free_block=int(data.get("largest_free_block", 0)),
        log_bytes=int(data.get("log_bytes", 0)),
        raw=data,
    )


class FobSerial:
    """Manages a serial connection to the fob."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 5.0):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        self._ser = serial.Serial(self._port, self._baudrate, timeout=self._timeout)
        time.sleep(0.5)
        if self._ser.in_waiting:
            self._ser.read(self._ser.in_waiting)

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    def __enter__(self) -> FobSerial:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_open(self) -> serial.Serial:
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Serial port not open")
        return self._ser

    def send_kv(self, key: str, value: str) -> None:
        ser = self._ensure_open()
        line = f"{key}={value}\n"
        ser.write(line.encode())
        ser.flush()
        time.sleep(0.1)

    def send_kvs(self, pairs: dict[str, str]) -> None:
        ser = self._ensure_open()
        line = ";".join(f"{k}={v}" for k, v in pairs.items()) + "\n"
        ser.write(line.encode())
        ser.flush()
        time.sleep(0.1)

    def read_lines(self, *, timeout: float = 3.0) -> list[str]:
        ser = self._ensure_open()
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ser.in_waiting:
                raw = ser.readline()
                if raw:
                    lines.append(raw.decode(errors="replace").strip())
            else:
                time.sleep(0.05)
        return lines

    def cmd_status(self) -> FobStatus:
        self.send_kv("cmd", "status")
        lines = self.read_lines(timeout=2.0)
        for line in lines:
            line = line.strip()
            if line.startswith("{"):
                return parse_status(line)
        raise RuntimeError(f"No JSON status in fob response: {lines}")

    def cmd_lockcams(self) -> tuple[bool, str]:
        """Send cmd=lockcams. Returns (success, raw_output)."""
        self.send_kv("cmd", "lockcams")
        lines = self.read_lines(timeout=10.0)
        output = "\n".join(lines)
        success = "allow_n=2" in output
        return success, output

    def provision(self, *, kit_id: str, site_id: str, cam_pass: str) -> None:
        self.send_kvs({"kit": kit_id, "site": site_id})
        if cam_pass:
            self.send_kv("cpass", cam_pass)
