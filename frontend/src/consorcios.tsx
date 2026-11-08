import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, type Consorcio, type Emergencia, type Evaluacion, type MiembroConsorcio, type Oferta, type OngResumen, type Rol } from "./api";

type OngEvaluada = Evaluacion["ongs"][number];

export function ventanaAbierta(e: Emergencia) {
  return e.estado === "CONVOCATORIA" && !!e.ventana_ofertas_fin && new Date(e.ventana_ofertas_fin) > new Date();
}

const ESTADO_MIEMBRO: Record<MiembroConsorcio["estado"], string> = {
  INVITADA: "Invitación pendiente",
  ACEPTADA: "Aceptada",
  RECHAZADA: "Rechazada",
  SALIO: "Salió",
};

function etiquetaMiembro(m: MiembroConsorcio, abierta: boolean) {
  if (m.estado === "INVITADA" && !abierta) return "Invitación vencida";
  return ESTADO_MIEMBRO[m.estado];
}

// Consorcios de la emergencia. Para una ONG también resuelve cuál es su id: /api/ongs lista todas menos la propia,
// así que la propia es el miembro de algún consorcio que falta en ese listado.
export function useConsorcios(emergenciaId: number, rol: Rol | undefined) {
  const [consorcios, setConsorcios] = useState<Consorcio[]>([]);
  const [miOngId, setMiOngId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recargar = useCallback(async () => {
    if (!rol) return;
    try {
      const lista = await api.listConsorcios(emergenciaId);
      setConsorcios(lista);
      if (rol === "ONG") {
        const otras = new Set((await api.listOngs()).map((o) => o.id));
        const propia = lista.flatMap((c) => c.miembros).find((m) => !otras.has(m.ong_id));
        setMiOngId(propia ? propia.ong_id : null);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  }, [emergenciaId, rol]);

  useEffect(() => {
    void recargar();
  }, [recargar]);

  return { consorcios, miOngId, error, recargar };
}

export function ConsorcioPanel({
  e,
  ofertas,
  onCambio,
}: {
  e: Emergencia;
  ofertas: Oferta[];
  onCambio: () => void | Promise<void>;
}) {
  const { consorcios, miOngId, error: errorCarga, recargar } = useConsorcios(e.id, "ONG");
  const [disponibles, setDisponibles] = useState<OngResumen[]>([]);
  const [nombre, setNombre] = useState("");
  const [invitada, setInvitada] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const abierta = ventanaAbierta(e);
  const mio = consorcios.find(
    (c) =>
      !c.disuelto &&
      c.miembros.some((m) => m.ong_id === miOngId && (m.estado === "INVITADA" || m.estado === "ACEPTADA")),
  );
  const miMiembro = mio?.miembros.find((m) => m.ong_id === miOngId);
  const soyLider = !!mio && mio.ong_lider_id === miOngId;

  const puedeInvitar = soyLider && abierta;
  useEffect(() => {
    if (!puedeInvitar) return;
    api
      .listOngs(e.id)
      .then(setDisponibles)
      .catch((err) => setError(err instanceof Error ? err.message : "Error"));
  }, [puedeInvitar, e.id, consorcios]);

  async function accion(paso: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await paso();
      await recargar();
      await onCambio();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  function crear(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    void accion(async () => {
      await api.crearConsorcio(e.id, nombre.trim());
      setNombre("");
    });
  }

  function invitar(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    if (!mio || !invitada) return;
    void accion(async () => {
      await api.invitar(mio.id, Number(invitada));
      setInvitada("");
    });
  }

  const otrasOfertas = mio?.valido ? ofertas.filter((o) => o.ong_id !== miOngId && o.consorcio_id === mio.id) : [];

  return (
    <div className="panel" style={{ marginBottom: "1.35rem", maxWidth: 620 }} data-testid="consorcio">
      <h3>Consorcio</h3>
      {(error || errorCarga) && <div className="alert">{error || errorCarga}</div>}

      {!mio && (
        <>
          <p>
            Un consorcio junta a varias ONGs para cubrir un pedido. Cada una carga su propia oferta; si el Municipio
            adjudica, lo hace al consorcio completo.
          </p>
          {abierta ? (
            <form onSubmit={crear}>
              <div className="field">
                <label htmlFor="consorcio-nombre">Nombre del consorcio</label>
                <input
                  id="consorcio-nombre"
                  value={nombre}
                  onChange={(ev) => setNombre(ev.target.value)}
                  minLength={2}
                  maxLength={80}
                  required
                />
              </div>
              <button className="btn btn-primary" disabled={busy || nombre.trim().length < 2} data-testid="consorcio-crear">
                Crear consorcio
              </button>
            </form>
          ) : (
            <p style={{ marginBottom: 0 }}>No formás parte de ningún consorcio en esta emergencia.</p>
          )}
        </>
      )}

      {mio && (
        <>
          <p>
            <strong>{mio.nombre}</strong> <span className="badge muted">líder: {mio.ong_lider_nombre}</span>{" "}
            {!mio.valido && <span className="badge signal">todavía no es consorcio (hacen falta 2 ONGs aceptadas)</span>}
          </p>
          {mio.miembros.map((m) => (
            <div className="lote-row" key={m.ong_id}>
              <span>
                {m.ong_nombre} {m.ong_id === mio.ong_lider_id && <span className="badge muted">líder</span>}
              </span>
              <span className={`badge ${m.estado === "ACEPTADA" ? "ok" : "muted"}`}>{etiquetaMiembro(m, abierta)}</span>
            </div>
          ))}

          {miMiembro?.estado === "INVITADA" &&
            (abierta ? (
              <div className="actions" style={{ marginTop: "1rem" }}>
                <p>Te invitaron a este consorcio.</p>
                <button className="btn btn-primary" disabled={busy} onClick={() => void accion(() => api.responder(mio.id, true))} data-testid="consorcio-aceptar">
                  Aceptar invitación
                </button>{" "}
                <button className="btn btn-ghost" disabled={busy} onClick={() => void accion(() => api.responder(mio.id, false))} data-testid="consorcio-rechazar">
                  Rechazar
                </button>
              </div>
            ) : (
              <p style={{ marginBottom: 0 }}>La invitación venció porque la ventana de ofertas cerró.</p>
            ))}

          {puedeInvitar && (
            <form onSubmit={invitar} style={{ marginTop: "1rem" }}>
              <div className="field">
                <label htmlFor="consorcio-ong">Invitar a una ONG</label>
                <select id="consorcio-ong" value={invitada} onChange={(ev) => setInvitada(ev.target.value)}>
                  <option value="">Elegí una ONG…</option>
                  {disponibles.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.nombre}
                    </option>
                  ))}
                </select>
              </div>
              <button className="btn btn-primary" disabled={busy || !invitada} data-testid="consorcio-invitar">
                Invitar
              </button>
            </form>
          )}

          {abierta && soyLider && (
            <div className="actions" style={{ marginTop: "1rem" }}>
              <button className="btn btn-ghost" disabled={busy} onClick={() => void accion(() => api.disolverConsorcio(mio.id))} data-testid="consorcio-disolver">
                Disolver el consorcio
              </button>
            </div>
          )}
          {abierta && !soyLider && miMiembro?.estado === "ACEPTADA" && (
            <div className="actions" style={{ marginTop: "1rem" }}>
              <button className="btn btn-ghost" disabled={busy} onClick={() => void accion(() => api.salirConsorcio(mio.id))} data-testid="consorcio-salir">
                Salir del consorcio
              </button>
            </div>
          )}
          {!abierta && mio.valido && <p style={{ marginBottom: 0 }}>El consorcio quedó fijo: la ventana de ofertas cerró.</p>}

          {otrasOfertas.length > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <strong>Ofertas de los otros miembros (solo lectura)</strong>
              {otrasOfertas.map((o) => (
                <div key={o.id} style={{ marginTop: "0.5rem" }}>
                  {o.ong_nombre} {o.retirada && <span className="badge muted">retirada</span>}
                  {e.lotes.map((l) => {
                    const c = o.items.find((i) => i.lote_id === l.id)?.cantidad;
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
          )}
        </>
      )}
    </div>
  );
}

export type MiembroAdjudicable = {
  miembro: MiembroConsorcio;
  evaluada: OngEvaluada | null;
  reservada: boolean;
};

export type BloqueAdjudicable = {
  consorcio: Consorcio;
  miembros: MiembroAdjudicable[];
  cuits: string[]; // CUIT de los miembros con reserva: lo que agrega la casilla
};

export function agruparParaAdjudicar(ev: Evaluacion, consorcios: Consorcio[]) {
  const bloques: BloqueAdjudicable[] = [];
  const enBloque = new Set<string>();
  for (const consorcio of consorcios) {
    if (consorcio.disuelto || !consorcio.valido) continue;
    const aceptados = consorcio.miembros.filter((m) => m.estado === "ACEPTADA");
    if (aceptados.length < 2) continue;
    const miembros = aceptados.map((miembro) => {
      const evaluada = (miembro.cuit && ev.ongs.find((o) => o.cuit === miembro.cuit)) || null;
      return { miembro, evaluada, reservada: evaluada?.estado === "RESERVADA" };
    });
    for (const m of miembros) if (m.miembro.cuit) enBloque.add(m.miembro.cuit);
    bloques.push({
      consorcio,
      miembros,
      cuits: miembros.filter((m) => m.reservada).map((m) => m.miembro.cuit as string),
    });
  }
  const sueltas = ev.ongs.filter((o) => o.estado === "RESERVADA" && !enBloque.has(o.cuit));
  return { bloques, sueltas };
}

export function BloqueConsorcio({
  bloque,
  ev,
  elegidas,
  onToggle,
}: {
  bloque: BloqueAdjudicable;
  ev: Evaluacion;
  elegidas: string[];
  onToggle: (cuits: string[], marcado: boolean) => void;
}) {
  const { consorcio, miembros, cuits } = bloque;
  const marcado = cuits.length > 0 && cuits.every((c) => elegidas.includes(c));
  const reservadoPorLote = (loteId: number) =>
    miembros
      .filter((m) => m.reservada)
      .reduce((tot, m) => tot + (m.evaluada?.items.filter((i) => i.lote_id === loteId).reduce((s, i) => s + i.reservado, 0) ?? 0), 0);

  return (
    <div className="panel" style={{ marginBottom: "1rem" }} data-testid="bloque-consorcio">
      <strong>Consorcio «{consorcio.nombre}»</strong> <span className="badge muted">líder: {consorcio.ong_lider_nombre}</span>
      {miembros.map(({ miembro, evaluada, reservada }) => (
        <div className="lote-row" key={miembro.ong_id}>
          <span>
            <strong>{miembro.ong_nombre}</strong>{" "}
            {evaluada && evaluada.items.map((i) => `${i.ofrecido} × ${i.tipo_recurso}`).join(", ")}
          </span>
          {reservada ? (
            <span className="badge ok">
              reservado: {evaluada!.items.map((i) => `${i.reservado} × ${i.tipo_recurso}`).join(", ")}
            </span>
          ) : (
            <span className="badge muted">0 reservado · sin reserva, no se adjudica</span>
          )}
        </div>
      ))}
      {ev.lotes
        .filter((l) => miembros.some((m) => m.evaluada?.items.some((i) => i.lote_id === l.lote_id)))
        .map((l) => {
          const r = reservadoPorLote(l.lote_id);
          const pct = l.pedido > 0 ? Math.round((r / l.pedido) * 100) : 0;
          return (
            <div className="lote-row" key={l.lote_id}>
              <span>Cobertura del lote {l.tipo_recurso ?? `#${l.lote_id}`}</span>
              <strong>
                {r}/{l.pedido} ({pct} %)
              </strong>
            </div>
          );
        })}
      <label style={{ cursor: cuits.length ? "pointer" : "not-allowed", display: "block", marginTop: "0.75rem" }}>
        <input
          type="checkbox"
          checked={marcado}
          disabled={cuits.length === 0}
          onChange={(ev2) => onToggle(cuits, ev2.target.checked)}
          data-testid={`elegir-consorcio-${consorcio.id}`}
        />{" "}
        Adjudicar consorcio
        {cuits.length === 0 && " (ningún miembro tiene reserva)"}
      </label>
    </div>
  );
}
