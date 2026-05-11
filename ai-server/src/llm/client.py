from anthropic import AsyncAnthropic
from src.config import settings
import structlog

logger = structlog.get_logger()

class LLMClient:
    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.ANTHROPIC_MODEL

    async def get_completion(self, system_prompt: str, user_prompt: str) -> str:
        try:
            logger.info("llm_request_started", model=self.model)
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
        except Exception as e:
            logger.error("llm_request_failed", error=str(e))
            raise

llm_client = LLMClient()
