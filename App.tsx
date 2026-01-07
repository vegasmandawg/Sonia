
import React, { useEffect } from 'react';
import WelcomeScreen from './components/WelcomeScreen';
import AgeGate from './components/AgeGate';
import CustomizationScreen from './components/CustomizationScreen';
import ChatScreen from './components/ChatScreen';
import SettingsModal from './components/SettingsModal';
import GalleryScreen from './components/GalleryScreen';
import ScenariosScreen from './components/ScenariosScreen';
import ErrorBoundary from './components/ErrorBoundary';
import Toast from './components/Toast';
import ChatLoadingState from './components/ChatLoadingState';
import useStore from './store/useStore';
import { useToast } from './hooks/useToast';
import { analytics } from './utils/analytics';
import { logger } from './utils/logger';

const App: React.FC = () => {
    const { 
        step, 
        messages, 
        isSettingsOpen, 
        soniaConfig, 
        availableVoices, 
        memory, 
        isSoniaSpeaking, 
        avatarUrl,
        isInitialized
    } = useStore(state => ({
        step: state.step,
        messages: state.messages,
        isSettingsOpen: state.isSettingsOpen,
        soniaConfig: state.soniaConfig,
        availableVoices: state.availableVoices,
        memory: state.memory,
        isSoniaSpeaking: state.isSoniaSpeaking,
        avatarUrl: state.avatarUrl,
        isInitialized: state.isInitialized
    }));
    
    const { 
        initialize, 
        setStep, 
        handleCustomizationComplete, 
        sendMessage, 
        openSettings, 
        closeSettings,
        handleSaveSettings,
        handleNavClick,
        handleAvatarAction,
        handlePinMemory,
        handleDeleteMemory,
        startScenario,
    } = useStore.getState();

    const { toasts, hideToast } = useToast();

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
                {/* Toast Notifications */}
                {toasts.map((toast) => (
                    <Toast
                        key={toast.id}
                        message={toast.message}
                        type={toast.type}
                        onClose={() => hideToast(toast.id)}
                    />
                ))}
            </>
        </ErrorBoundary>
    );
};

export default App;
