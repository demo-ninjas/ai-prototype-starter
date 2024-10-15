import os
import threading
from data import ReqContext
from aiproxy.data import ChatMessage
from aiproxy.streaming import stream_factory
from aiproxy.utils.date import now_millis

DEFAULT_WELCOME_MESSAGE = """Hello!

I'm {bot_name}, and I'm here to help you manage the operations on your route.

When you're ready, let's start chatting.
"""

DEFAULT_WELCOME_SPEECH = """Hello! I'm {bot_name}, and I'm here to help you. Let's start chatting!"""

DEFAULT_BOT_ORCHESTRATOR = os.environ.get("DEFAULT_BOT_ORCHESTRATOR", "default")
DEFAULT_BOT_TYPING_INTERVAL = os.environ.get("DEFAULT_BOT_TYPING_INTERVAL", "3")

class BotFrameworkActivity:
    activity_type:str = None
    id:str = None
    timestamp:str = None
    localTimestamp:str = None
    localTimezone:str = None
    channelId:str = None
    from_data:dict = None
    recipient:dict = None
    conversation:dict = None
    textFormat:str = None
    text:str = None
    speak:str = None
    inputHint:str = None
    replyToId:str = None
    locale:str = None
    entities:list = None
    channelData:dict = None
    attachments:list = None
    suggestedActions:dict = None

    def __init__(self) -> None:
        self.entities = []
        self.attachments = []
        self.channelData = {}


    def new_from_message(message:ChatMessage, conversation_id:str, bot_name:str, bot_id:str, bot_channel:str, context:ReqContext, increment:int = 0) -> 'BotFrameworkActivity':
        from aiproxy.utils.date import now_as_str
        activity = BotFrameworkActivity()
        activity.activity_type = "message"
        activity.id = conversation_id + '-' + str(increment)
        activity.timestamp = message.timestamp or now_as_str()
        activity.channelId = bot_channel
        activity.from_data = {
            "id":  context.user_id if message.role == "user" else bot_id,
            "name": context.user_name or context.user_id if message.role == "user" else bot_name,
            "role": message.role
        }
        activity.conversation = {
            "id": conversation_id
        }
        activity.textFormat = "markdown" if message.role in ["assistant", "bot" ] else "plain"
        activity.text = message.message
        activity.inputHint = "acceptingInput"
        activity.replyToId = conversation_id + "-" + str(increment - 1),
        return activity
    
    def new_text_message(conversation_id:str, bot_name:str, bot_id:str, bot_channel:str, message:str, speech:str = None) -> 'BotFrameworkActivity':
        from aiproxy.utils.date import now_as_str

        activity = BotFrameworkActivity()
        activity.activity_type = "message"
        activity.id = "1"
        activity.timestamp = now_as_str()
        activity.channelId = bot_channel
        activity.from_data = {
            "id": bot_id,
            "name": bot_name
        }
        activity.conversation = {
            "id": conversation_id
        }
        activity.textFormat = "markdown"
        activity.text = message
        if speech is not None:
            activity.speak = speech
        activity.inputHint = "acceptingInput"
        activity.replyToId = None
        return activity


    def from_dict(self, data:dict):
        self.activity_type = data.get("type")
        self.id = data.get("id")
        self.timestamp = data.get("timestamp")
        self.localTimestamp = data.get("localTimestamp")
        self.localTimezone = data.get("localTimezone")
        self.channelId = data.get("channelId")
        self.from_data = data.get("from")
        self.recipient = data.get("recipient")
        self.conversation = data.get("conversation")
        self.textFormat = data.get("textFormat")
        self.text = data.get("text")
        self.speak = data.get("speak")
        self.inputHint = data.get("inputHint")
        self.replyToId = data.get("replyToId")
        self.locale = data.get("locale")
        self.entities = data.et("entities") or []
        self.channelData = data.get("channelData") or {}
        self.attachments = data.get("attachments")
        self.suggestedActions = data.get("suggestedActions")
        return self
    
    def to_dict(self):
        return {
            "type": self.activity_type,
            "id": self.id,
            "timestamp": self.timestamp,
            "localTimestamp": self.localTimestamp or self.timestamp,
            "localTimezone": self.localTimezone,
            "channelId": self.channelId,
            "from": self.from_data,
            "recipient": self.recipient,
            "conversation": self.conversation,
            "textFormat": self.textFormat,
            "text": self.text,
            "speak": self.speak,
            "inputHint": self.inputHint,
            "replyToId": self.replyToId,
            "locale": self.locale, 
            "entities": self.entities, 
            "channelData": self.channelData,
            "attachments": self.attachments,
            "suggestedActions": self.suggestedActions
        }
        
class BotFrameworkActivityResponse: 
    activities: list[BotFrameworkActivity]
    watermark: str

    def __init__(self, activities:list[BotFrameworkActivity] = None, watermark:str = None) -> None:
        self.activities = activities or []
        self.watermark = watermark or str(now_millis())

    def new_with_activity(activity:BotFrameworkActivity, watermark:str = None) -> 'BotFrameworkActivityResponse':
        return BotFrameworkActivityResponse([activity], watermark)
    
    def new_with_activities(activities:list[BotFrameworkActivity], watermark:str = None) -> 'BotFrameworkActivityResponse':
        return BotFrameworkActivityResponse(activities, watermark)

    def from_dict(self, data:dict):
        self.activities = [BotFrameworkActivity().from_dict(activity) for activity in data.get("activities")]
        self.watermark = data.get("watermark")
        return self
    
    def to_dict(self):
        return {
            "activities": [activity.to_dict() for activity in self.activities],
            "watermark": self.watermark
        }

class BotframeworkFacade: 
    _context:ReqContext

    def __init__(self, context:ReqContext):
        import logging
        logging.info("Using config: " + str(context.get_config_value("name", context.get_config_value("id", "?"))))

        self._context = context
        self._context.init_history()


        ## Load the Stream Writer
        if self._context.stream_id is None:
            self._context.stream_id = self._context.thread_id
        self._context.stream_writer = stream_factory('pubsub', self._context.stream_id, self._context.get_config_value('stream-config'))

        self.bot_name = self._context.get_config_value("bot-name", "The Chat Playground")
        self.bot_id = self._context.get_config_value("bot-id", "chat-bot")
        self.bot_channel = self._context.get_config_value("bot-channel", "chat-bot")
        self.welcome_message = self._context.get_config_value("welcome-message", DEFAULT_WELCOME_MESSAGE).replace("{bot_name}", self.bot_name)
        self.welcome_speech = self._context.get_config_value("welcome-speech", DEFAULT_WELCOME_SPEECH).replace("{bot_name}", self.bot_name)
        self.typing_interval = int(self._context.get_config_value("typing-interval", DEFAULT_BOT_TYPING_INTERVAL))

    def send_start_activity(self):
        if not self._context.has_stream(): return
        if self._context.history is not None and len(self._context.history) > 0:
            ## Return the full history - sending one at a time now - we could consider sending the whole history in one go if it's not too big
            for idx,msg in enumerate(self._context.history):
                if msg.role not in ["user", "assistant"]: continue
                activity = BotFrameworkActivity.new_from_message(message=msg,context=self._context, increment=idx, conversation_id=self._context.thread_id, bot_name=self.bot_name, bot_id=self.bot_id, bot_channel=self.bot_channel)
                if msg.metadata is not None:
                    mdata = msg.metadata.copy()
                
                    ## Remove any system metadata (prefixed with '_')
                    keys = list(mdata.keys())
                    for key in keys:
                        if key.startswith("_"): mdata.pop(key)
                        if key == "speak": 
                            activity.speak = mdata.pop(key)

                    if len(mdata) > 0:
                        activity.entities.append({ "metadata": mdata, "type": "metadata" })

                if msg.citations is not None and len(msg.citations) > 0:
                    activity.entities.append({ "citations": [ citation.to_dict() for citation in msg.citations ], "type": "citations" })
                if msg.content is not None: 
                    activity.entities.append({ "content": msg.content, "type": "content" })

                resp = BotFrameworkActivityResponse.new_with_activity(activity)
                self._context.push_stream_update(resp.to_dict())
        else: 
            ## Send the start activity
            resp = BotFrameworkActivityResponse.new_with_activity(BotFrameworkActivity.new_text_message(conversation_id=self._context.thread_id, bot_name=self.bot_name, bot_id=self.bot_id, bot_channel=self.bot_channel, message=self.welcome_message, speech=self.welcome_speech))
            self._context.push_stream_update(resp.to_dict())

    def process_user_activity(self, prompt:str = None) -> bool:
        ## Process the user's activity message
        ## This is a requirement of the botframework's web client
        from uuid import uuid4
        from aiproxy.orchestration import orchestrator_factory
        from aiproxy.data import ChatConfig
        ## Grab Other Request Specific Settings
        use_functions = self._context.get_req_val("use-functions", 'true').lower() in ['true', 'yes', '1']
        timeout_secs = int(self._context.get_req_val("timeout", self._context.get_req_val("timeout-secs", "90")))

        ## Grab the channel data from the activity payload
        channel_data = self._context.get_req_val("channelData", {})

        ## Check if additional body params have been provided in the channel data
        override_orchestrator = None
        bparams = channel_data.get("bodyParams", None)
        if bparams is not None:
            if type(bparams) is str:
                import json
                bparams = json.loads(bparams)

            for key,val in bparams.items():
                if key == "orchestrator": 
                    ## Keep a record that we want to override the orchestrator ...
                    override_orchestrator = val
                    continue
                self._context.set_metadata(key, val)

        ## Get Selected Route from the header info
        selected_route = self._context.get_req_val("selected-route", "<None>")
        if selected_route is not None:
            self._context.set_metadata("selected-route", selected_route)

        ## Load the Orchestrator / Proxy to use for this request
        proxy = None
        try: 
            orchestrator_config = None
            orchestrator_name = override_orchestrator
            if orchestrator_name is None:
                orchestrator_name = channel_data.get("orchestrator", None)
            if orchestrator_name is None:
                orchestrator_name = self._context.get_req_val("orchestrator", None) or self._context.get_config_value("orchestrator", None)
            if orchestrator_name is None: 
                orchestrator_name = self._context.get_config_value("default-orchestrator", DEFAULT_BOT_ORCHESTRATOR)
                orchestrator_config = ChatConfig.load(orchestrator_name, False)
            else: 
                orchestrator_config = ChatConfig.load(orchestrator_name, False)

            if orchestrator_config is None: 
                ## Create a default Config
                orchestrator_config = self._context.config.clone()
                orchestrator_config['type'] = self._context.get_req_val("orchestrator-type", None) or self._context.get_config_value("orchestrator-type", None) or DEFAULT_BOT_ORCHESTRATOR
                orchestrator_config['name'] = orchestrator_name
                
            ## Load the Orchestrator/Proxy and send the message
            proxy = orchestrator_factory(orchestrator_config)
        except Exception as e: 
            import logging
            import traceback
            logging.error(f"Error loading orchestrator: {orchestrator_name}")
            logging.error(traceback.format_exc())

            self.send_error_activity()
            return False
            
        waiting_event = threading.Event()
        try: 
            msg_id = self._context.thread_id + "-" + uuid4().hex

            if self._context.get_config_value("maintain-typing", "true").lower() in ['true', 'yes', '1']:
                threading.Thread(target=self._send_typing_whilst_waiting, args=[msg_id, waiting_event], daemon=True).start()

            self.send_typing_activity()
            self._context.init_history()  ## Ensure that the history for this conversation has been loaded
            self._context.current_msg_id = msg_id
            resp = proxy.send_message(prompt, self._context, use_functions=use_functions, timeout_secs=timeout_secs, working_notifier=self.send_typing_activity)
            waiting_event.set()
            if resp.filtered:
                ## The response was filtered, so we don't want to send it
                activity = self.create_default_activity(id=msg_id)
                activity.text = "I'm sorry, but I can't respond to that message. Maybe try asking your question again?"
                activity_resp = BotFrameworkActivityResponse.new_with_activity(activity)
                self._context.push_stream_update(activity_resp.to_dict())
                return False
            elif resp.failed:
                ## The response failed, so we don't want to send it
                self.send_error_activity()
                return False
            else:
                ## The response was successful, so we want to send it
                activity = self.create_default_activity(id=msg_id)

                resp_type = resp.metadata.get("response-type", None) if resp.metadata is not None else None
                if resp_type is None:
                    resp_type = self._context.get_req_val("response-type", self._context.get_config_value("default-response-type", None))
                    if resp_type is not None:
                        resp.metadata["response-type"] = resp_type
                if resp_type is None:
                    resp_type = "text"
                
                resp_type = resp_type.lower().strip()
                if '/' in resp_type: 
                    resp_type = resp_type[resp_type.find('/')+1: ]
                if resp_type in ['json', 'yaml',  'adaptivecard', 'adaptive-card', 'card', 'vnd.microsoft.card.adaptive', 'html', 'xml' ]:
                    ## This is a structured response, so handle appropriately
                    import json
                    from aiproxy.functions.string_functions import extract_code_block_from_markdown
                    resp.message = extract_code_block_from_markdown(resp.message, return_original_if_not_found=True)

                    if resp_type in [ 'adaptive-card', 'adaptivecard', 'vnd.microsoft.card.adaptive','card' ]:
                        activity.attachments = [ { "contentType": "application/vnd.microsoft.card.adaptive", "content": json.loads(resp.message) } ]
                    elif resp_type == 'json': 
                        activity.attachments = [ { "contentType": "application/json", "content": json.loads(resp.message) } ]
                    elif resp_type == 'xml': 
                        activity.attachments = [ { "contentType": "application/xml", "content": resp.message } ]
                    elif resp_type == 'yaml': 
                        activity.attachments = [ { "contentType": "application/x-yaml", "content": resp.message } ]
                    elif resp_type == 'html': 
                        activity.attachments = [ { "contentType": "text/html", "content": resp.message } ]
                    else: 
                        activity.attachments = [ { "contentType": "application/" + resp_type, "content": resp.message } ]                                    
                else: 
                    ## The message is a plain text message
                    activity.text = resp.message

                
                activity.entities = []
                if resp.metadata is not None and len(resp.metadata) > 0:
                    speak = resp.metadata.get("speak", None) or resp.metadata.get("speech", None)
                    if speak is not None:
                        activity.speak = speak
                        if 'speak' in resp.metadata: del resp.metadata['speak']
                        if 'speech' in resp.metadata: del resp.metadata['speech']

                    filtered_metadata = resp.metadata.copy()
                    keys = list(filtered_metadata.keys())
                    for key in keys:
                        if key.startswith("_"): filtered_metadata.pop(key)
                    activity.entities.append({ "metadata": filtered_metadata, "type": "metadata" })
                if resp.citations is not None and len(resp.citations) > 0:
                    activity.entities.append({ "citations": [ citation.to_dict() for citation in resp.citations ], "type": "citations" })

                activity_resp = BotFrameworkActivityResponse.new_with_activity(activity)
                self._context.push_stream_update(activity_resp.to_dict())
                return True
        except Exception as e: 
            import logging
            import traceback
            logging.error(f"Error processing user activity: {e}")
            logging.error(traceback.format_exc())
            self.send_error_activity()
            return False
        finally: 
            waiting_event.set() ## Ensure that the waiting event is set to stop the typing activity

    def echo_user_activity(self):
        ## Echo the user's activity message back to them (via the stream) to ACK receipt of the message
        ## This is a requirement of the botframework's web client
        from aiproxy.utils.date import now_as_str

        activity = self.create_default_activity(timestamp=self._context.get_req_val("localTimestamp", now_as_str()))
        activity.from_data = self._context.get_req_val("from", {})
        activity.recipient = { "id": self.bot_id, "name": self.bot_name }
        activity.textFormat = self._context.get_req_val("textFormat", "plain")
        activity.text = self._context.get_req_val("text") or self._context.get_req_val("prompt")
        activity.entities = self._context.get_req_val("entities", [])
        activity.channelData = self._context.get_req_val("channelData", {})
        resp = BotFrameworkActivityResponse.new_with_activity(activity)
        self._context.push_stream_update(resp.to_dict())

    def send_suggestions(self):
        ## Process the user's activity message
        ## This is a requirement of the botframework's web client
        from uuid import uuid4
        from aiproxy.orchestration.agents import agent_factory
        from aiproxy.data import ChatConfig

        ## Load the suggestions agent
        agent_name = self._context.get_config_value("suggestions-agent", "suggestions")
        agent = agent_factory(agent_name)
        if agent is not None:
            try:
                result = agent.process_message("Provide the suggestions list", self._context)
                if result is not None and not result.failed:
                    suggestions = result.metadata.get("suggestions", [])
                    if len(suggestions) > 0:
                        suggestion_actions = [ { "type":"imBack", "title":action, "value":action } for action in suggestions ]
                        activity = self.create_default_activity()
                        activity.text = ""
                        activity.suggestedActions = { "actions": suggestion_actions }
                        activity_resp = BotFrameworkActivityResponse.new_with_activity(activity)
                        self._context.push_stream_update(activity_resp.to_dict())
            except Exception as e:
                import logging
                import traceback
                logging.error(f"Failed to generate suggestions, will ignore. Error: {e}")
                logging.error(traceback.format_exc())

        
    def _send_typing_whilst_waiting(self, msg_id, waiting_event:threading.Event):
        from time import sleep
        while not waiting_event.is_set():
            self.send_typing_activity(for_msg=msg_id)
            sleep(self.typing_interval)

    def send_typing_activity(self, for_msg:str = None):
        if not self._context.has_stream(): return
        activity = self.create_default_activity("typing", id=for_msg)
        resp = BotFrameworkActivityResponse.new_with_activity(activity)
        self._context.push_stream_update(resp.to_dict())

    def send_error_activity(self, message:str = None):
        if not self._context.has_stream(): return
        activity = self.create_default_activity()
        activity.text = message or "I'm sorry, but I had a bit of a problem processing your request. Maybe try asking your question again?"
        resp = BotFrameworkActivityResponse.new_with_activity(activity)
        self._context.push_stream_update(resp.to_dict())


    def send_message_activity(self, message:str = None):
        if not self._context.has_stream(): return
        activity = self.create_default_activity()
        activity.text = message or "I'm sorry, but I had a bit of a problem processing your request. Maybe try asking your question again?"
        resp = BotFrameworkActivityResponse.new_with_activity(activity)
        self._context.push_stream_update(resp.to_dict())


    def create_default_activity(self, activity_type:str = "message", id:str = None, timestamp:str = None) -> BotFrameworkActivity:
        from aiproxy.utils.date import now_as_str
        from uuid import uuid4

        if not self._context.has_stream(): return
        activity = BotFrameworkActivity()
        activity.activity_type = activity_type
        activity.id = id if id is not None else self._context.thread_id + "-" + uuid4().hex
        activity.timestamp = timestamp or now_as_str()
        activity.localTimestamp = timestamp or now_as_str()
        activity.localTimezone = "Australia/Sydney"
        activity.locale = "en-AU"
        activity.channelId = self.bot_channel
        activity.from_data = { "id": self.bot_id, "name": self.bot_name, "role": "bot" }
        activity.conversation = { "id": self._context.thread_id }
        if activity_type == "message":
            activity.textFormat = "markdown"
        return activity
