"use client";

import { useState } from "react";

export type TableColumn = { label: string; align?: "left" | "right" };

/**
 * "View as table": the same numbers a chart draws, as a real table with a caption and header
 * scopes, behind a button that says whether it is open. It is the text alternative to the picture.
 */
export function ChartTable({
  id,
  caption,
  columns,
  rows,
}: {
  id: string;
  caption: string;
  columns: TableColumn[];
  rows: string[][];
}) {
  const [open, setOpen] = useState(false);
  const tableId = `${id}-table`;
  return (
    <div className="mt-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={tableId}
        onClick={() => setOpen((o) => !o)}
        className="min-h-9 rounded-md border border-stone-300 bg-white px-3 py-1 text-sm font-medium text-green-900 hover:bg-stone-50"
      >
        {open ? "Hide table" : "View as table"}
      </button>
      <div id={tableId} hidden={!open} tabIndex={open ? 0 : undefined} role={open ? "region" : undefined} aria-label={open ? caption : undefined} className="mt-2 max-h-80 overflow-auto">
        {open && (
          <table className="w-full text-left text-xs">
            <caption className="sr-only">{caption}</caption>
            <thead className="sticky top-0 bg-white text-stone-600">
              <tr>
                {columns.map((c) => (
                  <th key={c.label} scope="col" className={`py-1 pr-3 font-medium ${c.align === "right" ? "text-right" : ""}`}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100 tabular-nums">
              {rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) =>
                    j === 0 ? (
                      <th key={j} scope="row" className="py-1 pr-3 font-normal">
                        {cell}
                      </th>
                    ) : (
                      <td key={j} className={`py-1 pr-3 ${columns[j]?.align === "right" ? "text-right" : ""}`}>
                        {cell}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/** A chart with a heading, a one-paragraph text summary, the picture (named) and a table view. */
export function ChartFigure({
  id,
  title,
  hint,
  summary,
  columns,
  rows,
  className = "h-56",
  children,
}: {
  id: string;
  title: string;
  hint?: string;
  summary: string;
  columns: TableColumn[];
  rows: string[][];
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <figure className="rounded-lg border border-stone-200 bg-white p-4">
      <figcaption>
        <h2 className="font-semibold">{title}</h2>
        {hint && <p className="text-xs text-stone-600">{hint}</p>}
      </figcaption>
      <p id={`${id}-summary`} className="mt-1 text-sm text-stone-700">
        {summary}
      </p>
      <div role="img" aria-label={title} aria-describedby={`${id}-summary`} className={`mt-3 ${className}`}>
        {children}
      </div>
      <ChartTable id={id} caption={`${title}: the numbers behind the chart`} columns={columns} rows={rows} />
    </figure>
  );
}
