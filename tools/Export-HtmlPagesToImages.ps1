[CmdletBinding(DefaultParameterSetName = "Glob")]
param(
    [Parameter(Mandatory = $true, Position = 0, ParameterSetName = "Glob")]
    [string]$HtmlGlob,

    [Parameter(Mandatory = $true, ParameterSetName = "Directory")]
    [Alias("Dir", "RootDir")]
    [string]$InputDir,

    [Parameter(ParameterSetName = "Directory")]
    [string]$HtmlPattern = "*.html",

    [string]$OutputDir = "",
    [string]$AdjustCssName = "size-chart.css",
    [int]$Width = 0,
    [int]$Height = 0,

    [Alias("Quality")]
    [ValidateRange(1, 100)]
    [int]$JpegQuality = 100,

    [ValidateSet("jpg", "jpeg", "png", "both")]
    [string]$Format = "jpg",

    [switch]$KeepPng,

    [ValidateRange(5, 300)]
    [int]$ScreenshotTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Read-CssVariables {
    param([string]$Path)

    $variables = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $variables
    }

    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $match = [regex]::Match($line, "--(?<name>[A-Za-z0-9_-]+)\s*:\s*(?<value>[^;]+);")
        if ($match.Success) {
            $variables[$match.Groups["name"].Value] = $match.Groups["value"].Value.Trim()
        }
    }
    return $variables
}

function Get-CssInt {
    param(
        [hashtable]$Variables,
        [string]$Name,
        [int]$Default
    )

    if (-not $Variables.ContainsKey($Name)) {
        return $Default
    }

    $match = [regex]::Match([string]$Variables[$Name], "-?\d+(\.\d+)?")
    if (-not $match.Success) {
        return $Default
    }
    return [int][Math]::Round([double]$match.Value)
}

function Get-BrowserPath {
    $candidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw "Cannot find Microsoft Edge or Google Chrome."
}

function Get-RelativeDirectoryPath {
    param(
        [System.IO.DirectoryInfo]$BaseDirectory,
        [System.IO.DirectoryInfo]$ChildDirectory
    )

    $separator = [System.IO.Path]::DirectorySeparatorChar
    $baseUri = New-Object System.Uri(($BaseDirectory.FullName.TrimEnd($separator) + $separator))
    $childUri = New-Object System.Uri(($ChildDirectory.FullName.TrimEnd($separator) + $separator))
    $relativeUri = $baseUri.MakeRelativeUri($childUri)
    $relativePath = [System.Uri]::UnescapeDataString($relativeUri.ToString()).Replace("/", $separator)
    return $relativePath.TrimEnd($separator)
}

function Convert-PngToJpeg {
    param(
        [string]$PngPath,
        [string]$JpegPath,
        [int]$Quality
    )

    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Image]::FromFile($PngPath)
    try {
        $jpegCodec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() |
            Where-Object { $_.MimeType -eq "image/jpeg" } |
            Select-Object -First 1
        if (-not $jpegCodec) {
            throw "JPEG encoder is unavailable."
        }

        $encoder = [System.Drawing.Imaging.Encoder]::Quality
        $encoderParameters = New-Object System.Drawing.Imaging.EncoderParameters(1)
        $encoderParameters.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter(
            $encoder,
            [long]$Quality
        )
        $bitmap.Save($JpegPath, $jpegCodec, $encoderParameters)
    }
    finally {
        $bitmap.Dispose()
    }
}

function Export-HtmlDirectory {
    param(
        [System.IO.FileInfo[]]$HtmlFiles,
        [string]$TargetOutputDir,
        [string]$BrowserPath,
        [string]$UserDataDir,
        [int]$RequestedWidth,
        [int]$RequestedHeight,
        [string]$CssName,
        [string]$OutputFormat,
        [int]$Quality,
        [int]$TimeoutSeconds,
        [switch]$ShouldKeepPng
    )

    if ($HtmlFiles.Count -eq 0) {
        return
    }

    $cssPath = Join-Path $HtmlFiles[0].DirectoryName $CssName
    $cssVariables = Read-CssVariables -Path $cssPath
    $exportWidth = $RequestedWidth
    $exportHeight = $RequestedHeight
    if ($exportWidth -le 0) {
        $exportWidth = Get-CssInt -Variables $cssVariables -Name "page-width" -Default 2000
    }
    if ($exportHeight -le 0) {
        $exportHeight = Get-CssInt -Variables $cssVariables -Name "page-height" -Default 1800
    }

    New-Item -ItemType Directory -Path $TargetOutputDir -Force | Out-Null
    $resolvedOutputDir = (Resolve-Path -LiteralPath $TargetOutputDir).Path

    foreach ($htmlFile in $HtmlFiles) {
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($htmlFile.Name)
        $pngPath = Join-Path $resolvedOutputDir ($baseName + ".png")
        $jpgPath = Join-Path $resolvedOutputDir ($baseName + ".jpg")
        $fileUrl = (New-Object System.Uri($htmlFile.FullName)).AbsoluteUri
        $browserStdout = Join-Path $resolvedOutputDir ($baseName + ".browser.out.log")
        $browserStderr = Join-Path $resolvedOutputDir ($baseName + ".browser.err.log")

        Remove-Item -LiteralPath $pngPath, $jpgPath -ErrorAction SilentlyContinue

        $arguments = @(
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-component-update",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--timeout=5000",
            "--virtual-time-budget=5000",
            "--window-size=$exportWidth,$exportHeight",
            "--user-data-dir=$UserDataDir",
            "--screenshot=$pngPath",
            $fileUrl
        )

        $process = Start-Process `
            -FilePath $BrowserPath `
            -ArgumentList $arguments `
            -PassThru `
            -WindowStyle Hidden `
            -RedirectStandardError $browserStderr `
            -RedirectStandardOutput $browserStdout

        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "Browser screenshot timed out after $TimeoutSeconds seconds: $($htmlFile.FullName)"
        }
        if (-not (Test-Path -LiteralPath $pngPath -PathType Leaf)) {
            $logText = ""
            if (Test-Path -LiteralPath $browserStdout) {
                $logText += Get-Content -LiteralPath $browserStdout -Raw
            }
            if (Test-Path -LiteralPath $browserStderr) {
                $logText += Get-Content -LiteralPath $browserStderr -Raw
            }
            throw "Browser screenshot failed for $($htmlFile.FullName).`n$logText"
        }

        $writtenPaths = New-Object System.Collections.ArrayList
        if ($OutputFormat -eq "jpg" -or $OutputFormat -eq "both") {
            Convert-PngToJpeg -PngPath $pngPath -JpegPath $jpgPath -Quality $Quality
            [void]$writtenPaths.Add($jpgPath)
        }
        if ($OutputFormat -eq "png" -or $OutputFormat -eq "both" -or $ShouldKeepPng) {
            [void]$writtenPaths.Add($pngPath)
        }
        else {
            Remove-Item -LiteralPath $pngPath
        }

        Remove-Item -LiteralPath $browserStdout, $browserStderr -ErrorAction SilentlyContinue
        Write-Host ("Wrote " + (@($writtenPaths) -join ", "))
    }
}

$normalizedFormat = $Format.ToLowerInvariant()
if ($normalizedFormat -eq "jpeg") {
    $normalizedFormat = "jpg"
}

$browserPath = Get-BrowserPath
$userDataDir = Join-Path ([System.IO.Path]::GetTempPath()) ("html-image-export-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null

try {
    if ($PSCmdlet.ParameterSetName -eq "Directory") {
        $inputDirectory = Get-Item -LiteralPath $InputDir
        if (-not $inputDirectory.PSIsContainer) {
            throw "InputDir is not a directory: $InputDir"
        }

        if ([string]::IsNullOrWhiteSpace($OutputDir)) {
            $OutputDir = Join-Path (Join-Path $PSScriptRoot "image") $inputDirectory.Name
        }

        $allHtmlFiles = @(
            Get-ChildItem -LiteralPath $inputDirectory.FullName -Recurse -File -Filter $HtmlPattern |
                Sort-Object DirectoryName, Name
        )
        if ($allHtmlFiles.Count -eq 0) {
            throw "No HTML files matched under $($inputDirectory.FullName): $HtmlPattern"
        }

        foreach ($group in ($allHtmlFiles | Group-Object DirectoryName | Sort-Object Name)) {
            $groupFiles = @($group.Group | Sort-Object Name)
            $htmlDirectory = $groupFiles[0].Directory
            $relativeDirectory = Get-RelativeDirectoryPath `
                -BaseDirectory $inputDirectory `
                -ChildDirectory $htmlDirectory
            $targetOutputDir = if ([string]::IsNullOrWhiteSpace($relativeDirectory)) {
                $OutputDir
            }
            else {
                Join-Path $OutputDir $relativeDirectory
            }

            Export-HtmlDirectory `
                -HtmlFiles $groupFiles `
                -TargetOutputDir $targetOutputDir `
                -BrowserPath $browserPath `
                -UserDataDir $userDataDir `
                -RequestedWidth $Width `
                -RequestedHeight $Height `
                -CssName $AdjustCssName `
                -OutputFormat $normalizedFormat `
                -Quality $JpegQuality `
                -TimeoutSeconds $ScreenshotTimeoutSeconds `
                -ShouldKeepPng:$KeepPng
        }
    }
    else {
        $htmlFiles = @(Get-ChildItem -Path $HtmlGlob -File | Sort-Object Name)
        if ($htmlFiles.Count -eq 0) {
            throw "No HTML files matched: $HtmlGlob"
        }

        if ([string]::IsNullOrWhiteSpace($OutputDir)) {
            $OutputDir = Join-Path (Join-Path $PSScriptRoot "image") $htmlFiles[0].Directory.Name
        }

        Export-HtmlDirectory `
            -HtmlFiles $htmlFiles `
            -TargetOutputDir $OutputDir `
            -BrowserPath $browserPath `
            -UserDataDir $userDataDir `
            -RequestedWidth $Width `
            -RequestedHeight $Height `
            -CssName $AdjustCssName `
            -OutputFormat $normalizedFormat `
            -Quality $JpegQuality `
            -TimeoutSeconds $ScreenshotTimeoutSeconds `
            -ShouldKeepPng:$KeepPng
    }
}
finally {
    if (Test-Path -LiteralPath $userDataDir) {
        Remove-Item -LiteralPath $userDataDir -Recurse -Force
    }
}
