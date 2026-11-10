import { type FormEvent, useEffect, useState } from "react";
import { api, type InventarioOng, type TipoRecurso } from "./api";
import { PageHeader } from "./PageHeader";
import { Shell } from "./pages";

// Total nuevo por tipo de recurso, como lo escribe la persona (texto del input).
type Totales = Record<string, string>;

function totalesDe(ficha: InventarioOng): Totales {
  return Object.fromEntries(ficha.inventario.map((i) => [i.tipo_recurso, String(i.cantidad_total)]));
}

export function InventarioPage() {
  const [ficha, setFicha] = useState<InventarioOng | null>(null);
  const [tipos, setTipos] = useState<TipoRecurso[]>([]);
  const [totales, setTotales] = useState<Totales>({});
  const [nuevo, setNuevo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([api.inventario(), api.tiposRecurso()])
      .then(([f, t]) => {
        setFicha(f);
        setTotales(totalesDe(f));
        setTipos(t);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "No se pudo cargar el inventario"));
  }, []);

  const actual = new Map(ficha?.inventario.map((i) => [i.tipo_recurso, i]) ?? []);
  const nombre = new Map(tipos.map((t) => [t.codigo, `${t.nombre} (${t.unidad})`]));
  const filas = Object.keys(totales);
  const sinDeclarar = tipos.filter((t) => !(t.codigo in totales));
  // Solo se manda lo que cambió: Nacional hace upsert y lo demás queda igual.
  const cambios = filas
    .map((codigo) => ({ tipo_recurso: codigo, cantidad_total: Math.max(0, Math.floor(Number(totales[codigo]) || 0)) }))
    .filter((r) => actual.get(r.tipo_recurso)?.cantidad_total !== r.cantidad_total);

  function agregar() {
    if (!nuevo) return;
    setTotales((t) => ({ ...t, [nuevo]: "0" }));
    setNuevo("");
  }

  async function guardar(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!cambios.length) return;
    setBusy(true);
    setError(null);
    setOk(false);
    try {
      const f = await api.declararInventario(cambios);
      setFicha(f);
      setTotales(totalesDe(f));
      setOk(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el inventario");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <div className="fade-in">
        <PageHeader
          to="/"
          label="Volver al panel"
          kicker="ONG"
          title="Mi inventario"
          lede="Lo que tu organización tiene declarado en el Sistema Nacional. Lo comprometido está reservado o adjudicado en emergencias abiertas y no se puede bajar."
        />
        {ok && <div className="alert ok">Inventario actualizado en el Sistema Nacional.</div>}
        {error && <div className="alert">{error}</div>}
        {!ficha && !error && <div className="panel">Cargando inventario…</div>}
        {ficha && (
          <div className="form-layout">
            <form className="panel" onSubmit={guardar} data-testid="inventario">
              <h3>{ficha.nombre} · CUIT {ficha.cuit}</h3>
              {filas.length === 0 && <p className="empty">Todavía no declaraste ningún rubro.</p>}
              {filas.map((codigo) => {
                const i = actual.get(codigo);
                const minimo = i?.cantidad_comprometida ?? 0;
                return (
                  <div className="lote-row" key={codigo} data-testid={`rubro-${codigo}`}>
                    <span>
                      <strong>{i ? `${i.nombre} (${i.unidad})` : (nombre.get(codigo) ?? codigo)}</strong>
                      <br />
                      {i ? (
                        <>
                          <span className="badge ok">{i.disponible} disponibles</span>{" "}
                          <span className="badge muted">{i.cantidad_comprometida} comprometidos</span>{" "}
                          {!i.riesgo_permitido && <span className="badge signal">Sin certificación vigente</span>}
                        </>
                      ) : (
                        <span className="badge signal">Nuevo</span>
                      )}
                    </span>
                    <span className="field" style={{ margin: 0, flex: "0 0 7.5rem" }}>
                      <label htmlFor={`total-${codigo}`}>Total</label>
                      <input
                        id={`total-${codigo}`}
                        style={{ width: "100%", minWidth: 0 }}
                        type="number"
                        min={minimo}
                        step={1}
                        value={totales[codigo]}
                        onChange={(ev) => setTotales((t) => ({ ...t, [codigo]: ev.target.value }))}
                        required
                      />
                    </span>
                  </div>
                );
              })}
              {sinDeclarar.length > 0 && (
                <div className="field-row two" style={{ marginTop: "1rem" }}>
                  <div className="field">
                    <label htmlFor="nuevo-rubro">Agregar rubro</label>
                    <select id="nuevo-rubro" value={nuevo} onChange={(ev) => setNuevo(ev.target.value)}>
                      <option value="">Elegí un tipo de recurso</option>
                      {sinDeclarar.map((t) => (
                        <option key={t.codigo} value={t.codigo}>
                          {t.nombre} ({t.unidad})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-actions">
                    <button className="btn btn-ghost" type="button" onClick={agregar} disabled={!nuevo}>
                      Agregar
                    </button>
                  </div>
                </div>
              )}
              <div className="form-actions">
                <button className="btn btn-primary" disabled={busy || cambios.length === 0}>
                  {busy ? "Guardando…" : "Guardar cambios"}
                </button>
              </div>
            </form>
            <aside className="panel form-side" data-testid="certificaciones">
              <h3>Certificaciones</h3>
              {ficha.certificaciones.length === 0 && <p className="empty">Sin certificaciones registradas.</p>}
              {ficha.certificaciones.map((c) => (
                <div className="lote-row" key={c.codigo}>
                  <span>
                    <strong>{c.nombre}</strong>
                    <br />
                    Hasta riesgo {c.riesgo_max.toLowerCase()} · vence el{" "}
                    {new Date(`${c.vence_el}T00:00:00`).toLocaleDateString("es-AR")}
                  </span>
                  <span className={`badge ${c.vigente ? "ok" : "signal"}`}>{c.vigente ? "Vigente" : "Vencida"}</span>
                </div>
              ))}
            </aside>
          </div>
        )}
      </div>
    </Shell>
  );
}
