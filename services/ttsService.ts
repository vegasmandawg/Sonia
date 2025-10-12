import type { SoniaConfig } from '../types';

let voices: SpeechSynthesisVoice[] = [];
let voicesPromise: Promise<SpeechSynthesisVoice[]>;

interface SpeakCallbacks {
    onstart?: () => void;
    onend?: () => void;
}

// Function to get voices, returns a promise that resolves when voices are loaded.
export const getAvailableVoices = (): Promise<SpeechSynthesisVoice[]> => {
    if (voices.length > 0) {
        return Promise.resolve(voices);
    }
    
    if (voicesPromise) {
        return voicesPromise;
    }

    voicesPromise = new Promise((resolve) => {
        if (typeof speechSynthesis === 'undefined') {
            return resolve([]);
        }

        const populateVoices = () => {
            const voiceList = speechSynthesis.getVoices();
            if (voiceList.length > 0) {
                voices = voiceList;
                resolve(voices);
            }
        };

        populateVoices();
        if (voices.length === 0 && speechSynthesis.onvoiceschanged !== null) {
            speechSynthesis.onvoiceschanged = () => {
                populateVoices();
            };
        } else if (voices.length === 0) {
            // Fallback for browsers that don't fire onvoiceschanged
            setTimeout(() => {
                populateVoices();
            }, 500);
        }
    });
    
    return voicesPromise;
};

// Heuristics to select the best available voice if none is specified
const selectDefaultVoice = (): SpeechSynthesisVoice | null => {
    if (voices.length === 0) return null;

    const userLang = navigator.language.split('-')[0]; // e.g., 'en' from 'en-US'

    // This scoring system evaluates voices based on several criteria to find the best fit for Sonia.
    const scoreVoice = (voice: SpeechSynthesisVoice): number => {
        let score = 0;
        const name = voice.name.toLowerCase();
        const lang = voice.lang.toLowerCase();

        // 1. Language Match (Highest Priority)
        if (lang.startsWith(userLang)) {
            score += 200;
        } else if (lang.startsWith('en')) {
            score += 50;
        }

        // 2. Gender Preference (Female) - Increased weight
        if (name.includes('female') || name.includes('woman') || name.includes('zira') || name.includes('eva') || name.includes('susan')) {
            score += 100; // Increased preference for female voices
        }
        
        // Penalize male voices very heavily to ensure a female persona.
        const maleKeywords = ['male', 'man', 'david', 'mark', 'guy', 'boy', 'paul', 'lee', 'daniel', 'fenrir'];
        if (maleKeywords.some(keyword => name.includes(keyword))) {
            score -= 1000; // Drastic penalty for male voices to prevent immersion breaking.
        }

        // 3. Voice Quality Indicators (Higher weight for key terms)
        if (!voice.localService) {
            score += 50; // Cloud-based voices are strongly preferred
        }
        if (name.includes('natural') || name.includes('neural') || name.includes('studio') || name.includes('premium')) {
            score += 60; // These are very strong indicators of high quality
        }
        if (name.includes('google') || name.includes('microsoft') || name.includes('apple')) {
            score += 30; // Major providers are a good sign
        }
        
        // 4. Penalize Robotic/Generic Voices (More keywords)
        if (name.includes('robot') || name.includes('desktop') || name.includes('mobile') || name.includes('standard') || name.includes('compact') || name.includes('espeak')) {
            score -= 75; // Increased penalty for low-quality indicators
        }

        return score;
    };

    const sortedVoices = voices
        .map(voice => ({ voice, score: scoreVoice(voice) }))
        .sort((a, b) => b.score - a.score);

    // Return the best scored voice, or the first available as a last resort.
    return sortedVoices.length > 0 ? sortedVoices[0].voice : voices[0] || null;
}

const getVoiceByName = (name: string): SpeechSynthesisVoice | null => {
    if (voices.length === 0) return null;
    return voices.find(v => v.name === name) || null;
}

const speakInternal = (text: string, tone: SoniaConfig['voice']['tone'], voiceName: string | null, callbacks?: SpeakCallbacks) => {
    if (typeof speechSynthesis === 'undefined' || !text.trim()) {
        console.warn("Speech synthesis not supported or text is empty.");
        // Ensure onend is called even if speech doesn't start
        callbacks?.onend?.();
        return;
    }
    
    // Do not cancel here for sequential speaking in samples
    // speechSynthesis.cancel(); 
    
    const utterance = new SpeechSynthesisUtterance();
    utterance.text = text.replace(/\*.*?\*/g, '').trim();

    if (!utterance.text) {
        callbacks?.onend?.();
        return;
    }

    if (callbacks) {
        utterance.onstart = callbacks.onstart || null;
        utterance.onend = callbacks.onend || null;
    }

    const selectedVoice = voiceName ? getVoiceByName(voiceName) : selectDefaultVoice();
    
    if (selectedVoice) {
        utterance.voice = selectedVoice;
    }
    
    // These values are fine-tuned for a more natural-sounding performance.
    switch (tone) {
        case 'Seductive':
            utterance.pitch = 0.9; // Raised slightly from 0.85 to be less deep, more breathy
            utterance.rate = 0.9;   // Slowed for intimacy
            break;
        case 'Warm':
        case 'Confident': // A confident voice is clear and steady. The default rate/pitch is most natural.
            utterance.pitch = 1;
            utterance.rate = 1;
            break;
        case 'Playful':
            utterance.pitch = 1.15; // Higher pitch for energy, but not unnaturally so (toned down from 1.2)
            utterance.rate = 1.05; // Slightly faster for a bubbly feel (toned down from 1.1)
            break;
        default:
            utterance.pitch = 1;
            utterance.rate = 1;
    }
    
    speechSynthesis.speak(utterance);
}

export const speak = (text: string, tone: SoniaConfig['voice']['tone'], voiceName: string | null, callbacks?: SpeakCallbacks) => {
    getAvailableVoices().then(() => {
        speechSynthesis.cancel(); // Cancel any ongoing speech before starting a new one.
        speakInternal(text, tone, voiceName, callbacks);
    });
};

export const speakSample = (voiceName: string | null) => {
    getAvailableVoices().then(() => {
        // Stop any currently playing speech before starting the samples.
        speechSynthesis.cancel();
        
        const tones: SoniaConfig['voice']['tone'][] = ['Warm', 'Playful', 'Seductive', 'Confident'];
        let toneIndex = 0;
        
        const speakNextTone = () => {
            if (toneIndex >= tones.length) return;
            
            const currentTone = tones[toneIndex];
            const text = `This is my voice with a ${currentTone.toLowerCase()} tone.`;
            
            speakInternal(text, currentTone, voiceName, {
                onend: () => {
                    toneIndex++;
                    // Short delay between samples for clarity
                    setTimeout(speakNextTone, 250);
                }
            });
        };
        
        speakNextTone();
    });
};