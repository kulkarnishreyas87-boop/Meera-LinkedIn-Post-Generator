import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import "./index.css";
import { Backlog } from "./pages/Backlog";
import { Inbox } from "./pages/Inbox";
import { Studio } from "./pages/Studio";
import { Week } from "./pages/Week";

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: true } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <ToastProvider>
          <Layout>
            <Routes>
              <Route path="/" element={<Inbox />} />
              <Route path="/studio" element={<Studio />} />
              <Route path="/studio/:noteId" element={<Studio />} />
              <Route path="/week" element={<Week />} />
              <Route path="/backlog" element={<Backlog />} />
              <Route path="*" element={<Inbox />} />
            </Routes>
          </Layout>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
