# Production Deployment Checklist

Use this checklist before deploying Sonia AI Companion to production.

## Pre-Deployment

### Environment Configuration
- [ ] `.env.local` created with all required variables
- [ ] `GEMINI_API_KEY` set and tested
- [ ] Optional analytics ID configured (if using)
- [ ] `.env.local` added to `.gitignore` (already done ✅)
- [ ] No hardcoded API keys in source code

### Code Quality
- [ ] TypeScript compilation successful (`npx tsc --noEmit`)
- [ ] No console errors in development mode
- [ ] Build completes successfully (`npm run build`)
- [ ] Preview build works (`npm run preview`)
- [ ] All TODO comments resolved or documented
- [ ] Code reviewed by team member

### Testing
- [ ] Tested on Chrome (latest)
- [ ] Tested on Firefox (latest)
- [ ] Tested on Safari (latest)
- [ ] Tested on Edge (latest)
- [ ] Mobile testing (iOS Safari)
- [ ] Mobile testing (Chrome Mobile)
- [ ] Keyboard navigation works
- [ ] Screen reader compatibility tested (optional but recommended)

### Functionality Testing
- [ ] Welcome screen displays correctly
- [ ] Age gate confirmation works
- [ ] Customization screen functional
  - [ ] Appearance sliders work
  - [ ] Personality traits adjustable
  - [ ] Voice selection functional
  - [ ] Avatar generation works
- [ ] Chat functionality
  - [ ] Text messages send/receive correctly
  - [ ] Image generation works
  - [ ] Video generation works (if API allows)
  - [ ] Voice input functional (microphone)
  - [ ] Voice output works (TTS)
- [ ] Gallery displays all media
- [ ] Scenarios load and start correctly
- [ ] Settings modal
  - [ ] All settings save correctly
  - [ ] Memory management works
  - [ ] Model configuration functional
- [ ] Error handling
  - [ ] API errors show user-friendly messages
  - [ ] Rate limits enforced and displayed
  - [ ] Network errors handled gracefully
  - [ ] Error boundary catches crashes

### Security
- [ ] API keys not exposed in client bundle (verify in DevTools)
- [ ] Input validation working on all forms
- [ ] XSS protection tested
- [ ] CSP headers configured correctly
- [ ] HTTPS enabled on domain
- [ ] Security headers present (check with browser DevTools)
- [ ] No sensitive data in localStorage
- [ ] Google Cloud API restrictions configured
  - [ ] HTTP referrer restriction set
  - [ ] API access limited to necessary services

### Performance
- [ ] Initial bundle size < 500KB
- [ ] Lighthouse Performance score > 90
- [ ] Lighthouse Accessibility score > 95
- [ ] First Contentful Paint < 2s
- [ ] Time to Interactive < 4s
- [ ] Images optimized
- [ ] No memory leaks (check with DevTools Profiler)
- [ ] Smooth animations (60fps)

### SEO & Meta
- [ ] All meta tags present (title, description, OG tags)
- [ ] Favicon configured
- [ ] robots.txt created (if needed)
- [ ] sitemap.xml created (if needed)
- [ ] Social media cards display correctly
- [ ] Analytics tracking verified (if enabled)

### Documentation
- [ ] README.md updated with deployment instructions
- [ ] CHANGELOG.md updated with version info
- [ ] Environment variables documented
- [ ] API costs estimated and documented
- [ ] Troubleshooting guide reviewed

---

## Deployment

### Hosting Platform Setup

#### Vercel
- [ ] Project created in Vercel dashboard
- [ ] GitHub repository connected
- [ ] Environment variables added:
  - [ ] `GEMINI_API_KEY`
  - [ ] `VITE_GA_MEASUREMENT_ID` (optional)
  - [ ] `VITE_APP_ENV=production`
- [ ] Build settings verified (auto-detected)
- [ ] Custom domain configured (if applicable)
- [ ] SSL certificate issued automatically

#### Netlify
- [ ] Site created in Netlify
- [ ] Repository linked
- [ ] Build command: `npm run build`
- [ ] Publish directory: `dist`
- [ ] Environment variables configured
- [ ] `netlify.toml` configuration verified
- [ ] Custom domain configured (if applicable)
- [ ] SSL certificate enabled

#### Docker
- [ ] Dockerfile tested locally
- [ ] docker-compose.yml configured
- [ ] Environment variables in `.env` file
- [ ] Build successful
- [ ] Container runs correctly
- [ ] Nginx configuration tested
- [ ] Health check endpoint responds

### DNS Configuration
- [ ] Domain purchased
- [ ] DNS records configured
  - [ ] A record or CNAME to hosting provider
  - [ ] SSL verification records added
- [ ] DNS propagation verified (use `dig` or `nslookup`)
- [ ] WWW redirect configured (if needed)

### Monitoring Setup
- [ ] Google Analytics configured (if using)
  - [ ] Tracking ID verified
  - [ ] Events firing correctly
  - [ ] Real-time data visible
- [ ] Error tracking setup (Sentry, etc.)
  - [ ] DSN configured
  - [ ] Source maps uploaded (if using)
  - [ ] Test error logged successfully
- [ ] Uptime monitoring configured
  - [ ] UptimeRobot or similar service
  - [ ] Alert notifications set up

---

## Post-Deployment

### Immediate Verification (within 1 hour)
- [ ] Production URL accessible
- [ ] HTTPS working (padlock icon)
- [ ] No console errors
- [ ] All features functional
- [ ] API calls succeeding
- [ ] Analytics tracking data
- [ ] Error tracking receiving logs
- [ ] Mobile version working
- [ ] Cross-browser compatibility verified

### Performance Testing
- [ ] Run Lighthouse on production URL
  - [ ] Performance > 90
  - [ ] Accessibility > 95
  - [ ] Best Practices > 95
  - [ ] SEO > 90
- [ ] WebPageTest results acceptable
  - [ ] First Byte Time < 500ms
  - [ ] Start Render < 2s
  - [ ] Fully Loaded < 5s
- [ ] GTmetrix grade A or B
- [ ] PageSpeed Insights score > 90

### Security Scan
- [ ] SSL Labs test: A or A+ rating
- [ ] SecurityHeaders.com: A+ rating
- [ ] No mixed content warnings
- [ ] CSP violations checked in console
- [ ] API key not visible in Network tab
- [ ] No sensitive data in responses

### Monitoring (first 24 hours)
- [ ] Monitor error rates
- [ ] Check API usage and costs
- [ ] Verify analytics data accuracy
- [ ] Review user feedback (if available)
- [ ] Monitor server performance
- [ ] Check for security alerts

### Documentation Updates
- [ ] Production URL documented
- [ ] Deployment date recorded
- [ ] Known issues logged
- [ ] Monitoring dashboards linked
- [ ] Support contacts updated

---

## Ongoing Maintenance

### Weekly
- [ ] Review error logs
- [ ] Check API usage and costs
- [ ] Monitor performance metrics
- [ ] Review user feedback

### Monthly
- [ ] Update dependencies (`npm update`)
- [ ] Run security audit (`npm audit`)
- [ ] Review and optimize performance
- [ ] Backup configuration and documentation
- [ ] Check SSL certificate expiration (auto-renew should work)
- [ ] Review Google Cloud API quotas and usage

### Quarterly
- [ ] Review and rotate API keys
- [ ] Update documentation
- [ ] Performance optimization review
- [ ] Security audit
- [ ] User feedback analysis
- [ ] Feature roadmap review

---

## Emergency Procedures

### Site Down
1. Check hosting provider status page
2. Verify DNS records
3. Check SSL certificate validity
4. Review recent deployments (rollback if needed)
5. Check error logs for clues
6. Contact hosting support if needed

### API Key Compromised
1. **Immediately** revoke key in Google Cloud Console
2. Generate new key
3. Update environment variables
4. Redeploy application
5. Monitor for unauthorized usage
6. Review billing for suspicious charges
7. Document incident

### High API Costs
1. Check usage patterns in Google Cloud Console
2. Verify rate limiting is working
3. Check for abuse (bot traffic)
4. Temporarily reduce rate limits if needed
5. Review and optimize API calls
6. Consider implementing backend proxy

### Performance Issues
1. Check Lighthouse scores
2. Review bundle size
3. Check for memory leaks
4. Analyze slow API calls
5. Review image optimization
6. Consider CDN for assets

---

## Rollback Procedure

If deployment causes critical issues:

### Vercel
```bash
# List recent deployments
vercel ls

# Promote previous deployment
vercel promote [deployment-url]
```

### Netlify
- Go to Deploys tab
- Click "Publish deploy" on a previous successful deployment

### Docker
```bash
# Stop current container
docker-compose down

# Checkout previous version
git checkout [previous-commit]

# Rebuild and restart
docker-compose up -d --build
```

---

## Success Metrics

Track these metrics post-deployment:

### Technical
- Uptime: > 99.9%
- Average response time: < 200ms
- Error rate: < 0.1%
- Build success rate: 100%

### User Experience
- Page load time: < 3s
- Time to first interaction: < 2s
- Bounce rate: < 40%
- Average session duration: > 5 minutes

### Business
- API costs within budget
- User growth rate
- User retention rate
- Feature adoption rate

---

## Support Contacts

- **Hosting Issues**: [hosting-provider-support]
- **API Issues**: Google Cloud Support
- **Security Issues**: [security-team-email]
- **General Support**: [support-email]

---

## Notes

_Add deployment-specific notes here:_

- Deployment date: __________
- Deployed by: __________
- Production URL: __________
- Monitoring dashboard: __________
- Special considerations: __________

---

**Remember**: Take your time with this checklist. A thorough pre-deployment review prevents production issues. 🚀
