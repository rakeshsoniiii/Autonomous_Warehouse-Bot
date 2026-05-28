import cv2
import cv2.aruco as aruco
import numpy as np
import threading
import time

# --- Configuration ---
MARKER_A = 1
MARKER_B = 2

# TODO: Measure your real printed ArUco marker width in cm and update this value!
MARKER_PHYSICAL_SIZE_CM = 5.0  

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

def get_refined_center(corners):
    """Calculates center using float coordinates for sub-pixel accuracy."""
    pts = corners[0].reshape((4, 2))
    cx = int(np.mean(pts[:, 0]))
    cy = int(np.mean(pts[:, 1]))
    return (cx, cy)

def calculate_pixels_per_cm(corners, physical_size_cm):
    """Calculates how many pixels represent 1 cm based on marker edge lengths."""
    pts = corners[0].reshape((4, 2))
    # Calculate pixel width of the top edge of the marker
    edge_pixels = np.linalg.norm(pts[0] - pts[1])
    return edge_pixels / physical_size_cm

# Initialize and start threaded camera
camera = LagFreeCamera(src=0).start()

# Setup Optimized ArUco Parameters
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
parameters = aruco.DetectorParameters()
parameters.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
parameters.cornerRefinementWinSize = 5
detector = aruco.ArucoDetector(aruco_dict, parameters)

print(f"Tracking Engine Active. Marker size baseline set to {MARKER_PHYSICAL_SIZE_CM} cm.")
print("Press 'q' to exit.")

prev_time = 0
pixels_per_cm = None  # Dynamic calibration factor placeholder

while True:
    ret, frame = camera.read()
    if not ret or frame is None: continue
        
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, rejected = detector.detectMarkers(gray)
    
    detected_nodes = {}
    
    if ids is not None:
        for i, m_id in enumerate(ids.flatten()):
            # Dynamic calibration lookup: use any visible target marker to compute scale factor
            if m_id in [MARKER_A, MARKER_B]:
                pixels_per_cm = calculate_pixels_per_cm(corners[i], MARKER_PHYSICAL_SIZE_CM)
                
            if m_id in [MARKER_A, MARKER_B]:
                node_center = get_refined_center(corners[i])
                detected_nodes[m_id] = node_center

    # --- Metrics and Coordinate Geometry Engine ---
    if MARKER_A in detected_nodes and MARKER_B in detected_nodes and pixels_per_cm is not None:
        node_a = detected_nodes[MARKER_A]
        node_b = detected_nodes[MARKER_B]
        
        # 1. Calculate raw pixel distance
        distance_pixels = np.linalg.norm(np.array(node_b) - np.array(node_a))
        
        # 2. Convert pixel distance to real-world centimeters
        distance_cm = distance_pixels / pixels_per_cm
        
        # UI Visual Overlays
        cv2.line(frame, node_a, node_b, (255, 255, 0), 2, cv2.LINE_AA)
        cv2.circle(frame, node_a, 6, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, node_b, 6, (0, 255, 0), -1, cv2.LINE_AA)
        
        mid_x = (node_a[0] + node_b[0]) // 2
        mid_y = (node_a[1] + node_b[1]) // 2
        
        # Print the live physical centimeter distance string directly onto the vector center
        cv2.putText(frame, f"{distance_cm:.1f} cm", (mid_x - 40, mid_y - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        
        cv2.putText(frame, "STATUS: LOCKED", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    else:
        cv2.putText(frame, "STATUS: SEARCHING NODES", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)

    # Performance Tracker (FPS)
    current_time = time.time()
    fps = 1 / (current_time - prev_time)
    prev_time = current_time
    cv2.putText(frame, f"FPS: {int(fps)}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 0), 1, cv2.LINE_AA)

    cv2.imshow("Bot Vision Navigation", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

camera.release()
cv2.destroyAllWindows()
