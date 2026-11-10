export type Rol = "MUNICIPIO" | "COORDINADOR" | "ONG" | "AUDITOR";

export type Usuario = {
  id: number;
  username: string;
  nombre: string;
  rol: Rol;
  ong_id: number | null;
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

export type AltaOngIn = {
  ong_nombre: string;
  cuit: string;
  nombre: string;
  username: string;
  password: string;
  rubros: { tipo_recurso: string; cantidad_total: number }[];
};

export type AltaOngOut = {
  ong_nombre: string;
  cuit: string;
  username: string;
  rubros: { tipo_recurso: string; cantidad_total: number }[];
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
  ejecucion?: Ejecucion | null;
};

// Cómo va la ejecución de una emergencia adjudicada; la ONG solo trae su propia fila.
export type Ejecucion = {
  monitoreo_iniciado: boolean;
  cierre_validado: boolean;
  todas_finalizadas: boolean;
  ongs: { cuit: string | null; nombre: string; estado: "ADJUDICADA" | "FINALIZADA" }[];
};

export type Notificacion = {
  id: number;
  emergencia_id: number;
  texto: string;
  creada_en: string;
  leida: boolean;
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
  consorcio_id: number | null;
  consorcio_nombre: string | null;
};

// Reporte del dashboard (GET /api/indicadores; contrato en docs/dashboard-contrato.md).
export type Reporte = {
  filtros: { desde: string; hasta: string; municipio_id: number | null };
  generado_en: string;
  kpis: {
    emergencias: number;
    resueltas: number;
    en_curso: number;
    pct_consorcio: number | null;
    cobertura_promedio: number | null;
  };
  suministros: { mes: string; tipo_recurso: string; cantidad: number }[];
  estados: { estado: string; etiqueta: string; cantidad: number }[];
  tiempos: {
    disponible: boolean;
    motivo: string | null;
    etapas: { tarea: string; horas_promedio: number; emergencias: number }[];
    horas_total_promedio: number | null;
  };
  finalizadas: {
    emergencia_id: number;
    municipio: string;
    tipo: string;
    gravedad: string;
    ongs: string[];
    consorcio: boolean;
    horas_total: number | null;
    cobertura: number | null;
  }[];
};

export const exportCsvUrl = (bloque: string, desde: string, hasta: string) =>
  `/api/indicadores/export.csv?${new URLSearchParams({ bloque, desde, hasta })}`;

// Ficha de la ONG en el Sistema Nacional (GET/PUT /api/ong/inventario).
export type InventarioOng = {
  cuit: string;
  nombre: string;
  estado: string;
  certificaciones: { codigo: string; nombre: string; riesgo_max: string; vence_el: string; vigente: boolean }[];
  inventario: {
    tipo_recurso: string;
    nombre: string;
    unidad: string;
    cantidad_total: number;
    cantidad_comprometida: number;
    disponible: number;
    riesgo_permitido: string | null;
  }[];
};

export type MiembroConsorcio = {
  ong_id: number;
  ong_nombre: string;
  cuit: string | null;
  estado: "INVITADA" | "ACEPTADA" | "RECHAZADA" | "SALIO";
  invitado_en: string;
  respondido_en: string | null;
  salio_en: string | null;
};

export type Consorcio = {
  id: number;
  emergencia_id: number;
  nombre: string;
  ong_lider_id: number;
  ong_lider_nombre: string;
  valido: boolean;
  disuelto: boolean;
  miembros: MiembroConsorcio[];
};

export type OngResumen = { id: number; nombre: string; cuit: string | null };

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
    // detail de FastAPI: texto, o lista de errores de validación ([{loc, msg, ...}]); otro caso, el cuerpo crudo.
    const raw = (data as { detail?: unknown } | null)?.detail;
    throw new Error(
      typeof raw === "string"
        ? raw
        : Array.isArray(raw)
          ? raw.map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item))).join(" · ")
          : text || res.statusText,
    );
  }
  return data as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const put = <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) });

// /api/meta no cambia en la sesión: una sola petición compartida; si falla, la próxima llamada reintenta.
let metaPromise: Promise<Meta> | null = null;

export const api = {
  meta: () =>
    (metaPromise ??= request<Meta>("/api/meta").catch((err) => {
      metaPromise = null;
      throw err;
    })),
  me: () => request<Usuario>("/api/auth/me"),
  login: (username: string, password: string) => post<Usuario>("/api/auth/login", { username, password }),
  logout: () => post<void>("/api/auth/logout"),
  listEmergencias: () => request<Emergencia[]>("/api/emergencias"),
  getEmergencia: (id: number) => request<Emergencia>(`/api/emergencias/${id}`),
  createEmergencia: (body: { tipo: string; nivel_gravedad: string; zona_afectada: string; descripcion: string }) =>
    post<Emergencia>("/api/emergencias", body),
  tiposRecurso: () => request<TipoRecurso[]>("/api/tipos-recurso"),
  tiposRecursoAlta: () => request<TipoRecurso[]>("/api/ongs/alta/tipos-recurso"),
  altaOng: (body: AltaOngIn) => post<AltaOngOut>("/api/ongs/alta", body),
  createLote: (id: number, body: { tipo_recurso: string; detalle?: string; cantidad: number; tipo: string }) =>
    post<Lote>(`/api/emergencias/${id}/lotes`, body),
  publicar: (id: number, ventana_fin: string) =>
    post<Emergencia>(`/api/emergencias/${id}/publicar`, { ventana_fin }),
  decidir: (id: number, decision: "PARCIAL" | "REFORMULAR") =>
    post<Emergencia>(`/api/emergencias/${id}/decision`, { decision }),
  adjudicar: (id: number, cuits: string[]) =>
    post<Emergencia>(`/api/emergencias/${id}/adjudicar`, { cuits }),
  monitorear: (id: number) => post<Emergencia>(`/api/emergencias/${id}/monitorear`),
  finalizar: (id: number) => post<Emergencia>(`/api/emergencias/${id}/finalizar`),
  validarCierre: (id: number) => post<Emergencia>(`/api/emergencias/${id}/validar-cierre`),
  indicadores: (desde: string, hasta: string) =>
    request<Reporte>(`/api/indicadores?${new URLSearchParams({ desde, hasta })}`),
  inventario: () => request<InventarioOng>("/api/ong/inventario"),
  declararInventario: (rubros: { tipo_recurso: string; cantidad_total: number }[]) =>
    put<InventarioOng>("/api/ong/inventario", { rubros }),
  notificaciones: () => request<Notificacion[]>("/api/notificaciones"),
  marcarLeida: (id: number) => post<Notificacion>(`/api/notificaciones/${id}/leida`),
  listOfertas: (id: number) => request<Oferta[]>(`/api/emergencias/${id}/ofertas`),
  createOferta: (id: number, items: { lote_id: number; recurso: string; cantidad: number }[]) =>
    post<Oferta>(`/api/emergencias/${id}/ofertas`, { items }),
  listConsorcios: (id: number) => request<Consorcio[]>(`/api/emergencias/${id}/consorcios`),
  crearConsorcio: (id: number, nombre: string) => post<Consorcio>(`/api/emergencias/${id}/consorcios`, { nombre }),
  invitar: (cid: number, ong_id: number) => post<Consorcio>(`/api/consorcios/${cid}/invitaciones`, { ong_id }),
  responder: (cid: number, acepta: boolean) => post<Consorcio>(`/api/consorcios/${cid}/respuesta`, { acepta }),
  salirConsorcio: (cid: number) => post<void>(`/api/consorcios/${cid}/salida`),
  disolverConsorcio: (cid: number) => request<void>(`/api/consorcios/${cid}`, { method: "DELETE" }),
  listOngs: (emergencia_id?: number) =>
    request<OngResumen[]>(emergencia_id ? `/api/ongs?emergencia_id=${emergencia_id}` : "/api/ongs"),
};
