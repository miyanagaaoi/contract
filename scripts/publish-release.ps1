<#
  V2.5.0 发行：推送代码/标签并把 docker 包作为 GitHub Release 资产上传。

  前置（二选一）：
    A) 安装 GitHub CLI 并登录：winget install GitHub.cli ; gh auth login
    B) 准备 Personal Access Token（scope: repo）放进环境变量 $env:GITHUB_TOKEN

  用法（在仓库根目录）：
    pwsh -File scripts/publish-release.ps1                 # 默认 v2.5.0 + ctms-image-2.5.0.tar
    pwsh -File scripts/publish-release.ps1 -SkipPush       # 只建 Release（代码已推过）
#>
param(
  [string]$Tag = 'v2.5.0',
  [string]$Asset = 'ctms-image-2.5.0.tar',
  [string]$NotesFile = 'docs/35-release-v2.5.0.md',
  [switch]$SkipPush
)
$ErrorActionPreference = 'Stop'
$repo = 'miyanagaaoi/contract'

if (-not $SkipPush) {
  Write-Host "[1/3] 推送 main 与标签 $Tag ..."
  git push origin main
  git push origin $Tag
} else { Write-Host "[1/3] 跳过推送" }

$noteExists = Test-Path $NotesFile
if (-not (Test-Path $Asset)) { throw "发行包不存在：$Asset（先执行 bash scripts/export-docker.sh 2.5.0）" }

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($gh) {
  Write-Host "[2/3] 用 gh 创建 Release 并上传资产（$([math]::Round((Get-Item $Asset).Length/1MB,1)) MB）..."
  $args = @('release', 'create', $Tag, $Asset, '--repo', $repo, '--title', "CTMS $Tag（财务模块）")
  if ($noteExists) { $args += @('--notes-file', $NotesFile) } else { $args += @('--generate-notes') }
  & gh @args
  Write-Host "[3/3] 完成：https://github.com/$repo/releases/tag/$Tag"
  exit 0
}

if (-not $env:GITHUB_TOKEN) {
  throw "未找到 gh，且未设置 `$env:GITHUB_TOKEN。请任选其一后重跑：winget install GitHub.cli && gh auth login，或 setx GITHUB_TOKEN <PAT>"
}
$h = @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = 'application/vnd.github+json';
        'X-GitHub-Api-Version' = '2022-11-28' }
$body = if ($noteExists) { Get-Content $NotesFile -Raw } else { "CTMS $Tag 发行版" }
Write-Host "[2/3] 用 REST API 创建 Release ..."
$rel = Invoke-RestMethod -Method Post -Headers $h -ContentType 'application/json' `
  -Uri "https://api.github.com/repos/$repo/releases" `
  -Body (@{ tag_name = $Tag; name = "CTMS $Tag（财务模块）"; body = $body; draft = $false } | ConvertTo-Json)
Write-Host "[3/3] 上传资产（$([math]::Round((Get-Item $Asset).Length/1MB,1)) MB，请耐心等待）..."
$upload = "https://uploads.github.com/repos/$repo/releases/$($rel.id)/assets?name=$Asset"
Invoke-RestMethod -Method Post -Headers $h -ContentType 'application/octet-stream' `
  -InFile $Asset -Uri $upload | Out-Null
Write-Host "完成：$($rel.html_url)"
