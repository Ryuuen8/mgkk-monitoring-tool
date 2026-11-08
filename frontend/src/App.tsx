import { useEffect, useState } from "react";
import CredentialProfiles from "./components/CredentialProfiles";
import DeviceDetailPage from "./components/DeviceDetail";
import DeviceForm from "./components/DeviceForm";
import DeviceList from "./components/DeviceList";

type Tab = "overview" | "devices" | "credentials";

type DeviceRoute =
  | { view: "list" }
  | { view: "add" }
  | { view: "edit"; id: number }
  | { view: "detail"; id: number };

type ApiStatus = "checking" | "online" | "offline";

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("devices");
  const [route, setRoute] = useState<DeviceRoute>({ view: "list" });
  const [refreshToken, setRefreshToken] = useState(0);
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
      .then((result) =>
        setApiStatus(result.status === "ok" ? "online" : "offline"),
      )
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setApiStatus("offline");
      });

    return () => controller.abort();
  }, []);

  const showDevices = () => {
    setActiveTab("devices");
    setRoute({ view: "list" });
  };

  const handleSaved = (id: number) => {
    setRefreshToken((token) => token + 1);
    setRoute({ view: "detail", id });
  };

  const handleDeleted = () => {
    setRefreshToken((token) => token + 1);
    setRoute({ view: "list" });
  };

  const statusLabel = {
    checking: "Checking",
    online: "Operational",
    offline: "Unavailable",
  }[apiStatus];

  return (
    <main className="dashboard">
      <header className="topbar">
        <a
          className="brand"
          href="/"
          aria-label="MGKK Monitoring home"
          onClick={(event) => {
            event.preventDefault();
            setActiveTab("overview");
          }}
        >
          <span className="brand-mark">M</span>
          <span>
            MGKK<span className="brand-light"> / MONITOR</span>
          </span>
        </a>
        <span className="environment">
          <span className="environment-dot" /> NETWORK OPERATIONS
        </span>
      </header>

      <nav className="tabs" aria-label="Dashboard tabs">
        <button
          className={`tab ${activeTab === "overview" ? "tab-active" : ""}`}
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          className={`tab ${activeTab === "devices" ? "tab-active" : ""}`}
          onClick={showDevices}
        >
          Devices
        </button>
        <button
          className={`tab ${activeTab === "credentials" ? "tab-active" : ""}`}
          onClick={() => setActiveTab("credentials")}
        >
          Credentials
        </button>
      </nav>

      {activeTab === "overview" && (
        <section className="page-section">
          <div className="intro">
            <p className="eyebrow">
              OPERATIONS CENTER <span> / </span> OVERVIEW
            </p>
            <h1>Monitoring, at a glance.</h1>
            <p className="subtitle">
              A live view of your monitoring platform services.
            </p>
          </div>

          <div className="service-section" aria-labelledby="services-title">
            <div className="section-heading">
              <h2 id="services-title">Core services</h2>
              <span className="service-count">02 SERVICES</span>
            </div>

            <article className="service-card">
              <div className="service-icon" aria-hidden="true">
                API
              </div>
              <div className="service-info">
                <h3>Monitoring API</h3>
                <p>Inventory, device status and Prometheus chart data</p>
              </div>
              <div className={`status status-${apiStatus}`}>
                <span className="status-dot" />
                {statusLabel}
              </div>
            </article>

            <article className="service-card">
              <div className="service-icon" aria-hidden="true">
                POLL
              </div>
              <div className="service-info">
                <h3>Device poller</h3>
                <p>
                  ICMP, SNMPv2c and MikroTik RouterOS HTTPS checks
                </p>
              </div>
              <button className="button" onClick={showDevices}>
                View devices
              </button>
            </article>
          </div>
        </section>
      )}

      {activeTab === "devices" && (
        <>
          {route.view === "list" && (
            <DeviceList
              refreshToken={refreshToken}
              onAdd={() => setRoute({ view: "add" })}
              onOpen={(id) => setRoute({ view: "detail", id })}
              onEdit={(id) => setRoute({ view: "edit", id })}
              onDeleted={handleDeleted}
            />
          )}
          {route.view === "add" && (
            <DeviceForm
              onSaved={handleSaved}
              onCancel={() => setRoute({ view: "list" })}
            />
          )}

          {route.view === "edit" && (
            <DeviceForm
              deviceId={route.id}
              onSaved={handleSaved}
              onCancel={() => setRoute({ view: "detail", id: route.id })}
            />
          )}

          {route.view === "detail" && (
            <DeviceDetailPage
              deviceId={route.id}
              onBack={() => setRoute({ view: "list" })}
              onEdit={(id) => setRoute({ view: "edit", id })}
            />
          )}
        </>
      )}
      {activeTab === "credentials" && (
        <CredentialProfiles onDevices={showDevices} />
      )}

      <footer>
        <span>MGKK MONITORING</span>
        <span>
          CONNECTED SERVICES <b>02</b>
        </span>
      </footer>
    </main>
  );
}

export default App;
