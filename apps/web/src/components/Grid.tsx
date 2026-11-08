"use client";

import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useEffect, useState } from "react";

ModuleRegistry.registerModules([AllCommunityModule]);

const light = themeQuartz.withParams({ fontFamily: "inherit", headerFontWeight: 600, accentColor: "#0070e0" });
const dark = themeQuartz.withParams({
  fontFamily: "inherit", headerFontWeight: 600, accentColor: "#4da3ff",
  backgroundColor: "#121417", foregroundColor: "#e6e8eb", headerBackgroundColor: "#1a1d21",
  borderColor: "#2a2e34", oddRowBackgroundColor: "#15181b",
});

function useDark() {
  const [isDark, setDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(mq.matches);
    const h = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, []);
  return isDark;
}

export default function Grid<T>({
  rows, cols, height = 420, onRowClicked, getRowId,
}: {
  rows: T[] | null;
  cols: ColDef<T>[];
  height?: number;
  onRowClicked?: (row: T) => void;
  getRowId?: (row: T) => string;
}) {
  const isDark = useDark();
  return (
    <div style={{ height }} className="w-full">
      <AgGridReact<T>
        theme={isDark ? dark : light}
        rowData={rows ?? []}
        loading={rows === null}
        columnDefs={cols}
        defaultColDef={{ sortable: true, filter: true, resizable: true, flex: 1, minWidth: 90 }}
        animateRows
        getRowId={getRowId ? (p) => getRowId(p.data) : undefined}
        onRowClicked={(e) => e.data && onRowClicked?.(e.data)}
        rowSelection={onRowClicked ? { mode: "singleRow", checkboxes: false, enableClickSelection: true } : undefined}
      />
    </div>
  );
}
