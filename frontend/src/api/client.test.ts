import { describe, expect, it } from "vitest";
import {
  errorMessage,
  formatCollector,
  formatLatency,
  formatLoss,
  formatOsFamily,
} from "./client";

describe("formatOsFamily", () => {
  it("maps vendor OS families", () => {
    expect(formatOsFamily("routeros")).toBe("RouterOS");
    expect(formatOsFamily("iosxe")).toBe("Cisco IOS-XE");
    expect(formatOsFamily("nxos")).toBe("Cisco NX-OS");
    expect(formatOsFamily("linux")).toBe("Linux");
  });

  it("handles a missing family", () => {
    expect(formatOsFamily(null)).toBe("Not recorded");
    expect(formatOsFamily(undefined)).toBe("Not recorded");
  });
});

describe("formatLatency", () => {
  it("formats milliseconds to one decimal", () => {
    expect(formatLatency(12.345)).toBe("12.3 ms");
    expect(formatLatency(0)).toBe("0.0 ms");
  });

  it("shows a dash when latency is unknown", () => {
    expect(formatLatency(null)).toBe("—");
    expect(formatLatency(undefined)).toBe("—");
  });
});

describe("formatLoss", () => {
  it("formats a fraction as a percentage", () => {
    expect(formatLoss(0)).toBe("0%");
    expect(formatLoss(0.25)).toBe("25%");
  });

  it("shows a dash when loss is unknown", () => {
    expect(formatLoss(null)).toBe("—");
  });
});

describe("formatCollector", () => {
  it("labels the supported collectors", () => {
    expect(formatCollector("generic_snmp")).toBe("Generic SNMP");
    expect(formatCollector("mikrotik")).toBe("MikroTik");
    expect(formatCollector("cisco")).toBe("Cisco");
  });

  it("passes unknown values through", () => {
    expect(formatCollector("snmp")).toBe("snmp");
  });
});

describe("errorMessage", () => {
  it("returns Error messages", () => {
    expect(errorMessage(new Error("boom"))).toBe("boom");
  });

  it("reads a FastAPI string detail", () => {
    expect(errorMessage({ detail: "site not found" })).toBe("site not found");
  });

  it("joins validation details", () => {
    expect(
      errorMessage({
        detail: [{ msg: "field required" }, { msg: "bad type" }],
      }),
    ).toBe("field required; bad type");
  });

  it("falls back for unknown values", () => {
    expect(errorMessage({})).toBe(
      "Request failed. Check that the API is running.",
    );
    expect(errorMessage("nope")).toBe(
      "Request failed. Check that the API is running.",
    );
  });
});
