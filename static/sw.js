const CACHE_NAME = 'lifestore-app-v4';
const ASSETS_TO_CACHE = [
    '/manifest.json',
    '/static/manifest.json',
    '/static/favicon.ico',
    '/static/favicon-32x32.png',
    '/static/favicon-16x16.png',
    '/static/img/icons/icon-192x192.png',
    '/static/img/icons/icon-512x512.png',
    '/static/img/icons/apple-touch-icon.png',
    '/static/img/lifestore_branding_dark.png',
    '/static/img/lifestore_branding_light.png',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(ASSETS_TO_CACHE))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cache) => {
                    if (cache !== CACHE_NAME) {
                        return caches.delete(cache);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    // Solo manejar peticiones GET
    if (event.request.method !== 'GET') {
        return;
    }

    const url = new URL(event.request.url);

    // Solo cachear activos estáticos reales (CSS, JS, imágenes, fuentes o en /static/)
    // NUNCA cachear páginas HTML dinámicas ni rutas del servidor
    const isStaticAsset = url.pathname.startsWith('/static/') || 
                          url.hostname.includes('cdnjs.cloudflare.com') || 
                          url.hostname.includes('cdn.jsdelivr.net') ||
                          /\.(png|jpg|jpeg|svg|ico|css|js|woff2?)$/i.test(url.pathname);

    if (!isStaticAsset) {
        // Peticiones de navegación / HTML / API van directo a la red (sin cache)
        return;
    }

    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }
            return fetch(event.request).then((response) => {
                if (response && response.status === 200 && response.type === 'basic') {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone).catch(() => {});
                    });
                }
                return response;
            });
        })
    );
});
