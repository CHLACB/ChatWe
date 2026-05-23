from typing import Any
from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool
    message: str = ""
    data: Any = None


def ok(data: Any = None, message: str = "") -> ApiResponse:
    return ApiResponse(success=True, message=message, data=data)


def fail(message: str, data: Any = None) -> ApiResponse:
    return ApiResponse(success=False, message=message, data=data)
