    document.addEventListener('DOMContentLoaded', function() {
        // DOM 元素获取
        const profileList = document.getElementById('profileList');
        const currentProfileStatus = document.getElementById('currentProfileStatus');
        const addNewProfileBtn = document.getElementById('addNewProfileBtn');
        const newProfileAlias = document.getElementById('newProfileAlias');
        const newProfileConfigText = document.getElementById('newProfileConfigText');
        const newProfileSshKey = document.getElementById('newProfileSshKey');
        const newProfileKeyFile = document.getElementById('newProfileKeyFile');
        const refreshInstancesBtn = document.getElementById('refreshInstancesBtn');
        const createInstanceBtn = document.getElementById('createInstanceBtn');
        const instanceList = document.getElementById('instanceList');
        const logOutput = document.getElementById('logOutput');
        const clearLogBtn = document.getElementById('clearLogBtn');
        const editProfileModal = new bootstrap.Modal(document.getElementById('editProfileModal'));
        const createInstanceModal = new bootstrap.Modal(document.getElementById('createInstanceModal'));
        const snatchInstanceBtn = document.getElementById('snatchInstanceBtn');
        const viewSnatchTasksBtn = document.getElementById('viewSnatchTasksBtn');
        const snatchInstanceModal = new bootstrap.Modal(document.getElementById('snatchInstanceModal'));
        const viewSnatchTasksModal = new bootstrap.Modal(document.getElementById('viewSnatchTasksModal'));
        const taskResultModal = new bootstrap.Modal(document.getElementById('taskResultModal'));
        const stopSnatchTaskBtn = document.getElementById('stopSnatchTaskBtn');
        const deleteSnatchTaskBtn = document.getElementById('deleteSnatchTaskBtn');
        const runningSnatchTasksList = document.getElementById('runningSnatchTasksList');
        const completedSnatchTasksList = document.getElementById('completedSnatchTasksList');
        const actionAreaProfile = document.getElementById('actionAreaProfile');
        
        // 实例操作按钮
        const instanceActionButtons = {
            start: document.getElementById('startBtn'),
            stop: document.getElementById('stopBtn'),
            restart: document.getElementById('restartBtn'),
            changeIp: document.getElementById('changeIpBtn'),
            assignIpv6: document.getElementById('assignIpv6Btn'),
            terminate: document.getElementById('terminateBtn'),
        };
    
        let selectedInstance = null;
        let runningTasksData = [];
        let completedTasksData = [];
    
        // --- 通用辅助函数 ---
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
        
        clearLogBtn.addEventListener('click', () => logOutput.innerHTML = '');
    
        async function apiRequest(url, options = {}) {
            try {
                const response = await fetch(url, options);
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP 错误! 状态: ${response.status}`);
                }
                 const text = await response.text();
                 return text ? JSON.parse(text) : {};
            } catch (error) {
                addLog(`请求失败: ${error.message}`, 'error');
                throw error;
            }
        }
    
        // --- 账号管理 ---
        async function loadProfiles() {
            profileList.innerHTML = `<tr><td colspan="2" class="text-center text-muted">正在加载...</td></tr>`;
            try {
                const profileNames = await apiRequest('/oci/api/profiles');
                profileList.innerHTML = '';
                if (profileNames.length === 0) {
                    profileList.innerHTML = `<tr><td colspan="2" class="text-center text-muted">未找到账号，请在左侧添加</td></tr>`;
                } else {
                    profileNames.forEach(name => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td>${name}</td>
                            <td class="text-end action-buttons">
                                <button class="btn btn-success btn-sm connect-btn profile-action-btn" data-alias="${name}">连接</button>
                                <button class="btn btn-info btn-sm edit-btn profile-action-btn" data-alias="${name}"><i class="bi bi-pencil"></i> 编辑</button>
                                <button class="btn btn-danger btn-sm delete-btn profile-action-btn" data-alias="${name}"><i class="bi bi-trash"></i> 删除</button>
                            </td>
                        `;
                        profileList.appendChild(tr);
                    });
                }
                checkSession(); 
            } catch (error) {
                profileList.innerHTML = `<tr><td colspan="2" class="text-center text-danger">加载账号列表失败</td></tr>`;
            }
        }
        
        addNewProfileBtn.addEventListener('click', async () => {
            const alias = newProfileAlias.value.trim();
            const configText = newProfileConfigText.value.trim();
            const sshKey = newProfileSshKey.value.trim();
            const keyFile = newProfileKeyFile.files[0];
    
            if (!alias || !configText || !sshKey || !keyFile) {
                return addLog('所有字段都不能为空', 'error');
            }
    
            try {
                addLog(`正在添加账号: ${alias}...`);
                const profileData = {};
                configText.split('\n').forEach(line => {
                    const parts = line.split('=');
                    if (parts.length === 2) profileData[parts[0].trim()] = parts[1].trim();
                });
    
                profileData['default_ssh_public_key'] = sshKey;
                
                const reader = new FileReader();
                reader.onload = async (event) => {
                    profileData['key_content'] = event.target.result;
                    const payload = { alias, profile_data: profileData };
                    await apiRequest('/oci/api/profiles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                    addLog(`账号 ${alias} 添加成功!`, 'success');
                    [newProfileAlias, newProfileConfigText, newProfileSshKey].forEach(el => el.value = '');
                    newProfileKeyFile.value = '';
                    loadProfiles();
                };
                reader.readAsText(keyFile);
    
            } catch (error) {
                addLog(`添加账号时出错: ${error.message}`, 'error');
            }
        });
    
        profileList.addEventListener('click', async (e) => {
            const button = e.target.closest('button');
            if (!button) return;
            const alias = button.dataset.alias;
            if (!alias) return;
    
            if (button.classList.contains('connect-btn')) {
                addLog(`正在连接到 ${alias}...`);
                try {
                    await apiRequest('/oci/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ alias }) });
                    addLog(`连接成功! 当前账号: ${alias}`, 'success');
                    checkSession();
                } catch (error) {}
            }
    
            if (button.classList.contains('edit-btn')) {
                addLog(`正在加载账号 ${alias} 的信息以供编辑...`);
                try {
                    const profileData = await apiRequest(`/oci/api/profiles/${alias}`);
                    document.getElementById('editProfileOriginalAlias').value = alias;
                    document.getElementById('editProfileAlias').value = alias;
                    
                    const { default_ssh_public_key, key_content, default_subnet_ocid, ...configParts } = profileData;
                    const configText = Object.entries(configParts).map(([k, v]) => `${k}=${v || ''}`).join('\n');
    
                    document.getElementById('editProfileConfigText').value = configText;
                    document.getElementById('editProfileSshKey').value = default_ssh_public_key || '';
                    document.getElementById('editProfileKeyFile').value = '';
                    
                    editProfileModal.show();
                } catch (error) {}
            }
    
            if (button.classList.contains('delete-btn')) {
                if (!confirm(`确定要删除账号 "${alias}" 吗?`)) return;
                addLog(`正在删除账号: ${alias}...`);
                try {
                    await apiRequest(`/oci/api/profiles/${alias}`, { method: 'DELETE' });
                    addLog('删除成功!', 'success');
                    loadProfiles();
                } catch (error) {}
            }
        });
    
        document.getElementById('saveProfileChangesBtn').addEventListener('click', async () => {
            const originalAlias = document.getElementById('editProfileOriginalAlias').value;
            const newAlias = document.getElementById('editProfileAlias').value.trim();
            const configText = document.getElementById('editProfileConfigText').value.trim();
            const sshKey = document.getElementById('editProfileSshKey').value.trim();
            const keyFile = document.getElementById('editProfileKeyFile').files[0];
    
            if (!newAlias || !configText || !sshKey) {
                return addLog('账号名称、配置信息和SSH公钥不能为空', 'error');
            }
    
            addLog(`正在保存对账号 ${originalAlias} 的更改...`);
            try {
                const originalProfileData = await apiRequest(`/oci/api/profiles/${originalAlias}`);
                const profileData = {...originalProfileData};
                
                configText.split('\n').forEach(line => {
                    const parts = line.split('=');
                    if (parts.length === 2) profileData[parts[0].trim()] = parts[1].trim();
                });
    
                profileData['default_ssh_public_key'] = sshKey;
                
                const saveChanges = async (finalProfileData) => {
                    if (originalAlias !== newAlias) {
                        if(confirm(`账号名称将从 "${originalAlias}" 更改为 "${newAlias}", 确定吗?`)){
                            await apiRequest(`/oci/api/profiles/${originalAlias}`, { method: 'DELETE' });
                            addLog(`旧账号名称 ${originalAlias} 已删除。`);
                        } else {
                            return;
                        }
                    }
                    const payload = { alias: newAlias, profile_data: finalProfileData };
                    await apiRequest('/oci/api/profiles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                    addLog(`账号 ${newAlias} 保存成功!`, 'success');
                    editProfileModal.hide();
                    loadProfiles();
                };
    
                if (keyFile) {
                    addLog('检测到新的私钥文件，将进行更新。');
                    const reader = new FileReader();
                    reader.onload = (event) => {
                        profileData['key_content'] = event.target.result;
                        saveChanges(profileData);
                    };
                    reader.readAsText(keyFile);
                } else {
                    saveChanges(profileData);
                }
            } catch (error) {}
        });
    
        // --- 会话与状态控制 ---
        async function checkSession() {
            try {
                const data = await apiRequest('/oci/api/session');
                
                document.querySelectorAll('.connect-btn').forEach(btn => {
                    btn.textContent = '连接';
                    btn.classList.remove('btn-secondary');
                    btn.classList.add('btn-success');
                    btn.disabled = false;
                });
    
                if (data.logged_in && data.alias) {
                    currentProfileStatus.textContent = `已连接: ${data.alias}`;
                    actionAreaProfile.textContent = `当前账号: ${data.alias}`;
                    actionAreaProfile.classList.remove('d-none');
                    enableMainControls(true, data.can_create, data.can_snatch);
                    refreshInstances();
    
                    const activeButton = document.querySelector(`.connect-btn[data-alias="${data.alias}"]`);
                    if (activeButton) {
                        activeButton.textContent = '已连接';
                        activeButton.classList.remove('btn-success');
                        activeButton.classList.add('btn-secondary');
                        activeButton.disabled = true;
                    }
                } else {
                    currentProfileStatus.textContent = '未连接';
                    actionAreaProfile.classList.add('d-none');
                    enableMainControls(false, false, false);
                }
            } catch (error) {
                 currentProfileStatus.textContent = '未连接 (会话检查失败)';
                 actionAreaProfile.classList.add('d-none');
                 enableMainControls(false, false, false);
            }
        }
        
        function enableMainControls(enabled, canCreate, canSnatch) {
            refreshInstancesBtn.disabled = !enabled;
            createInstanceBtn.disabled = !canCreate;
            snatchInstanceBtn.disabled = !canSnatch;
            
            if (!enabled) {
                instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-5">请先连接一个账号并刷新列表</td></tr>`;
                Object.values(instanceActionButtons).forEach(btn => btn.disabled = true);
            }
        }
    
        // --- 实例管理 ---
        async function refreshInstances() {
            addLog('正在刷新实例列表...');
            refreshInstancesBtn.disabled = true;
            instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-5"><div class="spinner-border spinner-border-sm"></div> 正在加载...</td></tr>`;
            
            try {
                const instances = await apiRequest('/oci/api/instances');
                instanceList.innerHTML = '';
                if (instances.length === 0) {
                     instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-5">未找到任何实例</td></tr>`;
                } else {
                    instances.forEach(inst => {
                        const tr = document.createElement('tr');
                        tr.dataset.instanceId = inst.id;
                        tr.dataset.instanceData = JSON.stringify(inst);
                        const state = inst.lifecycle_state;
                        let dotClass = 'status-other';
                        if (state === 'RUNNING') dotClass = 'status-running';
                        if (state === 'STOPPED') dotClass = 'status-stopped';
                        tr.innerHTML = `
                            <td style="text-align: left; padding-left: 1rem;">${inst.display_name}</td>
                            <td><span class="status-dot ${dotClass}"></span>${state}</td>
                            <td>${inst.public_ip || '无'}</td>
                            <td>${inst.ipv6_address || '无'}</td>
                            <td>${inst.ocpus}c / ${inst.memory_in_gbs}g / ${inst.boot_volume_size_gb}</td>
                            <td>${new Date(inst.time_created).toLocaleString()}</td>
                        `;
                        instanceList.appendChild(tr);
                    });
                }
                addLog('实例列表刷新成功!', 'success');
            } catch (error) {
                instanceList.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-5">加载实例列表失败</td></tr>`;
            } finally {
                refreshInstancesBtn.disabled = false;
            }
        }
        
        refreshInstancesBtn.addEventListener('click', refreshInstances);
        
        instanceList.addEventListener('click', (e) => {
            const row = e.target.closest('tr');
            if (!row || !row.dataset.instanceId) return;
    
            document.querySelectorAll('#instanceList tr').forEach(r => r.classList.remove('table-active'));
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
        
        async function performInstanceAction(action) {
            if (!selectedInstance) {
                addLog('请先选择一个实例', 'warning');
                return;
            }
            
            let confirmMessage = `确定要对实例 "${selectedInstance.display_name}" 执行 "${action}" 操作吗?`;
            if (action === 'terminate') {
                if (!confirm(`!!! 警告: 终止实例 "${selectedInstance.display_name}" 操作无法撤销 !!!\n\n确定要继续吗？`)) return;
            } else if (action === 'changeip') {
                confirmMessage = `确定更换实例 "${selectedInstance.display_name}" 的公网 IP (IPV4) 吗？\n将尝试删除旧临时IP并创建新临时IP。`;
                if (!confirm(confirmMessage)) return;
            } else if (action === 'assignipv6') {
                confirmMessage = `确定要为实例 "${selectedInstance.display_name}" 分配一个 IPV6 地址吗？\n请确保子网已启用IPv6。`;
                if (!confirm(confirmMessage)) return;
            }
            else {
                 if (!confirm(confirmMessage)) return;
            }
           
            const payload = {
                action: action,
                instance_id: selectedInstance.id,
                instance_name: selectedInstance.display_name,
                vnic_id: selectedInstance.vnic_id,
                subnet_id: selectedInstance.subnet_id
            };
    
            if (action === 'terminate') {
                 payload.preserve_boot_volume = confirm("终止实例时是否保留其引导卷？");
            }
    
            addLog(`正在为实例 ${selectedInstance.display_name} 提交 ${action} 请求...`);
            try {
                const response = await apiRequest('/oci/api/instance-action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                addLog(response.message, 'success');
                if (response.task_id) {
                    pollTaskStatus(response.task_id);
                }
            } catch(e) {}
        }
    
        Object.entries(instanceActionButtons).forEach(([action, button]) => {
            button.addEventListener('click', () => performInstanceAction(action.toLowerCase()));
        });
    
        // --- 任务管理 ---
        async function loadSnatchTasks() {
            runningSnatchTasksList.innerHTML = '<li class="list-group-item">正在加载...</li>';
            completedSnatchTasksList.innerHTML = '<li class="list-group-item">正在加载...</li>';
            stopSnatchTaskBtn.disabled = true;
            deleteSnatchTaskBtn.disabled = true;
            
            try {
                const [running, completed] = await Promise.all([
                    apiRequest('/oci/api/tasks/snatching/running'),
                    apiRequest('/oci/api/tasks/snatching/completed')
                ]);
                
                runningTasksData = running;
                completedTasksData = completed;
    
                runningSnatchTasksList.innerHTML = '';
                if (running.length === 0) {
                    runningSnatchTasksList.innerHTML = '<li class="list-group-item text-muted">没有正在运行的抢占任务。</li>';
                } else {
                    running.forEach(task => {
                        const li = document.createElement('li');
                        li.className = 'list-group-item list-group-item-action';
                        li.dataset.taskId = task.id;
                        li.innerHTML = `
                            <strong>
                                <span class="badge bg-primary me-2">${task.account_alias || '未知账号'}</span>
                                ${task.name}
                            </strong>
                            <br>
                            <small class="text-muted">${task.result}</small>
                        `;
                        runningSnatchTasksList.appendChild(li);
                    });
                }
    
                completedSnatchTasksList.innerHTML = '';
                 if (completed.length === 0) {
                    completedSnatchTasksList.innerHTML = '<li class="list-group-item text-muted">没有已完成的抢占任务记录。</li>';
                } else {
                    completed.forEach(task => {
                        const li = document.createElement('li');
                        li.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center';
                        li.dataset.taskId = task.id;
                        
                        let statusBadge = task.status === 'success' ? '<span class="badge bg-success">成功</span>' : '<span class="badge bg-danger">失败</span>';
                        
                        li.innerHTML = `
                            <div>
                                <strong>
                                    <span class="badge bg-secondary me-2">${task.account_alias || '未知账号'}</span>
                                    ${task.name}
                                </strong>
                                <br>
                                <small class="text-muted">完成于: ${new Date(task.created_at).toLocaleString()}</small>
                            </div>
                            ${statusBadge}
                        `;
                        completedSnatchTasksList.appendChild(li);
                    });
                }
    
            } catch(e) {
                runningSnatchTasksList.innerHTML = '<li class="list-group-item list-group-item-danger">加载正在运行任务失败。</li>';
                completedSnatchTasksList.innerHTML = '<li class="list-group-item list-group-item-danger">加载已完成任务失败。</li>';
            }
        }
        
        viewSnatchTasksBtn.addEventListener('click', loadSnatchTasks);
    
        runningSnatchTasksList.addEventListener('click', (e) => {
            const li = e.target.closest('li');
            if (li && li.dataset.taskId) {
                document.querySelectorAll('#runningSnatchTasksList li').forEach(el => el.classList.remove('active'));
                li.classList.add('active');
                stopSnatchTaskBtn.disabled = false;
            }
        });
    
        completedSnatchTasksList.addEventListener('dblclick', (e) => {
            const li = e.target.closest('li');
            if (!li || !li.dataset.taskId) return;
            const task = completedTasksData.find(t => t.id === li.dataset.taskId);
            if (task) {
                document.getElementById('taskResultContent').textContent = task.result;
                taskResultModal.show();
            }
        });
    
        completedSnatchTasksList.addEventListener('click', (e) => {
            const li = e.target.closest('li');
            if (li && li.dataset.taskId) {
                document.querySelectorAll('#completedSnatchTasksList li').forEach(el => el.classList.remove('active'));
                li.classList.add('active');
                deleteSnatchTaskBtn.disabled = false;
            }
        });
    
        stopSnatchTaskBtn.addEventListener('click', async () => {
            const selectedLi = document.querySelector('#runningSnatchTasksList li.active');
            if (!selectedLi) return addLog('请先选择一个要停止的任务', 'warning');
            
            const taskId = selectedLi.dataset.taskId;
            if (!confirm(`确定要停止任务 "${taskId}" 吗？`)) return;
    
            addLog(`正在发送停止任务 ${taskId} 的请求...`);
            try {
                await apiRequest(`/oci/api/tasks/${taskId}/stop`, { method: 'POST' });
                addLog(`已成功发送停止请求。`, 'success');
                setTimeout(loadSnatchTasks, 2000);
            } catch(e) {}
        });
    
        deleteSnatchTaskBtn.addEventListener('click', async () => {
            const selectedLi = document.querySelector('#completedSnatchTasksList li.active');
            if (!selectedLi) return addLog('请先选择一个要删除的任务记录', 'warning');
    
            const taskId = selectedLi.dataset.taskId;
            if (!confirm(`确定要删除这条任务记录吗？此操作不可逆。`)) return;
    
            addLog(`正在删除任务记录 ${taskId}...`);
            try {
                await apiRequest(`/oci/api/tasks/${taskId}`, { method: 'DELETE' });
                addLog('任务记录已删除。', 'success');
                loadSnatchTasks();
            } catch(e) {}
        });
    
        // --- 任务状态轮询 ---
        function pollTaskStatus(taskId) {
            addLog(`正在监控任务 ${taskId}...`);
            const maxRetries = 300; // 轮询大约 25 分钟
            let retries = 0;
            let lastLoggedStatus = ''; 
        
            const intervalId = setInterval(async () => {
                if (retries >= maxRetries) {
                    clearInterval(intervalId);
                    addLog(`任务 ${taskId} 监控超时。`, 'warning');
                    return;
                }
                try {
                    const result = await apiRequest(`/oci/api/task_status/${taskId}`);
                    if (result.status === 'success' || result.status === 'failure') {
                        clearInterval(intervalId);
                        const logType = result.status === 'success' ? 'success' : 'error';
                        addLog(`<pre>${result.result}</pre>`, logType);
                        
                        if (result.status === 'success') {
                            setTimeout(refreshInstances, 2000);
                        }
                    } else if (result.status === 'running') {
                        if (result.result && result.result !== lastLoggedStatus) {
                             addLog(result.result, 'info');
                             lastLoggedStatus = result.result;
                        }
                    }
                } catch (error) {
                    clearInterval(intervalId);
                    if (error.message.includes("404")) {
                         console.log(`停止监控任务 ${taskId}，因为它已不存在。`);
                    } else {
                        addLog(`查询任务 ${taskId} 状态时出错。`, 'error');
                    }
                }
                retries++;
            }, 5000);
        }
    
        // --- 创建实例 (单次) ---
        const createShapeSelect = document.getElementById('instanceShape');
        const createFlexConfig = document.getElementById('flexShapeConfig');
        if (createShapeSelect && createFlexConfig) {
            createShapeSelect.addEventListener('change', () => {
                const isFlex = createShapeSelect.value.includes('Flex');
                createFlexConfig.style.display = isFlex ? 'flex' : 'none';
            });
            createShapeSelect.dispatchEvent(new Event('change'));
        }
        if (document.getElementById('submitCreateInstance')) {
            document.getElementById('submitCreateInstance').addEventListener('click', async () => {
                const shape = createShapeSelect.value;
                const details = {
                    display_name_prefix: document.getElementById('instanceNamePrefix').value.trim(),
                    instance_count: parseInt(document.getElementById('instanceCount').value, 10),
                    os_name_version: document.getElementById('instanceOS').value,
                    shape: shape,
                    boot_volume_size: parseInt(document.getElementById('bootVolumeSize').value, 10),
                };
                if (shape.includes('Flex')) {
                    details.ocpus = parseInt(document.getElementById('instanceOcpus').value, 10);
                    details.memory_in_gbs = parseInt(document.getElementById('instanceMemory').value, 10);
                }
                if (!details.display_name_prefix) { return addLog('实例名称前缀不能为空', 'error'); }
                addLog(`正在提交创建实例 [${details.display_name_prefix}] 的请求...`);
                try {
                    const response = await apiRequest('/oci/api/create-instance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(details) });
                    addLog(response.message, 'success');
                    createInstanceModal.hide();
                    if (response.task_id) { pollTaskStatus(response.task_id); }
                } catch (error) {}
            });
        }
    
        // --- 抢占实例 (循环重试) ---
        const snatchShapeSelect = document.getElementById('snatchInstanceShape');
        const snatchFlexConfig = document.getElementById('snatchFlexShapeConfig');
        if (snatchShapeSelect && snatchFlexConfig) {
            snatchShapeSelect.addEventListener('change', () => {
                const isFlex = snatchShapeSelect.value.includes('Flex');
                snatchFlexConfig.style.display = isFlex ? 'flex' : 'none';
            });
            snatchShapeSelect.dispatchEvent(new Event('change'));
        }
        document.getElementById('submitSnatchInstanceBtn').addEventListener('click', async () => {
            const shape = snatchShapeSelect.value;
            const details = {
                display_name_prefix: document.getElementById('snatchInstanceNamePrefix').value.trim(),
                availabilityDomain: document.getElementById('snatchAvailabilityDomain').value.trim() || null,
                os_name_version: document.getElementById('snatchInstanceOS').value,
                shape: shape,
                boot_volume_size: parseInt(document.getElementById('snatchBootVolumeSize').value, 10),
                min_delay: parseInt(document.getElementById('snatchMinDelay').value, 10) || 30,
                max_delay: parseInt(document.getElementById('snatchMaxDelay').value, 10) || 90
            };
            if (shape.includes('Flex')) {
                details.ocpus = parseInt(document.getElementById('snatchInstanceOcpus').value, 10);
                details.memory_in_gbs = parseInt(document.getElementById('snatchInstanceMemory').value, 10);
            }
            if (!details.display_name_prefix) { return addLog('实例名称不能为空', 'error'); }
            if (details.min_delay >= details.max_delay) { return addLog('最短重试间隔必须小于最长重试间隔', 'error'); }
            addLog(`正在提交抢占实例 [${details.display_name_prefix}] 的任务...`);
            try {
                const response = await apiRequest('/oci/api/snatch-instance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(details) });
                addLog(response.message, 'success');
                snatchInstanceModal.hide();
                if (response.task_id) { pollTaskStatus(response.task_id); }
            } catch (error) {}
        });
    
        // 初始化页面
        loadProfiles();
    });
    

