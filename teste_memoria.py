from agents import Agent, Runner, SQLiteSession

teste = Agent(
    name="Teste",
    instructions="Responda sempre em português do Brasil."
)

session = SQLiteSession("teste_memoria")

resultado = Runner.run_sync(
    teste,
    "Meu nome é Du.",
    session=session,
)

print(resultado.final_output)

resultado = Runner.run_sync(
    teste,
    "Qual é o meu nome?",
    session=session,
)

print(resultado.final_output)