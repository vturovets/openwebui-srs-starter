This application delivers an NLP-powered holiday request assistant that turns free-form text or voice inputs into structured itineraries for OpenWebUI experiments as part of the Ciklum AI Academy program.
It is built around a deterministic FastAPI pipeline that chains language detection, rules/LLM extraction, normalization, validation, and timing capture so every stage remains explainable and benchmarkable.
Dialogue orchestration and CSV-backed observability ensure clarification prompts, audit trails, and per-stage telemetry stay aligned across both direct-parse and dialog interaction modes.
A Vite + Svelte frontend mirrors the OpenWebUI experience, offering component and Playwright E2E tests to validate UI flows against the backend contract.
Bulk import guardrails let teams replay CSV backlogs with retry logic, resource-aware throttling, and performance summaries suitable for A/B comparisons.
Configuration is environment-driven, allowing teams to toggle LLM strategies, speech-to-text engines, and fixture-backed defaults without code changes.
Docker Compose examples and helper scripts accelerate local development while keeping parity with the documented SRS/SDD architecture.
