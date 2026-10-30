import { type CSSProperties, useEffect, useState } from "react";

type ZoneId = "municipio" | "centro" | "ong" | "rescate" | "ambulancia";
type Phase = "panorama" | "traveling" | "scene";

type Zone = {
  id: ZoneId;
  step: 1 | 2 | 3 | 4;
  label: string;
  hint: string;
  scene: string;
  hit: { left: number; top: number; width: number; height: number };
  /** Direction the camera "flies" toward during travel. */
  fly: { x: number; y: number };
};

const ZONES: Zone[] = [
  {
    id: "municipio",
    step: 1,
    label: "Municipio",
    hint: "Alta de la emergencia",
    scene: "/scenes/municipio.jpg",
    hit: { left: 5, top: 10, width: 26, height: 36 },
    fly: { x: -40, y: -20 },
  },
  {
    id: "centro",
    step: 2,
    label: "Centro coordinador",
    hint: "Lotes y convocatoria",
    scene: "/scenes/centro.jpg",
    hit: { left: 33, top: 26, width: 28, height: 44 },
    fly: { x: 0, y: 10 },
  },
  {
    id: "ong",
    step: 3,
    label: "Red de ONGs",
    hint: "Ofertas de ayuda",
    scene: "/scenes/ong.jpg",
    hit: { left: 68, top: 6, width: 28, height: 42 },
    fly: { x: 45, y: -18 },
  },
  {
    id: "rescate",
    step: 1,
    label: "Equipo en campo",
    hint: "Respuesta operativa",
    scene: "/scenes/rescate.jpg",
    hit: { left: 2, top: 56, width: 28, height: 40 },
    fly: { x: -35, y: 35 },
  },
  {
    id: "ambulancia",
    step: 4,
    label: "Recursos y cierre",
    hint: "Adjudicación",
    scene: "/scenes/ambulancia.jpg",
    hit: { left: 68, top: 54, width: 30, height: 42 },
    fly: { x: 42, y: 32 },
  },
];

const STEPS = [
  {
    id: 1 as const,
    label: "Registrar",
    sub: "Municipio",
    detail: "Alta de la emergencia y arranque del caso en Bonita.",
    zone: "municipio" as ZoneId,
  },
  {
    id: 2 as const,
    label: "Lotes",
    sub: "Coordinador",
    detail: "Se desglosan necesidades y se publica la convocatoria.",
    zone: "centro" as ZoneId,
  },
  {
    id: 3 as const,
    label: "Ofertas",
    sub: "ONGs",
    detail: "La red carga ofertas dentro de la ventana de tiempo.",
    zone: "ong" as ZoneId,
  },
  {
    id: 4 as const,
    label: "Adjudicar",
    sub: "Cierre",
    detail: "Se eligen ofertas, se comprometen recursos y se cierra.",
    zone: "ambulancia" as ZoneId,
  },
];

const TRAVEL_MS = 700; // = transition of .flow-panorama in styles.css

export function FlowBubbles() {
  const [activeStep, setActiveStep] = useState(1);
  const [focus, setFocus] = useState<ZoneId | null>(null);
  const [phase, setPhase] = useState<Phase>("panorama");
  const [pinned, setPinned] = useState(false);
  /** Scenes mounted so far: they stay mounted so they can fade out with CSS. */
  const [seen, setSeen] = useState<ZoneId[]>([]);
  /** Bumped on every trip so the travel streak animation restarts. */
  const [trip, setTrip] = useState(0);

  const activeZone = focus ? ZONES.find((z) => z.id === focus) ?? null : null;
  const inScene = phase === "scene" && activeZone;
  const traveling = phase === "traveling";

  useEffect(() => {
    if (pinned || focus) return;
    const id = window.setInterval(() => {
      setActiveStep((prev) => {
        const idx = STEPS.findIndex((s) => s.id === prev);
        return STEPS[(idx + 1) % STEPS.length].id;
      });
    }, 4200);
    return () => window.clearInterval(id);
  }, [pinned, focus]);

  function startJourney(zoneId: ZoneId) {
    const zone = ZONES.find((z) => z.id === zoneId);
    if (!zone) return;
    if (focus === zoneId && phase === "scene") return;
    setPinned(true);
    setFocus(zoneId);
    setActiveStep(zone.step);
    setSeen((s) => (s.includes(zoneId) ? s : [...s, zoneId]));
    setTrip((t) => t + 1);
    setPhase("traveling");
    window.setTimeout(() => setPhase("scene"), TRAVEL_MS);
  }

  function focusStep(stepId: number) {
    const step = STEPS.find((s) => s.id === stepId);
    if (!step) return;
    if (focus === step.zone && phase === "scene") return;
    startJourney(step.zone);
  }

  function resetView() {
    setTrip((t) => t + 1);
    setPhase("traveling");
    window.setTimeout(() => {
      setFocus(null);
      setPhase("panorama");
    }, 480);
  }

  return (
    <div className="flow-scene" aria-label="Flujo RescueSync">
      <div className="flow-art">
        <div className="flow-stage">
          {/* Panorama base */}
          <div
            className={`flow-panorama ${traveling && activeZone ? "is-traveling" : phase === "scene" ? "is-scene" : ""}`}
            style={
              {
                "--fly-x": `${activeZone?.fly.x ?? 0}px`,
                "--fly-y": `${activeZone?.fly.y ?? 0}px`,
              } as CSSProperties
            }
          >
            <img
              src="/hero-dssd.png"
              alt="Red de coordinación RescueSync"
              className="flow-art-img"
              width={1774}
              height={887}
              decoding="async"
              draggable={false}
            />
          </div>

          {/* Destination scenes */}
          {ZONES.filter((zone) => seen.includes(zone.id)).map((zone) => (
            <div
              key={zone.id}
              className={`flow-destination ${inScene && activeZone.id === zone.id ? "is-on" : ""}`}
            >
              <img
                src={zone.scene}
                alt={zone.label}
                className="flow-destination-img"
                width={1200}
                height={675}
                decoding="async"
                draggable={false}
              />
            </div>
          ))}

          {/* Travel streak */}
          <div className={`flow-travel-veil ${traveling ? "is-on" : ""}`} aria-hidden>
            <span key={trip} className="flow-travel-line" />
          </div>

          {/* Hotspots only on panorama */}
          {phase === "panorama" && (
            <div className="flow-hotspots">
              {ZONES.map((zone) => (
                <button
                  key={zone.id}
                  type="button"
                  className="flow-hotspot"
                  style={{
                    left: `${zone.hit.left}%`,
                    top: `${zone.hit.top}%`,
                    width: `${zone.hit.width}%`,
                    height: `${zone.hit.height}%`,
                  }}
                  aria-label={`Viajar a ${zone.label}`}
                  onClick={() => startJourney(zone.id)}
                >
                  <span className="flow-hotspot-pulse" />
                  <span className="flow-hotspot-dot" />
                </button>
              ))}
            </div>
          )}

          <button type="button" className={`flow-reset ${inScene ? "is-on" : ""}`} onClick={resetView}>
            Ver panorama
          </button>
        </div>

      </div>

      <ol className="flow-steps">
        {STEPS.map((step) => {
          const isActive = activeStep === step.id;
          return (
            <li key={step.id}>
              <button
                type="button"
                className={`flow-step ${isActive ? "is-active" : ""}`}
                aria-pressed={isActive}
                aria-label={`${step.label}: ${step.detail}`}
                onClick={() => focusStep(step.id)}
                onMouseEnter={() => {
                  if (!focus) {
                    setPinned(true);
                    setActiveStep(step.id);
                  }
                }}
                onMouseLeave={() => {
                  if (!focus) setPinned(false);
                }}
              >
                <span className="flow-step-num">{step.id}</span>
                <span className="flow-step-text">
                  <strong>{step.label}</strong>
                  <small>{step.sub}</small>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
