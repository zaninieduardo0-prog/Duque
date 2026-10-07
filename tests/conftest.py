"""Os testes antigos do servidor conferem o núcleo anterior (sem IA de verdade).

O núcleo novo (telex/) tem testes próprios em test_telex_nucleo.py, inclusive
um que liga o servidor a ele com uma IA simulada.
"""

import os

os.environ.setdefault("DUQUE_NUCLEO", "antigo")
