"""Amounts in words for cheques and invoices (AED dirhams / fils)."""
from decimal import Decimal

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_thousand(n):
    words = []
    if n >= 100:
        words += [ONES[n // 100], "Hundred"]
        n %= 100
    if n >= 20:
        words.append(TENS[n // 10] + (f"-{ONES[n % 10]}" if n % 10 else ""))
    elif n:
        words.append(ONES[n])
    return " ".join(words)


def number_words(n):
    if n == 0:
        return "Zero"
    parts = []
    for value, name in ((10 ** 9, "Billion"), (10 ** 6, "Million"), (1000, "Thousand"), (1, "")):
        if n >= value:
            parts.append((_below_thousand(n // value) + (f" {name}" if name else "")).strip())
            n %= value
    return " ".join(parts)


def amount_words(amount, currency="Dirhams", minor="Fils"):
    amount = Decimal(amount).quantize(Decimal("0.01"))
    whole = int(amount)
    cents = int((amount - whole) * 100)
    text = f"{currency} {number_words(whole)}"
    if cents:
        text += f" and {minor} {number_words(cents)}"
    return text + " Only"
