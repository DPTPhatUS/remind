import { Navigate, Route, Routes } from "react-router-dom"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { TopNav } from "@/components/TopNav"
import { LiveAssistantPage } from "@/pages/LiveAssistantPage"
import { PeoplePage } from "@/pages/PeoplePage"
import { PersonDetailPage } from "@/pages/PersonDetailPage"
import { ProfilePage } from "@/pages/ProfilePage"

export default function App() {
  return (
    <TooltipProvider>
      <TopNav />
      <Routes>
        <Route path="/" element={<LiveAssistantPage />} />
        <Route path="/people" element={<PeoplePage />} />
        <Route path="/people/:id" element={<PersonDetailPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Routes>
      <Toaster />
    </TooltipProvider>
  )
}