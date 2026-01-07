
import React, { useEffect } from 'react';
import WelcomeScreen from './components/WelcomeScreen';
import AgeGate from './components/AgeGate';
import CustomizationScreen from './components/CustomizationScreen';
import ChatScreen from './components/ChatScreen';
import SettingsModal from './components/SettingsModal';
import GalleryScreen from './components/GalleryScreen';
import ScenariosScreen from './components/ScenariosScreen';
import ErrorBoundary from './components/ErrorBoundary';
import ChatLoadingState from './components/ChatLoadingState';
import useStore from './store/useStore';
import { analytics } from './utils/analytics';
import { logger } from './utils/logger';

const App: React.FC = () => {
    // Select state individually to prevent unnecessary re-renders
    const step = useStore(state => state.step);
    const messages = useStore(state => state.messages);
    const isSettingsOpen = useStore(state => state.isSettingsOpen);
    const soniaConfig = useStore(state => state.soniaConfig);
    const availableVoices = useStore(state => state.availableVoices);
    const memory = useStore(state => state.memory);
    const isSoniaSpeaking = useStore(state => state.isSoniaSpeaking);
    const avatarUrl = useStore(state => state.avatarUrl);
    const isInitialized = useStore(state => state.isInitialized);
    
    // Get actions from the store
    const initialize = useStore(state => state.initialize);
    const setStep = useStore(state => state.setStep);
    const handleCustomizationComplete = useStore(state => state.handleCustomizationComplete);
    const sendMessage = useStore(state => state.sendMessage);
    const openSettings = useStore(state => state.openSettings);
    const closeSettings = useStore(state => state.closeSettings);
    const handleSaveSettings = useStore(state => state.handleSaveSettings);
    const handleNavClick = useStore(state => state.handleNavClick);
    const handleAvatarAction = useStore(state => state.handleAvatarAction);
    const handlePinMemory = useStore(state => state.handlePinMemory);
    const handleDeleteMemory = useStore(state => state.handleDeleteMemory);
    const startScenario = useStore(state => state.startScenario);

    useEffect(() => {
        // Initialize analytics
        analytics.init();
        logger.info('Sonia AI Companion started');
        
        // Initialize app
        initialize();
        
        // Track initial page view
        analytics.trackPageView('App Start');
    }, []); // Empty dependency array - only run once on mount

    // Track step changes
    useEffect(() => {
        if (step) {
            analytics.trackPageView(step);
            logger.debug('Navigation', { step });
        }
    }, [step]);

    // Show loading state while initializing
    if (!isInitialized && (step === 'chat' || step === 'gallery' || step === 'scenarios')) {
        return <ChatLoadingState />;
    }

    const renderStep = () => {
        switch (step) {
            case 'welcome':
                return <WelcomeScreen onStart={() => setStep('ageGate')} />;
            case 'ageGate':
                return <AgeGate onConfirm={() => setStep('customization')} />;
            case 'customization':
                return <CustomizationScreen config={soniaConfig} onComplete={handleCustomizationComplete} onOpenSettings={openSettings} />;
            case 'chat':
                return <ChatScreen 
                    messages={messages} 
                    onSendMessage={sendMessage} 
                    onOpenSettings={openSettings} 
                    isSoniaSpeaking={isSoniaSpeaking}
                    onNavClick={handleNavClick}
                    onAvatarAction={handleAvatarAction}
                    avatarUrl={avatarUrl}
                    soniaConfig={soniaConfig}
                />;
            case 'gallery':
                return <GalleryScreen messages={messages} onBack={() => setStep('chat')} />;
            case 'scenarios':
                return <ScenariosScreen 
                            onBack={() => setStep('chat')} 
                            onSelectScenario={startScenario}
                            nsfwMode={soniaConfig.nsfwMode} 
                        />;
            default:
                return <div>Error: Unknown step</div>;
        }
    };

    return (
        <ErrorBoundary>
            <>
                {renderStep()}
                {isSettingsOpen && (
                    <SettingsModal
                        isOpen={isSettingsOpen}
                        onClose={closeSettings}
                        config={soniaConfig}
                        onSave={handleSaveSettings}
                        availableVoices={availableVoices}
                        memory={memory}
                        onPinMemory={handlePinMemory}
                        onDeleteMemory={handleDeleteMemory}
                    />
                )}
            </>
        </ErrorBoundary>
    );
};

export default App;
