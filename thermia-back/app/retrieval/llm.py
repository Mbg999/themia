"""
LLM analysis helper — LangChain + Groq llama-3.1-8b-instant.

Returns a structured dict with keys:
    resumen                 : str
    implicaciones_legales   : list[str]
    fundamento_juridico     : list[str]
"""
from __future__ import annotations

import json
import os

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage


_SYSTEM_PROMPT = """Eres un asistente jurídico especializado en derecho español.
Analiza el contexto legal proporcionado y responde SOLO con un objeto JSON válido
con las siguientes claves (sin texto adicional):

{
  "resumen": "<resumen breve del contenido legal relevante>",
  "implicaciones_legales": ["<implicación 1>", "<implicación 2>", ...],
  "fundamento_juridico": ["<LEY X - Artículo Y: descripción>", ...]
}
"""


def analyze_with_llm(context: str, query: str) -> dict:
    """Call Groq LLM via LangChain and return parsed structured response.

    Parameters
    ----------
    context:
        Pre-formatted legal context string built by ``build_context``.
    query:
        The original user query / extracted PDF text snippet.

    Returns
    -------
    dict
        Keys: ``resumen`` (str), ``implicaciones_legales`` (list[str]),
        ``fundamento_juridico`` (list[str]).

    Raises
    ------
    ValueError
        If the LLM response cannot be parsed as valid JSON.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=api_key,
        temperature=0.0,
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Contexto legal:\n{context}\n\n"
                f"Consulta del usuario:\n{query}"
            )
        ),
    ]

    response = llm.invoke(messages)
    raw = response.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")].strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON response: {raw!r}") from exc

    return {
        "resumen": parsed.get("resumen", ""),
        "implicaciones_legales": parsed.get("implicaciones_legales", []),
        "fundamento_juridico": parsed.get("fundamento_juridico", []),
    }
