# SLO Demo: SLIs, SLOs e Error Budgets em Sistemas Distribuídos

Demonstração prática para o seminário de **Observabilidade em Sistemas Distribuídos** para a 23ª Semana Nacional de Ciência e Tecnologia (SNCT) do ano de 2026.
O objetivo dessa *demo* é mostra como uma equipe de SRE (Site Reliability Engineering ou Engenharia de Confiabilidade de Sites) para responder uma simples pergunta: *"o sistema está bom?"*, mas de uma maneira objetiva: definindo um **SLO** para medir o **consumo do error budget** via **burn rate** e, usando os dados (métricas -> traces -> logs) para **diagnosticar a causa** de uma degradação iminente, ou seja, que o serviço que está prestes a falhar, perder desempenho significativamente ou ficar indisponível.

> **Sobre a demo:** será um serviço `checkout` depende de um serviço `shipping`
> através de um proxy de caos. Em estado normal, o SLO de 99,5% de disponibilidade
> está dentro da meta. Ao injetar uma falha intermitente (30% de erro 503) no
> `shipping`, o **burn rate** dispara um alerta no Alertmanager **antes** de o
> SLO ser violado, e o diagnóstico conduzido pelos traces identifica o
> `shipping` como causa, mas não o `checkout`, que é o serviço medido.

## Sumário

- [Arquitetura](#arquitetura)
- [Pré-requisitos](#pré-requisitos)
- [Como rodar (comando único)](#como-rodar-comando-único)
- [Roteiro da demonstração](#roteiro-da-demonstração)
- [Onde ver cada sinal](#onde-ver-cada-sinal)
- [Como funciona por dentro](#como-funciona-por-dentro)
- [Troubleshooting](#troubleshooting)
- [Limitações e trade-offs](#limitações-e-trade-offs)
- [Referências](#referências)
- [Declaração de uso de IA generativa](#declaração-de-uso-de-ia-generativa)

---

## Arquitetura

```text
         tráfego de teste (curl loop)
                    │
                    ▼
          ┌───────────────────┐
          │   checkout :5000  │  ← serviço cujo SLI é medido
          └─────────┬─────────┘
                    │ HTTP
                    ▼
          ┌───────────────────┐
          │ chaos-proxy :8080 │  ← injeta X% de erro 503 quando ativado
          └─────────┬─────────┘
                    │ HTTP (quando não injeta caos)
                    ▼
          ┌───────────────────┐
          │   shipping :5001  │  ← dependência instável
          └───────────────────┘

  Telemetria (OTLP gRPC :4317)
     checkout ─────┐
                   ▼
        ┌─────────────────────────┐
        │   otel-collector :8889  │─── métricas ───┐
        └────────────┬────────────┘                │
                     │                             ▼
                     │ traces              ┌──────────────────┐
                     ▼                     │ prometheus :9090 │── alertas ──┐
              ┌───────────────┐            └──────────────────┘              │
              │ jaeger :16686 │                     ▲                        ▼
              └───────────────┘                     │ regras SLO    ┌──────────────────┐
                                                    │ (geradas      │ alertmanager     │
                                                    │  pelo Sloth)  │ :9093            │
                                                    │               └──────────────────┘
                                                    │
                                              ┌──────────────┐
                                              │ grafana :3000│
                                              └──────────────┘
```

**Serviços (mínimo exigido: 2 se comunicando pela rede):**

| Serviço          | Porta       | Papel |
|------------------|-------------|-------|
| `checkout`       | 5000        | Serviço medido pelo SLO; chama o `shipping` via proxy |
| `shipping`       | 5001        | Dependência do `checkout` |
| `chaos-proxy`    | 8080        | Injeção de falha controlada entre `checkout` e `shipping` |
| `otel-collector` | 4317, 8889  | Recebe OTLP e expõe métricas para o Prometheus; encaminha traces ao Jaeger |
| `prometheus`     | 9090        | Armazena métricas e avalia as regras de SLO |
| `alertmanager`   | 9093        | Recebe alertas de burn rate |
| `grafana`        | 3000        | Dashboard de error budget e burn rate |
| `jaeger`         | 16686       | UI de traces distribuídos |


## Pré-requisitos

- **Docker** ≥ 20.10
- **Docker Compose** ≥ 2.0 (plugin `docker compose`, não o antigo `docker-compose`)
- **make** (opcional, mas recomendado, mas há também um `demo.sh` equivalente)
- ~2 GB de RAM livres
- Portas livres: `3000, 4317, 4318, 5000, 5001, 8080, 8889, 9090, 9093, 16686`

Nenhuma conta em nuvem é necessária. Tudo roda localmente.


## Como rodar (comando único)

```bash
make demo
```

Esse comando:

1. Gera as regras de SLO do Prometheus a partir de `sloth/slo.yaml` usando a imagem oficial do Sloth.
2. Sobe todos os containers com `docker compose up --build`.

Alternativa sem `make`:

```bash
./demo.sh
```

Ou, manualmente:

```bash
mkdir -p prometheus/rules
docker run --rm \
  -v "$PWD/sloth/slo.yaml:/slo.yaml" \
  -v "$PWD/prometheus/rules:/output" \
  slok/sloth:latest \
  generate -i /slo.yaml -o /output/slo-rules.yaml

docker compose up --build
```

Para derrubar tudo:

```bash
make clean
```

> Aguarde ~30 segundos após o `up` para que o Prometheus avalie as regras e os
> primeiros pontos de burn rate apareçam no Grafana.


## Roteiro da demonstração

A demo segue o roteiro **estado normal → falha → detecção → diagnóstico → causa**.
Tem cerca de **8 minutos** quando cronometrada.

### 1. Gerar tráfego normal (baseline)

Em um terminal separado, gere tráfego contínuo para o `checkout`:

```bash
while true; do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/checkout
  sleep 0.5
done
```

Você deve ver uma sequência de `200`.

Abra o Grafana em http://localhost:3000 (login `admin`/`admin`, ou *skip* na primeira tela):

- Dashboard **"SLO - Checkout Availability"**.
- **Error Budget Remaining** próximo de 100%.
- **Burn Rate** próximo de `0` (nenhum erro).

### 2. Injetar a falha intermitente

Ative o caos no proxy:

```bash
curl "http://localhost:8080/chaos/on?rate=0.3"
```

> **Nota importante sobre a taxa:** o Sloth usa janelas longas (1h, 5m) para o
> alerta de *page*. Com 30% de erro, o alerta levaria ~30 min para disparar.
> Para a demo, usamos **100% de erro**, já com essa taxa, o alerta dispara em
> **~5 minutos**. Discutimos isso na seção [Limitações](#limitações-e-trade-offs).

### 3. Detecção via burn rate

Em 4–6 minutos, observe:

- **Grafana** → painel **Burn Rate (5m)** sobe de `0` para valores >100 (100% de erro / 0,5% de budget = 200).
- **Grafana** → painel **Burn Rate (1h)** também sobe, cruzando `14,4` (limiar de page).
- **Alertmanager** (http://localhost:9093) → alerta `CheckoutAvailabilityBurnRate`
  com `severity="critical"` no estado `firing`.

> O alerta **não** disparou porque "a taxa de erro passou de X%". Ele disparou
> porque a **velocidade de consumo do orçamento** é incompatível com a meta de
> 99,5% em 30 dias. A janela dupla (1h + 5m) existe para evitar alertas por
> oscilações momentâneas.

### 4. Diagnóstico conduzido pelos dados

Aqui está o ponto central da demo: **o diagnóstico vem dos dados, não de suposição**.

1. **Métrica de burn rate** → aponta para o serviço `checkout` (é ele que tem o
   SLI medido). Até aqui, tudo o que sabemos é *"o checkout está queimando
   orçamento"*.

2. **Trace (Jaeger, http://localhost:16686)**:
   - Selecione o serviço `checkout` no dropdown.
   - Clique em **Find Traces** e filtre por `error=true`.
   - Abra um trace com erro. O waterfall deve mostrar:
     - Span `checkout-handler` com o OK.
     - Span filho `GET http://chaos-proxy:8080/ship` que tem **status 503**.

   **Conclusão do trace:** o `checkout` está saudável; o que falha é a **chamada
   HTTP para o `shipping`** (via proxy).

3. **Logs do serviço** (confirmação): `docker compose logs checkout | tail`.

4. **Conclusão do diagnóstico:** *"O `checkout` está saudável. O que queima o
   error budget é a dependência `shipping`, que está falhando de forma
   intermitente. O burn rate é o sintoma; o trace é a evidência da causa."*

### 5. Causa e reversão

Reverta a falha:

```bash
curl "http://localhost:8080/chaos/off"
```

O burn rate volta a cair, **mas o orçamento já consumido permanece consumido**
até o fim da janela de 30 dias. Esse é o argumento para a decisão de SRE:
*"o time deve priorizar estabilidade em vez de novas features até o orçamento
se recuperar."*


## Onde ver cada sinal

| Sinal      | Ferramenta   | URL                          | Responde a pergunta... |
|------------|--------------|------------------------------|-------------------------|
| Métricas   | Prometheus   | http://localhost:9090        | *"Qual a taxa agregada? Estamos queimando orçamento?"* |
| Métricas   | Grafana      | http://localhost:3000        | *"Qual o burn rate e o error budget restante?"* |
| Métricas   | Alertmanager | http://localhost:9093        | *"Qual alerta de SLO disparou e com qual severidade?"* |
| Traces     | Jaeger       | http://localhost:16686       | *"Onde na cadeia de chamadas a requisição falha?"* |
| Logs       | `docker compose logs <svc>` | - | *"Qual a mensagem de erro exata e em qual instância?"* |
| Aplicação  | `checkout`   | http://localhost:5000/checkout | Endpoint gerador de tráfego |
| Caos       | `chaos-proxy`| http://localhost:8080/chaos/on?rate=1.0 | Ativa falha |


## Como funciona por dentro

### Sinais e instrumentação

- **Métricas:** o `checkout` é instrumentado com o SDK do OpenTelemetry para
  Python e expõe o contador `http_requests` (o exporter do Collector adiciona
  o sufixo `_total`, resultando em `http_requests_total` no Prometheus) com
  labels `service` e `status_code`.
- **Traces:** o `checkout` usa `FlaskInstrumentor` e `RequestsInstrumentor`
  para criar spans automáticos. O `otel-collector` encaminha os spans ao Jaeger
  via OTLP gRPC (`otlp/jaeger` exporter).
- **Logs:** disponíveis em `docker compose logs checkout`. A demo não depende
  de logs para o diagnóstico, com isso eles são o sinal *terciário*, usado para
  confirmar a mensagem exata.

### SLO e burn rate

- O arquivo `sloth/slo.yaml` declara o SLO de **99,5% de disponibilidade em 30
  dias** para o `checkout`.
- O SLI é calculado como **eventos de erro (5xx) / eventos totais**.
- O Sloth gera **recording rules** que produzem métricas genéricas
  (distinguidas por labels `sloth_id`, `sloth_service`, `sloth_slo`,
  `sloth_window`):
  - `slo:current_burn_rate:ratio` (burn rate na janela curta)
  - `slo:period_burn_rate:ratio` (burn rate no período do SLO)
  - `slo:period_error_budget_remaining:ratio` (orçamento restante)
  - `slo:sli_error:ratio_rate{5m,30m,1h,2h,6h,1d,3d}` (taxa de erro por janela)
- O Sloth também gera **alerting rules** `CheckoutAvailabilityBurnRate`
  (page + ticket) que o Alertmanager recebe.

> **Atenção:** o Sloth gera métricas com nomes **genéricos**, já os SLOs são
> distinguidos por labels, não pelo nome da métrica. Se você procurar por
> `slo:checkout_availability:burn_rate`, não vai encontrar. Use
> `slo:current_burn_rate:ratio{sloth_service="checkout"}`.

### Injeção de falha

- O `chaos-proxy` mantém estado em memória (`CHAOS_ENABLED`, `ERROR_RATE`).
- Quando ativado, decide por requisição se injeta `503` (com probabilidade
  `ERROR_RATE`) ou encaminha ao `shipping` real.
- Simula uma **dependência intermitentemente instável**, o tipo de falha mais
  difícil de detectar com alertas de limiar simples.


## Troubleshooting

### O Collector não sobe: `unknown type: "jaeger"` ou `references exporter "jaeger" which is not configured`

O exporter `jaeger` nativo foi **removido** do OpenTelemetry Collector a partir
da versão `v0.86.0`. Use o exporter `otlp/jaeger` e certifique-se de que o nome
no bloco `exporters:` é **idêntico** ao referenciado em
`service.pipelines.traces.exporters:`.

Configuração correta (`otel-collector/config.yaml`):

```yaml
exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      exporters: [otlp/jaeger]   # ← nome exato
```

### Métrica base ausente: `http_requests_total` retorna vazio no Prometheus

Duas causas possíveis:

1. **Sufixo `_total` duplicado.** Se o contador em Python se chama
   `http_requests_total` **e** o Collector adiciona `_total`, o Prometheus
   mostra `http_requests_total_total`. Renomeie o contador para `http_requests`.
2. **Intervalo de exportação de 60s.** O `PeriodicExportingMetricReader` do
   OpenTelemetry Python exporta a cada 60s. Aguarde **2 minutos** de tráfego
   contínuo antes de checar o Prometheus.

### Dashboard “No data” mas `slo:*` existe no Prometheus

O dashboard está consultando nomes de métricas que não existem. Confirme os
nomes reais com:

```promql
count({sloth_id!=""}) by (__name__)
```

Use esses nomes no `grafana/dashboards/slo-dashboard.json`.

### Alerta não dispara

O Sloth usa janelas longas (1h para page, 6h para ticket). Com 30% de erro, o
alerta de page leva ~30 min. Para a demo:

- Use `chaos/on?rate=1.0` (100% de erro) e aguarde ~5 min, ou
- Adicione uma regra de alerta de demonstração em
  `prometheus/rules/demo-fast.yaml`:

```yaml
groups:
  - name: demo-fast-burn-rate
    rules:
      - alert: DemoFastBurnRate
        expr: slo:current_burn_rate:ratio{sloth_window="5m", sloth_service="checkout"} > 14.4
        for: 1m
        labels:
          severity: critical
```

Recarregue o Prometheus (`docker compose restart prometheus`) e o alerta
dispara em ~1 min com o caos ativo.

### Validar o arquivo gerado pelo Sloth com promtool

```bash
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus/rules:/rules" \
  prom/prometheus:v2.50.1 \
  check rules /rules/slo-rules.yaml
```

O `--entrypoint promtool` é necessário porque a imagem `prom/prometheus` tem
entrypoint `prometheus` por padrão.

## Limitações e trade-offs

### Custos e overhead

- **Recording rules do Sloth** geram séries temporais extras no Prometheus
  (uma por janela e por SLO). Em produção, o custo cresce com o número de SLOs
  e de serviços.
- **Armazenamento de traces:** o Jaeger *all-in-one* guarda em memória; em
  produção, usa-se backend persistente (Cassandra, Elasticsearch, Tempo), com
  custo proporcional ao volume.
- **Overhead de instrumentação:** `RequestsInstrumentor` adiciona spans e
  headers W3C `traceparent` em todas as chamadas HTTP.

### Limitações da solução escolhida

- **Janela de 30 dias não é simulada em tempo real.** O *error budget remaining*
  parece estático em uma demo de minutos. O que muda visivelmente é o **burn
  rate**, que é uma taxa instantânea.
- **SLOs muito frouxos (<~94%) não disparam alerta** com os padrões do Sloth
  (burn rate de 14,4). A meta de 99,5% foi escolhida por isso.
- **Janelas longas atrasam a demo.** O alerta de page usa 1h/5m; com 30% de
  erro, leva ~30 min. Solução para a demo: 100% de erro + regra de atalho.
- **Pouco tráfego:** em serviços com poucas requisições por minuto, o padrão
  multi-window pode ter baixa precisão (SRE Workbook tem seção dedicada).

### Alternativas avaliadas

- **Alertas por limiar estático** ("erro > 1%"): simples, mas geram ruído ou
  demoram a detectar degradações lentas.
- **Pyrra (CNCF):** mais integrado ao Kubernetes (CRDs), calcula burn rate via
  subqueries. Para Docker Compose, o Sloth é mais direto.
- **Apenas traces sem SLO:** excelente para depuração, mas não responde
  *"estamos queimando o orçamento?"* de forma agregada.

## Referências

1. **Google SRE Workbook** : *Alerting on SLOs* (cap. 5).
   https://sre.google/workbook/alerting-on-slos/
2. **Sloth** : documentação oficial. https://sloth.dev/
3. **Kinto Technologies** : *Using Sloth to Monitor SLOs Easily*.
4. **Elastic Observability Labs** : *Your SLO is on fire*.
5. **Grafana Labs** : *How to implement multi-window, multi-burn-rate alerts*.
6. **OpenTelemetry Documentation** : https://opentelemetry.io/docs/
7. **Prometheus** : https://prometheus.io/docs/
8. **Pyrra (CNCF)** : https://github.com/pyrra-dev/pyrra
9. Majors, Fong-Jones e Miranda. *Observability Engineering*. O'Reilly, 2022.

