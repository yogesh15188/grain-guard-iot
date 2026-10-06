"""Monitor an append-only sensor CSV and feed each complete row once."""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import math
import os
import threading

FIELDS = ("temp", "rh", "fork_raw", "ldr_raw", "distance_cm")


class CsvWorker(threading.Thread):
    """Import existing CSV rows, then follow appended rows without replaying."""

    daemon = True

    def __init__(self, path, db, on_packet, interval: float = 1.0):
        super().__init__()
        self.path = os.path.abspath(os.path.expanduser(path))
        self.db = db
        self.on_packet = on_packet
        self.interval = interval
        self.detail = f"waiting for CSV file: {self.path}"
        self.last_error = None
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    @staticmethod
    def _packet(headers, line):
        try:
            values = next(csv.reader([line.decode("utf-8-sig").rstrip("\r\n")]))
        except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
            raise ValueError(f"invalid CSV row: {exc}") from exc
        if len(values) != len(headers):
            raise ValueError(
                f"CSV row has {len(values)} values; expected {len(headers)}")

        row = dict(zip(headers, values))
        packet = {}
        timestamp = row.get("timestamp", "").strip()
        if not timestamp:
            raise ValueError("CSV row is missing 'timestamp'")
        try:
            parsed_timestamp = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("CSV 'timestamp' must be ISO-8601") from exc
        if parsed_timestamp.tzinfo is None:
            raise ValueError("CSV 'timestamp' must include a timezone")
        packet["timestamp"] = timestamp
        for field in FIELDS:
            value = row.get(field, "").strip()
            if not value:
                raise ValueError(f"CSV row is missing '{field}'")
            try:
                number = float(value)
            except ValueError as exc:
                raise ValueError(f"CSV '{field}' is not numeric") from exc
            if not math.isfinite(number):
                raise ValueError(f"CSV '{field}' must be finite")
            packet[field] = number
        return packet

    def read_available(self) -> int:
        """Process complete rows currently available; return rows accepted."""
        with open(self.path, "rb") as source:
            stat = os.fstat(source.fileno())
            header_line = source.readline()
            if not header_line.endswith((b"\n", b"\r")):
                raise ValueError("CSV header must end with a newline")
            try:
                headers = next(csv.reader([header_line.decode("utf-8-sig").rstrip("\r\n")]))
            except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
                raise ValueError(f"invalid CSV header: {exc}") from exc

            if len(headers) != len(set(headers)):
                raise ValueError("CSV header contains duplicate column names")
            missing = sorted(set(FIELDS + ("timestamp",)) - set(headers))
            if missing:
                raise ValueError("CSV header is missing: " + ", ".join(missing))

            header_end = source.tell()
            signature = hashlib.sha256(
                f"{stat.st_dev}:{stat.st_ino}:".encode("utf-8") + header_line
            ).hexdigest()
            cursor = self.db.csv_cursor(self.path)
            offset = header_end
            if cursor and cursor["file_signature"] == signature \
                    and header_end <= cursor["byte_offset"] <= stat.st_size:
                offset = cursor["byte_offset"]
            source.seek(offset)

            accepted = 0
            while not self._stop_event.is_set():
                row_start = source.tell()
                line = source.readline()
                if not line:
                    break
                if not line.endswith((b"\n", b"\r")):
                    source.seek(row_start)
                    break
                row_end = source.tell()
                try:
                    packet = self._packet(headers, line)
                except ValueError as exc:
                    self.last_error = f"row at byte {row_start}: {exc}"
                    self.db.save_csv_cursor(self.path, signature, row_end)
                    continue

                self.on_packet(packet, "FILE")
                self.db.save_csv_cursor(self.path, signature, row_end)
                self.last_error = None
                accepted += 1

            if self.last_error:
                self.detail = f"CSV monitoring with invalid row ({self.last_error})"
            else:
                self.detail = f"CSV LIVE — {self.path}"
            return accepted

    def run(self):
        while not self._stop_event.is_set():
            try:
                self.read_available()
            except (OSError, ValueError, csv.Error) as exc:
                self.last_error = str(exc)[:200]
                self.detail = f"CSV INPUT ERROR — {self.last_error}"
            except Exception as exc:  # keep the worker alive and expose failures
                self.last_error = str(exc)[:200]
                self.detail = f"CSV PIPELINE ERROR — {self.last_error}"
            self._stop_event.wait(self.interval)
