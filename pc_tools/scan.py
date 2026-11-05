"""Scan for the HealthyPi Move and dump its full GATT table."""
import asyncio
import sys

from bleak import BleakScanner, BleakClient

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
import hpi_ble as H


async def main():
    print("Scanning 10 s for BLE devices...\n")
    devices = await BleakScanner.discover(timeout=10.0)
    if not devices:
        print("No BLE devices found. Is Bluetooth on?")
        return

    target = None
    for d in sorted(devices, key=lambda x: x.address):
        name = d.name or "(no name)"
        mark = ""
        if d.name and H.DEVICE_NAME.lower() in d.name.lower():
            target = d
            mark = "   <-- HealthyPi Move"
        print(f"  {d.address}  {name}{mark}")

    if target is None:
        print(f"\nNo device named '{H.DEVICE_NAME}' found.")
        print("Wake the watch, make sure it is not connected to the phone app, retry.")
        return

    print(f"\nConnecting to {target.address} ...")
    async with BleakClient(target.address) as client:
        print(f"Connected. MTU = {client.mtu_size}\n")
        print("GATT table:")
        for service in client.services:
            print(f"\n[Service] {service.uuid}  {service.description}")
            for ch in service.characteristics:
                props = ",".join(ch.properties)
                known = ""
                if ch.uuid.lower() in H.WAVEFORMS_BY_UUID:
                    s = H.WAVEFORMS_BY_UUID[ch.uuid.lower()]
                    known = f"  <== {s.label} @ {s.rate_hz} Hz"
                elif ch.uuid.lower() in H.SCALAR_SIGNALS:
                    known = f"  <== {H.SCALAR_SIGNALS[ch.uuid.lower()][1]}"
                print(f"   [Char] {ch.uuid}  ({props}){known}")


if __name__ == "__main__":
    asyncio.run(main())
