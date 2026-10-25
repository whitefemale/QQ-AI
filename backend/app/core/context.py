"""请求上下文变量。"""

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def current_request_id() -> str:
    return request_id_var.get()


def current_correlation_id() -> str:
    return correlation_id_var.get() or request_id_var.get()
