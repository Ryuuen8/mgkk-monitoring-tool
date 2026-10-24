import { useEffect, useState } from "react";

type ApiStatus = "checking" | "online" | "offline";

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/health", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Health check returned ${response.status}`);
        }
        return response.json() as Promise<{ status: string }>;
      })
      .then((result) => setApiStatus(result.status === "ok" ? "online" : "offline"))
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setApiStatus("offline");
      });

    return () => controller.abort();
  }, []);

  const statusLabel = {
    checking: "Checking",
    online: "Operational",
    offline: "Unavailable",
  }[apiStatus];

  return (
    <main className="dashboard">
      <header className="topbar">
        <a className="brand" href="/" aria-label="MGKK Monitoring home">
          <span className="brand-mark">M</span>
          <span>MGKK<span className="brand-light"> / MONITOR</span></span>
        </a>
        <span className="environment"><span className="environment-dot" /> SYSTEM OVERVIEW</span>
      </header>

      <section className="intro">
        <p className="eyebrow">OPERATIONS CENTER <span> / </span> OVERVIEW</p>
        <h1>Monitoring, at a glance.</h1>
        <p className="subtitle">A live view of your monitoring platform services.</p>
      </section>

      <section className="service-section" aria-labelledby="services-title">
        <div className="section-heading">
          <h2 id="services-title">Core services</h2>
          <span className="service-count">01 SERVICE</span>
        </div>
        <article className="service-card">
          <div className="service-icon" aria-hidden="true">API</div>
          <div className="service-info">
            <h3>Monitoring API</h3>
            <p>Application health and metrics endpoint</p>
          </div>
          <div className={`status status-${apiStatus}`}>
            <span className="status-dot" />
            {statusLabel}
          </div>
        </article>
      </section>

      <footer>
        <span>MGKK MONITORING</span>
        <span>CONNECTED SERVICES <b>01</b></span>
      </footer>
    </main>
  );
}

export default App;
