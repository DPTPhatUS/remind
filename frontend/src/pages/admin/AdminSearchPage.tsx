import { useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { createApiClient } from "@/lib/api"
import type { MemoryClaim } from "@/lib/api-types"

export function AdminSearchPage() {
  const [results, setResults] = useState<MemoryClaim[]>([])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = String(new FormData(event.currentTarget).get("query"))
    const claims = await createApiClient().post<MemoryClaim[]>("/memories/search", {
      query,
      limit: 10,
    })
    setResults(claims)
  }

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Memory Search</h1>
        <p className="text-muted-foreground">
          Search visible memory claims. Treat unconfirmed results as evidence.
        </p>
      </div>
      <Card>
        <form onSubmit={submit}>
          <CardHeader>
            <CardTitle>Search claims</CardTitle>
            <CardDescription>Embedding search is used when configured on the backend.</CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="memory-query">Search memories</FieldLabel>
                <div className="flex gap-2">
                  <Input id="memory-query" name="query" />
                  <Button type="submit">Search</Button>
                </div>
              </Field>
            </FieldGroup>
          </CardContent>
        </form>
      </Card>
      <div className="grid gap-3">
        {results.map((claim) => (
          <Card key={claim.id}>
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">{claim.claim_text}</CardTitle>
                <Badge variant={claim.confirmed_by_user_id ? "secondary" : "outline"}>
                  {claim.confirmed_by_user_id ? "Confirmed memory" : "Unconfirmed claim"}
                </Badge>
              </div>
              <CardDescription>
                Source: {claim.source_type} · Confidence {Math.round(claim.confidence * 100)}%
              </CardDescription>
            </CardHeader>
          </Card>
        ))}
      </div>
    </section>
  )
}
