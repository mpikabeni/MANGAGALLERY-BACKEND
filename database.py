from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()


def init_database(app):
    db.init_app(app)
    migrate.init_app(app, db)
    return db
