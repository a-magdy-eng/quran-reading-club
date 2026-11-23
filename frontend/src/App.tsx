import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Spinner, ToastProvider } from "./components";
import { Layout } from "./Layout";
import { AdminPage } from "./pages/Admin";
import { CreateGroupPage, JoinPage, LoginPage, NoGroupPage, SetupPage } from "./pages/AuthPages";
import { DashboardPage } from "./pages/Dashboard";
import { MePage } from "./pages/Me";
import { ReaderPage } from "./pages/Reader";

function RequireGroup({ children, admin }: { children: ReactNode; admin?: boolean }) {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!me) return <Navigate to="/login" replace />;
  if (!me.membership) return <Navigate to="/welcome" replace />;
  if (admin && me.membership.role !== "admin") return <Navigate to="/" replace />;
  return <>{children}</>;
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (me) return <Navigate to={me.membership ? "/" : "/welcome"} replace />;
  return <>{children}</>;
}

function SignedIn({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!me) return <Navigate to="/login" replace />;
  if (me.membership) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
            <Route path="/join" element={<PublicOnly><JoinPage /></PublicOnly>} />
            <Route path="/setup" element={<PublicOnly><SetupPage /></PublicOnly>} />
            <Route path="/welcome" element={<SignedIn><NoGroupPage /></SignedIn>} />
            <Route path="/create-group" element={<SignedIn><CreateGroupPage /></SignedIn>} />
            <Route path="/read/:page?" element={<RequireGroup><ReaderPage /></RequireGroup>} />
            <Route element={<RequireGroup><Layout /></RequireGroup>}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/me" element={<MePage />} />
              <Route path="/admin" element={<RequireGroup admin><AdminPage /></RequireGroup>} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  );
}
