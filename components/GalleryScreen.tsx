
import React from 'react';
import type { ChatMessage } from '../types';
import { ICONS } from '../constants';

interface GalleryScreenProps {
  messages: ChatMessage[];
  onBack: () => void;
}

const GalleryScreen: React.FC<GalleryScreenProps> = ({ messages, onBack }) => {
  const mediaMessages = messages.filter(
    (msg) => msg.type === 'image' || msg.type === 'video'
  ).reverse(); // Show newest first

  return (
    <div className="flex flex-col h-screen w-screen bg-gray-900 text-white">
      {/* Top Bar */}
      <div className="flex items-center p-3 bg-gray-900/80 backdrop-blur-sm border-b border-white/10 sticky top-0 z-10">
        <button onClick={onBack} className="p-2 text-gray-400 hover:text-white transition-colors mr-2">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
        </button>
        <h1 className="font-bold text-lg">Gallery</h1>
      </div>

      {/* Media Grid */}
      <div className="flex-1 p-4 overflow-y-auto custom-scrollbar">
        {mediaMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="text-violet-400 mb-4">{ICONS.gallery}</div>
            <h2 className="text-xl font-semibold">Your Gallery is Empty</h2>
            <p className="text-gray-400 mt-2">
              Ask Sonia to "send a picture" or "send a video" in the chat to save memories here.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {mediaMessages.map((msg) => (
              <div
                key={msg.id}
                className="aspect-square bg-gray-800 rounded-lg overflow-hidden group relative cursor-pointer shadow-lg"
                onClick={() => window.open(msg.content, '_blank')}
              >
                {msg.type === 'image' ? (
                  <img src={msg.content} alt="Gallery item" className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105" />
                ) : (
                  <>
                    <video src={msg.content} className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105" />
                    <div className="absolute inset-0 bg-black/30 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                      <div className="p-3 bg-white/20 rounded-full backdrop-blur-sm">
                         {ICONS.play}
                      </div>
                    </div>
                  </>
                )}
                 <div className="absolute bottom-0 left-0 w-full p-2 bg-gradient-to-t from-black/80 to-transparent">
                    <p className="text-xs text-white truncate">{new Date(msg.timestamp).toLocaleString()}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default GalleryScreen;
