from flask import Flask, jsonify, request, Response
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

estado_duque = {
    "estado": "standby",
    "tarefa": "",
    "atividade": "Sistema online",
    "coerencia": 100,
    "ultima_atualizacao": None,
}

ESTADOS_PERMITIDOS = [
    "standby",
    "ouvindo",
    "processando",
    "executando",
    "falando",
]


def atualizar_estado(
    estado,
    tarefa=None,
    atividade=None,
    coerencia=None
):
    if estado not in ESTADOS_PERMITIDOS:
        return False

    estado_duque["estado"] = estado

    if tarefa is not None:
        estado_duque["tarefa"] = tarefa

    if atividade is not None:
        estado_duque["atividade"] = atividade

    if coerencia is not None:
        try:
            estado_duque["coerencia"] = max(
                0,
                min(100, int(coerencia))
            )
        except (TypeError, ValueError):
            pass

    estado_duque["ultima_atualizacao"] = (
        datetime.now().isoformat(
            timespec="milliseconds"
        )
    )

    print(
        "[DUQUE] "
        f"{estado.upper()} | "
        f"{estado_duque['atividade']} | "
        f"{estado_duque['tarefa']}"
    )

    return True


@app.route("/")
def inicio():
    caminho = Path("interface/index.html")

    if not caminho.exists():
        return (
            "Erro: interface/index.html não encontrado.",
            500
        )

    html = caminho.read_text(
        encoding="utf-8"
    )

    ponte = """
<script>
(function(){

    const URL_ESTADO = "/api/estado";

    let ultimoEstado = null;
    let ultimaAtividade = null;

    function sincronizarEstado(dados){

        if(!dados) return;

        if(typeof window.DUQUE === "undefined"){
            return;
        }

        const estado = dados.estado || "standby";
        const tarefa = dados.tarefa || "";
        const atividade = dados.atividade || "";

        /*
         * O servidor usa nomes em português.
         * A HUD usa nomes em inglês.
         */
        const mapaEstados = {
            standby: "standby",
            ouvindo: "listening",
            processando: "processing",
            executando: "executing",
            falando: "speaking"
        };

        const estadoVisual =
            mapaEstados[estado] || "standby";

        window.DUQUE.setState({
            state: estadoVisual,
            currentTask: tarefa
        });

        if(
            atividade &&
            atividade !== ultimaAtividade
        ){

            ultimaAtividade = atividade;

            if(
                typeof window.DUQUE.activity ===
                "function"
            ){
                window.DUQUE.activity(
                    atividade
                );
            }
        }

        if(
            typeof dados.coerencia === "number"
        ){

            const elemento =
                document.getElementById(
                    "coherence"
                );

            if(elemento){

                elemento.dataset.serverCoherence =
                    dados.coerencia.toFixed(3);

            }
        }

        if(
            ultimoEstado !== null &&
            ultimoEstado !== estado
        ){

            if(
                typeof window.DUQUE.telemetry ===
                "function"
            ){

                const nomes = {

                    standby:
                        "Standby",

                    ouvindo:
                        "Canal de voz",

                    processando:
                        "Processamento",

                    executando:
                        "Computer Use",

                    falando:
                        "Síntese de voz"
                };

                window.DUQUE.telemetry(
                    [
                        {
                            k: "Estado",
                            v:
                                nomes[estado] ||
                                estado
                        }
                    ],
                    2200
                );
            }
        }

        ultimoEstado = estado;
    }


    async function atualizar(){

        try{

            const resposta =
                await fetch(
                    URL_ESTADO,
                    {
                        method: "GET",
                        cache: "no-store"
                    }
                );

            if(!resposta.ok){
                return;
            }

            const dados =
                await resposta.json();

            sincronizarEstado(dados);

        }catch(erro){

            /*
             * O servidor pode estar
             * temporariamente indisponível.
             * Não interromper a HUD.
             */

        }
    }


    atualizar();

    setInterval(
        atualizar,
        300
    );


    console.log(
        "[DUQUE] HUD conectada ao servidor."
    );

})();
</script>
"""

    marcador = "</body>"

    if marcador in html:

        html = html.replace(
            marcador,
            ponte + "\n" + marcador,
            1
        )

    else:

        html += ponte

    return Response(
        html,
        mimetype="text/html"
    )


@app.route(
    "/api/estado",
    methods=["GET"]
)
def obter_estado():

    return jsonify(
        estado_duque
    )


@app.route(
    "/api/estado",
    methods=["POST"]
)
def alterar_estado():

    dados = request.get_json(
        silent=True
    )

    if not dados:

        return jsonify({
            "erro":
                "JSON não informado."
        }), 400

    novo_estado = dados.get(
        "estado"
    )

    if novo_estado not in ESTADOS_PERMITIDOS:

        return jsonify({

            "erro":
                f"Estado inválido: {novo_estado}",

            "estados_permitidos":
                ESTADOS_PERMITIDOS

        }), 400

    atualizar_estado(

        novo_estado,

        tarefa=dados.get(
            "tarefa"
        ),

        atividade=dados.get(
            "atividade"
        ),

        coerencia=dados.get(
            "coerencia"
        )
    )

    return jsonify(
        estado_duque
    )


@app.route(
    "/estado/<novo_estado>",
    methods=["GET"]
)
def estado_compatibilidade(
    novo_estado
):

    if novo_estado not in ESTADOS_PERMITIDOS:

        return jsonify({
            "erro":
                "Estado inválido."
        }), 400

    atualizar_estado(
        novo_estado
    )

    return jsonify(
        estado_duque
    )


@app.route(
    "/status",
    methods=["GET"]
)
def status():

    return jsonify({

        "estado":
            estado_duque["estado"],

        "atividade":
            estado_duque["atividade"],

        "tarefa":
            estado_duque["tarefa"]

    })


if __name__ == "__main__":

    print()

    print("=" * 60)
    print("DUQUE - SERVIDOR CENTRAL")
    print("=" * 60)

    print()

    print("Interface:")
    print(
        "http://127.0.0.1:5000"
    )

    print()

    print("API:")
    print(
        "http://127.0.0.1:5000/api/estado"
    )

    print()

    print("HUD:")
    print(
        "Sincronização automática: ATIVA"
    )
    print(
        "Intervalo: 300 ms"
    )

    print()

    print("=" * 60)
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )