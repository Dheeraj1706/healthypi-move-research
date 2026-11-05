"""
Probe the v2.x CMD service: does REC_CONFIGURE/START actually wake the sensors,
and does live BLE notify traffic appear while a recording is running?

Sequence: baseline count (silent) -> configure+start -> count -> stop -> count.
"""
import asyncio
import os
import sys

from bleak import BleakScanner, BleakClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpi_ble as H
import hpi_control as C

WINDOW_S = 10.0


async def main():
    print("Scanning ...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: bool(d.name) and H.DEVICE_NAME.lower() in d.name.lower(),
        timeout=15.0)
    if dev is None:
        print("Device not found.")
        return 1

    counts = {}

    def wf_cb(key):
        def handler(_h, data):
            c = counts.setdefault(key, {"pkts": 0, "samples": 0})
            c["pkts"] += 1
            c["samples"] += len(data) // 4
        return handler

    responses = []

    def rsp_cb(_h, data):
        parsed = C.parse_response(bytes(data))
        responses.append(parsed)
        print("    <- RSP %s" % parsed)

    def snapshot():
        return {k: dict(v) for k, v in counts.items()}

    def delta(before, label):
        print("\n  %s (%.0f s window):" % (label, WINDOW_S))
        any_data = False
        for sig in H.WAVEFORM_SIGNALS:
            b = before.get(sig.key, {"samples": 0, "pkts": 0})
            a = counts.get(sig.key, {"samples": 0, "pkts": 0})
            d_pkts = a["pkts"] - b["pkts"]
            d_smp = a["samples"] - b["samples"]
            rate = d_smp / WINDOW_S
            if d_smp:
                any_data = True
            print("    %-12s pkts=%-5d samples=%-6d  %6.1f Hz (nominal %d)"
                  % (sig.key, d_pkts, d_smp, rate, sig.rate_hz))
        if not any_data:
            print("    (no waveform data at all)")

    async with BleakClient(dev.address) as client:
        print("Connected %s  MTU=%s" % (dev.address, client.mtu_size))

        available = {c.uuid.lower() for s in client.services
                     for c in s.characteristics}
        if C.UUID_CMD_TX not in available:
            print("CMD service absent -- this firmware is v3.x. Stop here.")
            return 1
        print("CMD service present (firmware v2.x protocol).")

        for sig in H.WAVEFORM_SIGNALS:
            try:
                await client.start_notify(sig.uuid, wf_cb(sig.key))
            except Exception as exc:
                print("  ! %s subscribe failed: %s" % (sig.key, exc))
        try:
            await client.start_notify(C.UUID_CMD_RX, rsp_cb)
        except Exception as exc:
            print("  ! CMD RX subscribe failed: %s" % exc)

        async def write(frame, label):
            print("\n  -> %s : %s" % (label, frame.hex()))
            try:
                await client.write_gatt_char(C.UUID_CMD_TX, frame, response=False)
            except Exception as exc:
                print("     write failed: %s" % exc)
            # cmd_thread sleeps 1 s between commands in v2.1.1 -- pace writes.
            await asyncio.sleep(1.5)

        # --- 1. Baseline -------------------------------------------------
        base = snapshot()
        await asyncio.sleep(WINDOW_S)
        delta(base, "BASELINE (no command sent)")

        await write(C.frame_get_status(), "REC_GET_STATUS")

        # --- 2. Configure + start ----------------------------------------
        mask = C.REC_SIGNAL_GSR | C.REC_SIGNAL_PPG_WRIST | C.REC_SIGNAL_IMU_ACCEL
        await write(C.frame_configure(duration_s=120, signal_mask=mask,
                                      decimation=1),
                    "REC_CONFIGURE dur=120 mask=%s" % C.names_from_mask(mask))
        await write(C.frame_start(), "REC_START")
        await write(C.frame_get_status(), "REC_GET_STATUS")

        during = snapshot()
        await asyncio.sleep(WINDOW_S)
        delta(during, "WHILE RECORDING")

        # --- 3. Stop ------------------------------------------------------
        await write(C.frame_stop(), "REC_STOP")
        await write(C.frame_get_status(), "REC_GET_STATUS")

        after = snapshot()
        await asyncio.sleep(WINDOW_S)
        delta(after, "AFTER STOP")

        for sig in H.WAVEFORM_SIGNALS:
            try:
                await client.stop_notify(sig.uuid)
            except Exception:
                pass

    print("\n%d command response(s) received." % len(responses))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
