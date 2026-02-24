"""
Run database migration to add new columns to documents and group_messages tables.
Execute: python run_migration.py
Supports MySQL. For SQLite, the app will run migrate_group_messages_sqlite() on startup.
"""
import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv

load_dotenv()


def _get_mysql_conn():
    database_url = os.getenv("DATABASE_URL")
    if not database_url or "mysql" not in database_url:
        return None, None
    try:
        import pymysql
    except ImportError:
        return None, None
    url = database_url.replace("mysql+pymysql://", "")
    if "@" not in url:
        return None, None
    auth, rest = url.split("@")
    user, password = auth.split(":", 1)
    host_db = rest.split("/")
    host_port = host_db[0]
    dbname = host_db[1].split("?")[0] if len(host_db) > 1 else "ai_study_assistant"
    host, port = (host_port.split(":") + ["3306"])[:2]
    try:
        conn = pymysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=dbname,
        )
        return conn, None
    except Exception as e:
        return None, str(e)


def migrate_documents(conn):
    """Add page_data_path and total_pages to documents if missing."""
    cursor = conn.cursor()
    cursor.execute("SHOW COLUMNS FROM documents LIKE 'page_data_path'")
    if cursor.fetchone():
        return True
    try:
        cursor.execute("""
            ALTER TABLE documents
            ADD COLUMN page_data_path VARCHAR(500) NULL AFTER content_path,
            ADD COLUMN total_pages INT NULL AFTER page_data_path
        """)
        conn.commit()
        print("Documents: Added page_data_path and total_pages.")
    except Exception as e:
        conn.rollback()
        print(f"Documents migration: {e}")
        return False
    return True


def _column_exists(cursor, table, column):
    cursor.execute("SHOW COLUMNS FROM {} LIKE %s".format(table), (column,))
    return cursor.fetchone() is not None


def migrate_group_messages(conn):
    """Ensure group_messages has sender_type, message_type, file_path, file_name, message_status, group_file_id. Backfill old rows."""
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW TABLES LIKE 'group_messages'")
        if not cursor.fetchone():
            conn.commit()
            return True  # Table created by SQLAlchemy create_all
    except Exception:
        conn.rollback()
        return True

    added = []
    # Add columns one by one (ignore if exists)
    columns_to_add = [
        ("sender_type", "VARCHAR(20) NOT NULL DEFAULT 'user'"),
        ("message_type", "VARCHAR(20) NOT NULL DEFAULT 'text'"),
        ("file_path", "VARCHAR(500) NULL"),
        ("file_name", "VARCHAR(255) NULL"),
        ("message_status", "VARCHAR(20) NOT NULL DEFAULT 'sent'"),
        ("group_file_id", "INT NULL"),
    ]
    for col_name, col_def in columns_to_add:
        if not _column_exists(cursor, "group_messages", col_name):
            try:
                cursor.execute(
                    "ALTER TABLE group_messages ADD COLUMN {} {}".format(col_name, col_def)
                )
                added.append(col_name)
            except Exception as e:
                conn.rollback()
                print(f"group_messages: failed to add {col_name}: {e}")
                return False
    if added:
        conn.commit()
        print("group_messages: Added columns:", ", ".join(added))

    # Backfill: set sender_type/message_type for old AI messages
    try:
        cursor.execute(
            "UPDATE group_messages SET sender_type = 'ai', message_type = 'ai' WHERE user_id IS NULL AND (sender_type IS NULL OR sender_type = '' OR message_type IS NULL OR message_type = '')"
        )
        if cursor.rowcount:
            conn.commit()
            print("group_messages: Backfilled sender_type/message_type for AI messages.")
        cursor.execute(
            "UPDATE group_messages SET message_type = COALESCE(NULLIF(message_type, ''), 'text') WHERE message_type IS NULL OR message_type = ''"
        )
        if cursor.rowcount:
            conn.commit()
        cursor.execute(
            "UPDATE group_messages SET message_status = COALESCE(NULLIF(message_status, ''), 'sent') WHERE message_status IS NULL OR message_status = ''"
        )
        if cursor.rowcount:
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"group_messages backfill: {e}")

    # Add FK for group_file_id if column was just added and table group_documents exists
    if "group_file_id" in added:
        try:
            cursor.execute("SHOW TABLES LIKE 'group_documents'")
            if cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE group_messages ADD CONSTRAINT fk_group_message_file "
                    "FOREIGN KEY (group_file_id) REFERENCES group_documents(id) ON DELETE SET NULL"
                )
                conn.commit()
        except Exception:
            conn.rollback()
    return True


def run_migration():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in .env")
        return False

    if "mysql" in database_url:
        conn, err = _get_mysql_conn()
        if err:
            print(f"ERROR: MySQL connection failed: {err}")
            return False
        if not conn:
            print("ERROR: Could not parse DATABASE_URL for MySQL")
            return False
        try:
            migrate_documents(conn)
            migrate_group_messages(conn)
            print("Migration completed successfully.")
            return True
        finally:
            conn.close()
    else:
        print("Note: Only MySQL migrations run from this script. For SQLite, the app migrates group_messages on startup.")
        return True


if __name__ == "__main__":
    success = run_migration()
    exit(0 if success else 1)
