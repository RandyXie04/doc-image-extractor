import re

# Update app.py
with open('src/web/app.py', 'r', encoding='utf-8') as f:
    app_content = f.read()

upload_func_old = '''@app.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4()) + ".pdf"
    file_path = PATHS.input_dir / file_id
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"file_id": file_id}'''

upload_func_new = '''@app.post("/api/upload_file")
async def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4()) + ".pdf"
    file_path = PATHS.input_dir / file_id
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    total_pages = 1
    try:
        import pymupdf as fitz
        with fitz.open(file_path) as doc:
            total_pages = len(doc)
    except Exception:
        pass

    return {"file_id": file_id, "total_pages": total_pages}'''

if upload_func_old in app_content:
    app_content = app_content.replace(upload_func_old, upload_func_new)
else:
    app_content = re.sub(
        r'@app.post\("/api/upload_file"\).*?return \{"file_id": file_id\}', 
        upload_func_new, 
        app_content, 
        flags=re.DOTALL
    )

with open('src/web/app.py', 'w', encoding='utf-8') as f:
    f.write(app_content)


# Update index.html
with open('src/web/static/index.html', 'r', encoding='utf-8') as f:
    html_content = f.read()

# Add pagination UI
ui_old = '''                <div style="display: flex; gap: 1rem; margin-top: 1rem; align-items: center;">
                    <label style="flex: 1;">頂部裁切 (0~0.5): <span id="headerVal">0.10</span>'''
ui_new = '''                <div style="display: flex; align-items: center; justify-content: center; gap: 1rem; margin-top: 1rem;">
                    <button type="button" id="prevPageBtn" class="btn" style="padding: 5px 15px; min-width: auto;">◀ 上一頁</button>
                    <span>預覽頁碼: <span id="previewPageDisplay">1</span> / <span id="totalPagesDisplay">?</span></span>
                    <button type="button" id="nextPageBtn" class="btn" style="padding: 5px 15px; min-width: auto;">下一頁 ▶</button>
                </div>
                <div style="display: flex; gap: 1rem; margin-top: 1rem; align-items: center;">
                    <label style="flex: 1;">頂部裁切 (0~0.5): <span id="headerVal">0.10</span>'''
html_content = html_content.replace(ui_old, ui_new)

# Add variables
js_var_old = '''        let debounceTimer = null;'''
js_var_new = '''        let debounceTimer = null;
        let currentPreviewPage = 1;
        let totalPdfPages = 1;'''
html_content = html_content.replace(js_var_old, js_var_new)

# Update handleFileSelect
js_upload_old = '''                if (data.file_id) {
                    currentFileId = data.file_id;
                    fileNameDisplay.textContent = file.name;
                    submitBtn.disabled = false;
                    submitBtn.textContent = "開始處理";
                    previewContainer.style.display = 'block';
                    updatePreview();
                }'''
js_upload_new = '''                if (data.file_id) {
                    currentFileId = data.file_id;
                    fileNameDisplay.textContent = file.name;
                    submitBtn.disabled = false;
                    submitBtn.textContent = "開始處理";
                    
                    totalPdfPages = data.total_pages || 1;
                    currentPreviewPage = 1;
                    document.getElementById('totalPagesDisplay').textContent = totalPdfPages;
                    document.getElementById('previewPageDisplay').textContent = currentPreviewPage;
                    
                    previewContainer.style.display = 'block';
                    updatePreview();
                }'''
html_content = html_content.replace(js_upload_old, js_upload_new)

# Replace updatePreview logic
updatePreview_old = '''            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                let startPage = document.querySelector('[name="start_page"]').value || 1;
                previewImage.src = `/api/render_preview/${currentFileId}?page=${startPage}&header=${h}&footer=${f}&_t=${Date.now()}`;
            }, 500);'''
updatePreview_new = '''            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                previewImage.src = `/api/render_preview/${currentFileId}?page=${currentPreviewPage}&header=${h}&footer=${f}&_t=${Date.now()}`;
            }, 500);'''
html_content = html_content.replace(updatePreview_old, updatePreview_new)

# Add event listeners for buttons and remove start_page binding
listeners_old = '''        headerSlider.addEventListener('input', updatePreview);
        footerSlider.addEventListener('input', updatePreview);
        document.querySelector('[name="start_page"]').addEventListener('change', updatePreview);'''
listeners_new = '''        headerSlider.addEventListener('input', updatePreview);
        footerSlider.addEventListener('input', updatePreview);
        
        document.getElementById('prevPageBtn').addEventListener('click', () => {
            if (currentPreviewPage > 1) {
                currentPreviewPage--;
                document.getElementById('previewPageDisplay').textContent = currentPreviewPage;
                updatePreview();
            }
        });
        document.getElementById('nextPageBtn').addEventListener('click', () => {
            if (currentPreviewPage < totalPdfPages) {
                currentPreviewPage++;
                document.getElementById('previewPageDisplay').textContent = currentPreviewPage;
                updatePreview();
            }
        });'''
html_content = html_content.replace(listeners_old, listeners_new)

with open('src/web/static/index.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print('Updated UI and API.')
