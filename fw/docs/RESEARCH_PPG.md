# Additional live PPG channels

This change extends the existing custom research service in this checkout. It
does not change the original vendor waveform characteristics. The new channels
are sent on encrypted research DATA notifications, UUID
`a17e0003-4d52-4f56-9100-524553454152`.

| Signal ID | Python name | Source array | Nominal rate |
|---|---|---|---|
| 3 (existing) | ppg_wrist | wrist raw_green | 25 Hz |
| 4 (existing) | ppg_finger | finger raw_ir | 100 Hz |
| 9 (new) | ppg_wrist_red | wrist raw_red | 25 Hz |
| 10 (new) | ppg_wrist_ir | wrist raw_ir | 25 Hz |
| 11 (new) | ppg_finger_red | finger raw_red | 100 Hz |

IDs 1 through 8 and all control target IDs retain their previous meanings.
The packet version stays 1: the layout is unchanged, with appended signal IDs.
Old research decoders must be updated to accept the new IDs. A client handling
this version should ignore unknown signal IDs rather than label them incorrectly.
The supplied reference decoder in `tools/research_protocol.py` understands all
11 signals. The project's Python GUI and Flutter app still need integration
with this custom service before they can show or save the additional channels.

All five PPG streams carry unsigned little-endian 32-bit driver values with a
16-byte research header. The current driver assembles optical FIFO words and
right-shifts them by four bits; this patch forwards those existing values without
additional filtering, conversion or invented replacements. These are optical
waveforms, not separate heart-rate or SpO2 results.

The wrist red/IR packets reuse the green batch's producer stamp. Finger red
reuses the finger IR batch's stamp. Channels from the same sensor batch therefore
have the same boot ID, first sample index, sample count and estimated uptime.
Counters are allocated once per source batch before queuing, so a dropped source
batch advances all its channels. Individual BLE sends can still fail separately;
track continuity per signal and join channels by boot ID and sample index, not
by notification arrival order. ATT-MTU fragmentation applies the same index/time
offsets to each channel. No extra sensor queue copies or sample arrays are added.

The existing sensor modes, skin-contact gates, finite measurement durations and
nominal rates are unchanged. Red/IR validity and LED activity depend on the hub
mode and must be checked on the watch. In particular, zero values must not be
presented as evidence of a valid active optical channel. Wrist and finger sensors
are not made exactly synchronized by sharing stamps within their own batches.

Bandwidth increases: wrist PPG has three research streams and finger PPG has
two. At the nominal rates, the additional raw sample bytes alone total 600
bytes/s when both sources are active; headers, BLE overhead and legacy streams
are extra. A larger negotiated MTU reduces overhead. Check gaps and notification
failures under actual load, particularly at MTU 23. Failed sends are not retried.

## Validation

Reference Python protocol tests cover the new channel names/rates, unsigned
values, multiple samples, scalar validation, flags and per-channel gap tracking.
The host C codec test covers the actual encoder, new IDs, unsigned values,
small-MTU offsets, invalid IDs and unchanged legacy packet behavior.

A successful host test is not a Nordic firmware build or a hardware test. The
delivery README records whether a target update image was actually produced.
Only a generated, compatible `dfu_application.zip` is an installable OTA package;
a source overlay ZIP must not be selected in the watch updater. Preserve the
installed bootloader's signing key and select an accepted firmware image version
when producing the target build. Do not replace the watch bootloader just to
make a source build installable.

Hardware acceptance: pair/encrypt, subscribe to research DATA, start the required
measurement, verify IDs 3/9/10 for wrist and 4/11 for finger, inspect optical
response and values in each mode, compare indices across channels, then record
long enough to measure throughput and gaps. Also confirm original phone-app
streaming and measurement controls still behave correctly.
