# Android startup fix — 3.0.11+99

The preceding 3.0.10 APK was built with an empty native Android plugin
registrant. Its compiled `registerWith(FlutterEngine)` method contained only a
return instruction. `main()` awaited native Bluetooth and local storage calls
before `runApp()`, so a missing-plugin error prevented the first Flutter screen.
Widget tests of the Live screen did not cover native Android registration.

Version 3.0.11 regenerates all nine Android native plugin registrations through
Flutter's dependency preparation. The Android build now rejects a registrant
missing Bluetooth, preferences, SQLite or path-provider initialization. Run
`flutter pub get` before building; use the normal `flutter build apk --release`
flow. Do not reuse stale generated files with an unchecked `--no-pub` build.

The entry point also mounts a startup UI before initialization. It shows progress
while preparing Bluetooth/local data, and displays the actual error with Retry
if initialization fails. Main data screens remain behind successful preparation,
preserving real-data filtering. It does not clear user storage or require an
uninstall. App identity and signing certificate match the previous research APK.

Validation includes three bootstrap widget tests and the preceding 33 targeted
Live/protocol/controller tests; changed-file analysis; a negative Gradle test
with an empty registrant; and release artifact checks for native registration,
identity, signing and alignment. No connected phone was available for a physical
cold-start test. A successful build is not a physical phone/watch test.

Firmware 3.1.2-continuous is unchanged and does not need to be reinstalled for
this Android startup fix.
