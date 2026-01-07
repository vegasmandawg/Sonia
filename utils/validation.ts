/**
 * Input validation utilities for production safety
 */

export const validateInput = {
  /**
   * Validate text input (prevent XSS, check length)
   */
  text: (input: string, maxLength: number = 10000): { valid: boolean; error?: string } => {
    if (typeof input !== 'string') {
      return { valid: false, error: 'Input must be a string' };
    }
    
    if (input.trim().length === 0) {
      return { valid: false, error: 'Input cannot be empty' };
    }
    
    if (input.length > maxLength) {
      return { valid: false, error: `Input exceeds maximum length of ${maxLength} characters` };
    }
    
    // Check for suspicious patterns
    const suspiciousPatterns = [
      /<script[^>]*>.*?<\/script>/gi,
      /javascript:/gi,
      /on\w+\s*=/gi // onclick, onerror, etc.
    ];
    
    for (const pattern of suspiciousPatterns) {
      if (pattern.test(input)) {
        return { valid: false, error: 'Input contains potentially harmful content' };
      }
    }
    
    return { valid: true };
  },

  /**
   * Validate URL
   */
  url: (url: string): { valid: boolean; error?: string } => {
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        return { valid: false, error: 'URL must use HTTP or HTTPS protocol' };
      }
      return { valid: true };
    } catch {
      return { valid: false, error: 'Invalid URL format' };
    }
  },

  /**
   * Validate API key format
   */
  apiKey: (key: string): { valid: boolean; error?: string } => {
    if (!key || typeof key !== 'string') {
      return { valid: false, error: 'API key is required' };
    }
    
    if (key.length < 20) {
      return { valid: false, error: 'API key appears to be too short' };
    }
    
    return { valid: true };
  },

  /**
   * Sanitize text for display
   */
  sanitizeText: (text: string): string => {
    return text
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;')
      .replace(/\//g, '&#x2F;');
  }
};

/**
 * File validation utilities
 */
export const validateFile = {
  image: (file: File): { valid: boolean; error?: string } => {
    const maxSize = 10 * 1024 * 1024; // 10MB
    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    
    if (!allowedTypes.includes(file.type)) {
      return { valid: false, error: 'File type not supported. Use JPEG, PNG, GIF, or WebP' };
    }
    
    if (file.size > maxSize) {
      return { valid: false, error: 'File size exceeds 10MB limit' };
    }
    
    return { valid: true };
  },

  audio: (file: File): { valid: boolean; error?: string } => {
    const maxSize = 25 * 1024 * 1024; // 25MB
    const allowedTypes = ['audio/webm', 'audio/mp3', 'audio/wav', 'audio/ogg'];
    
    if (!allowedTypes.includes(file.type)) {
      return { valid: false, error: 'Audio format not supported' };
    }
    
    if (file.size > maxSize) {
      return { valid: false, error: 'Audio file size exceeds 25MB limit' };
    }
    
    return { valid: true };
  }
};
