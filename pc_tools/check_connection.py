"""Connect without subscribing, to isolate link lifetime from sensor recording."""
import asyncio
import logging
import time
from pathlib import Path
from bleak import BleakClient, BleakScanner

async def main():
    log = Path(__file__).resolve().parents[1] / 'data' / 'idle_connection.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log, filemode='w', level=logging.DEBUG,
                        format='%(asctime)s %(name)s %(message)s')
    print('Scanning for the watch...', flush=True)
    dev = await BleakScanner.find_device_by_filter(
        lambda d, a: 'healthypi move' in (d.name or '').lower(), timeout=15)
    if dev is None:
        print('Watch not found.'); return
    closed = asyncio.Event()
    started = time.monotonic()
    expected_close = False
    def disconnected(client):
        if not expected_close:
            print('UNEXPECTED disconnect after %.1f seconds' %
                  (time.monotonic() - started), flush=True)
        closed.set()
    async with BleakClient(dev, pair=True, disconnected_callback=disconnected) as client:
        started = time.monotonic()
        print('Connected. No sensor subscriptions or file recording.', flush=True)
        for step in range(9):
            try:
                await asyncio.wait_for(closed.wait(), 10)
                break
            except asyncio.TimeoutError:
                print('Still connected: %.1f seconds' %
                      (time.monotonic() - started), flush=True)
        else:
            print('PASS: Bluetooth link stayed connected for 90 seconds.', flush=True)
        expected_close = True
    print('Diagnostic log:', log)

if __name__ == '__main__':
    asyncio.run(main())
