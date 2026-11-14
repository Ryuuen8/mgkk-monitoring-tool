import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

/** Typed client generated from the FastAPI OpenAPI document. */
export const api = createClient<paths>({ baseUrl: "" });

export type DeviceDetail = components["schemas"]["DeviceDetail"];
export type DeviceRead = components["schemas"]["DeviceRead"];
export type DeviceStatus = components["schemas"]["DeviceStatusRead"];
export type DeviceMetrics = components["schemas"]["DeviceMetrics"];
export type DeviceType = components["schemas"]["DeviceType"];
export type CheckType = components["schemas"]["DeviceCheckType"];
export type CollectorType = components["schemas"]["CollectorType"];
export type CredentialType = components["schemas"]["CredentialType"];
export type CredentialProfile =
  components["schemas"]["CredentialProfileRead"];
export type SnmpAuthProtocol = components["schemas"]["SnmpAuthProtocol"];
export type SnmpPrivacyProtocol = components["schemas"]["SnmpPrivacyProtocol"];
export type DeviceCreate = components["schemas"]["DeviceCreate"];
export type DeviceUpdate = components["schemas"]["DeviceUpdate"];
export type Site = components["schemas"]["SiteRead"];
export type DeviceGroup = components["schemas"]["DeviceGroupRead"];
export type MetricPoint = components["schemas"]["MetricPoint"];
export type DeviceV1 = components["schemas"]["DeviceV1Read"];
export type DeviceV1Create = components["schemas"]["DeviceV1Create"];
export type DeviceV1Update = components["schemas"]["DeviceV1Update"];
export type DeviceV1Status = components["schemas"]["DeviceV1Status"];
export type DeviceMetricSeries = components["schemas"]["DeviceMetricSeries"];
export type CollectorV1 = components["schemas"]["DeviceV1Read"]["collector"];
export type InterfaceMetrics = components["schemas"]["InterfaceMetrics"];
export type NetworkInterface = components["schemas"]["NetworkInterfaceRead"];

export const DEVICE_TYPES: DeviceType[] = [
  "router",
  "switch",
  "firewall",
  "server",
  "access_point",
  "other",
];

export const CHECK_TYPES: CheckType[] = [
  "ping_only",
  "snmp",
  "routeros_api",
  "restconf",
];

/** Turn a FastAPI error body (or anything else) into a readable message. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && error !== null && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === "object" && item !== null && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return String(item);
        })
        .join("; ");
    }
  }
  return "Request failed. Check that the API is running.";
}

export function formatDeviceType(type: DeviceType): string {
  return type === "access_point"
    ? "Access point"
    : type.charAt(0).toUpperCase() + type.slice(1);
}

export function formatCollector(type: string): string {
  switch (type) {
    case "generic_snmp":
      return "Generic SNMP";
    case "mikrotik":
      return "MikroTik";
    case "cisco":
      return "Cisco";
    default:
      return type;
  }
}

export function formatCheckType(type: CheckType | undefined): string {
  switch (type) {
    case "ping_only":
      return "Ping only";
    case "snmp":
      return "SNMP";
    case "routeros_api":
      return "RouterOS API";
    case "restconf":
      return "RESTCONF";
    default:
      return "Ping only";
  }
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

export function formatLatency(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(1)} ms`;
}

export function formatLoss(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(0)}%`;
}
