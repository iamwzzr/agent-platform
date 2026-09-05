# Stage 8 fixed evaluation

The current Stage 8 deliverable is the first offline smoke slice, not the formal
ten-case evaluation milestone. Its versioned dataset is
`evals/datasets/smoke-v1/cases.json` and contains exactly three synthetic cases:

1. grounded evidence produces a cited artifact;
2. missing evidence produces an explicit gap;
3. a schema-valid forged citation is rejected after bounded revision and no
   successful artifact record is published.

## Run the smoke gate

From `backend/`:

```bash
uv run python -m app.eval_cli
uv run python -m app.eval_cli --format json
```

The command exits with `0` when every case passes, `1` when one or more product
expectations or quality thresholds fail, and `2` when the dataset or evaluation
harness is invalid. A quality failure never stops the remaining cases, so the
report contains every failed case ID.

## Execution boundary

Every case receives its own temporary file-backed SQLite database and workspace.
The evaluator uses the production document ingestion, chunking, retrieval,
`AgentRunService`, `ApplicationGraphRunExecutor`, LangGraph workflow,
deterministic validator, RunEvent persistence, and ArtifactRecord publication
path. It explicitly constructs `DeterministicMockProvider` or the local forged
citation fault provider; it never selects a provider through application
settings and does not make a network request.

The smoke harness deliberately fixes graph execution to one revision and one
provider attempt. This makes the regression gate fast and deterministic; it is
an evaluation configuration, not a claim that the production defaults are the
same.

Runtime UUIDs and timestamps are excluded from the report. Expected evidence is
stored as `(requirement_id, document_ref, chunk_position)` and resolved to the
runtime database IDs after ingestion, which keeps repeated reports comparable.

## Metrics

- `retrieval_recall_at_5` is the fraction of labeled relevant chunk references
  returned for a requirement. A case with no relevant source reports `N/A` and
  separately requires `unexpected_retrieval_count == 0`.
- `citation_validity` is the fraction of declared citations that resolve to
  retrieved evidence supporting a referenced requirement and exact claim text.
- `citation_coverage` is the fraction of claims whose requirements are all
  supported by valid citations.
- `requirement_coverage` requires every trusted requirement to belong to exactly
  one classification: supported by one or more valid claims, or represented by
  a gap.
- `gap_accuracy` compares each expected supported/gap classification with the
  published artifact.

Positive quality metrics are aggregated only from successfully publishable
quality cases. The forged-citation case is a negative guardrail: its correct
result is `validation_failed`, an `invalid_citation_chunk_ids` validation flag,
and zero ArtifactRecord rows. Its deliberately invalid candidate citation is not
mixed into positive citation averages.

The frozen thresholds in `smoke-v1` are retrieval recall at 5 of at least `0.8`
and citation validity, citation coverage, requirement coverage, and gap accuracy
of `1.0` whenever those metrics apply.

## Limits and next milestone

This suite is a deterministic production-pipeline regression check. It does not
measure real OpenAI output, prompt quality, latency, token cost, or semantic
embedding quality. The Stage 6 live OpenAI smoke remains explicitly deferred.

Formal Stage 8 completion still requires a new, frozen ten-case dataset. The
three-case `smoke-v1` dataset must not be silently expanded in place; add a new
version for the ten-case suite.
