/**
 * Rate limiting utility for API calls
 * Prevents excessive API usage and potential quota exhaustion
 */

interface RateLimitConfig {
  maxRequests: number;
  windowMs: number;
}

interface RateLimitRecord {
  count: number;
  resetTime: number;
}

class RateLimiter {
  private limits: Map<string, RateLimitRecord> = new Map();
  private configs: Map<string, RateLimitConfig> = new Map();

  /**
   * Configure rate limit for a specific key
   */
  configure(key: string, config: RateLimitConfig) {
    this.configs.set(key, config);
  }

  /**
   * Check if an action is allowed under rate limit
   */
  checkLimit(key: string): { allowed: boolean; retryAfter?: number } {
    const config = this.configs.get(key);
    if (!config) {
      // No limit configured, allow
      return { allowed: true };
    }

    const now = Date.now();
    const record = this.limits.get(key);

    // No record or window expired, allow and create new record
    if (!record || now >= record.resetTime) {
      this.limits.set(key, {
        count: 1,
        resetTime: now + config.windowMs
      });
      return { allowed: true };
    }

    // Within window, check count
    if (record.count < config.maxRequests) {
      record.count++;
      return { allowed: true };
    }

    // Rate limit exceeded
    const retryAfter = Math.ceil((record.resetTime - now) / 1000);
    return { allowed: false, retryAfter };
  }

  /**
   * Manually reset a rate limit
   */
  reset(key: string) {
    this.limits.delete(key);
  }

  /**
   * Get current usage for a key
   */
  getUsage(key: string): { count: number; limit: number; resetTime: number } | null {
    const config = this.configs.get(key);
    const record = this.limits.get(key);
    
    if (!config) return null;
    
    if (!record || Date.now() >= record.resetTime) {
      return { count: 0, limit: config.maxRequests, resetTime: Date.now() + config.windowMs };
    }
    
    return { count: record.count, limit: config.maxRequests, resetTime: record.resetTime };
  }
}

// Create singleton instance
export const rateLimiter = new RateLimiter();

// Configure default rate limits
rateLimiter.configure('text-generation', { maxRequests: 30, windowMs: 60000 }); // 30 per minute
rateLimiter.configure('image-generation', { maxRequests: 10, windowMs: 60000 }); // 10 per minute
rateLimiter.configure('video-generation', { maxRequests: 3, windowMs: 300000 }); // 3 per 5 minutes
rateLimiter.configure('audio-transcription', { maxRequests: 20, windowMs: 60000 }); // 20 per minute
