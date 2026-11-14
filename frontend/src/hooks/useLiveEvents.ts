import { useEffect, useRef } from "react";

export type LiveEvent = {
  type: string;
  timestamp?: string;
  device?: string | null;
  device_id?: string | null;
  site?: string | null;
  up?: boolean;
  latency_ms?: number | null;
  packet_loss_percent?: number | null;
  interface?: string;
  admin_status?: number | null;
  oper_status?: number | null;
  severity?: number | string;
  event_type?: string;
  alertname?: string;
  summary?: string | null;
  message?: string;
  source_ip?: string;
  status?: string;
};

type Handler = (event: LiveEvent) => void;

const TOKEN = import.meta.env.VITE_WS_AUTH_TOKEN as string | undefined;

function eventUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const query = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "";
  return `${protocol}://${window.location.host}/api/v1/ws/events${query}`;
}

/** Subscribe to `/api/v1/ws/events` with reconnect and a stable callback. */
export function useLiveEvents(handler: Handler): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      socket = new WebSocket(eventUrl());
      socket.onopen = () => {
        attempt = 0;
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data as string) as LiveEvent;
          if (event.type !== "heartbeat") handlerRef.current(event);
        } catch {
          // Ignore malformed frames; the next event will still arrive.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        attempt += 1;
        retry = window.setTimeout(
          connect,
          Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5)),
        );
      };
    };

    connect();
    return () => {
      closed = true;
      if (retry !== undefined) window.clearTimeout(retry);
      socket?.close();
    };
  }, []);
}
