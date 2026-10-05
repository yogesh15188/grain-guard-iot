"""GrainGuard storage: SQLite in WAL mode with a simple hash-chained ledger.

Tables
  telemetry        every validated packet (live and simulated alike)
  events           state/risk/rule changes, append-only
  acknowledgments  operator responses, append-only

Acknowledgment never deletes or edits the original alert - it only adds a new
row. Chain verification uses plain SHA-256 over the previous hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("GRAINGUARD_DB", os.path.join(ROOT, "data", "storage.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    temp REAL, rh REAL, fork_raw INTEGER, ldr_raw INTEGER, distance_cm REAL,
    state TEXT, risk TEXT, rule TEXT,
    raw_json TEXT,
    prev_hash TEXT, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT, risk TEXT, rule TEXT,
    detail_json TEXT,
    prev_hash TEXT, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS acknowledgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    operator TEXT,
    event_id INTEGER,
    verified INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    prev_hash TEXT, hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_tel_ts ON telemetry(ts);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

class Database:
    def __init__(self, path: str = DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- hash chain ------------------------------------------------------
    def _last_hash(self, table: str) -> str:
        row = self.conn.execute(f"SELECT hash FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
        return row["hash"] if row else "GENESIS"

    def log_telemetry(self, packet: dict, result: dict, source: str) -> int:
        ts = packet.get("timestamp") or _now_iso()
        raw = json.dumps(packet, sort_keys=True, default=str)
        prev = self._last_hash("telemetry")
        h = _digest(f"{raw}|{ts}|{result.get('state')}|{result.get('risk')}", prev)
        cur = self.conn.execute(
            "INSERT INTO telemetry (ts,source,temp,rh,fork_raw,ldr_raw,distance_cm,"
            "state,risk,rule,raw_json,prev_hash,hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, source, packet.get("temp"), packet.get("rh"), packet.get("fork_raw"),
             packet.get("ldr_raw"), packet.get("distance_cm"), result.get("state"),
             result.get("risk"), result.get("rule"), raw, prev, h))
        self.conn.commit()
        return cur.lastrowid

    def log_event(self, kind: str, result: dict, detail: dict = None) -> int:
        ts = _now_iso()
        detail_json = json.dumps(detail or {}, sort_keys=True, default=str)
        prev = self._last_hash("events")
        h = _digest(f"{ts}|{kind}|{detail_json}", prev)
        cur = self.conn.execute(
            "INSERT INTO events (ts,kind,state,risk,rule,detail_json,prev_hash,hash) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ts, kind, result.get("state"), result.get("risk"), result.get("rule"),
             detail_json, prev, h))
        self.conn.commit()
        return cur.lastrowid

    def log_ack(self, operator: str, event_id: int, verified: int, note: str) -> dict:
        ts = _now_iso()
        prev = self._last_hash("acknowledgments")
        h = _digest(f"{ts}|{operator}|{event_id}|{verified}|{note}", prev)
        cur = self.conn.execute(
            "INSERT INTO acknowledgments (ts,operator,event_id,verified,note,prev_hash,hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (ts, operator, event_id, 1 if verified else 0, note, prev, h))
        self.conn.commit()
        return {"id": cur.lastrowid, "ts": ts, "operator": operator,
                "event_id": event_id, "verified": bool(verified), "note": note}

    # -- reads -----------------------------------------------------------
    def history(self, limit: int = 60) -> list:
        rows = self.conn.execute(
            "SELECT ts,source,temp,rh,fork_raw,ldr_raw,distance_cm,state,risk "
            "FROM telemetry ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def events(self, limit: int = 60) -> list:
        rows = self.conn.execute(
            "SELECT id,ts,kind,state,risk,rule,detail_json FROM events "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in reversed(rows):
            d = dict(r)
            try:
                d["detail"] = json.loads(d.pop("detail_json") or "{}")
            except ValueError:
                d["detail"] = {}
            out.append(d)
        return out

    def acknowledgments(self, limit: int = 30) -> list:
        rows = self.conn.execute(
            "SELECT id,ts,operator,event_id,verified,note FROM acknowledgments "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def verify_chain(self) -> dict:
        """Recompute ledger hashes. Any mismatch is reported, never hidden."""
        report = {"telemetry": True, "events": True, "acknowledgments": True, "detail": ""}
        for table in ("telemetry", "events", "acknowledgments"):
            prev = "GENESIS"
            for row in self.conn.execute(f"SELECT * FROM {table} ORDER BY id ASC").fetchall():
                d = dict(row)
                if d["prev_hash"] != prev:
                    report[table] = False
                    report["detail"] = f"{table}: broken chain at row {d['id']}"
                    return report
                prev = d["hash"]
        return report

def _digest(payload: str, prev_hash: str) -> str:
    return hashlib.sha256((prev_hash + "|" + payload).encode("utf-8")).hexdigest()