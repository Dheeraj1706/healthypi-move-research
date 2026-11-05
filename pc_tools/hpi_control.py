"""
HealthyPi Move command interface (firmware v2.x legacy CMD service).

The v2.x firmware exposes a write characteristic whose handler is
`hpi_decode_data_packet(buf, len)` with `buf[0]` = opcode -- so a command is
just its opcode byte followed by its arguments, written with-response or
without. Responses arrive as notifications on the RX characteristic, framed as
`[CES_CMDIF_TYPE_CMD_RSP=0x06][opcode][status...]`.

Source: app/src/cmd_module.{c,h}, app/src/recording_module.h at tag v2.1.1.
This service was REMOVED in firmware v3.x (replaced by the HPI_HS MCUmgr group
0x1000), so probe for it rather than assuming it exists.
"""

# --- Legacy command service ---------------------------------------------------
UUID_CMD_SERVICE = "01bf7492-970f-8d96-d44d-9023c47faddc"
UUID_CMD_TX      = "01bf1528-970f-8d96-d44d-9023c47faddc"  # host -> watch (write)
UUID_CMD_RX      = "01bf1527-970f-8d96-d44d-9023c47faddc"  # watch -> host (notify)

# --- Opcodes (enum hpi_cmds) --------------------------------------------------
CMD_GET_DEVICE_STATUS   = 0x40
CMD_SET_DEVICE_TIME     = 0x41
CMD_DEVICE_RESET        = 0x42

CMD_REC_CONFIGURE       = 0x70  # [dur_lo][dur_hi][signal_mask][decimation]
CMD_REC_START           = 0x71
CMD_REC_STOP            = 0x72
CMD_REC_GET_STATUS      = 0x73
CMD_REC_GET_SESSION_LIST = 0x74
CMD_REC_DELETE_SESSION  = 0x75
CMD_REC_WIPE_ALL        = 0x76

RSP_TYPE_CMD_RSP        = 0x06

# --- Recording signal mask (recording_module.h) -------------------------------
REC_SIGNAL_PPG_WRIST  = 1 << 0   # wrist PPG (IR, Red, Green) @ 25 Hz
REC_SIGNAL_PPG_FINGER = 1 << 1   # finger PPG (IR, Red) @ 25 Hz
REC_SIGNAL_IMU_ACCEL  = 1 << 2   # 3-axis accelerometer @ 100 Hz
REC_SIGNAL_IMU_GYRO   = 1 << 3   # 3-axis gyroscope @ 100 Hz
REC_SIGNAL_GSR        = 1 << 4   # GSR / EDA @ 32 Hz
REC_SIGNAL_ALL = (REC_SIGNAL_PPG_WRIST | REC_SIGNAL_PPG_FINGER |
                  REC_SIGNAL_IMU_ACCEL | REC_SIGNAL_IMU_GYRO | REC_SIGNAL_GSR)

SIGNAL_MASK_NAMES = {
    "ppg_wrist":  REC_SIGNAL_PPG_WRIST,
    "ppg_finger": REC_SIGNAL_PPG_FINGER,
    "accel":      REC_SIGNAL_IMU_ACCEL,
    "gyro":       REC_SIGNAL_IMU_GYRO,
    "gsr":        REC_SIGNAL_GSR,
}

REC_START_STATUS = {0: "started", 1: "already recording",
                    2: "not configured / error"}
REC_STOP_STATUS = {0: "stopped", 1: "error (was not recording?)"}
REC_STATE = {0: "idle", 1: "configured", 2: "recording",
             3: "stopping", 4: "error"}


def mask_from_names(names):
    """['gsr','accel'] -> integer bitmask. Raises on an unknown name."""
    mask = 0
    for n in names:
        key = n.strip().lower()
        if key not in SIGNAL_MASK_NAMES:
            raise ValueError("unknown recording signal %r; known: %s"
                             % (n, sorted(SIGNAL_MASK_NAMES)))
        mask |= SIGNAL_MASK_NAMES[key]
    return mask


def names_from_mask(mask):
    return [n for n, bit in sorted(SIGNAL_MASK_NAMES.items()) if mask & bit]


# --- Frame builders -----------------------------------------------------------

REC_MAX_DURATION_S = 3600  # recording_module.c: hpi_recording_configure()


def frame_configure(duration_s, signal_mask, decimation=1):
    """[0x70][dur_lo][dur_hi][signal_mask][decimation].

    Firmware validation (recording_module.c:187): duration_s must be in
    1..3600 -- 0 is rejected as REC_ERR_INVALID_CONFIG, so there is no
    open-ended mode. signal_mask must be non-zero and within REC_SIGNAL_ALL.
    decimation 0 is silently coerced to 1.
    """
    if not 1 <= duration_s <= REC_MAX_DURATION_S:
        raise ValueError("duration_s must be 1..%d (0 is rejected by firmware)"
                         % REC_MAX_DURATION_S)
    if signal_mask == 0 or (signal_mask & ~REC_SIGNAL_ALL):
        raise ValueError("signal_mask must be non-zero and within REC_SIGNAL_ALL")
    return bytes([CMD_REC_CONFIGURE,
                  duration_s & 0xFF, (duration_s >> 8) & 0xFF,
                  signal_mask & 0xFF, decimation & 0xFF])


def frame_start():
    return bytes([CMD_REC_START])


def frame_stop():
    return bytes([CMD_REC_STOP])


def frame_get_status():
    return bytes([CMD_REC_GET_STATUS])


def frame_device_status():
    return bytes([CMD_GET_DEVICE_STATUS])


# --- Response parsing ---------------------------------------------------------

def parse_response(payload):
    """Decode a CMD RX notification into a dict. Returns None if not a cmd rsp."""
    if len(payload) < 2 or payload[0] != RSP_TYPE_CMD_RSP:
        return {"type": "unknown", "raw": payload.hex()}

    opcode = payload[1]
    out = {"type": "cmd_rsp", "opcode": opcode, "raw": payload.hex()}

    if opcode in (CMD_REC_CONFIGURE, CMD_REC_START, CMD_REC_STOP,
                  CMD_REC_DELETE_SESSION, CMD_REC_WIPE_ALL):
        status = payload[2] if len(payload) > 2 else None
        out["status"] = status
        if opcode == CMD_REC_START:
            out["meaning"] = REC_START_STATUS.get(status, "unknown")
        elif opcode == CMD_REC_STOP:
            out["meaning"] = REC_STOP_STATUS.get(status, "unknown")
        else:
            out["meaning"] = "ok" if status == 0 else "error"

    elif opcode == CMD_REC_GET_STATUS and len(payload) >= 8:
        # [06][73][state][elapsed_lo][elapsed_hi][remain_lo][remain_hi][mask]
        out["state"] = payload[2]
        out["state_name"] = REC_STATE.get(payload[2], "unknown(%d)" % payload[2])
        out["elapsed_s"] = payload[3] | (payload[4] << 8)
        out["remaining_s"] = payload[5] | (payload[6] << 8)
        out["signal_mask"] = payload[7]
        out["signals"] = names_from_mask(payload[7])

    return out
