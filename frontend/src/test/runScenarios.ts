import { http, HttpResponse, type HttpHandler } from "msw";

export const WORKSPACE_ID = "portfolio";
export const JOB_ID = "10000000-0000-4000-8000-000000000001";
export const DOCUMENT_ID = "20000000-0000-4000-8000-000000000002";
export const CHUNK_ID = "30000000-0000-4000-8000-000000000003";
export const RUN_ID = "40000000-0000-4000-8000-000000000004";

const ARTIFACT_ID = "50000000-0000-4000-8000-000000000005";
const NOW = "2026-09-05T08:00:00Z";
const EVIDENCE_TEXT =
  "Built and operated Python FastAPI services in production.";

type ScenarioName = "grounded" | "gap" | "recoverable";

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

interface RunEvent {
  id: string;
  run_id: string;
  sequence: number;
  kind: string;
  data: Record<string, JsonValue>;
  created_at: string;
}

interface ArtifactValidation {
  passed: boolean;
  invalid_citation_chunk_ids: string[];
  unsupported_claim_ids: string[];
  unsupported_requirement_ids: string[];
  unsupported_resume_bullet_indexes: number[];
  unsupported_cover_letter: boolean;
  uncovered_requirement_ids: string[];
  conflicting_requirement_ids: string[];
  mismatched_requirement_ids: string[];
  duplicate_requirement_ids: string[];
  unknown_gap_requirement_ids: string[];
  evidenced_gap_requirement_ids: string[];
  duplicate_gap_requirement_ids: string[];
  duplicate_claim_ids: string[];
  unsupported_citation_chunk_ids: string[];
  run_id_mismatch: boolean;
}

interface RunArtifact {
  id: string;
  run_id: string;
  content: {
    run_id: string;
    requirements: Array<{
      id: string;
      text: string;
      priority: "high" | "medium" | "low";
    }>;
    claims: Array<{
      id: string;
      text: string;
      requirement_ids: string[];
      citation_chunk_ids: string[];
    }>;
    resume_bullets: Array<{ text: string; claim_ids: string[] }>;
    cover_letter: string | null;
    gaps: Array<{
      requirement_id: string;
      reason_code: "no_grounded_evidence";
    }>;
    citations: Array<{ document_id: string; chunk_id: string }>;
  };
  validation: ArtifactValidation;
  citation_sources: Array<{
    document_id: string;
    document_name: string;
    chunk_id: string;
    position: number;
    excerpt: string;
  }>;
  created_at: string;
}

interface RunSnapshot {
  id: string;
  workspace_id: string;
  job_id: string;
  idempotency_key: string;
  document_ids: string[];
  status:
    | "queued"
    | "running"
    | "succeeded"
    | "validation_failed"
    | "failed";
  provider: string;
  model: string;
  current_node: string | null;
  revision_count: number;
  attempt_count: number;
  retryable: boolean;
  can_resume: boolean;
  terminal_validation: ArtifactValidation | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  lease_expires_at: string | null;
  events: RunEvent[];
  artifact: RunArtifact | null;
}

export interface ScenarioCalls {
  createJob: number;
  createDocument: number;
  ingestDocument: number;
  startRun: number;
  getRun: number;
  resumeRun: number;
  startKeys: string[];
  responseKeys: string[];
}

export interface RunScenario {
  calls: ScenarioCalls;
  handlers: HttpHandler[];
}

const passingValidation: ArtifactValidation = {
  passed: true,
  invalid_citation_chunk_ids: [],
  unsupported_claim_ids: [],
  unsupported_requirement_ids: [],
  unsupported_resume_bullet_indexes: [],
  unsupported_cover_letter: false,
  uncovered_requirement_ids: [],
  conflicting_requirement_ids: [],
  mismatched_requirement_ids: [],
  duplicate_requirement_ids: [],
  unknown_gap_requirement_ids: [],
  evidenced_gap_requirement_ids: [],
  duplicate_gap_requirement_ids: [],
  duplicate_claim_ids: [],
  unsupported_citation_chunk_ids: [],
  run_id_mismatch: false,
};

function runEvent(
  sequence: number,
  kind: string,
  data: Record<string, JsonValue> = {},
): RunEvent {
  const eventSuffix = String(sequence + 10).padStart(12, "0");
  return {
    id: `60000000-0000-4000-8000-${eventSuffix}`,
    run_id: RUN_ID,
    sequence,
    kind,
    data,
    created_at: NOW,
  };
}

const activeEvents = [
  runEvent(0, "queued"),
  runEvent(1, "running", { attempt: 1 }),
];

const groundedArtifact: RunArtifact = {
  id: ARTIFACT_ID,
  run_id: RUN_ID,
  content: {
    run_id: RUN_ID,
    requirements: [
      {
        id: "req-1",
        text: "Build Python FastAPI services.",
        priority: "high",
      },
    ],
    claims: [
      {
        id: "claim-1",
        text: EVIDENCE_TEXT,
        requirement_ids: ["req-1"],
        citation_chunk_ids: [CHUNK_ID],
      },
    ],
    resume_bullets: [
      {
        text: EVIDENCE_TEXT,
        claim_ids: ["claim-1"],
      },
    ],
    cover_letter: null,
    gaps: [],
    citations: [{ document_id: DOCUMENT_ID, chunk_id: CHUNK_ID }],
  },
  validation: passingValidation,
  citation_sources: [
    {
      document_id: DOCUMENT_ID,
      document_name: "resume.txt",
      chunk_id: CHUNK_ID,
      position: 0,
      excerpt: EVIDENCE_TEXT,
    },
  ],
  created_at: NOW,
};

const gapArtifact: RunArtifact = {
  id: ARTIFACT_ID,
  run_id: RUN_ID,
  content: {
    run_id: RUN_ID,
    requirements: [
      {
        id: "req-1",
        text: "Operate Kubernetes clusters.",
        priority: "high",
      },
    ],
    claims: [],
    resume_bullets: [],
    cover_letter: null,
    gaps: [
      {
        requirement_id: "req-1",
        reason_code: "no_grounded_evidence",
      },
    ],
    citations: [],
  },
  validation: passingValidation,
  citation_sources: [],
  created_at: NOW,
};

function activeRun(idempotencyKey: string, attemptCount = 1): RunSnapshot {
  return {
    id: RUN_ID,
    workspace_id: WORKSPACE_ID,
    job_id: JOB_ID,
    idempotency_key: idempotencyKey,
    document_ids: [DOCUMENT_ID],
    status: "running",
    provider: "mock",
    model: "deterministic-mock-v1",
    current_node: null,
    revision_count: 0,
    attempt_count: attemptCount,
    retryable: false,
    can_resume: false,
    terminal_validation: null,
    error_code: null,
    created_at: NOW,
    started_at: NOW,
    finished_at: null,
    lease_expires_at: "2026-09-05T08:05:00Z",
    events: activeEvents,
    artifact: null,
  };
}

function succeededRun(
  idempotencyKey: string,
  artifact: RunArtifact,
  attemptCount = 1,
  events: RunEvent[] = [...activeEvents, runEvent(2, "succeeded")],
): RunSnapshot {
  return {
    ...activeRun(idempotencyKey, attemptCount),
    status: "succeeded",
    current_node: "terminal",
    finished_at: "2026-09-05T08:00:02Z",
    lease_expires_at: null,
    events,
    artifact,
  };
}

function failedRun(idempotencyKey: string): RunSnapshot {
  return {
    ...activeRun(idempotencyKey),
    status: "failed",
    current_node: "retrieve",
    retryable: true,
    can_resume: true,
    error_code: "connection_error",
    finished_at: "2026-09-05T08:00:01Z",
    lease_expires_at: null,
    events: [
      ...activeEvents,
      runEvent(2, "failed", {
        reason_code: "connection_error",
        retryable: true,
      }),
    ],
  };
}

export function createRunScenario(name: ScenarioName): RunScenario {
  const calls: ScenarioCalls = {
    createJob: 0,
    createDocument: 0,
    ingestDocument: 0,
    startRun: 0,
    getRun: 0,
    resumeRun: 0,
    startKeys: [],
    responseKeys: [],
  };
  let idempotencyKey = "";
  let resumed = false;

  const handlers: HttpHandler[] = [
    http.post(
      "*/api/v1/workspaces/:workspaceId/jobs",
      async ({ params, request }) => {
        calls.createJob += 1;
        const payload = (await request.json()) as {
          title?: unknown;
          description?: unknown;
        };
        if (
          params.workspaceId !== WORKSPACE_ID ||
          payload.title !== "Backend Engineer" ||
          payload.description !== "Build Python FastAPI services."
        ) {
          return HttpResponse.json(
            { detail: "Invalid job request" },
            { status: 422 },
          );
        }
        return HttpResponse.json(
          {
            id: JOB_ID,
            workspace_id: WORKSPACE_ID,
            title: "Backend Engineer",
            description: "Build Python FastAPI services.",
            created_at: NOW,
          },
          { status: 201 },
        );
      },
    ),
    http.get(
      "*/api/v1/workspaces/:workspaceId/jobs/:jobId",
      ({ params }) =>
        params.workspaceId === WORKSPACE_ID && params.jobId === JOB_ID
          ? HttpResponse.json({
              id: JOB_ID,
              workspace_id: WORKSPACE_ID,
              title: "Backend Engineer",
              description: "Build Python FastAPI services.",
              created_at: NOW,
            })
          : HttpResponse.json({ detail: "Job not found" }, { status: 404 }),
    ),
    http.post(
      "*/api/v1/workspaces/:workspaceId/documents",
      async ({ params, request }) => {
        calls.createDocument += 1;
        const payload = (await request.json()) as {
          name?: unknown;
          content?: unknown;
        };
        if (
          params.workspaceId !== WORKSPACE_ID ||
          typeof payload.name !== "string" ||
          !payload.name.trim() ||
          payload.content !== EVIDENCE_TEXT
        ) {
          return HttpResponse.json(
            { detail: "Invalid document request" },
            { status: 422 },
          );
        }
        return HttpResponse.json(
          {
            id: DOCUMENT_ID,
            workspace_id: WORKSPACE_ID,
            name: "resume.txt",
            content: EVIDENCE_TEXT,
            created_at: NOW,
          },
          { status: 201 },
        );
      },
    ),
    http.post(
      "*/api/v1/workspaces/:workspaceId/documents/:documentId/ingest",
      ({ params }) => {
        calls.ingestDocument += 1;
        if (
          params.workspaceId !== WORKSPACE_ID ||
          params.documentId !== DOCUMENT_ID
        ) {
          return HttpResponse.json(
            { detail: "Document not found" },
            { status: 404 },
          );
        }
        return HttpResponse.json({
          document_id: DOCUMENT_ID,
          workspace_id: WORKSPACE_ID,
          chunk_count: 1,
          chunks: [
            {
              id: CHUNK_ID,
              workspace_id: WORKSPACE_ID,
              document_id: DOCUMENT_ID,
              position: 0,
              content: EVIDENCE_TEXT,
              created_at: NOW,
            },
          ],
        });
      },
    ),
    http.post(
      "*/api/v1/workspaces/:workspaceId/jobs/:jobId/runs",
      async ({ params, request }) => {
        calls.startRun += 1;
        const requestKey = request.headers.get("Idempotency-Key") ?? "";
        idempotencyKey ||= requestKey;
        calls.startKeys.push(requestKey);
        const payload = (await request.json()) as { document_ids?: unknown };
        if (
          params.workspaceId !== WORKSPACE_ID ||
          params.jobId !== JOB_ID ||
          !requestKey ||
          !Array.isArray(payload.document_ids) ||
          payload.document_ids[0] !== DOCUMENT_ID
        ) {
          return HttpResponse.json(
            { detail: "Invalid run request" },
            { status: 422 },
          );
        }
        calls.responseKeys.push(idempotencyKey);
        return HttpResponse.json(activeRun(idempotencyKey), { status: 202 });
      },
    ),
    http.get("*/api/v1/workspaces/:workspaceId/runs/:runId", ({ params }) => {
      calls.getRun += 1;
      if (params.workspaceId !== WORKSPACE_ID || params.runId !== RUN_ID) {
        return HttpResponse.json({ detail: "Run not found" }, { status: 404 });
      }
      if (name === "recoverable" && !resumed) {
        return HttpResponse.json(failedRun(idempotencyKey));
      }
      if (name === "gap") {
        if (calls.getRun === 1) {
          return HttpResponse.json(activeRun(idempotencyKey));
        }
        return HttpResponse.json(succeededRun(idempotencyKey, gapArtifact));
      }
      if (name === "grounded") {
        if (calls.getRun === 1) {
          return HttpResponse.json({
            ...activeRun(idempotencyKey),
            current_node: "retrieve",
            events: [
              ...activeEvents,
              runEvent(2, "node_completed", { node: "extract" }),
              runEvent(3, "node_completed", { node: "retrieve" }),
            ],
          });
        }
        return HttpResponse.json(
          succeededRun(idempotencyKey, groundedArtifact, 1, [
            ...activeEvents,
            runEvent(2, "node_completed", { node: "extract" }),
            runEvent(3, "node_completed", { node: "retrieve" }),
            runEvent(4, "future_internal_event", {
              private: "private-event-marker",
            }),
            runEvent(5, "succeeded"),
          ]),
        );
      }
      return HttpResponse.json(
        succeededRun(idempotencyKey, groundedArtifact, 2, [
          ...activeEvents,
          runEvent(2, "failed", {
            reason_code: "connection_error",
            retryable: true,
          }),
          runEvent(3, "resumed", { attempt: 2 }),
          runEvent(4, "succeeded"),
        ]),
      );
    }),
    http.post(
      "*/api/v1/workspaces/:workspaceId/runs/:runId/resume",
      ({ params }) => {
        calls.resumeRun += 1;
        if (params.workspaceId !== WORKSPACE_ID || params.runId !== RUN_ID) {
          return HttpResponse.json({ detail: "Run not found" }, { status: 404 });
        }
        resumed = true;
        return HttpResponse.json(
          {
            ...activeRun(idempotencyKey, 2),
            events: [
              ...activeEvents,
              runEvent(2, "failed", {
                reason_code: "connection_error",
                retryable: true,
              }),
              runEvent(3, "resumed", { attempt: 2 }),
            ],
          },
          { status: 202 },
        );
      },
    ),
  ];

  return { calls, handlers };
}
