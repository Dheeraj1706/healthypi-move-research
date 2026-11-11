import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:move/ui/app_startup.dart';

void main() {
  testWidgets(
    'pending initialization paints progress and waits before opening the app',
    (tester) async {
      final initialized = Completer<void>();
      await tester.pumpWidget(
        AppStartup(
          initialize: () => initialized.future,
          app: const MaterialApp(home: Text('App ready')),
        ),
      );
      expect(find.text('Opening HealthyPi Move…'), findsOneWidget);
      expect(find.text('App ready'), findsNothing);
      initialized.complete();
      await tester.pumpAndSettle();
      expect(find.text('App ready'), findsOneWidget);
    },
  );

  testWidgets('missing native plugin becomes a visible retryable error', (
    tester,
  ) async {
    int attempts = 0;
    await tester.pumpWidget(
      AppStartup(
        initialize: () async {
          if (++attempts == 1) {
            throw MissingPluginException('Bluetooth plugin is missing');
          }
        },
        app: const MaterialApp(home: Text('App ready')),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Could not open HealthyPi Move'), findsOneWidget);
    expect(find.textContaining('Bluetooth plugin is missing'), findsOneWidget);
    expect(find.text('App ready'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('App ready'), findsOneWidget);
    expect(attempts, 2);
  });

  testWidgets('storage initialization errors do not mount the data screens', (
    tester,
  ) async {
    await tester.pumpWidget(
      AppStartup(
        initialize:
            () async => throw StateError('Could not open local database'),
        app: const MaterialApp(home: Text('App ready')),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Could not open local database'),
      findsOneWidget,
    );
    expect(find.text('App ready'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
