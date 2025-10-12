import React from 'react';
import type { UserMemory } from '../types';
import { ICONS } from '../constants';

interface MemoryManagerProps {
  memory: UserMemory;
  onPin: (key: string) => void;
  onDelete: (key: string) => void;
}

const MemoryManager: React.FC<MemoryManagerProps> = ({ memory, onPin, onDelete }) => {
  const memoryEntries = Object.entries(memory);

  const formatValue = (value: any): string => {
    if (Array.isArray(value)) {
      return value.join(', ');
    }
    return String(value);
  };

  const handleDelete = (key: string) => {
    if (window.confirm(`Are you sure you want Sonia to forget about "${key}"? This action cannot be undone.`)) {
      onDelete(key);
    }
  };

  return (
    <div className="bg-gray-700/50 rounded-lg p-4">
      {memoryEntries.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-4">Sonia hasn't learned anything about you yet. Just keep chatting!</p>
      ) : (
        <div className="max-h-64 overflow-y-auto custom-scrollbar -mr-2 pr-2 space-y-3">
          {memoryEntries
            .sort(([, a], [, b]) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || b.timestamp - a.timestamp)
            .map(([key, item]) => (
            <div key={key} className="bg-gray-800/70 p-3 rounded-lg flex items-start justify-between">
              <div className="flex-1">
                <p className="font-semibold text-violet-300 capitalize">{key}</p>
                <p className="text-sm text-gray-200 break-words pr-2">{formatValue(item.value)}</p>
                <p className="text-xs text-gray-500 mt-1">Learned: {new Date(item.timestamp).toLocaleString()}</p>
              </div>
              <div className="flex items-center space-x-2">
                <button 
                  onClick={() => onPin(key)}
                  className={`p-2 rounded-full transition-colors focus:outline-none ${item.pinned ? 'text-fuchsia-400 bg-fuchsia-900/50 hover:bg-fuchsia-900' : 'text-gray-400 hover:bg-gray-700'}`}
                  aria-label={item.pinned ? 'Unpin memory' : 'Pin memory'}
                >
                  {item.pinned ? ICONS.pin : ICONS.pin_outline}
                </button>
                <button 
                  onClick={() => handleDelete(key)} 
                  className="p-2 rounded-full text-gray-400 hover:bg-red-900/50 hover:text-red-400 transition-colors focus:outline-none"
                  aria-label="Delete memory"
                >
                  {ICONS.trash}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MemoryManager;