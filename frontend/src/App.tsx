import { Navigate, Route, Routes } from "react-router-dom";

import { CreateRunPage } from "./pages/CreateRunPage";
import { JobsPage } from "./pages/JobsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RunPage } from "./pages/RunPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<CreateRunPage />} />
      <Route path="/overview" element={<OverviewPage />} />
      <Route path="/workspaces/:workspaceId/overview" element={<OverviewPage />} />
      <Route path="/workspaces/:workspaceId/jobs" element={<JobsPage />} />
      <Route
        path="/workspaces/:workspaceId/runs/:runId"
        element={<RunPage />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
