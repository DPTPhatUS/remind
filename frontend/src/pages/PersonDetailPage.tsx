import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { Fact, PersonMemory } from "@/lib/api-types";
import { ProfileFacts } from "@/features/people/ProfileFacts";

export function PersonDetailPage() {
  const { id } = useParams();
  return id ? <PersonDetail key={id} id={id} /> : null;
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
    if (!person) return false;
    if (value === undefined && !confirm("Remove this fact from the profile?"))
      return false;
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
      return true;
    } catch (e) {
      setError(String(e));
      return false;
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
          <ProfileFacts facts={person.facts} busy={busy} onChange={changeFact} />
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
