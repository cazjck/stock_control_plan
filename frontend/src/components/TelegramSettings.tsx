import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Severity, type TelegramStatus } from "../lib/api";
import { cn, fmtTime } from "../lib/format";
import { Button, Field, Panel, inputCls } from "./ui";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Không thực hiện được. Thử lại.");
const LEVELS: [Severity, string][] = [["critical", "Chỉ cảnh báo khẩn"], ["warning", "Khẩn và cần chú ý"], ["info", "Tất cả, kể cả chốt lời"]];

function Status({ s }: { s: TelegramStatus }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
      <dt className="text-muted">Trạng thái</dt>
      <dd className={cn("font-medium", s.configured && s.enabled ? "text-ok" : "text-muted")}>
        {s.configured ? (s.enabled ? "Đang gửi" : "Đã tắt") : "Chưa cài"}
      </dd>
      {s.token_masked && <><dt className="text-muted">Bot</dt><dd className="num">{s.token_masked}</dd></>}
      {s.chat_id != null && <><dt className="text-muted">Gửi tới</dt><dd>{s.chat_title || s.chat_id}</dd></>}
      <dt className="text-muted">Lần gửi gần nhất</dt><dd className="num">{s.last_sent_at ? fmtTime(s.last_sent_at) : "—"}</dd>
      <dt className="text-muted">Lần kiểm tra gần nhất</dt><dd className="num">{s.last_run_at ? fmtTime(s.last_run_at) : "—"}</dd>
      {s.last_error && <><dt className="text-muted">Lỗi gần nhất</dt><dd className="text-lead">{s.last_error}</dd></>}
    </dl>
  );
}

/** Bản tin đầu phiên (8:45) và cuối phiên (15:20), cùng các lệnh nhắn cho bot. */
function Briefs({ s }: { s: TelegramStatus }) {
  const qc = useQueryClient();
  const [kind, setKind] = useState<"open" | "close" | "now">("open");
  const preview = useMutation({ mutationFn: () => api.notifyBrief(kind) });
  const send = useMutation({ mutationFn: () => api.notifySendBrief(kind), onSuccess: () => void qc.invalidateQueries({ queryKey: ["notify"] }) });
  const toggle = useMutation({ mutationFn: (brief: boolean) => api.notifySave({ brief }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["notify"] }) });
  return (
    <Panel className="space-y-3 p-4" as="div">
      <h3 className="display text-lg">Bản tin và lệnh</h3>
      <label className="flex min-h-10 items-center gap-2 text-sm">
        <input type="checkbox" checked={s.brief} onChange={(e) => toggle.mutate(e.target.checked)} />
        Gửi bản tin đầu phiên lúc 8:45 và cuối phiên lúc 15:20 các ngày thường
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Loại bản tin" className={cn(inputCls, "max-w-48")} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="open">Đầu phiên</option><option value="close">Cuối phiên</option><option value="now">Tình trạng hiện tại</option>
        </select>
        <Button type="button" onClick={() => preview.mutate()} disabled={preview.isPending}>{preview.isPending ? "Đang soạn…" : "Xem trước"}</Button>
        <Button type="button" onClick={() => send.mutate()} disabled={send.isPending}>Gửi vào Telegram</Button>
      </div>
      {send.isSuccess && <p className="text-sm text-ok">Đã gửi bản tin.</p>}
      {(preview.isError || send.isError) && <p role="alert" className="text-sm text-lead">{errText(preview.error || send.error)}</p>}
      {preview.data && <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-sea-soft/40 p-3 text-sm">{preview.data.text}</pre>}
      <div className="text-sm">
        <p className="font-medium">Nhắn cho bot:</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted">
          <li><span className="num text-ink">/tinhtrang</span>: ký quỹ, giá gọi ký quỹ, việc cần làm</li>
          <li><span className="num text-ink">/kiemtra PDR 2000</span>: bảng kiểm trước khi mua; thêm giá và nguồn nếu cần, ví dụ <span className="num text-ink">/kiemtra DXG 1000 10200 ssi</span></li>
        </ul>
        <p className="mt-1 text-xs text-muted">Bot chỉ trả lời cuộc trò chuyện đã chọn ở trên. Bot không đặt lệnh.</p>
      </div>
    </Panel>
  );
}

/** Cài thông báo Telegram: tạo bot bằng BotFather, nhắn /start, dán mã bot, chọn cuộc trò chuyện, gửi thử. */
export function TelegramSettings() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["notify"], queryFn: api.notifyStatus, retry: false });
  const s = q.data;
  const [token, setToken] = useState("");
  const [chats, setChats] = useState<{ id: number; title: string; type: string }[] | null>(null);
  const [bot, setBot] = useState<string | null>(null);
  const [chat, setChat] = useState<string>("");
  const [level, setLevel] = useState<Severity | "">("");
  const [url, setUrl] = useState("");
  const done = () => void qc.invalidateQueries({ queryKey: ["notify"] });

  const discover = useMutation({
    mutationFn: () => api.notifyDiscover(token.trim() || undefined),
    onSuccess: (r) => { setBot(r.bot); setChats(r.chats); if (r.chats.length === 1) setChat(String(r.chats[0].id)); },
  });
  const save = useMutation({
    mutationFn: () => {
      const c = chats?.find((x) => String(x.id) === chat);
      return api.notifySave({
        ...(token.trim() ? { token: token.trim() } : {}),
        ...(c ? { chat_id: c.id, chat_title: c.title } : {}),
        enabled: true,
        min_severity: (level || s?.min_severity || "warning") as Severity,
        app_url: (url || s?.app_url || window.location.origin).trim(),
      });
    },
    onSuccess: () => { setToken(""); done(); },
  });
  const toggle = useMutation({ mutationFn: (enabled: boolean) => api.notifySave({ enabled }), onSuccess: done });
  const test = useMutation({ mutationFn: api.notifyTest, onSuccess: done });
  const run = useMutation({ mutationFn: api.notifyRun, onSuccess: done });

  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const canSave = (!!token.trim() || !!s?.token_masked) && (!!chat || s?.chat_id != null);

  return (
    <section aria-labelledby="tg" className="space-y-3">
      <h2 id="tg" className="display text-2xl">Thông báo Telegram</h2>
      <p className="max-w-2xl text-sm text-muted">
        Gửi cảnh báo mới vào Telegram của bạn: tỷ lệ ký quỹ sát ngưỡng, lô phải bán, giá tới vùng bán, thủng mức vô hiệu, phiên TCBS hết hạn.
        App kiểm tra 5 phút một lần trong giờ giao dịch và một lượt trước, sau phiên. Mỗi cảnh báo chỉ gửi một lần, nặng lên thì gửi lại.
      </p>
      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Panel className="p-4" as="div">
          <form onSubmit={submit} className="space-y-4">
            <ol className="list-decimal space-y-1 pl-5 text-sm">
              <li>Trong Telegram, mở <span className="font-medium">@BotFather</span>, gửi <span className="num">/newbot</span>, đặt tên. BotFather trả về mã bot.</li>
              <li>Mở bot vừa tạo và bấm <span className="font-medium">Start</span>.</li>
              <li>Dán mã bot vào đây, bấm Tìm cuộc trò chuyện, chọn tên của bạn, rồi Lưu.</li>
            </ol>
            <Field label="Mã bot" hint={s?.token_masked ? `Đang dùng ${s.token_masked}. Để trống nếu giữ nguyên.` : "Dạng 123456789:AA…, chỉ lưu trên máy chủ của bạn."}>
              <div className="flex flex-wrap gap-2">
                <input type="password" autoComplete="off" className={cn(inputCls, "max-w-sm")} value={token} onChange={(e) => setToken(e.target.value)} />
                <Button type="button" onClick={() => discover.mutate()} disabled={discover.isPending || (!token.trim() && !s?.token_masked)}>
                  {discover.isPending ? "Đang tìm…" : "Tìm cuộc trò chuyện"}
                </Button>
              </div>
            </Field>
            {discover.isError && <p role="alert" className="text-sm text-lead">{errText(discover.error)}</p>}
            {chats && (
              <fieldset className="space-y-1">
                <legend className="mb-1 text-sm font-medium">Gửi tới{bot ? ` (bot @${bot})` : ""}</legend>
                {chats.length === 0 && <p className="text-sm text-amber">Chưa thấy ai nhắn cho bot. Mở bot, bấm Start rồi tìm lại.</p>}
                {chats.map((c) => (
                  <label key={c.id} className="flex min-h-10 items-center gap-2 text-sm">
                    <input type="radio" name="chat" value={c.id} checked={chat === String(c.id)} onChange={() => setChat(String(c.id))} />
                    {c.title} <span className="text-xs text-muted">{c.type}</span>
                  </label>
                ))}
              </fieldset>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Gửi những cảnh báo">
                <select className={inputCls} value={level || s?.min_severity || "warning"} onChange={(e) => setLevel(e.target.value as Severity)}>
                  {LEVELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </Field>
              <Field label="Địa chỉ app trong tin nhắn" hint="Để mở nhanh trang Cảnh báo từ Telegram.">
                <input className={inputCls} value={url || s?.app_url || ""} placeholder={window.location.origin} onChange={(e) => setUrl(e.target.value)} />
              </Field>
            </div>
            {save.isError && <p role="alert" className="text-sm text-lead">{errText(save.error)}</p>}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="primary" disabled={!canSave || save.isPending}>Lưu và bật</Button>
              {s?.configured && <Button type="button" onClick={() => test.mutate()} disabled={test.isPending}>Gửi tin thử</Button>}
              {s?.configured && <Button type="button" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Đang kiểm tra…" : "Kiểm tra ngay"}</Button>}
              {s?.configured && <Button type="button" onClick={() => toggle.mutate(!s.enabled)}>{s.enabled ? "Tắt thông báo" : "Bật lại"}</Button>}
            </div>
            {test.isSuccess && <p className="text-sm text-ok">Đã gửi tin thử. Mở Telegram để xem.</p>}
            {test.isError && <p role="alert" className="text-sm text-lead">{errText(test.error)}</p>}
            {run.isSuccess && <p className="text-sm text-ok">Đã kiểm tra: gửi {run.data.sent} cảnh báo mới.</p>}
          </form>
        </Panel>
        <Panel className="p-4" as="div">{s ? <Status s={s} /> : <p className="text-sm text-muted">Đang tải…</p>}</Panel>
      </div>
      {s?.configured && <Briefs s={s} />}
    </section>
  );
}
