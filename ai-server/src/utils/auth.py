import jwt
from fastapi import Header, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.config import settings
import structlog

logger = structlog.get_logger()
security = HTTPBearer()

async def verify_ingest_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.AI_INGEST_API_KEY:
        logger.warning("invalid_ingest_api_key")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

async def verify_backend_jwt(auth: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(
            auth.credentials, 
            settings.BACKEND_JWT_SECRET, 
            algorithms=["HS256"]
        )
        return payload
    except jwt.PyJWTError as e:
        logger.warning("invalid_backend_jwt", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid token")
