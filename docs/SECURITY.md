# Security Best Practices - Sonia AI Companion

## 🔒 Security Overview

This document outlines security measures implemented in Sonia and best practices for maintaining a secure deployment.

---

## API Key Security

### ⚠️ Critical Rules

1. **NEVER commit API keys to version control**
   - Use `.env.local` (already in `.gitignore`)
   - Never hardcode keys in source files
   - Use environment variables exclusively

2. **Rotate API keys regularly**
   - Change keys every 90 days
   - Immediately rotate if compromised
   - Use different keys for dev/staging/production

3. **Restrict API key permissions**
   - In Google Cloud Console, restrict by:
     - HTTP referrer (your domain only)
     - API (only Gemini APIs)
     - IP address (if possible)

### How Keys Are Protected

```typescript
// ✅ CORRECT: Key injected at build time via environment
const apiKey = process.env.API_KEY;

// ❌ WRONG: Never do this!
const apiKey = "AIzaSy...actual-key...";
```

**Note**: In a static site, the compiled API key IS visible in the bundle. For maximum security, use a backend proxy (see Advanced Security).

---

## Content Security Policy (CSP)

Implemented in `index.html`:

```html
<meta http-equiv="Content-Security-Policy" content="
  default-src 'self';
  script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://aistudiocdn.com;
  style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com;
  img-src 'self' data: https: blob:;
  media-src 'self' blob: https:;
  connect-src 'self' https://generativelanguage.googleapis.com;
  font-src 'self' data:;
" />
```

### What This Does

- **Prevents XSS**: Scripts can only load from trusted sources
- **Blocks inline scripts**: Except where explicitly allowed
- **Restricts connections**: API calls only to Gemini endpoints
- **Image safety**: Only loads images from HTTPS or data URIs

### Customizing CSP

If you add new external services:

1. Add domain to appropriate directive
2. Test in development
3. Monitor browser console for CSP violations

---

## Input Validation

### Text Input Sanitization

```typescript
import { validateInput } from './utils/validation';

const result = validateInput.text(userInput, 1000);
if (!result.valid) {
  showError(result.error);
  return;
}
```

### Protections Implemented

1. **XSS Prevention**
   - Escapes HTML special characters
   - Blocks `<script>` tags
   - Filters `javascript:` URIs
   - Removes event handlers (`onclick`, etc.)

2. **Length Limits**
   - Chat messages: 1000 characters
   - Prompts: 10000 characters
   - Prevents abuse and excessive API costs

3. **Content Filtering**
   - Validates URLs before fetching
   - Checks file types before upload
   - Validates API responses

---

## Rate Limiting

### Built-in Limits

```typescript
// Automatically applied
rateLimiter.configure('text-generation', { 
  maxRequests: 30, 
  windowMs: 60000 
});
```

### Why It Matters

1. **Prevents abuse**: Limits automated attacks
2. **Protects budget**: Prevents runaway API costs
3. **Fair usage**: Ensures quality service for all users

### Customizing Limits

Edit `/app/utils/rateLimiter.ts`:

```typescript
// More restrictive
rateLimiter.configure('text-generation', { 
  maxRequests: 10,  // 10 requests
  windowMs: 60000   // per minute
});

// More permissive (be careful!)
rateLimiter.configure('text-generation', { 
  maxRequests: 100, 
  windowMs: 60000 
});
```

---

## HTTPS / SSL

### Why HTTPS Is Required

1. **Protects API keys**: Encrypted in transit
2. **Required for Web APIs**: 
   - Microphone access
   - Camera access
   - Geolocation
3. **SEO benefit**: Google ranks HTTPS sites higher
4. **User trust**: Browser shows 🔒 padlock

### Enabling HTTPS

**Development**:
```bash
# Vite with HTTPS
npm install @vitejs/plugin-basic-ssl
```

```typescript
// vite.config.ts
import basicSsl from '@vitejs/plugin-basic-ssl';

export default defineConfig({
  plugins: [react(), basicSsl()],
  server: { https: true }
});
```

**Production**: Automatic on:
- Vercel
- Netlify  
- CloudFlare
- AWS CloudFront (with ACM certificate)

---

## Data Privacy

### What's Stored Locally

```javascript
// In browser LocalStorage
{
  "sonia-ai-companion-storage": {
    "state": {
      "soniaConfig": { /* customization */ },
      "messages": [ /* chat history */ ],
      "memory": { /* learned user preferences */ }
    }
  }
}
```

### Privacy Considerations

1. **No server storage**: Everything stays in user's browser
2. **User control**: Can clear anytime via Settings
3. **No analytics by default**: Must explicitly enable
4. **No tracking**: No third-party cookies

### GDPR Compliance

If deploying in EU:

1. **Add cookie consent banner**
2. **Privacy policy**: Explain data usage
3. **Data export**: Allow users to download their data
4. **Right to deletion**: Clear localStorage + API cache

---

## Advanced Security

### Backend Proxy (Recommended for Production)

Instead of exposing API keys in frontend, use a backend:

```
User → Your Backend → Gemini API
      (no key exposed)
```

#### Simple Express Proxy

```javascript
// server.js
const express = require('express');
const { GoogleGenAI } = require('@google/genai');

const app = express();
const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

app.use(express.json());

app.post('/api/chat', async (req, res) => {
  const { message } = req.body;
  
  // Add authentication, rate limiting, logging here
  
  const response = await ai.models.generateContent({
    model: 'gemini-2.5-flash',
    contents: message
  });
  
  res.json({ response: response.text });
});

app.listen(3001);
```

#### Update Frontend

```typescript
// Instead of direct API calls
const response = await fetch('/api/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message: userInput })
});
```

### Authentication (Optional)

For multi-user deployments:

```typescript
// Add JWT authentication
import jwt from 'jsonwebtoken';

app.post('/api/login', (req, res) => {
  const { username, password } = req.body;
  // Verify credentials
  const token = jwt.sign({ username }, process.env.JWT_SECRET);
  res.json({ token });
});

app.use('/api/*', (req, res, next) => {
  const token = req.headers.authorization?.split(' ')[1];
  jwt.verify(token, process.env.JWT_SECRET);
  next();
});
```

---

## Security Headers

Implemented in `index.html`:

```html
<!-- Prevent clickjacking -->
<meta http-equiv="X-Frame-Options" content="DENY" />

<!-- Prevent MIME sniffing -->
<meta http-equiv="X-Content-Type-Options" content="nosniff" />

<!-- Control referrer info -->
<meta name="referrer" content="strict-origin-when-cross-origin" />
```

### Additional Headers (Server-Side)

If using a custom server, add:

```javascript
app.use((req, res, next) => {
  res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  next();
});
```

---

## Monitoring & Incident Response

### Error Tracking

**Sentry Integration**:

```typescript
// utils/logger.ts already has Sentry hooks
import * as Sentry from '@sentry/react';

if (process.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.VITE_SENTRY_DSN,
    environment: process.env.VITE_APP_ENV || 'production',
    tracesSampleRate: 0.1,
  });
}
```

### Security Incident Response

1. **If API key is compromised**:
   ```bash
   # Immediately rotate in Google Cloud Console
   # Update .env.local and redeploy
   # Check billing for unusual usage
   ```

2. **If vulnerability discovered**:
   - Assess severity (CVSS score)
   - Apply patch immediately for critical issues
   - Notify users if data was exposed
   - Document incident for future reference

3. **Regular security audits**:
   ```bash
   # Check for vulnerable dependencies
   npm audit
   
   # Fix automatically (review changes!)
   npm audit fix
   
   # Lighthouse security scan
   lighthouse https://your-site.com --only-categories=best-practices
   ```

---

## Security Checklist

Before deploying to production:

- [ ] API keys in environment variables only
- [ ] `.env.local` in `.gitignore`
- [ ] HTTPS enabled on domain
- [ ] CSP headers configured
- [ ] Input validation on all user inputs
- [ ] Rate limiting active
- [ ] Error tracking configured
- [ ] Security headers set
- [ ] Dependencies updated (`npm audit`)
- [ ] No console.logs with sensitive data
- [ ] API keys restricted in Google Cloud Console
- [ ] Backups configured
- [ ] Incident response plan documented

---

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Web Security Best Practices](https://developer.mozilla.org/en-US/docs/Web/Security)
- [Google Cloud Security](https://cloud.google.com/security/best-practices)
- [Gemini API Security](https://ai.google.dev/docs/oauth)

---

**Remember**: Security is an ongoing process, not a one-time task. Stay updated on best practices and regularly review your security posture.
