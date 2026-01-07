<div align="center">
<img width="1200" height="475" alt="Sonia AI Companion Banner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Sonia: Your AI Companion 🌟

[![Production Ready](https://img.shields.io/badge/production-ready-brightgreen.svg)](https://github.com)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-blue.svg)](https://www.typescriptlang.org/)
[![React](https://img.shields.io/badge/React-19.2-61dafb.svg)](https://reactjs.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A professional, production-ready AI companion application featuring advanced customization, multi-modal interactions, and intelligent memory management.

## ✨ Features

### 🎨 **Deep Customization**
- **Appearance**: Face style, body type, hair, attire, and more
- **Personality**: Adjustable traits (flirty, sweet, dominant, intelligent, playful, shy)
- **Voice**: Multiple tones (Seductive, Warm, Playful, Confident) with TTS
- **Relationship**: Choose your dynamic (Girlfriend, Best Friend, Lover, Fantasy Partner)
- **Backstory**: Create unique narratives

### 💬 **Advanced AI Interactions**
- **Text Chat**: Powered by Google Gemini 2.5 Flash
- **Image Generation**: High-quality images via Imagen 4.0
- **Video Generation**: Dynamic videos using Veo 2.0
- **Voice Input**: Speech-to-text via Whisper integration
- **Text-to-Speech**: Natural voice synthesis

### 🧠 **Intelligent Memory System**
- Automatic memory extraction from conversations
- Pin important memories
- Context-aware responses based on history
- Persistent storage across sessions

### 🎭 **Immersive Features**
- **Scenarios**: Pre-built roleplay scenarios
- **Gallery**: View all generated media
- **NSFW Mode**: Toggle for mature content
- **Idle Animations**: Realistic presence indicators

### 🛡️ **Production Features**
- **Error Boundaries**: Graceful error handling
- **Rate Limiting**: Prevent API quota exhaustion
- **Analytics Ready**: Google Analytics integration
- **SEO Optimized**: Complete meta tags
- **Security Headers**: CSP, XSS protection
- **Responsive Design**: Mobile-first approach
- **Accessibility**: ARIA labels, keyboard navigation
- **PWA Ready**: Installable on devices

---

## 🚀 Quick Start

### Prerequisites
- **Node.js** 18+ ([Download](https://nodejs.org/))
- **Gemini API Key** ([Get one free](https://makersuite.google.com/app/apikey))

### Installation

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd sonia-ai-companion
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env.local
   ```
   
   Edit `.env.local` and add your API key:
   ```env
   GEMINI_API_KEY=your_actual_api_key_here
   ```

4. **Start development server**
   ```bash
   npm run dev
   ```

5. **Open your browser**
   ```
   http://localhost:3000
   ```

---

## 📦 Production Build

### Build for Production

```bash
npm run build
```

This creates an optimized production build in the `dist/` directory.

### Preview Production Build

```bash
npm run preview
```

### Test Production Build Locally

```bash
npx serve dist
```

---

## 🌐 Deployment

### Vercel (Recommended)

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new)

1. Push your code to GitHub/GitLab/Bitbucket
2. Import project in Vercel
3. Add environment variable: `GEMINI_API_KEY`
4. Deploy!

### Netlify

[![Deploy to Netlify](https://www.netlify.com/img/deploy/button.svg)](https://app.netlify.com/start)

1. Connect your repository
2. Build command: `npm run build`
3. Publish directory: `dist`
4. Add environment variable in Site Settings

### Manual Deployment

After building (`npm run build`):
- Upload `dist/` contents to your web server
- Configure environment variables on your hosting platform
- Ensure HTTPS is enabled

**Important**: Never commit `.env.local` - it contains your API keys!

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ Yes | Your Google Gemini API key |
| `VITE_GA_MEASUREMENT_ID` | ❌ Optional | Google Analytics 4 Measurement ID |
| `VITE_SENTRY_DSN` | ❌ Optional | Sentry error tracking DSN |
| `VITE_APP_ENV` | ❌ Optional | Environment (development/production) |

### Local AI Models (Advanced)

Sonia supports local AI models for complete privacy:

1. Set provider to "local" in Settings
2. Configure endpoints:
   - **Text**: OpenAI-compatible endpoint (e.g., `http://localhost:8080/v1/chat/completions`)
   - **Image**: Image generation endpoint
   - **Audio**: Whisper-compatible endpoint

**Compatible with**: Ollama, LocalAI, LM Studio, and more.

---

## 🛠️ Technology Stack

- **Frontend**: React 19.2, TypeScript 5.8
- **Build Tool**: Vite 6.2
- **State Management**: Zustand 5.0
- **AI Services**: Google Gemini API
- **Styling**: TailwindCSS
- **Voice**: Web Speech API
- **Storage**: Browser LocalStorage

---

## 📊 Performance & Best Practices

### Rate Limiting

Built-in rate limits protect your API quota:
- **Text Generation**: 30 requests/minute
- **Image Generation**: 10 requests/minute  
- **Video Generation**: 3 requests/5 minutes
- **Audio Transcription**: 20 requests/minute

### Security

- Content Security Policy (CSP) enabled
- XSS protection
- Input validation and sanitization
- Secure API key handling
- No sensitive data in localStorage

### Accessibility

- ARIA labels on interactive elements
- Keyboard navigation support
- Screen reader friendly
- Focus management
- Color contrast compliance

---

## 📱 Browser Support

- ✅ Chrome/Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Mobile browsers (iOS Safari, Chrome Mobile)

**Note**: Voice features require HTTPS (except on localhost).

---

## 🐛 Troubleshooting

### API Key Issues

**Problem**: "API key is not configured"

**Solution**: 
1. Ensure `.env.local` exists in project root
2. Verify `GEMINI_API_KEY=your_key` is set
3. Restart dev server after changing `.env.local`

### Voice Input Not Working

**Problem**: Microphone access denied

**Solution**:
1. Check browser permissions (🔒 icon in address bar)
2. Ensure using HTTPS (or localhost)
3. Grant microphone access when prompted

### CORS Errors with Local Models

**Problem**: Connection failed to local AI server

**Solution**:
1. Enable CORS on your local AI server
2. Check firewall settings
3. Verify endpoint URL is correct
4. See [Local AI Setup Guide](./docs/LOCAL_AI_SETUP.md)

### Rate Limit Exceeded

**Problem**: "Please wait X seconds before..."

**Solution**: 
- Wait for the cooldown period
- Rate limits reset automatically
- Consider upgrading your API plan for higher limits

---

## 📚 Documentation

- [API Reference](./docs/API.md)
- [Local AI Setup](./docs/LOCAL_AI_SETUP.md)
- [Deployment Guide](./docs/DEPLOYMENT.md)
- [Security Best Practices](./docs/SECURITY.md)

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Google Gemini**: For powerful AI models
- **React Team**: For the amazing framework
- **Vite**: For lightning-fast builds
- **Zustand**: For simple state management

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/your-repo/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-repo/discussions)
- **Email**: support@sonia-ai.example.com

---

<div align="center">
  <p>Made with ❤️ by the Sonia Team</p>
  <p>
    <a href="https://github.com/your-repo">GitHub</a> •
    <a href="https://sonia-ai.example.com">Website</a> •
    <a href="https://twitter.com/sonia_ai">Twitter</a>
  </p>
</div>
