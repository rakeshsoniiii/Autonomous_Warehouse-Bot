import cv2
import numpy as np
import requests
import tensorflow as tf
import time

# ================= LOAD MODEL =================

model = tf.keras.models.load_model(
    "warehouse_ai_model.h5"
)

classes = ["ball", "Square", "unknown"]

# ================= ESP32 CAM =================

url = "http://172.20.10.4/capture"

# ================= ROBOT ESP32 =================

robot_ip = "172.20.10.5"

# ================= ARUCO =================

aruco_dict = cv2.aruco.getPredefinedDictionary(
    cv2.aruco.DICT_4X4_50
)

aruco_params = cv2.aruco.DetectorParameters()

aruco_detector = cv2.aruco.ArucoDetector(
    aruco_dict,
    aruco_params
)

# ================= WINDOW =================

window_name = "WAREHOUSE AI"

cv2.namedWindow(
    window_name,
    cv2.WINDOW_NORMAL
)

cv2.resizeWindow(
    window_name,
    1000,
    700
)

# ================= VARIABLES =================

current_object = None

detect_start_time = 0

required_duration = 5.0

object_locked = False

target_marker = None

last_marker = -1

return_started = False

home_reached = False

status_text = "WAITING FOR OBJECT"

detect_again_visible = False

navigation_started = False

marker_reached = False

# ================= BUTTON =================

button_x1 = 700
button_y1 = 20

button_x2 = 950
button_y2 = 80

# ================= MOTOR =================

def move(l, r):

    try:

        requests.get(
            f"http://{robot_ip}/drive?l={l}&r={r}",
            timeout=1
        )

    except:
        pass

def stop():

    try:

        requests.get(
            f"http://{robot_ip}/stop",
            timeout=1
        )

    except:
        pass

# ================= DISTANCE =================

def get_distance():

    try:

        d = requests.get(
            f"http://{robot_ip}/distance",
            timeout=1
        ).text

        return float(d)

    except:

        return 999

# ================= MOUSE CLICK =================

def mouse_click(event, x, y, flags, param):

    global object_locked
    global target_marker
    global return_started
    global current_object
    global status_text
    global home_reached
    global detect_again_visible
    global navigation_started
    global marker_reached

    if event == cv2.EVENT_LBUTTONDOWN:

        # ================= DETECT AGAIN =================

        if (
            detect_again_visible
            and x >= button_x1
            and x <= button_x2
            and y >= button_y1
            and y <= button_y2
        ):

            print("DETECT AGAIN CLICKED")

            object_locked = False

            target_marker = None

            return_started = False

            home_reached = False

            detect_again_visible = False

            current_object = None

            navigation_started = False

            marker_reached = False

            status_text = "WAITING FOR OBJECT"

cv2.setMouseCallback(
    window_name,
    mouse_click
)

# ================= LOOP =================

while True:

    try:

        # ================= CAMERA =================

        img_resp = requests.get(
            url,
            timeout=5
        )

        img_arr = np.frombuffer(
            img_resp.content,
            np.uint8
        )

        frame = cv2.imdecode(
            img_arr,
            cv2.IMREAD_COLOR
        )

        if frame is None:
            continue

        # ================= FRAME SIZE =================

        frame = cv2.resize(
            frame,
            (1000,700)
        )

        # ================= CENTER BOX =================

        h, w, _ = frame.shape

        size = 220

        x1 = w//2 - size//2
        y1 = h//2 - size//2

        x2 = x1 + size
        y2 = y1 + size

        crop = frame[y1:y2, x1:x2]

        # ================= ARUCO DETECT =================

        corners, ids, rejected = (
            aruco_detector.detectMarkers(frame)
        )

        marker_text = ""

        if ids is not None:

            ids = ids.flatten()

            cv2.aruco.drawDetectedMarkers(
                frame,
                corners,
                ids
            )

            for i, marker_id in enumerate(ids):

                marker_text = (
                    f"ARUCO ID : {marker_id}"
                )

                marker_area = cv2.contourArea(
                    corners[i]
                )

                if marker_id != last_marker:

                    print(
                        f"ARUCO ID : {marker_id}"
                    )

                    last_marker = marker_id

        # ================= AI DETECTION =================

        if not object_locked:

            img = cv2.resize(
                crop,
                (224,224)
            )

            img = np.expand_dims(
                img,
                axis=0
            )

            prediction = model.predict(
                img,
                verbose=0
            )

            class_index = np.argmax(
                prediction
            )

            confidence = np.max(
                prediction
            )

            detected = classes[class_index]

            # ================= LOW CONFIDENCE =================

            if confidence < 0.85:

                detected = "unknown"

            # ================= TIMER =================

            if detected != current_object:

                current_object = detected

                detect_start_time = time.time()

            elapsed_time = (
                time.time() - detect_start_time
            )

            # ================= FINAL DETECTION =================

            if elapsed_time >= required_duration:

                # ================= BALL =================

                if detected == "ball":

                    status_text = (
                        "BALL DETECTED -> ID1"
                    )

                    target_marker = 1

                    print("TARGET ID 1")

                # ================= SQUARE =================

                elif detected == "Square":

                    status_text = (
                        "SQUARE DETECTED -> ID2"
                    )

                    target_marker = 2

                    print("TARGET ID 2")

                # ================= UNKNOWN =================

                else:

                    status_text = (
                        "UNKNOWN DETECTED -> ID3"
                    )

                    target_marker = 3

                    print("TARGET ID 3")

                object_locked = True

                navigation_started = True

            else:

                status_text = (
                    f"CONFIRMING "
                    f"{detected.upper()} "
                    f"{elapsed_time:.1f}/5s"
                )

                color = (0,255,255)

        # ================= SMART NAVIGATION =================

        if (
            navigation_started
            and target_marker is not None
            and not marker_reached
        ):

            # ================= DISTANCE =================

            distance = get_distance()

            # ================= OBSTACLE =================

            if distance < 20:

                status_text = (
                    "OBSTACLE BYPASS"
                )

                stop()
                time.sleep(0.3)

                # BACK

                move(-120,-120)
                time.sleep(0.5)

                stop()
                time.sleep(0.2)

                # RIGHT

                move(180,-180)
                time.sleep(0.45)

                stop()
                time.sleep(0.2)

                # FORWARD

                move(120,120)
                time.sleep(1.0)

                stop()
                time.sleep(0.2)

                # LEFT

                move(-180,180)
                time.sleep(0.45)

                stop()
                time.sleep(0.2)

                # FORWARD

                move(120,120)
                time.sleep(1.0)

                stop()
                time.sleep(0.2)

            # ================= TARGET FOLLOW =================

            if ids is not None:

                found_target = False

                for i, marker_id in enumerate(ids):

                    if marker_id == target_marker:

                        found_target = True

                        c = corners[i][0]

                        center_x = int(
                            c[:,0].mean()
                        )

                        marker_area = cv2.contourArea(
                            corners[i]
                        )

                        # ================= LEFT =================

                        if center_x < 420:

                            status_text = (
                                "ALIGN LEFT"
                            )

                            move(80,150)

                        # ================= RIGHT =================

                        elif center_x > 580:

                            status_text = (
                                "ALIGN RIGHT"
                            )

                            move(150,80)

                        # ================= CENTER =================

                        else:

                            # ================= CLOSE =================

                            if marker_area > 50000:

                                status_text = (
                                    f"ID {target_marker} REACHED"
                                )

                                print(
                                    f"TARGET {target_marker} REACHED"
                                )

                                stop()

                                marker_reached = True

                                home_reached = True

                                detect_again_visible = True

                            else:

                                status_text = (
                                    "MOVING FORWARD"
                                )

                                move(120,120)

                # ================= SEARCH =================

                if not found_target:

                    status_text = (
                        "SEARCHING TARGET"
                    )

                    move(100,-100)

            else:

                status_text = (
                    "SEARCHING MARKER"
                )

                move(100,-100)

        # ================= UI COLORS =================

        if object_locked:

            color = (255,255,255)

        else:

            color = (0,255,255)

        # ================= DARK UI =================

        overlay = frame.copy()

        cv2.rectangle(
            overlay,
            (0,0),
            (1000,100),
            (20,20,20),
            -1
        )

        alpha = 0.6

        frame = cv2.addWeighted(
            overlay,
            alpha,
            frame,
            1-alpha,
            0
        )

        # ================= CENTER BOX =================

        cv2.rectangle(
            frame,
            (x1,y1),
            (x2,y2),
            color,
            3
        )

        # ================= STATUS =================

        cv2.putText(
            frame,
            status_text,
            (20,60),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            color,
            3
        )

        # ================= MARKER =================

        if marker_text != "":

            cv2.putText(
                frame,
                marker_text,
                (20,95),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255,255,0),
                2
            )

        # ================= DETECT AGAIN BUTTON =================

        if detect_again_visible:

            cv2.rectangle(
                frame,
                (button_x1, button_y1),
                (button_x2, button_y2),
                (0,255,0),
                -1
            )

            cv2.putText(
                frame,
                "DETECT AGAIN",
                (730,60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0,0,0),
                3
            )

        # ================= SHOW =================

        cv2.imshow(
            window_name,
            frame
        )

    except Exception as e:

        print(e)

    # ================= EXIT =================

    if cv2.waitKey(1) == 27:

        stop()
        break

cv2.destroyAllWindows()