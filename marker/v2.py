import cv2
import cv2.aruco as aruco
import numpy as np
import threading
import time
import math
import requests

# --- System Configuration ---
BOT_ID = 1      # Marker 1 is your Bot
TARGET_ID = 2   # Marker 2 is the target it follows

# Update this with the IP address printed on your Bot's LCD screen!
ESP32_IP = "111.111.1.11"  
BASE_URL = f"http://{ESP32_IP}"

MARKER_PHYSICAL_SIZE_CM = 5.0 # Update this with your marker width in cm

class LagFreeCamera:
    """Reads camera frames in a background thread to eliminate video buffering lag."""
    def __init__(self, src=0):
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.ret, self.frame = self.cap.read()
        self.started = False
        self.read_lock = threading.Lock()

    def start(self):
        if self.started: return self
        self.started = True
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()
        return self

    def update(self):
        while self.started:
            ret, frame = self.cap.read()
            if ret:
                with self.read_lock:
                    self.ret = ret
                    self.frame = frame
            time.sleep(0.01)

    def read(self):
        with self.read_lock:
            return self.ret, self.frame.copy() if self.frame is not None else None

    def release(self):
        self.started = False
        if self.thread.is_alive(): self.thread.join()
        self.cap.release()

def send_motor_command(l_speed, r_speed):
    """Sends motor speed parameters asynchronously to keep video processing lag-free."""
    def send_request():
        try:
            url = f"{BASE_URL}/follow?l={l_speed}&r={r_speed}"
            requests.get(url, timeout=0.2)
        except Exception:
            pass # Suppress network timeouts/errors to keep frame loop running smoothly
            
    threading.Thread(target=send_request).start()

def get_node_telemetry(corners):
    """Calculates center coordinates and heading angle of the marker."""
    pts = corners[0].reshape((4, 2))
    cx = int(np.mean(pts[:, 0]))
    cy = int(np.mean(pts[:, 1]))
    
    # Use front two corners to find heading orientation
    front_x = (pts[0][0] + pts[1][0]) / 2
    front_y = (pts[0][1] + pts[1][1]) / 2
    heading = math.atan2(front_y - cy, front_x - cx)
    
    return (cx, cy), heading

def get_pixels_per_cm(corners, physical_size):
    pts = corners[0].reshape((4, 2))
    edge_px = np.linalg.norm(pts[0] - pts[1])
    return edge_px / physical_size

# Start system components
camera = LagFreeCamera(src=0).start()
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
parameters = aruco.DetectorParameters()
parameters.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
detector = aruco.ArucoDetector(aruco_dict, parameters)

print(f"Tracking Server active. Sending data to: {BASE_URL}")
last_command_time = 0
command_cooldown = 0.15 # Restrict Wi-Fi packet flooding (Max ~7 commands per second)

while True:
    ret, frame = camera.read()
    if not ret or frame is None: continue
        
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, rejected = detector.detectMarkers(gray)
    
    nodes_map = {}
    headings_map = {}
    px_per_cm = None
    
    if ids is not None:
        for i, m_id in enumerate(ids.flatten()):
            if m_id in [BOT_ID, TARGET_ID]:
                center, heading = get_node_telemetry(corners[i])
                nodes_map[m_id] = center
                headings_map[m_id] = heading
                px_per_cm = get_pixels_per_cm(corners[i], MARKER_PHYSICAL_SIZE_CM)

    # --- Core Tracking & Navigation Execution Logic ---
    if BOT_ID in nodes_map and TARGET_ID in nodes_map and px_per_cm is not None:
        p_bot = nodes_map[BOT_ID]
        p_target = nodes_map[TARGET_ID]
        
        # 1. Coordinate Distance
        dist_px = np.linalg.norm(np.array(p_target) - np.array(p_bot))
        dist_cm = dist_px / px_per_cm
        
        # 2. Alignment Vectors 
        global_target_angle = math.atan2(p_target[1] - p_bot[1], p_target[0] - p_bot[0])
        heading_error = global_target_angle - headings_map[BOT_ID]
        heading_error = math.atan2(math.sin(heading_error), math.cos(heading_error)) # Normalize (-pi to pi)
        heading_error_deg = math.degrees(heading_error)
        
        # Visual Node Overlays
        cv2.line(frame, p_bot, p_target, (255, 255, 0), 2, cv2.LINE_AA)
        cv2.circle(frame, p_bot, 6, (0, 0, 255), -1)   # Red Node = Bot
        cv2.circle(frame, p_target, 6, (0, 255, 0), -1) # Green Node = Target
        
        mid_x = (p_bot[0] + p_target[0]) // 2
        mid_y = (p_bot[1] + p_target[1]) // 2
        cv2.putText(frame, f"{dist_cm:.1f} cm", (mid_x - 30, mid_y - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)

        # 3. Decision Control Logic Engine
        now = time.time()
        if now - last_command_time > command_cooldown:
            if dist_cm > 15.0: # Stop when within 15 cm of target marker
                if abs(heading_error_deg) > 20: # Needs alignment correction
                    if heading_error_deg > 0:
                        send_motor_command(140, -140) # Spin right
                        action_label = "ALIGNING RIGHT"
                    else:
                        send_motor_command(-140, 140) # Spin left
                        action_label = "ALIGNING LEFT"
                else:
                    # Move forward (adjust motor trim dynamically based on slight angle error)
                    if heading_error_deg > 5:
                        send_motor_command(160, 110)
                    elif heading_error_deg < -5:
                        send_motor_command(110, 160)
                    else:
                        send_motor_command(150, 150)
                    action_label = "DRIVING FORWARD"
            else:
                send_motor_command(0, 0) # Arrived close enough
                action_label = "TARGET REACHED"
                
            last_command_time = now
            cv2.putText(frame, f"CMD: {action_label}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
    else:
        cv2.putText(frame, "SEARCHING FOR NODES...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    cv2.imshow("Global Vision Control Base Station", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        send_motor_command(0, 0)
        break

camera.release()
cv2.destroyAllWindows()
