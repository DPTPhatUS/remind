import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Spinner } from "@/components/ui/spinner"
import { ApiError, AuthSessionStore, createApiClient } from "@/lib/api"
import type { AuthTokenResponse } from "@/lib/api-types"

export function SetupPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    const form = new FormData(event.currentTarget)
    const body = {
      email: String(form.get("email")),
      display_name: String(form.get("display_name")),
      password: String(form.get("password")),
      patient_display_name: String(form.get("patient_display_name")),
    }

    try {
      const session = await createApiClient().post<AuthTokenResponse>(
        "/auth/bootstrap-admin",
        body
      )
      new AuthSessionStore().save(session)
      navigate("/live")
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        navigate("/login")
        return
      }
      setError(caught instanceof Error ? caught.message : "Setup failed")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-6">
      <Card className="w-full max-w-xl">
        <form onSubmit={submit}>
          <CardHeader>
            <CardTitle>First launch setup</CardTitle>
            <CardDescription>
              Create the caregiver admin and local patient profile.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              {error && (
                <Alert variant="destructive">
                  <AlertTitle>Setup failed</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <Field>
                <FieldLabel htmlFor="setup-email">Caregiver email</FieldLabel>
                <Input id="setup-email" name="email" type="email" required />
              </Field>
              <Field>
                <FieldLabel htmlFor="setup-name">Caregiver name</FieldLabel>
                <Input id="setup-name" name="display_name" required />
              </Field>
              <Field>
                <FieldLabel htmlFor="setup-password">Password</FieldLabel>
                <Input id="setup-password" name="password" type="password" required />
              </Field>
              <Field>
                <FieldLabel htmlFor="setup-patient">Patient name</FieldLabel>
                <Input id="setup-patient" name="patient_display_name" required />
                <FieldDescription>
                  Camera and microphone permissions are requested on the live screen.
                </FieldDescription>
              </Field>
            </FieldGroup>
          </CardContent>
          <CardFooter>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting && <Spinner data-icon="inline-start" />}
              Create setup
            </Button>
          </CardFooter>
        </form>
      </Card>
    </main>
  )
}
