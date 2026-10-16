import { useState } from "react";
import { AlertItem } from "../components/AlertItem";
import { QueryState } from "../components/QueryState";
import { Empty } from "../components/ui";
import { cn } from "../lib/format";
import { useAlerts } from "../lib/hooks";

export default function Alerts() {
  const [tab, setTab] = useState<"active" | "all">("active");
  const q = useAlerts(tab);
  return (
    <>
      <h1 className="display mb-4 text-3xl">Cảnh báo</h1>
      <div role="tablist" aria-label="Lọc cảnh báo" className="mb-4 flex gap-2">
        {([["active", "Đang mở"], ["all", "Toàn bộ lịch sử"]] as const).map(([v, l]) => (
          <button key={v} role="tab" type="button" aria-selected={tab === v} onClick={() => setTab(v)}
            className={cn("min-h-10 rounded-md border px-3.5 text-sm font-medium", tab === v ? "border-ink bg-ink text-paper" : "border-line bg-panel")}>{l}</button>
        ))}
      </div>
      <QueryState query={q}>
        {(list) => list.length === 0 ? (
          <Empty title={tab === "active" ? "Không có cảnh báo nào đang mở" : "Chưa có cảnh báo nào"}>
            Cảnh báo xuất hiện khi một mã chạm cắt lỗ, tỷ lệ ký quỹ gần ngưỡng, khoản vay sắp đáo hạn hoặc lỗ danh mục vượt ngưỡng bạn đặt.
          </Empty>
        ) : (
          <div className="max-w-3xl space-y-2.5">{list.map((a) => <AlertItem key={a.id} alert={a} manage />)}</div>
        )}
      </QueryState>
    </>
  );
}
