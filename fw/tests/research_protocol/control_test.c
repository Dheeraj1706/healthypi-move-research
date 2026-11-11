#include <assert.h>
#include "hpi_research_policy.h"

int main(void)
{
    /* Each successive continuous target is admissible, including ECG+BioZ. */
    for (unsigned mask = 0; mask < 16; ++mask) {
        assert(!hpr_start_busy(true, false, mask, mask, mask, !!(mask & 8)));
        if (mask) assert(hpr_start_busy(false, false, mask, mask, mask, false));
        assert(hpr_start_busy(true, true, mask, mask, mask, false));
    }
    /* Local spot checks, BP and remotely owned finite checks stay exclusive. */
    assert(hpr_start_busy(true, false, 0, 0, 1, false));
    assert(hpr_start_busy(true, false, 0, 0, 0, true));
    assert(hpr_start_busy(true, false, 1, 0, 1, false));
    assert(hpr_start_busy(true, false, 3, 3, 7, false));
    /* Stopping one target leaves the remaining continuous targets admissible. */
    assert(!hpr_start_busy(true, false, 14, 14, 14, true));
    return 0;
}
