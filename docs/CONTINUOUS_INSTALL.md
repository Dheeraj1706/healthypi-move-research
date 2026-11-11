# HealthyPi Move continuous research build

Matching pair: Android app 3.0.10+98 and watch firmware 3.1.2-continuous.

1. Install `app/HealthyPi_Move_Continuous_3.0.10.apk` on the phone. It updates
   the previous HealthyPi Move PPG research app (same ID and signing certificate).
2. In the phone firmware updater, choose the local firmware ZIP via Advanced
   options / Select firmware file: `firmware/HealthyPi_Move_3.1.2_Continuous_OTA.zip`.
   This is the installable OTA ZIP, containing signed application and radio images.
3. After the watch reboots, reconnect, open Live and accept pairing if requested.
   Tap Start all, or Sensors for independent ECG/GSR/wrist/finger Start/Stop.
4. Keep the app foreground on Live. Chart selection/Compare do not restart the
   sensors. Stop all stops the research session; leaving Live or disconnecting
   also requests cancellation. Normal wrist HR/green PPG may continue after Stop.
5. Confirm each channel receives fresh samples for longer than 30 seconds,
   then test all together. Check that stopping one leaves the others running.

Implemented continuous mode bypasses ECG/GSR spot durations and the application's
optical completion stop. Wrist uses continuous HR+SpO2 mode. Finger retains the
existing sensor+algorithm mode without the application's completion shutdown.

This is an experimental build. No watch was flashed or physically tested here.
Concurrent signal quality, the finger hub's sustained output, battery/runtime,
bootloader compatibility on your installed watch, and 3–5 hour reliability remain
unverified. Host image signature checks verify against the configured repository
key, not against a key read from your physical watch. App static RAM use is
446416/450560 bytes (99.08%); runtime stability must be checked on hardware.

Live shows waveforms and counters; it does not save recordings or add background
Android recording. Existing laptop legacy capture does not automatically record
all extra research channels. Continuous research paths do not open unbounded
watch flash records.

The separate Continuous Sources ZIP contains source, not watch firmware. Do not
select the source ZIP in the updater. See the app/fw continuous documentation
and CONTINUOUS_BUILD_REPORT.json files for implementation and validation details.
