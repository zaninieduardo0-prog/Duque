"""Inicialização de compatibilidade do Duque.

O Python carrega este módulo automaticamente quando a raiz do projeto está
no sys.path. Os patches aqui são pequenos e não alteram a lógica de execução;
eles apenas completam casos de linguagem natural e apresentação final.
"""

try:
    from brain.natural_language_patch import install as install_natural_language
    install_natural_language()
except Exception:
    # A inicialização do servidor não pode depender de compatibilidade opcional.
    pass

try:
    from brain.stability_patch import install as install_stability
    install_stability()
except Exception:
    pass
