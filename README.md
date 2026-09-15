# Resultado Operacional FT

Aplicação Streamlit para registrar e analisar o resultado operacional por data, modalidade, equipe e pelotão.

## Indicadores fixos

- Abordados
- Carros
- Motos
- BOPM
- Ocorrências
- Índice de produção

O índice de produção é calculado com pesos configuráveis na página **Indicadores**.

A configuração inicial (equivalente à fórmula histórica) é:

```text
abordados * 2 + carros * 1 + motos * 1 + ocorrencias * 5
```

Os demais indicadores começam com peso 0. Alterar um peso recalcula o índice de todo o período com a régua atual.

## Efetivo da equipe

No lançamento, o efetivo é um texto separado por `/`:

```text
CB PAULINO / SD RUSTIGUELLI / SD BATISTA / SD GARCIA
```

Não existe cadastro formal de policiais. O nome (incluindo graduação) é a identidade estatística. `CB MORETTO` e `SD MORETTO` são pessoas diferentes.

A produção individual futura representa **participação no resultado da equipe**, não pontuação exclusiva.

Registros antigos não têm efetivo extraído automaticamente da observação.

## Edição de resultados

Em **Registros**, selecione a linha e use **Editar resultado**. A atualização é transacional (resultado + efetivo + indicadores adicionais). `id` e `created_at` não mudam.

Se o resultado tiver ocorrências vinculadas, a exclusão exige confirmação explícita.

## Novos KPIs fixos

Campos permanentes em `resultados`:

- Pessoas presas
- Condenados capturados
- Veículos recuperados

Apoios continua sendo o indicador adicional **Apoios Operacionais** (não há coluna duplicada `apoios`).

## Ocorrências

A página **Ocorrências** registra o detalhamento analítico. O campo `Ocorrências` do resultado permanece o consolidado oficial e **não** é recalculado a partir dessa lista.

Cada ocorrência exige:

- um `result_id` (equipe do dia)
- um tipo do catálogo (`code` + nome)
- BOPM e BOPC como texto opcional

A data da ocorrência é a data do resultado vinculado.

### Tipos de ocorrência

O usuário cadastra os códigos reais da unidade. Não há tabela fictícia de códigos.

Categoria para KPI (opcional):

- Nenhuma
- Roubo
- Furto
- Roubo de veículo
- Furto de veículo

Os KPIs de roubo/furto vêm dessa categoria, não do campo `resultados.ocorrencias`.

## Apreensões

Uma ocorrência pode ter 0..N apreensões.

- DROGA: armazenada em **gramas** (kg é convertido). `SUM()` permanece consistente.
- OBJETO / ARMA / MUNIÇÃO: quantidade inteira em `un`
- DINHEIRO: `NUMERIC` em BRL

Objetos são consultáveis, mas não são KPI executivo.

## Indicadores adicionais

O sistema permite cadastrar métricas complementares sem alterar o banco a cada necessidade.

O indicador padrão criado automaticamente é:

```text
Apoios Operacionais
```

Na página **Indicadores** é possível:

- criar um novo indicador pelo nome (o slug é gerado automaticamente)
- ativar ou desativar
- excluir somente se o indicador nunca tiver sido usado

Indicadores inativos:

- não aparecem em novos lançamentos
- continuam no histórico, nos gráficos e na exportação CSV

No dashboard, o seletor de ranking/pelotão/modalidade inclui os indicadores adicionais. Os cards principais permanecem apenas com os indicadores fixos.

A exportação CSV transforma cada indicador adicional em coluna. A importação Excel continua baseada nas colunas fixas; se existir uma coluna com o **mesmo nome** de um indicador adicional (ex.: `APOIOS OPERACIONAIS`), o valor também é importado.

## Instalação local

Recomendado: Python 3.11, 3.12 ou 3.13.

```bash
python -m venv .venv
```

Windows (PowerShell):

```powershell
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

## Execução

```bash
streamlit run app.py
```

## Banco de dados

### SQLite local (desenvolvimento)

Se `DATABASE_URL` **não** estiver definida, o aplicativo cria e usa:

```text
data/resultado_operacional.db
```

Esse arquivo é adequado para uso local. No Streamlit Community Cloud ele **não** é persistência definitiva: sleep, redeploy ou recriação do container podem apagar o disco local.

### PostgreSQL (produção)

Para produção, configure:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
```

A aplicação escolhe o banco assim:

- com `DATABASE_URL` → PostgreSQL
- sem `DATABASE_URL` → SQLite local

Nunca coloque usuário, senha ou host no código. Nunca faça commit de `.env` ou `.streamlit/secrets.toml`.

Copie o exemplo:

```bash
copy .env.example .env
```

Preencha o `.env` localmente se for testar PostgreSQL. O Streamlit lê `DATABASE_URL` também pelos Secrets da nuvem.

## Streamlit Community Cloud

1. Faça o deploy do repositório.
2. Em **App settings → Secrets**, adicione:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
```

3. Use um PostgreSQL externo (recomendado: Neon).
4. Reinicie o aplicativo após salvar os secrets.

O arquivo local `.streamlit/secrets.toml` não deve ir para o GitHub. No Cloud, copie o conteúdo pelo painel **Edit Secrets**.

## Migração SQLite → PostgreSQL

O Streamlit **não** migra dados automaticamente na inicialização.

Depois de criar o banco PostgreSQL e configurar `DATABASE_URL`:

```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
python scripts/migrate_sqlite_to_postgres.py
```

O script:

1. lê `data/resultado_operacional.db`
2. cria a tabela no PostgreSQL se necessário
3. insere os registros
4. ignora IDs que já existam
5. informa quantos foram migrados

## Backup básico

- **SQLite:** copie `data/resultado_operacional.db` para um local seguro.
- **CSV:** use a tela **Exportar dados**.
- **PostgreSQL (Neon):** utilize o backup/restore do provedor e exporte CSV periodicamente.

## Importar Excel

Abra **Importar Excel**, selecione a planilha e clique em **Importar registros**.

O importador procura a linha com:

`DATA`, `MODALIDADE`, `EQUIPE`, `PELOTÃO`, `ABORDADOS`, `CARROS`, `MOTOS`, `OCORRENCIAS`

A coluna `BOPM` é importada quando existir; caso contrário, grava 0.

Colunas opcionais, se existirem:

`PESSOAS PRESAS`, `CONDENADOS CAPTURADOS`, `VEICULOS RECUPERADOS`, `EFETIVO`

A exportação CSV inclui efetivo (nomes separados por `/`) e os novos KPIs fixos. Ocorrências e apreensões não entram nesse CSV principal.

Observações completas são lidas em **Registros → Ver detalhes**. O dashboard mostra apenas 📝 quando o registro possui observação.

## Estrutura do projeto

```text
resultado-operacional/
├── app.py
├── charts/
│   └── dashboard.py
├── database/
│   ├── connection.py
│   └── repository.py
├── scripts/
│   └── migrate_sqlite_to_postgres.py
├── data/
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Segurança

- Não commitar `.env`
- Não commitar `.streamlit/secrets.toml`
- Não exibir senha no dashboard
- Não registrar `DATABASE_URL` completa nos logs
