# HealthyPi Move — BLE Data Acquisition Specification

Derived by reading the firmware source at
[Protocentral/healthypi-move-fw](https://github.com/Protocentral/healthypi-move-fw)
(`app/src/ble_module.c`, `app/src/data_module.c`, `app/src/sm/smf_ecg_bioz.c`).
Device advertises as **`healthypi move`** (`app/prj.conf:10`).

## 1. Signal inventory

### 1.1 Waveform signals (continuous, custom services)

| Signal | Service UUID | Characteristic UUID | Rate | Sample format | Batch | Source |
|---|---|---|---|---|---|---|
| ECG | `00001122-0000-1000-8000-00805f9b34fb` | `00001424-0000-1000-8000-00805f9b34fb` | 128 Hz | `int32` LE | 8 | MAX30001 |
| GSR / BioZ (EDA) | `00001122-…` (same) | `babe4a4c-7789-11ed-a1eb-0242ac120002` | 32 Hz | `int32` LE | var | MAX30001 BioZ |
| PPG wrist (green) | `cd5c7491-4448-7db8-ae4c-d1da8cba36d0` | `cd5c1525-4448-7db8-ae4c-d1da8cba36d0` | 25 Hz | `uint32` LE | var | MAX32664C |
| PPG finger (IR) | `cd5c7491-…` (same) | `cd5ca86f-4448-7db8-ae4c-d1da8cba36d0` | 100 Hz | `uint32` LE | var | MAX32664D |

All four are `READ | NOTIFY`, permission `BT_GATT_PERM_READ` (**not** encrypted).

### 1.2 Scalar / event signals (standard SIG services)

| Signal | Service | Characteristic | Mode | Notes |
|---|---|---|---|---|
| Heart rate | HRS `0x180D` | `0x2A37` | notify | Published on `hr_chan` when `hr_ready_flag` set |
| Battery | BAS `0x180F` | `0x2A19` | notify | Percent |
| SpO₂ | PLX `0x1822` | `0x2A5E` spot-check | notify, **encrypted read** | IEEE-11073 SFLOAT; only on a *completed* spot check |
| Skin temperature | HTS `0x1809` | `0x2A1C` | **indicate**, encrypted read | Rate-limited: ≥0.1 °C change or 1 per 30 s |

### 1.3 Not available over live BLE

**Accelerometer and gyroscope are not exposed on any GATT characteristic.** No
IMU notify path exists in `ble_module.c`. Motion data reaches the phone only
through the *HealthyPi Health Store* — an MCUmgr group (id `0x1000`, see
`docs/HPI_HS_API.md` in the firmware) used for post-hoc file sync of on-watch
recordings, not for live streaming. Getting live IMU requires a firmware change.

## 2. Packet format

Every waveform notification is a **bare packed array of 32-bit little-endian
samples**. From `ble_ecg_notify()` (`ble_module.c:288`):

```c
for (int i = 0; i < len; i++) {
    out_data[i*4]     = (uint8_t)(ecg_data[i]);
    out_data[i*4 + 1] = (uint8_t)(ecg_data[i] >> 8);
    out_data[i*4 + 2] = (uint8_t)(ecg_data[i] >> 16);
    out_data[i*4 + 3] = (uint8_t)(ecg_data[i] >> 24);
}
bt_gatt_notify(NULL, &hpi_ecg_gsr_service.attrs[2], &out_data, len * 4);
```

Therefore: `n_samples = len(payload) / 4`, and

> **There is no header, no timestamp, and no sequence number in the payload.**

This is the single most important finding for this project. Consequences:

1. **Packet loss is undetectable from the payload alone.** The firmware itself
   drops ECG batches when the BLE TX pool is empty — `ble_module.c:298` counts
   these and logs "ECG notify dropped %u batches". A receiver sees only a gap it
   cannot measure.
2. **Timestamps must be reconstructed on the host.** Our recorder stamps each
   notification with wall-clock and monotonic arrival time, and assigns a
   cumulative sample index; nominal time is `index / rate_hz`. Arrival time and
   index-derived time drift apart exactly in proportion to lost samples, which
   is what makes loss *estimable* even before the firmware change.
3. Cross-signal synchronization is only as good as BLE arrival jitter until
   device-side timestamps are added.

## 3. What gates the data flow

Two independent gates must both be open:

**Gate A — BLE send enable.** `data_module.c:80` declares
`static bool settings_send_ble_enabled = true;` and it is never assigned
anywhere else. So this gate is **permanently open** — no BLE command is needed
to enable transmission.

**Gate B — sensor sampling active.** This is the real gate. Sampling runs off
Zephyr timers started by the sensor state machine (`smf_ecg_bioz.c`):

```c
#define ECG_SAMPLING_INTERVAL_MS  125
#define BIOZ_SAMPLING_INTERVAL_MS 62   /* ~16 Hz poll for 32 SPS BioZ */
```

with `ecg_start_sampling()` / `bioz_start_sampling()` (or a DRDY interrupt when
`CONFIG_MAX30001_TRIGGER` is set). These are entered from the watch's own UI
flow — the user opens the ECG measurement screen. On entering
`st_ecg_idle_entry()` the timers stop and `hw_max30001_ecg_disable()` runs.

**So: stock firmware streams live data only while a measurement is active on the
watch.** There is no BLE-writable Start/Stop control characteristic — the
legacy framed command service (SOF `0x0A 0xFA`) was removed, per the comment in
`ble_module.c`.

Useful existing entry points for a firmware modification:

- `gsr_background_start()` / `gsr_background_stop()` (`smf_ecg_bioz.c:869`) —
  already a clean, idempotent, atomically-guarded start/stop pair.
- The ECG SMF is event-driven (`k_event_post(&ecg_evt, …)`), so a command
  handler can post the same events the UI posts.

## 4. Proposed acquisition method

**Phase 1 (no firmware change) — works today:**
Subscribe to the four waveform characteristics plus HR/battery/SpO₂/temp; start
a measurement on the watch by hand; host assigns timestamps and sample indices.
Implemented in `pc_tools/record.py` (Python + `bleak`) and mirrored in the
Flutter app with `flutter_blue_plus`. Sufficient for signal validation and for
the storage-architecture benchmark, which is the project's research core.

**Phase 2 (firmware change) — needed for research-grade capture:**

1. Add a **control characteristic** (write, in the ECG/GSR service) with a small
   command set: `0x01 START <signal_mask>`, `0x02 STOP <signal_mask>`,
   `0x03 GET_STATUS`. Handler calls `gsr_background_start()` and posts the ECG
   SMF events, bypassing the UI requirement.
2. Add an **8-byte packet header** to every waveform notify:
   `uint16 seq | uint16 n_samples | uint32 device_ticks_ms`. Costs 8 of 244
   usable MTU bytes and makes loss countable and cross-signal sync measurable.
3. Optionally expose the IMU on a new characteristic for live motion data.

Item 2 is what turns "we collected data" into "we can prove the data is
complete and synchronized" — deliverable (8) of the project brief.

## 5. Security posture of the stock link

The four waveform characteristics use `BT_GATT_PERM_READ` — **plaintext, no
pairing or encryption required**. Only the SpO₂ and temperature characteristics
use `BT_GATT_PERM_READ_ENCRYPT`. Raw ECG/EDA/PPG is therefore readable by any
BLE central in range. Our application-layer encryption (project deliverable 6)
addresses data at rest and in transit to the cloud, but the *link itself* is
unprotected unless the firmware is changed to require encrypted permissions on
the waveform characteristics — worth stating explicitly in the final report.
