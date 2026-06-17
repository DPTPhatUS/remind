import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { AuthSessionStore } from "@/lib/api"
import { LiveAssistantPage } from "@/pages/LiveAssistantPage"
import { LoginPage } from "@/pages/LoginPage"
import { SetupPage } from "@/pages/SetupPage"
import { AdminEventsPage } from "@/pages/admin/AdminEventsPage"
import { AdminLayout } from "@/pages/admin/AdminLayout"
import { AdminPeoplePage } from "@/pages/admin/AdminPeoplePage"
import { AdminRelationshipsPage } from "@/pages/admin/AdminRelationshipsPage"
import { AdminReviewPage } from "@/pages/admin/AdminReviewPage"
import { AdminSearchPage } from "@/pages/admin/AdminSearchPage"
import { AdminSettingsPage } from "@/pages/admin/AdminSettingsPage"

function RequireCaregiver() {
  const location = useLocation()
  const session = new AuthSessionStore().current()

  if (!session) {
    return <Navigate replace to="/login" state={{ from: location.pathname }} />
  }

  return <Outlet />
}

export default function App() {
  return (
    <TooltipProvider>
      <Routes>
        <Route path="/" element={<Navigate replace to="/live" />} />
        <Route path="/live" element={<LiveAssistantPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireCaregiver />}>
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate replace to="/admin/review" />} />
            <Route path="review" element={<AdminReviewPage />} />
            <Route path="people" element={<AdminPeoplePage />} />
            <Route path="relationships" element={<AdminRelationshipsPage />} />
            <Route path="events" element={<AdminEventsPage />} />
            <Route path="search" element={<AdminSearchPage />} />
            <Route path="settings" element={<AdminSettingsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate replace to="/live" />} />
      </Routes>
      <Toaster />
    </TooltipProvider>
  )
}
