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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AuthSessionStore, createApiClient } from "@/lib/api"
import type { AuthTokenResponse } from "@/lib/api-types"

export function LoginPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const form = new FormData(event.currentTarget)

    try {
      const session = await createApiClient().post<AuthTokenResponse>("/auth/login", {
        email: String(form.get("email")),
        password: String(form.get("password")),
      })
      new AuthSessionStore().save(session)
      navigate("/admin/review")
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed")
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-6">
      <Card className="w-full max-w-md">
        <form onSubmit={submit}>
          <CardHeader>
            <CardTitle>Caregiver login</CardTitle>
            <CardDescription>Access review, people, events, and settings.</CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              {error && (
                <Alert variant="destructive">
                  <AlertTitle>Login failed</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <Field>
                <FieldLabel htmlFor="login-email">Caregiver email</FieldLabel>
                <Input id="login-email" name="email" type="email" required />
              </Field>
              <Field>
                <FieldLabel htmlFor="login-password">Password</FieldLabel>
                <Input id="login-password" name="password" type="password" required />
              </Field>
            </FieldGroup>
          </CardContent>
          <CardFooter>
            <Button type="submit">Log in</Button>
          </CardFooter>
        </form>
      </Card>
    </main>
  )
}
