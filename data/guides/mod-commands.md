Mod Commands
(required) [optional]. Don't type the brackets. Use a mention or a user ID.

## Warnings
$warn (member) [reason]
$warnings [member]
$warn remove (member) (case-number)
$warn clear (member)

## Jail
$jail (member) [reason]
$unjail (member) [reason]
$jail list      who's in jail

## Timeouts & Mutes
$timeout (member) [duration] [reason]      10m, 1h, 1d (max 28d)
$untimeout (member) [reason]
$timeout list      who's timed out
$imute (member) [reason]      no images or files
$unimute (member) [reason]
$rmute (member) [reason]      no reactions
$unrmute (member) [reason]

## Kicks & Bans (Mods only)
$kick (member) [reason]
$softban (user) [reason]      kick + delete messages
$ban (user) [reason]
$unban (user-id) [reason]
$hardban (user) [reason]      re-bans if unbanned
$hardban list
$hardban remove (user-id)
$strip (member) [reason]      removes dangerous perms
$staffstrip (member) [reason]      removes staff roles

## Channels
$purge [amount]
$purge (member) [amount]
$cleanup [amount]      this bot's messages
$botclear [amount]      all bot messages
$selfpurge [amount]      your own messages
$lockdown [channel] [reason]
$unlockdown [channel] [reason]
$lockdown all [reason]      every channel, for raids
$unlockdown all

## Other
$history (user)
$modhistory [moderator]
$audit [amount]
$nickname (member) [nickname]
$nickname force (member) (nickname)      stays until cancelled
$nickname force cancel (member)

## Points
$points [member]
$toppoints
$point (member) [reason]      Mods only
$removepoint (point-number)      Mods only
