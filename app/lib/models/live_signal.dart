import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../globals.dart';
import '../theme/hpi_colors.dart';

enum LiveSignal { ecg, wristGreen, wristRed, wristIr, fingerIr, fingerRed, gsr }

extension LiveSignalInfo on LiveSignal {
  String get label => switch (this) {
    LiveSignal.ecg => 'ECG',
    LiveSignal.wristGreen => 'Wrist green',
    LiveSignal.wristRed => 'Wrist red',
    LiveSignal.wristIr => 'Wrist IR',
    LiveSignal.fingerIr => 'Finger IR',
    LiveSignal.fingerRed => 'Finger red',
    LiveSignal.gsr => 'GSR',
  };

  int get researchId => switch (this) {
    LiveSignal.ecg => 1,
    LiveSignal.gsr => 2,
    LiveSignal.wristGreen => 3,
    LiveSignal.fingerIr => 4,
    LiveSignal.wristRed => 9,
    LiveSignal.wristIr => 10,
    LiveSignal.fingerRed => 11,
  };

  int get rate => switch (this) {
    LiveSignal.ecg => 128,
    LiveSignal.gsr => 32,
    LiveSignal.fingerIr || LiveSignal.fingerRed => 100,
    _ => 25,
  };

  bool get isPpg => this != LiveSignal.ecg && this != LiveSignal.gsr;
  bool get researchRequired =>
      this == LiveSignal.wristRed ||
      this == LiveSignal.wristIr ||
      this == LiveSignal.fingerRed;
  bool get isFinger =>
      this == LiveSignal.fingerIr || this == LiveSignal.fingerRed;
  Color get color => switch (this) {
    LiveSignal.ecg => HpiColors.hr,
    LiveSignal.gsr => HpiColors.eda,
    LiveSignal.wristGreen => HpiColors.steps,
    LiveSignal.wristRed || LiveSignal.fingerRed => HpiColors.bpSys,
    LiveSignal.wristIr => HpiColors.stress,
    LiveSignal.fingerIr => HpiColors.spo2,
  };

  String get legacyService =>
      isPpg ? hPi4Global.UUID_SERV_PPG : hPi4Global.UUID_ECG_SERVICE;
  String get legacyCharacteristic => switch (this) {
    LiveSignal.ecg => hPi4Global.UUID_ECG_CHAR,
    LiveSignal.gsr => hPi4Global.UUID_GSR_CHAR,
    LiveSignal.wristGreen => hPi4Global.UUID_CHAR_PPG,
    LiveSignal.fingerIr => 'cd5ca86f-4448-7db8-ae4c-d1da8cba36d0',
    _ => throw StateError('$label needs the research service'),
  };

  List<double> decodeLegacy(Uint8List bytes) {
    if (bytes.isEmpty || bytes.length % 4 != 0) {
      throw const FormatException('Invalid waveform payload length');
    }
    final data = ByteData.sublistView(bytes);
    return [
      for (int offset = 0; offset < bytes.length; offset += 4)
        (isPpg
                ? data.getUint32(offset, Endian.little)
                : data.getInt32(offset, Endian.little))
            .toDouble(),
    ];
  }

  String get waitingHint => switch (this) {
    LiveSignal.ecg => 'Start ECG on the watch and touch the electrodes.',
    LiveSignal.gsr => 'Start an EDA / GSR measurement on the watch.',
    LiveSignal.fingerIr || LiveSignal.fingerRed =>
      'Start a finger measurement on the watch and keep your finger in contact.',
    LiveSignal.wristRed || LiveSignal.wristIr =>
      'Start wrist SpO₂ on the watch. Red / IR availability depends on its measurement mode.',
    LiveSignal.wristGreen => 'Wear the watch snugly and wait for wrist PPG.',
  };
}
