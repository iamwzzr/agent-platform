import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../App";
import type { WorkspaceOverview } from "../api/contracts";
import { server } from "../test/server";

const OVERVIEW: WorkspaceOverview = {
  workspace_id: "demo",
  generated_at: "2026-09-09T08:00:00Z",
  configuration: {
    provider: "mock",
    model: "deterministic-mock-v1",
    max_revisions: 2,
    provider_retry_max_attempts: 3,
    provider_retry_initial_delay_seconds: 0.5,
    retrieval_method: "deterministic_sparse_cosine",
    retrieval_top_k: 5,
  },
  usage: {
    saved_jobs: 2,
    jobs_with_runs: 2,
    runs: 3,
    succeeded_runs: 3,
    validation_failed_runs: 0,
    failed_runs: 0,
    active_runs: 0,
    published_artifacts: 3,
    jobs_with_published_artifacts: 2,
    mock_runs: 3,
    openai_runs: 0,
    other_provider_runs: 0,
    artifacts_with_resume_bullets: 1,
    gap_only_artifacts: 2,
    resume_bullets: 1,
    gaps: 2,
    cover_letters: 0,
  },
};

function renderOverview(path = "/workspaces/demo/overview") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("Agent overview", () => {
  it("loads real API counts, separates gap-only packages, and explains the graph and Mock boundary", async () => {
    const methods: string[] = [];
    server.use(
      http.get(
        "*/api/v1/workspaces/:workspaceId/overview",
        async ({ request }) => {
          methods.push(request.method);
          await delay(25);
          return HttpResponse.json(OVERVIEW);
        },
      ),
    );
    renderOverview();
    expect(screen.getByRole("status")).toHaveTextContent("Loading Agent overview");
    await screen.findByText("Mock mode — deterministic rules, no model API calls.");
    expect(
      screen.getByText("Saved JD records").nextElementSibling,
    ).toHaveTextContent("2");
    expect(
      screen.getByText("Published packages").nextElementSibling,
    ).toHaveTextContent("3");
    expect(
      screen.getByText("Packages with résumé bullets").nextElementSibling,
    ).toHaveTextContent("1");
    expect(
      screen.getByText("Gap-only packages").nextElementSibling,
    ).toHaveTextContent("2");
    expect(screen.getByText("Six nodes, not six Agents")).toBeInTheDocument();
    expect(screen.getAllByText("Provider call")).toHaveLength(2);
    expect(screen.getByText(/not a semantic fact-check/)).toBeInTheDocument();
    expect(
      screen.getByText(/Non-empty cover letters are currently rejected/),
    ).toBeInTheDocument();
    expect(methods).toEqual(["GET"]);
  });

  it("retains the current snapshot on refresh failure and can retry", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/workspaces/:workspaceId/overview", () => {
        calls += 1;
        return calls === 2
          ? HttpResponse.json({ detail: "outage" }, { status: 503 })
          : HttpResponse.json(OVERVIEW);
      }),
    );
    const user = userEvent.setup();
    renderOverview();
    await screen.findByText("Published packages");
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("The latest overview refresh failed");
    expect(
      screen.getByText("Published packages").nextElementSibling,
    ).toHaveTextContent("3");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(calls).toBe(3);
  });

  it("does not show the previous workspace's counts while another workspace loads or fails", async () => {
    server.use(
      http.get(
        "*/api/v1/workspaces/:workspaceId/overview",
        async ({ params }) => {
          if (params.workspaceId === "demo") return HttpResponse.json(OVERVIEW);
          await delay(40);
          return HttpResponse.json({ detail: "outage" }, { status: 503 });
        },
      ),
    );
    const user = userEvent.setup();
    renderOverview();
    await screen.findByText("Published packages");
    await user.clear(screen.getByRole("textbox", { name: "Inspect workspace" }));
    await user.type(
      screen.getByRole("textbox", { name: "Inspect workspace" }),
      "another",
    );
    await user.click(screen.getByRole("button", { name: "View workspace" }));
    expect(screen.queryByText("Published packages")).not.toBeInTheDocument();
    await screen.findByText("Agent overview could not be loaded");
    expect(screen.queryByText("Published packages")).not.toBeInTheDocument();
  });

  it("offers a workspace picker without inventing usage on the unscoped guide page", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/v1/workspaces/:workspaceId/overview", ({ params }) => {
        expect(params.workspaceId).toBe("demo");
        return HttpResponse.json(OVERVIEW);
      }),
    );
    renderOverview("/overview");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText("Published packages")).not.toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "Inspect workspace" }),
      "demo",
    );
    await user.click(screen.getByRole("button", { name: "View workspace" }));
    await screen.findByText("Published packages");
  });

  it("does not label OpenAI configuration as verified model quality", async () => {
    server.use(
      http.get("*/api/v1/workspaces/:workspaceId/overview", () =>
        HttpResponse.json({
          ...OVERVIEW,
          configuration: {
            ...OVERVIEW.configuration,
            provider: "openai",
            model: "configured-model",
            max_revisions: 0,
          },
        }),
      ),
    );
    renderOverview();
    await screen.findByText(
      "OpenAI mode selected — configuration alone does not prove live-model success.",
    );
    expect(
      screen.getByText("At most 0 revisions after the first draft"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Historical runs: 3 Mock \/ 0 OpenAI/),
    ).toBeInTheDocument();
  });
});
