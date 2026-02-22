# Stage 2: Provider Integration

**Duration:** 3-4 weeks  
**Priority:** Critical — the core value proposition  
**Depends on:** Stage 1 (Core Foundation)  
**Agents:** Backend Engineer (multiple can work in parallel on different providers)

---

## Objective

Build the provider adapter framework and implement adapters for the top LLM providers. Each provider adapter translates between RouterBot's unified OpenAI format and the provider's native API. Providers must be self-contained, testable in isolation, and support all relevant endpoints (chat, embeddings, images, audio).

---

## Prerequisites

- Stage 1 complete: core types, config system, exceptions, token counting

---

## Tasks

### 2.1 — Provider Base Framework

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

Build the abstract provider interface and provider registration system.

**Deliverables:**
- [ ] `src/routerbot/providers/base.py` — Abstract base class
  ```python
  class BaseProvider(ABC):
      """Abstract base class for all LLM provider adapters."""
      
      provider_name: str  # e.g., "openai", "anthropic"
      
      @abstractmethod
      async def chat_completion(
          self, request: CompletionRequest, **kwargs
      ) -> CompletionResponse: ...
      
      @abstractmethod
      async def chat_completion_stream(
          self, request: CompletionRequest, **kwargs
      ) -> AsyncIterator[CompletionResponseChunk]: ...
      
      async def embedding(self, request: EmbeddingRequest, **kwargs) -> EmbeddingResponse:
          raise NotImplementedError(f"{self.provider_name} does not support embeddings")
      
      async def image_generation(self, request: ImageRequest, **kwargs) -> ImageResponse:
          raise NotImplementedError(f"{self.provider_name} does not support image generation")
      
      async def audio_transcription(self, request: AudioRequest, **kwargs) -> AudioResponse:
          raise NotImplementedError(f"{self.provider_name} does not support audio")
      
      async def rerank(self, request: RerankRequest, **kwargs) -> RerankResponse:
          raise NotImplementedError(f"{self.provider_name} does not support reranking")
      
      async def health_check(self) -> bool:
          """Check if the provider is reachable and healthy."""
          ...
      
      async def close(self) -> None:
          """Clean up resources (HTTP clients, connections)."""
          ...
  ```

- [ ] `src/routerbot/providers/registry.py` — Provider registration
  - Registry singleton that maps `provider_name -> ProviderClass`
  - Auto-discovery of providers in `providers/` directory
  - Support for dynamic provider registration at runtime
  - Support for OpenAI-compatible providers via JSON config (no code needed)
  - `get_provider(model_string: str) -> BaseProvider` — parse "provider/model" format
  
- [ ] `src/routerbot/providers/openai_compatible.py` — Generic OpenAI-compatible adapter
  - Works with any provider that implements the OpenAI API
  - Configurable `api_base`, `api_key`, custom headers
  - Used as the default for unknown providers
  
- [ ] `src/routerbot/providers/transform.py` — Shared transformation utilities
  - Convert OpenAI messages to provider format and back
  - Handle tool/function calling format differences
  - Normalize streaming chunk formats
  
- [ ] Tests for registry, provider resolution, and generic adapter

**Acceptance Criteria:**
- `get_provider("openai/gpt-4o")` returns `OpenAIProvider` instance
- `get_provider("anthropic/claude-sonnet-4-20250514")` returns `AnthropicProvider` instance
- Unknown but OpenAI-compatible providers work through generic adapter
- 90%+ coverage

### 2.2 — OpenAI Provider

**Agent:** Backend Engineer  
**Estimated effort:** 8-10 hours

**Deliverables:**
- [ ] `src/routerbot/providers/openai/provider.py` — Main provider class
- [ ] `src/routerbot/providers/openai/chat.py` — Chat completions
  - Regular completion
  - Streaming completion
  - Tool/function calling
  - Vision (image inputs)
  - JSON mode
  - Response format (structured outputs)
- [ ] `src/routerbot/providers/openai/embeddings.py` — Embeddings
- [ ] `src/routerbot/providers/openai/images.py` — DALL-E image generation
- [ ] `src/routerbot/providers/openai/audio.py` — Whisper transcription + TTS
- [ ] `src/routerbot/providers/openai/transform.py` — Request/response transforms
- [ ] `src/routerbot/providers/openai/config.py` — OpenAI-specific config
- [ ] Full test suite with mocked HTTP responses (use real OpenAI response fixtures)

**Supported Models:**
- GPT-4o, GPT-4o-mini, GPT-4-turbo, GPT-3.5-turbo
- o1, o1-mini, o1-preview, o3, o3-mini, o4-mini
- text-embedding-3-small, text-embedding-3-large
- dall-e-3
- whisper-1, tts-1, tts-1-hd

**Acceptance Criteria:**
- Chat completion request → OpenAI API → response → normalized to RouterBot format
- Streaming works with proper chunk format
- Tool calling works end-to-end
- All provider-specific params passed through correctly
- 85%+ coverage

### 2.3 — Anthropic Provider

**Agent:** Backend Engineer  
**Estimated effort:** 8-10 hours

**Deliverables:**
- [ ] `src/routerbot/providers/anthropic/provider.py`
- [ ] `src/routerbot/providers/anthropic/chat.py`
  - Messages API translation (OpenAI ↔ Anthropic format)
  - System message handling (Anthropic uses separate `system` field)
  - Tool use / function calling
  - Vision (image inputs)
  - Extended thinking support
- [ ] `src/routerbot/providers/anthropic/transform.py`
  - Convert OpenAI messages → Anthropic messages format
  - Convert Anthropic response → OpenAI response format
  - Handle stop_reason ↔ finish_reason mapping
  - Handle content blocks (text, tool_use, tool_result)
- [ ] `src/routerbot/providers/anthropic/config.py`
- [ ] Full test suite

**Supported Models:**
- Claude Opus 4, Claude Sonnet 4, Claude Sonnet 3.5 v2
- Claude Haiku 3.5

**Key Differences to Handle:**
- System message is a top-level field, not in messages array
- Different stop reasons (`end_turn` → `stop`, `max_tokens` → `length`)
- Content blocks instead of single content string
- Different streaming event format (message_start, content_block_delta, etc.)
- `anthropic-version` header required

**Acceptance Criteria:**
- OpenAI-format request correctly translated to Anthropic format
- Anthropic response correctly translated to OpenAI format
- Streaming events properly converted to OpenAI chunks
- Tool calling works end-to-end
- 85%+ coverage

### 2.4 — Azure OpenAI Provider

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/providers/azure/provider.py`
- [ ] `src/routerbot/providers/azure/chat.py`
- [ ] `src/routerbot/providers/azure/embeddings.py`
- [ ] `src/routerbot/providers/azure/images.py`
- [ ] `src/routerbot/providers/azure/transform.py`
- [ ] `src/routerbot/providers/azure/config.py`
  - Azure-specific: `api_version`, `deployment_name`, `resource_name`
  - API base URL construction: `https://{resource}.openai.azure.com/openai/deployments/{deployment}`
  - Support for Azure AD authentication
- [ ] Full test suite

**Key Differences:**
- Different URL structure (deployment-based)
- `api-key` header instead of `Authorization: Bearer`
- `api-version` query parameter required
- Deployment names instead of model names
- Azure AD token support

**Acceptance Criteria:**
- Correct URL construction from resource + deployment config
- API key and Azure AD auth both work
- All OpenAI-compatible features pass through correctly
- 85%+ coverage

### 2.5 — AWS Bedrock Provider

**Agent:** Backend Engineer  
**Estimated effort:** 8-10 hours

**Deliverables:**
- [ ] `src/routerbot/providers/bedrock/provider.py`
- [ ] `src/routerbot/providers/bedrock/chat.py`
  - Converse API support
  - Claude on Bedrock
  - Llama on Bedrock
  - Titan models
- [ ] `src/routerbot/providers/bedrock/embeddings.py` — Titan embeddings
- [ ] `src/routerbot/providers/bedrock/transform.py`
- [ ] `src/routerbot/providers/bedrock/config.py`
  - AWS credentials (access key, secret key, session token, profile)
  - Region configuration
  - Assume role support
- [ ] Full test suite

**Key Differences:**
- AWS SigV4 authentication
- Different API structure (Converse API vs Invoke)
- Model IDs are ARNs or model identifiers
- Region-specific endpoints
- Different streaming format (EventStream)

**Acceptance Criteria:**
- SigV4 authentication works
- Converse API translation correct
- Cross-region support
- Streaming via EventStream properly converted
- 85%+ coverage

### 2.6 — Google Vertex AI / Gemini Provider

**Agent:** Backend Engineer  
**Estimated effort:** 8-10 hours

**Deliverables:**
- [ ] `src/routerbot/providers/vertex_ai/provider.py` — Vertex AI (GCP)
- [ ] `src/routerbot/providers/gemini/provider.py` — Google AI Studio
- [ ] Chat completion with Gemini format translation
- [ ] Embeddings support
- [ ] Image generation (Imagen)
- [ ] Google Cloud auth (service account, ADC)
- [ ] Full test suite

**Key Differences:**
- Google auth (service account JSON, Application Default Credentials)
- Different message format (`parts` instead of `content`)
- `generateContent` API endpoint
- Safety ratings in responses
- Different streaming format

**Acceptance Criteria:**
- Both Vertex AI and Google AI Studio routes work
- Auth via service account and API key
- Message format translation correct
- 85%+ coverage

### 2.7 — Groq, Mistral, Cohere, DeepSeek Providers

**Agent:** Backend Engineer (can be parallelized — one agent per provider)  
**Estimated effort:** 3-4 hours each

These are all OpenAI-compatible or near-compatible, so they can largely reuse the generic adapter with provider-specific tweaks.

**Deliverables (per provider):**
- [ ] Provider-specific adapter extending `OpenAICompatibleProvider` or `BaseProvider`
- [ ] Any format translation needed
- [ ] Provider-specific configuration (API base, auth headers)
- [ ] Test suite

**Groq:** OpenAI-compatible, just different base URL + API key
**Mistral:** OpenAI-compatible with minor differences
**Cohere:** Different API format, needs full translation (Command R+ models)
**DeepSeek:** OpenAI-compatible

**Acceptance Criteria (each):**
- Chat completion works
- Streaming works
- Provider-specific quirks handled
- 85%+ coverage

### 2.8 — Ollama Provider

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] `src/routerbot/providers/ollama/provider.py`
- [ ] Chat and generate endpoints
- [ ] Embeddings support
- [ ] Local-first configuration (default: `http://localhost:11434`)
- [ ] Model pulling support (optional)
- [ ] Test suite

**Key Differences:**
- Local deployment (different default base URL)
- `/api/chat` and `/api/generate` endpoints
- Different streaming format
- No authentication by default
- Model names without provider prefix

**Acceptance Criteria:**
- Works with default Ollama installation
- Chat and embeddings work
- Streaming properly normalized
- 85%+ coverage

### 2.9 — Provider Integration Testing

**Agent:** QA Engineer  
**Estimated effort:** 4-6 hours

Create integration test infrastructure that can test providers against real APIs (opt-in, not in CI by default).

**Deliverables:**
- [ ] `tests/integration/providers/conftest.py` — Shared fixtures
  - Skip tests if provider API key not set
  - Rate limiting between test calls
  - Response recording for fixture generation
- [ ] Integration tests for each provider (chat, streaming, embeddings)
- [ ] `tests/fixtures/` — Recorded real API responses for unit test mocking
- [ ] Documentation on how to run integration tests locally

**Acceptance Criteria:**
- `OPENAI_API_KEY=x make test-integration` runs OpenAI tests against real API
- Tests are skipped gracefully when API keys not present
- Recorded fixtures can be used for offline testing

---

## Definition of Done (Stage 2)

- [ ] All 2.1–2.9 tasks completed and merged
- [ ] Provider registry correctly resolves all implemented providers
- [ ] Chat completions work for: OpenAI, Anthropic, Azure, Bedrock, Vertex AI, Gemini, Groq, Mistral, Cohere, DeepSeek, Ollama
- [ ] Streaming works for all providers
- [ ] Embeddings work for: OpenAI, Azure, Bedrock, Vertex AI, Cohere, Ollama
- [ ] All provider responses normalize to OpenAI format
- [ ] All provider errors map to RouterBot exception hierarchy
- [ ] Token counting works per-provider
- [ ] Cost calculation works per-provider
- [ ] All tests pass, 85%+ coverage per provider
- [ ] No circular imports

---

## Notes for Agents

- Each provider is fully self-contained in its own directory
- Providers must not import from each other
- Use `httpx.AsyncClient` for all HTTP calls — never `requests`
- Always set timeouts on HTTP calls (connect=5s, read=60s, write=10s)
- Use connection pooling (create client in `__init__`, reuse)
- Mock all HTTP calls in unit tests using `respx` or `httpx` mock transport
- Real API response JSON should be captured and stored in `tests/fixtures/` for accurate mocking
- Provider-specific parameters (not in the OpenAI spec) must be passed through via `extra_body` / `**kwargs`
