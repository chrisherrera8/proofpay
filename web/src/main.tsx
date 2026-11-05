import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Book from "./pages/Book";
import Booked from "./pages/Booked";
import "./styles.css";

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="nav">
        <Link to="/" className="brand">✨ Sparkle &amp; Shine</Link>
        <Link to="/book" className="btn small">Book now</Link>
      </header>
      <main>{children}</main>
      <footer className="footer">Demo site. Payments run in the PayPal sandbox; no real money moves.</footer>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/book" element={<Book />} />
          <Route path="/booked/:jobId" element={<Booked />} />
          <Route path="*" element={<Home />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  </React.StrictMode>,
);
