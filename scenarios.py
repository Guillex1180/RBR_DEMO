"""
RBR - Catalogo de escenarios de balanceo (industria aerea)

Escenario 0 = PNR conciliado (BALANCED).
Escenarios 1..24 = casuisticas reales de desbalance en aviacion.

Cada escenario define:
    id            -> identificador numerico (0..24)
    code          -> codigo corto legible
    family        -> familia de negocio (SEAT_CHANGE, CREDIT_SHELL, VOUCHERS, NAME_CHANGE_FEE, OTHER)
    description    -> descripcion operativa
    sign          -> 'owed'   (el pasajero/empresa debe -> total_paid < total_fare)
                     'credit' (hay saldo a favor      -> total_paid > total_fare)
                     'none'   (balanceado)

------------------------------------------------------------------------------
DECISION DE NEGOCIO (ambiguedad "Escenario 7"):
La auditoria de negocio asume "Escenario 7 = Name Change Fee". En este catalogo
tecnico, el id #7 corresponde a SHELL_UNUSED (familia CREDIT_SHELL). Para NO
romper los datos ya sembrados (los scenario_id persisten en la base y en los
runs/transacciones), NO se renumera el catalogo.

Resolucion adoptada en el agente (ver agent_engine.scenario_audit):
  - Si el usuario pide un escenario POR NUMERO, se responde con el escenario real
    de ese id en este catalogo.
  - Si el usuario menciona explicitamente "Name Change Fee" (o la familia), el
    agente audita la FAMILIA NAME_CHANGE_FEE (ids 19..24) en lugar de un id suelto.
  - Ambos casos se explican en la respuesta para que la ambiguedad quede trazable.
La familia Name Change Fee abarca los escenarios 19..24.
------------------------------------------------------------------------------
"""

SCENARIOS = {
    0:  {"code": "RECONCILED",      "family": "NONE",            "sign": "none",   "description": "PNR conciliado - sin discrepancia"},

    # --- Seat Change (1-6) ---
    1:  {"code": "SEAT_UPGRADE",    "family": "SEAT_CHANGE",     "sign": "owed",   "description": "Seat Change - upgrade a cabina superior sin cobro"},
    2:  {"code": "SEAT_PREMIUM",    "family": "SEAT_CHANGE",     "sign": "owed",   "description": "Seat Change - asiento premium/preferente pendiente"},
    3:  {"code": "SEAT_EXITROW",    "family": "SEAT_CHANGE",     "sign": "owed",   "description": "Seat Change - fila de emergencia no cobrada"},
    4:  {"code": "SEAT_DOWNGRADE",  "family": "SEAT_CHANGE",     "sign": "credit", "description": "Seat Change - downgrade con reembolso parcial pendiente"},
    5:  {"code": "SEAT_INFANT",     "family": "SEAT_CHANGE",     "sign": "owed",   "description": "Seat Change - asiento para infante agregado"},
    6:  {"code": "SEAT_GROUP",      "family": "SEAT_CHANGE",     "sign": "owed",   "description": "Seat Change - reasignacion de grupo con diferencia tarifaria"},

    # --- Credit Shell (7-12) ---
    7:  {"code": "SHELL_UNUSED",    "family": "CREDIT_SHELL",    "sign": "credit", "description": "Credit Shell - saldo a favor no aplicado al PNR"},
    8:  {"code": "SHELL_PARTIAL",   "family": "CREDIT_SHELL",    "sign": "credit", "description": "Credit Shell - aplicacion parcial del credito"},
    9:  {"code": "SHELL_EXPIRED",   "family": "CREDIT_SHELL",    "sign": "credit", "description": "Credit Shell - credito vencido pendiente de ajuste"},
    10: {"code": "SHELL_MULTIPNR",  "family": "CREDIT_SHELL",    "sign": "credit", "description": "Credit Shell - credito compartido entre varios PNR"},
    11: {"code": "SHELL_CURRENCY",  "family": "CREDIT_SHELL",    "sign": "credit", "description": "Credit Shell - diferencia por conversion de moneda"},
    12: {"code": "SHELL_TAXONLY",   "family": "CREDIT_SHELL",    "sign": "credit", "description": "Credit Shell - credito solo de impuestos sin conciliar"},

    # --- Vouchers (13-18) ---
    13: {"code": "VCH_COMPENSATION","family": "VOUCHERS",        "sign": "credit", "description": "Voucher - compensacion por demora emitida sin conciliar"},
    14: {"code": "VCH_OVERBOOK",    "family": "VOUCHERS",        "sign": "credit", "description": "Voucher - denegacion de embarque (overbooking)"},
    15: {"code": "VCH_MEAL",        "family": "VOUCHERS",        "sign": "credit", "description": "Voucher - alimentos/hotel por interrupcion"},
    16: {"code": "VCH_GOODWILL",    "family": "VOUCHERS",        "sign": "credit", "description": "Voucher - cortesia comercial (goodwill)"},
    17: {"code": "VCH_DUPLICATE",   "family": "VOUCHERS",        "sign": "credit", "description": "Voucher - emision duplicada a conciliar"},
    18: {"code": "VCH_PARTIALUSE",  "family": "VOUCHERS",        "sign": "credit", "description": "Voucher - uso parcial con remanente"},

    # --- Name Change Fee (19-24) ---
    19: {"code": "NCF_SPELLING",    "family": "NAME_CHANGE_FEE", "sign": "owed",   "description": "Name Change Fee - correccion de ortografia pendiente"},
    20: {"code": "NCF_TRANSFER",    "family": "NAME_CHANGE_FEE", "sign": "owed",   "description": "Name Change Fee - transferencia de titular"},
    21: {"code": "NCF_CORPORATE",   "family": "NAME_CHANGE_FEE", "sign": "owed",   "description": "Name Change Fee - cambio en reserva corporativa"},
    22: {"code": "NCF_PENALTY",     "family": "NAME_CHANGE_FEE", "sign": "owed",   "description": "Name Change Fee - penalidad de cambio no cobrada"},
    23: {"code": "NCF_WAIVED",      "family": "NAME_CHANGE_FEE", "sign": "credit", "description": "Name Change Fee - exencion aplicada con reembolso pendiente"},
    24: {"code": "NCF_GROUPSPLIT",  "family": "NAME_CHANGE_FEE", "sign": "owed",   "description": "Name Change Fee - division de grupo con cargo pendiente"},
}

FAMILIES = ["SEAT_CHANGE", "CREDIT_SHELL", "VOUCHERS", "NAME_CHANGE_FEE"]

# Escenarios desbalanceados (todos menos el 0)
UNBALANCED_SCENARIO_IDS = [sid for sid in SCENARIOS if sid != 0]


def scenario(sid: int) -> dict:
    """Devuelve el escenario por id, con fallback seguro."""
    return SCENARIOS.get(int(sid), SCENARIOS[0])


def scenario_ids_for_family(family: str) -> list:
    """Ids de escenario que pertenecen a una familia (p.ej. NAME_CHANGE_FEE)."""
    fam = (family or "").upper()
    return [sid for sid, info in SCENARIOS.items() if info["family"] == fam]
