"""Read Device Information Service + probe which live signals actually flow."""
import asyncio
import os
import sys

from bleak import BleakScanner, BleakClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpi_ble as H

DIS = {
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Revision",
}
GAP_NAME = "00002a00-0000-1000-8000-00805f9b34fb"


async def main():
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: bool(d.name) and H.DEVICE_NAME.lower() in d.name.lower(),
        timeout=15.0)
    if dev is None:
        print("Device not found.")
        return

    async with BleakClient(dev.address) as client:
        print("Connected %s  MTU=%s\n" % (dev.address, client.mtu_size))
        for uuid, label in DIS.items():
            try:
                val = await client.read_gatt_char(uuid)
                print("  %-20s %s" % (label + ":", val.decode(errors="replace")))
            except Exception as exc:
                print("  %-20s <%s>" % (label + ":", exc))
        try:
            val = await client.read_gatt_char(GAP_NAME)
            print("  %-20s %s" % ("Device Name:", val.decode(errors="replace")))
        except Exception:
            pass

        print("\nProbing live waveform characteristics for 12 s ...")
        counts = {}

        def cb(key):
            def handler(_h, data):
                c = counts.setdefault(key, {"pkts": 0, "bytes": 0, "first": None})
                c["pkts"] += 1
                c["bytes"] += len(data)
                if c["first"] is None:
                    c["first"] = bytes(data)
            return handler

        subs = []
        for sig in H.WAVEFORM_SIGNALS:
            try:
                await client.start_notify(sig.uuid, cb(sig.key))
                subs.append(sig.uuid)
            except Exception as exc:
                print("  ! %s subscribe failed: %s" % (sig.key, exc))

        # Scalars, including the 0x2A6E temperature this build actually exposes.
        for uuid, (key, label, _u, dec) in H.SCALAR_SIGNALS.items():
            try:
                await client.start_notify(uuid, cb(key))
                subs.append(uuid)
            except Exception:
                pass

        await asyncio.sleep(12)
        for uuid in subs:
            try:
                await client.stop_notify(uuid)
            except Exception:
                pass

        print("\n%-14s%8s%10s   %s" % ("signal", "pkts", "bytes", "first payload (hex)"))
        for sig in H.WAVEFORM_SIGNALS:
            c = counts.get(sig.key)
            if c:
                print("%-14s%8d%10d   %s"
                      % (sig.key, c["pkts"], c["bytes"], c["first"][:16].hex()))
            else:
                print("%-14s%8d%10d   %s" % (sig.key, 0, 0, "-- silent --"))
        for uuid, (key, label, _u, dec) in H.SCALAR_SIGNALS.items():
            c = counts.get(key)
            if c:
                try:
                    decoded = dec(c["first"])
                except Exception as exc:
                    decoded = "decode error: %s" % exc
                print("%-14s%8d%10d   %s  -> %s"
                      % (key, c["pkts"], c["bytes"], c["first"].hex(), decoded))


if __name__ == "__main__":
    asyncio.run(main())
