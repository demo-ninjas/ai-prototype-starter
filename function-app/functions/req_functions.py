from typing import Annotated

from aiproxy import ChatContext

from data import ReqContext

def get_request_param(
        param:Annotated[str, 'The name of the request parameter to retrieve'],
        context:ChatContext = None
) -> str:
    if context is None or type(context) is not ReqContext:
        raise AssertionError("The context must be a ReqContext object")
    return context.get_req_val(param)


def register_functions(): 
    from aiproxy import GLOBAL_FUNCTIONS_REGISTRY
    GLOBAL_FUNCTIONS_REGISTRY.register_base_function("get_request_param", 'Retrieves the value of a given request parameter. For example, the request post data might include a "question" field, passing "question" as the param to this function will retrieve the value of that field (or None if the request doesn''t contain the parameter)',  get_request_param)