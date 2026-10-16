import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "./lib/api";
import { SelectionProvider } from "./lib/selection";
import { Shell } from "./components/Shell";
import { Skeleton } from "./components/ui";
import Overview from "./pages/Overview";
import Positions from "./pages/Positions";
import Margin from "./pages/Margin";
import Alerts from "./pages/Alerts";
import Scenarios from "./pages/Scenarios";
import Settings from "./pages/Settings";
import Ledger from "./pages/Ledger";
import Board from "./pages/Board";

const SymbolPage = lazy(() => import("./pages/SymbolPage")); // kéo theo thư viện biểu đồ, chỉ nạp khi cần

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && [0, 401, 403, 404, 409, 422].includes(e.status)) && n < 2,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <SelectionProvider>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<Overview />} />
              <Route path="positions" element={<Positions />} />
              <Route path="symbol/:symbol" element={<Suspense fallback={<Skeleton className="h-96" />}><SymbolPage /></Suspense>} />
              <Route path="margin" element={<Margin />} />
              <Route path="scenarios" element={<Scenarios />} />
              <Route path="alerts" element={<Alerts />} />
              <Route path="ledger" element={<Ledger />} />
              <Route path="board" element={<Board />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<p className="py-10 text-center text-muted">Không có trang này.</p>} />
            </Route>
          </Routes>
        </SelectionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
