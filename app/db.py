import sqlite3, os
DB = os.environ.get("SLOTH_DB", "data/sloth.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)
SCHEMA = """
create table if not exists subjects(id integer primary key, name text, syllabus text default '', units text default '[]');
create table if not exists lectures(id integer primary key, subject_id int, title text, transcript text default '', points text default '[]', board text default '[]');
create table if not exists pdf_notes(id integer primary key, subject_id int, title text, source_name text, source_path text, notes text default '');
create table if not exists cards(id integer primary key, subject_id int, lecture_id int, lab_id int, pdf_note_id int, manual_id int, kind text, q text, a text, extra text default '');
create table if not exists labs(id integer primary key, subject_id int, title text, code text, output text, output_note text default '', record text default '{}', reviewed int default 0);
create table if not exists lab_manuals(id integer primary key, subject_id int, student_name text, class_name text, branch text, institution text default '', semester text default '', roll_number text default '', experiment_count int, experiments text default '[]');
create table if not exists jobs(id integer primary key, kind text, ref_id int, status text, progress real, message text);
"""
def conn():
    c = sqlite3.connect(DB, check_same_thread=False); c.row_factory = sqlite3.Row; return c
def init():
    with conn() as c:
        c.executescript(SCHEMA)
        card_columns = {row["name"] for row in c.execute("pragma table_info(cards)")}
        if "manual_id" not in card_columns:
            c.execute("alter table cards add column manual_id int")
        if "pdf_note_id" not in card_columns:
            c.execute("alter table cards add column pdf_note_id int")
def q(sql, args=()):
    with conn() as c: return [dict(r) for r in c.execute(sql, args)]
def x(sql, args=()):
    with conn() as c: return c.execute(sql, args).lastrowid
