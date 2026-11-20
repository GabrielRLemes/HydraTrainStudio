# Run only on the disposable Windows release runner. The runner discards its disk after the job.
$ErrorActionPreference = 'Stop'
if ($env:RUNNER_ENVIRONMENT -ne 'github-hosted') { throw 'Requires a disposable GitHub-hosted runner.' }
$root = Join-Path $env:RUNNER_TEMP 'Hydra clean install'
$installer = (Resolve-Path 'dist/HydraTrainStudio-Windows.exe').Path
$assembly = [Reflection.Assembly]::LoadFrom($installer)
$setup = $assembly.GetType('Setup')
$install = $setup.GetMethod('Install',[Reflection.BindingFlags]'Static,NonPublic')
$choices = New-Object 'System.Collections.Generic.Dictionary[string,string]'
$choices['folder'] = $root
$choices['start'] = 'True'
$choices['desktop'] = 'True'
try {
    $arguments = [object[]]::new(2)
    $arguments[0] = $choices.psobject.BaseObject
    $arguments[1] = [Action[string]]{ param($line) Write-Host $line }
    $install.Invoke($null, $arguments)
    foreach ($where in 'Programs','DesktopDirectory') {
        $link = Join-Path ([Environment]::GetFolderPath($where)) 'HydraTrainStudio.lnk'
        $target = (New-Object -ComObject WScript.Shell).CreateShortcut($link).TargetPath
        if ($target -ne (Join-Path $root 'HydraTrainStudio.exe')) { throw "Incorrect shortcut: $link" }
        Start-Process -FilePath $link
        $studio = $null
        for ($i=0; $i -lt 60 -and !$studio; $i++) {
            Start-Sleep -Seconds 1
            $studio = Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'HydraTrainStudio' }
        }
        if (!$studio) { throw "Studio window did not open using $link" }
        [void]$studio.CloseMainWindow()
        if (!$studio.WaitForExit(15000)) {throw 'Studio did not exit normally'}
    }
} catch {
    Get-Content -LiteralPath (Join-Path $root 'dados/logs/setup.log') -Tail 45 -ErrorAction SilentlyContinue
    Get-Content -LiteralPath (Join-Path $root 'dados/logs/inicializacao.log') -Tail 20 -ErrorAction SilentlyContinue
    throw
}
