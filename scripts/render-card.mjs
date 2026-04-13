#!/usr/bin/env node
/**
 * Render a card video from a script JSON.
 * Usage: node scripts/render-card.mjs <script.json> [--output <name>]
 */

import {readFileSync, writeFileSync, unlinkSync, mkdirSync, existsSync} from 'fs';
import {execSync} from 'child_process';
import {resolve, dirname, basename} from 'path';
import {fileURLToPath} from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, '..');

const args = process.argv.slice(2);
const scriptPath = args.find((a) => !a.startsWith('--'));
const outputIdx = args.indexOf('--output');
const outputName = outputIdx >= 0 ? args[outputIdx + 1] : null;

if (!scriptPath) {
  console.log('Usage: node scripts/render-card.mjs <script.json> [--output <name>]');
  process.exit(1);
}

const script = JSON.parse(readFileSync(scriptPath, 'utf-8'));

// 自动读取 manifest.json 获取音频文件和时长
const manifestPath = resolve(projectRoot, 'public/audio/manifest.json');
let audioFiles = [];
let durations = script.slides.map((s) => s.duration || 3);

if (existsSync(manifestPath)) {
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));
  audioFiles = manifest.audioFiles || [];
  if (manifest.slideDurations && manifest.slideDurations.length === durations.length) {
    durations = manifest.slideDurations;
  }
  console.log(`Audio manifest loaded: ${audioFiles.filter(Boolean).length} audio files`);
}

const totalDur = durations.reduce((a, b) => a + b, 0);

const name = outputName || basename(scriptPath, '.json').replace('-script', '');
const outputDir = resolve(projectRoot, 'out');
mkdirSync(outputDir, {recursive: true});
const outputPath = resolve(outputDir, `${name}.mp4`);

console.log(`=== Card Video Render ===`);
console.log(`Script: ${scriptPath}`);
console.log(`Slides: ${script.slides.length}`);
console.log(`Duration: ${totalDur.toFixed(1)}s`);
console.log(`Output: ${outputPath}`);
console.log('');

const props = {
  script,
  audioFiles,
  slideDurations: durations,
  layout: 'landscape',
};

const propsPath = resolve(projectRoot, '.tmp-props.json');
writeFileSync(propsPath, JSON.stringify(props));

try {
  execSync(
    `npx remotion render src/index.ts CardVideo "${outputPath}" --props="${propsPath}"`,
    {stdio: 'inherit', cwd: projectRoot, timeout: 600000}
  );
  console.log('');
  console.log(`=== DONE: ${outputPath} ===`);
} finally {
  try { unlinkSync(propsPath); } catch {}
}
