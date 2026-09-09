document.addEventListener("DOMContentLoaded", () => {
    // Check if sidebar already exists
    if (document.getElementById('sidebar')) return;

    const currentPath = window.location.pathname;
    
    const sidebarHtml = `
    <div id="sidebar">
        <a href="/" class="brand">📚 轉檔工具箱</a>
        <nav>
            <a href="/static/formula.html" class="nav-link ${currentPath.includes('formula') ? 'active' : ''}">
                <span class="nav-icon">🔍</span> 公式提取
            </a>
            <a href="/static/extract_images.html" class="nav-link ${currentPath.includes('extract_images') ? 'active' : ''}">
                <span class="nav-icon">🖼️</span> 圖片提取
            </a>
            <a href="/static/founder_repair.html" class="nav-link ${currentPath.includes('founder_repair') ? 'active' : ''}">
                <span class="nav-icon">🛠️</span> 方正修復
            </a>
            <a href="/static/ocr_pipeline.html" class="nav-link ${currentPath.includes('ocr_pipeline') ? 'active' : ''}">
                <span class="nav-icon">📄</span> 自動 OCR
            </a>
        </nav>
        <div style="padding: 1.5rem; margin-top: auto;">
            <button id="globalReportBtn" style="width: 100%; background: #334155; color: white; border: none; padding: 10px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;">
                💬 問題回報
            </button>
        </div>
    </div>
    `;

    // Wrap body content in main-content
    const bodyContents = Array.from(document.body.childNodes);
    const mainContent = document.createElement('div');
    mainContent.id = 'main-content';
    bodyContents.forEach(node => mainContent.appendChild(node));

    document.body.appendChild(mainContent);
    document.body.insertAdjacentHTML('afterbegin', sidebarHtml);

    // Inject sidebar CSS if not already there
    if (!document.querySelector('link[href*="sidebar.css"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/static/sidebar.css';
        document.head.appendChild(link);
    }

    // Modal HTML for Issue Reporting
    const modalHtml = `
    <div id="issueModal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 1000;">
        <div style="background: white; padding: 2rem; border-radius: 12px; width: 400px; max-width: 90%;">
            <h3 style="margin-top: 0;">💬 提交問題回報</h3>
            <p style="font-size: 0.9rem; color: #64748b;">請用簡單的描述告訴我們您遇到了什麼問題，或希望新增什麼功能。送出後將自動建立內部任務。</p>
            <textarea id="issueDesc" rows="5" style="width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 8px; margin-bottom: 1rem; box-sizing: border-box;" placeholder="例如：我上傳的 PDF 檔案一直轉圈圈沒有反應..."></textarea>
            <div id="issueMsg" style="margin-bottom: 1rem; font-size: 0.9rem; font-weight: bold;"></div>
            <div style="display: flex; gap: 10px; justify-content: flex-end;">
                <button id="closeIssueBtn" style="padding: 8px 16px; border: none; background: #e2e8f0; border-radius: 6px; cursor: pointer;">取消</button>
                <button id="submitIssueBtn" style="padding: 8px 16px; border: none; background: #0f172a; color: white; border-radius: 6px; cursor: pointer;">送出回報</button>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Modal logic
    const modal = document.getElementById('issueModal');
    const openBtn = document.getElementById('globalReportBtn');
    const closeBtn = document.getElementById('closeIssueBtn');
    const submitBtn = document.getElementById('submitIssueBtn');
    const issueDesc = document.getElementById('issueDesc');
    const issueMsg = document.getElementById('issueMsg');

    openBtn.onclick = () => { modal.style.display = 'flex'; issueMsg.textContent = ''; issueDesc.value = ''; };
    closeBtn.onclick = () => { modal.style.display = 'none'; };
    
    // Wire any in-page report links to also open this modal
    document.querySelectorAll('a[href*="issues"]').forEach(link => {
        link.onclick = (e) => {
            e.preventDefault();
            modal.style.display = 'flex';
            issueMsg.textContent = '';
            issueDesc.value = '';
        };
    });
    
    submitBtn.onclick = async () => {
        if (!issueDesc.value.trim()) {
            issueMsg.style.color = '#dc2626';
            issueMsg.textContent = '內容不可為空';
            return;
        }
        submitBtn.disabled = true;
        submitBtn.textContent = '傳送中...';
        issueMsg.style.color = '#0284c7';
        issueMsg.textContent = '🚀 正在上傳回報至 GitHub...';

        try {
            const res = await fetch('/api/report_issue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ description: issueDesc.value })
            });
            const data = await res.json();
            if (res.ok) {
                issueMsg.style.color = '#16a34a';
                issueMsg.innerHTML = '✅ 提交成功！<br>內部追蹤連結：<a href="' + data.url + '" target="_blank">查看 Issue</a>';
                setTimeout(() => { modal.style.display = 'none'; }, 5000);
            } else {
                issueMsg.style.color = '#dc2626';
                issueMsg.textContent = '❌ ' + (data.detail || '未知錯誤');
            }
        } catch (e) {
            issueMsg.style.color = '#dc2626';
            issueMsg.textContent = '❌ 網路錯誤，請稍後再試';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = '送出回報';
        }
    };
});
