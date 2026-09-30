import sqlite3
from datetime import datetime


BANCO = "duque_memoria.db"


def conectar():
    return sqlite3.connect(BANCO)


def inicializar():
    conexao = conectar()

    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assunto TEXT NOT NULL,
            conteudo TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )
    """)

    conexao.commit()
    conexao.close()


def salvar_memoria(assunto: str, conteudo: str) -> str:

    inicializar()

    conexao = conectar()

    cursor = conexao.cursor()

    cursor.execute(
        """
        INSERT INTO memorias
        (assunto, conteudo, criado_em)
        VALUES (?, ?, ?)
        """,
        (
            assunto,
            conteudo,
            datetime.now().isoformat()
        )
    )

    conexao.commit()
    conexao.close()

    return (
        f"Memória salva com sucesso: "
        f"{assunto}"
    )


def buscar_memorias(
    assunto: str
) -> str:

    inicializar()

    conexao = conectar()

    cursor = conexao.cursor()

    cursor.execute(
        """
        SELECT assunto, conteudo, criado_em
        FROM memorias
        WHERE assunto LIKE ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (f"%{assunto}%",)
    )

    resultados = cursor.fetchall()

    conexao.close()

    if not resultados:
        return "Nenhuma memória encontrada."

    resposta = []

    for item in resultados:

        resposta.append(
            f"Assunto: {item[0]}\n"
            f"Conteúdo: {item[1]}\n"
            f"Data: {item[2]}"
        )

    return "\n\n".join(resposta)


inicializar()