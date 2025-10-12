
import React, { useEffect } from 'react';
import WelcomeScreen from './components/WelcomeScreen';
import AgeGate from './components/AgeGate';
import CustomizationScreen from './components/CustomizationScreen';
import ChatScreen from './components/ChatScreen';
import SettingsModal from './components/SettingsModal';
import GalleryScreen from './components/GalleryScreen';
import ScenariosScreen from './components/ScenariosScreen';
import useStore from './store/useStore';

const App: React.FC = () => {
    const { 
        step, 
        messages, 
        isSettingsOpen, 
        soniaConfig, 
        availableVoices, 
        memory, 
        isSoniaSpeaking, 
        avatarUrl 
    } = useStore(state => ({
        step: state.step,
        messages: state.messages,
        isSettingsOpen: state.isSettingsOpen,
        soniaConfig: state.soniaConfig,
        availableVoices: state.availableVoices,
        memory: state.memory,
        isSoniaSpeaking: state.isSoniaSpeaking,
        avatarUrl: state.avatarUrl
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

    useEffect(() => {
        initialize();
    }, [initialize]);

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
    );
};

export default App;
