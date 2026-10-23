"""Punto de entrada para Gunicorn en producción: `gunicorn wsgi:app`.

Replica la inicialización que app.py hace solo cuando se ejecuta con
`python app.py` (crear tablas y el usuario admin inicial), porque Gunicorn
importa este módulo sin pasar por ese bloque __main__.
"""
import os
from app import create_app
from models import db, User
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    if not User.query.filter_by(email='admin@lifestore.com').first():
        db.session.add(User(
            nombre='Administrador LifeStore',
            email='admin@lifestore.com',
            password_hash=generate_password_hash('Admin123'),
            rol='admin'
        ))
        db.session.commit()
        print("[INFO] Usuario maestro 'admin@lifestore.com' fue creado automáticamente.")

if __name__ == '__main__':
    app.run()
