/**
 * Analytics utilities for tracking user interactions
 * Ready to integrate with Google Analytics, Mixpanel, etc.
 */

import { logger } from './logger';

interface AnalyticsEvent {
  category: string;
  action: string;
  label?: string;
  value?: number;
}

class Analytics {
  private isInitialized = false;
  private isDevelopment = import.meta.env.DEV;

  /**
   * Initialize analytics (call this in App.tsx)
   */
  init() {
    if (this.isInitialized) return;

    const gaId = import.meta.env.VITE_GA_MEASUREMENT_ID;
    
    if (gaId && typeof window !== 'undefined') {
      // Load Google Analytics
      const script = document.createElement('script');
      script.async = true;
      script.src = `https://www.googletagmanager.com/gtag/js?id=${gaId}`;
      document.head.appendChild(script);

      (window as any).dataLayer = (window as any).dataLayer || [];
      function gtag(...args: any[]) {
        (window as any).dataLayer.push(args);
      }
      (window as any).gtag = gtag;
      gtag('js', new Date());
      gtag('config', gaId);

      this.isInitialized = true;
      logger.info('Analytics initialized', { gaId });
    }
  }

  /**
   * Track a page view
   */
  trackPageView(pageName: string) {
    if (this.isDevelopment) {
      logger.debug('Page view', { pageName });
      return;
    }

    if (typeof window !== 'undefined' && (window as any).gtag) {
      (window as any).gtag('event', 'page_view', {
        page_title: pageName,
        page_location: window.location.href,
        page_path: window.location.pathname
      });
    }
  }

  /**
   * Track a custom event
   */
  trackEvent({ category, action, label, value }: AnalyticsEvent) {
    if (this.isDevelopment) {
      logger.debug('Event tracked', { category, action, label, value });
      return;
    }

    if (typeof window !== 'undefined' && (window as any).gtag) {
      (window as any).gtag('event', action, {
        event_category: category,
        event_label: label,
        value: value
      });
    }
  }

  /**
   * Track feature usage
   */
  trackFeature(featureName: string, metadata?: Record<string, any>) {
    this.trackEvent({
      category: 'Feature',
      action: 'Used',
      label: featureName
    });
    logger.trackEvent(`feature_${featureName}`, metadata);
  }

  /**
   * Track errors
   */
  trackError(errorMessage: string, errorType: string = 'Unknown') {
    this.trackEvent({
      category: 'Error',
      action: errorType,
      label: errorMessage
    });
  }
}

export const analytics = new Analytics();
