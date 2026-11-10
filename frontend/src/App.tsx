import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { InventarioPage } from "./InventarioPage";
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
          element={
            <RequireAuth>
              <Outlet />
            </RequireAuth>
          }
        >
          <Route path="/" element={<HomePage />} />
          <Route path="/emergencias" element={<EmergenciasPage />} />
          <Route path="/emergencias/nueva" element={<NuevaEmergenciaPage />} />
          <Route path="/emergencias/:id" element={<DetallePage />} />
          <Route path="/inventario" element={<InventarioPage />} />
        </Route>
        <Route path="/alta-ong" element={<AltaOngPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
