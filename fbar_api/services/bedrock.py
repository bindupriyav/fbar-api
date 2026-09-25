"""AWS Bedrock service client for the FBAR classification agent.

Thin wrapper around the Bedrock Runtime invoke_model API so it can be easily
mocked in unit tests. Uses the Anthropic Messages API request/response shape.
"""

import json

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from fbar_api.config import Settings
from fbar_api.middleware.error_handler import BedrockError


class BedrockService:
    """Client for invoking a Claude model via AWS Bedrock."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the Bedrock runtime client with a bounded timeout.

        Args:
            settings: Application settings (region, model id, tokens, timeout).
        """
        self._settings = settings
        self._model_id = settings.BEDROCK_MODEL_ID
        self._max_tokens = settings.BEDROCK_MAX_TOKENS

        timeout_config = Config(
            connect_timeout=settings.BEDROCK_TIMEOUT_SECONDS,
            read_timeout=settings.BEDROCK_TIMEOUT_SECONDS,
            retries={"max_attempts": 0},
        )
        client_kwargs: dict = {
            "service_name": "bedrock-runtime",
            "region_name": settings.AWS_REGION,
            "config": timeout_config,
        }
        if settings.AWS_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL

        self._client = boto3.client(**client_kwargs)

    @property
    def model_id(self) -> str:
        """Return the configured Bedrock model id."""
        return self._model_id

    def invoke(self, system_prompt: str, user_content: str) -> str:
        """Invoke the model and return the raw text output.

        Args:
            system_prompt: The system prompt (guardrails/task definition).
            user_content: The user message (filing summary + signals).

        Returns:
            The model's raw text response.

        Raises:
            BedrockError: On any client error, timeout, or unexpected response shape.
        """
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self._max_tokens,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": user_content}]}
                ],
            }
        )

        try:
            response = self._client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            raw = response["body"].read()
            parsed = json.loads(raw)
            # Anthropic Messages API returns content as a list of blocks.
            content_blocks = parsed.get("content", [])
            text_parts = [
                block.get("text", "")
                for block in content_blocks
                if block.get("type") == "text"
            ]
            text = "".join(text_parts).strip()
            if not text:
                raise BedrockError("Model returned an empty response")
            return text
        except BedrockError:
            raise
        except (BotoCoreError, ClientError) as exc:
            raise BedrockError(f"Bedrock invocation failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - normalize to BedrockError
            raise BedrockError(f"Unexpected Bedrock error: {exc}") from exc
