import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "./api/client";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import { ContactsPage } from "./pages/Contacts";
import { ConversationsPage } from "./pages/Conversations";
import { LoginPage } from "./pages/Login";
import { NumbersPage } from "./pages/Numbers";
import { OpsPage } from "./pages/Ops";
import { OverviewPage } from "./pages/Overview";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
    },
  },
});

export function AppRoutes() {
  const { user, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!user) return <LoginPage />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="conversations" element={<ConversationsPage />} />
        <Route path="conversations/:id" element={<ConversationsPage />} />
        <Route path="contacts" element={<ContactsPage />} />
        <Route path="numbers" element={<NumbersPage />} />
        {user.role === "admin" && <Route path="ops" element={<OpsPage />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
