import cv2
import requests
import time
import math
import numpy as np

# ================= ESP =================

robot_ip = "172.20.10.6"
cam_url  = "http://172.20.10.7:81/stream"

# ================= ARUCO =================

aruco_dict   = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
aruco_params = cv2.aruco.DetectorParameters()
aruco_det    = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

# ================= CAMERA =================

cap = cv2.VideoCapture(cam_url, cv2.CAP_FFMPEG)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

# ================= TUNING =================

FRAME_W         = 1200
FRAME_H         = 750
CENTER_X        = FRAME_W // 2

DEAD_ZONE       = 60      # px — within this offset = centered
STOP_AREA       = 18000   # px² — marker this big = close enough, stop
FOLLOW_SPEED    = 160     # base forward speed while following
TURN_BOOST      = 60      # extra speed added to faster wheel when turning

# ================= STATE =================

main_text       = "WAITING..."
detected_text   = ""
status_time     = 0
shape_sent      = False          # have we told the bot about the object yet?
following       = False          # are we in ArUco-follow mode?
target_id       = None           # which ArUco ID we are chasing (1, 2, or 3)
last_drive_time = 0

# ================= HTTP HELPERS =================

def send(path, timeout=0.3):
    try:
        requests.get(f"http://{robot_ip}{path}", timeout=timeout)
    except Exception:
        pass

def drive(l, r):
    send(f"/drive?l={int(l)}&r={int(r)}")

def stop_bot():
    send("/stop")

# ================= SHAPE DETECTION =================

def detect_shape(frame):
    """
    Returns 'circle', 'square', or 'unknown' if an object is found
    in the center scan box, otherwise returns None.
    """
    size = 240
    x1 = CENTER_X - size // 2
    y1 = FRAME_H  // 2 - size // 2
    roi = frame[y1:y1+size, x1:x1+size]

    gray    = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)
    _, thresh = cv2.threshold(blurred, 60, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)

    if area < 1500:
        return None

    perimeter = cv2.arcLength(cnt, True)
    if perimeter == 0:
        return None

    circularity = 4 * math.pi * area / (perimeter * perimeter)

    approx = cv2.approxPolyDP(cnt, 0.04 * perimeter, True)
    vertices = len(approx)

    if circularity > 0.78:
        return "circle"
    elif 4 <= vertices <= 6:
        return "square"
    else:
        return "unknown"

# ================= ARUCO FOLLOW =================

def follow_aruco(corners, ids, frame):
    """
    Given detected ArUco corners + IDs, steer toward target_id.
    Returns (steering_label, marker_found).
    """
    global following, target_id

    if ids is None:
        return "SEARCHING...", False

    ids_flat = ids.flatten()

    # pick target if not set yet
    if target_id is None:
        if 1 in ids_flat:
            target_id = 1
        elif 2 in ids_flat:
            target_id = 2
        elif 3 in ids_flat:
            target_id = 3
        else:
            return "SEARCHING...", False

    # find matching marker
    for i, mid in enumerate(ids_flat):
        if mid != target_id:
            continue

        pts = corners[i][0]  # shape (4,2)

        # marker center
        mx = int(pts[:, 0].mean())
        my = int(pts[:, 1].mean())

        # marker area (approximate via bounding box)
        w = float(pts[:, 0].max() - pts[:, 0].min())
        h = float(pts[:, 1].max() - pts[:, 1].min())
        area = w * h

        # draw marker overlay
        cv2.polylines(frame, [pts.astype(np.int32)], True, (0, 255, 0), 2)
        cv2.circle(frame, (mx, my), 6, (0, 255, 0), -1)
        cv2.putText(frame, f"ID {mid}", (mx - 20, my - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # arrow from frame center to marker center
        cv2.arrowedLine(frame, (CENTER_X, FRAME_H // 2),
                        (mx, my), (0, 200, 255), 2, tipLength=0.2)

        offset = mx - CENTER_X

        # --- close enough → stop ---
        if area >= STOP_AREA:
            stop_bot()
            following = False
            return "STOP  ✓", True

        # --- steering ---
        if abs(offset) <= DEAD_ZONE:
            # straight
            drive(FOLLOW_SPEED, FOLLOW_SPEED)
            label = "FORWARD ↑"
        elif offset < 0:
            # marker is left of center → turn left
            drive(FOLLOW_SPEED - TURN_BOOST, FOLLOW_SPEED + TURN_BOOST)
            label = "◄ LEFT"
        else:
            # marker is right of center → turn right
            drive(FOLLOW_SPEED + TURN_BOOST, FOLLOW_SPEED - TURN_BOOST)
            label = "RIGHT ►"

        # offset bar (visual guide)
        bar_x1 = CENTER_X - 120
        bar_x2 = CENTER_X + 120
        bar_y  = FRAME_H - 60
        cv2.rectangle(frame, (bar_x1, bar_y - 6), (bar_x2, bar_y + 6),
                      (60, 60, 60), -1)
        indicator_x = int(CENTER_X + offset * 0.5)
        indicator_x = max(bar_x1, min(bar_x2, indicator_x))
        cv2.circle(frame, (indicator_x, bar_y), 10, (0, 255, 255), -1)
        cv2.line(frame, (CENTER_X, bar_y - 12), (CENTER_X, bar_y + 12),
                 (255, 255, 255), 1)

        return label, True

    return "SEARCHING...", False

# ================= WINDOW =================

cv2.namedWindow("WAREHOUSE AI", cv2.WINDOW_NORMAL)
cv2.resizeWindow("WAREHOUSE AI", FRAME_W, FRAME_H)

animation = 0

# ================= MAIN LOOP =================

while True:

    ret, frame = cap.read()
    if not ret:
        continue

    frame = cv2.resize(frame, (FRAME_W, FRAME_H))

    # ---- shape detection (only while we haven't sent a shape yet) ----

    if not shape_sent and not following:

        shape = detect_shape(frame)

        if shape:
            detected_text = f"{shape.upper()} DETECTED"
            main_text     = detected_text

            # tell the bot which ID to go to
            send(f"/shape?type={shape}")
            shape_sent = True
            following  = True   # switch to ArUco-follow mode

    # ---- ArUco following ----

    steering_label = ""

    if following:
        gray_frame    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = aruco_det.detectMarkers(gray_frame)

        now = time.time()
        if now - last_drive_time > 0.08:          # 12 Hz drive loop
            steering_label, found = follow_aruco(corners, ids, frame)
            last_drive_time = now

            if not found:
                # nothing visible — nudge forward slowly to search
                drive(90, 90)

        main_text = f"FOLLOWING ID {target_id}" if target_id else "SCANNING..."

    # ---- ESP status poll (only when not following to reduce traffic) ----

    if not following and time.time() - status_time > 0.25:
        try:
            resp   = requests.get(f"http://{robot_ip}/status", timeout=0.2)
            status = resp.text
            if "GOING TO" in status:
                main_text = status
        except Exception:
            pass
        status_time = time.time()

    # ---- OSD ----

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (FRAME_W, 155), (20, 20, 20), -1)
    frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

    cv2.putText(frame, main_text,      (30, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
    cv2.putText(frame, detected_text,  (30, 120),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0),   2)

    # steering direction label (big, bottom-center)
    if steering_label:
        color = (0, 255, 0) if "STOP" in steering_label else (0, 200, 255)
        cv2.putText(frame, steering_label,
                    (CENTER_X - 120, FRAME_H - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3)

    # scan box (only while waiting for object)
    if not shape_sent:
        animation += 1
        pulse  = int(25 * math.sin(animation * 0.1))
        size   = 240
        x1 = CENTER_X - size // 2
        y1 = FRAME_H  // 2 - size // 2
        color  = (0, 255 - pulse, 255)
        cv2.rectangle(frame, (x1, y1), (x1 + size, y1 + size), color, 3)
        scan_y = y1 + (animation % size)
        cv2.line(frame, (x1, scan_y), (x1 + size, scan_y), (0, 255, 0), 2)
        cv2.putText(frame, "SCANNING...", (x1, y1 - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    # live cam badge
    cv2.rectangle(frame, (850, 20), (1180, 120), (0, 255, 255), 3)
    cv2.putText(frame, "ESP32-CAM LIVE", (900, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    # reset button hint
    cv2.putText(frame, "R = reset  ESC = quit", (30, FRAME_H - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1)

    cv2.imshow("WAREHOUSE AI", frame)

    key = cv2.waitKey(1)
    if key == 27:                          # ESC → quit
        break
    elif key == ord('r') or key == ord('R'):  # R → reset state
        shape_sent    = False
        following     = False
        target_id     = None
        detected_text = ""
        main_text     = "WAITING..."
        stop_bot()

cap.release()
cv2.destroyAllWindows()
