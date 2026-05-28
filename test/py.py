import cv2
import requests
import time
import math
import numpy as np
import threading
from collections import deque

# ================================================================
#  SETTINGS — tweak these if needed
# ================================================================

ROBOT_IP     = "172.20.10.6"
CAM_URL      = "http://172.20.10.7:81/stream"

# Display window size (does NOT affect processing resolution)
WIN_W, WIN_H = 1200, 750

# ArUco is run on a downscaled copy for speed (faster detection)
ARUCO_W, ARUCO_H = 480, 320

# Shape detection scan-box size (pixels, in display coords)
SCAN_SIZE = 240

# How many CONSECUTIVE seconds the same shape must be seen before confirming
CONFIRM_SECONDS = 5.0

# ArUco steering
DEAD_ZONE    = 50     # px offset inside which bot goes straight
STOP_AREA    = 6000   # px² at ARUCO_W×ARUCO_H resolution → bot stops
FOLLOW_SPEED = 160    # base forward PWM
TURN_BOOST   = 65     # differential added to faster wheel

# ================================================================
#  CAMERA THREAD  — always reads the very latest frame,
#  never buffers old ones
# ================================================================

class CamStream:
    def __init__(self, url):
        self.cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame = None
        self.ok    = False
        self.lock  = threading.Lock()
        self._stop = False
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()

    def _reader(self):
        while not self._stop:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
                    self.ok    = True
            else:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.ok, self.frame.copy()

    def release(self):
        self._stop = True
        self.cap.release()

# ================================================================
#  HTTP — fire-and-forget so it never blocks the frame loop
# ================================================================

_http_lock  = threading.Lock()
_last_cmd   = ""

def send_async(path):
    """Send HTTP GET in a background thread (non-blocking)."""
    def _do():
        try:
            requests.get(f"http://{ROBOT_IP}{path}", timeout=0.4)
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

def drive(l, r):
    global _last_cmd
    cmd = f"/drive?l={int(l)}&r={int(r)}"
    with _http_lock:
        if cmd == _last_cmd:
            return          # don't spam identical commands
        _last_cmd = cmd
    send_async(cmd)

def stop_bot():
    global _last_cmd
    with _http_lock:
        _last_cmd = "/stop"
    send_async("/stop")

def send_shape(shape):
    send_async(f"/shape?type={shape}")

# ================================================================
#  ARUCO DETECTOR
# ================================================================

aruco_dict   = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
aruco_params = cv2.aruco.DetectorParameters()

# These two settings dramatically improve detection at distance/blur:
aruco_params.adaptiveThreshWinSizeMin  = 3
aruco_params.adaptiveThreshWinSizeMax  = 23
aruco_params.adaptiveThreshWinSizeStep = 4
aruco_params.minMarkerPerimeterRate    = 0.02   # detect smaller markers
aruco_params.maxMarkerPerimeterRate    = 4.0
aruco_params.polygonalApproxAccuracyRate = 0.04
aruco_params.cornerRefinementMethod   = cv2.aruco.CORNER_REFINE_SUBPIX

aruco_det = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

# ================================================================
#  SHAPE DETECTION
# ================================================================

def detect_shape_in_roi(roi):
    """
    Returns 'circle', 'square', 'unknown', or None (nothing found).
    roi is the scan-box crop from the display frame.
    """
    gray    = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 2)

    # Adaptive threshold is more robust to lighting than fixed threshold
    thresh = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        11, 4
    )

    # Remove tiny noise
    kernel  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    thresh  = cv2.morphologyEx(thresh, cv2.MORPH_OPEN,  kernel, iterations=1)
    thresh  = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    cnt  = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)

    # Must fill at least 8% of the scan box to count as a real object
    roi_area = roi.shape[0] * roi.shape[1]
    if area < roi_area * 0.08:
        return None

    perimeter = cv2.arcLength(cnt, True)
    if perimeter == 0:
        return None

    circularity = 4 * math.pi * area / (perimeter * perimeter)
    approx      = cv2.approxPolyDP(cnt, 0.03 * perimeter, True)
    vertices    = len(approx)

    if circularity > 0.75:
        return "circle"
    elif 4 <= vertices <= 7:
        return "square"
    else:
        return "unknown"

# ================================================================
#  STATE
# ================================================================

main_text     = "WAITING..."
detected_text = ""
shape_sent    = False
following     = False
target_id     = None          # ArUco ID to chase

# Confirmation state: shape must appear for CONFIRM_SECONDS straight
confirm_shape     = None      # currently accumulating shape
confirm_start     = 0.0       # when we first saw confirm_shape
confirm_progress  = 0.0       # 0.0 → 1.0 progress bar

last_drive_time = 0.0
animation       = 0

# FPS display
fps_times = deque(maxlen=30)

# ================================================================
#  ARUCO FOLLOW  (operates on downscaled frame)
# ================================================================

def follow_aruco(small_frame, display_frame):
    """
    Detect ArUco in small_frame (ARUCO_W×ARUCO_H), steer toward target_id,
    draw overlays scaled back onto display_frame.
    Returns (steering_label, marker_found).
    """
    global following, target_id

    scale_x = WIN_W  / ARUCO_W
    scale_y = WIN_H  / ARUCO_H
    center_xs = ARUCO_W // 2      # center in small-frame coords

    gray_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)

    # CLAHE improves contrast for detection under variable lighting
    clahe      = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    gray_small = clahe.apply(gray_small)

    corners, ids, _ = aruco_det.detectMarkers(gray_small)

    if ids is None or len(ids) == 0:
        return "SEARCHING...", False

    ids_flat = ids.flatten()

    # Auto-pick target if not yet decided
    if target_id is None:
        for pick in [1, 2, 3]:
            if pick in ids_flat:
                target_id = pick
                break
        else:
            return "SEARCHING...", False

    for i, mid in enumerate(ids_flat):
        if mid != target_id:
            continue

        pts = corners[i][0]                  # (4,2) in small-frame coords

        # Scale corners back up for display drawing
        pts_big = pts.copy()
        pts_big[:, 0] *= scale_x
        pts_big[:, 1] *= scale_y
        pts_big = pts_big.astype(np.int32)

        mx_big = int(pts_big[:, 0].mean())
        my_big = int(pts_big[:, 1].mean())

        # Draw on display frame
        cv2.polylines(display_frame, [pts_big], True, (0, 255, 0), 2)
        cv2.circle(display_frame, (mx_big, my_big), 7, (0, 255, 0), -1)
        cv2.putText(display_frame, f"ArUco ID {mid}",
                    (mx_big - 30, my_big - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
        cv2.arrowedLine(display_frame,
                        (WIN_W // 2, WIN_H // 2),
                        (mx_big, my_big),
                        (0, 200, 255), 2, tipLength=0.2)

        # Steering uses small-frame coords (consistent with STOP_AREA)
        mx_s = float(pts[:, 0].mean())
        w_s  = float(pts[:, 0].max() - pts[:, 0].min())
        h_s  = float(pts[:, 1].max() - pts[:, 1].min())
        area_s = w_s * h_s
        offset = mx_s - center_xs

        # Stop when marker is large enough (bot is close)
        if area_s >= STOP_AREA:
            stop_bot()
            following = False
            return "  STOP  ", True

        if abs(offset) <= DEAD_ZONE:
            drive(FOLLOW_SPEED, FOLLOW_SPEED)
            label = "FORWARD"
        elif offset < 0:
            drive(FOLLOW_SPEED - TURN_BOOST, FOLLOW_SPEED + TURN_BOOST)
            label = "LEFT"
        else:
            drive(FOLLOW_SPEED + TURN_BOOST, FOLLOW_SPEED - TURN_BOOST)
            label = "RIGHT"

        # Offset bar on display
        bar_cx = WIN_W // 2
        bar_y  = WIN_H - 55
        cv2.rectangle(display_frame,
                      (bar_cx - 130, bar_y - 7),
                      (bar_cx + 130, bar_y + 7),
                      (50, 50, 50), -1)
        ind_x = int(bar_cx + offset * (130 / (ARUCO_W // 2)))
        ind_x = max(bar_cx - 130, min(bar_cx + 130, ind_x))
        cv2.circle(display_frame, (ind_x, bar_y), 11, (0, 255, 255), -1)
        cv2.line(display_frame,
                 (bar_cx, bar_y - 14), (bar_cx, bar_y + 14),
                 (255, 255, 255), 1)

        return label, True

    return "SEARCHING...", False

# ================================================================
#  MAIN
# ================================================================

cam = CamStream(CAM_URL)

cv2.namedWindow("WAREHOUSE AI", cv2.WINDOW_NORMAL)
cv2.resizeWindow("WAREHOUSE AI", WIN_W, WIN_H)

while True:

    ret, raw = cam.read()
    if not ret or raw is None:
        time.sleep(0.01)
        continue

    # Always work on a fixed display-size copy
    frame = cv2.resize(raw, (WIN_W, WIN_H))

    # FPS counter
    now = time.time()
    fps_times.append(now)
    if len(fps_times) >= 2:
        fps = (len(fps_times) - 1) / (fps_times[-1] - fps_times[0])
    else:
        fps = 0.0

    # ---- PHASE 1: Shape detection + 5-second confirmation ----

    if not shape_sent and not following:

        cx = WIN_W // 2 - SCAN_SIZE // 2
        cy = WIN_H // 2 - SCAN_SIZE // 2
        roi = frame[cy:cy + SCAN_SIZE, cx:cx + SCAN_SIZE]

        shape_now = detect_shape_in_roi(roi)

        if shape_now is None:
            # Nothing seen — reset confirmation
            confirm_shape    = None
            confirm_start    = 0.0
            confirm_progress = 0.0

        elif shape_now != confirm_shape:
            # New/different shape — restart timer
            confirm_shape    = shape_now
            confirm_start    = now
            confirm_progress = 0.0

        else:
            # Same shape persisting — advance progress
            elapsed          = now - confirm_start
            confirm_progress = min(elapsed / CONFIRM_SECONDS, 1.0)

            if elapsed >= CONFIRM_SECONDS:
                # Confirmed! Trigger the bot
                detected_text = f"{confirm_shape.upper()} DETECTED"
                main_text     = detected_text
                send_shape(confirm_shape)
                shape_sent    = True
                following     = True
                confirm_progress = 1.0

        # Draw scan box
        animation += 1
        pulse = int(25 * math.sin(animation * 0.1))
        box_color = (0, int(255 - pulse), 255)

        if confirm_shape:
            # Change box color to yellow while confirming
            box_color = (0, 200, 255)

        cv2.rectangle(frame,
                      (cx, cy),
                      (cx + SCAN_SIZE, cy + SCAN_SIZE),
                      box_color, 3)

        # Scan line (only when not confirming)
        if confirm_shape is None:
            scan_y = cy + (animation % SCAN_SIZE)
            cv2.line(frame, (cx, scan_y), (cx + SCAN_SIZE, scan_y),
                     (0, 255, 0), 2)

        # Confirmation progress bar inside scan box
        if confirm_shape and confirm_progress < 1.0:
            bar_full = SCAN_SIZE - 10
            bar_done = int(bar_full * confirm_progress)
            cv2.rectangle(frame,
                          (cx + 5, cy + SCAN_SIZE - 18),
                          (cx + 5 + bar_full, cy + SCAN_SIZE - 8),
                          (60, 60, 60), -1)
            cv2.rectangle(frame,
                          (cx + 5, cy + SCAN_SIZE - 18),
                          (cx + 5 + bar_done, cy + SCAN_SIZE - 8),
                          (0, 255, 200), -1)
            secs_left = CONFIRM_SECONDS - (now - confirm_start)
            cv2.putText(frame,
                        f"{confirm_shape.upper()}  {secs_left:.1f}s",
                        (cx, cy - 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 200), 2)
        else:
            label = f"SCANNING..." if not confirm_shape else "CONFIRMED"
            cv2.putText(frame, label,
                        (cx, cy - 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    # ---- PHASE 2: ArUco follow ----

    steering_label = ""

    if following:
        # Downscale for faster ArUco detection
        small = cv2.resize(frame, (ARUCO_W, ARUCO_H))

        t_drive = time.time()
        if t_drive - last_drive_time > 0.08:      # 12 Hz
            steering_label, found = follow_aruco(small, frame)
            last_drive_time = t_drive

            if not found:
                drive(90, 90)                      # slow search creep

        main_text = f"FOLLOWING  ArUco ID {target_id}" if target_id else "SEARCHING ArUco..."

    # ---- OSD top bar ----

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (WIN_W, 155), (15, 15, 15), -1)
    frame = cv2.addWeighted(overlay, 0.72, frame, 0.28, 0)

    cv2.putText(frame, main_text,
                (30, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
    cv2.putText(frame, detected_text,
                (30, 120),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

    # Steering label (large, bottom center)
    if steering_label:
        if "STOP" in steering_label:
            s_color = (0, 255, 80)
            s_text  = "STOP  ✓"
        elif "LEFT" in steering_label:
            s_color = (0, 200, 255)
            s_text  = "◄  LEFT"
        elif "RIGHT" in steering_label:
            s_color = (0, 200, 255)
            s_text  = "RIGHT  ►"
        else:
            s_color = (0, 255, 255)
            s_text  = steering_label

        cv2.putText(frame, s_text,
                    (WIN_W // 2 - 100, WIN_H - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.3, s_color, 3)

    # FPS counter (top right)
    cv2.putText(frame, f"FPS: {fps:.0f}",
                (WIN_W - 160, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2)

    # Live badge
    cv2.rectangle(frame, (WIN_W - 330, 65), (WIN_W - 10, 130), (0, 255, 255), 2)
    cv2.putText(frame, "ESP32-CAM LIVE",
                (WIN_W - 310, 108),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

    # Bottom hint
    cv2.putText(frame, "R = reset    ESC = quit",
                (30, WIN_H - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (130, 130, 130), 1)

    cv2.imshow("WAREHOUSE AI", frame)

    key = cv2.waitKey(1)
    if key == 27:
        break
    elif key in (ord('r'), ord('R')):
        shape_sent       = False
        following        = False
        target_id        = None
        detected_text    = ""
        main_text        = "WAITING..."
        confirm_shape    = None
        confirm_start    = 0.0
        confirm_progress = 0.0
        stop_bot()

cam.release()
cv2.destroyAllWindows()
