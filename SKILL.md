---
name: 文案自动成片
description: >
  不用数字人时，把现成文案或同轮刚生成的文案直接做成卡片式短视频。默认使用 MiniMax 克隆声音配音。
  当用户提到"文案成片""把文案做成视频""文字转视频""卡片视频""自动配音成片""不需要数字人"时触发。
  若当前请求明确提到"数字人/石榴/16AI/分身"，严禁使用本技能，改用 `shiliu-digital-human` 或 `digital-human-video`。
---

# 文案自动成片

## 执行回执（硬规则）

只要本轮因为 `skill` / `技能` 指名，或因为关键词命中而进入本技能，第一行先写：
`已走技能：文案卡片成片`

## 适用场景

- 用户直接给了一段文案，要做成视频
- 上一轮刚用文案 skill 产出文案，这一轮要继续做成视频
- 不需要数字人出镜
- 默认使用 MiniMax 克隆声音配音
- 输出形式为卡片动画成片

**不适用**：
- 明确提到 `数字人` / `石榴` / `16AI` / `分身`
- 用户要的是“数字人口播视频”
- 用户要的是“数字人 + 字幕/BGM/剪辑/卡片叠加的最终成片”

这两类请求分别改走：
- 只生成数字人口播：`shiliu-digital-human`
- 数字人剪辑成片：`digital-human-video`

## 硬规则

- 只要用户明确提到 `数字人`，立刻退出本技能，不要再走 MiniMax 配音
- 如果请求是“先写文案，再成片”，顺序必须是：
  - 先用匹配的文案 skill 产出最终文案
  - 再把该文案交给本技能
- 如果用户没有提供文案，也没有同轮刚生成的文案，禁止自己编文案
- 默认声音是当前 `.env` 中的 `MINIMAX_VOICE_ID`

## 验证安装

```bash
node scripts/setup.mjs --check
```

## 配音方案（三级降级）

默认走 MiniMax 克隆声音，没有 API Key 自动降级到免费方案：

```
1. MiniMax 克隆声音（最优）→ 需要 .env 中配置 MINIMAX_API_KEY / GROUP_ID / VOICE_ID
2. edge-tts 免费语音（兜底）→ 不需要任何 API Key，自动使用微软免费语音
3. 静音占位（保底）→ 如果 edge-tts 也不可用，生成无声视频
```

**判断逻辑**：
- 检查项目根目录有没有 `.env` 且包含 `MINIMAX_API_KEY`
  - 有 → 走 MiniMax：`python3 scripts/generate_tts_minimax.py`
  - 没有 → 走 edge-tts：`node scripts/generate-tts.mjs`（需要 `pip install edge-tts`，如果没装就自动装）
  - edge-tts 也失败 → 跳过配音，生成无声视频，提示用户后续补录

**学员首次使用时**：没有 .env 是正常的，直接走 edge-tts 免费配音即可。
**想升级克隆声音时**：配置 .env 并用 `python3 scripts/clone_voice.py scripts/my_voice.mp3` 克隆。

## Workflow

### Step 0: 先判断是不是数字人模式

如果当前用户消息出现以下任一表达：
- `数字人`
- `石榴`
- `16AI`
- `分身`

则**禁止继续执行本技能**：
- 只生成数字人视频 -> `shiliu-digital-human`
- 数字人最终成片 -> `digital-human-video`

### Step 1: 确定文案来源

优先级从高到低：

1. 用户直接贴了完整文案 -> 直接使用
2. 同一轮刚由 `touliu-agent` / `录音文案改写` / `热点文案改写V2` 等技能生成了文案 -> 直接复用
3. 用户明确指定了某个现有文案文件 -> 读取后使用

禁止行为：

- 没有文案时自己现场编一版
- 只因为用户提到行业，就自动写一版文案再继续成片

### Step 2: 生成 script JSON

把文案拆成 `src/data/<name>-script.json`，每页至少包含：

- `lines`
- `narration`
- `duration`

排版规则：

- 长文本不要整段塞进 `gradient`
- `gradient` 只用于短关键句
- 长句拆成 `title / body / emphasis`

### Step 3: 生成配音（自动选择方案）

**先检查 `.env` 是否存在且包含 `MINIMAX_API_KEY`**：

**有 MiniMax API Key → 走克隆声音**：
```bash
python3 scripts/generate_tts_minimax.py src/data/<name>-script.json public/audio/
```

**没有 .env 或没有 API Key → 走 edge-tts 免费配音**：
```bash
# 先确保 edge-tts 已安装
pip install edge-tts 2>/dev/null
node scripts/generate-tts.mjs src/data/<name>-script.json
```

两种方案都会写入 `public/audio/manifest.json`，后续渲染步骤完全一样。

### Step 4: 渲染成片

```bash
node scripts/render-card.mjs src/data/<name>-script.json --output <name>
```

### Step 5: 返回结果

成功后返回：

- 使用的文案来源
- 使用的 MiniMax `voice_id`
- script JSON 路径
- 最终视频路径

默认输出目录：

- `out/<name>.mp4`

## 快速路径

如果文案已经准备好，最短执行链就是：

```bash
python3 scripts/generate_tts_minimax.py src/data/<name>-script.json public/audio/
node scripts/render-card.mjs src/data/<name>-script.json --output <name>
```
