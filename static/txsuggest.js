// 거래내역 등록 폼 공용 모듈
//  1) 분류 선택 팝업 레이어 (자동분류 유력 후보 순 정렬, 그리드로 표시)
//  2) 금액 입력 시 제목 자동완성 (동일 금액의 최근 3개월 내역 최대 3건)
// calendar.html / transactions.html 의 등록·수정 시트에서 initTxSuggest() 로 초기화한다.
(function () {
    var STYLE_ID = 'txsuggest-style';
    var CSS = [
        '#txcat-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2000;display:none;align-items:flex-end;}',
        '#txcat-overlay.active{display:flex;}',
        '#txcat-panel{background:var(--color-canvas);width:100%;max-width:768px;margin:0 auto;border-radius:24px 24px 0 0;padding:24px;box-sizing:border-box;max-height:80vh;display:flex;flex-direction:column;}',
        '#txcat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:8px;overflow-y:auto;}',
        '.txcat-chip{padding:12px 8px;border-radius:12px;border:1px solid var(--color-line);background:var(--color-canvas);color:var(--color-foreground);font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;text-align:center;line-height:1.3;}',
        '.txcat-chip .dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}',
        '.txcat-chip.suggested{border-color:var(--color-action);border-width:2px;color:var(--color-action);}',
        '.txcat-btn{text-align:left;cursor:pointer;}',
        '.txtitle-ac{position:absolute;left:0;right:0;top:100%;margin-top:2px;background:var(--color-canvas);border:1px solid var(--color-line);border-radius:12px;z-index:20;box-shadow:0 8px 20px rgba(0,0,0,.12);overflow:hidden;display:none;}',
        '.txtitle-ac.active{display:block;}',
        '.txtitle-ac button{display:block;width:100%;text-align:left;padding:10px 14px;background:none;border:none;border-bottom:1px solid var(--color-line);font-size:14px;font-family:inherit;color:var(--color-foreground);cursor:pointer;}',
        '.txtitle-ac button:last-child{border-bottom:none;}'
    ].join('');

    var overlay, panel, grid, activeInst = null;

    function ensureStyle() {
        if (document.getElementById(STYLE_ID)) return;
        var s = document.createElement('style');
        s.id = STYLE_ID;
        s.textContent = CSS;
        document.head.appendChild(s);
    }

    function ensureModal() {
        // SPA 네비게이션으로 이 스크립트가 다시 실행돼도 모달은 body에 하나만 유지한다.
        var existing = document.getElementById('txcat-overlay');
        if (existing) {
            overlay = existing;
            panel = overlay.querySelector('#txcat-panel');
            grid = overlay.querySelector('#txcat-grid');
            return;
        }
        overlay = document.createElement('div');
        overlay.id = 'txcat-overlay';
        overlay.innerHTML =
            '<div id="txcat-panel">' +
            '  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
            '    <h3 style="font-size:18px;font-weight:700;">분류 선택</h3>' +
            '    <button type="button" id="txcat-close" class="chip" style="background:none;color:var(--color-muted);font-size:18px;padding:0;">✕</button>' +
            '  </div>' +
            '  <div id="txcat-grid"></div>' +
            '</div>';
        document.body.appendChild(overlay);
        panel = overlay.querySelector('#txcat-panel');
        grid = overlay.querySelector('#txcat-grid');
        overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(); });
        overlay.querySelector('#txcat-close').addEventListener('click', closeModal);
    }

    function closeModal() {
        if (overlay) overlay.classList.remove('active');
        activeInst = null;
    }

    async function openModal(inst) {
        ensureModal();
        activeInst = inst;
        grid.innerHTML = '<div style="color:var(--color-muted);font-size:14px;padding:8px;">불러오는 중...</div>';
        overlay.classList.add('active');

        var params = new URLSearchParams({
            title: inst.cfg.titleInput.value || '',
            amount: (inst.cfg.amountInput.value || '').replace(/[^0-9]/g, ''),
            tx_type: inst.cfg.txTypeInput.value || '지출'
        });
        var data;
        try {
            var res = await fetch('/api/category_suggest?' + params.toString());
            data = await res.json();
        } catch (e) {
            grid.innerHTML = '<div style="color:var(--color-danger);font-size:14px;padding:8px;">분류를 불러오지 못했습니다.</div>';
            return;
        }
        if (activeInst !== inst) return; // 그 사이 다른 폼이 열었으면 무시

        (data.items || []).forEach(function (c) { inst.catMap[c.id] = c; });
        grid.innerHTML = '';
        (data.items || []).forEach(function (c) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'txcat-chip' + (data.matched_id && c.id === data.matched_id ? ' suggested' : '');
            b.innerHTML = (c.color ? '<span class="dot" style="background:' + c.color + ';"></span>' : '') +
                '<span>' + escapeHtml(c.name) + '</span>';
            b.addEventListener('click', function () {
                inst.setCategoryId(c.id, c.name);
                closeModal();
            });
            grid.appendChild(b);
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (m) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
        });
    }

    window.initTxSuggest = function (cfg) {
        // cfg: { amountInput, titleInput, txTypeInput, catValueInput(hidden), catButton }
        ensureStyle();

        var inst = { cfg: cfg, catMap: {}, uncatId: null };

        // --- 분류 값/라벨 ---
        inst.setCategoryId = function (id, name) {
            cfg.catValueInput.value = (id == null ? '' : id);
            var label = name || (inst.catMap[id] && inst.catMap[id].name) || '분류 선택';
            cfg.catButton.textContent = label;
        };
        inst.reset = async function () {
            inst.hideTitleAC();
            if (inst.uncatId == null) await loadCats();
            inst.setCategoryId(inst.uncatId, '미분류');
        };

        async function loadCats() {
            try {
                var res = await fetch('/api/categories');
                var cats = await res.json();
                cats.forEach(function (c) {
                    inst.catMap[c.id] = c;
                    if (c.name === '미분류') inst.uncatId = c.id;
                });
            } catch (e) { /* 팝업 열 때 다시 시도됨 */ }
        }
        loadCats();

        cfg.catButton.addEventListener('click', function () { openModal(inst); });

        // --- 제목 자동완성 ---
        var wrap = cfg.titleInput.parentElement;
        wrap.style.position = 'relative';
        var ac = document.createElement('div');
        ac.className = 'txtitle-ac';
        wrap.appendChild(ac);

        inst.hideTitleAC = function () { ac.classList.remove('active'); };

        function renderAC(titles) {
            if (!titles || !titles.length) { inst.hideTitleAC(); return; }
            ac.innerHTML = '';
            titles.forEach(function (t) {
                var b = document.createElement('button');
                b.type = 'button';
                b.textContent = t;
                b.addEventListener('mousedown', function (e) {
                    e.preventDefault(); // blur 보다 먼저 처리
                    cfg.titleInput.value = t;
                    inst.hideTitleAC();
                });
                ac.appendChild(b);
            });
            ac.classList.add('active');
        }

        async function queryAC() {
            var amt = (cfg.amountInput.value || '').replace(/[^0-9]/g, '');
            if (!amt) { inst.hideTitleAC(); return; }
            var params = new URLSearchParams({ amount: amt, tx_type: cfg.txTypeInput.value || '지출' });
            try {
                var res = await fetch('/api/title_suggest?' + params.toString());
                renderAC(await res.json());
            } catch (e) { inst.hideTitleAC(); }
        }

        var t;
        cfg.amountInput.addEventListener('input', function () {
            clearTimeout(t);
            t = setTimeout(queryAC, 250);
        });
        cfg.titleInput.addEventListener('focus', queryAC);
        cfg.titleInput.addEventListener('blur', function () { setTimeout(inst.hideTitleAC, 150); });
        cfg.titleInput.addEventListener('keydown', function (e) { if (e.key === 'Escape') inst.hideTitleAC(); });

        return inst;
    };
})();
