# Integration Testing Guide

This document describes how to run RouterBot's provider integration tests against real LLM APIs.

## Overview

Integration tests make real HTTP calls to provider APIs. They are:
- **Excluded from CI** by default (no API keys in CI environment)
- **Opt-in** via environment variables
- **Rate-limited** to avoid 429 errors
- **Gracefully skipped** when API keys are missing

## Running Integration Tests

### Run all integration tests (skips providers without API keys)

```bash
OPENAI_API_KEY=sk-... \
ANTHROPIC_API_KEY=sk-ant-... \
GROQ_API_KEY=gsk_... \
make test-integration
```

### Run tests for a single provider

```bash
OPENAI_API_KEY=sk-... pytest tests/integration/ -k openai -v -m integration
```

### Run Ollama tests (local, no API key needed)

```bash
# Ensure Ollama is running locally:
ollama serve &
ollama pull llama3.2

pytest tests/integration/providers/test_ollama_integration.py -v -m integration
```

## Provider-Specific Environment Variables

| Provider   | Required Variables                          | Optional                        |
|------------|---------------------------------------------|---------------------------------|
| OpenAI     | `OPENAI_API_KEY`                            | —                               |
| Anthropic  | `ANTHROPIC_API_KEY`                         | —                               |
| Azure      | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | `AZURE_OPENAI_DEPLOYMENT`   |
| Bedrock    | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `AWS_DEFAULT_REGION`           |
| Gemini     | `GEMINI_API_KEY`                            | —                               |
| Groq       | `GROQ_API_KEY`                              | —                               |
| Mistral    | `MISTRAL_API_KEY`                           | —                               |
| DeepSeek   | `DEEPSEEK_API_KEY`                          | —                               |
| Cohere     | `COHERE_API_KEY`                            | —                               |
| Ollama     | —                                           | `OLLAMA_BASE_URL`, `OLLAMA_TEST_MODEL`, `OLLAMA_EMBED_MODEL` |

## Rate Limiting

By default, a 1-second delay is inserted between API calls. To adjust:

```bash
INTEGRATION_RATE_LIMIT_DELAY=2.0 pytest tests/integration/ -m integration
```

## Test Structure

```
tests/integration/
├── __init__.py
└── providers/
    ├── __init__.py
    ├── conftest.py                          # Shared fixtures, helpers, skip logic
    ├── test_openai_integration.py
    ├── test_anthropic_integration.py
    ├── test_azure_integration.py
    ├── test_bedrock_integration.py
    ├── test_gemini_integration.py
    ├── test_multi_providers_integration.py  # Groq, Mistral, DeepSeek, Cohere
    └── test_ollama_integration.py
```

## What Each Test Validates

Each provider integration test verifies:
1. **Non-streaming chat completion** — full response, valid OpenAI format, usage tokens
2. **Streaming chat completion** — chunks with content, valid finish_reason
3. **Embeddings** (where supported) — non-empty float vectors, valid response shape
4. **Health check** (where applicable) — provider is reachable

## Contributing

When adding a new provider:
1. Add API key fixture to `tests/integration/providers/conftest.py`
2. Add a test file `tests/integration/providers/test_{provider}_integration.py`
3. Update the table in this document

## Recording Fixtures

To generate new unit test fixtures from real API responses:

```python
import json
from pathlib import Path

# After a successful integration test call:
Path("tests/fixtures/myprovider/chat_completion.json").write_text(
    json.dumps(raw_response_dict, indent=2)
)
```
