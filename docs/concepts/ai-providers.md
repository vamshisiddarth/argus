# AI Providers

Argus supports four AI providers. All implement the same `AIProvider` interface —
swapping providers requires only changing `AI_PROVIDER` in your environment.

## Provider comparison

| Provider | Best for | Auth | Model |
|----------|---------|------|-------|
| **Anthropic API** | Local dev, any cloud | `ANTHROPIC_API_KEY` | claude-sonnet-4-6 |
| **AWS Bedrock** | AWS production | IAM execution role | anthropic.claude-sonnet-4-6 |
| **Vertex AI** | GCP production | Application Default Credentials | google/gemini-1.5-pro-002 |
| **Azure OpenAI** | Azure production | Managed identity / `az login` | gpt-4o |

## Anthropic API

The universal fallback — works on any cloud, best for local development.

```ini
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**Features:**
- Prompt caching (`cache_control: ephemeral`) on the system prompt — iterations 2–N pay 10% of normal input cost for the cached portion
- No retry logic needed (Anthropic SDK handles this)

## AWS Bedrock

The default in production AWS deployments. Uses the Lambda execution role — no API key.

```ini
AI_PROVIDER=bedrock
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-6   # optional
BEDROCK_REGION=us-east-1                        # optional
```

**Requirements:**
- Bedrock must be enabled in `BEDROCK_REGION`
- Model access must be requested: Bedrock console → Model access → Claude Sonnet
- Lambda execution role needs `bedrock:InvokeModel`

**Features:**
- Exponential backoff on `ThrottlingException` (3 retries, 1s/2s/4s delays)

## Vertex AI (Gemini)

The default for GCP Cloud Run deployments.

```ini
AI_PROVIDER=vertexai
VERTEXAI_PROJECT=my-gcp-project
VERTEXAI_LOCATION=us-central1    # optional
VERTEXAI_MODEL=google/gemini-1.5-pro-002  # optional
```

**Authentication:** Uses Google Application Default Credentials.
- On Cloud Run: automatically uses the service account attached to the job
- Locally: `gcloud auth application-default login`

**Features:**
- Uses the OpenAI-compatible Vertex AI endpoint — no extra SDK dependency
- Automatic credential refresh when token expires (1-hour TTL)
- Exponential backoff on rate limits

## Azure OpenAI (GPT-4o)

The default for Azure Function deployments.

```ini
AI_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://my-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o        # optional
AZURE_OPENAI_API_VERSION=2024-10-21   # optional
# For local dev without az login:
AZURE_OPENAI_API_KEY=...
```

**Authentication:**
- In production: `DefaultAzureCredential` — picks up managed identity automatically
- Locally: either `az login` (recommended) or set `AZURE_OPENAI_API_KEY`

**Features:**
- Wraps `AuthenticationError` into a friendly `EnvironmentError` with setup instructions
- Exponential backoff on rate limits

## The AIProvider interface

All providers implement one method:

```python
class AIProvider(ABC):
    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        ...
```

The agent loop calls `chat()` — it never knows which provider is underneath.
See [Adding an AI Provider](../contributing/new-ai-provider.md) to add your own.
