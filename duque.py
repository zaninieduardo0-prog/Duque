from agents import Runner, SQLiteSession
from agent.duque import duque


session = SQLiteSession("duque_memoria")


while True:
    pergunta = input("\nDu: ")

    if pergunta.lower() in ["sair", "exit", "quit"]:
        print("Duque: Até mais, Du!")
        break

    resultado = Runner.run_sync(
        duque,
        pergunta,
        session=session,
    )

    print(f"\nDuque: {resultado.final_output}")