import azure.functions as func
import azure.durable_functions as df

import logging

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)
# app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

logging.getLogger("azure").setLevel(logging.ERROR) ## Only log the ERRORs from the azure libraries (some of which are otherwise quite verbose in their logging)

GLOBAL_HISTORY_PROVIDER = None
PUBLIC_ORCHESTRATOR_LIST = []

def build_public_orchestrator_list():
    global PUBLIC_ORCHESTRATOR_LIST

    from botframework import DEFAULT_BOT_ORCHESTRATOR
    from aiproxy.utils.config import load_public_orchestrator_list
    orchestrators = load_public_orchestrator_list()
    
    ## Add any additional orchestrators here that are not in the public list but you want to be available
    # orchestrators.insert(0, {
    #     "name": "Some Orchestrator Name",
    #     "description": "Chat with the this orchestrator",
    #     "pattern": "Completion",
    # })
    
    for orchestratror in orchestrators:
        orchestratror['default'] = orchestratror['name'] == DEFAULT_BOT_ORCHESTRATOR
    PUBLIC_ORCHESTRATOR_LIST = orchestrators
    return orchestrators

def setup_app():
    global GLOBAL_HISTORY_PROVIDER

    ## Register App Functions
    from aiproxy.functions import register_all_base_functions
    register_all_base_functions()

    ## Register locally implemented functions
    from functions import register_all_functions
    register_all_functions()

    ## Setup a global History Provider
    from aiproxy.history import CosmosHistoryProvider
    GLOBAL_HISTORY_PROVIDER = CosmosHistoryProvider()

    ## Load the Publish Orchestrator List
    build_public_orchestrator_list()

    print('App setup and ready to go!')

setup_app()



@app.function_name(name="refresh_config_cache")
@app.timer_trigger(schedule="0,20,40 * * * * *", arg_name="tm", run_on_startup=False) 
def refresh_config_cache(tm: func.TimerRequest) -> None:
    ## Refresh the configs in the config cache (every 20s)
    from aiproxy.utils.config import CACHED_CONFIGS, load_named_config
    try: 
        for k in CACHED_CONFIGS.keys():
            updated_val = load_named_config(k, False, False)
            if updated_val is not None:
                CACHED_CONFIGS[k] = updated_val
        
        ## Refresh the Orchestrator list
        build_public_orchestrator_list()

        ## Update the configs in each of the Orchestrators, Agents + Proxies
        from aiproxy import GLOBAL_PROXIES_REGISTRY
        GLOBAL_PROXIES_REGISTRY.reset()
        
        from aiproxy.orchestration.agents import reset_agents
        reset_agents()

    except Exception as e:
        print(f"Error refreshing cache: {e}")

@app.route(route="chat", methods=["POST", "GET"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER

    import json
    from aiproxy.orchestration import orchestrator_factory
    from aiproxy.data import ChatConfig
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401)
    if not valid: return login_redir

    ## Load the prompt for this request
    prompt = context.get_req_val("prompt", None)
    if prompt is None: 
        raise ValueError("No prompt specified")

    ## Check if there is a request specific system prompt to use
    override_system_prompt = determine_override_system_prompt(context)

    ## Grab Other Request Specific Settings
    use_functions = context.get_req_val("use-functions", 'true').lower() in ['true', 'yes', '1']
    timeout_secs = int(context.get_req_val("timeout", context.get_req_val("timeout-secs", "90")))

    ## Load the Orchestrator / Proxy to use for this request
    proxy = None
    try: 
        orchestrator_config = None
        orchestrator_name = None
        orchestrator_name = context.get_req_val("orchestrator", None) or context.get_config_value("orchestrator", None)
        if orchestrator_name is None: 
            orchestrator_name = context.get_config_value("default-orchestrator", "completion")
            orchestrator_config = ChatConfig.load(orchestrator_name, False)
        else: 
            orchestrator_config = ChatConfig.load(orchestrator_name, False)

        if orchestrator_config is None: 
            ## Create a default Config
            orchestrator_config = context.config.clone()
            orchestrator_config['type'] = context.get_req_val("orchestrator-type", None) or context.get_config_value("orchestrator-type", None) or 'completion'
            orchestrator_config['name'] = orchestrator_name
            
        ## Load the Orchestrator/Proxy and send the message
        proxy = orchestrator_factory(orchestrator_config)
    except Exception as e: 
        if 'unknown orchestrator' in str(e).lower():
            return func.HttpResponse(
                status_code=400,
                headers={
                    "reason": "Orchestrator Not Found",
                },
            )
        else:  
            raise e

    
    context.init_history()  ## Ensure that the history for this conversation has been loaded
    resp = proxy.send_message(prompt, context, override_system_prompt=override_system_prompt, use_functions=use_functions, timeout_secs=timeout_secs)

    return func.HttpResponse(
        body=json.dumps({
            "response": resp.to_api_response(), 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )

@app.route(route="completion", methods=["POST", "GET"])
def chat_completion(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER

    import json
    from aiproxy import CompletionsProxy, GLOBAL_PROXIES_REGISTRY
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401)
    if not valid: return login_redir

    proxy = GLOBAL_PROXIES_REGISTRY.load_proxy(context.config['default-completion-proxy'], CompletionsProxy)

    prompt = context.get_req_val("prompt", None)
    if prompt is None: 
        raise ValueError("No prompt specified")
    
    ## Check if there is a request specific system prompt to use
    override_system_prompt = determine_override_system_prompt(context)

    ## Grab Other Request Specific Settings
    use_functions = context.get_req_val("use-functions", 'true').lower() in ['true', 'yes', '1']
    timeout_secs = int(context.get_req_val("timeout", context.get_req_val("timeout-secs", "90")))

    context.init_history()  ## Ensure that the history for this conversation has been loaded
    resp = proxy.send_message(prompt, context, override_system_prompt=override_system_prompt, use_functions=use_functions, timeout_secs=timeout_secs)
    return func.HttpResponse(
        body=json.dumps({
            "response": resp.to_api_response(), 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )


@app.route(route="refresh-caches", methods=["POST", "GET"])
def refresh_caches(req: func.HttpRequest) -> func.HttpResponse:
    from aiproxy.utils.config import CACHED_CONFIGS
    from aiproxy import GLOBAL_PROXIES_REGISTRY
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401, allow_entra_user=False)
    if not valid: return login_redir

    if context.is_admin is not True:
        return func.HttpResponse(
            status_code=403,
            headers={
                "reason": "Forbidden",
            },
        )
    
    CACHED_CONFIGS.clear()
    GLOBAL_PROXIES_REGISTRY._proxies.clear()
    
    return func.HttpResponse(
        body="ok",
        status_code=200, 
        headers={
            "content-type": "text/plain",
        }
    )

@app.route(route="list-orchestrators", methods=["POST", "GET"])
def orchestrator_list(req: func.HttpRequest) -> func.HttpResponse:
    global PUBLIC_ORCHESTRATOR_LIST
    global GLOBAL_HISTORY_PROVIDER
    import json
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401)
    if not valid: return login_redir


    ## Confirm that the request is authorised (either with a subscription or logged in as a user)
    if context.user_id is None or context.user_id == '?':
        valid, login_redir = context.validate_request()
        if not valid: return login_redir


    orchestrators = PUBLIC_ORCHESTRATOR_LIST
    return func.HttpResponse(
        body=json.dumps({
            "orchestrators": orchestrators
        }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )

@app.route(route="who-am-i", methods=["POST", "GET"])
def who_am_i(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401)
    if not valid: return login_redir

    return func.HttpResponse(
        body=json.dumps({
            "id": context.user_id, 
            "name": context.user_name,
            "admin": context.is_admin,
        }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )

@app.route(route="a-list-configs", methods=["POST", "GET"])
def admin_config_list(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from aiproxy.utils.config import load_configs
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401, allow_entra_user=False)
    if not valid: return login_redir

    if not context.is_admin:
        return func.HttpResponse(
            status_code=403,
            headers={
                "reason": "Forbidden",
            },
        )
    
    configs = load_configs(False)
    return func.HttpResponse(
        body=json.dumps({
            "configs": configs
        }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )

@app.route(route="a-get-config", methods=["POST", "GET"])
def admin_get_config(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from aiproxy.utils.config import get_config_record
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401, allow_entra_user=False)
    if not valid: return login_redir

    if not context.is_admin:
        return func.HttpResponse(
            status_code=403,
            headers={
                "reason": "Forbidden",
            },
        )
    
    
    config = context.get_req_val("config", None)
    if config is None: 
        return func.HttpResponse(
            status_code=400,
            headers={
                "reason": "Config not specified",
            },
        )
    
    config_record = get_config_record(config)
    return func.HttpResponse(
        body=json.dumps({
            "config": config_record
        }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )

@app.route(route="a-update-config", methods=["POST"])
def admin_update_config(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from aiproxy.utils.config import update_config
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401, allow_entra_user=False)
    if not valid: return login_redir

    if not context.is_admin:
        return func.HttpResponse(
            status_code=403,
            headers={
                "reason": "Forbidden",
            },
        )

    config_record = json.loads(req.get_body()) if context.body is None else context.body
    if config_record is None:
        return func.HttpResponse(
            status_code=400,
            headers={
                "reason": "Config not specified",
            },
        )
    
    update_config(config_record, by_user=context.user_id)

    return func.HttpResponse(
        body=json.dumps({ "status": "ok" }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )



@app.route(route="assistant", methods=["POST", "GET"])
def chat_with_assistant(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER

    import json
    from aiproxy import AssistantProxy, GLOBAL_PROXIES_REGISTRY, ChatResponse
    from aiproxy.orchestration.multi_agent_orchestrator import MultiAgentOrchestrator
    from aiproxy.data import ChatConfig
    from data import ReqContext

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    
    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401)
    if not valid: return login_redir

    context.init_history()  ## Ensure that the history for this conversation has been loaded

    prompt = context.get_req_val("prompt", None)
    if prompt is None: 
        raise ValueError("No prompt specified")
    
    assistant = context.get_req_val("assistant") or context.get_req_val("assistants") or context.get_req_val("assistant-id") or context.get_req_val("assistant-name") or context.get_req_val("assistantid")
    
    proxy = None
    result:list[ChatResponse] = None
    if ',' in assistant:
        ## Multiple assistants have been specified, so split them into a list + use the Multi-Assistant Orchestrator
        orchestrator_config = ChatConfig('legacy-multi-assistant-orchestrator')
        agents = []
        for assistant_name in assistant.split(","):
            agent_config = {
                "name": assistant_name,
                "assistant": assistant_name,
                "description": f"An AI assistant named {assistant_name}",
                "type": "assistant"
            }
            agents.append(agent_config)
        orchestrator_config.extra['agents'] = agents
        proxy = MultiAgentOrchestrator(orchestrator_config)
        result = [ proxy.send_message(prompt, context) ]
    else: 
        proxy = GLOBAL_PROXIES_REGISTRY.load_proxy(context.config['default-assistant-proxy'], AssistantProxy)
        if type(proxy) is AssistantProxy:
            result = proxy.send_message_and_return_outcome(prompt, context, assistant)
        else: 
            raise AssertionError("The proxy is not an AssistantProxy")

    chat_responses = [resp.to_api_response() for resp in result]
    return func.HttpResponse(
        body=json.dumps({
            "response": chat_responses, 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )







#############################################################################################
#                                                                                           #
#  The following APIs are for the Bot Framework API (to support the BotFramework WebClient) #
#                                                                                           #
#  - This is a basic implementation of the Bot Framework API, and is not yet complete       #
#                                                                                           #
#############################################################################################

@app.route(route="webchat/conversations", methods=["GET", "POST"])
def bf_start_conversation(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER
    import json
    from data import ReqContext
    from botframework import BotframeworkFacade

    # Build the context for the request
    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request()
    if not valid: return login_redir

    ## Load the Botframework Facade
    facade = BotframeworkFacade(context)

    ## Send the welcome activity to the stream + respond OK
    facade.send_start_activity()

    response = {
        "context": context.build_context(),
        ## And anything else relevant to the frontend 
    }

    return func.HttpResponse(
        body=json.dumps(response, indent=4),
        status_code=200, 
        headers={"Content-Type": "application/json"}
    )


@app.route(route="webchat/conversations/{conversation_id}/activities", methods=["POST"])
@app.durable_client_input(client_name="client")
async def bf_conversation_activity(req: func.HttpRequest, client) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER

    from data import ReqContext
    from botframework import BotframeworkFacade

    # Build the context for the request
    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request()
    if not valid: return login_redir

    # The Thead ID is required - without it we are not participating in a conversation
    #  so raise if it's not provided
    if context.thread_id is None:
        raise ValueError("Conversation ID (conversation_id) or Thread (thread) is required")
    
    ## Load the Botframework Facade
    facade = BotframeworkFacade(context)

    # Get the User's prompt to validate that there is a prompt ;p
    prompt = context.get_req_val("text", None) or context.get_req_val("prompt", None)   ## Text is used by botframework's webclient, prompt is commonly used by other types of clients
    if prompt is None:  
        return func.HttpResponse(
            status_code=400,
            headers={ "reason": "Prompt is required (Specified as either: text or prompt)", }
        )

    ## First, echo the user's prompt back on the stream (ack'ing the message)
    facade.echo_user_activity()

    ## Then, start the conversation trigger
    instance_id = await client.start_new("bf_conversation_orchestrator", client_input=context)
    response = client.create_check_status_response(req, instance_id)
    facade.send_typing_activity()
    return response

@app.orchestration_trigger(context_name="context")
def bf_conversation_orchestrator(context:df.DurableOrchestrationContext):
    prompt_outcome = yield context.call_activity("bf_send_prompt", context.get_input())
    if not prompt_outcome:
        return
    
    # channelData = context.get_input().get_req_val("channelData", {})
    # from_speech = channelData.get("speech", None) is not None
    
    # if from_speech: 
    #    post_prompt_tasks.append(context.call_activity("send_speech_response", context.get_input()))
    
    outputs = yield context.task_all([  
        context.call_activity("bf_send_suggestions", context.get_input())
    ])
    ## Other things that might be useful to do: 
    #   - Pull out key information about the conversation into the user profile notes to remember for future conversations 
    #   - Check if the conversation is getting long, and if it is, summarise it and set a flag in the conversation history object to use the summary instead of the history
    #   - Maintain a list of recipes added to cart / set in meal plan against the user profile to provide this information to the AI in future conversations
    #   - Do some sentiment analysis of the conversation, and if the convo is going towards a dark place, make some notes in the conversation that inform the AI to try and lift the conversation back 
    #   - Score the response from the AI against some rules, and for responses that do not score well, send a snapshot of the convo + the response to somewhere where it can be further analysed by a human
    #   - Keep a global record of recipe impressions, and subsequent usage of the recipes (saved / added to cart etc...)
    #   - Check the length of the user profile notes, and when they get too long, go ahead and summarise them into their key points



@app.activity_trigger(input_name="context")
def bf_send_prompt(context):
    global GLOBAL_HISTORY_PROVIDER

    from botframework import BotframeworkFacade

    # The Thead ID is required - without it we are not participating in a conversation
    #  so raise if it's not provided
    if context.thread_id is None:
        raise ValueError("Conversation ID (conversation_id) or Thread (thread) is required")
    
    ## Init the Thread History (if it's not already initialised)
    context.history_provider = GLOBAL_HISTORY_PROVIDER
    context.init_history()

    ## Load the Botframework Facade
    facade = BotframeworkFacade(context)

    # Get the User's prompt
    prompt = context.get_req_val("text", None) or context.get_req_val("prompt", None)   ## Text is used by botframework's webclient, prompt is commonly used by other types of clients
    if prompt is None:  
        raise ValueError("Prompt is required (Specified as either: text or prompt)")
    
    ## Process the User's Prompt activity
    outcome = facade.process_user_activity(prompt)
    return outcome

@app.activity_trigger(input_name="context")
def bf_send_suggestions(context):
    global GLOBAL_HISTORY_PROVIDER

    from botframework import BotframeworkFacade

    # The Thead ID is required - without it we are not participating in a conversation
    #  so raise if it's not provided
    if context.thread_id is None:
        raise ValueError("Conversation ID (conversation_id) or Thread (thread) is required")
    
    ## Init the Thread History (if it's not already initialised)
    context.history_provider = GLOBAL_HISTORY_PROVIDER
    context.init_history()

    ## Load the Botframework Facade
    facade = BotframeworkFacade(context)

    ## Process the User's Prompt activity
    outcome = facade.send_suggestions()
    return outcome

@app.route(route="webchat/conversations/{conversation_id}", methods=["GET", "POST"])
def bf_conversation(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER

    import json
    from data import ReqContext
    from botframework import BotframeworkFacade

    # Build the context for the request
    context = ReqContext(req ,history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request()
    if not valid: return login_redir

    ## Load the Botframework Facade
    facade = BotframeworkFacade(context)

    ## Send the welcome activity to the stream + respond OK
    facade.send_start_activity()

    response = {
        "context": context.build_context(),
        ## And anything else relevant to the frontend 
    }

    return func.HttpResponse(
        body=json.dumps(response, indent=4),
        status_code=200, 
        headers={"Content-Type": "application/json"}
    )

@app.route(route="webchat/conversations/{conversation_id}/messages", methods=["GET", "POST"])
def bf_conversation_messages(req: func.HttpRequest) -> func.HttpResponse:
    raise NotImplementedError("This method is not yet implemented")


#############################################################################################
#                                                                                           #
#  END OF BotFramework API Method (to support the BotFramework WebClient)                   #
#                                                                                           #
#############################################################################################


@app.route(route="create-stream", methods=["POST", "GET"])
def create_stream(req: func.HttpRequest) -> func.HttpResponse:
    import json
    from uuid import uuid4
    from data import ReqContext
    from aiproxy.streaming import stream_factory, PubsubStreamWriter, BotframeworkStreamWriter

    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request(default_fail_status=401)
    if not valid: return login_redir

    stream_id = context.stream_id or context.thread_id or uuid4().hex
    writer = stream_factory('pubsub', stream_id, context.get_config_value('stream-config'))
    stream_url = None
    if type(writer) is PubsubStreamWriter:
        stream_url = writer.generate_access_url()

    return func.HttpResponse(
        body=json.dumps({
            "stream-id": stream_id,
            "stream-url": stream_url
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )

@app.route(route="push-stream", methods=["POST", "GET"])
def push_stream(req: func.HttpRequest) -> func.HttpResponse:
    from data import ReqContext
    from azure.messaging.webpubsubservice import WebPubSubServiceClient
    import logging
    import os

    try:
        context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
        
        ## Confirm that the request is authorised
        valid, login_redir = context.validate_request(default_fail_status=401)
        if not valid: return login_redir

        connection_string = context.get_config_value('connection') or context.get_config_value('connection_string') or os.environ.get('PUBSUB_CONNECTION_STRING', None)
        client = WebPubSubServiceClient.from_connection_string(connection_string=connection_string, hub="hub")
        logging.info("Endpoint: " + client._config.endpoint)
        logging.info("Hub:" + client._config.hub)
        client.send_to_group(group=context.get_req_val("thread"), message="Hello World")
    except Exception as e:
        import traceback
        logging.error(f"Error in push_stream: {str(e)}")
        traceback.print_exc()
        return func.HttpResponse(
            body=str(e) + "\n\n" + traceback.format_exc(),
            status_code=200, 
            headers={
                "content-type": "text/plain",
            }
        )
    
    return func.HttpResponse(
        body="ok",
        status_code=200, 
        headers={
            "content-type": "text/plain",
        }
    )



@app.route(route="connect", methods=["GET", "POST"])
def connect(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER
    global PUBLIC_ORCHESTRATOR_LIST

    import json
    from data import ReqContext
    from aiproxy.streaming import PubsubStreamWriter, stream_factory
    from botframework import DEFAULT_BOT_ORCHESTRATOR

    ## Build the context for the request
    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised
    override_redirect_path = context.get_req_val("redirect", None)
    valid, login_redir = context.validate_request(override_redirect=override_redirect_path)
    if not valid: return login_redir

    ## Generate Speech Services Access Key
    speech_key, speech_region = generate_speech_access_key()

    ## Generate a new stream for the user
    context.init_history()  ## Ensure that the history for this conversation has been loaded
    stream_id = context.stream_id or context.thread_id
    stream_url = None
    writer = stream_factory('pubsub', stream_id, context.get_config_value('stream-config'))
    if type(writer) is PubsubStreamWriter:
        stream_url = writer.generate_access_url()

    

    orchestrator_list = None
    if context.get_req_val("listorchestrators", False): 
        orchestrator_list = PUBLIC_ORCHESTRATOR_LIST

    ## Return the connection details to the frontend
    response = {
        "context": context.build_context(),
        "thread": context.thread_id,
        "stream": stream_url,
        "speechKey": speech_key,
        "speechRegion": speech_region,
        "username": context.user_id,
        "name": context.user_name,
    }
    if orchestrator_list is not None:
        response["orchestrators"] = orchestrator_list

    ## Add headers...
    headers = { 
        "Content-Type": "application/json",
    }

    return func.HttpResponse(
        body=json.dumps(response, indent=4), 
        status_code=200, 
        headers=headers
    )



@app.route(route="speechtoken", methods=["GET", "POST"])
def refresh_speechtoken(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER

    import json
    from data import ReqContext
    
    ## Build the context for the request
    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised
    valid, login_redir = context.validate_request()
    if not valid: return login_redir

    ## Generate Speech Services Access Key
    speech_key, speech_region = generate_speech_access_key()

    ## Return the token
    response = {
        "authorizationToken": speech_key,
        "region": speech_region,
    }

    return func.HttpResponse(
        body=json.dumps(response, indent=4), 
        status_code=200, 
        headers={"Content-Type": "application/json"}
    )

@app.route(route="auth-callback", methods=["GET", "POST"])
def callback(req: func.HttpRequest) -> func.HttpResponse:
    global GLOBAL_HISTORY_PROVIDER

    import os
    import base64
    import msal
    from data import ReqContext

    app = msal.ClientApplication(
        app_name=os.environ.get("ENTRA_APP_NAME"), 
        client_id=os.environ.get("ENTRA_CLIENT_ID"), 
        client_credential=os.environ.get("ENTRA_CLIENT_SECRET"),
        authority=os.environ.get("ENTRA_AUTHORITY")
        )

    ## Build the context for the request
    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)

    result = app.acquire_token_by_authorization_code(
        context.get_req_val("code"),
        scopes=context.get_auth_scopes(),
        redirect_uri=context.get_auth_redirect_url(),
        )

    if "error" in result:
        return func.HttpResponse(
            body="Not Allowed", 
            status_code=401
        )
    
    id_token = result.get("id_token", None)
    if id_token is None:
        return func.HttpResponse(
            body="Not Allowed",
            status_code=401
        )

    send_to_url = context.get_req_val("state", context.get_req_val("session_state", None))
    if send_to_url is not None: 
        send_to_url = base64.urlsafe_b64decode((send_to_url+"==").encode("utf-8")).decode("utf-8")
    
    if send_to_url is None or send_to_url == '/' or len(send_to_url) == 0: 
        send_to_url = context.get_config_value('ui-default-redirect-url', os.environ.get("DEFAULT_REDIRECT_URL", "/"))
    

    is_secure = 'Secure;' if req.url.startswith("https") else ''
    headers = { 
        "Set-Cookie": f"token={id_token};{is_secure} Path=/; Max-Age=28800", # HttpOnly; 
        "Location": send_to_url
    }

    return func.HttpResponse(
        status_code=302,
        headers=headers
    )


@app.route(route="app/{*path}", methods=["GET"])
def serve_ui(req: func.HttpRequest) -> func.HttpResponse:
    import os
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from data import ReqContext
    from utils.media_types import infer_content_type

    context = ReqContext(req)

    path = req.route_params.get("path", "index.html")
    if path.endswith("/"): path += "index.html"
    path = path.replace("%2F", "/")

    referer = context.get_req_val("Referer", None)
    subscription_id = context.get_req_val("subscription", None)
    if referer is None:
        # Check if there is a default redirect prefix
        referer_prefix = context.get_config_value('ui-default-redirect-prefix', os.environ.get("DEFAULT_REDIRECT_PREFIX"))
        if referer_prefix is not None and referer_prefix != "/":
            ## Remove slash from referer prefix
            if referer_prefix.endswith("/"): referer_prefix = referer_prefix[:-1]
            if path.startswith('/'):
                referer = referer_prefix + path
            else: 
                referer = referer_prefix + '/' + path
    elif subscription_id is None and "subscription=" in referer: 
        subscription_id = referer.split("subscription=")[1].split("&")[0]

    valid, login_redir = context.validate_request(override_redirect=referer)
    if not valid:
        if subscription_id is not None:
            ## Check the subscription exists in the API Management Service
            import requests
            try:
                who_url = os.environ.get("WHO_AM_I_URL", "https://aichat.mihsydney.com/who-am-i")
                who_resp = requests.get(f"{who_url}?subscription={subscription_id}")
                if who_resp.status_code == 200:
                    who_body = who_resp.json()
                    who_id = who_body.get("id", None)
                    context.user_sub = {
                        "sub-id": who_id, 
                        "sub-name": who_body.get("name", None)
                    }
                    if who_id is not None: 
                        valid = True
            except: 
                pass

    if not valid:
        ## Grab file extension of the path
        last_dot = path.rfind(".")
        if last_dot > -1: 
            ext = path[last_dot+1:]
            if ext in ["html", "htm", "js", "cjs", "map", "css", 'svg', 'png', 'jpeg', 'jpg']:
                valid = True

    if not valid: 
        ## Check if it's an allowed known url
        check_path = path
        if check_path.startswith("/"): check_path = check_path[1:]
        if check_path in ["favicon.ico", "robots.txt", "sitemap.xml", "manifest.json"]:
            valid = True

    if not valid:
        return login_redir

    ## Serve static file from Azure Blob Storage 
    blob_service_client = None

    ## Setup Storage Connection
    blob_storage_connection = context.get_config_value("ui-storage-connection-string")
    if blob_storage_connection is not None:
        blob_service_client = BlobServiceClient.from_connection_string(blob_storage_connection)
    else: 
        account_url = context.get_config_value("ui-storage-account-url")
        credential = context.get_config_value("ui-storage-account-key")
        if account_url is not None and credential is not None:
            blob_service_client = BlobServiceClient(account_url, credential=credential)

    
    ## Check for a Managed Identity Config
    account_name = context.get_config_value("ui-storage-account-name", os.environ.get("UI_STORAGE_ACCOUNT_NAME", None))
    if blob_service_client is None and account_name is not None:
        blob_service_client = BlobServiceClient(account_url=f"https://{account_name}.blob.core.windows.net", credential=DefaultAzureCredential())
        
    # Fallback to default storage account
    if blob_service_client is None: 
        blob_storage_connection = os.environ.get("UI_STORAGE_CONNECTION_STRING")
        if blob_storage_connection is not None: 
            blob_service_client = BlobServiceClient.from_connection_string(blob_storage_connection)
        else: 
            account_url = os.environ.get("UI_STORAGE_ACCOUNT_URL")
            credential = os.environ.get("UI_STORAGE_ACCOUNT_KEY")
            if account_url is not None and credential is not None:
                blob_service_client = BlobServiceClient(account_url, credential=credential)
            else: 
                account_name = os.environ.get("UI_STORAGE_ACCOUNT_NAME", os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", None))
                if account_name is not None:
                    blob_service_client = BlobServiceClient(account_url=f"https://{account_name}.blob.core.windows.net")
            
    if blob_service_client is None: 
        return func.HttpResponse(
            body="Malformed Configuration", 
            status_code=404
        )

    
    ## Setup Storage Container
    container_name = context.get_config_value("ui-storage-container-name")
    if container_name is None:
        container_name = os.environ.get("UI_STORAGE_CONTAINER_NAME")

    if container_name is None:
        return func.HttpResponse(
            body="Malformed Configuration - could not determine where to look for the file", 
            status_code=404
        )
    
    
    ## Load the Client + Download the file
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=path)

    blob_data = None
    retries = 3
    while retries > 0:
        try:
            # encoding param is necessary for readall() to return str, otherwise it returns bytes
            downloader = blob_client.download_blob(max_concurrency=1, encoding=None)
            blob_data = downloader.readall()
            retries = 0
            break
        except ResourceNotFoundError:
            return func.HttpResponse(
                body="Not Found", 
                status_code=404
            )
        except Exception as e:
            retries -= 1
    
    if blob_data is None:
        return func.HttpResponse(
            body="Not Found", 
            status_code=404
        )

    ## Infer content type from the file extension
    content_type = infer_content_type(path)
    
    if path.endswith(".js"):
        blob_data = blob_data.decode("utf-8", errors="ignore").encode("utf-8", errors="ignore")

    headers = {
        "Content-Type": content_type
    }

    ## Get the configured cache settings
    cache_settings = context.get_config_value("ui-cache-control", None)
    if cache_settings is not None:
        if type(cache_settings) is str:
            cache_settings = { "Cache-Control": cache_settings }
            headers.update(cache_settings)
        elif type(cache_settings) is dict:
            if path in cache_settings:
                headers.update({ "Cache-Control": cache_settings[path] })
            else: 
                import re
                for key, val in cache_settings.items():
                    ## Key is a regex pattern, so check if it matches the path
                    # Load pattern from the key, then do match
                    if key.startswith("regex:"):
                        pattern = key[6:]
                        if re.match(pattern, path):
                            headers.update({ "Cache-Control": val })
                            break
                    elif key.endswith("*"):
                        if path.startswith(key[:-1]):
                            headers.update({ "Cache-Control": val })
                            break
        elif type(cache_settings) is list:
            for item in cache_settings:
                if path in item:
                    headers.update({ "Cache-Control": item[path] })
                    break
                else:
                    import re
                    for key, val in item.items():
                        ## Key is a regex pattern, so check if it matches the path
                        # Load pattern from the key, then do match
                        if key.startswith("regex:"):
                            pattern = key[6:]
                            if re.match(pattern, path):
                                headers.update({ "Cache-Control": val })
                                break
                        elif key.endswith("*"):
                            if path.startswith(key[:-1]):
                                headers.update({ "Cache-Control": val })
                                break
    else: 
        ## Apply default cache control                        
        if 'imgs/' in path or 'images/' in path or 'img/' in path:
            ## Cache Images for 1week
            headers["Cache-Control"] = "public, max-age=604800"
        elif 'lib/' in path or 'scripts/' in path or 'js/' in path:
            ## Cache Libraries for 48 hours
            headers["Cache-Control"] = "public, max-age=172800"
        else: 
            ## No Cache
            headers["Cache-Control"] = "no-cache, no-store, must-revalidate"


    return func.HttpResponse(
        body=blob_data, 
        status_code=200, 
        headers=headers
    )




def generate_speech_access_key() -> tuple[str, str]:
    import os
    import requests

    subscription_key = os.environ.get('SPEECH_API_KEY')
    cognitive_services_endpoint = os.environ.get('SPEECH_API_ENDPOINT', 'westus2.api.cognitive.microsoft.com')
    if not cognitive_services_endpoint.startswith('https://'):
        cognitive_services_endpoint = f'https://{cognitive_services_endpoint}'
    cognitive_speech_region = os.environ.get('COGNITIVE_SPEECH_REGION', None)
    if cognitive_speech_region is None:
        cognitive_speech_region = cognitive_services_endpoint.replace('https://', '').split('.')
        if len(cognitive_speech_region) > 1:
            cognitive_speech_region = cognitive_speech_region[0]
        else:
            cognitive_speech_region = 'westus2'

    url = f"{cognitive_services_endpoint}/sts/v1.0/issueToken"
    headers = { 'Ocp-Apim-Subscription-Key': subscription_key }
    response = requests.post(url, headers=headers)
    if response.status_code != 200:
        return None, None
    return str(response.text), cognitive_speech_region

def determine_override_system_prompt(context) -> str:
    from data import ReqContext
    from aiproxy.data import ChatConfig
    if type(context) is not ReqContext:
        raise AssertionError("The context must be a ReqContext object")
    
    override_system_prompt = context.get_req_val("system-prompt") or context.get_req_val("prompt-config") or context.get_req_val("prompt-file")
    if override_system_prompt is not None:
        ## Secret hack to allow specifying the system prompt directly
        if override_system_prompt.startswith("!DIRECT!"):
            return override_system_prompt[8:].strip()

        ## Assume the system prompt is the name of a config that contains the system prompt
        tmp_config = ChatConfig.load(override_system_prompt, raise_if_not_found=False)
        if tmp_config is not None:
            return tmp_config.system_prompt
        raise ValueError("The requested system prompt could not be found")
    
    return None
