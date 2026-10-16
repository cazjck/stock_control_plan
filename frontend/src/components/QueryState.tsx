import { useState, type ReactNode } from "react";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { ApiError, tokenStore } from "../lib/api";
import { isAppToken, isAuthRequired } from "../lib/hooks";
import { useSelection } from "../lib/selection";
import { Button, Panel, Skeleton, inputCls } from "./ui";
import { OtpForm } from "./OtpForm";

function AppTokenForm() {
  const qc = useQueryClient();
  const [v, setV] = useState("");
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); tokenStore.set(v.trim()); void qc.invalidateQueries(); }}>
      <p className="text-sm text-muted">Máy chủ đang bật bảo vệ truy cập. Nhập mã truy cập (APP_ACCESS_TOKEN trong backend/.env).</p>
      <div className="flex gap-2">
        <input type="password" className={`${inputCls} max-w-xs`} aria-label="Mã truy cập ứng dụng" value={v} onChange={(e) => setV(e.target.value)} />
        <Button type="submit" variant="primary">Vào</Button>
      </div>
    </form>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { sel, brokers } = useSelection();
  const display = brokers.find((b) => b.name === sel.broker)?.display_name;

  if (isAuthRequired(error) && sel.broker) {
    return (
      <Panel className="max-w-xl p-5">
        <h2 className="display text-xl">Cần đăng nhập {display ?? sel.broker}</h2>
        <div className="mt-3"><OtpForm broker={sel.broker} displayName={display} /></div>
      </Panel>
    );
  }
  if (isAppToken(error)) {
    return <Panel className="max-w-xl p-5"><h2 className="display text-xl">Cần mã truy cập</h2><div className="mt-3"><AppTokenForm /></div></Panel>;
  }
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Có lỗi không xác định.";
  const code = error instanceof ApiError ? error.code : "";
  return (
    <Panel className="max-w-xl p-5" as="div">
      <h2 className="display text-xl text-lead">{code === "BROKER_ERROR" ? "Broker trả về lỗi" : code === "NETWORK" ? "Mất kết nối" : "Không tải được dữ liệu"}</h2>
      <p role="alert" className="mt-1 text-sm">{msg}</p>
      {onRetry && <Button className="mt-3" onClick={onRetry}>Thử lại</Button>}
    </Panel>
  );
}

export function QueryState<T>({ query, children, skeleton }: { query: UseQueryResult<T>; children: (data: T) => ReactNode; skeleton?: ReactNode }) {
  if (query.isPending && query.fetchStatus !== "idle") {
    return <>{skeleton ?? <div className="space-y-3"><Skeleton className="h-48" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}</>;
  }
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <Skeleton className="h-48" />;
  return <>{children(query.data)}</>;
}
