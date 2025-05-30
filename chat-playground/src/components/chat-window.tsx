import ReactWebChat from 'botframework-webchat';
import { useState, useEffect, useRef } from 'react';
import { ApiClient } from '../service/api';
import { WebPubSubToWebChatWrapper } from '../utils/wrappedWebsocket'
import { MessageDelta, DELTA_STATUS_CAPTURING, DELTA_STATUS_EXPIRED } from '../data/delta-message';
import chatStyleOptions from './chat-style-options';
import './chat-window.css';

import { CLEAR_STEPS, CLEAR_PROGRESS, STEP_MESSAGE, PROGRESS_MESSAGE,  METADATA_LEVEL_CHANGED, SENTIMENT_UPDATE } from '../data/events';
import { text } from 'stream/consumers';

const messageDelta = new MessageDelta();

function ChatWindow({apiClient}: {apiClient:ApiClient}) {
    // const [apiClient] = useState(new ApiClient());
    const [eventsRegistered, setEventsRegistered] = useState(false);
    const [threadId, setThreadId] = useState('');
    const [directLine, setDirectLine] = useState(null);
    const [apiFailing, setApiFailing] = useState(0);
    const renderMetadataLevel = useRef(parseInt(localStorage.getItem('metadata-level') || '2'));

    const create_ajax_wrapper = (ajax:Function, subscriptionKey:string|null) => {
        let extraHeaders = {};

        

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

    const handleMetadataLevelChanged = (event: Event): void => {
      // @ts-ignore
      if (event.detail != null && event.detail != null) {
        // @ts-ignore
        let level = event.detail;
        if (level == null) {
          level = 2;
        } else if (typeof(level) == 'string') {
          level = parseInt(level);
        }
        
        renderMetadataLevel.current = level;
      }
    };
    

    useEffect(() => {
        if (apiClient == null) {
            return;
        }

        // Register the event listeners
        document.addEventListener('display-notification', handleDisplayNotificationEvent);
        document.addEventListener(METADATA_LEVEL_CHANGED, handleMetadataLevelChanged);



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
            activity.text = textWithoutRefs(messageDelta.full.trim());
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
      } else if (activity.name == "sentiment") {
          document.dispatchEvent(new CustomEvent(SENTIMENT_UPDATE, { bubbles: true, detail: activity.value }));
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
              SpeechSynthesisUtterance: speechServicesPonyfill.SpeechSynthesisUtterance
              // (speech:string) => {
              //   speak(speech, 'en-AU');
              // }
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

    const textWithoutRefs = (text:string) => {
      if (renderMetadataLevel.current >= 2) {
        return text;
      } else {
        if (!text) {
          return '';
        } else {
          return text.replace(/(\[Ref\:.*?\])/g, '');
        }
      }
    };


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

                    // Remove references from the text (if the renderMetadataLevel is set to not render references)
                    activity.text = textWithoutRefs(activity.text);

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
    
                    {renderMetadataLevel.current >= 2 && card.activity.entities && card.activity.entities.find((e:any) => e.type == "citations") && <div>
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

        if (renderMetadataLevel.current == 0) {
          return <span />
        }

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
            if (renderMetadataLevel.current < 2) {
              continue;
            }

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
          } else if (key == "interim_responses") {
            output.push(
              <div key={"metadata-" + key}>
              <button
                onClick={() => {
                const dialog = document.createElement('div');
                dialog.style.position = 'fixed';
                dialog.style.top = '50%';
                dialog.style.left = '50%';
                dialog.style.transform = 'translate(-50%, -50%)';
                dialog.style.width = '80%';
                dialog.style.height = '60%';
                dialog.style.overflowY = 'scroll';
                dialog.style.backgroundColor = 'white';
                dialog.style.border = '1px solid #ccc';
                dialog.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
                dialog.style.padding = '20px';
                dialog.style.zIndex = '1000';

                const closeButton = document.createElement('button');
                closeButton.textContent = 'Close';
                closeButton.style.position = 'absolute';
                closeButton.style.top = '10px';
                closeButton.style.right = '10px';
                closeButton.onclick = () => document.body.removeChild(dialog);

                const content = document.createElement('div');
                metadata[key].forEach((interim: any) => {
                  const interimDiv = document.createElement('div');
                  interimDiv.style.marginBottom = '10px';
                  let txtContent = interim.replace(/\\n/g, '\n');
                  let txtTitle = "Agent";
                  if (txtContent.startsWith("[")) {
                    // Take the first line as the title, and the rest as the content
                    txtTitle = txtContent.substring(1, txtContent.indexOf("\n")-1).trim();
                    txtContent = txtContent.substring(txtContent.indexOf("\n")+1).trim();
                  }
                  interimDiv.innerHTML = `<b>${txtTitle}:</b><br/>`;
                  interimDiv.innerHTML += txtContent;
                  interimDiv.style.border = '1px solid #ccc';
                  interimDiv.style.padding = '10px';
                  interimDiv.style.backgroundColor = '#c5c5c5';
                  interimDiv.style.borderRadius = '5px';
                  interimDiv.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.1)';
                  interimDiv.style.maxWidth = '100%';
                  interimDiv.style.whiteSpace = 'pre-wrap';
                  interimDiv.style.overflowWrap = 'break-word';
                  interimDiv.style.fontFamily = 'monospace';
                  content.appendChild(interimDiv);
                });

                dialog.appendChild(closeButton);
                dialog.appendChild(content);
                document.body.appendChild(dialog);
                }}
              >
                Group Chat Messages
              </button>
              </div>
            );
          } else {
            output.push(<div key={"metadata-"+key}><b>{key}</b>{JSON.stringify(metadata[key])}</div>);
          }
        }
  
        return output;
      }

      const typingMiddleware = () => (next:any) => ({ activeTyping }: { activeTyping: any }) => {
        activeTyping = Object.values(activeTyping);
        return (
          !!activeTyping.length && (
            <span className="webchat__typing-indicator">
              <img src="typing.svg" alt="Typing" />
            </span>
          )
        );
      };

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
            typingIndicatorMiddleware={typingMiddleware}
          />
    } else {
        return <div>Unknown State</div>
    }
}

export default ChatWindow;
