import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:move/models/device_info.dart';
import 'package:move/screens/scr_live.dart';
import 'package:move/theme/hpi_theme.dart';

import 'research_session_controller_test.dart' show FakeControlTransport;

void main() {
  testWidgets(
    'phone can start all sensors, show independent controls, and stop on leaving Live',
    (tester) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final transport = FakeControlTransport();
      Widget screen(bool active) => MaterialApp(
        theme: HpiTheme.dark(),
        home: Scaffold(
          body: ScrLive(
            active: active,
            transport: transport,
            initialDevice: DeviceInfo(
              macAddress: 'watch',
              deviceName: 'Test watch',
              firstPaired: DateTime(2026),
            ),
          ),
        ),
      );
      await tester.pumpWidget(screen(true));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Start all'));
      await tester.pumpAndSettle();
      expect(transport.mask, 15);
      await tester.tap(find.text('Sensors ON'));
      await tester.pumpAndSettle();
      expect(find.text('Continuous sensors'), findsOneWidget);
      expect(find.textContaining('ECG\nWaiting for contact'), findsOneWidget);
      expect(find.textContaining('GSR\nWaiting for contact'), findsOneWidget);
      expect(tester.takeException(), isNull);
      // Close the panel, compare two traces, and verify the phone layout.
      await tester.tapAt(const Offset(20, 40));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();
      expect(
        transport.commands.length,
        4,
      ); // Chart changes did not restart sensors.
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(screen(false));
      await tester.pump();
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 50)),
      );
      await tester.pumpAndSettle();
      expect(transport.mask, 0);
      expect(transport.commands.where((c) => c[1] == 2).length, 4);
      await tester.pumpWidget(const SizedBox());
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 20)),
      );
      await tester.pump();
    },
  );
}
