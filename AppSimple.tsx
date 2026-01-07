// Simplified App component for debugging
import React, { useEffect } from 'react';
import useStore from './store/useStore';

const AppSimple: React.FC = () => {
    const step = useStore(state => state.step);
    const initialize = useStore(state => state.initialize);

    useEffect(() => {
        console.log('AppSimple mounted');
        initialize();
    }, []);

    return (
        <div style={{ color: 'white', padding: '50px', fontSize: '24px' }}>
            <h1>Sonia Debug Mode</h1>
            <p>Current step: {step}</p>
            <p>If you see this, React is rendering!</p>
        </div>
    );
};

export default AppSimple;
