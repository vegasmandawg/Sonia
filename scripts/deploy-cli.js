#!/usr/bin/env node

/**
 * Interactive Deployment CLI for Sonia AI Companion
 * Provides a guided deployment experience
 */

const readline = require('readline');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

// Colors
const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m'
};

const log = {
  info: (msg) => console.log(`${colors.blue}[INFO]${colors.reset} ${msg}`),
  success: (msg) => console.log(`${colors.green}[✓]${colors.reset} ${msg}`),
  error: (msg) => console.log(`${colors.red}[✗]${colors.reset} ${msg}`),
  warning: (msg) => console.log(`${colors.yellow}[⚠]${colors.reset} ${msg}`),
  title: (msg) => console.log(`${colors.cyan}${colors.bright}${msg}${colors.reset}`)
};

function ask(question) {
  return new Promise((resolve) => rl.question(question, resolve));
}

function exec(command, silent = false) {
  try {
    const result = execSync(command, { 
      encoding: 'utf8',
      stdio: silent ? 'pipe' : 'inherit'
    });
    return { success: true, output: result };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

function showBanner() {
  console.clear();
  console.log('');
  console.log(colors.cyan + '╔═══════════════════════════════════════════════════════╗' + colors.reset);
  console.log(colors.cyan + '║     SONIA AI COMPANION - DEPLOYMENT WIZARD        ║' + colors.reset);
  console.log(colors.cyan + '║              Production Ready v1.0.0                 ║' + colors.reset);
  console.log(colors.cyan + '╚═══════════════════════════════════════════════════════╝' + colors.reset);
  console.log('');
}

function checkPrerequisites() {
  log.title('Checking Prerequisites...');
  
  // Check Node.js
  const nodeResult = exec('node -v', true);
  if (nodeResult.success) {
    log.success(`Node.js ${nodeResult.output.trim()} installed`);
  } else {
    log.error('Node.js not found! Please install Node.js 18+');
    return false;
  }
  
  // Check npm
  const npmResult = exec('npm -v', true);
  if (npmResult.success) {
    log.success(`npm ${npmResult.output.trim()} installed`);
  } else {
    log.error('npm not found!');
    return false;
  }
  
  // Check .env.local
  if (!fs.existsSync('.env.local')) {
    log.warning('.env.local not found');
    log.info('Creating from .env.example...');
    if (fs.existsSync('.env.example')) {
      fs.copyFileSync('.env.example', '.env.local');
      log.success('Created .env.local');
    } else {
      log.error('.env.example not found!');
      return false;
    }
  } else {
    log.success('.env.local exists');
  }
  
  console.log('');
  return true;
}

async function selectDeploymentTarget() {
  log.title('Select Deployment Target:');
  console.log('1) Vercel (Serverless, recommended)');
  console.log('2) Netlify (Static hosting)');
  console.log('3) Docker (Single container)');
  console.log('4) Docker Compose (Multi-container)');
  console.log('5) Kubernetes (Cloud-native)');
  console.log('6) Exit');
  console.log('');
  
  const choice = await ask('Enter your choice (1-6): ');
  return parseInt(choice);
}

async function deployVercel() {
  log.title('Deploying to Vercel...');
  
  // Check if Vercel CLI is installed
  const vercelCheck = exec('vercel --version', true);
  if (!vercelCheck.success) {
    log.warning('Vercel CLI not installed');
    const install = await ask('Install Vercel CLI? (y/n): ');
    if (install.toLowerCase() === 'y') {
      log.info('Installing Vercel CLI...');
      exec('npm i -g vercel');
    } else {
      log.error('Cannot deploy without Vercel CLI');
      return;
    }
  }
  
  // Build
  log.info('Building application...');
  const buildResult = exec('npm run build');
  if (!buildResult.success) {
    log.error('Build failed!');
    return;
  }
  
  // Deploy
  log.info('Deploying to Vercel...');
  exec('vercel --prod');
  
  log.success('Deployment complete!');
}

async function deployNetlify() {
  log.title('Deploying to Netlify...');
  
  // Check if Netlify CLI is installed
  const netlifyCheck = exec('netlify --version', true);
  if (!netlifyCheck.success) {
    log.warning('Netlify CLI not installed');
    const install = await ask('Install Netlify CLI? (y/n): ');
    if (install.toLowerCase() === 'y') {
      log.info('Installing Netlify CLI...');
      exec('npm i -g netlify-cli');
    } else {
      log.error('Cannot deploy without Netlify CLI');
      return;
    }
  }
  
  // Build
  log.info('Building application...');
  const buildResult = exec('npm run build');
  if (!buildResult.success) {
    log.error('Build failed!');
    return;
  }
  
  // Deploy
  log.info('Deploying to Netlify...');
  exec('netlify deploy --prod --dir=dist');
  
  log.success('Deployment complete!');
}

async function deployDocker() {
  log.title('Deploying with Docker...');
  
  // Check if Docker is installed
  const dockerCheck = exec('docker --version', true);
  if (!dockerCheck.success) {
    log.error('Docker not installed! Please install Docker first.');
    return;
  }
  log.success('Docker detected');
  
  // Build image
  log.info('Building Docker image...');
  const buildResult = exec('docker build -t sonia-ai-companion:latest .');
  if (!buildResult.success) {
    log.error('Docker build failed!');
    return;
  }
  
  // Run container
  log.info('Starting container...');
  exec('docker stop sonia-ai-companion 2>/dev/null || true', true);
  exec('docker rm sonia-ai-companion 2>/dev/null || true', true);
  exec('docker run -d --name sonia-ai-companion -p 80:80 --restart unless-stopped sonia-ai-companion:latest');
  
  log.success('Deployment complete!');
  log.info('Access your app at: http://localhost');
}

async function deployDockerCompose() {
  log.title('Deploying with Docker Compose...');
  
  // Check if Docker Compose is installed
  const composeCheck = exec('docker-compose --version', true);
  if (!composeCheck.success) {
    log.error('Docker Compose not installed!');
    return;
  }
  log.success('Docker Compose detected');
  
  // Deploy
  log.info('Building and starting services...');
  exec('docker-compose up -d --build');
  
  log.success('Deployment complete!');
  log.info('Access your app at: http://localhost');
}

async function deployKubernetes() {
  log.title('Deploying to Kubernetes...');
  
  // Check kubectl
  const kubectlCheck = exec('kubectl version --client', true);
  if (!kubectlCheck.success) {
    log.error('kubectl not installed!');
    return;
  }
  log.success('kubectl detected');
  
  log.info('Applying Kubernetes manifests...');
  
  // Apply secrets
  log.warning('Make sure to update k8s/secrets.yaml with your API keys first!');
  const proceed = await ask('Continue? (y/n): ');
  if (proceed.toLowerCase() !== 'y') {
    log.info('Deployment cancelled');
    return;
  }
  
  exec('kubectl apply -f k8s/secrets.yaml');
  exec('kubectl apply -f k8s/deployment.yaml');
  exec('kubectl apply -f k8s/ingress.yaml');
  
  log.success('Kubernetes deployment complete!');
  log.info('Check status: kubectl get pods');
}

async function main() {
  showBanner();
  
  if (!checkPrerequisites()) {
    log.error('Prerequisites check failed!');
    process.exit(1);
  }
  
  const target = await selectDeploymentTarget();
  console.log('');
  
  switch (target) {
    case 1:
      await deployVercel();
      break;
    case 2:
      await deployNetlify();
      break;
    case 3:
      await deployDocker();
      break;
    case 4:
      await deployDockerCompose();
      break;
    case 5:
      await deployKubernetes();
      break;
    case 6:
      log.info('Exiting...');
      break;
    default:
      log.error('Invalid choice');
  }
  
  console.log('');
  rl.close();
}

main().catch(error => {
  log.error(`Deployment failed: ${error.message}`);
  process.exit(1);
});
