import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api, type Emergencia, type Meta, type Oferta, type Rol, type TipoRecurso } from "./api";
import { useAuth } from "./auth";
import { FlowBubbles } from "./FlowBubbles";
import { PageHeader } from "./PageHeader";

const ROL_LABEL: Record<Rol, string> = {
  MUNICIPIO: "Operador Municipal",
  COORDINADOR: "Centro Coordinador",
  ONG: "Representante ONG",
  AUDITOR: "Auditor / Directivo",
};

const GRAV_COLOR: Record<Emergencia["nivel_gravedad"], string> = {
  CRITICO: "#9f1239",
  ALTO: "#c2410c",
  MEDIO: "#a16207",
  BAJO: "#3f6212",
};

const MENU: Record<Rol, { title: string; to: string; hint: string }[]> = {
  MUNICIPIO: [
    { title: "Registrar emergencia", to: "/emergencias/nueva", hint: "Alta operativa y caso Bonita" },
    { title: "Mis emergencias", to: "/emergencias", hint: "Estado y seguimiento" },
  ],
  COORDINADOR: [
    { title: "Emergencias", to: "/emergencias", hint: "Armar lotes y publicar convocatoria" },
  ],
  ONG: [
    { title: "Convocatorias abiertas", to: "/emergencias", hint: "Cargar ofertas de ayuda" },
  ],
  AUDITOR: [
    { title: "Consulta de emergencias", to: "/emergencias", hint: "Vista de solo lectura" },
  ],
};

const fade = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: { duration: 0.38, ease: "easeOut" as const },
};

function formatFecha(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-AR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function estadoBadge(estado: Emergencia["estado"]) {
  if (estado === "CONVOCATORIA") return <span className="badge signal">Convocatoria abierta</span>;
  if (estado === "CERRADA") return <span className="badge muted">Ventana cerrada</span>;
  if (estado === "EN_EVALUACION") return <span className="badge muted">En evaluación</span>;
  if (estado === "ADJUDICACION") return <span className="badge signal">Adjudicación</span>;
  if (estado === "EN_EJECUCION") return <span className="badge signal">En ejecución</span>;
  if (estado === "RESUELTA") return <span className="badge muted">Resuelta</span>;
  return <span className="badge ok">Registrada</span>;
}

export function Shell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand">
          Rescue<em>Sync</em>
        </Link>
        {user && (
          <div className="topbar-meta">
            <span className="role-chip">{ROL_LABEL[user.rol]}</span>
            <span>{user.nombre}</span>
            <button className="btn btn-ghost light" type="button" onClick={() => void logout()}>
              Salir
            </button>
          </div>
        )}
      </header>
      <main className="page">{children}</main>
    </div>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="loading">
        <div className="loading-dot" aria-hidden />
        <span>RescueSync</span>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    void api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  if (user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo ingresar");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-stage">
      <section className="login-hero">
        <motion.div className="login-hero-inner" {...fade}>
          <FlowBubbles />
          <div className="login-hero-copy">
            <p className="kicker" style={{ color: "rgba(246,243,236,0.7)" }}>
              Coordinación de emergencias
            </p>
            <h1 className="login-brand">
              Rescue<em>Sync</em>
            </h1>
            <p className="login-copy">
              Un flujo claro para registrar, convocar y responder — pensado para equipos que
              necesitan actuar ya.
            </p>
            <div className="login-stats">
              <span className="login-stat">Municipio</span>
              <span className="login-stat">Coordinador</span>
              <span className="login-stat">Red de ONGs</span>
            </div>
          </div>
        </motion.div>
      </section>
      <section className="login-panel">
        <motion.div className="login-card" {...fade} transition={{ ...fade.transition, delay: 0.08 }}>
          <h1>Ingresar</h1>
          <p className="sub">Usá tu perfil operativo para continuar.</p>
          {error && (
            <motion.div className="alert" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>
              {error}
            </motion.div>
          )}
          <form onSubmit={onSubmit}>
            <div className="field">
              <label htmlFor="username">Usuario</label>
              <input
                id="username"
                value={username}
                onChange={(ev) => setUsername(ev.target.value)}
                autoComplete="username"
                placeholder="ej. operador.municipal"
                required
                autoFocus
              />
            </div>
            <div className="field">
              <label htmlFor="password">Contraseña</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(ev) => setPassword(ev.target.value)}
                autoComplete="current-password"
                placeholder="••••••••"
                required
              />
            </div>
            <button className="btn btn-primary btn-block" disabled={busy}>
              {busy ? "Entrando…" : "Entrar al panel"}
            </button>
          </form>
          {meta?.demo && (
            <details className="demo">
              <summary>
                Accesos de demo · clave <code>{meta.demo.password}</code>
              </summary>
              <ul>
                {meta.demo.users.map((u) => (
                  <li key={u.username}>
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => {
                        setUsername(u.username);
                        setPassword(meta.demo!.password);
                      }}
                    >
                      {u.username}
                    </button>
                    <span>{u.label}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </motion.div>
      </section>
    </div>
  );
}

export function HomePage() {
  const { user } = useAuth();
  const items = MENU[user!.rol] ?? [];
  return (
    <Shell>
      <motion.div {...fade}>
        <p className="kicker">Panel operativo</p>
        <h1 className="title" style={{ fontSize: "clamp(1.9rem, 4vw, 2.45rem)" }}>
          Hola, {user!.nombre.split(" ")[0]}
        </h1>
        <p className="lede">
          Estás como <strong>{ROL_LABEL[user!.rol]}</strong>. Elegí qué querés hacer ahora.
        </p>
        <nav className={`menu-grid ${items.length > 1 ? "cols-2" : ""}`}>
          {items.map((item, i) => (
            <motion.div
              key={item.to}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.06 * i, duration: 0.35 }}
            >
              <Link className="menu-card" to={item.to}>
                <div className="menu-title">
                  <strong>{item.title}</strong>
                  <span>{item.hint}</span>
                </div>
                <span className="arrow" aria-hidden>
                  →
                </span>
              </Link>
            </motion.div>
          ))}
        </nav>
      </motion.div>
    </Shell>
  );
}

export function EmergenciasPage() {
  const { user } = useAuth();
  const [items, setItems] = useState<Emergencia[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void Promise.all([api.listEmergencias(), api.meta()])
      .then(([list, m]) => {
        setItems(list);
        setMeta(m);
      })
      .catch((err) => setError(String(err.message || err)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Shell>
      <motion.div {...fade}>
        <div className="page-head">
          <div>
            <p className="kicker">Operación</p>
            <h1 className="title" style={{ fontSize: "clamp(1.6rem, 3vw, 1.95rem)" }}>
              {user!.rol === "ONG" ? "Convocatorias abiertas" : "Emergencias"}
            </h1>
          </div>
          <div className="form-actions" style={{ marginTop: 0 }}>
            <Link className="btn btn-ghost" to="/">
              ← Panel
            </Link>
            {user!.rol === "MUNICIPIO" && (
              <Link className="btn btn-primary" to="/emergencias/nueva">
                Nueva emergencia
              </Link>
            )}
          </div>
        </div>
        {error && <div className="alert">{error}</div>}
        {loading ? (
          <div className="panel empty">
            <div className="loading-dot" style={{ margin: "0 auto" }} />
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            {items.length === 0 ? (
              <div className="panel empty">
                <div className="empty-mark">∅</div>
                <p>
                  {user!.rol === "ONG"
                    ? "No hay convocatorias abiertas por ahora."
                    : "Todavía no hay emergencias registradas."}
                </p>
              </div>
            ) : (
              <div className="cards two">
                {items.map((em, i) => (
                  <motion.div
                    key={em.id}
                    layout
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04, duration: 0.35 }}
                  >
                    <Link
                      className="em-card"
                      to={`/emergencias/${em.id}`}
                      style={{ ["--grav-color" as string]: GRAV_COLOR[em.nivel_gravedad] }}
                    >
                      <div className="em-card-top">
                        <span className="badge muted">#{em.id}</span>
                        {estadoBadge(em.estado)}
                      </div>
                      <h3>{meta?.tipos[em.tipo] ?? em.tipo}</h3>
                      <p>{em.zona_afectada}</p>
                      <div className="meta-line">
                        <span className={`badge g-${em.nivel_gravedad}`}>{em.nivel_gravedad}</span>
                        <span>{formatFecha(em.creada_en)}</span>
                        {em.lotes.length > 0 && (
                          <span>
                            {em.lotes.length} lote{em.lotes.length === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>
                    </Link>
                  </motion.div>
                ))}
              </div>
            )}
          </AnimatePresence>
        )}
      </motion.div>
    </Shell>
  );
}

export function NuevaEmergenciaPage() {
  const navigate = useNavigate();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.meta().then(setMeta);
  }, []);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const created = await api.createEmergencia({
        tipo: String(fd.get("tipo")),
        nivel_gravedad: String(fd.get("nivel_gravedad")),
        zona_afectada: String(fd.get("zona_afectada")),
        descripcion: String(fd.get("descripcion")),
      });
      navigate(`/emergencias/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al registrar");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <motion.div {...fade}>
        <PageHeader
          to="/"
          label="Volver al panel"
          kicker="Municipio"
          title="Registrar emergencia"
          lede="Completá los datos iniciales. Al guardar se abre el caso en Bonita para el Centro Coordinador."
        />
        {error && <div className="alert">{error}</div>}
        <div className="form-layout">
          <form className="panel" onSubmit={onSubmit}>
            <div className="field-row two">
              <div className="field">
                <label htmlFor="tipo">Tipo de evento</label>
                <select id="tipo" name="tipo" required>
                  {Object.entries(
                    meta?.tipos ?? {
                      inundacion: "Inundación",
                      incendio: "Incendio",
                      terremoto: "Terremoto",
                      otro: "Otro",
                    },
                  ).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="nivel_gravedad">Nivel de gravedad</label>
                <select id="nivel_gravedad" name="nivel_gravedad" required>
                  {["BAJO", "MEDIO", "ALTO", "CRITICO"].map((g) => (
                    <option key={g} value={g}>
                      {g}
                    </option>
                  ))}
                </select>
                <span className="hint">Define la prioridad operativa del caso.</span>
              </div>
            </div>
            <div className="field">
              <label htmlFor="zona_afectada">Zona afectada</label>
              <input id="zona_afectada" name="zona_afectada" placeholder="Barrio, localidad o área" required />
            </div>
            <div className="field">
              <label htmlFor="descripcion">Descripción</label>
              <textarea
                id="descripcion"
                name="descripcion"
                rows={5}
                placeholder="Situación inicial, impacto y necesidades estimadas"
                required
              />
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>
                {busy ? "Registrando…" : "Registrar emergencia"}
              </button>
              <Link className="btn btn-ghost" to="/">
                Cancelar
              </Link>
            </div>
          </form>
          <aside className="form-side">
            <div className="panel">
              <h3>Qué pasa al guardar</h3>
              <ol>
                <li>La emergencia queda persistida en la base local.</li>
                <li>Se instancia el proceso en Bonita (si el motor está arriba).</li>
                <li>El Centro Coordinador puede armar lotes y publicar.</li>
              </ol>
            </div>
          </aside>
        </div>
      </motion.div>
    </Shell>
  );
}

export function DetallePage() {
  const { user } = useAuth();
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const [e, setE] = useState<Emergencia | null>(null);
  const [ofertas, setOfertas] = useState<Oferta[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tipos, setTipos] = useState<TipoRecurso[]>([]);

  const reload = useCallback(async () => {
    const [em, m, of] = await Promise.all([api.getEmergencia(id), api.meta(), api.listOfertas(id)]);
    setE(em);
    setMeta(m);
    setOfertas(of);
  }, [id]);

  useEffect(() => {
    void reload().catch((err) => setError(String(err.message || err)));
  }, [reload]);

  // El catálogo de recursos (Sistema Nacional) solo hace falta para cargar lotes.
  const cargaLotes = user?.rol === "COORDINADOR" && e?.estado === "REGISTRADA";
  useEffect(() => {
    if (!cargaLotes) return;
    api
      .tiposRecurso()
      .then(setTipos)
      .catch((err) => setError(err instanceof Error ? err.message : "Error"));
  }, [cargaLotes]);

  if (!e) {
    return (
      <Shell>
        <div className="loading" style={{ minHeight: "40vh" }}>
          <div className="loading-dot" aria-hidden />
          <span>{error || "Cargando emergencia…"}</span>
        </div>
      </Shell>
    );
  }

  async function addLote(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const form = ev.currentTarget;
    const fd = new FormData(form);
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      await api.createLote(id, {
        tipo_recurso: String(fd.get("tipo_recurso")),
        detalle: String(fd.get("detalle") ?? "").trim() || undefined,
        cantidad: Number(fd.get("cantidad")),
        tipo: String(fd.get("tipo")),
      });
      form.reset();
      setOk("Lote agregado");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function publicar(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const fd = new FormData(ev.currentTarget);
    const iso = new Date(String(fd.get("ventana_fin"))).toISOString();
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      await api.publicar(id, iso);
      setOk("Convocatoria publicada");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function enviarOferta(
    items: { lote_id: number; recurso: string; cantidad: number }[],
    mensaje: (o: Oferta) => string,
  ) {
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      const o = await api.createOferta(id, items);
      setOk(mensaje(o));
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function oferta(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    if (!e) return;
    const fd = new FormData(ev.currentTarget);
    const items = e.lotes
      .map((l) => ({ lote_id: l.id, recurso: l.recurso, cantidad: Number(fd.get(`lote_${l.id}`) || 0) }))
      .filter((i) => i.cantidad > 0);
    if (!items.length) {
      setError("Indicá cuánto ofrecés para al menos un lote (o usá «Retirar mi oferta»).");
      return;
    }
    await enviarOferta(items, (o) => `Oferta enviada (versión ${o.version_actual})`);
  }

  const miOferta = user!.rol === "ONG" ? ofertas[0] : undefined;

  // Retirar = reenviar la oferta sin ese lote (versión nueva); sin ningún lote, la oferta queda retirada.
  const itemsVigentes = (miOferta && !miOferta.retirada ? miOferta.items : []).map(({ lote_id, recurso, cantidad }) => ({
    lote_id,
    recurso,
    cantidad,
  }));
  const retirarLote = (loteId: number) =>
    enviarOferta(
      itemsVigentes.filter((i) => i.lote_id !== loteId),
      (o) => (o.retirada ? "Retiraste tu oferta" : `Retiraste tu oferta a ese lote (versión ${o.version_actual})`),
    );

  const ventanaAbierta = !!e.ventana_ofertas_fin && new Date(e.ventana_ofertas_fin) > new Date();
  const cantidadOfrecida = (o: Oferta | undefined, loteId: number) =>
    o?.items.find((i) => i.lote_id === loteId)?.cantidad;

  return (
    <Shell>
      <motion.div {...fade}>
        <PageHeader
          to="/emergencias"
          label="Volver al listado"
          kicker="Detalle"
          title={`#${e.id} · ${meta?.tipos[e.tipo] ?? e.tipo}`}
          action={estadoBadge(e.estado)}
        />
        {error && <div className="alert">{error}</div>}
        {ok && <div className="alert ok">{ok}</div>}
        {e.tarea_bonita && (
          <div className="alert ok" data-testid="tarea-bonita">
            <strong>Bonita:</strong> tenés pendiente la tarea «{e.tarea_bonita}». Se cierra sola cuando vence la
            ventana de ofertas; no hace falta completarla, cargá tu oferta abajo.
          </div>
        )}

        <div className="meta-grid">
          <div className="meta-item">
            <span>Municipio</span>
            <strong>
              {e.municipio_nombre} ({e.municipio_provincia})
            </strong>
          </div>
          <div className="meta-item">
            <span>Gravedad</span>
            <strong>
              <span className={`badge g-${e.nivel_gravedad}`}>{e.nivel_gravedad}</span>
            </strong>
          </div>
          <div className="meta-item">
            <span>Zona</span>
            <strong>{e.zona_afectada}</strong>
          </div>
          <div className="meta-item">
            <span>Caso Bonita</span>
            <strong>{e.bonita_case_id ?? "pendiente"}</strong>
          </div>
          <div className="meta-item">
            <span>Registrada</span>
            <strong>{formatFecha(e.creada_en)}</strong>
          </div>
          <div className="meta-item">
            <span>Cierre de ofertas</span>
            <strong>{formatFecha(e.ventana_ofertas_fin)}</strong>
          </div>
          <div className="meta-item" style={{ gridColumn: "1 / -1" }}>
            <span>Descripción</span>
            <strong style={{ fontWeight: 500, whiteSpace: "pre-line" }}>{e.descripcion}</strong>
          </div>
        </div>

        <h2 className="section-title">Lotes de necesidades</h2>
        <div className="panel" style={{ marginBottom: "1.35rem" }}>
          {e.lotes.length === 0 ? (
            <div className="empty" style={{ padding: "1.25rem" }}>
              <p>El Centro Coordinador todavía no cargó lotes.</p>
            </div>
          ) : (
            e.lotes.map((l) => (
              <div className="lote-row" key={l.id}>
                <span>
                  <strong>
                    #{l.id} {l.recurso}
                  </strong>{" "}
                  · {l.cantidad} {l.unidad}
                </span>
                <span className="badge muted">{l.tipo}</span>
              </div>
            ))
          )}
        </div>

        {user!.rol === "COORDINADOR" && e.estado === "REGISTRADA" && (
          <div className="cards two" style={{ marginBottom: "1.35rem" }}>
            <form className="panel" onSubmit={addLote}>
              <h3>Agregar lote</h3>
              <div className="field">
                <label>Tipo de recurso</label>
                <select name="tipo_recurso" required defaultValue="">
                  <option value="" disabled>
                    Elegí un recurso…
                  </option>
                  {tipos.map((t) => (
                    <option key={t.codigo} value={t.codigo}>
                      {t.nombre} ({t.unidad})
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Detalle (opcional)</label>
                <input name="detalle" maxLength={80} placeholder="con equipo de trauma…" />
              </div>
              <div className="field">
                <label>Cantidad</label>
                <input name="cantidad" type="number" min={1} defaultValue={5} required />
              </div>
              <div className="field">
                <label>Tipo</label>
                <select name="tipo" defaultValue="PRINCIPAL">
                  <option value="PRINCIPAL">Principal</option>
                  <option value="APOYO">Apoyo</option>
                </select>
              </div>
              <button className="btn btn-primary" disabled={busy}>
                Agregar lote
              </button>
            </form>
            <form className="panel" onSubmit={publicar}>
              <h3>Publicar convocatoria</h3>
              <div className="field">
                <label>Cierre de ofertas</label>
                <input name="ventana_fin" type="datetime-local" required />
                <span className="hint">Tiene que ser una fecha futura.</span>
              </div>
              <button className="btn btn-primary" disabled={busy || e.lotes.length === 0}>
                Publicar a la red
              </button>
            </form>
          </div>
        )}

        {user!.rol === "ONG" && (e.estado === "CERRADA" || (e.estado === "CONVOCATORIA" && !ventanaAbierta)) && (
          <div className="alert" style={{ marginBottom: "1.35rem" }}>
            La ventana de ofertas cerró: {formatFecha(e.ventana_ofertas_fin)}
          </div>
        )}

        {user!.rol === "ONG" && e.estado === "CONVOCATORIA" && ventanaAbierta && (
          <form className="panel" style={{ maxWidth: 620, marginBottom: "1.35rem" }} onSubmit={oferta}>
            <h3>
              {itemsVigentes.length
                ? `Modificar oferta (vas por la versión ${miOferta!.version_actual})`
                : miOferta
                  ? `Cargar oferta (retiraste la anterior, versión ${miOferta.version_actual})`
                  : "Cargar oferta"}
            </h3>
            <p className="hint">
              Cada envío reemplaza la oferta completa y queda como una versión nueva. Dejá en 0 lo que no ofrecés. No podés
              ofrecer más de lo que tenés disponible, sumando tus ofertas en todas las convocatorias abiertas.
            </p>
            {e.lotes.map((l) => (
              <div className="field" key={`${l.id}-${miOferta?.version_actual ?? 0}`}>
                <label>
                  #{l.id} {l.recurso} (pedido {l.cantidad} {l.unidad})
                </label>
                <input
                  name={`lote_${l.id}`}
                  type="number"
                  min={0}
                  defaultValue={(!miOferta?.retirada && cantidadOfrecida(miOferta, l.id)) || 0}
                />
                {!!itemsVigentes.find((i) => i.lote_id === l.id) && (
                  <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void retirarLote(l.id)}>
                    Retirar de este lote
                  </button>
                )}
              </div>
            ))}
            <button className="btn btn-primary" disabled={busy}>
              Enviar oferta
            </button>
            {itemsVigentes.length > 0 && (
              <button
                type="button"
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => void enviarOferta([], () => "Retiraste tu oferta")}
              >
                Retirar mi oferta
              </button>
            )}
          </form>
        )}

        {ofertas.length > 0 && (
          <>
            <h2 className="section-title">{user!.rol === "ONG" ? "Mi oferta vigente" : "Ofertas recibidas"}</h2>
            <div className="panel" style={{ marginBottom: "1.35rem" }}>
              {ofertas.map((o) => (
                <div key={o.id} style={{ marginBottom: "0.75rem" }}>
                  <strong>{o.ong_nombre}</strong> <span className="badge muted">v{o.version_actual}</span>
                  {o.retirada && <span className="badge muted">retirada</span>}
                  {e.lotes.map((l) => {
                    const c = cantidadOfrecida(o, l.id);
                    return c ? (
                      <div className="lote-row" key={l.id}>
                        <span>
                          #{l.id} {l.recurso}
                        </span>
                        <span>
                          {c} / {l.cantidad} {l.unidad}
                        </span>
                      </div>
                    ) : null;
                  })}
                </div>
              ))}
            </div>
          </>
        )}

        <Link className="btn btn-ghost" to="/emergencias" style={{ display: "inline-flex" }}>
          ← Volver al listado
        </Link>
      </motion.div>
    </Shell>
  );
}
