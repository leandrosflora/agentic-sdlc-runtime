# Agentic SDLC Runtime

Runtime compartilhado e funcional para os agentes da [Agentic SDLC Reference Architecture](https://github.com/leandrosflora/agentic-sdlc-reference-architecture).

Os papéis Product, Architecture, Developer, Test, Security, Reviewer, Release e Incident são definições declarativas executadas por este runtime. Eles não precisam operar como oito serviços persistentes.

## Capacidades implementadas

- registry de definições declarativas JSON;
- Context Builder com classificação, proveniência, redaction por escopo, limites e hashes;
- Fake Model Gateway determinístico;
- gateway HTTP real compatível com OpenAI, proxies corporativos e vLLM;
- MCP fake com grants por agente;
- runtime com tool loop limitado;
- eventos compatíveis com agent-event.schema.json;
- evidence bundles persistidos com SHA-256;
- checkpoints atômicos;
- retomada sem repetir chamada ao modelo;
- CLI e golden path;
- testes em Python 3.11 e 3.12.

## Arquitetura

~~~mermaid
flowchart LR
  D["Agent Definition"] --> R["Shared Runtime"]
  C["Context Builder"] --> R
  R --> M["Model Gateway"]
  R --> T["MCP Gateway"]
  R --> E["Events e Evidence"]
  R --> P["Checkpoint"]
  P -->|resume| R
~~~

## Instalação e demo

~~~bash
pip install -e ".[dev]"
pytest
python examples/run_demo.py
~~~

Ou use a CLI:

~~~bash
agentic-sdlc \
  --agent product \
  --project payments \
  --change CHG-1001 \
  --objective "Refine payment API requirement"
~~~

Por padrão a CLI usa o modelo fake. Para um endpoint OpenAI-compatible:

~~~bash
export MODEL_BASE_URL="https://api.openai.com/v1"
export MODEL_API_KEY="..."
export MODEL_NAME="..."
agentic-sdlc --real-model --agent product --project payments \
  --change CHG-1001 --objective "Refine requirement"
~~~

Credenciais são lidas do ambiente e nunca entram no contexto ou nas evidências.

## Definição de agente

~~~json
{
  "role": "product",
  "version": "1.0.0",
  "system_prompt": "Return a governed JSON response.",
  "allowed_tools": ["project.read", "requirements.write"],
  "limits": {
    "max_steps": 8,
    "max_input_chars": 32000,
    "max_output_chars": 8000
  }
}
~~~

## Estado durável

Cada execução persiste:

~~~text
.runtime/
├── checkpoints/<change_id>/<role>.json
├── evidence/<change_id>/<run_id>/*.json
└── events/<change_id>/*.json
~~~

Uma falha após a resposta do modelo preserva o checkpoint. A execução com --resume reutiliza a resposta persistida e continua no tool call, evitando custo e efeito duplicados.

## Limites desta versão

- o gateway MCP incluído é fake e voltado a testes;
- o gateway real de modelo usa o contrato chat completions OpenAI-compatible;
- persistência local demonstra os contratos; produção deve usar storage durável/WORM;
- policy OPA permanece no repositório de referência e será integrada como PDP remoto ou sidecar.
