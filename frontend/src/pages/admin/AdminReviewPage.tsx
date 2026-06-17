import { useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Spinner } from "@/components/ui/spinner"
import { createApiClient } from "@/lib/api"
import type { ReviewItem } from "@/lib/api-types"

export function AdminReviewPage() {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    createApiClient()
      .get<ReviewItem[]>("/review-items")
      .then(setItems)
      .finally(() => setIsLoading(false))
  }, [])

  async function decide(item: ReviewItem, status: "approved" | "rejected") {
    await createApiClient().patch(`/review-items/${item.id}`, {
      status,
      payload:
        status === "approved"
          ? { confirmed_display_name: item.title.replace(/^Review new person: /, "") }
          : {},
    })
    setItems((current) => current.filter((candidate) => candidate.id !== item.id))
  }

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Review Inbox</h1>
        <p className="text-muted-foreground">
          Confirm captured people, corrections, and memory candidates before they become trusted.
        </p>
      </div>
      {isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-2 p-6">
            <Spinner />
            Loading review items
          </CardContent>
        </Card>
      ) : items.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>No pending review</EmptyTitle>
            <EmptyDescription>Silent captures will appear here.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid gap-4">
          {items.map((item) => (
            <Card key={item.id}>
              <CardHeader>
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <CardTitle>{item.title}</CardTitle>
                    <CardDescription>{item.summary ?? "No summary provided."}</CardDescription>
                  </div>
                  <Badge variant="outline">{item.item_type}</Badge>
                </div>
              </CardHeader>
              <CardContent className="flex gap-2">
                <Button onClick={() => decide(item, "approved")}>Approve</Button>
                <Button variant="outline" onClick={() => decide(item, "rejected")}>
                  Reject
                </Button>
                <Button variant="secondary" onClick={() => decide(item, "approved")}>
                  Edit and approve
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  )
}
