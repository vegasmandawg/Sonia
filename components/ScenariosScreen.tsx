import React from 'react';
import { ICONS } from '../constants';

interface Scenario {
  title: string;
  description: string;
  prompt: string;
  icon: React.ReactNode;
  isExplicit?: boolean;
}

const SCENARIOS_LIST: Scenario[] = [
  {
    title: 'Romantic Dinner Date',
    description: 'Enjoy an intimate, candlelit dinner at a fancy restaurant.',
    prompt: "I'm so glad you could make it tonight. The table is ready, right this way... You look absolutely stunning.",
    icon: <span className="text-3xl">🍷</span>,
  },
  {
    title: 'Cozy Night In',
    description: 'Cuddle up on the couch for a movie marathon with snacks.',
    prompt: "I've got the blankets, the popcorn is ready, and I've picked out a movie I think you'll love. Come sit next to me.",
    icon: <span className="text-3xl">🍿</span>,
  },
  {
    title: 'Adventurous Getaway',
    description: 'Explore ancient ruins in a lush jungle, searching for treasure.',
    prompt: "Look at this map! The locals say the lost temple is just beyond this waterfall. Are you ready for an adventure?",
    icon: <span className="text-3xl">🗺️</span>,
  },
  {
    title: 'Fantasy Roleplay',
    description: 'A loyal knight must protect their enchanting queen from danger.',
    prompt: "My brave knight, you've returned. There are whispers of a dragon in the northern mountains. I need your strength and counsel.",
    icon: <span className="text-3xl">👑</span>,
  },
  {
    title: 'Private Session',
    description: 'An intimate and passionate encounter, just the two of you.',
    prompt: "I've been waiting for you all day... I can't wait to have you all to myself. Come here...",
    icon: <span className="text-3xl">💋</span>,
    isExplicit: true,
  },
  {
    title: 'Late Night Desire',
    description: 'The passion intensifies in the quiet hours of the night.',
    prompt: "*appears wearing only lingerie* I couldn't sleep... I kept thinking about you. About us. I need you right now.",
    icon: <span className="text-3xl">🌙</span>,
    isExplicit: true,
  },
  {
    title: 'Steamy Shower',
    description: 'Join her for an intimate moment in the warm cascading water.',
    prompt: "*water running down my body* The shower's big enough for two... Want to join me? I could use some company.",
    icon: <span className="text-3xl">💦</span>,
    isExplicit: true,
  },
  {
    title: 'Morning Temptation',
    description: 'Wake up next to her with mischievous intentions.',
    prompt: "*stretches beside you in bed, wearing almost nothing* Good morning, sleepyhead... I have some ideas about how we could start this day...",
    icon: <span className="text-3xl">🌅</span>,
    isExplicit: true,
  },
  {
    title: 'Seductive Dance',
    description: 'She performs a private, sensual dance just for you.',
    prompt: "*dims the lights and starts moving slowly to music* Sit back and relax... I want to show you something special. Just keep your eyes on me.",
    icon: <span className="text-3xl">💃</span>,
    isExplicit: true,
  },
  {
    title: 'Forbidden Office',
    description: 'A risky encounter at work after everyone else has left.',
    prompt: "*locks the office door* Everyone's gone home... We're completely alone. I've been thinking about this all day.",
    icon: <span className="text-3xl">🏢</span>,
    isExplicit: true,
  },
  {
    title: 'Pool Party',
    description: 'A wet and wild time by the pool on a hot summer day.',
    prompt: "*emerges from the pool in a revealing bikini* The water feels amazing... But I think we could have even more fun. Want to help me with my sunscreen?",
    icon: <span className="text-3xl">🏊</span>,
    isExplicit: true,
  },
  {
    title: 'Massage Session',
    description: 'A relaxing massage that turns increasingly intimate.',
    prompt: "*prepares massage oils* Lie down, I'll take care of you... Let me help you release all that tension. Every. Single. Bit.",
    icon: <span className="text-3xl">💆</span>,
    isExplicit: true,
  },
  {
    title: 'Dominant Play',
    description: 'She takes full control and shows her commanding side.',
    prompt: "*crosses arms and gives you a commanding look* On your knees. Tonight, you're going to do exactly as I say. Understand?",
    icon: <span className="text-3xl">⛓️</span>,
    isExplicit: true,
  },
  {
    title: 'Submissive Desire',
    description: 'She surrenders herself completely to your desires.',
    prompt: "*kneels before you, looking up with desire* I'm all yours... Use me however you want. I'll do anything to please you.",
    icon: <span className="text-3xl">🎀</span>,
    isExplicit: true,
  },
];

interface ScenariosScreenProps {
  onBack: () => void;
  onSelectScenario: (scenario: { title: string; prompt:string }) => void;
  nsfwMode: boolean;
}

const ScenariosScreen: React.FC<ScenariosScreenProps> = ({ onBack, onSelectScenario, nsfwMode }) => {
  const availableScenarios = nsfwMode
    ? SCENARIOS_LIST
    : SCENARIOS_LIST.filter(s => !s.isExplicit);

  return (
    <div className="flex flex-col h-screen w-screen bg-gray-900 text-white">
      {/* Top Bar */}
      <div className="flex items-center p-3 bg-gray-900/80 backdrop-blur-sm border-b border-white/10 sticky top-0 z-10">
        <button onClick={onBack} className="p-2 text-gray-400 hover:text-white transition-colors mr-2">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
        </button>
        <h1 className="font-bold text-lg">Choose a Scenario</h1>
      </div>

      {/* Scenarios List */}
      <div className="flex-1 p-4 overflow-y-auto custom-scrollbar">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-4xl mx-auto">
          {availableScenarios.map(scenario => (
            <button
              key={scenario.title}
              onClick={() => onSelectScenario(scenario)}
              className="bg-gray-800/80 border border-white/10 rounded-2xl p-6 text-left hover:bg-violet-900/40 hover:border-fuchsia-500/50 transition-all duration-300 transform hover:-translate-y-1"
            >
              <div className="flex items-start space-x-4">
                <div className="text-4xl mt-1">{scenario.icon}</div>
                <div>
                    <h3 className="text-lg font-bold text-violet-300">{scenario.title}</h3>
                    <p className="text-gray-400 text-sm mt-1">{scenario.description}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ScenariosScreen;
