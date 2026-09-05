import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RunRead, RunStatus as RunStatusValue } from "../api/contracts";
import { RunStatus } from "./RunStatus";

describe("RunStatus terminal safety states", () => {
  it("explains validation failure without offering resume", () => {
    const onResume = vi.fn();

    render(
      <RunStatus
        run={terminalRun("validation_failed")}
        onResume={onResume}
      />,
    );

    expect(
      screen.getByRole("heading", {
        name: "Evidence check stopped publication",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume run" })).toBeNull();
    expect(onResume).not.toHaveBeenCalled();
  });

  it("does not offer resume for a permanent execution failure", () => {
    render(
      <RunStatus
        run={{
          ...terminalRun("failed"),
          error_code: "configuration_error",
        }}
        onResume={vi.fn()}
      />,
    );

    expect(
      screen.getByText("The generation service is not configured for this run."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume run" })).toBeNull();
  });
});

function terminalRun(status: RunStatusValue): RunRead {
  return {
    id: "40000000-0000-4000-8000-000000000004",
    workspace_id: "portfolio",
    job_id: "10000000-0000-4000-8000-000000000001",
    idempotency_key: "status-test-key",
    document_ids: ["20000000-0000-4000-8000-000000000002"],
    status,
    provider: "mock",
    model: "deterministic-mock-v1",
    current_node: "terminal",
    revision_count: 0,
    attempt_count: 1,
    retryable: false,
    can_resume: false,
    terminal_validation: null,
    error_code: null,
    created_at: "2026-09-05T08:00:00Z",
    started_at: "2026-09-05T08:00:00Z",
    finished_at: "2026-09-05T08:00:01Z",
    lease_expires_at: null,
    events: [],
    artifact: null,
  };
}
