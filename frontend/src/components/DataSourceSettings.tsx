import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type DataSourceView } from "../lib/api";
import { cn, fmtTime } from "../lib/format";
import { Panel } from "./ui";

/** Chọn nơi lấy giá và nến cho Sổ danh mục tổng: TCBS hoặc DNSE, có hoặc không dùng nguồn còn lại làm dự phòng. */
export function DataSourceSettings() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["data-source"], queryFn: api.dataSource, refetchInterval: 60_000 });
  const save = useMutation({
    mutationFn: api.setDataSource,
    onSuccess: (d) => { qc.setQueryData(["data-source"], d); void qc.invalidateQueries(); },
  });
  const d = q.data;
  const set = (patch: Partial<Pick<DataSourceView, "primary" | "fallback">>) =>
    d && save.mutate({ primary: patch.primary ?? d.primary, fallback: patch.fallback ?? d.fallback });

  return (
    <section aria-labelledby="ds" className="space-y-3">
      <h2 id="ds" className="display text-2xl">Nguồn dữ liệu giá</h2>
      <p className="max-w-2xl text-sm text-muted">
        Giá hiện tại, nến ngày và VN-Index của Sổ danh mục tổng lấy từ đâu. Tỷ lệ ký quỹ, giá gọi ký quỹ, kế hoạch kỹ thuật,
        cảnh báo và bản tin đều tính theo nguồn này. Khi xem trực tiếp một công ty ở thanh chọn phía trên, giá lấy từ chính công ty đó.
      </p>
      {!d ? <p className="text-sm text-muted">{q.isError ? "Không tải được." : "Đang tải…"}</p> : (
        <Panel className="space-y-4 p-4" as="div">
          <p className={cn("rounded-md px-3 py-2 text-sm", d.active ? "bg-ok-soft text-ok" : "bg-lead-soft text-lead")}>
            {d.active
              ? <>Đang lấy giá từ <span className="font-semibold">{d.active_label}</span>
                {d.active !== d.primary ? " (nguồn chính chưa dùng được nên đang dùng dự phòng)" : ""}.</>
              : "Không có nguồn giá nào dùng được. App đang dùng giá đã lưu trong sổ, tỷ lệ ký quỹ có thể sai."}
          </p>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Nguồn chính</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {d.sources.map((s) => {
                const on = d.primary === s.name;
                return (
                  <label key={s.name} className={cn("flex cursor-pointer gap-3 rounded-md border p-3", on ? "border-ink" : "border-line", !s.enabled && "opacity-60")}>
                    <input type="radio" name="primary" className="mt-1" checked={on} disabled={!s.enabled || save.isPending}
                      onChange={() => set({ primary: s.name })} />
                    <span className="min-w-0 text-sm">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{s.label}</span>
                        <span className={cn("rounded px-1.5 text-[11px] font-medium", s.available ? "bg-ok-soft text-ok" : "bg-amber-soft text-amber")}>
                          {!s.enabled ? "chưa bật" : s.available ? (s.expires_at ? `dùng được tới ${fmtTime(s.expires_at)}` : "dùng được") : "chưa dùng được"}
                        </span>
                      </span>
                      <span className="mt-1 block text-muted">{s.note}</span>
                      {!s.available && s.message && <span className="mt-1 block text-xs text-amber">{s.message}</span>}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
          <label className="flex min-h-10 items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={d.fallback} disabled={save.isPending} onChange={(e) => set({ fallback: e.target.checked })} />
            <span>Khi nguồn chính không dùng được (ví dụ phiên TCBS hết hạn), tự lấy giá từ nguồn còn lại
              <span className="block text-xs text-muted">Nên bật. Tắt thì lúc nguồn chính hỏng app chỉ còn giá đã lưu.</span></span>
          </label>
          {save.isError && <p role="alert" className="text-sm text-lead">{save.error instanceof ApiError ? save.error.message : "Không lưu được."}</p>}
        </Panel>
      )}
    </section>
  );
}
