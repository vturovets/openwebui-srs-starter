# Import Operations Playbook

This guide documents the operational controls for running bulk imports through
`ImportJobRunner`, including configuration knobs, retry tuning, and how to read
the resulting summaries.

## Configuring Import Runs

Application settings (environment variables) control the runtime behaviour of
import jobs. Key options include:

- `IMPORT_WORKER_CONCURRENCY` and `IMPORT_MAX_CONCURRENCY` – define the default
  and hard-ceiling concurrency for in-flight parse requests.
- `IMPORT_BATCH_SIZE` – number of scheduled requests before the runner awaits
  in-flight work. This indirectly bounds the size of the task queue.
- `IMPORT_CPU_THRESHOLD` / `IMPORT_MEMORY_THRESHOLD_MB` – guardrail thresholds
  that temporarily pause scheduling when host utilisation is too high.
- `IMPORT_PAUSE_SECONDS` – sleep interval between guardrail samples while the
  runner is paused.
- `IMPORT_RETRY_ATTEMPTS` – maximum attempts made for transient pipeline errors
  before the request is marked as a permanent failure.
- `IMPORT_RETRY_BACKOFF_SECONDS` – initial delay (seconds) for exponential
  backoff between retry attempts.

Configuration values can be provided via `.env` or direct environment variables.
Use smaller concurrency/batch sizes for resource-constrained deployments.

## Retry Behaviour and Tuning

Transient pipeline failures (`status == "error"` or unexpected exceptions)
trigger an exponential backoff retry. Backoff delays grow as
`IMPORT_RETRY_BACKOFF_SECONDS * 2**(attempt-1)` until the request succeeds,
returns a non-retriable failure, or the attempt limit is reached. Each retry is
counted in the job metrics (`retryCount`). When the final attempt still fails
transiently, the request is recorded as a permanent failure
(`permanentFailures`).

Tune retry settings to balance responsiveness against load on downstream
services:

- Increase `IMPORT_RETRY_ATTEMPTS` when transient provider errors are common and
  recovery is likely within a few tries.
- Increase `IMPORT_RETRY_BACKOFF_SECONDS` to reduce pressure on unstable
  providers at the cost of slower throughput.
- Decrease both values if retries exacerbate overload conditions.

## Guardrail Pausing and Resumption

When CPU or memory usage exceeds configured thresholds, the runner queues
remaining requests and pauses scheduling. Sampling continues at
`IMPORT_PAUSE_SECONDS` intervals. Once utilisation drops below guardrails,
queued work resumes automatically. Guardrail activity is summarised in
`guardrail_actions` and `throttleCount` within the summary.

## Interpreting Import Summaries

`ImportSummary` aggregates job-level metrics:

- `metrics.total_requests`, `success_count`, `failed_count`, and `error_count`
  mirror final request outcomes.
- `metrics.retry_count`/`summary.retryCount` – total number of retry attempts
  executed across the job.
- `metrics.permanent_failures`/`summary.permanentFailures` – count of transient
  failures that remained unresolved after exhausting retries.
- `latency_histogram`, `latency_percentiles`, and `total_processing_ms` help
  spot performance regressions.
- `cpu_samples`, `memory_samples`, `peakCpu`, `peakMemoryMb`, and
  `throttleCount` support capacity analysis.
- `guardrail_actions` details throttle reasons (e.g. `cpu`, `memory`).

Persisting `ImportSummary` objects (e.g. to CSV) enables longitudinal tracking
of throughput, stability, and guardrail engagement across import runs.
