import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:move/models/device_info.dart';
import 'package:move/screens/scr_live.dart';
import 'package:move/theme/hpi_theme.dart';
import 'package:move/ui/charts/hpi_sweep_waveform.dart';
import 'live_stream_controller_test.dart' show FakeLiveTransport;
import 'research_packet_test.dart' show packet;

void main() {
  testWidgets('leaving Live stops subscriptions and returning restarts them', (
    tester,
  ) async {
    final transport = FakeLiveTransport();
    final device = DeviceInfo(
      macAddress: 'watch',
      deviceName: 'Test watch',
      firstPaired: DateTime(2026),
    );
    Widget screen(bool active) => MaterialApp(
      theme: HpiTheme.dark(),
      home: Scaffold(
        body: ScrLive(
          initialDevice: device,
          transport: transport,
          active: active,
        ),
      ),
    );
    await tester.pumpWidget(screen(false));
    await tester.pumpAndSettle();
    expect(transport.enabled, isEmpty);
    await tester.pumpWidget(screen(true));
    await tester.pumpAndSettle();
    expect(transport.enabled.length, 1);
    await tester.pumpWidget(screen(false));
    await tester.pump();
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 10)),
    );
    await tester.pumpAndSettle();
    expect(transport.disabled.length, 1);
    expect(transport.streams.values.single.hasListener, isFalse);
    await tester.pumpWidget(screen(true));
    await tester.pumpAndSettle();
    expect(transport.enabled.length, 2);
    await tester.pumpWidget(const SizedBox());
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 10)),
    );
    await tester.pump();
  });
  for (final size in [const Size(360, 640), const Size(800, 1000)]) {
    testWidgets('PPG selection and comparison fit $size', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final transport = FakeLiveTransport();
      await tester.pumpWidget(
        MaterialApp(
          theme: HpiTheme.dark(),
          home: Scaffold(
            body: ScrLive(
              initialDevice: DeviceInfo(
                macAddress: 'watch',
                deviceName: 'Test watch',
                firstPaired: DateTime(2026),
              ),
              transport: transport,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Wrist green PPG'), findsOneWidget);
      await tester.tap(find.text('Wrist red').first);
      await tester.pump();
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 10)),
      );
      await tester.pump(const Duration(milliseconds: 100));
      await tester.pumpAndSettle();
      expect(find.text('Wrist red PPG'), findsOneWidget);
      await tester.tap(find.byType(Switch));
      await tester.pump();
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 10)),
      );
      await tester.pump(const Duration(milliseconds: 100));
      await tester.pumpAndSettle();
      expect(find.byType(HpiSweepWaveform), findsNWidgets(2));
      transport.emit(packet(signal: 9));
      await tester.pump(const Duration(seconds: 1));
      expect(find.textContaining('3 samples'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    });
  }
}
