# Continuous Live controls — app 3.0.10+98

Use with firmware **3.1.2-continuous**. The app ID remains
`com.protocentral.move.research` and the launcher remains HealthyPi Move PPG.

1. Install the APK, update the watch using the supplied OTA ZIP, then reconnect.
2. Open Live and accept Bluetooth pairing if asked.
3. Tap **Start all** to request ECG, GSR, wrist PPGs and finger PPGs together.
   The phone checks firmware capability; old firmware cannot silently fall back
   to a 30-second spot check.
4. Tap **Sensors** for independent Start/Stop and actual per-target status.
   Waiting for contact is different from streaming; command acceptance is not
   proof that usable samples are arriving.
5. Select any of seven waveforms and optionally Compare two. All seven are
   subscribed through one encrypted data characteristic while Live is active.
   Changing charts does not restart sensor acquisition.
6. Tap Stop all or stop an individual group. Wrist PPGs share one optical mode;
   finger PPGs share another. You cannot independently stop red while keeping
   IR on the same sensor. Stopping the wrist research group restores normal
   wrist HR/green PPG operation.

Keep the app foreground on Live. Leaving Live requests cancellation, and link
loss also requests cancellation in firmware. Reconnection needs an explicit
Start. This version has no background acquisition service or new persistent
mobile recording/export; Live plots and sample counts are not stored sessions.

The watch still needs proper electrode/optical contact. Continuous operation
and simultaneous signal quality have not been tested on physical hardware here.
See `fw/docs/CONTINUOUS_RESEARCH.md` in the project for implementation and test
limits. The research APK is a release-mode build with a local debug certificate.
