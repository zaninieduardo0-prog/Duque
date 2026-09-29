from __future__ import annotations

from brain.agent_loop import AgentLoop


def main() -> None:
    """Modo de teste textual do Duque, sem microfone ou wake word."""
    agent = AgentLoop()
    print("Duque modo texto. Digite uma solicitação ou 'sair'.")
    while True:
        try:
            text = input("Você > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.casefold() in {"sair", "exit", "quit"}:
            break
        result = agent.handle(text)
        print(f"Duque > {result.text}")
        if result.execution is not None:
            print(f"  execução: success={result.execution.success}")


if __name__ == "__main__":
    main()
