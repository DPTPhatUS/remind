import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { toast } from 'sonner';
import { TopNav } from '@/components/TopNav';
import { createApiClient, ApiError } from '@/lib/api';
import type { Patient } from '@/lib/api-types';

export function ProfilePage() {
  const [patient, setPatient] = useState<Patient | null>(null);
  const [draft, setDraft] = useState<Patient | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    createApiClient().get<Patient>('/patients/me')
      .then(p => { if (alive) { setPatient(p); setDraft(p); } })
      .catch(() => { if (alive) setPatient(null); });
    return () => { alive = false; };
  }, []);

  async function save() {
    if (!draft) return;
    if (!draft.display_name.trim()) {
      setNameError('Please enter a name.');
      return;
    }
    setNameError(null);
    setSaving(true);
    try {
      const updated = await createApiClient().patch<Patient>('/patients/me', {
        display_name: draft.display_name,
        date_of_birth: draft.date_of_birth,
        preferences: draft.preferences,
        accessibility_settings: draft.accessibility_settings,
      });
      setPatient(updated); setDraft(updated);
      toast.success('Saved');
    } catch (e) {
      toast.error(e instanceof ApiError ? `${e.status}: ${e.message}` : (e instanceof Error ? e.message : 'Save failed'));
    } finally { setSaving(false); }
  }

  function update<K extends keyof Patient>(key: K, value: Patient[K]) {
    setDraft(d => d ? { ...d, [key]: value } : d);
  }

  return (
    <div>
      <TopNav />
      <main className="container mx-auto max-w-2xl p-6">
        <h1 className="mb-6 text-2xl font-semibold">Your profile</h1>
        {!patient && <p className="text-muted-foreground">Loading…</p>}
        {patient && draft && (
          <Card>
            <CardHeader>
              <CardTitle>About you</CardTitle>
              <CardDescription>This is what the camera uses to greet you and how reminders address you.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div>
                <Label htmlFor="display_name">Your name</Label>
                <Input id="display_name" value={draft.display_name} onChange={e => update('display_name', e.target.value)} aria-invalid={!!nameError} />
                {nameError && <p className="mt-1 text-sm text-destructive" role="alert">{nameError}</p>}
              </div>
              <div>
                <Label htmlFor="date_of_birth">Date of birth</Label>
                <Input id="date_of_birth" type="date" value={draft.date_of_birth ?? ''} onChange={e => update('date_of_birth', e.target.value)} />
              </div>
              <div>
                <Label htmlFor="prefs">Preferences (JSON)</Label>
                <Textarea id="prefs" rows={3} value={JSON.stringify(draft.preferences ?? {}, null, 2)} onChange={e => {
                  try { update('preferences', JSON.parse(e.target.value)); } catch { /* keep prior */ }
                }} />
              </div>
              <div>
                <Label htmlFor="a11y">Accessibility (JSON)</Label>
                <Textarea id="a11y" rows={3} value={JSON.stringify(draft.accessibility_settings ?? {}, null, 2)} onChange={e => {
                  try { update('accessibility_settings', JSON.parse(e.target.value)); } catch { /* keep prior */ }
                }} />
              </div>
              <Button onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
