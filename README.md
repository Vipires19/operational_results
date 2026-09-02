# Resultado Operacional — Streamlit

Aplicação para controle e análise do resultado operacional por:
- data
- modalidade
- equipe
- pelotão
- abordados
- carros
- motos
- BOPM
- ocorrências

## Rodar localmente

Recomendado: Python 3.11, 3.12 ou 3.13.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

O banco SQLite é criado automaticamente em `data/resultado_operacional.db`.

## Importar a planilha atual

Abra **📥 Importar Excel**, selecione a planilha `Resultado operacional - pelotões FT.xlsx` e clique em **Importar registros**.

O importador procura automaticamente a linha que contém:
`DATA`, `MODALIDADE`, `EQUIPE`, `PELOTÃO`, `ABORDADOS`, `CARROS`, `MOTOS`, `BOPM`, `OCORRENCIAS`.

## Observação sobre o índice de produção

O dashboard exibe também um índice simples para ordenar o ranking:

`abordados + carros + motos + (BOPM × 3) + (ocorrências × 5)`

Esse peso é apenas uma convenção inicial. A ideia é posteriormente definir com você uma metodologia operacional mais adequada, ou retirar o índice e trabalhar somente com rankings independentes por indicador.

## Próximos passos naturais

1. Cadastro fixo de equipes e pelotões.
2. Usuários/login e permissões.
3. Edição de registros.
4. Indicadores por serviço e médias.
5. Comparação entre pelotões.
6. Ranking mensal/anual.
7. Exportação para Excel/PDF.
8. PostgreSQL para uso multiusuário.
9. Camada de análise inteligente sobre o histórico.
