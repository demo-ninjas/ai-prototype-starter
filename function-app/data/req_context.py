import os
import json 
import base64
from typing import Callable

import azure.functions as func

from aiproxy.data import ChatContext, ChatConfig, ChatMessage
from aiproxy.history import HistoryProvider
from aiproxy.streaming import StreamWriter, stream_factory
from aiproxy.functions import FunctionDef

from subauth import Subscription, get_subscription

DEFAULT_CONFIG_NAME = "default"
GLOBAL_TOKEN_KEYS = None


class _FakeRequest:
    headers:dict
    params:dict
    route_params:dict
    body:dict
    method:str
    sub_id:str
    url:str

    def __init__(self, data:dict = None) -> None:
        if data is None:
            self.headers = {}
            self.route_params = {}
            self.params = {}
            self.body = {}
            self.sub_id = None
            self.method = "POST"
            self.url = ""
        else: 
            self.headers = data.get('headers', {})
            self.params = data.get('params', {})
            self.route_params = data.get('route_params', {})
            self.body = data.get('body', {})
            self.method = data.get('method', "POST")
            self.sub_id = data.get("sub_id", None)
            self.url = data.get("url", "")

    
    def get_json(self) -> dict:
        return self.body


class ReqContext(ChatContext):
    req: func.HttpRequest = None
    body:dict = None
    body_bytes:bytes = None
    subscription:Subscription = None
    config:ChatConfig
    stream_id:str = None
    
    def __init__(self, req: func.HttpRequest = None, 
                 history_provider:HistoryProvider = None, 
                 subscription:Subscription = None,
                 function_args_preprocessor:Callable[[dict, FunctionDef, ChatContext], dict] = None
                 ) -> None:
        
        self.req = req
        if req is None: return

        ## Body must be parsed first, as it can be used to set other values
        self.__parse_req_body(req)

        ## Next, Load the Chat Config - as it can also be used to set other values
        self.__load_chat_config(req)

        ## Next, Load the User Information
        if subscription is None and type(req) == _FakeRequest and req.sub_id is not None:
            subscription = get_subscription(req.sub_id, False)
        self.subscription = subscription
        
        ## Then, Load the rest of the settings
        self.__load_stream_id(req)
        self.__load_bot_conversation_id(req)
        
        ## Finally, parse the context variable (if provided) - This must be done last as it can override some of the already loaded settings
        self.__load_chat_context(req)

        ## If the config has params that need to be added to metadata for saving to history, then add them to the metadata directly here so they can be saved
        if self.config is not None:
            mdp = self.config['metadata-params']
            if mdp is not None and len(mdp) > 0: 
                for key in mdp:
                    val = self.get_req_val(key, None)
                    if val is not None: 
                        self.set_metadata(key, val, transient=False)

        super().__init__(thread_id=self.thread_id, history_provider=history_provider, stream=self._load_stream_writer(), function_args_preprocessor=function_args_preprocessor)
    

    def to_json(self) -> dict:
        data = {}
        data["body"] = self.body
        data["method"] = self.req.method
        data["headers"] = { k:v for k,v in self.req.headers.items() if self.req.headers is not None }
        data["params"] = { k:v for k,v in self.req.params.items() }
        data["route_params"] = { k:v for k,v in self.req.route_params.items() }
        data["sub_id"] = self.subscription.id if self.subscription is not None else None
        data["url"] = self.req.url
        return data

    def from_json(data:dict) -> 'ReqContext':
        return ReqContext(_FakeRequest(data))
    

    @property
    def is_admin(self) -> bool:
        admin_users = os.environ.get('ADMIN_USERS', 'ai-chat-admin').split(',')
        if admin_users is None or len(admin_users) == 0: return False
        if len(admin_users) == 1 and admin_users[0] == '__ALL__': return True
        return self.user_id in admin_users

    @property
    def user_id(self) -> str:
        if self.subscription is None:
            return None
        if self.subscription.is_entra_user:
            return self.subscription.entra_username
        if self.subscription.id is not None:
            return self.subscription.id
        return None

    @property
    def user_name(self) -> str:
        if self.subscription is None:
            return None
        if self.subscription.is_entra_user and self.subscription.entra_user_claims is not None:
            return self.subscription.entra_user_claims.get("name", self.subscription.entra_username)
        if self.subscription.name is not None:
            return self.subscription.name
        return None

    def clone_for_single_shot(self, with_streamer:bool = False) -> 'ReqContext':
        ctx = ReqContext()
        ctx.req = self.req
        ctx.body = self.body
        ctx.subscription = self.subscription
        ctx.config = self.config
        ctx.stream_writer = self.stream_writer if with_streamer else None
        ctx.metadata = self.metadata.copy() if self.metadata is not None else None
        ctx.metadata_transient_keys = self.metadata_transient_keys
        ctx.function_args_preprocessor = self.function_args_preprocessor
        ctx.function_filter = self.function_filter
        return ctx
    
    def clone_for_thread_isolation(self, thread_id_to_use:str = None, with_streamer:bool = False) -> 'ReqContext':
        ctx = ReqContext()
        ctx.req = self.req
        ctx.body = self.body
        ctx.subscription = self.subscription
        ctx.config = self.config
        ctx.stream_writer = self.stream_writer if with_streamer else None
        ctx.metadata = self.metadata.copy() if self.metadata is not None else None
        ctx.metadata_transient_keys = self.metadata_transient_keys
        ctx.function_args_preprocessor = self.function_args_preprocessor
        ctx.function_filter = self.function_filter
        ctx.history_provider = self.history_provider
        ctx.thread_id = thread_id_to_use
        return ctx
    
    def get_req_val(self, field:str, default_val:any = None) -> any:
        """
        Get a value from the body of the request, or return a default value if no value is provided for the field
        """

        val = None
        if self.body is not None: 
            val = self.body.get(field, None)
        if val is None and self.req is not None: 
            if val is None:
                val = self.req.params.get(field, None)
            if val is None:
                val = self.req.route_params.get(field, None)
            if val is None:
                val = self.req.headers.get(field, None)
            if val is None:
                val = self.req.headers.get(field.lower(), None)
            if val is None:
                val = self.req.headers.get(field.title(), None)
        return val if val is not None else default_val

    def has_config(self, config_field:str=None) -> bool:
        """
        Returns True if this context has a config object associated with it, unless config_field is specified, in which case it returns if the specific config field is specified.
        """
        if self.config is not None and config_field is not None: 
            return config_field in self.config

        return self.config is not None

    def get_config_value(self, config_field:str, default_value:any = None, fallback_to_env:bool = True) -> any:
        """
        Returns the config value as set in the config, otherwise, returns the default value (if no value is set in the config)
        """
        if not self.config: return default_value
        val = None
        if config_field in self.config:
            val = self.config[config_field]
        if  val is None:
            val = os.environ.get(config_field.upper(), None) if fallback_to_env else None
        return val if val is not None else default_value

    def build_context(self)->str:
        """
        Build a context string that can be provided by subsequent requests to this API to maintain a conversation's context (thread).

        The context string is a base64 encoded JSON object containing the contextual data needed to continue the conversation
        """
        data = dict()
        if self.thread_id is not None:
            data['t'] = self.thread_id
        
        ## TODO: Add any additional context that might be needed 
        return base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _unpack_context(self, context:str):
        """
        Unpacks the request context string (if provided) and sets the contextual data needed to continue an already active conversation
        """
        
        # Context is assumed to have been packed by the `build_context` method, essentially a b64 encoded json of the contextual data
        if context is None or len(context) == 0:
            ## Obviously, we need a better way of enabling conversastions to be re-joined - this is just a placeholder
            self.thread_id = self.get_req_val("thread") or self.get_req_val("thread-id") or self.get_req_val("conversation") or self.get_req_val("conversation-id") or self.get_req_val("conversation_id") or self.get_req_val("bot-conversation-id")
            if self.thread_id is not None and self.thread_id.lower() in [ "undefined", "none", "null", "new", ""]:
                self.thread_id = None
        else:  
            padded_context = context + '=='
            unpacked = base64.urlsafe_b64decode(padded_context.encode("utf-8"))
            data = json.loads(unpacked)
            self.thread_id = data.get('t',None)

    def __parse_req_body(self, req: func.HttpRequest):
         ## Grab the JSON body (if there is one)
        if req.method == "POST" or req.method == "PUT": 
            try: 
                self.body = req.get_json()
            except ValueError: 
                self.body = None ## If the body isn't JSON, ignore it

            try:
                self.body_bytes = req.get_body()
            except Exception: 
                self.body_bytes = None
        else: 
            self.body = None
            self.noddy_bytes = None

    def __load_chat_context(self, req: func.HttpRequest):
        """
        Loads the context for this request from the request headers, body, or query parameters
        """
         ## Get the context for this request (if there is one)
        context_sources = [
            req.route_params.get('context', None),
            req.headers.get('context', None),
            self.body.get('context', None) if self.body else None,
            req.params.get('context', None)
        ]
        context = next((ctx for ctx in context_sources if ctx and len(ctx) > 3), None)
        self._unpack_context(context)
    
    def __load_stream_id(self, req: func.HttpRequest):
        """
        Loads the Stream ID from the request headers, body, or query parameters
        """
        sources = [
            req.headers.get("stream-id", None),
            self.body.get("stream-id", None) if self.body else None,
            req.params.get("stream-id", None),
        ]
        val = next((key for key in sources if key is not None), None)
        self.stream_id = val
    
    def __load_bot_conversation_id(self, req: func.HttpRequest):
        """
        Loads the BotFramework Conversation ID from the request headers, body, or query parameters
        """
        sources = [
            req.headers.get("bot-conversation-id", None),
            self.body.get("bot-conversation-id", None) if self.body else None,
            req.params.get("bot-conversation-id", None),
        ]
        val = next((key for key in sources if key is not None), None)
        self.bot_conversation_id = val
    
    def __load_chat_config(self, req: func.HttpRequest):
        """
        Loads the Chat Config from the request headers, body, or query parameters
        """
        sources = [
            req.headers.get("config", None),
            req.headers.get("x-config", None),
            req.params.get("config", None),
            self.body.get("config", None) if self.body else None,
            DEFAULT_CONFIG_NAME ## Default Config
        ]
        val = next((key for key in sources if key is not None and len(key.strip()) > 2), None)
        if val is not None: 
            from aiproxy.data import ChatConfig
            self.config = ChatConfig.load(val)

    def _load_stream_writer(self) -> StreamWriter: 
        ## Initialize the Stream
        stream_type = self.get_config_value("stream-type", None)
        if stream_type is None and self.bot_conversation_id is not None:
            stream_type = "botframework"
        if stream_type is None and self.stream_id is not None:
            stream_type = "pubsub"

        if stream_type is None: return None
        return stream_factory(stream_type, stream_id=self.bot_conversation_id or self.stream_id or self.thread_id, config_name=self.get_config_value("stream-config", None))

    def get_metadata(self, key: str, default: any = None) -> any:
        val = self.get_req_val(key, None)
        if val is None and (key == 'bytes' or key == 'body' or key == 'body-bytes' or key == 'image-bytes'):
            val = self.body_bytes
        if val is None: 
            val = super().get_metadata(key, default)
        return val
    
    def parse_prompt_key(self, key: str) -> str:
        if key == 'user_name' or key == 'user': return self.user_name
        if key == 'user_id' or key == 'sub': return self.user_id
        if key == 'is_admin': return str(self.is_admin)
        return super().parse_prompt_key(key)
    
    def add_message_to_history(self, message:ChatMessage):
        message.add_metadata("_user_id", self.user_id)
        message.add_metadata("_user_name", self.user_name)
        super().add_message_to_history(message)