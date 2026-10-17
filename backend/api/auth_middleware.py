import uuid
from typing import Optional
from fastapi import Header, HTTPException, Request, status
from pydantic import BaseModel


class StandardErrorResponse(BaseModel):
    code: str
    user_message: str
    technical_details: Optional[str] = None
    retryable: bool = False
    correlation_id: str


def make_error_response(
    code: str,
    user_message: str,
    technical_details: Optional[str] = None,
    retryable: bool = False,
    correlation_id: Optional[str] = None,
) -> dict:
    cid = correlation_id or f"req_{uuid.uuid4().hex[:10]}"
    return StandardErrorResponse(
        code=code,
        user_message=user_message,
        technical_details=technical_details,
        retryable=retryable,
        correlation_id=cid,
    ).model_dump()

