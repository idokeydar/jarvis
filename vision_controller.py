import cv2
import numpy as np
import math
import time
import random

# ----------------- MEDIAPIPE INITIALIZATION -----------------
import mediapipe as mp
mp_hands = mp.solutions.hands
mp_face = mp.solutions.face_detection

hands_detector = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.75,
    min_tracking_confidence=0.7
)
face_detector = mp_face.FaceDetection(min_detection_confidence=0.6)

# ----------------- CAMERA SETUP -----------------
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
if not cap.isOpened():
    cap = cv2.VideoCapture(0)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# ----------------- 3D MODEL GEOMETRY -----------------
def generate_stark_suit_geometry():
    vertices = []
    edges = []
    group_map = []

    # 1. Helmet
    h_idx = len(vertices)
    h_verts = [
        [-35, -130, 25], [35, -130, 25], [45, -75, 30], [28, -40, 25], [-28, -40, 25], [-45, -75, 30],
        [-40, -140, -30], [40, -140, -30], [50, -75, -35], [35, -35, -30], [-35, -35, -30], [-50, -75, -35],
        [-25, -95, 32], [-10, -95, 32], [-12, -85, 32], [-25, -85, 32],
        [10, -95, 32], [25, -95, 32], [25, -85, 32], [12, -85, 32]
    ]
    for v in h_verts:
        vertices.append(v)
        group_map.append("helmet")
    h_edges = [
        (0,1), (1,2), (2,3), (3,4), (4,5), (5,0),
        (6,7), (7,8), (8,9), (9,10), (10,11), (11,6),
        (0,6), (1,7), (2,8), (3,9), (4,10), (5,11),
        (12,13), (13,14), (14,15), (15,12),
        (16,17), (17,18), (18,19), (19,16)
    ]
    for e in h_edges:
        edges.append((h_idx + e[0], h_idx + e[1]))

    # 2. Chest & Arc Reactor
    c_idx = len(vertices)
    c_verts = [
        [-65, -30, 20], [65, -30, 20], [80, 50, 25], [45, 95, 20], [-45, 95, 20], [-80, 50, 25],
        [-55, -30, -35], [55, -30, -35], [70, 50, -35], [40, 95, -30], [-40, 95, -30], [-70, 50, -35],
        [-18, 15, 30], [0, -3, 30], [18, 15, 30], [12, 35, 30], [-12, 35, 30]
    ]
    for v in c_verts:
        vertices.append(v)
        group_map.append("chest")
    c_edges = [
        (0,1), (1,2), (2,3), (3,4), (4,5), (5,0),
        (6,7), (7,8), (8,9), (9,10), (10,11), (11,6),
        (0,6), (1,7), (2,8), (3,9), (4,10), (5,11),
        (12,13), (13,14), (14,15), (15,16), (16,12),
        (0,12), (1,14), (3,15), (4,16)
    ]
    for e in c_edges:
        edges.append((c_idx + e[0], c_idx + e[1]))

    # 3. Shoulders
    lp_idx = len(vertices)
    lp_verts = [
        [-75, -28, 15], [-115, -15, 10], [-130, 30, 5], [-85, 35, 15],
        [-70, -28, -25], [-110, -15, -25], [-120, 30, -20], [-80, 35, -20]
    ]
    for v in lp_verts:
        vertices.append(v)
        group_map.append("left_shoulder")
    for e in [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]:
        edges.append((lp_idx + e[0], lp_idx + e[1]))

    rp_idx = len(vertices)
    rp_verts = [
        [75, -28, 15], [115, -15, 10], [130, 30, 5], [85, 35, 15],
        [70, -28, -25], [110, -15, -25], [120, 30, -20], [80, 35, -20]
    ]
    for v in rp_verts:
        vertices.append(v)
        group_map.append("right_shoulder")
    for e in [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]:
        edges.append((rp_idx + e[0], rp_idx + e[1]))

    return np.array(vertices, dtype=float), edges, group_map

mesh_verts, mesh_edges, mesh_groups = generate_stark_suit_geometry()

# Transformation States
rot_x = 0.05
rot_y = 0.0
holo_center = [640.0, 340.0]
target_holo_center = [640.0, 340.0]
zoom = 1.15
target_zoom = 1.15
explode_factor = 0.0
target_explode = 0.0
prev_drag = None
drag_vel = [0.0, 0.0]
is_discarded = False
discard_alpha = 1.0

# Nanite Particle Field
nanites = [{"pos": [random.randint(520, 760), random.randint(220, 460)], 
            "vel": [random.uniform(-1, 1), random.uniform(-1, 1)], 
            "life": random.uniform(0.3, 1.0)} for _ in range(40)]

# Blast Flash State
repulsor_blast_rings = []
prev_hand_closed = [False, False]

scan_plane_y = -150.0

print("[Stark Tech] Advanced Mk 85 Holographic Workshop Active.")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.01)
        continue

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    t = time.time()

    # Cinematic Darkened Contrast
    hud = cv2.addWeighted(frame, 0.35, np.zeros_like(frame), 0.65, 0)

    # 1. HOLOGRAPHIC SCANNING PLANE (Laser cross-section line)
    scan_plane_y += 2.5
    if scan_plane_y > 150.0:
        scan_plane_y = -150.0

    # 2. HOLOGRAPHIC PEDESTAL TABLE (Hacksmith / GZreel Circular Emitter)
    emitter_cx, emitter_cy = int(holo_center[0]), 610
    emitter_rx, emitter_ry = int(240 * zoom), int(55 * zoom)
    for r_offset in [0, -30, -70, 35]:
        erx = max(10, emitter_rx + r_offset)
        ery = max(5, emitter_ry + int(r_offset * 0.25))
        cv2.ellipse(hud, (emitter_cx, emitter_cy), (erx, ery), 0, 0, 360, (255, 140, 0), 1, cv2.LINE_AA)

    # Base projection radial spokes
    for ang in range(0, 360, 30):
        rad = math.radians(ang + (t * 8))
        px1 = int(emitter_cx + (emitter_rx - 40) * math.cos(rad))
        py1 = int(emitter_cy + (emitter_ry - 10) * math.sin(rad))
        px2 = int(emitter_cx + emitter_rx * math.cos(rad))
        py2 = int(emitter_cy + emitter_ry * math.sin(rad))
        cv2.line(hud, (px1, py1), (px2, py2), (255, 200, 0), 1)

    # 3. BIOMETRIC FACE HUD
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faces = face_detector.process(rgb)
    if faces.detections:
        for det in faces.detections:
            bb = det.location_data.relative_bounding_box
            fx, fy, fw, fh = int(bb.xmin*w), int(bb.ymin*h), int(bb.width*w), int(bb.height*h)
            col = (0, 230, 255)
            cv2.line(hud, (fx, fy), (fx + 18, fy), col, 2)
            cv2.line(hud, (fx, fy), (fx, fy + 18), col, 2)
            cv2.line(hud, (fx + fw, fy + fh), (fx + fw - 18, fy + fh), col, 2)
            cv2.line(hud, (fx + fw, fy + fh), (fx + fw, fy + fh - 18), col, 2)
            cv2.putText(hud, "PILOT AUTH: T.STARK", (fx, fy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)

    # 4. HAND DETECTION & TACTILE GESTURES
    hands_res = hands_detector.process(rgb)
    hands_pts = []

    if hands_res.multi_hand_landmarks:
        for h_idx_num, hand in enumerate(hands_res.multi_hand_landmarks):
            mp.solutions.drawing_utils.draw_landmarks(hud, hand, mp_hands.HAND_CONNECTIONS)
            lm = {i: (int(pt.x * w), int(pt.y * h)) for i, pt in enumerate(hand.landmark)}
            hands_pts.append(lm)

            # Palmar Repulsor Arc
            px, py = lm[9]
            cv2.circle(hud, (px, py), 16, (255, 220, 0), 2)
            cv2.circle(hud, (px, py), 6, (255, 255, 255), -1)

            # Check for Repulsor Blast (Fist clench to open release)
            # Distance from tips to wrist (0)
            fingers_folded = all(
                math.hypot(lm[tip][0] - lm[0][0], lm[tip][1] - lm[0][1]) < 
                math.hypot(lm[tip-2][0] - lm[0][0], lm[tip-2][1] - lm[0][1])
                for tip in [8, 12, 16, 20]
            )

            if fingers_folded:
                cv2.circle(hud, (px, py), 22, (0, 100, 255), 3) # Charging red/orange glow
                prev_hand_closed[h_idx_num % 2] = True
            else:
                if prev_hand_closed[h_idx_num % 2]:
                    # Hand just popped open -> TRIGGER REPULSOR BLAST
                    repulsor_blast_rings.append({"pos": (px, py), "r": 20, "max_r": 160, "alpha": 1.0})
                    prev_hand_closed[h_idx_num % 2] = False

    # Process and draw expanding Repulsor Blast Shockwaves
    for blast in repulsor_blast_rings[:]:
        bx, by = blast["pos"]
        cv2.circle(hud, (bx, by), int(blast["r"]), (255, 255, 255), 3)
        cv2.circle(hud, (bx, by), int(blast["r"] * 0.7), (0, 255, 255), 2)
        blast["r"] += 12
        blast["alpha"] -= 0.08
        if blast["alpha"] <= 0 or blast["r"] >= blast["max_r"]:
            repulsor_blast_rings.remove(blast)

    # GESTURE: 1-Hand Pinch & Drag / Flick to Discard
    if len(hands_pts) == 1 and not is_discarded:
        th = hands_pts[0][4]
        ix = hands_pts[0][8]
        if math.hypot(th[0] - ix[0], th[1] - ix[1]) < 45:
            cv2.circle(hud, ix, 10, (0, 255, 120), 2)
            if prev_drag is not None:
                dx = ix[0] - prev_drag[0]
                dy = ix[1] - prev_drag[1]
                drag_vel = [dx, dy]
                rot_y += dx * 0.012
                rot_x += dy * 0.012
                holo_center[0] += dx
                holo_center[1] += dy
            prev_drag = ix
        else:
            if prev_drag is not None:
                # Released pinch: check for swipe/throw velocity
                speed = math.hypot(drag_vel[0], drag_vel[1])
                if speed > 22.0:
                    is_discarded = True # Flick to discard triggered
                prev_drag = None
            rot_y += 0.006

    # GESTURE: 2-Hand Volumetric Disassembly & Zoom
    elif len(hands_pts) >= 2 and not is_discarded:
        prev_drag = None
        h1 = hands_pts[0][9]
        h2 = hands_pts[1][9]
        dist = math.hypot(h1[0] - h2[0], h1[1] - h2[1])

        cv2.line(hud, h1, h2, (0, 220, 255), 1)
        mid = ((h1[0] + h2[0]) // 2, (h1[1] + h2[1]) // 2)
        cv2.putText(hud, f"CALIBRATION SPREAD: {int(dist)}", (mid[0]-80, mid[1]-15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

        target_explode = float(np.interp(dist, [120, 480], [0.0, 1.6]))
        target_zoom = float(np.interp(dist, [120, 480], [0.85, 1.5]))
    else:
        prev_drag = None
        rot_y += 0.006

    # Discard animation handling (flings away and respawns)
    if is_discarded:
        holo_center[0] += drag_vel[0] * 1.5
        holo_center[1] += drag_vel[1] * 1.5
        discard_alpha -= 0.05
        if discard_alpha <= 0.0:
            is_discarded = False
            discard_alpha = 1.0
            holo_center = [640.0, 340.0]
            drag_vel = [0.0, 0.0]

    # Smooth interpolations
    explode_factor += (target_explode - explode_factor) * 0.12
    zoom += (target_zoom - zoom) * 0.1

    # 5. 3D PROJECTION & EXPLODED MESH RENDERING
    Rx = np.array([[1, 0, 0], [0, math.cos(rot_x), -math.sin(rot_x)], [0, math.sin(rot_x), math.cos(rot_x)]])
    Ry = np.array([[math.cos(rot_y), 0, math.sin(rot_y)], [0, 1, 0], [-math.sin(rot_y), 0, math.cos(rot_y)]])
    R = np.dot(Ry, Rx)

    projected_nodes = []
    for idx, (x, y, z) in enumerate(mesh_verts):
        vx, vy, vz = x, y, z
        grp = mesh_groups[idx]

        if grp == "helmet":
            vy -= explode_factor * 60.0
            vz += explode_factor * 35.0
        elif grp == "chest":
            vz += explode_factor * 70.0
        elif grp == "left_shoulder":
            vx -= explode_factor * 65.0
            vy -= explode_factor * 20.0
        elif grp == "right_shoulder":
            vx += explode_factor * 65.0
            vy -= explode_factor * 20.0

        pt3d = np.dot(R, np.array([vx, vy, vz]) * zoom)
        px = int(holo_center[0] + pt3d[0])
        py = int(holo_center[1] + pt3d[1])
        projected_nodes.append((px, py, pt3d[1]))

    # Draw laser scanline intersecting the mesh
    scan_y_proj = int(holo_center[1] + scan_plane_y * zoom)
    cv2.line(hud, (int(holo_center[0] - 180 * zoom), scan_y_proj), (int(holo_center[0] + 180 * zoom), scan_y_proj), (0, 255, 255), 1)

    # Render suit wireframe bonds
    for e in mesh_edges:
        pt1 = (projected_nodes[e[0]][0], projected_nodes[e[0]][1])
        pt2 = (projected_nodes[e[1]][0], projected_nodes[e[1]][1])
        
        # Color highlight when passing through scanline
        mid_y = (pt1[1] + pt2[1]) // 2
        line_col = (255, 255, 255) if abs(mid_y - scan_y_proj) < 15 else (255, 220, 0)
        cv2.line(hud, pt1, pt2, line_col, 1, cv2.LINE_AA)

    for p in projected_nodes:
        cv2.circle(hud, (p[0], p[1]), 2, (0, 240, 255), -1)

    # 6. ACTIVE NANITE PARTICLE FIELD (Reacting to fingers)
    for part in nanites:
        # Attracted gently to fingertips if near
        for hpt in hands_pts:
            tip = hpt[8]
            pdist = math.hypot(part["pos"][0] - tip[0], part["pos"][1] - tip[1])
            if pdist < 120:
                part["vel"][0] += (tip[0] - part["pos"][0]) * 0.02
                part["vel"][1] += (tip[1] - part["pos"][1]) * 0.02

        part["pos"][0] += part["vel"][0]
        part["pos"][1] += part["vel"][1]
        part["vel"][0] *= 0.95
        part["vel"][1] *= 0.95

        cv2.circle(hud, (int(part["pos"][0]), int(part["pos"][1])), 1, (0, 255, 255), -1)

    # 7. FLOATING STARK CAD TELEMETRY CARDS
    cv2.rectangle(hud, (30, 200), (240, 340), (255, 140, 0), 1)
    cv2.line(hud, (30, 230), (240, 230), (255, 140, 0), 1)
    cv2.putText(hud, "SUIT SCHEMATIC: MK LXXXV", (40, 222), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 230, 100), 1)
    cv2.putText(hud, f"NANITE MATRIX: {'DECOUPLED' if explode_factor > 0.4 else 'STRUCTURAL'}", (40, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 180), 1)
    cv2.putText(hud, f"EXPLOSION: {int(explode_factor*100)}%", (40, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    cv2.putText(hud, f"SCAN FREQ: 32.4 GHz", (40, 305), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    cv2.rectangle(hud, (1040, 200), (1250, 340), (255, 140, 0), 1)
    cv2.line(hud, (1040, 230), (1250, 230), (255, 140, 0), 1)
    cv2.putText(hud, "ARC REACTOR OUTPUT", (1050, 222), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 230, 100), 1)
    cv2.putText(hud, "VOLTAGE: 4.2 GJ/sec", (1050, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 180), 1)
    cv2.putText(hud, "THRUSTER EFF: 98.4%", (1050, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    cv2.putText(hud, "STATUS: CAD ONLINE", (1050, 305), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 180), 1)

    # Header & Footer branding
    cv2.putText(hud, "STARK INDUSTRIES // ADVANCED PROJECTION LAB", (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 200, 0), 2)
    cv2.putText(hud, "MARK 57 VOLUMETRIC SYSTEM", (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 200), 1)

    cv2.imshow("Stark Holographic Workspace", hud)

    k = cv2.waitKey(1) & 0xFF
    if k == ord('q') or k == 27:
        break

cap.release()
cv2.destroyAllWindows()