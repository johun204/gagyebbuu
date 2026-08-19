const CACHE_NAME = 'gagye-bbu-cache-v3';
const STATIC_URLS = [
    '/',
    '/home',
    '/calendar',
    '/transactions',
    '/settings',
    '/search',
    '/static/manifest.json',
    '/static/icon-192.png',
    '/static/icon-512.png',
    'https://cdn.jsdelivr.net/npm/chart.js',
    'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_URLS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.map(key => {
                if (key !== CACHE_NAME) return caches.delete(key);
            })
        ))
    );
    self.clients.claim();
});

self.addEventListener('push', event => {
    let data = { title: '가계쀼', body: '' };
    try { data = event.data.json(); } catch (e) {
        if (event.data) data.body = event.data.text();
    }
    event.waitUntil(
        self.registration.showNotification(data.title || '가계쀼', {
            body: data.body || '',
            icon: '/static/icon-192.png',
            badge: '/static/icon-192.png',
            data: { url: data.url || '/home' }
        })
    );
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/home';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
            for (const client of clientList) {
                if ('focus' in client) return client.focus();
            }
            if (clients.openWindow) return clients.openWindow(url);
        })
    );
});

self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;
    
    // API 통신은 캐시하지 않고 항상 네트워크 요청
    if (event.request.url.includes('/api/')) {
        return;
    }
    
    event.respondWith(
        fetch(event.request)
            .then(response => {
                let resClone = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, resClone));
                return response;
            })
            .catch(() => {
                // 오프라인 상태 시 캐시된 화면 및 스켈레톤을 렌더링하도록 맵핑
                return caches.match(event.request).then(res => {
                    if (res) return res;
                    if (event.request.mode === 'navigate') {
                        return caches.match('/');
                    }
                });
            })
    );
});