import { useState, useCallback } from 'react';

export interface ToastType {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
}

let toastIdCounter = 0;

export const useToast = () => {
  const [toasts, setToasts] = useState<ToastType[]>([]);

  const showToast = useCallback((message: string, type: ToastType['type'] = 'info') => {
    const id = `toast-${toastIdCounter++}`;
    setToasts(prev => [...prev, { id, message, type }]);
    return id;
  }, []);

  const hideToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(toast => toast.id !== id));
  }, []);

  const showSuccess = useCallback((message: string) => showToast(message, 'success'), [showToast]);
  const showError = useCallback((message: string) => showToast(message, 'error'), [showToast]);
  const showInfo = useCallback((message: string) => showToast(message, 'info'), [showToast]);
  const showWarning = useCallback((message: string) => showToast(message, 'warning'), [showToast]);

  return {
    toasts,
    showToast,
    hideToast,
    showSuccess,
    showError,
    showInfo,
    showWarning
  };
};
