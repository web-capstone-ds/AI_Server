import jwt
import uuid
from datetime import datetime, timezone, timedelta


def _load_private_key(pem: str):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    normalized = pem.replace("\\n", "\n").encode()
    return load_pem_private_key(normalized, password=None)


def create_ai_service_token(settings) -> str:
    """AI Server → Web-Backend 호출용 RS256 서비스 JWT (5분 유효)."""
    if not settings.AI_SERVER_PRIVATE_KEY:
        raise RuntimeError("AI_SERVER_PRIVATE_KEY not configured")
    private_key = _load_private_key(settings.AI_SERVER_PRIVATE_KEY)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "ai-server",
        "type": "service",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=300)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")
