export type Rol = "MUNICIPIO" | "COORDINADOR" | "ONG" | "AUDITOR";

export type Usuario = {
  id: number;
  username: string;
  nombre: string;
  rol: Rol;
};

type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  user: Usuario;
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
  estado:
    | "REGISTRADA"
    | "CONVOCATORIA"
    | "CERRADA"
    | "EN_EVALUACION"
    | "ADJUDICACION"
    | "EN_EJECUCION"
    | "RESUELTA";
  bonita_case_id: number | null;
  ventana_ofertas_fin: string | null;
  creada_en: string;
  municipio_nombre: string | null;
  municipio_provincia: string | null;
  lotes: Lote[];
  tarea_bonita?: string | null;
  evaluacion?: Evaluacion | null;
};

export type Evaluacion = {
  emergencia_id: number;
  ronda: number;
  cobertura_completa: boolean;
  porcentaje_cobertura: number;
  lotes: {
    lote_id: number;
    tipo_recurso: string | null;
    pedido: number;
    reservado: number;
    porcentaje: number;
    cubierto: boolean;
  }[];
  ongs: {
    cuit: string;
    ong: string | null;
    referencia: string | null;
    estado: "RESERVADA" | "ADJUDICADA" | "NO_RESERVADA";
    items: {
      lote_id: number;
      tipo_recurso: string;
      ofrecido: number;
      reservado: number;
      nivel: "PLENA" | "PARCIAL" | "SUPERVISADA";
      riesgo_permitido: string | null;
      asignacion_sugerida: "PRINCIPAL" | "APOYO";
      observaciones: string[];
    }[];
  }[];
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
  retirada: boolean;
  estado: "PRESENTADA" | "ADJUDICADA" | "NO_ADJUDICADA" | "FINALIZADA";
};

let accessToken: string | null = null;

function getAccessToken() {
  if (accessToken !== null) return accessToken;
  return typeof window === "undefined" ? null : window.sessionStorage.getItem("access_token");
}

function clearAccessToken() {
  accessToken = null;
  if (typeof window !== "undefined") window.sessionStorage.removeItem("access_token");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) clearAccessToken();
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
  login: async (username: string, password: string) => {
    const response = await request<TokenResponse>("/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    window.sessionStorage.setItem("access_token", response.access_token);
    accessToken = response.access_token;
    return response.user;
  },
  registerOng: async (body: {
    ong_nombre: string;
    cuit?: string;
    nombre: string;
    username: string;
    password: string;
  }) => {
    const response = await request<TokenResponse>("/ongs", {
      method: "POST",
      body: JSON.stringify(body),
    });
    window.sessionStorage.setItem("access_token", response.access_token);
    accessToken = response.access_token;
    return response.user;
  },
  logout: async () => {
    try {
      await request<void>("/api/auth/logout", { method: "POST" });
    } finally {
      clearAccessToken();
    }
  },
  listEmergencias: () => request<Emergencia[]>("/api/emergencias"),
  listConvocatoriasAbiertas: () =>
    request<Emergencia[]>("/api/emergencias/convocatorias/abiertas"),
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
  decidir: (id: number, decision: "PARCIAL" | "REFORMULAR") =>
    request<Emergencia>(`/api/emergencias/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    }),
  adjudicar: (id: number, cuits: string[]) =>
    request<Emergencia>(`/api/emergencias/${id}/adjudicar`, {
      method: "POST",
      body: JSON.stringify({ cuits }),
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
