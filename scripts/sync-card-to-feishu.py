#!/usr/bin/env python3
"""
Sync card video result back to Feishu bitable.

After rendering a card video, this script updates the existing ShiLiu digital human
record in Feishu bitable with the card video status and local path.

Usage:
  # Update existing record (from ShiLiu generate_video.py output):
  python3 scripts/sync-card-to-feishu.py --record-id recvd55SVwCICF --card-video out/demo.mp4

  # Create new record (standalone card video):
  python3 scripts/sync-card-to-feishu.py --new --name demo --card-video out/demo.mp4

  # With script JSON for full metadata:
  python3 scripts/sync-card-to-feishu.py --record-id recvXXX --card-video out/demo.mp4 --script src/data/demo-script.json

Dependencies:
  - feishu-bridge/feishu_bitable_ops.py (in user home)
  - feishu-bridge/.env.feishu (in user home)
"""

import argparse
import json
import os
import sys
import importlib.util
from datetime import datetime
from pathlib import Path

# ─── Feishu integration ─────────────────────────────────────────────────────

FEISHU_BRIDGE_PATH = Path(os.environ.get('FEISHU_BRIDGE_PATH', Path.home() / 'feishu-bridge'))
FEISHU_ENV_PATH = FEISHU_BRIDGE_PATH / '.env.feishu'
FEISHU_OPS_PATH = FEISHU_BRIDGE_PATH / 'feishu_bitable_ops.py'
SHILIU_CONFIG_PATH = Path(os.environ.get('SHILIU_CONFIG_PATH', Path.home() / '.openclaw/workspace/skills/shiliu-digital-human/data/runtime/config.json'))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_feishu_ops():
    """Load feishu_bitable_ops module."""
    if not FEISHU_OPS_PATH.exists():
        print(f"❌ Feishu ops not found: {FEISHU_OPS_PATH}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location('feishu_bitable_ops', FEISHU_OPS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_shiliu_config():
    """Load ShiLiu config for table ID."""
    if SHILIU_CONFIG_PATH.exists():
        return json.loads(SHILIU_CONFIG_PATH.read_text(encoding='utf-8'))
    return {}


def get_feishu_credentials(feishu_ops):
    """Get Feishu credentials."""
    feishu_ops.load_env_file(str(FEISHU_ENV_PATH))
    app_id = os.getenv('FEISHU_APP_ID', '').strip()
    app_secret = os.getenv('FEISHU_APP_SECRET', '').strip()
    app_token = os.getenv('FEISHU_APP_TOKEN', '').strip()

    if not all([app_id, app_secret, app_token]):
        print("❌ Missing Feishu credentials")
        print(f"   Check: {FEISHU_ENV_PATH}")
        sys.exit(1)

    return app_id, app_secret, app_token


def main():
    parser = argparse.ArgumentParser(
        description='Sync card video result to Feishu bitable',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--record-id', help='Existing Feishu record ID to update (from ShiLiu sync)')
    mode_group.add_argument('--new', action='store_true', help='Create new record instead of updating')

    parser.add_argument('--card-video', required=True, help='Path to rendered card video MP4')
    parser.add_argument('--script', help='Path to script JSON (for metadata)')
    parser.add_argument('--name', help='Project name (for new records)')
    parser.add_argument('--table-id', help='Override Feishu table ID')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be synced without actually syncing')

    args = parser.parse_args()

    # Validate card video exists
    card_video_path = Path(args.card_video)
    if not card_video_path.exists():
        # Try relative to project root
        card_video_path = PROJECT_ROOT / args.card_video
    if not card_video_path.exists():
        print(f"❌ Card video not found: {args.card_video}")
        sys.exit(1)

    card_video_abs = str(card_video_path.resolve())
    card_video_size_mb = card_video_path.stat().st_size / 1024 / 1024

    # Load script JSON for metadata
    script_data = {}
    if args.script:
        script_path = Path(args.script)
        if not script_path.exists():
            script_path = PROJECT_ROOT / args.script
        if script_path.exists():
            script_data = json.loads(script_path.read_text(encoding='utf-8'))

    # Build fields to sync
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    slides_count = len(script_data.get('slides', []))
    total_duration = sum(s.get('duration', 0) for s in script_data.get('slides', []))

    fields = {
        '卡片视频状态': '✅ 完成',
        '卡片视频路径': card_video_abs,
        '卡片视频大小': f'{card_video_size_mb:.1f}MB',
        '卡片视频时间': now_str,
    }

    if slides_count:
        fields['卡片视频slides'] = str(slides_count)
    if total_duration:
        fields['卡片视频时长'] = f'{total_duration:.1f}s'

    # For new records, add more metadata
    if args.new:
        if args.name:
            fields['多行文本'] = f'卡片视频: {args.name}'
            fields['标题'] = args.name
        if script_data.get('title'):
            fields['标题'] = script_data['title']

        # Add slide text as narration summary
        narrations = [s.get('narration', '') for s in script_data.get('slides', [])[:3]]
        if narrations:
            fields['文案全文'] = ' '.join(narrations)[:500]

    print("═" * 50)
    print("Sync Card Video → Feishu Bitable")
    print("═" * 50)
    print(f"  Card video: {card_video_abs}")
    print(f"  Size: {card_video_size_mb:.1f}MB")
    if slides_count:
        print(f"  Slides: {slides_count}, Duration: {total_duration:.1f}s")
    print(f"  Mode: {'New record' if args.new else f'Update record {args.record_id}'}")
    print()
    print("  Fields to sync:")
    for k, v in fields.items():
        v_display = v if len(v) <= 60 else v[:60] + '...'
        print(f"    {k}: {v_display}")
    print()

    if args.dry_run:
        print("  [DRY RUN] Would sync above fields to Feishu. Exiting.")
        return

    # Load Feishu integration
    feishu_ops = load_feishu_ops()
    app_id, app_secret, app_token = get_feishu_credentials(feishu_ops)

    # Get table ID
    config = load_shiliu_config()
    table_id = args.table_id or config.get('feishu_digital_human_table_id', '')
    if not table_id:
        table_id = os.getenv('FEISHU_DIGITAL_HUMAN_TABLE_ID', '').strip()
    if not table_id:
        print("❌ No table ID found. Use --table-id or set in ShiLiu config.")
        sys.exit(1)

    # Get auth token
    token = feishu_ops.get_tenant_access_token(app_id, app_secret)

    if args.new:
        # Create new record
        resp = feishu_ops.create_record(token, app_token, table_id, fields)
        if resp.get('code') != 0:
            print(f"❌ Failed to create record: {resp}")
            sys.exit(1)
        record_id = resp.get('data', {}).get('record', {}).get('record_id', '')
        print(f"  ✅ Created new record: {record_id}")
    else:
        # Update existing record
        resp = feishu_ops.update_record(token, app_token, table_id, args.record_id, fields)
        if resp.get('code') != 0:
            # If field doesn't exist, the update may fail.
            # This is OK - the fields will be auto-created if the table supports it.
            # Or the user needs to add columns manually.
            error_msg = resp.get('msg', '')
            if 'FieldNameNotFound' in str(resp):
                print(f"  ⚠️  Some fields don't exist in the table yet.")
                print(f"  Please add these columns to the Feishu table:")
                for k in fields.keys():
                    print(f"    - {k} (文本类型)")
                print()
                print(f"  Or create them automatically:")
                # Try to create the fields
                for field_name in fields.keys():
                    try:
                        feishu_ops.create_field(token, app_token, table_id, field_name, 1)  # 1 = text
                        print(f"    ✅ Created field: {field_name}")
                    except Exception as e:
                        print(f"    ⚠️  Could not create field {field_name}: {e}")
                # Retry update
                resp2 = feishu_ops.update_record(token, app_token, table_id, args.record_id, fields)
                if resp2.get('code') == 0:
                    print(f"\n  ✅ Updated record: {args.record_id}")
                else:
                    print(f"\n  ❌ Still failed: {resp2}")
                    sys.exit(1)
            else:
                print(f"❌ Failed to update record: {resp}")
                sys.exit(1)
        else:
            print(f"  ✅ Updated record: {args.record_id}")

    # Build table URL
    base_url = os.getenv('FEISHU_BASE_WEB_URL', 'https://feishu.cn/base').strip() or 'https://feishu.cn/base'
    table_url = f"{base_url.rstrip('/')}/{app_token}?table={table_id}"
    print(f"  📋 Table: {table_url}")


if __name__ == '__main__':
    main()
