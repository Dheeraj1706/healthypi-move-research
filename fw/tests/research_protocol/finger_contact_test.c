#include <assert.h>
#include <stdio.h>
#include "hpi_finger_contact.h"

int main(void)
{
    struct hpi_finger_contact_debounce d = {0};
    bool contact = hpi_finger_contact_update(&d, false, true, true, 59980);
    assert(contact);
    /* Regression: old uint8 timestamp stored 60000 as 96 and lost contact
     * after only 20 ms. Check the complete delay at realistic watch uptime. */
    assert(hpi_finger_contact_update(&d, contact, true, false, 60000));
    assert(d.bad_since_ms == 60000);
    assert(hpi_finger_contact_update(&d, contact, true, false, 60020));
    assert(hpi_finger_contact_update(&d, contact, true, false, 60999));
    assert(!hpi_finger_contact_update(&d, contact, true, false, 61000));
    /* A recovered signal clears the pending loss instead of carrying it over. */
    assert(hpi_finger_contact_update(&d, false, true, true, 61020));
    assert(!d.bad_pending);
    assert(hpi_finger_contact_update(&d, true, true, false, 62000));
    assert(hpi_finger_contact_update(&d, true, true, true, 62020));
    assert(hpi_finger_contact_update(&d, true, true, false, 63000));
    assert(hpi_finger_contact_update(&d, true, true, false, 63020));
    /* Missing data cannot toggle contact on or off or start a loss timer. */
    d = (struct hpi_finger_contact_debounce){0};
    assert(hpi_finger_contact_update(&d, true, false, false, 70000));
    assert(!d.bad_pending);
    assert(!hpi_finger_contact_update(&d, false, false, true, 70020));
    /* No zero-timestamp sentinel; also safe beyond 32-bit millisecond wrap. */
    assert(hpi_finger_contact_update(&d, true, true, false, 0));
    assert(!hpi_finger_contact_update(&d, true, true, false, 1000));
    d = (struct hpi_finger_contact_debounce){0};
    const int64_t long_uptime = INT64_C(4294967296) + 60000;
    assert(hpi_finger_contact_update(&d, true, true, false, long_uptime));
    assert(hpi_finger_contact_update(&d, true, true, false, long_uptime + 999));
    assert(!hpi_finger_contact_update(&d, true, true, false, long_uptime + 1000));
    puts("PASS: finger contact delay, recovery, empty frames, uptime zero and long uptime");
    return 0;
}
