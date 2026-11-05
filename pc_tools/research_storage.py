"""S3/S4: versioned host packets and Windows-user encrypted SQLite storage."""
import csv
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsCipher:
    """DPAPI with UI forbidden and current-user scope; never silently plaintext."""
    name = "windows-dpapi-user-v1"

    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Encrypted recording currently requires Windows DPAPI.")
        self.dll = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p
        for name in ("CryptProtectData", "CryptUnprotectData"):
            fn = getattr(self.dll, name)
            fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p,
                           ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                           wintypes.DWORD, ctypes.POINTER(_Blob)]
            fn.restype = wintypes.BOOL

    def _convert(self, payload, decrypt):
        buf = ctypes.create_string_buffer(payload)
        incoming = _Blob(len(payload), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        outgoing = _Blob()
        fn = self.dll.CryptUnprotectData if decrypt else self.dll.CryptProtectData
        if not fn(ctypes.byref(incoming), None, None, None, None, 1,
                  ctypes.byref(outgoing)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(outgoing.data, outgoing.size)
        finally:
            self.kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))

    def encrypt(self, data):
        return self._convert(data, False)

    def decrypt(self, data):
        return self._convert(data, True)


class SessionStore:
    def __init__(self, path, cipher=None):
        self.cipher = cipher or WindowsCipher()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS research_sessions (
            id TEXT PRIMARY KEY, started_utc REAL NOT NULL, ended_utc REAL,
            status TEXT NOT NULL, source TEXT NOT NULL, device TEXT,
            selected TEXT NOT NULL, note TEXT NOT NULL, cipher TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS research_packets (
            session_id TEXT NOT NULL REFERENCES research_sessions(id),
            seq INTEGER NOT NULL, signal TEXT NOT NULL, recv_utc REAL NOT NULL,
            encrypted BLOB NOT NULL, PRIMARY KEY(session_id,seq));
          CREATE TABLE IF NOT EXISTS research_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES research_sessions(id),
            utc REAL NOT NULL, elapsed_s REAL NOT NULL,
            kind TEXT NOT NULL, details TEXT NOT NULL);
        ''')
        self.db.commit()

    def start(self, signals, source="watch", device=None, note=""):
        sid = str(uuid.uuid4())
        self.db.execute("INSERT INTO research_sessions VALUES (?,?,NULL,?,?,?,?,?,?)",
                        (sid, time.time(), "recording", source, device,
                         json.dumps(signals), note, self.cipher.name))
        self.db.commit()
        return sid

    def append(self, sid, packet):
        envelope = dict(packet, session_id=sid)
        data = json.dumps(envelope, allow_nan=False, separators=(",", ":")).encode()
        encrypted = self.cipher.encrypt(data)
        self.db.execute("INSERT INTO research_packets VALUES (?,?,?,?,?)",
                        (sid, packet["seq"], packet["signal"], packet["recv_utc"], encrypted))

    def flush(self):
        self.db.commit()

    def event(self, sid, elapsed, kind, details=""):
        self.db.execute("INSERT INTO research_events "
                        "(session_id,utc,elapsed_s,kind,details) VALUES (?,?,?,?,?)",
                        (sid, time.time(), elapsed, kind, details))
        self.db.commit()

    def events(self, sid):
        return self.db.execute("SELECT utc,elapsed_s,kind,details FROM research_events "
                               "WHERE session_id=? ORDER BY id", (sid,)).fetchall()

    def export_events_csv(self, sid, destination):
        with open(destination, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["utc", "elapsed_s", "event", "details"])
            writer.writerows(self.events(sid))

    def finish(self, sid, status):
        self.db.execute("UPDATE research_sessions SET ended_utc=?,status=? WHERE id=?",
                        (time.time(), status, sid))
        self.db.commit()

    def sessions(self):
        return self.db.execute("SELECT id,started_utc,status,source FROM research_sessions "
                               "ORDER BY started_utc DESC").fetchall()

    def packets(self, sid):
        row = self.db.execute("SELECT cipher FROM research_sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise ValueError("Session does not exist")
        if row[0] != self.cipher.name:
            raise ValueError("Session uses a different encryption scheme")
        for seq, signal, received, encrypted in self.db.execute(
                "SELECT seq,signal,recv_utc,encrypted FROM research_packets "
                "WHERE session_id=? ORDER BY seq", (sid,)):
            packet = json.loads(self.cipher.decrypt(encrypted))
            if (packet["session_id"] != sid or packet["seq"] != seq or
                    packet["signal"] != signal or packet["recv_utc"] != received):
                raise ValueError("Packet metadata does not match its protected contents")
            yield packet

    def export_csv(self, sid, destination):
        # Explicit user export only. CSV contains plaintext readings.
        with open(destination, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["schema", "session_id", "packet_seq_host", "signal",
                             "recv_utc", "recv_elapsed_s", "sample_index_host",
                             "estimated_elapsed_s", "timing_basis", "value", "connection_segment"])
            for packet in self.packets(sid):
                for i, value in enumerate(packet["values"]):
                    estimated = packet["estimated_first_s"]
                    if packet["nominal_hz"]:
                        estimated += i / packet["nominal_hz"]
                    writer.writerow([1, sid, packet["seq"], packet["signal"],
                                     packet["recv_utc"], packet["recv_elapsed_s"],
                                     packet["first_index"] + i, estimated,
                                     packet["timing_basis"],
                                     json.dumps(value, allow_nan=False), packet.get("connection_segment", 0)])

    def close(self):
        self.db.close()


class PacketBuilder:
    """Host metadata; does not invent device timestamps or loss guarantees."""
    def __init__(self):
        self.started = time.monotonic()
        self.seq = 0
        self.index = {}
        self.anchor = {}
        self.connection_segment = 0

    def make(self, signal, values, rate=None, raw=b""):
        if not values:
            raise ValueError("Empty reading")
        if rate is not None and (not math.isfinite(rate) or rate <= 0):
            raise ValueError("Invalid rate")
        elapsed = time.monotonic() - self.started
        first = self.index.get(signal, 0)
        # Approximate positions within a batch using nominal spacing. Anchor
        # each batch to host arrival; gaps remain visible, but BLE jitter remains.
        estimated = elapsed - ((len(values) - 1) / rate if rate else 0)
        packet = dict(schema=1, seq=self.seq, signal=signal, recv_utc=time.time(),
                      connection_segment=self.connection_segment,
                      recv_elapsed_s=elapsed, first_index=first, nominal_hz=rate,
                      estimated_first_s=estimated,
                      timing_basis="host-arrival/nominal-spacing" if rate else "host-arrival",
                      device_timestamp=None, device_sequence=None,
                      values=values, raw_hex=raw.hex())
        # Validate before changing counters or writing.
        json.dumps(packet, allow_nan=False)
        self.index[signal] = first + len(values)
        self.seq += 1
        return packet
