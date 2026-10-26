import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { Person } from "@/lib/api-types";

export function PeoplePage() {
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    api<Person[]>("/people")
      .then((data) => {
        if (active) setPeople(data);
      })
      .catch((e) => {
        if (active) setError(String(e));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <main className="content">
      <div className="page-heading">
        <h1>People you’ve met</h1>
        <p>A little context for every familiar face.</p>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading ? (
        <p>Loading people…</p>
      ) : error ? null : people.length ? (
        <div className="people-grid">
          {people.map((person) => (
            <Link
              className="person-card"
              to={`/people/${person.id}`}
              key={person.id}
            >
              <img
                src={`/api/people/${person.id}/thumbnail`}
                alt=""
                onError={(event) => {
                  event.currentTarget.style.visibility = "hidden";
                }}
              />
              <div>
                <h2>{person.name ?? "Name not learned yet"}</h2>
                <p>{person.relationship ?? "Someone you’ve met"}</p>
                {person.profile_summary && (
                  <p className="person-summary">{person.profile_summary}</p>
                )}
                <small>
                  First met {new Date(person.created_at).toLocaleDateString()}
                </small>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <h2>Your memories start with a hello.</h2>
          <p>
            People will appear here after a sustained encounter in the live
            view.
          </p>
          <Link to="/">Open live view →</Link>
        </div>
      )}
    </main>
  );
}
