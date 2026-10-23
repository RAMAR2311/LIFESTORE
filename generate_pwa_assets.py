import subprocess
import os
from PIL import Image

# 1. Creamos el SVG para el PWA Icon de alta gama (512x512)
pwa_svg_content = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body {
    width: 512px;
    height: 512px;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
</style>
</head>
<body>
  <svg width="512" height="512" viewBox="0 0 512 512" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <!-- Background Obsidian Metallic Gradient -->
      <radialGradient id="bgGrad" cx="50%" cy="38%" r="68%">
        <stop offset="0%" stop-color="#1e293b" />
        <stop offset="55%" stop-color="#0f172a" />
        <stop offset="100%" stop-color="#05080f" />
      </radialGradient>

      <!-- Outer Metallic Border -->
      <linearGradient id="borderGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#94a3b8" stop-opacity="0.8" />
        <stop offset="50%" stop-color="#334155" stop-opacity="0.3" />
        <stop offset="100%" stop-color="#cbd5e1" stop-opacity="0.7" />
      </linearGradient>

      <!-- Silver Metallic Apple Gradient -->
      <linearGradient id="appleSilver" x1="15%" y1="10%" x2="85%" y2="90%">
        <stop offset="0%" stop-color="#FFFFFF" />
        <stop offset="25%" stop-color="#F1F5F9" />
        <stop offset="50%" stop-color="#CBD5E1" />
        <stop offset="75%" stop-color="#94A3B8" />
        <stop offset="100%" stop-color="#64748B" />
      </linearGradient>

      <!-- Drop Shadows -->
      <filter id="iconGlow" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="10" stdDeviation="16" flood-color="#000000" flood-opacity="0.75" />
        <feDropShadow dx="0" dy="2" stdDeviation="4" flood-color="#FFFFFF" flood-opacity="0.25" />
      </filter>

      <filter id="textShadow" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="0.9" />
      </filter>
    </defs>

    <!-- App Icon Base Squircle -->
    <rect x="16" y="16" width="480" height="480" rx="105" fill="url(#bgGrad)" stroke="url(#borderGrad)" stroke-width="4.5" />

    <!-- Subtle Inner Glow Ring -->
    <rect x="21" y="21" width="470" height="470" rx="100" fill="none" stroke="#FFFFFF" stroke-opacity="0.08" stroke-width="1.5" />

    <!-- Apple Metallic Icon (Center) -->
    <g transform="translate(156, 82) scale(12.5)" filter="url(#iconGlow)">
      <!-- Leaf -->
      <path d="M15.22 6.13c.69-.84 1.15-2.01.99-3.18-1.01.04-2.2.66-2.91 1.5-.63.73-1.18 1.9-1.02 3.03 1.12.09 2.25-.51 2.94-1.35z"
            fill="url(#appleSilver)" />
      <!-- Body -->
      <path d="M16.14 7.62c-1.57-.09-2.91.9-3.67.9-.76 0-1.89-.86-3.12-.84-1.6.02-3.08.93-3.9 2.37-1.68 2.89-.43 7.17 1.2 9.51.8 1.14 1.74 2.41 2.99 2.36 1.21-.05 1.66-.77 3.12-.77 1.46 0 1.88.77 3.14.75 1.29-.02 2.11-1.16 2.89-2.31.91-1.32 1.29-2.6 1.31-2.67-.03-.01-2.52-.96-2.54-3.83-.02-2.39 1.95-3.53 2.05-3.6-1.12-1.64-2.85-1.82-3.47-1.87z"
            fill="url(#appleSilver)" />
    </g>

    <!-- Typography: LIFESTORE Brand -->
    <text x="256" y="410"
          text-anchor="middle"
          font-family="-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
          font-size="38"
          font-weight="800"
          letter-spacing="7"
          fill="#F8FAFC"
          filter="url(#textShadow)">LIFESTORE</text>

    <!-- Subtitle: CELULARES -->
    <text x="256" y="442"
          text-anchor="middle"
          font-family="-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
          font-size="14"
          font-weight="600"
          letter-spacing="9"
          fill="#94A3B8">CELULARES</text>
  </svg>
</body>
</html>
"""

# 2. Creamos el SVG para Favicon de alta definición (64x64, sin texto, isotipo puro con contraste absoluto)
favicon_svg_content = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body {
    width: 64px;
    height: 64px;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
</style>
</head>
<body>
  <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <!-- Base badge gradient for ultra sharp tab visibility -->
      <radialGradient id="tabBadgeGrad" cx="50%" cy="40%" r="65%">
        <stop offset="0%" stop-color="#1e293b" />
        <stop offset="100%" stop-color="#0a0f18" />
      </radialGradient>

      <!-- Silver Apple -->
      <linearGradient id="tabAppleSilver" x1="15%" y1="10%" x2="85%" y2="90%">
        <stop offset="0%" stop-color="#FFFFFF" />
        <stop offset="40%" stop-color="#E2E8F0" />
        <stop offset="80%" stop-color="#94A3B8" />
        <stop offset="100%" stop-color="#64748B" />
      </linearGradient>

      <linearGradient id="tabBorder" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#cbd5e1" stop-opacity="0.8" />
        <stop offset="100%" stop-color="#475569" stop-opacity="0.4" />
      </linearGradient>
    </defs>

    <!-- Dark metallic squircle badge with metallic edge -->
    <rect x="2" y="2" width="60" height="60" rx="15" fill="url(#tabBadgeGrad)" stroke="url(#tabBorder)" stroke-width="1.5" />

    <!-- Pure crisp metallic Apple (Fills 75% of badge, perfectly readable even at 16x16) -->
    <g transform="translate(18, 10) scale(1.75)">
      <!-- Leaf -->
      <path d="M15.22 6.13c.69-.84 1.15-2.01.99-3.18-1.01.04-2.2.66-2.91 1.5-.63.73-1.18 1.9-1.02 3.03 1.12.09 2.25-.51 2.94-1.35z"
            fill="url(#tabAppleSilver)" />
      <!-- Body -->
      <path d="M16.14 7.62c-1.57-.09-2.91.9-3.67.9-.76 0-1.89-.86-3.12-.84-1.6.02-3.08.93-3.9 2.37-1.68 2.89-.43 7.17 1.2 9.51.8 1.14 1.74 2.41 2.99 2.36 1.21-.05 1.66-.77 3.12-.77 1.46 0 1.88.77 3.14.75 1.29-.02 2.11-1.16 2.89-2.31.91-1.32 1.29-2.6 1.31-2.67-.03-.01-2.52-.96-2.54-3.83-.02-2.39 1.95-3.53 2.05-3.6-1.12-1.64-2.85-1.82-3.47-1.87z"
            fill="url(#tabAppleSilver)" />
    </g>
  </svg>
</body>
</html>
"""

temp_pwa = 'temp_pwa.html'
temp_fav = 'temp_fav.html'

with open(temp_pwa, 'w', encoding='utf-8') as f:
    f.write(pwa_svg_content)

with open(temp_fav, 'w', encoding='utf-8') as f:
    f.write(favicon_svg_content)

edge_exe = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

# Render 512x512 PWA Icon
out_512 = os.path.abspath('static/img/icons/icon-512x512.png')
cmd_512 = [
    edge_exe,
    '--headless',
    '--disable-gpu',
    '--window-size=512,512',
    '--hide-scrollbars',
    '--default-background-color=00000000',
    f'--screenshot={out_512}',
    'file:///' + os.path.abspath(temp_pwa).replace('\\', '/')
]
subprocess.run(cmd_512, check=True)
print('Generated 512x512 icon successfully.')

# Render Favicon 64x64
out_fav64 = os.path.abspath('temp_fav64.png')
cmd_fav = [
    edge_exe,
    '--headless',
    '--disable-gpu',
    '--window-size=64,64',
    '--hide-scrollbars',
    '--default-background-color=00000000',
    f'--screenshot={out_fav64}',
    'file:///' + os.path.abspath(temp_fav).replace('\\', '/')
]
subprocess.run(cmd_fav, check=True)
print('Generated 64x64 favicon temp successfully.')

# Resize using high-quality Lanczos with Pillow
im512 = Image.open(out_512)
# 192x192 PWA
im192 = im512.resize((192, 192), Image.Resampling.LANCZOS)
im192.save('static/img/icons/icon-192x192.png', 'PNG')
print('Generated 192x192 icon successfully.')

# Apple touch icon 180x180
im180 = im512.resize((180, 180), Image.Resampling.LANCZOS)
im180.save('static/img/icons/apple-touch-icon.png', 'PNG')
print('Generated apple-touch-icon.png successfully.')

# Multi-resolution ICO (16x16, 32x32, 48x48)
im_fav = Image.open(out_fav64)
fav16 = im_fav.resize((16, 16), Image.Resampling.LANCZOS)
fav32 = im_fav.resize((32, 32), Image.Resampling.LANCZOS)
fav48 = im_fav.resize((48, 48), Image.Resampling.LANCZOS)

fav32.save('static/favicon.ico', format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
fav32.save('static/favicon-32x32.png', 'PNG')
fav16.save('static/favicon-16x16.png', 'PNG')
print('Generated favicon.ico and favicon-32x32.png successfully.')

# Cleanup temp files
for p in [temp_pwa, temp_fav, out_fav64]:
    if os.path.exists(p):
        os.remove(p)
print('All icons generated with high precision.')
