import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { PersonMemory } from "@/lib/api-types";

export function PersonDetailPage() {
  const { id } = useParams(),
    navigate = useNavigate();
  const [person, setPerson] = useState<PersonMemory | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [fields, setFields] = useState({
    name: "",
    relationship: "",
    age: "",
    notes: "",
  });
  useEffect(() => {
    let active = true;
    api<PersonMemory>(`/people/${id}`)
      .then((data) => {
        if (active) {
          setPerson(data);
          setFields({
            name: data.name ?? "",
            relationship: data.relationship ?? "",
            age: data.age ?? "",
            notes: data.notes ?? "",
          });
        }
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
    if (
      !Object.entries(fields).some(
        ([key, value]) => value !== (person[key as keyof typeof fields] ?? ""),
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api(`/people/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          version: person.version,
          fields: Object.fromEntries(
            Object.entries(fields).filter(
              ([key, value]) =>
                value !== (person[key as keyof typeof fields] ?? ""),
            ),
          ),
        }),
      });
      setPerson(await api<PersonMemory>(`/people/${id}`));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function forget() {
    if (
      !confirm(
        "Forget this person? Their face templates, facts, and related conversation records will be removed.",
      )
    )
      return;
    setBusy(true);
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
          <form onSubmit={save} className="profile-form">
            {(["name", "relationship", "age", "notes"] as const).map((key) => (
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
            ))}
            <button disabled={busy}>Save corrections</button>
            <p className="muted">
              Your corrections take precedence over automatically learned facts.
            </p>
          </form>
          <h2>Previous encounters</h2>
          {person.encounters.length ? (
            person.encounters.map((encounter) => (
              <article className="encounter" key={encounter.id}>
                <time>{new Date(encounter.started_at).toLocaleString()}</time>
                <p>
                  {encounter.summary ?? "No conversation summary recorded."}
                </p>
              </article>
            ))
          ) : (
            <p>No completed encounters yet.</p>
          )}
          <h2>What was learned</h2>
          {person.facts.map((fact) => (
            <details className="fact" key={fact.id}>
              <summary>
                {fact.predicate}: {fact.value}{" "}
                {fact.status === "conflict" ? "(conflicting statement)" : ""}
              </summary>
              <p>{JSON.parse(fact.evidence).quote}</p>
              <small>{new Date(fact.created_at).toLocaleString()}</small>
            </details>
          ))}
          <button
            className="danger"
            onClick={() => void forget()}
            disabled={busy}
          >
            Forget this person
          </button>
        </>
      ) : (
        <p>Loading…</p>
      )}
    </main>
  );
}
