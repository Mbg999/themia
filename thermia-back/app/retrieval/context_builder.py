"""
Context builder — formats retrieved Document chunks into a prompt-ready string.

Format per chunk:
    [{law_id} | {law_title}]
    Rango: {legal_rank} · Estado: {status} · Art. {article} · {section}

    {content}

    ---
"""
from __future__ import annotations


def build_context(chunks: list) -> str:
    """Concatenate *chunks* into a structured context string for the LLM.

    Each chunk is formatted as::

        [{law_id} | {law_title}]
        Rango: {legal_rank} · Estado: {status} · Art. {article} · {section}

        {content}

        ---

    The metadata line is omitted when all fields are empty.  ``legal_rank``
    and ``status`` come from the dedicated ORM columns so the LLM can reason
    about normative hierarchy and validity without parsing free text.

    Parameters
    ----------
    chunks:
        List of Document ORM objects.  Each must have a ``metadata_`` dict
        with keys ``law_id``, ``law_title``, ``article``, ``section`` and
        dedicated columns ``legal_rank``, ``status``.

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
        law_title = meta.get("law_title", "")
        article = meta.get("article", "")
        section = meta.get("section", "")
        legal_rank = doc.legal_rank or ""
        status = doc.status or ""

        title_parts = [p for p in [law_id, law_title] if p]
        header = "[" + " | ".join(title_parts) + "]"

        meta_parts = []
        if legal_rank:
            meta_parts.append(f"Rango: {legal_rank}")
        if status:
            meta_parts.append(f"Estado: {status}")
        if article:
            meta_parts.append(f"Art. {article}")
        if section:
            meta_parts.append(section)

        block = header
        if meta_parts:
            block += "\n" + " · ".join(meta_parts)
        block += f"\n\n<doc>\n{doc.content}\n</doc>\n\n---"
        parts.append(block)

    return "\n\n".join(parts)
