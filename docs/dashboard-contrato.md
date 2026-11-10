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
- Bonita caído → **200** con `tiempos.disponible = false` y `motivo` descriptivo; el resto del reporte llega igual.

---

### GET `/api/indicadores/export.csv`

CSV de un bloque del reporte.

**Query params**

| Parámetro    | Tipo     | Requerido | Descripción                                               |
|--------------|----------|-----------|-----------------------------------------------------------|
| `bloque`     | `string` | Sí        | Uno de: `kpis`, `suministros`, `estados`, `tiempos`, `finalizadas` |
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

Período con datos, Bonita no disponible (bloque `tiempos` degradado):

```json
{
  "tiempos": {
    "disponible": false,
    "motivo": "Bonita no disponible: no se pudieron leer los tiempos por etapa.",
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
