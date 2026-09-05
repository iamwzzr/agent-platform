import { useCallback, useEffect, useState } from "react";

import { getRun } from "../api/agentPlatform";
import { getErrorMessage, isAbortError, isApiError } from "../api/client";
import type { RunRead } from "../api/contracts";

const ACTIVE_STATUSES = new Set<RunRead["status"]>(["queued", "running"]);

export const DEFAULT_POLL_INTERVAL_MS = import.meta.env.MODE === "test" ? 20 : 1_500;

interface RunPollingState {
  run: RunRead | null;
  errorMessage: string | null;
  isInitialLoading: boolean;
  notFound: boolean;
}

export interface RunPollingResult extends RunPollingState {
  refresh: () => void;
}

export function useRunPolling(
  workspaceId: string,
  runId: string,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
): RunPollingResult {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [state, setState] = useState<RunPollingState>({
    run: null,
    errorMessage: null,
    isInitialLoading: true,
    notFound: false,
  });

  const refresh = useCallback(() => {
    setRefreshVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    let stopped = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let latestRun: RunRead | null = null;

    setState((current) => {
      const belongsToRoute =
        current.run?.id === runId && current.run.workspace_id === workspaceId;
      return belongsToRoute
        ? { ...current, errorMessage: null, notFound: false }
        : {
            run: null,
            errorMessage: null,
            isInitialLoading: true,
            notFound: false,
          };
    });

    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const schedule = (poll: () => Promise<void>) => {
      clearTimer();
      if (!stopped && document.visibilityState !== "hidden") {
        timer = setTimeout(() => void poll(), pollIntervalMs);
      }
    };

    const poll = async (): Promise<void> => {
      if (stopped || inFlight || document.visibilityState === "hidden") {
        return;
      }

      inFlight = true;
      controller = new AbortController();
      try {
        const run = await getRun(workspaceId, runId, {
          signal: controller.signal,
        });
        if (stopped) {
          return;
        }
        latestRun = run;
        setState({
          run,
          errorMessage: null,
          isInitialLoading: false,
          notFound: false,
        });
        if (ACTIVE_STATUSES.has(run.status)) {
          schedule(poll);
        }
      } catch (error: unknown) {
        if (stopped || isAbortError(error)) {
          return;
        }

        const notFound = isApiError(error) && error.status === 404;
        setState((current) => ({
          ...current,
          run: notFound ? null : current.run,
          errorMessage: getErrorMessage(error),
          isInitialLoading: false,
          notFound,
        }));
        if (!notFound && (!latestRun || ACTIVE_STATUSES.has(latestRun.status))) {
          schedule(poll);
        }
      } finally {
        inFlight = false;
        controller = null;
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        clearTimer();
        controller?.abort();
        return;
      }
      void poll();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    void poll();

    return () => {
      stopped = true;
      clearTimer();
      controller?.abort();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [pollIntervalMs, refreshVersion, runId, workspaceId]);

  return { ...state, refresh };
}
