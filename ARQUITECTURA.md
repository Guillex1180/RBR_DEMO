# Arquitectura — RBR Airline Insight Engine (v0.5.0)

Vista de componentes del laboratorio local: frontend estático, backend FastAPI,
motor del agente con capa LLM opcional, base SQLite de 7 tablas y el generador de
semilla (full / incremental). La suite pytest verifica API y agente.

```mermaid
graph TB
    subgraph Cliente["Navegador"]
        UI["Dashboard (index.html)<br/>styles.css · app.js<br/>Login · KPIs · Timeline · RBCheck<br/>Editor no-code · Asistente RBR"]
    end

    subgraph Servidor["FastAPI — main.py (v0.5.0)"]
        API["API REST /api/v1/*<br/>metrics · pnrs · agent/query<br/>analytics/* · pnr/import<br/>pnr/balance-bulk · pnrs/export<br/>pnr/id/timeline · scenarios/config"]
        AGENT["agent_engine.py<br/>RBRAirlineAgent<br/>25 tools + balance-bulk<br/>gate no-code (scenario_config)"]
        LLM["llm_provider.py<br/>OpenAI / Anthropic / Bedrock<br/>fallback a reglas"]
        SCN["scenarios.py<br/>catálogo 25 escenarios"]
    end

    subgraph Datos["SQLite — rbr_local_lab.db"]
        T1["pnrs (250+)"]
        T2["processing_runs"]
        T3["pnr_passengers"]
        T4["transactions"]
        T5["pnr_audit_logs"]
        T6["internal_notes"]
        T7["scenario_config"]
    end

    subgraph Seed["seed_generator.py"]
        FULL["run_full() — reproducible seed 42"]
        APP["run_append(N) — incremental"]
    end

    subgraph Ext["LLM externo (opcional, vía .env)"]
        OAI["OpenAI"]
        ANT["Anthropic"]
        BED["Amazon Bedrock"]
    end

    TESTS["tests/ (pytest)<br/>35 tests de regresión"]

    UI -->|HTTP/JSON| API
    API --> AGENT
    AGENT --> SCN
    AGENT --> LLM
    AGENT -->|SQL| Datos
    API -->|SQL lectura| Datos
    LLM -.->|si hay credenciales| Ext
    Seed -->|crea / puebla| Datos
    TESTS -.->|verifica| API
    TESTS -.->|verifica| AGENT
```

## Flujo típico

1. El navegador carga el dashboard (`index.html` + `styles.css` + `app.js`) servido por FastAPI.
2. Las acciones del usuario llaman endpoints `/api/v1/*`.
3. El `RBRAirlineAgent` resuelve la intención: consulta SQLite y, para texto generativo (resumen ejecutivo), usa el LLM si hay credenciales o cae a reglas locales.
4. El balanceo (individual o masivo) respeta `scenario_config`: una regla desactivada no se concilia.
5. `seed_generator.py` crea la base reproducible (`run_full`) o agrega datos sin borrar (`run_append`).
