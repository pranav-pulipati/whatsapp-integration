/**
 * Small, dependency-free SVG charts following the dashboard's chart spec:
 * 2px lines, hairline solid grid, one y-axis, crosshair + single tooltip listing
 * every series, keyboard access, legend for ≥2 series, and a data-table twin.
 */
import { useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { formatNumber } from "../lib/format";

export interface Series {
  key: string;
  label: string;
  color: string; // CSS colour (a var() token)
}

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(Math.round(v * 100) / 100);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

export function Legend({ series, shape = "line" }: { series: Series[]; shape?: "line" | "rect" }) {
  if (series.length < 2) return null;
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.key}>
          <i className={shape === "line" ? "key-line" : "key-rect"} style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

const shortDate = (d: string) =>
  new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

export function LineChart<T extends { date: string }>({
  data,
  series,
  height = 220,
  area = false,
  refreshing = false,
  caption,
}: {
  data: T[];
  series: Series[];
  height?: number;
  area?: boolean;
  refreshing?: boolean;
  caption: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const pad = { top: 12, right: 12, bottom: 26, left: 40 };
  const plotW = Math.max(0, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;

  const value = (row: T, key: string) => Number((row as Record<string, unknown>)[key] ?? 0);
  const max = useMemo(
    () => Math.max(0, ...data.flatMap((row) => series.map((s) => value(row, s.key)))),
    [data, series],
  );
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const x = (i: number) => pad.left + (data.length <= 1 ? plotW / 2 : (i / (data.length - 1)) * plotW);
  const y = (v: number) => pad.top + plotH - (v / top) * plotH;

  const xTickEvery = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(plotW / 80))));

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - rect.left) / Math.max(1, rect.width);
    setHover(Math.max(0, Math.min(data.length - 1, Math.round(rel * (data.length - 1)))));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowRight") setHover((h) => Math.min(data.length - 1, (h ?? -1) + 1));
    else if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? data.length) - 1));
    else if (e.key === "Escape") setHover(null);
    else return;
    e.preventDefault();
  };

  const hovered = hover !== null ? data[hover] : null;
  const tipLeft = hover !== null ? x(hover) : 0;

  return (
    <div className="stack" style={{ gap: 10 }}>
      <Legend series={series} />
      <div ref={ref} className={`chart${refreshing ? " refreshing" : ""}`} style={{ height }}>
        {width > 0 && (
          <svg
            height={height}
            role="img"
            aria-label={caption}
            tabIndex={0}
            onKeyDown={onKey}
            onBlur={() => setHover(null)}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? "baseline" : "grid-line"} x1={pad.left} x2={pad.left + plotW} y1={y(t)} y2={y(t)} />
                <text className="tick" x={pad.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
                  {formatNumber(t)}
                </text>
              </g>
            ))}
            {data.map((d, i) =>
              i % xTickEvery === 0 ? (
                <text key={d.date} className="tick" x={x(i)} y={height - 6} textAnchor="middle">
                  {shortDate(d.date)}
                </text>
              ) : null,
            )}
            {series.map((s) => {
              const pts = data.map((row, i) => `${x(i)},${y(value(row, s.key))}`);
              if (!pts.length) return null;
              return (
                <g key={s.key}>
                  {area && (
                    <path
                      d={`M${x(0)},${y(0)} L${pts.join(" L")} L${x(data.length - 1)},${y(0)} Z`}
                      fill={s.color}
                      opacity={0.1}
                    />
                  )}
                  <path d={`M${pts.join(" L")}`} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                </g>
              );
            })}
            {hovered && (
              <g>
                <line className="crosshair" x1={tipLeft} x2={tipLeft} y1={pad.top} y2={pad.top + plotH} />
                {series.map((s) => (
                  <circle key={s.key} cx={tipLeft} cy={y(value(hovered, s.key))} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                ))}
              </g>
            )}
            <rect
              x={pad.left}
              y={pad.top}
              width={plotW}
              height={plotH}
              fill="transparent"
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
        )}
        {hovered && (
          <div
            className="tooltip"
            style={{
              top: pad.top,
              left: tipLeft > width - 180 ? undefined : tipLeft + 12,
              right: tipLeft > width - 180 ? width - tipLeft + 12 : undefined,
            }}
          >
            <div className="t-title">
              {new Date(`${hovered.date}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}
            </div>
            {series.map((s) => (
              <div className="t-row" key={s.key}>
                <i className="key-line" style={{ background: s.color }} />
                <b>{value(hovered, s.key).toLocaleString()}</b>
                <span>{s.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <DataTable
        caption={caption}
        columns={["Date", ...series.map((s) => s.label)]}
        rows={data.map((d) => [d.date, ...series.map((s) => value(d, s.key).toLocaleString())])}
      />
    </div>
  );
}

export interface BarRow {
  key: string | number;
  label: string;
  sub?: string;
  values: Record<string, number>;
}

/** Horizontal stacked bars: ≤14px thick, 2px surface gap, rounded data end. */
export function StackedBars({ rows, series, caption }: { rows: BarRow[]; series: Series[]; caption: string }) {
  const [hover, setHover] = useState<string | number | null>(null);
  const total = (r: BarRow) => series.reduce((a, s) => a + (r.values[s.key] ?? 0), 0);
  const max = Math.max(1, ...rows.map(total));
  return (
    <div className="stack" style={{ gap: 14 }}>
      <Legend series={series} shape="rect" />
      <div className="bars" role="list" aria-label={caption}>
        {rows.map((r) => {
          const t = total(r);
          return (
            <div
              className="bar-row"
              key={r.key}
              role="listitem"
              tabIndex={0}
              onPointerEnter={() => setHover(r.key)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(r.key)}
              onBlur={() => setHover(null)}
              aria-label={`${r.label}: ${series.map((s) => `${r.values[s.key] ?? 0} ${s.label}`).join(", ")}`}
            >
              <div className="label truncate">
                {r.label}
                {r.sub && <div className="muted" style={{ fontSize: 12 }}>{r.sub}</div>}
              </div>
              <div className="bar-track" style={{ width: `${(t / max) * 100}%`, minWidth: t ? 4 : 0 }}>
                {series.map((s) => {
                  const v = r.values[s.key] ?? 0;
                  return v ? <span key={s.key} className="bar-seg" style={{ flex: v, background: s.color }} /> : null;
                })}
              </div>
              <div className="value">{formatNumber(t)}</div>
              {hover === r.key && (
                <div className="tooltip" style={{ top: -6, right: 64, transform: "translateY(-100%)" }}>
                  <div className="t-title">{r.label}</div>
                  {series.map((s) => (
                    <div className="t-row" key={s.key}>
                      <i className="key-rect" style={{ background: s.color }} />
                      <b>{(r.values[s.key] ?? 0).toLocaleString()}</b>
                      <span>{s.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <DataTable
        caption={caption}
        columns={["Number", ...series.map((s) => s.label), "Total"]}
        rows={rows.map((r) => [r.label, ...series.map((s) => (r.values[s.key] ?? 0).toLocaleString()), total(r).toLocaleString()])}
      />
    </div>
  );
}

function DataTable({ caption, columns, rows }: { caption: string; columns: string[]; rows: string[][] }) {
  return (
    <details className="data-table-toggle">
      <summary>View as table</summary>
      <div className="table-wrap">
        <table className="table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((c, i) => (
                <th key={c} className={i ? "num" : ""}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r[0]}>
                {r.map((c, i) => (
                  <td key={i} className={i ? "num" : ""}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
