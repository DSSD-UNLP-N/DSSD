import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Suministro = { mes: string; tipo_recurso: string; cantidad: number };
type Estado = { estado: string; etiqueta: string; cantidad: number };
type Etapa = { tarea: string; horas_promedio: number; emergencias: number };

type Props = {
  suministros: Suministro[];
  estados: Estado[];
  tiempos: { disponible: boolean; motivo: string | null; etapas: Etapa[] };
};

type Vista = "suministros" | "estados" | "tiempos";
type DatoMensual = { mes: string; [recurso: string]: string | number };

const COLORES = ["#12665a", "#e08912", "#337da1", "#b44b35", "#789447", "#735a8f"];

function formatoMes(mes: string) {
  const [anio, numero] = mes.split("-").map(Number);
  return new Intl.DateTimeFormat("es-AR", { month: "short", year: "2-digit" })
    .format(new Date(anio, numero - 1, 1))
    .replace(".", "");
}

export function IndicadoresChart({ suministros, estados, tiempos }: Props) {
  const [vista, setVista] = useState<Vista>("suministros");
  const mensual = new Map<string, DatoMensual>();

  for (const fila of suministros) {
    const mes = mensual.get(fila.mes) ?? { mes: fila.mes };
    mes[fila.tipo_recurso] = (Number(mes[fila.tipo_recurso]) || 0) + fila.cantidad;
    mensual.set(fila.mes, mes);
  }

  const datosMensuales = [...mensual.values()].sort((a, b) => a.mes.localeCompare(b.mes));
  const recursos = [...new Set(suministros.map((fila) => fila.tipo_recurso))];
  const estadosConDatos = estados.filter((fila) => fila.cantidad > 0);

  return (
    <section className="indicadores-chart" aria-label="Gráfico interactivo de indicadores">
      <div className="indicadores-chart-tabs" role="group" aria-label="Métrica a visualizar">
        {([
          ["suministros", "Suministros"],
          ["estados", "Estados"],
          ["tiempos", "Tiempos por etapa"],
        ] as const).map(([valor, etiqueta]) => (
          <button
            key={valor}
            type="button"
            className={vista === valor ? "activo" : ""}
            aria-pressed={vista === valor}
            onClick={() => setVista(valor)}
          >
            {etiqueta}
          </button>
        ))}
      </div>

      <div className="indicadores-chart-plot">
        {vista === "suministros" && (datosMensuales.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={datosMensuales} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid vertical={false} stroke="#d8ddd8" />
              <XAxis dataKey="mes" tickFormatter={formatoMes} tickLine={false} axisLine={false} />
              <YAxis width={44} tickLine={false} axisLine={false} />
              <Tooltip labelFormatter={(valor) => formatoMes(String(valor))} />
              <Legend />
              {recursos.map((recurso, indice) => (
                <Bar
                  key={recurso}
                  dataKey={recurso}
                  name={recurso}
                  stackId="suministros"
                  fill={COLORES[indice % COLORES.length]}
                  maxBarSize={48}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        ) : <p className="indicadores-chart-empty">No hay suministros adjudicados en este período.</p>)}

        {vista === "estados" && (estadosConDatos.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={estadosConDatos} dataKey="cantidad" nameKey="etiqueta" innerRadius="48%" outerRadius="72%" paddingAngle={3}>
                {estadosConDatos.map((fila, indice) => (
                  <Cell key={fila.estado} fill={COLORES[indice % COLORES.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        ) : <p className="indicadores-chart-empty">No hay emergencias en este período.</p>)}

        {vista === "tiempos" && (!tiempos.disponible ? (
          <p className="indicadores-chart-empty">{tiempos.motivo ?? "Los tiempos de Bonita no están disponibles."}</p>
        ) : tiempos.etapas.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={tiempos.etapas} layout="vertical" margin={{ top: 8, right: 16, left: 12, bottom: 4 }}>
              <CartesianGrid horizontal={false} stroke="#d8ddd8" />
              <XAxis type="number" tickLine={false} axisLine={false} unit=" h" />
              <YAxis type="category" dataKey="tarea" width={220} tickLine={false} axisLine={false} />
              <Tooltip formatter={(valor) => [`${valor} h`, "Promedio"]} />
              <Bar dataKey="horas_promedio" name="Horas promedio" fill="#12665a" radius={[0, 4, 4, 0]} maxBarSize={26} />
            </BarChart>
          </ResponsiveContainer>
        ) : <p className="indicadores-chart-empty">Todavía no hay tiempos registrados por etapa.</p>)}
      </div>
    </section>
  );
}