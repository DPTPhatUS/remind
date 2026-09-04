import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { TopNav } from "@/components/TopNav"

function renderTopNav() {
  return render(
    <MemoryRouter>
      <TopNav />
    </MemoryRouter>
  )
}

describe("TopNav", () => {
  it("renders three links: Live, People, Profile", () => {
    renderTopNav()

    const links = screen.getAllByRole("link")
    expect(links).toHaveLength(3)
    expect(links.map((link) => link.textContent)).toEqual([
      "Live",
      "People",
      "Profile",
    ])
  })

  it("Live links to /", () => {
    renderTopNav()
    expect(screen.getByRole("link", { name: "Live" })).toHaveAttribute(
      "href",
      "/"
    )
  })

  it("People links to /people", () => {
    renderTopNav()
    expect(screen.getByRole("link", { name: "People" })).toHaveAttribute(
      "href",
      "/people"
    )
  })

  it("Profile links to /profile", () => {
    renderTopNav()
    expect(screen.getByRole("link", { name: "Profile" })).toHaveAttribute(
      "href",
      "/profile"
    )
  })

  it("uses Button variant ghost", () => {
    renderTopNav()

    const nav = screen.getByTestId("top-nav")
    const links = screen.getAllByRole("link")

    expect(links).not.toHaveLength(0)
    for (const link of links) {
      expect(link).toHaveAttribute("data-slot", "button")
      expect(link).toHaveAttribute("data-variant", "ghost")
    }
    expect(nav).toBeInTheDocument()
  })
})