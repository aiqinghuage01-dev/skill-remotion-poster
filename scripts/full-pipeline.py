#!/usr/bin/env python3
"""
Full Pipeline: Digital Human Video → Card-Style Video
Handles: rotation fix, audio extraction, retake detection/removal,
face detection, Whisper transcription, script generation, quality check.

Usage:
  python3 scripts/full-pipeline.py <video_path_or_url> [--name <project_name>] [--shiliu]

Modes:
  1. Local file:  python3 scripts/full-pipeline.py ~/video.mp4 --name my-project
  2. URL:         python3 scripts/full-pipeline.py https://example.com/video.mp4 --name my-project
  3. ShiLiu mode: python3 scripts/full-pipeline.py <path_or_url> --name my-project --shiliu
     (Skips retake detection — ShiLiu AI-generated videos have no retakes)

Output:
  - public/<name>.mp4           (clean digital human video)
  - public/audio/<name>.mp3     (clean audio)
  - src/data/<name>-script.json (script ready for rendering, needs user review)
  - Prints quality check results

After user reviews and fixes the script JSON, render with:
  node scripts/render-card.mjs src/data/<name>-script.json
"""

import sys
import os
import json
import subprocess
import shutil
import re
import urllib.request
import urllib.error
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

FFMPEG = None  # Auto-detected
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def find_ffmpeg():
    """Find ffmpeg binary."""
    candidates = [
        shutil.which('ffmpeg'),
        '/usr/local/bin/ffmpeg',
        '/opt/homebrew/bin/ffmpeg',
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    print("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
    sys.exit(1)


def is_url(path):
    """Check if the given path is a URL."""
    return path.startswith('http://') or path.startswith('https://')


def download_video(url, dest_path):
    """Download video from URL with progress reporting."""
    print(f"  Downloading from: {url}")
    print(f"  Saving to: {dest_path}")

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = resp.headers.get('Content-Length')
            total = int(total) if total else None

            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB
            with open(dest_path, 'wb') as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        mb = downloaded / 1024 / 1024
                        print(f"\r  Progress: {mb:.1f}MB / {total/1024/1024:.1f}MB ({pct:.0f}%)", end='', flush=True)
                    else:
                        mb = downloaded / 1024 / 1024
                        print(f"\r  Downloaded: {mb:.1f}MB", end='', flush=True)

            print()  # newline after progress

        if os.path.getsize(dest_path) < 10000:
            print(f"  ❌ Downloaded file too small ({os.path.getsize(dest_path)} bytes), likely an error page")
            sys.exit(1)

        print(f"  ✅ Download complete: {os.path.getsize(dest_path) / 1024 / 1024:.1f}MB")
        return dest_path

    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP Error {e.code}: {e.reason}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"  ❌ URL Error: {e.reason}")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ Download failed: {e}")
        sys.exit(1)


def ensure_dependencies():
    """Check and install Python dependencies."""
    missing = []
    try:
        import cv2
    except ImportError:
        missing.append('opencv-python-headless')
    try:
        import whisper
    except ImportError:
        missing.append('openai-whisper')

    if missing:
        print(f"Installing missing dependencies: {', '.join(missing)}")
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--quiet'] + missing,
            check=True
        )
        print("Dependencies installed.\n")


def run_ffmpeg(*args, check=True):
    """Run ffmpeg command."""
    cmd = [FFMPEG] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ffmpeg error:\n{result.stderr}")
        sys.exit(1)
    return result


def get_media_info(filepath):
    """Get media file info from ffmpeg."""
    result = run_ffmpeg('-i', filepath, check=False)
    info = {
        'duration': None,
        'width': None,
        'height': None,
        'fps': None,
        'rotation': 0,
        'has_audio': False,
    }

    for line in result.stderr.split('\n'):
        # Duration
        if 'Duration:' in line:
            m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', line)
            if m:
                info['duration'] = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))

        # Video stream
        if 'Video:' in line and 'Stream' in line:
            m = re.search(r'(\d{3,4})x(\d{3,4})', line)
            if m:
                info['width'] = int(m.group(1))
                info['height'] = int(m.group(2))
            m = re.search(r'([\d.]+)\s*fps', line)
            if m:
                info['fps'] = float(m.group(1))

        # Audio stream
        if 'Audio:' in line and 'Stream' in line:
            info['has_audio'] = True

        # Rotation
        if 'displaymatrix' in line and 'rotation' in line:
            m = re.search(r'rotation of\s*([-\d.]+)', line)
            if m:
                info['rotation'] = float(m.group(1))

    return info


# ─── Step 1: Copy & Fix Rotation ────────────────────────────────────────────

def step1_prepare_video(video_path, name):
    """Copy video to public/, fix rotation if needed."""
    print("=" * 60)
    print("Step 1: Prepare Video")
    print("=" * 60)

    info = get_media_info(video_path)
    print(f"  Source: {video_path}")
    print(f"  Size: {info['width']}x{info['height']}, {info['duration']:.1f}s, {info['fps']} fps")

    output_raw = PROJECT_ROOT / 'public' / f'{name}-raw.mp4'
    output_clean = PROJECT_ROOT / 'public' / f'{name}.mp4'

    # Check rotation
    if abs(info['rotation']) > 0.1:
        print(f"  ⚠️  Rotation detected: {info['rotation']}°")
        print(f"  Fixing rotation via re-encode + MPEG-TS roundtrip...")

        # Re-encode with auto-rotation applied
        tmp1 = '/tmp/pipeline-step1a.mp4'
        run_ffmpeg(
            '-i', video_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k',
            tmp1, '-y'
        )

        # MPEG-TS roundtrip to strip displaymatrix
        tmp2 = '/tmp/pipeline-step1b.ts'
        run_ffmpeg('-i', tmp1, '-c', 'copy', '-f', 'mpegts', tmp2, '-y')
        run_ffmpeg(
            '-i', tmp2,
            '-c', 'copy', '-movflags', '+faststart',
            str(output_clean), '-y'
        )

        # Verify
        new_info = get_media_info(str(output_clean))
        if abs(new_info['rotation']) > 0.1:
            print(f"  ❌ Rotation still present after fix! Manual intervention needed.")
            sys.exit(1)
        print(f"  ✅ Rotation fixed: {new_info['width']}x{new_info['height']}")

        # Cleanup
        for f in [tmp1, tmp2]:
            try: os.remove(f)
            except: pass
    else:
        print(f"  No rotation issues.")
        shutil.copy2(video_path, str(output_clean))
        print(f"  ✅ Copied to {output_clean.name}")

    return str(output_clean)


# ─── Step 2: Extract Audio ──────────────────────────────────────────────────

def step2_extract_audio(video_path, name):
    """Extract audio from video."""
    print("\n" + "=" * 60)
    print("Step 2: Extract Audio")
    print("=" * 60)

    audio_dir = PROJECT_ROOT / 'public' / 'audio'
    audio_dir.mkdir(exist_ok=True)
    audio_path = audio_dir / f'{name}.mp3'

    run_ffmpeg(
        '-i', video_path,
        '-vn', '-acodec', 'libmp3lame', '-q:a', '2',
        str(audio_path), '-y'
    )

    info = get_media_info(str(audio_path))
    print(f"  ✅ Audio extracted: {audio_path.name} ({info['duration']:.1f}s)")
    return str(audio_path)


# ─── Step 3: Whisper Transcription ──────────────────────────────────────────

def step3_transcribe(audio_path):
    """Run Whisper transcription."""
    print("\n" + "=" * 60)
    print("Step 3: Whisper Transcription")
    print("=" * 60)

    import whisper
    model = whisper.load_model('base')
    result = model.transcribe(audio_path, language='zh', word_timestamps=True)

    segments = []
    for seg in result['segments']:
        segments.append({
            'start': round(seg['start'], 2),
            'end': round(seg['end'], 2),
            'text': seg['text'].strip(),
        })

    print(f"  Transcribed {len(segments)} segments:")
    for seg in segments:
        print(f"    [{seg['start']:6.2f} -> {seg['end']:6.2f}] {seg['text']}")

    return segments


# ─── Step 4: Detect Retakes ─────────────────────────────────────────────────

def step4_detect_retakes(segments):
    """Detect retake/stutter segments based on gaps and repetition."""
    print("\n" + "=" * 60)
    print("Step 4: Detect Retakes")
    print("=" * 60)

    retakes = []

    # Method 1: Prefix-based repetition detection
    # Look for segments where a later segment starts with the same characters
    # Only flag as retake if the gap between them has no meaningful content
    for i in range(len(segments) - 1):
        text_i = segments[i]['text']
        if len(text_i) < 2:
            continue

        for j in range(i + 1, min(i + 5, len(segments))):
            text_j = segments[j]['text']
            if len(text_j) < 2:
                continue

            gap = segments[j]['start'] - segments[i]['end']
            if gap < 0.2:
                continue  # No real gap, just continuous speech

            # Check various prefix lengths (2-4 chars)
            prefix_len = min(2, len(text_i), len(text_j))
            if text_i[:prefix_len] == text_j[:prefix_len]:
                # Check segments between i and j — if they contain substantial
                # non-matching content, this is natural repetition, not a retake
                between_text = ''.join(segments[k]['text'] for k in range(i+1, j))
                # Allow only short/fragmentary content between (< 5 chars)
                if len(between_text) > 4:
                    continue  # Meaningful content between = not a retake

                retakes.append({
                    'type': 'repetition',
                    'cut_start': segments[i]['end'],
                    'cut_end': segments[j]['start'],
                    'seg_i': i,
                    'seg_j': j,
                    'context': f'"{text_i}" → "{text_j}"'
                })

    # Method 2: Cluster of short segments with gaps (stuttering pattern)
    # e.g., "千万不要" [gap] "千万" [gap] "千万一定" = stuttering
    for i in range(len(segments) - 2):
        # Check for 3+ consecutive segments with gaps between them
        # where the segments share common prefixes
        cluster = [i]
        for j in range(i + 1, min(i + 5, len(segments))):
            gap = segments[j]['start'] - segments[cluster[-1]]['end']
            if 0.3 < gap < 2.0:
                # Check if any text overlap with cluster members
                text_j = segments[j]['text']
                has_overlap = any(
                    text_j[:min(2, len(text_j))] == segments[k]['text'][:min(2, len(segments[k]['text']))]
                    for k in cluster
                    if len(segments[k]['text']) >= 2 and len(text_j) >= 2
                )
                if has_overlap:
                    cluster.append(j)

        if len(cluster) >= 3:
            # Found a stutter cluster — keep only the last segment
            cut_start = segments[cluster[0]]['end']
            cut_end = segments[cluster[-1]]['start']
            if cut_end > cut_start:
                already_covered = any(
                    r['cut_start'] <= cut_start and r['cut_end'] >= cut_end
                    for r in retakes
                )
                if not already_covered:
                    texts = [segments[k]['text'] for k in cluster]
                    retakes.append({
                        'type': 'stutter_cluster',
                        'cut_start': cut_start,
                        'cut_end': cut_end,
                        'context': f'Stutter: {" → ".join(texts)}'
                    })

    # Method 3: Large gaps (>2s) that might indicate retakes
    for i in range(len(segments) - 1):
        gap = segments[i + 1]['start'] - segments[i]['end']
        if gap > 2.0:
            retakes.append({
                'type': 'long_gap',
                'cut_start': segments[i]['end'] + 0.1,
                'cut_end': segments[i + 1]['start'] - 0.1,
                'context': f'{gap:.1f}s gap after "{segments[i]["text"]}"'
            })

    # Deduplicate and merge overlapping retakes
    if retakes:
        retakes.sort(key=lambda r: r['cut_start'])
        merged = [retakes[0]]
        for r in retakes[1:]:
            if r['cut_start'] <= merged[-1]['cut_end'] + 0.5:
                # Merge overlapping
                merged[-1]['cut_end'] = max(merged[-1]['cut_end'], r['cut_end'])
                merged[-1]['context'] += f" + {r['context']}"
            else:
                merged.append(r)
        retakes = merged

    if retakes:
        print(f"  ⚠️  Found {len(retakes)} potential retake(s):")
        for r in retakes:
            print(f"    [{r['type']}] {r['cut_start']:.2f}-{r['cut_end']:.2f}s: {r['context']}")
    else:
        print(f"  ✅ No retakes detected, audio is clean.")

    return retakes


# ─── Step 5: Cut Retakes ────────────────────────────────────────────────────

def step5_cut_retakes(video_path, audio_path, name, retakes):
    """Cut retake segments from video and audio."""
    print("\n" + "=" * 60)
    print("Step 5: Cut Retakes")
    print("=" * 60)

    if not retakes:
        print("  No retakes to cut, using original files.")
        return video_path, audio_path

    info = get_media_info(video_path)
    total_dur = info['duration']

    # Build keep segments (inverse of cut segments)
    cuts = sorted(retakes, key=lambda r: r['cut_start'])
    keep_segments = []
    pos = 0
    for cut in cuts:
        if cut['cut_start'] > pos:
            keep_segments.append((pos, cut['cut_start']))
        pos = cut['cut_end']
    if pos < total_dur:
        keep_segments.append((pos, total_dur))

    print(f"  Keeping {len(keep_segments)} segment(s):")
    for start, end in keep_segments:
        print(f"    [{start:.2f} -> {end:.2f}] ({end-start:.2f}s)")

    cut_total = sum(c['cut_end'] - c['cut_start'] for c in cuts)
    print(f"  Cutting {cut_total:.1f}s of retakes")

    # Build ffmpeg filter complex
    n = len(keep_segments)
    filter_parts = []
    for i, (start, end) in enumerate(keep_segments):
        filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")

    concat_inputs = ''.join(f'[v{i}][a{i}]' for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]")
    filter_complex = ' '.join(filter_parts)

    # Output paths
    clean_video = str(PROJECT_ROOT / 'public' / f'{name}.mp4')
    tmp_video = '/tmp/pipeline-cut.mp4'

    run_ffmpeg(
        '-i', video_path,
        '-filter_complex', filter_complex,
        '-map', '[outv]', '-map', '[outa]',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k',
        tmp_video, '-y'
    )

    # Check if rotation metadata leaked through
    tmp_info = get_media_info(tmp_video)
    if abs(tmp_info.get('rotation', 0)) > 0.1:
        # MPEG-TS roundtrip
        tmp_ts = '/tmp/pipeline-cut.ts'
        run_ffmpeg('-i', tmp_video, '-c', 'copy', '-f', 'mpegts', tmp_ts, '-y')
        run_ffmpeg('-i', tmp_ts, '-c', 'copy', '-movflags', '+faststart', clean_video, '-y')
        try: os.remove(tmp_ts)
        except: pass
    else:
        shutil.move(tmp_video, clean_video)

    # Extract clean audio
    audio_dir = PROJECT_ROOT / 'public' / 'audio'
    clean_audio = str(audio_dir / f'{name}.mp3')
    run_ffmpeg(
        '-i', clean_video,
        '-vn', '-acodec', 'libmp3lame', '-q:a', '2',
        clean_audio, '-y'
    )

    new_info = get_media_info(clean_video)
    print(f"  ✅ Clean video: {new_info['duration']:.1f}s (was {total_dur:.1f}s)")

    try: os.remove(tmp_video)
    except: pass

    return clean_video, clean_audio


# ─── Step 6: Face Detection ─────────────────────────────────────────────────

def step6_detect_face(video_path):
    """Detect face position for circular overlay cropping."""
    print("\n" + "=" * 60)
    print("Step 6: Face Detection")
    print("=" * 60)

    import cv2
    import numpy as np

    cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    cascade = cv2.CascadeClassifier(cascade_path)

    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Sample 15 frames
    sample_indices = np.linspace(
        int(fps * 1), total_frames - int(fps * 1), 15, dtype=int
    )

    detections = []
    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(50, 50))
        if len(faces) > 0:
            areas = [w * h for (x, y, w, h) in faces]
            idx_max = np.argmax(areas)
            x, y, w, h = faces[idx_max]
            detections.append({'cx': x + w/2, 'cy': y + h/2, 'w': w, 'h': h})

    cap.release()

    if not detections:
        print("  ⚠️  No face detected! Using default center position.")
        return "center center"

    med_cx = np.median([d['cx'] for d in detections])
    med_cy = np.median([d['cy'] for d in detections])

    x_pct = round((med_cx / width) * 100, 1)
    y_pct = round((med_cy / height) * 100, 1)

    x_str = "center" if abs(x_pct - 50) < 10 else f"{x_pct}%"
    y_str = f"{y_pct}%"
    crop_position = f"{x_str} {y_str}"

    print(f"  Video: {width}x{height}")
    print(f"  Face detected in {len(detections)}/15 frames")
    print(f"  ✅ Crop position: '{crop_position}'")
    return crop_position


# ─── Whisper Correction ─────────────────────────────────────────────────────

def _correct_segments_with_original(segments, original_text):
    """Replace Whisper transcription text with original text, keeping timestamps.

    Strategy: strip punctuation from original text, then consume characters
    one-to-one matching each Whisper segment's character count. Since the
    digital human reads the exact original text, character counts should
    match closely. Any remainder goes to the last segment.
    """
    import re

    def strip_punct(t):
        return re.sub(r'[\s，。！？；：、""''（）()【】《》,.!?;:\'"\\—\-\n\r]', '', t)

    original_chars = strip_punct(original_text)

    if not original_chars:
        return segments

    corrected = []
    cursor = 0

    for i, seg in enumerate(segments):
        seg_len = len(strip_punct(seg['text']))

        if seg_len == 0:
            corrected.append(seg)
            continue

        # Last segment: take all remaining characters
        if i == len(segments) - 1:
            corrected_text = original_chars[cursor:]
        else:
            corrected_text = original_chars[cursor:cursor + seg_len]

        corrected.append({
            **seg,
            'text': corrected_text,
        })
        cursor += seg_len

    print(f"  ✅ Corrected {len(corrected)} segments with original text")
    return corrected


# ─── Segment Reshaping (fix line-break quality) ─────────────────────────────

# Particles / fillers that should never stand alone as a line
_TRAILING_PARTICLES = set('呢啊吧嘛呀哦哈嗯嘞啦噢喔了的吗么呐哩咯着过嘿诶唉哟')

def _reshape_segments(segments, max_chars=16, min_chars=4):
    """Merge tiny trailing-particle segments into their predecessor and
    re-split overly long segments at natural punctuation boundaries.

    This fixes the common Whisper problem where filler words like '呢', '的',
    '了' end up as standalone segments and appear as separate subtitle lines.
    """
    if not segments:
        return segments

    # ── Pass 1: merge tiny / particle-only segments into neighbours ──
    merged = [segments[0].copy()]
    for seg in segments[1:]:
        text = seg['text'].strip()
        prev = merged[-1]

        # Merge if: text is only particles, or text is very short (<=2 chars)
        # and previous segment isn't already too long
        is_particle_only = all(ch in _TRAILING_PARTICLES for ch in text) and len(text) <= 3
        is_tiny = len(text) <= 2

        if (is_particle_only or is_tiny) and len(prev['text']) < max_chars:
            # Absorb into previous segment
            prev['text'] = prev['text'] + text
            prev['end'] = seg['end']
        else:
            merged.append(seg.copy())

    # ── Pass 2: merge any segment still below min_chars into neighbour ──
    final = [merged[0]]
    for seg in merged[1:]:
        if len(seg['text']) < min_chars and len(final[-1]['text']) < max_chars:
            final[-1]['text'] = final[-1]['text'] + seg['text']
            final[-1]['end'] = seg['end']
        else:
            final.append(seg)

    print(f"  ✅ Reshaped segments: {len(segments)} → {len(final)} (merged tiny/particle segments)")
    return final


# ─── Step 7: Generate Script JSON ───────────────────────────────────────────

# Style color palette
STYLE_COLORS = [
    ('#f59e0b', 'gradient'),   # amber
    ('#ef4444', 'emphasis'),   # red
    ('#06b6d4', 'gradient'),   # cyan
    ('#10b981', 'gradient'),   # green
    ('#8b5cf6', 'gradient'),   # purple
    ('#ec4899', 'gradient'),   # pink
    ('#3b82f6', 'gradient'),   # blue
    ('#eab308', 'emphasis'),   # yellow
]

EMOJI_MAP = {
    '难': '😩', '苦': '😩', '愁': '😟', '可怜': '😩',
    '钱': '💸', '花': '💸', '贵': '💸',
    '手机': '📱', '电话': '📞',
    'AI': '🤖', '人工智能': '🤖',
    '火': '🔥', '爆': '💥', '成交': '🔥',
    '不用': '👌', '简单': '👌', '小白': '👌',
    '快': '⚡', '效率': '⚡', '高': '⚡',
    '直播': '👆', '头像': '👆', '进来': '👆',
    '点': '👆', '限量': '⚠️', '千万': '⚠️',
    '时间': '⏰', '时机': '⏰',
    '教': '📚', '学': '📚',
    '精准': '🎯', '流程': '🎯',
}


def pick_emoji(text):
    """Pick a relevant emoji based on text content."""
    for keyword, emoji in EMOJI_MAP.items():
        if keyword in text:
            return emoji
    return None


def step7_generate_script(segments, name, video_name, audio_name, crop_position):
    """Generate script JSON from transcription segments."""
    print("\n" + "=" * 60)
    print("Step 7: Generate Script JSON")
    print("=" * 60)

    # Group short consecutive segments into slides
    slides = []
    current_texts = []
    current_start = None
    current_narration_parts = []

    for i, seg in enumerate(segments):
        if current_start is None:
            current_start = seg['start']

        current_texts.append(seg['text'])
        current_narration_parts.append(seg['text'])

        # Decide whether to create a new slide:
        # - If accumulated text is long enough (>15 chars)
        # - If there's a gap after this segment (>0.3s)
        # - If this is the last segment
        next_gap = (segments[i+1]['start'] - seg['end']) if i+1 < len(segments) else 999
        total_text = ''.join(current_texts)
        accumulated_dur = seg['end'] - current_start

        should_break = (
            i == len(segments) - 1 or  # Last segment
            (len(total_text) >= 12 and next_gap >= 0.2) or  # Natural break
            accumulated_dur >= 4.5 or  # Max slide duration
            next_gap >= 0.5  # Significant pause
        )

        if should_break:
            # Calculate duration: from start to next segment start (or end of this segment + gap)
            if i + 1 < len(segments):
                duration = segments[i+1]['start'] - current_start
            else:
                duration = seg['end'] - current_start + 0.4  # Add a bit of padding at end

            narration = ''.join(current_narration_parts)

            # Build text lines with styles
            style_idx = len(slides) % len(STYLE_COLORS)
            color, style = STYLE_COLORS[style_idx]

            lines = []
            if len(current_texts) == 1:
                text = current_texts[0]
                # gradient only for short text (<=10 chars), otherwise use emphasis
                if len(text) <= 10 and style == 'gradient':
                    lines.append({'text': text, 'style': 'gradient', 'color': color})
                else:
                    lines.append({'text': text, 'style': 'emphasis', 'color': color})
            else:
                # First segment as title
                lines.append({'text': current_texts[0], 'style': 'title'})
                # Remaining segments: each as its own line
                for j, txt in enumerate(current_texts[1:]):
                    if len(txt) <= 10 and j == len(current_texts) - 2 and style == 'gradient':
                        # Last short segment gets gradient (the punchline)
                        lines.append({'text': txt, 'style': 'gradient', 'color': color})
                    elif j == len(current_texts) - 2:
                        # Last segment gets emphasis
                        lines.append({'text': txt, 'style': 'emphasis', 'color': color})
                    else:
                        # Middle segments as body
                        lines.append({'text': txt, 'style': 'body'})

            slide = {
                'lines': lines,
                'narration': narration,
                'duration': round(duration, 2),
            }

            # Add emoji for ~40% of slides
            emoji = pick_emoji(narration)
            if emoji and len(slides) % 3 != 1:  # Not every slide
                slide['emoji'] = emoji

            slides.append(slide)
            current_texts = []
            current_start = None
            current_narration_parts = []

    # Build script
    script = {
        'title': slides[0]['lines'][0]['text'] if slides else name,
        'digitalHuman': video_name,
        'digitalHumanCrop': crop_position,
        'audioTrack': audio_name,
        'slides': slides,
    }

    # Save
    script_path = PROJECT_ROOT / 'src' / 'data' / f'{name}-script.json'
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    total_dur = sum(s['duration'] for s in slides)
    print(f"  Generated {len(slides)} slides, total {total_dur:.1f}s")
    print(f"  ✅ Saved to: {script_path.name}")

    return str(script_path), script


# ─── Step 8: Quality Check ──────────────────────────────────────────────────

def step8_quality_check(script_path, script):
    """Run quality checks on the generated script."""
    print("\n" + "=" * 60)
    print("Step 8: Quality Check")
    print("=" * 60)

    errors = []
    warnings = []

    # Check slide durations
    total_dur = sum(s.get('duration', 0) for s in script['slides'])
    for i, s in enumerate(script['slides']):
        d = s.get('duration', 0)
        if d < 0.5:
            warnings.append(f"Slide {i+1}: very short ({d}s)")
        if d > 8:
            warnings.append(f"Slide {i+1}: very long ({d}s)")

    # Check audio duration
    audio_path = script.get('audioTrack')
    if audio_path:
        audio_full = str(PROJECT_ROOT / 'public' / audio_path)
        if os.path.exists(audio_full):
            info = get_media_info(audio_full)
            if info['duration']:
                diff = abs(total_dur - info['duration'])
                print(f"  Slides total: {total_dur:.2f}s")
                print(f"  Audio total:  {info['duration']:.2f}s")
                print(f"  Difference:   {diff:.2f}s")
                if diff > 3.0:
                    errors.append(f"Duration mismatch: slides {total_dur:.1f}s vs audio {info['duration']:.1f}s (diff {diff:.1f}s > 3s)")
                elif diff > 1.5:
                    warnings.append(f"Duration slightly off: {diff:.1f}s")
        else:
            errors.append(f"Audio file not found: {audio_full}")

    # Check video
    dh = script.get('digitalHuman')
    if dh:
        dh_full = str(PROJECT_ROOT / 'public' / dh)
        if os.path.exists(dh_full):
            info = get_media_info(dh_full)
            if abs(info.get('rotation', 0)) > 0.1:
                errors.append(f"Video has rotation metadata: {info['rotation']}°")
        else:
            errors.append(f"Video not found: {dh_full}")

    if not script.get('digitalHumanCrop'):
        errors.append("No face crop position set")

    # Report
    if warnings:
        for w in warnings:
            print(f"  ⚠️  {w}")
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        return False
    else:
        print(f"  ✅ All checks passed!")
        return True


# ─── Main Pipeline ──────────────────────────────────────────────────────────

def main():
    # Parse args
    args = sys.argv[1:]
    video_path = None
    name = None
    shiliu_mode = False
    original_text = None

    i = 0
    while i < len(args):
        if args[i] == '--name' and i + 1 < len(args):
            name = args[i + 1]
            i += 2
        elif args[i] == '--text' and i + 1 < len(args):
            original_text = args[i + 1]
            i += 2
        elif args[i] == '--text-file' and i + 1 < len(args):
            original_text = open(args[i + 1], 'r', encoding='utf-8').read().strip()
            i += 2
        elif args[i] in ('--shiliu', '--skip-retake'):
            shiliu_mode = True
            i += 1
        elif not args[i].startswith('--'):
            video_path = args[i]
            i += 1
        else:
            i += 1

    if not video_path:
        print("Usage: python3 scripts/full-pipeline.py <video_path_or_url> [--name <name>] [--shiliu]")
        print("\nExamples:")
        print("  # From local file (real person, with retake detection):")
        print("  python3 scripts/full-pipeline.py ~/video.mp4 --name my-project")
        print()
        print("  # From URL (download first):")
        print("  python3 scripts/full-pipeline.py https://example.com/video.mp4 --name my-project")
        print()
        print("  # ShiLiu AI-generated (skip retake detection):")
        print("  python3 scripts/full-pipeline.py <path_or_url> --name my-project --shiliu")
        sys.exit(1)

    # Handle URL input — download to local temp file first
    url_source = None
    if is_url(video_path):
        url_source = video_path
        print("=" * 60)
        print("Step 0: Download Video from URL")
        print("=" * 60)
        # Determine file extension from URL
        url_basename = video_path.split('?')[0].split('#')[0].rsplit('/', 1)[-1]
        ext = '.mp4'
        if '.' in url_basename:
            ext = '.' + url_basename.rsplit('.', 1)[-1]
            if len(ext) > 5:
                ext = '.mp4'
        download_dest = f'/tmp/pipeline-download{ext}'
        download_video(video_path, download_dest)
        video_path = download_dest
        print()

    if not os.path.exists(video_path):
        print(f"Error: Video not found: {video_path}")
        sys.exit(1)

    # Auto-generate name from filename if not provided
    if not name:
        name = Path(video_path).stem
        # Sanitize
        name = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff-]', '-', name)
        name = re.sub(r'-+', '-', name).strip('-')
        if len(name) > 30:
            name = name[:30]

    global FFMPEG
    FFMPEG = find_ffmpeg()

    mode_label = "ShiLiu AI Mode (no retake detection)" if shiliu_mode else "Full Mode (with retake detection)"
    source_label = f"URL: {url_source}" if url_source else f"File: {video_path}"

    print("╔" + "═" * 58 + "╗")
    print("║  Card Video Pipeline                                    ║")
    print("╚" + "═" * 58 + "╝")
    print(f"  Source: {source_label}")
    print(f"  Name:   {name}")
    print(f"  Mode:   {mode_label}")
    print()

    # Ensure dependencies
    ensure_dependencies()

    # Step 1: Prepare video (copy + fix rotation)
    # ShiLiu-generated videos typically have no rotation issues,
    # but we still check just in case
    clean_video = step1_prepare_video(video_path, name)

    # Step 2: Extract audio
    audio_path = step2_extract_audio(clean_video, name)

    # Step 3: Transcribe
    segments = step3_transcribe(audio_path)

    if shiliu_mode:
        # ShiLiu AI-generated videos — skip retake detection
        print("\n" + "=" * 60)
        print("Step 4-5: SKIPPED (ShiLiu mode — no retakes in AI-generated video)")
        print("=" * 60)
    else:
        # Step 4: Detect retakes
        retakes = step4_detect_retakes(segments)

        # Step 5: Cut retakes if any
        if retakes:
            clean_video, audio_path = step5_cut_retakes(clean_video, audio_path, name, retakes)
            # Re-transcribe clean audio for accurate timestamps
            print("\n  Re-transcribing clean audio for accurate timestamps...")
            segments = step3_transcribe(audio_path)

    # Step 6: Face detection
    crop_position = step6_detect_face(clean_video)

    # Step 7: Generate script
    video_name = f'{name}.mp4'
    audio_name = f'audio/{name}.mp3'

    # If original text provided, use it to correct Whisper transcription
    if original_text and shiliu_mode:
        segments = _correct_segments_with_original(segments, original_text)

    # Reshape segments: merge tiny particle-only segments into neighbours
    # This prevents '呢', '了', '的' etc. from appearing as standalone subtitle lines
    segments = _reshape_segments(segments)

    script_path, script = step7_generate_script(
        segments, name, video_name, audio_name, crop_position
    )

    # Step 8: Quality check
    passed = step8_quality_check(script_path, script)

    # Summary
    print("\n" + "=" * 60)
    print("Pipeline Complete!")
    print("=" * 60)
    print(f"  Video:  public/{name}.mp4")
    print(f"  Audio:  public/audio/{name}.mp3")
    print(f"  Script: src/data/{name}-script.json")
    print(f"  Face:   {crop_position}")
    print(f"  Slides: {len(script['slides'])}")
    print(f"  Mode:   {'ShiLiu AI' if shiliu_mode else 'Full (retake detection)'}")
    print(f"  Status: {'✅ PASSED' if passed else '⚠️  NEEDS REVIEW'}")
    if url_source:
        print(f"  Source URL: {url_source}")
    print()
    print("⚠️  IMPORTANT: Please review the script JSON!")
    if shiliu_mode:
        print("  ShiLiu TTS is generally accurate, but check for:")
    else:
        print("  Whisper ASR may have errors with:")
    print("  - Numbers (四五百 → 4500)")
    print("  - Proper nouns and names")
    print("  - Similar-sounding words")
    print()
    print("After reviewing, render with:")
    print(f"  node scripts/render-card.mjs src/data/{name}-script.json")

    # Cleanup downloaded file
    if url_source and os.path.exists('/tmp/pipeline-download.mp4'):
        try: os.remove('/tmp/pipeline-download.mp4')
        except: pass


if __name__ == '__main__':
    main()
