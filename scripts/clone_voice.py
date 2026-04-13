"""
一键声音克隆脚本
用法:
  python3 clone_voice.py /path/to/your_voice.mp3
  python3 clone_voice.py ./my_voice.mp3 --voice-name "black-chen" --test-text "这是一段音色测试"

流程：
  1) 上传录音文件到 MiniMax -> 拿到 file_id
  2) 用 file_id 创建声音克隆 -> 拿到 voice_id
  3) 自动写入 .env 的 MINIMAX_VOICE_ID
  4) 立即做一次 TTS 测试，确认克隆音色可用
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import random
import string
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv, set_key

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

load_dotenv(ENV_FILE)

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "").strip()
MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID", "").strip()
BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat").strip().rstrip("/")


def _require_env() -> None:
    missing = []
    if not MINIMAX_API_KEY:
        missing.append("MINIMAX_API_KEY")
    if not MINIMAX_GROUP_ID:
        missing.append("MINIMAX_GROUP_ID")
    if missing:
        raise RuntimeError(f"缺少环境变量: {', '.join(missing)}")


def _api_url(path: str) -> str:
    sep = "&" if "?" in path else "?"
    return f"{BASE_URL}{path}{sep}GroupId={MINIMAX_GROUP_ID}"


def _auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}"}
    if extra:
        headers.update(extra)
    return headers


def _check_api_result(result: dict[str, Any], action: str) -> None:
    base_resp = result.get("base_resp", {})
    code = base_resp.get("status_code", 0)
    if code != 0:
        msg = base_resp.get("status_msg", "未知错误")
        raise RuntimeError(f"{action}失败: {msg} (status_code={code})")


def _pick_file_id(result: dict[str, Any]) -> str:
    candidates = [
        result.get("file", {}).get("file_id"),
        result.get("data", {}).get("file_id"),
        result.get("data", {}).get("file", {}).get("file_id"),
        result.get("file_id"),
    ]
    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, int):
            return str(item)
    raise RuntimeError(f"上传成功但未解析到 file_id，响应: {result}")


def upload_audio(file_path: Path) -> str:
    """Step 1: 上传音频文件，返回 file_id"""
    print(f"[1/3] 正在上传音频: {file_path}")

    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    with file_path.open("rb") as f:
        files = {"file": (file_path.name, f, mime)}
        data = {"purpose": "voice_clone"}
        resp = requests.post(
            _api_url("/v1/files/upload"),
            headers=_auth_headers(),
            files=files,
            data=data,
            timeout=120,
        )

    resp.raise_for_status()
    result = resp.json()
    _check_api_result(result, "上传音频")
    file_id = _pick_file_id(result)
    print(f"[1/3] 上传成功，file_id: {file_id}")
    return file_id


def create_voice_clone(
    file_id: str,
    voice_name: str,
    voice_id: str | None = None,
    preview_text: str | None = None,
) -> str:
    """Step 2: 用 file_id 创建声音克隆，返回 voice_id"""
    print("[2/3] 正在克隆声音，请稍候...")

    custom_voice_id = (voice_id or "").strip()
    if not custom_voice_id:
        # voice_id 必须是 8-20 位字母数字，不能有特殊字符
        custom_voice_id = "myvoice" + "".join(random.choices(string.digits, k=6))

    parsed_file_id: int | str
    if isinstance(file_id, str) and file_id.isdigit():
        parsed_file_id = int(file_id)
    else:
        parsed_file_id = file_id

    payload = {
        "file_id": parsed_file_id,
        "voice_id": custom_voice_id,
        # 兼容新接口参数
        "model": "speech-02-turbo",
        "text": preview_text or "这是一段用于音色克隆的试听文本。",
        "need_noise_reduction": False,
        "need_volume_normalization": False,
        "aigc_watermark": False,
    }
    # 兼容旧参数（部分账户仍会读取 voice_name）
    if voice_name:
        payload["voice_name"] = voice_name
    resp = requests.post(
        _api_url("/v1/voice_clone"),
        headers=_auth_headers({"Content-Type": "application/json"}),
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()
    _check_api_result(result, "克隆声音")

    # 有的返回不会带 voice_id，兜底用我们传入值
    returned_voice_id = (
        result.get("voice_id")
        or result.get("data", {}).get("voice_id")
        or custom_voice_id
    )
    if not isinstance(returned_voice_id, str) or not returned_voice_id.strip():
        returned_voice_id = custom_voice_id
    returned_voice_id = returned_voice_id.strip()

    print(f"[2/3] 克隆成功！voice_id: {returned_voice_id}")
    return returned_voice_id


def save_to_env(voice_id: str) -> None:
    """把 voice_id 写入 .env 文件"""
    set_key(str(ENV_FILE), "MINIMAX_VOICE_ID", voice_id)
    print(f"[3/3] 已写入 .env: MINIMAX_VOICE_ID={voice_id}")


def smoke_test_tts(voice_id: str, text: str, out_path: Path) -> Path:
    """克隆完成后做一次 TTS 验证，确保 voice_id 可立即生效"""
    payload = {
        "model": "speech-02-turbo",
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": 1.05,
            "pitch": 0,
            "vol": 1.0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
        },
    }
    resp = requests.post(
        _api_url("/v1/t2a_v2"),
        headers=_auth_headers({"Content-Type": "application/json"}),
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()
    _check_api_result(result, "克隆音色TTS验证")

    audio_hex = result.get("data", {}).get("audio", "")
    if not audio_hex:
        raise RuntimeError("TTS 验证失败：返回中没有 audio 字段")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes.fromhex(audio_hex))
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MiniMax 声音克隆")
    parser.add_argument("audio_file", help="用于克隆的音频文件路径")
    parser.add_argument("--voice-name", default="my_voice", help="音色名称")
    parser.add_argument(
        "--voice-id",
        default="",
        help="可选：自定义 voice_id（8-20位字母数字），不传则自动生成",
    )
    parser.add_argument(
        "--test-text",
        default="这是一段克隆音色验证语音，如果你听起来像你自己，说明已经打通。",
        help="克隆后用于验证的测试文案",
    )
    parser.add_argument(
        "--clone-preview-text",
        default="这是一段用于音色复刻的试听文本。",
        help="voice_clone 接口的 text 参数（用于创建时试听）",
    )
    parser.add_argument(
        "--test-out",
        default="../output/voice-clone-test.mp3",
        help="克隆后验证音频输出路径",
    )
    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="跳过克隆后 TTS 验证",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _require_env()

    audio_file = Path(args.audio_file).expanduser()
    if not audio_file.is_absolute():
        audio_file = (Path(__file__).resolve().parent / audio_file).resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"文件不存在: {audio_file}")

    test_out = Path(args.test_out).expanduser()
    if not test_out.is_absolute():
        test_out = (Path(__file__).resolve().parent / test_out).resolve()

    print(f"\n{'=' * 44}")
    print(" MiniMax 声音克隆")
    print(f" BASE_URL: {BASE_URL}")
    print(f" GROUP_ID: {MINIMAX_GROUP_ID}")
    print(f"{'=' * 44}\n")

    file_id = upload_audio(audio_file)
    voice_id = create_voice_clone(
        file_id=file_id,
        voice_name=args.voice_name,
        voice_id=args.voice_id,
        preview_text=args.clone_preview_text,
    )
    save_to_env(voice_id)

    if args.skip_test:
        print("\n已跳过 TTS 验证。")
    else:
        test_path = smoke_test_tts(voice_id=voice_id, text=args.test_text, out_path=test_out)
        print(f"\n克隆音色验证完成：{test_path}")

    print("\n完成！后续 run.py / step2_tts.py 会自动使用该 voice_id。")


if __name__ == "__main__":
    main()
