param(
    [Parameter(Mandatory = $true)]
    [string]$SongsRoot,

    [Parameter(Mandatory = $true)]
    [string]$SshTarget,

    [Parameter(Mandatory = $true)]
    [string]$RemoteRoot,

    [string]$OutputRoot = ".\prepared-karaoke",
    [string]$SongIdMap,
    [string]$SshKey,
    [string]$Image = "dreayrt/audio_separator_for_karaoke:0.3.0-prep-gpu"
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Program @Arguments
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode -or $exitCode -ne 0) {
        throw "$Program failed with exit code $exitCode"
    }
}

function Get-SafeSongId {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$') {
        throw "SongId '$Value' is not path-safe. Use letters, numbers, dot, underscore or hyphen; it must start with a letter or number."
    }
    return $Value
}

if ($SshTarget.StartsWith("-") -or $SshTarget -match '\s') {
    throw "SshTarget must be a host alias or user@host without spaces or leading hyphens."
}
if ($RemoteRoot -notmatch '^/?[A-Za-z0-9._/-]+$') {
    throw "RemoteRoot must be a simple Linux path such as '/srv/moodify/karaoke'."
}
if (($RemoteRoot -split '/') -contains '..' -or ($RemoteRoot -split '/') -contains '.') {
    throw "RemoteRoot cannot contain '.' or '..' path segments."
}
$RemoteRoot = $RemoteRoot.TrimEnd('/')
if ([string]::IsNullOrWhiteSpace($RemoteRoot)) {
    throw "RemoteRoot cannot be the filesystem root."
}

foreach ($program in @("docker", "ssh", "scp")) {
    if (-not (Get-Command $program -ErrorAction SilentlyContinue)) {
        throw "Required command '$program' was not found. Install/start Docker Desktop and Windows OpenSSH Client."
    }
}

$sourceRoot = (Resolve-Path -LiteralPath $SongsRoot).Path.TrimEnd([char[]]@('\', '/'))
$outputPath = [System.IO.Path]::GetFullPath($OutputRoot).TrimEnd([char[]]@('\', '/'))
$sourcePrefix = $sourceRoot + [System.IO.Path]::DirectorySeparatorChar
if ($outputPath.Equals($sourceRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $outputPath.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot must be outside SongsRoot so prepared WAV files are not picked up as source songs."
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

if ($SshKey) {
    $SshKey = (Resolve-Path -LiteralPath $SshKey).Path
    $sshOptions = @("-i", $SshKey, "-o", "IdentitiesOnly=yes")
} else {
    $sshOptions = @()
}

$audioExtensions = @(".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wma", ".webm")
$audioFiles = @(Get-ChildItem -LiteralPath $sourceRoot -File -Recurse |
    Where-Object { $audioExtensions -contains $_.Extension.ToLowerInvariant() } |
    Sort-Object FullName)
if ($audioFiles.Count -eq 0) {
    throw "No supported audio files were found under '$sourceRoot'."
}

$idByRelativePath = @{}
if ($SongIdMap) {
    $mapPath = (Resolve-Path -LiteralPath $SongIdMap).Path
    $mapRows = @(Import-Csv -LiteralPath $mapPath)
    if ($mapRows.Count -eq 0 -or
        -not ($mapRows[0].PSObject.Properties.Name -contains "RelativePath") -or
        -not ($mapRows[0].PSObject.Properties.Name -contains "SongId")) {
        throw "SongIdMap CSV must have columns named RelativePath and SongId."
    }
    foreach ($row in $mapRows) {
        $relativeKey = ([string]$row.RelativePath).Trim().Replace('\', '/').TrimStart('/')
        if ([string]::IsNullOrWhiteSpace($relativeKey) -or $relativeKey -match '(^|/)\.\.(/|$)') {
            throw "SongIdMap contains an invalid RelativePath '$($row.RelativePath)'."
        }
        if ($idByRelativePath.ContainsKey($relativeKey)) {
            throw "SongIdMap contains duplicate RelativePath '$relativeKey'."
        }
        $idByRelativePath[$relativeKey] = Get-SafeSongId ([string]$row.SongId)
    }
}

$songs = @()
$seenIds = @{}
foreach ($file in $audioFiles) {
    $relativePath = $file.FullName.Substring($sourcePrefix.Length).Replace('\', '/')
    if ($SongIdMap) {
        if (-not $idByRelativePath.ContainsKey($relativePath)) {
            throw "SongIdMap has no entry for '$relativePath'."
        }
        $songId = $idByRelativePath[$relativePath]
    } else {
        $songId = $file.BaseName -replace '[^A-Za-z0-9._-]', '-'
        $songId = $songId.Trim([char[]]@('.', '_', '-'))
        if ([string]::IsNullOrWhiteSpace($songId)) {
            throw "Cannot derive a safe SongId from '$relativePath'; provide -SongIdMap."
        }
        $songId = Get-SafeSongId $songId
    }
    if ($seenIds.ContainsKey($songId)) {
        throw "SongId '$songId' is duplicated. Provide a SongIdMap with unique IDs for every file."
    }
    $seenIds[$songId] = $true
    $songs += [pscustomobject]@{ File = $file; RelativePath = $relativePath; SongId = $songId }
}

Write-Host "Pulling GPU preparation image: $Image"
Invoke-CheckedNative "docker" @("pull", $Image)

Write-Host "Checking that Docker can access the NVIDIA GPU..."
$gpuCheck = "import torch; assert torch.cuda.is_available(), 'CUDA is not visible to this container'; print(torch.cuda.get_device_name(0))"
Invoke-CheckedNative "docker" @("run", "--rm", "--gpus", "all", "--entrypoint", "python", $Image, "-c", $gpuCheck)

$remoteRootCommand = "mkdir -p -- '$RemoteRoot'"
Write-Host "Creating/checking Google Cloud VM destination: $SshTarget`:$RemoteRoot"
Invoke-CheckedNative "ssh" ($sshOptions + @($SshTarget, $remoteRootCommand))

$requiredNames = @("instrumental.wav", "vocals.wav", "pitch_reference.json", "karaoke_asset_manifest.json")
$results = [System.Collections.Generic.List[object]]::new()
$index = 0

foreach ($song in $songs) {
    $index++
    $songId = $song.SongId
    $songOutput = Join-Path $outputPath $songId
    $remoteSongPath = "$RemoteRoot/$songId"
    Write-Host "[$index/$($songs.Count)] $($song.RelativePath) -> $songId"

    try {
        if (Test-Path -LiteralPath $songOutput) {
            $existingManifestPath = Join-Path $songOutput "karaoke_asset_manifest.json"
            $complete = (Test-Path -LiteralPath $existingManifestPath) -and
                (@($requiredNames | Where-Object { -not (Test-Path -LiteralPath (Join-Path $songOutput $_)) }).Count -eq 0)
            if (-not $complete) {
                throw "Output folder '$songOutput' exists but is incomplete. Move it aside or choose another OutputRoot before retrying."
            }
            $existingManifest = Get-Content -LiteralPath $existingManifestPath -Raw | ConvertFrom-Json
            $sourceHash = (Get-FileHash -LiteralPath $song.File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($existingManifest.songId -ne $songId -or
                $existingManifest.status -ne "prepared_local" -or
                $existingManifest.source.sha256 -ne $sourceHash) {
                throw "Existing output for '$songId' does not match this source file/ID. Move it aside before retrying."
            }
            Write-Host "  Reusing complete local output; will retry/upload it."
        } else {
            $dockerArgs = @(
                "run", "--rm", "--gpus", "all",
                "--mount", "type=bind,source=$($song.File.DirectoryName),target=/input,readonly",
                "--mount", "type=bind,source=$outputPath,target=/output",
                $Image,
                "--input", "/input/$($song.File.Name)",
                "--song-id", $songId,
                "--output-dir", "/output/$songId",
                "--device", "cuda",
                "--cpu-threads", "auto"
            )
            Invoke-CheckedNative "docker" $dockerArgs
        }

        foreach ($name in $requiredNames) {
            $assetPath = Join-Path $songOutput $name
            if (-not (Test-Path -LiteralPath $assetPath) -or (Get-Item -LiteralPath $assetPath).Length -le 0) {
                throw "Expected output '$assetPath' is missing or empty."
            }
        }
        $manifest = Get-Content -LiteralPath (Join-Path $songOutput "karaoke_asset_manifest.json") -Raw | ConvertFrom-Json
        if ($manifest.songId -ne $songId -or $manifest.status -ne "prepared_local") {
            throw "Output manifest does not match songId '$songId' or is not marked prepared_local."
        }

        Invoke-CheckedNative "ssh" ($sshOptions + @($SshTarget, "mkdir -p -- '$remoteSongPath'"))
        $remoteDestination = "${SshTarget}:$remoteSongPath/"
        foreach ($name in $requiredNames) {
            $assetPath = Join-Path $songOutput $name
            Invoke-CheckedNative "scp" ($sshOptions + @($assetPath, $remoteDestination))
        }

        $verifyCommand = "cd '$remoteSongPath' && sha256sum $($requiredNames -join ' ')"
        $remoteHashLines = & ssh @sshOptions $SshTarget $verifyCommand
        $remoteExitCode = $LASTEXITCODE
        if ($null -eq $remoteExitCode -or $remoteExitCode -ne 0) {
            throw "Could not verify uploaded files on the Google Cloud VM (ssh exit code $remoteExitCode)."
        }
        $remoteHashes = @{}
        foreach ($line in $remoteHashLines) {
            if ([string]$line -match '^([0-9A-Fa-f]{64})\s+\*?(.+)$') {
                $remoteHashes[$Matches[2].Trim()] = $Matches[1].ToLowerInvariant()
            }
        }
        foreach ($name in $requiredNames) {
            $localHash = (Get-FileHash -LiteralPath (Join-Path $songOutput $name) -Algorithm SHA256).Hash.ToLowerInvariant()
            if (-not $remoteHashes.ContainsKey($name) -or $remoteHashes[$name] -ne $localHash) {
                throw "SHA-256 mismatch for uploaded file '$name' on the Google Cloud VM."
            }
        }

        $results.Add([pscustomobject]@{
            songId = $songId
            relativePath = $song.RelativePath
            status = "uploaded"
            remotePath = $remoteSongPath
            error = $null
        })
        Write-Host "  Uploaded to $SshTarget`:$remoteSongPath"
    } catch {
        $results.Add([pscustomobject]@{
            songId = $songId
            relativePath = $song.RelativePath
            status = "failed"
            remotePath = $remoteSongPath
            error = $_.Exception.Message
        })
        Write-Warning "  Failed '$songId': $($_.Exception.Message)"
    }
}

$reportPath = Join-Path $outputPath "batch-upload-report.json"
$results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
$failedCount = @($results | Where-Object { $_.status -eq "failed" }).Count
$uploadedCount = $results.Count - $failedCount
Write-Host "Finished: $uploadedCount uploaded, $failedCount failed. Report: $reportPath"

if ($failedCount -gt 0) {
    exit 1
}
