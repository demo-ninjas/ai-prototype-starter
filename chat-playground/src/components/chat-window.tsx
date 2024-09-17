import ReactWebChat from 'botframework-webchat';
import { useState, useEffect } from 'react';
import { ApiClient } from '../service/api';
import { WebPubSubToWebChatWrapper } from '../utils/wrappedWebsocket'
import { MessageDelta, DELTA_STATUS_CAPTURING, DELTA_STATUS_EXPIRED } from '../data/delta-message';
import chatStyleOptions from './chat-style-options';
import './chat-window.css';

import { CLEAR_STEPS, CLEAR_PROGRESS, STEP_MESSAGE, PROGRESS_MESSAGE, ORCHESTRATOR_SELECTED } from '../data/events';

const messageDelta = new MessageDelta();

function ChatWindow({apiClient}: {apiClient:ApiClient}) {
    // const [apiClient] = useState(new ApiClient());
    const [eventsRegistered, setEventsRegistered] = useState(false);
    const [threadId, setThreadId] = useState('');
    const [directLine, setDirectLine] = useState(null);
    const [apiFailing, setApiFailing] = useState(0);

    const create_ajax_wrapper = (ajax:Function, subscriptionKey:string|null) => {
        let extraHeaders = {};

        // Subscribe to the route-selected event
        document.addEventListener(ORCHESTRATOR_SELECTED, async (event) => {
          // @ts-ignore
          if (event.detail != null && event.detail.length > 0) {
            // @ts-ignore
              let route = event.detail;
              if (typeof(route) === 'object') {
                  route = route['num'];
              }
              // set extra header for route
              // @ts-ignore
              extraHeaders['selected-route'] = route;
          }
        });

        return (options:any) => {
          let headers = options.headers || {};
          
          // Add extra headers to the request
          headers = { ...headers, ...apiClient.headers, ...extraHeaders };
          
          return ajax({ ...options, headers });
        };
    };

    const create_ws_wrapper = (threadId:string, subscriptionKey:string|null, reconnectFunction:Function|null, startConversationFunction:Function|null) => {
        return function (url:string) {
            return new WebPubSubToWebChatWrapper(url, threadId, subscriptionKey, reconnectFunction, startConversationFunction);
        }
    }

    const handleDisplayNotificationEvent = (event: Event): void => {
      // @ts-ignore
      if (event.detail != null && event.detail != null) {
        // @ts-ignore
        let level = event.detail.level || 'info';
        // @ts-ignore
        let message = event.detail.message || '';
        // @ts-ignore
        let duration = event.detail.duration || 5000;
        let id = new Date().getTime();

        // Trigger the notification to be displayed
        // @ts-ignore
        store.dispatch({
          type: 'WEB_CHAT/SET_NOTIFICATION',
          payload: {
            id: id,
            level: level,
            message: message
          }
        });

        // Schedule the notification to be dismissed
        setTimeout(() => {
          // @ts-ignore
          store.dispatch({
            type: 'WEB_CHAT/DISMISS_NOTIFICATION',
            payload: {
              id: id
            }
          });
        }, duration);
      }
    };

    useEffect(() => {
        if (apiClient == null) {
            return;
        }

        // Register the event listeners
        document.addEventListener('display-notification', handleDisplayNotificationEvent);


      (async () => {
          // Connect to the API and get the threadId for this conversation
          let threadId = '';
          
          try {
              threadId = await apiClient.connect();
              if (threadId == null || threadId.length == 0) {
                  throw new Error("Failed to connect to the API - no thread created by the API");
              }
              setThreadId(threadId);
          } catch (error) {
              console.error("Failed to connect to the API - perhaps it's not available at the moment?!", error);
              setApiFailing(1);
              while (true) {
                await new Promise(resolve => setTimeout(resolve, 2000));
                try {
                  await apiClient.connect();
                  setApiFailing(2);
                  return;
                } catch (error) { }
              }
          }
        
          // Setup the Speech Factory for the WebChat
          await setupSpeechFactory(apiClient.speechKey, apiClient.speechRegion);
          

          // Create Direct Line Client
          // @ts-ignore
          let dl = window.WebChat.createDirectLine({
              conversationId: threadId,
              streamUrl: apiClient.stream,
              token: '1',
              domain:apiClient.directLineUrl,
          });
          
          // If there is a subscription key that needs to be presented to the API, then wrap the ajax function to include it
          if (apiClient.subscriptionKey) {
              // @ts-ignore
              dl.services.ajax = create_ajax_wrapper(dl.services.ajax, apiClient.subscriptionKey);
              // @ts-ignore
              dl.services.subscriptionKey = apiClient.subscriptionKey;
          } else {
              // @ts-ignore
              dl.services.ajax = create_ajax_wrapper(dl.services.ajax, null);
          }

          // Subscribe to the connection status so we can re-connect when needed
          if (dl.connectionStatus$) {
              // @ts-ignore
              dl.connectionStatus$.subscribe(async connectionStatus => {
              //   console.log("Connection Status Updated:", connectionStatus);
                if (connectionStatus === 3) {
                  // Connection has been lost - attempt to reconnect
                  console.log("Trying to reconnect...");
                  let threadId = await apiClient.connect();
                  console.log("Reconnected to thread:", threadId);
                  dl.reconnect({ conversationId: threadId, streamUrl: apiClient.stream, token: '' });
                }
              });
            }
    
            // @ts-ignore
            setDirectLine(dl);

            // Focus the chat input
            setTimeout(() => {
              let input = document.querySelector('textarea[aria-label="Message input box"]');
              if (input) {
                // @ts-ignore
                input.focus();
              }
            }, 100);
      })();
    }, [ ]);

    const onEventFromDirectLine = (activity:any, dispatch:any): void => {
      if (activity.name === 'interim') {
        if (messageDelta.isEmpty()) {
            // This is a new delta message
            messageDelta.addDelta(activity.value.delta);
            messageDelta.status = DELTA_STATUS_CAPTURING;
            messageDelta.id = activity.id;
        } else if (messageDelta.id === activity.id) {
            // This is a continuation of the current delta message
            messageDelta.addDelta(activity.value.delta);
        } else {
            // New interim message without a message activity, so let's assume it's a new message and clear the old one
            messageDelta.setExpired();
            messageDelta.reset();
            messageDelta.addDelta(activity.value.delta);
            messageDelta.status = DELTA_STATUS_CAPTURING;
            messageDelta.id = activity.id;
        }
        
        // Now, update the activity 
        if (messageDelta.status === DELTA_STATUS_CAPTURING) {
            activity.text = messageDelta.full.trim();
            activity.speak = false;
            activity.from.role = 'bot';
            activity.type = 'message';
            activity.id = messageDelta.id;
        }
      } else if (activity.name === "progress") {
          // If we've recieved a progress event, then convert it to a typing event and publish the progress message
          activity.type = "typing";
          
          if (activity.value && activity.value.message) {
            // console.log("Dispatching Progress Message:", activity);
              document.dispatchEvent(new CustomEvent(PROGRESS_MESSAGE, { bubbles: true, detail: activity.value.message }));
          }
      } else if (activity.name === "step") {
          // If we've recieved a step event, then publist the step message
          // console.log("Dispatching Step Message:", activity.value.message);
          if (activity.value && activity.value.message) {
              let msg = activity.value.message;
              if (msg.startsWith("Executing step: ")) {
                  msg = msg.substring("Executing step: ".length);
              }
              document.dispatchEvent(new CustomEvent(STEP_MESSAGE, { bubbles: true, detail: msg }));
          }
      }
    };


    const setupSpeechFactory = async (speechKey:string, speechRegion:string) => {
        // Setup Speech Service Credentials Loader...
      const credential_loader = function() {
        let current_creds = {
              authorizationToken: speechKey,
              region: speechRegion
            };
        
        let expireAfter = Date.now() + 300000; // Require refresh after 5mins
        return async () => {
          const now = Date.now();
          if (now > expireAfter) {
            expireAfter = now + 300000; // Require refresh after 5mins
            
            let new_creds = await apiClient.getSpeechToken();
            if (new_creds) {
              current_creds = {
                authorizationToken: new_creds.authorizationToken,
                region: new_creds.region
              };
            }
          }

          return current_creds;
        };
      }

      // Setup the Speech Factory
      if (speechKey == null || speechRegion == null) {
        console.log("Speech Disabled, not currently available...");
        // @ts-ignore
        window.__speechfactory = undefined
      } else {
        // @ts-ignore
        const speechServicesPonyfillFactory = await window.WebChat.createCognitiveServicesSpeechServicesPonyfillFactory({  credentials:credential_loader() } );
        // @ts-ignore
        const webSpeechPonyfillFactory = await window.WebChat.createBrowserWebSpeechPonyfillFactory();
        // @ts-ignore
        window.__speechfactory = options => {
            const speechServicesPonyfill = speechServicesPonyfillFactory(options);
            const webSpeechPonyfill = webSpeechPonyfillFactory(options);
            
            let service = {
              SpeechGrammarList: webSpeechPonyfill.SpeechGrammarList,
              SpeechRecognition: webSpeechPonyfill.SpeechRecognition,
              speechSynthesis: {
                cancel:() => {}, 
                getVoices: () => [],  
                pause: () => {}, 
                resume: () => {}, 
                speak: (e:any) => {}, 
                speaking: () => false,
                addEventListener: (e:any) => {},
                removeEventListener: (e:any) => {}
              },
              SpeechSynthesisUtterance: (speech:string) => {
                speak(speech, 'en-AU');
              }
            };

            // @ts-ignore
            window.__ss = speechServicesPonyfill.speechSynthesis;
            // @ts-ignore
            window.__su = speechServicesPonyfill.SpeechSynthesisUtterance;

            return service;
          };
      }
    };

    const speak = (msg:string, lang:string) => {
      if (!msg || msg.trim().length == 0) {
        return;
      }

      // @ts-ignore
      if (!window.__should_speak) {
        return
      }

      // @ts-ignore
      if (!window.__ss) {
        // @ts-ignore
        window.__speechfactory({})
      }

      // @ts-ignore
      let utterance = new window.__su(msg.trim());

      // If lang is not set, then default to en-AU
      if (!lang || lang.trim().length == 0) {
        lang = 'en-AU';
      }

      // @ts-ignore
      let voiceList = window.__ss.getVoices();

      // Print voice names + langs to console
      if (apiClient.isDebug) {
        // @ts-ignore
        if (!window.__printed_voices) {
          // @ts-ignore
          window.__printed_voices = true;  
          console.log("Available Voices:");
          let printArr: { [key: string]:string[] } = {};
          voiceList.forEach((voice:any) => {
            let bPos = voice.name.indexOf("(");
            let name = voice.name;
            if (bPos > -1) {
              name = name.substring(bPos+1, name.length-1).trim();
              name = name.substring(name.indexOf(",")+1).trim();
            }

            let langArr = printArr[voice.lang];
            if (!langArr) {
              langArr = [];
              printArr[voice.lang] = langArr;
            }
            langArr.push(`${name} (${voice.gender})`);
          });
          
          for (let lang in printArr) {
            console.log(`\n${lang}:`, printArr[lang]);
          }
        }
      }

      let voices = voiceList.filter((voice:any) => voice.lang.toLowerCase().startsWith(lang.toLowerCase()));
      let voice = null;

      // @ts-ignore
      if (window.__speaker_voice && window.__speaker_voice.length > 0) {
        // Attempt to find the requested voice in the list of voices
        // @ts-ignore
        voices = voiceList.filter((voice:any) => voice.name.indexOf(window.__speaker_voice) > -1);
        if (voices.length == 0) {
          // @ts-ignore
          voices = voiceList.filter((voice:any) => voice.name.toLowerCase().indexOf(window.__speaker_voice.toLowerCase()) > -1);
        }

        if (voices.length > 0) {
          voice = voices[0];
        }
      }

      if (voice == null) {
        if (voices.length == 0) {
          voices = voiceList.filter((voice:any) => voice.lang.toLowerCase().indexOf(lang) > -1);
        }
        if (voices.length == 0) {
          voices =  voiceList.filter((voice:any) => voice.lang == 'en-AU');
        }
        if (voices.length == 0) {
          voices =  voiceList.filter((voice:any) => voice.lang == 'en-US');
        }

        voice = voices.find((voice:any) => voice.name.indexOf('Kim') > -1);
        if (typeof(voice) == undefined || voice == null) {
          voice = voices.find((voice:any) => voice.gender == 'Female');
        }
        if (typeof(voice) == undefined || voice == null) {
          voice = voices[0];
        }
      }

      utterance.voice = voice;
      if (apiClient.isDebug) {
        console.log("Utterance:", utterance);
      }
      // @ts-ignore
      window.__ss.speak(utterance);
    }


    // @ts-ignore
    const store = window.WebChat.createStore({},
        // @ts-ignore
        ({ dispatch }) => next => action => {
            if (action.type === 'DIRECT_LINE/CONNECT') {
              // We're about to connect to the direct line, but first we need to wrap the Websocket object to handle translation from WebPubSub payloads
              action.payload.directLine.services.WebSocket = create_ws_wrapper(threadId, apiClient.subscriptionKey, apiClient.reconnect.bind(apiClient), apiClient.startConversation.bind(apiClient));
            } else if (action.type === 'DIRECT_LINE/POST_ACTIVITY') {
              // console.log("POST ACTION:", action);
            // } else if (action.type === 'WEB_CHAT/SET_NOTIFICATION') {
              // console.log("Setting Notification:", action.payload);
            } else if (action.type === 'WEB_CHAT/SEND_MESSAGE') {
                // Reset the Delta Message Object
                // console.log("Dispatching Clear Steps Message");
                document.dispatchEvent(new Event(CLEAR_STEPS, { bubbles: true }));
                messageDelta.reset();
            } else if (action.type === 'DIRECT_LINE/INCOMING_ACTIVITY') {
                let activity = action.payload.activity;

                // If we've recieved an event from the bot, and it's an interim result, then display it's delta as a message
                if ( (activity.from.role === 'bot' || activity.from.role === 'assistant') && activity.type === 'event') {
                  onEventFromDirectLine(activity, dispatch);
                } else if ( (activity.from.role === 'bot' || activity.from.role === 'assistant') && activity.type === 'message') {
                    // Post message to clear progress messages
                    // console.log("Dispatching Clear Progress Message");
                    document.dispatchEvent(new Event(CLEAR_PROGRESS, { bubbles: true }));

                    // If the message is a speak message, then speak it
                    if (activity.speak && activity.speak.length > 0 && activity.text.trim().length > 0) {
                      // console.log("Speaking: [" + activity.lang + "]:", activity.text.trim());
                      speak(activity.speak.trim(), (activity.lang || "").trim());
                    }
                }
            }
            
            return next(action);
        }
    );

    if (apiClient) {
      apiClient.store = store;
    }

    // @ts-ignore
    const activityMiddleware = () => next => (...setupArgs) => {
        const [card] = setupArgs;
        
        // Ignore cards without an activity
        if (!card.activity) {
          return next(...setupArgs);
        }
  
        // Ignore messages from the bot that are marked as expired (these are the delta messages that have been replaced by the final message)
        if (card.activity.from.role === DELTA_STATUS_EXPIRED) {
          return false;
        }
  
        // Ignore non-message activities
        if (card.activity.type !== 'message') {
          return next(...setupArgs);
        }
  
        // Ignore expired messages (aka. Accumulated interim messages that have expired due to a final message being sent)
        if (card.activity.id === messageDelta.id && messageDelta.isExpired()) {
          card.activity.from.role = DELTA_STATUS_EXPIRED;
          messageDelta.clearExpired(card.activity.id);
          return false;
        } else if (MessageDelta.isMessageExpired(card.activity.id, messageDelta)) {
            card.activity.from.role = DELTA_STATUS_EXPIRED;
            messageDelta.clearExpired(card.activity.id);
            return false;
        } else if (card.activity.steps || (card.activity.entities && card.activity.entities.length > 0)) {
            // @ts-ignore
            return (...renderArgs) => (
                <div>
                    {next(...setupArgs)(...renderArgs)}
                    <div className="card-metadata">
                    {card.activity.steps && card.activity.steps.length > 0 && <div>
                        <b>Plan:</b>
                        <ul className='card-metadata-list'>
                            {card.activity.steps.map((step:any, index:any) => (
                            <li key={index}>
                                {step}
                            </li>
                            ))}
                        </ul>
                        </div>

                    }
    
                    {card.activity.entities 
                        && card.activity.entities.find((e:any) => e.type == "metadata") 
                        && renderCardMetadata(card.activity.entities.find((e:any) => e.type == "metadata")['metadata'])}
    
                    {card.activity.entities && card.activity.entities.find((e:any) => e.type == "citations") && <div>
                        <b>Citations:</b><br/>
                        {card.activity.entities.find((e:any) => e.type == "citations")['citations'].map((citation:any) => (
                        <div key={citation.id}>
                            <pre>{JSON.stringify(citation, null, 4)}</pre>
                        </div>
                        ))}
                        </div>
                    }
    
                    </div>
                </div>
            );
        }
  
        return next(card)
    };


    const renderCardMetadata = (metadata:any) => {
        if (!metadata) { ( <span /> ) }
  
        let output = [];
        for (let key in metadata) {
          if (key == "steps") {
            output.push(<div key={"metadata-"+key}>
              <b>Plan:</b><ul className='card-metadata-list'>
              {metadata[key].map((step:any, index:any) => (
                <li key={index}>
                  {step}
                </li>
              ))}
              </ul>
            </div>)
          } else if (key == "citations") {
            output.push(<div key={"metadata-"+key}>
              <b>Citations:</b><br/>
              {metadata[key].map((citation:any) => (
                <div key={citation.id}>
                  <pre>{JSON.stringify(citation, null, 4)}</pre>
                </div>
              ))}
            </div>)
          } else if (key == "responder") {
            output.push(<div key={"metadata-"+key}>
              <b>Responder:</b>{metadata[key]}
            </div>)
          } else {
            output.push(<div key={"metadata-"+key}><b>{key}</b>{JSON.stringify(metadata[key])}</div>);
          }
        }
  
        return output;
      }

    if (directLine == null) {
        return <>
          <div>Waking up the Chat Playground...</div>
          {apiFailing == 1 && <div className='api-failing-div'>API is not available at the moment - will keep trying to connect every few seconds</div>}
          {apiFailing == 2 && <div className='api-returned-div'>API is now available - refresh the page when you're ready</div>}
        </>
    } else if (directLine) {
        return <ReactWebChat 
            key={threadId} 
            directLine={directLine} 
            activityMiddleware={activityMiddleware}
            styleOptions={chatStyleOptions}
            locale='en-AU' 
            store={store} 
            // @ts-ignore
            streamUrl={apiClient.stream} 
            // @ts-ignore
            webSpeechPonyfillFactory={window.__speechfactory}
          />
    } else {
        return <div>Unknown State</div>
    }
}

export default ChatWindow;
