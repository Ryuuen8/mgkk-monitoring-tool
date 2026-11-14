import { useEffect, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  errorMessage,
  type CollectorV1,
  type CheckType,
  type CredentialProfile,
  type DeviceType,
  type DeviceV1Create,
  type DeviceV1Update,
} from "../api/client";

type Props = {
  deviceId?: string;
  onSaved: (id: string) => void;
  onCancel: () => void;
};

function DeviceFormV1({ deviceId, onSaved, onCancel }: Props) {
  const [siteId, setSiteId] = useState("");
  const [name, setName] = useState("");
  const [ipAddress, setIpAddress] = useState("");
  const [macAddress, setMacAddress] = useState("");
  const [collector, setCollector] = useState<CollectorV1>("generic_snmp");
  const [deviceType, setDeviceType] = useState<DeviceType>("other");
  const [checkType, setCheckType] = useState<CheckType>("ping_only");
  const [credentialProfileId, setCredentialProfileId] = useState("");
  const [vendor, setVendor] = useState("");
  const [model, setModel] = useState("");
  const [osVersion, setOsVersion] = useState("");
  const [parentDeviceId, setParentDeviceId] = useState("");
  const [active, setActive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const sitesQuery = useQuery({
    queryKey: ["v1-sites"],
    queryFn: async () => {
      const response = await api.GET("/api/v1/sites", {
        params: { query: { limit: 200 } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
  });
  const devicesQuery = useQuery({
    queryKey: ["v1-devices-parents"],
    queryFn: async () => {
      const response = await api.GET("/api/v1/devices", {
        params: { query: { limit: 200 } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
  });
  const profilesQuery = useQuery({
    queryKey: ["credential-profiles"],
    queryFn: async () => {
      const response = await api.GET("/api/credential-profiles");
      return response.data;
    },
  });
  const deviceQuery = useQuery({
    queryKey: ["v1-device", deviceId],
    enabled: Boolean(deviceId),
    queryFn: async () => {
      if (!deviceId) throw new Error("Device ID is required");
      const response = await api.GET("/api/v1/devices/{device_id}", {
        params: { path: { device_id: deviceId } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data;
    },
  });

  useEffect(() => {
    const device = deviceQuery.data;
    if (device) {
      setSiteId(String(device.site_id));
      setName(device.name);
      setIpAddress(device.ip_address);
      setMacAddress(device.mac_address ?? "");
      setCollector(device.collector);
      setDeviceType(device.device_type);
      setCheckType(device.check_type);
      setCredentialProfileId(
        device.credential_profile_id == null
          ? ""
          : String(device.credential_profile_id),
      );
      setVendor(device.vendor ?? "");
      setModel(device.model ?? "");
      setOsVersion(device.os_version ?? "");
      setParentDeviceId(device.parent_device_id ?? "");
      setActive(device.active);
    } else if (!deviceId && sitesQuery.data?.length && !siteId) {
      setSiteId(String(sitesQuery.data[0].id));
    }
  }, [deviceId, deviceQuery.data, siteId, sitesQuery.data]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSaving(true);
    const body = {
      site_id: Number(siteId),
      name: name.trim(),
      ip_address: ipAddress.trim(),
      mac_address: macAddress.trim() || null,
      collector,
      device_type: deviceType,
      check_type: checkType,
      credential_profile_id: credentialProfileId
        ? Number(credentialProfileId)
        : null,
      vendor: vendor.trim() || null,
      model: model.trim() || null,
      os_version: osVersion.trim() || null,
      parent_device_id: parentDeviceId || null,
      active,
    };

    try {
      if (deviceId) {
        const response = await api.PATCH("/api/v1/devices/{device_id}", {
          params: { path: { device_id: deviceId } },
          body: body satisfies DeviceV1Update,
        });
        if (response.error) {
          setError(errorMessage(response.error));
          return;
        }
        onSaved(response.data.id);
        return;
      }

      const response = await api.POST("/api/v1/devices", {
        body: body satisfies DeviceV1Create,
      });
      setSaving(false);
      if (response.error) {
        setError(errorMessage(response.error));
        return;
      }
      onSaved(response.data.id);
    } catch (reason: unknown) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  const loading =
    sitesQuery.isPending ||
    devicesQuery.isPending ||
    profilesQuery.isPending ||
    (Boolean(deviceId) && deviceQuery.isPending);
  const availableProfiles = (profilesQuery.data ?? []).filter(
    (profile: CredentialProfile) =>
      checkType === "snmp"
        ? profile.credential_type === "snmp_v2c" ||
          profile.credential_type === "snmp_v3"
        : checkType === "routeros_api"
          ? collector === "mikrotik" &&
            profile.credential_type === "routeros_api"
          : checkType === "restconf"
            ? collector === "cisco" &&
              profile.credential_type === "cisco_restconf"
            : false,
  );

  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        className="device-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="device-form-title"
      >
        <div className="page-heading">
          <div>
            <p className="eyebrow">INVENTORY / DEVICE</p>
            <h1 id="device-form-title">
              {deviceId ? "Edit device" : "Add device"}
            </h1>
          </div>
          <button className="button" type="button" onClick={onCancel}>
            Close
          </button>
        </div>

        {error && <p className="banner banner-error">{error}</p>}
        {loading ? (
          <p className="muted">Loading device data…</p>
        ) : sitesQuery.error ||
          devicesQuery.error ||
          profilesQuery.error ||
          deviceQuery.error ? (
          <p className="banner banner-error">
            {errorMessage(
              sitesQuery.error ??
                devicesQuery.error ??
                profilesQuery.error ??
                deviceQuery.error,
            )}
          </p>
        ) : sitesQuery.data?.length === 0 ? (
          <p className="banner banner-error">
            Create a site before adding a device.
          </p>
        ) : (
          <form className="device-form v1-device-form" onSubmit={submit}>
            <label>
              Device name
              <input
                required
                maxLength={120}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              Site
              <select
                required
                value={siteId}
                onChange={(event) => setSiteId(event.target.value)}
              >
                {sitesQuery.data?.map((site) => (
                  <option value={site.id} key={site.id}>
                    {site.name} ({site.code})
                  </option>
                ))}
              </select>
            </label>
            <label>
              IP address
              <input
                required
                value={ipAddress}
                onChange={(event) => setIpAddress(event.target.value)}
                placeholder="192.0.2.10"
              />
            </label>
            <label>
              MAC address <span className="muted">(optional, unique)</span>
              <input
                value={macAddress}
                onChange={(event) => setMacAddress(event.target.value)}
                placeholder="00:11:22:33:44:55"
              />
            </label>
            <label>
              Collector
              <select
                value={collector}
                onChange={(event) => {
                  const value = event.target.value as CollectorV1;
                  setCollector(value);
                  if (
                    (value !== "mikrotik" && checkType === "routeros_api") ||
                    (value !== "cisco" && checkType === "restconf")
                  ) {
                    setCheckType("ping_only");
                    setCredentialProfileId("");
                  }
                }}
              >
                <option value="generic_snmp">Generic SNMP</option>
                <option value="mikrotik">MikroTik</option>
                <option value="cisco">Cisco</option>
              </select>
            </label>
            <label>
              Device role
              <select
                value={deviceType}
                onChange={(event) =>
                  setDeviceType(event.target.value as DeviceType)
                }
              >
                <option value="router">Router</option>
                <option value="switch">Switch</option>
                <option value="firewall">Firewall</option>
                <option value="server">Server</option>
                <option value="access_point">Access point</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label>
              Check type
              <select
                value={checkType}
                onChange={(event) => {
                  setCheckType(event.target.value as CheckType);
                  setCredentialProfileId("");
                }}
              >
                <option value="ping_only">Ping only</option>
                <option value="snmp">SNMP</option>
                {collector === "mikrotik" && (
                  <option value="routeros_api">RouterOS API</option>
                )}
                {collector === "cisco" && (
                  <option value="restconf">RESTCONF</option>
                )}
              </select>
            </label>
            {checkType !== "ping_only" && (
              <label>
                Credential profile
                <select
                  required
                  value={credentialProfileId}
                  onChange={(event) =>
                    setCredentialProfileId(event.target.value)
                  }
                >
                  <option value="">Select a profile</option>
                  {availableProfiles.map((profile) => (
                    <option value={profile.id} key={profile.id}>
                      {profile.name} ({profile.credential_type})
                    </option>
                  ))}
                </select>
                {availableProfiles.length === 0 && (
                  <span className="muted">
                    Create a matching credential profile first.
                  </span>
                )}
              </label>
            )}
            <label>
              Parent device <span className="muted">(optional)</span>
              <select
                value={parentDeviceId}
                onChange={(event) => setParentDeviceId(event.target.value)}
              >
                <option value="">None</option>
                {devicesQuery.data
                  ?.filter((device) => device.id !== deviceId)
                  .map((device) => (
                    <option value={device.id} key={device.id}>
                      {device.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Vendor <span className="muted">(optional)</span>
              <input
                value={vendor}
                onChange={(event) => setVendor(event.target.value)}
                maxLength={64}
              />
            </label>
            <label>
              Model <span className="muted">(optional)</span>
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                maxLength={120}
              />
            </label>
            <label>
              OS version <span className="muted">(optional)</span>
              <input
                value={osVersion}
                onChange={(event) => setOsVersion(event.target.value)}
                maxLength={64}
              />
            </label>
            <label className="checkbox-field">
              <input
                type="checkbox"
                checked={active}
                onChange={(event) => setActive(event.target.checked)}
              />
              Poll this device
            </label>
            <div className="form-actions">
              <button className="button" type="button" onClick={onCancel}>
                Cancel
              </button>
              <button
                className="button button-primary"
                type="submit"
                disabled={saving || !siteId}
              >
                {saving ? "Saving…" : "Save device"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

export default DeviceFormV1;
