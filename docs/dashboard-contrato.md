# Contrato del endpoint de indicadores

Documento de referencia para el equipo de frontend que implementa los gráficos del dashboard.

---

## Autenticación y permisos

- Todos los endpoints requieren sesión activa (cookie de sesión del login `/api/auth/login`).
- Solo el rol `AUDITOR` tiene acceso. Otros roles reciben **403**, sin sesión **401**.

---

## Endpoints

### GET `/api/indicadores`

Reporte completo en JSON.

**Query params**

| Parámetro    | Tipo    | Requerido | Default          | Descripción                            |
|--------------|---------|-----------|------------------|----------------------------------------|
| `desde`      | `date`  | No        | Hoy − 6 meses   | Inicio del período (`YYYY-MM-DD`)      |
| `hasta`      | `date`  | No        | Hoy              | Fin del período (`YYYY-MM-DD`)         |
| `municipio_id` | `int` | No        | —                | Filtrar por municipio; sin valor: todos|

**Errores**

| Código | Situación                                                   |
|--------|-------------------------------------------------------------|
| 401    | Sin sesión                                                  |
| 403    | Rol distinto de AUDITOR                                     |
| 422    | `desde` > `hasta`, o formato de fecha inválido (`YYYY-MM-DD` esperado) |

**Notas**
- `municipio_id` inexistente → **200** con todo en cero, no 404.
- Bonita caído → **200** con `tiempos`, `cursos` y `casos` en `disponible = false` y `motivo` descriptivo; el resto del reporte llega igual.

---

### GET `/api/indicadores/export.csv`

CSV de un bloque del reporte.

**Query params**

| Parámetro    | Tipo     | Requerido | Descripción                                               |
|--------------|----------|-----------|-----------------------------------------------------------|
| `bloque`     | `string` | Sí        | Uno de: `kpis`, `suministros`, `estados`, `tiempos`, `cursos`, `casos`, `finalizadas` |
| `desde`      | `date`   | No        | Igual que el endpoint JSON                                |
| `hasta`      | `date`   | No        | Igual que el endpoint JSON                                |
| `municipio_id` | `int`  | No        | Igual que el endpoint JSON                                |

**Respuesta**
- `Content-Type: text/csv; charset=utf-8`
- `Content-Disposition: attachment; filename="indicadores_<bloque>_<desde>_<hasta>.csv"`
- Cuerpo: UTF-8 con BOM (`\xef\xbb\xbf`), separador coma, CRLF.
- Si el período no tiene datos, solo se devuelven los encabezados (sin filas).

**Errores**

| Código | Situación                       |
|--------|---------------------------------|
| 401    | Sin sesión                      |
| 403    | Rol distinto de AUDITOR         |
| 422    | Bloque inválido, o fechas inválidas |

**Encabezados por bloque**

| Bloque       | Encabezados (en orden)                                                        |
|--------------|-------------------------------------------------------------------------------|
| `kpis`       | Emergencias, Resueltas, En curso, % Consorcio, Cobertura promedio (%)         |
| `suministros`| Mes, Tipo de recurso, Cantidad                                                |
| `estados`    | Estado, Etiqueta, Cantidad                                                    |
| `tiempos`    | Tarea, Horas promedio, Emergencias                                            |
| `cursos`     | Curso, Etiqueta, Emergencias, Veces, Cobertura promedio (%)                   |
| `casos`      | Casos abiertos, Casos archivados, Consistentes, Inconsistentes (ids), Horas de resolución (Bonita) |
| `finalizadas`| ID, Municipio, Tipo, Gravedad, ONGs, Consorcio, Horas total (h), Cobertura (%)|

---

## Schema de respuesta JSON: `Reporte`

```typescript
interface Filtros {
  desde: string;        // "YYYY-MM-DD"
  hasta: string;        // "YYYY-MM-DD"
  municipio_id: number | null;
}

interface Kpis {
  emergencias: number;
  resueltas: number;
  en_curso: number;
  pct_consorcio: number | null;    // null si no hay resueltas
  cobertura_promedio: number | null; // null si ninguna fue evaluada
}

interface SuministroMes {
  mes: string;          // "YYYY-MM"
  tipo_recurso: string; // ej. "RACION_ALIMENTO" o "Sin tipo"
  cantidad: number;
}

interface EstadoCantidad {
  estado: string;    // valor del enum, ej. "RESUELTA"
  etiqueta: string;  // texto para mostrar, ej. "Resuelta"
  cantidad: number;
}

interface TiempoEtapa {
  tarea: string;         // nombre de la tarea en Bonita
  horas_promedio: number;
  emergencias: number;   // cuántas emergencias contribuyeron al promedio
}

interface Tiempos {
  disponible: boolean;
  motivo: string | null;             // presente solo cuando disponible=false
  etapas: TiempoEtapa[];            // vacío cuando disponible=false
  horas_total_promedio: number | null; // promedio de alta→cierre de las resueltas
}

// De dónde sale: las tareas humanas completadas de cada caso en Bonita (archivedFlowNode) dicen qué curso tomó;
// la cobertura final sale de la base de la app. Cada REFORMULAR vuelve a «Revisar», cada REABRIR vuelve a «Publicar» sin
// «Revisar»; al llegar a «Adjudicar» el caso cuenta como TOTAL (sin «Evaluar» en la última ronda) o PARCIAL.
interface CursoAccion {
  curso: "TOTAL" | "PARCIAL" | "REFORMULAR" | "REABRIR";  // siempre los cuatro, en este orden
  etiqueta: string;
  emergencias: number;              // emergencias que pasaron por ese curso
  veces: number;                    // una emergencia puede reformular o reabrir más de una vez
  cobertura_promedio: number | null; // cobertura final (app) de esas emergencias
}

interface Cursos {
  disponible: boolean;
  motivo: string | null;
  filas: CursoAccion[];             // vacío cuando disponible=false
}

// Estado del caso en Bonita (GET /API/bpm/case/{id}; si da 404, /API/bpm/archivedCase) contra la app:
// resuelta en la app = caso archivado; cualquier otro estado = caso abierto.
interface Casos {
  disponible: boolean;
  motivo: string | null;
  abiertos: number;
  archivados: number;
  consistentes: number;
  inconsistentes: number[];         // ids de emergencia que no coinciden (o cuyo caso Bonita ya no conoce)
  horas_resolucion_promedio: number | null; // Bonita: end_date - start de los casos archivados
}

interface Finalizada {
  emergencia_id: number;
  municipio: string;
  tipo: string;        // etiqueta legible, ej. "Inundación"
  gravedad: string;    // valor del enum, ej. "ALTO"
  ongs: string[];      // nombres de las ONGs adjudicadas, ordenados
  consorcio: boolean;
  horas_total: number | null;  // null si no cerró con validación bilateral
  cobertura: number | null;    // 0-100, null si no se evaluó
}

interface Reporte {
  filtros: Filtros;
  generado_en: string;  // ISO 8601 UTC, ej. "2026-11-09T18:30:00Z"
  kpis: Kpis;
  suministros: SuministroMes[];
  estados: EstadoCantidad[];
  tiempos: Tiempos;
  cursos: Cursos;
  casos: Casos;
  finalizadas: Finalizada[];
}
```

---

## Ejemplo de respuesta completa

Período con datos, Bonita disponible:

```json
{
  "filtros": {
    "desde": "2026-05-09",
    "hasta": "2026-11-09",
    "municipio_id": null
  },
  "generado_en": "2026-11-09T18:30:00.123456Z",
  "kpis": {
    "emergencias": 14,
    "resueltas": 9,
    "en_curso": 5,
    "pct_consorcio": 33.3,
    "cobertura_promedio": 87.0
  },
  "suministros": [
    { "mes": "2026-09", "tipo_recurso": "RACION_ALIMENTO", "cantidad": 1200 },
    { "mes": "2026-10", "tipo_recurso": "PARAMEDICO",      "cantidad": 8    },
    { "mes": "2026-10", "tipo_recurso": "RACION_ALIMENTO", "cantidad": 500  }
  ],
  "estados": [
    { "estado": "REGISTRADA",    "etiqueta": "Registrada",          "cantidad": 0 },
    { "estado": "CONVOCATORIA",  "etiqueta": "Convocatoria abierta","cantidad": 2 },
    { "estado": "CERRADA",       "etiqueta": "Ventana cerrada",     "cantidad": 1 },
    { "estado": "EN_EVALUACION", "etiqueta": "En evaluación",       "cantidad": 1 },
    { "estado": "ADJUDICACION",  "etiqueta": "Adjudicación",        "cantidad": 0 },
    { "estado": "EN_EJECUCION",  "etiqueta": "En ejecución",        "cantidad": 1 },
    { "estado": "RESUELTA",      "etiqueta": "Resuelta",            "cantidad": 9 }
  ],
  "tiempos": {
    "disponible": true,
    "motivo": null,
    "etapas": [
      { "tarea": "Revisar Informacion y Generar Lotes de Necesidades",    "horas_promedio": 1.5,  "emergencias": 9 },
      { "tarea": "Publicar Convocatoria y Notificar a la Red de ONGs",    "horas_promedio": 0.8,  "emergencias": 9 },
      { "tarea": "Cargar Ofertas de Ayuda",                               "horas_promedio": 24.3, "emergencias": 7 },
      { "tarea": "Evaluar Cobertura y Definir Curso de Accion",           "horas_promedio": 3.2,  "emergencias": 7 },
      { "tarea": "Adjudicar Ofertas",                                     "horas_promedio": 6.5,  "emergencias": 7 },
      { "tarea": "Monitorear Ejecucion del Despliegue",                   "horas_promedio": 12.0, "emergencias": 6 },
      { "tarea": "Confirmar Finalizacion de Actividades",                 "horas_promedio": 4.1,  "emergencias": 5 },
      { "tarea": "Validar Cierre Operativo Bilateral",                    "horas_promedio": 1.2,  "emergencias": 5 }
    ],
    "horas_total_promedio": 48.3
  },
  "cursos": {
    "disponible": true,
    "motivo": null,
    "filas": [
      { "curso": "TOTAL",      "etiqueta": "Cobertura total: directo a adjudicar", "emergencias": 5, "veces": 5, "cobertura_promedio": 100.0 },
      { "curso": "PARCIAL",    "etiqueta": "Continuar con cobertura parcial",      "emergencias": 2, "veces": 2, "cobertura_promedio": 60.0 },
      { "curso": "REFORMULAR", "etiqueta": "Reformular lotes",                     "emergencias": 1, "veces": 1, "cobertura_promedio": 100.0 },
      { "curso": "REABRIR",    "etiqueta": "Reabrir convocatoria",                 "emergencias": 2, "veces": 3, "cobertura_promedio": 85.0 }
    ]
  },
  "casos": {
    "disponible": true, "motivo": null, "abiertos": 5, "archivados": 9, "consistentes": 14,
    "inconsistentes": [], "horas_resolucion_promedio": 47.9
  },
  "finalizadas": [
    {
      "emergencia_id": 3,
      "municipio": "Bahía Blanca",
      "tipo": "Inundación",
      "gravedad": "ALTO",
      "ongs": ["Cruz Roja Argentina", "Bomberos Voluntarios"],
      "consorcio": true,
      "horas_total": 36.2,
      "cobertura": 90.0
    },
    {
      "emergencia_id": 7,
      "municipio": "Bahía Blanca",
      "tipo": "Incendio",
      "gravedad": "MEDIO",
      "ongs": ["Cruz Roja Argentina"],
      "consorcio": false,
      "horas_total": 60.5,
      "cobertura": null
    }
  ]
}
```

Período con datos, Bonita no disponible (`tiempos` degradado; `cursos` y `casos` llegan igual con `disponible: false`, sin datos):

```json
{
  "tiempos": {
    "disponible": false,
    "motivo": "Bonita no disponible: no se pudieron leer los datos del motor.",
    "etapas": [],
    "horas_total_promedio": 48.3
  }
}
```

> `horas_total_promedio` se calcula desde la base de la app (alta → cierre validado), independientemente de Bonita. Puede tener valor aunque `disponible` sea `false`.

---

## Notas de implementación frontend

- El campo `estados` siempre devuelve los 7 estados del enum, incluso con `cantidad: 0`. Útil para mantener el orden del eje en gráficos de barras horizontales.
- El campo `suministros` solo incluye los (mes, tipo_recurso) con `cantidad > 0`.
- El campo `etapas` dentro de `tiempos` solo incluye las tareas que tuvieron al menos una emergencia en el período. El orden es el del flujo del proceso (ver schema).
- Para la descarga de JSON, el front puede serializar `body` directamente desde la respuesta ya cargada (es el mismo objeto).
- Para la descarga de CSV, construir la URL con los mismos filtros activos y usarla como `href` de un `<a>` con `download`.
