import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import type { WorkspaceOverview } from "../api/contracts";
import { AppHeader } from "../components/AppHeader";
import { ErrorNotice } from "../components/ErrorNotice";
import { useOverview } from "../hooks/useOverview";

const NODES = [
  [
    "extract",
    "Split the JD into at most 20 requirements with deterministic rules. Reject empty or duplicate IDs.",
  ],
  [
    "retrieve",
    "Rank chunks by word-frequency cosine similarity in this workspace and the selected documents. Verify their database provenance.",
  ],
  [
    "draft",
    "Call the configured Provider for a structured material bundle. Mock uses rules; OpenAI uses the model.",
  ],
  [
    "validate",
    "Check requirement coverage, references, and exact claim-to-evidence / bullet-to-claim text. This is not a semantic fact-check.",
  ],
  [
    "revise",
    "Only after business validation fails, ask the Provider to revise from trusted inputs and validation feedback. Then validate again.",
  ],
  [
    "terminal",
    "Finish as succeeded or validation_failed. Invalid inputs, invalid provider responses, and execution errors fail the run separately.",
  ],
] as const;

function OverviewData({ data }: { data: WorkspaceOverview }) {
  const { configuration: config, usage } = data;
  const metrics = [
    ["Saved JD records", usage.saved_jobs],
    ["JDs with a published package", usage.jobs_with_published_artifacts],
    ["Run records", usage.runs],
    ["Published packages", usage.published_artifacts],
    ["Packages with résumé bullets", usage.artifacts_with_resume_bullets],
    ["Gap-only packages", usage.gap_only_artifacts],
    ["Résumé bullets", usage.resume_bullets],
    ["Evidence gaps", usage.gaps],
  ] as const;

  return (
    <>
      <section className="panel overview-section" aria-labelledby="usage-title">
        <p className="eyebrow">Measured from this workspace</p>
        <h2 id="usage-title">What has actually been produced?</h2>
        <p className="overview-muted">
          Saved records are not a count of verified real-world jobs or users.
          This workspace may contain demonstrations or tests.
        </p>
        <dl className="overview-metrics">
          {metrics.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value.toLocaleString()}</dd>
            </div>
          ))}
        </dl>
        <p>
          {usage.jobs_with_runs} JDs have runs · {usage.succeeded_runs} succeeded ·{" "}
          {usage.validation_failed_runs} validation failed · {usage.failed_runs}{" "}
          failed ·{" "}
          {usage.active_runs} queued / running
        </p>
        <p>
          Historical runs: {usage.mock_runs} Mock / {usage.openai_runs} OpenAI /{" "}
          {usage.other_provider_runs} other. Cover letters: {usage.cover_letters}.
        </p>
        <p className="overview-note">
          One package is one persisted, validated artifact for a succeeded run,
          not a full résumé file. Revisions and resuming the same run do not add
          packages. Multiple runs for one JD can add packages. A gap-only package
          can pass validation without producing a single résumé bullet.
        </p>
        <p className="overview-muted">
          Database snapshot:{" "}
          <time dateTime={data.generated_at}>
            {new Date(data.generated_at).toLocaleString()}
          </time>.
          Refresh to update; counts are not a model-quality benchmark.
        </p>
      </section>

      <section className="panel overview-section" aria-labelledby="config-title">
        <p className="eyebrow">Backend deployment settings</p>
        <h2 id="config-title">How is the Agent configured?</h2>
        <p className="overview-mode">
          {config.provider === "mock"
            ? "Mock mode — deterministic rules, no model API calls."
            : "OpenAI mode selected — configuration alone does not prove live-model success."}
        </p>
        <dl className="overview-config">
          <div>
            <dt>Provider / model</dt>
            <dd>{config.provider} / {config.model}</dd>
          </div>
          <div>
            <dt>Revision budget</dt>
            <dd>At most {config.max_revisions} revisions after the first draft</dd>
          </div>
          <div>
            <dt>Transient-error retries</dt>
            <dd>
              At most {config.provider_retry_max_attempts} attempts per Provider
              call; initial delay {config.provider_retry_initial_delay_seconds}s
            </dd>
          </div>
          <div>
            <dt>Retrieval</dt>
            <dd>
              Word-frequency cosine · top {config.retrieval_top_k} positive-score
              chunks per requirement
            </dd>
          </div>
        </dl>
        <p className="overview-note">
          These are current settings, not a snapshot of each historical run.
          Provider, model, and revision budget are configured on the server;
          credentials are never returned here. Docker Compose defaults to Mock.
          This page is read-only and does not call a model.
        </p>
      </section>
    </>
  );
}

export function OverviewPage() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const { data, error, pending, refresh } = useOverview(workspaceId);

  function selectWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(
      new FormData(event.currentTarget).get("workspace") ?? "",
    ).trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(value)) return;
    if (value === workspaceId) refresh();
    else navigate(`/workspaces/${encodeURIComponent(value)}/overview`);
  }

  return (
    <main className="app-shell overview-page">
      <AppHeader workspaceId={workspaceId || undefined} backTo="/" />
      <section className="workspace-heading">
        <div>
          <p className="eyebrow">Agent overview</p>
          <h1>One workflow. Inspectable outcomes.</h1>
          <p>
            A single-Agent application workbench: fixed orchestration, two
            Provider-call nodes, and a bounded revision loop. Not a multi-Agent
            team.
          </p>
        </div>
      </section>

      <form className="panel overview-workspace" onSubmit={selectWorkspace}>
        <label>
          Inspect workspace
          <input
            key={workspaceId}
            name="workspace"
            defaultValue={workspaceId}
            maxLength={100}
            pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
            placeholder="Your workspace ID"
            required
          />
        </label>
        <button className="secondary-button" type="submit">
          View workspace
        </button>
        {workspaceId ? (
          <button
            className="text-button"
            type="button"
            disabled={pending}
            onClick={refresh}
          >
            {pending && data ? "Refreshing…" : "Refresh"}
          </button>
        ) : null}
      </form>
      <p className="overview-muted">
        Workspace IDs scope stored resources; they are not a login or
        membership-based authorization system. Use the same ID as your application
        form.
      </p>

      {pending && !data ? <p role="status">Loading Agent overview…</p> : null}
      {error ? (
        <ErrorNotice
          title={
            data
              ? "The latest overview refresh failed"
              : "Agent overview could not be loaded"
          }
          message={error}
          onRetry={refresh}
        />
      ) : null}
      {data ? <OverviewData data={data} /> : null}

      <section className="panel overview-section" aria-labelledby="graph-title">
        <p className="eyebrow">The actual execution graph</p>
        <h2 id="graph-title">Six nodes, not six Agents</h2>
        <p className="overview-flow">
          extract → retrieve → draft → validate → terminal
        </p>
        <p className="overview-note">
          If business validation fails and budget remains: validate → revise →
          validate. If the budget is exhausted: terminal (validation_failed). With
          a zero revision budget, no revise node runs.
        </p>
        <ol className="overview-nodes">
          {NODES.map(([name, description]) => (
            <li key={name}>
              <h3>
                <code>{name}</code>
                <span className="overview-node-kind">
                  {name === "draft" || name === "revise"
                    ? "Provider call"
                    : "Program logic"}
                </span>
              </h3>
              <p>{description}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="panel overview-section" aria-labelledby="guide-title">
        <p className="eyebrow">Try the platform</p>
        <h2 id="guide-title">From a JD to a traceable material bundle</h2>
        <ol className="overview-guide">
          <li>
            Open <Link to="/">New application</Link>. Enter a workspace, role title,
            and JD. Paste your own résumé or project evidence; there is no PDF
            upload.
          </li>
          <li>
            Select Prepare evidence. The frontend saves the Job and Document,
            ingests the document into chunks, then creates a Run.
          </li>
          <li>
            The Run page polls for status and displays persisted node events. It
            is status polling, not token-by-token model streaming.
          </li>
          <li>
            On success, inspect the résumé bullets, source excerpts, citations,
            and missing-evidence gaps. Check the original evidence before using a
            bullet.
          </li>
          <li>
            Return here with the same workspace ID and refresh to count the saved
            output. To evaluate another JD, create another application with that
            JD and relevant evidence.
          </li>
        </ol>
        <p className="overview-note">
          Current boundary: a local, single-machine demonstration, not a
          production ML platform. Retrieval is lexical, not semantic embedding
          search. The validator enforces text and reference consistency, not
          experience authenticity or job suitability. Non-empty cover letters are
          currently rejected; Word/PDF export is not implemented.
        </p>
      </section>
    </main>
  );
}
