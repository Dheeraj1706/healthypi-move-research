"""
Physiological validation + dropout correlation.

Two questions this answers for the report:

1. Are the dropout gaps simultaneous across signals? If both characteristics
   stall in the same wall-clock window the cause is the BLE link (connection
   event starvation), not any one sensor -- which changes the mitigation.
2. Does the wrist PPG contain a real cardiac rhythm? Recovering a plausible
   heart rate from the raw waveform is the strongest evidence that the whole
   decode chain (UUID -> byte order -> sample width) is correct.

Usage:  python validate.py [session_id]
"""
import math
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpi_ble as H

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "recordings.db")


def load(conn, session_id, key):
    return conn.execute(
        "SELECT recv_mono, n_samples, payload FROM packets"
        " WHERE session_id=? AND signal=? ORDER BY pkt_seq",
        (session_id, key)).fetchall()


def find_gaps(times, factor=3.0, floor_s=0.05):
    if len(times) < 3:
        return []
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    med = statistics.median(gaps)
    return [(times[i], times[i + 1], gaps[i])
            for i in range(len(gaps))
            if gaps[i] > factor * med and gaps[i] > floor_s]


def dropout_correlation(conn, session_id, keys):
    print("\n--- dropout correlation ---")
    per = {}
    for key in keys:
        rows = load(conn, session_id, key)
        if len(rows) > 2:
            per[key] = find_gaps([r[0] for r in rows])

    for key, gaps in per.items():
        print("  %-12s %d gap(s): %s" % (
            key, len(gaps),
            ", ".join("%.2fs@t+%.1f" % (g[2], g[0]) for g in gaps) or "-"))

    names = list(per)
    if len(names) < 2:
        return
    a, b = names[0], names[1]
    matched = 0
    for s_a, e_a, _d in per[a]:
        for s_b, e_b, _d2 in per[b]:
            # Overlapping stall windows -> the link was down for both.
            if max(s_a, s_b) < min(e_a, e_b):
                matched += 1
                break
    total = max(len(per[a]), len(per[b]))
    print("  overlapping stalls : %d of %d" % (matched, total))
    if total and matched == total:
        print("  => ALL stalls simultaneous: cause is the BLE LINK, not a sensor.")
    elif matched:
        print("  => partially simultaneous: mixed link and per-sensor causes.")
    else:
        print("  => independent stalls: per-characteristic, not the link.")


def detrend(values, fs, window_s=1.2):
    """High-pass by subtracting a centred moving average.

    Wrist PPG is dominated by baseline wander (motion, contact pressure,
    venous return) an order of magnitude larger than the cardiac AC component.
    Without removing it the spectral peak lands on the drift, not the pulse.
    A 1.2 s window puts the cutoff near 0.8 Hz (~50 bpm), below any plausible
    heart rate but above the wander.
    """
    w = max(3, int(fs * window_s) | 1)          # odd window
    half = w // 2
    n = len(values)
    out = []
    run = sum(values[:min(w, n)])
    for i in range(n):
        lo, hi = i - half, i + half
        if lo < 0 or hi >= n:                    # edges: local mean
            a, b = max(0, lo), min(n - 1, hi)
            out.append(values[i] - sum(values[a:b + 1]) / (b - a + 1))
        else:
            out.append(values[i] - run / w)
            if hi + 1 < n:
                run += values[hi + 1] - values[lo]
    return out


def estimate_heart_rate(values, fs, use_detrend=True):
    """Coarse spectral HR estimate over the physiological 40-180 bpm band."""
    n = len(values)
    if n < fs * 10:
        return None, "need >=10 s of data"

    x = detrend(values, fs) if use_detrend else values
    mean = statistics.mean(x)
    x = [v - mean for v in x]
    # Hann window to suppress spectral leakage from the strong DC/drift term.
    x = [x[i] * 0.5 * (1 - math.cos(2 * math.pi * i / (n - 1))) for i in range(n)]

    best_bpm, best_mag = None, 0.0
    # Direct DFT over the narrow band of interest -- cheaper than a full FFT here.
    for bpm in [b * 0.5 for b in range(80, 361)]:      # 40.0 .. 180.0 bpm
        f = bpm / 60.0
        re = im = 0.0
        for i, v in enumerate(x):
            ang = 2 * math.pi * f * i / fs
            re += v * math.cos(ang)
            im -= v * math.sin(ang)
        mag = math.hypot(re, im)
        if mag > best_mag:
            best_mag, best_bpm = mag, bpm
    return best_bpm, None


def main(session_id=None):
    conn = sqlite3.connect(DB)
    if session_id is None:
        session_id = conn.execute("SELECT MAX(id) FROM sessions").fetchone()[0]

    keys = [r[0] for r in conn.execute(
        "SELECT DISTINCT signal FROM packets WHERE session_id=?", (session_id,))]
    print("SESSION #%d  signals=%s" % (session_id, keys))

    dropout_correlation(conn, session_id, keys)

    print("\n--- physiological validation ---")
    for key in ("ppg_wrist", "ppg_finger"):
        if key not in keys:
            continue
        sig = H.WAVEFORMS_BY_KEY[key]
        vals = []
        for _t, _n, payload in load(conn, session_id, key):
            vals.extend(sig.decode(payload))
        if not vals:
            continue
        bpm, err = estimate_heart_rate(vals, sig.rate_hz)
        raw_bpm, _ = estimate_heart_rate(vals, sig.rate_hz, use_detrend=False)
        if err:
            print("  %-12s %s" % (key, err))
        else:
            dc = statistics.mean(vals)
            ac = statistics.pstdev(detrend(vals, sig.rate_hz))
            print("  %-12s n=%d  dominant rhythm = %.1f bpm  (undetrended %.1f)"
                  % (key, len(vals), bpm, raw_bpm))
            print("  %-12s pulsatile AC/DC = %.3f%% (perfusion index proxy)"
                  % ("", 100.0 * ac / dc if dc else 0.0))
            if 45 <= bpm <= 150:
                print("  %-12s => PLAUSIBLE HUMAN HEART RATE: decode chain verified."
                      % "")
            else:
                print("  %-12s => outside typical resting range; check contact."
                      % "")
    conn.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
