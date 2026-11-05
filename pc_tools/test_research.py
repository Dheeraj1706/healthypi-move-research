"""Offline regression tests: python -m unittest discover -s pc_tools -p test_research.py -v"""
import asyncio
import csv
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace as N

import hpi_ble as H
from research_storage import PacketBuilder, SessionStore, WindowsCipher
from research_capture import Capture


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "tmp")
        self.path = Path(self.temp.name) / "recordings.db"

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows only")
    def test_dpapi_roundtrip_and_tampering(self):
        cipher = WindowsCipher()
        data = b"private test sensor values 1,2,3"
        encrypted = cipher.encrypt(data)
        self.assertNotIn(data, encrypted)
        self.assertEqual(cipher.decrypt(encrypted), data)
        damaged = bytearray(encrypted)
        damaged[-1] ^= 1
        with self.assertRaises(OSError):
            cipher.decrypt(bytes(damaged))

    def test_storage_reopen_export_and_metadata_integrity(self):
        store = SessionStore(self.path)
        sid = store.start(["ecg", "spo2"])
        builder = PacketBuilder()
        packet = builder.make("ecg", [-12, 1000], 128, b"example")
        store.append(sid, packet)
        store.append(sid, builder.make("spo2", [{"spo2": 98, "pulse_rate": 66}]))
        store.flush()
        reader = SessionStore(self.path)
        self.assertEqual(len(list(reader.packets(sid))), 2)
        reader.close()
        store.finish(sid, "stopped")
        store.close()
        with sqlite3.connect(self.path) as db:
            payload = db.execute("SELECT encrypted FROM research_packets LIMIT 1").fetchone()[0]
            self.assertNotIn(b'"values"', payload)
            self.assertEqual(db.execute("SELECT status FROM research_sessions").fetchone()[0], "stopped")
        db.close()
        store = SessionStore(self.path)
        self.assertEqual(list(store.packets(sid))[0]["values"], [-12, 1000])
        out = Path(self.temp.name) / "export.csv"
        store.export_csv(sid, out)
        with out.open(newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(rows[-1]), len(rows[0]))
        self.assertEqual(float(rows[2][7]) - float(rows[1][7]), 1 / 128)
        store.db.execute("UPDATE research_packets SET signal='wrong' WHERE seq=0")
        store.flush()
        with self.assertRaises(ValueError):
            list(store.packets(sid))
        store.close()

    def test_ui_demo_start_stop(self):
        import tkinter as tk
        import research_app as app
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(app, "DATABASE", self.path):
                ui = app.ResearchApp(root)
                ui.mode.set(True)
                ui.duration.set("0")
                ui.start()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and ui.metrics["hr"].get() == "--":
                    root.update()
                    time.sleep(.02)
                self.assertEqual(ui.metrics["hr"].get(), "66")
                self.assertTrue(ui.buffers["ppg_wrist"])
                ui.stop()
                deadline = time.monotonic() + 5
                while ui.capture is not None and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.02)
                self.assertIsNone(ui.capture)
                self.assertTrue(ui.sessions.get_children())
                self.assertTrue(ui.session_id)
        finally:
            root.destroy()

    def test_demo_stop_persists_marked_synthetic_session(self):
        cap = Capture(self.path, ["ppg_wrist", "hr", "spo2"], demo=True)
        cap.start()
        deadline = time.monotonic() + 8
        while cap.plot_packets.empty() and cap.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        cap.stop()
        cap.thread.join(10)
        self.assertFalse(cap.thread.is_alive())
        store = SessionStore(self.path)
        rows = store.sessions()
        self.assertEqual(rows[0][2:], ("stopped", "synthetic-demo"))
        self.assertTrue(list(store.packets(rows[0][0])))
        store.close()

    def test_mock_ble_selection_malformed_and_disconnect(self):
        selected = []
        class Scanner:
            @staticmethod
            async def find_device_by_filter(*a, **k):
                return N(address="mock-watch", name="healthypi move")
        class Client:
            def __init__(self, *a, **k):
                self.disconnect = k["disconnected_callback"]
                self.services = [N(characteristics=[
                    N(uuid=H.UUID_ECG_CHAR, properties=["notify"]),
                    N(uuid=H.UUID_TEMPERATURE, properties=["indicate"])])]
            async def connect(self):
                return self
            async def disconnect(self):
                pass
            async def start_notify(self, char, cb):
                selected.append(char.uuid)
                if char.uuid == H.UUID_ECG_CHAR:
                    cb(None, b"bad")
                    cb(None, b"\x01\x00\x00\x00")
                else:
                    cb(None, bytes([0, 16, 14, 0, 254]))
                    asyncio.get_running_loop().call_later(.02, self.disconnect, self)
            async def stop_notify(self, uuid):
                pass
        cap = Capture(self.path, ["ecg", "temp"], seconds=.4, retry_delay=.02)
        with patch("research_capture.BleakScanner", Scanner), patch("research_capture.BleakClient", Client):
            cap.start()
            cap.thread.join(10)
        self.assertFalse(cap.thread.is_alive())
        self.assertGreaterEqual(cap.malformed["ecg"], 2)
        self.assertEqual(cap.counts["ecg"], cap.counts["temp"])
        store = SessionStore(self.path)
        sid, started, status, source = store.sessions()[0]
        self.assertEqual(status, "completed_with_gaps")
        packets = list(store.packets(sid))
        self.assertGreaterEqual(len(packets), 4)
        self.assertEqual(len(store.sessions()), 1)
        self.assertEqual([p["seq"] for p in packets], list(range(len(packets))))
        self.assertGreater(packets[-1]["connection_segment"], 0)
        self.assertGreater(packets[-2]["first_index"], 0)
        self.assertTrue(any(row[2] == "connection_gap" for row in store.events(sid)))
        store.close()

    def test_stop_cancels_long_scan(self):
        class Scanner:
            @staticmethod
            async def find_device_by_filter(*a, **k):
                await asyncio.sleep(60)
        cap = Capture(self.path, ["hr"])
        with patch("research_capture.BleakScanner", Scanner):
            cap.start()
            time.sleep(.1)
            cap.stop()
            cap.thread.join(2)
        self.assertFalse(cap.thread.is_alive())


    def test_duration_expires_while_reconnecting(self):
        attempts = []
        class Scanner:
            @staticmethod
            async def find_device_by_filter(*a, **k):
                attempts.append(1)
                if len(attempts) > 1:
                    await asyncio.sleep(60)
                return N(address="mock-watch", name="healthypi move")
        class Client:
            def __init__(self, *a, **k):
                self.callback = k["disconnected_callback"]
                self.services = [N(characteristics=[N(uuid=H.UUID_HR_MEASUREMENT,
                                                     properties=["notify"])])]
            async def connect(self):
                pass
            async def disconnect(self):
                pass
            async def start_notify(self, char, cb):
                cb(None, bytes([0, 66]))
                asyncio.get_running_loop().call_later(.02, self.callback, self)
        cap = Capture(self.path, ["hr"], seconds=.4, retry_delay=.01)
        with patch("research_capture.BleakScanner", Scanner), patch("research_capture.BleakClient", Client):
            cap.start()
            cap.thread.join(3)
        self.assertFalse(cap.thread.is_alive())
        self.assertGreaterEqual(len(attempts), 2)
        store = SessionStore(self.path)
        self.assertEqual(store.sessions()[0][2], "completed_with_gaps")
        store.close()


if __name__ == "__main__":
    unittest.main()
