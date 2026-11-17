from app import create_app
from models import db

def run():
    app = create_app()
    with app.app_context():
        try:
            db.session.execute(db.text("ALTER TABLE sales ADD COLUMN provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL;"))
            db.session.commit()
            print("Column provider_id added successfully to sales table.")
        except Exception as e:
            db.session.rollback()
            print(f"Error or column already exists: {e}")

if __name__ == '__main__':
    run()
