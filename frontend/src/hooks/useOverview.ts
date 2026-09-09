import { useCallback, useEffect, useState } from "react";

import { getWorkspaceOverview } from "../api/agentPlatform";
import { getErrorMessage, isAbortError } from "../api/client";
import type { WorkspaceOverview } from "../api/contracts";

interface OverviewState {
  workspaceId: string;
  version: number;
  data: WorkspaceOverview | null;
  error: string | null;
}

export function useOverview(workspaceId: string) {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<OverviewState>({
    workspaceId: "",
    version: -1,
    data: null,
    error: null,
  });
  const refresh = useCallback(() => setVersion((previous) => previous + 1), []);

  useEffect(() => {
    if (!workspaceId) return;
    const controller = new AbortController();
    let current = true;
    void getWorkspaceOverview(workspaceId, { signal: controller.signal })
      .then((data) => {
        if (current) setState({ workspaceId, version, data, error: null });
      })
      .catch((error: unknown) => {
        if (!current || isAbortError(error)) return;
        setState((previous) => ({
          workspaceId,
          version,
          data: previous.workspaceId === workspaceId ? previous.data : null,
          error: getErrorMessage(error),
        }));
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [workspaceId, version]);

  const data = state.workspaceId === workspaceId ? state.data : null;
  const error = state.workspaceId === workspaceId ? state.error : null;
  const pending =
    Boolean(workspaceId) &&
    (state.workspaceId !== workspaceId || state.version !== version);
  return { data, error, pending, refresh };
}
