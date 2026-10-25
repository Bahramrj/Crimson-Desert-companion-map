// /cdlm/ws with automatic reconnect (exponential backoff, 0.5 s .. 10 s).
import type { Realm } from "./coord";

export interface PositionMsg {
  type: "position";
  x: number; y: number; z: number;
  realm: Realm;
  heading?: number;
  ts?: number | null;
}
export interface StatusMsg { type: "status"; status: string; message: string }
export interface ProfileChangedMsg { type: "profile_changed"; id: string | null; action: string }
export interface MapChangedMsg { type: "map_changed"; id: string | null; action: string }
export interface MarkersChangedMsg { type: "markers_changed" }
export interface ProgressChangedMsg { type: "progress_changed"; key: string; found: boolean }
export type ServerMsg = PositionMsg | StatusMsg | ProfileChangedMsg | MapChangedMsg | MarkersChangedMsg | ProgressChangedMsg;

export interface LiveHandlers {
  open(): void;
  close(): void;
  message(msg: ServerMsg): void;
}

export class Live {
  private ws: WebSocket | null = null;
  private backoff = 500;
  private stopped = false;

  constructor(private url: string, private on: LiveHandlers) {}

  start() {
    this.stopped = false;
    this.connect();
  }

  private connect() {
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => { this.backoff = 500; this.on.open(); };
    ws.onmessage = (e) => {
      try { this.on.message(JSON.parse(e.data as string) as ServerMsg); } catch { /* ignore malformed */ }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.on.close();
      if (!this.stopped) {
        setTimeout(() => this.connect(), this.backoff);
        this.backoff = Math.min(this.backoff * 2, 10000);
      }
    };
  }

  /** Reconnect now (e.g. when the device wakes up) instead of waiting for the backoff. */
  kick() {
    if (!this.ws && !this.stopped) { this.backoff = 500; this.connect(); }
  }
}
