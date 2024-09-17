import { useEffect, useState } from 'react';
import logo from '../logo.png';
import './header.css';
function Header() {
    const [ shouldSpeak, setShouldSpeak ] = useState(false);

    useEffect(() => {
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


        let speaker_voice = new URLSearchParams(window.location.search).get('voice');
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
        </>
    );
}

export default Header;