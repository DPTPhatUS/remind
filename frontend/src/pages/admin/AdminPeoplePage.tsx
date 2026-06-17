import { useEffect, useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldContent, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { createApiClient } from "@/lib/api"
import type { Person, RecognitionStatus } from "@/lib/api-types"

const statuses: RecognitionStatus[] = [
  "unknown",
  "seen_before",
  "introduced",
  "confirmed",
  "trusted",
  "opted_out",
]

export function AdminPeoplePage() {
  const [people, setPeople] = useState<Person[]>([])
  const [status, setStatus] = useState<RecognitionStatus>("introduced")
  const [sensitive, setSensitive] = useState(false)

  useEffect(() => {
    void createApiClient().get<Person[]>("/people").then(setPeople)
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const person = await createApiClient().post<Person>("/people", {
      display_name: String(form.get("display_name")),
      relationship_to_patient: String(form.get("relationship_to_patient")),
      notes: String(form.get("notes")),
      recognition_status: status,
      consent_status: String(form.get("consent_status") || "unknown"),
      sensitive,
    })
    setPeople((current) => [person, ...current])
    event.currentTarget.reset()
  }

  async function uploadFace(personId: string, file: File | null) {
    if (!file) return
    const body = new FormData()
    body.append("file", file)
    await createApiClient().post(`/people/${personId}/face-examples`, body)
  }

  return (
    <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
      <Card>
        <form onSubmit={submit}>
          <CardHeader>
            <CardTitle>Add person</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="person-name">Name</FieldLabel>
                <Input id="person-name" name="display_name" required />
              </Field>
              <Field>
                <FieldLabel htmlFor="person-relationship">Relationship</FieldLabel>
                <Input id="person-relationship" name="relationship_to_patient" />
              </Field>
              <Field>
                <FieldLabel htmlFor="person-consent">Consent status</FieldLabel>
                <Input id="person-consent" name="consent_status" placeholder="unknown" />
              </Field>
              <Field>
                <FieldLabel>Recognition status</FieldLabel>
                <Select value={status} onValueChange={(value) => setStatus(value as RecognitionStatus)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {statuses.map((item) => (
                        <SelectItem key={item} value={item}>
                          {item}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
              <Field orientation="horizontal">
                <Checkbox
                  id="person-sensitive"
                  checked={sensitive}
                  onCheckedChange={(checked) => setSensitive(checked === true)}
                />
                <FieldContent>
                  <FieldLabel htmlFor="person-sensitive">Sensitive profile</FieldLabel>
                </FieldContent>
              </Field>
              <Field>
                <FieldLabel htmlFor="person-notes">Notes</FieldLabel>
                <Textarea id="person-notes" name="notes" />
              </Field>
              <Button type="submit">Create person</Button>
            </FieldGroup>
          </CardContent>
        </form>
      </Card>
      <div className="grid gap-3">
        {people.map((person) => (
          <Card key={person.id}>
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle>{person.display_name}</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    {person.relationship_to_patient ?? "Relationship not set"}
                  </p>
                </div>
                <Badge variant="outline">{person.recognition_status}</Badge>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">{person.notes ?? "No notes"}</p>
              <Input
                type="file"
                accept="image/*"
                onChange={(event) =>
                  void uploadFace(person.id, event.currentTarget.files?.[0] ?? null)
                }
              />
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  )
}
