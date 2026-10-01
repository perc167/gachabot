"""Paper Premium: Stripe payments, per server, and per player.

Three plans for a server (PLANS):
    premium   monthly, with a free trial: the Premium perks
    plus      monthly: Premium and the server builder ($serversetup)
    lifetime  paid once: Plus for that server forever, never charged again
and one for a person (PLAYER): Player Premium, monthly, their own gacha
boosts on every server. Its Stripe objects carry metadata kind=player and a
user_id instead of a guild_id, and it has its own table, so the two never
mix.

Card details never reach the bot. The dashboard asks Stripe for a Checkout
page and sends the admin there; Stripe tells the bot what happened through
a signed webhook, and the bot keeps one row per server saying how long its
premium lasts. That's the only thing gating reads: premium means `until` is
in the future. A renewal pushes it on, a cancellation lets it run to the
end of what was paid for, and a subscription that ends stops it.

Needs, from the Stripe dashboard:
    STRIPE_SECRET_KEY      Developers > API keys (sk_test_... to try it out)
    STRIPE_PRICE_ID        Product catalogue > the monthly price (price_...)
    STRIPE_WEBHOOK_SECRET  Developers > Webhooks > the endpoint (whsec_...)
    STRIPE_PLUS_PRICE_ID      the Plus monthly price (optional)
    STRIPE_LIFETIME_PRICE_ID  the Lifetime one-time price (optional)
    STRIPE_PLAYER_PRICE_ID    the Player Premium monthly price (optional)
and, optionally, PREMIUM_PRICE_LABEL (e.g. "$4.99 a month") for the button.
STRIPE_API_BASE exists only so tests can stand in for Stripe.

Talks to Stripe's REST API directly, so there's no extra dependency.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time

import aiohttp

API = os.getenv("STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")
TIMEOUT = aiohttp.ClientTimeout(total=20)
TOLERANCE = 300          # seconds a webhook signature stays good for
GRACE = 86400            # a day's slack past the paid-for period, for renewals
TRIAL_DAYS = 7
FOREVER = 32503680000    # the year 3000: when a Lifetime purchase "runs out"

# key: (price env var, Stripe mode, the tier it gives, name, one line on it)
PLANS = {
    "premium": ("STRIPE_PRICE_ID", "subscription", "premium", "Paper Premium",
                "Everything in Premium, with a free week first"),
    "plus": ("STRIPE_PLUS_PRICE_ID", "subscription", "plus", "Paper Premium Plus",
             "Premium, and your gacha set your way, events, champions and the server builder"),
    "lifetime": ("STRIPE_LIFETIME_PRICE_ID", "payment", "lifetime", "Paper Lifetime",
                 "Premium Plus for this server forever. Pay once, never again"),
}
# Higher outranks lower: a lower plan's events never replace a higher one.
RANK = {"premium": 1, "plus": 2, "lifetime": 3}

# Player Premium: (price env var, name, one line on it).
PLAYER = ("STRIPE_PLAYER_PRICE_ID", "Paper Player Premium",
          "Your own extra rolls, wishes and karuda, on every server")


class BillingError(Exception):
    """Stripe said no, or couldn't be reached."""


class BadSignature(Exception):
    """A webhook that Stripe didn't sign, or signed too long ago."""


def secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def price_id(plan: str = "premium") -> str:
    return os.getenv(PLANS[plan][0], "").strip()


def plan_on_sale(plan: str) -> bool:
    return configured() and bool(price_id(plan))


def configured() -> bool:
    return bool(secret_key() and price_id()
                and os.getenv("STRIPE_WEBHOOK_SECRET", "").strip())


_labels = {}            # plan -> the price as Stripe describes it, once asked
SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£", "cad": "CA$", "aud": "A$"}


def price_label() -> str:
    """What Premium costs, for buttons: PREMIUM_PRICE_LABEL if it's set,
    otherwise read from the Stripe price itself, so it can't disagree with
    what Stripe charges."""
    return os.getenv("PREMIUM_PRICE_LABEL", "").strip() or _labels.get("premium", "")


def plan_label(plan: str) -> str:
    return price_label() if plan == "premium" else _labels.get(plan, "")


def player_price_id() -> str:
    return os.getenv(PLAYER[0], "").strip()


def player_on_sale() -> bool:
    return configured() and bool(player_price_id())


def player_label() -> str:
    return _labels.get("player", "")


# Prices are shown in US dollars. The account is Australian, so each price
# is AUD with a USD amount beside it (Stripe's currency_options), which US
# buyers are charged exactly. A price without one is converted at the AUD ->
# USD rate of 29 Sep 2026, rounded to the nearest 50 cents.
TO_USD = {"aud": 0.70045}
# Said wherever the prices are, so a checkout page in AUD is no surprise.
PRICE_NOTE = "Prices in US dollars. Outside the US, checkout may show another currency."


def describe_price(price: dict) -> str:
    """A Stripe price as words, e.g. "$2.99 a month"."""
    amount = price.get("unit_amount")
    currency = (price.get("currency") or "").lower()
    usd = ((price.get("currency_options") or {}).get("usd") or {}).get("unit_amount")
    if isinstance(usd, int):
        amount, currency = usd, "usd"
    if not isinstance(amount, int):
        return ""
    if currency in TO_USD:
        amount = max(50, round(amount * TO_USD[currency] / 50) * 50)
        currency = "usd"
    money = f"{amount / 100:.2f}"
    symbol = SYMBOLS.get(currency)
    money = f"{symbol}{money}" if symbol else f"{money} {currency.upper()}"
    recurring = price.get("recurring") or {}
    interval, count = recurring.get("interval"), recurring.get("interval_count") or 1
    if interval:
        money += f" a {interval}" if count == 1 else f" every {count} {interval}s"
    return money


async def load_price_label():
    """Ask Stripe what each plan costs, for plan_label()."""
    # Each plan on its own, so one bad price ID can't blank all three. The
    # USD amount needs an expand; if Stripe refuses it, the plain price
    # still gives a converted label.
    wanted = [(plan, price_id(plan), PLANS[plan][1] == "payment")
              for plan in PLANS if plan_on_sale(plan)]
    if player_on_sale():
        wanted.append(("player", player_price_id(), False))
    for plan, price, once in wanted:
        path = f"/v1/prices/{price}"
        try:
            try:
                price = await _call("GET", path + "?expand[]=currency_options")
            except BillingError as error:
                logging.getLogger("billing").warning(
                    "%s price without its currencies: %s", plan, error)
                price = await _call("GET", path)
        except (BillingError, OSError, asyncio.TimeoutError) as error:
            logging.getLogger("billing").warning(
                "couldn't read the %s price (%s): %s", plan, path.rsplit("/", 1)[1], error)
            continue
        label = describe_price(price)
        _labels[plan] = label + (" once" if once else "")


async def _call(method: str, path: str, form: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {secret_key()}"}
    async with aiohttp.ClientSession(timeout=TIMEOUT) as http:
        async with http.request(method, f"{API}{path}", data=form,
                                headers=headers) as response:
            try:
                body = await response.json(content_type=None)
            except ValueError:
                body = {}
            if response.status >= 400:
                message = (body.get("error") or {}).get("message") or response.status
                raise BillingError(f"Stripe: {message}")
            return body


async def checkout(guild_id: int, guild_name: str, buyer_id: int,
                   success_url: str, cancel_url: str, customer: str = "",
                   trial: bool = False, plan: str = "premium") -> str:
    """A Stripe Checkout page for one server's plan. Returns its URL."""
    _env, mode, tier, name, _line = PLANS[plan]
    form = {
        "mode": mode,
        "line_items[0][price]": price_id(plan),
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(guild_id),
        "allow_promotion_codes": "true",
        "metadata[guild_id]": str(guild_id),
        "metadata[buyer_id]": str(buyer_id),
        "metadata[tier]": tier,
    }
    if mode == "subscription":
        # On the subscription itself, so every later event says which
        # server it's for, and which plan.
        form.update({
            "subscription_data[metadata][guild_id]": str(guild_id),
            "subscription_data[metadata][buyer_id]": str(buyer_id),
            "subscription_data[metadata][tier]": tier,
            "subscription_data[description]": f"{name} for {guild_name}"[:500],
        })
    else:
        form.update({
            "payment_intent_data[metadata][guild_id]": str(guild_id),
            "payment_intent_data[description]": f"{name} for {guild_name}"[:500],
            # A customer and a receipt, like a subscription gets.
            "invoice_creation[enabled]": "true",
        })
        if not customer:
            form["customer_creation"] = "always"
    if trial and plan == "premium":
        # Stripe takes a card now and charges after the trial, unless
        # they cancel first.
        form["subscription_data[trial_period_days]"] = str(TRIAL_DAYS)
    if customer:
        form["customer"] = customer
    session = await _call("POST", "/v1/checkout/sessions", form)
    return session["url"]


async def player_checkout(user_id: int, success_url: str, cancel_url: str,
                          customer: str = "") -> str:
    """A Stripe Checkout page for one person's Player Premium."""
    meta = {"kind": "player", "user_id": str(user_id)}
    form = {
        "mode": "subscription",
        "line_items[0][price]": player_price_id(),
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": f"user-{user_id}",
        "allow_promotion_codes": "true",
        "subscription_data[description]": PLAYER[1],
    }
    for key, value in meta.items():
        form[f"metadata[{key}]"] = value
        # On the subscription too, so every later event says whose it is.
        form[f"subscription_data[metadata][{key}]"] = value
    if customer:
        form["customer"] = customer
    session = await _call("POST", "/v1/checkout/sessions", form)
    return session["url"]


async def portal(customer: str, return_url: str) -> str:
    """Stripe's own page for changing the card or cancelling."""
    session = await _call("POST", "/v1/billing_portal/sessions",
                          {"customer": customer, "return_url": return_url})
    return session["url"]


async def subscription(subscription_id: str) -> dict:
    return await _call("GET", f"/v1/subscriptions/{subscription_id}")


async def end_at_period_end(subscription_id: str):
    """Stop a subscription renewing, e.g. the old plan after an upgrade."""
    await _call("POST", f"/v1/subscriptions/{subscription_id}",
                {"cancel_at_period_end": "true"})


def verify(payload: bytes, header: str, secret: str = None, now: float = None) -> dict:
    """The event, if Stripe signed it in the last few minutes. Otherwise
    BadSignature. Stripe's scheme: HMAC-SHA256 of "<timestamp>.<body>"."""
    secret = secret if secret is not None else os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret or not header:
        raise BadSignature("no signature")
    parts = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, []).append(value)
    try:
        stamp = int(parts["t"][0])
    except (KeyError, ValueError):
        raise BadSignature("no timestamp")
    if abs((now or time.time()) - stamp) > TOLERANCE:
        raise BadSignature("too old")
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + payload,
                        hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise BadSignature("wrong signature")
    return json.loads(payload)


def period_end(sub: dict) -> int:
    """When the paid-for period ends. Newer Stripe API versions keep this on
    the subscription's items rather than the subscription."""
    end = sub.get("current_period_end")
    if not end:
        items = (sub.get("items") or {}).get("data") or []
        end = items[0].get("current_period_end") if items else 0
    return int(end or 0)


def _number(value) -> int:
    """An id from Stripe's metadata, or 0. A bad buyer note must never be
    what stops a paid server getting premium."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def apply_subscription(db, sub: dict, guild_id: int = None):
    """Record what a subscription means for its server. Returns the id of a
    different subscription this one takes over from, if any, so it can be
    stopped from renewing."""
    meta = sub.get("metadata") or {}
    guild_id = guild_id or _number(meta.get("guild_id"))
    if not guild_id:
        return None
    status = sub.get("status", "")
    tier = meta.get("tier") if meta.get("tier") in ("premium", "plus") else "premium"
    sub_id = str(sub.get("id") or "")
    live = status in ("active", "trialing", "past_due")
    row = db.premium_of(guild_id)
    replaced = None
    if row and row["until"] > time.time():
        if row["status"] == "lifetime":
            return None                 # paid for good; no subscription changes it
        if row["subscription"] and row["subscription"] != sub_id:
            # Another subscription is the one in charge. An old one ending,
            # or a lower plan, mustn't take over from it.
            if not live or RANK[tier] < RANK.get(row["tier"], 1):
                return None
            replaced = row["subscription"]
    if live:
        # past_due: Stripe is still retrying the card. Premium runs to the end
        # of what was paid; if the retries fail the subscription ends and a
        # deleted event follows.
        until = period_end(sub) + GRACE
    else:
        until = int(time.time())
    buyer = _number(meta.get("buyer_id"))
    db.set_premium(guild_id, status=status, until=until,
                   customer=str(sub.get("customer") or ""),
                   subscription=sub_id, buyer_id=buyer, tier=tier)
    return replaced if live else None


def apply_player(db, sub: dict):
    """Record what a Player Premium subscription means for its person."""
    meta = sub.get("metadata") or {}
    user_id = _number(meta.get("user_id"))
    if not user_id:
        return
    status = sub.get("status", "")
    sub_id = str(sub.get("id") or "")
    live = status in ("active", "trialing", "past_due")
    row = db.player_premium_of(user_id)
    if (not live and row and row["subscription"] and row["subscription"] != sub_id
            and row["until"] > time.time()):
        return                          # an old subscription ending; a newer one runs
    until = period_end(sub) + GRACE if live else int(time.time())
    db.set_player_premium(user_id, status=status, until=until,
                          customer=str(sub.get("customer") or ""), subscription=sub_id)


def apply_lifetime(db, session: dict, guild_id: int):
    """A paid Lifetime purchase: Plus, for good. Returns the subscription it
    replaces, if one was running, so it can be stopped from renewing."""
    row = db.premium_of(guild_id)
    running = row["subscription"] if row and row["until"] > time.time() \
        and row["status"] != "lifetime" else ""
    db.set_premium(guild_id, status="lifetime", until=FOREVER,
                   customer=str(session.get("customer") or ""), subscription="",
                   buyer_id=_number((session.get("metadata") or {}).get("buyer_id")),
                   tier="lifetime")
    return running or None


async def handle(db, event: dict):
    """Act on one webhook event. Safe to run twice for the same event."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    if (obj.get("metadata") or {}).get("kind") == "player":
        if kind == "checkout.session.completed" and obj.get("subscription"):
            apply_player(db, await subscription(obj["subscription"]))
        elif kind in ("customer.subscription.created", "customer.subscription.updated",
                      "customer.subscription.deleted"):
            apply_player(db, obj)
        return
    replaced = None
    guild_id = _number(obj.get("client_reference_id")
                       or (obj.get("metadata") or {}).get("guild_id"))
    if kind == "checkout.session.completed" and obj.get("mode") == "subscription":
        if guild_id and obj.get("subscription"):
            sub = await subscription(obj["subscription"])
            replaced = apply_subscription(db, sub, guild_id)
    elif (kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded")
          and obj.get("mode") == "payment" and obj.get("payment_status") == "paid"
          and (obj.get("metadata") or {}).get("tier") == "lifetime" and guild_id):
        replaced = apply_lifetime(db, obj, guild_id)
    elif kind in ("customer.subscription.created", "customer.subscription.updated",
                  "customer.subscription.deleted"):
        replaced = apply_subscription(db, obj)
    if replaced:
        # Upgraded: the old plan stops renewing, so nobody pays twice.
        try:
            await end_at_period_end(replaced)
        except (BillingError, OSError):
            logging.getLogger("billing").error(
                "couldn't stop the old subscription %s after an upgrade; cancel it"
                " in Stripe so the server isn't charged twice", replaced)
