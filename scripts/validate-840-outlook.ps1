# Exercise the actual production correlation function with synthetic MailItems.
# No Outlook application/profile is opened and no message is created or sent.
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../ZakazkyApp_base_6.1/price_lists_domain/platform/outlook_tracking.ps1'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path $source), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$function = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Read-TrackedItem'}, $true)
. ([ScriptBlock]::Create($function.Extent.Text))
$property = 'test-property'
$known = @{'token-1'=$true}
$results = @{'token-1'=@{state='unknown'}}
function Item($token, $sent, $submitted, $folder) {
    $accessor = [PSCustomObject]@{token=$token}
    $accessor | Add-Member ScriptMethod GetProperty {param($p) return $this.token}
    $store = [PSCustomObject]@{}
    $store | Add-Member ScriptMethod GetDefaultFolder {param($id) return [PSCustomObject]@{EntryID='drafts'}}
    return [PSCustomObject]@{Class=43;PropertyAccessor=$accessor;Sent=$sent;Submitted=$submitted;
        SentOn=[DateTime]'2026-09-20T08:00:00Z';Subject='Changed by user';EntryID='changed-id';
        Parent=[PSCustomObject]@{EntryID=$folder;Store=$store}}
}
Read-TrackedItem (Item 'wrong-token' $true $false 'sent') $false
if ($results['token-1'].state -ne 'unknown') { throw 'Subject-only false match' }
Read-TrackedItem (Item 'token-1' $false $true 'outbox') $true
if ($results['token-1'].state -ne 'unknown') { throw 'Queued message is not sent' }
Read-TrackedItem (Item 'token-1' $false $false 'deleted') $true
if ($results['token-1'].state -ne 'unknown') { throw 'Deleted message is not a draft' }
Read-TrackedItem (Item 'token-1' $false $false 'drafts') $true
if ($results['token-1'].state -ne 'draft') { throw 'Saved draft missing' }
Read-TrackedItem (Item 'token-1' $true $false 'sent') $false
if ($results['token-1'].state -ne 'sent' -or -not $results['token-1'].sent_at) { throw 'Sent message not verified' }
Read-TrackedItem (Item 'token-1' $false $false 'drafts') $true
if ($results['token-1'].state -ne 'sent') { throw 'Verified sending lost' }
Write-Output '8.0.40: production Outlook function, token matching, subject/EntryID changes, outbox/deleted exclusion, sent evidence OK'

# Run the WHOLE script through the same JSON boundary as Python. Only the
# connection to Outlook is substituted; no real mail profile is accessed.
# This catches Windows PowerShell 5.1 array nesting and stores that silently
# return zero/partial matches for a named-property Restrict query.
class TrackingTestItems : System.Collections.IEnumerable {
    [object[]] $Rows
    [object[]] $FastRows
    [bool] $FailFast
    [int] $DateQueries
    TrackingTestItems([object[]] $rows, [object[]] $fastRows, [bool] $failFast) {
        $this.Rows=$rows; $this.FastRows=$fastRows; $this.FailFast=$failFast
    }
    [object] Restrict([string] $filter) {
        if ($filter.Contains('0x00390040')) {
            $this.DateQueries++
            return [TrackingTestItems]::new($this.Rows, @(), $false)
        }
        if ($this.FailFast) { throw 'Custom property query unavailable' }
        return [TrackingTestItems]::new($this.FastRows, @(), $false)
    }
    [void] Sort([string] $field, [bool] $descending) {
        if ($field -ne '[SentOn]' -or -not $descending) { throw 'Wrong date sort' }
    }
    [System.Collections.IEnumerator] GetEnumerator() { return $this.Rows.GetEnumerator() }
}
$scriptSource=[IO.File]::ReadAllText((Resolve-Path $source), [Text.Encoding]::UTF8)
# Windows PowerShell 5.1 uses the ANSI code page for BOM-less -File scripts.
$sourceBytes=[IO.File]::ReadAllBytes((Resolve-Path $source))
if ($sourceBytes[0] -ne 239 -or $sourceBytes[1] -ne 187 -or $sourceBytes[2] -ne 191) {
    throw 'The Unicode Outlook script needs a UTF-8 BOM for Windows PowerShell 5.1'
}
$connect="[Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')"
if (-not $scriptSource.Contains($connect)) { throw 'Outlook connection seam changed' }
$check=[ScriptBlock]::Create($scriptSource.Replace($connect, '$script:testOutlook'))
function Run-Tracking($attemptList, $recent, $fast, $failFast, $direct) {
    $items=[TrackingTestItems]::new($recent, $fast, $failFast)
    $emptyStore=[PSCustomObject]@{Folder=[PSCustomObject]@{Items=[TrackingTestItems]::new(@(),@(),$false)}}
    $store=[PSCustomObject]@{Folder=[PSCustomObject]@{Items=$items}}
    foreach ($s in @($emptyStore,$store)) {
        $s | Add-Member ScriptMethod GetDefaultFolder {param($id) return $this.Folder}
    }
    $ns=[PSCustomObject]@{Stores=@($emptyStore,$store);Direct=$direct}
    $ns | Add-Member ScriptMethod GetItemFromID {
        param($entry, $storeId)
        if (-not $this.Direct.ContainsKey($entry)) { throw 'Original draft no longer exists' }
        return $this.Direct[$entry]
    }
    $script:testOutlook=[PSCustomObject]@{Namespace=$ns}
    $script:testOutlook | Add-Member ScriptMethod GetNamespace {param($name) return $this.Namespace}
    $env:TURTO_MAIL_ATTEMPTS=ConvertTo-Json -InputObject @($attemptList) -Compress
    $env:TURTO_MAIL_PROPERTY='test-property'
    $raw=& $check
    if (-not $raw.StartsWith('[')) { throw 'Tracking must return a JSON array, even for one attempt' }
    $decoded=$raw | ConvertFrom-Json
    if (@($decoded).Count -ne @($attemptList).Count -or @($decoded | Where-Object {$null -eq $_}).Count) {
        throw 'Tracking JSON lost attempt records'
    }
    return [PSCustomObject]@{Results=@($decoded);DateQueries=$items.DateQueries}
}
function Attempt($token) {
    return @{token=$token;created_at='2026-09-20T07:00:00Z';draft_entry_id="old-$token";store_id='test-store'}
}
foreach ($count in @(1,2,100)) {
    $attemptList=@(1..$count | ForEach-Object { Attempt "batch-$_" })
    $recent=@(1..$count | ForEach-Object { Item "batch-$_" $true $false 'sent' })
    # A same-subject message with a different token must never be accepted.
    $recent += Item 'unrelated-token' $true $false 'sent'
    $run=Run-Tracking $attemptList $recent @() $false @{}
    if (@($run.Results | Where-Object {$_.state -ne 'sent'}).Count -or $run.DateQueries -ne 1) {
        throw "Empty-query fallback failed for $count attempt(s)"
    }
    $actual=@($run.Results.token | Sort-Object)
    $expected=@($attemptList.token | Sort-Object)
    if (Compare-Object $actual $expected) { throw 'Result token set changed' }
    foreach ($result in $run.Results) {
        # Source must retain Czech text when loaded by powershell.exe -File.
        if ($result.detail -ne ('Ov' + [char]0x011b + [char]0x0159 + 'eno v klasick' + [char]0x00e9 + 'm Outlooku.')) {
            throw 'Outlook status text encoding changed'
        }
    }
}
$attemptList=@(Attempt 'batch-1';Attempt 'batch-2')
$recent=@(Item 'batch-1' $true $false 'sent';Item 'batch-2' $true $false 'sent')
foreach ($failFast in @($false,$true)) {
    $run=Run-Tracking $attemptList $recent @($recent[0]) $failFast @{}
    if (@($run.Results | Where-Object {$_.state -ne 'sent'}).Count) { throw 'Partial/throwing query lost a sent message' }
}
$attemptList=@(Attempt 'saved';Attempt 'queued';Attempt 'deleted';Attempt 'missing')
$direct=@{
    'old-saved'=(Item 'saved' $false $false 'drafts')
    'old-queued'=(Item 'queued' $false $true 'outbox')
    'old-deleted'=(Item 'deleted' $false $false 'deleted')
}
$run=Run-Tracking $attemptList @((Item 'other-token' $true $false 'sent')) @() $false $direct
if ($run.Results[0].state -ne 'draft' -or @($run.Results | Select-Object -Skip 1 | Where-Object {$_.state -ne 'unknown'}).Count) {
    throw 'Draft/outbox/deleted/missing distinction lost'
}
$run=Run-Tracking @() @() @() $false @{}
if ($run.Results.Count) { throw 'Empty input returned records' }
Write-Output 'Full Outlook reconciliation: 1/2/100 attempts, JSON, empty/partial/error query fallback, multiple stores, exact tokens and draft/outbox/deleted states OK'
