import cv2
import mediapipe as mp
import numpy as np
import math
import psutil
import time

# --- Camera & Window Setup ---
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# --- MediaPipe Hands ---
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.75, min_tracking_confidence=0.7)

# --- Hologram State ---
holo_center = np.array([640.0, 360.0])
holo_scale = 130.0
holo_rot_x = 25.0
holo_rot_y = 0.0
holo_rot_z = 0.0
is_locked = False
grab_offset = np.array([0.0, 0.0])
prev_hand_pos = None

# Palettes (BGR)
CYAN = (255, 230, 0)
GOLD = (0, 215, 255)
BLUE = (255, 140, 0)
WHITE = (255, 255, 255)
DARK_BLUE = (120, 50, 0)
RED_ALERT = (0, 0, 255)

def rotate_point(pt, ax, ay, az):
    rad_x, rad_y, rad_z = np.radians(ax), np.radians(ay), np.radians(az)
    Rx = np.array([[1, 0, 0], [0, np.cos(rad_x), -np.sin(rad_x)], [0, np.sin(rad_x), np.cos(rad_x)]])
    Ry = np.array([[np.cos(rad_y), 0, np.sin(rad_y)], [0, 1, 0], [-np.sin(rad_y), 0, np.cos(rad_y)]])
    Rz = np.array([[np.cos(rad_z), -np.sin(rad_z), 0], [np.sin(rad_z), np.cos(rad_z), 0], [0, 0, 1]])
    return pt @ Rx @ Ry @ Rz

def project_3d(pt, center, scale, fov=350):
    z = pt[2] * (scale / 100.0) + 3.0
    x = int(center[0] + (pt[0] * scale * fov) / (z * 100.0))
    y = int(center[1] + (pt[1] * scale * fov) / (z * 100.0))
    return (x, y)

def draw_arc_reactor(overlay, center, scale, rot_x, rot_y, rot_z, t):
    cx, cy = int(center[0]), int(center[1])
    
    # 1. Outer Gyroscope Rings (3D tilted)
    for radius_factor, speed_mult, col in [(1.6, 1.0, CYAN), (1.4, -1.3, BLUE), (1.1, 2.0, CYAN)]:
        ring_pts = []
        for deg in range(0, 360, 10):
            rad = np.radians(deg)
            pt = np.array([radius_factor * np.cos(rad), radius_factor * np.sin(rad), 0.0])
            rot_pt = rotate_point(pt, rot_x, rot_y + (t * speed_mult * 20) % 360, rot_z)
            ring_pts.append(project_3d(rot_pt, center, scale))
        
        for i in range(len(ring_pts)):
            cv2.line(overlay, ring_pts[i], ring_pts[(i + 1) % len(ring_pts)], col, 1, cv2.LINE_AA)

    # 2. 10 Electromagnetic Induction Coils (Toroid segments)
    num_coils = 10
    for i in range(num_coils):
        angle = (i * (360 / num_coils)) + (t * 15) % 360
        rad = np.radians(angle)
        
        # Coil 3D boundaries
        p_in = np.array([0.65 * np.cos(rad), 0.65 * np.sin(rad), 0.0])
        p_out = np.array([0.95 * np.cos(rad), 0.95 * np.sin(rad), 0.0])
        p_high = np.array([0.80 * np.cos(rad), 0.80 * np.sin(rad), 0.15])
        
        pt1 = project_3d(rotate_point(p_in, rot_x, rot_y, rot_z), center, scale)
        pt2 = project_3d(rotate_point(p_out, rot_x, rot_y, rot_z), center, scale)
        pt3 = project_3d(rotate_point(p_high, rot_x, rot_y, rot_z), center, scale)
        
        cv2.line(overlay, pt1, pt2, GOLD, 2, cv2.LINE_AA)
        cv2.line(overlay, pt2, pt3, CYAN, 1, cv2.LINE_AA)
        cv2.line(overlay, pt3, pt1, CYAN, 1, cv2.LINE_AA)

    # 3. Central Core Plasma & Particle Emitters
    core_pt = project_3d(rotate_point(np.array([0, 0, 0]), rot_x, rot_y, rot_z), center, scale)
    cv2.circle(overlay, core_pt, int(scale * 0.25), CYAN, -1)
    cv2.circle(overlay, core_pt, int(scale * 0.18), WHITE, -1)

    # 4. Rotating Audio/Energy Waveform Ring
    wave_pts = []
    for deg in range(0, 360, 5):
        wave_freq = math.sin(np.radians(deg * 6) + t * 5) * 0.08
        r = 1.25 + wave_freq
        rad = np.radians(deg)
        pt = np.array([r * np.cos(rad), r * np.sin(rad), 0.0])
        wave_pts.append(project_3d(rotate_point(pt, rot_x, rot_y, rot_z), center, scale))
    for i in range(len(wave_pts)):
        cv2.line(overlay, wave_pts[i], wave_pts[(i + 1) % len(wave_pts)], CYAN, 1, cv2.LINE_AA)

def draw_hud_elements(frame, t):
    h, w, _ = frame.shape
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    
    # --- Top Banner Diagnostics ---
    cv2.line(frame, (40, 40), (w - 40, 40), CYAN, 1)
    cv2.line(frame, (40, 40), (40, 65), CYAN, 2)
    cv2.line(frame, (w - 40, 40), (w - 40, 65), CYAN, 2)
    cv2.putText(frame, "MARK-LXXXV // TACTICAL SCHEMATIC INTERFACE", (60, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.45, CYAN, 1)
    cv2.putText(frame, "ONLINE // GESTURE GIMBAL READY", (w - 320, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

    # --- Left Diagnostics Bracket ---
    cv2.rectangle(frame, (40, 70), (280, 200), (20, 20, 20), -1)
    cv2.rectangle(frame, (40, 70), (280, 200), CYAN, 1)
    cv2.putText(frame, "SYSTEM METRICS", (55, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.45, GOLD, 1)
    cv2.putText(frame, f"CORE FREQ:  {cpu}%", (55, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
    cv2.putText(frame, f"BUFFER:     {ram}%", (55, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
    cv2.putText(frame, f"REPULSOR:   {98.4 + math.sin(t)*1.2:.1f}%", (55, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 180), 1)

    # --- Right Radar Hex Grid ---
    rcx, rcy = w - 120, 140
    cv2.circle(frame, (rcx, rcy), 55, DARK_BLUE, -1)
    cv2.circle(frame, (rcx, rcy), 55, CYAN, 1)
    cv2.circle(frame, (rcx, rcy), 25, CYAN, 1)
    radar_angle = math.radians((t * 90) % 360)
    cv2.line(frame, (rcx, rcy), (int(rcx + 55 * math.cos(radar_angle)), int(rcy + 55 * math.sin(radar_angle))), CYAN, 2)
    cv2.putText(frame, "RADAR LOCK", (w - 170, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.4, CYAN, 1)

def draw_palm_target(frame, center, is_pinching):
    cx, cy = int(center[0]), int(center[1])
    color = (0, 255, 0) if is_pinching else CYAN
    size = 20
    # Corner brackets around hand
    cv2.line(frame, (cx - size, cy - size), (cx - size + 10, cy - size), color, 2)
    cv2.line(frame, (cx - size, cy - size), (cx - size, cy - size + 10), color, 2)
    cv2.line(frame, (cx + size, cy - size), (cx + size - 10, cy - size), color, 2)
    cv2.line(frame, (cx + size, cy - size), (cx + size, cy - size + 10), color, 2)
    cv2.line(frame, (cx - size, cy + size), (cx - size + 10, cy + size), color, 2)
    cv2.line(frame, (cx - size, cy + size), (cx - size, cy + size - 10), color, 2)
    cv2.line(frame, (cx + size, cy + size), (cx + size - 10, cy + size), color, 2)
    cv2.line(frame, (cx + size, cy + size), (cx + size, cy + size - 10), color, 2)
    cv2.putText(frame, "LOCK" if is_pinching else "TARGET", (cx - 22, cy - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

# --- Main Interaction Loop ---
start_time = time.time()

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    t = time.time() - start_time
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb)

    active_hands = []
    if results.multi_hand_landmarks:
        for lms in results.multi_hand_landmarks:
            idx = np.array([lms.landmark[8].x * w, lms.landmark[8].y * h])
            thmb = np.array([lms.landmark[4].x * w, lms.landmark[4].y * h])
            wrist = np.array([lms.landmark[0].x * w, lms.landmark[0].y * h])
            pinch_dist = np.linalg.norm(idx - thmb)
            mid = (idx + thmb) / 2
            is_pinch = pinch_dist < 42
            active_hands.append({'mid': mid, 'pinch': is_pinch, 'wrist': wrist})
            draw_palm_target(frame, mid, is_pinch)

    # --- Gestures Engine ---
    if len(active_hands) == 1:
        hand = active_hands[0]
        if hand['pinch']:
            # Grab & Drag
            if not is_locked:
                grab_offset = holo_center - hand['mid']
                is_locked = True
            holo_center = hand['mid'] + grab_offset
            prev_hand_pos = None
        else:
            is_locked = False
            # Gimbal Rotation: Move hand without pinching to rotate core in 3D
            if prev_hand_pos is not None:
                delta = hand['mid'] - prev_hand_pos
                holo_rot_y += delta[0] * 0.4
                holo_rot_x -= delta[1] * 0.4
            prev_hand_pos = hand['mid']

    elif len(active_hands) >= 2:
        h1, h2 = active_hands[0], active_hands[1]
        prev_hand_pos = None
        # Two-Hand Pinch: Dynamic Zoom/Scale
        if h1['pinch'] and h2['pinch']:
            span = np.linalg.norm(h1['mid'] - h2['mid'])
            holo_scale = np.clip(span * 0.6, 60.0, 380.0)
            holo_center = (h1['mid'] + h2['mid']) / 2
            cv2.putText(frame, "RESONANCE SCALING ACTIVE", (w // 2 - 130, h - 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, GOLD, 2)
        else:
            is_locked = False
    else:
        is_locked = False
        prev_hand_pos = None
        # Slow idle drift when hands are out of view
        holo_rot_y += 0.5

    # --- Render Hologram Layer with Alpha Glow ---
    holo_layer = np.zeros_like(frame)
    draw_arc_reactor(holo_layer, holo_center, holo_scale, holo_rot_x, holo_rot_y, holo_rot_z, t)
    
    # Additive blend creates the translucent neon glow over camera
    frame = cv2.addWeighted(frame, 1.0, holo_layer, 1.2, 0)
    
    # Render 2D Interface Overlays
    draw_hud_elements(frame, t)

    cv2.imshow("JARVIS Mark-85 Hologram Laboratory", frame)
    if cv2.waitKey(1) & 0xFF == 27:  # Esc to exit
        break

cap.release()
cv2.destroyAllWindows()