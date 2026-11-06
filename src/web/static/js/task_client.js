/**
 * src/web/static/js/task_client.js
 * ================================
 * Universal Standard Task Client for Pluggable Specialized Publishing Tasks.
 * Encapsulates unified SSE event streaming, robust polling fallback,
 * live task cancellation, and standardized result delivery.
 */

(function (window) {
    'use strict';

    class StandardTaskClient {
        constructor(options = {}) {
            this.options = Object.assign({
                pollIntervalMs: 1200,
                sseTimeoutMs: 15000,
            }, options);

            this.activeTaskId = null;
            this.evtSource = null;
            this.pollTimer = null;
            this.isFinished = false;
        }

        /**
         * 提交任務表單
         * @param {string} endpoint - API 端點 (例如 '/api/upload_and_run_ocr' 或 '/api/process_pdf')
         * @param {FormData} formData
         * @returns {Promise<Object>}
         */
        async submitTask(endpoint, formData) {
            this.cleanup();
            this.isFinished = false;

            const res = await fetch(endpoint, {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                const errMsg = typeof errData.detail === 'string'
                    ? errData.detail
                    : JSON.stringify(errData.detail || '任務啟動失敗');
                throw new Error(errMsg);
            }

            const data = await res.json();
            this.activeTaskId = data.task_id || data.filename_stem || null;
            return data;
        }

        /**
         * 啟動雙模即時進度監聽 (SSE 優先，中斷或不支援時自動降級為輪詢)
         * @param {string} taskId
         * @param {Object} callbacks - { onProgress, onComplete, onError, onCancel }
         */
        listen(taskId, callbacks = {}) {
            this.activeTaskId = taskId;
            this.isFinished = false;

            const { onProgress, onComplete, onError, onCancel } = callbacks;

            const handleUpdate = (prog) => {
                if (this.isFinished || !prog) return;

                const status = (prog.status || '').toLowerCase();
                const progressVal = typeof prog.progress === 'number' ? prog.progress : parseFloat(prog.progress || 0);
                const message = prog.message || '';

                if (onProgress) {
                    onProgress({
                        status,
                        progress: progressVal,
                        message,
                        raw: prog
                    });
                }

                if (status === 'completed') {
                    this.isFinished = true;
                    this.cleanup();
                    if (onComplete) onComplete(prog);
                } else if (status === 'failed') {
                    this.isFinished = true;
                    this.cleanup();
                    if (onError) onError(new Error(message || prog.error || '任務執行失敗'));
                } else if (status === 'cancelled') {
                    this.isFinished = true;
                    this.cleanup();
                    if (onCancel) onCancel(prog);
                }
            };

            const startPolling = () => {
                if (this.pollTimer || this.isFinished) return;
                this.pollTimer = setInterval(async () => {
                    if (this.isFinished) return;
                    try {
                        const statusUrl = `/api/status/${encodeURIComponent(taskId)}`;
                        const res = await fetch(statusUrl);
                        if (!res.ok) return;
                        const data = await res.json();
                        handleUpdate(data);
                    } catch (e) {
                        console.debug('[TaskClient] Polling skipped:', e);
                    }
                }, this.options.pollIntervalMs);
            };

            if (window.EventSource) {
                try {
                    const sseUrl = `/api/tasks/${encodeURIComponent(taskId)}/events`;
                    this.evtSource = new EventSource(sseUrl);
                    this.evtSource.onmessage = (e) => {
                        try {
                            const data = JSON.parse(e.data);
                            handleUpdate(data);
                        } catch (err) {}
                    };
                    this.evtSource.onerror = () => {
                        if (!this.isFinished && !this.pollTimer) {
                            if (this.evtSource) {
                                this.evtSource.close();
                                this.evtSource = null;
                            }
                            startPolling();
                        }
                    };
                } catch (err) {
                    startPolling();
                }
            } else {
                startPolling();
            }
        }

        /**
         * 即時取消目前任務
         * @param {string} [taskId]
         * @returns {Promise<boolean>}
         */
        async cancel(taskId = null) {
            const targetId = taskId || this.activeTaskId;
            if (!targetId) return false;

            try {
                const res = await fetch(`/api/queue/cancel/${encodeURIComponent(targetId)}`, {
                    method: 'POST'
                });
                const ok = res.ok;
                if (ok) {
                    this.isFinished = true;
                    this.cleanup();
                }
                return ok;
            } catch (err) {
                console.error('[TaskClient] Cancel failed:', err);
                return false;
            }
        }

        /**
         * 清理目前監聽與連線
         */
        cleanup() {
            if (this.evtSource) {
                this.evtSource.close();
                this.evtSource = null;
            }
            if (this.pollTimer) {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
        }
    }

    window.StandardTaskClient = StandardTaskClient;

})(window);
