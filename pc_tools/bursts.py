"""
Burst-wise throughput.

The watch's ECG measurement runs in fixed ~30 s windows, so a session contains
several bursts separated by long idle gaps. Averaging across the whole session
mixes "sensor off" with "sensor on but dropping packets" and understates real
throughput. This splits the stream at long gaps and reports each burst.

Usage:  python bursts.py [session_id] [signal]
"""
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpi_ble as H

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "recordings.db")
IDLE_GAP_S = 5.0     # longer than this = sensor was off, not a dropped packet


def bursts_for(conn, session_id, key):
    rows = conn.execute(
        "SELECT recv_mono, n_samples FROM packets"
        " WHERE session_id=? AND signal=? ORDER BY pkt_seq",
        (session_id, key)).fetchall()
    if not rows:
        return []

    groups, cur = [], [rows[0]]
    for prev, curr in zip(rows, rows[1:]):
        if curr[0] - prev[0] > IDLE_GAP_S:
            groups.append(cur)
            cur = [curr]
        else:
            cur.append(curr)
    groups.append(cur)
    return groups


def main(session_id=None, only=None):
    conn = sqlite3.connect(DB)
    if session_id is None:
        session_id = conn.execute("SELECT MAX(id) FROM sessions").fetchone()[0]

    keys = [r[0] for r in conn.execute(
        "SELECT DISTINCT signal FROM packets WHERE session_id=?", (session_id,))]
    if only:
        keys = [k for k in keys if k == only]

    print("SESSION #%d  (bursts split at gaps > %.0f s)\n" % (session_id, IDLE_GAP_S))

    for key in sorted(keys):
        sig = H.WAVEFORMS_BY_KEY.get(key)
        if sig is None:
            continue
        groups = bursts_for(conn, session_id, key)
        print("--- %s (nominal %d Hz) : %d burst(s) ---" % (key, sig.rate_hz, len(groups)))

        active_samples = active_span = 0.0
        for i, g in enumerate(groups, 1):
            span = g[-1][0] - g[0][0]
            n = sum(r[1] for r in g)
            if span <= 0:
                print("  burst %d: %d samples, instantaneous" % (i, n))
                continue
            rate = n / span
            print("  burst %-2d %6.1f s  %6d samples  %7.2f Hz  yield %5.1f%%"
                  % (i, span, n, rate, 100.0 * rate / sig.rate_hz))
            active_samples += n
            active_span += span

        if active_span > 0:
            rate = active_samples / active_span
            print("  ACTIVE TOTAL  %.1f s  %d samples  %.2f Hz  yield %.1f%%"
                  % (active_span, active_samples, rate,
                     100.0 * rate / sig.rate_hz))
        print()

    conn.close()


if __name__ == "__main__":
    sid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    sg = sys.argv[2] if len(sys.argv) > 2 else None
    main(sid, sg)
