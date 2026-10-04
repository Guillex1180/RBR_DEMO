# Guía de contribución — RBR Airline Insight Engine

Gracias por tu interés en revisar o extender este laboratorio. Está pensado para
correr 100% en local y ser fácil de reconfigurar.

## Puesta en marcha

```bash
# 1. Clonar
git clone https://github.com/Guillex1180/RBR_DEMO.git
cd RBR_DEMO

# 2. (Opcional) entorno virtual
python3 -m venv .venv && source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate                             # Windows

# 3. Dependencias
pip install -r requirements.txt

# 4. Base de datos (reproducible)
python seed_generator.py

# 5. Servidor
uvicorn main:app --reload
```

Dashboard en `http://127.0.0.1:8000/` · Swagger en `/docs` · Login `admin` / `rbr2026`.

> Si el puerto 8000 está ocupado: `uvicorn main:app --reload --port 8080`.

## Correr los tests

```bash
pytest -q      # suite de regresión (API, agente, lógica no-code, LLM mock)
```

Todo cambio debería mantener la suite en verde. Si agregas una capacidad nueva,
acompáñala de un test en `tests/`.

## Reconfigurar

- **Datos**: `python seed_generator.py` regenera 250 PNRs (reproducible, `seed 42`).
  `python seed_generator.py --append N` agrega N sin borrar lo existente.
- **Escenarios**: edita el catálogo en `scenarios.py`, o ajusta reglas en caliente
  desde el panel "Editor de escenarios" del dashboard (persistido en `scenario_config`).
- **LLM**: copia `.env.example` a `.env` y añade una API key (OpenAI / Anthropic /
  Bedrock). Sin credenciales, el asistente usa su motor de reglas local.

## Estructura

Ver [`ARQUITECTURA.md`](./ARQUITECTURA.md) para el diagrama de componentes y
[`Configuracion.md`](./Configuracion.md) para el detalle de endpoints y entorno.

## Flujo de cambios

1. Crea una rama: `git checkout -b feature/mi-cambio`.
2. Haz tus cambios y añade tests.
3. Corre `pytest -q` (debe pasar).
4. Commit descriptivo y abre un Pull Request contra `main`.

## Alcance y uso

Proyecto de **uso interno para pruebas locales de los colaboradores**. Sin licencia
pública: no está destinado a distribución ni uso productivo. Datos **sintéticos**
(sin información real de pasajeros) y sin conexión a sistemas de reservas reales.

No subas credenciales: el archivo `.env` está en `.gitignore`.
