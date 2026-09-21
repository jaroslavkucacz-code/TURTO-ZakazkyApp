# Read-only reconciliation with the already running classic Outlook profile.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$attempts = @($env:TURTO_MAIL_ATTEMPTS | ConvertFrom-Json)
$property = $env:TURTO_MAIL_PROPERTY
$known = @{}
$results = @{}
foreach ($attempt in $attempts) {
    $known[$attempt.token] = $attempt
    $results[$attempt.token] = @{token=$attempt.token;state='unknown';detail='Zpráva nebyla nalezena nebo není dostupná.'}
}
$watch = [Diagnostics.Stopwatch]::StartNew()
function Read-TrackedItem($item, $allowDraft) {
    try {
        if ($item.Class -ne 43) { return }
        $token = [string]$item.PropertyAccessor.GetProperty($property)
        if (-not $known.ContainsKey($token)) { return }
        if ($item.Sent) {
            $sent = $item.SentOn.ToUniversalTime()
            if ($sent.Year -ge 2000 -and $sent.Year -le (Get-Date).Year+1) {
                $results[$token] = @{token=$token;state='sent';sent_at=$sent.ToString('o');detail='Ověřeno v klasickém Outlooku.'}
            }
        } elseif ($allowDraft -and -not $item.Submitted -and $results[$token].state -ne 'sent' -and
                  $item.Parent.EntryID -eq $item.Parent.Store.GetDefaultFolder(16).EntryID) {
            $results[$token] = @{token=$token;state='draft';detail='Koncept je uložen v Outlooku.'}
        }
    } catch {}
}
try {
    # Never launch Outlook, display a login window or prompt the user from a timer.
    $outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
    $namespace = $outlook.GetNamespace('MAPI')
    foreach ($attempt in $attempts) {
        if ($watch.Elapsed.TotalSeconds -gt 30) { break }
        if ($attempt.draft_entry_id -and $attempt.store_id) {
            try { Read-TrackedItem ($namespace.GetItemFromID($attempt.draft_entry_id, $attempt.store_id)) $true } catch {}
        }
    }
    $earliest = ($attempts | ForEach-Object { [DateTime]::Parse($_.created_at).ToUniversalTime() } | Sort-Object | Select-Object -First 1).AddMinutes(-5)
    $cutoff = $earliest.ToString('yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
    $dateFilter = '@SQL="http://schemas.microsoft.com/mapi/proptag/0x00390040" >= ' + "'" + $cutoff + "'"
    $tokenFilter = '@SQL=' + (($attempts | ForEach-Object { '"' + $property + '" = ' + "'" + $_.token.Replace("'", "''") + "'" }) -join ' OR ')
    $scanned = 0
    foreach ($store in $namespace.Stores) {
        if ($watch.Elapsed.TotalSeconds -gt 30) { break }
        try {
            $folder = $store.GetDefaultFolder(5) # olFolderSentMail; independent of translated folder names.
            try { $items = $folder.Items.Restrict($tokenFilter) }
            catch { $items = $folder.Items.Restrict($dateFilter) }
            foreach ($item in $items) {
                if ($watch.Elapsed.TotalSeconds -gt 30 -or $scanned -ge 20000) { break }
                $scanned++
                Read-TrackedItem $item $false
            }
        } catch {}
    }
} catch {}
ConvertTo-Json -InputObject @($attempts | ForEach-Object { $results[$_.token] }) -Compress -Depth 4
