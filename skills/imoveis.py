import sqlite3
from typing import Optional


BANCO = "duque_imoveis.db"


def conectar():
    return sqlite3.connect(BANCO)


def inicializar():
    conexao = conectar()
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS imoveis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empreendimento TEXT NOT NULL,
            torre TEXT,
            unidade TEXT,
            andar TEXT,
            dormitorios INTEGER,
            valor REAL,
            entrada REAL,
            parcela_entrada REAL,
            financiamento REAL,
            parcela_pos_chaves REAL,
            renda_minima REAL,
            sol TEXT,
            observacoes TEXT
        )
    """)

    conexao.commit()
    conexao.close()


def adicionar_imovel(
    empreendimento: str,
    torre: str = "",
    unidade: str = "",
    andar: str = "",
    dormitorios: int = 2,
    valor: float = 0,
    entrada: float = 0,
    parcela_entrada: float = 0,
    financiamento: float = 0,
    parcela_pos_chaves: float = 0,
    renda_minima: float = 0,
    sol: str = "",
    observacoes: str = ""
) -> str:

    inicializar()

    conexao = conectar()
    cursor = conexao.cursor()

    cursor.execute("""
        INSERT INTO imoveis (
            empreendimento,
            torre,
            unidade,
            andar,
            dormitorios,
            valor,
            entrada,
            parcela_entrada,
            financiamento,
            parcela_pos_chaves,
            renda_minima,
            sol,
            observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        empreendimento,
        torre,
        unidade,
        andar,
        dormitorios,
        valor,
        entrada,
        parcela_entrada,
        financiamento,
        parcela_pos_chaves,
        renda_minima,
        sol,
        observacoes
    ))

    conexao.commit()
    conexao.close()

    return (
        f"Imóvel cadastrado com sucesso: "
        f"{empreendimento} - unidade {unidade}"
    )


def buscar_imoveis(
    empreendimento: str = "",
    valor_maximo: Optional[float] = None,
    entrada_maxima: Optional[float] = None,
    parcela_maxima: Optional[float] = None,
    sol: str = ""
) -> str:

    inicializar()

    conexao = conectar()
    cursor = conexao.cursor()

    consulta = """
        SELECT
            empreendimento,
            torre,
            unidade,
            andar,
            dormitorios,
            valor,
            entrada,
            parcela_entrada,
            financiamento,
            parcela_pos_chaves,
            renda_minima,
            sol,
            observacoes
        FROM imoveis
        WHERE 1=1
    """

    parametros = []

    if empreendimento:
        consulta += """
            AND empreendimento LIKE ?
        """
        parametros.append(f"%{empreendimento}%")

    if valor_maximo is not None:
        consulta += """
            AND valor <= ?
        """
        parametros.append(valor_maximo)

    if entrada_maxima is not None:
        consulta += """
            AND entrada <= ?
        """
        parametros.append(entrada_maxima)

    if parcela_maxima is not None:
        consulta += """
            AND parcela_entrada <= ?
        """
        parametros.append(parcela_maxima)

    if sol:
        consulta += """
            AND sol LIKE ?
        """
        parametros.append(f"%{sol}%")

    consulta += """
        ORDER BY valor ASC
        LIMIT 20
    """

    cursor.execute(consulta, parametros)

    resultados = cursor.fetchall()

    conexao.close()

    if not resultados:
        return "Nenhum imóvel encontrado com esses critérios."

    resposta = []

    for imovel in resultados:

        (
            empreendimento,
            torre,
            unidade,
            andar,
            dormitorios,
            valor,
            entrada,
            parcela_entrada,
            financiamento,
            parcela_pos_chaves,
            renda_minima,
            sol,
            observacoes
        ) = imovel

        resposta.append(
            f"""
Empreendimento: {empreendimento}
Torre: {torre}
Unidade: {unidade}
Andar: {andar}
Dormitórios: {dormitorios}
Valor: R$ {valor:,.2f}
Entrada: R$ {entrada:,.2f}
Parcela da entrada: R$ {parcela_entrada:,.2f}
Financiamento: R$ {financiamento:,.2f}
Parcela pós-chaves: R$ {parcela_pos_chaves:,.2f}
Renda mínima: R$ {renda_minima:,.2f}
Sol: {sol}
Observações: {observacoes}
""".strip()
        )

    return "\n\n" + "\n\n".join(resposta)


def listar_empreendimentos() -> str:

    inicializar()

    conexao = conectar()
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT DISTINCT empreendimento
        FROM imoveis
        ORDER BY empreendimento
    """)

    resultados = cursor.fetchall()

    conexao.close()

    if not resultados:
        return "Nenhum empreendimento cadastrado."

    return "\n".join(
        item[0] for item in resultados
    )


inicializar()