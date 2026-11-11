import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:move/ble/research_packet.dart';
import 'package:move/models/live_signal.dart';
import 'package:move/utils/live_stream_controller.dart';
import 'research_packet_test.dart' show packet;

class FakeLiveTransport implements LiveTransport {
  @override
  bool connected = true;
  @override
  bool hasResearch = true;
  final streams = <LiveRoute, StreamController<Uint8List>>{};
  final enabled = <LiveRoute>[];
  final disabled = <LiveRoute>[];
  Completer<void>? pairing;
  bool failEnable = false;
  @override
  Future<void> pair() async {
    await pairing?.future;
  }

  @override
  Stream<Uint8List> values(LiveRoute route) =>
      streams
          .putIfAbsent(route, () => StreamController.broadcast(sync: true))
          .stream;
  @override
  Future<void> enable(LiveRoute route) async {
    if (failEnable) throw StateError('pairing rejected');
    enabled.add(route);
  }

  @override
  Future<void> disable(LiveRoute route) async {
    disabled.add(route);
  }

  void emit(Uint8List bytes) =>
      streams[(service: researchService, characteristic: researchData)]!.add(
        bytes,
      );
}

void main() {
  test(
    'retargeting an active PPG subscription completes cleanup and restart',
    () async {
      final transport = FakeLiveTransport();
      final feed = LiveStreamController(transport, onSamples: (_, _, _) {});
      await feed.select({LiveSignal.wristGreen});
      await feed.select({LiveSignal.wristRed});
      await feed.select({LiveSignal.wristRed, LiveSignal.ecg});
      expect(feed.active, {LiveSignal.wristRed, LiveSignal.ecg});
      expect(transport.enabled.length, 3);
      feed.dispose();
    },
  );
  test(
    'two PPG charts share one subscription and route samples by ID',
    () async {
      final transport = FakeLiveTransport();
      final received = <LiveSignal, List<double>>{};
      final feed = LiveStreamController(
        transport,
        onSamples: (s, v, _) => received[s] = v,
      );
      await feed.select({LiveSignal.wristRed, LiveSignal.wristIr});
      expect(transport.enabled.length, 1);
      transport.emit(packet(signal: 9));
      transport.emit(packet(signal: 10, samples: [15, 16]));
      transport.emit(packet(signal: 11, samples: [99]));
      expect(
        received.keys,
        unorderedEquals([LiveSignal.wristRed, LiveSignal.wristIr]),
      );
      expect(received[LiveSignal.wristRed], [0, 4000000000, 4294967295]);
      expect(received[LiveSignal.wristIr], [15, 16]);
      await feed.select({});
      expect(transport.disabled.length, 1);
      expect(feed.isStreaming, isFalse);
      feed.dispose();
    },
  );
  test(
    'old firmware keeps original streams and explains unavailable channels',
    () async {
      final transport = FakeLiveTransport()..hasResearch = false;
      final feed = LiveStreamController(transport, onSamples: (_, _, _) {});
      await feed.select({LiveSignal.wristGreen, LiveSignal.wristRed});
      expect(feed.active, {LiveSignal.wristGreen});
      expect(feed.errors[LiveSignal.wristRed], contains('3.1.1-ppg'));
      expect(
        transport.enabled.single.characteristic,
        LiveSignal.wristGreen.legacyCharacteristic,
      );
      feed.dispose();
    },
  );
  test(
    'a selection change during pairing enables only the newest selection',
    () async {
      final transport = FakeLiveTransport()..pairing = Completer<void>();
      final feed = LiveStreamController(transport, onSamples: (_, _, _) {});
      final first = feed.select({LiveSignal.wristRed});
      await Future<void>.delayed(Duration.zero);
      final second = feed.select({LiveSignal.fingerRed});
      transport.pairing!.complete();
      await first;
      await second;
      expect(feed.active, {LiveSignal.fingerRed});
      expect(transport.enabled.length, 1);
      feed.dispose();
    },
  );
  test('subscribe errors are visible and retry can recover', () async {
    final transport = FakeLiveTransport()..failEnable = true;
    final feed = LiveStreamController(transport, onSamples: (_, _, _) {});
    await feed.select({LiveSignal.wristIr});
    expect(feed.isStreaming, isFalse);
    expect(feed.errors[LiveSignal.wristIr], contains('pairing'));
    transport.failEnable = false;
    await feed.select({LiveSignal.wristIr});
    expect(feed.isStreaming, isTrue);
    expect(feed.errors, isEmpty);
    feed.dispose();
  });
  test(
    'missing indices break the trace; malformed packets do not add samples',
    () async {
      final transport = FakeLiveTransport();
      final breaks = <bool>[];
      final feed = LiveStreamController(
        transport,
        onSamples: (_, _, b) => breaks.add(b),
      );
      await feed.select({LiveSignal.fingerRed});
      transport.emit(packet(signal: 11, index: 0, samples: [1, 2]));
      transport.emit(Uint8List(19));
      expect(feed.errors, isNotEmpty);
      transport.emit(packet(signal: 11, index: 5, samples: [3]));
      expect(breaks, [false, true]);
      expect(feed.missingCounts[LiveSignal.fingerRed], 3);
      expect(feed.sampleCounts[LiveSignal.fingerRed], 3);
      expect(feed.errors, isEmpty);
      transport.connected = false;
      await feed.select({LiveSignal.fingerRed});
      expect(feed.isStreaming, isFalse);
      feed.dispose();
    },
  );
}
