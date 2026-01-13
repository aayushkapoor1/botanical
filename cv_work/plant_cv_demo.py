import cv2
from ultralytics import YOLO

# Pretrained COCO detector (auto-downloads weights on first run)
model = YOLO("yolov8n.pt")  # or "yolo11n.pt" if that's what you have installed

POTTED_PLANT_CLASS = 58     # Ultralytics COCO: "potted plant" :contentReference[oaicite:2]{index=2}
CONF_THRES = 0.35

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise RuntimeError("Could not open camera")

while True:
    ok, frame = cap.read()
    if not ok:
        break

    # Predict ONLY potted plant class
    res = model.predict(frame, conf=CONF_THRES, classes=[POTTED_PLANT_CLASS], verbose=False)[0]

    plant_present = (res.boxes is not None) and (len(res.boxes) > 0)

    if plant_present:
        # pick best box
        b = max(res.boxes, key=lambda x: float(x.conf[0]))
        x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
        conf = float(b.conf[0])

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0,0,0), 3)
        cv2.putText(frame, f"PLANT ({conf:.2f})", (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,0), 3)
        print(f"Plant present (conf={conf:.2f})")
    else:
        cv2.putText(frame, "No plant", (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,0), 3)

    cv2.imshow("Plant Presence (YOLO)", frame)
    if cv2.waitKey(1) & 0xFF == 27:  # ESC
        break

cap.release()
cv2.destroyAllWindows()
