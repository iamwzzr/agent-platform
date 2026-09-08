import { useParams, useSearchParams } from "react-router-dom";

import { AppHeader } from "../components/AppHeader";
import { ErrorNotice } from "../components/ErrorNotice";
import { useJobs } from "../hooks/useJobs";

const PAGE_SIZE = 20;

function parsePage(value: string | null): number {
  if (!value || !/^[1-9]\d*$/.test(value)) {
    return 1;
  }

  const page = Number(value);
  return Number.isSafeInteger(page) ? page : 1;
}

function formatTimestamp(value: string): string {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return "Saved date unavailable";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(timestamp);
}

function buildSearchParams(query: string, page: number): URLSearchParams {
  const params = new URLSearchParams();
  if (query) {
    params.set("q", query);
  }
  if (page > 1) {
    params.set("page", String(page));
  }
  return params;
}

export function JobsPage() {
  const { workspaceId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q")?.trim() ?? "";
  const page = parsePage(searchParams.get("page"));
  const { data, errorMessage, isInitialLoading, isRefreshing, refresh } =
    useJobs(workspaceId, {
      q: query,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    });

  const submitSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const nextQuery = String(formData.get("q") ?? "").trim();
    setSearchParams(buildSearchParams(nextQuery, 1));
  };

  const moveToPage = (nextPage: number) => {
    setSearchParams(buildSearchParams(query, nextPage));
  };

  if (!workspaceId) {
    return (
      <main className="app-shell">
        <AppHeader backTo="/" />
        <ErrorNotice
          title="Workspace address is incomplete"
          message="Open the saved roles page from a workspace."
        />
      </main>
    );
  }

  const totalLabel = data
    ? `${data.items.length} saved ${data.items.length === 1 ? "role" : "roles"}`
    : "Saved roles";

  return (
    <main className="app-shell">
      <AppHeader workspaceId={workspaceId} backTo="/" />

      <section className="jobs-heading">
        <div>
          <p className="eyebrow">Workspace library</p>
          <h1>Saved roles</h1>
          <p>Search the role records that are available for this workspace.</p>
        </div>
      </section>

      <section className="panel jobs-panel" aria-busy={isInitialLoading || isRefreshing}>
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Role records</p>
            <h2>{totalLabel}</h2>
          </div>
          {isRefreshing ? (
            <p className="jobs-refreshing" role="status">
              <span className="loading-spinner" aria-hidden="true" />
              Refreshing roles…
            </p>
          ) : null}
        </div>

        <form
          className="jobs-toolbar"
          key={`${workspaceId}:${query}`}
          onSubmit={submitSearch}
        >
          <label>
            Search saved roles
            <input
              name="q"
              placeholder="e.g. Python, backend, platform"
              type="search"
              defaultValue={query}
            />
          </label>
          <div className="jobs-toolbar__actions">
            <button className="primary-button primary-button--compact" type="submit">
              Search
            </button>
            <button className="secondary-button" type="button" onClick={refresh}>
              Refresh
            </button>
          </div>
        </form>

        {isInitialLoading && !data ? (
          <section className="loading-state jobs-loading" role="status" aria-live="polite">
            <span className="loading-spinner" aria-hidden="true" />
            <p>Loading saved roles…</p>
          </section>
        ) : null}

        {!data && errorMessage ? (
          <ErrorNotice
            focusOnMount
            title="Saved roles could not be loaded"
            message={errorMessage}
            onRetry={refresh}
          />
        ) : null}

        {data && errorMessage ? (
          <ErrorNotice
            title="The latest refresh failed"
            message={`${errorMessage} The previous list is still shown below.`}
            onRetry={refresh}
          />
        ) : null}

        {data && data.items.length === 0 ? (
          <section className="jobs-empty" aria-live="polite">
            <h3>{query ? "No matching roles" : "No saved roles yet"}</h3>
            <p>
              {query
                ? "Try a different title keyword, or clear the search."
                : "Save a role from the application workbench to see it here."}
            </p>
          </section>
        ) : null}

        {data && data.items.length > 0 ? (
          <>
            <ol className="jobs-list">
              {data.items.map((job) => (
                <li key={job.id} className="job-list-item">
                  <article>
                    <h3>{job.title}</h3>
                    <p>
                      Saved <time dateTime={job.created_at}>{formatTimestamp(job.created_at)}</time>
                    </p>
                  </article>
                </li>
              ))}
            </ol>

            <nav className="jobs-pagination" aria-label="Saved roles pages">
              <button
                className="secondary-button"
                type="button"
                disabled={page === 1}
                onClick={() => moveToPage(page - 1)}
              >
                Previous page
              </button>
              <span aria-live="polite">Page {page}</span>
              <button
                className="secondary-button"
                type="button"
                disabled={!data.has_more}
                onClick={() => moveToPage(page + 1)}
              >
                Next page
              </button>
            </nav>
          </>
        ) : null}
      </section>
    </main>
  );
}
