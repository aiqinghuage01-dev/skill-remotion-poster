#!/usr/bin/env node
/**
 * remotion-poster setup — 安装依赖并验证环境
 * 用法:
 *   node scripts/setup.mjs          # 安装
 *   node scripts/setup.mjs --check   # 仅验证
 */

import { execSync } from 'child_process';
import { existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const checkOnly = process.argv.includes('--check');

function run(cmd, opts = {}) {
  try {
    return execSync(cmd, { cwd: root, stdio: 'pipe', ...opts }).toString().trim();
  } catch {
    return null;
  }
}

function findCmd(name) {
  const which = process.platform === 'win32' ? 'where' : 'which';
  return run(`${which} ${name}`);
}

let ok = true;

// 1. Node.js
const nodeVer = run('node --version');
if (nodeVer) {
  const major = parseInt(nodeVer.replace('v', ''));
  if (major < 18) { console.error(`❌ Node.js >= 18 required, got ${nodeVer}`); ok = false; }
  else console.log(`✅ Node.js ${nodeVer}`);
} else { console.error('❌ Node.js not found'); ok = false; }

// 2. npm
if (findCmd('npm')) console.log('✅ npm available');
else { console.error('❌ npm not found'); ok = false; }

// 3. Python 3
if (findCmd('python3')) console.log('✅ python3 available');
else { console.error('❌ python3 not found — needed for TTS'); ok = false; }

// 4. FFmpeg
if (findCmd('ffmpeg')) console.log('✅ ffmpeg available');
else { console.error('⚠️  ffmpeg not found — some features may not work'); }

// 5. package.json
if (!existsSync(resolve(root, 'package.json'))) {
  console.error('❌ package.json not found'); ok = false;
} else if (!checkOnly) {
  if (!existsSync(resolve(root, 'node_modules'))) {
    console.log('📦 Installing npm dependencies...');
    try { execSync('npm install', { cwd: root, stdio: 'inherit' }); }
    catch { console.error('❌ npm install failed'); ok = false; }
  } else {
    console.log('✅ node_modules already exists');
  }
}

// 6. .env
if (existsSync(resolve(root, '.env'))) {
  console.log('✅ .env file found');
} else {
  console.error('⚠️  .env not found — create it with MINIMAX_API_KEY, MINIMAX_GROUP_ID, MINIMAX_VOICE_ID');
}

if (ok) console.log('\n🟢 环境就绪');
else { console.error('\n🔴 有依赖缺失，请修复后重试'); process.exit(1); }
