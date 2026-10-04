export type Rol = "MUNICIPIO" | "COORDINADOR" | "ONG" | "AUDITOR";

export type Usuario = {
  id: number;
  username: string;
  nombre: string;
  rol: Rol;
};

export type Lote = {
  id: number;
  recurso: string;
  tipo_recurso: string | null;
  cantidad: number;
  unidad: string;
  tipo: "PRINCIPAL" | "APOYO";
};

export type TipoRecurso = {
  codigo: string;
  nombre: string;
  categoria: string;
  unidad: string;
  certificacion_requerida: string | null;
};

export type Emergencia = {
  id: number;
  tipo: string;
  nivel_gravedad: "BAJO" | "MEDIO" | "ALTO" | "CRITICO";
  zona_afectada: string;
  descripcion: string;
  estado: "REGISTRADA" | "CONVOCATORIA" | "CERRADA";
  bonita_case_id: number | null;
  ventana_ofertas_fin: string | null;
  creada_en: string;
  municipio_nombre: string | null;
  municipio_provincia: string | null;
  lotes: Lote[];
  tarea_bonita?: string | null;
};

export type Meta = {
  tipos: Record<string, string>;
  roles: Record<string, string>;
  demo: { password: string; users: { username: string; rol: string; label: string }[] } | null;
};

export type Oferta = {
  id: number;
  emergencia_id: number;
  ong_id: number;
  ong_nombre: string;
  version_actual: number;
  items: { lote_id: number; recurso: string; cantidad: number; version: number }[];
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    let detail = text || res.statusText;
    if (typeof data === "object" && data && "detail" in data) {
      const raw = (data as { detail: unknown }).detail;
      if (typeof raw === "string") detail = raw;
      else if (Array.isArray(raw)) {
        detail = raw
          .map((item) =>
            typeof item === "object" && item && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : String(item),
          )
          .join(" · ");
      }
    }
    throw new Error(detail);
  }
  return data as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  me: () => request<Usuario>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<Usuario>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  listEmergencias: () => request<Emergencia[]>("/api/emergencias"),
  getEmergencia: (id: number) => request<Emergencia>(`/api/emergencias/${id}`),
  createEmergencia: (body: {
    tipo: string;
    nivel_gravedad: string;
    zona_afectada: string;
    descripcion: string;
  }) =>
    request<Emergencia>("/api/emergencias", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  tiposRecurso: () => request<TipoRecurso[]>("/api/tipos-recurso"),
  createLote: (
    id: number,
    body: { tipo_recurso: string; detalle?: string; cantidad: number; tipo: string },
  ) =>
    request<Lote>(`/api/emergencias/${id}/lotes`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteLote: (id: number, loteId: number) =>
    request<void>(`/api/emergencias/${id}/lotes/${loteId}`, { method: "DELETE" }),
  publicar: (id: number, ventana_fin: string) =>
    request<Emergencia>(`/api/emergencias/${id}/publicar`, {
      method: "POST",
      body: JSON.stringify({ ventana_fin }),
    }),
  listOfertas: (id: number) => request<Oferta[]>(`/api/emergencias/${id}/ofertas`),
  createOferta: (
    id: number,
    items: { lote_id: number; recurso: string; cantidad: number }[],
  ) =>
    request<Oferta>(`/api/emergencias/${id}/ofertas`, {
      method: "POST",
      body: JSON.stringify({ items }),
    }),
};
