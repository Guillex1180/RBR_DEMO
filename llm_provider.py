"""
RBR Airline Insight Engine - Capa de proveedor LLM (llm_provider.py)

Abstrae la generacion de texto por un LLM real, con deteccion automatica del
proveedor a partir de variables de entorno (.env). Si no hay credenciales
configuradas, el metodo generate() devuelve None y el llamador debe usar su
logica local de reglas (fallback).

Proveedores soportados:
    - openai     (OPENAI_API_KEY)
    - anthropic  (ANTHROPIC_API_KEY)
    - bedrock    (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY, via boto3)

Variable de control:
    RBR_LLM_PROVIDER = rules | openai | anthropic | bedrock
      - 'rules' o vacio  -> fuerza fallback local (sin llamadas externas)
      - 'auto' (default) -> detecta el primer proveedor con credenciales

El diseno es tolerante a fallos: si la libreria del proveedor no esta instalada
o la llamada falla, generate() devuelve None y el sistema sigue operando con
reglas locales. Esto garantiza que la app corra 100% local sin configuracion.
"""

import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()  # carga .env si existe
except Exception:  # pragma: no cover - dotenv es opcional
    pass


class LLMProvider:
    """Selector y cliente de LLM con fallback seguro."""

    def __init__(self):
        self.control = (os.getenv("RBR_LLM_PROVIDER") or "auto").strip().lower()
        self.provider = self._detect_provider()

    # ------------------------------------------------------------------ #
    def _detect_provider(self) -> Optional[str]:
        if self.control == "rules":
            return None
        if self.control in ("openai", "anthropic", "bedrock"):
            return self.control if self._has_credentials(self.control) else None
        # auto: primer proveedor con credenciales
        for p in ("openai", "anthropic", "bedrock"):
            if self._has_credentials(p):
                return p
        return None

    def _has_credentials(self, provider: str) -> bool:
        if provider == "openai":
            return bool(os.getenv("OPENAI_API_KEY"))
        if provider == "anthropic":
            return bool(os.getenv("ANTHROPIC_API_KEY"))
        if provider == "bedrock":
            return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))
        return False

    @property
    def active(self) -> str:
        """Nombre del proveedor activo o 'rules' si es fallback local."""
        return self.provider or "rules"

    def is_live(self) -> bool:
        return self.provider is not None

    # ------------------------------------------------------------------ #
    def generate(self, system: str, prompt: str, max_tokens: int = 600) -> Optional[str]:
        """
        Genera texto con el proveedor activo. Devuelve None si no hay proveedor
        o si la llamada falla (el llamador hara fallback a reglas locales).
        """
        if not self.provider:
            return None
        try:
            if self.provider == "openai":
                return self._gen_openai(system, prompt, max_tokens)
            if self.provider == "anthropic":
                return self._gen_anthropic(system, prompt, max_tokens)
            if self.provider == "bedrock":
                return self._gen_bedrock(system, prompt, max_tokens)
        except Exception as exc:  # fallo de red/credenciales/libreria
            print(f"[LLMProvider] fallo con {self.provider}: {exc}. Usando fallback local.")
            return None
        return None

    # ---- Implementaciones por proveedor ---- #
    def _gen_openai(self, system: str, prompt: str, max_tokens: int) -> Optional[str]:
        from openai import OpenAI  # import diferido
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()

    def _gen_anthropic(self, system: str, prompt: str, max_tokens: int) -> Optional[str]:
        import anthropic  # import diferido
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text").strip()

    def _gen_bedrock(self, system: str, prompt: str, max_tokens: int) -> Optional[str]:
        import json
        import boto3  # import diferido
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")
        client = boto3.client("bedrock-runtime", region_name=region)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
        resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        parts = payload.get("content", [])
        return "".join(p.get("text", "") for p in parts).strip()
