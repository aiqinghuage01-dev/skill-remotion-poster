#!/usr/bin/env python3
"""
Generate one MiniMax cloned-voice TTS MP3 per slide and write manifest.json.

Usage:
  python3 scripts/generate_tts_minimax.py src/data/<name>-script.json public/audio/
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_env() -> tuple[str, str, str, str]:
    load_dotenv(ENV_PATH)
    api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    group_id = os.getenv("MINIMAX_GROUP_ID", "").strip()
    voice_id = os.getenv("MINIMAX_VOICE_ID", "").strip()
    base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat").strip().rstrip("/")
    missing = [name for name, value in {
        "MINIMAX_API_KEY": api_key,
        "MINIMAX_GROUP_ID": group_id,
        "MINIMAX_VOICE_ID": voice_id,
    }.items() if not value]
    if missing:
        raise RuntimeError(f"缺少环境变量: {', '.join(missing)}")
    return api_key, group_id, voice_id, base_url


def probe_duration(audio_path: Path, fallback: float) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        value = (result.stdout or "").strip()
        if value:
            duration = float(value) + 0.5
            return max(duration, fallback)
    except Exception:
        pass
    return fallback


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/generate_tts_minimax.py <script.json> <audio_dir>", file=sys.stderr)
        return 2

    script_path = Path(sys.argv[1]).expanduser().resolve()
    audio_dir = Path(sys.argv[2]).expanduser().resolve()

    if not script_path.exists():
        print(f"ERROR: script.json not found: {script_path}", file=sys.stderr)
        return 2

    audio_dir.mkdir(parents=True, exist_ok=True)

    api_key, group_id, voice_id, base_url = load_env()
    script = json.loads(script_path.read_text(encoding="utf-8"))

    audio_files: list[str] = []
    slide_durations: list[float] = []

    for i, slide in enumerate(script.get("slides", [])):
        narration = str(slide.get("narration", "")).strip()
        fallback_duration = float(slide.get("duration", 3) or 3)

        if not narration:
            audio_files.append("")
            slide_durations.append(fallback_duration)
            continue

        out_file = f"audio/slide-{i:03d}.mp3"
        out_path = audio_dir / f"slide-{i:03d}.mp3"

        print(f"Slide {i}: 生成 MiniMax TTS「{narration[:30]}...」")

        resp = requests.post(
            f"{base_url}/v1/t2a_v2?GroupId={group_id}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "speech-02-turbo",
                "text": narration,
                "stream": False,
                "voice_setting": {
                    "voice_id": voice_id,
                    "speed": 1.0,
                    "pitch": 0,
                    "vol": 1.0,
                },
                "audio_setting": {
                    "sample_rate": 32000,
                    "bitrate": 128000,
                    "format": "mp3",
                },
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()

        base_resp = result.get("base_resp", {})
        if base_resp.get("status_code") != 0:
            print(f"  ERROR: {base_resp.get('status_msg', 'unknown error')}")
            audio_files.append("")
            slide_durations.append(fallback_duration)
            continue

        audio_hex = result.get("data", {}).get("audio", "")
        if not audio_hex:
            print("  ERROR: 返回中没有 audio 数据")
            audio_files.append("")
            slide_durations.append(fallback_duration)
            continue

        out_path.write_bytes(bytes.fromhex(audio_hex))
        duration = round(probe_duration(out_path, fallback_duration), 1)
        audio_files.append(out_file)
        slide_durations.append(duration)
        print(f"  -> {out_file} ({duration:.1f}s)")

    manifest = {
        "audioFiles": audio_files,
        "slideDurations": slide_durations,
    }
    manifest_path = audio_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nManifest: {manifest_path}")
    print(f"Total: {sum(slide_durations):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
