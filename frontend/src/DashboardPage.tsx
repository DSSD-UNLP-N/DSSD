// Dashboard de indicadores del Auditor/Directivo. La base (tarjetas, barras, exportación) es de Leandro Masuda
// (feature/e4-metricas); los datos salen de GET /api/indicadores (docs/dashboard-contrato.md).
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
import { api, exportCsvUrl, type Reporte, type TipoRecurso } from "./api";
import { PageHeader } from "./PageHeader";
import { Shell } from "./pages";

const COLOR = { verde: "#1b6b45", petroleo: "#1a5c52", ambar: "#e08912", bordo: "#9f1239" };

function isoLocal(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function haceDias(dias: number) {
  const d = new Date();
  d.setDate(d.getDate() - dias);
  return isoLocal(d);
}

const num = (v: number) => v.toLocaleString("es-AR");
const dec = (v: number | null, sufijo = "", decimales = 1) =>
  v === null ? "—" : `${v.toLocaleString("es-AR", { maximumFractionDigits: decimales })}${sufijo}`;
// Las etapas reales duran horas; las corridas de prueba, segundos: por debajo de una hora se muestra en min o s.
const horas = (v: number | null) =>
  v === null ? "—" : v >= 1 ? dec(v, " h") : v * 60 >= 1 ? dec(v * 60, " min") : dec(v * 3600, " s", 0);

function download(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function MetricCard({ label, valor, color }: { label: string; valor: string; color: string }) {
  return (
    <article className="metric-card">
      <span className="metric-card-dot" style={{ background: color }} aria-hidden />
      <p>{label}</p>
      <strong>{valor}</strong>
    </article>
  );
}

type Barra = { clave: string; label: string; valor: number; texto: string; detalle: string };

// Barras horizontales de una sola unidad. Pasar el mouse muestra el valor exacto; tocar una barra la fija y muestra
// su detalle abajo.
function Barras({ barras, color, vacio }: { barras: Barra[]; color: string; vacio: string }) {
  const [elegida, setElegida] = useState<string | null>(null);
  const max = Math.max(...barras.map((b) => b.valor), 1);
  const detalle = barras.find((b) => b.clave === elegida)?.detalle;
  if (barras.length === 0) return <p className="chart-detalle">{vacio}</p>;
  return (
    <>
      <div className="chart-bars" role="list">
        {barras.map((b) => (
          <button
            key={b.clave}
            type="button"
            role="listitem"
            title={b.detalle}
            aria-label={b.detalle}
            aria-pressed={elegida === b.clave}
            className={`chart-bar${elegida === b.clave ? " selected" : ""}`}
            onClick={() => setElegida(elegida === b.clave ? null : b.clave)}
            style={{ "--bar-color": color, "--bar-size": `${(b.valor / max) * 100}%` } as CSSProperties}
          >
            <span className="chart-bar-label">{b.label}</span>
            <span className="chart-bar-track">
              <span className="chart-bar-fill" />
            </span>
            <strong>{b.texto}</strong>
          </button>
        ))}
      </div>
      <p className="chart-detalle" aria-live="polite">
        {detalle ?? "Tocá una barra para ver el detalle."}
      </p>
    </>
  );
}

function Panel({ titulo, kicker, bloque, desde, hasta, children }: {
  titulo: string; kicker: string; bloque: string; desde: string; hasta: string; children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="kicker">{kicker}</p>
          <h2>{titulo}</h2>
        </div>
        <a className="btn btn-ghost" href={exportCsvUrl(bloque, desde, hasta)} download>
          CSV
        </a>
      </div>
      {children}
    </section>
  );
}

function Suministros({ datos, nombres, desde, hasta }: {
  datos: Reporte["suministros"]; nombres: Map<string, TipoRecurso>; desde: string; hasta: string;
}) {
  // Un tipo de recurso por vez: sumar personas con raciones en una misma barra no dice nada.
  const tipos = [...new Set(datos.map((d) => d.tipo_recurso))];
  const [tipo, setTipo] = useState<string | null>(null);
  const actual = tipo && tipos.includes(tipo) ? tipo : tipos[0];
  const t = actual ? nombres.get(actual) : undefined;
  const unidad = t?.unidad ?? "";
  const barras: Barra[] = datos
    .filter((d) => d.tipo_recurso === actual)
    .map((d) => ({
      clave: d.mes,
      label: d.mes,
      valor: d.cantidad,
      texto: num(d.cantidad),
      detalle: `${d.mes}: ${num(d.cantidad)} ${unidad} de ${t?.nombre ?? actual} adjudicados`,
    }));
  return (
    <Panel titulo="Suministros movilizados por mes" kicker="Adjudicados" bloque="suministros" desde={desde} hasta={hasta}>
      {tipos.length > 1 && (
        <div className="chips" role="group" aria-label="Tipo de recurso">
          {tipos.map((c) => (
            <button key={c} type="button" className={`chip${c === actual ? " selected" : ""}`} onClick={() => setTipo(c)}>
              {nombres.get(c)?.nombre ?? c}
            </button>
          ))}
        </div>
      )}
      <Barras barras={barras} color={COLOR.petroleo} vacio="No hubo ofertas adjudicadas en el período." />
    </Panel>
  );
}

export function DashboardPage() {
  const [desde, setDesde] = useState(() => haceDias(183));
  const [hasta, setHasta] = useState(() => isoLocal(new Date()));
  const [reporte, setReporte] = useState<Reporte | null>(null);
  const [nombres, setNombres] = useState<Map<string, TipoRecurso>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    api.tiposRecurso().then((ts) => setNombres(new Map(ts.map((t) => [t.codigo, t])))).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (desde > hasta) {
      setError("La fecha desde no puede ser posterior a la fecha hasta.");
      return;
    }
    let activo = true;
    setCargando(true);
    setError(null);
    api
      .indicadores(desde, hasta)
      .then((r) => activo && setReporte(r))
      .catch((err) => activo && setError(err instanceof Error ? err.message : "No se pudieron cargar los indicadores"))
      .finally(() => activo && setCargando(false));
    return () => {
      activo = false;
    };
  }, [desde, hasta]);

  const r = reporte;
  return (
    <Shell>
      <div className="fade-in">
        <PageHeader
          to="/"
          label="Volver al panel"
          kicker="Auditor / Directivo"
          title="Dashboard de indicadores"
          lede="Datos de la app (emergencias, ofertas, consorcios) combinados con los tiempos de cada etapa registrados por Bonita."
          action={
            r && (
              <div className="export-actions">
                <a className="btn btn-ghost" href={exportCsvUrl("kpis", desde, hasta)} download>
                  CSV de indicadores
                </a>
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={() => download(`rescuesync-indicadores_${desde}_${hasta}.json`, JSON.stringify(r, null, 2), "application/json")}
                >
                  Exportar JSON
                </button>
              </div>
            )
          }
        />
        <div className="filtros panel">
          <div className="field">
            <label htmlFor="desde">Desde</label>
            <input id="desde" type="date" value={desde} max={hasta} onChange={(e) => e.target.value && setDesde(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="hasta">Hasta</label>
            <input id="hasta" type="date" value={hasta} min={desde} onChange={(e) => e.target.value && setHasta(e.target.value)} />
          </div>
          {cargando && <span className="chart-caption">Actualizando…</span>}
        </div>
        {error && <div className="alert" role="alert">{error}</div>}
        {!r && cargando && !error && <div className="panel">Cargando indicadores…</div>}
        {r && (
          <>
            <section className="metric-grid" aria-label="Indicadores clave" data-testid="kpis">
              <MetricCard label="Emergencias" valor={num(r.kpis.emergencias)} color={COLOR.petroleo} />
              <MetricCard label="Resueltas" valor={num(r.kpis.resueltas)} color={COLOR.verde} />
              <MetricCard label="En curso" valor={num(r.kpis.en_curso)} color={COLOR.ambar} />
              <MetricCard label="Resueltas con consorcio" valor={dec(r.kpis.pct_consorcio, " %")} color={COLOR.ambar} />
              <MetricCard label="Cobertura promedio" valor={dec(r.kpis.cobertura_promedio, " %")} color={COLOR.verde} />
              <MetricCard label="Alta → cierre (promedio)" valor={horas(r.tiempos.horas_total_promedio)} color={COLOR.bordo} />
            </section>
            <div className="dashboard-grid">
              <Suministros datos={r.suministros} nombres={nombres} desde={desde} hasta={hasta} />
              <Panel titulo="Estado de las emergencias" kicker="Proyectos" bloque="estados" desde={desde} hasta={hasta}>
                <Barras
                  color={COLOR.verde}
                  vacio="Sin emergencias en el período."
                  barras={r.estados.map((e) => ({
                    clave: e.estado,
                    label: e.etiqueta,
                    valor: e.cantidad,
                    texto: num(e.cantidad),
                    detalle: `${e.etiqueta}: ${num(e.cantidad)} ${e.cantidad === 1 ? "emergencia" : "emergencias"}`,
                  }))}
                />
              </Panel>
            </div>
            <Panel titulo="Tiempo promedio por etapa" kicker="Datos de Bonita" bloque="tiempos" desde={desde} hasta={hasta}>
              {r.tiempos.disponible ? (
                <Barras
                  color={COLOR.bordo}
                  vacio="Ninguna emergencia del período tiene tareas cerradas en Bonita."
                  barras={r.tiempos.etapas.map((t) => ({
                    clave: t.tarea,
                    label: t.tarea,
                    valor: t.horas_promedio,
                    texto: horas(t.horas_promedio),
                    detalle: `${t.tarea}: ${horas(t.horas_promedio)} en promedio, sobre ${t.emergencias} ${t.emergencias === 1 ? "emergencia" : "emergencias"}`,
                  }))}
                />
              ) : (
                <p className="chart-detalle" data-testid="tiempos-no-disponibles">
                  Tiempos no disponibles: {r.tiempos.motivo}
                </p>
              )}
            </Panel>
            <div style={{ height: "1rem" }} />
            <Panel titulo="Emergencias finalizadas" kicker="Cierre bilateral" bloque="finalizadas" desde={desde} hasta={hasta}>
              {r.finalizadas.length === 0 ? (
                <p className="chart-detalle">Ninguna emergencia se resolvió en el período.</p>
              ) : (
                <div className="tabla-scroll">
                  <table className="tabla">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Municipio</th>
                        <th>Tipo</th>
                        <th>Gravedad</th>
                        <th>ONGs</th>
                        <th>Consorcio</th>
                        <th>Duración</th>
                        <th>Cobertura</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.finalizadas.map((f) => (
                        <tr key={f.emergencia_id}>
                          <td>{f.emergencia_id}</td>
                          <td>{f.municipio}</td>
                          <td>{f.tipo}</td>
                          <td>{f.gravedad}</td>
                          <td>{f.ongs.join(", ") || "—"}</td>
                          <td>{f.consorcio ? "Sí" : "No"}</td>
                          <td>{horas(f.horas_total)}</td>
                          <td>{dec(f.cobertura, " %")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </>
        )}
      </div>
    </Shell>
  );
}
