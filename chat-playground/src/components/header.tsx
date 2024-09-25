import { useEffect, useState } from 'react';
import { METADATA_LEVEL_CHANGED } from '../data/events';

import logo from '../logo.png';
import './header.css';
function Header() {
    const [ shouldSpeak, setShouldSpeak ] = useState(false);
    const [ metadataLevel, setMetadataLevel ] = useState(2);

    useEffect(() => {
        let qParams = new URLSearchParams(window.location.search);

        // Check if the renderMetadataLevel has been set in the query string or local storage
        let render_metadata_level = qParams.get('metadata-level');
        if (!render_metadata_level) {
          render_metadata_level = localStorage.getItem('metadata-level');
        }
        if (render_metadata_level) {
            // Post the metadata level to the document
            localStorage.setItem('metadata-level', render_metadata_level);
            let metadata_level = parseInt(render_metadata_level);
            setMetadataLevel(metadata_level);
            setTimeout(() => {
                document.dispatchEvent(new CustomEvent(METADATA_LEVEL_CHANGED, { detail: metadata_level }));
            }, 8);
        }


        let speak_setting = localStorage.getItem('should-speak');
        if (speak_setting && speak_setting == 'true') {
            // @ts-ignore
            window.__should_speak = true;
            setShouldSpeak(true);
        } else {
            // @ts-ignore
            window.__should_speak = false;
            setShouldSpeak(false);
        }


        let speaker_voice = qParams.get('voice');
        if (!speaker_voice) {
            speaker_voice = localStorage.getItem('speaker-voice');
        }
        if (speaker_voice) {
            // @ts-ignore
            window.__speaker_voice = speaker_voice;
            localStorage.setItem('speaker-voice', speaker_voice);
        } else {
            // @ts-ignore
            window.__speaker_voice = '';
        }
    }
    , []);
    
    const newChat = () => {
        let qparameters = new URLSearchParams(window.location.search);
        qparameters.delete("thread");
        window.location.replace(window.location.protocol + "//" + window.location.host + window.location.pathname + "?" + qparameters.toString());
        return false;
      }

    const toggleSpeaking = () => {
        // @ts-ignore
        window.__should_speak = !window.__should_speak;
        // @ts-ignore
        setShouldSpeak(window.__should_speak);
        // @ts-ignore
        localStorage.setItem('should-speak', window.__should_speak  ? 'true' : 'false');
    }

    return (
        <>
            <img src={logo} className="App-logo" alt="logo" />
            <h1>Chat Playground</h1>
            <button className='new-chat-btn' onClick={newChat}>New Chat</button>

            <button 
                id="speaker-toggle"
                onClick={toggleSpeaking}  
                title="Toggle Spoken responses On/Off"
                className={ shouldSpeak ? 'speaker-on' : 'speaker-off' }
            >  
                { shouldSpeak ? '🔊' : '🔇' }
            </button>

            <button 
                id="metadata-toggle"
                onClick={() => {
                    let current_level = parseInt(localStorage.getItem('metadata-level') || '0');
                    let new_level = (current_level + 1) % 3;
                    localStorage.setItem('metadata-level', new_level.toString());
                    document.dispatchEvent(new CustomEvent(METADATA_LEVEL_CHANGED, { detail: new_level }));
                    setMetadataLevel(new_level);
                }}
                title="Toggle Metadata Level (None, Metadata Only, Metadata + Citations)"
            >
                {
                    {
                        0: '📕', // None
                        1: '📘', // Metadata only
                        2: '📚'  // Metadata + Citations
                    }[metadataLevel]
                }
            </button>
        </>
    );
}

export default Header;