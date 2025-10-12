
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SoniaConfig, ChatMessage, AppStep, UserMemory } from '../types';
import { DEFAULT_SONIA_CONFIG } from '../constants';
import { startChat, sendMessageToAI, generateImage, generateVideo, extractKeyDetails, getChatHistory, generateAvatar, testLocalEndpoint } from '../services/geminiService';
import { speak, getAvailableVoices } from '../services/ttsService';
import { loadMemory, mergeAndSaveMemory, saveFullMemory } from '../services/memoryService';

interface AppState {
    step: AppStep;
    soniaConfig: SoniaConfig;
    messages: ChatMessage[];
    isSettingsOpen: boolean;
    memory: UserMemory;
    availableVoices: SpeechSynthesisVoice[];
    isSoniaSpeaking: boolean;
    avatarUrl: string;
    isInitialized: boolean;
    localEndpointsStatus: {
        text: 'idle' | 'ok' | 'error' | 'testing';
        image: 'idle' | 'ok' | 'error' | 'testing';
        audio: 'idle' | 'ok' | 'error' | 'testing';
    };
    localEndpointsError: {
        text: string | null;
        image: string | null;
        audio: string | null;
    };
}

interface AppActions {
    initialize: () => void;
    setStep: (step: AppStep) => void;
    handleCustomizationComplete: (newConfig: SoniaConfig) => void;
    sendMessage: (text: string) => void;
    updateMemoryAndChatContext: (userText: string, soniaText: string) => void;
    handleAvatarAction: (text: string) => void;
    openSettings: () => void;
    closeSettings: () => void;
    handleSaveSettings: (newConfig: SoniaConfig) => void;
    handleNavClick: (screen: 'customization' | 'gallery' | 'scenarios') => void;
    startScenario: (scenario: { title: string; prompt: string }) => void;
    reinitializeChatWithNewMemory: (newMemory: UserMemory) => void;
    handlePinMemory: (key: string) => void;
    handleDeleteMemory: (key: string) => void;
    regenerateAvatar: (showMessages?: boolean) => void;
    checkLocalEndpoints: () => Promise<void>;
    testSingleEndpoint: (key: 'text' | 'image' | 'audio', url: string) => Promise<void>;
}

const useStore = create<AppState & AppActions>()(
    persist(
        (set, get) => ({
            step: 'welcome',
            soniaConfig: DEFAULT_SONIA_CONFIG,
            messages: [],
            isSettingsOpen: false,
            memory: {},
            availableVoices: [],
            isSoniaSpeaking: false,
            avatarUrl: '',
            isInitialized: false,
            localEndpointsStatus: { text: 'idle', image: 'idle', audio: 'idle' },
            localEndpointsError: { text: null, image: null, audio: null },

            initialize: async () => {
                if (get().isInitialized) return;

                const memory = loadMemory();
                const voices = await getAvailableVoices();
                set({ memory, availableVoices: voices, isInitialized: true });

                const { step, soniaConfig, avatarUrl } = get();

                if (soniaConfig.modelConfig.provider === 'local') {
                    get().checkLocalEndpoints();
                }

                if (step === 'chat' || step === 'gallery' || step === 'scenarios') {
                    startChat(soniaConfig, memory);

                    if (!avatarUrl) {
                        console.log("Avatar not found for returning user, generating now...");
                        get().regenerateAvatar(false);
                    }

                    const history = await getChatHistory();
                    if (!history || history.length === 0) {
                         const initialMessageContent = "Hey... I'm ready to talk when you are.";
                         set({ messages: [{ id: 'initial', sender: 'sonia', type: 'text', content: initialMessageContent, timestamp: new Date() }] });
                         // Only speak if user is on chat screen
                         if (step === 'chat') {
                             get().handleAvatarAction(initialMessageContent);
                         }
                    }
                }
            },
            
            checkLocalEndpoints: async () => {
                const { soniaConfig } = get();
                if (soniaConfig.modelConfig.provider !== 'local') {
                    set({
                        localEndpointsStatus: { text: 'idle', image: 'idle', audio: 'idle' },
                        localEndpointsError: { text: null, image: null, audio: null }
                    });
                    return;
                }
            
                const endpoints = soniaConfig.modelConfig.localEndpoints;
                const statuses: AppState['localEndpointsStatus'] = { text: 'idle', image: 'idle', audio: 'idle' };
                const errors: AppState['localEndpointsError'] = { text: null, image: null, audio: null };
            
                const testPromises = (Object.entries(endpoints) as [keyof typeof endpoints, string][]).map(async ([key, url]) => {
                    if (url) {
                        const result = await testLocalEndpoint(url);
                        statuses[key] = result.success ? 'ok' : 'error';
                        errors[key] = result.error || null;
                    } else {
                        // Consider empty URL as an error if user is in local mode
                         statuses[key] = 'error';
                         errors[key] = 'Endpoint URL is not configured.';
                    }
                });
            
                await Promise.all(testPromises);
                set({ localEndpointsStatus: statuses, localEndpointsError: errors });
            },
            
            testSingleEndpoint: async (key, url) => {
                set(state => ({
                    localEndpointsStatus: { ...state.localEndpointsStatus, [key]: 'testing' },
                    localEndpointsError: { ...state.localEndpointsError, [key]: null },
                }));
        
                const { success, error } = await testLocalEndpoint(url);
                
                set(state => ({
                    localEndpointsStatus: { ...state.localEndpointsStatus, [key]: success ? 'ok' : 'error' },
                    localEndpointsError: { ...state.localEndpointsError, [key]: error || null },
                }));
            },

            setStep: (step) => set({ step }),

            handleCustomizationComplete: async (newConfig) => {
                // Ensure default model config is merged if it's a fresh start
                const fullConfig = { ...DEFAULT_SONIA_CONFIG, ...newConfig };
                set({ soniaConfig: fullConfig, step: 'chat', messages: [] });
                startChat(fullConfig, get().memory);
                get().regenerateAvatar(true);
            },

            regenerateAvatar: async (showMessages = false) => {
                const config = get().soniaConfig;
                let loadingMessageId: string | null = null;
            
                if (showMessages) {
                    const loadingMessage: ChatMessage = { id: `avatar-loading-${Date.now()}`, sender: 'sonia', type: 'loading', content: 'Updating my look...', timestamp: new Date() };
                    loadingMessageId = loadingMessage.id;
                    set(state => ({ messages: [...state.messages, loadingMessage] }));
                }
            
                try {
                    const newAvatarUrl = await generateAvatar(config);
                    
                    // Add a validation check to ensure the returned URL is valid before setting state.
                    if (!newAvatarUrl || typeof newAvatarUrl !== 'string') {
                        // This will be caught by the catch block below and display a user-friendly error.
                        throw new Error("Image generation failed to return a valid image URL.");
                    }

                    set({ avatarUrl: newAvatarUrl });
            
                    if (showMessages && loadingMessageId) {
                        const successMessage: ChatMessage = { id: `avatar-ready-${Date.now()}`, sender: 'sonia', type: 'text', content: "All done. What do you think of the new look?", timestamp: new Date() };
                        set(state => ({ messages: state.messages.filter(m => m.id !== loadingMessageId).concat(successMessage) }));
                        get().handleAvatarAction(successMessage.content);
                    }
                } catch (error: any) {
                    console.error("Failed to regenerate avatar:", error);
                    if (showMessages && loadingMessageId) {
                        const errorContent = `I had trouble generating my new portrait: ${error.message || 'An unknown error occurred.'}`;
                        const errorMessage: ChatMessage = { id: `avatar-error-${Date.now()}`, sender: 'sonia', type: 'error', content: errorContent, timestamp: new Date() };
                        set(state => ({ messages: state.messages.filter(m => m.id !== loadingMessageId).concat(errorMessage) }));
                    }
                }
            },
            
            sendMessage: async (text) => {
                const userMessage: ChatMessage = { id: Date.now().toString(), sender: 'user', type: 'text', content: text, timestamp: new Date() };
                set(state => ({ messages: [...state.messages, userMessage] }));

                const loadingMessage: ChatMessage = { id: (Date.now() + 1).toString(), sender: 'sonia', type: 'loading', content: '', timestamp: new Date() };
                set(state => ({ messages: [...state.messages, loadingMessage] }));

                try {
                    const lowerText = text.toLowerCase();
                    const config = get().soniaConfig;
                    
                    if (lowerText.includes('show me') || lowerText.includes('send a pic') || lowerText.includes('picture of you')) {
                        // Create a safe config for in-chat image requests to decouple them from the NSFW avatar setting.
                        const safeImageConfig: SoniaConfig = { ...config, nsfwMode: false };
                        const imgContent = await generateImage(text, safeImageConfig);
                        const imgMessage: ChatMessage = { id: (Date.now() + 2).toString(), sender: 'sonia', type: 'image', content: imgContent, timestamp: new Date() };
                        set(state => ({ messages: state.messages.filter(m => m.id !== loadingMessage.id).concat(imgMessage) }));
                    } else if (lowerText.includes('send a video') || lowerText.includes('video of you')) {
                        const onProgress = (progressText: string) => {
                            set(state => ({ messages: state.messages.map(m => m.id === loadingMessage.id ? { ...m, content: progressText } : m) }));
                        };
                        const videoUrl = await generateVideo(text, config, onProgress);
                        const videoMessage: ChatMessage = { id: (Date.now() + 2).toString(), sender: 'sonia', type: 'video', content: videoUrl, timestamp: new Date() };
                        set(state => ({ messages: state.messages.filter(m => m.id !== loadingMessage.id).concat(videoMessage) }));
                    } else {
                        const soniaResponse = await sendMessageToAI(text, get().soniaConfig, get().memory, get().messages);
                        const soniaMessage: ChatMessage = { id: (Date.now() + 2).toString(), sender: 'sonia', type: 'text', content: soniaResponse, timestamp: new Date() };
                        set(state => ({ messages: state.messages.filter(m => m.id !== loadingMessage.id).concat(soniaMessage) }));
                        get().handleAvatarAction(soniaResponse);
                        get().updateMemoryAndChatContext(text, soniaResponse);
                    }
                } catch (error: any) {
                    console.error("Error handling message:", error);
                    const errorContent = error.message || "Oh, something went wrong. I couldn't generate that for you. Please try something else.";
                    const errorMessage: ChatMessage = { id: (Date.now() + 2).toString(), sender: 'sonia', type: 'error', content: errorContent, timestamp: new Date() };
                    set(state => ({ messages: state.messages.filter(m => m.id !== loadingMessage.id).concat(errorMessage) }));
                    get().handleAvatarAction(errorContent);
                }
            },

            updateMemoryAndChatContext: async (userText, soniaText) => {
                const conversationSnippet = `User: "${userText}"\nSonia: "${soniaText}"`;
                const newDetails = await extractKeyDetails(conversationSnippet, get().soniaConfig);
                if (Object.keys(newDetails).length > 0) {
                    const history = await getChatHistory();
                    mergeAndSaveMemory(newDetails);
                    const updatedMemory = loadMemory();
                    set({ memory: updatedMemory });
                    startChat(get().soniaConfig, updatedMemory, history);
                }
            },

            handleAvatarAction: (text) => {
                const { voice } = get().soniaConfig;
                speak(text, voice.tone, voice.voiceName, {
                    onstart: () => set({ isSoniaSpeaking: true }),
                    onend: () => set({ isSoniaSpeaking: false }),
                });
            },
            
            openSettings: () => set({ isSettingsOpen: true }),
            closeSettings: () => set({ isSettingsOpen: false }),
            
            handleSaveSettings: (newConfig) => {
                const oldConfig = get().soniaConfig;
                set({ soniaConfig: newConfig });
                get().reinitializeChatWithNewMemory(get().memory);

                if (newConfig.modelConfig.provider === 'local') {
                    get().checkLocalEndpoints();
                }

                // Regenerate avatar only if appearance has changed
                if (JSON.stringify(oldConfig.appearance) !== JSON.stringify(newConfig.appearance) || oldConfig.modelConfig.provider !== newConfig.modelConfig.provider) {
                    get().regenerateAvatar(true);
                }
            },
            
            handleNavClick: (screen) => {
                set({ step: screen });
            },

            startScenario: (scenario) => {
                const scenarioMessage: ChatMessage = {
                    id: `scenario-${Date.now()}`,
                    sender: 'sonia',
                    type: 'text',
                    content: `*Scenario Started: ${scenario.title}*\n\n${scenario.prompt}`,
                    timestamp: new Date(),
                };
                set(state => ({
                    step: 'chat',
                    messages: [...state.messages, scenarioMessage]
                }));
                get().handleAvatarAction(scenario.prompt);
            },

            reinitializeChatWithNewMemory: async (newMemory) => {
                const history = await getChatHistory() || [];
                startChat(get().soniaConfig, newMemory, history);
            },
            
            handlePinMemory: (key) => {
                const memory = { ...get().memory };
                if (memory[key]) {
                    memory[key].pinned = !memory[key].pinned;
                    set({ memory });
                    saveFullMemory(memory);
                    get().reinitializeChatWithNewMemory(memory);
                }
            },

            handleDeleteMemory: (key) => {
                const memory = { ...get().memory };
                if (memory[key]) {
                    delete memory[key];
                    set({ memory });
                    saveFullMemory(memory);
                    get().reinitializeChatWithNewMemory(memory);
                }
            },
        }),
        {
            name: 'sonia-ai-companion-storage',
            storage: createJSONStorage(() => localStorage),
            merge: (persistedState, currentState) => {
                const typedState = persistedState as Partial<AppState>;
                // Reset transient state on load
                const newState: Partial<AppState> = {
                    isSettingsOpen: false,
                    isSoniaSpeaking: false,
                    isInitialized: false,
                    localEndpointsStatus: { text: 'idle', image: 'idle', audio: 'idle' },
                    localEndpointsError: { text: null, image: null, audio: null },
                };

                // If the app was closed while on a "deep" screen, reset to chat screen
                if (typedState.step && typedState.step !== 'welcome' && typedState.step !== 'ageGate' && typedState.step !== 'customization') {
                    newState.step = 'chat';
                }

                return { ...currentState, ...persistedState, ...newState };
            },
        }
    )
);

export default useStore;
