"""Entry point para execução da PoC via python -m src.poc_orchestrator.

Uso:
    python -m src

Carrega configuração de variáveis de ambiente e executa o
orquestrador principal da PoC.
"""
from __future__ import annotations

import asyncio
import sys

from src.config import PoCConfig
from src.poc_orchestrator import PoCOrchestrator


def main() -> None:
    """Entry point principal da PoC.

    Fluxo:
    1. Carrega configuração de variáveis de ambiente
    2. Valida configuração
    3. Executa orquestrador com asyncio.run()
    4. Imprime resumo no stdout
    5. Sai com código 0 (GO) ou 1 (NO_GO)
    """
    # Carregar configuração de variáveis de ambiente
    config = PoCConfig.from_env()

    # Validar configuração
    errors = config.validate()
    if errors:
        print("=" * 60)
        print("ERRO: Configuração inválida")
        print("=" * 60)
        for error in errors:
            print(f"  - {error}")
        print()
        print("Configure as variáveis de ambiente obrigatórias:")
        print("  POC_STORAGE_STATE_PATH: Caminho para storageState")
        print("  POC_CHANNEL_URL: URL do canal SKY+")
        print("=" * 60)
        sys.exit(2)

    # Executar orquestrador
    print("=" * 60)
    print("  Widevine PoC - Validação DRM com Playwright")
    print("=" * 60)
    print(f"  Canal: {config.channel_url}")
    print(f"  StorageState: {config.storage_state_path}")
    print(f"  Output: {config.output_dir}")
    print(f"  Log Level: {config.log_level}")
    print("=" * 60)
    print()

    orchestrator = PoCOrchestrator(config)
    report = asyncio.run(orchestrator.run())

    # Imprimir resumo
    print()
    print("=" * 60)
    print(f"  RESULTADO: {report.decision.value}")
    print("=" * 60)
    print()

    for validation in report.validations:
        status_icon = {
            "PASS": "✓",
            "FAIL": "✗",
            "SKIPPED": "⊘",
        }.get(validation.status.value, "?")
        print(
            f"  {status_icon} {validation.name:12s} "
            f"[{validation.status.value}] "
            f"({validation.duration_ms}ms)"
        )
        if validation.error_message:
            print(f"    └─ {validation.error_message}")
        if validation.skipped_reason:
            print(f"    └─ {validation.skipped_reason}")

    print()
    print(f"  Duração total: {report.total_duration_ms}ms")
    print(f"  Relatório: {report.log_file_path}")
    print("=" * 60)

    # Exit code baseado na decisão
    if report.decision.value == "GO":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
