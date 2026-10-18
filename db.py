"""Database layer: schema (3NF), constraints, validation, CRUD helpers.
Engine is chosen by DATABASE_URL (default: local SQLite file for easy testing).
  PostgreSQL: postgresql+psycopg2://user:pass@localhost/ledger
  MySQL     : mysql+pymysql://user:pass@localhost/ledger
"""
import os, datetime as dt
import pandas as pd
from sqlalchemy import (create_engine, event, MetaData, Table, Column, Integer, String,
                        Numeric, Date, ForeignKey, CheckConstraint, UniqueConstraint,
                        select, insert, update, delete)
from sqlalchemy.exc import IntegrityError, DataError

DB_URL = os.getenv("DATABASE_URL", "sqlite:///ledger.db")
engine = create_engine(DB_URL, future=True)

if DB_URL.startswith("sqlite"):          # SQLite ignores FKs unless told otherwise
    @event.listens_for(engine, "connect")
    def _fk_on(conn, _):
        cur = conn.cursor(); cur.execute("PRAGMA foreign_keys=ON"); cur.close()

md = MetaData()
N = lambda p, s: Numeric(p, s, asdecimal=False)

student = Table("student", md,
    Column("student_id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), nullable=False),
    Column("email", String(120), unique=True),
    Column("dob", Date),
    Column("status", String(15), nullable=False, server_default="ACTIVE"),   # current student status
    CheckConstraint("name <> ''", name="ck_student_name"),
    CheckConstraint("status IN ('ACTIVE','DROPPED','PASSED_OUT')", name="ck_student_status"))

board_result = Table("board_result", md,   # secondary + higher secondary
    Column("result_id", Integer, primary_key=True, autoincrement=True),
    Column("student_id", Integer, ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False),
    Column("level", String(20), nullable=False),
    Column("board_name", String(80), nullable=False),
    Column("passing_year", Integer, nullable=False),
    Column("percentage", N(5, 2), nullable=False),
    CheckConstraint("level IN ('SECONDARY','HIGHER_SECONDARY')", name="ck_board_level"),
    CheckConstraint("percentage BETWEEN 0 AND 100", name="ck_board_pct"),
    CheckConstraint("passing_year BETWEEN 1990 AND 2100", name="ck_board_year"),
    UniqueConstraint("student_id", "level", name="uq_board_student_level"))

semester = Table("semester", md,
    Column("sem_id", Integer, primary_key=True, autoincrement=True),
    Column("student_id", Integer, ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False),
    Column("sem_no", Integer, nullable=False),
    Column("academic_year", Integer, nullable=False),      # start year, 2022 = 2022-23
    Column("sgpa", N(4, 2), nullable=False),
    Column("result_status", String(10), nullable=False, server_default="PASS"),   # per-semester status
    CheckConstraint("result_status IN ('PASS','ATKT','FAIL','ONGOING')", name="ck_sem_status"),
    CheckConstraint("sem_no BETWEEN 1 AND 8", name="ck_sem_no"),
    CheckConstraint("sgpa BETWEEN 0 AND 10", name="ck_sem_sgpa"),
    CheckConstraint("academic_year BETWEEN 2000 AND 2100", name="ck_sem_year"),
    UniqueConstraint("student_id", "sem_no", name="uq_sem_student_no"))

gap_year = Table("gap_year", md,           # drop / gap years
    Column("gap_id", Integer, primary_key=True, autoincrement=True),
    Column("student_id", Integer, ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False),
    Column("start_year", Integer, nullable=False),
    Column("kind", String(10), nullable=False),
    Column("reason", String(200)),
    CheckConstraint("kind IN ('DROP','GAP')", name="ck_gap_kind"),
    CheckConstraint("start_year BETWEEN 2000 AND 2100", name="ck_gap_year"),
    UniqueConstraint("student_id", "start_year", name="uq_gap_student_year"))

subject = Table("subject", md,
    Column("subject_id", Integer, primary_key=True, autoincrement=True),
    Column("code", String(20), nullable=False, unique=True),
    Column("name", String(120), nullable=False),
    Column("sem_no", Integer, nullable=False),
    Column("kind", String(10), nullable=False),
    Column("credits", Integer, nullable=False),
    Column("max_marks", Integer, nullable=False),
    CheckConstraint("sem_no BETWEEN 1 AND 8", name="ck_subj_sem"),
    CheckConstraint("kind IN ('THEORY','LAB')", name="ck_subj_kind"),
    CheckConstraint("credits > 0", name="ck_subj_credits"),
    CheckConstraint("max_marks > 0", name="ck_subj_max"))

mark = Table("mark", md,
    Column("mark_id", Integer, primary_key=True, autoincrement=True),
    Column("student_id", Integer, ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False),
    Column("subject_id", Integer, ForeignKey("subject.subject_id", ondelete="RESTRICT"), nullable=False),
    Column("marks", N(6, 2), nullable=False),
    CheckConstraint("marks >= 0", name="ck_mark_nonneg"),
    UniqueConstraint("student_id", "subject_id", name="uq_mark_student_subject"))

organizer = Table("organizer", md,         # stops duplicate organiser strings
    Column("organizer_id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(120), nullable=False, unique=True))

activity = Table("activity", md,
    Column("activity_id", Integer, primary_key=True, autoincrement=True),
    Column("student_id", Integer, ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False),
    Column("organizer_id", Integer, ForeignKey("organizer.organizer_id", ondelete="SET NULL")),
    Column("title", String(150), nullable=False),
    Column("category", String(20), nullable=False),
    Column("scope", String(10)),           # INTERNAL / EXTERNAL, seminars only
    Column("activity_date", Date),
    Column("details", String(300)),
    CheckConstraint("category IN ('SEMINAR','CO_CURRICULAR','EXTRA_CURRICULAR')", name="ck_act_cat"),
    CheckConstraint("scope IS NULL OR scope IN ('INTERNAL','EXTERNAL')", name="ck_act_scope"),
    CheckConstraint("(category = 'SEMINAR' AND scope IS NOT NULL) OR (category <> 'SEMINAR' AND scope IS NULL)",
                    name="ck_act_seminar_scope"))

TABLES = {t.name: t for t in (student, board_result, semester, gap_year, subject, mark, organizer, activity)}
ORDER = ["student", "organizer", "subject", "board_result", "semester", "gap_year", "mark", "activity"]  # parents first


def init_db():
    md.create_all(engine)


# ---------- reading ----------
def table_df(name):
    t = TABLES[name]
    return pd.read_sql(select(t).order_by(list(t.primary_key.columns)[0]), engine)

def search_students(q):
    with engine.connect() as c:
        rows = c.execute(select(student).where(student.c.name.ilike(f"%{q}%")).order_by(student.c.name)).mappings().all()
    return [dict(r) for r in rows]

def df_for_student(name, sid):
    t = TABLES[name]
    return pd.read_sql(select(t).where(t.c.student_id == sid), engine)

def marks_for_student(sid):
    q = (select(subject.c.sem_no, subject.c.code, subject.c.name, subject.c.kind, subject.c.credits,
                subject.c.max_marks, mark.c.marks)
         .select_from(mark.join(subject, mark.c.subject_id == subject.c.subject_id))
         .where(mark.c.student_id == sid).order_by(subject.c.sem_no, subject.c.kind, subject.c.code))
    return pd.read_sql(q, engine)

def activity_df():
    q = (select(activity.c.activity_id, student.c.name.label("student"), activity.c.title, activity.c.category,
                activity.c.scope, organizer.c.name.label("organizer"), activity.c.activity_date, activity.c.details)
         .select_from(activity.join(student, activity.c.student_id == student.c.student_id)
                      .outerjoin(organizer, activity.c.organizer_id == organizer.c.organizer_id))
         .order_by(activity.c.activity_date))
    return pd.read_sql(q, engine)


# ---------- validation + writing ----------
def _clean(col, v):
    try:
        if v is None or pd.isna(v): return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str) and v.strip() == "": return None
    t = col.type
    if isinstance(t, Integer): return int(float(v))
    if isinstance(t, Numeric): return float(v)
    if isinstance(t, Date):
        if isinstance(v, (dt.datetime, pd.Timestamp)): return v.date()
        if isinstance(v, dt.date): return v
        return dt.date.fromisoformat(str(v)[:10])
    return str(v).strip()

def _validate(conn, tname, row):
    """Rules a single-table CHECK cannot express (these also guard spreadsheet edits)."""
    if tname == "mark":
        mx = conn.execute(select(subject.c.max_marks).where(subject.c.subject_id == row.get("subject_id"))).scalar()
        if mx is None: raise ValueError("unknown subject_id")
        if row["marks"] > mx: raise ValueError(f"marks {row['marks']} exceed the subject maximum {mx}")
    if tname == "semester":
        pass  # sgpa range is enforced by ck_sem_sgpa

def save_row(tname, row):
    """Insert-or-update one row. Returns None on success, else an error message."""
    t = TABLES[tname]; pk = list(t.primary_key.columns)[0].name
    try:
        vals = {c.name: _clean(c, row.get(c.name)) for c in t.columns if c.name in row}
        with engine.begin() as conn:
            _validate(conn, tname, vals)
            pk_val = vals.get(pk)
            if pk_val is not None and conn.execute(select(t.c[pk]).where(t.c[pk] == pk_val)).first():
                conn.execute(update(t).where(t.c[pk] == pk_val).values(**{k: v for k, v in vals.items() if k != pk}))
            else:
                conn.execute(insert(t).values(**{k: v for k, v in vals.items()
                                                 if not (v is None and (k == pk or t.c[k].server_default is not None))}))
        return None
    except (IntegrityError, DataError) as e:
        return f"Constraint violated: {str(e.orig).splitlines()[0]}"
    except (ValueError, TypeError) as e:
        return f"Invalid value: {e}"

def delete_row(tname, pk_value):
    t = TABLES[tname]; pk = list(t.primary_key.columns)[0]
    try:
        with engine.begin() as conn:
            conn.execute(delete(t).where(pk == int(pk_value)))
        return None
    except IntegrityError as e:
        return f"Cannot delete: {str(e.orig).splitlines()[0]}"
