import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import {
  AltaOngPage,
  DetallePage,
  EmergenciasPage,
  HomePage,
  LoginPage,
  NuevaEmergenciaPage,
  RequireAuth,
} from "./pages";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <HomePage />
            </RequireAuth>
          }
        />
        <Route
          path="/emergencias"
          element={
            <RequireAuth>
              <EmergenciasPage />
            </RequireAuth>
          }
        />
        <Route
          path="/emergencias/nueva"
          element={
            <RequireAuth>
              <NuevaEmergenciaPage />
            </RequireAuth>
          }
        />
        <Route
          path="/emergencias/:id"
          element={
            <RequireAuth>
              <DetallePage />
            </RequireAuth>
          }
        />
        <Route path="/alta-ong" element={<AltaOngPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
