"""Synthetic parser contracts; no database, files, HTTP server or financial posting."""

import hashlib
from dataclasses import replace
from datetime import date
from decimal import Decimal
from time import perf_counter

import pytest

from app.imports.csv_parser import (
    MAX_BYTES,
    MAX_ROWS,
    CsvLayout,
    CsvRejected,
    normalize_rows,
    read_csv,
)

OPENING = date(2026, 1, 1)
LAYOUT = CsvLayout(0, 1, "day-first", "decimal-comma", amount_column=2)


def test_utf8_quotes_bom_explicit_formats_and_exact_signed_money():
    content = (
        "\ufeffData;Descrição;Valor\r\n"
        '02/01/2026;"Compra, item; sintético";"-1.234,56"\r\n'
        "03/01/2026;Receita sintética;+1234,50\r\n"
    ).encode()
    document = read_csv(content)
    assert document.delimiter == ";"
    assert document.headers == ("Data", "Descrição", "Valor")
    assert document.checksum == hashlib.sha256(content).hexdigest()
    rows = normalize_rows(document, LAYOUT, opening_date=OPENING)
    assert all(row.valid for row in rows)
    assert (
        rows[0].row_number,
        rows[0].transaction_date,
        rows[0].description,
        rows[0].amount,
        rows[0].type,
    ) == (2, date(2026, 1, 2), "Compra, item; sintético", Decimal("1234.56"), "expense")
    assert (rows[1].amount, rows[1].type) == (Decimal("1234.50"), "income")
    assert "sintético" not in repr(document) + repr(rows[0])
    dot = read_csv(
        b'date,description,amount\n2026-01-02,"Synthetic, income",1234.56\n'
        b"2026-01-03,No rounding,1.234\n"
    )
    normalized = normalize_rows(
        dot, replace(LAYOUT, date_format="iso", money_format="decimal-dot"), opening_date=OPENING
    )
    assert normalized[0].valid and normalized[0].amount == Decimal("1234.56")
    assert normalized[1].errors == ("invalid_amount",)
    ambiguous = read_csv(b"Data;Description;Value\n02/01/2026;Synthetic;1.234\n")
    assert normalize_rows(ambiguous, LAYOUT, opening_date=OPENING)[0].amount == Decimal("1234.00")
    assert normalize_rows(
        ambiguous, replace(LAYOUT, money_format="decimal-dot"), opening_date=OPENING
    )[0].errors == ("invalid_amount",)


def test_split_columns_and_row_errors_preserve_records_for_manual_review():
    document = read_csv(
        (
            "Data;Descrição;Débito;Crédito;ID\n"
            "02/01/2026;Compra;10,20;;synthetic-1\n"
            "03/01/2026;Receita;;20,00;synthetic-2\n"
            "03/01/2026;Ambos;1,00;2,00;\n"
            "03/01/2026;Negativo;-1,00;;\n"
            "03/01/2026;Zero;0;0;\n"
            "01/01/2026;Abertura;1;;\n"
            "31/02/2026;Data inválida;1;;\n"
            '03/01/2026;"Linha\nquebrada";1;;\n'
            "03/01/2026;ID inválido;1;;\u202e\n"
            "03/01/2026;Campos faltantes\n"
            "03/01/2026;Extra;1;;;extra\n"
        ).encode()
    )
    layout = CsvLayout(
        0, 1, "day-first", "decimal-comma", debit_column=2, credit_column=3, external_id_column=4
    )
    rows = normalize_rows(document, layout, opening_date=OPENING)
    assert len(rows) == 11
    assert [(r.amount, r.type, r.external_id) for r in rows[:2]] == [
        (Decimal("10.20"), "expense", "synthetic-1"),
        (Decimal("20.00"), "income", "synthetic-2"),
    ]
    assert [r.errors for r in rows[2:]] == [("invalid_amount",)] * 3 + [
        ("date_not_after_opening",),
        ("invalid_date",),
        ("invalid_description",),
        ("invalid_external_id",),
        ("column_count",),
        ("column_count",),
    ]
    invalid_values = [
        "0",
        "-0,00",
        "NaN",
        "Infinity",
        "1e2",
        "1,234",
        "R$ 1,00",
        "10000000000000",
        "1.23,45",
    ]
    for value in invalid_values:
        row = normalize_rows(
            read_csv(f"Data;Descrição;Valor\n02/01/2026;Synthetic;{value}\n".encode()),
            LAYOUT,
            opening_date=OPENING,
        )[0]
        assert row.errors == ("invalid_amount",) and row.amount is None
    # Identical real purchases must remain distinct; duplicate review comes in a later service.
    identical = read_csv(
        b"Date;Description;Amount\n02/01/2026;Synthetic;10\n02/01/2026;Synthetic;10\n"
    )
    assert len(normalize_rows(identical, LAYOUT, opening_date=OPENING)) == 2


def test_structural_limits_mapping_and_diagnostics_never_echo_source():
    cases = [
        (b"", "empty_file"),
        (b" \n", "empty_file"),
        (b"a;b;c\n", "empty_data"),
        (b"a;b;c\n\xff", "unsupported_encoding"),
        (b"a;b;c\nsecret\x00payload", "invalid_control_character"),
        (b'a;b;c\n"secret payload', "malformed_csv"),
        (b"a; A ;c\nx;y;z", "invalid_headers"),
        (b"a;;c\nx;y;z", "invalid_headers"),
        (b"x" * (MAX_BYTES + 1), "file_too_large"),
        (b"a;b;c\n" + b"x" * 4097, "row_too_large"),
        (b"a;b;c\n" + b"x;y;z\n" * (MAX_ROWS + 1), "too_many_rows"),
        (b"a;b;c\n" + b";".join([b"x"] * 33), "row_too_large"),
    ]
    for content, code in cases:
        with pytest.raises(CsvRejected) as failure:
            read_csv(content, delimiter=";")
        assert str(failure.value) == code and "secret" not in repr(failure.value)
    with pytest.raises(CsvRejected, match="^choose_delimiter$"):
        read_csv(b"Original,date;Description;Amount\n02/01/2026;Synthetic;1")
    assert (
        read_csv(
            b"Original,date;Description;Amount\n02/01/2026;Synthetic;1", delimiter=";"
        ).headers[0]
        == "Original,date"
    )
    document = read_csv(b"Date;Description;Amount\n02/01/2026;Synthetic;1")
    for layout in [
        replace(LAYOUT, date_column=True),
        replace(LAYOUT, date_column=3),
        replace(LAYOUT, description_column=0),
        replace(LAYOUT, amount_column=None),
        replace(LAYOUT, debit_column=2),
        replace(LAYOUT, money_format="guess"),
    ]:
        with pytest.raises(CsvRejected):
            normalize_rows(document, layout, opening_date=OPENING)


def test_five_thousand_rows_are_bounded_and_exact_without_database_work():
    content = b"Date;Description;Amount\n" + b"02/01/2026;Synthetic item;-1234,56\n" * MAX_ROWS
    start = perf_counter()
    document = read_csv(content)
    rows = normalize_rows(document, LAYOUT, opening_date=OPENING)
    elapsed = perf_counter() - start
    assert len(rows) == MAX_ROWS and all(row.valid for row in rows)
    assert sum((row.amount for row in rows), Decimal(0)) == Decimal("6172800.00")
    print(f"Synthetic parser: {MAX_ROWS} rows in {elapsed:.3f}s; excludes HTTP, DB and UI")
