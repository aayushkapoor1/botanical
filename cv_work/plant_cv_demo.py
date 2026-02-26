import cv2
import time
from ultralytics import YOLO

# Load pretrained COCO detector (auto-downloads weights on first run)
model = YOLO("yolov8n.pt")  # or "yolo11n.pt" if that's what you have installed

# 58 is the potted plant class. I don't think this is trained on topdown views particularly
POTTED_PLANT_CLASS = 58     # Ultralytics COCO: "potted plant" :contentReference[oaicite:2]{index=2}
CONF_THRES = 0.35

# Debounce parameters
ON_HITS = 3        # need 3 consecutive detections to turn ON
OFF_MISSES = 6     # need 6 consecutive misses to turn OFF

# Optional cooldown to prevent repeated triggers if you jitter at boundary
COOLDOWN_S = 1.5
last_trigger = 0.0

state_on = False
hit_count = 0
miss_count = 0

# Open the camera (1 for external camera, 0 for default camera)
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise RuntimeError("Could not open camera")

while True:
    # OK is a boolean on if the frame was captured successfully, frame is the array of pixels
    ok, frame = cap.read()
    if not ok:
        break

    # Predict ONLY potted plant class
    # res will contain bounded boxes that matches the filters
    res = model.predict(frame, conf=CONF_THRES, classes=[POTTED_PLANT_CLASS], verbose=False)[0]

    plant_present = (res.boxes is not None) and (len(res.boxes) > 0)

    # Update counters
    if plant_present:
        hit_count += 1
        miss_count = 0
    else:
        miss_count += 1
        hit_count = 0

    # Rising edge: OFF -> ON
    if (not state_on) and (hit_count >= ON_HITS):
        now = time.time()
        if now - last_trigger >= COOLDOWN_S:
            state_on = True
            last_trigger = now
            print("NEW PLANT FOUND (trigger action here)")

    # Falling edge: ON -> OFF
    if state_on and (miss_count >= OFF_MISSES):
        state_on = False
        print("Plant left view (ready for next plant)")

    # UI
    status = "PLANT" if state_on else "No plant"
    cv2.putText(frame, f"{status}  hit={hit_count} miss={miss_count}", (10, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3)
    cv2.imshow("Plant Presence (debounced)", frame)

    if cv2.waitKey(1) & 0xFF == 27:  # ESC
        break

cap.release()
cv2.destroyAllWindows()
