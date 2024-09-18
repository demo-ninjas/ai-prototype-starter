

import { useEffect, useState } from 'react';
import { USER_STATE_CHANGED } from '../data/events';
import './footer.css';
function Footer() {
    const [username, setUsername] = useState('');
    const [name, setName] = useState('');

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
    }, []);

    return (
        <div>
            <p>The Chat Playground</p>
            <div className='user-div'>
                User: {name}
            </div>
        </div>
    );
}

export default Footer;