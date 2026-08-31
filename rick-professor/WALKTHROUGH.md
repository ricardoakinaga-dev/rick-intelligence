# CVG Agent Professor - Walkthrough (v2)

This document details the improvements made to the `cvg-agent-professor` module.

## Improvements Implemented

### 1. Conversational Memory
- **Library**: `src/lib/memory.ts` uses `ioredis` to store chat history.
- **Logic**: Stores the last 10 turns (user/assistant).
- **Integration**: `processor.ts` fetches history and injects it into the `CLINICAL_AGENT` prompt via `{{CHAT_HISTORY}}`.

### 2. Configurable Models
- **Config**: `src/config.ts` now includes:
  - `MODEL_PREPROCESSOR`
  - `MODEL_PLANNER`
  - `MODEL_AGENT`
  - `MODEL_FALLBACK`
- **Usage**: `processor.ts` uses these variables instead of hardcoded strings, preventing 404 errors with invalid model names.

### 3. Structured Logging
- **Implementation**: Replaced `console.log` with a structured `log` function in `processor.ts`.
- **Output**: JSON-formatted logs with timestamp, level, and metadata for easier debugging in production tools (e.g., Datadog, CloudWatch).

## Updated Deployment Instructions

Ensure the new environment variables are set:

```env
REDIS_URL=redis://professor-redis:6379
MODEL_PREPROCESSOR=gpt-4o-mini
MODEL_PLANNER=gpt-4o
MODEL_AGENT=gpt-4o
MODEL_FALLBACK=gpt-4o-mini
```

The Docker build process remains the same:
```bash
docker build -t cvg-agent-professor .
```
