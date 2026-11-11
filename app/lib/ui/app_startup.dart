import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/hpi_theme.dart';

/// Paints before native initialization and keeps failures visible and retryable.
/// The main screens are only mounted after local data preparation succeeds.
class AppStartup extends StatefulWidget {
  const AppStartup({super.key, required this.initialize, required this.app});
  final Future<void> Function() initialize;
  final Widget app;

  @override
  State<AppStartup> createState() => _AppStartupState();
}

class _AppStartupState extends State<AppStartup> {
  late Future<void> _initialization;

  @override
  void initState() {
    super.initState();
    _initialization = Future<void>.sync(widget.initialize);
  }

  void _retry() {
    final initialization = Future<void>.sync(widget.initialize);
    setState(() {
      _initialization = initialization;
    });
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<void>(
    future: _initialization,
    builder: (context, snapshot) {
      if (snapshot.connectionState == ConnectionState.done &&
          !snapshot.hasError) {
        return widget.app;
      }
      return MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: HpiTheme.dark(),
        home: Scaffold(
          body: SafeArea(
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (!snapshot.hasError) ...[
                        const CircularProgressIndicator(),
                        const SizedBox(height: 20),
                        const Text('Opening HealthyPi Move…'),
                        const SizedBox(height: 8),
                        const Text('Preparing Bluetooth and local data.'),
                      ] else ...[
                        const Icon(Icons.error_outline, size: 40),
                        const SizedBox(height: 16),
                        const Text('Could not open HealthyPi Move'),
                        const SizedBox(height: 12),
                        SelectableText(
                          '${snapshot.error}',
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 20),
                        FilledButton(
                          onPressed: _retry,
                          child: const Text('Retry'),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    },
  );
}
