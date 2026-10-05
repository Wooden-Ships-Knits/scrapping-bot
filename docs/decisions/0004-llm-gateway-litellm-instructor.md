# 0004 — LLM gateway: LiteLLM + instructor

**Date:** 2026-10-05
**Status:** Accepted

## Context

The operator wants to choose any LLM provider (Gemini, GPT, Claude, and others) and
only paste an API key. The LLM stage must return products that match a fixed Pydantic
schema, with an evidence URL for each product. Tests must run offline.

## Decision

- **LiteLLM** is the single gateway to every provider. Models are written as
  `provider/model` (for example `gemini/...`, `openai/...`, `anthropic/...`,
  `ollama/...`), so a new model needs no code change.
- **instructor** wraps the LiteLLM call (`instructor.from_litellm`) to return validated
  Pydantic objects, and re-asks the model when validation fails.
- Keys come from the UI session (memory only) or from `.env`, using each provider's
  standard variable name. They are held as `SecretStr` and never logged or written.
- Token use and cost are recorded per call from LiteLLM's usage and cost data. A
  per-run budget stops LLM calls when reached.
- An optional fallback order lets a run continue when one provider fails.

## Rejected alternatives

- **One SDK per provider.** Every provider becomes its own integration, with its own
  error types and structured-output quirks, to build and maintain.
- **LangChain.** Covers far more than this stage needs and is heavier to test offline.
- **ScrapeGraphAI as the gateway.** It is an extraction pipeline, not a provider
  layer. It stays a benchmark candidate for the extraction step itself.
- **pydantic-ai.** A credible alternative with typed outputs. LiteLLM was chosen for
  its wider provider coverage and cost data; revisit if instructor stops fitting.

## Consequences

- LiteLLM is a large, fast-moving dependency. Pin its version and upgrade deliberately.
- Providers differ in how they support structured output. Each provider in the
  supported list gets a contract test against a recorded response.
- The LLM stage depends only on an `LLMExtractor` interface, so a different gateway can
  replace this one without touching acquisition.
