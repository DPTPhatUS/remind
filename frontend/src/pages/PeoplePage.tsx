import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { TopNav } from '@/components/TopNav';
import { createApiClient, ApiError } from '@/lib/api';
import type { Person, RecognitionStatus } from '@/lib/api-types';

function statusVariant(s: RecognitionStatus): 'default' | 'secondary' | 'outline' {
  if (s === 'confirmed') return 'default';
  if (s === 'recognized') return 'secondary';
  if (s === 'introduced') return 'outline';
  return 'outline';
}

const label = (s: RecognitionStatus) => s.charAt(0).toUpperCase() + s.slice(1);

export function PeoplePage() {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    createApiClient().get<Person[]>('/people')
      .then(d => { if (alive) setPeople(d); })
      .catch(e => { if (alive) setError(e instanceof ApiError ? `${e.status} ${e.message}` : (e instanceof Error ? e.message : 'Unknown error')); });
    return () => { alive = false; };
  }, []);

  function reload() {
    setPeople(null);
    setError(null);
    createApiClient().get<Person[]>('/people')
      .then(d => setPeople(d))
      .catch(e => setError(e instanceof ApiError ? `${e.status} ${e.message}` : (e instanceof Error ? e.message : 'Unknown error')));
  }

  return (
    <div>
      <TopNav />
      <main className="container mx-auto max-w-5xl p-6">
        <header className="mb-6 flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold">People you know</h1>
          <p className="text-sm text-muted-foreground">{people?.length ?? '...'} total</p>
        </header>

        {error && (
          <Alert variant="destructive" className="mb-4">
            <AlertTitle>Couldn't load people</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
            <Button variant="outline" size="sm" className="mt-2" onClick={reload}>Retry</Button>
          </Alert>
        )}

        {people === null && !error && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map(i => <Skeleton key={i} className="h-40" />)}
          </div>
        )}

        {people !== null && people.length === 0 && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
              <p className="text-lg font-medium">No people yet</p>
              <p className="max-w-md text-sm text-muted-foreground">
                When someone you meet is recognized by the camera or introduced in conversation, they'll appear here automatically.
              </p>
            </CardContent>
          </Card>
        )}

        {people !== null && people.length > 0 && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {people.map(p => (
              <Card key={p.id}>
                <CardHeader>
                  <CardTitle>{p.display_name || 'Unnamed'}</CardTitle>
                  <CardDescription>{p.relationship_to_patient ?? 'No relationship set'}</CardDescription>
                </CardHeader>
                <CardContent>
                  <Badge variant={statusVariant(p.recognition_status)} data-status={p.recognition_status}>
                    {label(p.recognition_status)}
                  </Badge>
                </CardContent>
                <CardFooter>
                  <Button variant="ghost" size="sm" asChild>
                    <Link to={`/people/${p.id}`}>View</Link>
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
