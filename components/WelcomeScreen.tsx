import React from 'react';

interface WelcomeScreenProps {
  onStart: () => void;
}

const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ onStart }) => {
  return (
    <div className="flex flex-col items-center justify-center h-screen w-screen bg-gray-900 text-white p-4">
      <div className="relative w-full max-w-md h-64 md:h-80 rounded-2xl overflow-hidden mb-8 shadow-2xl shadow-fuchsia-500/10">
        <img src="https://picsum.photos/seed/sonia-welcome/600/800" alt="Glimpse of Sonia" className="w-full h-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-t from-gray-900 via-gray-900/50 to-transparent"></div>
        <div className="absolute bottom-0 left-0 p-6">
          <h1 className="text-4xl font-bold text-white drop-shadow-lg">Sonia</h1>
          <p className="text-lg text-violet-300">Your AI Companion</p>
        </div>
      </div>
      
      <div className="text-center">
        <h2 className="text-2xl font-semibold mb-2">Experience a personalized, intimate connection.</h2>
        <p className="text-gray-400 mb-8 max-w-sm">Create your ideal companion, shape her personality, and explore a relationship without limits.</p>
        <button
          onClick={onStart}
          className="w-full max-w-sm bg-fuchsia-500 hover:bg-fuchsia-600 text-white font-bold py-3 px-6 rounded-lg text-lg transition-all duration-300 transform hover:scale-105 focus:outline-none focus:ring-4 focus:ring-fuchsia-500/50"
        >
          Create Your Sonia
        </button>
        <p className="text-gray-500 text-sm mt-4 cursor-pointer hover:text-gray-400">Learn More</p>
      </div>
    </div>
  );
};

export default WelcomeScreen;