import asyncio
from anthropic import AsyncAnthropic, APIStatusError, APITimeoutError
from src.config import settings
import structlog

logger = structlog.get_logger()

class LLMClient:
    def __init__(self):
        self.client = AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=settings.ANTHROPIC_TIMEOUT_SECONDS,
        )
        self.model = settings.ANTHROPIC_MODEL

    async def get_completion(self, system_prompt: str, user_prompt: str, max_retries: int = 2) -> str:
        attempt = 0
        while attempt <= max_retries:
            try:
                logger.info("llm_request_started", 
                            model=self.model, 
                            attempt=attempt + 1)
                
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=settings.ANTHROPIC_MAX_TOKENS,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_prompt}
                    ]
                )
                # Anthropic returns a list of content blocks
                content = "".join([block.text for block in response.content])
                logger.info("llm_request_completed")
                return content

            except APITimeoutError as e:
                logger.error("llm_request_timeout", error=str(e), attempt=attempt + 1)
                if attempt == max_retries:
                    raise
                attempt += 1
                await asyncio.sleep(1 * attempt) # Exponential backoff
                
            except APIStatusError as e:
                logger.error("llm_request_status_error", 
                             status_code=e.status_code, 
                             error=str(e), 
                             attempt=attempt + 1)
                if e.status_code >= 500 and attempt < max_retries:
                    attempt += 1
                    await asyncio.sleep(1 * attempt)
                    continue
                raise
                
            except Exception as e:
                logger.error("llm_request_unexpected_error", error=str(e), attempt=attempt + 1)
                raise

llm_client = LLMClient()
