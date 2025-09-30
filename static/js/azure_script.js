document.addEventListener('DOMContentLoaded', function() {
    const VM_SIZE_MAP = {
        "Standard_B1s": "B1s (1 vCPU, 1 GB RAM)", "Standard_B1ms": "B1ms (1 vCPU, 2 GB RAM)",
        "Standard_B2s": "B2s (2 vCPU, 4 GB RAM)", "Standard_D2s_v3": "D2s v3 (2 vCPU, 8 GB RAM)",
        "Standard_F2s_v2": "F2s v2 (2 vCPU, 4 GB RAM)"
    };

    const UI = {
        vmList: document.getElementById('vmList'), accountList: document.getElementById('accountList'),
        addAccountForm: document.getElementById('addAccountForm'), currentAccountStatus: document.getElementById('currentAccountStatus'),
        refreshBtn: document.getElementById('refreshVms'), logOutput: document.getElementById('logOutput'),
        clearLogBtn: document.getElementById('clearLogBtn'), queryAllStatusBtn: document.getElementById('queryAllStatusBtn'),
        startBtn: document.getElementById('startBtn'), stopBtn: document.getElementById('stopBtn'),
        restartBtn: document.getElementById('restartBtn'), changeIpBtn: document.getElementById('changeIpBtn'),
        deleteBtn: document.getElementById('deleteBtn'), regionSelector: document.getElementById('regionSelector'),
        createVmBtn: document.getElementById('createVmBtn'), userData: document.getElementById('userData'),
        createVmModal: document.getElementById('createVmModal'), confirmCreateVmBtn: document.getElementById('confirmCreateVmBtn'),
        vmRegionDisplay: document.getElementById('vmRegionDisplay'),
        editAccountModal: document.getElementById('editAccountModal'),
        confirmEditAccountBtn: document.getElementById('confirmEditAccountBtn'),
        editOriginalAccountName: document.getElementById('editOriginalAccountName'),
        editAccountName: document.getElementById('editAccountName'),
        editExpirationDate: document.getElementById('editExpirationDate'),
    };
    
    let selectedInstance = null;
    let createVmModalInstance;
    let editAccountModalInstance;
    let cachedAccounts = [];

    const log = (message, type = 'info') => {
        const now = new Date().toLocaleTimeString();
        const colorClass = type === 'error' ? 'text-danger' : (type === 'success' ? 'text-success' : '');
        UI.logOutput.innerHTML += `<div>[${now}] ${message.replace(/\n/g, '<br>')}</div>`;
        UI.logOutput.scrollTop = UI.logOutput.scrollHeight;
    };

    const apiCall = async (url, options = {}) => {
        try {
            const response = await fetch(url, options);
            const data = await response.json();
            if (!response.ok) {
                log(data.error || `HTTP error! status: ${response.status}`, 'error');
                throw new Error(data.error);
            }
            if (data.error) log(data.error, 'error');
            return data;
        } catch (error) {
            log(error.message || '请求失败', 'error');
            throw error;
        }
    };

    const calculateUptime = (isoString) => {
        if (!isoString) return 'N/A';
        const startTime = new Date(isoString);
        const now = new Date();
        const diffMs = now - startTime;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        const diffHrs = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
        if (diffDays > 0) return `${diffDays}天${diffHrs}小时`;
        if (diffHrs > 0) return `${diffHrs}小时${diffMins}分钟`;
        return `${diffMins}分钟`;
    };

    const populateRegionSelectors = (regions) => {
        if (!regions || regions.length === 0) {
            UI.regionSelector.innerHTML = '<option value="">无法加载区域</option>'; return;
        }
        const optionsHtml = regions.sort((a, b) => a.display_name.localeCompare(b.display_name)).map(r => `<option value="${r.name}">${r.display_name}</option>`).join('');
        UI.regionSelector.innerHTML = optionsHtml;
    };

    const handleAccountSelected = async () => {
        try {
            log('正在获取可用区域列表...');
            const regions = await apiCall('/azure/api/regions');
            populateRegionSelectors(regions);
            log('可用区域列表已更新', 'success');
            loadVms();
        } catch (e) {
            log('获取区域列表失败，请检查账户权限或网络', 'error');
            UI.regionSelector.innerHTML = '<option value="">获取区域失败</option>';
        }
    };

    const displaySubscriptionStatus = (row) => {
        if (!row) return;
        const statusCell = row.querySelector('.status-cell');
        const expirationDate = row.dataset.expirationDate;
        if (!expirationDate || expirationDate === 'null' || expirationDate === '') {
            statusCell.innerHTML = `<span class="badge bg-secondary">未设置</span>`; return;
        }
        const today = new Date();
        const expiry = new Date(expirationDate);
        today.setHours(0, 0, 0, 0);
        const diffDays = Math.ceil((expiry - today) / (1000 * 60 * 60 * 24));
        let statusText = `剩余 ${diffDays} 天`, badgeClass = 'bg-success';
        if (diffDays < 0) { statusText = '已过期'; badgeClass = 'bg-danger'; } 
        else if (diffDays <= 7) { badgeClass = 'bg-danger'; } 
        else if (diffDays <= 30) { badgeClass = 'bg-warning text-dark'; }
        statusCell.innerHTML = `<span class="badge ${badgeClass}">${statusText}</span>`;
    };

    const loadAccounts = async () => {
        try {
            const accounts = await apiCall('/azure/api/accounts');
            cachedAccounts = accounts;
            UI.accountList.innerHTML = accounts.length === 0 ? '<tr><td colspan="3" class="text-center">没有已保存的账户</td></tr>' : '';
            accounts.forEach(acc => {
                const row = document.createElement('tr');
                row.dataset.accountName = acc.name;
                row.dataset.expirationDate = acc.expiration_date || '';
                row.innerHTML = `<td>${acc.name}</td><td class="status-cell text-center">--</td><td class="text-center"><div class="d-flex justify-content-center gap-1"><button class="btn btn-success btn-sm" data-action="select">选择</button><button class="btn btn-warning btn-sm" data-action="edit">修改</button><button class="btn btn-info btn-sm" data-action="query-status">查状态</button><button class="btn btn-danger btn-sm" data-action="delete">删除</button></div></td>`;
                UI.accountList.appendChild(row);
            });
            const session = await apiCall('/azure/api/session');
            if (session.logged_in) {
                UI.currentAccountStatus.textContent = ` (当前: ${session.name})`;
                [UI.refreshBtn, UI.regionSelector, UI.createVmBtn].forEach(el => el.disabled = false);
                await handleAccountSelected();
            } else {
                UI.currentAccountStatus.textContent = '';
                [UI.refreshBtn, UI.regionSelector, UI.createVmBtn].forEach(el => el.disabled = true);
                UI.regionSelector.innerHTML = '<option>请先选择账户</option>';
            }
        } catch (e) {}
    };

    const loadVms = async () => {
        selectedInstance = null;
        updateActionButtonsState();
        UI.vmList.innerHTML = `<tr><td colspan="7" class="text-center">正在加载... <div class="spinner-border spinner-border-sm"></div></td></tr>`;
        try {
            const vms = await apiCall('/azure/api/vms');
            if (vms.length === 0) { UI.vmList.innerHTML = `<tr><td colspan="7" class="text-center">未找到任何虚拟机</td></tr>`; return; }
            UI.vmList.innerHTML = '';
            vms.forEach(vm => {
                const isRunning = vm.status.toLowerCase().includes('running');
                const row = document.createElement('tr');
                Object.assign(row.dataset, { name: vm.name, group: vm.resource_group, status: vm.status });
                const friendlyVmSize = VM_SIZE_MAP[vm.vm_size] || vm.vm_size;
                const uptime = calculateUptime(vm.time_created);
                row.innerHTML = `<td>${vm.name}</td><td>${vm.resource_group}</td><td>${vm.location}</td><td>${friendlyVmSize}</td><td>${uptime}</td><td>${vm.public_ip}</td><td><span class="badge bg-${isRunning ? 'success' : 'secondary'}">${vm.status}</span></td>`;
                row.addEventListener('click', () => {
                    if (selectedInstance) selectedInstance.classList.remove('table-active');
                    row.classList.add('table-active');
                    selectedInstance = row;
                    updateActionButtonsState();
                });
                UI.vmList.appendChild(row);
            });
        } catch (e) { UI.vmList.innerHTML = `<tr><td colspan="7" class="text-center text-danger">加载失败，请选择账户或检查凭据</td></tr>`; }
    };
    
    const updateActionButtonsState = () => {
        const setButtonState = (button, activeClass, isEnabled) => {
            button.disabled = !isEnabled;
            button.className = isEnabled ? `btn ${activeClass}` : 'btn btn-secondary';
        };

        if (!selectedInstance) {
            [UI.startBtn, UI.stopBtn, UI.restartBtn, UI.changeIpBtn, UI.deleteBtn].forEach(btn => {
                btn.disabled = true;
                btn.className = 'btn btn-secondary';
            });
            return;
        }

        const status = selectedInstance.dataset.status.toLowerCase();
        const isRunning = status.includes('running');
        const isStopped = status.includes('deallocated');

        setButtonState(UI.startBtn, 'btn-success', isStopped);
        setButtonState(UI.stopBtn, 'btn-warning', isRunning);
        setButtonState(UI.restartBtn, 'btn-info', isRunning);
        setButtonState(UI.changeIpBtn, 'btn-secondary', isRunning || isStopped);
        setButtonState(UI.deleteBtn, 'btn-danger', true);
    };

    const handleVmAction = async (action) => {
        if (!selectedInstance) return;
        const vmName = selectedInstance.dataset.name, rgName = selectedInstance.dataset.group;
        const confirmText = { start: `启动 ${vmName}?`, stop: `停止 ${vmName}?`, restart: `重启 ${vmName}?`, delete: `【警告】删除资源组 ${rgName}？此操作不可逆！` };
        if (!confirm(`确定要${confirmText[action]}`)) return;
        log(`正在对 ${vmName} 执行 ${action} 操作...`);
        try {
            const result = await apiCall('/azure/api/vm-action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, vm_name: vmName, resource_group: rgName }) });
            log(result.message, 'info');
            if (result.task_id) {
                pollTaskStatus(result.task_id);
            }
        } catch (e) {}
    };

    const handleChangeIpAction = async () => {
        if (!selectedInstance) return;
        const vmName = selectedInstance.dataset.name, rgName = selectedInstance.dataset.group;
        if (!confirm(`确定要为虚拟机 ${vmName} 更换一个新的公网IP吗？\n旧IP将被释放并删除。`)) return;
        log(`正在为虚拟机 ${vmName} 更换IP...`);
        try {
            const result = await apiCall('/azure/api/vm-change-ip', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ vm_name: vmName, resource_group: rgName }) });
            log(result.message, 'info');
            if (result.task_id) {
                pollTaskStatus(result.task_id);
            }
        } catch (e) {}
    };

    UI.addAccountForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = { name: document.getElementById('accountName').value, client_id: document.getElementById('clientId').value, client_secret: document.getElementById('clientSecret').value, tenant_id: document.getElementById('tenantId').value, subscription_id: document.getElementById('subscriptionId').value, expiration_date: document.getElementById('expirationDate').value };
        try { await apiCall('/azure/api/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); log('账户添加成功', 'success'); UI.addAccountForm.reset(); loadAccounts(); } catch (e) {}
    });

    UI.accountList.addEventListener('click', async (event) => {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const action = button.dataset.action; const row = button.closest('tr'); const accountName = row.dataset.accountName;
        if (action === 'select') { try { await apiCall('/azure/api/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: accountName }) }); log(`账户 ${accountName} 已选择`, 'success'); loadAccounts(); } catch (e) {} }
        else if (action === 'edit') {
            const account = cachedAccounts.find(acc => acc.name === accountName);
            if (account) {
                UI.editOriginalAccountName.value = account.name; UI.editAccountName.value = account.name;
                UI.editExpirationDate.value = account.expiration_date || '';
                if (!editAccountModalInstance) editAccountModalInstance = new bootstrap.Modal(UI.editAccountModal);
                editAccountModalInstance.show();
            }
        } else if (action === 'delete') { if (confirm(`确定要删除账户 ${accountName} 吗？`)) { try { await apiCall(`/azure/api/accounts/${accountName}`, { method: 'DELETE' }); log(`账户 ${accountName} 已删除`, 'success'); loadAccounts(); } catch (e) {} }
        } else if (action === 'query-status') { displaySubscriptionStatus(row); }
    });

    UI.confirmEditAccountBtn.addEventListener('click', async () => {
        const payload = { original_name: UI.editOriginalAccountName.value, new_name: UI.editAccountName.value, expiration_date: UI.editExpirationDate.value };
        try { await apiCall('/azure/api/accounts/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); log(`账户 ${payload.original_name} 已更新`, 'success'); editAccountModalInstance.hide(); loadAccounts(); } catch(e) {}
    });

    UI.queryAllStatusBtn.addEventListener('click', () => {
        log(`正在为所有账户显示到期状态...`);
        UI.accountList.querySelectorAll('tr[data-account-name]').forEach(row => { displaySubscriptionStatus(row); });
    });

    UI.createVmBtn.addEventListener('click', () => {
        const selectedRegionName = UI.regionSelector.options[UI.regionSelector.selectedIndex].text;
        UI.vmRegionDisplay.value = selectedRegionName;
        if (!createVmModalInstance) createVmModalInstance = new bootstrap.Modal(UI.createVmModal);
        createVmModalInstance.show();
    });
    
    const pollTaskStatus = (taskId) => {
        let notFoundCount = 0;
        let lastLoggedStatus = '';
        const interval = setInterval(async () => {
            try {
                const status = await apiCall(`/azure/api/task_status/${taskId}`);
                if (status.status === 'success' || status.status === 'failure') {
                    clearInterval(interval);
                    log(status.result, status.status === 'success' ? 'success' : 'error');
                    if (status.status === 'success') {
                        setTimeout(loadVms, 5000); 
                    }
                } else if (status.status === 'running') {
                    if(status.result && status.result !== lastLoggedStatus) {
                        log(status.result, 'info');
                        lastLoggedStatus = status.result;
                    }
                } else if (status.status === 'not_found') {
                    notFoundCount++;
                    if (notFoundCount > 3) {
                        log(`错误：无法追踪任务 ${taskId} 的状态。`, 'error');
                        clearInterval(interval);
                    }
                }
            } catch (e) {
                log(`查询任务状态失败: ${e.message}`, 'error');
                clearInterval(interval);
            }
        }, 5000);
    };

    UI.confirmCreateVmBtn.addEventListener('click', async () => {
        try {
            const selectedIpTypeElement = document.querySelector('input[name="ipType"]:checked');
            if (!selectedIpTypeElement) { log("错误：请选择一个公网IP类型。", "error"); return; }
            const userData = UI.userData.value;
            const userDataB64 = userData ? btoa(unescape(encodeURIComponent(userData))) : "";
            const payload = {
                region: UI.regionSelector.value, vm_size: document.getElementById('vmSize').value,
                os_image: document.getElementById('vmOs').value, disk_size: parseInt(document.getElementById('vmDiskSize').value, 10),
                ip_type: selectedIpTypeElement.value, user_data: userDataB64
            };
            if (!payload.region) { log('请先选择一个区域', 'error'); return; }
            if (createVmModalInstance) createVmModalInstance.hide();
            
            const result = await apiCall('/azure/api/create-vm', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
            log(result.message, 'info'); 
            if (result.task_id) {
                pollTaskStatus(result.task_id);
            }
        } catch (e) {
            console.error("创建虚拟机过程中发生错误:", e);
        }
    });

    UI.refreshBtn.addEventListener('click', loadVms);
    UI.startBtn.addEventListener('click', () => handleVmAction('start'));
    UI.stopBtn.addEventListener('click', () => handleVmAction('stop'));
    UI.restartBtn.addEventListener('click', () => handleVmAction('restart'));
    UI.changeIpBtn.addEventListener('click', handleChangeIpAction);
    UI.deleteBtn.addEventListener('click', () => handleVmAction('delete'));
    UI.clearLogBtn.addEventListener('click', () => { UI.logOutput.innerHTML = '' });

    loadAccounts();
    updateActionButtonsState();
});
