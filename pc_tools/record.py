"""
HealthyPi Move real-time acquisition with Start/Stop, timestamping and storage.

Writes each session to SQLite (queryable) and optionally CSV (export). Every
notification is stamped with host wall-clock and monotonic arrival time and
given a synthetic per-signal sample index, because the firmware sends no
timestamp and no sequence number of its own (see docs/BLE_SPEC.md).

Usage:
    python record.py --duration 60 --signals ecg,gsr --csv
    python record.py --signals none --duration 120 --csv  # scalar readings only

Firmware 3.1.0: receive live waveforms plus scalar notifications/indications.
Start measurements on the watch. Legacy v2 control is opt-in (--legacy-control).
"""
import argparse
import asyncio
import contextlib
import csv
import math
import logging
import os
import signal as _signal
import sqlite3
import sys
import time

from bleak import BleakScanner, BleakClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpi_ble as H
import hpi_control as C

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class Recorder:
    """Session-scoped writer for waveform packets and scalar readings."""

    def __init__(self, db_path, session_note=""):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self.session_id = self._start_session(session_note)
        self.stats = {}
        self.t0_mono = time.monotonic()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_utc REAL NOT NULL,
                ended_utc   REAL,
                device_addr TEXT,
                note        TEXT
            );
            CREATE TABLE IF NOT EXISTS packets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id),
                signal      TEXT    NOT NULL,
                pkt_seq     INTEGER NOT NULL,
                recv_utc    REAL    NOT NULL,
                recv_mono   REAL    NOT NULL,
                n_samples   INTEGER NOT NULL,
                first_index INTEGER NOT NULL,
                payload     BLOB    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scalars (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id),
                signal      TEXT    NOT NULL,
                recv_utc    REAL    NOT NULL,
                value       TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pkt_sess
                ON packets(session_id, signal, pkt_seq);
            """
        )
        self.conn.commit()

    def _start_session(self, note):
        cur = self.conn.execute(
            "INSERT INTO sessions (started_utc, note) VALUES (?, ?)",
            (time.time(), note))
        self.conn.commit()
        return cur.lastrowid

    def set_device(self, addr):
        self.conn.execute("UPDATE sessions SET device_addr=? WHERE id=?",
                          (addr, self.session_id))
        self.conn.commit()

    def on_waveform(self, sig, payload):
        if not payload or len(payload) % 4:
            print("Invalid %s payload: %d bytes; discarded" % (sig.key, len(payload)))
            return
        st = self.stats.setdefault(sig.key, {"pkts": 0, "samples": 0})
        n = len(payload) // 4
        self.conn.execute(
            "INSERT INTO packets (session_id, signal, pkt_seq, recv_utc,"
            " recv_mono, n_samples, first_index, payload)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (self.session_id, sig.key, st["pkts"], time.time(),
             time.monotonic(), n, st["samples"], payload))
        st["pkts"] += 1
        st["samples"] += n

    def on_scalar(self, key, value):
        if value is None:
            print("Invalid/empty %s reading; discarded" % key)
            return
        print("  reading %s = %s" % (key, value))
        self.conn.execute(
            "INSERT INTO scalars (session_id, signal, recv_utc, value)"
            " VALUES (?,?,?,?)",
            (self.session_id, key, time.time(), str(value)))
        st = self.stats.setdefault(key, {"pkts": 0, "samples": 0})
        st["pkts"] += 1
        st["samples"] += 1

    def close(self):
        self.conn.execute("UPDATE sessions SET ended_utc=? WHERE id=?",
                          (time.time(), self.session_id))
        self.conn.commit()
        self.conn.close()

    def summary(self):
        """Returns (elapsed_s, [(key, pkts, samples, eff_hz, nominal, yield%)])."""
        elapsed = time.monotonic() - self.t0_mono
        rows = []
        for key, st in sorted(self.stats.items()):
            sig = H.WAVEFORMS_BY_KEY.get(key)
            eff = st["samples"] / elapsed if elapsed > 0 else 0.0
            nominal = sig.rate_hz if sig else None
            yield_pct = (100.0 * eff / nominal) if nominal else None
            rows.append((key, st["pkts"], st["samples"], eff, nominal, yield_pct))
        return elapsed, rows


def export_csv(db_path, session_id, out_dir):
    """One CSV per signal: sample_index, recv_utc, est_time_s, value."""
    os.makedirs(out_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    written = []

    waveform_keys = [r[0] for r in conn.execute(
        "SELECT DISTINCT signal FROM packets WHERE session_id=?", (session_id,))]
    for key in waveform_keys:
        sig = H.WAVEFORMS_BY_KEY[key]
        path = os.path.join(out_dir, "session%d_%s.csv" % (session_id, key))
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("sample_index,recv_utc,est_time_s,value\n")
            for first_index, recv_utc, payload in conn.execute(
                    "SELECT first_index, recv_utc, payload FROM packets"
                    " WHERE session_id=? AND signal=? ORDER BY pkt_seq",
                    (session_id, key)):
                for i, v in enumerate(sig.decode(payload)):
                    idx = first_index + i
                    f.write("%d,%.6f,%.6f,%d\n"
                            % (idx, recv_utc, idx / sig.rate_hz, v))
        written.append(path)

    scalar_keys = [r[0] for r in conn.execute(
        "SELECT DISTINCT signal FROM scalars WHERE session_id=?", (session_id,))]
    for key in scalar_keys:
        path = os.path.join(out_dir, "session%d_%s.csv" % (session_id, key))
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["recv_utc", "value"])
            for recv_utc, value in conn.execute(
                    "SELECT recv_utc, value FROM scalars"
                    " WHERE session_id=? AND signal=? ORDER BY id",
                    (session_id, key)):
                writer.writerow(["%.6f" % recv_utc, value])
        written.append(path)

    conn.close()
    return written


async def run(args):
    scalar_keys = [k.strip() for k in getattr(args, "scalar_signals", "hr,temp,spo2,battery").split(",")]
    invalid_scalars = set(scalar_keys) - {"hr", "temp", "spo2", "battery"}
    if invalid_scalars:
        print("Unknown scalar readings: %s" % sorted(invalid_scalars))
        return 1
    scalar_keys = list(dict.fromkeys(scalar_keys)) if args.scalars else []
    keys = ([k.strip() for k in args.signals.split(",")]
            if args.signals else list(H.WAVEFORMS_BY_KEY))
    if keys == ["none"]:
        keys = []
    unknown = [k for k in keys if k not in H.WAVEFORMS_BY_KEY]
    if unknown:
        print("Unknown signal(s): %s. Known: %s"
              % (unknown, list(H.WAVEFORMS_BY_KEY)))
        return 1

    print("Scanning for '%s' ..." % H.DEVICE_NAME)
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: bool(d.name) and H.DEVICE_NAME.lower() in d.name.lower(),
        timeout=args.scan_timeout)
    if dev is None:
        print("Device not found. Wake the watch and disconnect the phone app.")
        return 1

    db_path = args.db or os.path.join(DATA_DIR, "recordings.db")
    rec = Recorder(db_path, args.note)
    print("Found %s. Session #%d -> %s" % (dev.address, rec.session_id, db_path))
    rec.set_device(dev.address)

    stop = asyncio.Event()
    stop_reason = []

    def disconnected(_client):
        if not stop_reason:
            stop_reason.append("unexpected Bluetooth disconnect")
            print("Unexpected Bluetooth disconnect; ending partial recording.")
        logging.getLogger(__name__).debug("Disconnect callback; reason=%s", stop_reason)
        stop.set()

    try:
        async with BleakClient(dev.address, disconnected_callback=disconnected,
                               pair=args.pair) as client:
            print("Connected. MTU=%s" % client.mtu_size)
            available = {c.uuid.lower()
                         for s in client.services for c in s.characteristics}
    
            chars = {c.uuid.lower(): c for service in client.services
                     for c in service.characteristics}
            subscribed = []
            for key in keys:
                sig = H.WAVEFORMS_BY_KEY[key]
                if sig.uuid not in available:
                    print("  ! %s: characteristic absent on this firmware" % sig.label)
                    continue
    
                def make_cb(s):
                    return lambda _h, data: rec.on_waveform(s, bytes(data))
    
                try:
                    await client.start_notify(sig.uuid, make_cb(sig))
                    subscribed.append(sig.uuid)
                    print("  + %s @ %d Hz" % (sig.label, sig.rate_hz))
                except Exception as exc:
                    print("  ! %s: subscribe failed: %s" % (sig.label, exc))
    
            if args.scalars:
                for uuid, (skey, label, _unit, decoder) in H.SCALAR_SIGNALS.items():
                    if skey not in scalar_keys:
                        continue
                    if uuid not in available:
                        print("  ! %s: endpoint absent" % label)
                        continue
                    props = chars[uuid].properties
                    if not ({"notify", "indicate"} & set(props)):
                        print("  ! %s: no notify/indicate support" % label)
                        continue
    
                    def make_scb(k, dec):
                        def callback(_h, data):
                            try:
                                rec.on_scalar(k, dec(bytes(data)))
                            except (ValueError, IndexError, OverflowError) as exc:
                                print("Invalid %s reading: %s" % (k, exc))
                        return callback
    
                    try:
                        await client.start_notify(uuid, make_scb(skey, decoder))
                        subscribed.append(uuid)
                        print("  + %s (%s)" % (label, ",".join(props)))
                    except Exception as exc:
                        print("  ! %s: subscribe failed: %s" % (label, exc))
    
            if not subscribed:
                print("Nothing subscribed - aborting.")
                return 1
    
            # Remote Start/Stop via the v2.x CMD service. Without this the sensors
            # only run while a measurement is open on the watch itself, so the
            # waveform characteristics stay silent (see docs/BLE_SPEC.md section 3).
            control = (args.legacy_control and C.UUID_CMD_TX in available
                       and not args.no_control)
            if not control:
                print("\nReceive-only mode for firmware 3.1.0: start ECG/EDA/SpO2 "
                      "measurements on the watch. Stopping Python does not stop sensors.")
                if args.legacy_control:
                    print("Legacy control unavailable or disabled; no commands sent.")
            else:
                def rsp_cb(_h, data):
                    parsed = C.parse_response(bytes(data))
                    rec.on_scalar("cmd_rsp", parsed)
                    print("  <- %s" % parsed.get("meaning", parsed))
    
                with contextlib.suppress(Exception):
                    await client.start_notify(C.UUID_CMD_RX, rsp_cb)
                    subscribed.append(C.UUID_CMD_RX)
    
                mask = C.mask_from_names(args.record_signals.split(","))
                # Firmware caps duration at 3600 s and rejects 0; it stops itself at
                # the configured duration, so ask for the full window we intend.
                dur = int(min(args.duration or C.REC_MAX_DURATION_S,
                              C.REC_MAX_DURATION_S))
                print("\nStarting on-watch recording: %s, %d s"
                      % (C.names_from_mask(mask), dur))
                await client.write_gatt_char(
                    C.UUID_CMD_TX, C.frame_configure(dur, mask, args.decimation),
                    response=False)
                await asyncio.sleep(1.5)   # v2.1.1 cmd_thread sleeps 1 s per command
                await client.write_gatt_char(C.UUID_CMD_TX, C.frame_start(),
                                             response=False)
                await asyncio.sleep(1.5)
    
            print("\n--- RECORDING (Ctrl+C to stop) ---")
            loop = asyncio.get_running_loop()
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(_signal.SIGINT, stop.set)
    
            async def ticker():
                while not stop.is_set():
                    await asyncio.sleep(2)
                    rec.conn.commit()  # bound loss from a process crash
                    elapsed, rows = rec.summary()
                    parts = ["%s:%d" % (k, rec.stats.get(k, {}).get("samples", 0))
                             for k in dict.fromkeys(keys +
                                 scalar_keys)]
                    print("  t=%6.1fs  %s" % (elapsed, "  ".join(parts)), flush=True)
    
            tick = asyncio.create_task(ticker())
            try:
                if args.duration:
                    await asyncio.wait_for(stop.wait(), timeout=args.duration)
                else:
                    await stop.wait()
            except asyncio.TimeoutError:
                stop_reason.append("requested duration reached")
            except KeyboardInterrupt:
                stop_reason.append("user stopped recording")
            finally:
                tick.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tick
                if control:
                    print("\nStopping on-watch recording ...")
                    with contextlib.suppress(Exception):
                        await client.write_gatt_char(C.UUID_CMD_TX, C.frame_stop(),
                                                     response=False)
                        await asyncio.sleep(1.5)
                for uuid in subscribed:
                    with contextlib.suppress(Exception):
                        await client.stop_notify(uuid)
    except (Exception, asyncio.CancelledError) as exc:
        stop_reason.append("capture error or cancellation")
        logging.getLogger(__name__).exception("Capture interrupted")
        print("Capture interrupted: %s: %s" % (type(exc).__name__, exc))
        return 1
    finally:
        print("Capture ended: %s" % (stop_reason[0] if stop_reason else "setup ended"))
        rec.close()
        if args.csv:
            for path in export_csv(db_path, rec.session_id, os.path.join(DATA_DIR, "csv")):
                print("  CSV -> %s" % path)

    elapsed, rows = rec.summary()
    session_id = rec.session_id

    print("\n--- SESSION #%d SUMMARY  (%.1f s) ---" % (session_id, elapsed))
    print("%-12s%8s%10s%10s%10s%9s"
          % ("signal", "pkts", "samples", "eff Hz", "nominal", "yield"))
    for key, pkts, n, eff, nominal, yld in rows:
        print("%-12s%8d%10d%10.2f%10s%9s"
              % (key, pkts, n, eff,
                 nominal if nominal else "-",
                 ("%.1f%%" % yld) if yld is not None else "-"))

    for key in keys + scalar_keys:
        if key not in rec.stats:
            print("  NO DATA: %s (not a zero measurement; no reading received)" % key)
    return 0


def main():
    ap = argparse.ArgumentParser(description="HealthyPi Move real-time recorder")
    ap.add_argument("--signals", help="comma list: ecg,gsr,ppg_wrist,ppg_finger; none for scalars only")
    ap.add_argument("--duration", type=float,
                    help="seconds; omit to run until Ctrl+C")
    ap.add_argument("--scan-timeout", type=float, default=15.0)
    ap.add_argument("--db", help="SQLite path (default data/recordings.db)")
    ap.add_argument("--csv", action="store_true", help="export CSV afterwards")
    ap.add_argument("--scalars", action=argparse.BooleanOptionalAction, default=True,
                    help="also subscribe HR/battery/SpO2/temp")
    ap.add_argument("--scalar-signals", default="hr,temp,spo2,battery",
                    help="comma list of processed/status readings: hr,temp,spo2,battery")
    ap.add_argument("--note", default="", help="session note")
    ap.add_argument("--record-signals", default="gsr,ppg_wrist,accel,gyro",
                    help="on-watch recording mask: ppg_wrist,ppg_finger,"
                         "accel,gyro,gsr")
    ap.add_argument("--decimation", type=int, default=1,
                    help="on-watch decimation (1 = full rate)")
    ap.add_argument("--no-control", action="store_true",
                    help="do not send Start/Stop; drive the watch by hand")
    ap.add_argument("--legacy-control", action="store_true",
                    help="opt in to OLD v2.x recording commands; not for v3.1.0")
    ap.add_argument("--pair", action="store_true",
                    help="request Bluetooth pairing if protected readings require it")
    ap.add_argument("--debug", action="store_true",
                    help="write detailed BLE diagnostics to data/ble_debug.log")
    args = ap.parse_args()
    if args.debug:
        os.makedirs(DATA_DIR, exist_ok=True)
        log_path = os.path.join(DATA_DIR, "ble_debug.log")
        logging.basicConfig(filename=log_path, filemode="w", level=logging.DEBUG,
                            format="%(asctime)s %(name)s %(levelname)s %(message)s",
                            force=True)
        print("Detailed Bluetooth log: %s" % log_path)
        logging.getLogger(__name__).debug("Recording arguments: %s", args)
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        ap.error("--duration must be a finite positive number")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
