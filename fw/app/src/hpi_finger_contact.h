/* SPDX-License-Identifier: MIT */
#ifndef HPI_FINGER_CONTACT_H
#define HPI_FINGER_CONTACT_H
#include <stdbool.h>
#include <stdint.h>

struct hpi_finger_contact_debounce {
    int64_t bad_since_ms;
    bool bad_pending;
};

/* Caller serializes this state and its contact flag. Empty frames are neither
 * contact nor loss evidence. Preserve the existing status mapping and immediate
 * contact-on behavior; require a full second before contact-off. */
static inline bool hpi_finger_contact_update(struct hpi_finger_contact_debounce *d,
                                            bool previous, bool fresh,
                                            bool candidate, int64_t now_ms)
{
    if (!fresh) { return previous; }
    if (candidate) {
        d->bad_pending = false;
        return true;
    }
    if (!previous) { d->bad_pending = false; return false; }
    if (!d->bad_pending || now_ms < d->bad_since_ms) {
        d->bad_since_ms = now_ms;
        d->bad_pending = true;
        return true;
    }
    return now_ms - d->bad_since_ms < 1000;
}
#endif
