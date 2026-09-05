import { Link } from "react-router-dom";

interface AppHeaderProps {
  workspaceId?: string;
  backTo?: string;
}

export function AppHeader({ workspaceId, backTo }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header__inner">
        <Link className="brand" to="/" aria-label="Proofline home">
          <span className="brand-mark" aria-hidden="true">
            P
          </span>
          <span className="brand-copy">
            <strong>Proofline</strong>
            <small>Evidence-led applications</small>
          </span>
        </Link>

        <div className="app-header__actions">
          {workspaceId ? (
            <span className="workspace-chip" title={workspaceId}>
              <span aria-hidden="true" />
              <span className="workspace-chip__label">Workspace</span>
              <span className="workspace-chip__value">{workspaceId}</span>
            </span>
          ) : null}
          {backTo ? (
            <Link className="quiet-link" to={backTo}>
              <span aria-hidden="true">←</span>
              New application
            </Link>
          ) : null}
        </div>
      </div>
    </header>
  );
}
