import { useState } from "react";

import type { RunArtifactRead } from "../api/contracts";

interface ArtifactViewProps {
  artifact: RunArtifactRead;
}

const PRIORITY_LABELS: Record<string, string> = {
  high: "High priority",
  medium: "Medium priority",
  low: "Low priority",
};

function itemNumber(index: number): string {
  return String(index + 1).padStart(2, "0");
}

export function ArtifactView({ artifact }: ArtifactViewProps) {
  const { content, citation_sources: sources, validation } = artifact;
  const [requestedChunkId, setRequestedChunkId] = useState<string | null>(
    sources[0]?.chunk_id ?? null,
  );
  const selectedSource =
    sources.find((source) => source.chunk_id === requestedChunkId) ??
    sources[0] ??
    null;
  const claimedRequirementIds = new Set(
    content.claims.flatMap((claim) => claim.requirement_ids),
  );
  const gapRequirementIds = new Set(
    content.gaps.map((gap) => gap.requirement_id),
  );
  const requirementById = new Map(
    content.requirements.map((requirement) => [requirement.id, requirement]),
  );
  const claimPositionById = new Map(
    content.claims.map((claim, index) => [claim.id, index]),
  );
  const supportedCount = content.requirements.filter((requirement) =>
    claimedRequirementIds.has(requirement.id),
  ).length;

  function evidenceButton(chunkId: string, occurrenceIndex: number) {
    const sourceIndex = sources.findIndex((source) => source.chunk_id === chunkId);
    if (sourceIndex < 0) {
      return (
        <span
          className="evidence-unavailable"
          key={`${chunkId}-${occurrenceIndex}`}
        >
          Evidence unavailable
        </span>
      );
    }
    const source = sources[sourceIndex];
    if (!source) {
      return null;
    }
    const label = `Evidence ${sourceIndex + 1}`;
    return (
      <button
        className="evidence-button"
        type="button"
        key={`${chunkId}-${occurrenceIndex}`}
        aria-controls="evidence-inspector"
        aria-label={`${label}: ${source.document_name}, excerpt ${source.position + 1}`}
        aria-pressed={selectedSource?.chunk_id === chunkId}
        onClick={() => setRequestedChunkId(chunkId)}
      >
        <span aria-hidden="true">⌁</span>
        {label}
      </button>
    );
  }

  return (
    <section className="artifact" aria-labelledby="artifact-heading">
      <div className="artifact__header">
        <div>
          <p className="eyebrow">Validated material package</p>
          <h2 id="artifact-heading">{content.resume_bullets.length ? "Evidence-backed material" : "Evidence gap report"}</h2>
          <p>
            {supportedCount} of {content.requirements.length} role requirements have
            linked source excerpts. Check their relevance and accuracy yourself.
          </p>
        </div>
        <span
          className={`validation-seal ${validation.passed ? "validation-seal--passed" : "validation-seal--failed"}`}
        >
          <span aria-hidden="true">{validation.passed ? "✓" : "!"}</span>
          {validation.passed ? "Evidence checked" : "Not validated"}
        </span>
      </div>

      <div className="artifact-layout">
        <article className="artifact-sheet">
          <section className="artifact-section" aria-labelledby="requirements-heading">
            <div className="section-heading">
              <div>
                <p className="section-index">01</p>
                <h3 id="requirements-heading">Role coverage</h3>
              </div>
              <span className="record-count">
                {content.requirements.length} requirements
              </span>
            </div>
            <ol className="requirement-list">
              {content.requirements.map((requirement, index) => {
                const status = claimedRequirementIds.has(requirement.id)
                  ? "supported"
                  : gapRequirementIds.has(requirement.id)
                    ? "gap"
                    : "unresolved";
                return (
                  <li className="requirement" key={requirement.id}>
                    <span className="requirement__number" aria-hidden="true">
                      {itemNumber(index)}
                    </span>
                    <div>
                      <p>{requirement.text}</p>
                      <span className="requirement__priority">
                        {PRIORITY_LABELS[requirement.priority] ?? "Role requirement"}
                      </span>
                    </div>
                    <span className={`coverage-label coverage-label--${status}`}>
                      {status === "supported"
                        ? "Verified"
                        : status === "gap"
                          ? "Evidence gap"
                          : "Needs review"}
                    </span>
                  </li>
                );
              })}
            </ol>
          </section>

          <section className="artifact-section" aria-labelledby="claims-heading">
            <div className="section-heading">
              <div>
                <p className="section-index">02</p>
                <h3 id="claims-heading">Verified claims</h3>
              </div>
              <span className="record-count">{content.claims.length} claims</span>
            </div>
            {content.claims.length === 0 ? (
              <p className="empty-state">
                No candidate claims were published for this run.
              </p>
            ) : (
              <ol className="claim-list">
                {content.claims.map((claim, index) => (
                  <li className="claim-card" key={claim.id}>
                    <div className="claim-card__heading">
                      <span>Fact {itemNumber(index)}</span>
                      <span>{claim.requirement_ids.length} linked requirement</span>
                    </div>
                    <p className="claim-card__text">{claim.text}</p>
                    <ul className="claim-requirements" aria-label="Supported requirements">
                      {claim.requirement_ids.map((requirementId) => (
                        <li key={requirementId}>
                          {requirementById.get(requirementId)?.text ??
                            "Linked role requirement"}
                        </li>
                      ))}
                    </ul>
                    <div className="evidence-actions" aria-label="Claim evidence">
                      {claim.citation_chunk_ids.map(evidenceButton)}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="artifact-section" aria-labelledby="bullets-heading">
            <div className="section-heading">
              <div>
                <p className="section-index">03</p>
                <h3 id="bullets-heading">Tailored résumé bullets</h3>
              </div>
              <span className="record-count">
                {content.resume_bullets.length} bullets
              </span>
            </div>
            {content.resume_bullets.length === 0 ? (
              <p className="empty-state">No résumé bullets were published.</p>
            ) : (
              <ul className="resume-bullets">
                {content.resume_bullets.map((bullet, index) => {
                  const groundedClaims = bullet.claim_ids
                    .map((claimId) => claimPositionById.get(claimId))
                    .filter((position): position is number => position !== undefined)
                    .map((position) => `Fact ${itemNumber(position)}`);
                  return (
                    <li key={`${bullet.text}-${index}`}>
                      <p>{bullet.text}</p>
                      {groundedClaims.length > 0 ? (
                        <span>Grounded in {groundedClaims.join(", ")}</span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="artifact-section" aria-labelledby="letter-heading">
            <div className="section-heading">
              <div>
                <p className="section-index">04</p>
                <h3 id="letter-heading">Cover letter</h3>
              </div>
            </div>
            {content.cover_letter ? (
              <div className="cover-letter">{content.cover_letter}</div>
            ) : (
              <p className="empty-state">No cover letter was generated for this run.</p>
            )}
          </section>

          <section className="artifact-section" aria-labelledby="gaps-heading">
            <div className="section-heading">
              <div>
                <p className="section-index">05</p>
                <h3 id="gaps-heading">Evidence gaps</h3>
              </div>
              <span className="record-count">{content.gaps.length} gaps</span>
            </div>
            {content.gaps.length === 0 ? (
              <p className="empty-state empty-state--success">
                No evidence gaps were identified.
              </p>
            ) : (
              <ul className="gap-list">
                {content.gaps.map((gap) => (
                  <li className="gap-card" key={gap.requirement_id}>
                    <span className="gap-card__mark" aria-hidden="true">
                      !
                    </span>
                    <div>
                      <strong>Missing verified evidence</strong>
                      <p>
                        {requirementById.get(gap.requirement_id)?.text ??
                          "This role requirement is not supported by the supplied documents."}
                      </p>
                      <span>
                        Add a project, result, credential, or work sample that directly
                        supports this requirement.
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </article>

        <aside className="artifact-rail">
          <section
            className="evidence-inspector"
            id="evidence-inspector"
            aria-labelledby="evidence-inspector-heading"
            aria-live="polite"
          >
            <p className="eyebrow">Source inspector</p>
            <h3 id="evidence-inspector-heading">
              {selectedSource
                ? `Evidence ${sources.findIndex((source) => source.chunk_id === selectedSource.chunk_id) + 1}`
                : "Evidence"}
            </h3>
            {selectedSource ? (
              <>
                <div className="source-meta">
                  <strong>{selectedSource.document_name}</strong>
                  <span>Excerpt {selectedSource.position + 1}</span>
                </div>
                <blockquote>{selectedSource.excerpt}</blockquote>
                <p className="source-assurance">
                  This excerpt comes from a document in the current workspace.
                </p>
              </>
            ) : (
              <p className="empty-state">
                No source excerpts were published for this result.
              </p>
            )}
          </section>

          {sources.length > 1 ? (
            <nav className="source-index" aria-label="Published evidence sources">
              <span>Source index</span>
              <ul>
                {sources.map((source, index) => (
                  <li key={source.chunk_id}>
                    <button
                      type="button"
                      aria-controls="evidence-inspector"
                      aria-pressed={selectedSource?.chunk_id === source.chunk_id}
                      onClick={() => setRequestedChunkId(source.chunk_id)}
                    >
                      <span>Evidence {index + 1}</span>
                      <small>{source.document_name}</small>
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          ) : null}
        </aside>
      </div>
    </section>
  );
}
