// Gantt Excel PRO - Alpine.js & Scheduling Engine Controller

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

window.ganttApp = function(projectId) {
    return {
        projectId: projectId,
        projectMeta: {},
        tasks: [],
        filteredTasks: [],
        ganttTasks: [],
        dependencies: [],
        users: [],
        evmData: {},
        workloadData: [],
        activityLogs: [],
        taskComments: [],

        // Workspaces & Toggles
        activeWorkspaceView: 'gantt', // 'gantt' | 'kanban' | 'workload' | 'evm' | 'audit'
        viewMode: 'Week',
        showCriticalPath: false,
        showBaseline: false,
        ganttInstance: null,
        selectedTaskId: null,
        isRecalculating: false,
        isScrollingSync: false,
        modalTab: 'general',

        // Filters
        searchQuery: '',
        filterStatus: '',
        filterPriority: '',
        filterAssignee: '',

        // Modals & Forms
        showEditModal: false,
        showImportModal: false,
        isCreating: false,
        newCommentText: '',
        editForm: {
            id: null,
            name: '',
            description: '',
            parent_task: null,
            assignee: null,
            start_date: '',
            end_date: '',
            duration_days: 1,
            progress: 0,
            status: 'NOT_STARTED',
            priority: 'MEDIUM',
            is_milestone: false,
            is_critical: false,
            total_float_days: 0,
            estimated_cost: 0,
            actual_cost: 0,
            estimated_hours: 0,
            actual_hours: 0,
            wbs_code: '',
            predecessors_list: []
        },
        newDep: {
            from_task: '',
            dependency_type: 'FS',
            lag_days: 0
        },

        kanbanColumns: [
            { status: 'NOT_STARTED', label: 'Not Started', badgeColor: 'bg-slate-500' },
            { status: 'IN_PROGRESS', label: 'In Progress', badgeColor: 'bg-blue-500' },
            { status: 'DELAYED', label: 'Delayed / Critical', badgeColor: 'bg-rose-500' },
            { status: 'COMPLETE', label: 'Complete', badgeColor: 'bg-emerald-500' }
        ],

        getDependencyTypeLabel(type) {
            const map = {
                'FS': 'Finish-to-Start (FS)',
                'SS': 'Start-to-Start (SS)',
                'FF': 'Finish-to-Finish (FF)',
                'SF': 'Start-to-Finish (SF)'
            };
            return map[type] || type;
        },

        get currentProjectName() {
            return this.tasks.filter(t => t.status === 'COMPLETE').length;
        },

        get completedCount() {
            return this.tasks.filter(t => t.status === 'COMPLETE').length;
        },

        async initApp() {
            await this.loadData();
            this.initGantt();
            if (window.lucide) lucide.createIcons();

            // Auto-refresh icons when switching workspace views
            this.$watch('activeWorkspaceView', (newVal) => {
                if (newVal === 'gantt') {
                    this.$nextTick(() => {
                        this.initGantt();
                    });
                }
                if (newVal === 'audit') this.loadActivityLogs();
                if (window.lucide) setTimeout(lucide.createIcons, 50);
            });
        },

        async loadData() {
            try {
                const res = await fetch(`/api/projects/${this.projectId}/gantt-data/`, {
                    headers: { 'Accept': 'application/json' }
                });
                if (!res.ok) throw new Error("Failed to load project data");
                const data = await res.json();
                
                this.projectMeta = data.project;
                this.tasks = data.tasks;
                this.ganttTasks = data.gantt_tasks;
                this.dependencies = data.dependencies;
                this.users = data.users;
                this.evmData = data.evm || {};
                this.workloadData = data.workload || [];

                this.calculateDepths();
                this.filterTasks();
            } catch (err) {
                console.error("Error loading project data:", err);
            }
        },

        calculateDepths() {
            const parentMap = {};
            this.tasks.forEach(t => { parentMap[t.id] = t.parent_task; });

            this.tasks.forEach(t => {
                let depth = 0;
                let currParent = t.parent_task;
                while (currParent && depth < 10) {
                    depth++;
                    currParent = parentMap[currParent];
                }
                t.depth = depth;
            });
        },

        filterTasks() {
            let filtered = [...this.tasks];

            if (this.searchQuery) {
                const q = this.searchQuery.toLowerCase();
                filtered = filtered.filter(t => 
                    t.name.toLowerCase().includes(q) || 
                    (t.description && t.description.toLowerCase().includes(q)) ||
                    t.wbs_code.includes(q)
                );
            }

            if (this.filterStatus) {
                filtered = filtered.filter(t => t.status === this.filterStatus);
            }

            if (this.filterPriority) {
                filtered = filtered.filter(t => t.priority === this.filterPriority);
            }

            if (this.filterAssignee) {
                filtered = filtered.filter(t => t.assignee == this.filterAssignee);
            }

            this.filteredTasks = filtered;
            this.refreshGanttChart();
            if (window.lucide) setTimeout(lucide.createIcons, 50);
        },

        getTasksByStatus(status) {
            return this.tasks.filter(t => t.status === status);
        },

        initGantt() {
            const container = document.getElementById('gantt-chart-container');
            const svg = document.getElementById('gantt-svg');
            if (!container || !svg) return;

            const tasksForFrappe = this.formatTasksForFrappe(this.filteredTasks);
            if (tasksForFrappe.length === 0) return;

            try {
                this.ganttInstance = new Gantt('#gantt-svg', tasksForFrappe, {
                    header_height: 38,
                    column_width: this.getColumnWidth(this.viewMode),
                    step: 24,
                    view_modes: ['Day', 'Week', 'Month', 'Year'],
                    bar_height: 24,
                    bar_corner_radius: 5,
                    arrow_curve: 5,
                    padding: 20,
                    view_mode: this.viewMode,
                    date_format: 'YYYY-MM-DD',
                    custom_popup_html: (task) => this.generateCustomPopup(task),
                    on_date_change: (task, start, end) => this.handleGanttDateChange(task, start, end),
                    on_progress_change: (task, progress) => this.handleGanttProgressChange(task, progress),
                    on_view_change: (mode) => { this.viewMode = mode; },
                    on_click: (task) => {
                        const target = this.tasks.find(t => String(t.id) === String(task.id));
                        if (target) this.openEditModal(target);
                    }
                });
            } catch (e) {
                console.warn("Gantt initialization note:", e);
            }
        },

        getColumnWidth(mode) {
            switch (mode) {
                case 'Day': return 38;
                case 'Week': return 48;
                case 'Month': return 80;
                case 'Year': return 120;
                default: return 48;
            }
        },

        formatTasksForFrappe(taskList) {
            return taskList.map(t => {
                const s = t.start_date ? t.start_date.substring(0, 10) : new Date().toISOString().substring(0, 10);
                const e = t.end_date ? t.end_date.substring(0, 10) : s;
                const deps = t.predecessors_list ? t.predecessors_list.map(p => String(p.predecessor_id)).join(', ') : '';

                let customClass = [];
                if (t.is_milestone) customClass.push('bar-milestone');
                if (t.is_parent) customClass.push('bar-parent');

                if (this.showCriticalPath && t.is_critical) {
                    customClass.push('bar-critical-path-highlight');
                } else {
                    if (t.status === 'COMPLETE') customClass.push('bar-completed');
                    else if (t.status === 'DELAYED') customClass.push('bar-delayed');
                    else if (t.priority === 'CRITICAL') customClass.push('bar-critical');
                    else if (t.priority === 'HIGH') customClass.push('bar-high');
                    else customClass.push('bar-medium');
                }

                return {
                    id: String(t.id),
                    name: `[${t.wbs_code}] ${t.name}`,
                    start: s,
                    end: e,
                    progress: t.progress || 0,
                    dependencies: deps,
                    custom_class: customClass.join(' '),
                    _task: t
                };
            });
        },

        refreshGanttChart() {
            if (!this.ganttInstance) {
                this.initGantt();
                return;
            }
            const tasksForFrappe = this.formatTasksForFrappe(this.filteredTasks);
            if (tasksForFrappe.length > 0) {
                try {
                    this.ganttInstance.refresh(tasksForFrappe);
                } catch (e) {
                    this.initGantt();
                }
            }
        },

        changeViewMode(mode) {
            this.viewMode = mode;
            if (this.ganttInstance) {
                this.ganttInstance.change_view_mode(mode);
            }
        },

        toggleCriticalPath() {
            this.showCriticalPath = !this.showCriticalPath;
            this.refreshGanttChart();
        },

        async saveBaseline() {
            if (!confirm("Save a snapshot of all current task dates as baseline?")) return;
            try {
                const res = await fetch(`/api/projects/${this.projectId}/save-baseline/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCookie('csrftoken') }
                });
                if (!res.ok) throw new Error("Failed to save baseline");
                alert("Project baseline snapshot saved successfully!");
                await this.loadData();
            } catch (e) {
                alert("Error saving baseline: " + e.message);
            }
        },

        generateCustomPopup(task) {
            const raw = task._task || this.tasks.find(t => String(t.id) === String(task.id));
            if (!raw) return '';

            const assignee = raw.assignee_detail ? (raw.assignee_detail.full_name || raw.assignee_detail.username) : 'Unassigned';
            const cpmBadge = raw.is_critical ? '<span style="color:#fb7185; font-weight:bold;">[CRITICAL PATH]</span>' : `Float: ${raw.total_float_days || 0}d`;
            const variance = raw.schedule_variance_days ? `<div style="color:#f59e0b;"><strong>Variance vs Baseline:</strong> ${raw.schedule_variance_days > 0 ? '+' : ''}${raw.schedule_variance_days}d</div>` : '';

            const startStr = this.formatDateIndian(raw.start_date);
            const endStr = this.formatDateIndian(raw.end_date);
            const estCost = this.formatCurrencyINR(raw.estimated_cost);
            const actCost = this.formatCurrencyINR(raw.actual_cost);

            return `
                <div class="popup-wrapper">
                    <div class="title">${raw.name} ${cpmBadge}</div>
                    <div class="subtitle space-y-1">
                        <div><strong>WBS:</strong> ${raw.wbs_code}</div>
                        <div><strong>Dates:</strong> ${startStr} &rarr; ${endStr} (${raw.duration_days} Days)</div>
                        ${variance}
                        <div><strong>Progress:</strong> ${task.progress}% | Status: ${raw.status.replace('_', ' ')}</div>
                        <div><strong>Assignee:</strong> ${assignee}</div>
                        <div><strong>Cost (INR):</strong> Est: ${estCost} | Act: ${actCost}</div>
                        <div><strong>Effort:</strong> Est: ${raw.estimated_hours}h | Act: ${raw.actual_hours}h (Man-Hours)</div>
                    </div>
                </div>
            `;
        },

        async handleGanttDateChange(task, start, end) {
            const startDateStr = start.toISOString().substring(0, 10);
            const endDateStr = end.toISOString().substring(0, 10);
            const taskId = task.id;

            try {
                const res = await fetch(`/api/tasks/${taskId}/reschedule/`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        start_date: startDateStr,
                        end_date: endDateStr
                    })
                });

                if (!res.ok) throw new Error("Failed to reschedule task");
                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                console.error("Reschedule error:", err);
                await this.loadData();
            }
        },

        async handleGanttProgressChange(task, progress) {
            const taskId = task.id;
            try {
                const res = await fetch(`/api/tasks/${taskId}/reschedule/`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({ progress: progress })
                });

                if (!res.ok) throw new Error("Failed to update progress");
                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                console.error("Progress update error:", err);
            }
        },

        // Kanban Drag & Drop
        handleKanbanDragStart(e, task) {
            e.dataTransfer.setData('text/plain', String(task.id));
        },

        async handleKanbanDrop(e, targetStatus) {
            const taskId = e.dataTransfer.getData('text/plain');
            if (!taskId) return;

            try {
                const res = await fetch(`/api/tasks/${taskId}/update-status/`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({ status: targetStatus })
                });
                if (!res.ok) throw new Error("Failed to update status");
                await this.loadData();
            } catch (err) {
                console.error("Kanban update error:", err);
            }
        },

        syncScroll(event, source) {
            if (this.isScrollingSync) return;
            this.isScrollingSync = true;

            const grid = document.getElementById('grid-scroll-body');
            const gantt = document.getElementById('gantt-chart-container');

            if (source === 'grid' && gantt && grid) {
                gantt.scrollTop = grid.scrollTop;
            } else if (source === 'gantt' && grid && gantt) {
                grid.scrollTop = gantt.scrollTop;
            }

            setTimeout(() => { this.isScrollingSync = false; }, 30);
        },

        startResize(e) {
            const container = document.getElementById('dual-pane-container');
            const leftPane = document.getElementById('left-pane');
            if (!container || !leftPane) return;

            const startX = e.clientX;
            const startWidth = leftPane.getBoundingClientRect().width;
            const containerWidth = container.getBoundingClientRect().width;

            const onMouseMove = (moveEvent) => {
                const deltaX = moveEvent.clientX - startX;
                const newWidth = Math.max(250, Math.min(containerWidth - 250, startWidth + deltaX));
                const percentage = (newWidth / containerWidth) * 100;
                leftPane.style.width = `${percentage}%`;
            };

            const onMouseUp = () => {
                window.removeEventListener('mousemove', onMouseMove);
                window.removeEventListener('mouseup', onMouseUp);
            };

            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        },

        selectTask(taskId) {
            this.selectedTaskId = taskId;
        },

        openEditModal(task) {
            this.isCreating = false;
            this.modalTab = 'general';
            this.editForm = {
                id: task.id,
                name: task.name,
                description: task.description || '',
                parent_task: task.parent_task || null,
                assignee: task.assignee || null,
                start_date: task.start_date ? task.start_date.substring(0, 10) : '',
                end_date: task.end_date ? task.end_date.substring(0, 10) : '',
                duration_days: task.duration_days || 1,
                progress: task.progress || 0,
                status: task.status,
                priority: task.priority,
                is_milestone: task.is_milestone || false,
                is_critical: task.is_critical || false,
                total_float_days: task.total_float_days || 0,
                estimated_cost: task.estimated_cost || 0,
                actual_cost: task.actual_cost || 0,
                estimated_hours: task.estimated_hours || 0,
                actual_hours: task.actual_hours || 0,
                wbs_code: task.wbs_code,
                predecessors_list: task.predecessors_list ? [...task.predecessors_list] : []
            };
            this.newDep = { from_task: '', dependency_type: 'FS', lag_days: 0 };
            this.taskComments = [];
            this.showEditModal = true;
            if (window.lucide) setTimeout(lucide.createIcons, 50);
        },

        openNewTaskModal(isMilestone = false, insertAfterTaskId = null) {
            this.isCreating = true;
            this.modalTab = 'general';
            const todayStr = new Date().toISOString().substring(0, 10);
            this.editForm = {
                id: null,
                name: isMilestone ? 'New Key Milestone' : 'New Task',
                description: '',
                parent_task: null,
                insert_after_task_id: insertAfterTaskId,
                assignee: null,
                start_date: todayStr,
                end_date: todayStr,
                duration_days: 1,
                progress: 0,
                status: 'NOT_STARTED',
                priority: isMilestone ? 'CRITICAL' : 'MEDIUM',
                is_milestone: isMilestone,
                is_critical: false,
                total_float_days: 0,
                estimated_cost: 0,
                actual_cost: 0,
                estimated_hours: 0,
                actual_hours: 0,
                wbs_code: '',
                predecessors_list: []
            };
            this.showEditModal = true;
            if (window.lucide) setTimeout(lucide.createIcons, 50);
        },

        openSubtaskModal(parentTask) {
            this.openNewTaskModal(false, null);
            this.editForm.parent_task = parentTask.id;
            this.editForm.name = `Subtask of ${parentTask.name}`;
            this.editForm.start_date = parentTask.start_date ? parentTask.start_date.substring(0, 10) : this.editForm.start_date;
            this.editForm.end_date = parentTask.end_date ? parentTask.end_date.substring(0, 10) : this.editForm.end_date;
        },

        insertTaskBelow(refTask) {
            this.openNewTaskModal(false, refTask.id);
            this.editForm.parent_task = refTask.parent_task;
            this.editForm.name = `Task after ${refTask.name}`;
            this.editForm.start_date = refTask.end_date ? refTask.end_date.substring(0, 10) : this.editForm.start_date;
            this.editForm.end_date = refTask.end_date ? refTask.end_date.substring(0, 10) : this.editForm.end_date;
        },

        async moveTaskUp(task) {
            try {
                const res = await fetch(`/api/tasks/${task.id}/move-up/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCookie('csrftoken') }
                });
                const data = await res.json();
                if (res.ok) {
                    await this.loadData();
                    this.refreshGanttChart();
                    if (data.status === 'success') this.showToast(data.message, 'success');
                }
            } catch (err) {
                console.error("Move task up error:", err);
            }
        },

        async moveTaskDown(task) {
            try {
                const res = await fetch(`/api/tasks/${task.id}/move-down/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCookie('csrftoken') }
                });
                const data = await res.json();
                if (res.ok) {
                    await this.loadData();
                    this.refreshGanttChart();
                    if (data.status === 'success') this.showToast(data.message, 'success');
                }
            } catch (err) {
                console.error("Move task down error:", err);
            }
        },

        onDateChange() {
            if (this.editForm.start_date && this.editForm.end_date) {
                const s = new Date(this.editForm.start_date);
                const e = new Date(this.editForm.end_date);
                const diffTime = e - s;
                const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
                this.editForm.duration_days = Math.max(1, diffDays);
            }
        },

        async saveTask() {
            if (!this.editForm.name) {
                alert("Task name is required");
                return;
            }

            const payload = {
                project: this.projectId,
                name: this.editForm.name,
                description: this.editForm.description,
                parent_task: this.editForm.parent_task ? parseInt(this.editForm.parent_task) : null,
                insert_after_task_id: this.editForm.insert_after_task_id ? parseInt(this.editForm.insert_after_task_id) : null,
                assignee: this.editForm.assignee ? parseInt(this.editForm.assignee) : null,
                start_date: this.editForm.start_date,
                end_date: this.editForm.end_date,
                duration_days: this.editForm.duration_days,
                progress: parseInt(this.editForm.progress),
                status: this.editForm.status,
                priority: this.editForm.priority,
                is_milestone: this.editForm.is_milestone,
                estimated_cost: parseFloat(this.editForm.estimated_cost || 0),
                actual_cost: parseFloat(this.editForm.actual_cost || 0),
                estimated_hours: parseInt(this.editForm.estimated_hours || 0),
                actual_hours: parseInt(this.editForm.actual_hours || 0)
            };

            try {
                let url = '/api/tasks/';
                let method = 'POST';
                if (!this.isCreating && this.editForm.id) {
                    url = `/api/tasks/${this.editForm.id}/`;
                    method = 'PUT';
                }

                const res = await fetch(url, {
                    method: method,
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(JSON.stringify(errData));
                }

                this.showEditModal = false;
                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                alert("Error saving task: " + err.message);
            }
        },

        async deleteTask(taskId) {
            if (!confirm("Are you sure you want to delete this task and its subtasks?")) return;

            try {
                const res = await fetch(`/api/tasks/${taskId}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': getCookie('csrftoken') }
                });

                if (!res.ok) throw new Error("Failed to delete task");
                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                alert("Delete failed: " + err.message);
            }
        },

        async addDependency() {
            if (!this.newDep.from_task) {
                alert("Please select a predecessor task.");
                return;
            }

            const payload = {
                from_task: parseInt(this.newDep.from_task),
                to_task: this.editForm.id,
                dependency_type: this.newDep.dependency_type,
                lag_days: parseInt(this.newDep.lag_days || 0)
            };

            try {
                const res = await fetch('/api/dependencies/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    const errorJson = await res.json();
                    const errMsg = errorJson.non_field_errors ? errorJson.non_field_errors.join(' ') : JSON.stringify(errorJson);
                    alert("Cannot add dependency: " + errMsg);
                    return;
                }

                const newDepData = await res.json();
                this.editForm.predecessors_list.push({
                    id: newDepData.id,
                    predecessor_id: newDepData.from_task,
                    predecessor_name: newDepData.from_task_name,
                    dependency_type: newDepData.dependency_type,
                    lag_days: newDepData.lag_days
                });
                this.newDep = { from_task: '', dependency_type: 'FS', lag_days: 0 };

                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                alert("Error linking dependency: " + err.message);
            }
        },

        async deleteDependency(depId) {
            try {
                const res = await fetch(`/api/dependencies/${depId}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': getCookie('csrftoken') }
                });

                if (!res.ok) throw new Error("Failed to delete dependency");
                this.editForm.predecessors_list = this.editForm.predecessors_list.filter(d => d.id !== depId);

                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                alert("Error deleting dependency: " + err.message);
            }
        },

        async loadComments() {
            if (!this.editForm.id) return;
            try {
                const res = await fetch(`/api/tasks/${this.editForm.id}/comments/`);
                if (res.ok) {
                    this.taskComments = await res.json();
                }
            } catch (e) {
                console.error("Comments error:", e);
            }
        },

        async postComment() {
            if (!this.newCommentText.trim() || !this.editForm.id) return;
            try {
                const res = await fetch(`/api/tasks/${this.editForm.id}/comments/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({ text: this.newCommentText })
                });
                if (res.ok) {
                    const newC = await res.json();
                    this.taskComments.unshift(newC);
                    this.newCommentText = '';
                }
            } catch (e) {
                alert("Failed to post comment");
            }
        },

        async loadActivityLogs() {
            try {
                const res = await fetch(`/api/projects/${this.projectId}/activity-logs/`);
                if (res.ok) {
                    this.activityLogs = await res.json();
                }
            } catch (e) {
                console.error("Activity logs error:", e);
            }
        },

        async handleExcelImport(e) {
            const fileInput = document.getElementById('excel-file-input');
            if (!fileInput.files.length) return;

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);

            try {
                const res = await fetch(`/api/projects/${this.projectId}/import-excel/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCookie('csrftoken') },
                    body: formData
                });
                if (!res.ok) throw new Error("Excel import failed");
                const resData = await res.json();
                alert(`Successfully imported ${resData.imported_count} tasks!`);
                this.showImportModal = false;
                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                alert("Import failed: " + err.message);
            }
        },

        async recalculateCascades() {
            this.isRecalculating = true;
            try {
                const res = await fetch(`/api/projects/${this.projectId}/recalculate/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCookie('csrftoken') }
                });
                if (!res.ok) throw new Error("Failed to recalculate schedules");
                await this.loadData();
                this.refreshGanttChart();
            } catch (err) {
                console.error("Recalculate error:", err);
            } finally {
                this.isRecalculating = false;
            }
        },

        formatCurrencyINR(amount) {
            if (amount === undefined || amount === null || isNaN(amount)) return '₹0.00';
            const num = Number(amount);
            return new Intl.NumberFormat('en-IN', {
                style: 'currency',
                currency: 'INR',
                maximumFractionDigits: 2
            }).format(num);
        },

        formatDateIndian(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return dateStr;
            const day = String(d.getDate()).padStart(2, '0');
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const year = d.getFullYear();
            return `${day}/${month}/${year}`;
        },

        formatDateShort(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return dateStr;
            const day = String(d.getDate()).padStart(2, '0');
            const month = d.toLocaleDateString('en-IN', { month: 'short' });
            return `${day} ${month}`;
        },

        formatDateFull(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return dateStr;
            const day = String(d.getDate()).padStart(2, '0');
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const year = d.getFullYear();
            const time = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
            return `${day}/${month}/${year}, ${time} IST`;
        },

        exportGanttImage() {
            const svg = document.getElementById('gantt-svg');
            if (!svg) {
                this.showToast('Gantt chart element not found', 'error');
                return;
            }
            try {
                const clone = svg.cloneNode(true);
                clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
                
                const rect = svg.getBoundingClientRect();
                let bbox = { width: 1200, height: 600 };
                try { bbox = svg.getBBox(); } catch(e) {}
                const width = Math.max(svg.scrollWidth || 1200, bbox.width + 60);
                const height = Math.max(svg.scrollHeight || 600, bbox.height + 60);
                clone.setAttribute('width', width);
                clone.setAttribute('height', height);

                const svgString = new XMLSerializer().serializeToString(clone);
                const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
                const blobURL = URL.createObjectURL(svgBlob);

                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    canvas.width = width * 2;
                    canvas.height = height * 2;
                    const ctx = canvas.getContext('2d');
                    ctx.scale(2, 2);

                    // Background fill
                    ctx.fillStyle = '#0f172a';
                    ctx.fillRect(0, 0, width, height);
                    ctx.drawImage(img, 10, 10);

                    const pngData = canvas.toDataURL('image/png');
                    const a = document.createElement('a');
                    a.href = pngData;
                    a.download = `${(this.projectMeta.name || 'Milestone_Project').replace(/[^a-zA-Z0-9_-]/g, '_')}_Gantt_Chart.png`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(blobURL);
                    this.showToast('Gantt chart image exported successfully (PNG)!', 'success');
                };
                img.onerror = () => {
                    const a = document.createElement('a');
                    a.href = blobURL;
                    a.download = `${(this.projectMeta.name || 'Milestone_Project').replace(/[^a-zA-Z0-9_-]/g, '_')}_Gantt_Chart.svg`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    this.showToast('Gantt chart exported as SVG vector image!', 'success');
                };
                img.src = blobURL;
            } catch (err) {
                console.error('Export Gantt Image Error:', err);
                this.showToast('Could not export Gantt chart image: ' + err.message, 'error');
            }
        }
    };
};

