import { useEffect, useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldContent, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { createApiClient } from "@/lib/api"
import type { MemoryEvent } from "@/lib/api-types"

const importanceOptions = ["low", "medium", "high"]

export function AdminEventsPage() {
  const [events, setEvents] = useState<MemoryEvent[]>([])
  const [importance, setImportance] = useState("medium")
  const [patientVisible, setPatientVisible] = useState(true)

  useEffect(() => {
    void createApiClient().get<MemoryEvent[]>("/events").then(setEvents)
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const memoryEvent = await createApiClient().post<MemoryEvent>("/events", {
      title: String(form.get("title")),
      description: String(form.get("description") || ""),
      event_date: String(form.get("event_date") || "") || null,
      emotional_importance: importance,
      patient_visible: patientVisible,
    })

    setEvents((current) => [memoryEvent, ...current])
    event.currentTarget.reset()
  }

  return (
    <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
      <Card>
        <form onSubmit={submit}>
          <CardHeader>
            <CardTitle>Add event</CardTitle>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="event-title">Title</FieldLabel>
                <Input id="event-title" name="title" required />
              </Field>
              <Field>
                <FieldLabel htmlFor="event-date">Date</FieldLabel>
                <Input id="event-date" name="event_date" type="date" />
              </Field>
              <Field>
                <FieldLabel>Emotional importance</FieldLabel>
                <Select value={importance} onValueChange={setImportance}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {importanceOptions.map((option) => (
                      <SelectItem key={option} value={option}>
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field orientation="horizontal">
                <Switch
                  id="event-visible"
                  checked={patientVisible}
                  onCheckedChange={setPatientVisible}
                />
                <FieldContent>
                  <FieldLabel htmlFor="event-visible">Patient visible</FieldLabel>
                </FieldContent>
              </Field>
              <Field>
                <FieldLabel htmlFor="event-description">Description</FieldLabel>
                <Textarea id="event-description" name="description" />
              </Field>
              <Button type="submit">Create event</Button>
            </FieldGroup>
          </CardContent>
        </form>
      </Card>
      <div className="grid content-start gap-3">
        {events.map((eventItem) => (
          <Card key={eventItem.id}>
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-base">{eventItem.title}</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    {eventItem.description || "No description"}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {eventItem.event_date ?? "Date not set"}
                  </p>
                </div>
                <Badge variant={eventItem.patient_visible ? "secondary" : "outline"}>
                  {eventItem.patient_visible ? "Patient visible" : "Hidden"}
                </Badge>
              </div>
            </CardHeader>
          </Card>
        ))}
      </div>
    </section>
  )
}
