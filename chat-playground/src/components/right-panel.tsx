import './right-panel.css';
import { useState, useEffect } from 'react';
import { ApiClient } from '../service/api';
import { CLEAR_STEPS, CLEAR_PROGRESS, STEP_MESSAGE, PROGRESS_MESSAGE } from '../data/events';

function RightPanel({apiClient}: {apiClient:ApiClient}) {
    const [progress_msg, setProgress] = useState('');
    const [steps, setSteps] = useState([]);

    useEffect(() => {
        // Subscribe to the progress-message events
        document.addEventListener(PROGRESS_MESSAGE, (event) => {
            // console.log('progress-message event received', event);
            // @ts-ignore
            if (event.detail != null && event.detail.length > 0) {
                // @ts-ignore
                setProgress(event.detail);
            } else {
                console.log('No detail in progress-message event');
            }
        })

        document.addEventListener(STEP_MESSAGE, (event) => {
            // console.log('step-message event received', event);
            // @ts-ignore
            if (event.detail != null && event.detail.length > 0) {
                if (steps.length > 0) {
                    // @ts-ignore
                    if (steps.find(step => step === event.detail)) {
                        return;
                    }
                }
                
                // Create a new array with the new step added
                let newSteps = steps;   // Add to existing array, because it seems like there's a timing issue where this can be called multiple times before the state is updated
                // @ts-ignore
                newSteps.push(event.detail);
                setSteps(newSteps.slice());
            } else {
                console.log('No detail in step-message event');
            }
        })

        document.addEventListener(CLEAR_PROGRESS, (event) => {
            // console.log('clear-progress event received', event);
            setProgress('');
        })
        document.addEventListener(CLEAR_STEPS, (event) => {
            // console.log('clear-steps event received', event);
            
            // Remove all items from the array
            steps.splice(0, steps.length);

            // Set new array to empty
            setSteps([]);
        })
    }, [])

    return (
    <div>        
        {steps && steps.length > 0 &&
        <div className='steps-div'>
            <h5>Steps Taken:</h5>
            <ul className='steps-list'>
                {steps.map((step, index) => {
                    return <li key={index}>{step}</li>
                })}
            </ul>
        </div>
        }

        {progress_msg && progress_msg.length > 0 &&
        <div className='progress-div'>
            <h5>Currently:</h5>
             {progress_msg}
        </div>}

    </div>
    );
}

export default RightPanel;