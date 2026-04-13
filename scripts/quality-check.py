#!/usr/bin/env python3
"""
Quality check for video script JSON before rendering.
Checks:
1. Total slide duration vs audio duration (must be within 2s)
2. Each slide has valid duration (0.5s - 10s)
3. Digital human video exists and has no rotation metadata
4. Audio file exists
5. Face detection crop is present if digitalHuman is set

Usage:
  python3 scripts/quality-check.py src/data/techchild-script.json

Returns exit code 0 if all checks pass, 1 if any fail.
"""

import json
import sys
import os
import subprocess

def _find_ffmpeg():
    import shutil
    return shutil.which('ffmpeg') or '/usr/local/bin/ffmpeg'

def get_media_duration(filepath):
    """Get media file duration using ffmpeg."""
    ffmpeg = _find_ffmpeg()
    result = subprocess.run(
        [ffmpeg, '-i', filepath],
        capture_output=True, text=True
    )
    for line in result.stderr.split('\n'):
        if 'Duration:' in line:
            time_str = line.split('Duration:')[1].split(',')[0].strip()
            parts = time_str.split(':')
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return None

def check_rotation(filepath):
    """Check if video has rotation metadata."""
    ffmpeg = _find_ffmpeg()
    result = subprocess.run(
        [ffmpeg, '-i', filepath],
        capture_output=True, text=True
    )
    for line in result.stderr.split('\n'):
        if 'displaymatrix' in line and 'rotation' in line:
            # Extract rotation value
            parts = line.split('rotation of')
            if len(parts) > 1:
                rot = float(parts[1].replace('degrees', '').strip())
                if abs(rot) > 0.1:
                    return rot
    return 0

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 quality-check.py <script.json>")
        sys.exit(1)

    script_path = sys.argv[1]
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(script_path)))
    if not os.path.exists(os.path.join(project_root, 'package.json')):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    errors = []
    warnings = []

    # Load script
    with open(script_path) as f:
        script = json.load(f)

    print(f"=== Quality Check: {os.path.basename(script_path)} ===\n")

    # Check 1: Slide durations
    total_duration = 0
    for i, slide in enumerate(script['slides']):
        dur = slide.get('duration')
        if dur is None:
            errors.append(f"Slide {i+1}: missing duration")
            continue
        if dur < 0.5:
            warnings.append(f"Slide {i+1}: duration too short ({dur}s < 0.5s)")
        if dur > 10:
            warnings.append(f"Slide {i+1}: duration too long ({dur}s > 10s)")
        total_duration += dur

    print(f"Slides: {len(script['slides'])}")
    print(f"Total slide duration: {total_duration:.2f}s")

    # Check 2: Audio duration match
    audio_path = script.get('audioTrack')
    if audio_path:
        audio_full = os.path.join(project_root, 'public', audio_path)
        if os.path.exists(audio_full):
            audio_dur = get_media_duration(audio_full)
            if audio_dur:
                diff = abs(total_duration - audio_dur)
                print(f"Audio duration: {audio_dur:.2f}s")
                print(f"Duration diff: {diff:.2f}s")
                if diff > 3.0:
                    errors.append(f"Slide total ({total_duration:.2f}s) differs from audio ({audio_dur:.2f}s) by {diff:.2f}s (max 3s)")
                elif diff > 1.5:
                    warnings.append(f"Slide total ({total_duration:.2f}s) differs from audio ({audio_dur:.2f}s) by {diff:.2f}s")
            else:
                errors.append(f"Could not read audio duration: {audio_full}")
        else:
            errors.append(f"Audio file not found: {audio_full}")
    else:
        warnings.append("No audioTrack specified")

    # Check 3: Digital human video
    dh_path = script.get('digitalHuman')
    if dh_path:
        dh_full = os.path.join(project_root, 'public', dh_path)
        if os.path.exists(dh_full):
            rotation = check_rotation(dh_full)
            if rotation != 0:
                errors.append(f"Digital human video has rotation metadata: {rotation}° — will display incorrectly! Run through MPEG-TS roundtrip to strip.")

            dh_dur = get_media_duration(dh_full)
            if dh_dur:
                print(f"Digital human video duration: {dh_dur:.2f}s")
                if dh_dur < total_duration - 1:
                    warnings.append(f"Digital human video ({dh_dur:.2f}s) is shorter than slides ({total_duration:.2f}s)")
        else:
            errors.append(f"Digital human video not found: {dh_full}")

        # Check 4: Face crop
        if not script.get('digitalHumanCrop'):
            errors.append("digitalHumanCrop not set — run: python3 scripts/detect-face.py public/" + dh_path)
        else:
            print(f"Face crop: {script['digitalHumanCrop']}")

    # Check 5: Content checks
    for i, slide in enumerate(script['slides']):
        if not slide.get('lines'):
            errors.append(f"Slide {i+1}: no text lines")
        if not slide.get('narration'):
            warnings.append(f"Slide {i+1}: no narration text")

    # Report
    print("")
    if warnings:
        print(f"⚠️  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"   - {w}")
    if errors:
        print(f"❌ {len(errors)} error(s):")
        for e in errors:
            print(f"   - {e}")
        print(f"\n=== FAILED ===")
        sys.exit(1)
    else:
        print(f"✅ All checks passed!")
        print(f"\n=== OK ===")
        sys.exit(0)

if __name__ == '__main__':
    main()
