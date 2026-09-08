import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../App";
import { server } from "../test/server";

const FIRST_JOB = {
  id: "10000000-0000-4000-8000-000000000001",
  workspace_id: "portfolio",
  title: "Python Platform Engineer",
  created_at: "2026-09-08T09:00:00Z",
};

const SECOND_JOB = {
  id: "10000000-0000-4000-8000-000000000002",
  workspace_id: "portfolio",
  title: "Python Backend Engineer",
  created_at: "2026-09-08T08:00:00Z",
};

function renderJobs(initialEntry = "/workspaces/portfolio/jobs") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <App />
    </MemoryRouter>,
  );
}

describe("saved roles page", () => {
  it("shows a loading state, searches from the URL contract, and moves between pages", async () => {
    const requests: string[] = [];
    server.use(
      http.get("*/api/v1/workspaces/:workspaceId/jobs", async ({ request }) => {
        const url = new URL(request.url);
        requests.push(url.search);
        await delay(25);
        const query = url.searchParams.get("q");
        const offset = url.searchParams.get("offset");
        if (query === "Python" && offset === "20") {
          return HttpResponse.json({
            items: [SECOND_JOB],
            limit: 20,
            offset: 20,
            has_more: false,
          });
        }
        if (query === "Python") {
          return HttpResponse.json({
            items: [FIRST_JOB],
            limit: 20,
            offset: 0,
            has_more: true,
          });
        }
        return HttpResponse.json({
          items: [],
          limit: 20,
          offset: 0,
          has_more: false,
        });
      }),
    );
    const user = userEvent.setup();
    renderJobs();

    expect(screen.getByText("Loading saved roles…")).toBeInTheDocument();
    await screen.findByRole("heading", { name: "No saved roles yet" });

    await user.type(
      screen.getByRole("searchbox", { name: "Search saved roles" }),
      "Python",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByRole("heading", { name: FIRST_JOB.title });
    expect(screen.getByText("Page 1")).toBeInTheDocument();
    expect(requests.at(-1)).toBe("?limit=20&offset=0&q=Python");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByRole("heading", { name: SECOND_JOB.title });
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(requests.at(-1)).toBe("?limit=20&offset=20&q=Python");
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("keeps the saved list visible when a refresh fails and retries the same request", async () => {
    let requestCount = 0;
    server.use(
      http.get("*/api/v1/workspaces/:workspaceId/jobs", () => {
        requestCount += 1;
        if (requestCount === 2) {
          return HttpResponse.json(
            { detail: "temporary outage" },
            { status: 503 },
          );
        }
        return HttpResponse.json({
          items: [FIRST_JOB],
          limit: 20,
          offset: 0,
          has_more: false,
        });
      }),
    );
    const user = userEvent.setup();
    renderJobs();

    await screen.findByRole("heading", { name: FIRST_JOB.title });
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await screen.findByText("The latest refresh failed");
    expect(screen.getByRole("heading", { name: FIRST_JOB.title })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(requestCount).toBe(3));
    expect(screen.queryByText("The latest refresh failed")).not.toBeInTheDocument();
  });

  it("renders an actionable error when the first load cannot reach the service", async () => {
    server.use(
      http.get("*/api/v1/workspaces/:workspaceId/jobs", () =>
        HttpResponse.json({ detail: "temporary outage" }, { status: 503 }),
      ),
    );
    renderJobs();

    expect(
      await screen.findByText("Saved roles could not be loaded"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
