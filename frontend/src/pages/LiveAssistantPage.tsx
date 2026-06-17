import { useEffect, useRef } from "react"
import { MoreHorizontalIcon, ShieldIcon, UserRoundIcon, WifiIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useLiveSession } from "@/features/live/live-session"

export function LiveAssistantPage() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const { state, stream, connectionState, submitCorrection } = useLiveSession()
  const activeRecognition = state.recognitions[0]

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream
    }
  }, [stream])

  const title = state.reminder?.title ?? "Waiting for a meaningful interaction"
  const lines =
    state.reminder?.lines.length
      ? state.reminder.lines
      : ["The assistant will stay quiet until recognition or conversation context matters."]

  return (
    <main className="min-h-svh bg-background text-foreground">
      <section className="relative flex min-h-svh flex-col overflow-hidden bg-foreground text-background">
        <header className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
          <div>
            <h1 className="text-lg font-semibold tracking-normal">Live assistant</h1>
            <p className="text-sm text-background/70">Visual-first memory support</p>
          </div>
          <Button asChild variant="secondary" size="sm">
            <a href="/admin/review">
              <ShieldIcon data-icon="inline-start" />
              Caregiver
            </a>
          </Button>
        </header>

        <video
          ref={videoRef}
          data-live-video
          autoPlay
          muted
          playsInline
          className="absolute inset-0 size-full object-cover opacity-70"
        />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_0,transparent_45%,color-mix(in_oklch,var(--foreground),black_18%)_100%)]" />

        <div className="relative mt-24 flex flex-1 items-start justify-center px-6">
          <div className="rounded-full border border-background/30 px-4 py-2 text-sm text-background/80">
            {state.interaction.status === "active"
              ? "Interaction active"
              : state.interaction.status === "candidate"
                ? "Possible interaction"
                : "Monitoring quietly"}
          </div>
        </div>

        <div className="absolute right-4 bottom-40 flex flex-col gap-2">
          {state.recognitions.slice(1).map((recognition) => (
            <Badge key={recognition.subject} variant="secondary">
              <UserRoundIcon data-icon="inline-start" />
              {recognition.label}
            </Badge>
          ))}
        </div>

        <section className="absolute right-4 bottom-4 left-4 rounded-xl border border-background/15 bg-background p-4 text-foreground shadow-2xl md:right-auto md:left-1/2 md:w-[min(560px,calc(100%-2rem))] md:-translate-x-1/2">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <Badge variant={state.requiresReview ? "outline" : "secondary"}>
                  {state.requiresReview ? "Needs review" : "Patient-safe"}
                </Badge>
                <Badge variant="outline">
                  <WifiIcon data-icon="inline-start" />
                  {connectionState}
                </Badge>
              </div>
              <h2 className="text-2xl font-semibold tracking-normal">{title}</h2>
              {lines.map((line) => (
                <p key={line} className="text-base text-muted-foreground">
                  {line}
                </p>
              ))}
            </div>

            <DropdownMenu>
              <Tooltip>
                <TooltipTrigger asChild>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="icon" aria-label="Reminder actions">
                      <MoreHorizontalIcon />
                    </Button>
                  </DropdownMenuTrigger>
                </TooltipTrigger>
                <TooltipContent>Reminder actions</TooltipContent>
              </Tooltip>
              <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                  <DropdownMenuItem
                    onClick={() =>
                      submitCorrection("confirmed_correct", activeRecognition?.subject)
                    }
                  >
                    This is correct
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() =>
                      submitCorrection("wrong_person", activeRecognition?.subject)
                    }
                  >
                    Wrong person
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() =>
                      submitCorrection("unknown_person", activeRecognition?.subject)
                    }
                  >
                    I don&apos;t know them
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() =>
                      submitCorrection("ask_caregiver", activeRecognition?.subject)
                    }
                  >
                    Ask caregiver
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </section>
      </section>
    </main>
  )
}
