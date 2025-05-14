import azure.functions as func
import azure.durable_functions as df

import logging

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)
# app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

logging.getLogger("azure").setLevel(logging.ERROR) ## Only log the ERRORs from the azure libraries (some of which are otherwise quite verbose in their logging)

GLOBAL_HISTORY_PROVIDER = None
PUBLIC_ORCHESTRATOR_LIST = []
APP_SETUP = False

def build_public_orchestrator_list():
    global PUBLIC_ORCHESTRATOR_LIST

    from botframework import DEFAULT_BOT_ORCHESTRATOR
    from aiproxy.utils.config import load_public_orchestrator_list
    orchestrators = load_public_orchestrator_list()
    
    ## Remove any orchestrators that have an agent type of graph-agent or a pattern of GraphRAG
    ## (these are not supported by this function app)
    orchestrators = [o for o in orchestrators if o.get('agent-type', None) != 'graph-agent' and o.get('pattern', None) != 'GraphRAG']

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

    logging.warning('App setup and ready to go!')


def ensure_app_setup():
    global APP_SETUP
    if not APP_SETUP:
        setup_app()
        APP_SETUP = True


@app.function_name(name="refresh_config_cache")
@app.timer_trigger(schedule="0,20,40 * * * * *", arg_name="tm", run_on_startup=False) 
def refresh_config_cache(tm: func.TimerRequest) -> None:
    ensure_app_setup()

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
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER

    import json
    from aiproxy.orchestration import orchestrator_factory
    from aiproxy.data import ChatConfig
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

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
        orchestrator_name = context.get_req_val("orchestrator", context.get_config_value("orchestrator", None))
        if orchestrator_name is None: 
            orchestrator_name = context.get_config_value("default-orchestrator", "completion")
            orchestrator_config = ChatConfig.load(orchestrator_name, False)
        else: 
            orchestrator_config = ChatConfig.load(orchestrator_name, False)

        if orchestrator_config is None: 
            ## Create a default Config
            orchestrator_config = context.config.clone()
            orchestrator_config['type'] = context.get_req_val("orchestrator-type", context.get_config_value("orchestrator-type", 'completion'))
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

    response = func.HttpResponse(
        body=json.dumps({
            "response": resp.to_api_response(), 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="completion", methods=["POST", "GET"])
def chat_completion(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER

    import json
    from aiproxy import CompletionsProxy, GLOBAL_PROXIES_REGISTRY
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)
    
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
    response = func.HttpResponse(
        body=json.dumps({
            "response": resp.to_api_response(), 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response


@app.route(route="refresh-caches", methods=["POST", "GET"])
def refresh_caches(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    from aiproxy.utils.config import CACHED_CONFIGS
    from aiproxy import GLOBAL_PROXIES_REGISTRY
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)
    

    if context.is_admin is not True:
        return func.HttpResponse(
            status_code=403,
            headers={
                "reason": "Forbidden",
            },
        )
    
    CACHED_CONFIGS.clear()
    GLOBAL_PROXIES_REGISTRY._proxies.clear()
    
    response = func.HttpResponse(
        body="ok",
        status_code=200, 
        headers={
            "content-type": "text/plain",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="list-orchestrators", methods=["POST", "GET"])
def orchestrator_list(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global PUBLIC_ORCHESTRATOR_LIST
    global GLOBAL_HISTORY_PROVIDER
    import json
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Confirm that the request is authorised (either with a subscription or logged in as a user)
    if context.user_id is None or context.user_id == '?':
        valid, login_redir = context.validate_request()
        if not valid: return login_redir


    orchestrators = PUBLIC_ORCHESTRATOR_LIST
    response = func.HttpResponse(
        body=json.dumps({
            "orchestrators": orchestrators
        }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="who-am-i", methods=["POST", "GET"])
def who_am_i(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    import json
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

    response = func.HttpResponse(
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
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="a-list-configs", methods=["POST", "GET"])
def admin_config_list(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    import json
    from aiproxy.utils.config import load_configs
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

    if not context.is_admin:
        return func.HttpResponse(
            status_code=403,
            headers={
                "reason": "Forbidden",
            },
        )
    
    configs = load_configs(False)
    response = func.HttpResponse(
        body=json.dumps({
            "configs": configs
        }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="a-get-config", methods=["POST", "GET"])
def admin_get_config(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    import json
    from aiproxy.utils.config import get_config_record
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

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
    response = func.HttpResponse(
        body=json.dumps({
            "config": config_record
        }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="a-update-config", methods=["POST"])
def admin_update_config(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    import json
    from aiproxy.utils.config import update_config
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

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

    response = func.HttpResponse(
        body=json.dumps({ "status": "ok" }),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response




@app.route(route="assistant", methods=["POST", "GET"])
def chat_with_assistant(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER

    import json
    from aiproxy import AssistantProxy, GLOBAL_PROXIES_REGISTRY, ChatResponse
    from aiproxy.orchestration.multi_agent_orchestrator import MultiAgentOrchestrator
    from aiproxy.data import ChatConfig
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

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
    response = func.HttpResponse(
        body=json.dumps({
            "response": chat_responses, 
            "context": context.build_context()
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response







#############################################################################################
#                                                                                           #
#  The following APIs are for the Bot Framework API (to support the BotFramework WebClient) #
#                                                                                           #
#  - This is a basic implementation of the Bot Framework API, and is not yet complete       #
#                                                                                           #
#############################################################################################

@app.route(route="webchat/conversations", methods=["GET", "POST"])
def bf_start_conversation(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER
    import json
    from data import ReqContext
    from botframework import BotframeworkFacade
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Load the Botframework Facade
    facade = BotframeworkFacade(context)

    ## Send the welcome activity to the stream + respond OK
    facade.send_start_activity()

    resp = {
        "context": context.build_context(),
        ## And anything else relevant to the frontend 
    }

    response = func.HttpResponse(
        body=json.dumps(resp, indent=4),
        status_code=200, 
        headers={"Content-Type": "application/json"}
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response


@app.route(route="webchat/conversations/{conversation_id}/activities", methods=["POST"])
@app.durable_client_input(client_name="client")
async def bf_conversation_activity(req: func.HttpRequest, client) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER

    from data import ReqContext
    from botframework import BotframeworkFacade
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

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
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
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
    
    post_activities = []
    if context.get_input().get_config_value("send-suggestions", True):
        post_activities.append(context.call_activity("bf_send_suggestions", context.get_input()))
    if context.get_input().get_config_value("send-sentiment", True):
        post_activities.append(context.call_activity("bf_send_sentiment", context.get_input()))
    outputs = yield context.task_all(post_activities)
    ## Other things that might be useful to do: 
    #   - Pull out key information about the conversation into the user profile notes to remember for future conversations 
    #   - Check if the conversation is getting long, and if it is, summarise it and set a flag in the conversation history object to use the summary instead of the history
    #   - Do some sentiment analysis of the conversation, and if the convo is going towards a dark place, make some notes in the conversation that inform the AI to try and lift the conversation back 
    #   - Score the response from the AI against some rules, and for responses that do not score well, send a snapshot of the convo + the response to somewhere where it can be further analysed by a human



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


@app.activity_trigger(input_name="context")
def bf_send_sentiment(context):
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

    ## Process the sentiment of the conversation
    outcome = facade.send_sentiment()
    return outcome


@app.route(route="webchat/conversations/{conversation_id}", methods=["GET", "POST"])
def bf_conversation(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER

    import json
    from data import ReqContext
    from botframework import BotframeworkFacade
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)


    ## Load the Botframework Facade
    facade = BotframeworkFacade(context)

    ## Send the welcome activity to the stream + respond OK
    facade.send_start_activity()

    resp = {
        "context": context.build_context(),
        ## And anything else relevant to the frontend 
    }

    response = func.HttpResponse(
        body=json.dumps(resp, indent=4),
        status_code=200, 
        headers={"Content-Type": "application/json"}
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="webchat/conversations/{conversation_id}/messages", methods=["GET", "POST"])
def bf_conversation_messages(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    raise NotImplementedError("This method is not yet implemented")


#############################################################################################
#                                                                                           #
#  END OF BotFramework API Method (to support the BotFramework WebClient)                   #
#                                                                                           #
#############################################################################################


@app.route(route="create-stream", methods=["POST", "GET"])
def create_stream(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    import json
    from uuid import uuid4
    from data import ReqContext
    from aiproxy.streaming import stream_factory, PubsubStreamWriter, BotframeworkStreamWriter
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

    stream_id = context.stream_id or context.thread_id or uuid4().hex
    writer = stream_factory('pubsub', stream_id, context.get_config_value('stream-config'))
    stream_url = None
    if type(writer) is PubsubStreamWriter:
        stream_url = writer.generate_access_url()

    response = func.HttpResponse(
        body=json.dumps({
            "stream-id": stream_id,
            "stream-url": stream_url
        }, indent=4),
        status_code=200, 
        headers={
            "content-type": "application/json",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="push-stream", methods=["POST", "GET"])
def push_stream(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    from data import ReqContext
    from azure.messaging.webpubsubservice import WebPubSubServiceClient
    import logging
    import os
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    try:
        context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)
        
        ## Confirm that the request is authorised
        valid, login_redir = context.validate_request(default_fail_status=401)
        if not valid: return login_redir

        connection_string = context.get_config_value('connection') or context.get_config_value('connection_string') or os.environ.get('PUBSUB_CONNECTION_STRING', None)
        client = WebPubSubServiceClient.from_connection_string(connection_string=connection_string, hub="hub")
        logging.info("Endpoint: " + client._config.endpoint)
        logging.info("Hub:" + client._config.hub)

        data = context.get_req_val("data", None)
        if data is None: 
            data = context.body_bytes.decode("utf-8")
        if data is None or len(data) == 0:
            data = "Test"
        
        thread = context.get_req_val("thread", None)
        if thread is None:
            thread = "debug-stream"

        client.send_to_group(group=context.get_req_val("thread"), message=data)
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
    
    response = func.HttpResponse(
        body="ok",
        status_code=200, 
        headers={
            "content-type": "text/plain",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response


@app.route(route="ip-notify", methods=["POST", "GET"])
def ip_notify(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    from data import ReqContext
    from azure.messaging.webpubsubservice import WebPubSubServiceClient
    import logging
    import os
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    try:
        context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

        ## Confirm that the request is authorised
        valid, login_redir = context.validate_request(default_fail_status=401)
        if not valid: return login_redir

        val = context.get_req_val("ip", None)
        if val is None: 
            val = context.body_bytes.decode("utf-8")
        print(f"IP: {val}")

        thread = context.get_req_val("thread", None)
        if thread is None:
            thread = "ip-notify"

        connection_string = context.get_config_value('connection') or context.get_config_value('connection_string') or os.environ.get('PUBSUB_CONNECTION_STRING', None)
        client = WebPubSubServiceClient.from_connection_string(connection_string=connection_string, hub="hub")
        logging.info("Endpoint: " + client._config.endpoint)
        logging.info("Hub:" + client._config.hub)
        client.send_to_group(group=thread, message=val)
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
    
    response = func.HttpResponse(
        body="ok",
        status_code=200, 
        headers={
            "content-type": "text/plain",
        }
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response



@app.route(route="connect", methods=["GET", "POST"])
def connect(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER
    global PUBLIC_ORCHESTRATOR_LIST

    import json
    from data import ReqContext
    from aiproxy.streaming import PubsubStreamWriter, stream_factory
    from botframework import DEFAULT_BOT_ORCHESTRATOR
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

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
    resp = {
        "context": context.build_context(),
        "thread": context.thread_id,
        "stream": stream_url,
        "speechKey": speech_key,
        "speechRegion": speech_region,
        "username": context.user_id,
        "name": context.user_name,
    }
    if orchestrator_list is not None:
        resp["orchestrators"] = orchestrator_list

    ## Add headers...
    headers = { 
        "Content-Type": "application/json",
    }

    response = func.HttpResponse(
        body=json.dumps(resp, indent=4), 
        status_code=200, 
        headers=headers
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response



@app.route(route="speechtoken", methods=["GET", "POST"])
def refresh_speechtoken(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER

    import json
    from data import ReqContext
    from subauth.function_utils import validate_function_request

    ## Validate the Request
    valid, subscription, login_resp = validate_function_request(req, default_fail_status=401)
    if not valid: 
        login_resp.headers["x-path"] = req.route_params.get("path", req.url)
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

    ## Generate Speech Services Access Key
    speech_key, speech_region = generate_speech_access_key()

    ## Return the token
    response = {
        "authorizationToken": speech_key,
        "region": speech_region,
    }

    response = func.HttpResponse(
        body=json.dumps(response, indent=4), 
        status_code=200, 
        headers={"Content-Type": "application/json"}
    )
    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response

@app.route(route="auth-callback", methods=["GET", "POST"])
def callback(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    global GLOBAL_HISTORY_PROVIDER

    import os
    from data import ReqContext
    from subauth.function_utils import handle_entra_auth_callback
    
    context = ReqContext(req, history_provider=GLOBAL_HISTORY_PROVIDER)
    return handle_entra_auth_callback(req, context.get_config_value('ui-default-redirect-url', os.environ.get("DEFAULT_REDIRECT_URL", "/")))


@app.route(route="app/{*path}", methods=["GET"])
def serve_ui(req: func.HttpRequest) -> func.HttpResponse:
    ensure_app_setup()
    import os
    from data import ReqContext
    from utils.media_types import infer_content_type
    from subauth.function_utils import validate_function_request

    ## Step 0: Get and adjust the path
    path = req.route_params.get("path", "index.html")
    if path.endswith("/"): path += "index.html"
    path = path.replace("%2F", "/")

    
    ## Step 1: Validate the Request
    valid, subscription, login_resp = validate_function_request(req, override_path=path, redirect_on_fail=True, default_fail_status=401)
    if not valid and (path.endswith("robots.txt") or path.endswith("manifest.json")):
        valid = True
        
    if not valid: 
        login_resp.headers["x-path"] = path
        return login_resp

    context = ReqContext(req, subscription=subscription, history_provider=GLOBAL_HISTORY_PROVIDER)

    blob_data = None

    try: 
        ## Check if we're serving from Blob storage or from the local file system
        ui_local_path = context.get_config_value("ui-local-path", os.environ.get("UI_LOCAL_PATH", None))
        if ui_local_path is not None:
            from utils.fs import load_file
            file_path = os.path.join(ui_local_path, path)
            blob_data = load_file(file_path, ui_local_path)
        else: 
            from utils.blob import get_blob_data
            blob_data = get_blob_data(path, context)
    except FileNotFoundError as e:
        return func.HttpResponse(
            body="Not Found",
            status_code=404
        )
    except ValueError as e:
        return func.HttpResponse(
            body="Configuration Error",
            status_code=500
        )


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


    response = func.HttpResponse(
        body=blob_data,
        status_code=200,
        headers=headers
    )

    ## Add the headers from the login response
    if login_resp is not None and login_resp.status_code == 0:
        response.headers.extend(login_resp.headers)
    return response




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
