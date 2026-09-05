import type { ApiError } from "../api/client";
import type {
  DocumentCreate,
  DocumentIngestionRead,
  DocumentRead,
  JobCreate,
  JobRead,
  RunRead,
} from "../api/contracts";

export interface WorkflowDraft {
  workspace_id: string;
  job: JobCreate;
  document: DocumentCreate;
}

export type WorkbenchInput = WorkflowDraft;

export type WorkbenchStep =
  | "create_job"
  | "create_document"
  | "ingest_document"
  | "start_run";

export type CompletedWorkbenchStep = WorkbenchStep;

export type WorkflowPhase =
  | "idle"
  | WorkbenchStep
  | "failed"
  | "launched";

export type WorkflowFailureOutcome = "known_failure" | "unknown_outcome";

export interface WorkflowProgress {
  job: JobRead | null;
  document: DocumentRead | null;
  ingestion: DocumentIngestionRead | null;
  run: RunRead | null;
}

export type WorkbenchProgress = WorkflowProgress;

export interface WorkbenchState {
  phase: WorkflowPhase;
  draft: WorkflowDraft | null;
  idempotency_key: string | null;
  progress: WorkflowProgress;
  failed_step: WorkbenchStep | null;
  failure_outcome: WorkflowFailureOutcome | null;
  error: ApiError | null;
}

export type WorkbenchAction =
  | {
      type: "start";
      draft: WorkflowDraft;
      idempotency_key: string;
    }
  | { type: "job_created"; job: JobRead }
  | { type: "document_created"; document: DocumentRead }
  | { type: "document_ingested"; ingestion: DocumentIngestionRead }
  | { type: "run_started"; run: RunRead }
  | {
      type: "step_failed";
      step: WorkbenchStep;
      error: ApiError;
      outcome?: WorkflowFailureOutcome;
    }
  | { type: "retry_current_step" }
  | { type: "restart" };

const EMPTY_PROGRESS: WorkflowProgress = {
  job: null,
  document: null,
  ingestion: null,
  run: null,
};

export const initialWorkflowState: WorkbenchState = {
  phase: "idle",
  draft: null,
  idempotency_key: null,
  progress: EMPTY_PROGRESS,
  failed_step: null,
  failure_outcome: null,
  error: null,
};

export const initialWorkbenchState = initialWorkflowState;

function snapshotDraft(draft: WorkflowDraft): WorkflowDraft {
  return {
    workspace_id: draft.workspace_id,
    job: { ...draft.job },
    document: { ...draft.document },
  };
}

function isCurrentStep(
  state: WorkbenchState,
  step: WorkbenchStep,
): boolean {
  return state.phase === step;
}

export function selectNextStep(
  progress: WorkflowProgress,
): WorkbenchStep | null {
  if (progress.job === null) {
    return "create_job";
  }
  if (progress.document === null) {
    return "create_document";
  }
  if (progress.ingestion === null) {
    return "ingest_document";
  }
  if (progress.run === null) {
    return "start_run";
  }
  return null;
}

export function canRetryCurrentStep(state: WorkbenchState): boolean {
  return state.phase === "failed" && state.failed_step !== null;
}

export function canSafelyRetryCurrentStep(state: WorkbenchState): boolean {
  if (!canRetryCurrentStep(state)) {
    return false;
  }

  if (state.failure_outcome !== "unknown_outcome") {
    return true;
  }

  return (
    state.failed_step === "ingest_document" ||
    state.failed_step === "start_run"
  );
}

export function workbenchReducer(
  state: WorkbenchState,
  action: WorkbenchAction,
): WorkbenchState {
  switch (action.type) {
    case "start":
      if (state.phase !== "idle") {
        return state;
      }
      return {
        phase: "create_job",
        draft: snapshotDraft(action.draft),
        idempotency_key: action.idempotency_key,
        progress: { ...EMPTY_PROGRESS },
        failed_step: null,
        failure_outcome: null,
        error: null,
      };

    case "job_created":
      if (!isCurrentStep(state, "create_job")) {
        return state;
      }
      return {
        ...state,
        phase: "create_document",
        progress: { ...state.progress, job: action.job },
        error: null,
      };

    case "document_created":
      if (!isCurrentStep(state, "create_document")) {
        return state;
      }
      return {
        ...state,
        phase: "ingest_document",
        progress: { ...state.progress, document: action.document },
        error: null,
      };

    case "document_ingested":
      if (!isCurrentStep(state, "ingest_document")) {
        return state;
      }
      return {
        ...state,
        phase: "start_run",
        progress: { ...state.progress, ingestion: action.ingestion },
        error: null,
      };

    case "run_started":
      if (!isCurrentStep(state, "start_run")) {
        return state;
      }
      return {
        ...state,
        phase: "launched",
        progress: { ...state.progress, run: action.run },
        failed_step: null,
        failure_outcome: null,
        error: null,
      };

    case "step_failed":
      if (!isCurrentStep(state, action.step)) {
        return state;
      }
      return {
        ...state,
        phase: "failed",
        failed_step: action.step,
        failure_outcome: action.outcome ?? "known_failure",
        error: action.error,
      };

    case "retry_current_step":
      if (state.phase !== "failed" || state.failed_step === null) {
        return state;
      }
      return {
        ...state,
        phase: state.failed_step,
        error: null,
        failure_outcome: null,
      };

    case "restart":
      return {
        ...initialWorkflowState,
        progress: { ...EMPTY_PROGRESS },
      };
  }
}
