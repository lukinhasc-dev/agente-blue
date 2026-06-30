# Agente Blue — Automação Windows

O **Agente Blue** é uma ferramenta standalone desenvolvida para automatizar a configuração técnica de estações de trabalho Windows, garantindo que as máquinas estejam prontas para uso em rede com os parâmetros corretos.

## 🚀 O que ele faz?

1.  **Configura a Rede:** Ativa a Descoberta de Rede e Compartilhamento de Arquivos em redes Privadas (e desativa em redes Públicas por segurança).
2.  **Ajusta o SMB:** Configura o cliente SMB para permitir conexões sem a necessidade de assinatura de segurança (ajuste de registro e PowerShell).
3.  **Instala Softwares:** Capaz de baixar e instalar softwares de forma silenciosa e automática.
4.  **Cria Usuários:** Cria/atualiza os usuários locais (Suporte e Administrador) com as senhas definidas na configuração.
5.  **Instala Impressora de Rede:** Adiciona a impressora por IP direto (porta TCP/IP) com driver via Windows Update. *(novo na v2.0)*
6.  **Otimiza o Windows:** Plano de energia, modo escuro, limpeza de disco/caches e ajustes de barra de tarefas.
7.  **Verifica a Integridade:** Ao final, roda `DISM /RestoreHealth` + `sfc /scannow` para reparar a imagem e os arquivos do sistema. *(novo na v2.0)*
8.  **Interface Moderna:** Possui uma interface gráfica simples para acompanhar o progresso e os logs em tempo real.

## ⚙️ Configuração (`config.json`)

A partir da v2.0, credenciais, usuários, softwares e dados da impressora ficam num arquivo **`config.json`** ao lado do executável — fora do código-fonte e fora do Git.

1.  Copie **`config.example.json`** para **`config.json`** (na mesma pasta do `agente.py` / `AgenteBlue.exe`).
2.  Preencha as senhas do administrador e dos usuários, e o IP da impressora.
3.  O `config.json` real **não é versionado** (está no `.gitignore`); apenas o modelo `config.example.json` fica no repositório.

## 📥 Como baixar e usar

1.  Acesse a pasta `dist` deste repositório.
2.  Baixe o arquivo **`AgenteBlue.exe`**.
3.  Clique com o botão direito no arquivo e escolha **"Executar como Administrador"**.
    *   *Nota: Se o Windows exibir um alerta de "Fornecedor Desconhecido", clique em "Mais Informações" e depois em "Executar assim mesmo".*

## 🛠️ Para Desenvolvedores

Se você alterou o código e deseja gerar um novo executável:
- Execute o arquivo `compilar.bat` como Administrador.
- O novo executável será gerado automaticamente na pasta `dist`.

---
*Desenvolvido por BlueControl IT*
