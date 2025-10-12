export interface ModelConfig {
  provider: 'cloud' | 'local';
  localEndpoints: {
    text: string;
    image: string;
    audio: string;
  };
}

export interface SoniaConfig {
  appearance: {
    faceStyle: 'Realistic' | 'Anime' | 'Stylized';
    eyeSize: number;
    noseSize: number;
    lipSize: number;
    jawline: number;
    hairStyle: 'Long & Wavy' | 'Short Bob' | 'Ponytail' | 'Pixie Cut';
    hairColor: string;
    bodyType: 'Athletic' | 'Curvy' | 'Slim';
    bust: number;
    waist: number;
    hips: number;
    attire: 'Casual' | 'Lingerie' | 'Formal' | 'Fantasy';
  };
  personality: {
    flirty: number;
    sweet: number;
    dominant: number;
    intelligent: number;
    playful: number;
    shy: number;
    quirks: string[];
  };
  voice: {
    tone: 'Seductive' | 'Warm' | 'Playful' | 'Confident';
    voiceName: string | null; // Can be null for auto-selection
  };
  relationship: 'Girlfriend' | 'Best Friend' | 'Lover' | 'Fantasy Partner';
  backstory: string;
  nsfwMode: boolean;
  modelConfig: ModelConfig;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'sonia';
  type: 'text' | 'image' | 'video' | 'loading' | 'error';
  content: string; // text, base64 for image, or URL for video
  timestamp: Date;
}

export type AppStep = 'welcome' | 'ageGate' | 'customization' | 'chat' | 'gallery' | 'scenarios';

export interface MemoryItem {
  value: any;
  timestamp: number;
  pinned?: boolean;
}

export interface UserMemory {
  [key: string]: MemoryItem;
}