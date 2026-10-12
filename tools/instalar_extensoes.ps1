# Instala as extensoes Silhouette deste repositorio no Inkscape e repoe as predefinicoes.
# Usar: fechar o Inkscape, abrir o PowerShell como administrador e correr
#   powershell -ExecutionPolicy Bypass -File "C:\Users\jasce\Documents\GitHub\inkscape-silhouette\tools\instalar_extensoes.ps1"
# Opcao -SemReset para copiar os ficheiros sem apagar os valores guardados.
param([switch]$SemReset)

$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $PSScriptRoot
$dst = "C:\Program Files\Inkscape\share\inkscape\extensions"
$prefs = Join-Path $env:APPDATA "inkscape\preferences.xml"
$prefix = "com.github.fablabnbg.inkscape-silhouette."

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Este script tem de correr como administrador (copia para Program Files)." -ForegroundColor Red
    Write-Host "Clica com o botao direito no PowerShell > 'Executar como administrador' e corre de novo." -ForegroundColor Red
    exit 1
}

if (Get-Process -Name inkscape -ErrorAction SilentlyContinue) {
    Write-Host "Fecha o Inkscape primeiro (ele grava as preferencias ao sair)." -ForegroundColor Red
    exit 1
}

# 1. Copiar as extensoes
$inx = Get-ChildItem $src -Filter *.inx
foreach ($f in $inx) {
    Copy-Item $f.FullName $dst -Force
    $py = Join-Path $src ($f.BaseName + ".py")
    if (Test-Path $py) { Copy-Item $py $dst -Force }
}
New-Item -ItemType Directory -Force (Join-Path $dst "silhouette") | Out-Null
Copy-Item (Join-Path $src "silhouette\*.py") (Join-Path $dst "silhouette") -Force
Write-Host ("Copiadas {0} extensoes e a pasta silhouette para {1}" -f $inx.Count, $dst)

# 2. Apagar os valores guardados destas extensoes (o Inkscape volta a usar as predefinicoes)
if (-not $SemReset) {
    if (Test-Path $prefs) {
        $backup = "$prefs.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        Copy-Item $prefs $backup
        [xml]$xml = Get-Content -Raw -Encoding UTF8 $prefs
        $removed = 0
        foreach ($node in $xml.SelectNodes("//*[@*]")) {
            $names = @($node.Attributes | Where-Object { $_.Name.StartsWith($prefix) } | ForEach-Object { $_.Name })
            foreach ($n in $names) { $node.RemoveAttribute($n); $removed++ }
        }
        $xml.Save($prefs)
        Write-Host ("Apagados {0} valores guardados (copia de seguranca: {1})" -f $removed, $backup)
    } else {
        Write-Host "Nao encontrei $prefs - nada para repor."
    }
}
Write-Host "Feito. Abre o Inkscape." -ForegroundColor Green
