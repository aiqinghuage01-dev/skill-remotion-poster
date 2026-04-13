#!/usr/bin/env node
/**
 * Render a scene video from a scene script JSON.
 * Usage: node scripts/render-scene.mjs <scene-script.json> [--output <name>]
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
  console.log('Usage: node scripts/render-scene.mjs <scene-script.json> [--output <name>]');
  process.exit(1);
}

const script = JSON.parse(readFileSync(scriptPath, 'utf-8'));

// Auto-load manifest.json for audio metadata
const manifestPath = resolve(projectRoot, 'public/audio/manifest.json');
let audioFiles = [];
let durations = script.scenes.map((s) => s.duration || 5);

if (existsSync(manifestPath)) {
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));
  audioFiles = manifest.audioFiles || [];
  if (manifest.slideDurations && manifest.slideDurations.length === durations.length) {
    durations = manifest.slideDurations;
  }
  console.log(`Audio manifest loaded: ${audioFiles.filter(Boolean).length} audio files`);
}

const totalDur = durations.reduce((a, b) => a + b, 0);

const name = outputName || basename(scriptPath, '.json').replace('-scene-script', '').replace('-script', '');
const outputDir = resolve(projectRoot, 'out');
mkdirSync(outputDir, {recursive: true});
const outputPath = resolve(outputDir, `${name}.mp4`);

console.log(`=== Scene Video Render ===`);
console.log(`Script: ${scriptPath}`);
console.log(`Scenes: ${script.scenes.length}`);
console.log(`Duration: ${totalDur.toFixed(1)}s`);
console.log(`Output: ${outputPath}`);
console.log('');

const props = {
  script,
  audioFiles,
  sceneDurations: durations,
};

const propsPath = resolve(projectRoot, '.tmp-scene-props.json');
writeFileSync(propsPath, JSON.stringify(props));

try {
  execSync(
    `npx remotion render src/index.ts SceneVideo "${outputPath}" --props="${propsPath}"`,
    {stdio: 'inherit', cwd: projectRoot, timeout: 600000}
  );
  console.log('');
  console.log(`=== DONE: ${outputPath} ===`);
} finally {
  try { unlinkSync(propsPath); } catch {}
}
