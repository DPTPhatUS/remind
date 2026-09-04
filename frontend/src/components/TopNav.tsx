import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"

const links = [
  { to: "/", label: "Live" },
  { to: "/people", label: "People" },
  { to: "/profile", label: "Profile" },
] as const

export function TopNav() {
  return (
    <nav
      data-testid="top-nav"
      className="flex items-center gap-2 border-b border-border px-4 py-2 bg-background"
    >
      {links.map((link) => (
        <Button
          key={link.to}
          variant="ghost"
          size="sm"
          asChild
        >
          <Link to={link.to}>{link.label}</Link>
        </Button>
      ))}
    </nav>
  )
}