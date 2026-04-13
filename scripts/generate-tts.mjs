#!/usr/bin/env node
/**
 * TTS Audio Generator
 * Usage: node scripts/generate-tts.mjs [script.json]
 *
 * Reads a VideoScript JSON, generates one MP3 per slide using edge-tts,
 * measures durations, and writes public/audio/manifest.json.
 */

import {readFileSync, writeFileSync, mkdirSync, existsSync} from 'fs';
import {execSync} from 'child_process';
import {resolve, dirname} from 'path';
import {fileURLToPath} from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, '..');

// Config
const VOICE = 'zh-CN-YunxiNeural'; // Male Chinese voice; alternatives: zh-CN-XiaoxiaoNeural (female)
const AUDIO_DIR = resolve(projectRoot, 'public/audio');

// Parse args
const scriptPath = process.argv[2] || resolve(projectRoot, 'src/data/sample-script.json');

console.log(`Reading script from: ${scriptPath}`);
const script = JSON.parse(readFileSync(scriptPath, 'utf-8'));

// Ensure audio directory exists
mkdirSync(AUDIO_DIR, {recursive: true});

const audioFiles = [];
const slideDurations = [];

for (let i = 0; i < script.slides.length; i++) {
  const slide = script.slides[i];
  const narration = slide.narration;

  if (!narration || narration.trim() === '') {
    console.log(`Slide ${i}: no narration, using duration ${slide.duration || 3}s`);
    audioFiles.push('');
    slideDurations.push(slide.duration || 3);
    continue;
  }

  const audioFile = `audio/slide-${String(i).padStart(3, '0')}.mp3`;
  const audioPath = resolve(projectRoot, 'public', audioFile);

  console.log(`Slide ${i}: generating TTS for "${narration.substring(0, 30)}..."`);

  try {
    // Generate audio using edge-tts via python3 -m
    execSync(
      `python3 -m edge_tts --voice "${VOICE}" --text "${narration.replace(/"/g, '\\"')}" --write-media "${audioPath}"`,
      {stdio: 'pipe', timeout: 30000},
    );

    // Measure duration using ffmpeg
    const durationStr = execSync(
      `ffmpeg -i "${audioPath}" -f null - 2>&1 | grep "time=" | tail -1`,
      {encoding: 'utf-8', timeout: 10000},
    );

    let duration = slide.duration || 5;
    const timeMatch = durationStr.match(/time=(\d+):(\d+):(\d+\.\d+)/);
    if (timeMatch) {
      duration = parseInt(timeMatch[1]) * 3600 + parseInt(timeMatch[2]) * 60 + parseFloat(timeMatch[3]);
      // Add 0.5s padding after each slide
      duration = Math.max(duration + 0.5, slide.duration || 0);
    }

    audioFiles.push(audioFile);
    slideDurations.push(Math.round(duration * 10) / 10);
    console.log(`  -> ${audioFile} (${duration.toFixed(1)}s)`);
  } catch (err) {
    console.error(`  ERROR generating TTS for slide ${i}:`, err.message);
    audioFiles.push('');
    slideDurations.push(slide.duration || 5);
  }
}

// Write manifest
const manifest = {audioFiles, slideDurations};
const manifestPath = resolve(AUDIO_DIR, 'manifest.json');
writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
console.log(`\nManifest written to: ${manifestPath}`);
console.log(`Total duration: ${slideDurations.reduce((a, b) => a + b, 0).toFixed(1)}s`);
console.log(`Slides: ${script.slides.length}`);
