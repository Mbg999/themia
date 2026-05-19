"""
Context builder — formats retrieved Document chunks into a prompt-ready string.

Format per chunk:
    [{law_id} | {article} | {section}]

    {content}

    ---
"""
from __future__ import annotations


def build_context(chunks: list) -> str:
    """Concatenate *chunks* into a structured context string for the LLM.

    Each chunk is formatted as::

        [{law_id} | {article} | {section}]

        {content}

        ---

    Parameters
    ----------
    chunks:
        List of Document ORM objects.  Each must have a ``metadata_`` dict
        with keys ``law_id``, ``article``, ``section`` and a ``content`` str.

    Returns
    -------
    str
        Concatenated context string, or ``""`` for an empty list.
    """
    if not chunks:
        return ""

    parts: list[str] = []
    for doc in chunks:
        meta = doc.metadata_ or {}
        law_id = meta.get("law_id", "")
        article = meta.get("article", "")
        section = meta.get("section", "")
        header = f"[{law_id} | {article} | {section}]"
        parts.append(f"{header}\n\n{doc.content}\n\n---")

    return "\n\n".join(parts)
