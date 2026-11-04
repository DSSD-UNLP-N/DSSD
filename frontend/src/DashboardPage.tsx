import { useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { motion } from "framer-motion";
import { api, type MetricasLocales } from "./api";
import { useAuth } from "./auth";
import { PageHeader } from "./PageHeader";
import { Shell } from "./pages";

type Indicador = {
  key: keyof MetricasLocales;
  label: string;
  shortLabel: string;
  format: (value: number) => string;
  color: string;
};

const INDICADORES: Indicador[] = [
  {
    key: "proyectos_finalizados",
    label: "Proyectos finalizados",
    shortLabel: "Proyectos",
    format: (value) => value.toLocaleString("es-AR"),
    color: "#1b6b45",
  },
  {
    key: "suministros_movilizados",
    label: "Suministros movilizados",
    shortLabel: "Suministros",
    format: (value) => value.toLocaleString("es-AR"),
    color: "#1a5c52",
  },
  {
    key: "porcentaje_consorcios",
    label: "Resolución por consorcios",
    shortLabel: "Consorcios",
    format: (value) => `${value.toFixed(2)}%`,
    color: "#e08912",
  },
  {
    key: "tiempo_promedio_resolucion_horas",
    label: "Tiempo promedio de resolución",
    shortLabel: "Tiempo Bonita",
    format: (value) => `${value.toFixed(2)} h`,
    color: "#9f1239",
  },
];

function download(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function exportCsv(metrics: MetricasLocales) {
  const rows = [
    ["indicador", "valor"],
    ["proyectos_finalizados", String(metrics.proyectos_finalizados)],
    ["suministros_movilizados", String(metrics.suministros_movilizados)],
    ["porcentaje_consorcios", String(metrics.porcentaje_consorcios)],
    ["tiempo_promedio_resolucion_horas", String(metrics.tiempo_promedio_resolucion_horas)],
  ];
  download(
    "rescuesync-metricas.csv",
    rows.map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\n"),
    "text/csv;charset=utf-8",
  );
}

function exportJson(metrics: MetricasLocales) {
  download("rescuesync-metricas.json", JSON.stringify(metrics, null, 2), "application/json");
}

function MetricCard({ indicator, value }: { indicator: Indicador; value: number }) {
  return (
    <article className="metric-card">
      <span className="metric-card-dot" style={{ background: indicator.color }} aria-hidden />
      <p>{indicator.label}</p>
      <strong>{indicator.format(value)}</strong>
    </article>
  );
}

function MetricsChart({ metrics }: { metrics: MetricasLocales }) {
  const [selected, setSelected] = useState<keyof MetricasLocales>("proyectos_finalizados");
  const max = Math.max(...INDICADORES.map(({ key }) => metrics[key]), 1);

  return (
    <section className="panel metrics-chart" aria-labelledby="chart-title">
      <div className="panel-heading">
        <div>
          <p className="kicker">Comparativa</p>
          <h2 id="chart-title">Indicadores del sistema</h2>
        </div>
        <span className="chart-caption">Seleccioná una barra para resaltarla</span>
      </div>
      <div className="chart-bars" role="list" aria-label="Gráfico de indicadores">
        {INDICADORES.map((indicator) => {
          const value = metrics[indicator.key];
          const selectedClass = selected === indicator.key ? " selected" : "";
          return (
            <button
              className={`chart-bar${selectedClass}`}
              key={indicator.key}
              type="button"
              onClick={() => setSelected(indicator.key)}
              style={{ "--bar-color": indicator.color, "--bar-size": `${(value / max) * 100}%` } as React.CSSProperties}
              role="listitem"
              aria-label={`${indicator.label}: ${indicator.format(value)}`}
            >
              <span className="chart-bar-label">{indicator.shortLabel}</span>
              <span className="chart-bar-track">
                <span className="chart-bar-fill" />
              </span>
              <strong>{indicator.format(value)}</strong>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const [metrics, setMetrics] = useState<MetricasLocales | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .getMetricasLocales()
      .then((data) => {
        if (active) setMetrics(data);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "No se pudieron cargar las métricas.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const values = useMemo(
    () => (metrics ? INDICADORES.map((indicator) => ({ indicator, value: metrics[indicator.key] })) : []),
    [metrics],
  );

  if (user?.rol !== "AUDITOR") {
    return <Navigate to="/" replace />;
  }

  return (
    <Shell>
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}>
        <PageHeader
          to="/"
          label="Volver al panel"
          kicker="Auditoría · Etapa 4"
          title="Dashboard de indicadores"
          lede="Una vista consolidada de la operación local y los tiempos informados por Bonita."
          action={
            metrics && (
              <div className="export-actions">
                <button className="btn btn-ghost" type="button" onClick={() => exportCsv(metrics)}>
                  Exportar CSV
                </button>
                <button className="btn btn-primary" type="button" onClick={() => exportJson(metrics)}>
                  Exportar JSON
                </button>
              </div>
            )
          }
        />
        {loading && <div className="panel dashboard-message">Cargando indicadores…</div>}
        {error && (
          <div className="panel dashboard-message error-message" role="alert">
            No se pudo cargar el dashboard: {error}
          </div>
        )}
        {metrics && !error && (
          <>
            <section className="metric-grid" aria-label="Indicadores clave">
              {values.map(({ indicator, value }) => (
                <MetricCard indicator={indicator} value={value} key={indicator.key} />
              ))}
            </section>
            <MetricsChart metrics={metrics} />
          </>
        )}
      </motion.div>
    </Shell>
  );
}
