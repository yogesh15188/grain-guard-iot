"""Serial reader with automatic mock fallback.

Tries real hardware first. On any failure it switches to mock mode and keeps
running - this worker must never crash the application. It does not touch
firmware; it only reads the JSON line the firmware already emits.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time

PORT = os.environ.get("GRAINGUARD_SERIAL_PORT", "")
BAUD = int(os.environ.get("GRAINGUARD_SERIAL_BAUD", "9600"))
FIELDS = ("temp", "rh", "fork_raw", "ldr_raw", "distance_cm")


def parse_line(line: str):
    """Parse and validate one telemetry line. Returns dict or None."""
    if not line:
        return None
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    out = {}
    for key in FIELDS:
        val = obj.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out[key] = float(val)
    return out or None


class SerialWorker(threading.Thread):
    """Background thread producing telemetry dicts onto a queue-like callback."""

    daemon = True

    def __init__(self, on_packet, mock_packet=None, interval: float = 1.0):
        super().__init__()
        self.on_packet = on_packet
        self.mock_packet = mock_packet or {}
        self.interval = interval
        self.mode = "MOCK"           # MOCK | LIVE | SIMULATION
        self.detail = "starting"
        self.last_error = None
        self._stop = threading.Event()

    # -- hardware --------------------------------------------------------
    def _open_serial(self):
        try:
            import serial  # optional dependency
        except ImportError:
            raise RuntimeError("pyserial not installed")
        port = PORT or self._first_port()
        if not port:
            raise RuntimeError("no serial port found")
        return serial.Serial(port, BAUD, timeout=2)

    @staticmethod
    def _first_port():
        try:
            ports = glob.glob("COM*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
            return sorted(ports)[0] if ports else None
        except OSError:
            return None

    def _hardware_loop(self, ser):
        while not self._stop.is_set():
            raw = ser.readline()
            if not raw:
                continue
            packet = parse_line(raw.decode("utf-8", "ignore"))
            if packet:
                self.on_packet(packet, "LIVE")
        ser.close()

    # -- mock loop -------------------------------------------------------
    def _mock_loop(self):
        base = dict(self.mock_packet)
        while not self._stop.is_set():
            packet = dict(base)
            # Gentle drift so the dashboard feels alive without faking risk.
            packet["temp"] = round(packet.get("temp", 27.0) + _drift(), 2)
            packet["rh"] = round(min(100.0, max(0.0, packet.get("rh", 60.0) + _drift() * 2)), 2)
            packet["distance_cm"] = round(packet.get("distance_cm", 15.0) + _drift() * 0.3, 2)
            self.on_packet(packet, self.mode)
            time.sleep(self.interval)

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            self.mode = "LIVE"
            self.detail = f"opening serial on {PORT or 'auto'}"
            ser = self._open_serial()
            self.detail = f"connected to {ser.name}"
            self._hardware_loop(ser)
        except Exception as exc:                     # noqa: BLE001 - must not crash
            self.last_error = str(exc)[:200]
            self.mode = "MOCK"
            self.detail = f"HARDWARE OFFLINE — SIMULATION MODE ({exc})"[:200]
            try:
                self._mock_loop()
            except Exception:                        # noqa: BLE001
                pass


def _drift() -> float:
    import random
    return round(random.uniform(-0.05, 0.05), 3)