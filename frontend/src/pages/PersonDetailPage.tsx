import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { Fact, PersonMemory } from "@/lib/api-types";

const groups = [
  {
    title: "Background",
    categories: [
      "identity",
      "relationship",
      "age",
      "work",
      "education",
      "residence",
      "other",
    ],
  },
  {
    title: "Interests and routines",
    categories: ["interests", "preferences", "routines"],
  },
  { title: "Related people", categories: ["family"] },
  { title: "Experiences and plans", categories: ["experiences", "plans"] },
];
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
  onEdit: (value: string) => Promise<void>;
  onRemove: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(fact.value);
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await onEdit(value.trim());
      setEditing(false);
    } catch {
      /* The parent displays the error and keeps this form open. */
    }
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

export function PersonDetailPage() {
  const { id } = useParams();
  return <PersonDetail key={id} id={id!} />;
}

function PersonDetail({ id }: { id: string }) {
  const navigate = useNavigate();
  const [person, setPerson] = useState<PersonMemory | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [fields, setFields] = useState({
    name: "",
    relationship: "",
    age: "",
    notes: "",
  });
  function updatePerson(data: PersonMemory) {
    setPerson(data);
    setFields({
      name: data.name ?? "",
      relationship: data.relationship ?? "",
      age: data.age ?? "",
      notes: data.notes ?? "",
    });
  }
  useEffect(() => {
    let active = true;
    api<PersonMemory>(`/people/${id}`)
      .then((data) => {
        if (active) updatePerson(data);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [id]);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!person) return;
    const changed = Object.fromEntries(
      Object.entries(fields).filter(
        ([key, value]) => value !== (person[key as keyof typeof fields] ?? ""),
      ),
    );
    if (!Object.keys(changed).length) return;
    setBusy(true);
    setError("");
    try {
      await api(`/people/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ version: person.version, fields: changed }),
      });
      updatePerson(await api<PersonMemory>(`/people/${id}`));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function changeFact(fact: Fact, value?: string) {
    if (!person) return;
    if (value === undefined && !confirm("Remove this fact from the profile?"))
      return;
    setBusy(true);
    setError("");
    try {
      await api(`/people/${id}/facts/${fact.id}`, {
        method: value === undefined ? "DELETE" : "PATCH",
        body: JSON.stringify({
          version: person.version,
          ...(value === undefined ? {} : { value }),
        }),
      });
      updatePerson(await api<PersonMemory>(`/people/${id}`));
    } catch (e) {
      setError(String(e));
      throw e;
    } finally {
      setBusy(false);
    }
  }

  async function forget() {
    if (
      !confirm(
        "Forget this person? Their face, facts, conversation records, and pending processing will be removed.",
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api(`/people/${id}`, { method: "DELETE" });
      navigate("/people");
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  }
  const established =
    person?.facts.filter(
      (fact) =>
        fact.status === "accepted" && fact.temporal_status === "current",
    ) ?? [];
  const timeline =
    person?.facts.filter(
      (fact) =>
        fact.status === "accepted" && fact.temporal_status !== "current",
    ) ?? [];
  const unresolved =
    person?.facts.filter((fact) => fact.status === "conflict") ?? [];
  const history =
    person?.facts.filter(
      (fact) => fact.status === "superseded" || fact.status === "dismissed",
    ) ?? [];
  const renderFact = (fact: Fact) => (
    <FactCard
      key={`${fact.id}-${fact.updated_at}`}
      fact={fact}
      busy={busy}
      onEdit={(value) => changeFact(fact, value)}
      onRemove={() => changeFact(fact).catch(() => {})}
    />
  );
  return (
    <main className="content detail">
      <Link to="/people">← All people</Link>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {person ? (
        <>
          <h1>{person.name ?? "Someone you’ve met"}</h1>
          {person.profile_summary && (
            <p className="profile-summary">{person.profile_summary}</p>
          )}
          {person.highlights.length > 0 && (
            <ul className="profile-highlights">
              {person.highlights.slice(0, 3).map((highlight) => (
                <li key={highlight}>{highlight}</li>
              ))}
            </ul>
          )}
          {groups.map((group) => {
            const facts = established.filter((fact) =>
              group.title === "Related people"
                ? fact.subject !== "visitor" ||
                  group.categories.includes(fact.category)
                : fact.subject === "visitor" &&
                  group.categories.includes(fact.category),
            );
            return facts.length ? (
              <section className="profile-section" key={group.title}>
                <h2>{group.title}</h2>
                {facts.map(renderFact)}
              </section>
            ) : null;
          })}
          {!established.length && !timeline.length && (
            <p className="muted">
              Personal details will appear here as Remind learns from
              conversations.
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
              <summary>
                Previous and removed information ({history.length})
              </summary>
              {history.map(renderFact)}
            </details>
          )}
          <section className="profile-section">
            <h2>Previous encounters</h2>
            {person.encounters.length ? (
              person.encounters.map((encounter) => (
                <article className="encounter" key={encounter.id}>
                  <time>
                    {new Date(encounter.started_at).toLocaleString()}
                    {!encounter.ended_at ? " · In progress" : ""}
                  </time>
                  <p>
                    {encounter.summary ?? "No conversation summary recorded."}
                  </p>
                </article>
              ))
            ) : (
              <p>No completed encounters yet.</p>
            )}
          </section>
          <details className="profile-corrections">
            <summary>Correct profile details</summary>
            <form
              onSubmit={(event) => void save(event)}
              className="profile-form"
            >
              {(["name", "relationship", "age", "notes"] as const).map(
                (key) => (
                  <label key={key}>
                    {key === "age" ? "Age as stated" : key}
                    <input
                      maxLength={500}
                      value={fields[key]}
                      onChange={(event) =>
                        setFields({ ...fields, [key]: event.target.value })
                      }
                    />
                  </label>
                ),
              )}
              <button disabled={busy}>Save corrections</button>
              <p className="muted">
                Corrections take precedence over automatically learned facts.
              </p>
            </form>
          </details>
          <button
            className="danger"
            onClick={() => void forget()}
            disabled={busy}
          >
            Forget this person
          </button>
        </>
      ) : (
        <p>{error ? "The profile could not be loaded." : "Loading…"}</p>
      )}
    </main>
  );
}
