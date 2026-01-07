import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({
      error,
      errorInfo
    });
    
    // Here you can log to an error reporting service
    // e.g., Sentry.captureException(error);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex flex-col items-center justify-center h-screen w-screen bg-gray-900 text-white p-4">
          <div className="max-w-md w-full bg-gray-800 rounded-2xl p-6 shadow-2xl border border-red-500/20">
            <div className="flex items-center mb-4">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-10 w-10 text-red-500 mr-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <h1 className="text-2xl font-bold text-red-400">Oops! Something went wrong</h1>
            </div>
            
            <p className="text-gray-300 mb-4">
              Sonia encountered an unexpected error. Don't worry, your data is safe.
            </p>
            
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <details className="mb-4 bg-gray-900 rounded-lg p-3 text-sm">
                <summary className="cursor-pointer text-red-400 font-semibold">Error Details</summary>
                <pre className="mt-2 text-xs text-gray-400 overflow-auto">
                  {this.state.error.toString()}
                  {this.state.errorInfo && this.state.errorInfo.componentStack}
                </pre>
              </details>
            )}
            
            <button
              onClick={this.handleReset}
              className="w-full bg-fuchsia-500 hover:bg-fuchsia-600 text-white font-bold py-3 px-6 rounded-lg transition-colors"
            >
              Reload Application
            </button>
            
            <p className="text-gray-500 text-xs mt-4 text-center">
              If this problem persists, please clear your browser cache and try again.
            </p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
