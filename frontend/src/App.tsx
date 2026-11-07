import { useEffect, useState } from "react";

type ApiStatus = "checking" | "online" | "offline";

type DeviceStatus = {
  target: string;
  type: "http" | "ping";
  status: "online" | "offline" | "checking";
  http_status?: number;
  avg_rtt?: number;
  packet_loss?: number;
  checked_at?: string;
  error?: string;
};

type Tab = "overview" | "monitoring";

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [deviceStatus, setDeviceStatus] = useState<DeviceStatus | null>(null);
  const [deviceLoading, setDeviceLoading] = useState(false);

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

  useEffect(() => {
    if (activeTab !== "monitoring") return;

    let cancelled = false;

    const loadDeviceStatus = () => {
      setDeviceLoading(true);
      fetch("/api/device-status")
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Device status returned ${response.status}`);
          }
          return response.json() as Promise<DeviceStatus>;
        })
        .then((result) => {
          if (!cancelled) setDeviceStatus(result);
        })
        .catch(() => {
          if (!cancelled) {
            setDeviceStatus({
              target: "unknown",
              type: "ping",
              status: "offline",
            });
          }
        })
        .finally(() => {
          if (!cancelled) setDeviceLoading(false);
        });
    };

    loadDeviceStatus();
    const interval = window.setInterval(loadDeviceStatus, 10000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [activeTab]);

  const statusLabel = {
    checking: "Checking",
    online: "Operational",
    offline: "Unavailable",
  }[apiStatus];

  const deviceStatusLabel =
    deviceStatus?.status === "online"
      ? "Online"
      : deviceStatus?.status === "offline"
        ? "Offline"
        : "Checking";

  return (
    <main className="dashboard">
      <header className="topbar">
        <a className="brand" href="/" aria-label="MGKK Monitoring home">
          <span className="brand-mark">M</span>
          <span>MGKK<span className="brand-light"> / MONITOR</span></span>
        </a>
        <span className="environment"><span className="environment-dot" /> SYSTEM OVERVIEW</span>
      </header>

      <nav className="tabs" aria-label="Dashboard tabs">
        <button
          className={`tab ${activeTab === "overview" ? "tab-active" : ""}`}
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          className={`tab ${activeTab === "monitoring" ? "tab-active" : ""}`}
          onClick={() => setActiveTab("monitoring")}
        >
          Monitoring
        </button>
      </nav>

      {activeTab === "overview" && (
        <>
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
        </>
      )}

      {activeTab === "monitoring" && (
        <>
          <section className="intro">
            <p className="eyebrow">TEMPORARY TAB <span> / </span> DEVICE CHECK</p>
            <h1>Monitoring a single device.</h1>
            <p className="subtitle">Live ping/HTTP status for the configured target.</p>
          </section>

          <section className="service-section" aria-labelledby="device-title">
            <div className="section-heading">
              <h2 id="device-title">Device status</h2>
              <span className="service-count">01 DEVICE</span>
            </div>
            <article className="service-card">
              <div className="service-icon" aria-hidden="true">
                {deviceStatus?.type === "ping" ? "PING" : "HTTP"}
              </div>
              <div className="service-info">
                <h3>{deviceStatus?.target ?? "Configured target"}</h3>
                <p>
                  {deviceLoading
                    ? "Checking device..."
                    : deviceStatus?.type === "ping"
                      ? `Average RTT: ${deviceStatus?.avg_rtt?.toFixed(1) ?? "-"} ms, packet loss: ${((deviceStatus?.packet_loss ?? 0) * 100).toFixed(0)}%`
                      : deviceStatus?.http_status
                        ? `HTTP ${deviceStatus.http_status}`
                        : "No response yet"}
                </p>
                {deviceStatus?.error && <p className="error-text">{deviceStatus.error}</p>}
                {deviceStatus?.checked_at && (
                  <p className="checked-at">Last checked: {new Date(deviceStatus.checked_at).toLocaleTimeString()}</p>
                )}
              </div>
              <div className={`status status-${deviceStatus?.status ?? "checking"}`}>
                <span className="status-dot" />
                {deviceLoading ? "Checking" : deviceStatusLabel}
              </div>
            </article>
          </section>
        </>
      )}

      <footer>
        <span>MGKK MONITORING</span>
        <span>CONNECTED SERVICES <b>01</b></span>
      </footer>
    </main>
  );
}

export default App;