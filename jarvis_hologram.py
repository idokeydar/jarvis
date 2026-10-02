import cv2
import mediapipe as mp
import numpy as np
import math

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(min_detection_confidence=0.7, min_tracking_confidence=0.7)
mp_draw = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)

# Hologram state variables
holo_angle = 0
holo_size = 120
center_pos = [320, 240]

def draw_hologram_hud(img, center, radius, angle):
    cx, cy = int(center[0]), int(center[1])
    
    # Outer dashed/segmented arc
    for i in range(0, 360, 30):
        start_a = math.radians(i + angle)
        end_a = math.radians(i + angle + 18)
        pt1 = (int(cx + radius * math.cos(start_a)), int(cy + radius * math.sin(start_a)))
        pt2 = (int(cx + radius * math.cos(end_a)), int(cy + radius * math.sin(end_a)))
        cv2.line(img, pt1, pt2, (255, 230, 0), 2)  # Cyan/Blue hue in BGR

    # Inner rings
    cv2.circle(img, (cx, cy), int(radius * 0.7), (255, 180, 0), 1)
    cv2.circle(img, (cx, cy), int(radius * 0.4), (200, 255, 0), 2)
    cv2.circle(img, (cx, cy), 6, (255, 255, 255), -1)

    # Crosshair ticks
    offset = int(radius * 1.15)
    cv2.line(img, (cx - offset, cy), (cx - int(radius * 0.8), cy), (255, 200, 0), 1)
    cv2.line(img, (cx + int(radius * 0.8), cy), (cx + offset, cy), (255, 200, 0), 1)
    cv2.line(img, (cx, cy - offset), (cx, cy - int(radius * 0.8)), (255, 200, 0), 1)
    cv2.line(img, (cx, cy + int(radius * 0.8)), (cx, cy + offset), (255, 200, 0), 1)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # Flip horizontally for natural mirror interaction
    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = hands.process(rgb_frame)

    holo_angle = (holo_angle + 2) % 360

    if result.multi_hand_landmarks:
        for hand_landmarks in result.multi_hand_landmarks:
            lm = hand_landmarks.landmark
            index_tip = np.array([lm[8].x * w, lm[8].y * h])
            thumb_tip = np.array([lm[4].x * w, lm[4].y * h])

            # Calculate pinch distance
            pinch_dist = np.linalg.norm(index_tip - thumb_tip)

            # Draw minimal hand node trackers
            for pt in [index_tip, thumb_tip]:
                cv2.circle(frame, (int(pt[0]), int(pt[1])), 8, (0, 255, 255), -1)

            # Pinch detection (threshold < 40px)
            if pinch_dist < 40:
                # Move hologram with hand
                center_pos = [int(index_tip[0]), int(index_tip[1])]
                cv2.putText(frame, "TRACKING / LOCKED", (30, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            else:
                cv2.putText(frame, "IDLE - PINCH TO GRAB", (30, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

    # Render HUD over webcam stream
    draw_hologram_hud(frame, center_pos, holo_size, holo_angle)

    cv2.imshow("JARVIS Hologram Controller", frame)
    if cv2.waitKey(1) & 0xFF == 27:  # Esc to exit
        break

cap.release()
cv2.destroyAllWindows()