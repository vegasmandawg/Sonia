import React from 'react';

interface LoadingSkeletonProps {
  variant?: 'text' | 'circular' | 'rectangular' | 'avatar';
  width?: string;
  height?: string;
  className?: string;
}

const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({ 
  variant = 'text', 
  width = '100%', 
  height, 
  className = '' 
}) => {
  const getVariantClasses = () => {
    switch (variant) {
      case 'circular':
        return 'rounded-full';
      case 'rectangular':
        return 'rounded-lg';
      case 'avatar':
        return 'rounded-full';
      case 'text':
      default:
        return 'rounded';
    }
  };

  const defaultHeight = variant === 'text' ? '1rem' : variant === 'circular' || variant === 'avatar' ? '3rem' : '8rem';

  return (
    <div
      className={`bg-gray-700 animate-pulse ${getVariantClasses()} ${className}`}
      style={{ width, height: height || defaultHeight }}
      aria-label="Loading..."
    />
  );
};

export default LoadingSkeleton;
