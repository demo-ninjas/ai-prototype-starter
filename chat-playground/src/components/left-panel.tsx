import React, { useState, useEffect, MouseEventHandler } from 'react';
import './left-panel.css';
import { ApiClient } from '../service/api';

import { ORCHESTRATOR_LIST, ORCHESTRATOR_SELECTED } from '../data/events';

function LeftPanel({apiClient}: {apiClient:ApiClient}) {
    const [orchestrators, setOrchestrators] = useState([]);
    const [selectedOrchestrator, setSelectedOrchestrator] = useState({ 'name':'', 'description':'', 'pattern':'' });

    useEffect(() => {
        document.addEventListener(ORCHESTRATOR_LIST, (event) => {
            // @ts-ignore
            setOrchestrators(event.detail);
        });

        document.addEventListener(ORCHESTRATOR_SELECTED, (event) => {
            // @ts-ignore
            let orchestrator = event.detail;
            if (typeof(orchestrator) == 'string') {
                let orchestrator_list = orchestrators;
                if (orchestrators.length == 0) {
                    // @ts-ignore
                    orchestrator_list = apiClient.orchestrators;
                }
                let found_orchestrator = orchestrator_list.find((o:any) => o['name'] === orchestrator);
                if (found_orchestrator) {
                    setSelectedOrchestrator(found_orchestrator);
                } else {
                    console.log("Selected Orchestrator not found in the orchestrator list, adding it", orchestrator_list);
                    setSelectedOrchestrator({ 'name': orchestrator, 'description':'Private Orchestrator', 'pattern':'Unspecified' });
                }
            } else {
                setSelectedOrchestrator(orchestrator);
            }

            // Save to local storage
            if (orchestrator && orchestrator['name']) {
                localStorage.setItem('orchestrator', orchestrator['name']);
            }
        });
    }, []);

    return (
        <div>
            {orchestrators && orchestrators.length > 0 && <>
                <h3>Orchestrators</h3>
                <ul>
                    {orchestrators.map((orchestrator, index) => {
                        return <li key={index} className={ getOrchestratorItemClassName(orchestrator) } onClick={() => {
                            let event = new CustomEvent(ORCHESTRATOR_SELECTED, { detail: orchestrator });
                            document.dispatchEvent(event);
                        }}>
                            <b>{orchestrator['name']}</b>
                             {selectedOrchestrator && selectedOrchestrator['name'] == orchestrator['name'] && <>
                                <br/>
                                <p>{selectedOrchestrator['description'] || 'No Description'}</p>
                                <p>
                                    <b>Pattern:</b>&nbsp;
                                    {selectedOrchestrator['pattern'] || 'No Pattern Specified'}</p>
                            </>}
                        
                        </li>
                    })}
                </ul>
            </>}

           
        </div>
    );

    function getOrchestratorItemClassName(orchestrator: never): string | undefined {
        if (selectedOrchestrator['name'] == orchestrator['name']) { return 'orchestrator-selected'; }
        return '';
    }
}

export default LeftPanel;