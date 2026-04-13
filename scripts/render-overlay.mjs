#!/usr/bin/env node
/**
 * Render an overlay-style video from an overlay script JSON.
 *
 * Usage:
 *   node scripts/render-overlay.mjs src/data/<name>-overlay.json --output <name>
 */

import {execSync} from 'child_process';
import {readFileSync, writeFileSync, unlinkSync} from 'fs';
import {resolve, basename} from 'path';

const args = process.argv.slice(2);
const scriptPath = args[0];
if (!scriptPath) {
  console.error('Usage: node render-overlay.mjs <overlay-script.json> [--output <name>]');
  process.exit(1);
}

// Parse --output flag
let outputName = basename(scriptPath).replace('-overlay.json', '').replace('.json', '');
const outputIdx = args.indexOf('--output');
if (outputIdx !== -1 && args[outputIdx + 1]) {
  outputName = args[outputIdx + 1];
}

const script = JSON.parse(readFileSync(scriptPath, 'utf-8'));
const outputPath = resolve('out', `${outputName}-overlay.mp4`);

console.log('=== Overlay Video Render ===');
console.log(`Script: ${scriptPath}`);
console.log(`Segments: ${script.segments.length}`);
console.log(`Duration: ${script.totalDuration}s`);
console.log(`Hook: ${script.hookTitle} / ${script.hookSubtitle}`);
console.log(`Output: ${outputPath}`);
console.log();

// Write props to temp file
const props = {script};
const tmpProps = '.tmp-overlay-props.json';
writeFileSync(tmpProps, JSON.stringify(props));

try {
  const cmd = [
    'npx', 'remotion', 'render',
    'src/index.ts',
    'OverlayVideo',
    outputPath,
    `--props=${tmpProps}`,
  ].join(' ');

  console.log(`Running: ${cmd}\n`);
  execSync(cmd, {stdio: 'inherit', cwd: resolve('.')});
  console.log(`\n=== DONE: ${outputPath} ===`);
} finally {
  try { unlinkSync(tmpProps); } catch {}
}
