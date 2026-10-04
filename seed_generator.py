"""
RBR Airline Insight Engine & Agent Lab
Seed Generator (v0.4.0-Lab)

Crea la base de datos SQLite local (rbr_local_lab.db) con las tablas:
    - pnrs            : 250 PNRs sinteticos (40% BALANCED / 60% UNBALANCED)
    - internal_notes  : notas internas entre departamentos
    - processing_runs : historial de ejecuciones/intentos del RBR por PNR
    - pnr_passengers  : pasajeros por PNR (multipasajero) con codigos SSR
    - transactions    : transacciones financieras (TC/DD/AD/CC/CD/PC) por PNR
    - pnr_audit_logs  : bitacora cronologica por PNR (timeline)
    - scenario_config : configuracion editable (no-code) de las 24 reglas

El seeding es reproducible (random.seed(42)) para una auditoria consistente.
Los runs se distribuyen en los ultimos 7 dias, con densidad en las ultimas 24h
y en "hoy", e incluyen errores con origen (DATA/RBR_INTERNAL/EXTERNAL),
reintentos, bucles (3+ ERROR sin OK) y estados inconsistentes.

Uso:
    python seed_generator.py
"""

import json
import os
import random
import sqlite3
from datetime import datetime, timedelta

from scenarios import SCENARIOS, UNBALANCED_SCENARIO_IDS, scenario

# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "rbr_local_lab.db")
# Respaldo principal (dataset de 250 PNRs) + alias de compatibilidad (100).
JSON_BACKUP_PATH = os.path.join(BASE_DIR, "pnr_test_250.json")
JSON_LEGACY_PATH = os.path.join(BASE_DIR, "pnr_seed_100.json")

SEED = 42
TOTAL_PNRS = 250
BALANCED_RATIO = 0.40  # 40% BALANCED, 60% UNBALANCED

QUEUES = ["SLRCVR", "UBPPMT", "DELDEV", "GENERAL"]

FIRST_NAMES = [
    "MARIA", "JOSE", "JUAN", "ANA", "LUIS", "CARMEN", "PEDRO", "LAURA",
    "CARLOS", "SOFIA", "MIGUEL", "ELENA", "JORGE", "PAULA", "DIEGO",
    "VALERIA", "ANDRES", "ISABELLA", "FERNANDO", "CAMILA", "RICARDO",
    "GABRIELA", "ALBERTO", "DANIELA", "SERGIO", "LUCIA", "RAFAEL", "NATALIA",
]
LAST_NAMES = [
    "GARCIA", "RODRIGUEZ", "MARTINEZ", "LOPEZ", "GONZALEZ", "PEREZ",
    "SANCHEZ", "RAMIREZ", "TORRES", "FLORES", "RIVERA", "GOMEZ",
    "DIAZ", "REYES", "CRUZ", "MORALES", "ORTIZ", "GUTIERREZ", "CHAVEZ",
    "RUIZ", "JIMENEZ", "MENDOZA", "VARGAS", "CASTILLO", "ROMERO",
]
AIRLINE_CODES = ["AV", "LA", "CM", "AM", "AA", "UA", "DL", "IB", "HX", "AMX"]
AIRPORTS = [
    "BOG", "MDE", "CTG", "CLO", "MIA", "JFK", "LAX", "MEX", "LIM",
    "SCL", "GRU", "PTY", "MAD", "EZE", "UIO", "SJO", "CUN", "GDL",
]

CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"

# Codigos SSR tipicos
SSR_CODES = ["SEAT", "BAGS", "MEAL", "WCHR", "UMNR", "PETC", "SPEQ"]

# Codigos de transaccion financiera
TC_CODES = ["TC", "DD", "AD", "CC", "CD", "PC"]

# Catalogo de causas de error por origen
ERROR_CODES = {
    "DATA": ["PNR_MISSING_FIELD", "FARE_MISMATCH", "INVALID_SSR", "PAX_NAME_MISMATCH"],
    "RBR_INTERNAL": ["RULE_TIMEOUT", "NULL_REFERENCE", "BALANCE_OVERFLOW", "QUEUE_LOCKED"],
    "EXTERNAL": ["NAVITAIRE_TIMEOUT", "TOKEN_EXPIRED", "AUTH_FAILED", "GDS_UNAVAILABLE"],
}
ERROR_ORIGINS = list(ERROR_CODES.keys())


# --------------------------------------------------------------------------- #
# Generadores sinteticos de PNR
# --------------------------------------------------------------------------- #
def gen_pnr_id() -> str:
    return "".join(random.choice(CHARS) for _ in range(6))


def gen_passenger_name() -> str:
    return f"{random.choice(LAST_NAMES)}/{random.choice(FIRST_NAMES)}"


def gen_flight_number() -> str:
    return f"{random.choice(AIRLINE_CODES)}{random.randint(100, 9999)}"


def gen_flight_date() -> str:
    offset_hours = random.choice(
        [random.randint(-30, 120) * 24, random.randint(1, 23), random.randint(1, 23)]
    )
    return (datetime.now() + timedelta(hours=offset_hours)).strftime("%Y-%m-%d %H:%M")


def gen_route() -> str:
    o = random.choice(AIRPORTS)
    d = random.choice([a for a in AIRPORTS if a != o])
    return f"{o}-{d}"


def build_pnr(balanced: bool) -> dict:
    total_fare = round(random.uniform(120.0, 2500.0), 2)

    if balanced:
        sid = 0
        total_paid = total_fare
        balance_status = "BALANCED"
    else:
        sid = random.choice(UNBALANCED_SCENARIO_IDS)
        sc = scenario(sid)
        balance_status = "UNBALANCED"
        if sc["sign"] == "credit":
            total_paid = round(total_fare + random.uniform(20.0, 450.0), 2)
        else:  # owed
            total_paid = round(max(0.0, total_fare - random.uniform(20.0, 500.0)), 2)

    sc = scenario(sid)
    return {
        "pnr_id": gen_pnr_id(),
        "passenger_name": gen_passenger_name(),
        "flight_number": gen_flight_number(),
        "flight_date": gen_flight_date(),
        "route": gen_route(),
        "total_fare": total_fare,
        "total_paid": total_paid,
        "balance_status": balance_status,
        "queue": random.choice(QUEUES),
        "scenario_id": sid,
        "scenario_description": sc["description"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def generate_pnrs() -> list:
    balanced_count = int(TOTAL_PNRS * BALANCED_RATIO)
    unbalanced_count = TOTAL_PNRS - balanced_count

    pnrs = [build_pnr(True) for _ in range(balanced_count)]
    pnrs += [build_pnr(False) for _ in range(unbalanced_count)]

    seen = set()
    for p in pnrs:
        while p["pnr_id"] in seen:
            p["pnr_id"] = gen_pnr_id()
        seen.add(p["pnr_id"])

    random.shuffle(pnrs)
    return pnrs


# --------------------------------------------------------------------------- #
# Notas internas
# --------------------------------------------------------------------------- #
def seed_notes(pnrs: list) -> list:
    authors = ["Finanzas", "Soporte", "Operaciones"]
    templates = [
        "Requiere aprobacion de Finanzas antes de liberar.",
        "Pasajero contacto por el canal de soporte; pendiente de respuesta.",
        "Posible contracargo, revisar emision del voucher.",
        "Validar diferencia tarifaria con la aerolinea operadora.",
        "Caso escalado a Operaciones por cercania del vuelo.",
    ]
    unbalanced = [p for p in pnrs if p["balance_status"] == "UNBALANCED"]
    random.shuffle(unbalanced)
    notes = []
    for p in unbalanced[:12]:
        notes.append({
            "pnr_id": p["pnr_id"],
            "author": random.choice(authors),
            "note": random.choice(templates),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
    return notes


# --------------------------------------------------------------------------- #
# Pasajeros (multipasajero) + SSR
# --------------------------------------------------------------------------- #
def seed_passengers(pnrs: list) -> tuple[list, dict]:
    """Genera pasajeros por PNR. Devuelve (filas, mapa pnr_id -> n_pax)."""
    rows = []
    pax_count: dict[str, int] = {}
    for p in pnrs:
        # Los PNR desbalanceados tienden a tener grupos mas grandes
        if p["balance_status"] == "UNBALANCED":
            n = random.choices([1, 2, 3, 4, 5], weights=[25, 25, 20, 18, 12])[0]
        else:
            n = random.choices([1, 2, 3, 4, 5], weights=[45, 30, 15, 7, 3])[0]
        pax_count[p["pnr_id"]] = n
        for i in range(n):
            name = p["passenger_name"] if i == 0 else gen_passenger_name()
            # 1 a 3 codigos SSR; SEAT y BAGS mas frecuentes
            ssr = random.sample(
                SSR_CODES,
                k=random.randint(1, 3),
            )
            # Sesgo hacia SEAT/BAGS
            if random.random() < 0.5 and "SEAT" not in ssr:
                ssr.append("SEAT")
            if random.random() < 0.4 and "BAGS" not in ssr:
                ssr.append("BAGS")
            rows.append({
                "pnr_id": p["pnr_id"],
                "passenger_name": name,
                "ssr_codes": ",".join(sorted(set(ssr))),
            })
    return rows, pax_count


# --------------------------------------------------------------------------- #
# Processing runs (historial de intentos)
# --------------------------------------------------------------------------- #
def _rand_dt_within(days_back: int) -> datetime:
    """Timestamp aleatorio entre hace `days_back` dias y ahora."""
    now = datetime.now()
    delta = timedelta(days=days_back) * random.random()
    return now - delta


def _ts_today() -> datetime:
    """Timestamp aleatorio dentro del dia de hoy (hasta ahora)."""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    secs = random.randint(0, max(1, int((now - start).total_seconds())))
    return start + timedelta(seconds=secs)


def _ts_within_hours(hours: int) -> datetime:
    now = datetime.now()
    return now - timedelta(hours=hours * random.random())


def seed_runs(pnrs: list, pax_count: dict) -> list:
    """
    Genera el historial de ejecuciones del RBR.
    - BALANCED: normalmente 1 run OK (reciente).
    - UNBALANCED: 1 a 4 runs, con ERROR(es); algunos forman bucles (3+ ERROR
      sin OK) y otros quedan UNPROCESSED. A mas pasajeros, mas probabilidad
      de ERROR (correlacion).
    - Estados inconsistentes: unos pocos PNR UNBALANCED con ultimo run OK.
    """
    runs = []
    inconsistent_budget = 4  # cuantos estados inconsistentes introducir

    for p in pnrs:
        pid = p["pnr_id"]
        sid = p["scenario_id"]
        sc = scenario(sid)
        npax = pax_count.get(pid, 1)

        if p["balance_status"] == "BALANCED":
            # 1 run OK, a veces precedido por 1 ERROR transitorio
            attempts = []
            if random.random() < 0.25:
                attempts.append("ERROR")
            attempts.append("OK")
        else:
            # Probabilidad de fallo sube con el numero de pasajeros
            base_err = min(0.9, 0.45 + 0.1 * (npax - 1))
            n = random.choices([1, 2, 3, 4], weights=[30, 30, 25, 15])[0]
            attempts = []
            for _ in range(n):
                attempts.append("ERROR" if random.random() < base_err else "OK")
            # Garantizar que haya desbalance coherente: si todo OK, forzar un ERROR
            if "ERROR" not in attempts:
                attempts[0] = "ERROR"
            # Algunos casos quedan UNPROCESSED (sin desenlace)
            if random.random() < 0.12:
                attempts = ["UNPROCESSED"]

        # Construir runs cronologicos
        # Primer intento mas antiguo (hasta 7 dias atras), ultimos mas recientes
        n_att = len(attempts)
        for idx, result in enumerate(attempts):
            # Reparto temporal: ultimo intento tiende a "hoy" / ultimas 24h
            if idx == n_att - 1:
                started = _ts_today() if random.random() < 0.6 else _ts_within_hours(24)
            else:
                started = _rand_dt_within(7)
            finished = started + timedelta(seconds=random.randint(1, 90))

            error_code = None
            error_origin = None
            if result == "ERROR":
                error_origin = random.choice(ERROR_ORIGINS)
                error_code = random.choice(ERROR_CODES[error_origin])

            runs.append({
                "pnr_id": pid,
                "started_at": started.isoformat(timespec="seconds"),
                "finished_at": finished.isoformat(timespec="seconds") if result != "UNPROCESSED" else None,
                "result": result,
                "error_code": error_code,
                "error_origin": error_origin,
                "retry_number": idx,
                "scenario_id": sid,
                "_sort": started,
            })

        # Introducir estados inconsistentes: PNR UNBALANCED cuyo ultimo run es OK
        if (p["balance_status"] == "UNBALANCED" and inconsistent_budget > 0
                and runs and runs[-1]["pnr_id"] == pid and runs[-1]["result"] != "OK"):
            runs[-1]["result"] = "OK"
            runs[-1]["error_code"] = None
            runs[-1]["error_origin"] = None
            runs[-1]["finished_at"] = (runs[-1]["_sort"] + timedelta(seconds=30)).isoformat(timespec="seconds")
            inconsistent_budget -= 1

    # Ordenar por fecha y limpiar campo auxiliar
    runs.sort(key=lambda r: r["_sort"])
    for r in runs:
        r.pop("_sort", None)
    return runs


# --------------------------------------------------------------------------- #
# Transacciones financieras
# --------------------------------------------------------------------------- #
def seed_transactions(pnrs: list, run_err_pnrs: set) -> list:
    """
    Para cada PNR UNBALANCED, genera 1..3 transacciones cuya suma explica la
    diferencia (total_fare - total_paid). debtor = CLIENT si el cliente debe
    (sign owed), AIRLINE si hay saldo a favor del cliente (sign credit).
    Los PNR con runs ERROR sesgan hacia tc_code 'AD' y 'CC'.
    """
    rows = []
    for p in pnrs:
        if p["balance_status"] != "UNBALANCED":
            continue
        sc = scenario(p["scenario_id"])
        diff = round(p["total_fare"] - p["total_paid"], 2)  # >0: cliente debe
        debtor = "CLIENT" if sc["sign"] == "owed" else "AIRLINE"

        n = random.randint(1, 3)
        # Reparto del diff en n montos
        remaining = diff
        has_error = p["pnr_id"] in run_err_pnrs
        for i in range(n):
            if i == n - 1:
                amount = round(remaining, 2)
            else:
                part = round(remaining * random.uniform(0.2, 0.6), 2)
                amount = part
                remaining = round(remaining - part, 2)
            if has_error and random.random() < 0.6:
                tc = random.choice(["AD", "CC"])
            else:
                tc = random.choice(TC_CODES)
            rows.append({
                "pnr_id": p["pnr_id"],
                "tc_code": tc,
                "amount": amount,
                "debtor": debtor,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
    return rows


# --------------------------------------------------------------------------- #
# Audit logs (linea de tiempo por PNR)
# --------------------------------------------------------------------------- #
def seed_audit_logs(pnrs: list, runs: list, notes: list) -> list:
    """
    Construye la bitacora cronologica de cada PNR a partir de:
      - creacion y estado inicial
      - cada intento de procesamiento (processing_runs)
      - transiciones de estado
      - notas internas
    """
    logs = []
    runs_by_pnr: dict[str, list] = {}
    for r in runs:
        runs_by_pnr.setdefault(r["pnr_id"], []).append(r)

    pnr_map = {p["pnr_id"]: p for p in pnrs}

    for p in pnrs:
        pid = p["pnr_id"]
        created = p["created_at"]
        # 1) Creacion / estado inicial
        logs.append({
            "pnr_id": pid, "event_type": "CREATED",
            "description": (f"PNR creado. Estado inicial: {p['balance_status']}"
                            + ("" if p["balance_status"] == "BALANCED"
                               else f" (escenario {p['scenario_id']} - {p['scenario_description']}).")),
            "performed_by": "SYSTEM", "timestamp": created,
        })
        # 2) Intentos de procesamiento del RBR
        prev_state = p["balance_status"]
        for r in sorted(runs_by_pnr.get(pid, []), key=lambda x: x["started_at"]):
            if r["result"] == "ERROR":
                desc = f"Intento #{r['retry_number']+1}: ERROR ({r['error_code']} / {r['error_origin']})."
            elif r["result"] == "OK":
                desc = f"Intento #{r['retry_number']+1}: OK."
            else:
                desc = f"Intento #{r['retry_number']+1}: sin procesar (UNPROCESSED)."
            logs.append({
                "pnr_id": pid, "event_type": "PROCESS_ATTEMPT", "description": desc,
                "performed_by": "RBR", "timestamp": r["started_at"],
            })
            # 3) Transicion de estado si el run OK concilia
            if r["result"] == "OK" and prev_state == "UNBALANCED" and p["balance_status"] == "BALANCED":
                logs.append({
                    "pnr_id": pid, "event_type": "STATE_CHANGE",
                    "description": "Transicion UNBALANCED -> BALANCED tras conciliacion del RBR.",
                    "performed_by": "RBR",
                    "timestamp": (r["finished_at"] or r["started_at"]),
                })
                prev_state = "BALANCED"

    # 4) Notas internas
    for n in notes:
        logs.append({
            "pnr_id": n["pnr_id"], "event_type": "NOTE",
            "description": n["note"], "performed_by": n["author"],
            "timestamp": n["created_at"],
        })

    logs.sort(key=lambda x: (x["pnr_id"], x["timestamp"]))
    return logs


def seed_scenario_config() -> list:
    """Config editable (no-code) para las 24 reglas + escenario 0."""
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for sid, info in SCENARIOS.items():
        rows.append({
            "scenario_id": sid, "code": info["code"], "family": info["family"],
            "enabled": 1,
            "amount_threshold": 0.0,
            "time_threshold_h": 24,
            "updated_at": now,
        })
    return rows


# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #
def _create_tables(conn: sqlite3.Connection) -> None:
    """Crea las 7 tablas con IF NOT EXISTS (no borra datos existentes)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pnrs (
            pnr_id TEXT PRIMARY KEY, passenger_name TEXT NOT NULL, flight_number TEXT NOT NULL,
            flight_date TEXT NOT NULL, route TEXT NOT NULL, total_fare REAL NOT NULL,
            total_paid REAL NOT NULL, balance_status TEXT NOT NULL, queue TEXT NOT NULL,
            scenario_id INTEGER NOT NULL, scenario_description TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS internal_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pnr_id TEXT NOT NULL, author TEXT NOT NULL,
            note TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS processing_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT, pnr_id TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, result TEXT NOT NULL, error_code TEXT, error_origin TEXT,
            retry_number INTEGER NOT NULL DEFAULT 0, scenario_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pnr_passengers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pnr_id TEXT NOT NULL,
            passenger_name TEXT NOT NULL, ssr_codes TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pnr_id TEXT NOT NULL, tc_code TEXT NOT NULL,
            amount REAL NOT NULL, debtor TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pnr_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pnr_id TEXT NOT NULL, event_type TEXT NOT NULL,
            description TEXT NOT NULL, performed_by TEXT NOT NULL, timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scenario_config (
            scenario_id INTEGER PRIMARY KEY, code TEXT NOT NULL, family TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, amount_threshold REAL NOT NULL DEFAULT 0,
            time_threshold_h INTEGER NOT NULL DEFAULT 24, updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def create_schema(conn: sqlite3.Connection) -> None:
    for t in ("pnrs", "internal_notes", "processing_runs", "pnr_passengers",
              "transactions", "pnr_audit_logs", "scenario_config"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")

    conn.execute(
        """
        CREATE TABLE pnrs (
            pnr_id               TEXT PRIMARY KEY,
            passenger_name       TEXT NOT NULL,
            flight_number        TEXT NOT NULL,
            flight_date          TEXT NOT NULL,
            route                TEXT NOT NULL,
            total_fare           REAL NOT NULL,
            total_paid           REAL NOT NULL,
            balance_status       TEXT NOT NULL,
            queue                TEXT NOT NULL,
            scenario_id          INTEGER NOT NULL,
            scenario_description TEXT NOT NULL,
            created_at           TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE internal_notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            pnr_id     TEXT NOT NULL,
            author     TEXT NOT NULL,
            note       TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE processing_runs (
            run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            pnr_id       TEXT NOT NULL,
            started_at   TEXT NOT NULL,
            finished_at  TEXT,
            result       TEXT NOT NULL,          -- OK | ERROR | UNPROCESSED
            error_code   TEXT,
            error_origin TEXT,                    -- DATA | RBR_INTERNAL | EXTERNAL
            retry_number INTEGER NOT NULL DEFAULT 0,
            scenario_id  INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE pnr_passengers (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            pnr_id         TEXT NOT NULL,
            passenger_name TEXT NOT NULL,
            ssr_codes      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE transactions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            pnr_id     TEXT NOT NULL,
            tc_code    TEXT NOT NULL,            -- TC | DD | AD | CC | CD | PC
            amount     REAL NOT NULL,
            debtor     TEXT NOT NULL,            -- CLIENT | AIRLINE
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE pnr_audit_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            pnr_id       TEXT NOT NULL,
            event_type   TEXT NOT NULL,          -- CREATED | PROCESS_ATTEMPT | STATE_CHANGE | NOTE | BALANCED
            description  TEXT NOT NULL,
            performed_by TEXT NOT NULL,          -- RBR | Finanzas | Soporte | Operaciones | SYSTEM
            timestamp    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE scenario_config (
            scenario_id   INTEGER PRIMARY KEY,   -- 0..24
            code          TEXT NOT NULL,
            family        TEXT NOT NULL,
            enabled       INTEGER NOT NULL DEFAULT 1,
            amount_threshold REAL NOT NULL DEFAULT 0,     -- umbral de monto para accionar
            time_threshold_h INTEGER NOT NULL DEFAULT 24, -- umbral de tiempo (horas) para priorizar
            updated_at    TEXT NOT NULL
        )
        """
    )
    conn.commit()


def insert_pnrs(conn, pnrs):
    conn.executemany(
        """
        INSERT INTO pnrs (
            pnr_id, passenger_name, flight_number, flight_date, route,
            total_fare, total_paid, balance_status, queue,
            scenario_id, scenario_description, created_at
        ) VALUES (
            :pnr_id, :passenger_name, :flight_number, :flight_date, :route,
            :total_fare, :total_paid, :balance_status, :queue,
            :scenario_id, :scenario_description, :created_at
        )
        """, pnrs,
    )
    conn.commit()


def insert_notes(conn, notes):
    conn.executemany(
        "INSERT INTO internal_notes (pnr_id, author, note, created_at) "
        "VALUES (:pnr_id, :author, :note, :created_at)", notes,
    )
    conn.commit()


def insert_runs(conn, runs):
    conn.executemany(
        """
        INSERT INTO processing_runs
            (pnr_id, started_at, finished_at, result, error_code, error_origin, retry_number, scenario_id)
        VALUES
            (:pnr_id, :started_at, :finished_at, :result, :error_code, :error_origin, :retry_number, :scenario_id)
        """, runs,
    )
    conn.commit()


def insert_passengers(conn, pax):
    conn.executemany(
        "INSERT INTO pnr_passengers (pnr_id, passenger_name, ssr_codes) "
        "VALUES (:pnr_id, :passenger_name, :ssr_codes)", pax,
    )
    conn.commit()


def insert_transactions(conn, txns):
    conn.executemany(
        "INSERT INTO transactions (pnr_id, tc_code, amount, debtor, created_at) "
        "VALUES (:pnr_id, :tc_code, :amount, :debtor, :created_at)", txns,
    )
    conn.commit()


def insert_audit_logs(conn, logs):
    conn.executemany(
        "INSERT INTO pnr_audit_logs (pnr_id, event_type, description, performed_by, timestamp) "
        "VALUES (:pnr_id, :event_type, :description, :performed_by, :timestamp)", logs,
    )
    conn.commit()


def insert_scenario_config(conn, rows):
    conn.executemany(
        """
        INSERT INTO scenario_config
            (scenario_id, code, family, enabled, amount_threshold, time_threshold_h, updated_at)
        VALUES
            (:scenario_id, :code, :family, :enabled, :amount_threshold, :time_threshold_h, :updated_at)
        """, rows,
    )
    conn.commit()


def export_json(pnrs):
    # Respaldo principal (250) y alias de compatibilidad.
    for path in (JSON_BACKUP_PATH, JSON_LEGACY_PATH):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pnrs, fh, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Modos de ejecucion
# --------------------------------------------------------------------------- #
def run_full() -> None:
    """Regenera la base desde cero (reproducible con seed fijo)."""
    random.seed(SEED)
    print("RBR Airline Insight Engine - Seed Generator v0.5.0-Lab (full)")
    print("-" * 62)

    pnrs = generate_pnrs()
    notes = seed_notes(pnrs)
    passengers, pax_count = seed_passengers(pnrs)
    runs = seed_runs(pnrs, pax_count)
    err_pnrs = {r["pnr_id"] for r in runs if r["result"] == "ERROR"}
    txns = seed_transactions(pnrs, err_pnrs)
    audit = seed_audit_logs(pnrs, runs, notes)
    cfg = seed_scenario_config()

    conn = sqlite3.connect(DB_PATH)
    try:
        create_schema(conn)
        insert_pnrs(conn, pnrs)
        insert_notes(conn, notes)
        insert_runs(conn, runs)
        insert_passengers(conn, passengers)
        insert_transactions(conn, txns)
        insert_audit_logs(conn, audit)
        insert_scenario_config(conn, cfg)
    finally:
        conn.close()

    export_json(pnrs)

    balanced = sum(1 for p in pnrs if p["balance_status"] == "BALANCED")
    unbalanced = len(pnrs) - balanced
    print(f"Base de datos:             {DB_PATH}")
    print(f"Respaldo JSON:             {JSON_BACKUP_PATH}")
    print(f"Semilla (reproducible):    random.seed({SEED})")
    print(f"Total PNRs:                {len(pnrs)}  (BALANCED {balanced} / UNBALANCED {unbalanced})")
    print(f"Notas internas:            {len(notes)}")
    print(f"Pasajeros (multipax):      {len(passengers)}")
    print(f"Processing runs:           {len(runs)}")
    print(f"Transacciones:             {len(txns)}")
    print(f"Audit logs (timeline):     {len(audit)}")
    print(f"Config de escenarios:      {len(cfg)} reglas editables")
    print("-" * 62)
    print("Listo. Ejecuta 'uvicorn main:app --reload' para iniciar el servidor.")


def run_append(n: int) -> None:
    """Agrega N PNRs nuevos SIN borrar los existentes (seed incremental)."""
    if not os.path.exists(DB_PATH):
        print(f"No existe {DB_PATH}. Ejecuta primero 'python seed_generator.py' (modo full).")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _create_tables(conn)  # garantiza esquema sin borrar
        existing = {r["pnr_id"] for r in conn.execute("SELECT pnr_id FROM pnrs").fetchall()}

        # Generar N PNRs con la misma proporcion 40/60, ids unicos globales
        n_bal = int(n * BALANCED_RATIO)
        new = [build_pnr(True) for _ in range(n_bal)] + [build_pnr(False) for _ in range(n - n_bal)]
        for p in new:
            while p["pnr_id"] in existing:
                p["pnr_id"] = gen_pnr_id()
            existing.add(p["pnr_id"])
        random.shuffle(new)

        # Derivados coherentes solo para los nuevos
        notes = seed_notes(new)
        passengers, pax_count = seed_passengers(new)
        runs = seed_runs(new, pax_count)
        err = {r["pnr_id"] for r in runs if r["result"] == "ERROR"}
        txns = seed_transactions(new, err)
        audit = seed_audit_logs(new, runs, notes)

        insert_pnrs(conn, new)
        insert_notes(conn, notes)
        insert_runs(conn, runs)
        insert_passengers(conn, passengers)
        insert_transactions(conn, txns)
        insert_audit_logs(conn, audit)
        # scenario_config NO se toca en append (ya existe)

        total = conn.execute("SELECT COUNT(*) c FROM pnrs").fetchone()["c"]
    finally:
        conn.close()

    print("RBR Airline Insight Engine - Seed Generator v0.5.0-Lab (append)")
    print("-" * 62)
    print(f"PNRs agregados:            {len(new)}")
    print(f"Total PNRs en la base:     {total}")
    print(f"Pasajeros agregados:       {len(passengers)}")
    print(f"Processing runs agregados: {len(runs)}")
    print(f"Audit logs agregados:      {len(audit)}")
    print("-" * 62)
    print("Append completado (datos existentes preservados).")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="RBR Seed Generator")
    parser.add_argument("--append", type=int, metavar="N",
                        help="Agrega N PNRs nuevos sin borrar la base existente")
    args = parser.parse_args()
    if args.append:
        random.seed()  # entropia del sistema para que los nuevos no colisionen
        run_append(args.append)
    else:
        run_full()


if __name__ == "__main__":
    main()
