#!/usr/bin/env python3
"""
Text-to-Card: Full AI Pipeline
Text copy → ShiLiu Digital Human Video → Card-Style Video

This script chains:
1. ShiLiu API: Generate digital human video from text
2. Download the generated video
3. Full pipeline: Whisper + face detection + script generation + quality check

Usage:
  python3 scripts/text-to-card.py --text "你的文案内容" --name my-project
  python3 scripts/text-to-card.py --file copy.txt --name my-project
  python3 scripts/text-to-card.py --text "文案" --name proj --render  (auto-render after user review)

Requirements:
  - ShiLiu API key: set SHILIU_API_KEY env var, or use --api-key
  - ShiLiu MCP venv (auto-discovered from home directory)
  - ffmpeg, python3, opencv, whisper (auto-installed by full-pipeline.py)

After running, review the script JSON then render with:
  node scripts/render-card.mjs src/data/<name>-script.json
"""

import sys
import os
import json
import time
import subprocess
import asyncio
import importlib.util
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHILIU_MCP_PATH = Path(os.environ.get('SHILIU_MCP_PATH', Path.home() / '.openclaw/workspace/shared/shiliu-mcp'))
SHILIU_SKILL_PATH = Path(os.environ.get('SHILIU_SKILL_PATH', Path.home() / '.openclaw/workspace/skills/shiliu-digital-human'))
SHILIU_CONFIG_PATH = SHILIU_SKILL_PATH / 'data' / 'runtime' / 'config.json'

DEFAULT_POLL_INTERVAL = 10  # seconds
DEFAULT_POLL_TIMEOUT = 900  # 15 minutes


def load_shiliu_config():
    """Load ShiLiu runtime config."""
    if SHILIU_CONFIG_PATH.exists():
        return json.loads(SHILIU_CONFIG_PATH.read_text(encoding='utf-8'))
    return {}


def load_dotenv():
    """Load .env from ShiLiu MCP directory."""
    env_path = SHILIU_MCP_PATH / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key, value = stripped.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_api_client():
    """Import ShiLiuApiClient from the MCP repo."""
    api_client_path = SHILIU_MCP_PATH / 'api_client.py'
    if not api_client_path.exists():
        print(f"  ❌ ShiLiu API client not found: {api_client_path}")
        print(f"  Please ensure shiliu-mcp is set up at: {SHILIU_MCP_PATH}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location('api_client', api_client_path)
    if spec is None or spec.loader is None:
        print(f"  ❌ Cannot load module: {api_client_path}")
        sys.exit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─── Step 1: Generate Digital Human Video ─────────────────────────────────

async def step1_generate_video(api_key, avatar_id, speaker_id, text, title, poll_interval, timeout):
    """Call ShiLiu API to generate digital human video."""
    print("=" * 60)
    print("Step A: Generate Digital Human Video (ShiLiu API)")
    print("=" * 60)
    print(f"  Avatar ID:  {avatar_id}")
    print(f"  Speaker ID: {speaker_id}")
    print(f"  Text:       {text[:80]}{'...' if len(text) > 80 else ''}")
    print(f"  Title:      {title}")
    print()

    api_module = load_api_client()
    client = api_module.ShiLiuApiClient(api_key)

    try:
        # Create video
        print("  Creating video...")
        created = await client.create_video_by_text(
            avatar_id=avatar_id,
            speaker_id=speaker_id,
            text=text,
            title=title,
        )
        payload = created.model_dump()

        if payload.get('code') != 0:
            print(f"  ❌ Video creation failed: {payload.get('msg', 'unknown error')}")
            return None

        video_id = payload.get('video_id')
        print(f"  ✅ Video created: ID={video_id}")
        print(f"  Polling for completion (timeout: {timeout}s)...")

        # Poll for status
        deadline = time.time() + timeout
        last_progress = -1
        while time.time() < deadline:
            status = (await client.get_video_generation_status(video_id)).model_dump()
            progress = status.get('progress', 0)
            status_str = status.get('status', 'unknown')
            video_url = status.get('video_url', '')

            if progress != last_progress:
                print(f"  [{time.strftime('%H:%M:%S')}] Progress: {progress}% - Status: {status_str}")
                last_progress = progress

            if video_url and video_url.strip():
                print(f"\n  ✅ Video ready!")
                print(f"  URL: {video_url}")
                return video_url

            if status_str.lower() in ('success', 'done', 'completed', 'finished'):
                if video_url:
                    print(f"\n  ✅ Video ready!")
                    print(f"  URL: {video_url}")
                    return video_url

            await asyncio.sleep(poll_interval)

        print(f"\n  ⚠️  Timeout after {timeout}s. Video may still be processing.")
        print(f"  Check status at: https://16ai.vip")
        print(f"  Video ID: {video_id}")
        return None

    finally:
        await client.close()


# ─── Step 2: Run Full Pipeline ─────────────────────────────────────────────

def step2_run_pipeline(video_url, name):
    """Run full-pipeline.py with the video URL in ShiLiu mode."""
    print("\n" + "=" * 60)
    print("Step B: Run Card Video Pipeline")
    print("=" * 60)

    pipeline_script = PROJECT_ROOT / 'scripts' / 'full-pipeline.py'
    cmd = [
        sys.executable, str(pipeline_script),
        video_url,
        '--name', name,
        '--shiliu',
    ]

    print(f"  Running: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode == 0


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Text → Digital Human → Card Video (Full AI Pipeline)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # From text directly:
  python3 scripts/text-to-card.py --text "你好，今天给大家分享..." --name demo

  # From text file:
  python3 scripts/text-to-card.py --file copy.txt --name demo

  # With custom avatar/speaker:
  python3 scripts/text-to-card.py --text "文案" --name demo --avatar-id 12345 --speaker-id 67890

  # Skip video generation (if you already have a ShiLiu video URL):
  python3 scripts/text-to-card.py --video-url "https://..." --name demo
        """
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--text', help='Direct text content for digital human')
    input_group.add_argument('--file', help='Text file path containing the copy')
    input_group.add_argument('--video-url', help='Skip generation, use existing ShiLiu video URL')

    parser.add_argument('--name', required=True, help='Project name for output files')
    parser.add_argument('--title', help='Video title (default: first 30 chars of text)')
    parser.add_argument('--avatar-id', type=int, help='Override default avatar ID')
    parser.add_argument('--speaker-id', type=int, help='Override default speaker ID')
    parser.add_argument('--api-key', help='ShiLiu API key (or set SHILIU_API_KEY env var)')
    parser.add_argument('--poll-interval', type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f'Seconds between status polls (default: {DEFAULT_POLL_INTERVAL})')
    parser.add_argument('--timeout', type=int, default=DEFAULT_POLL_TIMEOUT,
                        help=f'Max wait time in seconds (default: {DEFAULT_POLL_TIMEOUT})')

    args = parser.parse_args()

    # Banner
    print("╔" + "═" * 58 + "╗")
    print("║  Text → Digital Human → Card Video (Full AI Pipeline)   ║")
    print("╚" + "═" * 58 + "╝")
    print()

    # If video URL provided, skip generation
    if args.video_url:
        print("  Mode: Direct video URL (skip generation)")
        print(f"  URL:  {args.video_url}")
        print(f"  Name: {args.name}")
        print()

        success = step2_run_pipeline(args.video_url, args.name)
        if not success:
            print("\n❌ Pipeline failed!")
            sys.exit(1)
        return

    # Get text content
    if args.file:
        text_path = Path(args.file)
        if not text_path.exists():
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
        text = text_path.read_text(encoding='utf-8').strip()
        print(f"  Mode:   Text file → Digital Human → Card Video")
        print(f"  File:   {args.file}")
    else:
        text = args.text
        print(f"  Mode:   Direct text → Digital Human → Card Video")

    if not text:
        print("Error: Text content is empty")
        sys.exit(1)

    title = args.title or text[:30]
    print(f"  Name:   {args.name}")
    print(f"  Title:  {title}")
    print(f"  Text:   {text[:100]}{'...' if len(text) > 100 else ''}")
    print(f"  Length: {len(text)} chars")
    print()

    # Load config
    load_dotenv()
    config = load_shiliu_config()

    avatar_id = args.avatar_id or config.get('default_avatar_id')
    speaker_id = args.speaker_id or config.get('default_speaker_id')
    api_key = args.api_key or os.getenv('SHILIU_API_KEY')

    if not api_key:
        print("❌ ShiLiu API key not found.")
        print("   Set SHILIU_API_KEY env var, or use --api-key, or configure:")
        print(f"   {SHILIU_MCP_PATH / '.env'}")
        sys.exit(1)

    if not avatar_id:
        print("❌ No avatar ID configured.")
        print(f"   Set default in: {SHILIU_CONFIG_PATH}")
        print("   Or use: --avatar-id <id>")
        sys.exit(1)

    if not speaker_id:
        print("❌ No speaker ID configured.")
        print(f"   Set default in: {SHILIU_CONFIG_PATH}")
        print("   Or use: --speaker-id <id>")
        sys.exit(1)

    # Step A: Generate digital human video
    video_url = asyncio.run(
        step1_generate_video(
            api_key=api_key,
            avatar_id=avatar_id,
            speaker_id=speaker_id,
            text=text,
            title=title,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )
    )

    if not video_url:
        print("\n❌ Digital human video generation failed or timed out.")
        print("   You can check status at: https://16ai.vip")
        print("   Or retry with: python3 scripts/text-to-card.py --video-url <url> --name " + args.name)
        sys.exit(1)

    # Step B: Run full pipeline on the generated video
    success = step2_run_pipeline(video_url, args.name)

    if not success:
        print("\n❌ Card video pipeline failed!")
        sys.exit(1)

    # Final summary
    print("\n" + "═" * 60)
    print("🎉 Full AI Pipeline Complete!")
    print("═" * 60)
    print(f"  1. ✅ Digital human video generated (ShiLiu API)")
    print(f"  2. ✅ Video downloaded and processed")
    print(f"  3. ✅ Script JSON generated")
    print()
    print(f"  ⚠️  Review script: src/data/{args.name}-script.json")
    print(f"  Then render with:")
    print(f"    node scripts/render-card.mjs src/data/{args.name}-script.json")


if __name__ == '__main__':
    main()
