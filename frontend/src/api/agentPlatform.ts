import type {
  DocumentCreate,
  DocumentIngestionRead,
  DocumentRead,
  JobCreate,
  JobRead,
  RunCreate,
  RunRead,
  UUID,
} from "./contracts";
import { requestJson } from "./client";

const API_ROOT = "/api/v1";

export interface RequestControl {
  signal?: AbortSignal;
}

function workspacePath(workspaceId: string): string {
  return `${API_ROOT}/workspaces/${encodeURIComponent(workspaceId)}`;
}

export function createJob(
  workspaceId: string,
  payload: JobCreate,
  control: RequestControl = {},
): Promise<JobRead> {
  return requestJson<JobRead>(`${workspacePath(workspaceId)}/jobs`, {
    method: "POST",
    json: payload,
    signal: control.signal,
  });
}

export function getJob(
  workspaceId: string,
  jobId: UUID,
  control: RequestControl = {},
): Promise<JobRead> {
  return requestJson<JobRead>(
    `${workspacePath(workspaceId)}/jobs/${encodeURIComponent(jobId)}`,
    { signal: control.signal },
  );
}

export function createDocument(
  workspaceId: string,
  payload: DocumentCreate,
  control: RequestControl = {},
): Promise<DocumentRead> {
  return requestJson<DocumentRead>(`${workspacePath(workspaceId)}/documents`, {
    method: "POST",
    json: payload,
    signal: control.signal,
  });
}

export function ingestDocument(
  workspaceId: string,
  documentId: UUID,
  control: RequestControl = {},
): Promise<DocumentIngestionRead> {
  return requestJson<DocumentIngestionRead>(
    `${workspacePath(workspaceId)}/documents/${encodeURIComponent(documentId)}/ingest`,
    { method: "POST", signal: control.signal },
  );
}

export function startRun(
  workspaceId: string,
  jobId: UUID,
  payload: RunCreate,
  idempotencyKey: string,
  control: RequestControl = {},
): Promise<RunRead> {
  return requestJson<RunRead>(
    `${workspacePath(workspaceId)}/jobs/${encodeURIComponent(jobId)}/runs`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      json: payload,
      signal: control.signal,
    },
  );
}

export function getRun(
  workspaceId: string,
  runId: UUID,
  control: RequestControl = {},
): Promise<RunRead> {
  return requestJson<RunRead>(
    `${workspacePath(workspaceId)}/runs/${encodeURIComponent(runId)}`,
    { signal: control.signal },
  );
}

export function resumeRun(
  workspaceId: string,
  runId: UUID,
  control: RequestControl = {},
): Promise<RunRead> {
  return requestJson<RunRead>(
    `${workspacePath(workspaceId)}/runs/${encodeURIComponent(runId)}/resume`,
    { method: "POST", signal: control.signal },
  );
}

export const agentPlatformApi = {
  createJob,
  getJob,
  createDocument,
  ingestDocument,
  startRun,
  getRun,
  resumeRun,
} as const;
