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
];

/** Turn a FastAPI error body (or anything else) into a readable message. */
export function errorMessage(error: unknown): string {
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

export function formatCheckType(type: CheckType | undefined): string {
  switch (type) {
    case "ping_only":
      return "Ping only";
    case "snmp":
      return "SNMP";
    case "routeros_api":
      return "RouterOS API";
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
