import { useCallback, useEffect, useState } from "react";

import { listJobs } from "../api/agentPlatform";
import { getErrorMessage, isAbortError } from "../api/client";
import type { JobListRead } from "../api/contracts";

export interface JobsQuery {
  q: string;
  limit: number;
  offset: number;
}

interface JobsState {
  requestKey: string;
  requestVersion: number;
  data: JobListRead | null;
  errorMessage: string | null;
}

export interface JobsResult {
  data: JobListRead | null;
  errorMessage: string | null;
  isInitialLoading: boolean;
  isRefreshing: boolean;
  refresh: () => void;
}

function makeRequestKey(workspaceId: string, query: JobsQuery): string {
  return JSON.stringify({ workspaceId, ...query });
}

export function useJobs(
  workspaceId: string,
  { q, limit, offset }: JobsQuery,
): JobsResult {
  const requestKey = makeRequestKey(workspaceId, { q, limit, offset });
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [state, setState] = useState<JobsState>({
    requestKey: "",
    requestVersion: -1,
    data: null,
    errorMessage: null,
  });

  const refresh = useCallback(() => {
    setRefreshVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    if (!workspaceId) {
      return;
    }

    const controller = new AbortController();
    let current = true;

    void listJobs(workspaceId, {
      q,
      limit,
      offset,
      signal: controller.signal,
    })
      .then((data) => {
        if (!current) {
          return;
        }
        setState({
          requestKey,
          requestVersion: refreshVersion,
          data,
          errorMessage: null,
        });
      })
      .catch((error: unknown) => {
        if (!current || isAbortError(error)) {
          return;
        }
        setState((previous) => ({
          requestKey,
          requestVersion: refreshVersion,
          data: previous.requestKey === requestKey ? previous.data : null,
          errorMessage: getErrorMessage(error),
        }));
      });

    return () => {
      current = false;
      controller.abort();
    };
  }, [limit, offset, q, refreshVersion, requestKey, workspaceId]);

  const data = state.requestKey === requestKey ? state.data : null;
  const errorMessage = state.requestKey === requestKey ? state.errorMessage : null;
  const isCurrentRequest =
    state.requestKey === requestKey && state.requestVersion === refreshVersion;

  return {
    data,
    errorMessage,
    isInitialLoading: Boolean(workspaceId) && !isCurrentRequest && data === null,
    isRefreshing: Boolean(workspaceId) && !isCurrentRequest && data !== null,
    refresh,
  };
}
