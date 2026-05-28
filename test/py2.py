import cv2
import requests
import time
import math
import numpy as np

# ================= ESP =================

robot_ip = "172.20.10.6"

cam_url = "http://172.20.10.7:81/stream"

# ================= ARUCO SETUP =================

aruco_dict   = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
aruco_params = cv2.aruco.DetectorParameters()
aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

# ================= CAMERA =================

cap = cv2.VideoCapture(
    cam_url,
    cv2.CAP_FFMPEG
)

cap.set(
    cv2.CAP_PROP_BUFFERSIZE,
    1
)

# ================= VARIABLES =================

main_text     = "WAITING..."
detected_text = ""
status_time   = 0
animation     = 0

# Phase: "detect_object" -> "aruco_track" -> "done"
phase = "detect_object"

# Which ArUco ID we are targeting (1, 2, or 3)
target_id = None

# Cooldown so we don't spam HTTP requests
last_cmd_time = 0
CMD_INTERVAL  = 0.15   # seconds between motor commands

# How large the marker must be (px area) before we stop
STOP_AREA = 18000

# Dead-zone: fraction of frame width where we consider marker "centered"
CENTER_ZONE = 0.20

# ================= HELPERS =================

def send_cmd(path):
    """Fire-and-forget HTTP request to ESP32."""
    try:
        requests.get(
            f"http://{robot_ip}{path}",
            timeout=0.3
        )
    except:
        pass


def marker_area(corners):
    """Return pixel area of a detected ArUco marker."""
    c = corners[0]
    w = np.linalg.norm(c[0] - c[1])
    h = np.linalg.norm(c[1] - c[2])
    return w * h


def marker_center_x(corners):
    """Return the X centre of a detected ArUco marker."""
    c = corners[0]
    return float(np.mean(c[:, 0]))


# ================= WINDOW =================

cv2.namedWindow(
    "WAREHOUSE AI",
    cv2.WINDOW_NORMAL
)

cv2.resizeWindow(
    "WAREHOUSE AI",
    1200,
    750
)

# ================= MAIN LOOP =================

while True:

    ret, frame = cap.read()

    if not ret:
        continue

    frame = cv2.resize(frame, (1200, 750))

    h, w, _ = frame.shape

    animation += 1

    pulse = int(25 * math.sin(animation * 0.1))

    # =========================================================
    # PHASE 1 — wait for object detection from ESP32
    # =========================================================

    if phase == "detect_object":

        if time.time() - status_time > 0.2:

            try:

                response = requests.get(
                    f"http://{robot_ip}/status",
                    timeout=0.2
                )

                status = response.text

                # ---- CIRCLE ----
                if status == "DETECTED CIRCLE":

                    detected_text = "CIRCLE DETECTED"
                    main_text     = "CIRCLE -> ID 1"
                    target_id     = 1
                    phase         = "aruco_track"

                # ---- SQUARE ----
                elif status == "DETECTED SQUARE":

                    detected_text = "SQUARE DETECTED"
                    main_text     = "SQUARE -> ID 2"
                    target_id     = 2
                    phase         = "aruco_track"

                # ---- UNKNOWN / CUBE ----
                elif status in ("DETECTED UNKNOWN", "DETECTED CUBE"):

                    detected_text = "UNKNOWN DETECTED"
                    main_text     = "UNKNOWN -> ID 3"
                    target_id     = 3
                    phase         = "aruco_track"

                elif "GOING TO" in status:

                    main_text = status

            except:
                pass

            status_time = time.time()

    # =========================================================
    # PHASE 2 — ArUco tracking
    # =========================================================

    elif phase == "aruco_track":

        # Detect all ArUco markers in the current frame
        corners_list, ids, _ = aruco_detector.detectMarkers(frame)

        found_target = False

        if ids is not None:

            for i, marker_id in enumerate(ids.flatten()):

                if marker_id == target_id:

                    found_target = True

                    cx   = marker_center_x(corners_list[i])
                    area = marker_area(corners_list[i])

                    # Draw the marker on screen
                    cv2.aruco.drawDetectedMarkers(frame, [corners_list[i]], np.array([[marker_id]]))

                    # ---- STOP if close enough ----
                    if area >= STOP_AREA:

                        if time.time() - last_cmd_time > CMD_INTERVAL:
                            send_cmd("/aruco?dir=stop")
                            last_cmd_time = time.time()

                        main_text = f"ID {target_id} REACHED!"
                        phase     = "done"

                    else:

                        # Decide direction
                        left_bound  = w * (0.5 - CENTER_ZONE / 2)
                        right_bound = w * (0.5 + CENTER_ZONE / 2)

                        if cx < left_bound:

                            direction = "left"
                            main_text = f"ARUCO ID{target_id}  <<< GO LEFT"

                        elif cx > right_bound:

                            direction = "right"
                            main_text = f"ARUCO ID{target_id}  GO RIGHT >>>"

                        else:

                            direction = "forward"
                            main_text = f"ARUCO ID{target_id}  ^ FORWARD ^"

                        if time.time() - last_cmd_time > CMD_INTERVAL:
                            send_cmd(f"/aruco?dir={direction}")
                            last_cmd_time = time.time()

                    # Draw centre dot
                    cv2.circle(
                        frame,
                        (int(cx), h // 2),
                        8,
                        (0, 255, 0),
                        -1
                    )

                    # Draw area text on marker
                    cv2.putText(
                        frame,
                        f"AREA:{int(area)}",
                        (int(cx) - 40, h // 2 - 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 0),
                        2
                    )

                    break   # only track the first match

        if not found_target:

            # Marker not visible — spin slowly to search
            main_text = f"SEARCHING ID {target_id}..."

            if time.time() - last_cmd_time > CMD_INTERVAL:
                send_cmd("/aruco?dir=right")
                last_cmd_time = time.time()

    # =========================================================
    # PHASE 3 — done
    # =========================================================

    elif phase == "done":

        main_text = f"ID {target_id} REACHED! DONE"

    # =========================================================
    # DRAW UI
    # =========================================================

    # Top bar background
    overlay = frame.copy()

    cv2.rectangle(
        overlay,
        (0, 0),
        (1200, 150),
        (20, 20, 20),
        -1
    )

    frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

    # Main status text
    cv2.putText(
        frame,
        main_text,
        (30, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (0, 255, 255),
        3
    )

    # Detected object text
    cv2.putText(
        frame,
        detected_text,
        (30, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 0),
        2
    )

    # Phase indicator (top-right)
    phase_color = {
        "detect_object": (0, 200, 255),
        "aruco_track":   (0, 255, 100),
        "done":          (100, 255, 0),
    }.get(phase, (255, 255, 255))

    cv2.putText(
        frame,
        f"PHASE: {phase.upper()}",
        (820, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        phase_color,
        2
    )

    # Centre crosshair (helps judge alignment)
    cv2.line(frame, (w // 2, 0),      (w // 2, h),      (80, 80, 80), 1)
    cv2.line(frame, (0,      h // 2), (w,      h // 2), (80, 80, 80), 1)

    # Left / right zone markers
    lz = int(w * (0.5 - CENTER_ZONE / 2))
    rz = int(w * (0.5 + CENTER_ZONE / 2))

    cv2.line(frame, (lz, 0), (lz, h), (0, 100, 255), 1)
    cv2.line(frame, (rz, 0), (rz, h), (0, 100, 255), 1)

    # Scanning box (only while waiting for object)
    if phase == "detect_object":

        size = 240
        x1 = w // 2 - size // 2
        y1 = h // 2 - size // 2
        x2 = x1 + size
        y2 = y1 + size

        color = (0, 255 - pulse, 255)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)

        scan_y = y1 + (animation % size)

        cv2.line(frame, (x1, scan_y), (x2, scan_y), (0, 255, 0), 2)

        cv2.putText(
            frame,
            "SCANNING...",
            (x1, y1 - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2
        )

    # ESP32-CAM badge
    cv2.rectangle(frame, (850, 20), (1180, 120), (0, 255, 255), 3)

    cv2.putText(
        frame,
        "ESP32-CAM LIVE",
        (900, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )

    # ================= SHOW =================

    cv2.imshow("WAREHOUSE AI", frame)

    key = cv2.waitKey(1)

    if key == 27:   # ESC to quit
        break

    # Press 'r' to reset back to detect_object phase
    if key == ord('r'):
        phase         = "detect_object"
        detected_text = ""
        main_text     = "WAITING..."
        target_id     = None

# ================= END =================

cap.release()
cv2.destroyAllWindows()
