"""
Per-session signal quality report.

Separates true throughput from startup latency: yield measured over the whole
wall-clock window is diluted by the seconds before the first packet arrives,
so we report a steady-state rate over [first packet, last packet] as well.

Also flags inter-packet gaps, which is how packet loss shows up given that the
firmware sends no sequence numbers (docs/BLE_SPEC.md section 2).

Usage:  python analyze.py [session_id]     (default: latest session)
"""
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpi_ble as H

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "recordings.db")


def analyze(db_path, session_id=None):
    conn = sqlite3.connect(db_path)

    if session_id is None:
        row = conn.execute("SELECT MAX(id) FROM sessions").fetchone()
        session_id = row[0]
        if session_id is None:
            print("No sessions in %s" % db_path)
            return

    srow = conn.execute(
        "SELECT started_utc, ended_utc, device_addr, note FROM sessions"
        " WHERE id=?", (session_id,)).fetchone()
    if srow is None:
        print("Session %s not found." % session_id)
        return
    started, ended, addr, note = srow
    wall = (ended - started) if ended else 0.0

    print("=" * 74)
    print("SESSION #%d   device=%s   %.1f s   note=%r"
          % (session_id, addr, wall, note or ""))
    print("=" * 74)

    signals = [r[0] for r in conn.execute(
        "SELECT DISTINCT signal FROM packets WHERE session_id=?", (session_id,))]

    for key in sorted(signals):
        sig = H.WAVEFORMS_BY_KEY.get(key)
        rows = conn.execute(
            "SELECT recv_mono, n_samples, payload FROM packets"
            " WHERE session_id=? AND signal=? ORDER BY pkt_seq",
            (session_id, key)).fetchall()
        if not rows:
            continue

        times = [r[0] for r in rows]
        n_samples = sum(r[1] for r in rows)
        span = times[-1] - times[0] if len(times) > 1 else 0.0
        startup = times[0] - (rows[0][0] - times[0]) if False else None

        print("\n--- %s (%s) ---" % (key, sig.label if sig else "?"))
        print("  packets            : %d" % len(rows))
        print("  samples            : %d" % n_samples)
        print("  samples/packet     : %.1f" % (n_samples / len(rows)))
        if span > 0:
            steady = n_samples / span
            print("  stream span        : %.1f s" % span)
            print("  steady-state rate  : %.2f Hz" % steady)
            if sig:
                print("  nominal rate       : %d Hz" % sig.rate_hz)
                print("  steady-state yield : %.1f%%"
                      % (100.0 * steady / sig.rate_hz))

        # Inter-packet gaps: with no sequence numbers, an outlier gap is the
        # only observable signature of dropped notifications.
        if len(times) > 2:
            gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
            med = statistics.median(gaps)
            big = [g for g in gaps if g > 3 * med and g > 0.05]
            print("  median gap         : %.1f ms" % (med * 1000))
            print("  max gap            : %.1f ms" % (max(gaps) * 1000))
            print("  gaps > 3x median   : %d" % len(big))
            if big and sig:
                lost = sum(int(round(g * sig.rate_hz)) for g in big)
                print("  est. samples lost  : ~%d in %d gap(s)" % (lost, len(big)))

        # Value statistics -- the check for whether the sensor was in contact.
        if sig:
            vals = []
            for _t, _n, payload in rows:
                vals.extend(sig.decode(payload))
            if vals:
                mean = statistics.mean(vals)
                sd = statistics.pstdev(vals)
                print("  value min/max      : %d / %d" % (min(vals), max(vals)))
                print("  value mean +/- sd  : %.1f +/- %.1f" % (mean, sd))
                # Outliers far outside the bulk indicate lead-off / no contact.
                if sd > 0:
                    outliers = [v for v in vals if abs(v - mean) > 10 * sd]
                    print("  extreme outliers   : %d (%.2f%%)"
                          % (len(outliers), 100.0 * len(outliers) / len(vals)))
                    q = sorted(vals)
                    lo, hi = q[len(q) // 100], q[-max(1, len(q) // 100)]
                    print("  robust 1-99%% range : %d .. %d" % (lo, hi))

    scal = conn.execute(
        "SELECT signal, COUNT(*) FROM scalars WHERE session_id=? GROUP BY signal",
        (session_id,)).fetchall()
    if scal:
        print("\n--- scalars ---")
        for name, cnt in scal:
            last = conn.execute(
                "SELECT value FROM scalars WHERE session_id=? AND signal=?"
                " ORDER BY id DESC LIMIT 1", (session_id, name)).fetchone()[0]
            print("  %-10s %4d reading(s)   last=%s" % (name, cnt, last[:60]))

    conn.close()


if __name__ == "__main__":
    sid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    analyze(DB, sid)
