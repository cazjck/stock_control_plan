import { fmtMoney, fmtPct } from "./format";
import type { MarginMetrics, Tone } from "./types";

export interface Verdict {
  tone: Tone;
  headline: string;
  detail: string;
}

/** Câu kết luận bằng lời cho một nhóm ký quỹ, viết từ góc nhìn của người dùng. */
export function verdictFor(m: MarginMetrics | undefined): Verdict {
  const b = m?.bucket;
  if (!m || !b || b.ratio_pct == null || b.maintenance_pct == null) {
    return { tone: "unknown", headline: "Chưa có dữ liệu ký quỹ", detail: "Tài khoản này không có nợ margin, hoặc broker chưa trả về tỷ lệ ký quỹ." };
  }
  const cash = m.cash_to_safe ?? 0;
  const target = m.safe_target_pct != null ? fmtPct(m.safe_target_pct, 0) : "";
  // TCBS: RTT = tài sản đảm bảo / (dư nợ − tiền mặt), nên tiền nộp vào được trừ thẳng vào dư nợ
  const tcbs = b.ratio_kind === "collateral_over_debt";
  const how = tcbs ? "Cần nộp thêm (tiền mặt được trừ thẳng vào dư nợ khi tính RTT) khoảng" : "Cần nộp khoảng";
  const need = cash > 0 ? `${how} ${fmtMoney(cash)} để về vùng an toàn (RTT từ ${target}).` : "Đang ở vùng an toàn.";

  switch (m.zone) {
    case "breach":
      return {
        tone: "breach",
        headline: "Đã chạm ngưỡng giải chấp",
        detail: tcbs
          ? `RTT ${fmtPct(b.ratio_pct)} thấp hơn tỷ lệ xử lý tài sản ${fmtPct(b.liquidation_pct)}. Theo chính sách TCBS, cổ phiếu bị bán xử lý vào ngày làm việc kế tiếp. ${need}`
          : `RTT ${fmtPct(b.ratio_pct)} thấp hơn ngưỡng giải chấp ${fmtPct(b.liquidation_pct)}. Công ty chứng khoán có thể bán giải chấp bất cứ lúc nào. ${need}`,
      };
    case "danger":
      return {
        tone: "danger",
        headline: "Đã dưới ngưỡng duy trì",
        detail: tcbs
          ? `RTT ${fmtPct(b.ratio_pct)} thấp hơn ngưỡng duy trì ${fmtPct(b.maintenance_pct)}. Theo chính sách TCBS, nếu RTT dưới ngưỡng này 3 ngày làm việc liên tiếp thì cổ phiếu bị bán vào ngày làm việc thứ 3 kể từ thông báo gọi ký quỹ đầu tiên. ${need}`
          : `RTT ${fmtPct(b.ratio_pct)} thấp hơn ngưỡng duy trì ${fmtPct(b.maintenance_pct)}. Nộp tiền hoặc bán bớt ngay. ${need}`,
      };
    case "watch":
      return {
        tone: "watch",
        headline: `Giảm thêm ${fmtPct(m.drop_to_maintenance_pct)} là bị gọi ký quỹ`,
        detail: `RTT ${fmtPct(b.ratio_pct)}, ngưỡng duy trì ${fmtPct(b.maintenance_pct)}. ${need}`,
      };
    default:
      return {
        tone: "safe",
        headline: `Còn biên ${fmtPct(m.drop_to_maintenance_pct)} trước khi bị gọi ký quỹ`,
        detail: `RTT ${fmtPct(b.ratio_pct)}, ngưỡng duy trì ${fmtPct(b.maintenance_pct)}. Nên giữ RTT trên ${target}.`,
      };
  }
}

/** Nhóm rủi ro nhất: ưu tiên vùng nguy hiểm, rồi khoảng cách tới ngưỡng duy trì nhỏ nhất. */
export function worstBucket(list: MarginMetrics[]): MarginMetrics | undefined {
  const rank: Record<string, number> = { breach: 0, danger: 1, watch: 2, safe: 3, unknown: 4 };
  return [...list].sort((a, b) =>
    rank[a.zone] - rank[b.zone] ||
    (a.drop_to_maintenance_pct ?? Infinity) - (b.drop_to_maintenance_pct ?? Infinity))[0];
}
