import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  api,
  errorMessage,
  type CredentialProfile,
  type CredentialType,
} from "../api/client";

type CredentialProfilesProps = {
  onDevices: () => void;
};

type ProfileForm = {
  name: string;
  credential_type: CredentialType;
  username: string;
  secret: string;
  port: string;
  verify_tls: boolean;
};

const EMPTY_FORM: ProfileForm = {
  name: "",
  credential_type: "snmp_v2c",
  username: "",
  secret: "",
  port: "161",
  verify_tls: true,
};

function profileTypeLabel(type: CredentialType): string {
  return type === "snmp_v2c" ? "SNMP v2c" : "RouterOS API";
}

function CredentialProfiles({ onDevices }: CredentialProfilesProps) {
  const [profiles, setProfiles] = useState<CredentialProfile[]>([]);
  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProfiles = async () => {
    setLoading(true);
    const { data, error: loadError } = await api.GET("/api/credential-profiles");
    if (loadError) {
      setLoadFailed(true);
      setError(
        `Could not load credential profiles: ${errorMessage(loadError)}. Restart the API with the latest backend changes if this route is unavailable.`,
      );
      setLoading(false);
      return;
    }
    setProfiles(data);
    setLoadFailed(false);
    setError(null);
    setLoading(false);
  };

  useEffect(() => {
    void loadProfiles();
  }, []);

  const beginCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormOpen(true);
    setError(null);
  };

  const beginEdit = (profile: CredentialProfile) => {
    setEditingId(profile.id);
    setForm({
      name: profile.name,
      credential_type: profile.credential_type,
      username: profile.username ?? "",
      secret: "",
      port: String(profile.port),
      verify_tls: profile.verify_tls,
    });
    setFormOpen(true);
    setError(null);
  };

  const updateType = (type: CredentialType) => {
    setForm((current) => ({
      ...current,
      credential_type: type,
      port: type === "snmp_v2c" ? "161" : "443",
    }));
  };

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    if (editingId === null) {
      const { data, error: saveError } = await api.POST(
        "/api/credential-profiles",
        {
          body: {
            name: form.name.trim(),
            credential_type: form.credential_type,
            username:
              form.credential_type === "routeros_api"
                ? form.username.trim()
                : null,
            secret: form.secret,
            port: Number(form.port),
            verify_tls: form.verify_tls,
          },
        },
      );
      setSaving(false);
      if (saveError) {
        setError(errorMessage(saveError));
        return;
      }
      setProfiles((current) =>
        [...current, data].sort((a, b) => a.name.localeCompare(b.name)),
      );
      setLoadFailed(false);
    } else {
      const { data, error: saveError } = await api.PATCH(
        "/api/credential-profiles/{profile_id}",
        {
          params: { path: { profile_id: editingId } },
          body: {
            name: form.name.trim(),
            username:
              form.credential_type === "routeros_api"
                ? form.username.trim()
                : null,
            secret: form.secret || undefined,
            port: Number(form.port),
            verify_tls: form.verify_tls,
          },
        },
      );
      setSaving(false);
      if (saveError) {
        setError(errorMessage(saveError));
        return;
      }
      setProfiles((current) =>
        current
          .map((profile) => (profile.id === data.id ? data : profile))
          .sort((a, b) => a.name.localeCompare(b.name)),
      );
    }

    setFormOpen(false);
    setForm(EMPTY_FORM);
    setEditingId(null);
  };

  const deleteProfile = async (profile: CredentialProfile) => {
    if (
      !window.confirm(
        `Delete "${profile.name}"? Profiles assigned to devices cannot be deleted.`,
      )
    ) {
      return;
    }
    const { error: deleteError } = await api.DELETE(
      "/api/credential-profiles/{profile_id}",
      { params: { path: { profile_id: profile.id } } },
    );
    if (deleteError) {
      setError(errorMessage(deleteError));
      return;
    }
    setProfiles((current) => current.filter((item) => item.id !== profile.id));
    setError(null);
  };

  return (
    <section className="page-section" aria-labelledby="credentials-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            SETTINGS <span> / </span> CREDENTIAL PROFILES
          </p>
          <h1 id="credentials-title">Credential profiles</h1>
          <p className="subtitle">
            Shared SNMP and RouterOS credentials, encrypted before storage.
          </p>
        </div>
        <div className="heading-actions">
          <button className="button" onClick={onDevices}>
            View devices
          </button>
          <button
            className="button button-primary"
            disabled={loadFailed}
            onClick={beginCreate}
          >
            + Add profile
          </button>
        </div>
      </div>

      {error && <p className="banner banner-error">{error}</p>}

      {formOpen && (
        <form
          className="form-card credential-form"
          onSubmit={(event) => void saveProfile(event)}
        >
          <fieldset>
            <legend>{editingId === null ? "New profile" : "Edit profile"}</legend>
            <div className="form-grid">
              <label className="field">
                <span>Profile name *</span>
                <input
                  required
                  maxLength={120}
                  value={form.name}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, name: event.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>Credential type</span>
                <select
                  value={form.credential_type}
                  disabled={editingId !== null}
                  onChange={(event) =>
                    updateType(event.target.value as CredentialType)
                  }
                >
                  <option value="snmp_v2c">SNMP v2c</option>
                  <option value="routeros_api">RouterOS API</option>
                </select>
              </label>
              {form.credential_type === "routeros_api" && (
                <label className="field">
                  <span>Read-only username *</span>
                  <input
                    required
                    maxLength={120}
                    value={form.username}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        username: event.target.value,
                      }))
                    }
                  />
                </label>
              )}
              <label className="field">
                <span>
                  {form.credential_type === "snmp_v2c"
                    ? editingId === null
                      ? "Read-only community"
                      : "Replace community (optional)"
                    : editingId === null
                      ? "Password"
                      : "Replace password (optional)"}
                  {editingId === null ? " *" : ""}
                </span>
                <input
                  required={editingId === null}
                  type="password"
                  autoComplete="new-password"
                  value={form.secret}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, secret: event.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>Port</span>
                <input
                  required
                  type="number"
                  min={1}
                  max={65535}
                  value={form.port}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, port: event.target.value }))
                  }
                />
              </label>
            </div>
            {form.credential_type === "routeros_api" && (
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={form.verify_tls}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      verify_tls: event.target.checked,
                    }))
                  }
                />
                Verify TLS certificate
              </label>
            )}
            <p className="muted">
              Secrets cannot be read back. Keep the encryption key configured and
              use a dedicated read-only account or community.
            </p>
            <div className="form-actions">
              <button className="button button-primary" disabled={saving}>
                {saving ? "Saving…" : "Save profile"}
              </button>
              <button
                type="button"
                className="button"
                onClick={() => {
                  setFormOpen(false);
                  setError(null);
                }}
              >
                Cancel
              </button>
            </div>
          </fieldset>
        </form>
      )}

      {loading ? (
        <p className="muted">Loading profiles…</p>
      ) : profiles.length === 0 && loadFailed ? (
        <div className="empty-state">
          <h2>Profiles unavailable</h2>
          <p>
            The credential-profile API is not responding. Restart or update the
            backend before creating SNMP or RouterOS profiles.
          </p>
        </div>
      ) : profiles.length === 0 ? (
        <div className="empty-state">
          <h2>No credential profiles</h2>
          <p>
            Create a profile to monitor devices with SNMP or the RouterOS REST
            API. Ping-only devices do not need credentials.
          </p>
          <button
            className="button button-primary"
            disabled={loadFailed}
            onClick={beginCreate}
          >
            Add credential profile
          </button>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="device-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Username</th>
                <th>Port</th>
                <th>Transport</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {profiles.map((profile) => (
                <tr key={profile.id}>
                  <td>{profile.name}</td>
                  <td>{profileTypeLabel(profile.credential_type)}</td>
                  <td>{profile.username ?? "Community string"}</td>
                  <td className="mono">{profile.port}</td>
                  <td>
                    {profile.credential_type === "routeros_api"
                      ? profile.verify_tls
                        ? "HTTPS · verified"
                        : "HTTPS · unverified"
                      : "SNMPv2c"}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button
                        className="link-button"
                        onClick={() => beginEdit(profile)}
                      >
                        Edit
                      </button>
                      <button
                        className="link-button link-danger"
                        onClick={() => void deleteProfile(profile)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default CredentialProfiles;
