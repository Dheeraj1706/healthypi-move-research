# HealthyPi Move research platform

Custom HealthyPi Move firmware, a Flutter Android app with additional live PPG
channels, and Windows laptop tools for physiological data recording and analysis.
This repository contains complete source snapshots, not Git submodule links.

The firmware and phone app extend ProtoCentral's projects. Their upstream
commits, licenses and the exact changed files are recorded below and in
[`docs/SOURCE_PROVENANCE.json`](docs/SOURCE_PROVENANCE.json). The custom research
features have been built and checked with automated tests; they have not yet
been validated as a complete system on a physical watch and phone.

## Repository contents

| Directory | Contents |
|---|---|
| [`fw/`](fw/) | Firmware source, research control/status/data service, protocol codec and tests |
| [`app/`](app/) | Flutter companion app and additional live PPG displays |
| [`pc_tools/`](pc_tools/) | BLE scan/capture, encrypted research recorder, SQLite/CSV and signal analysis |
| [`docs/`](docs/) | BLE specification, laptop implementation notes, source inventory and build reports |
| [`patches/`](patches/) | App and firmware changes relative to the recorded upstream commits |
| [`setup_nordic.ps1`](setup_nordic.ps1) | Windows Nordic SDK installation/build helper; external tooling and local signing keys are required |

## Implemented work

**Firmware, custom version `3.1.1-ppg`:**

- An encrypted research BLE service with measurement control, state updates,
  boot ID, estimated device uptime and sample indices.
- Three additional optical channels: wrist red, wrist infrared and finger red.
  The existing wrist green and finger infrared streams are retained.
- Channels from each optical sensor batch share its producer index/timestamp.
- Existing measurement state machines, contact checks and legacy BLE layouts
  are retained. Continuous acquisition of every sensor is not implemented.

**Flutter Android app, version `3.0.9+97`:**

- Live selection of ECG, GSR, wrist green/red/IR and finger IR/red PPG.
- Two-graph Compare mode on phones and tablets, adaptive PPG scaling, sample
  totals, latest values, inferred gaps, subscription errors and retry.
- One shared encrypted PPG subscription with per-channel decoding/continuity.
- Live subscriptions stop when leaving the Live tab and pause during SMP work.
- Legacy endpoint fallback for the original PPG channels when the custom service
  is absent. Extra channels display a firmware requirement message.
- Separate Android identity: `com.protocentral.move.research`, launcher name
  **HealthyPi Move PPG**, so it can coexist with the official application.

**Laptop tools:**

- Signal selection, capture duration, Start/Stop, live plots and reconnect events.
- Host arrival timestamps, estimated per-sample times and session management.
- Windows-user DPAPI encryption of packet contents in SQLite and plaintext CSV
  export, plus signal-rate/gap/PPG validation tools.

The laptop recorder still uses the original live BLE endpoints. Its GUI has not
been integrated with the new research protocol or the extra PPG channels.

## Current validation and remaining work

| Area | Recorded status |
|---|---|
| Firmware reference protocol | 9 Python tests and the host C encoder test passed |
| Nordic target build | NCS 3.4.0 build completed; both MCUboot image signatures checked |
| Firmware memory | Signed app 784,924 bytes; static RAM 446,368 / 450,560 bytes (99.07%) |
| Flutter | Changed files passed analysis; 26 targeted tests passed |
| Android APK | Release build, signature, package identity, CRC and alignment checks passed |
| Physical phone/watch integration | Pending |
| Finger PPG recording validation | Pending |
| Continuous 3–5+ hour collection and storage | Not demonstrated |
| Raw accelerometer/gyroscope live streaming | Not added by these changes |
| AWS, hybrid storage and architecture comparison | Pending |

Build evidence is in [`docs/builds/`](docs/builds/). Automated tests and a
successful build are not evidence of uninterrupted device recording. The custom
firmware retains finite measurement modes, and red/IR availability depends on
sensor mode/contact. Device uptime is estimated; indices do not prove exact
cross-sensor synchronization or lossless capture.

The phone changes in this repository add live display. They do not add continuous
mobile recording/storage of all live channels. The next milestones are finger
PPG hardware validation, complete recording integration, remaining sensor support,
and progressively longer capture tests with saved-data checks.

## Run and build

### Flutter app

Use a compatible Flutter SDK (the recorded APK used Flutter 3.47.9), Android SDK
36, JDK 17, and NDK 28.2.13676358. Local SDK paths and signing files are excluded.

```sh
cd app
flutter pub get
flutter test test/research_packet_test.dart test/live_stream_controller_test.dart test/live_screen_test.dart test/smp_lock_test.dart test/signal_view_test.dart
flutter build apk --release
```

The locally built APK is `app/build/app/outputs/flutter-apk/app-release.apk`.
Without private release signing configuration the project uses Android debug
signing for personal installation. It is a research build, not a Play Store
release. Pair the watch in this app, open Live, and start measurements on the
watch. Details: [`app/docs/RESEARCH_PPG_LIVE.md`](app/docs/RESEARCH_PPG_LIVE.md).

### Firmware

Install the nRF Connect SDK **v3.4.0** and use its matching toolchain environment.
Keep the repository's board/partition configuration and provide the required
signing keys locally; see [`docs/SIGNING.md`](docs/SIGNING.md).

For an SDK installed in a separate West workspace, from this repository root:

```sh
python fw/tools/build_research.py --sdk-root <SDK_WORKSPACE> --pristine
```

The helper sets `BOARD_ROOT` and `ZEPHYR_EXTRA_MODULES` to this checkout and builds
`healthypi_move/nrf5340/cpuapp`. Its log is written under `output/firmware/`.
The resulting OTA package is `fw/build/dfu_application.zip`. A source ZIP or a
patch is not an installable watch update. See the upstream [`fw/README.md`](fw/README.md)
and the additional channel contract in [`fw/docs/RESEARCH_PPG.md`](fw/docs/RESEARCH_PPG.md).

Reference protocol checks, from the repository root:

```sh
python -m unittest discover -s fw/tests/research_protocol -p test_protocol.py -v
gcc -std=c11 -Wall -Wextra -Werror -Ifw/app/src fw/tests/research_protocol/wire_test.c -o wire_test
```

Run the compiled `wire_test` on the host to execute the encoder checks.

### Windows laptop recorder

```powershell
python -m pip install -r pc_tools/requirements-research.txt
python pc_tools/research_app.py
```

Windows DPAPI protects recorded packet contents using the current Windows user.
Session metadata and exported CSVs are not all encrypted. Recordings are created
locally under the ignored `data/` directory. Test details and limitations:
[`docs/S2_S3_S4_IMPLEMENTATION.md`](docs/S2_S3_S4_IMPLEMENTATION.md).

## Upstream attribution and change review

| Component | Upstream | Base commit |
|---|---|---|
| Firmware | [ProtoCentral HealthyPi Move firmware](https://github.com/Protocentral/healthypi-move-fw) | `874f1347a6ec649cd9eef8bafb9d396d5806ca1e` |
| Flutter | [ProtoCentral HealthyPi Move Flutter app](https://github.com/Protocentral/healthypi_move_flutter) | `c58ff7a1f9a2fdd1d69be83f07bbf2fc079f90d5` |

The snapshots already contain the changes in `patches/`; do not apply those
patches again to this repository. They are provided for reviewing the research
contribution against the upstream base. Source hashes and exclusions are in the
provenance inventory. UTF-8 text line endings are normalized to LF for portable
checkouts; the inventory records both published and original workspace hashes.
Build-report source hashes refer to the original workspace files. No upstream
Git history is included.

Original copyright notices and licenses are retained. Firmware includes MIT,
Apache, BSD, Nordic-specific and font/documentation terms; read
[`fw/LICENSE.md`](fw/LICENSE.md), [`fw/THIRD_PARTY.md`](fw/THIRD_PARTY.md) and
[`app/LICENSE`](app/LICENSE). This project is not an official ProtoCentral release.

Signing keys, credentials, SDK installations, local recordings and generated
APK/OTA binaries are intentionally excluded from source control. Artifact names
and checksums from the local builds are retained in the build reports.
