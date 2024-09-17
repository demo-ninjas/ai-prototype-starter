export class WebPubSubToWebChatWrapper {
    url:string;
    subscriptionKey:string|null;
    threadId:string;
    ws:WebSocket;
    reconnectFunction:Function;
    startConversationFunction:Function|null;
    onmessage:Function|null = null;
    onerror:Function|null = null;
    onopen:Function|null = null;
    onclose:Function|null = null;
    _isReconnect:boolean = false;

    constructor(url:string, threadId:string, subscriptionKey:string|null, reconnectFunction:Function|null, startConversationFunction:Function|null) {
      this.url = url;
      this.threadId = threadId;
      this.subscriptionKey = subscriptionKey;
      this.reconnectFunction = () => {
        this._isReconnect = true;
        if (reconnectFunction) {
            reconnectFunction();
        }
      };
      this.startConversationFunction = startConversationFunction;
      this.ws = new WebSocket(url, 'json.webpubsub.azure.v1');
      this.ws.onmessage = (msg:MessageEvent) => {
        // Capture the message, strip the WebPubSub elements and only pass the activities data to the WebChat client
        if (this.onmessage) {
          // Translate from WebPubSub message to WebChat activity message
          try {
            let msgData = JSON.parse(msg.data);
            if (msgData.group === threadId && msgData.data) {
              let clone:any = Object.assign({}, msg);
              if (!msgData.data.activities) {
                // Convert the data to an EVENT activity
                clone.data = JSON.stringify({
                  "activities": [
                    {
                      from: { role: 'bot' }, 
                      type: 'event',
                      value: msgData.data,
                      name:  msgData.data.type || 'progress',
                      id: msgData.data.id,
                      timestamp: Date.now()
                    }
                  ]
                })
              } else {
                // Stringify the activity data, as the WebChat client expects a string
                clone.data = JSON.stringify(msgData.data);
              }

              this.onmessage(clone);
            }
          } catch(e) {
            console.log("Error parsing incoming WS message, will ignore this message. Error:", e);
          }
        }
      }
      this.ws.onerror = (msg) => {
        console.log("Caught an error in the Websocket - will attempt to re-connect:", msg);
        
        // Attempt to reconnect          
        if (this.reconnectFunction) {
            this.reconnectFunction();
        }
        
        if (this.onerror) {
          this.onerror(msg);
        }
      }
      this.ws.onopen = (msg) => {
        // Because this is a WebPubSub, we now need to connect to a group - which is the threadId
        this.ws.send(JSON.stringify({type:"joinGroup",group:this.threadId,ackId:Date.now()}))
        
        if (this.onopen) {
          this.onopen(msg);
        }

        // Also, trigger starting the conversation (if the convo hasn't been started yet)
        if (!this._isReconnect && this.startConversationFunction) {
            this.startConversationFunction();
        }

        // If there is a sendbox, then set focus on it
        let send_div = document.querySelector('.webchat__send-box__main');
        if (send_div) {
          let txt = send_div.querySelector('input[type="text"]') as HTMLInputElement;
          if (txt) {
            txt.focus();
          }
        }
      }

      this.ws.onclose = (msg) => {
        if (this.onclose) {
          this.onclose(msg);
        }
      }
    }

    send(data:any) {
      if (!data) { return; }  // Don't send blank messages - it may cause a disconnect
      this.ws.send(data);
    }

    close() {
      this.ws.close();
    }

    addEventListener(event:string, callback:Function) {
      if (event === 'message') {
        this.onmessage = callback;
      } else if (event === 'error') {
        this.onerror = callback;
      } else if (event === 'open') {
        this.onopen = callback;
      } else if (event === 'close') {
        this.onclose = callback;
      } else { 
        console.log("Unexpected Event Listener added to Websocket Wrapper - will ignore it. Listener Event Type:", event);
      }
    }
  }
