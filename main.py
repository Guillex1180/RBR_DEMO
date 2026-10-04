"""
RBR Airline Insight Engine & Agent Lab
Servidor API (main.py) - v0.2.0-Lab

Expone la API REST documentada (OpenAPI) y sirve el dashboard web.

Endpoints:
    GET  /api/v1/metrics        -> metricas globales + ingresos pendientes
    GET  /api/v1/pnrs           -> lista filtrable de PNRs con sus notas internas
    POST /api/v1/agent/query    -> { role, prompt } -> motor RBRAirlineAgent
    POST /api/v1/pnr/import     -> carga en caliente de PNRs (JSON o CSV)
    GET  /                      -> dashboard web (static/index.html)
    GET  /docs                  -> documentacion OpenAPI (Swagger UI)

Ejecucion:
    python seed_generator.py && uvicorn main:app --reload
"""

import csv
import io
import json
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_engine import RBRAirlineAgent
from scenarios import SCENARIOS, scenario

# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "rbr_local_lab.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")

VERSION = "0.5.0-Lab"

import sqlite3  # noqa: E402  (import after constants for clarity)

app = FastAPI(
    title="RBR Airline Insight Engine & Agent Lab",
    description="Laboratorio local del Robot Balanceador de Reservas (RBR) para aerolineas.",
    version=VERSION,
)


# --------------------------------------------------------------------------- #
# Acceso a datos
# --------------------------------------------------------------------------- #
def get_conn() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise HTTPException(
            status_code=503,
            detail="Base de datos no encontrada. Ejecuta 'python seed_generator.py' primero.",
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pnrs (
            pnr_id TEXT PRIMARY KEY, passenger_name TEXT, flight_number TEXT,
            flight_date TEXT, route TEXT, total_fare REAL, total_paid REAL,
            balance_status TEXT, queue TEXT, scenario_id INTEGER,
            scenario_description TEXT, created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS internal_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pnr_id TEXT, author TEXT,
            note TEXT, created_at TEXT
        )
        """
    )
    conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict:
    d = {k: row[k] for k in row.keys()}
    if "total_fare" in d and "total_paid" in d:
        d["pending_amount"] = round(d["total_fare"] - d["total_paid"], 2)
    return d


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class AgentQuery(BaseModel):
    role: str = Field(default="Operaciones", description="Finanzas | Soporte | Operaciones")
    prompt: str = Field(..., description="Consulta en lenguaje natural")


class ExecutiveSummaryRequest(BaseModel):
    role: str = Field(default="Finanzas", description="Area destinataria del informe")


class ScenarioConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    amount_threshold: Optional[float] = None
    time_threshold_h: Optional[int] = None


class BulkBalanceRequest(BaseModel):
    scope: str = Field(default="all", description="all | queue | scenario | family")
    value: Optional[str] = Field(default=None, description="Valor del alcance (ej. SLRCVR, 3, SEAT_CHANGE)")
    role: str = Field(default="Operaciones")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/v1/metrics")
def get_metrics() -> dict:
    conn = get_conn()
    try:
        agent = RBRAirlineAgent(conn)
        m = agent.compute_metrics()

        # Distribucion por escenario (para el grafico de barras)
        srows = conn.execute(
            "SELECT scenario_id, COUNT(*) c FROM pnrs "
            "WHERE balance_status='UNBALANCED' GROUP BY scenario_id ORDER BY c DESC"
        ).fetchall()
        by_scenario = [
            {
                "scenario_id": r["scenario_id"],
                "code": scenario(r["scenario_id"])["code"],
                "family": scenario(r["scenario_id"])["family"],
                "count": r["c"],
            }
            for r in srows
        ]

        # Agregado por familia (para la tendencia/mix)
        by_family: dict[str, int] = {}
        for item in by_scenario:
            by_family[item["family"]] = by_family.get(item["family"], 0) + item["count"]

        m["by_scenario"] = by_scenario
        m["by_family"] = by_family
        m["version"] = VERSION
        return m
    finally:
        conn.close()


@app.get("/api/v1/pnrs")
def get_pnrs(
    status: Optional[str] = Query(None, description="BALANCED | UNBALANCED"),
    queue: Optional[str] = Query(None, description="SLRCVR | UBPPMT | DELDEV | GENERAL"),
    scenario_id: Optional[int] = Query(None, description="0..24"),
    family: Optional[str] = Query(None, description="Familia de escenario"),
    with_notes: bool = Query(True, description="Incluir notas internas asociadas"),
) -> dict:
    conn = get_conn()
    try:
        sql = "SELECT * FROM pnrs"
        clauses, params = [], []
        if status:
            clauses.append("balance_status = ?"); params.append(status.upper())
        if queue:
            clauses.append("queue = ?"); params.append(queue.upper())
        if scenario_id is not None:
            clauses.append("scenario_id = ?"); params.append(scenario_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql, params).fetchall()

        # Mapa de notas por PNR (una sola consulta)
        notes_map: dict[str, list] = {}
        if with_notes:
            nrows = conn.execute(
                "SELECT id, pnr_id, author, note, created_at FROM internal_notes ORDER BY id DESC"
            ).fetchall()
            for n in nrows:
                notes_map.setdefault(n["pnr_id"], []).append({k: n[k] for k in n.keys()})

        pnrs = []
        for r in rows:
            d = row_to_dict(r)
            sc = scenario(r["scenario_id"])
            d["scenario_code"] = sc["code"]
            d["scenario_family"] = sc["family"]
            if family and sc["family"] != family.upper():
                continue
            d["notes"] = notes_map.get(r["pnr_id"], [])
            pnrs.append(d)

        return {"count": len(pnrs), "pnrs": pnrs}
    finally:
        conn.close()


@app.post("/api/v1/agent/query")
def agent_query(payload: AgentQuery) -> dict:
    conn = get_conn()
    try:
        agent = RBRAirlineAgent(conn)
        return agent.handle(payload.prompt, payload.role)
    finally:
        conn.close()


@app.post("/api/v1/pnr/balance-bulk")
def balance_bulk(payload: BulkBalanceRequest) -> dict:
    """Balanceo masivo por alcance (all | queue | scenario | family).
    Respeta las reglas desactivadas en scenario_config (no las balancea)."""
    # Traduce el scope estructurado a un prompt que entiende tool_balance_bulk.
    scope = (payload.scope or "all").lower()
    if scope == "queue" and payload.value:
        prompt = f"balancea toda la cola {payload.value}"
    elif scope == "scenario" and payload.value is not None:
        prompt = f"balancea el escenario {payload.value}"
    elif scope == "family" and payload.value:
        fam_kw = {"SEAT_CHANGE": "seat", "CREDIT_SHELL": "credit",
                  "VOUCHERS": "voucher", "NAME_CHANGE_FEE": "name change"}
        prompt = f"balancea la familia {fam_kw.get(payload.value.upper(), payload.value)}"
    else:
        prompt = "balancea todos los PNR desbalanceados"
    conn = get_conn()
    try:
        agent = RBRAirlineAgent(conn)
        return agent.tool_balance_bulk(prompt, payload.role)
    finally:
        conn.close()


@app.post("/api/v1/pnr/import")
async def import_pnrs(file: UploadFile = File(...)) -> JSONResponse:
    raw = await file.read()
    name = (file.filename or "").lower()

    try:
        if name.endswith(".csv") or (file.content_type or "").endswith("csv"):
            records = _parse_csv(raw)
        else:
            records = _parse_json(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    conn = get_conn()
    try:
        ensure_schema(conn)
        inserted = updated = skipped = 0
        errors = []
        for idx, rec in enumerate(records):
            normalized = _normalize_pnr(rec)
            if normalized is None:
                skipped += 1
                errors.append(f"Registro {idx}: falta pnr_id o es invalido.")
                continue
            exists = conn.execute(
                "SELECT 1 FROM pnrs WHERE pnr_id = ?", (normalized["pnr_id"],)
            ).fetchone()
            conn.execute(_UPSERT_SQL, normalized)
            updated += 1 if exists else 0
            inserted += 0 if exists else 1
        conn.commit()
        return JSONResponse({
            "status": "ok",
            "file": file.filename,
            "format": "csv" if name.endswith(".csv") else "json",
            "received": len(records),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "errors": errors[:20],
        })
    finally:
        conn.close()


@app.get("/api/v1/scenarios")
def list_scenarios() -> dict:
    return {"count": len(SCENARIOS), "scenarios": [
        {"scenario_id": sid, **info} for sid, info in SCENARIOS.items()
    ]}


# --------------------------------------------------------------------------- #
# Analytics (Bloques 1-4 de la auditoria) - reutilizan RBRAirlineAgent
# Cada endpoint delega en el metodo tool correspondiente para no duplicar logica.
# --------------------------------------------------------------------------- #
def _run_tool(fn_name: str, *args):
    conn = get_conn()
    try:
        agent = RBRAirlineAgent(conn)
        return getattr(agent, fn_name)(*args)
    finally:
        conn.close()


# --- Bloque 1: Diagnostico general ---
@app.get("/api/v1/analytics/success-rate")
def an_success_rate(window: str = Query("24h", description="24h | today | 7d")) -> dict:
    return _run_tool("tool_success_rate_window", window, "Operaciones")          # 1.1

@app.get("/api/v1/analytics/daily-counts")
def an_daily_counts() -> dict:
    return _run_tool("tool_daily_counts", "Operaciones")                          # 1.2

@app.get("/api/v1/analytics/scenario-error-ranking")
def an_scenario_error_ranking() -> dict:
    return _run_tool("tool_scenario_error_ranking", "Operaciones")               # 1.3

@app.get("/api/v1/analytics/top-error-pnrs")
def an_top_error_pnrs() -> dict:
    return _run_tool("tool_top_error_pnrs", "Operaciones")                        # 1.4

@app.get("/api/v1/analytics/failure-patterns")
def an_failure_patterns() -> dict:
    return _run_tool("tool_failure_patterns", "Operaciones")                      # 1.5


# --- Bloque 2: Escenarios ---
@app.get("/api/v1/analytics/lowest-success-scenario")
def an_lowest_success() -> dict:
    return _run_tool("tool_lowest_success_scenario", "Operaciones")              # 2.1

@app.get("/api/v1/analytics/scenario-audit")
def an_scenario_audit(scenario_id: Optional[int] = None, family: Optional[str] = None) -> dict:
    prompt = "auditoria del escenario 7"
    if family and family.upper() in ("NAME_CHANGE_FEE", "NAME CHANGE FEE"):
        prompt = "auditoria del escenario name change fee"
    elif family:
        prompt = f"auditoria del escenario {family}"
    elif scenario_id is not None:
        prompt = f"auditoria del escenario {scenario_id}"
    return _run_tool("tool_scenario_audit", prompt, "Operaciones")                # 2.2

@app.get("/api/v1/analytics/scenario-compare")
def an_scenario_compare(scenario_id: Optional[int] = None, family: Optional[str] = None) -> dict:
    prompt = "comparar ayer y hoy"
    if family:
        prompt = f"comparar {family} ayer y hoy"
    elif scenario_id is not None:
        prompt = f"comparar escenario {scenario_id} ayer y hoy"
    return _run_tool("tool_scenario_time_compare", prompt, "Operaciones")         # 2.3

@app.get("/api/v1/analytics/anomalies")
def an_anomalies() -> dict:
    return _run_tool("tool_anomaly_detection", "Operaciones")                     # 2.4

@app.get("/api/v1/analytics/retry-analysis")
def an_retry_analysis() -> dict:
    return _run_tool("tool_retry_analysis", "Operaciones")                        # 2.5


# --- Bloque 3: PNR / Pasajeros ---
@app.get("/api/v1/analytics/multipax-errors")
def an_multipax() -> dict:
    return _run_tool("tool_multipax_errors", "Operaciones")                       # 3.1

@app.get("/api/v1/analytics/loops")
def an_loops() -> dict:
    return _run_tool("tool_loop_detection", "Operaciones")                        # 3.2

@app.get("/api/v1/analytics/attempt-history")
def an_attempt_history(pnr_id: Optional[str] = None) -> dict:
    return _run_tool("tool_attempt_history", pnr_id, "Operaciones")               # 3.3

@app.get("/api/v1/analytics/inconsistent-states")
def an_inconsistent() -> dict:
    return _run_tool("tool_inconsistent_states", "Operaciones")                   # 3.4

@app.get("/api/v1/analytics/ssr-concentration")
def an_ssr() -> dict:
    return _run_tool("tool_ssr_concentration", "Operaciones")                     # 3.5


# --- Bloque 4: Balance / Deuda / Transacciones ---
@app.get("/api/v1/analytics/unbalanced-transactions")
def an_unbalanced_txn() -> dict:
    return _run_tool("tool_desbalance_transactions", "Finanzas")                  # 4.1 / 4.2

@app.get("/api/v1/analytics/tc-frequency")
def an_tc_frequency() -> dict:
    return _run_tool("tool_tc_frequency", "Finanzas")                             # 4.3

@app.get("/api/v1/analytics/debt-classification")
def an_debt() -> dict:
    return _run_tool("tool_debt_classification", "Finanzas")                      # 4.4

@app.get("/api/v1/analytics/failure-origin-7d")
def an_failure_origin() -> dict:
    return _run_tool("tool_failure_origin_7d", "Finanzas")                        # 4.5


# --- Analisis predictivo: alertas tempranas por ruta ---
@app.get("/api/v1/analytics/route-risk")
def an_route_risk(threshold: float = Query(15.0, description="% de error que dispara alerta"),
                  min_pnrs: int = Query(3, description="minimo de PNRs por ruta")) -> dict:
    conn = get_conn()
    try:
        agent = RBRAirlineAgent(conn)
        risk = agent._route_risk(threshold, min_pnrs)
        return {"threshold": threshold, "min_pnrs": min_pnrs, "count": len(risk), "routes": risk}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Modulo 3: Resumen ejecutivo generativo
# --------------------------------------------------------------------------- #
@app.post("/api/v1/agent/executive-summary")
def executive_summary(payload: ExecutiveSummaryRequest) -> dict:
    conn = get_conn()
    try:
        agent = RBRAirlineAgent(conn)
        return agent.executive_summary(payload.role)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Modulo 3: Exportacion de PNRs (CSV / Excel) con pandas
# --------------------------------------------------------------------------- #
@app.get("/api/v1/pnrs/export")
def export_pnrs(format: str = Query("csv", description="csv | excel")) -> StreamingResponse:
    import pandas as pd
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT pnr_id, passenger_name, flight_number, flight_date, route,
                   total_fare, total_paid,
                   ROUND(total_fare - total_paid, 2) AS pending_amount,
                   balance_status, queue, scenario_id, scenario_description, created_at
            FROM pnrs ORDER BY balance_status, (total_fare-total_paid) DESC
            """
        ).fetchall()
        df = pd.DataFrame([{k: r[k] for k in r.keys()} for r in rows])
    finally:
        conn.close()

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    if format.lower() in ("excel", "xlsx"):
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="PNRs")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="rbr_pnrs_{ts}.xlsx"'},
        )
    # CSV por defecto
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rbr_pnrs_{ts}.csv"'},
    )


# --------------------------------------------------------------------------- #
# Modulo 2: Timeline / auditoria detallada por PNR
# --------------------------------------------------------------------------- #
@app.get("/api/v1/pnr/{pnr_id}/timeline")
def pnr_timeline(pnr_id: str) -> dict:
    conn = get_conn()
    try:
        pnr = conn.execute("SELECT * FROM pnrs WHERE pnr_id = ?", (pnr_id.upper(),)).fetchone()
        if not pnr:
            raise HTTPException(status_code=404, detail=f"PNR {pnr_id} no encontrado.")
        logs = conn.execute(
            "SELECT id, event_type, description, performed_by, timestamp "
            "FROM pnr_audit_logs WHERE pnr_id = ? ORDER BY timestamp, id",
            (pnr_id.upper(),),
        ).fetchall()
        return {
            "pnr": row_to_dict(pnr),
            "scenario": scenario(pnr["scenario_id"]),
            "events": [{k: r[k] for k in r.keys()} for r in logs],
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Modulo 4: Gestion no-code de escenarios (config editable)
# --------------------------------------------------------------------------- #
@app.get("/api/v1/scenarios/config")
def get_scenario_config() -> dict:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT scenario_id, code, family, enabled, amount_threshold, time_threshold_h, updated_at "
            "FROM scenario_config ORDER BY scenario_id"
        ).fetchall()
        return {"count": len(rows), "config": [
            {**{k: r[k] for k in r.keys()}, "enabled": bool(r["enabled"]),
             "description": scenario(r["scenario_id"])["description"]}
            for r in rows
        ]}
    finally:
        conn.close()


@app.put("/api/v1/scenarios/config/{scenario_id}")
def update_scenario_config(scenario_id: int, update: ScenarioConfigUpdate) -> dict:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM scenario_config WHERE scenario_id = ?", (scenario_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Escenario {scenario_id} no existe en la config.")
        fields, params = [], []
        if update.enabled is not None:
            fields.append("enabled = ?"); params.append(1 if update.enabled else 0)
        if update.amount_threshold is not None:
            fields.append("amount_threshold = ?"); params.append(float(update.amount_threshold))
        if update.time_threshold_h is not None:
            fields.append("time_threshold_h = ?"); params.append(int(update.time_threshold_h))
        if not fields:
            raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar.")
        fields.append("updated_at = ?"); params.append(datetime.now().isoformat(timespec="seconds"))
        params.append(scenario_id)
        conn.execute(f"UPDATE scenario_config SET {', '.join(fields)} WHERE scenario_id = ?", params)
        conn.commit()
        updated = conn.execute(
            "SELECT scenario_id, code, family, enabled, amount_threshold, time_threshold_h, updated_at "
            "FROM scenario_config WHERE scenario_id = ?", (scenario_id,)
        ).fetchone()
        d = {k: updated[k] for k in updated.keys()}
        d["enabled"] = bool(d["enabled"])
        return {"status": "ok", "config": d}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Import helpers
# --------------------------------------------------------------------------- #
_UPSERT_SQL = """
INSERT INTO pnrs (
    pnr_id, passenger_name, flight_number, flight_date, route,
    total_fare, total_paid, balance_status, queue,
    scenario_id, scenario_description, created_at
) VALUES (
    :pnr_id, :passenger_name, :flight_number, :flight_date, :route,
    :total_fare, :total_paid, :balance_status, :queue,
    :scenario_id, :scenario_description, :created_at
)
ON CONFLICT(pnr_id) DO UPDATE SET
    passenger_name=excluded.passenger_name, flight_number=excluded.flight_number,
    flight_date=excluded.flight_date, route=excluded.route,
    total_fare=excluded.total_fare, total_paid=excluded.total_paid,
    balance_status=excluded.balance_status, queue=excluded.queue,
    scenario_id=excluded.scenario_id, scenario_description=excluded.scenario_description
"""


def _parse_json(raw: bytes) -> list:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"JSON invalido: {exc}")
    if isinstance(payload, dict) and "pnrs" in payload:
        return payload["pnrs"]
    if isinstance(payload, list):
        return payload
    raise ValueError("El JSON debe ser una lista de PNRs o un objeto {'pnrs': [...]}.")


def _parse_csv(raw: bytes) -> list:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"CSV invalido (codificacion): {exc}")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV sin encabezados.")
    return [dict(row) for row in reader]


def _normalize_pnr(rec: Any) -> Optional[dict]:
    if not isinstance(rec, dict):
        return None
    pnr_id = rec.get("pnr_id")
    if not pnr_id:
        return None

    total_fare = _to_float(rec.get("total_fare", 0.0))
    total_paid = _to_float(rec.get("total_paid", 0.0))

    balance_status = rec.get("balance_status")
    if not balance_status:
        balance_status = "BALANCED" if abs(total_fare - total_paid) < 0.01 else "UNBALANCED"

    try:
        sid = int(rec.get("scenario_id", 0))
    except (TypeError, ValueError):
        sid = 0
    sc = scenario(sid)

    return {
        "pnr_id": str(pnr_id).upper()[:6] if len(str(pnr_id)) >= 6 else str(pnr_id).upper(),
        "passenger_name": str(rec.get("passenger_name", "N/A")),
        "flight_number": str(rec.get("flight_number", "N/A")),
        "flight_date": str(rec.get("flight_date", "")),
        "route": str(rec.get("route", "")),
        "total_fare": total_fare,
        "total_paid": total_paid,
        "balance_status": str(balance_status).upper(),
        "queue": str(rec.get("queue", "GENERAL")).upper(),
        "scenario_id": sid,
        "scenario_description": str(rec.get("scenario_description") or sc["description"]),
        "created_at": str(rec.get("created_at") or datetime.now().isoformat(timespec="seconds")),
    }


def _to_float(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# Dashboard web
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    if not os.path.exists(INDEX_PATH):
        raise HTTPException(status_code=404, detail="static/index.html no encontrado.")
    return FileResponse(INDEX_PATH)


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
