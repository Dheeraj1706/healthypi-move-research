/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "hpi_research_wire.h"

int main(void)
{
    uint8_t out[244];
    const int32_t samples[] = {-12, 1000, 2000, 3000};
    struct hpr_stamp stamp = {.first_index = 0xfffffffeu, .first_ms = 1000};
    /* Default ATT MTU 23: payload 20, header 16, exactly one sample fits. */
    assert(hpr_encode(out, 20, HPR_ECG, 3, 0x12345678, &stamp, samples, 0, 1, 128) == 20);
    assert(out[0] == 1 && out[1] == 1 && out[2] == 3 && out[3] == 1);
    assert(out[4] == 0x78 && out[5] == 0x56 && out[6] == 0x34 && out[7] == 0x12);
    assert(out[16] == 0xf4 && out[17] == 0xff && out[19] == 0xff);
    assert(hpr_encode(out, 19, HPR_ECG, 3, 1, &stamp, samples, 0, 1, 128) == 0);
    assert(hpr_encode(out, 20, HPR_ECG, 3, 1, &stamp, samples, 0, 2, 128) == 0);
    assert(hpr_encode(out, 244, HPR_ECG, 3, 1, &stamp, samples, 2, 2, 128) == 24);
    assert(out[8] == 0 && out[9] == 0 && out[10] == 0 && out[11] == 0);
    assert(out[12] == 0xf7 && out[13] == 3); /* 1000 + floor(2000/128) = 1015 */
    int32_t temp = 3341;
    assert(hpr_encode(out, 20, HPR_TEMP, 3, 1, &stamp, &temp, 0, 1, 0) == 20);
    assert(hpr_encode(out, 20, HPR_TEMP, 3, 1, &stamp, &temp, 1, 1, 0) == 0);
    const uint32_t optical[] = {0, 4000000000u, 4294967295u};
    const uint8_t channels[] = {HPR_WRIST_RED, HPR_WRIST_IR, HPR_FINGER_RED};
    for (size_t i = 0; i < sizeof(channels); ++i) {
        uint8_t signal = channels[i];
        uint16_t rate = hpr_rate_hz(signal);
        assert(rate == (signal == HPR_FINGER_RED ? 100 : 25));
        assert(hpr_encode(out, sizeof(out), signal, 1, 42, &stamp, optical, 0, 3, rate) == 28);
        assert(out[1] == signal && out[2] == 1 && out[3] == 3);
        assert(out[20] == 0 && out[21] == 0x28 && out[22] == 0x6b && out[23] == 0xee);
        assert(out[24] == 0xff && out[27] == 0xff);
        /* MTU 23: second sample keeps the source batch's index/time offset. */
        assert(hpr_encode(out, 20, signal, 1, 42, &stamp, optical, 1, 1, rate) == 20);
        assert(out[8] == 0xff && out[11] == 0xff);
        uint32_t millis = 1000 + 1000 / rate;
        assert(out[12] == (uint8_t)millis && out[13] == (uint8_t)(millis >> 8));
    }
    assert(hpr_encode(out, sizeof(out), HPR_LAST_SIGNAL + 1, 1, 1, &stamp, optical, 0, 1, 25) == 0);
    puts("PASS: header, endian, signed values, MTU limits, splitting offsets, wrap and scalars");
    return 0;
}
