"""Módulo __main__ para suportar execução via python -m.

Permite executar o Unified Channel Monitor como:
    python -m src.unified_channel_monitor
    python -m src.unified_channel_monitor --continuous

Requirements: 1.1
"""

import asyncio

from src.unified_channel_monitor.run import main

if __name__ == "__main__":
    asyncio.run(main())
