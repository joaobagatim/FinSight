"""Small synthetic seed through real public registration/auth/financial endpoints."""

import json
from datetime import date, timedelta
from uuid import uuid4


def seed_demo(local, credentials, opener, request, save):
    path = local / "seed.json"
    if path.exists():
        plan = json.loads(path.read_text())
    else:
        today = date.today()
        plan = {
            "anchor": today.isoformat(),
            "opening": (today - timedelta(days=30)).isoformat(),
            "keys": [str(uuid4()) for _ in range(8)],
            "categories": {},
        }
        save(path, plan)  # Persist keys before any POST, including ambiguous responses.
    request(
        opener,
        "/api/v1/auth/register",
        {
            "name": "Pessoa Demonstração",
            "email": credentials["DEMO_EMAIL"],
            "password": credentials["DEMO_PASSWORD"],
        },
    )

    def csrf():
        return request(opener, "/api/v1/auth/csrf", {}, {"X-CSRF-Bootstrap": "1"})["csrf_token"]

    request(
        opener,
        "/api/v1/auth/login",
        {"email": credentials["DEMO_EMAIL"], "password": credentials["DEMO_PASSWORD"]},
        {"X-CSRF-Token": csrf()},
    )

    def create(resource, data, key=None):
        headers = {"X-CSRF-Token": csrf()}
        if key:
            headers["Idempotency-Key"] = key
        return request(opener, "/api/v1/" + resource, data, headers)

    accounts = []
    for index, (name, kind, amount) in enumerate(
        [
            ("Conta corrente fictícia", "checking", "1000.00"),
            ("Reserva fictícia", "savings", "2500.00"),
        ]
    ):
        accounts.append(
            create(
                "accounts",
                {
                    "name": name,
                    "type": kind,
                    "currency": "BRL",
                    "opening_balance": amount,
                    "opening_date": plan["opening"],
                },
                plan["keys"][index],
            )["id"]
        )

    existing = request(opener, "/api/v1/categories?limit=100")["items"]
    for name, kind in [
        ("Salário fictício", "income"),
        ("Serviços fictícios", "income"),
        ("Alimentação fictícia", "expense"),
        ("Moradia fictícia", "expense"),
    ]:
        if name not in plan["categories"]:
            match = next(
                (item for item in existing if item["name"] == name and item["type"] == kind), None
            )
            category = match or create("categories", {"name": name, "type": kind})
            plan["categories"][name] = category["id"]
            save(path, plan)
    anchor = date.fromisoformat(plan["anchor"])
    rows = [
        (0, "Salário fictício", "Receita mensal de exemplo", "4200.00", "income", "posted", -5),
        (0, "Alimentação fictícia", "Mercado de exemplo", "245.80", "expense", "posted", -3),
        (0, "Moradia fictícia", "Aluguel de exemplo", "1200.00", "expense", "posted", -2),
        (1, "Serviços fictícios", "Serviço de exemplo", "350.00", "income", "posted", -1),
        (0, "Moradia fictícia", "Próximo aluguel de exemplo", "1200.00", "expense", "planned", 7),
        (1, "Serviços fictícios", "Próximo serviço de exemplo", "500.00", "income", "planned", 10),
    ]
    for index, (account, category, description, amount, kind, status, offset) in enumerate(rows):
        create(
            "transactions",
            {
                "account_id": accounts[account],
                "category_id": plan["categories"][category],
                "description": description,
                "amount": amount,
                "type": kind,
                "status": status,
                "effective_date": (anchor + timedelta(days=offset)).isoformat(),
                "notes": "Dado fictício para experimentar o FinSight.",
            },
            plan["keys"][index + 2],
        )
    summary = {
        name: len(request(opener, "/api/v1/" + name + "?limit=100")["items"])
        for name in ("accounts", "categories", "transactions")
    }
    request(opener, "/api/v1/auth/logout", {}, {"X-CSRF-Token": csrf()})
    save(local / "seed-result.json", summary)
    return summary
