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
