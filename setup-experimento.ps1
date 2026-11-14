<#
    setup-experimento.ps1
    TCC - Autoscaling Preditivo para EWS

    Sobe o ambiente experimental COMPLETO, com versoes pinadas:
      ferramentas (kubectl, kind, helm) -> cluster Kind -> Online Boutique
      -> Prometheus (kube-prometheus-stack) -> KEDA -> ambiente conda.


    Ao final grava versoes-instaladas.txt (lockfile do experimento)

    Uso (PowerShell, NAO o cmd):
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned  # 1a vez
        .\setup-experimento.ps1 -BoutiquePath "C:\caminho\para\microservices-demo"
#>

param(
    # pasta onde a Online Boutique foi clonada
    [string]$BoutiquePath = "..\microservices-demo"
)

# ----------------------- VERSOES PINADAS -----------------------
# Binarios (conhecidos/estaveis; atualizar aqui se necessario)
$KubectlVersion = "v1.31.4"
$KindVersion    = "v0.25.0"
$HelmVersion    = "v3.16.2"
# KEDA 2.18 suporta Kubernetes v1.31-v1.33 (tabela oficial de compatibilidade);
# o cluster Kind (kind v0.25.0) roda v1.31.
$KedaChartVersion = "2.18.0"
$PythonVersion  = "3.10"
$CondaEnvName   = "tcc-ews"
$ClusterName    = "tcc-ews"
# ---------------------------------------------------------------

# "Continue" porque kind/helm/kubectl escrevem progresso no stderr; no Windows
# PowerShell 5.1 isso viraria erro fatal com "Stop".
$ErrorActionPreference = "Continue"

function Assert-Ok($etapa) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FALHOU: $etapa (codigo $LASTEXITCODE). Corrija e rode o script de novo, ele retoma de onde parou." -ForegroundColor Red
        exit 1
    }
}
$ToolsDir = "$env:LOCALAPPDATA\tcc-ews-tools"
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}
function Add-ToUserPath($dir) {
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($current -notlike "*$dir*") {
        [Environment]::SetEnvironmentVariable("Path", "$current;$dir", "User")
    }
    if ($env:Path -notlike "*$dir*") { $env:Path += ";$dir" }
}

# ========== 1. Docker ==========
Write-Host "`n== 1/8 Docker ==" -ForegroundColor Cyan
if (-not (Test-Command "docker")) {
    Write-Host "Docker nao encontrado. Instale: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
    exit 1
}
docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Docker instalado mas parado - abra o Docker Desktop e rode de novo." -ForegroundColor Yellow; exit 1 }
Write-Host "Docker ok." -ForegroundColor Green

# ========== 2. kubectl ==========
Write-Host "`n== 2/8 kubectl $KubectlVersion ==" -ForegroundColor Cyan
if (Test-Command "kubectl") {
    Write-Host "kubectl ja presente, mantendo o existente." -ForegroundColor Green
} else {
    Invoke-WebRequest -Uri "https://dl.k8s.io/release/$KubectlVersion/bin/windows/amd64/kubectl.exe" -OutFile "$ToolsDir\kubectl.exe"
    Write-Host "kubectl $KubectlVersion instalado." -ForegroundColor Green
}

# ========== 3. kind ==========
Write-Host "`n== 3/8 kind $KindVersion ==" -ForegroundColor Cyan
if (Test-Command "kind") {
    Write-Host "kind ja presente, mantendo o existente." -ForegroundColor Green
} else {
    Invoke-WebRequest -Uri "https://kind.sigs.k8s.io/dl/$KindVersion/kind-windows-amd64" -OutFile "$ToolsDir\kind.exe"
    Write-Host "kind $KindVersion instalado." -ForegroundColor Green
}

# ========== 4. helm ==========
Write-Host "`n== 4/8 helm $HelmVersion ==" -ForegroundColor Cyan
if (Test-Command "helm") {
    Write-Host "helm ja presente, mantendo o existente." -ForegroundColor Green
} else {
    $zip = "$ToolsDir\helm.zip"
    Invoke-WebRequest -Uri "https://get.helm.sh/helm-$HelmVersion-windows-amd64.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath "$ToolsDir\helm-extract" -Force
    Copy-Item "$ToolsDir\helm-extract\windows-amd64\helm.exe" "$ToolsDir\helm.exe" -Force
    Remove-Item $zip, "$ToolsDir\helm-extract" -Recurse -Force
    Write-Host "helm $HelmVersion instalado." -ForegroundColor Green
}
Add-ToUserPath $ToolsDir

# ========== 5. Cluster Kind ==========
Write-Host "`n== 5/8 Cluster Kind '$ClusterName' ==" -ForegroundColor Cyan
$clusters = @(kind get clusters 2>&1 | ForEach-Object { "$_".Trim() })
if ($clusters -contains $ClusterName) {
    Write-Host "Cluster '$ClusterName' ja existe, mantendo." -ForegroundColor Green
} else {
    kind create cluster --name $ClusterName
    Assert-Ok "criar cluster Kind"
}
kubectl cluster-info --context "kind-$ClusterName" 2>&1 | Out-Null
Assert-Ok "conectar ao cluster"
kubectl get nodes

# ========== 6. Online Boutique ==========
Write-Host "`n== 6/8 Online Boutique ==" -ForegroundColor Cyan
if (-not (Test-Path "$BoutiquePath\release\kubernetes-manifests.yaml")) {
    Write-Host "Nao achei '$BoutiquePath\release\kubernetes-manifests.yaml'." -ForegroundColor Yellow
    Write-Host "Passe o caminho certo: .\setup-experimento.ps1 -BoutiquePath 'C:\...\microservices-demo'"
    exit 1
}
kubectl apply -f "$BoutiquePath\release\kubernetes-manifests.yaml"
Assert-Ok "aplicar manifests da Online Boutique"
Write-Host "Manifests aplicados. Aguardando pods (pode levar varios minutos na 1a vez)..."
kubectl wait --for=condition=Ready pods --all --timeout=900s
Assert-Ok "aguardar pods da Online Boutique (rode de novo se foi so lentidao)"
# O loadgenerator nativo da Boutique gera trafego proprio e contaminaria os
# Perfis A/B do Locust - a carga do experimento deve vir SO do Locust.
kubectl scale deployment loadgenerator --replicas=0
Assert-Ok "desligar loadgenerator nativo"
# emailservice (Python) nao abre a porta a tempo das probes padrao da Boutique
# (delay=0s, timeout=1s) no Kind/Docker Desktop -> morto pela liveness (exit 137).
# O patch so atrasa/afrouxa as probes; nao altera requests/limits de CPU/memoria.
kubectl patch deployment emailservice --patch-file "$PSScriptRoot\k8s\patch-emailservice.json"
Assert-Ok "ajustar probes do emailservice"
kubectl rollout status deployment emailservice --timeout=300s
Assert-Ok "aguardar emailservice"
kubectl get pods

# ========== 7. Prometheus + KEDA (Helm) ==========
Write-Host "`n== 7/8 Prometheus e KEDA ==" -ForegroundColor Cyan
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>&1 | Out-Null
helm repo add kedacore https://kedacore.github.io/charts 2>&1 | Out-Null
helm repo update
Assert-Ok "atualizar repositorios Helm"

$installed = @(helm list -A --short 2>&1 | ForEach-Object { "$_".Trim() })
if ($installed -notcontains "monitoring") {
    helm install monitoring prometheus-community/kube-prometheus-stack --namespace monitoring --create-namespace --wait --timeout 15m
    Assert-Ok "instalar kube-prometheus-stack"
} else { Write-Host "kube-prometheus-stack ja instalado, mantendo." -ForegroundColor Green }

if ($installed -notcontains "keda") {
    helm install keda kedacore/keda --namespace keda --create-namespace --version $KedaChartVersion --wait --timeout 10m
    Assert-Ok "instalar KEDA"
} else { Write-Host "KEDA ja instalado, mantendo." -ForegroundColor Green }

# ========== 8. Ambiente conda ==========
Write-Host "`n== 8/8 Ambiente conda '$CondaEnvName' ==" -ForegroundColor Cyan
if (-not (Test-Command "conda")) {
    Write-Host "conda nao encontrado neste terminal - rode esta parte pelo 'Anaconda Prompt':" -ForegroundColor Yellow
    Write-Host "  conda create -n $CondaEnvName python=$PythonVersion -y"
    Write-Host "  conda activate $CondaEnvName"
    Write-Host "  pip install -r requirements.txt"
} else {
    $envExists = (conda env list 2>&1) | Select-String -Pattern "^\s*$CondaEnvName\s"
    if (-not $envExists) { conda create -n $CondaEnvName python=$PythonVersion -y }
    if (Test-Path ".\requirements.txt") {
        conda run -n $CondaEnvName pip install -r .\requirements.txt
    } else {
        Write-Host "requirements.txt nao esta nesta pasta - rode o pip install depois, de dentro do repo." -ForegroundColor Yellow
    }
}

# ========== Lockfile de versoes ==========
Write-Host "`n== Gravando versoes-instaladas.txt ==" -ForegroundColor Cyan
$lock = @()
$lock += "# Versoes efetivamente instaladas - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$lock += "# Commitar este arquivo no repo: e o registro de reprodutibilidade do experimento."
$lock += ""
$lock += "docker:  " + (docker --version)
$lock += "kubectl: " + (kubectl version --client --output=yaml | Select-String "gitVersion" | Select-Object -First 1).ToString().Trim()
$lock += "kind:    " + (kind version)
$lock += "helm:    " + (helm version --short)
$lock += ""
$lock += "## Charts Helm (nome, namespace, chart, app version):"
$lock += (helm list -A | Out-String)
$lock += "## Imagem de no do cluster Kind:"
$lock += (kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.kubeletVersion}')
$lock += ""
if (Test-Command "conda") {
    $lock += "## Python (pip freeze do ambiente ${CondaEnvName}):"
    $lock += (conda run -n $CondaEnvName pip freeze | Out-String)
}
$lock | Out-File -FilePath ".\versoes-instaladas.txt" -Encoding utf8
Write-Host "versoes-instaladas.txt gravado." -ForegroundColor Green

Write-Host "`n== PRONTO ==" -ForegroundColor Cyan
