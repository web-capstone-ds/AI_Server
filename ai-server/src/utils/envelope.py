"""
Backend response envelope.

Spring 백엔드(AiServerClient/BatchEnvelope)는 batch 계열 API 응답을
{status, requestId, servedAt, data, error} 형태로 기대한다.
BatchEnvelope.ok() == ("ok".equalsIgnoreCase(status) && data != null) 이므로
정상 응답은 status="ok" + data!=null 이어야 한다.
"""
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


def envelope(data: Any, *, error: Optional[dict] = None) -> dict:
    """Wrap a payload in the backend-expected response envelope."""
    return {
        "status": "ok" if error is None else "error",
        "requestId": str(uuid4()),
        "servedAt": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "error": error,
    }
