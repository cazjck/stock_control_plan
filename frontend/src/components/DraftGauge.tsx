import { useId, type CSSProperties } from "react";
import { buildScale, spreadLabels, zoneOf, type GaugeZone } from "../lib/gauge";
import { fmtPct } from "../lib/format";

interface Props {
  ratio: number | null | undefined;
  maintenance: number | null | undefined;
  liquidation?: number | null;
  safeTarget?: number | null;
  height?: number;
  liquidationLabel?: string;   // TCBS gọi là "xử lý" (tỷ lệ xử lý tài sản)
}

const ZONE_COLOR: Record<GaugeZone, string> = {
  breach: "var(--lead)", danger: "var(--lead)", watch: "var(--amber)", safe: "var(--ok)",
};
const ZONE_WORD: Record<GaugeZone, string> = {
  breach: "đã chạm ngưỡng bán xử lý", danger: "đã dưới ngưỡng duy trì", watch: "đang trong vùng theo dõi", safe: "ở vùng an toàn",
};

function wavePath(x0: number, x1: number, y: number): string {
  const n = Math.ceil((x1 - x0) / 12) + 2;
  return `M ${x0} ${y} q 6 -3.5 12 0` + " t 12 0".repeat(n - 1);
}

/** Thước mớn nước: tỷ lệ ký quỹ vẽ như vạch mớn nước trên thân tàu.
 *  Số tăng dần xuống dưới. Mực nước dâng khi RTT giảm. Vạch Plimsoll (vòng tròn gạch ngang) là ngưỡng duy trì. */
export function DraftGauge({ ratio, maintenance, liquidation = null, safeTarget = null, height = 300, liquidationLabel = "giải chấp" }: Props) {
  const uid = useId().replace(/:/g, "");
  const W = 184, plateX = 4, plateW = 72, plateR = plateX + plateW;
  const top = 18, bottom = height - 18;

  if (ratio == null || maintenance == null) {
    return (
      <div className="flex items-center justify-center rounded-md border border-dashed border-line text-sm text-muted"
           style={{ width: W, height }}>
        Chưa có tỷ lệ ký quỹ
      </div>
    );
  }

  const g = { ratio, maintenance, liquidation, safeTarget };
  const sc = buildScale(g, top, bottom);
  const zone = zoneOf(g);
  const yR = sc.y(ratio), yM = sc.y(maintenance);
  const yL = liquidation != null ? sc.y(liquidation) : null;
  const yS = safeTarget != null ? sc.y(safeTarget) : null;
  const zoneColor = ZONE_COLOR[zone];

  const labels = spreadLabels([
    ...(yL != null && liquidation != null ? [{ key: "l", y: yL, num: fmtPct(liquidation, 0).replace("%", ""), text: liquidationLabel.toUpperCase(), color: "var(--lead)", strong: false }] : []),
    { key: "m", y: yM, num: fmtPct(maintenance, 0).replace("%", ""), text: "DUY TRÌ", color: "var(--ink)", strong: false },
    ...(yS != null && safeTarget != null ? [{ key: "s", y: yS, num: fmtPct(safeTarget, 0).replace("%", ""), text: "AN TOÀN", color: "var(--ok)", strong: false }] : []),
    { key: "n", y: yR, num: fmtPct(ratio, 1).replace("%", ""), text: "HIỆN TẠI", color: zoneColor, strong: true },
  ], 30, top + 6, bottom - 6);

  const dangerBottom = yL ?? yM;
  const label =
    `Tỷ lệ ký quỹ hiện tại ${fmtPct(ratio)}, ${ZONE_WORD[zone]}. Ngưỡng duy trì ${fmtPct(maintenance, 0)}` +
    (liquidation != null ? `, ngưỡng ${liquidationLabel} ${fmtPct(liquidation, 0)}` : "") + ".";
  const riseFrom = bottom - yR + 24;

  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${W} ${height}`} width={W} height={height} className="shrink-0 select-none">
      <title>{label}</title>
      <defs>
        <clipPath id={`hull-${uid}`}><rect x={plateX} y={4} width={plateW} height={height - 8} rx={4} /></clipPath>
        <pattern id={`hatch-${uid}`} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" fill="var(--hull)" />
          <rect width="3" height="8" fill="var(--lead)" opacity="0.85" />
        </pattern>
      </defs>

      {/* thân tàu */}
      <rect x={plateX} y={4} width={plateW} height={height - 8} rx={4} fill="var(--hull)" />

      <g clipPath={`url(#hull-${uid})`}>
        {/* vùng nguy hiểm: boong tàu */}
        <rect x={plateX} y={4} width={plateW} height={Math.max(0, dangerBottom - 4)} fill={`url(#hatch-${uid})`} />
        {yL != null && (
          <rect x={plateX} y={yL} width={plateW} height={Math.max(0, yM - yL)} fill="var(--lead)" opacity="0.28" />
        )}
        {yS != null && (
          <rect x={plateX} y={yM} width={plateW} height={Math.max(0, yS - yM)} fill="var(--amber-fill)" opacity="0.14" />
        )}

        {/* nước */}
        <g className="water-rise" style={{ "--rise-from": `${riseFrom}px` } as CSSProperties}>
          <rect x={plateX} y={yR} width={plateW} height={height} fill="var(--sea)" opacity="0.6" />
          <g className="water-wave">
            <path d={wavePath(plateX - 24, plateR + 24, yR)} fill="none" stroke="var(--wave)" strokeWidth="1.8" strokeLinecap="round" />
          </g>
        </g>

        {/* vạch và số mớn nước */}
        {sc.ticks.map((t) => {
          const y = sc.y(t.v);
          return (
            <g key={t.v}>
              <line x1={plateX} x2={plateX + (t.major ? 15 : 7)} y1={y} y2={y} stroke="var(--hull-text)" strokeWidth={t.major ? 1.6 : 1} opacity={t.major ? 0.95 : 0.55} />
              {t.major && (
                <text x={plateX + 20} y={y + 4.5} fill="var(--hull-text)" fontFamily="var(--font-display)" fontWeight="600" fontSize="14" letterSpacing="0.04em">
                  {t.v}
                </text>
              )}
            </g>
          );
        })}
      </g>

      {/* vạch Plimsoll tại ngưỡng duy trì */}
      <g stroke="var(--hull-text)" strokeWidth="1.8" fill="none">
        <circle cx={plateR - 17} cy={yM} r="7.5" />
        <line x1={plateR - 31} x2={plateR - 3} y1={yM} y2={yM} />
      </g>
      {yL != null && <line x1={plateR - 31} x2={plateR - 3} y1={yL} y2={yL} stroke="var(--hull-text)" strokeWidth="1.8" />}
      {yS != null && <line x1={plateR - 31} x2={plateR - 3} y1={yS} y2={yS} stroke="var(--hull-text)" strokeWidth="1.8" strokeDasharray="3 2" />}

      {/* nhãn bên phải, có dây dẫn */}
      {labels.map((l) => (
        <g key={l.key}>
          <path d={`M ${plateR} ${l.y} L ${plateR + 8} ${l.y} L ${plateR + 14} ${l.ly}`} stroke={l.color} strokeWidth={l.strong ? 2 : 1.2} fill="none" />
          {l.strong && <path d={`M ${plateR} ${l.y} l 9 -6 v 12 z`} fill={l.color} />}
          <text x={plateR + 19} y={l.ly + (l.strong ? 6 : 5)} fill={l.color} fontFamily="var(--font-display)" fontWeight={l.strong ? 700 : 600}
                fontSize={l.strong ? 26 : 17} letterSpacing="0.01em">
            {l.num}
            <tspan dx="4" fontSize={l.strong ? 10 : 9.5} letterSpacing="0.1em" fontWeight="600">{l.text}</tspan>
          </text>
        </g>
      ))}
    </svg>
  );
}
