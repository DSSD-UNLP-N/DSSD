# Prueba a mano de la Parada 2: decisión y adjudicación

Se hace en el navegador, con Bonita real. Dos casos en paralelo comparten la misma ventana de ofertas (tarda unos 8 minutos).
Los datos de la API Nacional están limpios (nada comprometido). Claves: todos los usuarios usan `demo1234`.

**Antes de empezar:** Bonita arriba (`http://localhost:8080/bonita`) con el proceso ejecutado, app en `:8001`, front en
`http://localhost:5173`, API Nacional en `:8002`. Si desplegaste de nuevo con Ejecutar, los casos viejos ya no existen: no los uses.

## Caso A: cobertura parcial (pide 10 paramédicos; Cruz Roja ofrece 4, Bomberos 2 → 60 %)

1. **`operador.municipal`** → *Nueva emergencia*: inundación, gravedad **ALTO**, zona "Prueba P2 A".
2. **`coordinador.regional`** → abrir la emergencia → agregar lote **PARAMEDICO, 10, PRINCIPAL**.
3. Todavía como Coordinador, **Publicar convocatoria** con el fin de ventana a **unos 3 minutos desde ahora** (hora local).
   Hacé el Caso B antes de que pase ese tiempo (pasos 1 a 3 y las ofertas), con el **mismo** fin de ventana.
4. **`ong.cruzroja`** → la emergencia → oferta **PARAMEDICO 4**. **`ong.bomberos`** → oferta **PARAMEDICO 2**.
5. Esperar a que venza la ventana y un poco más (Bonita consulta las ofertas, reserva en la API y avisa a la app: 10 a 60 s).
   Como Coordinador, recargar la emergencia: estado **En evaluación** y el panel *Evaluación de las ofertas* con cobertura **60 %**
   y las dos ONGs **RESERVADA**.
6. Debajo aparecen los botones. Elegir **Seguir con cobertura parcial** → estado **Adjudicación**.
7. **`operador.municipal`** → la emergencia → *Adjudicar ofertas* → tildar solo **Cruz Roja** → *Adjudicar a 1 ONG*.
   A los pocos segundos pasa a **En ejecución**.

**Qué tiene que pasar:**
- Cruz Roja ve su oferta **adjudicada**; Bomberos, **no adjudicada**; las dos ONGs tienen un aviso.
- API Nacional: `GET http://localhost:8002/ongs/30-54666544-5` → paramédicos comprometidos **4**; Bomberos (`30-68522415-9`) → **0**.
- Bonita (`http://localhost:8080/bonita`, `walter.bates` / `bpm`): el caso espera en **Monitorear Ejecucion del Despliegue**.

## Caso B: reformular (pide 3000 raciones; Cruz Roja ofrece 2000 → 66,7 %)

Se usan **raciones** y no agua: una oferta vieja de Cruz Roja (emergencia 1, 8000 L de agua) sigue ocupando el tope de agua.

1. **`operador.municipal`** → emergencia, gravedad **MEDIO**, zona "Prueba P2 B".
2. **`coordinador.regional`** → lote **RACION_ALIMENTO, 3000, PRINCIPAL** → publicar con el mismo fin de ventana que el Caso A.
3. **`ong.cruzroja`** → oferta **RACION_ALIMENTO 2000**.
4. Al vencer: *En evaluación*, cobertura **66,7 %**. El Coordinador elige **Reformular la convocatoria**.
5. La emergencia vuelve a **Registrada** con **ronda 2**; las ofertas viejas quedan retiradas pero siguen en el historial.
   La API Nacional libera la reserva (raciones comprometidas de Cruz Roja: **0**).
6. Coordinador: cargar de nuevo el lote **RACION_ALIMENTO 3000** → publicar con una ventana nueva (unos 2 minutos) →
   **`ong.cruzroja`** ofrece **3000**.
7. Al vencer: la cobertura es completa y **pasa directo a Adjudicación** (sin decidir). La referencia es `emg-ID-r2-CUIT`.
8. **`operador.municipal`** adjudica a Cruz Roja → **En ejecución**.

## Si algo no sale
- No pasa a *En evaluación* a los 2 minutos de vencer: mirar el caso en el portal de Bonita (tarea "Obtener Ofertas…" con error) y
  el log `workspace\tomcat\server\logs\bonita.log`; es el trabajo del subagente `lector-de-logs`.
- La oferta se rechaza por tope: sobran ofertas viejas en emergencias 1, 3 o 4; se retiran con el escenario o desde el usuario ONG.
- Todo en un solo comando, sin clics: `backend/.venv/Scripts/python.exe backend/scripts/escenario_adjudicacion.py`.
