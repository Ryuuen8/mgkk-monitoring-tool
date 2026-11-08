import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  api,
  CHECK_TYPES,
  DEVICE_TYPES,
  errorMessage,
  formatCheckType,
  formatDeviceType,
  type CheckType,
  type CredentialProfile,
  type CredentialType,
  type DeviceCreate,
  type DeviceGroup,
  type DeviceType,
  type Site,
} from "../api/client";

type DeviceFormProps = {
  deviceId?: number;
  onSaved: (id: number) => void;
  onCancel: () => void;
};

type FormState = {
  name: string;
  site_id: string;
  mgmt_ip: string;
  hostname: string;
  device_type: DeviceType;
  vendor: string;
  model: string;
  os_version: string;
  serial_number: string;
  check_type: CheckType;
  credential_profile_id: string;
  poll_interval_seconds: string;
  is_active: boolean;
  notes: string;
  group_ids: number[];
};

const EMPTY_FORM: FormState = {
  name: "",
  site_id: "",
  mgmt_ip: "",
  hostname: "",
  device_type: "router",
  vendor: "",
  model: "",
  os_version: "",
  serial_number: "",
  check_type: "ping_only",
  credential_profile_id: "",
  poll_interval_seconds: "60",
  is_active: true,
  notes: "",
  group_ids: [],
};

function DeviceForm({ deviceId, onSaved, onCancel }: DeviceFormProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [sites, setSites] = useState<Site[]>([]);
  const [groups, setGroups] = useState<DeviceGroup[]>([]);
  const [credentialProfiles, setCredentialProfiles] = useState<
    CredentialProfile[]
  >([]);
  const [credentialProfilesAvailable, setCredentialProfilesAvailable] =
    useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showSiteForm, setShowSiteForm] = useState(false);
  const [newSiteCode, setNewSiteCode] = useState("");
  const [newSiteName, setNewSiteName] = useState("");
  const [creatingSite, setCreatingSite] = useState(false);
  const [showCredentialForm, setShowCredentialForm] = useState(false);
  const [credentialName, setCredentialName] = useState("");
  const [credentialUsername, setCredentialUsername] = useState("");
  const [credentialSecret, setCredentialSecret] = useState("");
  const [credentialPort, setCredentialPort] = useState("161");
  const [credentialVerifyTls, setCredentialVerifyTls] = useState(true);
  const [creatingCredential, setCreatingCredential] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const [siteResponse, groupResponse, credentialResponse] = await Promise.all([
        api.GET("/api/sites", { params: { query: { limit: 200 } } }),
        api.GET("/api/device-groups", { params: { query: { limit: 200 } } }),
        api.GET("/api/credential-profiles"),
      ]);
      if (cancelled) return;

      if (siteResponse.error) {
        setError(errorMessage(siteResponse.error));
        setLoading(false);
        return;
      }
      setSites(siteResponse.data.items);
      if (groupResponse.data) setGroups(groupResponse.data.items);
      if (credentialResponse.data) {
        setCredentialProfiles(credentialResponse.data);
        setCredentialProfilesAvailable(true);
      } else {
        setCredentialProfilesAvailable(false);
        setError(
          "Credential profiles could not be loaded. Restart the API with the latest backend changes to use SNMP or RouterOS checks.",
        );
      }

      if (deviceId) {
        const { data, error: deviceError } = await api.GET(
          "/api/devices/{device_id}",
          { params: { path: { device_id: deviceId } } },
        );
        if (cancelled) return;
        if (deviceError) {
          setError(errorMessage(deviceError));
          setLoading(false);
          return;
        }
        setForm({
          name: data.name,
          site_id: String(data.site_id),
          mgmt_ip: data.mgmt_ip,
          hostname: data.hostname ?? "",
          device_type: data.device_type,
          vendor: data.vendor ?? "",
          model: data.model ?? "",
          os_version: data.os_version ?? "",
          serial_number: data.serial_number ?? "",
          check_type: data.check_type ?? "ping_only",
          credential_profile_id:
            data.credential_profile_id == null
              ? ""
              : String(data.credential_profile_id),
          poll_interval_seconds: String(data.poll_interval_seconds),
          is_active: data.is_active,
          notes: data.notes ?? "",
          group_ids: (data.groups ?? []).map((group) => group.id),
        });
      } else if (siteResponse.data.items.length === 0) {
        setShowSiteForm(true);
      }
      setLoading(false);
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [deviceId]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  const createSite = async () => {
    if (!newSiteCode.trim() || !newSiteName.trim()) return;
    setCreatingSite(true);
    const { data, error: siteError } = await api.POST("/api/sites", {
      body: {
        code: newSiteCode.trim(),
        name: newSiteName.trim(),
        timezone: "UTC",
      },
    });
    setCreatingSite(false);
    if (siteError) {
      setError(errorMessage(siteError));
      return;
    }
    setSites((previous) => [...previous, data]);
    update("site_id", String(data.id));
    setNewSiteCode("");
    setNewSiteName("");
    setShowSiteForm(false);
    setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.site_id) {
      setError("Choose a site first.");
      return;
    }

    const payload: DeviceCreate = {
      site_id: Number(form.site_id),
      name: form.name.trim(),
      mgmt_ip: form.mgmt_ip.trim(),
      hostname: form.hostname.trim() || null,
      device_type: form.device_type,
      vendor: form.vendor.trim() || null,
      model: form.model.trim() || null,
      os_version: form.os_version.trim() || null,
      serial_number: form.serial_number.trim() || null,
      check_type: form.check_type,
      credential_profile_id:
        form.credential_profile_id === ""
          ? null
          : Number(form.credential_profile_id),
      poll_interval_seconds: Number(form.poll_interval_seconds),
      is_active: form.is_active,
      notes: form.notes.trim() || null,
      group_ids: form.group_ids,
    };

    setSaving(true);
    setError(null);

    if (deviceId) {
      const { data, error: saveError } = await api.PATCH(
        "/api/devices/{device_id}",
        { params: { path: { device_id: deviceId } }, body: payload },
      );
      setSaving(false);
      if (saveError) {
        setError(errorMessage(saveError));
        return;
      }
      onSaved(data.id);
      return;
    }

    const { data, error: saveError } = await api.POST("/api/devices", {
      body: payload,
    });
    setSaving(false);
    if (saveError) {
      setError(errorMessage(saveError));
      return;
    }
    onSaved(data.id);
  };

  const createCredentialProfile = async () => {
    if (!credentialName.trim() || !credentialSecret) {
      setError("Enter a profile name and secret.");
      return;
    }
    const credentialType: CredentialType =
      form.check_type === "snmp" ? "snmp_v2c" : "routeros_api";
    setCreatingCredential(true);
    const { data, error: profileError } = await api.POST(
      "/api/credential-profiles",
      {
        body: {
          name: credentialName.trim(),
          credential_type: credentialType,
          username:
            credentialType === "routeros_api" ? credentialUsername.trim() : null,
          secret: credentialSecret,
          port: Number(credentialPort),
          verify_tls: credentialVerifyTls,
        },
      },
    );
    setCreatingCredential(false);
    if (profileError) {
      setError(errorMessage(profileError));
      return;
    }
    setCredentialProfiles((previous) => [...previous, data]);
    update("credential_profile_id", String(data.id));
    setCredentialName("");
    setCredentialUsername("");
    setCredentialSecret("");
    setShowCredentialForm(false);
    setError(null);
  };

  if (loading) {
    return <p className="muted">Loading form…</p>;
  }

  return (
    <section className="page-section" aria-labelledby="form-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            INVENTORY <span> / </span> {deviceId ? "EDIT DEVICE" : "NEW DEVICE"}
          </p>
          <h1 id="form-title">{deviceId ? "Edit device" : "Add device"}</h1>
          <p className="subtitle">
            The poller picks new devices up within one tick, then every poll
            interval.
          </p>
        </div>
        <button className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>

      {error && <p className="banner banner-error">{error}</p>}

      <form className="form-card" onSubmit={(event) => void submit(event)}>
        <fieldset>
          <legend>Identity</legend>
          <div className="form-grid">
            <label className="field">
              <span>Name *</span>
              <input
                required
                maxLength={120}
                value={form.name}
                onChange={(event) => update("name", event.target.value)}
                placeholder="core-rtr-1"
              />
            </label>

            <label className="field">
              <span>Site *</span>
              <select
                required
                value={form.site_id}
                onChange={(event) => update("site_id", event.target.value)}
              >
                <option value="">Choose a site…</option>
                {sites.map((site) => (
                  <option key={site.id} value={site.id}>
                    {site.name} ({site.code})
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Device type</span>
              <select
                value={form.device_type}
                onChange={(event) =>
                  update("device_type", event.target.value as DeviceType)
                }
              >
                {DEVICE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {formatDeviceType(type)}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Hostname</span>
              <input
                maxLength={255}
                value={form.hostname}
                onChange={(event) => update("hostname", event.target.value)}
                placeholder="core-rtr-1.example.net"
              />
            </label>

            <label className="field">
              <span>Vendor</span>
              <input
                maxLength={64}
                value={form.vendor}
                onChange={(event) => update("vendor", event.target.value)}
                placeholder="mikrotik"
              />
            </label>

            <label className="field">
              <span>Model</span>
              <input
                maxLength={120}
                value={form.model}
                onChange={(event) => update("model", event.target.value)}
              />
            </label>

            <label className="field">
              <span>OS version</span>
              <input
                maxLength={64}
                value={form.os_version}
                onChange={(event) => update("os_version", event.target.value)}
              />
            </label>

            <label className="field">
              <span>Serial number</span>
              <input
                maxLength={120}
                value={form.serial_number}
                onChange={(event) => update("serial_number", event.target.value)}
              />
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>Network</legend>
          <div className="form-grid">
            <label className="field">
              <span>Management IP *</span>
              <input
                required
                value={form.mgmt_ip}
                onChange={(event) => update("mgmt_ip", event.target.value)}
                placeholder="192.168.88.1"
              />
            </label>

            <label className="field">
              <span>Poll interval (seconds)</span>
              <input
                type="number"
                min={10}
                max={3600}
                required
                value={form.poll_interval_seconds}
                onChange={(event) =>
                  update("poll_interval_seconds", event.target.value)
                }
              />
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>Monitoring</legend>
          <div className="form-grid">
            <label className="field">
              <span>Check type</span>
              <select
                value={form.check_type}
                onChange={(event) => {
                  const checkType = event.target.value as CheckType;
                  update("check_type", checkType);
                  update("credential_profile_id", "");
                  setCredentialPort(checkType === "snmp" ? "161" : "443");
                  if (checkType === "routeros_api" && !form.vendor.trim()) {
                    update("vendor", "mikrotik");
                    update("device_type", "router");
                  }
                }}
              >
                {CHECK_TYPES.map((type) => (
                  <option
                    key={type}
                    value={type}
                    disabled={type !== "ping_only" && !credentialProfilesAvailable}
                  >
                    {type !== "ping_only" && !credentialProfilesAvailable
                      ? `${formatCheckType(type)} (API unavailable)`
                      : formatCheckType(type)}
                  </option>
                ))}
              </select>
            </label>
            {form.check_type !== "ping_only" && (
              <label className="field">
                <span>Credential profile *</span>
                <select
                  required
                  value={form.credential_profile_id}
                  onChange={(event) =>
                    update("credential_profile_id", event.target.value)
                  }
                >
                  <option value="">Choose a profile…</option>
                  {credentialProfiles
                    .filter(
                      (profile) =>
                        profile.credential_type ===
                        (form.check_type === "snmp"
                          ? "snmp_v2c"
                          : "routeros_api"),
                    )
                    .map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.name}
                      </option>
                    ))}
                </select>
              </label>
            )}
          </div>
          {!credentialProfilesAvailable && (
            <p className="banner banner-error">
              SNMP and RouterOS checks are unavailable until the backend
              credential-profile API is running.
            </p>
          )}
          <div className="checkbox-row">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(event) => update("is_active", event.target.checked)}
              />
              Active
            </label>
          </div>
          {form.check_type !== "ping_only" && (
            <div className="inline-panel">
              {showCredentialForm ? (
                <>
                  <h3>New encrypted credential profile</h3>
                  <div className="form-grid">
                    <label className="field">
                      <span>Profile name *</span>
                      <input
                        required
                        maxLength={120}
                        value={credentialName}
                        onChange={(event) =>
                          setCredentialName(event.target.value)
                        }
                      />
                    </label>
                    {form.check_type === "routeros_api" && (
                      <label className="field">
                        <span>Username *</span>
                        <input
                          required
                          maxLength={120}
                          value={credentialUsername}
                          onChange={(event) =>
                            setCredentialUsername(event.target.value)
                          }
                        />
                      </label>
                    )}
                    <label className="field">
                      <span>
                        {form.check_type === "snmp" ? "Community *" : "Password *"}
                      </span>
                      <input
                        required
                        type="password"
                        value={credentialSecret}
                        onChange={(event) =>
                          setCredentialSecret(event.target.value)
                        }
                      />
                    </label>
                    <label className="field">
                      <span>Port</span>
                      <input
                        type="number"
                        min={1}
                        max={65535}
                        required
                        value={credentialPort}
                        onChange={(event) =>
                          setCredentialPort(event.target.value)
                        }
                      />
                    </label>
                  </div>
                  {form.check_type === "routeros_api" && (
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={credentialVerifyTls}
                        onChange={(event) =>
                          setCredentialVerifyTls(event.target.checked)
                        }
                      />
                      Verify TLS certificate
                    </label>
                  )}
                  <div className="row-actions">
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={creatingCredential}
                      onClick={() => void createCredentialProfile()}
                    >
                      {creatingCredential ? "Saving…" : "Save profile"}
                    </button>
                    <button
                      type="button"
                      className="button"
                      onClick={() => setShowCredentialForm(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </>
              ) : (
                <button
                  type="button"
                  className="link-button"
                  onClick={() => setShowCredentialForm(true)}
                >
                  + New credential profile
                </button>
              )}
              <p className="muted">
                Secrets are encrypted before storage and are never returned by
                the API. RouterOS API profiles require HTTPS.
              </p>
            </div>
          )}
        </fieldset>

        <fieldset>
          <legend>Groups</legend>
          {groups.length === 0 ? (
            <p className="muted">No device groups yet.</p>
          ) : (
            <div className="checkbox-grid">
              {groups.map((group) => (
                <label key={group.id} className="checkbox">
                  <input
                    type="checkbox"
                    checked={form.group_ids.includes(group.id)}
                    onChange={(event) =>
                      update(
                        "group_ids",
                        event.target.checked
                          ? [...form.group_ids, group.id]
                          : form.group_ids.filter((id) => id !== group.id),
                      )
                    }
                  />
                  {group.name}
                </label>
              ))}
            </div>
          )}
        </fieldset>

        <fieldset>
          <legend>Notes</legend>
          <label className="field">
            <textarea
              rows={3}
              value={form.notes}
              onChange={(event) => update("notes", event.target.value)}
              placeholder="Rack, owner, maintenance window…"
            />
          </label>
        </fieldset>

        {sites.length === 0 && (
          <div className="inline-panel">
            <p className="muted">
              A device must belong to a site. Create one without leaving this
              page.
            </p>
          </div>
        )}

        {showSiteForm && (
          <div className="inline-panel">
            <h3>Quick-create a site</h3>
            <div className="form-grid">
              <label className="field">
                <span>Code</span>
                <input
                  maxLength={16}
                  value={newSiteCode}
                  onChange={(event) => setNewSiteCode(event.target.value)}
                  placeholder="HQ"
                />
              </label>
              <label className="field">
                <span>Name</span>
                <input
                  maxLength={120}
                  value={newSiteName}
                  onChange={(event) => setNewSiteName(event.target.value)}
                  placeholder="Headquarters"
                />
              </label>
            </div>
            <div className="row-actions">
              <button
                type="button"
                className="button button-primary"
                disabled={creatingSite}
                onClick={() => void createSite()}
              >
                {creatingSite ? "Creating…" : "Create site"}
              </button>
              {sites.length > 0 && (
                <button
                  type="button"
                  className="button"
                  onClick={() => setShowSiteForm(false)}
                >
                  Hide
                </button>
              )}
            </div>
          </div>
        )}

        {!showSiteForm && sites.length > 0 && (
          <button
            type="button"
            className="link-button"
            onClick={() => setShowSiteForm(true)}
          >
            + New site
          </button>
        )}

        <div className="form-actions">
          <button className="button button-primary" disabled={saving}>
            {saving ? "Saving…" : deviceId ? "Save changes" : "Add device"}
          </button>
          <button type="button" className="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

export default DeviceForm;
