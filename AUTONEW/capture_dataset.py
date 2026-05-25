import cv2
import numpy as np
import requests
import os
import time

# ESP32 URL
url = "http://172.20.10.4/capture"

# OBJECT NAME
object_name = input("Enter object name: ")

# CREATE FOLDER
save_path = f"DATASET/{object_name}"

os.makedirs(save_path, exist_ok=True)

count = 0

print("Starting capture in 3 seconds...")
time.sleep(3)

while count < 120:

    try:

        # GET IMAGE
        img_resp = requests.get(url, timeout=5)

        img_arr = np.frombuffer(img_resp.content, np.uint8)

        frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

        if frame is None:
            continue

        # RESIZE
        frame = cv2.resize(frame, (640,480))

        # SAVE IMAGE
        img_name = f"{save_path}/{count}.jpg"

        cv2.imwrite(img_name, frame)

        # SHOW
        cv2.putText(
            frame,
            f"Capturing {object_name}: {count}",
            (20,40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0,255,0),
            2
        )

        cv2.imshow("CAPTURE DATASET", frame)

        count += 1

        # LITTLE DELAY
        time.sleep(0.1)

    except Exception as e:

        print("ERROR:", e)

    if cv2.waitKey(1) == 27:
        break

cv2.destroyAllWindows()

print("DATASET CAPTURE COMPLETE")