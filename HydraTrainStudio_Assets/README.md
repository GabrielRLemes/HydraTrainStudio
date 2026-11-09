# HydraTrainStudio — Pacote de Assets v1.0

Todos os elementos gráficos necessários para implementar uma interface minimalista em desktop, com PNGs prontos para importar.

## Estrutura
- `branding/`: símbolo da Hydra de **cinco cabeças** aprovado, versões quadradas, tipografia original, logo horizontal recortada e lockup compacto; PNG com canal alpha.
- `app_icon/`: PNG quadrado de 16 a 1024 px e `HydraTrainStudio.ico` com múltiplas resoluções para executável Windows.
- `icons/24/{light,purple,cyan}/`: ícones de navegação, botões e toolbar. Também disponíveis nas pastas `icons/32` e `icons/48`.
- `ui/`: placeholders visuais neutros para estados vazios e miniaturas ainda não carregadas.
- `assets_manifest.json`: catálogo completo com nomes, temas e tamanhos.

## Regras para implementação
1. Manter **o mesmo símbolo de cinco cabeças**, sem redesenhar o emblema.
2. No projeto, utilizar `Path(__file__).resolve().parent / 'assets'` ou equivalente para apontar aos arquivos; não usar caminhos absolutos.
3. Ícones regulares: PNG 24 px, `light`. Estados ativos: `purple`; ações secundárias: `cyan`. Ícones grandes: 32 ou 48 px.
4. Tratar os PNGs com alpha corretamente ao desenhar em fundos escuros. Evitar esticar fora da proporção original.
5. Implementar com componentes nativos todos os retângulos, painéis, bordas, botões, grids, formulários, barras, gráficos reais, imagens do dataset e caixas de seleção. **Não** usar imagens de mockup como fundo de interface.
6. Evitar carregar todos os PNGs na inicialização; carregar apenas os usados na tela, aplicar cache por caminho+tamanho.
7. Se usar Tkinter/CustomTkinter, conservar a referência à `PhotoImage` ou `CTkImage` durante a vida dos widgets.
8. Ícones de 16/24 px devem ser inspecionados em 100% de zoom; não aplicar filtros de brilho ou glow.

## Paleta sugerida
Background `#1B1E26` · Panel `#242834` · Purple `#8054D9` · Cyan `#22C9DC` · Text `#F0F1F5` · Border `#3A4050`.

## Nota de fidelidade
O emblema de cinco cabeças foi **recortado do logotipo aprovado nesta conversa**, não refeito por IA. A silhueta central e os gradientes são os originais, agora com área exterior transparente. O wordmark também foi extraído da marca horizontal anterior. Os ícones funcionais são desenhos geométricos de traço simples criados para este pacote.

### Limitação
Os PNGs são rasterizados. Para dimensionamento muito acima do fornecido, prefira `hydra_symbol_1024.png`. Não foram criados modelos, telas clicáveis ou componentes de interface; o pacote contém somente assets gráficos prontos para consumo pelo código.
