import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { LiveAssistantPage } from "@/pages/LiveAssistantPage";
import { PeoplePage } from "@/pages/PeoplePage";
import { PersonDetailPage } from "@/pages/PersonDetailPage";

export default function App() {
  return (
    <>
      <header className="navigation">
        <NavLink className="brand" to="/">
          remind<span>●</span>
        </NavLink>
        <nav aria-label="Main navigation">
          <NavLink to="/" end>
            Live view
          </NavLink>
          <NavLink to="/people">People</NavLink>
        </nav>
        <span className="ownership">Your personal memory</span>
      </header>
      <Routes>
        <Route path="/" element={<LiveAssistantPage />} />
        <Route path="/people" element={<PeoplePage />} />
        <Route path="/people/:id" element={<PersonDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
