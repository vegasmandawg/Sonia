#!/bin/bash

# Sonia AI Companion - Advanced All-in-One Deployment Script
# Supports: Vercel, Netlify, Docker, AWS, and local deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Banner
show_banner() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════╗"
    echo "║       Sonia AI Companion - Deployment Tool           ║"
    echo "║              Production Ready v1.0.0                 ║"
    echo "╚═══════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Node.js
    if ! command -v node &> /dev/null; then
        log_error "Node.js is not installed. Please install Node.js 18+"
        exit 1
    fi
    
    local NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$NODE_VERSION" -lt 18 ]; then
        log_error "Node.js version must be 18 or higher (current: $(node -v))"
        exit 1
    fi
    log_success "Node.js $(node -v) detected"
    
    # Check npm
    if ! command -v npm &> /dev/null; then
        log_error "npm is not installed"
        exit 1
    fi
    log_success "npm $(npm -v) detected"
    
    # Check git
    if ! command -v git &> /dev/null; then
        log_warning "git is not installed (optional for some deployments)"
    else
        log_success "git $(git --version | cut -d' ' -f3) detected"
    fi
}

# Validate environment
validate_environment() {
    log_info "Validating environment configuration..."
    
    # Check for .env.local
    if [ ! -f ".env.local" ]; then
        log_error ".env.local file not found!"
        log_info "Creating from .env.example..."
        
        if [ -f ".env.example" ]; then
            cp .env.example .env.local
            log_warning "Please edit .env.local and add your GEMINI_API_KEY"
            exit 1
        else
            log_error ".env.example not found. Cannot continue."
            exit 1
        fi
    fi
    
    # Check for API key
    if ! grep -q "GEMINI_API_KEY=.\+" .env.local; then
        log_error "GEMINI_API_KEY is not set in .env.local"
        log_info "Please add your Gemini API key to .env.local"
        exit 1
    fi
    
    log_success "Environment configuration validated"
}

# Run pre-flight checks
preflight_checks() {
    log_info "Running pre-flight checks..."
    
    # Check TypeScript
    log_info "Checking TypeScript..."
    if ! npm run build &> /dev/null; then
        log_error "Build failed! Please fix errors before deploying."
        npm run build
        exit 1
    fi
    log_success "TypeScript compilation successful"
    
    # Check for security vulnerabilities
    log_info "Running security audit..."
    npm audit --audit-level=high || log_warning "Security vulnerabilities detected. Review with 'npm audit'"
    
    log_success "Pre-flight checks completed"
}

# Deploy to Vercel
deploy_vercel() {
    log_info "Deploying to Vercel..."
    
    if ! command -v vercel &> /dev/null; then
        log_error "Vercel CLI not installed. Installing..."
        npm i -g vercel
    fi
    
    # Check if already linked
    if [ ! -f ".vercel/project.json" ]; then
        log_info "Linking project to Vercel..."
        vercel link
    fi
    
    # Set environment variables
    log_info "Setting environment variables..."
    source .env.local
    vercel env add GEMINI_API_KEY production <<< "$GEMINI_API_KEY" 2>/dev/null || log_warning "Environment variable may already exist"
    
    # Deploy
    log_info "Deploying to production..."
    vercel --prod
    
    log_success "Deployed to Vercel!"
}

# Deploy to Netlify
deploy_netlify() {
    log_info "Deploying to Netlify..."
    
    if ! command -v netlify &> /dev/null; then
        log_error "Netlify CLI not installed. Installing..."
        npm i -g netlify-cli
    fi
    
    # Build
    log_info "Building application..."
    npm run build
    
    # Deploy
    log_info "Deploying to Netlify..."
    netlify deploy --prod --dir=dist
    
    log_success "Deployed to Netlify!"
}

# Deploy with Docker
deploy_docker() {
    log_info "Deploying with Docker..."
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Load environment variables
    source .env.local
    
    # Build image
    log_info "Building Docker image..."
    docker build \
        --build-arg GEMINI_API_KEY="$GEMINI_API_KEY" \
        --build-arg VITE_APP_ENV=production \
        -t sonia-ai-companion:latest .
    
    # Stop existing container
    log_info "Stopping existing container..."
    docker stop sonia-ai-companion 2>/dev/null || true
    docker rm sonia-ai-companion 2>/dev/null || true
    
    # Run container
    log_info "Starting new container..."
    docker run -d \
        --name sonia-ai-companion \
        -p 80:80 \
        --restart unless-stopped \
        sonia-ai-companion:latest
    
    log_success "Deployed with Docker!"
    log_info "Access your app at: http://localhost"
}

# Deploy with Docker Compose
deploy_docker_compose() {
    log_info "Deploying with Docker Compose..."
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi
    
    # Build and deploy
    log_info "Building and starting services..."
    docker-compose up -d --build
    
    log_success "Deployed with Docker Compose!"
    log_info "Access your app at: http://localhost"
}

# Deploy to local (development)
deploy_local() {
    log_info "Starting local development server..."
    
    npm run dev
}

# Health check
health_check() {
    local URL=$1
    log_info "Running health check on $URL..."
    
    if command -v curl &> /dev/null; then
        if curl -f -s -o /dev/null -w "%{http_code}" "$URL" | grep -q "200\|301\|302"; then
            log_success "Health check passed!"
            return 0
        else
            log_error "Health check failed!"
            return 1
        fi
    else
        log_warning "curl not available, skipping health check"
        return 0
    fi
}

# Post-deployment verification
post_deployment_verification() {
    log_info "Running post-deployment verification..."
    
    # Check if build artifacts exist
    if [ -d "dist" ]; then
        log_success "Build artifacts found"
    else
        log_error "Build artifacts not found!"
        return 1
    fi
    
    # Check critical files
    local critical_files=("dist/index.html" "dist/assets")
    for file in "${critical_files[@]}"; do
        if [ -e "$file" ]; then
            log_success "Critical file/directory found: $file"
        else
            log_error "Missing critical file/directory: $file"
            return 1
        fi
    done
    
    log_success "Post-deployment verification passed!"
}

# Rollback function
rollback() {
    log_warning "Initiating rollback..."
    
    if [ -d "dist.backup" ]; then
        rm -rf dist
        mv dist.backup dist
        log_success "Rolled back to previous version"
    else
        log_error "No backup found to rollback to"
        exit 1
    fi
}

# Backup current deployment
backup_current() {
    if [ -d "dist" ]; then
        log_info "Backing up current deployment..."
        rm -rf dist.backup
        cp -r dist dist.backup
        log_success "Backup created"
    fi
}

# Main menu
show_menu() {
    echo ""
    echo "Select deployment target:"
    echo "1) Vercel (Serverless)"
    echo "2) Netlify (Static)"
    echo "3) Docker (Single Container)"
    echo "4) Docker Compose (Orchestrated)"
    echo "5) Local Development"
    echo "6) AWS S3 + CloudFront"
    echo "7) Run Pre-flight Checks Only"
    echo "8) Exit"
    echo ""
    read -p "Enter choice [1-8]: " choice
}

# Main execution
main() {
    show_banner
    
    # Change to script directory
    cd "$(dirname "$0")/.."
    
    check_prerequisites
    validate_environment
    
    show_menu
    
    case $choice in
        1)
            backup_current
            preflight_checks
            deploy_vercel
            post_deployment_verification
            ;;
        2)
            backup_current
            preflight_checks
            deploy_netlify
            post_deployment_verification
            ;;
        3)
            backup_current
            preflight_checks
            deploy_docker
            sleep 5
            health_check "http://localhost"
            ;;
        4)
            backup_current
            preflight_checks
            deploy_docker_compose
            sleep 5
            health_check "http://localhost"
            ;;
        5)
            deploy_local
            ;;
        6)
            log_error "AWS deployment script not yet implemented"
            log_info "Please refer to docs/DEPLOYMENT.md for manual AWS deployment"
            exit 1
            ;;
        7)
            preflight_checks
            post_deployment_verification
            ;;
        8)
            log_info "Exiting..."
            exit 0
            ;;
        *)
            log_error "Invalid choice"
            exit 1
            ;;
    esac
    
    log_success "Deployment completed successfully! 🚀"
}

# Run main function
main
