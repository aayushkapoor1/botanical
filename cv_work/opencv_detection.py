import cv2
import numpy as np

def detect_green_regions(frame_bgr):
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    lower = (25, 40, 40)
    upper = (95, 255, 255)
    mask = cv2.inRange(hsv, lower, upper)

    # clean up mask
    kernel = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 2000:
            continue
        x, y, w, h = cv2.boundingRect(c)
        boxes.append((x, y, x+w, y+h))
    return boxes, mask

cap = cv2.VideoCapture(0)
while True:
    ok, frame = cap.read()
    if not ok:
        break

    boxes, mask = detect_green_regions(frame)
    for (x1, y1, x2, y2) in boxes:
        cv2.rectangle(frame, (x1,y1), (x2,y2), (0,0,0), 3)

    cv2.imshow("frame", frame)
    cv2.imshow("mask", mask)
    if cv2.waitKey(1) & 0xFF == 27:
        break
cap.release()
cv2.destroyAllWindows()
