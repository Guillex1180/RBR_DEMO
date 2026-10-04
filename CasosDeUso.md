# Matriz de Casos de Uso — RBR Airline Engine (v0.4.0-Lab)

> Guía de pruebas locales para validar el laboratorio del Robot Balanceador de
> Reservas. Cada caso indica el **objetivo**, los **pasos**, el **resultado esperado**
> y cómo verificarlo desde la **interfaz web** o la **API**.
>
> Prerrequisito: haber ejecutado `python seed_generator.py` y tener el servidor
> corriendo (`uvicorn main:app --reload`). Login web: `admin` / `rbr2026`.

Leyenda de áreas: **F** = Finanzas · **S** = Soporte · **O** = Operaciones.

---

## A. Dashboard y métricas base

| ID | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| A-01 | Ver métricas globales | Abrir el dashboard | 5 tarjetas KPI: total PNRs (250), balanceados, desbalanceados, tasa de éxito (%) e ingresos pendientes |
| A-02 | Gráficos de operación | Observar los dos paneles superiores | Gráfico de tendencia de balanceo y distribución por escenarios coloreada por familia |
| A-03 | Filtrar PNRs | Usar los selectores Estado / Cola / Familia sobre la tabla | La tabla se filtra y el contador de resultados se actualiza |
| A-04 | Login y logout | Entrar con `admin`/`rbr2026`, luego "Salir" | Acceso al dashboard; logout regresa a la pantalla de login |

---

## B. Asistente RBR — 20 preguntas de auditoría

Abrir el widget flotante 🤖, elegir el **rol** y escribir (o usar un chip / el panel
"Auditoría e Insight"). Ninguna debe responder `unknown`.

### Bloque 1 · Diagnóstico general
| ID | Rol | Prompt de ejemplo | Resultado esperado |
|---|---|---|---|
| B1-01 | O | ¿Porcentaje de éxito de las últimas 24 horas y causas de fallo? | Tasa de éxito de la ventana + top códigos de error |
| B1-02 | O | ¿Cuántos PNR procesamos hoy, OK / error / sin procesar? | Conteo diario desglosado por resultado |
| B1-03 | O | ¿Qué escenarios generan más errores? | Ranking de escenarios por errores reales |
| B1-04 | O | Top 10 PNR con más errores del día | Lista con conteo y último error por PNR |
| B1-05 | O | ¿Patrón común entre los errores de 24h? | Origen dominante + código más frecuente |

### Bloque 2 · Análisis de escenarios
| ID | Rol | Prompt de ejemplo | Resultado esperado |
|---|---|---|---|
| B2-01 | O | ¿Qué escenario tiene la tasa de éxito más baja? | Escenario por **tasa** (OK/total), con causas |
| B2-02 | O | Auditoría del escenario 7 (OK vs fallidos) | Conteos + nota aclaratoria de catálogo (ver C-05) |
| B2-03 | O | Comparar escenario 7 entre ayer y hoy | Variación de tasa + mejora/degradación |
| B2-04 | O | ¿Algún escenario empezó a fallar más? | Anomalía con incremento de error ayer→hoy |
| B2-05 | O | ¿Qué escenarios generan más reintentos? | Ranking de reintentos + causa principal |

### Bloque 3 · PNR / Pasajeros
| ID | Rol | Prompt de ejemplo | Resultado esperado |
|---|---|---|---|
| B3-01 | S | PNR multipasajero con errores y su relación | Correlación nº pasajeros ↔ errores |
| B3-02 | S | ¿Algún PNR procesado repetidamente sin completar? | PNR en bucle (3+ ERROR, 0 OK) |
| B3-03 | S | PNR con más de un intento de procesamiento | Lista de PNR multi-intento |
| B3-04 | S | ¿PNR en estado inconsistente tras el proceso? | PNR con último run OK pero UNBALANCED (o viceversa) |
| B3-05 | S | ¿Errores concentrados en algún SSR (asiento/equipaje)? | Distribución de errores por código SSR |

### Bloque 4 · Balance / Deuda / Transacciones
| ID | Rol | Prompt de ejemplo | Resultado esperado |
|---|---|---|---|
| B4-01 | F | ¿Transacciones que más desbalancean? | PNR con balance ≠ 0 + frecuencia de TC |
| B4-02 | F | Casos con balance distinto de cero | Lista con transacciones que explican la diferencia |
| B4-03 | F | ¿Qué códigos TC aparecen más en fallidos? | Frecuencia TC/DD/AD/CC/CD/PC en casos ERROR |
| B4-04 | F | Deuda del cliente vs deuda de la aerolínea | Clasificación CLIENT vs AIRLINE con ejemplos |
| B4-05 | F | Clasifica errores de los últimos 7 días | DATA vs RBR_INTERNAL vs EXTERNAL (Navitaire/token) |

---

## C. Acciones del Asistente (escritura)

| ID | Rol | Prompt | Resultado esperado | Verificación |
|---|---|---|---|---|
| C-01 | O | `Balancea el PNR XXXXXX` (un UNBALANCED real) | Balanceo con explicabilidad: "aplicando el Escenario N - CODE" | El PNR pasa a BALANCED; pendiente = $0 |
| C-02 | O | `Balancea el PNR XXXXXX` (ya BALANCED) | "ya está BALANCED, no requiere acción" | Sin cambios |
| C-03 | F | `Agregar nota al PNR XXXXXX: Revisión por contracargo` | Nota registrada con autor = rol | Aparece el badge 📝 en la fila; nota en el modal |
| C-04 | F | `Agregar nota al PNR ZZZZZZ: ...` (PNR inexistente) | "No encontré el PNR ..." | No se crea nota |
| C-05 | O | `Auditoría del escenario Name Change Fee` | Audita la **familia** NAME_CHANGE_FEE (ids 19-24), no el #7 | Nota explica la ambigüedad de catálogo |

> **Nota de catálogo:** el negocio asume "Escenario 7 = Name Change Fee", pero en el
> catálogo técnico #7 = SHELL_UNUSED (Credit Shell). El agente responde el escenario real
> por número y mapea a la **familia** cuando se menciona "Name Change Fee".

---

## D. Módulo 2 — Línea de tiempo (Timeline)

| ID | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| D-01 | Abrir timeline | Clic sobre cualquier fila de la tabla de PNRs | Modal con la bitácora cronológica del PNR |
| D-02 | Evento de creación | Revisar el primer ítem | Evento `CREATED` con estado inicial y escenario |
| D-03 | Intentos del RBR | Revisar ítems de proceso | Eventos `PROCESS_ATTEMPT` con resultado y código de error |
| D-04 | Transición de estado | PNR que fue conciliado | Evento `STATE_CHANGE` UNBALANCED → BALANCED |
| D-05 | Notas en la línea | PNR con notas | Eventos `NOTE` con autor y texto |
| D-API | Vía API | `GET /api/v1/pnr/{pnr_id}/timeline` | JSON con `pnr`, `scenario` y `events[]` |

---

## E. Módulo 3 — Reportes y resumen ejecutivo

| ID | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| E-01 | Export CSV | Botón **⬇ CSV** en el dashboard | Descarga `rbr_pnrs_<fecha>.csv` con todas las columnas y pendiente |
| E-02 | Export Excel | Botón **⬇ Excel** | Descarga `.xlsx` (hoja "PNRs") |
| E-03 | Resumen ejecutivo | Botón **📄 Resumen ejecutivo** | Modal con informe de **3 párrafos** (estado, finanzas, riesgos) |
| E-04 | Indicador de modo | Observar el badge del modal | `motor local` sin credenciales; nombre del proveedor si hay LLM |
| E-API | Vía API | `POST /api/v1/agent/executive-summary` con `{"role":"Finanzas"}` | 3 párrafos + `data.mode` (`rules` o `live:<prov>`) |

---

## F. Módulo 4 — Predictivo y gestión no-code

| ID | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| F-01 | Alerta de ruta | Observar el banner superior | Rojo con rutas que superan 15% de error en 24h; verde si no hay |
| F-02 | Ajustar umbral (API) | `GET /api/v1/analytics/route-risk?threshold=25&min_pnrs=5` | Menos rutas al subir el umbral |
| F-03 | Ver matriz de reglas | Panel "Editor de escenarios" | 24 reglas con familia, umbrales y switch de activación |
| F-04 | Desactivar una regla | Mover el switch de un escenario y "Guardar" | La fila se atenúa; estado "actualizado ✓" |
| F-05 | Ajustar umbrales | Editar monto/tiempo y "Guardar" | Valores persistidos (verificables con `GET /scenarios/config`) |

---

## G. Importación en caliente (RBCheck)

| ID | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| G-01 | Balanceo manual | Escribir un PNR de 6 caracteres y "Balancear" | Resultado del balanceo con explicabilidad |
| G-02 | Importar JSON | Arrastrar un `.json` de PNRs a la zona de carga | "Importación (json)" con conteos insertados/actualizados |
| G-03 | Importar CSV | Arrastrar un `.csv` con encabezados | "Importación (csv)"; estado derivado si falta `balance_status` |
| G-04 | Archivo inválido | Subir un archivo mal formado | Mensaje de error claro, sin romper la base |

---

## H. Integración LLM y fallback

| ID | Caso | Configuración | Resultado esperado |
|---|---|---|---|
| H-01 | Fallback local | `.env` sin claves o `RBR_LLM_PROVIDER=rules` | Asistente y resumen operan con motor de reglas (`mode: rules`) |
| H-02 | Proveedor real | `.env` con una API key y `RBR_LLM_PROVIDER=auto` | El resumen ejecutivo se genera vía LLM (`mode: live:<prov>`) |
| H-03 | Falla de proveedor | Clave inválida con `provider` forzado | Fallback automático al motor local, sin caída del servicio |

---

## I. Matriz de verificación rápida (checklist)

Marca cada ítem tras la prueba:

- [ ] Dashboard carga con 250 PNRs y 5 KPIs
- [ ] Las 20 preguntas del asistente responden con datos (0 `unknown`)
- [ ] Balanceo de un PNR funciona y actualiza la tabla
- [ ] Nota interna se registra y aparece en el modal de notas
- [ ] Timeline abre al hacer clic en un PNR y muestra los 4 tipos de evento
- [ ] Export CSV y Excel descargan correctamente
- [ ] Resumen ejecutivo devuelve 3 párrafos
- [ ] Banner de alertas por ruta se muestra
- [ ] Editor de escenarios permite activar/desactivar y guardar umbrales
- [ ] Import JSON y CSV funcionan desde RBCheck
- [ ] `/docs` (Swagger) responde y lista todos los endpoints
