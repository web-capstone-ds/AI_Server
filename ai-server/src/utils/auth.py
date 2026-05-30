import jwt
import secrets
from fastapi import Header, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.config import settings
import structlog

logger = structlog.get_logger()
security = HTTPBearer()


def backend_public_key() -> str:
    return settings.BACKEND_JWT_PUBLIC_KEY.replace("\\n", "\n")

async def verify_ingest_api_key(x_api_key: str = Header(..., alias="X-Api-Key")):
    if not secrets.compare_digest(x_api_key, settings.AI_INGEST_API_KEY):
        logger.warning("invalid_ingest_api_key")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

async def verify_backend_jwt(auth: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(
            auth.credentials, 
            backend_public_key(),
            algorithms=["RS256"],
            options={"require": ["exp", "iat"]}
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("expired_backend_jwt")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError as e:
        logger.warning("invalid_backend_jwt", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid token")
