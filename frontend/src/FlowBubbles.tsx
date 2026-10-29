import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

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

const TRAVEL_MS = 700;

export function FlowBubbles() {
  const [activeStep, setActiveStep] = useState(1);
  const [focus, setFocus] = useState<ZoneId | null>(null);
  const [phase, setPhase] = useState<Phase>("panorama");
  const [pinned, setPinned] = useState(false);

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
          <motion.div
            className="flow-panorama"
            animate={
              traveling && activeZone
                ? {
                    scale: 1.22,
                    x: activeZone.fly.x,
                    y: activeZone.fly.y,
                    filter: "blur(7px)",
                    opacity: 0.45,
                  }
                : phase === "scene"
                  ? {
                      scale: 1.1,
                      opacity: 0,
                      filter: "blur(10px)",
                      x: activeZone?.fly.x ?? 0,
                      y: activeZone?.fly.y ?? 0,
                    }
                  : { scale: 1, x: 0, y: 0, filter: "blur(0px)", opacity: 1 }
            }
            transition={{ duration: TRAVEL_MS / 1000, ease: [0.22, 1, 0.36, 1] }}
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
          </motion.div>

          {/* Destination scene */}
          <AnimatePresence>
            {inScene && (
              <motion.div
                key={activeZone.id}
                className="flow-destination"
                initial={{ opacity: 0, scale: 1.08, filter: "blur(10px)" }}
                animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
                exit={{ opacity: 0, scale: 1.04, filter: "blur(6px)" }}
                transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
              >
                <img
                  src={activeZone.scene}
                  alt={activeZone.label}
                  className="flow-destination-img"
                  width={1200}
                  height={675}
                  decoding="async"
                  draggable={false}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Travel streak */}
          <AnimatePresence>
            {traveling && (
              <motion.div
                className="flow-travel-veil"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25 }}
              >
                <span className="flow-travel-line" />
              </motion.div>
            )}
          </AnimatePresence>

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

          <AnimatePresence>
            {inScene && (
              <motion.button
                type="button"
                className="flow-reset"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                onClick={resetView}
              >
                Ver panorama
              </motion.button>
            )}
          </AnimatePresence>
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
