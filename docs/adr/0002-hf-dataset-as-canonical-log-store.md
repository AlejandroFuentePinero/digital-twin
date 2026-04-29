# HuggingFace Dataset as the canonical production log store

The Digital Twin needs durable, queryable logs for production observability — gap rate, guardrail rejections, deflections, latency, retrieved chunks. The deployment target is HuggingFace Spaces, and a private HF Dataset repository is the natural log destination: it lives on the same auth boundary as the Space, supports JSONL append patterns via the Hub API, and is free at this traffic level. Logs are written from the Space using a write token in Space secrets, batched locally and flushed periodically (per-row writes are not the natural HF Datasets API). Local JSONL at `data/logs/interactions.jsonl` is the dev-time backend only; the **Sentinel** reads from whichever store is configured.

## Considered alternatives

- **S3 / GCS bucket.** Rejected: extra cloud account to manage, IAM complexity, cost overhead for a portfolio-scale app. No advantage at this volume.
- **Proper observability product (Sentry / Honeycomb).** Rejected: query model is wrong for this use case — we want full payloads (questions, answers, chunks, feedback), not metrics + traces. Cost is also disproportionate.
- **Local JSONL only.** Rejected: HF Spaces filesystem is ephemeral; logs would not survive a restart.

## Consequences

- A `LogReader` abstraction with `LocalReader` and `HFReader` implementations is the standard read path; **Sentinel** uses it.
- Per-row writes are buffered locally and flushed in batches (every N writes or M minutes) to match HF Datasets' commit-style API.
- The HF write token is held in Space secrets; rotation is a manual operation.
- Schema changes require a versioning convention in the dataset (e.g. `schema_version` field on each record) to avoid breaking the **Sentinel** when records from different schemas coexist.
