import cv2
import time
import numpy as np
import onnxruntime as ort
from ultralytics import YOLO
from collections import deque

# =========================
# Config (edit these)
# =========================
YOLO_WEIGHTS = "plant_detector.pt"          # detector weights
CLS_ONNX     = "plant_classifier.onnx"      # classifier model

# IMPORTANT: labels must match the classifier training order
PLANT_LABELS = ["basil", "mint", "pothos", "spider_plant", "snake_plant"]

CAMERA_INDEX = 0
DETECT_CONF  = 0.35     # YOLO confidence threshold
CLS_CONF     = 0.70     # min confidence to "accept" prediction
CROP_PAD     = 0.15     # expand bbox for cropping (15%)
INPUT_SIZE   = 224      # classifier input size (must match training)

# stability / anti-flicker
SMOOTH_N     = 7        # majority vote window
COOLDOWN_S   = 2.0      # seconds between prints

# =========================
# Utilities
# =========================
def softmax(x: np.ndarray) -> np.ndarray:
    x = x - np.max(x)
    ex = np.exp(x)
    return ex / np.sum(ex)

def expand_box(x1, y1, x2, y2, pad, w, h):
    bw = x2 - x1
    bh = y2 - y1
    x1n = int(max(0, x1 - pad * bw))
    y1n = int(max(0, y1 - pad * bh))
    x2n = int(min(w - 1, x2 + pad * bw))
    y2n = int(min(h - 1, y2 + pad * bh))
    return x1n, y1n, x2n, y2n

def preprocess_for_classifier(crop_bgr: np.ndarray) -> np.ndarray:
    """
    Preprocess crop for typical ImageNet-pretrained models.
    Must match what you used during training.
    """
    img = cv2.resize(crop_bgr, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    # ImageNet normalization
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    img = (img - mean) / std

    # HWC -> CHW and add batch dimension
    img = np.transpose(img, (2, 0, 1))[None, :, :, :]
    return img

def pick_best_box(yolo_boxes):
    """
    Choose the best detection (highest confidence).
    """
    best = None
    best_conf = -1.0
    for b in yolo_boxes:
        conf = float(b.conf[0])
        if conf > best_conf:
            best_conf = conf
            best = b
    return best, best_conf

# =========================
# Main
# =========================
def main():
    # Load models
    detector = YOLO(YOLO_WEIGHTS)

    sess = ort.InferenceSession(CLS_ONNX, providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name

    pred_hist = deque(maxlen=SMOOTH_N)
    last_print = 0.0

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {CAMERA_INDEX}")

    print("Running. Press ESC to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        h, w = frame.shape[:2]

        # 1) Detect plant
        results = detector.predict(frame, conf=DETECT_CONF, verbose=False)
        boxes = results[0].boxes

        if boxes is None or len(boxes) == 0:
            pred_hist.clear()
            cv2.putText(frame, "No plant detected", (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3)
            cv2.imshow("Plant CV Demo", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break
            continue

        best, best_det_conf = pick_best_box(boxes)
        x1, y1, x2, y2 = map(int, best.xyxy[0].tolist())
        x1, y1, x2, y2 = expand_box(x1, y1, x2, y2, CROP_PAD, w, h)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        # 2) Classify crop
        x = preprocess_for_classifier(crop)
        logits = sess.run(None, {input_name: x})[0][0]   # [num_classes]
        probs = softmax(logits)
        pred = int(np.argmax(probs))
        conf = float(probs[pred])

        pred_hist.append(pred)

        # Majority vote smoothing
        smoothed = max(set(pred_hist), key=list(pred_hist).count)
        label = PLANT_LABELS[smoothed]

        # 3) Print when stable + confident (demo "watering action")
        now = time.time()
        stable = (len(pred_hist) == SMOOTH_N) and (list(pred_hist).count(smoothed) >= (SMOOTH_N // 2 + 1))

        if stable and conf >= CLS_CONF and (now - last_print) >= COOLDOWN_S:
            print(f"[ACTION] Plant identified: {label} (conf={conf:.2f}, det={best_det_conf:.2f})")
            last_print = now

        # 4) Draw UI
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 0), 3)
        cv2.putText(frame, f"{label} (cls={conf:.2f}, det={best_det_conf:.2f})",
                    (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3)

        cv2.imshow("Plant CV Demo", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
