import cv2
import requests
import time
import math

# ================= ESP =================

robot_ip = "172.20.10.6"

cam_url = "http://172.20.10.7:81/stream"

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

main_text = "WAITING..."

detected_text = ""

 

status_time = 0

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

# ================= LOOP =================

animation = 0

while True:

    ret, frame = cap.read()

    if not ret:
        continue

    frame = cv2.resize(
        frame,
        (1200,750)
    )

    # ================= GET STATUS =================

    if time.time() - status_time > 0.2:

        try:

            response = requests.get(
                f"http://{robot_ip}/status",
                timeout=0.2
            )

            status = response.text

            # ================= CIRCLE =================

            if status == "DETECTED CIRCLE":

                detected_text = "CIRCLE DETECTED"

               

                main_text = "CIRCLE DETECTED"

            # ================= SQUARE =================

            elif status == "DETECTED SQUARE":

                detected_text = "SQUARE DETECTED"

                

                main_text = "SQUARE DETECTED"

            # ================= UNKNOWN =================

            elif status == "DETECTED UNKNOWN":

                detected_text = "UNKNOWN DETECTED"

              


                main_text = "UNKNOWN DETECTED"

            # ================= GOING =================

            elif "GOING TO" in status:

                main_text = status

        except:
            pass

        status_time = time.time()

    # ================= TOP BAR =================

    overlay = frame.copy()

    cv2.rectangle(
        overlay,
        (0,0),
        (1200,150),
        (20,20,20),
        -1
    )

    frame = cv2.addWeighted(
        overlay,
        0.7,
        frame,
        0.3,
        0
    )

    # ================= ANIMATION =================

    animation += 1

    pulse = int(
        25 * math.sin(animation * 0.1)
    )

    # ================= TEXT =================

    cv2.putText(
        frame,
        main_text,
        (30,70),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0,255,255),
        3
    )

    # ================= DETECTED =================

    cv2.putText(
        frame,
        detected_text,
        (30,120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0,255,0),
        2
    )


    # ================= BOX =================

    h,w,_ = frame.shape

    size = 240

    x1 = w//2 - size//2
    y1 = h//2 - size//2

    x2 = x1 + size
    y2 = y1 + size

    color = (
        0,
        255-pulse,
        255
    )

    if detected_text == "":

        cv2.rectangle(
            frame,
            (x1,y1),
            (x2,y2),
            color,
            3
        )

        scan_y = y1 + (
            animation % size
        )

        cv2.line(
            frame,
            (x1,scan_y),
            (x2,scan_y),
            (0,255,0),
            2
        )

        cv2.putText(
            frame,
            "SCANNING...",
            (x1,y1-20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0,255,255),
            2
        )

    # ================= RIGHT BOX =================

    cv2.rectangle(
        frame,
        (850,20),
        (1180,120),
        (0,255,255),
        3
    )

    cv2.putText(
        frame,
        "ESP32-CAM LIVE",
        (900,90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255,255,255),
        2
    )

    # ================= SHOW =================

    cv2.imshow(
        "WAREHOUSE AI",
        frame
    )

    # ================= EXIT =================

    key = cv2.waitKey(1)

    if key == 27:
        break

# ================= END =================

cap.release()

cv2.destroyAllWindows()
