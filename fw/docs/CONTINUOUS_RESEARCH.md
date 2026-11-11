# Continuous research acquisition — 3.1.2-continuous

This version adds phone-controlled continuous ECG, GSR/BioZ, wrist PPG and
finger PPG, with independent targets and concurrent operation in the firmware.
The Android companion is HealthyPi Move PPG 3.0.10+98.

The source and host tests support concurrent acquisition; simultaneous signal
quality, sensor-hub behavior, power consumption and 3–5 hour reliability have
not been validated on a physical watch. This is an experimental research build.

## Commands and compatibility

The encrypted research service UUIDs and data packet layout remain unchanged.
Control still uses four bytes `[1, opcode, target, request_id]`, written with
response. Target 1=ECG, 2=GSR/BioZ, 3=wrist PPG group, 4=finger PPG group.

- Opcode **4** starts a continuous target. Targets can coexist on the owning
  connection; starting an already active continuous target is idempotent.
- Opcode **2** requests Stop for that target. Stop one leaves the others active.
- Opcodes 1 (finite spot measurement) and 3 (query status) retain their meaning.
  Finite spot measurements remain exclusive.
- Status flag bit 1 (`0x02`) advertises continuous/concurrent control support.
  Bit 0 still denotes estimated time. These are status flags, separate from
  the data packet's signed-sample flag at bit 1.
- The app checks this capability before sending opcode 4. Older firmware can
  show existing waveforms but cannot use the new continuous controls.

A write acknowledgement only means queued. Match status request ID, opcode,
target and result; inspect the actual state and active mask afterward. Stop is
latched until sensor teardown reports a terminal state. Startup timeout requests
cancellation; it does not release ownership based only on elapsed time.
Disconnect and firmware update request cancellation of all remotely owned
targets. Reconnection does not automatically restart them. Watch spot-measurement
Start actions are blocked while the remote session owns targets.

## Acquisition paths

- **Wrist:** selects the existing MAX32664C
  `MAX32664C_ALGO_MODE_CONT_HR_CONT_SPO2` (0x00), rather than repeatedly
  restarting a one-shot SpO2 estimate. SpO2 completion/timeout no longer ends
  this research acquisition. The power-saving SMF and scheduled probe work
  cannot overwrite continuous mode. Stop restores the normal wrist state on
  the wrist SMF's own thread. Wrist green/red/IR samples retain IDs 3/9/10.
  Raw samples are still suppressed when the hub positively reports off-skin.
- **ECG + GSR:** the MAX30001's separate ECG/BioZ enable bits are reconciled by
  the ECG SMF thread independently. The research path bypasses the spot-check
  30-second countdown, fixed record limit and lead-placement timeout. Contact
  loss reports waiting; it does not end the session. When ECG is active, its
  one FIFO read forwards both ECG and BioZ, so GSR samples are not silently
  discarded. The polling fallback never runs a second BioZ reader alongside
  ECG. Adding/removing one channel avoids resetting the other channel's FIFO.
  FIFO empty/invalid entries are excluded from transmitted sample counts.
- **Finger:** retains the existing sensor+algorithm acquisition used by finger
  SpO2, while suppressing the application's stop on the first successful
  estimate and its contact-loss abort. It keeps sampling until Stop. Missing
  finger hardware still has a detection timeout. Red/IR retain IDs 11/4.
  Whether the installed hub itself continues delivering beyond its first
  estimate must be checked on the physical sensor.

No unbounded watch flash records are opened by these continuous paths. They
stream over BLE. The phone Live screen buffers plots and counts samples; this
change does **not** add persistent mobile recording/export or background Android
service support. Keep the app in the foreground on Live. Leaving Live requests
Stop. Chart selection and comparison do not restart acquisition.

Device times remain estimated FIFO-read-based uptime, not hardware-synchronized
ADC timestamps. Counters identify observable gaps after a baseline, not every
upstream loss. Data rates in the UI are nominal. GSR retains this checkout's
raw BioZ ADC integers; no new conductance conversion is introduced.

## Physical validation still required

Install the matching APK and OTA ZIP, reconnect and accept pairing. On Live,
start each target individually and confirm more than 30 seconds of fresh samples.
Then Start all, inspect all seven channels via the channel selector/Compare,
stop ECG while checking GSR and PPG continue, and repeat with each target.
Test contact removal/restoration, missing finger hardware, Stop during startup,
disconnect cancellation and reconnection without automatic restart.

Only after short checks pass should a long run be assessed. Use a recorder that
subscribes to the research service if storage is needed; the existing laptop
legacy recorder does not acquire every extra channel automatically. Record
duration, per-channel sample counts/gaps, boot changes, battery/temperature and
any resets. Host tests and a compiled ZIP do not establish 3–5 hour reliability.
