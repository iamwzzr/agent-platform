import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import {
  createRunScenario,
  type ScenarioCalls,
} from "./test/runScenarios";
import { server } from "./test/server";

const ROLE_DESCRIPTION = "Build Python FastAPI services.";
const EVIDENCE_TEXT =
  "Built and operated Python FastAPI services in production.";

function renderApplication() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
}

async function fillAndStartApplication() {
  const user = userEvent.setup();
  renderApplication();

  const workspace = screen.getByRole("textbox", { name: /^Workspace/ });
  await user.clear(workspace);
  await user.type(workspace, "portfolio");
  await user.type(
    screen.getByRole("textbox", { name: "Role title" }),
    "Backend Engineer",
  );
  await user.type(
    screen.getByRole("textbox", { name: "Job description" }),
    ROLE_DESCRIPTION,
  );
  const evidenceFileName = screen.queryByRole("textbox", {
    name: "Evidence file name",
  });
  if (evidenceFileName) {
    await user.clear(evidenceFileName);
    await user.type(evidenceFileName, "resume.txt");
  }
  await user.type(
    screen.getByRole("textbox", { name: /^Evidence document/ }),
    EVIDENCE_TEXT,
  );
  await user.click(
    screen.getByRole("button", { name: /Prepare evidence/i }),
  );
  return user;
}

async function waitForApplicationReady() {
  return screen.findByRole(
    "heading",
    { name: /Application ready/i },
    { timeout: 3_000 },
  );
}

async function waitForPollingWindow() {
  await new Promise((resolve) => setTimeout(resolve, 100));
}

function expectOneCreateChain(calls: ScenarioCalls) {
  expect(calls.createJob).toBe(1);
  expect(calls.createDocument).toBe(1);
  expect(calls.ingestDocument).toBe(1);
  expect(calls.startRun).toBe(1);
  expect(calls.startKeys).toHaveLength(1);
  expect(calls.startKeys[0]).toMatch(/^\S+$/);
  expect(calls.startKeys).toEqual(calls.responseKeys);
  expect(new Set(calls.startKeys).size).toBe(1);
}

describe("Stage 9 application workbench smoke", () => {
  it("UI-01 creates a grounded run, shows its source, and stops polling", async () => {
    const scenario = createRunScenario("grounded");
    server.use(...scenario.handlers);
    const user = await fillAndStartApplication();

    await waitForApplicationReady();

    expect(
      screen.getByRole("heading", { name: /Application ready/i }),
    ).toBeInTheDocument();
    expectOneCreateChain(scenario.calls);
    expect(scenario.calls.getRun).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(EVIDENCE_TEXT).length).toBeGreaterThan(0);

    await user.click(
      screen.getByRole("button", { name: /Evidence 1/i }),
    );
    expect(
      screen.getByText(EVIDENCE_TEXT, { selector: "blockquote" }),
    ).toBeInTheDocument();
    expect(screen.getByText("System event")).toBeInTheDocument();
    expect(screen.queryByText("private-event-marker")).not.toBeInTheDocument();

    const readsAtTerminal = scenario.calls.getRun;
    await waitForPollingWindow();
    expect(scenario.calls.getRun).toBe(readsAtTerminal);
  });

  it("UI-02 succeeds with an explicit evidence gap and no fabricated citation", async () => {
    const scenario = createRunScenario("gap");
    server.use(...scenario.handlers);
    await fillAndStartApplication();

    await waitForApplicationReady();

    expect(
      screen.getByRole("heading", { name: /Application ready/i }),
    ).toBeInTheDocument();
    expectOneCreateChain(scenario.calls);
    expect(
      screen.getAllByText("Operate Kubernetes clusters.").length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Missing verified evidence")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Evidence 1/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(EVIDENCE_TEXT)).not.toBeInTheDocument();
  });

  it("UI-03 resumes one recoverable failure and reaches attempt two", async () => {
    const scenario = createRunScenario("recoverable");
    server.use(...scenario.handlers);
    const user = await fillAndStartApplication();

    const resumeButton = await screen.findByRole(
      "button",
      { name: /Resume run/i },
      { timeout: 3_000 },
    );

    expect(resumeButton).toBeInTheDocument();
    expectOneCreateChain(scenario.calls);
    expect(scenario.calls.resumeRun).toBe(0);

    await user.click(resumeButton);
    await waitForApplicationReady();

    expect(scenario.calls.resumeRun).toBe(1);
    expect(
      screen.getByRole("heading", { name: /Application ready/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Attempt 2/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Resume run/i }),
    ).not.toBeInTheDocument();

    const readsAtTerminal = scenario.calls.getRun;
    await waitForPollingWindow();
    expect(scenario.calls.getRun).toBe(readsAtTerminal);
    expect(scenario.calls.resumeRun).toBe(1);
  });
});
