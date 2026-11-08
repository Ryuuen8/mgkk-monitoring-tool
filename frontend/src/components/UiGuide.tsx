type UiGuideProps = {
  onDevices: () => void;
  onAddDevice: () => void;
  onCredentials: () => void;
};

function UiGuide({ onDevices, onAddDevice, onCredentials }: UiGuideProps) {
  return (
    <section className="page-section" aria-labelledby="guide-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            HELP <span> / </span> UI WALKTHROUGH
          </p>
          <h1 id="guide-title">How to use MGKK Monitoring</h1>
          <p className="subtitle">
            A quick guide to the dashboard, inventory, device details, and
            monitoring credentials.
          </p>
        </div>
      </div>

      <div className="guide-layout">
        <nav className="guide-nav" aria-label="Guide sections">
          <a href="#guide-overview">Overview</a>
          <a href="#guide-devices">Devices</a>
          <a href="#guide-device-form">Add or edit a device</a>
          <a href="#guide-device-detail">Device details</a>
          <a href="#guide-credentials">Credentials</a>
          <a href="#guide-status">Understanding status</a>
        </nav>

        <div className="guide-content">
          <article className="guide-card" id="guide-overview">
            <p className="guide-step">01 / DASHBOARD</p>
            <h2>Overview</h2>
            <p>
              The Overview tab summarizes the app services. The Monitoring API
              indicator reports whether the API health endpoint is responding;
              the Device poller card describes the background checker.
            </p>
            <p className="muted">
              An operational API does not guarantee every monitored device is
              reachable. Check device status in the Devices view.
            </p>
          </article>

          <article className="guide-card" id="guide-devices">
            <p className="guide-step">02 / INVENTORY</p>
            <h2>Devices list</h2>
            <p>
              Devices lists registered targets and refreshes their latest status
              periodically. Use <strong>+ Add device</strong> to register a
              target. Select a device name or <strong>Open</strong> to view its
              details, <strong>Edit</strong> to change its settings, and{" "}
              <strong>Delete</strong> to remove it after confirmation.
            </p>
            <ul>
              <li>
                <strong>Device, site, type:</strong> identify the inventory
                entry and where it belongs.
              </li>
              <li>
                <strong>Check:</strong> shows whether it uses Ping, SNMP, or
                RouterOS API.
              </li>
              <li>
                <strong>Status and latency:</strong> reflect the latest
                successful or failed check.
              </li>
              <li>
                <strong>Loss:</strong> applies to ICMP Ping only; other check
                types do not measure packet loss.
              </li>
              <li>
                <strong>Last seen:</strong> the most recent successful check.
                “No data” means the poller has not reported a result yet.
              </li>
            </ul>
            <div className="guide-actions">
              <button className="button" onClick={onDevices}>
                Open devices
              </button>
              <button className="button button-primary" onClick={onAddDevice}>
                Add a device
              </button>
            </div>
          </article>

          <article className="guide-card" id="guide-device-form">
            <p className="guide-step">03 / DEVICE SETUP</p>
            <h2>Add or edit a device</h2>
            <p>The form is grouped by the kind of information you enter:</p>
            <ul>
              <li>
                <strong>Identity:</strong> name, site, device type, hostname,
                vendor, model, RouterOS version, and serial number. Use a
                recognizable unique name; the IP can change without changing
                the inventory identity.
              </li>
              <li>
                <strong>Network:</strong> management IP and how often the device
                should be checked (10–3600 seconds).
              </li>
              <li>
                <strong>Monitoring:</strong> select a check type and telemetry
                collector. Generic SNMP and MikroTik SNMP share system and
                interface polling; the MikroTik collector adds RouterOS
                resources. RouterOS API checks require the MikroTik collector.
              </li>
              <li>
                <strong>Groups:</strong> optionally add the device to one or
                more inventory groups. Group assignment is supported here, but
                there is not yet a screen to create or manage groups.
              </li>
              <li>
                <strong>Notes:</strong> record operational context such as rack,
                owner, or maintenance window.
              </li>
            </ul>
            <p className="muted">
              The poller discovers new active devices automatically. The first
              status appears after the next due check and Prometheus scrape.
            </p>
          </article>

          <article className="guide-card" id="guide-device-detail">
            <p className="guide-step">04 / DEVICE DETAILS</p>
            <h2>Device details</h2>
            <p>
              The detail page combines the latest status with historical
              measurements. The summary cards show current latency, last seen,
              poll interval, and—on Ping checks—packet loss. Use the chart range
              buttons to change the displayed history. Inventory details show
              the site, address, model, group membership, check type, and
              associated credential profile name. SNMP devices show system
              name/description, uptime, interfaces, CPU and memory when their
              agent reports the selected MIB. MikroTik API checks also report
              disk, temperature, voltage, and DHCP/ARP counts.
            </p>
            <p>
              Select an interface to view 24-hour, 7-day, or 30-day traffic,
              error, discard, and utilization charts. Set a link-speed override
              when virtual or tunnel links do not report a reliable{" "}
              <code>ifHighSpeed</code>.
            </p>
          </article>

          <article className="guide-card" id="guide-credentials">
            <p className="guide-step">05 / ACCESS PROFILES</p>
            <h2>Credential profiles</h2>
            <p>
              Use the Credentials tab to create shared authentication profiles
              for monitored devices. Choose SNMP v2c for a read-only community,
              SNMP v3 for a username and SHA/SHA-256 authentication with
              optional AES-128 privacy, or RouterOS API for a read-only username
              and password. RouterOS REST uses HTTPS and verifies TLS
              certificates by default; RouterOS v6 falls back to API-SSL on
              port 8729.
            </p>
            <ul>
              <li>
                Secrets are encrypted before storage and are never shown again
                in API responses. To replace one, edit the profile and enter a
                new secret; leave the secret blank to keep the current one.
              </li>
              <li>
                Profiles can be shared by multiple devices. A profile assigned
                to a device cannot be deleted.
              </li>
              <li>
                The backend requires{" "}
                <code>CREDENTIAL_ENCRYPTION_KEY</code>. Keep it private and
                unchanged while profile secrets are in use.
              </li>
            </ul>
            <div className="guide-actions">
              <button className="button button-primary" onClick={onCredentials}>
                Open credentials
              </button>
            </div>
            <p className="muted">
              For the platform architecture and a presentation talk track, see
              the system flow documentation in the project README.
            </p>
          </article>

          <article className="guide-card" id="guide-status">
            <p className="guide-step">06 / TROUBLESHOOTING</p>
            <h2>Understanding status</h2>
            <ul>
              <li>
                <strong>No data:</strong> the poller has not exposed a sample
                yet, or Prometheus has not scraped it. Allow a poll interval and
                scrape cycle.
              </li>
              <li>
                <strong>Offline:</strong> the selected check failed. Confirm
                address, routing, firewall rules, service settings, and
                credentials.
              </li>
              <li>
                <strong>SNMP:</strong> ensure the selected v2c or v3 user is
                enabled and reachable over UDP from the poller container.
              </li>
              <li>
                <strong>RouterOS:</strong> enable <code>www-ssl</code>, use a
                read-only RouterOS account, and allow HTTPS from the poller
                network.
              </li>
              <li>
                <strong>Ping:</strong> the poller container needs ICMP access
                (<code>NET_RAW</code> or permitted unprivileged ping). Docker
                Desktop may need extra routing to reach a separate lab subnet.
              </li>
            </ul>
            <p className="muted">
              The API currently has no user sign-in. Keep it restricted to a
              trusted network and use least-privilege monitoring credentials.
            </p>
          </article>
        </div>
      </div>
    </section>
  );
}

export default UiGuide;
