# RBR Airline Insight Engine & Agent Lab

Laboratorio local del **Robot Balanceador de Reservas (RBR)** para la industria aérea.
Simula la conciliación de PNRs (reservas) con un backend FastAPI, base de datos SQLite,
un asistente de IA con *tool calling* y un dashboard web con estética de aerolínea.

**Versión:** v0.4.0-Lab · Corre 100% local, sin dependencias externas obligatorias.

---

## Qué hace

- **Balanceo de reservas** con 24 escenarios de desbalance (Seat Change, Credit Shell, Vouchers, Name Change Fee) y explicabilidad de la regla aplicada.
- **Asistente RBR**: responde en lenguaje natural las 20 preguntas de negocio de la auditoría (diagnóstico, escenarios, PNR/pasajeros, finanzas), con roles Finanzas / Soporte / Operaciones.
- **Dashboard**: KPIs, gráficos, tabla filtrable, línea de tiempo por PNR, alertas por ruta y editor no-code de reglas.
- **Reportes**: exportación CSV/Excel y resumen ejecutivo generativo de 3 párrafos.
- **IA opcional**: se conecta a OpenAI, Anthropic o Amazon Bedrock vía `.env`; si no hay credenciales, usa su motor de reglas local (*fallback* automático).

---

## Arranque rápido

```bash
pip install -r requirements.txt
python seed_generator.py && uvicorn main:app --reload
```

- Dashboard: `http://127.0.0.1:8000/`  ·  Swagger: `http://127.0.0.1:8000/docs`
- Login: `admin` / `rbr2026`
- Si el puerto 8000 está ocupado: `uvicorn main:app --reload --port 8080`

---

## Documentación

| Documento | Contenido |
|---|---|
| [`Configuracion.md`](./Configuracion.md) | Manual de instalación, variables de entorno, seed, endpoints y troubleshooting |
| [`CasosDeUso.md`](./CasosDeUso.md) | Matriz de casos de uso para pruebas locales + checklist de verificación |
| [`ARQUITECTURA.md`](./ARQUITECTURA.md) | Diagrama de arquitectura (componentes y flujo) |
| [`.env.example`](./.env.example) | Plantilla de credenciales (LLM opcional) |

## Tests

```bash
pip install -r requirements.txt
pytest -q        # suite de regresión (API, agente, no-code, LLM mock)
```

## Seed de datos

```bash
python seed_generator.py            # regenera 250 PNRs (reproducible, seed 42)
python seed_generator.py --append 50  # agrega 50 PNRs sin borrar los existentes
```

---

## Estructura del proyecto

```
KIRO_RBR/
├── main.py              # Servidor FastAPI: API REST + sirve el dashboard
├── agent_engine.py      # RBRAirlineAgent: 25 tools + capa LLM con fallback
├── llm_provider.py      # Selector de LLM (OpenAI / Anthropic / Bedrock)
├── scenarios.py         # Catálogo de los 25 escenarios de balanceo
├── seed_generator.py    # Genera rbr_local_lab.db + 250 PNRs sintéticos
├── requirements.txt     # Dependencias
├── .env.example         # Plantilla de entorno
├── static/
│   └── index.html       # Dashboard, RBCheck y widget del asistente
├── Configuracion.md     # Manual de configuración y despliegue
├── CasosDeUso.md        # Matriz de casos de uso
├── pnr_test_250.json    # Respaldo del dataset (250 PNRs)
└── pnr_seed_100.json    # Alias de compatibilidad
```

---

## Base de datos (SQLite)

El seed crea 7 tablas reproducibles (`random.seed(42)`): `pnrs` (250 reservas),
`internal_notes`, `processing_runs` (historial de intentos del RBR),
`pnr_passengers` (multipasajero + SSR), `transactions` (códigos TC/DD/AD/CC/CD/PC),
`pnr_audit_logs` (línea de tiempo) y `scenario_config` (reglas editables no-code).

---

## Integración con LLM (opcional)

Por defecto el asistente usa reglas SQL locales. Para habilitar un LLM real:

```bash
cp .env.example .env
# edita .env: RBR_LLM_PROVIDER=auto y una API key (OpenAI / Anthropic / Bedrock)
```

Si una llamada al proveedor falla, el sistema cae automáticamente al motor local
sin interrumpir el servicio. Ver detalles en [`Configuracion.md`](./Configuracion.md).

---

## Colaboradores

Proyecto de uso interno para **pruebas locales de los colaboradores**. Lee
[`CONTRIBUTING.md`](./CONTRIBUTING.md) para levantar el entorno y correr los tests.

## Uso

Sin licencia pública: su uso está limitado a los colaboradores autorizados para
pruebas locales. No está destinado a distribución ni uso productivo.

## Nota

Proyecto de laboratorio con datos **sintéticos** para demostración. No contiene datos
reales de pasajeros ni se conecta a sistemas de reservas productivos.
