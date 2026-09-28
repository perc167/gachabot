-# The commands are in the **Mod Commands** thread.
# How to Moderate
**We talk first, then decide.**
Every problem starts with a jail, no matter who it is. We talk it out, then choose the fairest outcome.

## Ranks
**Trial Mods:** jail, unjail, warn, timeout, imute, rmute
**Mods:** everything above, plus kick and ban

## Step 1: Jail
Jail anyone who breaks a rule. No exceptions.
```
$jail @user reason
```

## Step 2: Talk
The bot pings them in the jail channel. Talk to them there.
- Tell them which rule they broke.
- Listen to their side.
- Stay calm, even if they don't.

## Step 3: Decide
- **Sorted out:** `$unjail` and `$warn`
- **Needs a break:** `$unjail` and `$timeout`
- **Should be kicked or banned:** keep them jailed and report it to a Mod

## Step 4: Mods handle reports
Read the jail chat, then kick, ban or unjail.

## Points
Points track your work and are used for promotions.

**Trial Mods get 1 point for each:**
- jail
- mute (timeout, imute or rmute)
- person you reported who gets banned

Jails and mutes give your point automatically. Check yours with `$points`.

**Mods:** when you ban someone a Trial Mod reported, give them their point:
```
$point @trialmod ban
```

## Good habits
- Always give a reason. It's saved to their history.
- Check `$history @user` before you decide.
- Unjail people once it's sorted.
- Jailing people without a reason to get points will count against you.
