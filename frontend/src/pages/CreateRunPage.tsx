import { useEffect, useReducer, useRef } from "react";
import { useNavigate } from "react-router-dom";

import {
  createDocument,
  createJob,
  ingestDocument,
  startRun,
} from "../api/agentPlatform";
import { ApiError, getErrorMessage, isApiError } from "../api/client";
import { AppHeader } from "../components/AppHeader";
import { ErrorNotice } from "../components/ErrorNotice";
import {
  canSafelyRetryCurrentStep,
  initialWorkflowState,
  selectNextStep,
  workbenchReducer,
  type WorkflowDraft,
  type WorkflowFailureOutcome,
  type WorkflowProgress,
  type WorkbenchStep,
} from "../state/workbenchReducer";

const STEP_LABELS: Readonly<Record<WorkbenchStep, string>> = {
  create_job: "Save role",
  create_document: "Save evidence",
  ingest_document: "Organize evidence",
  start_run: "Start generation",
};

const WORKSPACE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

export function CreateRunPage() {
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkflowState);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  const continueWorkflow = async (
    draft: WorkflowDraft,
    idempotencyKey: string,
    existingProgress: WorkflowProgress,
  ) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    let progress = { ...existingProgress };
    let step = selectNextStep(progress);

    try {
      if (step === "create_job") {
        const job = await createJob(draft.workspace_id, draft.job, {
          signal: controller.signal,
        });
        progress = { ...progress, job };
        dispatch({ type: "job_created", job });
        step = "create_document";
      }

      if (step === "create_document") {
        const document = await createDocument(
          draft.workspace_id,
          draft.document,
          { signal: controller.signal },
        );
        progress = { ...progress, document };
        dispatch({ type: "document_created", document });
        step = "ingest_document";
      }

      if (step === "ingest_document") {
        const documentId = requireProgressId(
          progress.document?.id,
          "evidence document",
        );
        const ingestion = await ingestDocument(
          draft.workspace_id,
          documentId,
          { signal: controller.signal },
        );
        progress = { ...progress, ingestion };
        dispatch({ type: "document_ingested", ingestion });
        step = "start_run";
      }

      if (step === "start_run") {
        const jobId = requireProgressId(progress.job?.id, "role");
        const documentId = requireProgressId(
          progress.document?.id,
          "evidence document",
        );
        const run = await startRun(
          draft.workspace_id,
          jobId,
          { document_ids: [documentId] },
          idempotencyKey,
          { signal: controller.signal },
        );
        dispatch({ type: "run_started", run });
        navigate(
          `/workspaces/${encodeURIComponent(draft.workspace_id)}/runs/${encodeURIComponent(run.id)}`,
        );
      }
    } catch (error: unknown) {
      if (controller.signal.aborted) {
        return;
      }
      const apiError = toApiError(error);
      dispatch({
        type: "step_failed",
        step: step ?? "start_run",
        error: apiError,
        outcome: getFailureOutcome(apiError),
      });
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const draft: WorkflowDraft = {
      workspace_id: getRequiredFormValue(data, "workspace"),
      job: {
        title: getRequiredFormValue(data, "title"),
        description: getRequiredFormValue(data, "description"),
      },
      document: {
        name: getRequiredFormValue(data, "document_name"),
        content: getRequiredFormValue(data, "evidence"),
      },
    };

    if (!WORKSPACE_PATTERN.test(draft.workspace_id)) {
      return;
    }

    const idempotencyKey = `ui-${crypto.randomUUID()}`;
    dispatch({ type: "start", draft, idempotency_key: idempotencyKey });
    void continueWorkflow(draft, idempotencyKey, initialWorkflowState.progress);
  };

  const handleRetry = () => {
    if (!state.draft || !state.idempotency_key || !state.failed_step) {
      return;
    }
    dispatch({ type: "retry_current_step" });
    void continueWorkflow(state.draft, state.idempotency_key, state.progress);
  };

  const handleRestart = () => {
    controllerRef.current?.abort();
    dispatch({ type: "restart" });
  };

  const busy = !["idle", "failed", "launched"].includes(state.phase);
  const safeRetry = canSafelyRetryCurrentStep(state);

  return (
    <main className="app-shell">
      <AppHeader workspaceId={state.draft?.workspace_id ?? "portfolio"} />

      <section className="workspace-heading">
        <div>
          <p className="eyebrow">Evidence before eloquence</p>
          <h1>Build an application you can prove.</h1>
          <p>
            Match a role to your real experience, then inspect every claim,
            citation, and evidence gap before you use it.
          </p>
        </div>
        <div className="trust-note">
          <span className="trust-index">01</span>
          <p>
            Unsupported experience is never filled in. Missing proof becomes a
            visible gap.
          </p>
        </div>
      </section>

      <section className="create-grid" aria-label="Application workbench">
        <form className="panel input-panel" onSubmit={handleSubmit}>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">New application</p>
              <h2>Role and evidence</h2>
            </div>
            <span className="step-count">1 application</span>
          </div>

          <fieldset disabled={busy || state.phase === "failed"}>
            <legend className="visually-hidden">Application inputs</legend>
            <label>
              Workspace
              <input
                defaultValue="portfolio"
                maxLength={100}
                name="workspace"
                pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
                required
              />
              <small>Letters, numbers, underscores, and hyphens.</small>
            </label>
            <label>
              Role title
              <input
                maxLength={200}
                name="title"
                placeholder="Backend Engineer"
                required
              />
            </label>
            <label>
              Job description
              <textarea
                maxLength={20_000}
                name="description"
                placeholder="Paste the responsibilities and requirements…"
                required
                rows={9}
              />
            </label>
            <label>
              Evidence file name
              <input
                defaultValue="candidate-evidence.txt"
                maxLength={255}
                name="document_name"
                required
              />
            </label>
            <label>
              Evidence document
              <textarea
                maxLength={100_000}
                name="evidence"
                placeholder="Paste a résumé, project note, or verified work sample…"
                required
                rows={12}
              />
              <small>The document body is sent only when you submit it.</small>
            </label>
          </fieldset>

          {state.phase === "idle" ? (
            <button className="primary-button" type="submit">
              Prepare evidence
              <span aria-hidden="true">→</span>
            </button>
          ) : null}

          {busy ? (
            <p className="submission-status" role="status">
              <span className="loading-spinner" aria-hidden="true" />
              {STEP_LABELS[state.phase as WorkbenchStep]}…
            </p>
          ) : null}

          {state.phase === "failed" && state.error ? (
            <ErrorNotice
              title={`${STEP_LABELS[state.failed_step ?? "start_run"]} failed`}
              message={state.error.message}
              onRetry={handleRetry}
              onReset={handleRestart}
              retryLabel={
                safeRetry ? "Retry this step" : "Retry and accept duplicate risk"
              }
            >
              {!safeRetry ? (
                <p>
                  The service may have saved this step before the connection
                  ended. Retrying could create a duplicate saved record.
                </p>
              ) : null}
            </ErrorNotice>
          ) : null}
        </form>

        <aside className="context-rail">
          <section className="panel workflow-panel" aria-labelledby="workflow-title">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Run preparation</p>
                <h2 id="workflow-title">
                  {state.phase === "idle" ? "Waiting for inputs" : "Saved progress"}
                </h2>
              </div>
            </div>
            <ol className="workflow-steps">
              {(Object.keys(STEP_LABELS) as WorkbenchStep[]).map((step) => (
                <WorkflowStep key={step} state={state} step={step} />
              ))}
            </ol>
          </section>

          <section className="principle-card">
            <span>Release rules</span>
            <strong>Every claim needs a source.</strong>
            <ul>
              <li>Evidence is limited to this workspace.</li>
              <li>Missing proof is shown as a gap.</li>
              <li>Validation runs before material is released.</li>
            </ul>
          </section>
        </aside>
      </section>
    </main>
  );
}

function WorkflowStep({
  state,
  step,
}: {
  state: typeof initialWorkflowState;
  step: WorkbenchStep;
}) {
  const completed = isStepComplete(state.progress, step);
  const current =
    state.phase === step ||
    (state.phase === "failed" && state.failed_step === step);

  return (
    <li className={completed ? "complete" : current ? "current" : undefined}>
      <span aria-hidden="true">{completed ? "✓" : current ? "•" : ""}</span>
      <div>
        <strong>{STEP_LABELS[step]}</strong>
        <small>
          {completed ? "Complete" : current ? "In progress" : "Not started"}
        </small>
      </div>
    </li>
  );
}

function isStepComplete(progress: WorkflowProgress, step: WorkbenchStep): boolean {
  switch (step) {
    case "create_job":
      return progress.job !== null;
    case "create_document":
      return progress.document !== null;
    case "ingest_document":
      return progress.ingestion !== null;
    case "start_run":
      return progress.run !== null;
  }
}

function getRequiredFormValue(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function requireProgressId(value: string | undefined, label: string): string {
  if (value) {
    return value;
  }
  throw new ApiError(`The saved ${label} could not be recovered.`, {
    code: "invalid_response",
    retryable: false,
  });
}

function toApiError(error: unknown): ApiError {
  if (isApiError(error)) {
    return error;
  }
  return new ApiError(getErrorMessage(error), {
    code: "network",
    retryable: true,
  });
}

function getFailureOutcome(error: ApiError): WorkflowFailureOutcome {
  return error.code === "network" || error.code === "invalid_response"
    ? "unknown_outcome"
    : "known_failure";
}
