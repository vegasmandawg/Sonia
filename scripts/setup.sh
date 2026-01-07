#!/bin/bash

# Automated Setup Script
# Prepares environment for first-time deployment

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║     Sonia AI Companion - Automated Setup           ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# Step 1: Check Node.js
log_info "Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    log_error "Node.js is not installed!"
    log_info "Please install Node.js 18+ from https://nodejs.org/"
    exit 1
fi
log_success "Node.js $(node -v) found"

# Step 2: Install dependencies
log_info "Installing dependencies..."
if [ ! -d "node_modules" ]; then
    npm install
    log_success "Dependencies installed"
else
    log_info "Dependencies already installed"
fi

# Step 3: Setup environment
log_info "Setting up environment..."
if [ ! -f ".env.local" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env.local
        log_success "Created .env.local from template"
    else
        log_error ".env.example not found!"
        exit 1
    fi
else
    log_info ".env.local already exists"
fi

# Step 4: Prompt for API key
if ! grep -q "GEMINI_API_KEY=.\+" .env.local 2>/dev/null; then
    log_warning "GEMINI_API_KEY not configured"
    echo ""
    read -p "Enter your Gemini API key (or press Enter to skip): " api_key
    if [ ! -z "$api_key" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s/GEMINI_API_KEY=.*/GEMINI_API_KEY=$api_key/" .env.local
        else
            sed -i "s/GEMINI_API_KEY=.*/GEMINI_API_KEY=$api_key/" .env.local
        fi
        log_success "API key configured"
    else
        log_warning "Skipped API key setup. Please edit .env.local manually."
    fi
else
    log_success "API key already configured"
fi

# Step 5: Make scripts executable
log_info "Making scripts executable..."
chmod +x scripts/*.sh 2>/dev/null || true
log_success "Scripts are now executable"

# Step 6: Test build
log_info "Testing build process..."
if npm run build > /dev/null 2>&1; then
    log_success "Build test passed"
else
    log_error "Build test failed!"
    log_info "Please check for errors and try again"
    exit 1
fi

# Step 7: Summary
echo ""
echo "========================================"
log_success "Setup completed successfully!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Review .env.local and add your API keys"
echo "2. Start development server: npm run dev"
echo "3. Build for production: npm run build"
echo "4. Deploy: ./scripts/deploy.sh"
echo ""
echo "For more information, see:"
echo "- GETTING_STARTED.md"
echo "- docs/DEPLOYMENT.md"
echo ""
