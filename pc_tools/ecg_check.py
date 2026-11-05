"""
ECG validation by R-peak detection.

A decoded ECG stream is only trustworthy if it contains the thing an ECG is
supposed to contain: sharp, regularly spaced R-peaks at a physiological rate,
with beat-to-beat intervals that vary a little (real hearts do) but not wildly
(noise does). This does a small Pan-Tompkins-style pipeline -- bandpass by
difference-of-moving-averages, square, integrate, then threshold with a
refractory period -- and reports rate and variability.

Also checks alignment between the ECG and GSR characteristics, since firmware
v2.1.1 duplicates ECG onto GSR.

Usage:  python ecg_check.py [session_id]
"""
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hpi_ble as H

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "recordings.db")
FS = 128.0


def moving_avg(x, w):
    if w < 2:
        return list(x)
    out, run = [], 0.0
    half = w // 2
    n = len(x)
    for i in range(n):
        a, b = max(0, i - half), min(n - 1, i + half)
        out.append(sum(x[a:b + 1]) / (b - a + 1))
    return out


def clip_artifacts(x, k=8.0):
    """Clamp motion-artifact spikes to a robust envelope.

    Wrist ECG carries occasional transients ~30x the QRS amplitude. Left in,
    they dominate any percentile-based threshold and the detector locks onto
    artifacts instead of beats. Clipping to a median-absolute-deviation
    envelope preserves QRS morphology while flattening the spikes.
    """
    med = statistics.median(x)
    mad = statistics.median([abs(v - med) for v in x]) or 1.0
    lim = k * mad
    return [max(med - lim, min(med + lim, v)) for v in x]


def detect_r_peaks(x, fs):
    """Return indices of detected R-peaks."""
    x = clip_artifacts(x)

    # Bandpass: subtract a slow baseline, then smooth out high-frequency noise.
    baseline = moving_avg(x, int(fs * 0.6) | 1)      # ~0.6 s -> removes drift
    bp = [x[i] - baseline[i] for i in range(len(x))]
    bp = moving_avg(bp, 3)                           # light smoothing

    # Derivative emphasises the steep QRS slope over slower P and T waves.
    deriv = [0.0] + [bp[i] - bp[i - 1] for i in range(1, len(bp))]
    squared = [d * d for d in deriv]
    integrated = moving_avg(squared, max(3, int(fs * 0.12) | 1))

    if not integrated:
        return []
    # Median-based threshold: robust to the residual spikes a percentile would
    # chase. QRS energy sits far above the median of the integrated signal.
    med = statistics.median(integrated)
    mad = statistics.median([abs(v - med) for v in integrated]) or 1.0
    thresh = med + 4.0 * mad
    refractory = int(fs * 0.28)                      # 280 ms -> max ~214 bpm

    peaks, i, n = [], 1, len(integrated)
    while i < n - 1:
        if integrated[i] > thresh and integrated[i] >= integrated[i - 1] \
                and integrated[i] >= integrated[i + 1]:
            # Snap to the largest absolute deflection nearby in the filtered signal.
            a, b = max(0, i - int(fs * 0.05)), min(n, i + int(fs * 0.05))
            best = max(range(a, b), key=lambda j: abs(bp[j]))
            peaks.append(best)
            i += refractory
        else:
            i += 1
    return peaks


def load_signal(conn, session_id, key):
    sig = H.WAVEFORMS_BY_KEY[key]
    vals = []
    for payload, in conn.execute(
            "SELECT payload FROM packets WHERE session_id=? AND signal=?"
            " ORDER BY pkt_seq", (session_id, key)):
        vals.extend(sig.decode(payload))
    return vals


def check_duplication(conn, session_id):
    e = [p for p, in conn.execute(
        "SELECT payload FROM packets WHERE session_id=? AND signal='ecg'"
        " ORDER BY pkt_seq", (session_id,))]
    g = [p for p, in conn.execute(
        "SELECT payload FROM packets WHERE session_id=? AND signal='gsr'"
        " ORDER BY pkt_seq", (session_id,))]
    if not e or not g:
        return
    best, best_off = 0, 0
    for off in range(-3, 4):
        m = 0
        for i in range(len(e)):
            j = i + off
            if 0 <= j < len(g) and e[i] == g[j]:
                m += 1
        if m > best:
            best, best_off = m, off
    total = min(len(e), len(g))
    print("  ECG/GSR duplication: %d of %d packets identical (offset %+d) = %.1f%%"
          % (best, total, best_off, 100.0 * best / total if total else 0))


def main(session_id=None):
    conn = sqlite3.connect(DB)
    if session_id is None:
        session_id = conn.execute("SELECT MAX(id) FROM sessions").fetchone()[0]

    note = conn.execute("SELECT note FROM sessions WHERE id=?",
                        (session_id,)).fetchone()[0]
    print("SESSION #%d  %r" % (session_id, note or ""))

    check_duplication(conn, session_id)

    ecg = load_signal(conn, session_id, "ecg")
    if not ecg:
        print("  no ECG data")
        return
    dur = len(ecg) / FS
    print("  ECG samples: %d (%.1f s at %g Hz)" % (len(ecg), dur, FS))

    peaks = detect_r_peaks(ecg, FS)
    if len(peaks) < 4:
        print("  R-peaks detected: %d -- too few to assess" % len(peaks))
        return

    rr = [(peaks[i + 1] - peaks[i]) / FS for i in range(len(peaks) - 1)]
    # Discard physiologically impossible intervals before summarising.
    rr_ok = [r for r in rr if 0.3 <= r <= 2.0]
    if not rr_ok:
        print("  no plausible RR intervals")
        return

    hr = 60.0 / statistics.mean(rr_ok)
    sdnn = statistics.pstdev(rr_ok) * 1000.0
    rmssd = (statistics.mean([(rr_ok[i + 1] - rr_ok[i]) ** 2
                              for i in range(len(rr_ok) - 1)]) ** 0.5 * 1000.0
             if len(rr_ok) > 1 else 0.0)

    print("  R-peaks detected  : %d (%d usable intervals)" % (len(peaks), len(rr_ok)))
    print("  mean heart rate   : %.1f bpm" % hr)
    print("  RR range          : %.2f - %.2f s" % (min(rr_ok), max(rr_ok)))
    print("  SDNN              : %.1f ms" % sdnn)
    print("  RMSSD             : %.1f ms" % rmssd)

    verdict = []
    if 40 <= hr <= 150:
        verdict.append("rate physiological")
    else:
        verdict.append("rate OUTSIDE physiological range")
    if 5 <= sdnn <= 300:
        verdict.append("variability consistent with a real heartbeat")
    elif sdnn < 5:
        verdict.append("variability too LOW -- suspiciously periodic")
    else:
        verdict.append("variability too HIGH -- likely noise, not beats")
    print("  => %s" % "; ".join(verdict))
    conn.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
