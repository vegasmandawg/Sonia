import React from 'react';
import LoadingSkeleton from './LoadingSkeleton';

const ChatLoadingState: React.FC = () => {
  return (
    <div className="flex flex-col h-screen w-screen bg-gray-900">
      {/* Header Skeleton */}
      <div className="flex items-center justify-between p-3 bg-gray-900/80 border-b border-white/10">
        <div className="flex items-center">
          <LoadingSkeleton variant="circular" width="2.5rem" height="2.5rem" />
          <div className="ml-3 space-y-2">
            <LoadingSkeleton width="8rem" height="1rem" />
            <LoadingSkeleton width="5rem" height="0.75rem" />
          </div>
        </div>
        <LoadingSkeleton variant="circular" width="2.5rem" height="2.5rem" />
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Avatar Panel Skeleton (Desktop) */}
        <div className="hidden md:flex flex-col items-center justify-center w-1/3 bg-surface-dark border-r border-white/10 p-4">
          <LoadingSkeleton variant="rectangular" width="100%" height="24rem" className="max-w-sm" />
        </div>

        {/* Chat Panel Skeleton */}
        <div className="flex-1 flex flex-col">
          <div className="flex-1 p-4 space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className={`flex ${i % 2 === 0 ? 'justify-end' : 'justify-start'}`}>
                <LoadingSkeleton 
                  variant="rectangular" 
                  width="60%" 
                  height="4rem" 
                  className="max-w-sm"
                />
              </div>
            ))}
          </div>
          <div className="p-4 bg-gray-900/80 border-t border-white/10">
            <LoadingSkeleton variant="rectangular" height="3rem" />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatLoadingState;
