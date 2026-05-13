# Agente Blue — Automação Windows

O **Agente Blue** é uma ferramenta standalone desenvolvida para automatizar a configuração técnica de estações de trabalho Windows, garantindo que as máquinas estejam prontas para uso em rede com os parâmetros corretos.

## 🚀 O que ele faz?

1.  **Configura a Rede:** Ativa a Descoberta de Rede e Compartilhamento de Arquivos em redes Privadas (e desativa em redes Públicas por segurança).
2.  **Ajusta o SMB:** Configura o cliente SMB para permitir conexões sem a necessidade de assinatura de segurança (ajuste de registro e PowerShell).
3.  **Instala Softwares:** Capaz de baixar e instalar softwares de forma silenciosa e automática.
4.  **Interface Moderna:** Possui uma interface gráfica simples para acompanhar o progresso e os logs em tempo real.

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
