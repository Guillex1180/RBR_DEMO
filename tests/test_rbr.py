"""
Suite de regresion del RBR Airline Insight Engine.

Cubre:
    - Las 20 preguntas de auditoria (ninguna devuelve intent 'unknown').
    - Endpoints clave del API (metrics, pnrs, analytics, timeline, config, export).
    - Logica no-code: un escenario DESACTIVADO no se balancea.
    - Balanceo masivo por cola/escenario/familia respetando reglas OFF.

Estrategia de aislamiento:
    - Los tests de SOLO LECTURA (preguntas, endpoints GET) corren contra el API
      con la base de desarrollo recien sembrada (fixture de sesion).
    - Los tests que MUTAN datos (no-code gate, balanceo masivo) usan una base
      SQLite temporal propia y el agente directamente, para no ensuciar la
      base de desarrollo ni depender del orden de ejecucion.

Ejecucion:
    pytest -q
"""

import importlib
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import seed_generator  # noqa: E402
import agent_engine     # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    """Regenera la base de desarrollo una vez para toda la sesion de tests."""
    subprocess.run([sys.executable, "seed_generator.py"], cwd=BASE_DIR, check=True,
                   capture_output=True)
    yield


@pytest.fixture(scope="session")
def client(seeded_db):
    """TestClient del API FastAPI (requiere httpx)."""
    from fastapi.testclient import TestClient
    import main
    importlib.reload(main)
    return TestClient(main.app)


@pytest.fixture()
def temp_agent():
    """Agente contra una base temporal recien sembrada (para tests que mutan)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Construir el esquema y datos en la base temporal reutilizando el generador.
    orig = seed_generator.DB_PATH
    seed_generator.DB_PATH = path
    try:
        import random
        random.seed(42)
        pnrs = seed_generator.generate_pnrs()
        notes = seed_generator.seed_notes(pnrs)
        passengers, pax_count = seed_generator.seed_passengers(pnrs)
        runs = seed_generator.seed_runs(pnrs, pax_count)
        err = {r["pnr_id"] for r in runs if r["result"] == "ERROR"}
        txns = seed_generator.seed_transactions(pnrs, err)
        audit = seed_generator.seed_audit_logs(pnrs, runs, notes)
        cfg = seed_generator.seed_scenario_config()
        conn = sqlite3.connect(path)
        seed_generator.create_schema(conn)
        seed_generator.insert_pnrs(conn, pnrs)
        seed_generator.insert_notes(conn, notes)
        seed_generator.insert_runs(conn, runs)
        seed_generator.insert_passengers(conn, passengers)
        seed_generator.insert_transactions(conn, txns)
        seed_generator.insert_audit_logs(conn, audit)
        seed_generator.insert_scenario_config(conn, cfg)
        conn.close()
    finally:
        seed_generator.DB_PATH = orig

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    agent = agent_engine.RBRAirlineAgent(conn)
    yield agent
    conn.close()
    os.remove(path)


# --------------------------------------------------------------------------- #
# Las 20 preguntas de auditoria
# --------------------------------------------------------------------------- #
QUESTIONS = [
    ("Operaciones", "¿Cuál fue el porcentaje de éxito del RBR durante las últimas 24 horas y las causas de fallo?"),
    ("Operaciones", "¿Cuántos PNR procesamos hoy, OK, con error o sin procesar?"),
    ("Operaciones", "¿Cuáles son los escenarios que están generando más errores?"),
    ("Operaciones", "Muéstrame los 10 PNR con más errores del día"),
    ("Operaciones", "¿Hay algún patrón común entre los errores de las últimas 24 horas?"),
    ("Operaciones", "¿Qué escenario tiene la tasa de éxito más baja y qué errores lo provocan?"),
    ("Operaciones", "Para el escenario 7, ¿cuántos se procesaron bien y cuántos fallaron?"),
    ("Operaciones", "Comparar el escenario 7 entre ayer y hoy"),
    ("Operaciones", "¿Existe algún escenario que haya comenzado a fallar más que antes?"),
    ("Operaciones", "¿Qué escenarios generan más reintentos y por qué?"),
    ("Soporte", "Busca PNR con múltiples pasajeros que presentaron errores y su relación"),
    ("Soporte", "¿Hay algún PNR procesado repetidamente sin completarse?"),
    ("Soporte", "Muéstrame los PNR con más de un intento de procesamiento"),
    ("Soporte", "¿Hay PNR en estado inconsistente tras el procesamiento?"),
    ("Soporte", "¿Los errores están concentrados en algún código SSR como asientos o equipaje?"),
    ("Finanzas", "¿Qué transacciones generan diferencias de balance con mayor frecuencia?"),
    ("Finanzas", "Muéstrame los casos con balance distinto de cero y sus transacciones"),
    ("Finanzas", "¿Qué códigos de transacción aparecen más en los casos fallidos?"),
    ("Finanzas", "Identifica deuda del cliente versus deuda de la aerolínea con ejemplos"),
    ("Finanzas", "Analiza y clasifica el origen de los errores de los últimos 7 días"),
]


@pytest.mark.parametrize("role,prompt", QUESTIONS, ids=[f"Q{i+1}" for i in range(len(QUESTIONS))])
def test_audit_questions_no_unknown(client, role, prompt):
    resp = client.post("/api/v1/agent/query", json={"role": role, "prompt": prompt})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] != "unknown", f"Pregunta cayo en unknown: {prompt}"
    assert data["tool"] is not None
    assert data["answer"]


# --------------------------------------------------------------------------- #
# Endpoints clave (solo lectura)
# --------------------------------------------------------------------------- #
def test_metrics(client):
    d = client.get("/api/v1/metrics").json()
    assert d["total_pnrs"] == 250
    assert d["balanced"] + d["unbalanced"] == 250
    assert d["version"].startswith("0.5")


def test_pnrs_list(client):
    d = client.get("/api/v1/pnrs").json()
    assert d["count"] == 250
    assert "notes" in d["pnrs"][0]


def test_timeline(client):
    pid = client.get("/api/v1/pnrs").json()["pnrs"][0]["pnr_id"]
    d = client.get(f"/api/v1/pnr/{pid}/timeline").json()
    assert d["pnr"]["pnr_id"] == pid
    assert isinstance(d["events"], list) and len(d["events"]) >= 1


def test_route_risk(client):
    d = client.get("/api/v1/analytics/route-risk?threshold=15&min_pnrs=3").json()
    assert "routes" in d and "count" in d


def test_executive_summary(client):
    d = client.post("/api/v1/agent/executive-summary", json={"role": "Finanzas"}).json()
    assert d["answer"].count("\n\n") + 1 == 3   # 3 parrafos
    assert d["data"]["mode"] in ("rules",) or d["data"]["mode"].startswith("live:")


def test_scenario_config(client):
    d = client.get("/api/v1/scenarios/config").json()
    assert d["count"] == 25


@pytest.mark.parametrize("fmt", ["csv", "excel"])
def test_export(client, fmt):
    r = client.get(f"/api/v1/pnrs/export?format={fmt}")
    assert r.status_code == 200
    assert len(r.content) > 100


# --------------------------------------------------------------------------- #
# Logica no-code (mutaciones sobre base temporal)
# --------------------------------------------------------------------------- #
def test_disabled_scenario_blocks_single_balance(temp_agent):
    conn = temp_agent.conn
    # Tomar un PNR UNBALANCED de un escenario concreto y desactivar ese escenario
    row = conn.execute(
        "SELECT pnr_id, scenario_id FROM pnrs WHERE balance_status='UNBALANCED' LIMIT 1"
    ).fetchone()
    sid = row["scenario_id"]
    conn.execute("UPDATE scenario_config SET enabled=0 WHERE scenario_id=?", (sid,))
    conn.commit()
    res = temp_agent.tool_balance_pnr(row["pnr_id"], "Operaciones")
    assert res["data"].get("skipped") is True
    assert res["data"].get("reason") == "scenario_disabled"
    # El PNR sigue UNBALANCED
    after = conn.execute("SELECT balance_status FROM pnrs WHERE pnr_id=?", (row["pnr_id"],)).fetchone()
    assert after["balance_status"] == "UNBALANCED"


def test_enabled_scenario_balances(temp_agent):
    conn = temp_agent.conn
    row = conn.execute(
        "SELECT pnr_id, scenario_id FROM pnrs WHERE balance_status='UNBALANCED' LIMIT 1"
    ).fetchone()
    conn.execute("UPDATE scenario_config SET enabled=1 WHERE scenario_id=?", (row["scenario_id"],))
    conn.commit()
    res = temp_agent.tool_balance_pnr(row["pnr_id"], "Operaciones")
    assert res["data"].get("skipped") is not True
    after = conn.execute("SELECT balance_status FROM pnrs WHERE pnr_id=?", (row["pnr_id"],)).fetchone()
    assert after["balance_status"] == "BALANCED"


def test_bulk_balance_respects_disabled(temp_agent):
    conn = temp_agent.conn
    # Desactivar escenario 3; balancear toda la cola SLRCVR
    conn.execute("UPDATE scenario_config SET enabled=0 WHERE scenario_id=3")
    conn.commit()
    res = temp_agent.tool_balance_bulk("balancea toda la cola SLRCVR", "Operaciones")
    assert res["intent"] == "balance_bulk"
    # No deben quedar SLRCVR UNBALANCED salvo los del escenario 3 (desactivado)
    remaining = conn.execute(
        "SELECT scenario_id FROM pnrs WHERE queue='SLRCVR' AND balance_status='UNBALANCED'"
    ).fetchall()
    assert all(r["scenario_id"] == 3 for r in remaining)


def test_bulk_balance_all(temp_agent):
    conn = temp_agent.conn
    # Asegurar todas las reglas activas y balancear todo
    conn.execute("UPDATE scenario_config SET enabled=1")
    conn.commit()
    res = temp_agent.tool_balance_bulk("balancea todos los PNR desbalanceados", "Operaciones")
    assert res["data"]["balanced"] >= 1
    left = conn.execute("SELECT COUNT(*) n FROM pnrs WHERE balance_status='UNBALANCED'").fetchone()["n"]
    assert left == 0
