import cv2
import requests
import time
import math
import numpy as np

# ================= CONFIG =================

robot_ip = "172.20.10.6"
cam_url  = "http://172.20.10.7:81/stream"

# ================= ARUCO SETUP =================

aruco_dict     = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
aruco_params   = cv2.aruco.DetectorParameters()
aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

# ================= CAMERA =================

cap = cv2.VideoCapture(cam_url, cv2.CAP_FFMPEG)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

# ================= CONSTANTS =================

CENTER_ZONE    = 0.20    # fraction of frame width = "centered"
STOP_AREA      = 18000   # marker pixel area = bot is close enough
CMD_INTERVAL   = 0.15    # seconds between motor commands
MIN_OBJECT_AREA = 3000   # min contour area to count as real object

# How long (seconds) ArUco tracking can run without finding the marker
# before we give up and reverse back
ARUCO_TIMEOUT  = 8.0

# How many times to retry before giving up completely
MAX_RETRIES    = 3

# ================= STATE =================

phase          = "scan_object"
target_id      = None
detected_text  = ""
main_text      = "SCANNING FOR OBJECT..."
animation      = 0
last_cmd_time  = 0
movement_sent  = False

# Move log: list of (direction, duration_ms)
# Each entry is one timed command sent to the bot during aruco_track
move_log       = []

# Timestamp of the last time we saw the target marker
last_seen_time = None

# Retry counter
retry_count    = 0

# ================= HELPERS =================

def send(path):
    """Non-blocking HTTP request to the main ESP32 bot."""
    try:
        requests.get(f"http://{robot_ip}{path}", timeout=0.4)
    except:
        pass


def send_timed_move(direction, duration_ms):
    """
    Send a timed move to the bot via /aruco_move.
    The ESP32 will run the motor for duration_ms then stop itself.
    Also logs the move so we can reverse it later.
    """
    try:
        requests.get(
            f"http://{robot_ip}/aruco_move?dir={direction}&ms={duration_ms}",
            timeout=(duration_ms / 1000.0) + 1.0   # wait for it to finish
        )
    except:
        pass

    move_log.append((direction, duration_ms))


def reverse_moves():
    """
    Replay move_log in reverse, with opposite directions.
    forward <-> back,  left <-> right
    """
    opposite = {
        "forward": "back",
        "back":    "forward",
        "left":    "right",
        "right":   "left",
    }

    for direction, duration_ms in reversed(move_log):
        rev_dir = opposite.get(direction, "stop")
        send_timed_move.__wrapped__(rev_dir, duration_ms)   # bypass logging


# Unwrapped version used internally so reverse moves don't get logged
def _raw_timed_move(direction, duration_ms):
    try:
        requests.get(
            f"http://{robot_ip}/aruco_move?dir={direction}&ms={duration_ms}",
            timeout=(duration_ms / 1000.0) + 1.0
        )
    except:
        pass


def reverse_moves():
    """Replay move_log in reverse with opposite directions."""
    opposite = {
        "forward": "back",
        "back":    "forward",
        "left":    "right",
        "right":   "left",
    }
    for direction, duration_ms in reversed(move_log):
        rev_dir = opposite.get(direction, "stop")
        _raw_timed_move(rev_dir, duration_ms)


def detect_shape(contour):
    peri     = cv2.arcLength(contour, True)
    approx   = cv2.approxPolyDP(contour, 0.04 * peri, True)
    area     = cv2.contourArea(contour)
    vertices = len(approx)

    if area < MIN_OBJECT_AREA:
        return None

    if vertices == 4:
        x, y, cw, ch = cv2.boundingRect(approx)
        ratio = cw / float(ch)
        if 0.85 <= ratio <= 1.15:
            return "square"
        else:
            return "unknown"

    if peri > 0:
        circularity = (4 * math.pi * area) / (peri * peri)
        if circularity > 0.75:
            return "circle"

    return "unknown"


def marker_area(corners):
    c  = corners[0]
    mw = np.linalg.norm(c[0] - c[1])
    mh = np.linalg.norm(c[1] - c[2])
    return mw * mh


def marker_center_x(corners):
    c = corners[0]
    return float(np.mean(c[:, 0]))


# ================= WINDOW =================

cv2.namedWindow("WAREHOUSE AI", cv2.WINDOW_NORMAL)
cv2.resizeWindow("WAREHOUSE AI", 1200, 750)

# ================= MAIN LOOP =================

while True:

    ret, frame = cap.read()
    if not ret:
        continue

    frame = cv2.resize(frame, (1200, 750))
    fh, fw, _ = frame.shape

    animation += 1
    pulse = int(25 * math.sin(animation * 0.1))

    # =========================================================
    # PHASE 1 — detect object shape from camera
    # =========================================================

    if phase == "scan_object":

        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        _, thresh = cv2.threshold(blurred, 60, 255, cv2.THRESH_BINARY_INV)

        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        best_shape   = None
        best_contour = None
        best_area    = 0

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > best_area:
                shape = detect_shape(cnt)
                if shape is not None:
                    best_area    = area
                    best_shape   = shape
                    best_contour = cnt

        if best_contour is not None:

            cv2.drawContours(frame, [best_contour], -1, (0, 255, 0), 3)

            M  = cv2.moments(best_contour)
            cx = int(M["m10"] / M["m00"]) if M["m00"] != 0 else fw // 2
            cy = int(M["m01"] / M["m00"]) if M["m00"] != 0 else fh // 2

            cv2.circle(frame, (cx, cy), 8, (0, 0, 255), -1)

            if best_shape == "circle":
                detected_text = "CIRCLE DETECTED"
                main_text     = "CIRCLE -> ID 1"
                target_id     = 1
                send("/setstatus?val=DETECTED CIRCLE")

            elif best_shape == "square":
                detected_text = "SQUARE DETECTED"
                main_text     = "SQUARE -> ID 2"
                target_id     = 2
                send("/setstatus?val=DETECTED SQUARE")

            else:
                detected_text = "UNKNOWN DETECTED"
                main_text     = "UNKNOWN -> ID 3"
                target_id     = 3
                send("/setstatus?val=DETECTED UNKNOWN")

            cv2.putText(
                frame, best_shape.upper(),
                (cx - 40, cy - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (0, 255, 255), 2
            )

            phase         = "do_movement"
            movement_sent = False

        else:
            main_text = "SCANNING FOR OBJECT..."

    # =========================================================
    # PHASE 2 — trigger bot's pre-programmed movement
    # =========================================================

    elif phase == "do_movement":

        if not movement_sent:

            if target_id == 1:
                send("/id1")
            elif target_id == 2:
                send("/id2")
            elif target_id == 3:
                send("/id3")

            movement_sent  = True
            main_text      = f"BOT DOING MOVEMENT FOR ID {target_id}..."

        try:
            status = requests.get(
                f"http://{robot_ip}/status",
                timeout=0.3
            ).text
        except:
            status = ""

        if "HOME" in status or "REACHED" in status:

            # Reset ArUco tracking state
            move_log.clear()
            last_seen_time = time.time()
            retry_count    = 0

            main_text = "MOVEMENT DONE — STARTING ARUCO TRACK"
            phase     = "aruco_track"

    # =========================================================
    # PHASE 3 — ArUco tracking with move logging + timeout reverse
    # =========================================================

    elif phase == "aruco_track":

        corners_list, ids, _ = aruco_detector.detectMarkers(frame)

        found_target = False

        if ids is not None:

            for i, marker_id in enumerate(ids.flatten()):

                if marker_id == target_id:

                    found_target   = True
                    last_seen_time = time.time()   # reset timeout

                    cx   = marker_center_x(corners_list[i])
                    area = marker_area(corners_list[i])

                    cv2.aruco.drawDetectedMarkers(
                        frame,
                        [corners_list[i]],
                        np.array([[marker_id]])
                    )

                    cv2.putText(
                        frame,
                        f"AREA:{int(area)}",
                        (int(cx) - 40, fh // 2 - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 0), 2
                    )

                    cv2.circle(frame, (int(cx), fh // 2), 8, (0, 255, 0), -1)

                    # ---- STOP if close enough ----
                    if area >= STOP_AREA:

                        send("/aruco?dir=stop")
                        send(f"/setstatus?val=ID {target_id} REACHED")

                        main_text = f"ID {target_id} REACHED!"
                        phase     = "done"

                    else:

                        left_bound  = fw * (0.5 - CENTER_ZONE / 2)
                        right_bound = fw * (0.5 + CENTER_ZONE / 2)

                        if cx < left_bound:
                            direction = "left"
                            main_text = f"ARUCO ID{target_id}  <<< GO LEFT"

                        elif cx > right_bound:
                            direction = "right"
                            main_text = f"ARUCO ID{target_id}  GO RIGHT >>>"

                        else:
                            direction = "forward"
                            main_text = f"ARUCO ID{target_id}  ^ FORWARD ^"

                        # Send timed move and log it
                        if time.time() - last_cmd_time > CMD_INTERVAL:
                            dur_ms = int(CMD_INTERVAL * 1000)
                            send_timed_move(direction, dur_ms)
                            last_cmd_time = time.time()

                    break

        # ---- Marker not visible ----
        if not found_target:

            elapsed = time.time() - last_seen_time

            # Still within search window — spin slowly to look
            if elapsed < ARUCO_TIMEOUT:

                remaining = int(ARUCO_TIMEOUT - elapsed)
                main_text = (
                    f"SEARCHING ARUCO ID {target_id}... "
                    f"TIMEOUT IN {remaining}s"
                )

                if time.time() - last_cmd_time > CMD_INTERVAL:
                    dur_ms = int(CMD_INTERVAL * 1000)
                    send_timed_move("right", dur_ms)
                    last_cmd_time = time.time()

            # Timed out — reverse all moves and retry
            else:

                retry_count += 1

                if retry_count <= MAX_RETRIES:

                    main_text = (
                        f"TIMEOUT! REVERSING... "
                        f"(RETRY {retry_count}/{MAX_RETRIES})"
                    )

                    send("/aruco?dir=stop")

                    # Reverse every move made so far
                    reverse_moves()

                    # Clear log and restart tracking
                    move_log.clear()
                    last_seen_time = time.time()
                    last_cmd_time  = time.time()

                    main_text = (
                        f"REVERSED — RETRYING ARUCO ID {target_id} "
                        f"({retry_count}/{MAX_RETRIES})"
                    )

                else:

                    # All retries exhausted
                    send("/aruco?dir=stop")
                    send("/setstatus?val=ARUCO FAILED")

                    main_text = f"ARUCO ID {target_id} NOT FOUND — GIVING UP"
                    phase     = "failed"

    # =========================================================
    # PHASE 4 — done
    # =========================================================

    elif phase == "done":
        main_text = f"ID {target_id} REACHED!  MISSION COMPLETE"

    # =========================================================
    # PHASE 5 — failed (all retries exhausted)
    # =========================================================

    elif phase == "failed":
        main_text = f"FAILED TO REACH ID {target_id}  — PRESS R TO RETRY"

    # =========================================================
    # DRAW UI
    # =========================================================

    # Top bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (1200, 150), (20, 20, 20), -1)
    frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

    # Main status
    cv2.putText(
        frame, main_text,
        (30, 70),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0,
        (0, 255, 255), 3
    )

    # Detected object label
    cv2.putText(
        frame, detected_text,
        (30, 120),
        cv2.FONT_HERSHEY_SIMPLEX, 0.9,
        (0, 255, 0), 2
    )

    # Phase badge
    phase_color = {
        "scan_object":  (0, 200, 255),
        "do_movement":  (255, 165, 0),
        "aruco_track":  (0, 255, 100),
        "done":         (100, 255, 0),
        "failed":       (0, 0, 255),
    }.get(phase, (255, 255, 255))

    cv2.putText(
        frame, f"PHASE: {phase.upper()}",
        (820, 50),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7,
        phase_color, 2
    )

    # Retry counter (shown during aruco_track)
    if phase == "aruco_track" and retry_count > 0:
        cv2.putText(
            frame, f"RETRIES: {retry_count}/{MAX_RETRIES}",
            (820, 90),
            cv2.FONT_HERSHEY_SIMPLEX, 0.65,
            (255, 100, 0), 2
        )

    # Centre crosshair
    cv2.line(frame, (fw // 2, 0),    (fw // 2, fh),   (80, 80, 80), 1)
    cv2.line(frame, (0, fh // 2),    (fw, fh // 2),   (80, 80, 80), 1)

    # Left / right zone lines
    lz = int(fw * (0.5 - CENTER_ZONE / 2))
    rz = int(fw * (0.5 + CENTER_ZONE / 2))
    cv2.line(frame, (lz, 0), (lz, fh), (0, 100, 255), 1)
    cv2.line(frame, (rz, 0), (rz, fh), (0, 100, 255), 1)

    # Scanning box (only during object scan)
    if phase == "scan_object":
        size = 240
        x1 = fw // 2 - size // 2
        y1 = fh // 2 - size // 2
        x2 = x1 + size
        y2 = y1 + size

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255 - pulse, 255), 3)

        scan_y = y1 + (animation % size)
        cv2.line(frame, (x1, scan_y), (x2, scan_y), (0, 255, 0), 2)

        cv2.putText(
            frame, "SCANNING...",
            (x1, y1 - 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8,
            (0, 255, 255), 2
        )

    # ESP32-CAM badge
    cv2.rectangle(frame, (850, 20), (1180, 120), (0, 255, 255), 3)
    cv2.putText(
        frame, "ESP32-CAM LIVE",
        (900, 90),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8,
        (255, 255, 255), 2
    )

    cv2.imshow("WAREHOUSE AI", frame)

    key = cv2.waitKey(1)

    if key == 27:           # ESC — quit
        break

    if key == ord('r'):     # R — full reset
        phase          = "scan_object"
        detected_text  = ""
        main_text      = "SCANNING FOR OBJECT..."
        target_id      = None
        movement_sent  = False
        move_log.clear()
        retry_count    = 0
        last_seen_time = None
        send("/setstatus?val=READY")

# ================= END =================

cap.release()
cv2.destroyAllWindows()
