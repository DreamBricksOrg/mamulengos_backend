# Projeto Mamulengos (CAIXA Econômica Federal) - Backend

Escopo inicial conforme backlog:

- Uso de api para gerar imagens com Stable Diffusion
- FIFO para a Geração de imagens
- Health-check

## Como rodar
```bash
pip install -r requirements.txt
uvicorn main:app --app-dir src--host 0.0.0.0 --port 5000
```
