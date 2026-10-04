# Manual de Configuración y Despliegue Local — RBR Airline Engine (v0.4.0-Lab)

> Este manual cubre la instalación, configuración y arranque del laboratorio local
> del **Robot Balanceador de Reservas (RBR)**. La versión actual del proyecto es
> **v0.4.0-Lab**, que incluye todo lo de la v0.3.0 (motor de reglas, 20 analíticas de
> auditoría, dashboard) más los módulos avanzados: integración LLM real con fallback,
> línea de tiempo por PNR, exportación CSV/Excel, resumen ejecutivo generativo,
> alertas tempranas por ruta y editor no-code de escenarios.

---

## 1. Requisitos Previos

- **Python 3.9 o superior** (el laboratorio se validó con Python 3.14).
- **Git** y **pip** instalados.
- **Navegador web** moderno (Chrome, Edge o Firefox).
- Conexión a internet **solo** si deseas usar un LLM real (OpenAI / Anthropic / Bedrock).
  Sin credenciales, la aplicación funciona 100% local con su motor de reglas.

---

## 2. Instalación de dependencias

Desde la raíz del proyecto:

```bash
# (opcional pero recomendado) entorno virtual
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# instalar dependencias
pip install -r requirements.txt
```

El archivo `requirements.txt` incluye:

| Librería | Uso |
|---|---|
| `fastapi` | Framework del servidor API |
| `uvicorn` | Servidor ASGI de desarrollo |
| `python-multipart` | Carga de archivos (import de PNRs) |
| `python-dotenv` | Lectura de variables de entorno desde `.env` |
| `boto3` | Cliente de Amazon Bedrock (LLM, opcional) |
| `pandas` | Exportación de reportes CSV/Excel |
| `openpyxl` | Escritura de archivos `.xlsx` |

---

## 3. Estrategia de Variables de Entorno (`.env`)

La aplicación es **local-first**: si no configuras ninguna credencial, el Asistente RBR
usa su motor de reglas SQL (fallback) sin llamadas externas. Para habilitar un LLM real,
copia la plantilla y completa **solo** el proveedor que uses:

```bash
cp .env.example .env
```

Estructura del `.env`:

```env
# ---- Configuración del entorno local ----
PORT=8000
ENVIRONMENT=local_lab

# Proveedor de LLM: rules | auto | openai | anthropic | bedrock
#   rules  -> fuerza el motor local (sin llamadas externas)
#   auto   -> detecta el primer proveedor con credenciales
RBR_LLM_PROVIDER=rules

# ---- Tokens para LLMs (opcional) ----
# Si se dejan vacíos, se usa el motor de reglas local.
OPENAI_API_KEY=
# OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_API_KEY=
# ANTHROPIC_MODEL=claude-3-5-sonnet-latest

# ---- Credenciales AWS (opcional, para Amazon Bedrock) ----
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=us-east-1
# BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0
```

> **Seguridad:** el archivo `.env` está incluido en `.gitignore` y nunca debe
> subirse al repositorio. Comparte únicamente `.env.example` (sin valores reales).

### Cómo se resuelve el proveedor

1. Si `RBR_LLM_PROVIDER=rules` (o vacío) → siempre motor local.
2. Si `RBR_LLM_PROVIDER=openai|anthropic|bedrock` → usa ese proveedor **si** hay credenciales; si faltan, cae a motor local.
3. Si `RBR_LLM_PROVIDER=auto` → toma el primer proveedor con credenciales disponibles.
4. Si una llamada al LLM falla (red, token inválido, librería ausente) → **fallback automático** al motor local, sin interrumpir el servicio.

---

## 4. Generación de la Base de Datos (Seed)

El proyecto usa **SQLite local** (`rbr_local_lab.db`). El generador crea las 7 tablas y
las puebla con datos sintéticos **reproducibles** (`random.seed(42)`):

```bash
python seed_generator.py
```

Salida esperada (resumen):

```
Total PNRs:                250  (BALANCED 100 / UNBALANCED 150)
Notas internas:            12
Pasajeros (multipax):      632
Processing runs:           ~451  (OK / ERROR / UNPROCESSED)
Transacciones:             ~315
Audit logs (timeline):     ~713
Config de escenarios:      25 reglas editables
```

Esto también exporta dos respaldos JSON:
- `pnr_test_250.json` (dataset principal de 250 PNRs)
- `pnr_seed_100.json` (alias de compatibilidad)

### Tablas creadas

| Tabla | Contenido |
|---|---|
| `pnrs` | 250 reservas (tarifa, pago, estado, cola, escenario) |
| `internal_notes` | Notas internas entre departamentos |
| `processing_runs` | Historial de intentos del RBR (OK/ERROR/UNPROCESSED, origen de error, reintentos) |
| `pnr_passengers` | Pasajeros por PNR (multipasajero) con códigos SSR |
| `transactions` | Transacciones financieras (TC/DD/AD/CC/CD/PC) con deudor CLIENT/AIRLINE |
| `pnr_audit_logs` | Bitácora cronológica por PNR (línea de tiempo) |
| `scenario_config` | Configuración editable (no-code) de las 24 reglas de balanceo |

---

## 5. Arranque del Servidor

Comando único (seed + servidor):

```bash
python seed_generator.py && uvicorn main:app --reload
```

Por defecto Uvicorn escucha en el puerto **8000**. Si está ocupado, especifica otro:

```bash
uvicorn main:app --reload --port 8080
```

### Accesos

| Recurso | URL |
|---|---|
| Dashboard web | `http://127.0.0.1:8000/` |
| Documentación OpenAPI (Swagger) | `http://127.0.0.1:8000/docs` |
| Métricas (JSON) | `http://127.0.0.1:8000/api/v1/metrics` |

**Credenciales de la interfaz web:** usuario `admin` · contraseña `rbr2026`.

---

## 6. Mapa de Endpoints (API v1)

### Núcleo
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/metrics` | Métricas globales + ingresos pendientes |
| GET | `/api/v1/pnrs` | Lista filtrable de PNRs con notas |
| POST | `/api/v1/agent/query` | Asistente RBR (`{role, prompt}`) |
| POST | `/api/v1/pnr/import` | Carga en caliente (JSON / CSV) |
| GET | `/api/v1/scenarios` | Catálogo de los 25 escenarios |

### Analítica de auditoría (Bloques 1-4)
| Método | Ruta |
|---|---|
| GET | `/api/v1/analytics/success-rate` · `daily-counts` · `scenario-error-ranking` · `top-error-pnrs` · `failure-patterns` |
| GET | `/api/v1/analytics/lowest-success-scenario` · `scenario-audit` · `scenario-compare` · `anomalies` · `retry-analysis` |
| GET | `/api/v1/analytics/multipax-errors` · `loops` · `attempt-history` · `inconsistent-states` · `ssr-concentration` |
| GET | `/api/v1/analytics/unbalanced-transactions` · `tc-frequency` · `debt-classification` · `failure-origin-7d` |

### Módulos avanzados (v0.4.0)
| Método | Ruta | Módulo |
|---|---|---|
| GET | `/api/v1/analytics/route-risk` | Alertas tempranas por ruta |
| POST | `/api/v1/agent/executive-summary` | Resumen ejecutivo generativo (3 párrafos) |
| GET | `/api/v1/pnrs/export?format=csv\|excel` | Exportación de reportes |
| GET | `/api/v1/pnr/{pnr_id}/timeline` | Línea de tiempo del PNR |
| GET | `/api/v1/scenarios/config` | Configuración de reglas (no-code) |
| PUT | `/api/v1/scenarios/config/{scenario_id}` | Activar/desactivar y ajustar umbrales |

---

## 7. Solución de Problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Base de datos no encontrada` (HTTP 503) | No se ejecutó el seed | Corre `python seed_generator.py` |
| `address already in use` al arrancar | Puerto 8000 ocupado | Usa `--port 8080` u otro libre |
| El asistente responde en modo `rules` esperando un LLM | No hay credenciales o `RBR_LLM_PROVIDER=rules` | Configura `.env` y pon `RBR_LLM_PROVIDER=auto` |
| `ModuleNotFoundError` (fastapi, pandas, etc.) | Dependencias no instaladas | `pip install -r requirements.txt` |
| El export Excel falla | Falta `openpyxl` | `pip install openpyxl` |

---

## 8. Reinicio Limpio

Para volver al estado inicial reproducible:

```bash
# detén el servidor (Ctrl+C) y regenera los datos
python seed_generator.py
```

El `seed(42)` garantiza que la base vuelva siempre al mismo estado, útil para
auditorías y demostraciones consistentes.
