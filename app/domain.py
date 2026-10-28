"""Money is calculated per line, rounded half up to integer cents."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def calculate(descriptions, quantities, prices, rates):
    if not descriptions or len(descriptions) > 100 or len({len(x) for x in (descriptions, quantities, prices, rates)}) != 1:
        raise ValueError('Voeg 1 tot 100 volledige regels toe.')
    lines = []
    for description, quantity, price, rate in zip(descriptions, quantities, prices, rates):
        try:
            if any(len(x)>32 for x in (quantity,price,rate)): raise ValueError()
            q, p, r = (Decimal(x.replace(',', '.')) for x in (quantity, price, rate))
            if not all(x.is_finite() for x in (q,p,r)) or not 0 < q <= 100000 or not 0 <= p <= 10000000 or r not in (0,9,21) or not description.strip() or len(description)>500:
                raise ValueError()
            net = int((q*p*100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            vat = int((Decimal(net)*r/100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            raise ValueError('Ongeldige omschrijving, hoeveelheid, prijs of btw.') from None
        lines.append(dict(description=description.strip(),quantity=str(q),price=str(p),rate=str(r),net=net,vat=vat))
    return lines
