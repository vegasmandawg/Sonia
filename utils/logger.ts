/**
 * Logger utility for production-ready logging
 * Integrates with error tracking services (Sentry, etc.)
 */

type LogLevel = 'info' | 'warn' | 'error' | 'debug';

interface LogContext {
  [key: string]: any;
}

class Logger {
  private isDevelopment = import.meta.env.DEV;
  private appEnv = import.meta.env.VITE_APP_ENV || 'development';

  private formatMessage(level: LogLevel, message: string, context?: LogContext): string {
    const timestamp = new Date().toISOString();
    const contextStr = context ? ` | Context: ${JSON.stringify(context)}` : '';
    return `[${timestamp}] [${level.toUpperCase()}] ${message}${contextStr}`;
  }

  info(message: string, context?: LogContext) {
    if (this.isDevelopment) {
      console.log(this.formatMessage('info', message, context));
    }
    // In production, send to analytics service
  }

  warn(message: string, context?: LogContext) {
    console.warn(this.formatMessage('warn', message, context));
    // Send to monitoring service
  }

  error(message: string, error?: Error, context?: LogContext) {
    const errorContext = {
      ...context,
      errorMessage: error?.message,
      errorStack: error?.stack
    };
    console.error(this.formatMessage('error', message, errorContext));
    
    // In production, send to error tracking service (e.g., Sentry)
    if (!this.isDevelopment && typeof window !== 'undefined') {
      // Example: Sentry.captureException(error, { extra: context });
    }
  }

  debug(message: string, context?: LogContext) {
    if (this.isDevelopment) {
      console.debug(this.formatMessage('debug', message, context));
    }
  }

  // Track user events (for analytics)
  trackEvent(eventName: string, properties?: Record<string, any>) {
    if (this.isDevelopment) {
      console.log(`[ANALYTICS] Event: ${eventName}`, properties);
    } else {
      // Send to analytics service (Google Analytics, Mixpanel, etc.)
      if (typeof window !== 'undefined' && (window as any).gtag) {
        (window as any).gtag('event', eventName, properties);
      }
    }
  }
}

export const logger = new Logger();
