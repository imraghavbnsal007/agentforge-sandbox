from app.services.sql_analyzer import (
    analyze_sql,
    deterministic_findings,
    schema_summary,
    schema_to_json,
)

DDL = """
--DDL FILE
-- comment with CREATE TABLE fake (x int);

DROP TABLE booking CASCADE CONSTRAINTS;
DROP VIEW booking_receipt;
DROP VIEW party_book_4;

CREATE TABLE booking (
    bookingid    NUMBER(7) NOT NULL,
    no_of_people NUMBER(10) NOT NULL,
    custid       NUMBER(7) NOT NULL,
    waiterid     NUMBER(7) NOT NULL
);

ALTER TABLE booking ADD CONSTRAINT booking_ppl_ck_1 CHECK ( no_of_people <= 6 );
ALTER TABLE booking ADD CONSTRAINT booking_pk PRIMARY KEY ( bookingid );

CREATE TABLE customer (
    custid  NUMBER(7) NOT NULL,
    email   VARCHAR2(30) NOT NULL
);

ALTER TABLE customer ADD CONSTRAINT customer_pk PRIMARY KEY ( custid );

CREATE TABLE "Table" (
    tableid  NUMBER(7) NOT NULL,
    location VARCHAR2(10) NOT NULL
);

CREATE TABLE orphan (
    orphanid NUMBER(7) NOT NULL,
    parentid NUMBER(7) NOT NULL
);

ALTER TABLE booking
    ADD CONSTRAINT booking_customer_fk FOREIGN KEY ( custid )
        REFERENCES customer ( custid );

CREATE INDEX booking_time_idx ON booking ( bookingid );

CREATE OR REPLACE VIEW active_bookings AS SELECT * FROM booking;

CREATE OR REPLACE PROCEDURE charge_penalty AS BEGIN NULL; END;

CREATE TRIGGER booking_audit AFTER INSERT ON booking BEGIN NULL; END;
"""


def test_full_ddl_parsing():
    schema = analyze_sql({"Project_ddl.sql": DDL})
    assert schema is not None
    names = [t.name for t in schema.tables]
    assert names == ["booking", "customer", "Table", "orphan"]

    booking = schema.table("booking")
    assert booking.primary_key == ["bookingid"]
    assert len(booking.columns) == 4
    assert booking.checks[0].name == "booking_ppl_ck_1"
    assert "no_of_people <= 6" in booking.checks[0].expression
    fk = booking.foreign_keys[0]
    assert (fk.columns, fk.ref_table, fk.ref_columns) == (["custid"], "customer", ["custid"])

    assert schema.table('"Table"') is not None or schema.table("Table") is not None
    assert [i["name"] for i in schema.indexes] == ["booking_time_idx"]
    assert [v["name"] for v in schema.views] == ["active_bookings"]
    assert [p["name"] for p in schema.procedures] == ["charge_penalty"]
    assert [t["name"] for t in schema.triggers] == ["booking_audit"]
    # Dropped views with no CREATE anywhere are flagged.
    assert schema.dropped_views_not_created == ["booking_receipt", "party_book_4"]


def test_schema_summary_and_json():
    schema = analyze_sql({"ddl.sql": DDL})
    text = schema_summary(schema)
    assert "4 tables" in text
    assert "NO PRIMARY KEY" in text  # Table + orphan lack PKs
    assert "booking_ppl_ck_1" in text
    data = schema_to_json(schema)
    assert data["tables"][0]["name"] == "booking"
    assert data["dropped_views_not_created"] == ["booking_receipt", "party_book_4"]


def test_deterministic_findings_reference_real_files():
    schema = analyze_sql({"ddl.sql": DDL})
    findings = deterministic_findings(schema)
    titles = [f["title"] for f in findings]
    assert any("Table" in t and "no primary key" in t for t in titles)
    assert any("orphan" in t and "no primary key" in t for t in titles)
    # orphan.parentid looks like an FK but has none.
    assert any("parentid" in t for t in titles)
    # waiterid on booking has no FK in this trimmed DDL.
    assert any("waiterid" in t for t in titles)
    assert any("booking_receipt" in t for t in titles)
    for f in findings:
        assert f["related_files"], f
        assert f["confidence"] in ("high", "medium", "low")
        assert f["effort"] in ("small", "medium", "large")
        assert f["reasoning"]


def test_no_sql_returns_none():
    assert analyze_sql({}) is None
    assert analyze_sql({"notes.sql": "-- just comments"}) is None
