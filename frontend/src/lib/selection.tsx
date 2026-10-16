import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Sel } from "./api";
import type { BrokerStatus } from "./types";

interface Ctx {
  sel: Sel;
  brokers: BrokerStatus[];
  ready: boolean;
  error: unknown;
  setBroker: (b: string) => void;
  setAccount: (a: string | undefined) => void;
}

const SelectionCtx = createContext<Ctx | null>(null);
const KEY = "stockctl.selection";

function load(): Sel {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "{}") as Sel; } catch { return {}; }
}

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState<Sel>(load);
  const q = useQuery({ queryKey: ["brokers"], queryFn: api.brokers, staleTime: 15_000 });
  const brokers = q.data ?? [];

  const broker = useMemo(() => {
    if (!brokers.length) return stored.broker;
    return brokers.some((b) => b.name === stored.broker) ? stored.broker : brokers[0].name;
  }, [brokers, stored.broker]);

  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify({ broker, account: stored.account })); } catch { /* bỏ qua */ }
  }, [broker, stored.account]);

  const value: Ctx = {
    sel: { broker, account: stored.account },
    brokers,
    ready: q.isSuccess,
    error: q.error,
    setBroker: (b) => setStored({ broker: b, account: undefined }),
    setAccount: (a) => setStored((s) => ({ ...s, account: a })),
  };
  return <SelectionCtx.Provider value={value}>{children}</SelectionCtx.Provider>;
}

export function useSelection(): Ctx {
  const c = useContext(SelectionCtx);
  if (!c) throw new Error("useSelection ngoài SelectionProvider");
  return c;
}
