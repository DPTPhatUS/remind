import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { TopNav } from '@/components/TopNav';
import { createApiClient, ApiError } from '@/lib/api';
import type { Person, RecognitionStatus, Relationship } from '@/lib/api-types';

const STATUSES: RecognitionStatus[] = ['unknown', 'recognized', 'introduced', 'confirmed'];
const label = (s: RecognitionStatus) => s.charAt(0).toUpperCase() + s.slice(1);

export function PersonDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [person, setPerson] = useState<Person | null | undefined>(undefined);
  const [interactions, setInteractions] = useState<Array<{ id: string; started_at: string; ended_at: string | null; status: string }>>([]);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Person | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    setPerson(undefined);
    if (!id) { setPerson(null); return; }
    Promise.all([
      createApiClient().get<Person[]>('/people'),
      createApiClient().get<unknown[]>('/interactions'),
      createApiClient().get<Relationship[]>('/relationships'),
    ]).then(([people, ints, rels]) => {
      if (!alive) return;
      const found = people.find(p => p.id === id) ?? null;
      setPerson(found);
      setDraft(found);
      setInteractions(((ints ?? []) as Array<{ id: string; started_at: string; ended_at: string | null; status: string; participants?: Array<{ person_id: string }> }>).filter(i => i.participants?.some(pp => pp.person_id === id)).slice(0, 10));
      setRelationships((rels ?? []).filter(r => r.from_person_id === id || r.to_person_id === id));
    }).catch(() => { if (alive) setPerson(null); });
    return () => { alive = false; };
  }, [id]);

  async function save() {
    if (!draft || !id) return;
    setSaving(true);
    try {
      const updated = await createApiClient().patch<Person>(`/people/${id}`, {
        display_name: draft.display_name,
        relationship_to_patient: draft.relationship_to_patient,
        notes: draft.notes,
        consent_status: draft.consent_status,
        recognition_status: draft.recognition_status,
      });
      setPerson(updated); setDraft(updated); setEditing(false);
      toast.success('Saved');
    } catch (e) {
      toast.error(e instanceof ApiError ? `${e.status}: ${e.message}` : (e instanceof Error ? e.message : 'Save failed'));
    } finally { setSaving(false); }
  }

  return (
    <div>
      <TopNav />
      <main className="container mx-auto max-w-3xl p-6">
        {person === undefined && <p className="text-muted-foreground">Loading…</p>}
        {person === null && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <p className="text-lg font-medium">Person not found</p>
              <p className="text-sm text-muted-foreground">They may have been removed from your memory.</p>
              <Button asChild variant="outline"><Link to="/people">Back to people</Link></Button>
            </CardContent>
          </Card>
        )}
        {person && draft && (
          <>
            <header className="mb-6 flex items-baseline justify-between">
              <h1 className="text-2xl font-semibold">{person.display_name || 'Unnamed'}</h1>
              <Button variant="outline" onClick={() => setEditing(e => !e)}>{editing ? 'Cancel' : 'Edit'}</Button>
            </header>
            <Card className="mb-6">
              <CardHeader><CardTitle>Profile</CardTitle></CardHeader>
              <CardContent className="grid gap-3">
                <div><Label htmlFor="display_name">Name</Label>
                  <Input id="display_name" value={draft.display_name ?? ''} onChange={e => setDraft(d => d ? { ...d, display_name: e.target.value } : d)} /></div>
                <div><Label htmlFor="relationship">Relationship</Label>
                  <Input id="relationship" value={draft.relationship_to_patient ?? ''} onChange={e => setDraft(d => d ? { ...d, relationship_to_patient: e.target.value } : d)} /></div>
                <div><Label htmlFor="notes">Notes</Label>
                  <Textarea id="notes" value={draft.notes ?? ''} onChange={e => setDraft(d => d ? { ...d, notes: e.target.value } : d)} /></div>
                <div><Label htmlFor="consent">Consent</Label>
                  <Input id="consent" value={draft.consent_status ?? ''} onChange={e => setDraft(d => d ? { ...d, consent_status: e.target.value } : d)} /></div>
                <div>
                  <Label htmlFor="status">Recognition status</Label>
                  {editing ? (
                    <Select value={draft.recognition_status ?? 'unknown'} onValueChange={v => setDraft(d => d ? { ...d, recognition_status: v as RecognitionStatus } : d)}>
                      <SelectTrigger id="status"><SelectValue /></SelectTrigger>
                      <SelectContent>{STATUSES.map(s => <SelectItem key={s} value={s}>{label(s)}</SelectItem>)}</SelectContent>
                    </Select>
                  ) : <p data-testid="recognition-status">{label(person.recognition_status)}</p>}
                </div>
                <div className="flex gap-2">
                  <Button onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
                  <Button variant="ghost" onClick={() => { setEditing(false); setDraft(person); }} disabled={saving}>Cancel</Button>
                </div>
              </CardContent>
            </Card>
            <Card className="mb-6">
              <CardHeader><CardTitle>Recent interactions</CardTitle></CardHeader>
              <CardContent>
                {interactions.length === 0 ? <p className="text-sm text-muted-foreground">No recorded interactions yet.</p> : (
                  <ul className="space-y-2 text-sm">{interactions.map(i => <li key={i.id}><span className="font-mono text-xs text-muted-foreground">{i.started_at}</span> – status: {i.status}</li>)}</ul>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Relationships</CardTitle></CardHeader>
              <CardContent>
                {relationships.length === 0 ? <p className="text-sm text-muted-foreground">No relationships recorded.</p> : (
                  <ul className="space-y-1 text-sm">{relationships.map(r => <li key={r.id}>{r.relationship_type}</li>)}</ul>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
