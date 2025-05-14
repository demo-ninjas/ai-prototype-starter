import { ORCHESTRATOR_LIST, ORCHESTRATOR_SELECTED, USER_STATE_CHANGED } from '../data/events';

const API_URL = '/api';

export const NOT_CONNECTED:number = 0;
export const CONNECTING:number = 1;
export const CONNECTED:number = 2;

export class ApiClient {
    debug:boolean = false;
    status:number = NOT_CONNECTED;
    thread:string = '';
    stream:string = '';
    orchestrators:string[] = [];
    selected_orchestrator:string = '';
    username:string = '';
    name:string = '';
    speechKey:string = '';
    speechRegion:string = '';
    
    store:any = null;
    headers:{ [key:string]:string } = {};
    queryParams:URLSearchParams = new URLSearchParams(window.location.search);

    constructor() {
        this.headers['Accept'] = 'application/json';

        // Add Subscription Key if it exists
        let subscriptionKey = this.queryParams.get('subscription');
        if (!subscriptionKey) {
            subscriptionKey = localStorage.getItem('subscription');
        } else {
            // Remove the subscription key from the URL
            localStorage.setItem('subscription', subscriptionKey);
            this.queryParams.delete('subscription');
            window.history.pushState(null, "", "?" + this.queryParams.toString());
        }

        if (subscriptionKey) {
            this.headers["subscription"] = subscriptionKey;
        }
        
        // Add Thread if it exists
        let thread = this.queryParams.get('thread');
        if (thread) {
            this.thread = thread;
        }

        this.debug = this.queryParams.get('debug') === 'true';
        document.addEventListener(ORCHESTRATOR_SELECTED, (event) => {
            // @ts-ignore
            let orchestrator = event.detail;
            if (typeof(orchestrator) == 'string') {
                this.selected_orchestrator = orchestrator;
            } else {
                this.selected_orchestrator = orchestrator['name'];
            }

            if (this.selected_orchestrator && this.selected_orchestrator.length > 0) {
                this.headers['orchestrator'] = this.selected_orchestrator;
            }
        });
    }

    get isDebug() : boolean {
        return this.debug;
    }

    get subscriptionKey() : string {
        return this.headers['subscription'] || '';
    }
    get directLineUrl() : string {
        return `${API_URL}/webchat`;
    }

    async reconnect() : Promise<string> {
        return this.connect();
    }

    async startConversation() : Promise<void> {
        let url = `${API_URL}/webchat/conversations?thread=${this.thread}`;
        await fetch(url, { method: 'POST', headers: this.headers });
    }
    

    async getSpeechToken() : Promise<any> {
        let url = `${API_URL}/speechtoken`;
        const response = await fetch(url, { headers: this.headers });
        const { authorizationToken, region } = await response.json();
        this.speechKey = authorizationToken;
        this.speechRegion = region;
        return { authorizationToken, region };
    }
    async loadOrchestrators() : Promise<string[]> {
        const response = await fetch(`${API_URL}/list-orchestrators`, { headers: this.headers });
        return await response.json();
    }

    async connect() : Promise<string> {
        if (this.status === CONNECTED) {
            return this.thread;
        } else if (this.status === CONNECTING) {
            return new Promise((resolve, reject) => {
                const interval = setInterval(() => {
                    if (this.status === CONNECTED) {
                        clearInterval(interval);
                        resolve(this.thread);
                    } else if (this.status === NOT_CONNECTED) {
                        clearInterval(interval);
                        reject('Failed to connect to the API');
                    }
                }, 256);
            });
        }

        this.status = CONNECTING;
        try {                    
            let connectUrl = `${API_URL}/connect`;
            if (this.thread) {
                connectUrl += `?thread=${this.thread}`;
            }

            // Connect to the API
            const connectBody = JSON.stringify({
                listorchestrators:true, 
                redirect:window.location.toString(), 
                redirectStatus:299
            });
            // @ts-ignore
            const response = await fetch(connectUrl, { method: 'POST', headers:{ ...this.headers }, cache: 'no-cache', body:connectBody });

            if (response.status !== 200) {
                this.status = NOT_CONNECTED;
                if (response.status == 299) {
                    let loc = response.headers.get('Location') || response.headers.get('location');
                    if (loc) {
                        console.log("Opening a window to authenticate");
                        let w = window.open(loc, "_self", "popup=true,width=800,height=600");
                        if (!w) {
                            // If the window was blocked, open in the same window
                            // @ts-ignore
                            window.location = loc;
                        } else {
                            w.onclose = () => { 
                                window.location.reload();
                            }
                            return "";
                        }
                    } else {
                        throw new Error("Not authorised to the API");
                    }
                } else {
                    throw new Error("Failed to connect to the API");
                }
            }

            const { thread, stream, speechKey, speechRegion, username, name, orchestrators } = await response.json();
            // TODO: Pull out any other data needed from the connect response
            this.thread = thread;
            this.stream = stream;
            this.orchestrators = orchestrators;
            this.username = username;
            this.name = name;
            this.speechKey = speechKey;
            this.speechRegion = speechRegion;

            this.status = CONNECTED;
            
            // Update the URL with the thread
            this.queryParams.set('thread', thread);
            window.history.pushState(null, "", "?" + this.queryParams.toString());

            // Check if there's an orchestrator query string, and select it
            let orchestratorParam = this.queryParams.get('orchestrator');
            if (!orchestratorParam) {
                orchestratorParam = localStorage.getItem('orchestrator');
            }
            if (orchestratorParam && orchestratorParam.length > 0) {
                // Check if the orchestrator is in the list
                if (!orchestrators.find((o:any) => o['name'] === orchestratorParam)) {
                    // Add the orchestrator to the list
                    orchestrators.push({
                        name:orchestratorParam, 
                        default: false, 
                        description: "Private Orchestrator",
                        pattern: "Custom",
                        requirements: null
                    }); 
                }

                this.selected_orchestrator = orchestratorParam;

                // Save to local storage
                localStorage.setItem('orchestrator', orchestratorParam);
            }

            // Post orchestrator list for other components to use
            document.dispatchEvent(new CustomEvent(ORCHESTRATOR_LIST, { detail: orchestrators }));

            // If there's an orchestrator selected, post it to the document
            if (this.selected_orchestrator && this.selected_orchestrator.length > 0) {
                document.dispatchEvent(new CustomEvent(ORCHESTRATOR_SELECTED, { detail: this.selected_orchestrator }));
            }


            // Notify that the username + name has been set
            document.dispatchEvent(new CustomEvent(USER_STATE_CHANGED, { detail: { username, name } }));

            return this.thread;
        } catch (error) {
            this.status = NOT_CONNECTED;
            console.error('Failed to connect to the API', error);
            throw new Error('Failed to connect to the API');
        }
    }
}