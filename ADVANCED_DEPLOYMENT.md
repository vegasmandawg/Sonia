# Advanced All-in-One Deployment Guide

## 🚀 Quick Deploy (Automated)

### Option 1: Interactive CLI Wizard (Recommended)

```bash
node scripts/deploy-cli.js
```

This interactive wizard will:
- Check prerequisites
- Validate environment
- Guide you through deployment options
- Handle the entire deployment process

### Option 2: Bash Deployment Script

```bash
./scripts/deploy.sh
```

Features:
- Pre-flight checks
- Multiple platform support
- Automatic backup
- Health monitoring
- Rollback capability

---

## 📋 Available Scripts

### Setup & Configuration

#### **Automated Setup**
```bash
./scripts/setup.sh
```
- Installs dependencies
- Creates environment files
- Configures API keys
- Tests build process

### Deployment Scripts

#### **Main Deployment Script**
```bash
./scripts/deploy.sh
```
Interactive menu with options:
1. Deploy to Vercel
2. Deploy to Netlify
3. Deploy with Docker
4. Deploy with Docker Compose
5. Local Development
6. AWS S3 + CloudFront (coming soon)
7. Pre-flight checks only

#### **Interactive CLI**
```bash
node scripts/deploy-cli.js
```
Node.js-based interactive deployment wizard

### Monitoring & Testing

#### **Health Check**
```bash
./scripts/health-check.sh [URL]
```
Tests:
- Server availability
- Response time
- HTML content
- Security headers
- SSL certificate
- Compression
- Cache headers

Example:
```bash
./scripts/health-check.sh https://your-app.com
```

#### **Performance Monitor**
```bash
./scripts/monitor.sh [URL] [DURATION]
```
Monitors application for specified duration:
```bash
./scripts/monitor.sh http://localhost 60  # Monitor for 60 seconds
```

Tracks:
- Response times (avg, min, max)
- Success/failure rates
- Uptime percentage

#### **Load Test**
```bash
./scripts/load-test.sh [URL] [CONCURRENT_USERS] [REQUESTS_PER_USER]
```
Stress tests your application:
```bash
./scripts/load-test.sh http://localhost 50 1000
# 50 concurrent users, 1000 requests each
```

### Backup & Recovery

#### **Create Backup**
```bash
./scripts/backup.sh
```
- Backs up build artifacts
- Saves configuration
- Creates compressed archive
- Keeps last 5 backups

#### **Restore from Backup**
```bash
./scripts/restore.sh backups/sonia-backup-TIMESTAMP.tar.gz
```

---

## 🐳 Docker Deployment

### Single Container

```bash
# Build
docker build -t sonia-ai-companion:latest .

# Run
docker run -d \
  --name sonia-ai-companion \
  -p 80:80 \
  --restart unless-stopped \
  sonia-ai-companion:latest

# Check logs
docker logs -f sonia-ai-companion

# Stop
docker stop sonia-ai-companion
```

### Docker Compose

```bash
# Start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Rebuild
docker-compose up -d --build
```

### Docker with Custom Port

```bash
docker run -d \
  --name sonia-ai \
  -p 8080:80 \
  -e GEMINI_API_KEY="your_key" \
  sonia-ai-companion:latest
```

---

## ☸️ Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (GKE, EKS, AKS, or local)
- kubectl configured
- cert-manager (for SSL)

### Quick Deploy

```bash
# 1. Update secrets
nano k8s/secrets.yaml  # Add your API keys

# 2. Apply manifests
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/ingress.yaml

# 3. Check status
kubectl get pods
kubectl get services
kubectl get ingress

# 4. View logs
kubectl logs -f deployment/sonia-ai-deployment
```

### Scaling

```bash
# Manual scaling
kubectl scale deployment sonia-ai-deployment --replicas=5

# Auto-scaling is configured (HPA)
# Min: 2, Max: 10
# Triggers: CPU > 70%, Memory > 80%
```

### Update Deployment

```bash
# Update image
kubectl set image deployment/sonia-ai-deployment \
  sonia-ai=sonia-ai-companion:v1.1.0

# Rollout status
kubectl rollout status deployment/sonia-ai-deployment

# Rollback if needed
kubectl rollout undo deployment/sonia-ai-deployment
```

---

## 🌐 Platform-Specific Deployments

### Vercel

#### Via CLI
```bash
# Install
npm i -g vercel

# Login
vercel login

# Deploy
vercel --prod

# Set environment variable
vercel env add GEMINI_API_KEY
```

#### Via GitHub Integration
1. Push code to GitHub
2. Import in Vercel dashboard
3. Add environment variables
4. Deploy automatically on push

### Netlify

#### Via CLI
```bash
# Install
npm i -g netlify-cli

# Login
netlify login

# Build
npm run build

# Deploy
netlify deploy --prod --dir=dist
```

#### Drag & Drop
1. Run `npm run build`
2. Go to [app.netlify.com](https://app.netlify.com)
3. Drag `dist` folder to deploy area

### AWS S3 + CloudFront

```bash
# Build
npm run build

# Create S3 bucket
aws s3 mb s3://sonia-ai-companion

# Upload
aws s3 sync dist/ s3://sonia-ai-companion

# Create CloudFront distribution (via console)
# Point origin to S3 bucket
# Configure SSL certificate
```

---

## 🔧 Environment Configuration

### Required Variables

```bash
# .env.local
GEMINI_API_KEY=your_gemini_api_key_here
```

### Optional Variables

```bash
# Analytics
VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX

# Error Tracking
VITE_SENTRY_DSN=https://...@sentry.io/...

# Environment
VITE_APP_ENV=production
```

### Platform-Specific

#### Vercel
Set via CLI or dashboard:
```bash
vercel env add GEMINI_API_KEY production
```

#### Netlify
Set via CLI or dashboard:
```bash
netlify env:set GEMINI_API_KEY your_key
```

#### Docker
Pass as build args:
```bash
docker build \
  --build-arg GEMINI_API_KEY="your_key" \
  -t sonia-ai-companion .
```

#### Kubernetes
Update `k8s/secrets.yaml`:
```yaml
stringData:
  gemini-api-key: "your_actual_key_here"
```

---

## 📊 Monitoring & Observability

### Health Checks

```bash
# Quick health check
curl -I https://your-app.com

# Comprehensive check
./scripts/health-check.sh https://your-app.com
```

### Continuous Monitoring

```bash
# Monitor for 5 minutes
./scripts/monitor.sh https://your-app.com 300

# Run in background
nohup ./scripts/monitor.sh https://your-app.com 3600 > monitor.log 2>&1 &
```

### Kubernetes Monitoring

```bash
# Pod status
kubectl get pods -w

# Resource usage
kubectl top pods

# Logs
kubectl logs -f deployment/sonia-ai-deployment

# Events
kubectl get events --sort-by=.metadata.creationTimestamp
```

### Docker Monitoring

```bash
# Container stats
docker stats sonia-ai-companion

# Logs
docker logs -f sonia-ai-companion --tail 100

# Inspect
docker inspect sonia-ai-companion
```

---

## 🧪 Testing

### Pre-Deployment Testing

```bash
# Run all pre-flight checks
./scripts/deploy.sh
# Select option 7

# Manual checks
npm run build          # Test build
npm run preview        # Test production build locally
```

### Load Testing

```bash
# Light load
./scripts/load-test.sh http://localhost 10 100

# Medium load
./scripts/load-test.sh http://localhost 50 500

# Heavy load (be careful!)
./scripts/load-test.sh http://localhost 100 1000
```

### Browser Testing

```bash
# Start local server
npm run preview

# Test in browsers:
# - Chrome
# - Firefox
# - Safari
# - Edge
```

---

## 🔄 CI/CD Automation

### GitHub Actions

Already configured in `.github/workflows/`:

- **ci-cd.yml**: Automated testing and deployment
- **dependency-updates.yml**: Automated dependency updates

#### Secrets to Configure

In GitHub Settings > Secrets:

```
GEMINI_API_KEY
VERCEL_TOKEN (or NETLIFY_AUTH_TOKEN)
VERCEL_ORG_ID
VERCEL_PROJECT_ID
```

### Manual Trigger

```bash
# Push to main branch
git push origin main

# Or create a tag
git tag -a v1.0.1 -m "Release 1.0.1"
git push origin v1.0.1
```

---

## 🚨 Troubleshooting

### Build Fails

```bash
# Clear cache
rm -rf node_modules dist .vite
npm install
npm run build
```

### Docker Build Fails

```bash
# Check Docker daemon
docker ps

# View build logs
docker build --progress=plain -t sonia-ai-companion .

# Check disk space
df -h
```

### Kubernetes Deployment Issues

```bash
# Check pod status
kubectl describe pod <pod-name>

# Check logs
kubectl logs <pod-name>

# Check events
kubectl get events

# Restart deployment
kubectl rollout restart deployment/sonia-ai-deployment
```

### Health Check Fails

```bash
# Check server is running
curl -I http://localhost

# Check Docker container
docker ps
docker logs sonia-ai-companion

# Check Kubernetes pod
kubectl get pods
kubectl logs deployment/sonia-ai-deployment
```

---

## 📦 Backup & Disaster Recovery

### Automated Backups

```bash
# Create backup
./scripts/backup.sh

# Schedule daily backups (cron)
crontab -e
# Add: 0 2 * * * /path/to/scripts/backup.sh
```

### Restore Process

```bash
# List backups
ls -lh backups/

# Restore
./scripts/restore.sh backups/sonia-backup-TIMESTAMP.tar.gz

# Test
npm run preview
```

### Database Backups (if applicable)

```bash
# Export user data (from browser)
# Implemented in Settings > Export Data

# Backup localStorage
# Done automatically by browser
```

---

## 🔒 Security Checklist

Before deploying:

- [ ] API keys in environment variables (not code)
- [ ] .env.local in .gitignore
- [ ] HTTPS enabled
- [ ] Security headers configured
- [ ] Rate limiting active
- [ ] Input validation working
- [ ] CORS properly configured
- [ ] No secrets in logs
- [ ] Dependencies updated (npm audit)
- [ ] Firewall rules configured

---

## 📈 Performance Optimization

### Build Optimization

```bash
# Analyze bundle size
npm run build -- --mode=analyze

# Check for large dependencies
npx vite-bundle-visualizer
```

### Runtime Optimization

- Enable Gzip/Brotli compression
- Configure CDN for static assets
- Set proper cache headers
- Use HTTP/2
- Minimize API calls

### Kubernetes Optimization

```yaml
# Resource requests and limits
resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "256Mi"
    cpu: "200m"
```

---

## 🎯 Deployment Best Practices

1. **Always test locally first**
   ```bash
   npm run build && npm run preview
   ```

2. **Use staging environment**
   - Deploy to staging first
   - Test thoroughly
   - Then deploy to production

3. **Monitor after deployment**
   ```bash
   ./scripts/monitor.sh https://your-app.com 300
   ```

4. **Keep backups**
   ```bash
   ./scripts/backup.sh
   ```

5. **Document changes**
   - Update CHANGELOG.md
   - Tag releases in git

6. **Use blue-green deployment**
   - Deploy new version alongside old
   - Switch traffic when verified
   - Rollback if issues

7. **Automate everything**
   - Use CI/CD pipelines
   - Automated testing
   - Automated backups

---

## 🆘 Emergency Procedures

### Immediate Rollback

#### Docker
```bash
docker stop sonia-ai-companion
docker start sonia-ai-companion-backup
```

#### Kubernetes
```bash
kubectl rollout undo deployment/sonia-ai-deployment
```

#### Vercel/Netlify
- Go to deployments dashboard
- Publish previous deployment

### Site Down

1. Check server status
2. Check logs
3. Verify DNS
4. Check SSL certificate
5. Rollback if needed

### High Load

1. Check current load: `./scripts/monitor.sh`
2. Scale up:
   - Kubernetes: `kubectl scale deployment sonia-ai-deployment --replicas=10`
   - Add more instances on platform
3. Enable rate limiting
4. Check for DDoS attack

---

## 📞 Support

- **Documentation**: See `/docs` folder
- **Issues**: GitHub Issues
- **Scripts**: All in `/scripts` folder
- **Kubernetes**: Manifests in `/k8s` folder

---

## 🎉 Quick Reference

```bash
# Setup
./scripts/setup.sh

# Deploy (interactive)
./scripts/deploy.sh

# Deploy (CLI)
node scripts/deploy-cli.js

# Health check
./scripts/health-check.sh https://your-app.com

# Monitor
./scripts/monitor.sh https://your-app.com 60

# Load test
./scripts/load-test.sh http://localhost 10 100

# Backup
./scripts/backup.sh

# Restore
./scripts/restore.sh backups/backup-file.tar.gz
```

---

**Ready to deploy? Start with:** `./scripts/setup.sh` then `./scripts/deploy.sh` 🚀
