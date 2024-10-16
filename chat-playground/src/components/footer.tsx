

import { useEffect, useState } from 'react';
import { USER_STATE_CHANGED, SENTIMENT_UPDATE } from '../data/events';
import './footer.css';
function Footer() {
    const [username, setUsername] = useState('');
    const [name, setName] = useState('');
    const [ currentSentiment, setCurrentSentiment ] = useState({ sentiment: 'neutral', emotion:'unknown', 'sentiment-meter': 0.5, confidence: 0.5, 'emotion-emoji': '😐', 'sentiment-emoji':'😐', 'sentiment-reasoning': 'Not Calculated', 'emotion-reasoning': 'Not Calculated' });

    useEffect(() => {
        // List for the USER_STATE_CHANGED event
        // When the event is received, update the username and name
        document.addEventListener(USER_STATE_CHANGED, (event) => {
            // @ts-ignore
            let detail = event.detail;
            if (detail != null) {
                setUsername(detail.username);
                setName(detail.name);
            }
        });


        document.addEventListener(SENTIMENT_UPDATE, (event) => {
            // @ts-ignore
            let detail = event.detail;
            if (detail != null) {
                setCurrentSentiment(detail);
            }
        });
    }, []);

    return (
        <div>
            <div className='sentiment-div'>
                <span title={`Sentiment: ${currentSentiment.sentiment} [Reasoning: ${currentSentiment['sentiment-reasoning']}, Confidence: ${currentSentiment.confidence}]`}>
                    <meter value={currentSentiment['sentiment-meter']} min="0" max="1" optimum={1} high={0.7} low={0.35}></meter>
                </span>
                &nbsp;/&nbsp;
                <span title={`Emotion: ${currentSentiment.emotion} [Reasoning: ${currentSentiment['emotion-reasoning']}, Confidence: ${currentSentiment.confidence}]`}>
                    {currentSentiment['emotion-emoji']}
                </span>
            </div>

            <p>The Chat Playground</p>
            <div className='user-div'>
                User: {name}
            </div>
        </div>
    );
}

export default Footer;