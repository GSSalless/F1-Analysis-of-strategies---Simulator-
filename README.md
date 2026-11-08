# Pit Wall · Central de Corrida de F1

Painel local para explorar o que aconteceu e comparar decisões de box após a corrida. O motor usa Python 3.9+ e a biblioteca padrão. A interface usa HTML, CSS, JavaScript e SVG.

## Rodar

Na raiz do repositório:

```sh
python3 -B ingest.py interlagos
python3 -B ingest.py mexico
python3 -B app.py
```

Abra <http://127.0.0.1:8765>. Na instalação do XAMPP, use a pasta `/Applications/XAMPP/xamppfiles/htdocs/F1 Interlagos 2026` e execute apenas o servidor se os caches já estiverem lá. O Apache não precisa estar em execução.

Escolha a corrida para ver classificação, ritmo e posições por volta, stints de todos os pilotos, paradas, clima e direção de prova. A aba Telemetria abre na volta mais rápida do piloto e permite consultar outras voltas observadas. O botão **Analisar estratégia do piloto** calcula as alternativas automaticamente.

O cache de corrida fica em `data/`. A telemetria carrega uma volta por vez pela OpenF1 e também fica em cache. Se o download de dados complementares falhar, `python3 -B ingest.py interlagos --extras` atualiza grid, trocas de posição e rádios sem baixar o restante. Para uma fonte alternativa do México, use `python3 -B ingest.py mexico --source jolpica`. Essa opção contém voltas, stints, boxes e classificação.

## Etapas e método

1. **Consolidar o que aconteceu.** A classificação, os tempos, os stints, as paradas, os intervalos e os avisos de pista usam a mesma linha do tempo. A chuva medida aparece separada da condição estimada. A estimativa combina precipitação, avisos de aderência e os compostos em uso. A fonte meteorológica não informa sol ou nebulosidade.
2. **Estimar ritmo e custo da troca.** A curva de desgaste usa a tendência mediana de voltas limpas dentro dos stints e incorpora uma correção aproximada de combustível. Para comparar compostos, o modelo procura voltas próximas com condição semelhante, temperatura e vento comparáveis. Prioriza até cinco pilotos à frente e cinco atrás e usa o restante do pelotão quando a amostra é pequena. O custo de parada vem das passagens pelo pit lane em condição de corrida semelhante. A estimativa de tráfego usa os intervalos disponíveis no ponto da decisão.
3. **Comparar alternativas.** Para cada parada registrada, o Python avalia até duas voltas antes e duas depois, com os compostos que tiveram evidência na janela e o que foi usado na parada real. A comparação encerra em até oito voltas após a parada, antes da próxima troca ou no fim da prova. Mostra ganho em segundos, retorno estimado à pista e possível posição de chegada mantendo os tempos observados dos outros pilotos. A projeção compara classificados com a mesma quantidade de voltas.
4. **Quantificar incerteza.** Com amostra suficiente, são gerados 500 sorteios reproduzíveis com a variação de ritmo, de box e uma margem para efeitos desconhecidos. A tabela mostra a faixa central de 80% e a proporção dos sorteios em que o piloto ganhou tempo ou posição. Essas proporções são condicionais ao modelo. A calibração exige testes fora da amostra em mais GPs e controle do que era conhecido na hora para futura análise ao vivo.

O modelo altera uma parada por vez. As condições usadas são as observadas depois da corrida e a reação dos rivais, o estoque real de pneus, danos e ordens de equipe ficam fora da projeção. Alguns cruzamentos de clima têm poucos pilotos em compostos diferentes ao mesmo tempo. O painel identifica essas amostras sem percentual.

Execute os testes com `python3 -B -m unittest -v`. Os testes com os dados reais rodam quando o cache da corrida está disponível.

Fontes: [OpenF1](https://openf1.org/docs/), [Jolpica F1](https://github.com/jolpica/jolpica-f1), [Pirelli](https://press.pirelli.com/the-champions-podium-verstappen-wins-in-mexico-as-kimi-secures-the-title/), [FIA](https://www.fia.com/events/fia-formula-one-world-championship/season-2026/mexico-city-grand-prix/event-timing).
