from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql, mysql
import db
for name, d in (("postgresql", postgresql.dialect()), ("mysql", mysql.dialect())):
    with open(f"schema_{name}.sql", "w") as f:
        for n in db.ORDER:
            f.write(str(CreateTable(db.TABLES[n]).compile(dialect=d)).strip() + ";\n\n")
print("wrote schema_postgresql.sql, schema_mysql.sql")
