"""Paper Premium: Stripe subscriptions, one per server.

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
and, optionally, PREMIUM_PRICE_LABEL (e.g. "$4.99 a month") for the button.
STRIPE_API_BASE exists only so tests can stand in for Stripe.

Talks to Stripe's REST API directly, so there's no extra dependency.
"""
import hashlib
import hmac
import json
import os
import time

import aiohttp

API = os.getenv("STRIPE_API_BASE", "https://api.stripe.com").rstrip("/")
TIMEOUT = aiohttp.ClientTimeout(total=20)
TOLERANCE = 300          # seconds a webhook signature stays good for
GRACE = 86400            # a day's slack past the paid-for period, for renewals
TRIAL_DAYS = 7


class BillingError(Exception):
    """Stripe said no, or couldn't be reached."""


class BadSignature(Exception):
    """A webhook that Stripe didn't sign, or signed too long ago."""


def secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def price_id() -> str:
    return os.getenv("STRIPE_PRICE_ID", "").strip()


def configured() -> bool:
    return bool(secret_key() and price_id()
                and os.getenv("STRIPE_WEBHOOK_SECRET", "").strip())


_fetched_label = ""     # the price as Stripe describes it, once asked
SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£", "cad": "CA$", "aud": "A$"}


def price_label() -> str:
    """What Premium costs, for buttons: PREMIUM_PRICE_LABEL if it's set,
    otherwise read from the Stripe price itself, so it can't disagree with
    what Stripe charges."""
    return os.getenv("PREMIUM_PRICE_LABEL", "").strip() or _fetched_label


def describe_price(price: dict) -> str:
    """A Stripe price as words, e.g. "$2.99 a month"."""
    amount = price.get("unit_amount")
    currency = (price.get("currency") or "").lower()
    if not isinstance(amount, int):
        return ""
    money = f"{amount / 100:.2f}"
    symbol = SYMBOLS.get(currency)
    money = f"{symbol}{money}" if symbol else f"{money} {currency.upper()}"
    recurring = price.get("recurring") or {}
    interval, count = recurring.get("interval"), recurring.get("interval_count") or 1
    if interval:
        money += f" a {interval}" if count == 1 else f" every {count} {interval}s"
    return money


async def load_price_label():
    """Ask Stripe what the price is, for price_label()."""
    global _fetched_label
    if configured() and not os.getenv("PREMIUM_PRICE_LABEL", "").strip():
        _fetched_label = describe_price(await _call("GET", f"/v1/prices/{price_id()}"))


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
                   trial: bool = False) -> str:
    """A Stripe Checkout page for one server's subscription. Returns its URL."""
    form = {
        "mode": "subscription",
        "line_items[0][price]": price_id(),
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(guild_id),
        "allow_promotion_codes": "true",
        # On the subscription itself, so every later event says which
        # server it's for.
        "subscription_data[metadata][guild_id]": str(guild_id),
        "subscription_data[metadata][buyer_id]": str(buyer_id),
        "subscription_data[description]": f"Paper Premium for {guild_name}"[:500],
        "metadata[guild_id]": str(guild_id),
    }
    if trial:
        # Stripe takes a card now and charges after the trial, unless
        # they cancel first.
        form["subscription_data[trial_period_days]"] = str(TRIAL_DAYS)
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
    """Record what a subscription means for its server."""
    guild_id = guild_id or _number((sub.get("metadata") or {}).get("guild_id"))
    if not guild_id:
        return
    status = sub.get("status", "")
    if status in ("active", "trialing", "past_due"):
        # past_due: Stripe is still retrying the card. Premium runs to the end
        # of what was paid; if the retries fail the subscription ends and a
        # deleted event follows.
        until = period_end(sub) + GRACE
    else:
        until = int(time.time())
    buyer = _number((sub.get("metadata") or {}).get("buyer_id"))
    db.set_premium(guild_id, status=status, until=until,
                   customer=str(sub.get("customer") or ""),
                   subscription=str(sub.get("id") or ""), buyer_id=buyer)


async def handle(db, event: dict):
    """Act on one webhook event. Safe to run twice for the same event."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed" and obj.get("mode") == "subscription":
        guild_id = _number(obj.get("client_reference_id")
                           or (obj.get("metadata") or {}).get("guild_id"))
        if guild_id and obj.get("subscription"):
            sub = await subscription(obj["subscription"])
            apply_subscription(db, sub, guild_id)
    elif kind in ("customer.subscription.created", "customer.subscription.updated",
                  "customer.subscription.deleted"):
        apply_subscription(db, obj)
