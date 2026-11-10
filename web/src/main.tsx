import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/layout";
import Home from "./pages/Home";
import Book from "./pages/Book";
import Booked from "./pages/Booked";
import CleanerJobs from "./pages/CleanerJobs";
import CleanerSignup from "./pages/CleanerSignup";
import CleanerJob from "./pages/CleanerJob";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/book" element={<Book />} />
          <Route path="/booked/:jobId" element={<Booked />} />
          <Route path="/cleaner" element={<CleanerJobs />} />
          <Route path="/cleaner/signup" element={<CleanerSignup />} />
          <Route path="/cleaner/:jobId" element={<CleanerJob />} />
          <Route path="*" element={<Home />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  </React.StrictMode>,
);
