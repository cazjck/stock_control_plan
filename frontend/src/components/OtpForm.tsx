import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { Button, inputCls } from "./ui";

/** Nhập iOTP để lấy token phiên của broker (TCBS). Đây là đăng nhập, không liên quan tới đặt lệnh. */
export function OtpForm({ broker, displayName, compact = false }: { broker: string; displayName?: string; compact?: boolean }) {
  const qc = useQueryClient();
  const [otp, setOtp] = useState("");
  const m = useMutation({
    mutationFn: () => api.auth(broker, otp),
    onSuccess: () => { setOtp(""); void qc.invalidateQueries(); },
  });
  const appName = broker === "tcbs" ? "TCInvest" : displayName ?? broker.toUpperCase();
  const submit = (e: FormEvent) => { e.preventDefault(); if (otp.trim().length >= 4) m.mutate(); };

  return (
    <form onSubmit={submit} className="space-y-3">
      {!compact && (
        <p className="text-sm text-muted">
          Mở app {appName}, lấy mã iOTP rồi nhập vào đây. Token phiên có hiệu lực tối đa 8 giờ,
          nên mỗi sáng chỉ cần nhập một lần.
        </p>
      )}
      <div className="flex gap-2">
        <input
          className={`${inputCls} num max-w-44 tracking-[0.3em]`} inputMode="numeric" autoComplete="one-time-code"
          aria-label={`Mã iOTP của ${broker}`} placeholder="••••••" value={otp} maxLength={8}
          onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
        />
        <Button type="submit" variant="primary" disabled={m.isPending || otp.length < 4}>
          <KeyRound size={16} aria-hidden /> {m.isPending ? "Đang lấy token…" : "Lấy token phiên"}
        </Button>
      </div>
      {m.error && (
        <p role="alert" className="text-sm text-lead">
          {m.error instanceof ApiError ? m.error.message : "Không lấy được token. Thử lại với mã iOTP mới."}
        </p>
      )}
    </form>
  );
}
