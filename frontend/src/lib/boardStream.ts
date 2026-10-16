import { useEffect, useState } from "react";
import { tokenStore } from "./api";
import { useSelection } from "./selection";
import type { BoardResponse, BoardRow } from "./types";

export type LiveMode = "connecting" | "live" | "polling" | "auth" | "error";

export interface LiveBoard {
  data?: BoardResponse;
  mode: LiveMode;
  message?: string | null;
  lastTick?: number;
}

/** Gộp một cập nhật giá vào dòng bảng giá, giữ các cột của bạn và tính lại lãi lỗ theo giá mới. */
export function mergeRow(row: BoardRow, q: Partial<BoardRow>): BoardRow {
  const next = { ...row, ...q, held_qty: row.held_qty, avg_cost: row.avg_cost, sources: row.sources } as BoardRow;
  const p = next.price ?? row.price;
  next.pnl_pct = p && row.avg_cost ? (p / row.avg_cost - 1) * 100 : row.pnl_pct;
  return next;
}

/** Bảng giá thời gian thực qua Server-Sent Events. Lỗi thì trả mode "polling" để trang dùng cách làm mới định kỳ. */
export function useBoardLive(): LiveBoard {
  const { sel, ready } = useSelection();
  const [st, setSt] = useState<LiveBoard>({ mode: "connecting" });

  useEffect(() => {
    if (!ready || !sel.broker || typeof EventSource === "undefined") {
      setSt({ mode: "polling" });
      return;
    }
    const p = new URLSearchParams({ broker: sel.broker });
    if (sel.account) p.set("account", sel.account);
    const t = tokenStore.get();
    if (t) p.set("app_token", t);
    setSt({ mode: "connecting" });
    const es = new EventSource(`/api/board/stream?${p.toString()}`);

    es.addEventListener("snapshot", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as BoardResponse & { live: boolean; status: string };
      setSt((s) => ({ ...s, data: d, mode: d.live ? (d.status === "live" ? "live" : "connecting") : "polling" }));
      if (!d.live) es.close();
    });
    es.addEventListener("quote", (e) => {
      const { row } = JSON.parse((e as MessageEvent).data) as { row: Partial<BoardRow> & { symbol: string } };
      setSt((s) => s.data ? {
        ...s, lastTick: Date.now(),
        data: { ...s.data, rows: s.data.rows.map((r) => (r.symbol === row.symbol ? mergeRow(r, row) : r)) },
      } : s);
    });
    es.addEventListener("index", (e) => {
      const { index } = JSON.parse((e as MessageEvent).data);
      setSt((s) => s.data && (!s.data.index || s.data.index.symbol === index.symbol)
        ? { ...s, data: { ...s.data, index } } : s);
    });
    es.addEventListener("status", (e) => {
      const { status, message } = JSON.parse((e as MessageEvent).data) as { status: string; message: string | null };
      const mode: LiveMode = status === "live" ? "live" : status === "auth" ? "auth" : status === "error" ? "error" : "connecting";
      setSt((s) => ({ ...s, mode, message }));
    });
    es.onerror = () => setSt((s) => ({ ...s, mode: s.mode === "auth" ? "auth" : "polling" }));
    return () => es.close();
  }, [ready, sel.broker, sel.account]);

  return st;
}
