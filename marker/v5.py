import cv2
import cv2.aruco as aruco
import numpy as np
import threading
import time
import math
import requests

# --- System Configuration ---
BOT_ID = 1      # Marker 1 is your Bot
HOME_ID = 3     # Marker 3 is the Home Base

# Update this with ESP32 IP
ESP32_IP = "172.20.95.11"  
BASE_URL = f"http://{ESP32_IP}"
MARKER_PHYSICAL_SIZE_CM = 5.0 

class LagFreeCamera:
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
    def send_request():
        try:
            url = f"{BASE_URL}/drive?l={l_speed}&r={r_speed}"
            requests.get(url, timeout=0.2)
        except Exception:
            pass 
            
    threading.Thread(target=send_request).start()

def send_stop_mission():
    try:
        requests.get(f"{BASE_URL}/stop", timeout=0.5)
    except Exception:
        pass

def get_node_telemetry(corners):
    pts = corners[0].reshape((4, 2))
    cx = int(np.mean(pts[:, 0]))
    cy = int(np.mean(pts[:, 1]))
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

print(f"Tracking Server active. Connected to: {BASE_URL}")
last_command_time = 0
command_cooldown = 0.05 # Fast response time for high speed

# --- Mission State Variables ---
current_target_id = 0
state = "IDLE" # IDLE, GOING_TO_TARGET, RETURNING_HOME

while True:
    ret, frame = camera.read()
    if not ret or frame is None: continue
        
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, rejected = detector.detectMarkers(gray)
    
    nodes_map = {}
    headings_map = {}
    px_per_cm = None
    
    # 1. Fetch current mission status from ESP32 Webserver dynamically
    try:
        if state == "IDLE":
            res = requests.get(f"{BASE_URL}/status", timeout=0.1).json()
            if res.get("mission") == 1:
                target = res.get("target")
                if target in [2, 4, 5]: # Valid target objects
                    current_target_id = target
                    state = "GOING_TO_TARGET"
                    print(f"Mission Started: Going to Object ID {current_target_id} at MAX SPEED")
    except Exception:
        pass

    # Detect ArUco Markers
    if ids is not None:
        for i, m_id in enumerate(ids.flatten()):
            if m_id in [BOT_ID, 2, HOME_ID, 4, 5]: # Track Bot, Objects, and Home
                center, heading = get_node_telemetry(corners[i])
                nodes_map[m_id] = center
                headings_map[m_id] = heading
                px_per_cm = get_pixels_per_cm(corners[i], MARKER_PHYSICAL_SIZE_CM)

    action_label = "WAITING AT HOME (ID 3)"
    
    # --- Core State Machine Logic ---
    if state != "IDLE":
        # Decide which ID we are currently driving towards
        active_target = current_target_id if state == "GOING_TO_TARGET" else HOME_ID
                
        if active_target in nodes_map and BOT_ID in nodes_map and px_per_cm is not None:
            p_bot = nodes_map[BOT_ID]
            p_target = nodes_map[active_target]
            
            dist_px = np.linalg.norm(np.array(p_target) - np.array(p_bot))
            dist_cm = dist_px / px_per_cm
            
            global_target_angle = math.atan2(p_target[1] - p_bot[1], p_target[0] - p_bot[0])
            heading_error = global_target_angle - headings_map[BOT_ID]
            heading_error = math.atan2(math.sin(heading_error), math.cos(heading_error))
            heading_error_deg = math.degrees(heading_error)
            
            # Visuals
            cv2.line(frame, p_bot, p_target, (255, 255, 0), 2, cv2.LINE_AA)
            cv2.circle(frame, p_bot, 6, (0, 0, 255), -1)
            cv2.circle(frame, p_target, 6, (0, 255, 0), -1)

            now = time.time()
            if now - last_command_time > command_cooldown:
                if dist_cm > 15.0: # Driving Logic
                    if abs(heading_error_deg) > 25: 
                        if heading_error_deg > 0:
                            send_motor_command(255, -255) # Max Spin Right
                            action_label = f"SPINNING RIGHT -> ID {active_target}"
                        else:
                            send_motor_command(-255, 255) # Max Spin Left
                            action_label = f"SPINNING LEFT -> ID {active_target}"
                    else:
                        if heading_error_deg > 10:
                            send_motor_command(255, 120)
                        elif heading_error_deg < -10:
                            send_motor_command(120, 255)
                        else:
                            send_motor_command(255, 255) # MAX SPEED FORWARD
                        action_label = f"FULL SPEED -> ID {active_target}"
                else:
                    # Target Reached Logic
                    if state == "GOING_TO_TARGET":
                        # ZERO DELAY: Switch immediately to Home (ID 3)
                        state = "RETURNING_HOME"
                        print(f"Object Picked! Returning directly to Home (ID {HOME_ID})")
                    
                    elif state == "RETURNING_HOME":
                        # Reached Home: Stop Bot and Reset Mission
                        send_motor_command(0, 0)
                        send_stop_mission() 
                        state = "IDLE"
                        print("Mission Accomplished! Safely at Home (ID 3).")
                        
                last_command_time = now
        else:
            action_label = f"SEARCHING FOR ID {active_target}..."
            send_motor_command(0, 0)

    # UI Feedback
    cv2.putText(frame, f"STATE: {state}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(frame, f"ACTION: {action_label}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.imshow("Warehouse Automation Base Station", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        send_motor_command(0, 0)
        break

camera.release()
cv2.destroyAllWindows()
