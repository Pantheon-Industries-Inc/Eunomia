"""Bench-side X3 camera protocol — telnet (:23) + OSC (:80) from the provisioning Mac.

Adapted from the C++ in firmware/coordinator/transport/proto/x3_protocol.{h,cpp} — same wire format,
Python for bench use. The C++ runs on the fob during capture; this module runs on the Mac during
provisioning.
"""

from __future__ import annotations

import http.client
import re
import socket
import time
from dataclasses import dataclass

TELNET_PORT = 23
OSC_PORT = 80
DONE_MARKER = "__PROV_DONE__"

CAMERA_ENV_PATH = "/pref/pantheon_camera.env"
FOB_ENV_PATH = "/pref/pantheon_fob.env"


@dataclass
class CameraFacts:
    body_serial: str
    ip: str
    mac: str = ""
    insv_serial: str = ""
    ap_ssid: str = ""


def build_write_file_cmd(path: str, body: str) -> str:
    """Heredoc file-write command (mirrors x3_protocol.cpp build_write_file_cmd)."""
    dir_ = path.rsplit("/", 1)[0] if "/" in path else "/"
    return f"mkdir -p '{dir_}'\ncat > '{path}' <<'X3EOF'\n{body}\nX3EOF\nsync\necho WROTE {path}"


def build_camera_env(
    *,
    camera_id: str,
    kit_id: str,
    side: str,
    mount: str = "wrist",
    calibration_id: str = "",
) -> str:
    lines = [
        f"CAMERA_ID={camera_id}",
        f"KIT_ID={kit_id}",
        f"CAMERA_SIDE={side}",
        f"CAMERA_MOUNT={mount}",
    ]
    if calibration_id:
        lines.append(f"CALIBRATION_ID={calibration_id}")
    return "\n".join(lines)


def build_fob_env(*, ssid: str, psk: str) -> str:
    lines = [
        f"ROOTKIT_FOB_SSID={ssid}",
        f"ROOTKIT_FOB_PASS={psk}",
    ]
    return "\n".join(lines)


def _drain_iac(sock: socket.socket) -> bytes:
    """Drain and respond to telnet IAC negotiation (DO→WONT, WILL→DONT)."""
    response = bytearray()
    data = bytearray()
    try:
        sock.setblocking(False)
        try:
            chunk = sock.recv(4096)
            data.extend(chunk)
        except BlockingIOError:
            pass
    finally:
        sock.setblocking(True)

    i = 0
    while i < len(data):
        if data[i] == 0xFF and i + 2 < len(data):
            cmd_byte = data[i + 1]
            opt = data[i + 2]
            if cmd_byte == 0xFD:  # DO → WONT
                response.extend([0xFF, 0xFC, opt])
            elif cmd_byte == 0xFB:  # WILL → DONT
                response.extend([0xFF, 0xFE, opt])
            i += 3
        else:
            i += 1
    return bytes(response)


def _strip_iac(data: bytes) -> bytes:
    """Remove inline IAC sequences from telnet output."""
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0xFF and i + 2 < len(data):
            i += 3
        else:
            result.append(data[i])
            i += 1
    return bytes(result)


def telnet_run(
    ip: str, cmd: str, *, port: int = TELNET_PORT, timeout: float = 15.0
) -> str:
    """Run one command over a telnet session, return stdout (marker-trimmed)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        time.sleep(0.4)

        neg = _drain_iac(sock)
        if neg:
            sock.sendall(neg)

        full = f"{cmd}\necho {DONE_MARKER}\n"
        sock.sendall(full.encode())

        out = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                out.extend(_strip_iac(chunk))
                if DONE_MARKER.encode() in out:
                    break
            except socket.timeout:
                break

        text = out.decode(errors="replace")
        marker_pos = text.find(DONE_MARKER)
        if marker_pos >= 0:
            text = text[:marker_pos]
        return text
    finally:
        sock.close()


def read_file(ip: str, path: str, *, timeout: float = 15.0) -> str:
    """Read a file from the camera over telnet."""
    raw = telnet_run(ip, f"cat '{path}'", timeout=timeout)
    lines = raw.split("\n")
    result_lines: list[str] = []
    past_echo = False
    for line in lines:
        if not past_echo and "cat " in line:
            past_echo = True
            continue
        if past_echo:
            result_lines.append(line)
    return "\n".join(result_lines).strip() if result_lines else raw.strip()


def write_file(ip: str, path: str, body: str, *, timeout: float = 15.0) -> bool:
    """Write a file to the camera over telnet. Returns True on success."""
    out = telnet_run(ip, build_write_file_cmd(path, body), timeout=timeout)
    return f"WROTE {path}" in out


def osc_info(ip: str, *, port: int = OSC_PORT, timeout: float = 5.0) -> str | None:
    """GET /osc/info — parse serialNumber. Returns None on failure."""
    try:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.request("GET", "/osc/info")
        resp = conn.getresponse()
        body = resp.read().decode(errors="replace")
        conn.close()
        match = re.search(r'"serialNumber"\s*:\s*"([^"]+)"', body)
        return match.group(1) if match else None
    except (OSError, http.client.HTTPException):
        return None


def discover_camera(ip: str = "192.168.42.2", *, timeout: float = 10.0) -> CameraFacts:
    """Discover camera facts from the bench Mac (on the camera's SoftAP)."""
    serial = osc_info(ip, timeout=timeout)
    if not serial:
        raise ConnectionError(f"Could not read serial from camera at {ip}")
    mac = _arp_lookup(ip)
    return CameraFacts(body_serial=serial, ip=ip, mac=mac)


def _arp_lookup(ip: str) -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["arp", "-n", ip],
            capture_output=True,
            text=True,
            timeout=5,
        )
        match = re.search(r"at\s+([0-9a-fA-F:]+)", result.stdout)
        return match.group(1) if match else ""
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
