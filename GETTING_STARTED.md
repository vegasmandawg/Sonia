# Getting Started with Sonia AI Companion

Welcome! This guide will help you set up and run Sonia locally in just a few minutes.

## 🎯 Quick Start (5 minutes)

### Step 1: Prerequisites

Make sure you have:
- **Node.js 18+** installed ([Download here](https://nodejs.org/))
- A **Gemini API key** ([Get free key](https://makersuite.google.com/app/apikey))
- A code editor (VS Code recommended)

### Step 2: Installation

```bash
# 1. Navigate to project directory
cd sonia-ai-companion

# 2. Install dependencies
npm install

# This installs React, TypeScript, Vite, and all other dependencies
# Takes about 1-2 minutes
```

### Step 3: Configuration

```bash
# 1. Copy the example environment file
cp .env.example .env.local

# 2. Open .env.local in your editor
# 3. Add your Gemini API key:
GEMINI_API_KEY=your_actual_api_key_here
```

**How to get a Gemini API key:**
1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key and paste it in `.env.local`

### Step 4: Start Development Server

```bash
npm run dev
```

You should see:
```
VITE v6.4.1  ready in 201 ms

➜  Local:   http://localhost:3000/
➜  Network: http://[your-ip]:3000/
```

### Step 5: Open in Browser

Open [http://localhost:3000](http://localhost:3000) in your browser.

You should see the Sonia welcome screen! 🎉

---

## 🎮 Using Sonia

### First Time Setup

1. **Welcome Screen**: Click "Create Your Sonia"
2. **Age Gate**: Confirm you're 18+ (required for NSFW mode access)
3. **Customization**: Design your companion
   - Adjust appearance sliders
   - Set personality traits
   - Choose voice tone
   - Write a backstory
   - Select relationship type
4. **Generate Avatar**: Wait 10-30 seconds for AI to create her image
5. **Start Chatting**: Begin your conversation!

### Features to Try

#### 💬 Text Chat
Just type and press Enter. Sonia responds naturally using Gemini AI.

#### 🖼️ Image Generation
Ask Sonia to "send a picture" or "show me yourself"
- Example: "Send me a picture of you at the beach"
- Takes 10-20 seconds to generate

#### 🎥 Video Generation (if enabled)
Request a video (requires higher API tier)
- Example: "Send a video of you dancing"
- Takes 2-5 minutes to generate

#### 🎤 Voice Input
Click the microphone icon to speak instead of typing.
- Browser will ask for microphone permission
- Only works on HTTPS (or localhost)

#### 🔊 Voice Output
Sonia speaks her responses using text-to-speech.
- Configurable voice in Settings
- Different tones available

#### 📸 Gallery
View all generated images and videos.
- Access via bottom navigation (mobile) or settings

#### 🎭 Scenarios
Pre-built roleplay scenarios to jump-start conversations.
- Romantic dinner
- Movie night
- Adventure scenarios
- More based on NSFW mode

#### ⚙️ Settings
- Adjust appearance and personality
- Manage memory (pin/delete learned facts)
- Change voice settings
- Toggle NSFW mode
- Configure local AI models (advanced)

---

## 🛠️ Development

### Project Structure

```
sonia-ai-companion/
├── components/          # React components
│   ├── WelcomeScreen.tsx
│   ├── ChatScreen.tsx
│   ├── CustomizationScreen.tsx
│   └── ...
├── services/            # API integrations
│   ├── geminiService.ts    # Google Gemini API
│   ├── ttsService.ts       # Text-to-Speech
│   ├── whisperService.ts   # Speech-to-Text
│   └── ...
├── store/               # State management (Zustand)
│   └── useStore.ts
├── utils/               # Utilities
│   ├── logger.ts
│   ├── analytics.ts
│   ├── validation.ts
│   └── rateLimiter.ts
├── hooks/               # Custom React hooks
│   └── useToast.ts
├── docs/                # Documentation
├── .env.example         # Environment template
├── .env.local          # Your secrets (git-ignored)
├── vite.config.ts      # Build configuration
└── package.json        # Dependencies
```

### Available Scripts

```bash
# Development server with hot reload
npm run dev

# Build for production
npm run build

# Preview production build locally
npm run preview

# Type checking (without emitting files)
npx tsc --noEmit

# Check for vulnerabilities
npm audit
```

### Making Changes

1. **Edit a component**: Changes auto-reload in browser
2. **Add a new component**: Import and use in existing components
3. **Modify state**: Edit `/store/useStore.ts`
4. **Add API calls**: Extend `/services/geminiService.ts`
5. **Style changes**: Use Tailwind classes directly

### Key Files to Understand

- **`App.tsx`**: Main application logic and routing
- **`store/useStore.ts`**: Application state (messages, config, etc.)
- **`services/geminiService.ts`**: All AI interactions
- **`constants.tsx`**: Default configuration and icons
- **`types.ts`**: TypeScript type definitions

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `GEMINI_API_KEY` | ✅ Yes | Your Google Gemini API key | - |
| `VITE_GA_MEASUREMENT_ID` | ❌ Optional | Google Analytics 4 ID | - |
| `VITE_SENTRY_DSN` | ❌ Optional | Sentry error tracking DSN | - |
| `VITE_APP_ENV` | ❌ Optional | Environment name | `development` |

### Customizing Sonia

#### Default Configuration (`constants.tsx`)

You can change Sonia's defaults:

```typescript
export const DEFAULT_SONIA_CONFIG: SoniaConfig = {
  appearance: {
    faceStyle: 'Realistic',  // or 'Anime', 'Stylized'
    hairColor: '#33a532',    // Any hex color
    bodyType: 'Slim',        // 'Athletic', 'Curvy', 'Slim'
    attire: 'Lingerie',      // 'Casual', 'Formal', 'Fantasy'
    // ... more options
  },
  personality: {
    flirty: 70,     // 0-100
    sweet: 50,
    intelligent: 80,
    // ... more traits
  },
  nsfwMode: false,   // Start with SFW mode
  // ... more config
};
```

#### Rate Limits (`utils/rateLimiter.ts`)

Adjust API call limits:

```typescript
rateLimiter.configure('text-generation', { 
  maxRequests: 30,   // Requests
  windowMs: 60000    // Per minute
});
```

---

## 🧪 Testing Locally

### Manual Testing

1. **Test each screen**:
   - Welcome → Age Gate → Customization → Chat
   
2. **Test features**:
   - Send text messages
   - Generate images
   - Try voice input
   - Check settings modal
   - Navigate to gallery/scenarios

3. **Test error handling**:
   - Disconnect internet (should show error)
   - Send rapid messages (should hit rate limit)
   - Try invalid inputs

4. **Test mobile**:
   - Open on phone's browser
   - Check touch interactions
   - Verify bottom navigation works

### Production Build Test

Always test the production build before deploying:

```bash
# Build
npm run build

# Preview
npm run preview

# Open http://localhost:4173 (or shown port)
# Test all features in production mode
```

---

## 🐛 Troubleshooting

### API Key Not Working

**Error**: "API key is not configured"

**Solutions**:
1. Check `.env.local` exists in project root
2. Verify `GEMINI_API_KEY=your_key` (no spaces)
3. Restart dev server (`Ctrl+C` then `npm run dev`)
4. Make sure key is valid (test in [AI Studio](https://makersuite.google.com))

### Port Already in Use

**Error**: "Port 3000 is in use"

**Solutions**:
```bash
# Option 1: Kill process on port 3000
# On macOS/Linux:
lsof -ti:3000 | xargs kill

# On Windows:
netstat -ano | findstr :3000
taskkill /PID <PID> /F

# Option 2: Use different port
# Vite automatically tries next port (3001, 3002, etc.)
```

### Build Fails

**Error**: Various TypeScript or build errors

**Solutions**:
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install

# Clear Vite cache
rm -rf .vite

# Try build again
npm run build
```

### Microphone Not Working

**Error**: "Microphone access denied"

**Solutions**:
1. Click 🔒 icon in address bar
2. Allow microphone access
3. Refresh page
4. Note: Requires HTTPS (or localhost)

### Images Not Generating

**Error**: "Image generation failed"

**Possible causes**:
1. **Safety filters**: Prompt was blocked
   - Try different wording
   - Avoid explicit requests if NSFW mode is off
2. **API quota exceeded**: Check Google Cloud Console
3. **Rate limit hit**: Wait 60 seconds

### CORS Errors with Local AI

**Error**: "Connection to local AI server failed"

**Solutions**:
1. Enable CORS on your local AI server
2. Check firewall isn't blocking connection
3. Verify endpoint URL is correct
4. See [Local AI Setup Guide](./docs/LOCAL_AI_SETUP.md)

---

## 💰 Cost Estimation

### Gemini API Pricing (as of 2025)

| Service | Price | Typical Usage |
|---------|-------|---------------|
| **Gemini 2.5 Flash (text)** | $0.15 per 1M input tokens | ~1000 messages = $0.05 |
| **Imagen 4.0 (image)** | $0.02 per image | 50 images = $1.00 |
| **Veo 2.0 (video)** | $0.01 per second | 5min video = $3.00 |

**Monthly estimates** (moderate use):
- Text only: $1-5/month
- With images: $5-15/month  
- With videos: $20-50/month

**Free tier**: Google provides monthly credits for new users.

### Cost Optimization Tips

1. **Use rate limiting** (already implemented)
2. **Start with low limits** and increase as needed
3. **Monitor usage** in Google Cloud Console
4. **Set billing alerts** to avoid surprises
5. **Use local models** for privacy and cost savings (advanced)

---

## 📚 Learning Resources

### React & TypeScript
- [React Docs](https://react.dev/) - Official React documentation
- [TypeScript Handbook](https://www.typescriptlang.org/docs/) - Learn TypeScript
- [Zustand Guide](https://github.com/pmndrs/zustand) - State management

### Gemini API
- [Gemini API Docs](https://ai.google.dev/docs) - Official API docs
- [AI Studio](https://makersuite.google.com) - Test prompts online
- [Gemini Cookbook](https://github.com/google-gemini/cookbook) - Examples

### Vite & Build Tools
- [Vite Guide](https://vitejs.dev/guide/) - Modern build tool
- [Vite Config](https://vitejs.dev/config/) - Configuration reference

---

## 🤝 Getting Help

### Community
- **GitHub Issues**: Report bugs and request features
- **GitHub Discussions**: Ask questions and share ideas
- **Discord** (if available): Real-time chat with community

### Professional Support
- **Email**: support@sonia-ai.example.com
- **Documentation**: Check `/docs` folder
- **FAQ**: See [Troubleshooting](#troubleshooting) section

---

## 🎓 Next Steps

Now that you have Sonia running:

1. **Explore the app**: Try all features
2. **Read the code**: Understand how it works
3. **Make modifications**: Customize to your needs
4. **Deploy to production**: See [DEPLOYMENT.md](./docs/DEPLOYMENT.md)
5. **Contribute**: See [CONTRIBUTING.md](./CONTRIBUTING.md)

### Recommended Reading Order

1. ✅ **You are here**: GETTING_STARTED.md
2. 📖 [README.md](./README.md) - Project overview
3. 🚀 [DEPLOYMENT.md](./docs/DEPLOYMENT.md) - Deploy to production
4. 🔒 [SECURITY.md](./docs/SECURITY.md) - Security best practices
5. ✅ [PRODUCTION_CHECKLIST.md](./PRODUCTION_CHECKLIST.md) - Pre-launch checklist

---

## ❓ FAQ

### Is this free to use?
The code is free (MIT license), but Google Gemini API has costs. Google provides free credits for new users.

### Can I use other AI models?
Yes! Sonia supports local AI models (Ollama, LocalAI, etc.) via Settings > Model configuration.

### Is my data private?
All data stays in your browser's LocalStorage. No server storage. However, prompts are sent to Google Gemini.

### Can I deploy this commercially?
Yes, under MIT license. Be aware of Google's API terms of service.

### Does this work offline?
No, it requires internet for AI features. However, the UI works offline after first load (PWA).

### Can I customize Sonia's personality?
Yes! Both in the initial customization screen and in Settings. Changes take effect immediately.

### How do I update Sonia?
```bash
git pull origin main
npm install
npm run build
```

### Can I contribute?
Absolutely! See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

---

**Enjoy building with Sonia! 💜**

If you create something awesome, share it with the community!
