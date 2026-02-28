import cv2

def digital_zoom(frame, zoom=1.0):
    h, w = frame.shape[:2]
    if zoom <= 1.0:
        return frame
    new_w, new_h = int(w / zoom), int(h / zoom)
    x1, y1 = (w - new_w)//2, (h - new_h)//2
    crop = frame[y1:y1+new_h, x1:x1+new_w]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)

cap = cv2.VideoCapture(0)

zoom = 1.0
while True:
    ret, frame = cap.read()
    if not ret: break

    out = digital_zoom(frame, zoom)
    cv2.imshow("C920 Zoom", out)

    k = cv2.waitKey(1) & 0xFF
    if k == ord('q'): break
    if k in (ord('+'), ord('=')): zoom = min(zoom + 0.2, 6.0)
    if k in (ord('-'), ord('_')): zoom = max(1.0, zoom - 0.2)

cap.release()
cv2.destroyAllWindows()