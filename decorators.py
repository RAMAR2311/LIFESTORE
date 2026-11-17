from functools import wraps
from flask import abort
from flask_login import current_user

def admin_required(f):
    """
    Decorador para proteger rutas exclusivas del administrador.
    Lanza un error 403 Forbidden si el usuario actual no tiene el rol de administrador.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.rol != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def bodega_required(f):
    """
    Decorador para proteger rutas exclusivas del encargado de bodega.
    (Opcionalmente, los administradores también pueden acceder si se desea)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.rol not in ['bodega', 'admin']:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def admin_or_bodega_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.rol not in ['admin', 'bodega']:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def any_bodega_required(f):
    """
    Permite acceso tanto al perfil 'bodega' como al 'vendedor_bodega' (y admin).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.rol not in ['admin', 'bodega', 'vendedor_bodega']:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
