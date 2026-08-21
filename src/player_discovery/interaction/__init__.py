"""Interaction — Gerenciamento de interações com o player em três níveis.

Exporta o InteractionManager e exceções relacionadas.
"""

from .manager import InteractionManager, InteractionRejectedError

__all__ = [
    "InteractionManager",
    "InteractionRejectedError",
]
