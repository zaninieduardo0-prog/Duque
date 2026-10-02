Segurança e considerações

1) Permissões de edição automática
- O Duque pode sugerir e aplicar alterações no código. Isso representa risco se o agente for comprometido ou comandos malformados.
- Recomenda-se manter DUQUE_ALLOW_SELF_MODIFICATION=0 em ambientes de produção e habilitar apenas para desenvolvimento local com supervisão.

2) Acesso à rede
- Não exponha o servidor HTTP do Duque em rede pública sem autenticação.
- Considere usar firewall ou binding em localhost apenas (padrão: 127.0.0.1).

3) Modelos locais
- Modelos baixados podem conter código ou licenças que restringem uso.
- Modelos podem exigir recursos de hardware significativos.

4) Auditoria
- Utilize git para auditar mudanças automáticas. Crie branches para alterações automáticas e revise antes de mesclar.

5) Backups
- Faça backup do workspace antes de habilitar auto-modificação automática.
