"""
RBR Airline Insight Engine & Agent Lab
Motor del Asistente RBR (agent_engine.py)

Implementa RBRAirlineAgent: un agente con "tool calling" basado en reglas que
interpreta prompts en lenguaje natural y ejecuta herramientas sobre la base de
datos local:

    tool_metrics          -> metricas globales e ingresos pendientes por cola
    tool_scenarios        -> escenarios con mayor desbalance
    tool_balance_pnr      -> balanceo con explicabilidad de la regla aplicada
    tool_add_note         -> registro de notas internas entre departamentos
    tool_flight_priority  -> PNRs en riesgo (vuelo dentro de las proximas 24h)
    tool_lookup_pnr       -> consulta puntual de un PNR

El agente es independiente de FastAPI: recibe una conexion sqlite3 ya abierta.
"""

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

from scenarios import scenario, scenario_ids_for_family

try:
    from llm_provider import LLMProvider
except Exception:  # pragma: no cover
    LLMProvider = None

PNR_RE = re.compile(r"\b([A-Za-z0-9]{6})\b")
SCEN_NUM_RE = re.compile(r"escenario\s+(?:n[uú]mero\s+|#\s*)?(\d{1,2})", re.IGNORECASE)
# "nota al PNR XXXXXX: texto"  /  "nota a XXXXXX - texto"
NOTE_RE = re.compile(
    r"nota\s+(?:interna\s+)?(?:al|a|para|en)?\s*(?:pnr\s+)?([A-Za-z0-9]{6})\s*[:\-]\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


class RBRAirlineAgent:
    """Agente de IA basado en reglas para el laboratorio RBR."""

    def __init__(self, conn: sqlite3.Connection, llm=None):
        self.conn = conn
        # Capa LLM opcional; si no hay credenciales, is_live() == False y se
        # usa el motor de reglas local (fallback).
        if llm is not None:
            self.llm = llm
        elif LLMProvider is not None:
            try:
                self.llm = LLMProvider()
            except Exception:
                self.llm = None
        else:
            self.llm = None

    @property
    def llm_mode(self) -> str:
        """'live:<provider>' si hay LLM real, 'rules' si es fallback local."""
        if self.llm is not None and getattr(self.llm, "is_live", lambda: False)():
            return f"live:{self.llm.active}"
        return "rules"

    # ------------------------------------------------------------------ #
    # Punto de entrada
    # ------------------------------------------------------------------ #
    def handle(self, prompt: str, role: str = "Operaciones") -> dict:
        text = (prompt or "").strip()
        low = self._norm(text)
        role = role or "Operaciones"

        # ============ ACCIONES (nota / balanceo) ============
        note_match = NOTE_RE.search(text)
        if note_match or ("nota" in low and self._extract_pnr(text)):
            return self.tool_add_note(text, role, note_match)

        if any(w in low for w in ("balancea", "balancear", "concilia", "conciliar", "corrige", "arregla")):
            # Balanceo masivo: "balancea toda/todos ...", "balancea la cola X",
            # "balancea el escenario N", "balancea la familia ...".
            is_bulk = any(w in low for w in ("todos", "todas", "toda la cola", "masivo",
                                             "en lote", "la cola", "la familia")) \
                or (("escenario" in low or "familia" in low) and self._extract_pnr(text) is None)
            if is_bulk:
                return self.tool_balance_bulk(text, role)
            pnr_id = self._extract_pnr(text)
            if pnr_id:
                return self.tool_balance_pnr(pnr_id, role)
            return self._reply("balance_pnr", role,
                               "Indica el localizador del PNR a balancear (ej. 'Balancea el PNR HX982A') "
                               "o un alcance masivo (ej. 'Balancea toda la cola SLRCVR').")

        # ============ BLOQUE 4: BALANCE / DEUDA / TRANSACCIONES ============
        # (van antes del bloque de escenarios/metricas para no ser capturadas)
        if ("origen" in low and ("fallo" in low or "falla" in low or "error" in low)) \
           or "navitaire" in low or "token" in low or ("7 dias" in low and "error" in low) \
           or ("clasifica" in low and "error" in low):
            return self.tool_failure_origin_7d(role)             # 4.5

        if ("deuda" in low and ("cliente" in low or "aerolinea" in low or "jetsmart" in low)) \
           or ("deuda" in low and ("tipo" in low or "versus" in low or " vs" in low)):
            return self.tool_debt_classification(role)           # 4.4

        if ("codigo" in low and ("transaccion" in low or "tc" in low)) \
           or ("tc" in low and ("frecuen" in low or "fallid" in low)):
            return self.tool_tc_frequency(role)                  # 4.3

        if ("balance" in low and ("diferente de cero" in low or "distinto de cero" in low or "!= 0" in low or "no cero" in low)) \
           or ("transaccion" in low and "diferencia" in low) \
           or ("desbalanceados" in low and "transaccion" in low) \
           or (low.strip().startswith("lista") and "desbalance" in low):
            return self.tool_desbalance_transactions(role)       # 4.1 / 4.2

        # ============ BLOQUE 2.5: REINTENTOS (antes de historial, por la
        # palabra 'procesamiento' que ambos comparten) ============
        if ("reintento" in low or "reintentos" in low or "reprocesos" in low
                or "reproceso" in low):
            return self.tool_retry_analysis(role)                # 2.5

        # ============ BLOQUE 3: PNR / PASAJEROS ============
        if ("ssr" in low) or ("concentra" in low and ("error" in low or "fallo" in low)) \
           or (("asiento" in low or "equipaje" in low) and ("error" in low or "concentr" in low)):
            return self.tool_ssr_concentration(role)             # 3.5

        if ("inconsistente" in low or "inconsistencia" in low or "estado inconsistente" in low):
            return self.tool_inconsistent_states(role)           # 3.4

        if ("historial" in low and ("intento" in low or "procesamiento" in low)) \
           or ("intento" in low and ("mas de un" in low or "varios" in low or "multiples" in low or "cada intento" in low)) \
           or ("intentos" in low and self._extract_pnr(text)):
            pid = self._extract_pnr(text)
            if pid:
                return self.tool_attempt_history(pid, role)      # 3.3
            return self.tool_attempt_history(None, role)

        if ("bucle" in low or "repetidamente" in low or "sin completar" in low
                or "sin llegar a completar" in low or "loop" in low):
            return self.tool_loop_detection(role)                # 3.2

        if ("multipasajero" in low or "multiples pasajeros" in low or "multiple pasajero" in low
                or ("pasajeros" in low and ("error" in low or "fallo" in low or "relacion" in low))):
            return self.tool_multipax_errors(role)               # 3.1

        # ============ BLOQUE 2: ESCENARIOS ============
        if ("anomalia" in low or "anomalias" in low
                or ("empezo a fallar" in low or "comenzo a fallar" in low or "fallar mas" in low)
                or ("incremento" in low and ("fallo" in low or "error" in low))):
            return self.tool_anomaly_detection(role)             # 2.4

        if ("comparar" in low or "comparativo" in low or "ayer y hoy" in low or "ayer vs hoy" in low
                or ("ayer" in low and "hoy" in low)):
            return self.tool_scenario_time_compare(text, role)   # 2.3

        if ("auditoria" in low and "escenario" in low) \
           or (SCEN_NUM_RE.search(text) and ("procesaron" in low or "fallaron" in low or "cuantos" in low or "auditor" in low)) \
           or ("name change fee" in low and ("cuantos" in low or "fallaron" in low or "procesaron" in low or "auditor" in low)):
            return self.tool_scenario_audit(text, role)          # 2.2

        if ("tasa" in low and ("mas baja" in low or "peor" in low or "baja" in low) and "escenario" in low) \
           or ("escenario" in low and "peor tasa" in low) \
           or ("escenario" in low and "menor exito" in low):
            return self.tool_lowest_success_scenario(role)       # 2.1

        # ============ BLOQUE 1: DIAGNOSTICO GENERAL ============
        if ("patron" in low or "patrones" in low) and ("error" in low or "fallo" in low or "24" in low):
            return self.tool_failure_patterns(role)              # 1.5

        if ("top" in low and ("pnr" in low) and ("error" in low or "fallo" in low)) \
           or ("10 pnr" in low) or ("diez pnr" in low):
            return self.tool_top_error_pnrs(role)                # 1.4

        if ("escenario" in low and ("mas error" in low or "mas errores" in low or "criticos" in low or "generando mas" in low)):
            return self.tool_scenario_error_ranking(role)        # 1.3

        if (("cuantos" in low or "conteo" in low or "procesamos" in low) and ("hoy" in low or "dia" in low)) \
           or ("sin procesar" in low):
            return self.tool_daily_counts(role)                  # 1.2

        if (("exito" in low or "tasa" in low) and ("24" in low or "ultimas" in low or "ventana" in low or "hoy" in low)) \
           or ("porcentaje de exito" in low):
            return self.tool_success_rate_window(text, role)     # 1.1

        # ============ INTENTS ORIGINALES (genericas, al final) ============
        if any(w in low for w in ("riesgo", "prioridad", "proximas 24", "proximo vuelo", "urgente", "impacto", "24 horas", "24h")):
            return self.tool_flight_priority(role)

        if any(w in low for w in ("escenario", "escenarios", "mayor desbalance", "mas desbalance", "casuistica")):
            return self.tool_scenarios(role)

        if any(w in low for w in ("pendiente", "pendientes", "monto", "ingreso", "cobrar", "liberar", "deuda",
                                  "metrica", "metricas", "resumen", "estado", "tasa", "exito", "cuant", "total")):
            return self.tool_metrics(role)

        pnr_id = self._extract_pnr(text)
        if pnr_id:
            return self.tool_lookup_pnr(pnr_id, role)

        return self._reply(
            "unknown", role,
            "Puedo ayudarte con diagnostico (exito 24h, conteo diario, top PNR con error, patrones), "
            "escenarios (peor tasa, auditoria, comparativo, anomalias, reintentos), "
            "PNR/pasajeros (multipasajero, bucles, historial de intentos, estados inconsistentes, SSR), "
            "y finanzas (desbalance y transacciones, codigos TC, deuda cliente vs aerolinea, origen de fallos 7 dias). "
            "Tambien: balancear un PNR o agregar notas internas.",
        )

    # ------------------------------------------------------------------ #
    # Herramientas (tools)
    # ------------------------------------------------------------------ #
    def tool_metrics(self, role: str) -> dict:
        m = self.compute_metrics()
        answer = (
            f"Total {m['total_pnrs']} PNRs: {m['balanced']} balanceados y {m['unbalanced']} desbalanceados "
            f"(tasa de exito {m['success_rate']}%). Ingresos pendientes por liberar: "
            f"${m['pending_revenue_usd']:,.2f}. Desglose por cola: "
            + ", ".join(f"{q}=${v:,.0f}" for q, v in m["pending_by_queue"].items())
            + "."
        )
        return self._reply("metrics", role, answer, tool="tool_metrics", data=m)

    def tool_scenarios(self, role: str) -> dict:
        rows = self.conn.execute(
            "SELECT scenario_id, COUNT(*) c FROM pnrs "
            "WHERE balance_status='UNBALANCED' GROUP BY scenario_id ORDER BY c DESC"
        ).fetchall()
        ranking = []
        for r in rows:
            sc = scenario(r["scenario_id"])
            ranking.append({
                "scenario_id": r["scenario_id"],
                "code": sc["code"],
                "family": sc["family"],
                "description": sc["description"],
                "count": r["c"],
            })
        if not ranking:
            return self._reply("scenarios", role, "No hay escenarios desbalanceados actualmente.")
        top = ranking[0]
        answer = (
            f"El escenario con mayor desbalance es #{top['scenario_id']} ({top['code']} - {top['family']}) "
            f"con {top['count']} PNRs: {top['description']}."
        )
        return self._reply("scenarios", role, answer, tool="tool_scenarios", data={"ranking": ranking})

    def tool_balance_pnr(self, pnr_id: str, role: str) -> dict:
        pnr_id = pnr_id.upper()
        row = self.conn.execute("SELECT * FROM pnrs WHERE pnr_id = ?", (pnr_id,)).fetchone()
        if not row:
            return self._reply("balance_pnr", role, f"No encontre el PNR {pnr_id}.")

        if row["balance_status"] == "BALANCED":
            return self._reply("balance_pnr", role,
                               f"El PNR {pnr_id} ya esta BALANCED. No requiere accion.",
                               tool="tool_balance_pnr", data={"pnr": self._row_to_pnr(row)})

        sid = row["scenario_id"]
        sc = scenario(sid)

        # Gestion no-code: si la regla del escenario esta DESACTIVADA, no se balancea.
        if not self.is_scenario_enabled(sid):
            return self._reply(
                "balance_pnr", role,
                f"El PNR {pnr_id} corresponde al Escenario {sid} ({sc['code']}), que esta "
                f"DESACTIVADO en la configuracion de reglas. No se aplico balanceo.",
                tool="tool_balance_pnr",
                data={"pnr": self._row_to_pnr(row), "skipped": True, "reason": "scenario_disabled"},
            )

        before_paid = row["total_paid"]
        fare = row["total_fare"]
        diff = round(fare - before_paid, 2)

        # Explicabilidad de la regla
        if sc["sign"] == "credit":
            action = f"se aplico el saldo a favor de ${abs(diff):,.2f} y se concilio el PNR"
        else:
            action = f"se registro el cobro pendiente de ${abs(diff):,.2f} y se concilio el PNR"

        self.conn.execute(
            """
            UPDATE pnrs
            SET total_paid = total_fare,
                balance_status = 'BALANCED',
                scenario_id = 0,
                scenario_description = ?
            WHERE pnr_id = ?
            """,
            (f"Conciliado por el Robot RBR (origen: Escenario {sid} - {sc['code']})", pnr_id),
        )
        self.conn.commit()
        updated = self.conn.execute("SELECT * FROM pnrs WHERE pnr_id = ?", (pnr_id,)).fetchone()

        explanation = (
            f"PNR {pnr_id} balanceado aplicando el Escenario {sid} - {sc['code']} "
            f"({sc['family']}). Regla: {sc['description']}; {action}."
        )
        return self._reply(
            "balance_pnr", role, explanation,
            tool="tool_balance_pnr",
            data={
                "pnr": self._row_to_pnr(updated),
                "explain": {
                    "scenario_id": sid,
                    "scenario_code": sc["code"],
                    "family": sc["family"],
                    "rule": sc["description"],
                    "adjusted_amount": abs(diff),
                    "direction": sc["sign"],
                },
            },
        )

    def tool_add_note(self, text: str, role: str, note_match: Optional[re.Match]) -> dict:
        pnr_id = None
        note = None
        if note_match:
            pnr_id = note_match.group(1).upper()
            note = note_match.group(2).strip()
        else:
            pnr_id = self._extract_pnr(text)
            # Tomar como nota lo que sigue a ':' o '-'
            m = re.search(r"[:\-]\s*(.+)", text, re.DOTALL)
            if m:
                note = m.group(1).strip()

        if not pnr_id or not note:
            return self._reply("add_note", role,
                               "Formato: 'Agregar nota al PNR AMX101: <texto>'.")

        exists = self.conn.execute("SELECT 1 FROM pnrs WHERE pnr_id = ?", (pnr_id,)).fetchone()
        if not exists:
            return self._reply("add_note", role, f"No encontre el PNR {pnr_id}; no se registro la nota.")

        created_at = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO internal_notes (pnr_id, author, note, created_at) VALUES (?,?,?,?)",
            (pnr_id, role, note, created_at),
        )
        self.conn.commit()
        return self._reply(
            "add_note", role,
            f"Nota registrada en el PNR {pnr_id} por {role}: \"{note}\".",
            tool="tool_add_note",
            data={"note": {"id": cur.lastrowid, "pnr_id": pnr_id, "author": role,
                           "note": note, "created_at": created_at}},
        )

    def tool_flight_priority(self, role: str) -> dict:
        now = datetime.now()
        horizon = now + timedelta(hours=24)
        rows = self.conn.execute(
            "SELECT * FROM pnrs WHERE balance_status='UNBALANCED'"
        ).fetchall()

        at_risk = []
        for r in rows:
            fd = self._parse_date(r["flight_date"])
            if fd and now <= fd <= horizon:
                at_risk.append({
                    "pnr_id": r["pnr_id"],
                    "passenger_name": r["passenger_name"],
                    "flight_number": r["flight_number"],
                    "flight_date": r["flight_date"],
                    "pending_amount": round(r["total_fare"] - r["total_paid"], 2),
                    "scenario_id": r["scenario_id"],
                    "hours_to_flight": round((fd - now).total_seconds() / 3600, 1),
                })
        at_risk.sort(key=lambda x: x["hours_to_flight"])

        if not at_risk:
            return self._reply("flight_priority", role,
                               "No hay PNRs desbalanceados con vuelo en las proximas 24 horas.")
        answer = (
            f"Hay {len(at_risk)} PNRs desbalanceados con vuelo en las proximas 24h "
            f"(riesgo de impacto a pasajeros). El mas urgente es {at_risk[0]['pnr_id']} "
            f"({at_risk[0]['flight_number']}) en {at_risk[0]['hours_to_flight']}h."
        )
        return self._reply("flight_priority", role, answer,
                           tool="tool_flight_priority", data={"at_risk": at_risk})

    def tool_lookup_pnr(self, pnr_id: str, role: str) -> dict:
        pnr_id = pnr_id.upper()
        row = self.conn.execute("SELECT * FROM pnrs WHERE pnr_id = ?", (pnr_id,)).fetchone()
        if not row:
            return self._reply("lookup_pnr", role, f"No encontre el PNR {pnr_id}.")
        pnr = self._row_to_pnr(row)
        notes = self._notes_for(pnr_id)
        sc = scenario(row["scenario_id"])
        answer = (
            f"PNR {pnr['pnr_id']} ({pnr['passenger_name']}) - {pnr['balance_status']}. "
            f"Tarifa ${pnr['total_fare']:,.2f}, pagado ${pnr['total_paid']:,.2f}, "
            f"pendiente ${pnr['pending_amount']:,.2f}. Escenario {row['scenario_id']} ({sc['code']}). "
            f"Notas internas: {len(notes)}."
        )
        return self._reply("lookup_pnr", role, answer,
                           tool="tool_lookup_pnr", data={"pnr": pnr, "notes": notes})

    # ================================================================== #
    # BLOQUE 1 · DIAGNOSTICO GENERAL
    # ================================================================== #
    def tool_success_rate_window(self, text: str, role: str) -> dict:
        """1.1 Tasa de exito en una ventana (24h/hoy/7d) + causas de fallo."""
        low = self._norm(text)
        if "7" in low and "dia" in low:
            window, label = ("7d", "ultimos 7 dias")
        elif "hoy" in low:
            window, label = ("today", "hoy")
        else:
            window, label = ("24h", "ultimas 24h")
        stats = self._run_stats(window)
        causes = self._top_error_codes(window, limit=3)
        causes_txt = ", ".join(f"{c['error_code']} ({c['count']})" for c in causes) or "sin fallos registrados"
        answer = (
            f"Tasa de exito del RBR en las {label}: {stats['success_rate']}% "
            f"({stats['ok']} OK de {stats['total']} ejecuciones). "
            f"Principales causas de fallo: {causes_txt}."
        )
        return self._reply("success_rate_window", role, answer,
                           tool="tool_success_rate_window",
                           data={"window": window, "stats": stats, "top_causes": causes})

    def tool_daily_counts(self, role: str) -> dict:
        """1.2 PNR procesados hoy: OK / ERROR / UNPROCESSED."""
        stats = self._run_stats("today")
        pnrs_today = self.conn.execute(
            "SELECT COUNT(DISTINCT pnr_id) c FROM processing_runs WHERE date(started_at)=date('now','localtime')"
        ).fetchone()["c"]
        answer = (
            f"Hoy se procesaron {pnrs_today} PNR distintos en {stats['total']} ejecuciones: "
            f"{stats['ok']} terminaron correctamente (OK), {stats['error']} con error, "
            f"y {stats['unprocessed']} quedaron sin procesar."
        )
        return self._reply("daily_counts", role, answer, tool="tool_daily_counts",
                           data={"pnrs_today": pnrs_today, "stats": stats})

    def tool_top_error_pnrs(self, role: str) -> dict:
        """1.4 Top 10 PNR con mas errores hoy + explicacion por PNR."""
        rows = self.conn.execute(
            """
            SELECT pr.pnr_id, COUNT(*) errors,
                   MAX(pr.started_at) last_at
            FROM processing_runs pr
            WHERE pr.result='ERROR' AND date(pr.started_at)=date('now','localtime')
            GROUP BY pr.pnr_id ORDER BY errors DESC, last_at DESC LIMIT 10
            """
        ).fetchall()
        if not rows:
            # fallback a ventana 7d si hoy no hay suficientes
            rows = self.conn.execute(
                """
                SELECT pr.pnr_id, COUNT(*) errors, MAX(pr.started_at) last_at
                FROM processing_runs pr WHERE pr.result='ERROR'
                GROUP BY pr.pnr_id ORDER BY errors DESC LIMIT 10
                """
            ).fetchall()
        top = []
        for r in rows:
            last = self.conn.execute(
                "SELECT error_code, error_origin, scenario_id FROM processing_runs "
                "WHERE pnr_id=? AND result='ERROR' ORDER BY started_at DESC LIMIT 1",
                (r["pnr_id"],),
            ).fetchone()
            sc = scenario(last["scenario_id"]) if last else scenario(0)
            top.append({
                "pnr_id": r["pnr_id"], "errors": r["errors"],
                "last_error_code": last["error_code"] if last else None,
                "last_error_origin": last["error_origin"] if last else None,
                "scenario_id": last["scenario_id"] if last else None,
                "scenario_code": sc["code"],
            })
        if not top:
            return self._reply("top_error_pnrs", role, "No hay PNR con errores registrados.")
        lead = top[0]
        answer = (
            f"Top {len(top)} PNR con mas errores. El mas afectado es {lead['pnr_id']} con "
            f"{lead['errors']} errores (ultimo: {lead['last_error_code']} / {lead['last_error_origin']}, "
            f"escenario {lead['scenario_id']} {lead['scenario_code']})."
        )
        return self._reply("top_error_pnrs", role, answer, tool="tool_top_error_pnrs",
                           data={"top": top})

    def tool_failure_patterns(self, role: str) -> dict:
        """1.5 Patron comun entre errores de las ultimas 24h."""
        origin = self.conn.execute(
            """
            SELECT error_origin, COUNT(*) c FROM processing_runs
            WHERE result='ERROR' AND error_origin IS NOT NULL
              AND started_at >= datetime('now','-1 day','localtime')
            GROUP BY error_origin ORDER BY c DESC
            """
        ).fetchall()
        code = self._top_error_codes("24h", limit=1)
        if not origin:
            return self._reply("failure_patterns", role,
                               "No hay suficientes errores en las ultimas 24h para detectar un patron.")
        top_o = origin[0]
        top_c = code[0]["error_code"] if code else "N/A"
        dist = {o["error_origin"]: o["c"] for o in origin}
        answer = (
            f"Patron detectado en las ultimas 24h: el origen dominante es {top_o['error_origin']} "
            f"({top_o['c']} errores) y el codigo mas comun es {top_c}. "
            f"Distribucion por origen: " + ", ".join(f"{k}={v}" for k, v in dist.items()) + "."
        )
        return self._reply("failure_patterns", role, answer, tool="tool_failure_patterns",
                           data={"by_origin": dist, "top_code": top_c})

    # ================================================================== #
    # BLOQUE 2 · ANALISIS DE ESCENARIOS
    # ================================================================== #
    def tool_scenario_error_ranking(self, role: str) -> dict:
        """1.3 Escenarios que generan mas ERROR reales."""
        rows = self.conn.execute(
            """
            SELECT scenario_id, COUNT(*) errors FROM processing_runs
            WHERE result='ERROR' GROUP BY scenario_id ORDER BY errors DESC
            """
        ).fetchall()
        ranking = []
        for r in rows:
            sc = scenario(r["scenario_id"])
            ranking.append({"scenario_id": r["scenario_id"], "code": sc["code"],
                            "family": sc["family"], "errors": r["errors"]})
        if not ranking:
            return self._reply("scenario_error_ranking", role, "No hay errores registrados por escenario.")
        top = ranking[0]
        answer = (f"El escenario que genera mas errores es #{top['scenario_id']} ({top['code']} - "
                  f"{top['family']}) con {top['errors']} ejecuciones fallidas.")
        return self._reply("scenario_error_ranking", role, answer,
                           tool="tool_scenario_error_ranking", data={"ranking": ranking})

    def tool_lowest_success_scenario(self, role: str) -> dict:
        """2.1 Escenario con la TASA de exito mas baja (no el de mayor conteo)."""
        rows = self.conn.execute(
            """
            SELECT scenario_id,
                   SUM(CASE WHEN result='OK' THEN 1 ELSE 0 END) ok,
                   COUNT(*) total
            FROM processing_runs
            WHERE scenario_id != 0
            GROUP BY scenario_id HAVING total >= 2
            """
        ).fetchall()
        scored = []
        for r in rows:
            rate = round((r["ok"] / r["total"]) * 100, 2) if r["total"] else 0.0
            sc = scenario(r["scenario_id"])
            scored.append({"scenario_id": r["scenario_id"], "code": sc["code"], "family": sc["family"],
                           "success_rate": rate, "ok": r["ok"], "total": r["total"]})
        if not scored:
            return self._reply("lowest_success_scenario", role, "No hay datos suficientes por escenario.")
        scored.sort(key=lambda x: (x["success_rate"], -x["total"]))
        worst = scored[0]
        causes = self._top_error_codes_for_scenario(worst["scenario_id"], limit=3)
        causes_txt = ", ".join(f"{c['error_code']} ({c['count']})" for c in causes) or "N/A"
        answer = (
            f"El escenario con la tasa de exito mas baja es #{worst['scenario_id']} ({worst['code']} - "
            f"{worst['family']}) con {worst['success_rate']}% ({worst['ok']}/{worst['total']} OK). "
            f"Errores que lo causan: {causes_txt}."
        )
        return self._reply("lowest_success_scenario", role, answer,
                           tool="tool_lowest_success_scenario",
                           data={"worst": worst, "causes": causes, "ranking": scored[:10]})

    def tool_scenario_audit(self, text: str, role: str) -> dict:
        """2.2 Auditoria de un escenario: OK vs ERROR + causa. Maneja la
        ambiguedad 'Name Change Fee' -> familia (ids 19..24)."""
        low = self._norm(text)
        note = ""
        if "name change fee" in low:
            ids = scenario_ids_for_family("NAME_CHANGE_FEE")
            note = ("Nota: 'Name Change Fee' corresponde a la FAMILIA NAME_CHANGE_FEE "
                    f"(escenarios {min(ids)}..{max(ids)}); se audita la familia completa.")
            scope_ids = ids
            label = "familia Name Change Fee"
        else:
            m = SCEN_NUM_RE.search(text)
            sid = int(m.group(1)) if m else 7
            sc = scenario(sid)
            scope_ids = [sid]
            label = f"escenario #{sid} ({sc['code']} - {sc['family']})"
            if sid == 7:
                note = ("Nota: en este catalogo tecnico #7 = SHELL_UNUSED (Credit Shell). "
                        "Si buscabas 'Name Change Fee', corresponde a la familia (ids 19..24).")
        placeholders = ",".join("?" for _ in scope_ids)
        row = self.conn.execute(
            f"""
            SELECT SUM(CASE WHEN result='OK' THEN 1 ELSE 0 END) ok,
                   SUM(CASE WHEN result='ERROR' THEN 1 ELSE 0 END) err,
                   COUNT(*) total
            FROM processing_runs WHERE scenario_id IN ({placeholders})
            """, scope_ids,
        ).fetchone()
        ok, err, total = row["ok"] or 0, row["err"] or 0, row["total"] or 0
        cause = self.conn.execute(
            f"""
            SELECT error_code, COUNT(*) c FROM processing_runs
            WHERE scenario_id IN ({placeholders}) AND result='ERROR' AND error_code IS NOT NULL
            GROUP BY error_code ORDER BY c DESC LIMIT 1
            """, scope_ids,
        ).fetchone()
        cause_txt = f"{cause['error_code']} ({cause['c']} casos)" if cause else "sin causa dominante"
        answer = (
            f"Auditoria de {label}: {ok} procesados correctamente y {err} fallidos "
            f"de {total} ejecuciones. Causa principal de fallo: {cause_txt}. {note}"
        ).strip()
        return self._reply("scenario_audit", role, answer, tool="tool_scenario_audit",
                           data={"scope_ids": scope_ids, "ok": ok, "error": err, "total": total,
                                 "top_cause": cause["error_code"] if cause else None})

    def tool_scenario_time_compare(self, text: str, role: str) -> dict:
        """2.3 Comparar un escenario entre ayer y hoy (mejora/degradacion)."""
        m = SCEN_NUM_RE.search(text)
        low = self._norm(text)
        if m:
            sid = int(m.group(1)); scope_ids = [sid]
            sc = scenario(sid); label = f"escenario #{sid} ({sc['code']})"
        elif "name change fee" in low:
            scope_ids = scenario_ids_for_family("NAME_CHANGE_FEE"); label = "familia Name Change Fee"
        else:
            scope_ids = scenario_ids_for_family("SEAT_CHANGE"); label = "familia Seat Change"
        today = self._scenario_rate(scope_ids, "today")
        yest = self._scenario_rate(scope_ids, "yesterday")
        delta = round(today["success_rate"] - yest["success_rate"], 2)
        trend = "mejora" if delta > 0 else ("degradacion" if delta < 0 else "sin cambio")
        answer = (
            f"Comparativo del {label}: ayer {yest['success_rate']}% ({yest['ok']}/{yest['total']}), "
            f"hoy {today['success_rate']}% ({today['ok']}/{today['total']}). "
            f"Variacion: {delta:+.2f} puntos -> {trend}."
        )
        return self._reply("scenario_time_compare", role, answer, tool="tool_scenario_time_compare",
                           data={"scope_ids": scope_ids, "yesterday": yest, "today": today, "delta": delta, "trend": trend})

    def tool_anomaly_detection(self, role: str) -> dict:
        """2.4 Escenario cuyo ratio de error subio mas de ayer a hoy."""
        anomalies = []
        for sid in self.conn.execute(
            "SELECT DISTINCT scenario_id FROM processing_runs WHERE scenario_id!=0"
        ).fetchall():
            s = sid["scenario_id"]
            y = self._scenario_rate([s], "yesterday")
            t = self._scenario_rate([s], "today")
            if y["total"] >= 1 and t["total"] >= 1:
                y_err = 100 - y["success_rate"]
                t_err = 100 - t["success_rate"]
                inc = round(t_err - y_err, 2)
                if inc > 0:
                    sc = scenario(s)
                    anomalies.append({"scenario_id": s, "code": sc["code"], "family": sc["family"],
                                      "error_rate_yesterday": round(y_err, 2),
                                      "error_rate_today": round(t_err, 2), "increase": inc})
        anomalies.sort(key=lambda x: x["increase"], reverse=True)
        if not anomalies:
            return self._reply("anomaly_detection", role,
                               "No se detectaron escenarios con incremento de fallos entre ayer y hoy.")
        top = anomalies[0]
        answer = (
            f"Anomalia detectada: el escenario #{top['scenario_id']} ({top['code']}) aumento su tasa de "
            f"error de {top['error_rate_yesterday']}% (ayer) a {top['error_rate_today']}% (hoy), "
            f"un incremento de {top['increase']} puntos. El incremento comenzo hoy."
        )
        return self._reply("anomaly_detection", role, answer, tool="tool_anomaly_detection",
                           data={"anomalies": anomalies})

    def tool_retry_analysis(self, role: str) -> dict:
        """2.5 Escenarios con mas reintentos + causas."""
        rows = self.conn.execute(
            """
            SELECT scenario_id, COUNT(*) retries FROM processing_runs
            WHERE retry_number > 0 GROUP BY scenario_id ORDER BY retries DESC
            """
        ).fetchall()
        ranking = []
        for r in rows:
            sc = scenario(r["scenario_id"])
            cause = self.conn.execute(
                "SELECT error_code, COUNT(*) c FROM processing_runs "
                "WHERE scenario_id=? AND retry_number>0 AND error_code IS NOT NULL "
                "GROUP BY error_code ORDER BY c DESC LIMIT 1", (r["scenario_id"],),
            ).fetchone()
            ranking.append({"scenario_id": r["scenario_id"], "code": sc["code"],
                            "retries": r["retries"],
                            "top_cause": cause["error_code"] if cause else None})
        if not ranking:
            return self._reply("retry_analysis", role, "No hay reintentos registrados.")
        top = ranking[0]
        answer = (f"El escenario con mas reintentos es #{top['scenario_id']} ({top['code']}) con "
                  f"{top['retries']} reintentos. Causa principal: {top['top_cause']}.")
        return self._reply("retry_analysis", role, answer, tool="tool_retry_analysis",
                           data={"ranking": ranking})

    # ================================================================== #
    # BLOQUE 3 · PNR / PASAJEROS
    # ================================================================== #
    def tool_multipax_errors(self, role: str) -> dict:
        """3.1 PNR multipasajero con errores + correlacion nº pax/fallos."""
        rows = self.conn.execute(
            """
            SELECT p.pnr_id, COUNT(DISTINCT pax.id) npax,
                   SUM(CASE WHEN pr.result='ERROR' THEN 1 ELSE 0 END) errors
            FROM pnrs p
            JOIN pnr_passengers pax ON pax.pnr_id = p.pnr_id
            LEFT JOIN processing_runs pr ON pr.pnr_id = p.pnr_id
            GROUP BY p.pnr_id
            """
        ).fetchall()
        multi_err = [{"pnr_id": r["pnr_id"], "passengers": r["npax"], "errors": r["errors"] or 0}
                     for r in rows if r["npax"] > 1 and (r["errors"] or 0) > 0]
        multi_err.sort(key=lambda x: (x["passengers"], x["errors"]), reverse=True)
        # Correlacion simple: promedio de errores por tamano de grupo
        buckets: dict[int, list] = {}
        for r in rows:
            buckets.setdefault(r["npax"], []).append(r["errors"] or 0)
        corr = {k: round(sum(v) / len(v), 2) for k, v in sorted(buckets.items())}
        trend = ("A mayor numero de pasajeros, mayor promedio de errores"
                 if len(corr) >= 2 and list(corr.values())[-1] >= list(corr.values())[0]
                 else "No se observa una relacion creciente clara")
        answer = (
            f"Hay {len(multi_err)} PNR multipasajero con errores. "
            f"Promedio de errores por tamano de grupo: "
            + ", ".join(f"{k} pax={v}" for k, v in corr.items())
            + f". {trend}."
        )
        return self._reply("multipax_errors", role, answer, tool="tool_multipax_errors",
                           data={"multipax_with_errors": multi_err[:15], "avg_errors_by_group_size": corr})

    def tool_loop_detection(self, role: str) -> dict:
        """3.2 PNR con 3+ ERROR y ningun OK (bucles sin completar)."""
        rows = self.conn.execute(
            """
            SELECT pnr_id,
                   SUM(CASE WHEN result='ERROR' THEN 1 ELSE 0 END) errors,
                   SUM(CASE WHEN result='OK' THEN 1 ELSE 0 END) oks
            FROM processing_runs GROUP BY pnr_id
            HAVING errors >= 3 AND oks = 0 ORDER BY errors DESC
            """
        ).fetchall()
        loops = [{"pnr_id": r["pnr_id"], "errors": r["errors"]} for r in rows]
        if not loops:
            return self._reply("loop_detection", role,
                               "No se detectaron PNR en bucle (3+ errores sin exito).")
        answer = (f"Se detectaron {len(loops)} PNR en bucle de procesamiento (3+ errores sin ningun OK). "
                  f"El mas critico es {loops[0]['pnr_id']} con {loops[0]['errors']} intentos fallidos.")
        return self._reply("loop_detection", role, answer, tool="tool_loop_detection",
                           data={"loops": loops})

    def tool_attempt_history(self, pnr_id: Optional[str], role: str) -> dict:
        """3.3 Historial de intentos de un PNR (o de los que tienen >1 intento)."""
        if pnr_id:
            pnr_id = pnr_id.upper()
            runs = self.conn.execute(
                "SELECT run_id, started_at, finished_at, result, error_code, error_origin, retry_number "
                "FROM processing_runs WHERE pnr_id=? ORDER BY started_at", (pnr_id,),
            ).fetchall()
            if not runs:
                return self._reply("attempt_history", role, f"No hay historial de intentos para {pnr_id}.")
            hist = [{k: r[k] for k in r.keys()} for r in runs]
            steps = "; ".join(
                f"intento {r['retry_number']+1}: {r['result']}" + (f" ({r['error_code']})" if r['error_code'] else "")
                for r in runs
            )
            answer = f"Historial de {pnr_id} ({len(runs)} intentos): {steps}."
            return self._reply("attempt_history", role, answer, tool="tool_attempt_history",
                               data={"pnr_id": pnr_id, "runs": hist})
        # Sin PNR: listar los que tienen mas de un intento
        rows = self.conn.execute(
            "SELECT pnr_id, COUNT(*) attempts FROM processing_runs GROUP BY pnr_id "
            "HAVING attempts > 1 ORDER BY attempts DESC LIMIT 15"
        ).fetchall()
        multi = [{"pnr_id": r["pnr_id"], "attempts": r["attempts"]} for r in rows]
        answer = (f"Hay {len(multi)} PNR con mas de un intento de procesamiento. "
                  "Indica un PNR para ver el detalle de cada intento (ej. 'historial de intentos del PNR XXXXXX').")
        return self._reply("attempt_history", role, answer, tool="tool_attempt_history",
                           data={"multi_attempt": multi})

    def tool_inconsistent_states(self, role: str) -> dict:
        """3.4 PNR con ultimo run OK pero balance UNBALANCED (o viceversa)."""
        rows = self.conn.execute(
            """
            SELECT p.pnr_id, p.balance_status,
                   (SELECT result FROM processing_runs r WHERE r.pnr_id=p.pnr_id
                    ORDER BY started_at DESC LIMIT 1) last_result
            FROM pnrs p
            """
        ).fetchall()
        inconsistent = []
        for r in rows:
            lr = r["last_result"]
            if lr == "OK" and r["balance_status"] == "UNBALANCED":
                inconsistent.append({"pnr_id": r["pnr_id"], "last_result": lr,
                                     "balance_status": r["balance_status"],
                                     "issue": "ultimo run OK pero sigue UNBALANCED"})
            elif lr == "ERROR" and r["balance_status"] == "BALANCED":
                inconsistent.append({"pnr_id": r["pnr_id"], "last_result": lr,
                                     "balance_status": r["balance_status"],
                                     "issue": "ultimo run ERROR pero figura BALANCED"})
        if not inconsistent:
            return self._reply("inconsistent_states", role, "No se detectaron estados inconsistentes.")
        answer = (f"Se detectaron {len(inconsistent)} PNR en estado inconsistente tras el procesamiento. "
                  f"Ejemplo: {inconsistent[0]['pnr_id']} - {inconsistent[0]['issue']}.")
        return self._reply("inconsistent_states", role, answer, tool="tool_inconsistent_states",
                           data={"inconsistent": inconsistent})

    def tool_ssr_concentration(self, role: str) -> dict:
        """3.5 Concentracion de errores por codigo SSR y por tipo de transaccion."""
        pax_rows = self.conn.execute(
            """
            SELECT pax.ssr_codes, COUNT(*) err
            FROM pnr_passengers pax
            JOIN processing_runs pr ON pr.pnr_id = pax.pnr_id AND pr.result='ERROR'
            GROUP BY pax.id
            """
        ).fetchall()
        ssr_count: dict[str, int] = {}
        for r in pax_rows:
            for code in (r["ssr_codes"] or "").split(","):
                code = code.strip()
                if code:
                    ssr_count[code] = ssr_count.get(code, 0) + r["err"]
        ssr_sorted = sorted(ssr_count.items(), key=lambda x: x[1], reverse=True)
        tc_rows = self.conn.execute(
            """
            SELECT t.tc_code, COUNT(*) c FROM transactions t
            WHERE t.pnr_id IN (SELECT DISTINCT pnr_id FROM processing_runs WHERE result='ERROR')
            GROUP BY t.tc_code ORDER BY c DESC
            """
        ).fetchall()
        tc = {r["tc_code"]: r["c"] for r in tc_rows}
        if not ssr_sorted:
            return self._reply("ssr_concentration", role, "No hay errores asociados a codigos SSR.")
        top_ssr = ssr_sorted[0]
        answer = (
            f"Los errores se concentran en el SSR '{top_ssr[0]}' ({top_ssr[1]} incidencias). "
            f"Distribucion SSR: " + ", ".join(f"{k}={v}" for k, v in ssr_sorted[:5])
            + ". Codigos de transaccion en casos fallidos: " + ", ".join(f"{k}={v}" for k, v in tc.items()) + "."
        )
        return self._reply("ssr_concentration", role, answer, tool="tool_ssr_concentration",
                           data={"by_ssr": dict(ssr_sorted), "by_tc": tc})

    # ================================================================== #
    # BLOQUE 4 · BALANCE / DEUDA / TRANSACCIONES
    # ================================================================== #
    def tool_desbalance_transactions(self, role: str) -> dict:
        """4.1 / 4.2 PNR con balance != 0 y transacciones que lo explican."""
        rows = self.conn.execute(
            "SELECT * FROM pnrs WHERE balance_status='UNBALANCED' "
            "ORDER BY (total_fare-total_paid) DESC"
        ).fetchall()
        cases = []
        for r in rows:
            txns = self.conn.execute(
                "SELECT tc_code, amount, debtor FROM transactions WHERE pnr_id=?", (r["pnr_id"],)
            ).fetchall()
            cases.append({
                "pnr_id": r["pnr_id"],
                "pending_amount": round(r["total_fare"] - r["total_paid"], 2),
                "scenario_id": r["scenario_id"],
                "transactions": [{k: t[k] for k in t.keys()} for t in txns],
            })
        # Frecuencia de TC que generan diferencias
        tc_freq_rows = self.conn.execute(
            "SELECT tc_code, COUNT(*) c FROM transactions GROUP BY tc_code ORDER BY c DESC"
        ).fetchall()
        tc_freq = {r["tc_code"]: r["c"] for r in tc_freq_rows}
        top_tc = next(iter(tc_freq), "N/A")
        answer = (
            f"Hay {len(cases)} PNR con balance diferente de cero. El de mayor diferencia es "
            f"{cases[0]['pnr_id']} (${cases[0]['pending_amount']:,.2f}), explicado por "
            f"{len(cases[0]['transactions'])} transaccion(es). "
            f"La transaccion que genera diferencias con mas frecuencia es '{top_tc}'."
        ) if cases else "No hay PNR con balance diferente de cero."
        return self._reply("desbalance_transactions", role, answer,
                           tool="tool_desbalance_transactions",
                           data={"count": len(cases), "cases": cases[:25], "tc_frequency": tc_freq})

    def tool_tc_frequency(self, role: str) -> dict:
        """4.3 Frecuencia de codigos TC en los PNR con runs ERROR."""
        rows = self.conn.execute(
            """
            SELECT t.tc_code, COUNT(*) c FROM transactions t
            WHERE t.pnr_id IN (SELECT DISTINCT pnr_id FROM processing_runs WHERE result='ERROR')
            GROUP BY t.tc_code ORDER BY c DESC
            """
        ).fetchall()
        freq = {r["tc_code"]: r["c"] for r in rows}
        if not freq:
            return self._reply("tc_frequency", role, "No hay transacciones en casos fallidos.")
        top = next(iter(freq))
        answer = (f"En los casos fallidos, el codigo de transaccion mas frecuente es '{top}' ({freq[top]}). "
                  f"Distribucion: " + ", ".join(f"{k}={v}" for k, v in freq.items()) + ".")
        return self._reply("tc_frequency", role, answer, tool="tool_tc_frequency",
                           data={"tc_frequency": freq})

    def tool_debt_classification(self, role: str) -> dict:
        """4.4 Deuda del CLIENTE vs deuda de la AEROLINEA/JetSMART, con ejemplos."""
        rows = self.conn.execute(
            "SELECT debtor, COUNT(DISTINCT pnr_id) pnrs, SUM(amount) total FROM transactions GROUP BY debtor"
        ).fetchall()
        summary = {r["debtor"]: {"pnrs": r["pnrs"], "total": round(r["total"] or 0, 2)} for r in rows}
        ex_client = self.conn.execute(
            "SELECT pnr_id, tc_code, amount FROM transactions WHERE debtor='CLIENT' ORDER BY amount DESC LIMIT 1"
        ).fetchone()
        ex_airline = self.conn.execute(
            "SELECT pnr_id, tc_code, amount FROM transactions WHERE debtor='AIRLINE' ORDER BY amount DESC LIMIT 1"
        ).fetchone()
        parts = []
        if ex_client:
            parts.append(f"deuda del CLIENTE ej. {ex_client['pnr_id']} (TC {ex_client['tc_code']}, ${ex_client['amount']:,.2f})")
        if ex_airline:
            parts.append(f"deuda de la AEROLINEA/JetSMART ej. {ex_airline['pnr_id']} (TC {ex_airline['tc_code']}, ${ex_airline['amount']:,.2f})")
        answer = (
            "Clasificacion de deuda: "
            + "; ".join(parts) + ". "
            + "Resumen: " + ", ".join(f"{k}={v['pnrs']} PNR / ${v['total']:,.2f}" for k, v in summary.items()) + "."
        )
        return self._reply("debt_classification", role, answer, tool="tool_debt_classification",
                           data={"summary": summary,
                                 "example_client": dict(ex_client) if ex_client else None,
                                 "example_airline": dict(ex_airline) if ex_airline else None})

    def tool_failure_origin_7d(self, role: str) -> dict:
        """4.5 Errores de 7 dias clasificados por origen DATA/RBR_INTERNAL/EXTERNAL."""
        rows = self.conn.execute(
            """
            SELECT error_origin, COUNT(*) c FROM processing_runs
            WHERE result='ERROR' AND error_origin IS NOT NULL
              AND started_at >= datetime('now','-7 day','localtime')
            GROUP BY error_origin ORDER BY c DESC
            """
        ).fetchall()
        by_origin = {r["error_origin"]: r["c"] for r in rows}
        ext_detail_rows = self.conn.execute(
            """
            SELECT error_code, COUNT(*) c FROM processing_runs
            WHERE result='ERROR' AND error_origin='EXTERNAL'
              AND started_at >= datetime('now','-7 day','localtime')
            GROUP BY error_code ORDER BY c DESC
            """
        ).fetchall()
        ext_detail = {r["error_code"]: r["c"] for r in ext_detail_rows}
        if not by_origin:
            return self._reply("failure_origin_7d", role, "No hay errores en los ultimos 7 dias.")
        total = sum(by_origin.values())
        answer = (
            f"Errores de los ultimos 7 dias ({total} en total) por origen: "
            f"problemas de datos/PNR = {by_origin.get('DATA', 0)}, "
            f"errores internos de RBR = {by_origin.get('RBR_INTERNAL', 0)}, "
            f"problemas externos (Navitaire/auth/token) = {by_origin.get('EXTERNAL', 0)}. "
            f"Detalle externo: " + (", ".join(f"{k}={v}" for k, v in ext_detail.items()) or "N/A") + "."
        )
        return self._reply("failure_origin_7d", role, answer, tool="tool_failure_origin_7d",
                           data={"by_origin": by_origin, "external_detail": ext_detail})

    # ================================================================== #
    # RESUMEN EJECUTIVO (generativo con LLM, fallback a plantilla)
    # ================================================================== #
    def executive_summary(self, role: str = "Finanzas") -> dict:
        """Informe de 3 parrafos para Finanzas y Operaciones. Usa LLM real si
        hay credenciales; si no, genera el texto con una plantilla local."""
        m = self.compute_metrics()
        day = self._run_stats("today")
        origin = self.conn.execute(
            "SELECT error_origin, COUNT(*) c FROM processing_runs "
            "WHERE result='ERROR' AND error_origin IS NOT NULL "
            "AND started_at >= datetime('now','-1 day','localtime') "
            "GROUP BY error_origin ORDER BY c DESC"
        ).fetchall()
        by_origin = {r["error_origin"]: r["c"] for r in origin}
        worst = self.conn.execute(
            "SELECT scenario_id, COUNT(*) c FROM processing_runs "
            "WHERE result='ERROR' GROUP BY scenario_id ORDER BY c DESC LIMIT 1"
        ).fetchone()
        worst_txt = (f"#{worst['scenario_id']} ({scenario(worst['scenario_id'])['code']})"
                     if worst else "N/A")
        routes = self._route_risk(threshold=15.0)

        facts = {
            "total_pnrs": m["total_pnrs"], "balanced": m["balanced"], "unbalanced": m["unbalanced"],
            "success_rate": m["success_rate"], "pending_revenue_usd": m["pending_revenue_usd"],
            "pending_by_queue": m["pending_by_queue"],
            "runs_today": day, "errors_by_origin_24h": by_origin,
            "worst_scenario": worst_txt, "routes_at_risk": routes[:5],
        }

        # 1) Intento con LLM real
        if self.llm is not None and self.llm.is_live():
            system = ("Eres un analista financiero y de operaciones de una aerolinea. "
                      "Redacta un resumen ejecutivo claro y accionable en espanol, de exactamente "
                      "3 parrafos, para las areas de Finanzas y Operaciones. Primer parrafo: estado "
                      "general y tasa de exito. Segundo: ingresos pendientes y colas. Tercero: riesgos "
                      "(escenario critico y rutas en alerta) y recomendacion.")
            prompt = f"Datos consolidados del dia (JSON): {facts}"
            text = self.llm.generate(system, prompt, max_tokens=700)
            if text:
                return self._reply("executive_summary", role, text,
                                   tool="executive_summary",
                                   data={"facts": facts, "mode": self.llm_mode})

        # 2) Fallback: plantilla local de 3 parrafos
        p1 = (
            f"Estado general del dia: se gestionan {m['total_pnrs']} reservas, de las cuales "
            f"{m['balanced']} estan conciliadas (BALANCED) y {m['unbalanced']} presentan desbalance. "
            f"La tasa de exito global es de {m['success_rate']}%. Hoy el RBR ejecuto "
            f"{day['total']} procesos ({day['ok']} OK, {day['error']} con error, "
            f"{day['unprocessed']} sin procesar)."
        )
        colas = ", ".join(f"{q}=${v:,.0f}" for q, v in m["pending_by_queue"].items()) or "sin pendientes"
        p2 = (
            f"Impacto financiero: hay ${m['pending_revenue_usd']:,.2f} en ingresos pendientes por liberar. "
            f"El desglose por cola operativa es: {colas}. Estos montos representan la prioridad de "
            f"conciliacion para el area de Finanzas."
        )
        orig_txt = ", ".join(f"{k}={v}" for k, v in by_origin.items()) or "sin fallos en 24h"
        rutas_txt = (", ".join(f"{r['route']} ({r['error_rate']}%)" for r in routes[:3])
                     if routes else "ninguna ruta supera el umbral de riesgo")
        p3 = (
            f"Riesgos y recomendacion: el escenario que mas errores concentra es {worst_txt}, y los "
            f"fallos de las ultimas 24h se originan en {orig_txt}. Rutas en alerta: {rutas_txt}. "
            f"Se recomienda priorizar la conciliacion de las colas con mayor monto y revisar los "
            f"escenarios y rutas senalados para contener el impacto a pasajeros."
        )
        text = f"{p1}\n\n{p2}\n\n{p3}"
        return self._reply("executive_summary", role, text, tool="executive_summary",
                           data={"facts": facts, "mode": "rules"})

    # ================================================================== #
    # ALERTAS TEMPRANAS POR RUTA
    # ================================================================== #
    def _route_risk(self, threshold: float = 15.0, min_pnrs: int = 3) -> list:
        """Rutas cuyo % de reservas con ERROR en ultimas 24h supera el umbral.
        Se exige un minimo de PNRs por ruta (min_pnrs) para que la alerta sea
        estadisticamente significativa y no la disparen rutas con 1-2 reservas."""
        rows = self.conn.execute(
            """
            SELECT p.route,
                   COUNT(DISTINCT p.pnr_id) total_pnrs,
                   COUNT(DISTINCT CASE WHEN pr.result='ERROR'
                         AND pr.started_at >= datetime('now','-1 day','localtime')
                         THEN p.pnr_id END) err_pnrs
            FROM pnrs p
            LEFT JOIN processing_runs pr ON pr.pnr_id = p.pnr_id
            GROUP BY p.route
            """
        ).fetchall()
        risk = []
        for r in rows:
            total = r["total_pnrs"] or 0
            errs = r["err_pnrs"] or 0
            if total < min_pnrs:
                continue
            rate = round((errs / total) * 100, 2)
            if rate >= threshold:
                risk.append({"route": r["route"], "total_pnrs": total,
                             "error_pnrs": errs, "error_rate": rate})
        risk.sort(key=lambda x: (x["error_rate"], x["total_pnrs"]), reverse=True)
        return risk

    def tool_route_risk(self, role: str, threshold: float = 15.0) -> dict:
        """4.predictivo: alertas tempranas de rutas en riesgo."""
        risk = self._route_risk(threshold)
        if not risk:
            return self._reply("route_risk", role,
                               f"Ninguna ruta supera el umbral de riesgo del {threshold}% en 24h.",
                               tool="tool_route_risk", data={"threshold": threshold, "routes": []})
        top = risk[0]
        answer = (
            f"ALERTA: {len(risk)} ruta(s) superan el umbral de riesgo del {threshold}% de reservas "
            f"con error en 24h. La mas critica es {top['route']} con {top['error_rate']}% "
            f"({top['error_pnrs']}/{top['total_pnrs']} PNRs)."
        )
        return self._reply("route_risk", role, answer, tool="tool_route_risk",
                           data={"threshold": threshold, "routes": risk})

    # ================================================================== #
    # GESTION NO-CODE + BALANCEO MASIVO
    # ================================================================== #
    def is_scenario_enabled(self, scenario_id: int) -> bool:
        """Lee scenario_config.enabled. Si la tabla no existe o no hay fila,
        se asume habilitado (compatibilidad hacia atras)."""
        try:
            row = self.conn.execute(
                "SELECT enabled FROM scenario_config WHERE scenario_id = ?", (scenario_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            return True
        if row is None:
            return True
        return bool(row["enabled"])

    def _parse_bulk_scope(self, text: str) -> dict:
        """Determina el alcance del balanceo masivo a partir del prompt."""
        low = self._norm(text)
        # Cola explicita
        for q in ("SLRCVR", "UBPPMT", "DELDEV", "GENERAL"):
            if q.lower() in low:
                return {"type": "queue", "value": q, "label": f"la cola {q}"}
        # Escenario por numero
        m = SCEN_NUM_RE.search(text)
        if m:
            sid = int(m.group(1))
            return {"type": "scenario", "value": sid,
                    "label": f"el escenario {sid} ({scenario(sid)['code']})"}
        # Familia
        for fam, kw in (("SEAT_CHANGE", "seat"), ("CREDIT_SHELL", "credit"),
                        ("VOUCHERS", "voucher"), ("NAME_CHANGE_FEE", "name change")):
            if kw in low:
                return {"type": "family", "value": fam, "label": f"la familia {fam}"}
        # Todos
        return {"type": "all", "value": None, "label": "todas las reservas desbalanceadas"}

    def tool_balance_bulk(self, text: str, role: str) -> dict:
        """Balanceo masivo por cola / escenario / familia / todos. Respeta las
        reglas desactivadas en scenario_config (no las balancea)."""
        scope = self._parse_bulk_scope(text)
        sql = "SELECT * FROM pnrs WHERE balance_status='UNBALANCED'"
        params: list = []
        if scope["type"] == "queue":
            sql += " AND queue = ?"; params.append(scope["value"])
        elif scope["type"] == "scenario":
            sql += " AND scenario_id = ?"; params.append(scope["value"])
        elif scope["type"] == "family":
            ids = scenario_ids_for_family(scope["value"])
            if not ids:
                return self._reply("balance_bulk", role, f"Familia {scope['value']} sin escenarios.")
            sql += f" AND scenario_id IN ({','.join('?' for _ in ids)})"; params.extend(ids)

        rows = self.conn.execute(sql, params).fetchall()
        balanced, skipped, total_adjusted = 0, 0, 0.0
        skipped_scenarios: dict[int, int] = {}
        balanced_ids = []
        for r in rows:
            sid = r["scenario_id"]
            if not self.is_scenario_enabled(sid):
                skipped += 1
                skipped_scenarios[sid] = skipped_scenarios.get(sid, 0) + 1
                continue
            diff = abs(round(r["total_fare"] - r["total_paid"], 2))
            sc = scenario(sid)
            self.conn.execute(
                """
                UPDATE pnrs SET total_paid = total_fare, balance_status='BALANCED',
                       scenario_id = 0,
                       scenario_description = ?
                WHERE pnr_id = ?
                """,
                (f"Conciliado masivamente por el RBR (origen: Escenario {sid} - {sc['code']})", r["pnr_id"]),
            )
            balanced += 1
            total_adjusted += diff
            balanced_ids.append(r["pnr_id"])
        self.conn.commit()

        skip_txt = ""
        if skipped:
            det = ", ".join(f"#{s}={c}" for s, c in sorted(skipped_scenarios.items()))
            skip_txt = (f" Se omitieron {skipped} PNR por tener su escenario DESACTIVADO "
                        f"en la configuracion ({det}).")
        answer = (
            f"Balanceo masivo sobre {scope['label']}: {balanced} PNR conciliados "
            f"(${total_adjusted:,.2f} ajustados).{skip_txt}"
        )
        return self._reply("balance_bulk", role, answer, tool="tool_balance_bulk",
                           data={"scope": scope, "balanced": balanced, "skipped": skipped,
                                 "total_adjusted": round(total_adjusted, 2),
                                 "skipped_by_scenario": skipped_scenarios,
                                 "balanced_pnrs": balanced_ids[:50]})

    # ------------------------------------------------------------------ #
    # Metricas compartidas
    # ------------------------------------------------------------------ #
    def compute_metrics(self) -> dict:
        rows = self.conn.execute("SELECT * FROM pnrs").fetchall()
        total = len(rows)
        balanced = sum(1 for r in rows if r["balance_status"] == "BALANCED")
        unbalanced = total - balanced

        pending_revenue = 0.0
        pending_by_queue: dict[str, float] = {}
        for r in rows:
            diff = r["total_fare"] - r["total_paid"]
            if r["balance_status"] == "UNBALANCED" and diff > 0:
                pending_revenue += diff
                pending_by_queue[r["queue"]] = round(pending_by_queue.get(r["queue"], 0.0) + diff, 2)

        success_rate = round((balanced / total) * 100, 2) if total else 0.0
        return {
            "total_pnrs": total,
            "balanced": balanced,
            "unbalanced": unbalanced,
            "success_rate": success_rate,
            "pending_revenue_usd": round(pending_revenue, 2),
            "pending_by_queue": pending_by_queue,
        }

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _row_to_pnr(self, row: sqlite3.Row) -> dict:
        d = {k: row[k] for k in row.keys()}
        d["pending_amount"] = round(d["total_fare"] - d["total_paid"], 2)
        return d

    def _notes_for(self, pnr_id: str) -> list:
        rows = self.conn.execute(
            "SELECT id, pnr_id, author, note, created_at FROM internal_notes "
            "WHERE pnr_id = ? ORDER BY id DESC",
            (pnr_id,),
        ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def _extract_pnr(self, text: str) -> Optional[str]:
        # Ignora tokens de solo digitos (fechas, montos) y palabras comunes
        stop = {"PENDIE", "BALANC", "ESCENA"}
        for token in PNR_RE.findall(text):
            if token.isdigit():
                continue
            if not re.search(r"[A-Za-z]", token):
                continue
            if token.upper() in stop:
                continue
            return token.upper()
        return None

    def _parse_date(self, value: str) -> Optional[datetime]:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _norm(self, text: str) -> str:
        """Minusculas sin acentos para matching robusto."""
        s = (text or "").lower()
        for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
            s = s.replace(a, b)
        return s

    # ---- Helpers de analitica temporal sobre processing_runs ---- #
    def _window_clause(self, window: str) -> str:
        """Devuelve la condicion SQL para una ventana temporal sobre started_at."""
        if window == "today":
            return "date(started_at)=date('now','localtime')"
        if window == "yesterday":
            return "date(started_at)=date('now','-1 day','localtime')"
        if window == "7d":
            return "started_at >= datetime('now','-7 day','localtime')"
        # default 24h
        return "started_at >= datetime('now','-1 day','localtime')"

    def _run_stats(self, window: str) -> dict:
        clause = self._window_clause(window)
        row = self.conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN result='OK' THEN 1 ELSE 0 END) ok,
                SUM(CASE WHEN result='ERROR' THEN 1 ELSE 0 END) error,
                SUM(CASE WHEN result='UNPROCESSED' THEN 1 ELSE 0 END) unprocessed,
                COUNT(*) total
            FROM processing_runs WHERE {clause}
            """
        ).fetchone()
        ok = row["ok"] or 0
        err = row["error"] or 0
        unp = row["unprocessed"] or 0
        total = row["total"] or 0
        rate = round((ok / total) * 100, 2) if total else 0.0
        return {"ok": ok, "error": err, "unprocessed": unp, "total": total, "success_rate": rate}

    def _scenario_rate(self, scope_ids: list, window: str) -> dict:
        clause = self._window_clause(window)
        placeholders = ",".join("?" for _ in scope_ids)
        row = self.conn.execute(
            f"""
            SELECT SUM(CASE WHEN result='OK' THEN 1 ELSE 0 END) ok, COUNT(*) total
            FROM processing_runs WHERE {clause} AND scenario_id IN ({placeholders})
            """, scope_ids,
        ).fetchone()
        ok = row["ok"] or 0
        total = row["total"] or 0
        rate = round((ok / total) * 100, 2) if total else 0.0
        return {"ok": ok, "total": total, "success_rate": rate}

    def _top_error_codes(self, window: str, limit: int = 3) -> list:
        clause = self._window_clause(window)
        rows = self.conn.execute(
            f"""
            SELECT error_code, COUNT(*) count FROM processing_runs
            WHERE result='ERROR' AND error_code IS NOT NULL AND {clause}
            GROUP BY error_code ORDER BY count DESC LIMIT ?
            """, (limit,),
        ).fetchall()
        return [{"error_code": r["error_code"], "count": r["count"]} for r in rows]

    def _top_error_codes_for_scenario(self, sid: int, limit: int = 3) -> list:
        rows = self.conn.execute(
            """
            SELECT error_code, COUNT(*) count FROM processing_runs
            WHERE result='ERROR' AND error_code IS NOT NULL AND scenario_id=?
            GROUP BY error_code ORDER BY count DESC LIMIT ?
            """, (sid, limit),
        ).fetchall()
        return [{"error_code": r["error_code"], "count": r["count"]} for r in rows]

    def _reply(self, intent: str, role: str, answer: str,
               tool: Optional[str] = None, data: Optional[dict] = None) -> dict:
        return {
            "intent": intent,
            "role": role,
            "tool": tool,
            "answer": answer,
            "data": data or {},
        }
