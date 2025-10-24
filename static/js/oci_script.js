document.addEventListener('DOMContentLoaded', function() {
    // --- 1. DOM 元素获取 ---
    const profileList = document.getElementById('profileList');
    const currentProfileStatus = document.getElementById('currentProfileStatus');
    
    const addAccountModal = new bootstrap.Modal(document.getElementById('addAccountModal'));
    // === MODIFICATION START: Add listener for when the modal is shown ===
    document.getElementById('addAccountModal').addEventListener('shown.bs.modal', loadAndDisplayDefaultKey);
    // === MODIFICATION END ===
    
    const addNewProfileBtnModal = document.getElementById('addNewProfileBtnModal');
    const newProfileAlias = document.getElementById('newProfileAlias');
    const newProfileConfigText = document.getElementById('newProfileConfigText');
    const newProfileKeyFile = document.getElementById('newProfileKeyFile');

    const refreshInstancesBtn = document.getElementById('refreshInstancesBtn');
    const createInstanceBtn = document.getElementById('createInstanceBtn');
    const networkSettingsBtn = document.getElementById('networkSettingsBtn');
    const instanceList = document.getElementById('instanceList');
    const logOutput = document.getElementById('logOutput');
    const clearLogBtn = document.getElementById('clearLogBtn');
    
    const snatchLogOutput = document.getElementById('snatchLogOutput');
    const clearSnatchLogBtn = document.getElementById('clearSnatchLogBtn');
    const snatchLogArea = document.getElementById('snatchLogArea');
    
    // Modals
    const launchInstanceModal = new bootstrap.Modal(document.getElementById('createLaunchInstanceModal'));
    const launchInstanceModalEl = document.getElementById('createLaunchInstanceModal');
    const viewSnatchTasksModal = new bootstrap.Modal(document.getElementById('viewSnatchTasksModal'));
    const viewSnatchTasksModalEl = document.getElementById('viewSnatchTasksModal'); 
    const taskResultModal = new bootstrap.Modal(document.getElementById('taskResultModal'));
    const networkSettingsModal = new bootstrap.Modal(document.getElementById('networkSettingsModal'));
    const editInstanceModal = new bootstrap.Modal(document.getElementById('editInstanceModal'));
    const confirmActionModal = new bootstrap.Modal(document.getElementById('confirmActionModal'));
    const editProfileModal = new bootstrap.Modal(document.getElementById('editProfileModal'));
    const proxySettingsModal = new bootstrap.Modal(document.getElementById('proxySettingsModal'));
    const cloudflareSettingsModal = new bootstrap.Modal(document.getElementById('cloudflareSettingsModal'));

    const instanceCountInput = document.getElementById('instanceCount');
    const launchInstanceShapeSelect = document.getElementById('instanceShape');
    const launchFlexConfig = document.getElementById('flexShapeConfig');
    const submitLaunchInstanceBtn = document.getElementById('submitLaunchInstanceBtn');
    const proxySettingsAlias = document.getElementById('proxySettingsAlias');
    const proxyUrlInput = document.getElementById('proxyUrl');
    const saveProxyBtn = document.getElementById('saveProxyBtn');
    const removeProxyBtn = document.getElementById('removeProxyBtn');
    
    const stopSnatchTaskBtn = document.getElementById('stopSnatchTaskBtn');
    const resumeSnatchTaskBtn = document.getElementById('resumeSnatchTaskBtn');
    const deleteSnatchTaskBtn = document.getElementById('deleteSnatchTaskBtn');
    const deleteCompletedBtn = document.getElementById('deleteCompletedBtn');
    
    const runningSnatchTasksList = document.getElementById('runningSnatchTasksList');
    const completedSnatchTasksList = document.getElementById('completedSnatchTasksList');
    const actionAreaProfile = document.getElementById('actionAreaProfile');
    const ingressRulesTable = document.getElementById('ingressRulesTable');
    const egressRulesTable = document.getElementById('egressRulesTable');
    // --- ✨ MODIFICATION START ✨ ---
    // 添加新的 VCN 和安全列表下拉菜单的引用
    const vcnSelect = document.getElementById('vcnSelect');
    const securityListSelect = document.getElementById('securityListSelect');
    const networkRulesSpinner = document.getElementById('networkRulesSpinner');
    // --- ✨ MODIFICATION END ✨ ---
    const addIngressRuleBtn = document.getElementById('addIngressRuleBtn');
    const addEgressRuleBtn = document.getElementById('addEgressRuleBtn');
    const saveNetworkRulesBtn = document.getElementById('saveNetworkRulesBtn');
    const openFirewallBtn = document.getElementById('openFirewallBtn');
    const editDisplayName = document.getElementById('editDisplayName');
    const saveDisplayNameBtn = document.getElementById('saveDisplayNameBtn');
    const editFlexInstanceConfig = document.getElementById('editFlexInstanceConfig');
    const editOcpus = document.getElementById('editOcpus');
    const editMemory = document.getElementById('editMemory');
    const saveFlexConfigBtn = document.getElementById('saveFlexConfigBtn');
    const editBootVolumeSize = document.getElementById('editBootVolumeSize');
    const saveBootVolumeSizeBtn = document.getElementById('saveBootVolumeSizeBtn');
    const editVpus = document.getElementById('editVpus');
    const saveVpusBtn = document.getElementById('saveVpusBtn');
    const confirmActionModalLabel = document.getElementById('confirmActionModalLabel');
    const confirmActionModalBody = document.getElementById('confirmActionModalBody');
    const confirmActionModalTerminateOptions = document.getElementById('confirmActionModalTerminateOptions');
    const confirmDeleteVolumeCheck = document.getElementById('confirmDeleteVolumeCheck');
    const confirmActionModalConfirmBtn = document.getElementById('confirmActionModalConfirmBtn');
    const tgBotTokenInput = document.getElementById('tgBotToken');
    const tgChatIdInput = document.getElementById('tgChatId');
    const saveTgConfigBtn = document.getElementById('saveTgConfigBtn');
    const getApiKeyBtn = document.getElementById('getApiKeyBtn');
    const apiKeyInput = document.getElementById('apiKeyInput');
    
    const cloudflareApiTokenInput = document.getElementById('cloudflareApiToken');
    const cloudflareZoneIdInput = document.getElementById('cloudflareZoneId');
    const cloudflareDomainInput = document.getElementById('cloudflareDomain');
    const saveCloudflareConfigBtn = document.getElementById('saveCloudflareConfigBtn');
    const autoBindDomainCheck = document.getElementById('autoBindDomainCheck');


    const instanceActionButtons = {
        start: document.getElementById('startBtn'),
        stop: document.getElementById('stopBtn'),
        restart: document.getElementById('restartBtn'),
        editInstance: document.getElementById('editInstanceBtn'),
        changeIp: document.getElementById('changeIpBtn'),
        assignIpv6: document.getElementById('assignIpv6Btn'),
        terminate: document.getElementById('terminateBtn'),
    };

    let currentInstances = [];
    let selectedInstance = null;
    let currentSecurityList = null;
    
    const accountColors = {};
    const colorPalette = ['#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8', '#6610f2', '#e83e8c'];
    let colorIndex = 0;
    const snatchTaskAnnounced = {};

    function getAccountColor(alias) {
        if (!accountColors[alias]) {
            accountColors[alias] = colorPalette[colorIndex % colorPalette.length];
            colorIndex++;
        }
        return accountColors[alias];
    }

    // --- Event Listeners ---

    launchInstanceShapeSelect.addEventListener('change', () => {
        const isFlex = launchInstanceShapeSelect.value.includes('Flex');
        launchFlexConfig.style.display = isFlex ? 'flex' : 'none';
    });
    launchInstanceShapeSelect.dispatchEvent(new Event('change'));

    submitLaunchInstanceBtn.addEventListener('click', () => {
        const proceedWithLaunch = async () => {
            const shape = launchInstanceShapeSelect.value;
            if (!shape) {
                addLog('请选择一个有效的实例规格。', 'error');
                return;
            }

            const details = {
                display_name_prefix: document.getElementById('instanceNamePrefix').value.trim(),
                instance_count: parseInt(instanceCountInput.value, 10),
                instance_password: document.getElementById('instancePassword').value.trim(),
                os_name_version: document.getElementById('instanceOS').value,
                shape: shape,
                boot_volume_size: parseInt(document.getElementById('bootVolumeSize').value, 10),
                startup_script: document.getElementById('startupScript').value.trim(),
                min_delay: parseInt(document.getElementById('minDelay').value, 10) || 30,
                max_delay: parseInt(document.getElementById('maxDelay').value, 10) || 90,
                auto_bind_domain: autoBindDomainCheck.checked
            };
    
            if (shape.includes('Flex')) {
                details.ocpus = parseInt(document.getElementById('instanceOcpus').value, 10);
                details.memory_in_gbs = parseInt(document.getElementById('instanceMemory').value, 10);
            }
            
            if (details.min_delay >= details.max_delay) return addLog('最短重试间隔必须小于最长重试间隔', 'error');
            if (!details.display_name_prefix) return addLog('实例名称/前缀不能为空', 'error');
    
            let logMessage = `正在提交抢占实例 [${details.display_name_prefix}] 的任务...`;
            if (details.auto_bind_domain) {
                logMessage += ' (已启用自动域名绑定)';
            }
            addLog(logMessage);
    
            try {
                const response = await apiRequest('/oci/api/launch-instance', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(details)
                });
                addLog(response.message, 'success');
                launchInstanceModal.hide();
                
                if (response.task_ids && Array.isArray(response.task_ids)) {
                    response.task_ids.forEach(pollTaskStatus);
                }
            } catch (error) {}
        };

        const shape = launchInstanceShapeSelect.value;
        const requestedCount = parseInt(instanceCountInput.value, 10);
        const requestedBootVolumeSize = parseInt(document.getElementById('bootVolumeSize').value, 10);
        
        const activeInstances = currentInstances.filter(inst => 
            !['TERMINATED', 'TERMINATING'].includes(inst.lifecycle_state)
        );

        const newRequestedTotalSize = requestedCount * requestedBootVolumeSize;
        const currentTotalBootVolumeSize = activeInstances.reduce((total, inst) => {
            const sizeInGb = parseInt(inst.boot_volume_size_gb, 10);
            return total + (isNaN(sizeInGb) ? 0 : sizeInGb);
        }, 0);

        if ((currentTotalBootVolumeSize + newRequestedTotalSize) > 200) {
            confirmActionModalLabel.textContent = '警告: 超出免费额度';
            confirmActionModalBody.innerHTML = `您当前已使用 <strong>${currentTotalBootVolumeSize} GB</strong> 磁盘，本次请求将导致总量达到 <strong>${currentTotalBootVolumeSize + newRequestedTotalSize} GB</strong>，超出 200 GB 的免费额度。这可能会导致您的账户产生额外费用。<br><br>确定要继续吗？`;
            confirmActionModalConfirmBtn.onclick = () => {
                confirmActionModal.hide();
                proceedWithLaunch();
            };
            confirmActionModal.show();
            return;
        }

        if (shape === 'VM.Standard.E2.1.Micro') {
            const existingAMDCount = activeInstances.filter(inst => inst.shape === shape).length;
            if ((existingAMDCount + requestedCount) > 2) {
                addLog(`免费账户最多只能创建2个AMD实例，您已有 ${existingAMDCount} 个活动实例，无法再创建 ${requestedCount} 个。`, 'error');
                return;
            }
        }
        
        proceedWithLaunch();
    });

    launchInstanceModalEl.addEventListener('shown.bs.modal', updateAvailableShapes);
    document.getElementById('instanceOS').addEventListener('change', updateAvailableShapes);


    const snatchTaskTabs = document.querySelectorAll('#snatchTaskTabs button[data-bs-toggle="tab"]');
    snatchTaskTabs.forEach(tab => {
        tab.addEventListener('shown.bs.tab', event => {
            const runningDeleteAction = document.getElementById('running-delete-action');
            if (event.target.id === 'running-tab') {
                document.getElementById('running-actions').style.display = 'flex';
                document.getElementById('completed-actions').style.display = 'none';
                runningDeleteAction.style.display = 'block';
                snatchLogArea.style.display = 'block';
            } else if (event.target.id === 'completed-tab') {
                document.getElementById('running-actions').style.display = 'none';
                document.getElementById('completed-actions').style.display = 'flex';
                runningDeleteAction.style.display = 'none';
                snatchLogArea.style.display = 'none';
            }
        });
    });
    
    viewSnatchTasksModalEl.addEventListener('shown.bs.modal', function () {
        snatchLogOutput.scrollTop = snatchLogOutput.scrollHeight;
    });

    document.getElementById('viewSnatchTasksBtn').addEventListener('click', function() {
        const runningTabBtn = document.getElementById('running-tab');
        const completedTabBtn = document.getElementById('completed-tab');
        const runningPane = document.getElementById('running-tab-pane');
        const completedPane = document.getElementById('completed-tab-pane');

        runningTabBtn.classList.add('active');
        completedTabBtn.classList.remove('active');
        runningPane.classList.add('show', 'active');
        completedPane.classList.remove('show', 'active');
        
        document.getElementById('running-actions').style.display = 'flex';
        document.getElementById('completed-actions').style.display = 'none';
        document.getElementById('running-delete-action').style.display = 'block';
        snatchLogArea.style.display = 'block';

        loadSnatchTasks();
    });
    
    // --- Core and Helper Functions ---

    async function updateAvailableShapes() {
        const os_name_version = document.getElementById('instanceOS').value;
        const shapeSelect = document.getElementById('instanceShape');
        
        shapeSelect.innerHTML = '<option value="">正在刷新实例规格...</option>';
        shapeSelect.disabled = true;
        submitLaunchInstanceBtn.disabled = true;

        try {
            const shapes = await apiRequest(`/oci/api/available-shapes?os_name_version=${os_name_version}`);
            shapeSelect.innerHTML = ''; 
            if (shapes.length === 0) {
                shapeSelect.innerHTML = '<option value="">当前系统无可用规格</option>';
            } else {
                shapes.sort((a, b) => a.includes('A1.Flex') ? -1 : (b.includes('A1.Flex') ? 1 : 0));
                shapes.forEach(shape => {
                    const option = document.createElement('option');
                    option.value = shape;
                    option.textContent = shape;
                    shapeSelect.appendChild(option);
                });
                submitLaunchInstanceBtn.disabled = false;
            }
        } catch (error) {
            shapeSelect.innerHTML = '<option value="">获取规格失败</option>';
            addLog('自动刷新实例规格失败，请检查网络或账号权限。', 'error');
        } finally {
            shapeSelect.disabled = false;
            shapeSelect.dispatchEvent(new Event('change'));
        }
    }
    
    function addLog(message, type = 'info') {
        const timestamp = new Date().toLocaleTimeString();
        const typeMap = { 'error': 'text-danger', 'success': 'text-success', 'warning': 'text-warning' };
        const color = typeMap[type] || '';
        const logEntry = document.createElement('div');
        logEntry.className = color;
        logEntry.innerHTML = `[${timestamp}] ${message.replace(/\n/g, '<br>')}`;
        logOutput.appendChild(logEntry);
        logOutput.scrollTop = logOutput.scrollHeight;
    }

    function addSnatchLog(message, accountAlias) {
        const timestamp = new Date().toLocaleTimeString();
        const color = getAccountColor(accountAlias);
        
        const logEntry = document.createElement('div');
        logEntry.style.color = color;
        logEntry.innerHTML = `[${timestamp}] <strong style="color: ${color};">[${accountAlias || '未知账户'}]</strong> ${message.replace(/\n/g, '<br>')}`;
        
        snatchLogOutput.appendChild(logEntry);
        snatchLogOutput.scrollTop = snatchLogOutput.scrollHeight;
    }
    
    clearLogBtn.addEventListener('click', () => logOutput.innerHTML = '');
    clearSnatchLogBtn.addEventListener('click', () => snatchLogOutput.innerHTML = '');

    async function apiRequest(url, options = {}) {
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: `HTTP 错误! 状态: ${response.status}` }));
                throw new Error(errorData.error || `HTTP 错误! 状态: ${response.status}`);
            }
            const text = await response.text();
            return text ? JSON.parse(text) : {};
        } catch (error) {
            addLog(`请求失败: ${error.message}`, 'error');
            throw error;
        }
    }

    async function refreshInstances() {
        addLog('正在刷新实例列表...');
        refreshInstancesBtn.disabled = true;
        instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-5"><div class="spinner-border spinner-border-sm"></div> 正在加载...</td></tr>`;
        try {
            const instances = await apiRequest('/oci/api/instances');
            currentInstances = instances; 
            instanceList.innerHTML = '';
            if (instances.length === 0) {
                 instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-5">未找到任何实例</td></tr>`;
            } else {
                instances.forEach(inst => {
                    const tr = document.createElement('tr');
                    tr.dataset.instanceId = inst.id;
                    tr.dataset.instanceData = JSON.stringify(inst);
                    const state = inst.lifecycle_state;
                    let dotClass = state === 'RUNNING' ? 'status-running' : (state === 'STOPPED' ? 'status-stopped' : 'status-other');
                    tr.innerHTML = `
                        <td style="text-align: left; padding-left: 1rem;">${inst.display_name}</td>
                        <td><div class="status-cell"><span class="status-dot ${dotClass}"></span><span>${state}</span></div></td>
                        <td>${inst.public_ip || '无'}</td>
                        <td>${inst.ipv6_address || '无'}</td>
                        <td>${inst.ocpus}c / ${inst.memory_in_gbs}g / ${inst.boot_volume_size_gb}</td>
                        <td>${new Date(inst.time_created).toLocaleString()}</td>`;
                    instanceList.appendChild(tr);
                });
            }
            addLog('实例列表刷新成功!', 'success');
        } catch (error) {
            currentInstances = [];
            instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-5">加载实例列表失败</td></tr>`;
        } finally {
            refreshInstancesBtn.disabled = false;
        }
    }
    
    refreshInstancesBtn.addEventListener('click', refreshInstances);
    
    async function checkSession(shouldRefreshInstances = true) {
        try {
            const data = await apiRequest('/oci/api/session');
            
            document.querySelectorAll('#profileList tr').forEach(r => {
                r.classList.remove('table-active', 'profile-disabled');
            });

            if (data.logged_in && data.alias) {
                currentProfileStatus.textContent = `已连接: ${data.alias}`;
                actionAreaProfile.textContent = `当前账号: ${data.alias}`;
                actionAreaProfile.classList.remove('d-none');
                enableMainControls(true, data.can_create);
                if (shouldRefreshInstances) {
                    await refreshInstances();
                }
                
                const activeRow = document.querySelector(`#profileList tr[data-alias="${data.alias}"]`);
                if (activeRow) {
                    activeRow.classList.add('table-active', 'profile-disabled');
                }
            } else {
                currentProfileStatus.textContent = '未连接';
                actionAreaProfile.classList.add('d-none');
                enableMainControls(false, false);
            }
        } catch (error) {
             currentProfileStatus.textContent = '未连接 (会话检查失败)';
             actionAreaProfile.classList.add('d-none');
             enableMainControls(false, false);
        }
    }
    
    function enableMainControls(enabled, canCreate) {
        refreshInstancesBtn.disabled = !enabled;
        createInstanceBtn.disabled = !canCreate;
        networkSettingsBtn.disabled = !enabled;
        if (!enabled) {
            instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-5">请先连接一个账号并刷新列表</td></tr>`;
            Object.values(instanceActionButtons).forEach(btn => btn.disabled = true);
        }
    }
    
    function pollTaskStatus(taskId, isRepoll = false) {
        if (!window.taskPollers) window.taskPollers = {};
    
        const poller = async () => {
            try {
                const apiResponse = await apiRequest(`/oci/api/task_status/${taskId}`);
                if (!apiResponse || apiResponse.status === 'not_found') {
                    console.warn(`Task ${taskId} not found or invalid response. Stopping poller.`);
                    delete window.taskPollers[taskId];
                    return;
                }
                const isFinalState = ['success', 'failure'].includes(apiResponse.status);

                if (apiResponse.type === 'snatch') {
                    handleSnatchTaskPolling(taskId, apiResponse, isFinalState, isRepoll);
                } else {
                    const lastLogKey = `lastLog_main_${taskId}`;
                    if (window[lastLogKey] !== apiResponse.result) {
                        const logType = apiResponse.status === 'success' ? 'success' : (apiResponse.status === 'failure' ? 'error' : 'info');
                        addLog(`任务[${taskId.substring(0,8)}] ${apiResponse.result}`, logType);
                        window[lastLogKey] = apiResponse.result;
                    }
                }
    
                if (!isFinalState) {
                    if (apiResponse.status === 'paused') {
                        delete window.taskPollers[taskId]; 
                        return;
                    }
                    window.taskPollers[taskId] = setTimeout(poller, 5000);
                } else {
                    delete window.taskPollers[taskId]; 
                    const lastLogKey = `lastLog_main_${taskId}`;
                    const lastSnatchLogKey = `lastSnatchLog_${taskId}`;
                    delete window[lastLogKey];
                    delete window[lastSnatchLogKey];

                    if (apiResponse.status === 'success') {
                        setTimeout(refreshInstances, 2000);
                    }
                }
    
            } catch (error) {
                addLog(`监控任务 ${taskId} 时发生网络错误，将在10秒后重试...`, 'warning');
                window.taskPollers[taskId] = setTimeout(poller, 10000); 
            }
        };
        
        poller();
    }

    function handleSnatchTaskPolling(taskId, apiResponse, isFinalState, isRepoll) {
        const lastLogKey = `lastSnatchLog_${taskId}`;
        let parsedResult = null;
        let currentMessage = apiResponse.result; 

        try {
            parsedResult = JSON.parse(apiResponse.result);
            if (parsedResult && parsedResult.details) {
                const taskName = parsedResult.details.display_name_prefix || parsedResult.details.name;
                if (parsedResult.attempt_count > 0) {
                    currentMessage = `任务 ${taskName}: 第 ${parsedResult.attempt_count} 次尝试，${parsedResult.last_message}`;
                } else {
                    currentMessage = `任务 ${taskName}: ${parsedResult.last_message}`;
                }
            }
        } catch (e) { /* Not JSON, keep original message */ }

        if(window[lastLogKey] === currentMessage) return; 
        window[lastLogKey] = currentMessage; 

        const accountAlias = parsedResult?.details?.account_alias;
        const taskNameForLog = parsedResult?.details?.display_name_prefix || parsedResult?.details?.name || taskId.substring(0,8);

        if (apiResponse.status === 'running' || apiResponse.status === 'paused') {
             if (apiResponse.status === 'running' && !isRepoll && !snatchTaskAnnounced[taskId]) {
                addLog(`任务 [${taskNameForLog}] 正在准备...`);
                addLog(`抢占任务已成功启动，具体详情请点击【查看抢占任务】`, 'success');
                snatchTaskAnnounced[taskId] = true;
            }
            addSnatchLog(currentMessage, accountAlias);
        } else if (isFinalState) {
            const logType = apiResponse.status === 'success' ? 'success' : 'error';
            addLog(`抢占任务 [${taskNameForLog}] 已完成: ${apiResponse.result}`, logType);
            addSnatchLog(`<strong>任务完成:</strong> ${apiResponse.result}`, accountAlias);
            delete snatchTaskAnnounced[taskId];
        } else {
            addLog(`任务 [${taskNameForLog}] 状态: ${apiResponse.status} - ${apiResponse.result}`);
        }
    }
    
    async function loadProfiles() {
        profileList.innerHTML = `<tr><td colspan="3" class="text-center text-muted">正在加载...</td></tr>`;
        try {
            const profileNames = await apiRequest(`/oci/api/profiles`);
            profileList.innerHTML = '';
            if (profileNames.length === 0) {
                profileList.innerHTML = `<tr><td colspan="3" class="text-center text-muted">未找到账号，请点击右上角添加</td></tr>`;
            } else {
                profileNames.forEach(name => {
                    const tr = document.createElement('tr');
                    tr.dataset.alias = name;
                    // --- ✨ 样式修复：为按钮添加固定宽度和居中样式 ✨ ---
                    tr.innerHTML = `
                        <td class="drag-handle text-center align-middle"><i class="bi bi-grip-vertical"></i></td>
                        <td class="align-middle">
                            <a href="#" class="btn btn-info btn-sm connect-btn" data-alias="${name}" onclick="event.preventDefault();" style="width: 8em; text-align: center;">${name}</a>
                        </td>
                        <td class="text-end action-buttons align-middle">
                            <button class="btn btn-warning btn-sm proxy-btn profile-action-btn" data-alias="${name}"><i class="bi bi-shield-lock"></i> 代理</button>
                            <button class="btn btn-info btn-sm edit-btn profile-action-btn" data-alias="${name}"><i class="bi bi-pencil"></i> 编辑</button>
                            <button class="btn btn-danger btn-sm delete-btn profile-action-btn" data-alias="${name}"><i class="bi bi-trash"></i> 删除</button>
                        </td>
                    `;
                    profileList.appendChild(tr);
                });
            }
            checkSession(false); 
        } catch (error) {
            profileList.innerHTML = `<tr><td colspan="3" class="text-center text-danger">加载账号列表失败</td></tr>`;
        }
    }
    
    function formatElapsedTime(startTimeString) {
        const startTime = new Date(startTimeString);
        const now = new Date();
        let seconds = Math.floor((now - startTime) / 1000);
        if (seconds < 60) return `不到1分钟`;
        const days = Math.floor(seconds / (3600 * 24));
        seconds -= days * 3600 * 24;
        const hours = Math.floor(seconds / 3600);
        seconds -= hours * 3600;
        const minutes = Math.floor(seconds / 60);
        let parts = [];
        if (days > 0) parts.push(`${days}天`);
        if (hours > 0) parts.push(`${hours}小时`);
        if (minutes > 0) parts.push(`${minutes}分钟`);
        return parts.join('') || '不到1分钟';
    }
    
    function formatDuration(startTimeString, endTimeString) {
        if (!startTimeString || !endTimeString) {
            return '未知';
        }
        const startTime = new Date(startTimeString);
        const endTime = new Date(endTimeString);
        let seconds = Math.floor((endTime - startTime) / 1000);

        if (isNaN(seconds) || seconds < 0) return '未知';
        if (seconds < 60) return `${seconds}秒`;

        const days = Math.floor(seconds / (3600 * 24));
        seconds -= days * 3600 * 24;
        const hours = Math.floor(seconds / 3600);
        seconds -= hours * 3600;
        const minutes = Math.floor(seconds / 60);
        
        let parts = [];
        if (days > 0) parts.push(`${days}天`);
        if (hours > 0) parts.push(`${hours}小时`);
        if (minutes > 0) parts.push(`${minutes}分钟`);
        
        return parts.join('') || '不到1分钟';
    }


    async function loadTgConfig() {
        try {
            const config = await apiRequest('/oci/api/tg-config');
            tgBotTokenInput.value = config.bot_token || '';
            tgChatIdInput.value = config.chat_id || '';
        } catch (error) {
            addLog('加载 Telegram 配置失败。', 'warning');
        }
    }

    async function loadCloudflareConfig() {
        try {
            const config = await apiRequest('/oci/api/cloudflare-config');
            cloudflareApiTokenInput.value = config.api_token || '';
            cloudflareZoneIdInput.value = config.zone_id || '';
            cloudflareDomainInput.value = config.domain || '';
        } catch (error) {
            addLog('加载 Cloudflare 配置失败。', 'warning');
        }
    }

    saveTgConfigBtn.addEventListener('click', async () => {
        const token = tgBotTokenInput.value.trim();
        const chatId = tgChatIdInput.value.trim();
        if (!token || !chatId) return addLog('Bot Token 和 Chat ID 均不能为空。', 'error');
        
        const spinner = saveTgConfigBtn.querySelector('.spinner-border');
        saveTgConfigBtn.disabled = true;
        spinner.classList.remove('d-none');
        try {
            const response = await apiRequest('/oci/api/tg-config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bot_token: token, chat_id: chatId })
            });
            addLog(response.message, 'success');
        } finally {
            saveTgConfigBtn.disabled = false;
            spinner.classList.add('d-none');
        }
    });
    
    saveCloudflareConfigBtn.addEventListener('click', async () => {
        const apiToken = cloudflareApiTokenInput.value.trim();
        const zoneId = cloudflareZoneIdInput.value.trim();
        const domain = cloudflareDomainInput.value.trim();
        if (!apiToken || !zoneId || !domain) {
            return addLog('Cloudflare API 令牌、Zone ID 和主域名均不能为空。', 'error');
        }

        const spinner = saveCloudflareConfigBtn.querySelector('.spinner-border');
        saveCloudflareConfigBtn.disabled = true;
        spinner.classList.remove('d-none');
        try {
            const response = await apiRequest('/oci/api/cloudflare-config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_token: apiToken, zone_id: zoneId, domain: domain })
            });
            addLog(response.message, 'success');
            cloudflareSettingsModal.hide();
        } finally {
            saveCloudflareConfigBtn.disabled = false;
            spinner.classList.add('d-none');
        }
    });


    getApiKeyBtn.addEventListener('click', async () => {
        addLog('正在获取API密钥...');
        try {
            const data = await apiRequest('/api/get-app-api-key'); 
            if (data.api_key) {
                apiKeyInput.value = data.api_key;
                navigator.clipboard.writeText(data.api_key).then(() => {
                    addLog('API密钥已成功复制到剪贴板！', 'success');
                    getApiKeyBtn.textContent = '已复制!';
                    setTimeout(() => { getApiKeyBtn.textContent = '获取/复制密钥'; }, 2000);
                }).catch(() => addLog('自动复制失败，请手动复制。', 'warning'));
            }
        } catch (error) {}
    });
    
    async function saveProfile(alias, profileData) {
        try {
            await apiRequest('/oci/api/profiles', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify({ alias, profile_data: profileData }) 
            });
            addLog(`账号 ${alias} 添加成功!`, 'success');
            [newProfileAlias, newProfileConfigText].forEach(el => el.value = '');
            newProfileKeyFile.value = '';
            document.getElementById('accountSshKeyFile').value = ''; // Clear file inputs
            addAccountModal.hide();
            loadProfiles();
        } catch (error) {}
    }

    addNewProfileBtnModal.addEventListener('click', () => {
        const alias = newProfileAlias.value.trim();
        const configText = newProfileConfigText.value.trim();
        // === MODIFICATION: Read from the correct ID ===
        const sshKeyFile = document.getElementById('accountSshKeyFile').files[0]; // Get the pubkey file
        const keyFile = newProfileKeyFile.files[0]; // Get the private key file

        if (!alias || !configText || !keyFile) {
            addLog('账号名称, 配置信息和私钥文件都不能为空', 'error');
            return;
        }
        
        addLog(`正在添加账号: ${alias}...`);
        const profileData = {};
        configText.split('\n').forEach(line => {
            const parts = line.split('=').map(p => p.trim());
            if (parts.length === 2) profileData[parts[0]] = parts[1];
        });
        
        const privateKeyReader = new FileReader();
        privateKeyReader.onload = (event) => {
            profileData['key_content'] = event.target.result;
            
            // Now check for the public key
            if (sshKeyFile) {
                // If user uploaded a specific SSH key, read it
                addLog('正在读取上传的 SSH 公钥...', 'info');
                const publicKeyReader = new FileReader();
                publicKeyReader.onload = (e) => {
                    profileData['default_ssh_public_key'] = e.target.result;
                    saveProfile(alias, profileData); // Save with specific pubkey
                };
                publicKeyReader.onerror = () => addLog('读取公钥文件失败！', 'error');
                publicKeyReader.readAsText(sshKeyFile);
            } else {
                // No specific key uploaded, fetch global default
                addLog('未上传SSH公钥，正在尝试使用全局默认公钥...', 'info');
                apiRequest('/oci/api/default-ssh-key').then(response => {
                    if (response.key) {
                        addLog('已应用全局默认公钥。', 'success');
                        profileData['default_ssh_public_key'] = response.key;
                    } else {
                        addLog('未找到全局默认公钥，此账号将不含公钥。', 'warning');
                        profileData['default_ssh_public_key'] = '';
                    }
                    saveProfile(alias, profileData); // Save with global pubkey (or empty)
                }).catch(error => {
                    addLog('获取全局公钥失败，将保存为空。', 'error');
                    profileData['default_ssh_public_key'] = '';
                    saveProfile(alias, profileData);
                });
            }
        };
        privateKeyReader.onerror = () => addLog('读取私钥文件失败！', 'error');
        privateKeyReader.readAsText(keyFile);
    });

    profileList.addEventListener('click', async (e) => {
        const connectBtn = e.target.closest('.connect-btn');
        const proxyBtn = e.target.closest('.proxy-btn');
        const editBtn = e.target.closest('.edit-btn');
        const deleteBtn = e.target.closest('.delete-btn');
    
        if (connectBtn) {
            const alias = connectBtn.dataset.alias;
            const row = connectBtn.closest('tr');
    
            if (row.classList.contains('profile-disabled')) {
                addLog(`账号 ${alias} 已连接，无需重复操作。`, 'warning');
                return;
            }
    
            addLog(`正在连接到 ${alias}...`);
            
            document.querySelectorAll('#profileList tr').forEach(otherRow => {
                otherRow.classList.add('profile-disabled');
            });
    
            try {
                const response = await apiRequest('/oci/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ alias }) });
                addLog(response.message, 'success');
                await refreshInstances();
            } catch (error) {
            } finally {
                checkSession(false);
            }
        } 
        else if (proxyBtn) {
            const alias = proxyBtn.dataset.alias;
            try {
                addLog(`加载 ${alias} 的代理设置...`);
                const profileData = await apiRequest(`/oci/api/profiles/${alias}`);
                proxySettingsAlias.value = alias;
                proxyUrlInput.value = profileData.proxy || '';
                proxySettingsModal.show();
            } catch (error) {}
        } 
        else if (editBtn) {
            const alias = editBtn.dataset.alias;
            try {
                addLog(`正在加载账号 ${alias} 的信息...`);
                const profileData = await apiRequest(`/oci/api/profiles/${alias}`);
                document.getElementById('editProfileOriginalAlias').value = alias;
                document.getElementById('editProfileAlias').value = alias;
                const { default_ssh_public_key, key_content, proxy, ...configParts } = profileData;
                document.getElementById('editProfileConfigText').value = Object.entries(configParts).map(([k, v]) => `${k || ''}=${v || ''}`).join('\n');
                document.getElementById('editProfileSshKey').value = default_ssh_public_key || '';
                document.getElementById('editProfileKeyFile').value = '';
                editProfileModal.show();
            } catch (error) {}
        } 
        else if (deleteBtn) {
            const alias = deleteBtn.dataset.alias;
            confirmActionModalLabel.textContent = '确认删除账号';
            confirmActionModalBody.textContent = `确定要删除账号 "${alias}" 吗？`;
            confirmActionModalTerminateOptions.classList.add('d-none');
            confirmActionModalConfirmBtn.onclick = async () => {
                confirmActionModal.hide();
                try {
                    addLog(`正在删除账号: ${alias}...`);
                    await apiRequest(`/oci/api/profiles/${alias}`, { method: 'DELETE' });
                    addLog('删除成功!', 'success');
                    loadProfiles();
                } catch (error) {}
            };
            confirmActionModal.show();
        }
    });

    document.getElementById('saveProfileChangesBtn').addEventListener('click', async () => {
        const originalAlias = document.getElementById('editProfileOriginalAlias').value;
        const newAlias = document.getElementById('editProfileAlias').value.trim();
        const configText = document.getElementById('editProfileConfigText').value.trim();
        const sshKey = document.getElementById('editProfileSshKey').value.trim();
        const keyFile = document.getElementById('editProfileKeyFile').files[0];
        if (!newAlias || !configText || !sshKey) return addLog('账号名称、配置信息和SSH公钥不能为空', 'error');

        addLog(`正在保存对账号 ${originalAlias} 的更改...`);
        try {
            const profileData = await apiRequest(`/oci/api/profiles/${originalAlias}`);
            configText.split('\n').forEach(line => {
                const parts = line.split('=').map(p => p.trim());
                if (parts.length === 2) profileData[parts[0]] = parts[1];
            });
            profileData['default_ssh_public_key'] = sshKey;

            const saveChanges = async () => {
                const { user, fingerprint, tenancy, region, key_content, default_ssh_public_key, proxy } = profileData;
                const cleanProfileData = { user, fingerprint, tenancy, region, key_content, default_ssh_public_key, proxy };

                if (originalAlias !== newAlias) {
                    await apiRequest(`/oci/api/profiles/${originalAlias}`, { method: 'DELETE' });
                }
                await apiRequest('/oci/api/profiles', { 
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, 
                    body: JSON.stringify({ alias: newAlias, profile_data: cleanProfileData }) 
                });
                addLog(`账号 ${newAlias} 保存成功!`, 'success');
                editProfileModal.hide();
                loadProfiles();
            };

            if (keyFile) {
                const reader = new FileReader();
                reader.onload = (event) => { profileData['key_content'] = event.target.result; saveChanges(); };
                reader.readAsText(keyFile);
            } else {
                saveChanges();
            }
        } catch (error) {}
    });
    
    async function saveProxy(remove = false) {
        const alias = proxySettingsAlias.value;
        const proxyUrl = remove ? "" : proxyUrlInput.value.trim();
        
        if (!alias) return;
        
        addLog(`正在为账号 ${alias} ${remove ? '移除' : '保存'} 代理...`);
        try {
            const payload = { alias: alias, profile_data: { proxy: proxyUrl } };
            await apiRequest('/oci/api/profiles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            addLog(`账号 ${alias} 的代理设置已${remove ? '移除' : '更新'}！`, 'success');
            proxySettingsModal.hide();
        } catch (error) {}
    }

    saveProxyBtn.addEventListener('click', () => saveProxy(false));
    removeProxyBtn.addEventListener('click', () => saveProxy(true));

    instanceList.addEventListener('click', (e) => {
        const row = e.target.closest('tr');
        if (!row || !row.dataset.instanceId) return;
        
        document.querySelectorAll('#instanceList tr.table-active').forEach(r => r.classList.remove('table-active'));
        row.classList.add('table-active');
        selectedInstance = JSON.parse(row.dataset.instanceData);
        
        const state = selectedInstance.lifecycle_state;
        const isTerminated = ['TERMINATED', 'TERMINATING'].includes(state);
        Object.values(instanceActionButtons).forEach(btn => btn.disabled = isTerminated);
        instanceActionButtons.start.disabled = state !== 'STOPPED';
        instanceActionButtons.stop.disabled = state !== 'RUNNING';
        instanceActionButtons.restart.disabled = state !== 'RUNNING';
        instanceActionButtons.changeIp.disabled = state !== 'RUNNING';
        instanceActionButtons.assignIpv6.disabled = !(state === 'RUNNING' && selectedInstance.vnic_id);
    });
    
    async function loadSnatchTasks() {
        runningSnatchTasksList.innerHTML = '<li class="list-group-item">正在加载...</li>';
        completedSnatchTasksList.innerHTML = '<li class="list-group-item">正在加载...</li>';
        
        stopSnatchTaskBtn.disabled = true;
        resumeSnatchTaskBtn.disabled = true;
        deleteSnatchTaskBtn.disabled = true;
        deleteCompletedBtn.disabled = true;

        document.getElementById('selectAllRunningTasks').checked = false;
        document.getElementById('selectAllCompletedTasks').checked = false;
        
        try {
            const [running, completed] = await Promise.all([
                apiRequest('/oci/api/tasks/snatching/running'),
                apiRequest('/oci/api/tasks/snatching/completed')
            ]);
            
            if (running && running.length > 0) {
                if (!window.taskPollers) window.taskPollers = {};
                running.forEach(task => {
                    if (task.status === 'running' && !window.taskPollers[task.id]) {
                        console.log(`Re-initiating poller for running task: ${task.id}`);
                        pollTaskStatus(task.id, true);
                    }
                });
            }

            runningSnatchTasksList.innerHTML = running.length === 0
                ? '<li class="list-group-item text-muted">没有正在运行或已暂停的任务。</li>'
                : running.map(task => {
                    if (task.result && typeof task.result === 'object' && task.result.details) {
                        const { details, start_time, attempt_count, last_message } = task.result;
                        const taskName = details.display_name_prefix || details.name;
                        const isPaused = task.status === 'paused';
                        const statusBadge = isPaused 
                            ? `<span class="badge bg-secondary">已暂停</span>`
                            : `<span class="badge bg-warning text-dark">第 ${attempt_count} 次尝试</span>`;
                        const progressBar = isPaused
                            ? `<div class="progress" style="height: 5px;"><div class="progress-bar bg-secondary" style="width: 100%"></div></div>`
                            : `<div class="progress" style="height: 5px;"><div class="progress-bar progress-bar-striped progress-bar-animated" style="width: 100%"></div></div>`;
                        
                        const configString = `<strong>配置:</strong> ${details.shape} / ${details.ocpus || 'N/A'} OCPU / ${details.memory_in_gbs || 'N/A'} GB / ${details.boot_volume_size || 'N/A'} GB<br><strong>系统:</strong> ${details.os_name_version}`;

                        return `
                        <li class="list-group-item" data-task-id="${task.id}" data-task-status="${task.status}">
                            <div class="row align-items-center">
                                <div class="col-auto"><input class="form-check-input task-checkbox" type="checkbox" data-task-id="${task.id}" style="transform: scale(1.2);"></div>
                                <div class="col">
                                    <div class="d-flex justify-content-between align-items-start">
                                        <div><strong><span class="badge bg-primary me-2">${task.account_alias}</span><code>${taskName}</code></strong><p class="mb-1 small text-muted">开始于: ${new Date(start_time).toLocaleString()}</p></div>
                                        <div class="text-end">${statusBadge}</div>
                                    </div>
                                    <div class="bg-light p-2 rounded small mt-1">${configString}<br><strong>可用域:</strong> <code>${details.ad || '未知'}</code><br><strong>执行时长:</strong> ${formatElapsedTime(start_time)}</div>
                                    <div class="mt-2">${progressBar}<p class="mb-0 mt-1 small text-info-emphasis"><strong>最新状态:</strong> ${last_message}</p></div>
                                </div>
                            </div>
                        </li>`;
                    }
                    return `<li class="list-group-item" data-task-id="${task.id}" data-task-status="${task.status}"><div class="d-flex w-100 align-items-center"><input class="form-check-input task-checkbox" type="checkbox" data-task-id="${task.id}"><div class="ms-3 flex-grow-1"><strong><span class="badge bg-primary me-2">${task.account_alias}</span>${task.name}</strong><br><small class="text-muted">${String(task.result)}</small></div></div></li>`;
                }).join('');

            completedSnatchTasksList.innerHTML = completed.length === 0
                ? '<li class="list-group-item text-muted">没有已完成的抢占任务记录。</li>'
                : completed.map(task => {
                    // --- ✨ 修复开始 ✨ ---
                    // 直接使用 task.created_at 作为开始时间
                    const startTime = task.created_at; 
                    const durationText = formatDuration(startTime, task.completed_at || task.created_at);
                    // --- ✨ 修复结束 ✨ ---
                    const timeInfo = `
                        <small class="text-muted d-block">完成于: ${new Date(task.completed_at || task.created_at).toLocaleString()}</small>
                        <small class="text-muted d-block">总用时: ${durationText}</small>
                    `;

                    return `
                    <li class="list-group-item list-group-item-action" data-task-id="${task.id}">
                        <div class="d-flex w-100 align-items-center">
                            <input class="form-check-input task-checkbox" type="checkbox" data-task-id="${task.id}">
                            <div class="ms-3 flex-grow-1 d-flex justify-content-between align-items-center">
                                <div><strong><span class="badge bg-secondary me-2">${task.account_alias}</span>${task.name}</strong><br>${timeInfo}</div>
                                <span class="badge bg-${task.status === 'success' ? 'success' : 'danger'}">${task.status === 'success' ? '成功' : '失败'}</span>
                            </div>
                        </div>
                    </li>`
                }).join('');
        } catch (e) {
            runningSnatchTasksList.innerHTML = '<li class="list-group-item list-group-item-danger">加载正在运行任务失败。</li>';
            completedSnatchTasksList.innerHTML = '<li class="list-group-item list-group-item-danger">加载已完成任务失败。</li>';
        }
    }
    
    completedSnatchTasksList.addEventListener('dblclick', async e => {
        const listItem = e.target.closest('li.list-group-item[data-task-id]');
        if (!listItem) return;
        try {
            const data = await apiRequest(`/oci/api/task_status/${listItem.dataset.taskId}`);
            document.getElementById('taskResultModalLabel').textContent = `任务结果: ${listItem.dataset.taskId}`;
            document.getElementById('taskResultModalBody').innerHTML = `<pre>${data.result}</pre>`;
            taskResultModal.show();
        } catch (error) {}
    });
    
    stopSnatchTaskBtn.addEventListener('click', () => handleTaskAction('stop', '#runningSnatchTasksList'));
    resumeSnatchTaskBtn.addEventListener('click', () => handleTaskAction('resume', '#runningSnatchTasksList'));
    deleteSnatchTaskBtn.addEventListener('click', () => handleTaskAction('delete', '#runningSnatchTasksList'));
    deleteCompletedBtn.addEventListener('click', () => handleTaskAction('delete', '#completedSnatchTasksList'));

    document.getElementById('selectAllRunningTasks').addEventListener('change', (e) => toggleSelectAll(e.target, '#runningSnatchTasksList'));
    document.getElementById('selectAllCompletedTasks').addEventListener('change', (e) => toggleSelectAll(e.target, '#completedSnatchTasksList'));
    
    runningSnatchTasksList.addEventListener('change', () => updateRunningActionButtons());
    completedSnatchTasksList.addEventListener('change', () => updateCompletedActionButtons());
    
    function toggleSelectAll(masterCheckbox, listSelector) {
        document.querySelectorAll(`${listSelector} .task-checkbox`).forEach(chk => chk.checked = masterCheckbox.checked);
        if (listSelector === '#runningSnatchTasksList') {
            updateRunningActionButtons();
        } else {
            updateCompletedActionButtons();
        }
    }

    function updateRunningActionButtons() {
        const checked = Array.from(document.querySelectorAll('#runningSnatchTasksList .task-checkbox:checked'));
        if (checked.length === 0) {
            stopSnatchTaskBtn.disabled = true;
            resumeSnatchTaskBtn.disabled = true;
            deleteSnatchTaskBtn.disabled = true;
            return;
        }
        
        const statuses = checked.map(chk => chk.closest('li').dataset.taskStatus);
        
        const allPaused = statuses.every(s => s === 'paused');
        const anyRunning = statuses.some(s => s === 'running');
        const anyPaused = statuses.some(s => s === 'paused');
        
        stopSnatchTaskBtn.disabled = !anyRunning || anyPaused;
        resumeSnatchTaskBtn.disabled = !anyPaused || anyRunning;
        deleteSnatchTaskBtn.disabled = !allPaused;
    }

    function updateCompletedActionButtons() {
        deleteCompletedBtn.disabled = document.querySelectorAll('#completedSnatchTasksList .task-checkbox:checked').length === 0;
    }
    
    async function handleTaskAction(action, listSelector) {
        const checked = document.querySelectorAll(`${listSelector} .task-checkbox:checked`);
        if (checked.length === 0) return addLog('请先选择任务', 'warning');

        const taskIds = Array.from(checked).map(cb => cb.dataset.taskId);
        const actionTextMap = { 'stop': '暂停', 'delete': '删除', 'resume': '恢复' };
        const actionText = actionTextMap[action];

        confirmActionModalLabel.textContent = `确认${actionText}任务`;
        confirmActionModalBody.textContent = `确定要${actionText}选中的 ${taskIds.length} 个任务吗？`;
        confirmActionModalConfirmBtn.onclick = async () => {
            confirmActionModal.hide();
            addLog(`正在${actionText} ${taskIds.length} 个任务...`);
            
            try {
                if (action === 'resume') {
                    const response = await apiRequest(`/oci/api/tasks/resume`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_ids: taskIds })
                    });
                    addLog(response.message, 'success');
                } else {
                    const endpoint = action === 'stop' ? '/stop' : '';
                    const method = action === 'stop' ? 'POST' : 'DELETE';
                    await Promise.all(taskIds.map(id => apiRequest(`/oci/api/tasks/${id}${endpoint}`, { method })));
                    addLog(`任务${actionText}请求已发送`, 'success');
                }
                loadSnatchTasks();
            } catch (error) {}
        };
        confirmActionModal.show();
    }
    
    Object.entries(instanceActionButtons).forEach(([key, button]) => {
        if (key !== 'editInstance') button.addEventListener('click', () => performInstanceAction(key.toLowerCase()));
    });
    
    async function performInstanceAction(action) {
        if (!selectedInstance) return addLog('请先选择一个实例', 'warning');
        let message = `确定要对实例 "${selectedInstance.display_name}" 执行 "${action}" 操作吗?`;
        let title = `请确认: ${action}`;
        if (action === 'terminate') {
            title = `!!! 警告: 终止实例 !!!`;
            message = `此操作无法撤销，确定要终止实例 "${selectedInstance.display_name}" 吗?`;
            confirmActionModalTerminateOptions.classList.remove('d-none');
            confirmDeleteVolumeCheck.checked = false; 
        } else {
            confirmActionModalTerminateOptions.classList.add('d-none');
        }
        if (action === 'changeip') message = `确定更换实例 "${selectedInstance.display_name}" 的公网 IP (IPV4) 吗？\n将尝试删除旧临时IP并创建新临时IP。如果已配置Cloudflare，将自动更新DNS解析。`;
        if (action === 'assignipv6') message = `确定要为实例 "${selectedInstance.display_name}" 分配/更换一个 IPV6 地址吗？如果已配置Cloudflare，将自动更新DNS解析。`;
        
        confirmActionModalLabel.textContent = title;
        confirmActionModalBody.innerHTML = message.replace(/\n/g, '<br>');
        confirmActionModalConfirmBtn.onclick = async () => {
            confirmActionModal.hide(); 
            const payload = {
                action,
                instance_id: selectedInstance.id,
                instance_name: selectedInstance.display_name,
                vnic_id: selectedInstance.vnic_id,
                subnet_id: selectedInstance.subnet_id,
                preserve_boot_volume: action === 'terminate' ? !confirmDeleteVolumeCheck.checked : undefined
            };
            addLog(`正在为实例 ${selectedInstance.display_name} 提交 ${action} 请求...`);
            try {
                const response = await apiRequest('/oci/api/instance-action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                addLog(response.message, 'success');
                if (response.task_id) pollTaskStatus(response.task_id);
            } catch(e) {}
        };
        confirmActionModal.show();
    }

    instanceActionButtons.editInstance.addEventListener('click', async () => {
        if (!selectedInstance) return addLog('请先选择一个实例', 'warning');
        try {
            addLog(`正在获取实例 ${selectedInstance.display_name} 的详细信息...`);
            const details = await apiRequest(`/oci/api/instance-details/${selectedInstance.id}`);
            editDisplayName.value = details.display_name;
            editBootVolumeSize.value = details.boot_volume_size_in_gbs;
            editVpus.value = details.vpus_per_gb;
            editFlexInstanceConfig.classList.toggle('d-none', !details.shape.toLowerCase().includes('flex'));
            if (details.shape.toLowerCase().includes('flex')) {
                editOcpus.value = details.ocpus;
                editMemory.value = details.memory_in_gbs;
            }
            editInstanceModal.show();
        } catch(error) {}
    });
    async function handleInstanceUpdateRequest(action, payload) {
        addLog(`正在提交 ${action} 请求...`);
        try {
            const response = await apiRequest('/oci/api/update-instance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            addLog(response.message, 'success');
            if (response.task_id) pollTaskStatus(response.task_id);
            editInstanceModal.hide();
            setTimeout(refreshInstances, 3000);
        } catch(e) {}
    }
    saveDisplayNameBtn.addEventListener('click', () => handleInstanceUpdateRequest('修改名称', { action: 'update_display_name', instance_id: selectedInstance.id, display_name: editDisplayName.value }));
    saveFlexConfigBtn.addEventListener('click', () => handleInstanceUpdateRequest('修改CPU/内存', { action: 'update_shape', instance_id: selectedInstance.id, ocpus: parseInt(editOcpus.value, 10), memory_in_gbs: parseInt(editMemory.value, 10) }));
    saveBootVolumeSizeBtn.addEventListener('click', () => handleInstanceUpdateRequest('修改引导卷大小', { action: 'update_boot_volume', instance_id: selectedInstance.id, size_in_gbs: parseInt(editBootVolumeSize.value, 10) }));
    saveVpusBtn.addEventListener('click', () => handleInstanceUpdateRequest('修改引导卷性能', { action: 'update_boot_volume', instance_id: selectedInstance.id, vpus_per_gb: parseInt(editVpus.value, 10) }));
    
    // --- ✨ MODIFICATION START ✨ ---
    // 缓存网络资源
    let allNetworkResources = [];

    // 新增: 辅助函数，用于加载特定安全列表的规则
    async function loadSecurityListRules(securityListId) {
        if (!securityListId) {
            renderRules('ingress', []);
            renderRules('egress', []);
            return;
        }
        
        networkRulesSpinner.classList.remove('d-none');
        saveNetworkRulesBtn.disabled = true;
        try {
            // 3. 调用新的详情API
            const slDetails = await apiRequest(`/oci/api/network/security-list/${securityListId}`);
            currentSecurityList = slDetails; // 存储完整的详情，保存时需要用到ID
            renderRules('ingress', slDetails.ingress_security_rules);
            renderRules('egress', slDetails.egress_security_rules);
        } catch (error) {
            addLog(`加载安全列表 ${securityListId} 规则失败`, 'error');
            renderRules('ingress', []);
            renderRules('egress', []);
        } finally {
            networkRulesSpinner.classList.add('d-none');
            saveNetworkRulesBtn.disabled = false;
        }
    }

    // 新增: VCN 下拉菜单的 'change' 事件监听
    vcnSelect.addEventListener('change', () => {
        const selectedVcnId = vcnSelect.value;
        const vcnData = allNetworkResources.find(v => v.vcn_id === selectedVcnId);
        
        securityListSelect.innerHTML = ''; // 清空安全列表下拉
        if (vcnData && vcnData.security_lists.length > 0) {
            vcnData.security_lists.forEach(sl => {
                const option = new Option(sl.display_name, sl.id);
                securityListSelect.add(option);
            });
            securityListSelect.disabled = false;
            // 自动触发 'change' 以加载第一个安全列表的规则
            securityListSelect.dispatchEvent(new Event('change')); 
        } else {
            securityListSelect.innerHTML = '<option value="">无安全列表</option>';
            securityListSelect.disabled = true;
            loadSecurityListRules(null); // 清空规则
        }
    });
    
    // 新增: 安全列表下拉菜单的 'change' 事件监听
    securityListSelect.addEventListener('change', () => {
        const selectedSlId = securityListSelect.value;
        loadSecurityListRules(selectedSlId);
    });

    // 替换 'networkSettingsBtn' 的 'click' 事件监听
    networkSettingsBtn.addEventListener('click', async () => {
        // 1. 打开模态框时，重置UI
        vcnSelect.innerHTML = '<option value="">正在加载 VCN...</option>';
        securityListSelect.innerHTML = '<option value="">请先选择VCN</option>';
        vcnSelect.disabled = true;
        securityListSelect.disabled = true;
        renderRules('ingress', []);
        renderRules('egress', []);
        networkRulesSpinner.classList.remove('d-none');
        
        try {
            addLog("正在获取所有网络资源...");
            // 2. 调用新的资源API
            allNetworkResources = await apiRequest('/oci/api/network/resources');
            networkRulesSpinner.classList.add('d-none');
            
            if (allNetworkResources.length === 0) {
                vcnSelect.innerHTML = '<option value="">未找到VCN</option>';
                return;
            }

            vcnSelect.innerHTML = ''; // 清空 "loading"
            allNetworkResources.forEach(vcn => {
                const option = new Option(vcn.vcn_name, vcn.vcn_id);
                vcnSelect.add(option);
            });
            vcnSelect.disabled = false;
            
            // 自动触发 'change' 来填充第一个VCN的安全列表
            vcnSelect.dispatchEvent(new Event('change'));

        } catch (error) {
            networkRulesSpinner.classList.add('d-none');
            vcnSelect.innerHTML = '<option value="">加载失败</option>';
            addLog('获取网络资源列表失败。', 'error');
        }
    });
    // --- ✨ MODIFICATION END ✨ ---

    function renderRules(type, rules) {
        const tableBody = type === 'ingress' ? ingressRulesTable : egressRulesTable;
        tableBody.innerHTML = !rules || rules.length === 0 
            ? `<tr><td colspan="6" class="text-center text-muted">没有规则</td></tr>`
            : rules.map(rule => createRuleRow(type, rule).outerHTML).join('');
        tableBody.querySelectorAll('.remove-rule-btn').forEach(btn => btn.onclick = () => btn.closest('tr').remove());
    }

    function createRuleRow(type, rule = {}) {
        const tr = document.createElement('tr');
        tr.className = 'rule-row';
        const sourceOrDest = type === 'ingress' ? (rule.source || '0.0.0.0/0') : (rule.destination || '0.0.0.0/0');
        const protocol = rule.protocol || '6';
        const protocolOptions = {'all': '所有', '1': 'ICMP', '6': 'TCP', '17': 'UDP'};
        const portRange = (options) => ({ min: options?.min || '', max: options?.max || '' });
        const destPorts = portRange(rule.tcp_options ? rule.tcp_options.destination_port_range : (rule.udp_options ? rule.udp_options.destination_port_range : null));
        const srcPorts = portRange(rule.tcp_options ? rule.tcp_options.source_port_range : (rule.udp_options ? rule.udp_options.source_port_range : null));
        tr.innerHTML = `
            <td><input class="form-check-input" type="checkbox" data-key="is_stateless" ${rule.is_stateless ? 'checked' : ''}></td>
            <td><input type="text" class="form-control form-control-sm" data-key="${type === 'ingress' ? 'source' : 'destination'}" value="${sourceOrDest}"></td>
            <td><select class="form-select form-select-sm" data-key="protocol">${Object.entries(protocolOptions).map(([k, v]) => `<option value="${k}" ${protocol == k ? 'selected' : ''}>${v}</option>`).join('')}</select></td>
            <td><div class="input-group input-group-sm"><input type="number" class="form-control" placeholder="Min" data-key="src_port_min" value="${srcPorts.min}"><input type="number" class="form-control" placeholder="Max" data-key="src_port_max" value="${srcPorts.max}"></div></td>
            <td><div class="input-group input-group-sm"><input type="number" class="form-control" placeholder="Min" data-key="dest_port_min" value="${destPorts.min}"><input type="number" class="form-control" placeholder="Max" data-key="dest_port_max" value="${destPorts.max}"></div></td>
            <td><button class="btn btn-sm btn-danger remove-rule-btn"><i class="bi bi-trash"></i></button></td>`;
        return tr;
    }
    
    addIngressRuleBtn.addEventListener('click', () => {
        const placeholderRow = ingressRulesTable.querySelector('td[colspan="6"]');
        if (placeholderRow) placeholderRow.parentElement.remove();
        ingressRulesTable.appendChild(createRuleRow('ingress'));
    });
    addEgressRuleBtn.addEventListener('click', () => {
        const placeholderRow = egressRulesTable.querySelector('td[colspan="6"]');
        if (placeholderRow) placeholderRow.parentElement.remove();
        egressRulesTable.appendChild(createRuleRow('egress'));
    });

    openFirewallBtn.addEventListener('click', () => {
        let ingressAdded = false;
        let egressAdded = false;

        const currentIngressRules = collectRulesFromTable(ingressRulesTable, 'ingress');
        const ingressExists = currentIngressRules.some(rule => rule.protocol === 'all' && rule.source === '0.0.0.0/0');

        if (!ingressExists) {
            const allowAllIngressRule = {
                source: '0.0.0.0/0',
                protocol: 'all',
                is_stateless: false
            };
            const ingressPlaceholder = ingressRulesTable.querySelector('td[colspan="6"]');
            if (ingressPlaceholder) ingressPlaceholder.parentElement.remove();
            ingressRulesTable.appendChild(createRuleRow('ingress', allowAllIngressRule));
            ingressAdded = true;
        }

        const currentEgressRules = collectRulesFromTable(egressRulesTable, 'egress');
        const egressExists = currentEgressRules.some(rule => rule.protocol === 'all' && rule.destination === '0.0.0.0/0');

        if (!egressExists) {
            const allowAllEgressRule = {
                destination: '0.0.0.0/0',
                protocol: 'all',
                is_stateless: false
            };
            const egressPlaceholder = egressRulesTable.querySelector('td[colspan="6"]');
            if (egressPlaceholder) egressPlaceholder.parentElement.remove();
            egressRulesTable.appendChild(createRuleRow('egress', allowAllEgressRule));
            egressAdded = true;
        }

        if (ingressAdded || egressAdded) {
            let message = '已添加 "允许所有" 的';
            if (ingressAdded && egressAdded) {
                message += '出入站规则';
            } else if (ingressAdded) {
                message += '入站规则';
            } else {
                message += '出站规则';
            }
            message += '，请点击 "保存更改" 以生效。';
            addLog(message, 'warning');
        } else {
            addLog('无需操作，允许所有的出入站规则均已存在。', 'info');
        }
    });

    saveNetworkRulesBtn.addEventListener('click', async () => {
        const spinner = saveNetworkRulesBtn.querySelector('.spinner-border');
        saveNetworkRulesBtn.disabled = true;
        spinner.classList.remove('d-none');
        try {
            const rules = {
                ingress_security_rules: collectRulesFromTable(ingressRulesTable, 'ingress'),
                egress_security_rules: collectRulesFromTable(egressRulesTable, 'egress')
            };
            await apiRequest('/oci/api/network/update-security-rules', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify({ security_list_id: currentSecurityList.id, rules }) 
            });
            addLog('网络规则保存成功', 'success');
            networkSettingsModal.hide();
        } finally {
            saveNetworkRulesBtn.disabled = false;
            spinner.classList.add('d-none');
        }
    });

    function collectRulesFromTable(tableBody, type) {
        return Array.from(tableBody.querySelectorAll('.rule-row')).map(tr => {
            const rule = { is_stateless: tr.querySelector('[data-key="is_stateless"]').checked, protocol: tr.querySelector('[data-key="protocol"]').value };
            rule[type === 'ingress' ? 'source' : 'destination'] = tr.querySelector(`[data-key="${type === 'ingress' ? 'source' : 'destination'}"]`).value;
            rule[`${type === 'ingress' ? 'source' : 'destination'}_type`] = 'CIDR_BLOCK';
            
            if (['6', '17'].includes(rule.protocol)) {
                const dest_min = parseInt(tr.querySelector('[data-key="dest_port_min"]').value, 10);
                const dest_max = parseInt(tr.querySelector('[data-key="dest_port_max"]').value, 10);
                const src_min = parseInt(tr.querySelector('[data-key="src_port_min"]').value, 10);
                const src_max = parseInt(tr.querySelector('[data-key="src_port_max"]').value, 10);
                const options = {};
                if (!isNaN(dest_min) && !isNaN(dest_max)) options.destination_port_range = { min: dest_min, max: dest_max };
                if (!isNaN(src_min) && !isNaN(src_max)) options.source_port_range = { min: src_min, max: src_max };
                
                if (rule.protocol === '6') rule.tcp_options = options;
                else rule.udp_options = options;
            }
            return rule;
        });
    }

    // --- Initial Load ---
    
    // === MODIFICATION START: New function to save the global key ===
    async function saveGlobalSshKey() {
        // === MODIFICATION: Read from the correct ID ===
        const sshKeyFile = document.getElementById('globalSshKeyFile').files[0];
        if (!sshKeyFile) {
            addLog('请先在“全局默认SSH公钥管理”区域选择一个 .pub 文件。', 'error');
            return;
        }

        addLog('正在读取公钥文件以保存为全局默认...', 'info');
        const reader = new FileReader();
        reader.onload = async (event) => {
            const key = event.target.result.trim();
            if (!key || !(key.startsWith('ssh-rsa') || key.startsWith('ssh-ed25519') || key.startsWith('ecdsa-sha2-nistp'))) {
                addLog('无效的 SSH 公钥文件。请确保这是一个有效的公钥文件。', 'error');
                return;
            }

            try {
                const response = await apiRequest('/oci/api/default-ssh-key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: key })
                });
                addLog(response.message, 'success');
                // Refresh the status display
                loadAndDisplayDefaultKey();
                // Clear the file input
                document.getElementById('globalSshKeyFile').value = '';
            } catch (error) {
                // apiRequest already logs the error
            }
        };
        reader.onerror = () => {
            addLog('读取公钥文件失败！', 'error');
        };
        reader.readAsText(sshKeyFile);
    }
    // === MODIFICATION END ===


    // === MODIFICATION START: Updated loadAndDisplayDefaultKey function ===
    async function loadAndDisplayDefaultKey() {
        const statusEl = document.getElementById('defaultSshKeyStatusText');
        const buttonTextEl = document.getElementById('saveGlobalSshKeyBtnText');
        if (!statusEl || !buttonTextEl) return;
        
        statusEl.innerHTML = '<div class="spinner-border spinner-border-sm" role="status" style="width: 0.8rem; height: 0.8rem;"><span class="visually-hidden">Loading...</span></div> 正在检查...';
        
        try {
            const response = await apiRequest('/oci/api/default-ssh-key');
            if (response.key) {
                statusEl.innerHTML = '<strong class="text-success">✓ 已设置全局SSH公钥</strong>';
                buttonTextEl.textContent = '更新';
            } else {
                statusEl.innerHTML = '<strong class="text-warning">! 未设置全局SSH公钥</strong>';
                buttonTextEl.textContent = '保存';
            }
        } catch (error) {
            statusEl.innerHTML = '<strong class="text-danger">加载默认公钥状态失败。</strong>';
        }
    }
    // === MODIFICATION END ===

    // === MODIFICATION START: Attach listener for the global key button ===
    document.getElementById('saveGlobalSshKeyBtn').addEventListener('click', saveGlobalSshKey);
    // === MODIFICATION END ===

    new Sortable(profileList, {
        handle: '.drag-handle',
        animation: 150,
        onEnd: async function (evt) {
            const newOrder = Array.from(profileList.querySelectorAll('tr')).map(row => row.dataset.alias);
            
            try {
                await apiRequest('/oci/api/profiles/order', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ order: newOrder })
                });
                addLog('账号顺序已保存。', 'success');
            } catch (error) {
                addLog('保存账号顺序失败，将自动刷新列表。', 'error');
                loadProfiles();
            }
        },
    });

    loadProfiles();
    checkSession();
    loadTgConfig();
    loadCloudflareConfig();
    // loadAndDisplayDefaultKey(); // This is now called when the modal opens
});
