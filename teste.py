from agents import Agent, Runner

teste = Agent(
    name="Teste",
    instructions="Responda sempre em português do Brasil."
)

resultado = Runner.run_sync(
    teste,
    "Diga apenas: funcionando"
)

print(resultado.final_output)