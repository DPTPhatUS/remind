import { useEffect, useState, type FormEvent } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldContent, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { createApiClient } from "@/lib/api"
import type { Patient } from "@/lib/api-types"

type MediaCleanupResponse = {
  deleted_count?: number
}

export function AdminSettingsPage() {
  const [patient, setPatient] = useState<Patient | null>(null)
  const [largeText, setLargeText] = useState(false)
  const [highContrast, setHighContrast] = useState(false)
  const [audioPrompts, setAudioPrompts] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    void createApiClient()
      .get<Patient>("/patients/me")
      .then((result) => {
        setPatient(result)
        setLargeText(Boolean(result.accessibility_settings.large_text))
        setHighContrast(Boolean(result.accessibility_settings.high_contrast))
        setAudioPrompts(Boolean(result.preferences.audio_prompts))
      })
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const updated = await createApiClient().patch<Patient>("/patients/me", {
      display_name: String(form.get("display_name")),
      date_of_birth: String(form.get("date_of_birth") || "") || null,
      preferences: {
        ...(patient?.preferences ?? {}),
        audio_prompts: audioPrompts,
      },
      accessibility_settings: {
        ...(patient?.accessibility_settings ?? {}),
        large_text: largeText,
        high_contrast: highContrast,
      },
    })

    setPatient(updated)
    setNotice("Patient settings saved.")
  }

  async function cleanupMedia() {
    const result = await createApiClient().post<MediaCleanupResponse>(
      "/media/cleanup-expired"
    )
    setNotice(`Expired media cleanup complete. Removed ${result.deleted_count ?? 0} files.`)
  }

  return (
    <section className="flex max-w-3xl flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Settings</h1>
        <p className="text-muted-foreground">
          Configure the patient profile and low-noise live assistant defaults.
        </p>
      </div>

      {notice && (
        <Alert>
          <AlertTitle>Settings updated</AlertTitle>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}

      <Card>
        <form key={patient?.id ?? "loading"} onSubmit={submit}>
          <CardHeader>
            <CardTitle>Patient profile</CardTitle>
            <CardDescription>
              These values shape reminders and accessibility behavior.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="patient-display-name">Display name</FieldLabel>
                <Input
                  id="patient-display-name"
                  name="display_name"
                  defaultValue={patient?.display_name ?? ""}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="patient-date-of-birth">Date of birth</FieldLabel>
                <Input
                  id="patient-date-of-birth"
                  name="date_of_birth"
                  type="date"
                  defaultValue={patient?.date_of_birth ?? ""}
                />
              </Field>
              <Separator />
              <Field orientation="horizontal">
                <Switch
                  id="audio-prompts"
                  checked={audioPrompts}
                  onCheckedChange={setAudioPrompts}
                />
                <FieldContent>
                  <FieldLabel htmlFor="audio-prompts">Audio prompts</FieldLabel>
                </FieldContent>
              </Field>
              <Field orientation="horizontal">
                <Switch
                  id="large-text"
                  checked={largeText}
                  onCheckedChange={setLargeText}
                />
                <FieldContent>
                  <FieldLabel htmlFor="large-text">Large text</FieldLabel>
                </FieldContent>
              </Field>
              <Field orientation="horizontal">
                <Switch
                  id="high-contrast"
                  checked={highContrast}
                  onCheckedChange={setHighContrast}
                />
                <FieldContent>
                  <FieldLabel htmlFor="high-contrast">High contrast</FieldLabel>
                </FieldContent>
              </Field>
            </FieldGroup>
          </CardContent>
          <CardFooter>
            <Button type="submit">Save settings</Button>
          </CardFooter>
        </form>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Maintenance</CardTitle>
          <CardDescription>
            Remove expired media according to the backend retention policy.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Button variant="outline" onClick={cleanupMedia}>
            Clean up expired media
          </Button>
        </CardFooter>
      </Card>
    </section>
  )
}
