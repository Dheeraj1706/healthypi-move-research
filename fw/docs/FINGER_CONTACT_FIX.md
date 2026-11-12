# Finger contact fix — 3.1.3-fingerfix

This OTA replaces 3.1.2-continuous while keeping its research BLE commands,
concurrent controls and waveform layout compatible with Android app 3.0.11.
No Android update is needed for this fix.

The finger contact-loss debounce previously assigned 64-bit millisecond uptime
to an 8-bit variable. At 60000 ms it stored 96, so a check only 20 ms later
mistakenly calculated 59924 ms elapsed and declared loss before the intended
1000 ms delay. This could amplify brief algorithm-status dips into rapid changes
between streaming and waiting for contact.

The fix uses a 64-bit timestamp and an explicit pending-loss flag, including at
uptime zero. A recovered accepted status clears the pending loss. Contact state
and the debounce state are serialized during updates/reset. The existing
algorithm-status mapping (1/2/4 accepted) and immediate contact-on behavior are
preserved; this change does not claim algorithm status is a direct measurement
of physical attachment.

Finger decode now checks buffer size and a nonzero valid sample count before
reading contact/status fields. The MAX32664D RTIO driver initializes each encoded
frame and returns an error for an unsupported mode. An empty FIFO/read therefore
cannot reuse an uninitialized status byte to toggle contact.

The shared header's host C regression test covers the 60000 ms truncation case,
the 999/1000 ms loss boundary, recovery between short dips, empty frames, uptime
zero and uptime beyond 32-bit millisecond wrap. Protocol/encoder/admission tests
are also retained. The Nordic target build and signed OTA package are checked
separately; these host checks are not a physical watch/contact test.

On the watch, maintain contact and verify short status dips no longer immediately
switch the label. Removing contact must still reach waiting after sustained
rejected statuses, and restoring accepted statuses must recover. Continued
waiting can still mean weak signal, an algorithm state or a genuine contact
issue. Compare raw samples and actual status values before diagnosing hardware.
