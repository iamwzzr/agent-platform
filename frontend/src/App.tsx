import { Navigate, Route, Routes } from "react-router-dom";

import { CreateRunPage } from "./pages/CreateRunPage";
import { RunPage } from "./pages/RunPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<CreateRunPage />} />
      <Route
        path="/workspaces/:workspaceId/runs/:runId"
        element={<RunPage />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
