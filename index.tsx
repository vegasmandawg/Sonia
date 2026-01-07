
import React from 'react';
import ReactDOM from 'react-dom/client';
import AppSimple from './AppSimple';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error("Could not find root element to mount to");
}

const root = ReactDOM.createRoot(rootElement);

// Render simple app for debugging
root.render(
  <AppSimple />
);
