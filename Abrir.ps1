param([switch]$Components)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
Add-Type -AssemblyName System.Windows.Forms
try {
    $env:PYTHONUTF8='1'
    $env:PYTHONDONTWRITEBYTECODE='1'
    $venv=Join-Path $PSScriptRoot 'componentes/interface'
    $python=Join-Path $venv 'Scripts/pythonw.exe'
    $ready=Join-Path $venv '.interface-pronta'
    if(!(Test-Path -LiteralPath $ready) -or !(Test-Path -LiteralPath $python)){$python=$null}
    if(!$python){
        $reply=[Windows.Forms.MessageBox]::Show("Instalar o Python 3.12 e as bibliotecas da interface nesta pasta? Download estimado de 100 a 250 MB. Os modelos sao selecionados separadamente.","HydraTrainer",[Windows.Forms.MessageBoxButtons]::YesNo)
        if($reply -ne 'Yes'){exit 0}
        $cache=Join-Path $PSScriptRoot 'dados\downloads'
        $tools=Join-Path $PSScriptRoot 'componentes\uv'
        New-Item -ItemType Directory -Force -Path $cache,$tools | Out-Null
        $uv=(Get-Command uv.exe -ErrorAction SilentlyContinue).Source
        if(!$uv){
            $uv=Join-Path $tools 'uv.exe'
            if(!(Test-Path $uv)){
                $assets=Get-Content (Join-Path $PSScriptRoot 'app\arquivos.json') -Raw -Encoding utf8 | ConvertFrom-Json
                $asset=$assets | Where-Object name -eq 'uv-x86_64-pc-windows-msvc.zip'
                $archive=Join-Path $cache $asset.name
                & curl.exe -fLsS --retry 4 -o $archive $asset.url
                if($LASTEXITCODE -ne 0 -or (Get-FileHash $archive -Algorithm SHA256).Hash -ne $asset.sha){throw "Falha ao verificar uv."}
                Expand-Archive -LiteralPath $archive -DestinationPath $tools -Force
                $uv=(Get-ChildItem $tools -Recurse -Filter uv.exe -File | Select-Object -First 1).FullName
            }
        }
        $env:UV_CACHE_DIR=Join-Path $PSScriptRoot 'dados\cache\uv'
        $env:UV_PYTHON_INSTALL_DIR=Join-Path $PSScriptRoot 'componentes\python'
        $venv=Join-Path $PSScriptRoot 'componentes\interface'
        if(!(Test-Path (Join-Path $venv "Scripts/python.exe"))){& $uv venv $venv --python 3.12 --managed-python}
        if($LASTEXITCODE -ne 0){throw 'Falha ao preparar Python 3.12.'}
        $console=Join-Path $venv 'Scripts\python.exe'
        & $uv pip install --python $console 'av==17.1.0' 'numpy==2.5.4' 'pillow==13.0.0' 'requests==2.34.2' 'psutil>=7,<8' 'nvidia-ml-py==13.595.45' 'pyyaml>=6,<7'
        if($LASTEXITCODE -ne 0){throw 'Falha ao instalar as dependencias da interface.'}
        New-Item -ItemType File -Force $ready | Out-Null
        $python=Join-Path $venv 'Scripts\pythonw.exe'
    }
    $script=if($Components){'app\componentes.py'}else{'app\inicio.py'}
    $log=Join-Path $PSScriptRoot 'dados\logs\inicializacao.log'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
    Start-Process -FilePath $python -ArgumentList @('-X','utf8',('-'+'B'),('"'+(Join-Path $PSScriptRoot $script)+'"')) -WorkingDirectory $PSScriptRoot -WindowStyle Normal
} catch {
    [Windows.Forms.MessageBox]::Show($_.Exception.Message,'HydraTrainer')|Out-Null
    exit 1
}


