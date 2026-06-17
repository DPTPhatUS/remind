import { useEffect, useMemo, useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { createApiClient } from "@/lib/api"
import type { Person, Relationship } from "@/lib/api-types"

const patientValue = "patient"

export function AdminRelationshipsPage() {
  const [people, setPeople] = useState<Person[]>([])
  const [relationships, setRelationships] = useState<Relationship[]>([])
  const [fromPersonId, setFromPersonId] = useState("")
  const [toPersonId, setToPersonId] = useState(patientValue)

  useEffect(() => {
    const api = createApiClient()
    void Promise.all([
      api.get<Person[]>("/people"),
      api.get<Relationship[]>("/relationships"),
    ]).then(([peopleResult, relationshipResult]) => {
      setPeople(peopleResult)
      setRelationships(relationshipResult)
      setFromPersonId(peopleResult[0]?.id ?? "")
    })
  }, [])

  const peopleById = useMemo(
    () => new Map(people.map((person) => [person.id, person.display_name])),
    [people]
  )

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!fromPersonId) return

    const form = new FormData(event.currentTarget)
    const relationship = await createApiClient().post<Relationship>("/relationships", {
      from_person_id: fromPersonId,
      to_person_id: toPersonId === patientValue ? null : toPersonId,
      relationship_type: String(form.get("relationship_type")),
      confidence: Number(form.get("confidence") || 0.8),
    })

    setRelationships((current) => [relationship, ...current])
    event.currentTarget.reset()
  }

  return (
    <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
      <Card>
        <form onSubmit={submit}>
          <CardHeader>
            <CardTitle>Add relationship</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel>Person</FieldLabel>
                <Select value={fromPersonId} onValueChange={setFromPersonId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Choose a person" />
                  </SelectTrigger>
                  <SelectContent>
                    {people.map((person) => (
                      <SelectItem key={person.id} value={person.id}>
                        {person.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel>Related to</FieldLabel>
                <Select value={toPersonId} onValueChange={setToPersonId}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={patientValue}>Patient</SelectItem>
                    {people
                      .filter((person) => person.id !== fromPersonId)
                      .map((person) => (
                        <SelectItem key={person.id} value={person.id}>
                          {person.display_name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel htmlFor="relationship-type">Relationship type</FieldLabel>
                <Input
                  id="relationship-type"
                  name="relationship_type"
                  placeholder="neighbor, daughter, friend"
                  required
                />
                <FieldDescription>
                  Stored as caregiver-reviewed context for reminders.
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="relationship-confidence">Confidence</FieldLabel>
                <Input
                  id="relationship-confidence"
                  name="confidence"
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  defaultValue="0.8"
                />
              </Field>
              <Button type="submit" disabled={!fromPersonId}>
                Create relationship
              </Button>
            </FieldGroup>
          </CardContent>
        </form>
      </Card>
      <div className="grid content-start gap-3">
        {relationships.map((relationship) => (
          <Card key={relationship.id}>
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-base">
                    {peopleById.get(relationship.from_person_id) ?? "Unknown person"} is{" "}
                    {relationship.relationship_type}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Related to{" "}
                    {relationship.to_person_id
                      ? peopleById.get(relationship.to_person_id) ?? "Unknown person"
                      : "the patient"}
                  </p>
                </div>
                <Badge variant={relationship.confirmed_by_user_id ? "secondary" : "outline"}>
                  {Math.round(relationship.confidence * 100)}%
                </Badge>
              </div>
            </CardHeader>
          </Card>
        ))}
      </div>
    </section>
  )
}
