import cv2
import cv2.aruco as aruco
import numpy as np
import threading
import time
import math
import requests
from inference_sdk import InferenceHTTPClient 

# --- System Configuration ---
BOT_ID = 1      # Marker 1 is your Bot
HOME_ID = 3     # Marker 3 is the Home Base

ESP32_IP = "10.192.77.11"  # Tera ESP IP
BASE_URL = f"http://{ESP32_IP}"
MARKER_PHYSICAL_SIZE_CM = 5.0 

STOP_DISTANCE_CM = 25.0 
SLOWDOWN_DISTANCE_CM = 45.0 

# --- Motor PWM Power Limits (Fix for Motor Humming/Stalling) ---
SPEED_FAST = 200     # Full speed on straight path
SPEED_SPIN = 180     # Itna power chahiye bot ko jagah par ghumne ke liye
SPEED_SLOW = 140     # Turn lete waqt minimum power

CLASS_TO_ID = {
    "circle": 2,
    "square": 4,
    "unknown": 5,
    "ball": 2  
}

CLIENT = InferenceHTTPClient(
    api_url="https://detect.roboflow.com",
    api_key="mF1bgzIacE8gPXw5x1SE" 
)

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

# --- SMART COMMAND SENDER (Prevents ESP32 Lag) ---
last_sent_l = None
last_sent_r = None
last_command_time = 0

def send_motor_command(l_speed, r_speed, force=False):
    global last_sent_l, last_sent_r, last_command_time
    now = time.time()
    
    # Send only if speeds changed OR 0.4 seconds passed (heartbeat to keep alive)
    if force or (l_speed != last_sent_l or r_speed != last_sent_r) or (now - last_command_time > 0.4):
        last_sent_l = l_speed
        last_sent_r = r_speed
        last_command_time = now
        
        def send_request():
            try:
                requests.get(f"{BASE_URL}/drive?l={l_speed}&r={r_speed}", timeout=0.3)
            except Exception:
                pass 
        threading.Thread(target=send_request).start()

def send_stop_mission():
    try: requests.get(f"{BASE_URL}/stop", timeout=1.0) 
    except Exception: pass

def send_beep_command():
    try: requests.get(f"{BASE_URL}/beep", timeout=0.5)
    except Exception: pass

def trigger_esp32_mission(target_id):
    try: requests.get(f"{BASE_URL}/mission?id={target_id}", timeout=1.0)
    except Exception: pass

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

# Start system 
camera = LagFreeCamera(src=0).start()
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
parameters = aruco.DetectorParameters()
parameters.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
detector = aruco.ArucoDetector(aruco_dict, parameters)

print("Tracking Server active. PRESS 'd' TO DETECT OBJECT & START MISSION")

current_target_id = 0
state = "IDLE" 

while True:
    ret, frame = camera.read()
    if not ret or frame is None: continue
        
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, rejected = detector.detectMarkers(gray)
    
    if ids is not None:
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)
    
    nodes_map = {}
    headings_map = {}
    px_per_cm = None
    
    if state == "IDLE":
        try:
            res = requests.get(f"{BASE_URL}/status", timeout=0.1).json()
            if res.get("mission") == 1:
                target = res.get("target")
                if target in [2, 4, 5]: 
                    current_target_id = target
                    state = "GOING_TO_TARGET"
                    print(f"\n---> Mission Started: Going to Object ID {current_target_id}")
        except Exception:
            pass

    if ids is not None:
        for i, m_id in enumerate(ids.flatten()):
            if m_id in [BOT_ID, 2, HOME_ID, 4, 5]: 
                center, heading = get_node_telemetry(corners[i])
                nodes_map[m_id] = center
                headings_map[m_id] = heading
                px_per_cm = get_pixels_per_cm(corners[i], MARKER_PHYSICAL_SIZE_CM)

    action_label = "WAITING AT HOME (ID 3)"
    
    if state != "IDLE":
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
            
            cv2.line(frame, p_bot, p_target, (255, 255, 0), 2, cv2.LINE_AA)
            cv2.circle(frame, p_bot, 6, (0, 0, 255), -1)
            cv2.circle(frame, p_target, 6, (0, 255, 0), -1)

            if dist_cm > STOP_DISTANCE_CM: 
                fwd_speed = SPEED_FAST if dist_cm > SLOWDOWN_DISTANCE_CM else SPEED_SLOW
                
                if abs(heading_error_deg) > 25: 
                    if heading_error_deg > 0:
                        send_motor_command(SPEED_SPIN, -SPEED_SPIN) 
                        action_label = f"SPINNING RIGHT -> ID {active_target}"
                    else:
                        send_motor_command(-SPEED_SPIN, SPEED_SPIN) 
                        action_label = f"SPINNING LEFT -> ID {active_target}"
                else:
                    if heading_error_deg > 10:
                        send_motor_command(fwd_speed, SPEED_SLOW)
                        action_label = f"TURNING RIGHT -> ID {active_target}"
                    elif heading_error_deg < -10:
                        send_motor_command(SPEED_SLOW, fwd_speed)
                        action_label = f"TURNING LEFT -> ID {active_target}"
                    else:
                        send_motor_command(fwd_speed, fwd_speed) 
                        action_label = f"DRIVING -> ID {active_target} (Dist: {int(dist_cm)}cm)"
            else:
                if state == "GOING_TO_TARGET":
                    send_motor_command(0, 0, force=True) 
                    send_beep_command() 
                    print(f"-----> Object Reached! Turning to Home (ID {HOME_ID}) in 1.5s...")
                    time.sleep(1.5) 
                    # State instantly changes to return Home
                    state = "RETURNING_HOME" 
                
                elif state == "RETURNING_HOME":
                    send_motor_command(0, 0, force=True)
                    send_beep_command() 
                    send_stop_mission() 
                    time.sleep(0.5) 
                    state = "IDLE" 
                    print("-----> Mission Accomplished! Safely at Home. Ready for next task!\n")
        else:
            action_label = f"WAITING TO SEE ID {active_target}..."
            send_motor_command(0, 0)

    cv2.putText(frame, f"STATE: {state}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.putText(frame, f"ACTION: {action_label}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.imshow("Warehouse Automation Base Station", frame)
    
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        send_motor_command(0, 0, force=True)
        break
        
    elif key == ord('d') and state == "IDLE":
        print("\n[AI] Scanning frame for objects...")
        try:
            optimized_frame = cv2.resize(frame, (640, 480))
            result = CLIENT.infer(optimized_frame, model_id="warehouse-ghkci/3")
            predictions = result.get("predictions", [])
            
            if len(predictions) > 0:
                best_pred = max(predictions, key=lambda x: x['confidence'])
                detected_label = best_pred["class"].lower()
                
                print(f"[AI] Detected '{detected_label}'!")
                
                if detected_label in CLASS_TO_ID:
                    mapped_id = CLASS_TO_ID[detected_label]
                    trigger_esp32_mission(mapped_id)
                    current_target_id = mapped_id
                    state = "GOING_TO_TARGET"
                else:
                    print(f"[AI] Unrecognized object. Try again.")
            else:
                print("[AI] Kuch detect nahi hua. Try again.")
        except Exception:
            print("[AI] Network delay... Retrying is required.")

camera.release()
cv2.destroyAllWindows()
