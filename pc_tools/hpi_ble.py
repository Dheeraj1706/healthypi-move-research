"""
HealthyPi Move BLE definitions and decoders.

Derived from firmware source: app/src/ble_module.c, app/src/data_module.c
(Protocentral/healthypi-move-fw). All waveform characteristics carry a packed
array of little-endian 32-bit samples with NO header, NO timestamp and NO
sequence number -- sample count = len(payload) // 4.
"""

DEVICE_NAME = "healthypi move"

# --- Custom waveform services -------------------------------------------------
UUID_ECG_GSR_SERVICE = "00001122-0000-1000-8000-00805f9b34fb"
UUID_ECG_CHAR        = "00001424-0000-1000-8000-00805f9b34fb"
UUID_GSR_CHAR        = "babe4a4c-7789-11ed-a1eb-0242ac120002"

UUID_PPG_SERVICE     = "cd5c7491-4448-7db8-ae4c-d1da8cba36d0"
UUID_PPG_WRIST_CHAR  = "cd5c1525-4448-7db8-ae4c-d1da8cba36d0"
UUID_PPG_FINGER_CHAR = "cd5ca86f-4448-7db8-ae4c-d1da8cba36d0"

# --- Standard SIG services (fed from zbus in ble_module.c) ---------------------
UUID_HR_MEASUREMENT  = "00002a37-0000-1000-8000-00805f9b34fb"  # HRS 0x180D
UUID_BATTERY_LEVEL   = "00002a19-0000-1000-8000-00805f9b34fb"  # BAS 0x180F
UUID_PLX_SPOT_CHECK  = "00002a5e-0000-1000-8000-00805f9b34fb"  # PLX 0x1822 (SpO2)
UUID_TEMP_MEASURE    = "00002a1c-0000-1000-8000-00805f9b34fb"  # HTS Temp Measurement
UUID_TEMPERATURE     = "00002a6e-0000-1000-8000-00805f9b34fb"  # HTS Temperature (0x2A6E)
# NOTE: the firmware declares HPI_TEMP_CHAR as BT_UUID_TEMPERATURE_VAL = 0x2A6E,
# v3.1.0 exposes this as read/indicate (Bleak start_notify handles both). Newer source
# formats the payload like an HTS Temperature Measurement (flags + float32),
# older builds use the plain 0x2A6E sint16 in 0.01 degC. decode_temperature()
# below accepts both by length.


class Signal:
    """One acquirable signal: how to subscribe to it and how to decode it."""

    def __init__(self, key, label, uuid, rate_hz, sample_fmt, unit, notes=""):
        self.key = key
        self.label = label
        self.uuid = uuid.lower()
        self.rate_hz = rate_hz
        self.sample_fmt = sample_fmt   # 'i32' | 'u32' | 'special'
        self.unit = unit
        self.notes = notes

    def decode(self, payload: bytes):
        """Return a list of numeric samples from one BLE notification."""
        if not payload or len(payload) % 4:
            raise ValueError("waveform length must be a positive multiple of four")
        if self.sample_fmt == "i32":
            n = len(payload) // 4
            return [int.from_bytes(payload[i * 4:i * 4 + 4], "little", signed=True)
                    for i in range(n)]
        if self.sample_fmt == "u32":
            n = len(payload) // 4
            return [int.from_bytes(payload[i * 4:i * 4 + 4], "little", signed=False)
                    for i in range(n)]
        raise NotImplementedError(self.sample_fmt)


# Waveform signals -- continuous, packed 32-bit arrays.
WAVEFORM_SIGNALS = [
    Signal("ecg", "ECG", UUID_ECG_CHAR, 128, "i32", "adc",
           "MAX30001. Batches of 8 -> ~16 notifications/s."),
    Signal("gsr", "GSR / BioZ", UUID_GSR_CHAR, 32, "i32", "adc",
           "MAX30001 BioZ. Polled ~16 Hz to avoid FIFO overflow."),
    Signal("ppg_wrist", "PPG Wrist (green)", UUID_PPG_WRIST_CHAR, 25, "u32", "adc",
           "MAX32664C raw_green."),
    Signal("ppg_finger", "PPG Finger (IR)", UUID_PPG_FINGER_CHAR, 100, "u32", "adc",
           "MAX32664D raw_ir."),
]

WAVEFORMS_BY_UUID = {s.uuid: s for s in WAVEFORM_SIGNALS}
WAVEFORMS_BY_KEY = {s.key: s for s in WAVEFORM_SIGNALS}


def decode_hr(payload: bytes):
    """Heart Rate Measurement (0x2A37). Returns bpm."""
    if len(payload) < 2:
        return None
    flags = payload[0]
    if flags & 1 and len(payload) < 3:
        return None
    if flags & 0x01:                      # 16-bit HR value
        return int.from_bytes(payload[1:3], "little")
    return payload[1]


def decode_battery(payload: bytes):
    return payload[0] if payload else None


def _sfloat(raw: int):
    """IEEE-11073 16-bit SFLOAT. Firmware writes exponent 0, 12-bit mantissa."""
    if raw in (0x07FF, 0x07FE, 0x0800, 0x0801, 0x0802):                     # NaN
        return None
    mantissa = raw & 0x0FFF
    exponent = (raw >> 12) & 0x0F
    if mantissa >= 0x0800:
        mantissa -= 0x1000
    if exponent >= 0x08:
        exponent -= 0x10
    return mantissa * (10 ** exponent)


def decode_spo2(payload: bytes):
    """PLX Spot-check Measurement (0x2A5E). Returns dict with spo2 % and pr bpm."""
    if len(payload) < 5:
        return None
    flags = payload[0]
    spo2 = _sfloat(int.from_bytes(payload[1:3], "little"))
    pr = _sfloat(int.from_bytes(payload[3:5], "little"))
    return {"spo2": spo2, "pulse_rate": pr,
            "timestamp_present": bool(flags & 0x01),
            "device_clock_unset": bool(flags & 0x10)}


def decode_temperature(payload: bytes):
    """Skin temperature in degrees C.

    Two wire formats are in the wild for this device:
      * 2 bytes -- plain 0x2A6E Temperature, sint16 in units of 0.01 degC.
      * 5 bytes -- HTS Temperature Measurement: flags + IEEE-11073 FLOAT32.
    """
    if len(payload) == 2:
        raw = int.from_bytes(payload[0:2], "little", signed=True)
        return raw / 100.0
    if len(payload) < 5:
        return None
    flags = payload[0]
    raw = int.from_bytes(payload[1:5], "little")
    mantissa = raw & 0x00FFFFFF
    if mantissa >= 0x00800000:
        mantissa -= 0x01000000
    exponent = (raw >> 24) & 0xFF
    if exponent >= 0x80:
        exponent -= 0x100
    value = mantissa * (10.0 ** exponent)
    if flags & 0x01:                      # Fahrenheit flag
        value = (value - 32.0) * 5.0 / 9.0
    return value


# Scalar/event signals -- low rate, standard SIG formats.
SCALAR_SIGNALS = {
    UUID_HR_MEASUREMENT: ("hr", "Heart Rate", "bpm", decode_hr),
    UUID_BATTERY_LEVEL:  ("battery", "Battery", "%", decode_battery),
    UUID_PLX_SPOT_CHECK: ("spo2", "SpO2 spot-check", "%", decode_spo2),
    UUID_TEMP_MEASURE:   ("temp", "Skin Temperature", "degC", decode_temperature),
    UUID_TEMPERATURE:    ("temp", "Skin Temperature", "degC", decode_temperature),
}
