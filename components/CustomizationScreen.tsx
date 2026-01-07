import React, { useState } from 'react';
import type { SoniaConfig } from '../types';
import { generateAvatar } from '../services/geminiService';
import { ICONS } from '../constants';

interface CustomizationScreenProps {
  config: SoniaConfig;
  onComplete: (newConfig: SoniaConfig) => void;
  onOpenSettings: () => void;
}

const archetypes = [
  {
    name: 'The Sweetheart',
    description: 'A kind and playful soul who has been by your side through thick and thin.',
    config: {
      personality: { flirty: 60, sweet: 85, dominant: 10, intelligent: 60, playful: 75, shy: 40 },
      relationship: 'Girlfriend',
      backstory: "Your childhood friend who has always been by your side, sharing secrets and dreams under the stars.",
      appearance: { attire: 'Casual' },
    }
  },
  {
    name: 'The Mystic',
    description: 'An intelligent and enigmatic partner from a world of magic and wonder.',
    config: {
      personality: { flirty: 50, sweet: 30, dominant: 40, intelligent: 90, playful: 50, shy: 70 },
      relationship: 'Fantasy Partner',
      backstory: "A mysterious sorceress you rescued from an enchanted tower, whose knowledge of the arcane is matched only by her curiosity about your world.",
      appearance: { attire: 'Fantasy' },
    }
  },
  {
    name: 'The Confidante',
    description: 'A sharp, dominant, and witty professional who you can always count on.',
    config: {
      personality: { flirty: 75, sweet: 40, dominant: 80, intelligent: 85, playful: 60, shy: 15 },
      relationship: 'Lover',
      backstory: "A brilliant and sharp-witted colleague who became your closest confidante, sharing ambitious goals and intimate secrets after hours.",
      appearance: { attire: 'Formal' },
    }
  },
  {
    name: 'The Seductress',
    description: 'A passionate and uninhibited lover who knows exactly what she wants.',
    config: {
      personality: { flirty: 95, sweet: 40, dominant: 75, intelligent: 70, playful: 80, shy: 5 },
      relationship: 'Lover',
      backstory: "A captivating woman you met at an exclusive club. The chemistry was instant and electric, leading to passionate nights together.",
      appearance: { attire: 'Lingerie' },
    }
  },
  {
    name: 'The Submissive',
    description: 'A sweet, obedient companion who loves to please and serve you.',
    config: {
      personality: { flirty: 70, sweet: 90, dominant: 5, intelligent: 60, playful: 65, shy: 75 },
      relationship: 'Lover',
      backstory: "She approached you shyly at first, but quickly revealed her deep desire to submit to you completely and fulfill your every wish.",
      appearance: { attire: 'Lingerie' },
    }
  },
  {
    name: 'The Domina',
    description: 'A commanding and powerful woman who takes control completely.',
    config: {
      personality: { flirty: 80, sweet: 20, dominant: 95, intelligent: 80, playful: 70, shy: 0 },
      relationship: 'Lover',
      backstory: "A fierce and commanding woman who saw something special in you and decided you would be hers. She demands obedience and rewards devotion.",
      appearance: { attire: 'Lingerie' },
    }
  },
] as const;

const Slider: React.FC<{ label: string; value: number; onChange: (e: React.ChangeEvent<HTMLInputElement>) => void; name: string; }> = ({ label, value, onChange, name }) => (
    <div className="mb-4">
        <label className="block text-sm font-medium text-gray-300 capitalize">{label}</label>
        <div className="flex items-center space-x-4">
            <input type="range" name={name} min="0" max="100" value={value} onChange={onChange} className="w-full h-2 bg-gray-600 rounded-lg appearance-none cursor-pointer accent-fuchsia-500" />
            <span className="text-sm text-violet-300 font-mono w-8 text-center">{value}</span>
        </div>
    </div>
);

const RadioGroup: React.FC<{ label: string; name: string; options: readonly string[]; value: string; onChange: (e: React.ChangeEvent<HTMLInputElement>) => void; }> = ({ label, name, options, value, onChange }) => (
    <div className="mb-6">
        <h4 className="text-md font-semibold text-gray-300 mb-2">{label}</h4>
        <div className="flex flex-wrap gap-2">
            {options.map(option => (
                <label key={option} className="cursor-pointer">
                    <input type="radio" name={name} value={option} checked={value === option} onChange={onChange} className="sr-only peer" />
                    <div className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-700 text-gray-300 ring-2 ring-transparent transition-all peer-checked:text-violet-300 peer-checked:bg-violet-900/50 peer-checked:ring-fuchsia-500">
                        {option}
                    </div>
                </label>
            ))}
        </div>
    </div>
);


const CustomizationScreen: React.FC<CustomizationScreenProps> = ({ config, onComplete, onOpenSettings }) => {
  const [localConfig, setLocalConfig] = useState<SoniaConfig>(config);
  const [previewImageUrl, setPreviewImageUrl] = useState(`https://picsum.photos/seed/sonia-preview/600/800`);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [activeArchetype, setActiveArchetype] = useState<string | null>(null);

  const handleManualChange = <T extends (...args: any[]) => any>(handler: T) => (...args: Parameters<T>): ReturnType<T> => {
      setActiveArchetype(null);
      return handler(...args);
  };
  
  const handleAppearanceChange = handleManualChange((e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    const isRange = (e.target as HTMLInputElement).type === 'range';
    setLocalConfig(prev => ({ ...prev, appearance: { ...prev.appearance, [name]: isRange ? parseInt(value, 10) : value } }));
  });

  const handlePersonalityChange = handleManualChange((e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setLocalConfig(prev => ({ ...prev, personality: { ...prev.personality, [name]: parseInt(value, 10) } }));
  });

  const handleQuirksChange = handleManualChange((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setLocalConfig(prev => ({ ...prev, personality: { ...prev.personality, quirks: e.target.value.split('\n').filter(q => q.trim() !== '') } }));
  });

  const handleRelationshipChange = handleManualChange((e: React.ChangeEvent<HTMLInputElement>) => {
    const { value } = e.target;
    setLocalConfig(prev => ({ ...prev, relationship: value as SoniaConfig['relationship'] }));
  });

  const handleBackstoryChange = handleManualChange((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setLocalConfig(prev => ({ ...prev, backstory: e.target.value }));
  });

  const handleGeneratePreview = async () => {
    setIsPreviewLoading(true);
    setPreviewError(null);
    try {
      const imageUrl = await generateAvatar(localConfig);
      setPreviewImageUrl(imageUrl);
    } catch (error: any)
{
      console.error("Failed to generate preview:", error);
      setPreviewError(error.message || "An unknown error occurred.");
    } finally {
      setIsPreviewLoading(false);
    }
  };

  // FIX: Correctly type the archetype parameter to avoid a mismatch.
  const handleSelectArchetype = (archetype: typeof archetypes[number]) => {
    setActiveArchetype(archetype.name);
    setLocalConfig(prev => ({
      ...prev,
      personality: { ...prev.personality, ...archetype.config.personality },
      relationship: archetype.config.relationship,
      backstory: archetype.config.backstory,
      appearance: { ...prev.appearance, ...archetype.config.appearance },
    }));
  };

  return (
    <div className="flex flex-col md:flex-row h-screen w-screen bg-gray-900 text-white">
      {/* Left Panel - Customization Form */}
      <div className="w-full md:w-1/2 lg:w-2/5 p-6 overflow-y-auto custom-scrollbar">
        <div className="flex justify-between items-center mb-6">
            <div>
                <h1 className="text-2xl font-bold">Create Your Sonia</h1>
                <p className="text-gray-400">Shape her look, personality, and backstory.</p>
            </div>
            <button onClick={onOpenSettings} className="p-2 text-gray-400 hover:text-white transition-colors">{ICONS.settings}</button>
        </div>

        {/* Quick Start Archetypes */}
        <div className="mb-8 p-4 bg-gray-800/50 rounded-lg border border-white/10">
            <h3 className="text-lg font-semibold text-violet-300 mb-3">Quick Start</h3>
            <p className="text-sm text-gray-400 mb-4">Choose an archetype as a starting point, then customize her further.</p>
            <div className="space-y-3">
            {archetypes.map(archetype => (
                <button 
                    key={archetype.name} 
                    onClick={() => handleSelectArchetype(archetype)} 
                    className={`w-full text-left p-4 rounded-lg border-2 transition-all ${activeArchetype === archetype.name ? 'bg-violet-900/50 border-fuchsia-500' : 'bg-gray-700/50 border-transparent hover:border-violet-600'}`}
                >
                <h4 className="font-bold">{archetype.name}</h4>
                <p className="text-xs text-gray-400 mt-1">{archetype.description}</p>
                </button>
            ))}
            </div>
        </div>

        {/* Appearance Section */}
        <div className="mb-6">
          <h2 className="text-xl font-semibold mb-4 text-violet-300">Appearance</h2>
          <RadioGroup label="Face Style" name="faceStyle" options={['Realistic', 'Anime', 'Stylized']} value={localConfig.appearance.faceStyle} onChange={handleAppearanceChange} />
          <Slider label="Eye Size" name="eyeSize" value={localConfig.appearance.eyeSize} onChange={handleAppearanceChange} />
          <Slider label="Lip Size" name="lipSize" value={localConfig.appearance.lipSize} onChange={handleAppearanceChange} />
          <RadioGroup label="Hair Style" name="hairStyle" options={['Long & Wavy', 'Short Bob', 'Ponytail', 'Pixie Cut']} value={localConfig.appearance.hairStyle} onChange={handleAppearanceChange} />
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-300">Hair Color</label>
            <input type="color" name="hairColor" value={localConfig.appearance.hairColor} onChange={handleAppearanceChange} className="w-full h-10 p-1 bg-gray-700 border border-gray-600 rounded-lg cursor-pointer" />
          </div>
          <RadioGroup label="Body Type" name="bodyType" options={['Athletic', 'Curvy', 'Slim']} value={localConfig.appearance.bodyType} onChange={handleAppearanceChange} />
          <RadioGroup label="Attire" name="attire" options={['Casual', 'Lingerie', 'Formal', 'Fantasy']} value={localConfig.appearance.attire} onChange={handleAppearanceChange} />
        </div>

        {/* Personality Section */}
        <div className="mb-6">
          <h2 className="text-xl font-semibold mb-4 text-violet-300">Personality</h2>
          <Slider label="Flirty" name="flirty" value={localConfig.personality.flirty} onChange={handlePersonalityChange} />
          <Slider label="Sweet" name="sweet" value={localConfig.personality.sweet} onChange={handlePersonalityChange} />
          <Slider label="Dominant" name="dominant" value={localConfig.personality.dominant} onChange={handlePersonalityChange} />
          <Slider label="Intelligent" name="intelligent" value={localConfig.personality.intelligent} onChange={handlePersonalityChange} />
          <Slider label="Playful" name="playful" value={localConfig.personality.playful} onChange={handlePersonalityChange} />
          <Slider label="Shy" name="shy" value={localConfig.personality.shy} onChange={handlePersonalityChange} />
           <div className="mb-4">
            <label className="block text-sm font-medium text-gray-300">Quirks (one per line)</label>
            <textarea
              name="quirks"
              value={localConfig.personality.quirks.join('\n')}
              onChange={handleQuirksChange}
              rows={3}
              className="w-full mt-1 bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white focus:ring-fuchsia-500 focus:border-fuchsia-500"
              placeholder="e.g., bites her lip when thinking"
            />
          </div>
        </div>
        
        {/* Relationship Section */}
        <div className="mb-6">
             <h2 className="text-xl font-semibold mb-4 text-violet-300">Relationship</h2>
             <RadioGroup label="Your Relationship" name="relationship" options={['Girlfriend', 'Best Friend', 'Lover', 'Fantasy Partner']} value={localConfig.relationship} onChange={handleRelationshipChange} />
             <div className="mb-4">
                <label className="block text-sm font-medium text-gray-300">Backstory</label>
                <textarea
                    name="backstory"
                    value={localConfig.backstory}
                    onChange={handleBackstoryChange}
                    rows={4}
                    className="w-full mt-1 bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white focus:ring-fuchsia-500 focus:border-fuchsia-500"
                    placeholder="e.g., You met at a cozy coffee shop on a rainy day."
                />
            </div>
        </div>

      </div>

      {/* Right Panel - Preview */}
      <div className="w-full md:w-1/2 lg:w-3/5 p-6 flex flex-col items-center justify-center bg-gray-800/50">
        <div className="w-full max-w-sm">
          <div className="relative aspect-[3/4] bg-gray-700 rounded-2xl overflow-hidden shadow-2xl shadow-fuchsia-900/20 mb-6">
            {isPreviewLoading && (
              <div className="absolute inset-0 bg-black/50 flex flex-col items-center justify-center z-10">
                <div className="w-12 h-12 border-4 border-t-transparent border-fuchsia-500 rounded-full animate-spin"></div>
                <p className="mt-4 text-white">Generating your Sonia...</p>
              </div>
            )}
            {previewError && (
                 <div className="absolute inset-0 bg-red-900/80 flex flex-col items-center justify-center z-10 p-4 text-center">
                    <p className="text-red-200 font-semibold">Preview Failed</p>
                    <p className="text-red-300 text-xs mt-2">{previewError}</p>
                 </div>
            )}
            <img src={previewImageUrl} alt="Sonia Preview" className="w-full h-full object-cover" />
          </div>
          
          <button
            onClick={handleGeneratePreview}
            disabled={isPreviewLoading}
            className="w-full mb-3 bg-indigo-800 hover:bg-indigo-700 text-white font-bold py-3 px-6 rounded-lg text-lg transition-all duration-300 transform hover:scale-105 disabled:bg-gray-600 disabled:cursor-not-allowed"
          >
            {isPreviewLoading ? 'Generating...' : 'Generate Preview'}
          </button>

          <button
            onClick={() => onComplete(localConfig)}
            className="w-full bg-fuchsia-500 hover:bg-fuchsia-600 text-white font-bold py-3 px-6 rounded-lg text-lg transition-all duration-300 transform hover:scale-105"
          >
            Start Chat
          </button>
        </div>
      </div>
    </div>
  );
};

export default CustomizationScreen;
