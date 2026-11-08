# Pit Wall · F1 Interlagos 2026

Replay pós-corrida e laboratório de estratégia de pneus. O motor, a importação e o servidor HTTP usam Python 3.9+ e a biblioteca padrão. O navegador usa HTML, CSS, JavaScript e SVG. O Apache do XAMPP não precisa estar em execução.

## Executar

Na raiz do repositório:

```sh
python3 -B ingest.py mexico --source jolpica
python3 -B app.py
```

Abra <http://127.0.0.1:8765>. Para mudar de porta, use `python3 -B app.py --port 8766`.

O primeiro comando importa o GP da Cidade do México (1/11/2026) da Jolpica com os stints da Pirelli e os estados de corrida da FIA. Para obter o conjunto OpenF1 do mesmo GP, use `python3 -B ingest.py mexico`. O cache gerado em `data/` é local.

Quando a janela gratuita da OpenF1 abrir, rode em outro Terminal:

```sh
python3 -B ingest.py interlagos
```

Clique em **Atualizar dados** e selecione o GP de São Paulo. A OpenF1 pode restringir consultas durante sessões ao vivo, inclusive de eventos antigos. A importação grava o cache somente após a coleta e validação. Ela exige classificação publicada e cobertura mínima de voltas, pilotos e stints. Um erro preserva o cache anterior.

## Testar com o México

1. Selecione Max Verstappen e avance até a V27. O painel mostra o set médio com 26 voltas e o que se conhecia no início da volta.
2. Em **Revisar parada real**, selecione a V27. Compare V26, V27 e V28 para o mesmo composto e com a mesma janela de avaliação. O pit real médio → macio está marcado na tabela.
3. Volte ao replay e mude para **Chuva aumenta** para ensaiar a sensibilidade à transição de pista. É uma hipótese aplicada ao México.
4. Na revisão, selecione a parada da V45. A interface distingue uma troca associada à bandeira vermelha de uma parada normal.

## Método

- O replay usa dados até o início da volta do piloto. Clima futuro é um cenário escolhido pelo usuário. Com safety car ou VSC, o desconto de parada vale na volta corrente e a projeção assume pista livre nas seguintes. A simulação avalia no máximo uma troca por cenário dentro de um horizonte configurável.
- A revisão de uma parada real congela a calibração no começo da volta anterior. Ela compara as alternativas sob o clima e o controle de corrida observados, até a suspensão ou o fim da janela. Uma troca sob bandeira vermelha exige um modelo à parte.
- A biblioteca de desgaste usa a mediana das inclinações dentro de cada stint, com correção fixa de combustível, exclusão de voltas de box/neutralizadas e regularização para uma premissa por composto e condição. O ritmo entre compostos é ajustado quando há voltas comparáveis do mesmo piloto. A tabela exibe quantas voltas e stints alimentaram o ajuste.
- A estimativa inclui perda de pit lane, aquecimento do jogo novo, intervalos e possível tráfego na volta de saída. Comparam-se segundos ganhos ou perdidos em relação a seguir sem parar na janela. A faixa varia o desgaste e a perda nos boxes. Ela não representa probabilidade estatística ou intervalo de confiança.
- A pista seca, úmida ou molhada é uma inferência a partir da chuva registrada. Sensores de chuva não medem aderência setor a setor. Rejoin e tráfego são projeções com base no pelotão no instante da decisão. O modelo não conhece os jogos disponíveis, danos, ordens de equipe ou reações futuras dos rivais.
- No cache alternativo do México, os intervalos são reconstruídos na última passagem em comum, os estados de pista da FIA têm resolução aproximada de minuto e pista seca é uma hipótese baseada no uso de slicks. A Pirelli identifica jogos usados sem publicar sua quilometragem inicial. Nesses casos, a idade mostrada é um mínimo desde o início do stint.
- O replay privilegia o cenário de volta a volta. Telemetria bruta e streaming ao vivo podem usar outro adaptador no futuro. Os arquivos locais e as rotas HTTP separam ingestão, estado e simulação.

Fontes: [OpenF1](https://openf1.org/docs/), [Jolpica F1](https://github.com/jolpica/jolpica-f1), [Pirelli](https://press.pirelli.com/the-champions-podium-verstappen-wins-in-mexico-as-kimi-secures-the-title/), [FIA](https://www.fia.com/events/fia-formula-one-world-championship/season-2026/mexico-city-grand-prix/event-timing).

Execute os testes com `python3 -B -m unittest -v`.
