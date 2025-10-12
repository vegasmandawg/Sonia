// components/SettingsModal.tsx
import React, { useState, useEffect } from 'react';
import type { SoniaConfig, UserMemory, ModelConfig } from '../types';
import { ICONS } from '../constants';
import { speakSample } from '../services/ttsService';
import MemoryManager from './MemoryManager';
import useStore from '../store/useStore';

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    config: SoniaConfig;
    onSave: (newConfig: SoniaConfig) => void;
    availableVoices: SpeechSynthesisVoice[];
    memory: UserMemory;
    onPinMemory: (key: string) => void;
    onDeleteMemory: (key: string) => void;
}

type SettingsTab = 'Sonia' | 'Voice' | 'Memory' | 'Model';
type EndpointKey = 'text' | 'image' | 'audio';

const CorsTroubleshootingGuide = () => (
    <div className="mt-6 p-4 bg-red-900/30 border border-red-700 rounded-lg text-sm">
        <h4 className="font-bold text-red-300 flex items-center">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 mr-2" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            Connection Failed? Check CORS.
        </h4>
        <p className="text-red-200 mt-2">
            "Failed to fetch" errors are usually caused by your local server's Cross-Origin Resource Sharing (CORS) policy. To fix this, you need to start your server with a flag that allows requests from this web app.
        </p>
        <p className="text-red-200 mt-3 font-semibold">Common Server Flags:</p>
        <ul className="list-disc list-inside space-y-2 mt-2 text-red-200">
            <li>
                <strong>Oobabooga Text Gen UI:</strong> Add the flag <code className="bg-black/50 px-1.5 py-1 rounded text-white">--api --cors-allow-origins *</code>
            </li>
            <li>
                <strong>Automatic1111/SD.Next:</strong> Add the flag <code className="bg-black/50 px-1.5 py-1 rounded text-white">--api --cors-allow-origins *</code>
            </li>
            <li>
                <strong>ComfyUI:</strong> Add the flag <code className="bg-black/50 px-1.5 py-1 rounded text-white">--enable-cors-header</code>
            </li>
        </ul>
        <p className="mt-3 text-xs text-red-300/80">
            Remember to restart your local server after adding the flag. The server's console window should confirm that the API is running with the correct CORS policy.
        </p>
    </div>
);

const EndpointInput: React.FC<{
    label: string;
    value: string;
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    nameKey: EndpointKey;
}> = ({ label, value, onChange, nameKey }) => {
    const testStatus = useStore(state => state.localEndpointsStatus[nameKey]);
    const testError = useStore(state => state.localEndpointsError[nameKey]);
    const testEndpoint = useStore(state => state.testSingleEndpoint);
    
    const handleTest = () => {
        if (!value) return;
        testEndpoint(nameKey, value);
    };

    const getStatusDisplay = () => {
        switch (testStatus) {
            case 'testing':
                return (
                    <div className="flex items-center space-x-2 text-gray-400">
                        <div className="w-4 h-4 border-2 border-t-transparent border-gray-400 rounded-full animate-spin"></div>
                        <span className="text-xs">Connecting...</span>
                    </div>
                );
            case 'ok':
                return (
                    <div className="flex items-center space-x-1 text-green-400">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" /></svg>
                        <span className="text-xs font-semibold">Connected</span>
                    </div>
                );
            case 'error':
                 return (
                    <div className="flex items-center space-x-1 text-red-400">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" /></svg>
                        <span className="text-xs font-semibold">Failed</span>
                    </div>
                );
            default:
                return <div className="h-5" style={{width: '75px'}}></div>; // Placeholder
        }
    };
    
    return (
        <div>
            <label className="block text-xs font-medium text-gray-400">{label}</label>
            <div className="flex items-center space-x-2 mt-1">
                <input
                    type="text"
                    value={value}
                    onChange={onChange}
                    placeholder="http://localhost:8080/v1/..."
                    className="w-full bg-gray-800 border border-gray-600 rounded-md p-2 text-sm text-white focus:ring-fuchsia-500 focus:border-fuchsia-500"
                />
                <button
                    onClick={handleTest}
                    disabled={!value || testStatus === 'testing'}
                    className="px-3 py-2 bg-indigo-800 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg disabled:bg-gray-600 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
                >
                    {testStatus === 'testing' ? 'Testing...' : 'Test'}
                </button>
                <div className="w-24 h-6 flex items-center justify-start">
                    {getStatusDisplay()}
                </div>
            </div>
            {testStatus === 'error' && testError && (
                <p className="text-xs text-red-400 mt-2 whitespace-pre-wrap">{testError}</p>
            )}
        </div>
    );
};

const SettingsModal: React.FC<SettingsModalProps> = ({
    isOpen,
    onClose,
    config,
    onSave,
    availableVoices,
    memory,
    onPinMemory,
    onDeleteMemory
}) => {
    const [localConfig, setLocalConfig] = useState<SoniaConfig>(config);
    const [activeTab, setActiveTab] = useState<SettingsTab>('Sonia');
    const statuses = useStore(state => state.localEndpointsStatus);

    useEffect(() => {
        setLocalConfig(config);
    }, [config, isOpen]);

    if (!isOpen) return null;

    const handleSave = () => {
        onSave(localConfig);
        onClose();
    };

    const handleConfigChange = (section: keyof SoniaConfig, key: string, value: any) => {
        setLocalConfig(prev => ({
            ...prev,
            [section]: {
                ...(prev[section] as any),
                [key]: value
            }
        }));
    };
    
    const handleModelConfigChange = (key: keyof ModelConfig, value: any) => {
        if (key === 'localEndpoints') {
            setLocalConfig(prev => ({ ...prev, modelConfig: { ...prev.modelConfig, localEndpoints: { ...prev.modelConfig.localEndpoints, ...value } }}));
        } else {
            setLocalConfig(prev => ({ ...prev, modelConfig: { ...prev.modelConfig, [key]: value } }));
        }
    };

    const TabButton: React.FC<{ tabName: SettingsTab }> = ({ tabName }) => (
        <button
            onClick={() => setActiveTab(tabName)}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                activeTab === tabName
                    ? 'bg-fuchsia-500 text-white'
                    : 'text-gray-300 hover:bg-gray-700'
            }`}
        >
            {tabName}
        </button>
    );

    const renderContent = () => {
        switch (activeTab) {
            case 'Sonia':
                return (
                    <div>
                        <h3 className="text-lg font-semibold text-violet-300 mb-4">Core Persona</h3>
                        <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-300 mb-2">Relationship</label>
                            <select value={localConfig.relationship} onChange={e => setLocalConfig(prev => ({...prev, relationship: e.target.value as SoniaConfig['relationship']}))} className="w-full bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white">
                                <option>Girlfriend</option>
                                <option>Best Friend</option>
                                <option>Lover</option>
                                <option>Fantasy Partner</option>
                            </select>
                        </div>
                        <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-300 mb-2">Backstory</label>
                            <textarea value={localConfig.backstory} onChange={e => setLocalConfig(prev => ({...prev, backstory: e.target.value}))} rows={4} className="w-full bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white" />
                        </div>
                        <div className="flex items-center justify-between bg-gray-700/50 p-3 rounded-lg">
                            <div>
                                <label className="font-medium text-gray-200">Enable NSFW Content</label>
                                <p className="text-xs text-gray-400">Allows for explicit conversation and imagery.</p>
                            </div>
                            <label className="relative inline-flex items-center cursor-pointer">
                                <input type="checkbox" checked={localConfig.nsfwMode} onChange={e => setLocalConfig(prev => ({...prev, nsfwMode: e.target.checked}))} className="sr-only peer" />
                                <div className="w-11 h-6 bg-gray-600 rounded-full peer peer-focus:ring-2 peer-focus:ring-fuchsia-500/50 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-fuchsia-500"></div>
                            </label>
                        </div>
                    </div>
                );
            case 'Voice':
                return (
                    <div>
                         <h3 className="text-lg font-semibold text-violet-300 mb-4">Voice Settings</h3>
                        <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-300 mb-2">Voice Tone</label>
                            <select value={localConfig.voice.tone} onChange={e => handleConfigChange('voice', 'tone', e.target.value)} className="w-full bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white">
                                <option>Seductive</option>
                                <option>Warm</option>
                                <option>Playful</option>
                                <option>Confident</option>
                            </select>
                        </div>
                        <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-300 mb-2">Specific Voice</label>
                            <select value={localConfig.voice.voiceName || ''} onChange={e => handleConfigChange('voice', 'voiceName', e.target.value || null)} className="w-full bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white">
                                <option value="">Auto-select best voice</option>
                                {availableVoices.map(v => <option key={v.name} value={v.name}>{v.name} ({v.lang})</option>)}
                            </select>
                        </div>
                        <button onClick={() => speakSample(localConfig.voice.voiceName)} className="w-full bg-indigo-800 hover:bg-indigo-700 text-white font-bold py-2 px-4 rounded-lg transition-colors">
                            Play Voice Sample
                        </button>
                    </div>
                );
            case 'Memory':
                return (
                     <div>
                         <h3 className="text-lg font-semibold text-violet-300 mb-4">Sonia's Memory</h3>
                         <p className="text-sm text-gray-400 mb-4">Here's what Sonia remembers about you. You can pin important details to keep them top of mind for her, or delete things you'd rather she forget.</p>
                         <MemoryManager memory={memory} onPin={onPinMemory} onDelete={onDeleteMemory} />
                    </div>
                );
            case 'Model':
                const isLocal = localConfig.modelConfig.provider === 'local';
                const hasError = isLocal && Object.values(statuses).some(s => s === 'error');
                return (
                    <div>
                        <h3 className="text-lg font-semibold text-violet-300 mb-4">AI Model Configuration</h3>
                         <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-300 mb-2">AI Provider</label>
                            <select value={localConfig.modelConfig.provider} onChange={e => handleModelConfigChange('provider', e.target.value)} className="w-full bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white">
                                <option value="cloud">Cloud (Gemini API)</option>
                                <option value="local">Local Server</option>
                            </select>
                             <p className="text-xs text-gray-400 mt-2">
                                {isLocal ? "Connect to a self-hosted AI model running on your computer." : "Use Google's cloud API. Requires a valid API Key."}
                            </p>
                        </div>

                        {isLocal && (
                            <div className="space-y-4 p-4 bg-gray-700/50 rounded-lg mt-4 border border-white/10">
                                <h4 className="font-semibold text-gray-200">Local Endpoints</h4>
                                <EndpointInput 
                                    label="Text Generation (OpenAI Compatible)"
                                    value={localConfig.modelConfig.localEndpoints.text}
                                    onChange={e => handleModelConfigChange('localEndpoints', { text: e.target.value })}
                                    nameKey="text"
                                />
                                 <EndpointInput 
                                    label="Image Generation"
                                    value={localConfig.modelConfig.localEndpoints.image}
                                    onChange={e => handleModelConfigChange('localEndpoints', { image: e.target.value })}
                                    nameKey="image"
                                />
                                 <EndpointInput 
                                    label="Audio Transcription (Whisper)"
                                    value={localConfig.modelConfig.localEndpoints.audio}
                                    onChange={e => handleModelConfigChange('localEndpoints', { audio: e.target.value })}
                                    nameKey="audio"
                                />
                            </div>
                        )}
                        
                        {hasError && <CorsTroubleshootingGuide />}

                        {!isLocal && (
                             <div className="p-3 bg-yellow-900/30 text-yellow-300 border border-yellow-700 rounded-lg text-sm">
                                You are using the Gemini Cloud API. Ensure your <code className="bg-black/30 px-1 py-0.5 rounded">API_KEY</code> environment variable is set.
                            </div>
                        )}
                    </div>
                );
        }
    }

    return (
        <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50 p-4 backdrop-blur-sm">
            <div className="bg-gray-800 rounded-2xl w-full max-w-2xl shadow-2xl shadow-fuchsia-500/10 border border-white/10 flex flex-col max-h-[90vh]">
                <div className="flex items-center justify-between p-4 border-b border-white/10">
                    <h2 className="text-xl font-bold text-white">Settings</h2>
                    <button onClick={onClose} className="p-2 text-gray-400 hover:text-white rounded-full transition-colors">{ICONS.close}</button>
                </div>

                <div className="flex-1 flex overflow-hidden">
                    <div className="p-4 border-r border-white/10">
                        <nav className="flex flex-col space-y-2">
                            <TabButton tabName="Sonia" />
                            <TabButton tabName="Voice" />
                            <TabButton tabName="Memory" />
                            <TabButton tabName="Model" />
                        </nav>
                    </div>
                    <div className="flex-1 p-6 overflow-y-auto custom-scrollbar">
                        {renderContent()}
                    </div>
                </div>

                <div className="p-4 bg-gray-900/50 border-t border-white/10 flex justify-end space-x-3">
                    <button onClick={onClose} className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white font-semibold rounded-lg transition-colors">Cancel</button>
                    <button onClick={handleSave} className="px-6 py-2 bg-fuchsia-500 hover:bg-fuchsia-600 text-white font-bold rounded-lg transition-colors">Save Changes</button>
                </div>
            </div>
        </div>
    );
};

export default SettingsModal;