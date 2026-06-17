import { NavLink, Outlet } from "react-router-dom"
import {
  CalendarDaysIcon,
  HeartHandshakeIcon,
  InboxIcon,
  SearchIcon,
  SettingsIcon,
  UsersIcon,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
} from "@/components/ui/sidebar"
import { Button } from "@/components/ui/button"

const navItems = [
  { to: "/admin/review", label: "Review Inbox", icon: InboxIcon },
  { to: "/admin/people", label: "People", icon: UsersIcon },
  { to: "/admin/relationships", label: "Relationships", icon: HeartHandshakeIcon },
  { to: "/admin/events", label: "Events", icon: CalendarDaysIcon },
  { to: "/admin/search", label: "Memory Search", icon: SearchIcon },
  { to: "/admin/settings", label: "Settings", icon: SettingsIcon },
]

export function AdminLayout() {
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="p-4">
          <div className="flex flex-col">
            <span className="text-base font-semibold">Remind</span>
            <span className="text-sm text-muted-foreground">Caregiver console</span>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {navItems.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild>
                      <NavLink to={item.to}>
                        <item.icon data-icon="inline-start" />
                        {item.label}
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="p-4">
          <Button asChild variant="outline">
            <a href="/live">Return to live assistant</a>
          </Button>
        </SidebarFooter>
      </Sidebar>
      <main className="min-h-svh flex-1 bg-muted/30 p-6">
        <Outlet />
      </main>
    </SidebarProvider>
  )
}
