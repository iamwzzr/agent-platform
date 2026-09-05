import type { RunEventRead } from "../api/contracts";

interface EventTimelineProps {
  events: RunEventRead[];
}

interface EventPresentation {
  title: string;
  description: string;
  tone: "neutral" | "active" | "success" | "warning" | "danger";
}

const NODE_LABELS: Record<string, string> = {
  extract: "Role requirements analysed",
  retrieve: "Candidate evidence checked",
  draft: "Application draft prepared",
  validate: "Claims and citations validated",
  revise: "Application draft revised",
  terminal: "Final evidence check completed",
};

function stringField(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === "string" ? value : null;
}

function numberField(data: Record<string, unknown>, key: string): number | null {
  const value = data[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function eventPresentation(event: RunEventRead): EventPresentation {
  switch (event.kind) {
    case "queued":
      return {
        title: "Application queued",
        description: "The role and evidence were saved for processing.",
        tone: "neutral",
      };
    case "running":
      return {
        title: "Run started",
        description: "Evidence-led generation is now in progress.",
        tone: "active",
      };
    case "resumed":
      return {
        title: "Run resumed",
        description: "Processing continued from the latest safe checkpoint.",
        tone: "active",
      };
    case "node_completed": {
      const node = stringField(event.data, "node");
      return {
        title: node ? (NODE_LABELS[node] ?? "Workflow step completed") : "Workflow step completed",
        description: "This step was saved and will not need to be repeated.",
        tone: "success",
      };
    }
    case "retry_scheduled": {
      const attempt = numberField(event.data, "attempt");
      const maximum = numberField(event.data, "max_attempts");
      const attemptCopy =
        attempt === null
          ? "A bounded retry was scheduled."
          : maximum === null
            ? `Attempt ${attempt} was scheduled.`
            : `Attempt ${attempt} of ${maximum} was scheduled.`;
      return {
        title: "Temporary service issue",
        description: attemptCopy,
        tone: "warning",
      };
    }
    case "succeeded":
      return {
        title: "Application published",
        description: "The final material passed its evidence checks.",
        tone: "success",
      };
    case "validation_failed":
      return {
        title: "Publication stopped",
        description: "Unverified material was found and the draft was withheld.",
        tone: "warning",
      };
    case "failed":
      return {
        title: "Run interrupted",
        description: "The run stopped without publishing an application.",
        tone: "danger",
      };
    default:
      return {
        title: "System event",
        description: "A workflow update was recorded.",
        tone: "neutral",
      };
  }
}

function formatEventTime(value: string): string {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return "Time unavailable";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(timestamp);
}

export function EventTimeline({ events }: EventTimelineProps) {
  const orderedEvents = [...events].sort(
    (first, second) => first.sequence - second.sequence,
  );

  return (
    <section className="timeline-panel" aria-labelledby="run-timeline-heading">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="eyebrow">Run record</p>
          <h2 id="run-timeline-heading">Activity</h2>
        </div>
        <span className="record-count">
          {orderedEvents.length} {orderedEvents.length === 1 ? "event" : "events"}
        </span>
      </div>

      {orderedEvents.length === 0 ? (
        <p className="empty-state">No activity has been recorded yet.</p>
      ) : (
        <ol className="event-timeline" aria-label="Run activity in chronological order">
          {orderedEvents.map((event) => {
            const presentation = eventPresentation(event);
            return (
              <li className={`event event--${presentation.tone}`} key={event.id}>
                <span className="event__marker" aria-hidden="true" />
                <div className="event__content">
                  <div className="event__heading">
                    <strong>{presentation.title}</strong>
                    <time dateTime={event.created_at}>
                      {formatEventTime(event.created_at)}
                    </time>
                  </div>
                  <p>{presentation.description}</p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
