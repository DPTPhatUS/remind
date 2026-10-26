import { useState } from "react";
import type { Fact } from "@/lib/api-types";

const groups = [
  { id: "background", title: "Background" },
  { id: "interests", title: "Interests and routines" },
  { id: "related", title: "Related people" },
  { id: "events", title: "Experiences and plans" },
];

function groupForFact(fact: Fact) {
  if (fact.subject !== "visitor" || fact.category === "family") return "related";
  switch (fact.category) {
    case "interests":
    case "preferences":
    case "routines":
      return "interests";
    case "experiences":
    case "plans":
      return "events";
    default:
      return "background";
  }
}

const factLabel = (fact: Fact) => fact.predicate.replaceAll("_", " ");
const subjectLabel = (subject: string) =>
  subject.replaceAll("_", " ").replace(/^related[:/]/, "");
const dateLabel = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
};

function FactCard({
  fact,
  busy,
  onEdit,
  onRemove,
}: {
  fact: Fact;
  busy: boolean;
  onEdit: (value: string) => Promise<boolean>;
  onRemove: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(fact.value);
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (await onEdit(value.trim())) setEditing(false);
  }
  return (
    <details className="fact">
      <summary>
        <span className="fact-label">
          {fact.subject !== "visitor" && `${subjectLabel(fact.subject)} · `}
          {factLabel(fact)}
        </span>
        <span className="fact-value">{fact.value}</span>
        {fact.temporal_status !== "current" && (
          <span className="fact-badge">
            {fact.temporal_status === "planned" ? "Planned" : "Past"}
          </span>
        )}
        {fact.manual && <span className="fact-badge">Corrected</span>}
      </summary>
      {(fact.valid_from || fact.valid_to) && (
        <p className="muted">
          {fact.valid_from && `From ${dateLabel(fact.valid_from)}`}
          {fact.valid_from && fact.valid_to && " · "}
          {fact.valid_to && `Until ${dateLabel(fact.valid_to)}`}
        </p>
      )}
      <div className="fact-evidence">
        <strong>Supporting conversation</strong>
        {fact.evidence.length ? (
          fact.evidence.map((evidence, index) => (
            <blockquote key={`${evidence.segment_id}-${index}`}>
              “{evidence.quote}”
            </blockquote>
          ))
        ) : (
          <p>No conversation quote; this information was added manually.</p>
        )}
        <small>Learned {dateLabel(fact.created_at)}</small>
      </div>
      {editing ? (
        <form className="fact-edit" onSubmit={(event) => void save(event)}>
          <label>
            Correct {factLabel(fact)}
            <input
              value={value}
              onChange={(event) => setValue(event.target.value)}
              maxLength={500}
              required
            />
          </label>
          <div className="button-row">
            <button disabled={busy || !value.trim()}>
              Save fact correction
            </button>
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="button-row fact-actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() => {
              setValue(fact.value);
              setEditing(true);
            }}
          >
            Correct fact
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void onRemove()}
          >
            Remove fact
          </button>
        </div>
      )}
    </details>
  );
}

export function ProfileFacts({
  facts,
  busy,
  onChange,
}: {
  facts: Fact[];
  busy: boolean;
  onChange: (fact: Fact, value?: string) => Promise<boolean>;
}) {
  const established = facts.filter(
    (fact) => fact.status === "accepted" && fact.temporal_status === "current",
  );
  const timeline = facts.filter(
    (fact) => fact.status === "accepted" && fact.temporal_status !== "current",
  );
  const unresolved = facts.filter((fact) => fact.status === "conflict");
  const history = facts.filter(
    (fact) => fact.status === "superseded" || fact.status === "dismissed",
  );
  const renderFact = (fact: Fact) => (
    <FactCard
      key={fact.id}
      fact={fact}
      busy={busy}
      onEdit={(value) => onChange(fact, value)}
      onRemove={async () => {
        await onChange(fact);
      }}
    />
  );

  return (
    <>
      {groups.map((group) => {
        const groupFacts = established.filter(
          (fact) => groupForFact(fact) === group.id,
        );
        return groupFacts.length ? (
          <section className="profile-section" key={group.id}>
            <h2>{group.title}</h2>
            {groupFacts.map(renderFact)}
          </section>
        ) : null;
      })}
      {!established.length && !timeline.length && (
        <p className="muted">
          Personal details will appear here as Remind learns from conversations.
        </p>
      )}
      {timeline.length > 0 && (
        <section className="profile-section">
          <h2>Past information and plans</h2>
          {timeline.map(renderFact)}
        </section>
      )}
      {unresolved.length > 0 && (
        <details className="memory-history">
          <summary>Unresolved information ({unresolved.length})</summary>
          <p className="muted">
            These statements need clearer evidence and are not shown as
            established reminders.
          </p>
          {unresolved.map(renderFact)}
        </details>
      )}
      {history.length > 0 && (
        <details className="memory-history">
          <summary>Previous and removed information ({history.length})</summary>
          {history.map(renderFact)}
        </details>
      )}
    </>
  );
}
