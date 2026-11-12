import { Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Book from "./pages/Book";
import Booked from "./pages/Booked";
import CleanerJobs from "./pages/CleanerJobs";
import CleanerSignup from "./pages/CleanerSignup";
import CleanerJob from "./pages/CleanerJob";

// Shared by main.tsx and the tests, so a route change can't drift from what's tested.
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/book" element={<Book />} />
      <Route path="/booked/:jobId" element={<Booked />} />
      <Route path="/cleaner" element={<CleanerJobs />} />
      <Route path="/cleaner/signup" element={<CleanerSignup />} />
      <Route path="/cleaner/:jobId" element={<CleanerJob />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
