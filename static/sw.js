const CACHE_NAME = 'gagye-bbu-cache-v4';
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

    if (event.request.mode === 'navigate') {
        // 최상위 페이지 진입(PWA 아이콘 실행, 새로고침)은 브라우저가 인증 헤더를 붙일 수 없어서
        // 서버가 항상 로그인 여부와 무관한 로딩 셸(bootstrap.html)을 내려준다. 이 셸은 사용자
        // 데이터가 없는 고정 UI라 캐시가 있으면 즉시 그려주고, 최신본은 백그라운드로 갱신해
        // 다음 실행 때 반영한다 (매번 서버 응답을 기다리느라 흰 화면이 오래 뜨는 문제 방지).
        event.respondWith(
            caches.match(event.request).then(cached => {
                const network = fetch(event.request).then(response => {
                    const resClone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, resClone));
                    return response;
                }).catch(() => cached || caches.match('/'));
                return cached || network;
            })
        );
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