"""BLE acquisition worker for the research UI. All SQLite work stays on its thread."""
import asyncio
import contextlib
import math
import queue
import struct
import threading
import time

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
import hpi_ble as H
from research_storage import PacketBuilder, SessionStore


class Capture:
    def __init__(self, db_path, selected, seconds=0, note="", demo=False,
                 store_factory=SessionStore, retry_delay=2.0):
        self.db_path, self.selected = db_path, list(selected)
        self.seconds, self.note, self.demo = seconds, note, demo
        self.store_factory = store_factory
        self.retry_delay = retry_delay
        self.interruptions = 0
        self.events = queue.SimpleQueue()
        self.plot_packets = queue.Queue(maxsize=1000)
        self.stop_requested = threading.Event()
        self.thread = None
        self.counts = {}
        self.malformed = {}
        self.display_drops = 0

    def start(self):
        if self.thread is not None:
            raise RuntimeError("Capture can only start once")
        if not self.selected:
            raise ValueError("Select at least one signal")
        if not math.isfinite(self.seconds) or self.seconds < 0:
            raise ValueError("Duration must be zero or a positive finite number")
        known = set(H.WAVEFORMS_BY_KEY) | {s[0] for s in H.SCALAR_SIGNALS.values()}
        if set(self.selected) - known:
            raise ValueError("Unknown selected signal")
        self.thread = threading.Thread(target=self._worker, daemon=False)
        self.thread.start()

    def stop(self):
        self.stop_requested.set()

    def _worker(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("done", None))

    def _display(self, packet):
        try:
            self.plot_packets.put_nowait(packet)
        except queue.Full:
            self.display_drops += 1  # storage already happened; display only

    async def _run(self):
        store = self.store_factory(self.db_path)
        sid = None
        status = "error"
        self._accepting = False
        self._callback_error = None
        builder = PacketBuilder()
        deadline = None
        target_address = None
        retry_attempt = 0

        def expired():
            return deadline is not None and time.monotonic() >= deadline

        async def operation(awaitable):
            """Keep Stop and total duration effective during scan/connect/subscribe."""
            task = asyncio.ensure_future(awaitable)
            try:
                while not task.done():
                    if self.stop_requested.is_set() or expired():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await task
                        return None
                    await asyncio.sleep(.05)
                return await task
            finally:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

        def save(key, values, rate=None, raw=b""):
            if not self._accepting:
                return
            try:
                packet = builder.make(key, values, rate, raw)
                store.append(sid, packet)
            except Exception as exc:
                self._callback_error = exc
                self.stop_requested.set()
                return
            self.counts[key] = self.counts.get(key, 0) + len(values)
            self._display(packet)

        async def wait_recording(disconnected=None):
            last_flush = time.monotonic()
            while not self.stop_requested.is_set():
                if disconnected and disconnected.is_set():
                    return "disconnected"
                if expired():
                    return "completed"
                now = time.monotonic()
                if now - last_flush >= 1:
                    store.flush()
                    self.events.put(("counts", dict(self.counts)))
                    last_flush = now
                await asyncio.sleep(0.05)
            if self._callback_error:
                raise self._callback_error
            return "stopped"

        try:
            if self.demo:
                sid = store.start(self.selected, source="synthetic-demo", note=self.note)
                self.events.put(("session", sid))
                self.events.put(("status", "DEMO: synthetic signals, not watch measurements"))
                builder = PacketBuilder()
                deadline = time.monotonic() + self.seconds if self.seconds else None
                self._accepting = True

                async def generate():
                    indices = {}
                    while True:
                        for key in self.selected:
                            if key in H.WAVEFORMS_BY_KEY:
                                sig = H.WAVEFORMS_BY_KEY[key]
                                count = max(1, round(sig.rate_hz / 5))
                                first = indices.get(key, 0)
                                values = [int(10000 + 500 * math.sin(2 * math.pi * 1.1 *
                                          (first + i) / sig.rate_hz)) for i in range(count)]
                                indices[key] = first + count
                                raw = struct.pack("<" + ("i" if sig.sample_fmt == "i32" else "I") * count, *values)
                                save(key, values, sig.rate_hz, raw)
                            else:
                                value = {"hr": 66, "temp": 33.4, "battery": 80,
                                         "spo2": {"spo2": 98, "pulse_rate": 66}}[key]
                                save(key, [value])
                        await asyncio.sleep(0.2)

                producer = asyncio.create_task(generate())
                try:
                    status = await wait_recording()
                finally:
                    producer.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await producer
                return

            while not self.stop_requested.is_set() and not expired():
                disconnected = asyncio.Event()
                client = None
                subscriptions = []
                try:
                    self.events.put(("status", "Scanning / reconnecting (up to 15 seconds)..."))
                    dev = await operation(BleakScanner.find_device_by_filter(
                        lambda d, a: ((d.address == target_address) if target_address else
                                      H.DEVICE_NAME in (d.name or "").lower()), timeout=15))
                    if self.stop_requested.is_set() or expired():
                        break
                    if not dev:
                        raise BleakError("Watch not found. Retrying; Stop cancels retries.")
                    # Reconnect to this watch, not any other nearby HealthyPi unit.
                    target_address = dev.address
                    self.events.put(("status", "Connecting / pairing. Check Windows and the watch for a passkey."))
                    client = BleakClient(dev, pair=True,
                                         disconnected_callback=lambda c, event=disconnected: event.set())
                    await operation(client.connect())
                    if self.stop_requested.is_set() or expired():
                        break
                    if sid is None:
                        sid = store.start(self.selected, device=dev.address, note=self.note)
                        builder = PacketBuilder()
                        deadline = time.monotonic() + self.seconds if self.seconds else None
                        self.events.put(("session", sid))
                    else:
                        builder.connection_segment += 1
                    store.event(sid, time.monotonic() - builder.started, "connected",
                                "connection segment %d" % builder.connection_segment)
                    self._accepting = True
                    chars = {c.uuid.lower(): c for service in client.services
                             for c in service.characteristics}
                    subscriptions = []
                    routes = [(sig.uuid, key, sig.rate_hz, sig.decode)
                              for key, sig in H.WAVEFORMS_BY_KEY.items() if key in self.selected]
                    routes += [(uuid, key, None, decoder)
                               for uuid, (key, label, unit, decoder) in H.SCALAR_SIGNALS.items()
                               if key in self.selected]
                    subscribed_keys = set()
                    for uuid, key, rate, decoder in routes:
                        if self.stop_requested.is_set():
                            break
                        if uuid not in chars or key in subscribed_keys:
                            continue
                        if not set(chars[uuid].properties) & {"notify", "indicate"}:
                            continue

                        def make_callback(key, rate, decoder, segment):
                            def callback(sender, data):
                                if segment != builder.connection_segment:
                                    return
                                try:
                                    raw = bytes(data)
                                    decoded = decoder(raw)
                                    if decoded is None:
                                        raise ValueError("empty/invalid reading")
                                    values = decoded if rate else [decoded]
                                    # Invalid JSON numbers must not poison an entire session.
                                    import json
                                    json.dumps(values, allow_nan=False)
                                except (ValueError, IndexError, OverflowError, TypeError):
                                    self.malformed[key] = self.malformed.get(key, 0) + 1
                                    return
                                save(key, values, rate, raw)
                            return callback
                        try:
                            await operation(client.start_notify(chars[uuid], make_callback(
                                key, rate, decoder, builder.connection_segment)))
                            if self.stop_requested.is_set() or expired():
                                break
                            subscriptions.append(uuid)
                            subscribed_keys.add(key)
                        except Exception as exc:
                            self.events.put(("notice", "%s subscription failed: %s" % (key, exc)))
                            if disconnected.is_set():
                                raise BleakError("Disconnected while subscribing")
                    missing = set(self.selected) - subscribed_keys
                    if missing:
                        self.events.put(("notice", "Unavailable subscriptions: " + ", ".join(sorted(missing))))
                    if not subscriptions:
                        if self.stop_requested.is_set():
                            status = "stopped"
                            return
                        if expired():
                            status = "completed"
                            return
                        raise BleakError("No channels subscribed; retrying")
                    self.events.put(("status", "Recording on laptop. Start the required measurement on the watch."))
                    status = await wait_recording(disconnected)
                    if status != "disconnected":
                        break
                except (BleakError, OSError, asyncio.TimeoutError) as exc:
                    if self._callback_error:
                        raise self._callback_error
                    self.events.put(("notice", "Bluetooth attempt failed: %s" % exc))
                    status = "disconnected"
                finally:
                    self._accepting = False
                    if sid:
                        store.flush()
                        if status == "disconnected":
                            self.interruptions += 1
                            store.event(sid, time.monotonic() - builder.started, "connection_gap",
                                        "Reception interrupted; missing samples cannot be recovered by reconnecting.")
                    if client:
                        # disconnect() removes subscriptions. Bound cleanup so a
                        # dead Windows session cannot prevent retries indefinitely.
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(client.disconnect(), timeout=5)
                if self._callback_error:
                    raise self._callback_error
                if self.stop_requested.is_set() or expired():
                    break
                retry_attempt += 1
                self.events.put(("notice", "Disconnected/unavailable. Auto-retry #%d; gaps are retained." % retry_attempt))
                self.events.put(("status", "Reconnecting automatically. Stop cancels retries."))
                retry_at = time.monotonic() + self.retry_delay
                while time.monotonic() < retry_at and not self.stop_requested.is_set() and not expired():
                    await asyncio.sleep(.05)
            if self._callback_error:
                raise self._callback_error
            status = "completed" if expired() else "stopped"
            if self.interruptions:
                status += "_with_gaps"

        except Exception:
            status = "error"
            raise
        finally:
            self._accepting = False
            try:
                if sid:
                    store.finish(sid, status)
                    self.events.put(("saved", dict(id=sid, status=status, counts=dict(self.counts),
                                                  malformed=dict(self.malformed),
                                                  display_drops=self.display_drops,
                                                  interruptions=self.interruptions)))
                elif self.stop_requested.is_set():
                    self.events.put(("status", "Stopped before a recording session started."))
            finally:
                store.close()
