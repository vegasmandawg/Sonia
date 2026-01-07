# Deployment Guide - Sonia AI Companion

This guide covers deploying Sonia to production on various platforms.

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Vercel Deployment](#vercel-deployment)
3. [Netlify Deployment](#netlify-deployment)
4. [AWS S3 + CloudFront](#aws-deployment)
5. [Docker Deployment](#docker-deployment)
6. [Post-Deployment](#post-deployment)

---

## Pre-Deployment Checklist

☐ **Environment Variables Configured**
- [ ] `GEMINI_API_KEY` set in hosting platform
- [ ] Optional: `VITE_GA_MEASUREMENT_ID` for analytics
- [ ] Optional: `VITE_SENTRY_DSN` for error tracking

☐ **Code Quality**
- [ ] All console.errors resolved
- [ ] TypeScript compilation successful (`npm run build`)
- [ ] No sensitive data in code

☐ **Testing**
- [ ] Tested in production mode locally (`npm run preview`)
- [ ] Verified on multiple browsers
- [ ] Mobile responsiveness checked
- [ ] API key works correctly

☐ **Security**
- [ ] CSP headers configured
- [ ] HTTPS enabled on domain
- [ ] Rate limiting tested
- [ ] No API keys in client code

☐ **Performance**
- [ ] Build size optimized (<500KB initial)
- [ ] Images compressed
- [ ] Lazy loading implemented

---

## Vercel Deployment

### Method 1: Deploy from GitHub

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/yourusername/sonia-ai.git
   git push -u origin main
   ```

2. **Import in Vercel**
   - Go to [vercel.com](https://vercel.com)
   - Click "New Project"
   - Import your GitHub repository
   - Vercel auto-detects Vite configuration

3. **Add Environment Variable**
   - Go to Project Settings > Environment Variables
   - Add: `GEMINI_API_KEY` = `your_api_key`
   - Click "Save"

4. **Deploy**
   - Click "Deploy"
   - Wait 1-2 minutes
   - Your app is live! 🎉

### Method 2: Vercel CLI

```bash
# Install Vercel CLI
npm i -g vercel

# Login
vercel login

# Deploy
vercel

# Add environment variable
vercel env add GEMINI_API_KEY

# Deploy to production
vercel --prod
```

### Custom Domain on Vercel

1. Go to Project Settings > Domains
2. Add your domain (e.g., `sonia.yourdomain.com`)
3. Configure DNS:
   - Type: `CNAME`
   - Name: `sonia`
   - Value: `cname.vercel-dns.com`
4. Wait for SSL certificate (automatic)

---

## Netlify Deployment

### Method 1: Drag & Drop

1. **Build locally**
   ```bash
   npm run build
   ```

2. **Deploy**
   - Go to [app.netlify.com](https://app.netlify.com)
   - Drag `dist` folder to deploy zone
   - Site is live!

3. **Add Environment Variables**
   - Site Settings > Build & Deploy > Environment
   - Add: `GEMINI_API_KEY`
   - Trigger redeploy

### Method 2: GitHub Integration

1. **Connect Repository**
   - New Site from Git
   - Choose your repository
   - Build command: `npm run build`
   - Publish directory: `dist`

2. **Configure Environment**
   - Site Settings > Build & Deploy > Environment Variables
   - Add `GEMINI_API_KEY`

3. **Deploy**
   - Automatic on every push to main branch

### Custom Domain on Netlify

1. Domain Settings > Add Custom Domain
2. Add your domain
3. Configure DNS:
   - Type: `CNAME`
   - Name: `sonia`
   - Value: `your-site-name.netlify.app`
4. Enable HTTPS (automatic)

---

## AWS Deployment

### S3 + CloudFront Setup

1. **Build the app**
   ```bash
   npm run build
   ```

2. **Create S3 Bucket**
   ```bash
   aws s3 mb s3://sonia-ai-companion
   aws s3 sync dist/ s3://sonia-ai-companion
   ```

3. **Configure S3 for static hosting**
   - Enable Static Website Hosting
   - Index document: `index.html`
   - Error document: `index.html` (for SPA routing)

4. **Create CloudFront Distribution**
   - Origin: Your S3 bucket
   - Viewer Protocol Policy: Redirect HTTP to HTTPS
   - Price Class: Use Only North America and Europe (cheaper)
   - Alternate Domain Names: your-domain.com
   - SSL Certificate: Request from ACM

5. **Configure Custom Error Pages**
   - 403: Return `/index.html` with 200 status
   - 404: Return `/index.html` with 200 status

6. **Update DNS**
   - Type: `CNAME`
   - Name: `sonia`
   - Value: CloudFront distribution domain

### Environment Variables in AWS

Since this is a static site, environment variables must be set at build time:

```bash
# Build with environment variable
GEMINI_API_KEY=your_key npm run build

# Then deploy
aws s3 sync dist/ s3://sonia-ai-companion
```

**Security Note**: For production, use AWS Secrets Manager and a build pipeline.

---

## Docker Deployment

### Create Dockerfile

```dockerfile
# Build stage
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG GEMINI_API_KEY
ENV GEMINI_API_KEY=$GEMINI_API_KEY
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Create nginx.conf

```nginx
worker_processes 1;

events {
  worker_connections 1024;
}

http {
  include mime.types;
  default_type application/octet-stream;
  sendfile on;
  keepalive_timeout 65;
  gzip on;

  server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # SPA routing
    location / {
      try_files $uri $uri/ /index.html;
    }

    # Security headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
  }
}
```

### Build and Run

```bash
# Build image
docker build --build-arg GEMINI_API_KEY=your_key -t sonia-ai .

# Run container
docker run -d -p 80:80 sonia-ai

# Or with docker-compose
docker-compose up -d
```

### docker-compose.yml

```yaml
version: '3.8'
services:
  sonia:
    build:
      context: .
      args:
        GEMINI_API_KEY: ${GEMINI_API_KEY}
    ports:
      - "80:80"
    restart: unless-stopped
```

---

## Post-Deployment

### 1. Verify Deployment

✅ Check these after deploying:

```bash
# Test production URL
curl -I https://your-domain.com

# Check for proper response
curl https://your-domain.com | grep "Sonia"

# Verify HTTPS
openssl s_client -connect your-domain.com:443
```

### 2. Set Up Monitoring

**Google Analytics** (if configured):
1. Verify events are being tracked
2. Set up goals and conversions
3. Configure custom reports

**Sentry** (if configured):
1. Check error tracking is working
2. Set up alerts for critical errors
3. Configure release tracking

### 3. Performance Testing

```bash
# Lighthouse CLI
npm install -g lighthouse
lighthouse https://your-domain.com --view

# WebPageTest
# Visit https://www.webpagetest.org/
```

**Target Scores**:
- Performance: >90
- Accessibility: >95
- Best Practices: >95
- SEO: >95

### 4. Security Scan

```bash
# Check security headers
curl -I https://your-domain.com

# SSL Labs test
# Visit https://www.ssllabs.com/ssltest/
```

### 5. Set Up Backups

- **Code**: Already in Git
- **User Data**: In browser LocalStorage (consider adding export feature)
- **Configuration**: Document environment variables

---

## Continuous Deployment

### GitHub Actions (Vercel)

```yaml
# .github/workflows/deploy.yml
name: Deploy to Vercel

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-node@v2
        with:
          node-version: '18'
      - run: npm ci
      - run: npm run build
      - uses: amondnet/vercel-action@v20
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
```

### GitHub Actions (Netlify)

```yaml
# .github/workflows/deploy.yml  
name: Deploy to Netlify

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-node@v2
        with:
          node-version: '18'
      - run: npm ci
      - run: npm run build
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      - uses: netlify/actions/cli@master
        with:
          args: deploy --prod --dir=dist
        env:
          NETLIFY_SITE_ID: ${{ secrets.NETLIFY_SITE_ID }}
          NETLIFY_AUTH_TOKEN: ${{ secrets.NETLIFY_AUTH_TOKEN }}
```

---

## Troubleshooting

### Build Fails

**Error**: "Module not found"
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
npm run build
```

### Environment Variables Not Working

**Issue**: API key not loading

**Solution**:
1. Verify variable name starts with `VITE_` (except GEMINI_API_KEY)
2. Restart dev server after changing .env
3. Check hosting platform's environment variables
4. Ensure variable is set at build time, not runtime

### 404 on Page Refresh

**Issue**: SPA routing not working

**Solution**: Configure hosting for SPA:
- **Vercel**: Auto-configured
- **Netlify**: Add `_redirects` file:
  ```
  /*    /index.html   200
  ```
- **Apache**: Add `.htaccess`:
  ```apache
  RewriteEngine On
  RewriteBase /
  RewriteRule ^index\.html$ - [L]
  RewriteCond %{REQUEST_FILENAME} !-f
  RewriteCond %{REQUEST_FILENAME} !-d
  RewriteRule . /index.html [L]
  ```

---

## Cost Estimation

### Hosting Costs (Monthly)

| Platform | Free Tier | Paid Plan |
|----------|-----------|----------|
| **Vercel** | 100GB bandwidth | $20/month (Pro) |
| **Netlify** | 100GB bandwidth | $19/month (Pro) |
| **AWS S3+CF** | ~$1-5 | Scales with traffic |
| **Docker VPS** | N/A | $5-20/month |

### API Costs (Google Gemini)

- **Gemini 2.5 Flash**: $0.15 per 1M input tokens
- **Imagen 4.0**: $0.02 per image
- **Veo 2.0**: $0.01 per second of video

**Estimated**: ~$5-20/month for moderate use

---

## Support

Need help deploying? 

- Check [GitHub Issues](https://github.com/your-repo/issues)
- Join [Discord Community](https://discord.gg/your-server)
- Email: deploy@sonia-ai.example.com
