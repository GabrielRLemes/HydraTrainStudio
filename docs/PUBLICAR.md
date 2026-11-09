# Publicar uma versão

O workflow Release é executado ao enviar uma tag começando por v. A tag identifica a revisão exata usada por ambos os instaladores. Um runner Windows compila os launchers .NET, empacota o código comum e publica o ZIP, os dois instaladores e SHA256SUMS nos assets da release.

Para gerar os mesmos arquivos localmente em Windows x64, com Python 3.11+ e o compilador .NET Framework 4.x:

```powershell
$env:GITHUB_REPOSITORY='GabrielRLemes/HydraTrainStudio'
$env:GITHUB_REF_NAME='v0.1.0-preview.2'
python release/build.py
```

Os arquivos estão em `dist/`. Antes da publicação, coloque o ZIP ao lado do instalador para uma instalação local. Após publicar, basta o instalador da plataforma. Para instalar as ferramentas opcionais e os modelos é necessária conexão à internet.

As pastas de usuários, configurações locais, caches, modelos e treinos são excluídas do pacote pelo construtor. Para subir uma versão, faça o commit das alterações revisadas, envie o branch e a tag correspondente ao repositório. O workflow requer permissão de escrita em Contents para criar a release.
