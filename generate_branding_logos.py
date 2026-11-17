import subprocess
import os
from PIL import Image

edge_exe = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

# HTML para Logo Oscuro (Para fondos oscuros/obsidian en navbar y login)
html_dark = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body {
    width: 1000px;
    height: 260px;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
</style>
</head>
<body>
  <svg width="1000" height="260" viewBox="0 0 1000 260" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <!-- Silver Metallic Apple Gradient -->
      <linearGradient id="appleSilver" x1="15%" y1="10%" x2="85%" y2="90%">
        <stop offset="0%" stop-color="#FFFFFF" />
        <stop offset="25%" stop-color="#F1F5F9" />
        <stop offset="50%" stop-color="#CBD5E1" />
        <stop offset="75%" stop-color="#94A3B8" />
        <stop offset="100%" stop-color="#64748B" />
      </linearGradient>

      <!-- Letters Silver Gradient -->
      <linearGradient id="lettersGradDark" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#FFFFFF" />
        <stop offset="60%" stop-color="#F8FAFC" />
        <stop offset="100%" stop-color="#E2E8F0" />
      </linearGradient>

      <filter id="subtleGleam" x="-10%" y="-10%" width="120%" height="120%">
        <feDropShadow dx="0" dy="2" stdDeviation="4" flood-color="#000000" flood-opacity="0.4" />
      </filter>
    </defs>

    <!-- Content Group -->
    <g transform="translate(40, 20)" filter="url(#subtleGleam)">
      <!-- Letters: LIFEST -->
      <text x="0" y="125"
            font-family="-apple-system, BlinkMacSystemFont, 'Montserrat', 'Inter', 'Segoe UI', sans-serif"
            font-size="120"
            font-weight="900"
            letter-spacing="5"
            fill="url(#lettersGradDark)">LIFEST</text>

      <!-- Apple Metallic Replacing 'O' -->
      <g transform="translate(545, 18) scale(5.8)">
        <!-- Leaf -->
        <path d="M15.22 6.13c.69-.84 1.15-2.01.99-3.18-1.01.04-2.2.66-2.91 1.5-.63.73-1.18 1.9-1.02 3.03 1.12.09 2.25-.51 2.94-1.35z"
              fill="url(#appleSilver)" />
        <!-- Body -->
        <path d="M16.14 7.62c-1.57-.09-2.91.9-3.67.9-.76 0-1.89-.86-3.12-.84-1.6.02-3.08.93-3.9 2.37-1.68 2.89-.43 7.17 1.2 9.51.8 1.14 1.74 2.41 2.99 2.36 1.21-.05 1.66-.77 3.12-.77 1.46 0 1.88.77 3.14.75 1.29-.02 2.11-1.16 2.89-2.31.91-1.32 1.29-2.6 1.31-2.67-.03-.01-2.52-.96-2.54-3.83-.02-2.39 1.95-3.53 2.05-3.6-1.12-1.64-2.85-1.82-3.47-1.87z"
              fill="url(#appleSilver)" />
      </g>

      <!-- Letters: RE -->
      <text x="680" y="125"
            font-family="-apple-system, BlinkMacSystemFont, 'Montserrat', 'Inter', 'Segoe UI', sans-serif"
            font-size="120"
            font-weight="900"
            letter-spacing="5"
            fill="url(#lettersGradDark)">RE</text>

      <!-- Subtitle: CELULARES & TECNOLOGÍA -->
      <text x="6" y="185"
            font-family="-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif"
            font-size="30"
            font-weight="700"
            letter-spacing="18"
            fill="#CBD5E1">CELULARES &amp; TECNOLOGÍA</text>
    </g>
  </svg>
</body>
</html>
"""

# HTML para Logo Claro (Para fondos claros)
html_light = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body {
    width: 1000px;
    height: 260px;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
</style>
</head>
<body>
  <svg width="1000" height="260" viewBox="0 0 1000 260" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <!-- Silver Metallic Apple Gradient -->
      <linearGradient id="appleSilverLight" x1="15%" y1="10%" x2="85%" y2="90%">
        <stop offset="0%" stop-color="#64748B" />
        <stop offset="35%" stop-color="#475569" />
        <stop offset="70%" stop-color="#334155" />
        <stop offset="100%" stop-color="#0F172A" />
      </linearGradient>

      <!-- Letters Charcoal Gradient -->
      <linearGradient id="lettersGradLight" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#0F172A" />
        <stop offset="100%" stop-color="#1E293B" />
      </linearGradient>
    </defs>

    <!-- Content Group -->
    <g transform="translate(40, 20)">
      <!-- Letters: LIFEST -->
      <text x="0" y="125"
            font-family="-apple-system, BlinkMacSystemFont, 'Montserrat', 'Inter', 'Segoe UI', sans-serif"
            font-size="120"
            font-weight="900"
            letter-spacing="5"
            fill="url(#lettersGradLight)">LIFEST</text>

      <!-- Apple Metallic Replacing 'O' -->
      <g transform="translate(545, 18) scale(5.8)">
        <!-- Leaf -->
        <path d="M15.22 6.13c.69-.84 1.15-2.01.99-3.18-1.01.04-2.2.66-2.91 1.5-.63.73-1.18 1.9-1.02 3.03 1.12.09 2.25-.51 2.94-1.35z"
              fill="url(#appleSilverLight)" />
        <!-- Body -->
        <path d="M16.14 7.62c-1.57-.09-2.91.9-3.67.9-.76 0-1.89-.86-3.12-.84-1.6.02-3.08.93-3.9 2.37-1.68 2.89-.43 7.17 1.2 9.51.8 1.14 1.74 2.41 2.99 2.36 1.21-.05 1.66-.77 3.12-.77 1.46 0 1.88.77 3.14.75 1.29-.02 2.11-1.16 2.89-2.31.91-1.32 1.29-2.6 1.31-2.67-.03-.01-2.52-.96-2.54-3.83-.02-2.39 1.95-3.53 2.05-3.6-1.12-1.64-2.85-1.82-3.47-1.87z"
              fill="url(#appleSilverLight)" />
      </g>

      <!-- Letters: RE -->
      <text x="680" y="125"
            font-family="-apple-system, BlinkMacSystemFont, 'Montserrat', 'Inter', 'Segoe UI', sans-serif"
            font-size="120"
            font-weight="900"
            letter-spacing="5"
            fill="url(#lettersGradLight)">RE</text>

      <!-- Subtitle: CELULARES & TECNOLOGÍA -->
      <text x="6" y="185"
            font-family="-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif"
            font-size="30"
            font-weight="700"
            letter-spacing="18"
            fill="#475569">CELULARES &amp; TECNOLOGÍA</text>
    </g>
  </svg>
</body>
</html>
"""

with open('temp_dark.html', 'w', encoding='utf-8') as f:
    f.write(html_dark)
with open('temp_light.html', 'w', encoding='utf-8') as f:
    f.write(html_light)

out_dark = os.path.abspath('static/img/lifestore_branding_dark.png')
out_light = os.path.abspath('static/img/lifestore_branding_light.png')

cmd_dark = [
    edge_exe,
    '--headless',
    '--disable-gpu',
    '--window-size=1000,260',
    '--hide-scrollbars',
    '--default-background-color=00000000',
    f'--screenshot={out_dark}',
    'file:///' + os.path.abspath('temp_dark.html').replace('\\', '/')
]
subprocess.run(cmd_dark, check=True)

cmd_light = [
    edge_exe,
    '--headless',
    '--disable-gpu',
    '--window-size=1000,260',
    '--hide-scrollbars',
    '--default-background-color=00000000',
    f'--screenshot={out_light}',
    'file:///' + os.path.abspath('temp_light.html').replace('\\', '/')
]
subprocess.run(cmd_light, check=True)

# Also generate cropped version without extra margin
for p in [out_dark, out_light]:
    im = Image.open(p)
    bbox = im.getbbox()
    if bbox:
        # Pad with 10px
        pad = 10
        b_padded = (max(0, bbox[0]-pad), max(0, bbox[1]-pad), min(im.width, bbox[2]+pad), min(im.height, bbox[3]+pad))
        cropped = im.crop(b_padded)
        cropped.save(p, 'PNG')

# Also duplicate to lifestore_logo.png
im_light = Image.open(out_light)
im_light.save('static/img/lifestore_logo.png', 'PNG')

for f in ['temp_dark.html', 'temp_light.html']:
    if os.path.exists(f):
        os.remove(f)

print('Branding logos generated successfully with transparent alpha backgrounds!')
