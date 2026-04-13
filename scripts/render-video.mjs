#!/usr/bin/env node
/**
 * Full Video Render Pipeline
 * Usage: node scripts/render-video.mjs [script.json] [--vertical]
 *
 * 1. Generates TTS audio (if manifest doesn't exist)
 * 2. Renders video using Remotion CLI
 */

import {readFileSync, existsSync, mkdirSync} from 'fs';
import {execSync} from 'child_process';
import {resolve, dirname} from 'path';
import {fileURLToPath} from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, '..');

// Parse args
const args = process.argv.slice(2);
const isVertical = args.includes('--vertical');
const scriptPath = args.find((a) => !a.startsWith('--')) || resolve(projectRoot, 'src/data/sample-script.json');

const compositionId = isVertical ? 'CardVideoVertical' : 'CardVideo';
const layoutName = isVertical ? 'portrait' : 'landscape';
const outputDir = resolve(projectRoot, 'out');
mkdirSync(outputDir, {recursive: true});
const outputPath = resolve(outputDir, isVertical ? 'card-video-vertical.mp4' : 'card-video.mp4');

console.log(`=== Card Video Render Pipeline ===`);
console.log(`Script: ${scriptPath}`);
console.log(`Layout: ${layoutName}`);
console.log(`Composition: ${compositionId}`);
console.log(`Output: ${outputPath}`);
console.log('');

// Step 1: Read script
const script = JSON.parse(readFileSync(scriptPath, 'utf-8'));

// Step 2: Generate TTS if needed
const manifestPath = resolve(projectRoot, 'public/audio/manifest.json');
if (!existsSync(manifestPath)) {
  const envPath = resolve(projectRoot, '.env');
  let useMiniMax = false;
  if (existsSync(envPath)) {
    const envText = readFileSync(envPath, 'utf-8');
    const has = (key) => envText.split('\n').some((line) => line.startsWith(`${key}=`) && line.split('=', 2)[1].trim() !== '');
    useMiniMax = has('MINIMAX_API_KEY') && has('MINIMAX_GROUP_ID') && has('MINIMAX_VOICE_ID');
  }

  if (useMiniMax) {
    console.log('Step 1/2: Generating MiniMax cloned-voice TTS audio...');
    execSync(`python3 ${resolve(__dirname, 'generate_tts_minimax.py')} "${scriptPath}" "${resolve(projectRoot, 'public/audio')}"`, {
      stdio: 'inherit',
      cwd: projectRoot,
    });
  } else {
    console.log('Step 1/2: Generating fallback Edge TTS audio...');
    execSync(`node ${resolve(__dirname, 'generate-tts.mjs')} "${scriptPath}"`, {
      stdio: 'inherit',
      cwd: projectRoot,
    });
  }
} else {
  console.log('Step 1/2: TTS audio already exists, skipping generation.');
  console.log('  (Delete public/audio/manifest.json to regenerate)');
}

// Step 3: Read manifest and build props
const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));

const props = {
  script,
  audioFiles: manifest.audioFiles,
  slideDurations: manifest.slideDurations,
  layout: layoutName,
};

// Write props to a temp file (avoid shell escaping issues with long JSON)
const propsPath = resolve(projectRoot, '.tmp-props.json');
const {writeFileSync} = await import('fs');
writeFileSync(propsPath, JSON.stringify(props));

console.log('');
console.log(`Step 2/2: Rendering video (${manifest.slideDurations.reduce((a, b) => a + b, 0).toFixed(1)}s)...`);
console.log('');

// Step 4: Render
try {
  execSync(
    `npx remotion render src/index.ts ${compositionId} "${outputPath}" --props="${propsPath}"`,
    {
      stdio: 'inherit',
      cwd: projectRoot,
      timeout: 600000, // 10 minutes max
    },
  );
  console.log('');
  console.log(`=== DONE ===`);
  console.log(`Output: ${outputPath}`);
} finally {
  // Clean up temp props file
  try {
    const {unlinkSync} = await import('fs');
    unlinkSync(propsPath);
  } catch {}
}
