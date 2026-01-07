# Contributing to Sonia AI Companion

Thank you for your interest in contributing to Sonia! This document provides guidelines for contributing to the project.

## Code of Conduct

By participating in this project, you agree to:

- Be respectful and inclusive
- Welcome newcomers and encourage diverse perspectives
- Focus on what is best for the community
- Show empathy towards other community members

## How to Contribute

### Reporting Bugs

1. **Check existing issues** to avoid duplicates
2. **Create a detailed report** including:
   - Clear description of the issue
   - Steps to reproduce
   - Expected vs actual behavior
   - Screenshots (if applicable)
   - Browser/OS information
   - Console errors (if any)

### Suggesting Features

1. **Check existing feature requests**
2. **Open a discussion** explaining:
   - The problem your feature solves
   - Proposed solution
   - Alternative approaches considered
   - Mockups/examples (if applicable)

### Pull Requests

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes**
   - Follow existing code style
   - Add comments for complex logic
   - Update documentation if needed
   - Add tests if applicable

4. **Test thoroughly**
   ```bash
   npm run build
   npm run preview
   ```

5. **Commit with clear messages**
   ```bash
   git commit -m "feat: add amazing feature"
   ```
   
   Use conventional commit format:
   - `feat:` New feature
   - `fix:` Bug fix
   - `docs:` Documentation changes
   - `style:` Code style changes (formatting)
   - `refactor:` Code refactoring
   - `perf:` Performance improvements
   - `test:` Adding/updating tests
   - `chore:` Maintenance tasks

6. **Push and create PR**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Describe your PR**
   - What changes were made
   - Why these changes are needed
   - Link related issues
   - Screenshots (for UI changes)

## Development Setup

1. **Clone your fork**
   ```bash
   git clone https://github.com/yourusername/sonia-ai-companion.git
   cd sonia-ai-companion
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Set up environment**
   ```bash
   cp .env.example .env.local
   # Add your GEMINI_API_KEY
   ```

4. **Start dev server**
   ```bash
   npm run dev
   ```

## Code Style Guidelines

### TypeScript

- Use TypeScript for all new code
- Define interfaces for props and state
- Avoid `any` type when possible
- Use meaningful variable names

```typescript
// Good
interface UserProfile {
  name: string;
  age: number;
}

// Avoid
const data: any = {};
```

### React Components

- Use functional components with hooks
- Keep components focused (single responsibility)
- Extract reusable logic into custom hooks
- Use proper TypeScript types

```typescript
// Good
interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

const Button: React.FC<ButtonProps> = ({ label, onClick, disabled = false }) => {
  return (
    <button onClick={onClick} disabled={disabled}>
      {label}
    </button>
  );
};
```

### CSS/Styling

- Use TailwindCSS utility classes
- Keep custom CSS minimal
- Follow mobile-first approach
- Ensure sufficient color contrast

### Accessibility

- Add ARIA labels to interactive elements
- Ensure keyboard navigation works
- Test with screen readers when possible
- Maintain proper heading hierarchy

```typescript
// Good
<button 
  onClick={handleClick}
  aria-label="Close modal"
  data-testid="close-button"
>
  <CloseIcon />
</button>
```

## Testing

Before submitting:

- [ ] Test in Chrome/Firefox/Safari
- [ ] Test on mobile device
- [ ] Verify accessibility (keyboard navigation)
- [ ] Check console for errors
- [ ] Test with API rate limits
- [ ] Verify error handling

## Documentation

Update documentation when:

- Adding new features
- Changing existing behavior
- Adding new configuration options
- Fixing significant bugs

Update:
- README.md (if user-facing changes)
- CHANGELOG.md (all changes)
- Code comments (complex logic)
- TypeScript types/interfaces

## Questions?

Feel free to:

- Open a GitHub discussion
- Join our Discord (if available)
- Email: contribute@sonia-ai.example.com

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for helping make Sonia better! 🚀
