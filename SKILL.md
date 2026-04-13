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

## 运行前提

- `.env` 位于项目根目录，至少包含：
  - `MINIMAX_API_KEY`
  - `MINIMAX_GROUP_ID`
  - `MINIMAX_VOICE_ID`
- 如果需要重新克隆声音，使用：

```bash
python3 scripts/clone_voice.py scripts/my_voice.mp3
```

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

### Step 3: 生成 MiniMax 克隆声音配音

使用项目内脚本，不要再调用 `/tmp` 旧脚本：

```bash
python3 scripts/generate_tts_minimax.py src/data/<name>-script.json public/audio/
```

这个脚本会：

- 读取项目根目录 `.env`
- 使用 `MINIMAX_VOICE_ID` 生成每页配音
- 写入 `public/audio/manifest.json`

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
