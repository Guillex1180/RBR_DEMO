"""
Tests de la capa LLM del RBR (ruta real simulada con mocks).

IMPORTANTE: estos tests NO llaman a ningun proveedor real (OpenAI/Anthropic/
Bedrock). Validan el *contrato* de integracion con un cliente simulado:
    - Si hay un LLM 'live', executive_summary usa el texto del LLM.
    - Si el LLM falla (devuelve None), cae al motor de reglas local (fallback).
    - Si no hay LLM, usa reglas.

La conexion con un proveedor real con credenciales NO se ha validado en este
entorno; esta suite cubre el camino de codigo, no la respuesta de un vendor.
"""

import os
import sqlite3
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import seed_generator  # noqa: E402
import agent_engine     # noqa: E402


class FakeLLMLive:
    """Simula un proveedor LLM disponible y funcional."""
    active = "mock-openai"
    def __init__(self, text="RESUMEN GENERADO POR LLM.\n\nParrafo 2.\n\nParrafo 3."):
        self._text = text
        self.calls = 0
    def is_live(self): return True
    def generate(self, system, prompt, max_tokens=600):
        self.calls += 1
        return self._text


class FakeLLMFailing:
    """Simula un proveedor presente pero cuya llamada falla (devuelve None)."""
    active = "mock-anthropic"
    def is_live(self): return True
    def generate(self, system, prompt, max_tokens=600):
        return None   # el proveedor fallo -> el agente debe hacer fallback


@pytest.fixture()
def conn(tmp_path):
    """Base temporal recien sembrada (seed 42)."""
    path = str(tmp_path / "t.db")
    import random
    random.seed(42)
    pnrs = seed_generator.generate_pnrs()
    notes = seed_generator.seed_notes(pnrs)
    passengers, pax = seed_generator.seed_passengers(pnrs)
    runs = seed_generator.seed_runs(pnrs, pax)
    err = {r["pnr_id"] for r in runs if r["result"] == "ERROR"}
    txns = seed_generator.seed_transactions(pnrs, err)
    audit = seed_generator.seed_audit_logs(pnrs, runs, notes)
    cfg = seed_generator.seed_scenario_config()
    c = sqlite3.connect(path); c.row_factory = sqlite3.Row
    seed_generator.create_schema(c)
    seed_generator.insert_pnrs(c, pnrs)
    seed_generator.insert_notes(c, notes)
    seed_generator.insert_runs(c, runs)
    seed_generator.insert_passengers(c, passengers)
    seed_generator.insert_transactions(c, txns)
    seed_generator.insert_audit_logs(c, audit)
    seed_generator.insert_scenario_config(c, cfg)
    yield c
    c.close()


def test_llm_live_used(conn):
    """Con un LLM live, el resumen usa el texto del LLM y marca el modo."""
    fake = FakeLLMLive()
    agent = agent_engine.RBRAirlineAgent(conn, llm=fake)
    assert agent.llm_mode == "live:mock-openai"
    res = agent.executive_summary("Finanzas")
    assert fake.calls == 1
    assert res["data"]["mode"] == "live:mock-openai"
    assert "RESUMEN GENERADO POR LLM" in res["answer"]


def test_llm_failure_falls_back(conn):
    """Si el LLM falla (None), el resumen cae a la plantilla local de reglas."""
    agent = agent_engine.RBRAirlineAgent(conn, llm=FakeLLMFailing())
    res = agent.executive_summary("Finanzas")
    assert res["data"]["mode"] == "rules"
    assert res["answer"].count("\n\n") + 1 == 3   # plantilla local = 3 parrafos


def test_no_llm_uses_rules(conn):
    """Sin LLM inyectado y sin credenciales, modo rules."""
    class NoLLM:
        active = "rules"
        def is_live(self): return False
        def generate(self, *a, **k): return None
    agent = agent_engine.RBRAirlineAgent(conn, llm=NoLLM())
    assert agent.llm_mode == "rules"
    res = agent.executive_summary("Operaciones")
    assert res["data"]["mode"] == "rules"
