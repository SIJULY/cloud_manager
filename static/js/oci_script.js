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
    const snatchInstanceBtn = document.getElementById('snatchInstanceBtn'); 
    const networkSettingsBtn = document.getElementById('networkSettingsBtn'); 
    const instanceList = document.getElementById('instanceList'); 
    const logOutput = document.getElementById('logOutput'); 
    const clearLogBtn = document.getElementById('clearLogBtn'); 
    const editProfileModal = new bootstrap.Modal(document.getElementById('editProfileModal')); 
    const createInstanceModal = new bootstrap.Modal(document.getElementById('createInstanceModal')); 
    const snatchInstanceModal = new bootstrap.Modal(document.getElementById('snatchInstanceModal')); 
    const viewSnatchTasksModal = new bootstrap.Modal(document.getElementById('viewSnatchTasksModal')); 
    const taskResultModal = new bootstrap.Modal(document.getElementById('taskResultModal')); 
    const stopSnatchTaskBtn = document.getElementById('stopSnatchTaskBtn'); 
    const deleteSnatchTaskBtn = document.getElementById('deleteSnatchTaskBtn'); 
    const runningSnatchTasksList = document.getElementById('runningSnatchTasksList'); 
    const completedSnatchTasksList = document.getElementById('completedSnatchTasksList'); 
    const actionAreaProfile = document.getElementById('actionAreaProfile'); 
    
    // 网络设置模态框元素 
    const networkSettingsModal = new bootstrap.Modal(document.getElementById('networkSettingsModal')); 
    const ingressRulesTable = document.getElementById('ingressRulesTable'); 
    const egressRulesTable = document.getElementById('egressRulesTable'); 
    const addIngressRuleBtn = document.getElementById('addIngressRuleBtn'); 
    const addEgressRuleBtn = document.getElementById('addEgressRuleBtn'); 
    const saveNetworkRulesBtn = document.getElementById('saveNetworkRulesBtn'); 

    // 修改实例模态框元素 
    const editInstanceModal = new bootstrap.Modal(document.getElementById('editInstanceModal')); 
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
    const applyNetBoostBtn = document.getElementById('applyNetBoostBtn'); 

    
    // 通用确认模态框的元素 
    const confirmActionModal = new bootstrap.Modal(document.getElementById('confirmActionModal')); 
    const confirmActionModalLabel = document.getElementById('confirmActionModalLabel'); 
    const confirmActionModalBody = document.getElementById('confirmActionModalBody'); 
    const confirmActionModalTerminateOptions = document.getElementById('confirmActionModalTerminateOptions'); 
    const confirmDeleteVolumeCheck = document.getElementById('confirmDeleteVolumeCheck'); 
    const confirmActionModalConfirmBtn = document.getElementById('confirmActionModalConfirmBtn'); 

    // 实例操作按钮 
    const instanceActionButtons = { 
        start: document.getElementById('startBtn'), 
        stop: document.getElementById('stopBtn'), 
        restart: document.getElementById('restartBtn'), 
        editInstance: document.getElementById('editInstanceBtn'), 
        changeIp: document.getElementById('changeIpBtn'), 
        assignIpv6: document.getElementById('assignIpv6Btn'), 
        terminate: document.getElementById('terminateBtn'), 
    }; 

    let selectedInstance = null; 
    let runningTasksData = []; 
    let completedTasksData = []; 
    let currentSecurityList = null; 

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
            confirmActionModalLabel.textContent = '确认删除账号'; 
            confirmActionModalBody.textContent = `确定要删除账号 "${alias}" 吗?`; 
            confirmActionModalTerminateOptions.classList.add('d-none'); 
            
            const confirmDelete = async () => { 
                confirmActionModal.hide(); 
                addLog(`正在删除账号: ${alias}...`); 
                try { 
                    await apiRequest(`/oci/api/profiles/${alias}`, { method: 'DELETE' }); 
                    addLog('删除成功!', 'success'); 
                    loadProfiles(); 
                } catch (error) {} 
                confirmActionModalConfirmBtn.removeEventListener('click', confirmDelete); 
            }; 
            confirmActionModalConfirmBtn.addEventListener('click', confirmDelete, { once: true }); 

            confirmActionModal.show(); 
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
                    await apiRequest(`/oci/api/profiles/${originalAlias}`, { method: 'DELETE' }); 
                    addLog(`旧账号名称 ${originalAlias} 已删除。`); 
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
        networkSettingsBtn.disabled = !enabled; 
        
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
                        <td> 
                            <div class="status-cell"> 
                                <span class="status-dot ${dotClass}"></span> 
                                <span>${state}</span> 
                            </div> 
                        </td> 
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
        if (action === 'changeip') { 
              message = `确定更换实例 "${selectedInstance.display_name}" 的公网 IP (IPV4) 吗？\n将尝试删除旧临时IP并创建新临时IP。`; 
        } 
        if (action === 'assignipv6') { 
              message = `确定要为实例 "${selectedInstance.display_name}" 分配一个 IPV6 地址吗？\n请确保子网已启用IPv6。`; 
        } 
        
        confirmActionModalLabel.textContent = title; 
        confirmActionModalBody.textContent = message; 
        confirmActionModalConfirmBtn.dataset.action = action; 
        confirmActionModal.show(); 
    } 
    
    Object.entries(instanceActionButtons).forEach(([key, button]) => { 
        if (key !== 'editInstance') { // Exclude the edit button from this generic handler 
            button.addEventListener('click', () => performInstanceAction(key.toLowerCase())); 
        } 
    }); 

    confirmActionModalConfirmBtn.addEventListener('click', async () => { 
        const action = confirmActionModalConfirmBtn.dataset.action; 
        if (!action || !selectedInstance) return; 

        confirmActionModal.hide(); 

        const payload = { 
            action: action, 
            instance_id: selectedInstance.id, 
            instance_name: selectedInstance.display_name, 
            vnic_id: selectedInstance.vnic_id, 
            subnet_id: selectedInstance.subnet_id 
        }; 

        if (action === 'terminate') { 
            payload.preserve_boot_volume = !confirmDeleteVolumeCheck.checked; 
        } 

        addLog(`正在为实例 ${selectedInstance.display_name} 提交 ${action} 请求...`); 
        try { 
            const response = await apiRequest('/oci/api/instance-action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); 
            addLog(response.message, 'success'); 
            if (response.task_id) { 
                pollTaskStatus(response.task_id); 
            } 
        } catch(e) {} 
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
        
        confirmActionModalLabel.textContent = '确认停止任务'; 
        confirmActionModalBody.textContent = `确定要停止任务 "${taskId}" 吗？`; 
        confirmActionModalTerminateOptions.classList.add('d-none'); 
        
        const confirmStop = async () => { 
            confirmActionModal.hide(); 
            addLog(`正在发送停止任务 ${taskId} 的请求...`); 
            try { 
                await apiRequest(`/oci/api/tasks/${taskId}/stop`, { method: 'POST' }); 
                addLog(`已成功发送停止请求。`, 'success'); 
                setTimeout(loadSnatchTasks, 2000); 
            } catch(e) {} 
            confirmActionModalConfirmBtn.removeEventListener('click', confirmStop); 
        }; 
        confirmActionModalConfirmBtn.addEventListener('click', confirmStop, { once: true }); 
        
        confirmActionModal.show(); 
    }); 

    deleteSnatchTaskBtn.addEventListener('click', async () => { 
        const selectedLi = document.querySelector('#completedSnatchTasksList li.active'); 
        if (!selectedLi) return addLog('请先选择一个要删除的任务记录', 'warning'); 

        const taskId = selectedLi.dataset.taskId; 

        confirmActionModalLabel.textContent = '确认删除记录'; 
        confirmActionModalBody.textContent = `确定要删除这条任务记录吗？此操作不可逆。`; 
        confirmActionModalTerminateOptions.classList.add('d-none'); 
        
        const confirmDelete = async () => { 
            confirmActionModal.hide(); 
            addLog(`正在删除任务记录 ${taskId}...`); 
            try { 
                await apiRequest(`/oci/api/tasks/${taskId}`, { method: 'DELETE' }); 
                addLog('任务记录已删除。', 'success'); 
                loadSnatchTasks(); 
            } catch(e) {} 
            confirmActionModalConfirmBtn.removeEventListener('click', confirmDelete); 
        }; 
        confirmActionModalConfirmBtn.addEventListener('click', confirmDelete, { once: true }); 

        confirmActionModal.show(); 
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

    // --- 网络设置 --- 
    networkSettingsBtn.addEventListener('click', async () => { 
        try { 
            addLog("正在获取网络安全规则..."); 
            const data = await apiRequest('/oci/api/network/security-list'); 
            currentSecurityList = data.security_list; 
            document.getElementById('currentVcnName').textContent = data.vcn_name || 'N/A'; 
            document.getElementById('currentSlName').textContent = currentSecurityList.display_name || 'N/A'; 
            
            renderRules('ingress', currentSecurityList.ingress_security_rules); 
            renderRules('egress', currentSecurityList.egress_security_rules); 

        } catch (error) { 
            addLog(`获取网络规则失败: ${error.message}`, 'error'); 
            document.getElementById('currentVcnName').textContent = '获取失败'; 
            document.getElementById('currentSlName').textContent = '获取失败'; 
        } 
    }); 

    function renderRules(type, rules) { 
        const tableBody = type === 'ingress' ? ingressRulesTable : egressRulesTable; 
        tableBody.innerHTML = ''; 
        if (!rules || rules.length === 0) { 
            tableBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">没有规则</td></tr>`; 
            return; 
        } 
        rules.forEach(rule => { 
            const row = createRuleRow(type, rule); 
            tableBody.appendChild(row); 
        }); 
    } 

    function createRuleRow(type, rule = {}) { 
        const tr = document.createElement('tr'); 
        tr.className = 'rule-row'; 
        const isStateless = rule.is_stateless || false; 
        const sourceOrDest = type === 'ingress' ? (rule.source || '0.0.0.0/0') : (rule.destination || '0.0.0.0/0'); 
        const protocol = rule.protocol || '6'; // Default to TCP 
        
        const protocolOptions = { 
            'all': '所有协议', '1': 'ICMP', '6': 'TCP', '17': 'UDP' 
        }; 
        const protocolSelect = `<select class="form-select form-select-sm" data-key="protocol"> 
            ${Object.entries(protocolOptions).map(([key, value]) => `<option value="${key}" ${protocol == key ? 'selected' : ''}>${value}</option>`).join('')} 
        </select>`; 

        const portRange = (options) => { 
            if (!options) return { min: '', max: '' }; 
            return { min: options.min || '', max: options.max || '' }; 
        }; 

        const srcPorts = portRange(rule.tcp_options ? rule.tcp_options.source_port_range : (rule.udp_options ? rule.udp_options.source_port_range : null)); 
        const destPorts = portRange(rule.tcp_options ? rule.tcp_options.destination_port_range : (rule.udp_options ? rule.tcp_options.destination_port_range : null)); 
        
        tr.innerHTML = ` 
            <td><input class="form-check-input" type="checkbox" data-key="is_stateless" ${isStateless ? 'checked' : ''}></td> 
            <td><input type="text" class="form-control form-control-sm" data-key="${type === 'ingress' ? 'source' : 'destination'}" value="${sourceOrDest}"></td> 
            <td>${protocolSelect}</td> 
            <td> 
                <div class="input-group input-group-sm"> 
                    <input type="number" class="form-control" placeholder="Min" data-key="src_port_min" value="${srcPorts.min}"> 
                    <input type="number" class="form-control" placeholder="Max" data-key="src_port_max" value="${srcPorts.max}"> 
                </div> 
            </td> 
            <td> 
                <div class="input-group input-group-sm"> 
                    <input type="number" class="form-control" placeholder="Min" data-key="dest_port_min" value="${destPorts.min}"> 
                    <input type="number" class="form-control" placeholder="Max" data-key="dest_port_max" value="${destPorts.max}"> 
                </div> 
            </td> 
            <td><button class="btn btn-sm btn-danger remove-rule-btn"><i class="bi bi-trash"></i></button></td> 
        `; 
        tr.querySelector('.remove-rule-btn').addEventListener('click', () => tr.remove()); 
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

    saveNetworkRulesBtn.addEventListener('click', async () => { 
        const spinner = saveNetworkRulesBtn.querySelector('.spinner-border'); 
        saveNetworkRulesBtn.disabled = true; 
        spinner.classList.remove('d-none'); 
        
        try { 
            const ingress_security_rules = collectRulesFromTable(ingressRulesTable, 'ingress'); 
            const egress_security_rules = collectRulesFromTable(egressRulesTable, 'egress'); 

            const payload = { 
                security_list_id: currentSecurityList.id, 
                rules: { 
                    ingress_security_rules, 
                    egress_security_rules 
                } 
            }; 

            addLog("正在保存网络规则..."); 
            const response = await apiRequest('/oci/api/network/update-security-rules', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(payload) 
            }); 

            addLog(response.message, 'success'); 
            networkSettingsModal.hide(); 

        } catch (error) { 
            addLog(`保存网络规则失败: ${error.message}`, 'error'); 
        } finally { 
            saveNetworkRulesBtn.disabled = false; 
            spinner.classList.add('d-none'); 
        } 
    }); 

    function collectRulesFromTable(tableBody, type) { 
        const rules = []; 
        tableBody.querySelectorAll('.rule-row').forEach(tr => { 
            const rule = { 
                is_stateless: tr.querySelector('[data-key="is_stateless"]').checked, 
                protocol: tr.querySelector('[data-key="protocol"]').value 
            }; 
            
            if (type === 'ingress') { 
                rule.source = tr.querySelector('[data-key="source"]').value; 
                rule.source_type = 'CIDR_BLOCK'; 
            } else { 
                rule.destination = tr.querySelector('[data-key="destination"]').value; 
                rule.destination_type = 'CIDR_BLOCK'; 
            } 

            if (rule.protocol === '6' || rule.protocol === '17') { // TCP or UDP 
                const options = {}; 
                const dest_min = parseInt(tr.querySelector('[data-key="dest_port_min"]').value, 10); 
                const dest_max = parseInt(tr.querySelector('[data-key="dest_port_max"]').value, 10); 
                const src_min = parseInt(tr.querySelector('[data-key="src_port_min"]').value, 10); 
                const src_max = parseInt(tr.querySelector('[data-key="src_port_max"]').value, 10); 

                if (!isNaN(dest_min) && !isNaN(dest_max)) { 
                    options.destination_port_range = { min: dest_min, max: dest_max }; 
                } 
                if (!isNaN(src_min) && !isNaN(src_max)) { 
                    options.source_port_range = { min: src_min, max: src_max }; 
                } 
                
                if (rule.protocol === '6') { 
                    rule.tcp_options = options; 
                } else { 
                    rule.udp_options = options; 
                } 
            } 
            rules.push(rule); 
        }); 
        return rules; 
    } 

    // --- 修改实例 --- 
    instanceActionButtons.editInstance.addEventListener('click', async () => { 
        if (!selectedInstance) { 
            addLog('请先选择一个实例', 'warning'); 
            return; 
        } 
        
        try { 
            addLog(`正在获取实例 ${selectedInstance.display_name} 的详细信息...`); 
            const details = await apiRequest(`/oci/api/instance-details/${selectedInstance.id}`); 
            
            editDisplayName.value = details.display_name; 
            editBootVolumeSize.value = details.boot_volume_size_in_gbs; 
            editVpus.value = details.vpus_per_gb; 
            
            if (details.shape.toLowerCase().includes('flex')) { 
                editOcpus.value = details.ocpus; 
                editMemory.value = details.memory_in_gbs; 
                editFlexInstanceConfig.classList.remove('d-none'); 
            } else { 
                editFlexInstanceConfig.classList.add('d-none'); 
            } 

            editInstanceModal.show(); 
        } catch(error) { 
            addLog(`获取实例详情失败: ${error.message}`, 'error'); 
        } 
    }); 
    
    async function handleInstanceUpdateRequest(action, payload) { 
        addLog(`正在提交 ${action} 请求...`); 
        try { 
            const response = await apiRequest('/oci/api/update-instance', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(payload) 
            }); 
            addLog(response.message, 'success'); 
            if (response.task_id) { 
                pollTaskStatus(response.task_id); 
            } 
            editInstanceModal.hide(); // 操作提交后关闭模态框 
            setTimeout(refreshInstances, 3000); // 稍后刷新列表 
        } catch(e) {} 
    } 

    saveDisplayNameBtn.addEventListener('click', () => { 
        handleInstanceUpdateRequest('修改名称', { 
            action: 'update_display_name', 
            instance_id: selectedInstance.id, 
            display_name: editDisplayName.value 
        }); 
    }); 

    saveFlexConfigBtn.addEventListener('click', () => { 
         handleInstanceUpdateRequest('修改CPU/内存', { 
            action: 'update_shape', 
            instance_id: selectedInstance.id, 
            ocpus: parseInt(editOcpus.value, 10), 
            memory_in_gbs: parseInt(editMemory.value, 10) 
        }); 
    }); 

    saveBootVolumeSizeBtn.addEventListener('click', () => { 
         handleInstanceUpdateRequest('修改引导卷大小', { 
            action: 'update_boot_volume', 
            instance_id: selectedInstance.id, 
            size_in_gbs: parseInt(editBootVolumeSize.value, 10) 
        }); 
    }); 

    saveVpusBtn.addEventListener('click', () => { 
         handleInstanceUpdateRequest('修改引导卷性能', { 
            action: 'update_boot_volume', 
            instance_id: selectedInstance.id, 
            vpus_per_gb: parseInt(editVpus.value, 10) 
        }); 
    }); 
    
    applyNetBoostBtn.addEventListener('click', () => { 
        handleInstanceUpdateRequest('网络提速', { 
            action: 'apply_net_boost', 
            instance_id: selectedInstance.id 
        }); 
    }); 


    // 初始化页面 
    loadProfiles(); 
});
