import { useEffect, useRef } from "react";
import {
  ColorType, CandlestickSeries, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart,
  type Time,
} from "lightweight-charts";
import { fmtInt } from "../lib/format";
import { cssVar, useThemeKey } from "../lib/theme";
import type { ChartResponse, SeriesPoint } from "../lib/types";

const t = (p: SeriesPoint) => ({ time: p.time as Time, value: p.value });

/** Biểu đồ nến + SMA/EMA + đường giá vốn + mức cắt lỗ; dưới là RSI và MACD. Màu lấy từ token thiết kế. */
export interface ChartLevel { price: number; title: string; kind: "sell" | "invalid" }

export function ChartPanel({ data, height = 640, levels = [] }: { data: ChartResponse; height?: number; levels?: ChartLevel[] }) {
  const levelKey = levels.map((l) => `${l.kind}:${Math.round(l.price)}:${l.title}`).join("|");
  const ref = useRef<HTMLDivElement>(null);
  const themeKey = useThemeKey();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const c = {
      ink: cssVar("--ink"), muted: cssVar("--muted"), line: cssVar("--line"), sea: cssVar("--sea"),
      lead: cssVar("--lead"), ok: cssVar("--ok"), amber: cssVar("--amber-fill"), panel: cssVar("--panel"),
    };
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" }, textColor: c.muted,
        fontFamily: cssVar("--font-mono"), fontSize: 11, panes: { separatorColor: c.line, enableResize: false },
      },
      grid: { vertLines: { color: "transparent" }, horzLines: { color: c.line } },
      rightPriceScale: { borderColor: c.line },
      timeScale: { borderColor: c.line, timeVisible: false, rightOffset: 4 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { locale: "vi-VN", priceFormatter: (p: number) => fmtInt(p) },
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: c.ok, downColor: c.lead, wickUpColor: c.ok, wickDownColor: c.lead, borderVisible: false, priceLineVisible: false,
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    }, 0);
    candles.setData(data.candles.map((k) => ({ time: k.time as Time, open: k.open, high: k.high, low: k.low, close: k.close })));

    const line = (pts: SeriesPoint[], color: string, width: 1 | 2 = 2, pane = 0) => {
      const s = chart.addSeries(LineSeries, {
        color, lineWidth: width, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "price", precision: 0, minMove: 1 },
      }, pane);
      s.setData(pts.map(t));
      return s;
    };
    line(data.sma20, c.sea, 2);
    line(data.sma50, c.amber, 2);
    line(data.ema20, c.ink, 1);

    if (data.avg_cost) {
      candles.createPriceLine({ price: data.avg_cost, color: c.sea, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Giá vốn" });
    }
    if (data.stop_level) {
      candles.createPriceLine({ price: data.stop_level, color: c.lead, lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "Cắt lỗ" });
    }

    // vùng bán và mức vô hiệu của kế hoạch kỹ thuật (mục 6d)
    levels.forEach((l) => candles.createPriceLine({
      price: l.price, color: l.kind === "sell" ? c.amber : c.lead, lineWidth: 1,
      lineStyle: l.kind === "sell" ? LineStyle.Dotted : LineStyle.Dashed, axisLabelVisible: true, title: l.title,
    }));

    // RSI
    const rsi = line(data.rsi14, c.ink, 2, 1);
    [[40, c.lead], [65, c.muted]].forEach(([price, color]) =>
      rsi.createPriceLine({ price: price as number, color: color as string, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: "" }));

    // MACD
    const hist = chart.addSeries(HistogramSeries, {
      priceLineVisible: false, lastValueVisible: false, priceFormat: { type: "price", precision: 0, minMove: 1 },
    }, 2);
    hist.setData(data.macd_hist.map((p) => ({ time: p.time as Time, value: p.value, color: p.value >= 0 ? c.ok : c.lead })));
    line(data.macd, c.ink, 1, 2);
    line(data.macd_signal, c.amber, 1, 2);

    const panes = chart.panes();
    // chia chiều cao theo tỷ lệ: giá chiếm phần lớn, RSI và MACD mỗi ô đủ đọc
    panes[0]?.setStretchFactor(0.62);
    panes[1]?.setStretchFactor(0.18);
    panes[2]?.setStretchFactor(0.2);
    chart.timeScale().fitContent();
    return () => chart.remove();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, themeKey, levelKey]);

  return (
    <div>
      <div ref={ref} style={{ height }} role="img"
           aria-label={`Biểu đồ nến ${data.symbol}, kèm đường trung bình SMA20, SMA50, EMA20, giá vốn, mức cắt lỗ, RSI và MACD`} />
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <Legend color="var(--sea)" label="SMA20" />
        <Legend color="var(--amber-fill)" label="SMA50" />
        <Legend color="var(--ink)" label="EMA20" />
        <Legend color="var(--sea)" label="Giá vốn" dashed />
        <Legend color="var(--lead)" label="Mức cắt lỗ" thick />
        <li>RSI: vạch 40 (yếu) và 65 (quá nóng)</li>
      </ul>
    </div>
  );
}

function Legend({ color, label, dashed, thick }: { color: string; label: string; dashed?: boolean; thick?: boolean }) {
  return (
    <li className="flex items-center gap-1.5">
      <svg width="18" height="6" aria-hidden><line x1="0" x2="18" y1="3" y2="3" stroke={color} strokeWidth={thick ? 3 : 2} strokeDasharray={dashed ? "4 3" : undefined} /></svg>
      {label}
    </li>
  );
}
