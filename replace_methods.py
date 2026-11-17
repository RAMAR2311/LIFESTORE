import os

dir_path = r"c:\Users\Marlo\Desktop\MARCA BLANCA\templates"

reps = [
    (
        '''<option value="efectivo">💵 Efectivo</option>\n                    <option value="nequi">📱 Nequi</option>\n                    <option value="bancolombia">🏦 Bancolombia</option>\n                    <option value="daviplata">📱 Daviplata</option>''',
        '''<option value="addi">🛍️ Addi</option>\n                    <option value="sitecredito">💳 Sitecredito</option>\n                    <option value="bancolombia">🏦 Bancolombia</option>\n                    <option value="davivienda">🏦 Davivienda</option>\n                    <option value="efectivo">💵 Efectivo</option>\n                    <option value="tarjeta_credito">💳 Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo">Efectivo</option>\n                                                            <option value="nequi">Nequi</option>\n                                                            <option value="bancolombia">Bancolombia</option>\n                                                            <option value="daviplata">Daviplata</option>''',
        '''<option value="addi">Addi</option>\n                                                            <option value="sitecredito">Sitecredito</option>\n                                                            <option value="bancolombia">Bancolombia</option>\n                                                            <option value="davivienda">Davivienda</option>\n                                                            <option value="efectivo">Efectivo</option>\n                                                            <option value="tarjeta_credito">Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo" selected>Efectivo (Caja)</option>\n                                <option value="transferencia">Transferencia (Bancolombia / Nequi / Daviplata)</option>''',
        '''<option value="addi">Addi</option>\n                                <option value="sitecredito">Sitecredito</option>\n                                <option value="bancolombia">Bancolombia</option>\n                                <option value="davivienda">Davivienda</option>\n                                <option value="efectivo" selected>Efectivo (Caja)</option>\n                                <option value="tarjeta_credito">Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo" selected>Efectivo (Caja)</option>\n                        <option value="transferencia">Transferencia (Bancolombia / Nequi / Daviplata)</option>''',
        '''<option value="addi">Addi</option>\n                        <option value="sitecredito">Sitecredito</option>\n                        <option value="bancolombia">Bancolombia</option>\n                        <option value="davivienda">Davivienda</option>\n                        <option value="efectivo" selected>Efectivo (Caja)</option>\n                        <option value="tarjeta_credito">Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo">Efectivo</option>\n                                <option value="transferencia">Transferencia</option>\n                                <option value="nequi">Nequi</option>\n                                <option value="bancolombia">Bancolombia</option>\n                                <option value="daviplata">Daviplata</option>''',
        '''<option value="addi">Addi</option>\n                                <option value="sitecredito">Sitecredito</option>\n                                <option value="bancolombia">Bancolombia</option>\n                                <option value="davivienda">Davivienda</option>\n                                <option value="efectivo">Efectivo</option>\n                                <option value="tarjeta_credito">Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo">💵 Efectivo Físico</option>\n                                <option value="nequi">📱 Nequi</option>\n                                <option value="bancolombia">🏦 Bancolombia</option>\n                                <option value="daviplata">📱 Daviplata</option>''',
        '''<option value="addi">🛍️ Addi</option>\n                                <option value="sitecredito">💳 Sitecredito</option>\n                                <option value="bancolombia">🏦 Bancolombia</option>\n                                <option value="davivienda">🏦 Davivienda</option>\n                                <option value="efectivo">💵 Efectivo Físico</option>\n                                <option value="tarjeta_credito">💳 Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo">💵 Efectivo Físico</option>\n                            <option value="nequi">📱 Nequi</option>\n                            <option value="bancolombia">🏦 Bancolombia</option>\n                            <option value="daviplata">📱 Daviplata</option>''',
        '''<option value="addi">🛍️ Addi</option>\n                            <option value="sitecredito">💳 Sitecredito</option>\n                            <option value="bancolombia">🏦 Bancolombia</option>\n                            <option value="davivienda">🏦 Davivienda</option>\n                            <option value="efectivo">💵 Efectivo Físico</option>\n                            <option value="tarjeta_credito">💳 Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo" {% if abono.metodo_pago == 'efectivo' %}selected{% endif %}>💵 Efectivo Físico</option>\n                            <option value="nequi" {% if abono.metodo_pago == 'nequi' %}selected{% endif %}>📱 Nequi</option>\n                            <option value="bancolombia" {% if abono.metodo_pago == 'bancolombia' %}selected{% endif %}>🏦 Bancolombia</option>\n                            <option value="daviplata" {% if abono.metodo_pago == 'daviplata' %}selected{% endif %}>📱 Daviplata</option>''',
        '''<option value="addi" {% if abono.metodo_pago == 'addi' %}selected{% endif %}>🛍️ Addi</option>\n                            <option value="sitecredito" {% if abono.metodo_pago == 'sitecredito' %}selected{% endif %}>💳 Sitecredito</option>\n                            <option value="bancolombia" {% if abono.metodo_pago == 'bancolombia' %}selected{% endif %}>🏦 Bancolombia</option>\n                            <option value="davivienda" {% if abono.metodo_pago == 'davivienda' %}selected{% endif %}>🏦 Davivienda</option>\n                            <option value="efectivo" {% if abono.metodo_pago == 'efectivo' %}selected{% endif %}>💵 Efectivo Físico</option>\n                            <option value="tarjeta_credito" {% if abono.metodo_pago == 'tarjeta_credito' %}selected{% endif %}>💳 Tarjeta Crédito</option>'''
    ),
    (
        '''<option value="efectivo">💵 Efectivo directo a Caja</option>\n                                                            <option value="nequi">📱 Nequi</option>\n                                                            <option value="bancolombia">🏦 Bancolombia</option>\n                                                            <option value="daviplata">📱 Daviplata</option>''',
        '''<option value="addi">🛍️ Addi</option>\n                                                            <option value="sitecredito">💳 Sitecredito</option>\n                                                            <option value="bancolombia">🏦 Bancolombia</option>\n                                                            <option value="davivienda">🏦 Davivienda</option>\n                                                            <option value="efectivo">💵 Efectivo directo a Caja</option>\n                                                            <option value="tarjeta_credito">💳 Tarjeta Crédito</option>'''
    ),
    (
        '''const METODOS_DISPONIBLES = [\n        { value: 'efectivo', label: '💵 Efectivo' },\n        { value: 'nequi', label: '📱 Nequi' },\n        { value: 'bancolombia', label: '🏦 Bancolombia' },\n        { value: 'daviplata', label: '📱 Daviplata' }\n    ];''',
        '''const METODOS_DISPONIBLES = [\n        { value: 'addi', label: '🛍️ Addi' },\n        { value: 'sitecredito', label: '💳 Sitecredito' },\n        { value: 'bancolombia', label: '🏦 Bancolombia' },\n        { value: 'davivienda', label: '🏦 Davivienda' },\n        { value: 'efectivo', label: '💵 Efectivo' },\n        { value: 'tarjeta_credito', label: '💳 Tarjeta Crédito' }\n    ];'''
    )
]

for root, dirs, files in os.walk(dir_path):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            original = content
            for r1, r2 in reps:
                content = content.replace(r1, r2)
            if original != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Updated {filepath}")

routes_path = r"c:\Users\Marlo\Desktop\MARCA BLANCA\routes"
for root, dirs, files in os.walk(routes_path):
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            original = content
            content = content.replace("['transferencia', 'nequi', 'bancolombia', 'daviplata']", "['addi', 'sitecredito', 'bancolombia', 'davivienda', 'tarjeta_credito', 'transferencia']")
            if original != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Updated backend {filepath}")
