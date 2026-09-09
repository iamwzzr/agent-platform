import type { RunRead } from "../api/contracts";

interface RunStatusProps {
  run: RunRead;
  jobTitle?: string;
  connectivityError?: string | null;
  isResuming?: boolean;
  resumeError?: string | null;
  onResume?: () => void | Promise<void>;
}

interface StatusPresentation {
  label: string;
  headline: string;
  description: string;
  symbol: string;
}

const STATUS_PRESENTATION: Record<RunRead["status"], StatusPresentation> = {
  queued: {
    label: "Queued",
    headline: "Application queued",
    description: "Your inputs are saved and waiting to be processed.",
    symbol: "·",
  },
  running: {
    label: "In progress",
    headline: "Building and checking your application",
    description:
      "Proofline is matching the role to your evidence and checking every claim before publication.",
    symbol: "↻",
  },
  succeeded: {
    label: "Complete",
    headline: "Application ready",
    description: "Every published claim passed the evidence check.",
    symbol: "✓",
  },
  validation_failed: {
    label: "Not published",
    headline: "Evidence check stopped publication",
    description:
      "The draft contained material that could not be verified, so it was not published.",
    symbol: "!",
  },
  failed: {
    label: "Interrupted",
    headline: "The run did not finish",
    description: "Your saved inputs are still available.",
    symbol: "!",
  },
};

const FAILURE_MESSAGES: Record<string, string> = {
  checkpoint_persistence_error:
    "Progress could not be saved safely. You can resume when the service is available.",
  client_error: "The generation service could not accept this request.",
  configuration_error: "The generation service is not configured for this run.",
  connection_error: "The generation service could not be reached.",
  execution_interrupted: "The run was interrupted before it could finish.",
  invalid_executor_result: "The generated result could not be accepted safely.",
  invalid_response: "The generation service returned an unusable response.",
  persistence_error: "The result could not be saved safely.",
  quota_exceeded: "The generation service is temporarily unavailable.",
  rate_limited: "The generation service is busy. Please try again shortly.",
  server_error: "The generation service reported a temporary problem.",
  timeout: "The generation service took too long to respond.",
  unknown_error: "An unexpected problem interrupted the run.",
};

function failureDescription(errorCode: string | null): string {
  if (!errorCode) {
    return "An unexpected problem interrupted the run.";
  }
  return FAILURE_MESSAGES[errorCode] ?? "An unexpected problem interrupted the run.";
}

function formatTimestamp(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(timestamp);
}

export function RunStatus({
  run,
  jobTitle,
  connectivityError,
  isResuming = false,
  resumeError,
  onResume,
}: RunStatusProps) {
  const noResumeBullets =
    run.status === "succeeded" &&
    run.artifact !== null &&
    run.artifact.content.resume_bullets.length === 0;
  const presentation = noResumeBullets
    ? {
        ...STATUS_PRESENTATION.succeeded,
        headline: "Evidence review complete",
        description:
          "The package passed validation but contains no résumé bullets. Review the evidence gaps before preparing an application.",
      }
    : STATUS_PRESENTATION[run.status];
  const description =
    run.status === "failed"
      ? failureDescription(run.error_code)
      : presentation.description;
  const updatedAt = formatTimestamp(
    run.finished_at ?? run.started_at ?? run.created_at,
  );

  return (
    <section
      className={`run-status run-status--${run.status}`}
      aria-labelledby="run-status-heading"
      aria-busy={run.status === "queued" || run.status === "running"}
    >
      {connectivityError ? (
        <div className="connection-notice" role="status">
          <strong>Status updates are temporarily unavailable.</strong>
          <span>{connectivityError} The latest confirmed result remains below.</span>
        </div>
      ) : null}

      <div className="run-status__main">
        <span className="run-status__symbol" aria-hidden="true">
          {presentation.symbol}
        </span>
        <div className="run-status__copy" aria-live="polite">
          <span className="status-badge">{presentation.label}</span>
          <h2 id="run-status-heading">{presentation.headline}</h2>
          {jobTitle ? <p className="run-status__job">{jobTitle}</p> : null}
          <p>{description}</p>
        </div>

        <dl className="run-status__meta">
          {run.attempt_count > 0 ? (
            <div>
              <dt>Run history</dt>
              <dd>Attempt {run.attempt_count}</dd>
            </div>
          ) : null}
          {updatedAt ? (
            <div>
              <dt>Last updated</dt>
              <dd>
                <time dateTime={run.finished_at ?? run.started_at ?? run.created_at}>
                  {updatedAt}
                </time>
              </dd>
            </div>
          ) : null}
        </dl>
      </div>

      {run.can_resume && onResume ? (
        <div className="run-status__recovery">
          <div>
            <strong>Your completed steps are saved.</strong>
            <p>Resume from the latest safe checkpoint without starting over.</p>
          </div>
          <button
            className="primary-button primary-button--compact"
            type="button"
            disabled={isResuming}
            onClick={onResume}
          >
            {isResuming ? "Resuming…" : "Resume run"}
          </button>
        </div>
      ) : null}

      {resumeError ? (
        <div className="inline-error" role="alert">
          <strong>Resume did not start.</strong> {resumeError}
        </div>
      ) : null}
    </section>
  );
}
