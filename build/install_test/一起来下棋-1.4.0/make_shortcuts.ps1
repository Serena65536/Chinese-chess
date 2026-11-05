param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$Name = "一起来下棋"
)

$Wsh = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$startMenu = Join-Path $programs $Name
$failed = @()

function New-Lnk {
    param([string]$Path, [string]$Exe, [string]$WorkDir, [string]$Desc, [string]$Label)
    try {
        $sc = $Wsh.CreateShortcut($Path)
        $sc.TargetPath = $Exe
        $sc.WorkingDirectory = $WorkDir
        $sc.Description = $Desc
        $sc.Save()
    } catch {
        $script:failed += $Label
    }
}

$clientExe = Join-Path $Target ("客户端\" + $Name + ".exe")
$serverExe = Join-Path $Target ("服务端\" + $Name + "-服务端.exe")
$clientDir = Join-Path $Target "客户端"
$serverDir = Join-Path $Target "服务端"

New-Lnk (Join-Path $desktop "$Name.lnk") $clientExe $clientDir "一起来下棋" "桌面-客户端"
New-Lnk (Join-Path $desktop "$Name-服务端.lnk") $serverExe $serverDir "联机服务端" "桌面-服务端"

try {
    New-Item -ItemType Directory -Force -Path $startMenu -ErrorAction Stop | Out-Null
    New-Lnk (Join-Path $startMenu "$Name.lnk") $clientExe $clientDir "一起来下棋" "开始菜单-客户端"
    New-Lnk (Join-Path $startMenu "$Name-服务端.lnk") $serverExe $serverDir "联机服务端" "开始菜单-服务端"
} catch {
    $failed += "开始菜单目录"
}

if ($failed.Count -gt 0) {
    Write-Host ("[提示] 这些快捷方式没能创建: " + ($failed -join "、"))
    Write-Host "       可以直接运行程序目录里的 exe。"
    exit 1
}
Write-Host "快捷方式已创建：桌面 + 开始菜单"
