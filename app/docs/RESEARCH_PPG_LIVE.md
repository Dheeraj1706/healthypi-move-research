# HealthyPi Move PPG research app

Custom Android app version 3.0.9+97. Application ID:
`com.protocentral.move.research`. Android launcher name: **HealthyPi Move PPG**.
It installs separately from the official app and keeps its own paired-device
settings and local history. Pair the watch in this app after installation.

## Live channels

- ECG and GSR retain their original live characteristics.
- Wrist green and finger IR work on the original BLE endpoints when the research
  service is absent.
- With the custom **3.1.1-ppg firmware**, all five PPG channels use the encrypted
  research data service: wrist green (3), wrist red (9), wrist IR (10), finger IR
  (4), finger red (11). The service is detected from GATT discovery, not inferred
  from a version string. Unknown future signal IDs are ignored.

The Live tab has a horizontally scrollable channel selector. Enable **Compare**
and choose the second channel to display two graphs on either a phone or tablet.
The graphs have eight seconds of nominal sample capacity, raw sample counts and
an adaptive PPG scale. They show sample totals, the latest raw value and inferred
missing samples after a device-counter baseline. Device indices are tracked
separately per signal; duplicates/out-of-order packets are ignored and a gap or
boot-ID change clears the previous trace rather than joining across missing data.
Counters do not prove lossless capture or exact synchronization between sensors.

One research notification subscription serves both PPG graphs. Leaving Live
stops its subscriptions. SMP recording/firmware transfers pause Live and release
its notifications, with resubscription on return. This is display functionality:
it does not add live recording/export or send remote sensor Start/Stop commands.

## Use on a phone

1. Install the provided APK and open **HealthyPi Move PPG**.
2. Disconnect any other phone/laptop application holding the watch connection.
3. Scan/pair the watch and grant the requested Bluetooth permissions. Accept
   pairing/passkey prompts on the phone and watch.
4. Open **Live**, swipe the signal selector and choose a channel. Tap the refresh
   button if pairing was rejected or a notification subscription failed.
5. Start the relevant measurement using the watch controls. Wrist red/IR depend
   on wrist SpO2 mode; finger channels need an active finger measurement and
   contact. Observe the watch's existing measurement restrictions. This app does
   not make all five channels run continuously or simultaneously.

A missing custom service gets a firmware requirement message for red/extra IR
channels. Zero/flat values are not replaced with synthetic waveforms. Verify
actual optical response and signal quality on hardware.

## Checks

Changed Dart files pass analysis. The targeted suite passes 26 tests covering
the wire decoder, uint32 values, payload slicing, malformed packets, per-channel
continuity, subscription sharing, selection races, retries, old-firmware fallback,
hidden-tab cleanup, phone/tablet layout, SMP locking and existing signal scaling.
Android APK build and signature details are recorded in the delivered build
report. No physical phone/watch BLE test has been performed.

The research APK uses the project's local Android signing fallback for personal
installation; it is not a Play Store release and cannot update the official app.
