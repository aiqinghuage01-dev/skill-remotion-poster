#!/usr/bin/env python3
"""
Detect face position in a digital human video.
Samples multiple frames, finds the most stable face bounding box,
and outputs the optimal CSS objectPosition for circular cropping.

Usage:
  python3 scripts/detect-face.py public/digital-human-2-clean.mp4
  python3 scripts/detect-face.py public/digital-human.mp4 --circle-size 200

Output (JSON to stdout):
  {
    "face": {"x": 360, "y": 280, "w": 200, "h": 200},
    "video": {"width": 720, "height": 1280},
    "objectPosition": "center 18.5%",
    "cropPosition": "center 18.5%"
  }
"""

import sys
import json
import os
import cv2
import numpy as np

def detect_face_in_frame(frame, cascade):
    """Detect the largest face in a frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(50, 50),
        flags=cv2.CASCADE_SCALE_IMAGE
    )

    if len(faces) == 0:
        return None

    # Return the largest face
    areas = [w * h for (x, y, w, h) in faces]
    idx = np.argmax(areas)
    return faces[idx]

def main():
    video_path = sys.argv[1] if len(sys.argv) > 1 else None
    circle_size = 200

    # Parse --circle-size argument
    for i, arg in enumerate(sys.argv):
        if arg == '--circle-size' and i + 1 < len(sys.argv):
            circle_size = int(sys.argv[i + 1])

    if not video_path:
        print("Usage: python3 detect-face.py <video_path> [--circle-size 200]", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(video_path):
        print(f"Error: File not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    # Load Haar cascade
    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    cascade = cv2.CascadeClassifier(cascade_path)

    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video: {video_path}", file=sys.stderr)
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Video: {width}x{height}, {total_frames} frames, {fps:.1f} fps", file=sys.stderr)

    # Sample frames at regular intervals (10 samples across the video)
    num_samples = 15
    sample_indices = np.linspace(
        int(fps * 1),  # skip first second
        total_frames - int(fps * 1),  # skip last second
        num_samples,
        dtype=int
    )

    detections = []

    for frame_idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        face = detect_face_in_frame(frame, cascade)
        if face is not None:
            x, y, w, h = face
            # Store face center and size
            cx = x + w / 2
            cy = y + h / 2
            detections.append({
                'cx': cx, 'cy': cy, 'w': w, 'h': h,
                'x': int(x), 'y': int(y),
                'frame': int(frame_idx)
            })
            print(f"  Frame {frame_idx}: face at ({cx:.0f}, {cy:.0f}) size {w}x{h}", file=sys.stderr)

    cap.release()

    if not detections:
        print("Error: No face detected in any sampled frame!", file=sys.stderr)
        # Fallback: center
        result = {
            "face": None,
            "video": {"width": width, "height": height},
            "objectPosition": "center center",
            "cropPosition": "center center",
            "confidence": 0
        }
        print(json.dumps(result, indent=2))
        sys.exit(0)

    print(f"\nDetected face in {len(detections)}/{num_samples} frames", file=sys.stderr)

    # Use median for robustness against outliers
    med_cx = np.median([d['cx'] for d in detections])
    med_cy = np.median([d['cy'] for d in detections])
    med_w = np.median([d['w'] for d in detections])
    med_h = np.median([d['h'] for d in detections])

    print(f"Median face center: ({med_cx:.0f}, {med_cy:.0f}), size: {med_w:.0f}x{med_h:.0f}", file=sys.stderr)

    # Calculate objectPosition for CSS
    # objectPosition is specified as percentages where:
    # - X%: 0% = left edge, 50% = center, 100% = right edge
    # - Y%: 0% = top, 50% = middle, 100% = bottom
    #
    # For a circular crop (objectFit: cover), we want the face center
    # to be in the center of the circle.
    #
    # The video is displayed in a circle of `circle_size` px.
    # objectFit: cover means the video is scaled to fill the circle,
    # maintaining aspect ratio, then cropped.
    #
    # For a portrait video (taller than wide) displayed in a square circle:
    # - Width fills exactly → X position doesn't matter much
    # - Height is cropped → Y position determines which vertical slice is shown
    #
    # objectPosition Y% means: at Y%, the viewport center aligns with that % of the image.

    x_pct = (med_cx / width) * 100
    y_pct = (med_cy / height) * 100

    # Round to 1 decimal
    x_pct = round(x_pct, 1)
    y_pct = round(y_pct, 1)

    # For portrait videos, X is typically ~50% (centered)
    x_str = "center" if abs(x_pct - 50) < 10 else f"{x_pct}%"
    y_str = f"{y_pct}%"

    object_position = f"{x_str} {y_str}"

    print(f"\nRecommended objectPosition: '{object_position}'", file=sys.stderr)

    # Calculate face-to-video ratio (useful for sizing the circle)
    face_ratio = med_w / width
    print(f"Face-to-video-width ratio: {face_ratio:.2%}", file=sys.stderr)

    result = {
        "face": {
            "centerX": round(med_cx),
            "centerY": round(med_cy),
            "width": round(med_w),
            "height": round(med_h)
        },
        "video": {
            "width": width,
            "height": height
        },
        "objectPosition": object_position,
        "cropPosition": object_position,
        "faceRatio": round(face_ratio, 3),
        "confidence": len(detections) / num_samples,
        "samplesUsed": len(detections),
        "totalSamples": num_samples
    }

    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
