from agents import Agent, Runner, function_tool


@function_tool
def dizer_oi() -> str:
    """Retorna uma mensagem simples."""
    return "Olá, Du! A ferramenta está funcionando."


teste = Agent(
    name="Teste",
    instructions="""
    Você é um agente de teste.

    Quando o usuário pedir para testar a ferramenta,
    use a ferramenta dizer_oi.
    """,
    tools=[dizer_oi],
)


resultado = Runner.run_sync(
    teste,
    "Teste a ferramenta.",
)

print(resultado.final_output)