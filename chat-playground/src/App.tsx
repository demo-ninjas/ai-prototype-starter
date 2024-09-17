import React from 'react';
import './App.css';

// Import Main App components
import ChatWindow from './components/chat-window';
import LeftPanel from './components/left-panel';
import RightPanel from './components/right-panel';
import Header from './components/header';
import Footer from './components/footer';

import { ApiClient } from './service/api';
import KeyboardManager from './components/keyboard-manager';

// Create Keyboard Manager
const keyboardManager = new KeyboardManager();

// Create Api Client
const apiClient = new ApiClient();

function App() {
  return (
    <div className="App">
      <header id="app-header" className="App-header" key="header-area">
          <Header />
      </header>
      <div className='App-content'>
        <aside id="app-aside-left" className='App-aside-left' key="left-panel">
          <LeftPanel apiClient={apiClient} />
        </aside>
        <main id="app-main" className='App-main' key="main-content">
          <ChatWindow apiClient={apiClient} />
        </main>

        <aside id="app-aside-right" className='App-aside-right' key="right-panel">
          <RightPanel apiClient={apiClient} />
        </aside>       
      </div>
      <footer id="app-footer" className='App-footer' key="footer-area">
          <Footer />
      </footer>
    </div>
  );
}

export default App;
