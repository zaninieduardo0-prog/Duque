"""Inicialização opcional do Duque.

O Python carrega este módulo automaticamente quando a raiz do projeto está
no sys.path. Ele instala pequenos patches de compatibilidade de linguagem
natural antes do servidor criar o AgentLoop.
"""

try:
    from brain.natural_language_patch import install
    install()
except Exception:
    # A inicialização do servidor não pode depender desse patch opcional.
    pass
