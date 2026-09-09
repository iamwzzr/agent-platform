export type UUID = string;

export type ISODateTime = string;

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface JobCreate {
  title: string;
  description: string;
}

export interface JobRead extends JobCreate {
  id: UUID;
  workspace_id: string;
  created_at: ISODateTime;
}

export interface JobSummary {
  id: UUID;
  workspace_id: string;
  title: string;
  created_at: ISODateTime;
}

export interface JobListRead {
  items: JobSummary[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface DocumentCreate {
  name: string;
  content: string;
}

export interface DocumentRead extends DocumentCreate {
  id: UUID;
  workspace_id: string;
  created_at: ISODateTime;
}

export interface DocumentChunkRead {
  id: UUID;
  workspace_id: string;
  document_id: UUID;
  position: number;
  content: string;
  created_at: ISODateTime;
}

export interface DocumentIngestionRead {
  document_id: UUID;
  workspace_id: string;
  chunk_count: number;
  chunks: DocumentChunkRead[];
}

export interface RunCreate {
  document_ids: UUID[];
}

export type RequirementPriority = "high" | "medium" | "low";

export interface Requirement {
  id: string;
  text: string;
  priority: RequirementPriority;
}

export interface Citation {
  document_id: UUID;
  chunk_id: UUID;
}

export interface Claim {
  id: string;
  text: string;
  requirement_ids: string[];
  citation_chunk_ids: UUID[];
}

export interface ResumeBullet {
  text: string;
  claim_ids: string[];
}

export interface Gap {
  requirement_id: string;
  reason_code: "no_grounded_evidence";
}

export interface ApplicationArtifact {
  run_id: UUID;
  requirements: Requirement[];
  claims: Claim[];
  resume_bullets: ResumeBullet[];
  cover_letter: string | null;
  gaps: Gap[];
  citations: Citation[];
}

export interface ArtifactValidation {
  passed: boolean;
  invalid_citation_chunk_ids: UUID[];
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
  unsupported_citation_chunk_ids: UUID[];
  run_id_mismatch: boolean;
}

export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "validation_failed"
  | "failed";

export interface RunEventRead {
  id: UUID;
  run_id: UUID;
  sequence: number;
  kind: string;
  data: Record<string, JsonValue>;
  created_at: ISODateTime;
}

export interface CitationSourceRead {
  document_id: UUID;
  document_name: string;
  chunk_id: UUID;
  position: number;
  excerpt: string;
}

export interface RunArtifactRead {
  id: UUID;
  run_id: UUID;
  content: ApplicationArtifact;
  validation: ArtifactValidation;
  citation_sources: CitationSourceRead[];
  created_at: ISODateTime;
}

export interface RunRead {
  id: UUID;
  workspace_id: string;
  job_id: UUID;
  idempotency_key: string;
  document_ids: UUID[];
  status: RunStatus;
  provider: string;
  model: string;
  current_node: string | null;
  revision_count: number;
  attempt_count: number;
  retryable: boolean;
  can_resume: boolean;
  terminal_validation: ArtifactValidation | null;
  error_code: string | null;
  created_at: ISODateTime;
  started_at: ISODateTime | null;
  finished_at: ISODateTime | null;
  lease_expires_at: ISODateTime | null;
  events: RunEventRead[];
  artifact: RunArtifactRead | null;
}

export interface FastAPIValidationIssue {
  type: string;
  loc: Array<string | number>;
  msg: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface FastAPIErrorResponse {
  detail: string | FastAPIValidationIssue[];
}
export interface WorkspaceOverview {
  workspace_id: string;
  generated_at: string;
  configuration: {
    provider: string;
    model: string;
    max_revisions: number;
    provider_retry_max_attempts: number;
    provider_retry_initial_delay_seconds: number;
    retrieval_method: "deterministic_sparse_cosine";
    retrieval_top_k: number;
  };
  usage: {
    saved_jobs: number;
    jobs_with_runs: number;
    runs: number;
    succeeded_runs: number;
    validation_failed_runs: number;
    failed_runs: number;
    active_runs: number;
    published_artifacts: number;
    jobs_with_published_artifacts: number;
    mock_runs: number;
    openai_runs: number;
    other_provider_runs: number;
    artifacts_with_resume_bullets: number;
    gap_only_artifacts: number;
    resume_bullets: number;
    gaps: number;
    cover_letters: number;
  };
}
