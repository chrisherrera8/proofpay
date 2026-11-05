import { Link } from "react-router-dom";
import { TIERS } from "../tiers";

export default function Home() {
  return (
    <>
      <section className="hero">
        <h1>A spotless home, paid for only when the job is done.</h1>
        <p>Your payment is held on your PayPal account and only collected after the cleaner's before and after photos are verified.</p>
        <a href="#pricing" className="btn">See services</a>
      </section>
      <section id="pricing" className="section">
        <h2>Choose your clean</h2>
        <div className="tiers">
          {TIERS.map((t) => (
            <article key={t.id} className={`card${t.popular ? " popular" : ""}`}>
              {t.popular && <span className="badge">Most popular</span>}
              <h3>{t.name}</h3>
              <p className="price">${t.price}</p>
              <p className="muted">{t.blurb}</p>
              <ul>{t.features.map((f) => <li key={f}>{f}</li>)}</ul>
              <Link to={`/book?tier=${t.id}`} className="btn">Book {t.name}</Link>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
